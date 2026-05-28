"""Bug 2 condition exploration test — webhook secret cannot be stored.

Spec: ``.kiro/specs/email-delivery-visibility-fixes`` — Phase 0 task 3.

Bug 2 of the bugfix is that Brevo / SendGrid webhook signing secrets
cannot currently be stored from the admin GUI: the
``EmailProviderCredentialsRequest`` schema has no ``webhook_secret``
field, ``save_email_credentials`` does not accept a ``webhook_secret``
kwarg, and there is no redaction logic on read. As a result, every
incoming Brevo / SendGrid webhook is rejected with HTTP 403 and the
``Brevo bounce webhook: no signing secret configured`` warning.

This file pins the post-fix contract via three sub-tests.

**On UNFIXED code (running this file before the schema/service/router
fixes ship):**

  - Sub-test A (PUT persists ``webhook_secret`` to ``config``) — FAILS.
    The request schema silently drops the field; the service never
    writes ``config[<provider_key>_webhook_secret]``.
  - Sub-test B (GET redacts the secret with ``"***"``) — FAILS. There
    is no redaction logic today; were the secret stored, it would leak
    in the response.
  - Sub-test C (signed webhook accepted when ``config`` secret present)
    — PASSES. The handler already reads from ``config[<provider>
    _webhook_secret]``; this lock-in test must keep passing post-fix.

**On FIXED code:** all three sub-tests PASS.

The first two failures are the success case for an exploration test —
they confirm the bug exists. The third case is a contract lock-in.

Validates: Requirements 2.1, 2.2, 2.3
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Import models so SQLAlchemy can resolve relationships at import time —
# the email_providers router transitively imports models from many
# other modules.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.core.database import get_db_session
from app.core.webhook_security import sign_webhook_payload
from app.modules.email_providers.router import router as email_providers_router


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_provider_row(
    *,
    provider_key: str = "brevo",
    config: dict | None = None,
    is_active: bool = True,
) -> SimpleNamespace:
    """Stand up an EmailProvider-shaped object usable by the service code.

    The real ORM class lives in ``app.modules.admin.models`` but we use
    a SimpleNamespace here so the mock DB can hand it back from
    ``execute(...).scalar_one_or_none()`` without setting up SQLAlchemy
    sessions or the DB.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        provider_key=provider_key,
        display_name=provider_key.title(),
        description=None,
        smtp_host=None,
        smtp_port=None,
        smtp_encryption="tls",
        priority=1,
        is_active=is_active,
        credentials_encrypted=b"existing-blob",
        credentials_set=True,
        config=dict(config or {}),
        setup_guide=None,
        created_at=now,
        updated_at=now,
    )


def _scalar_one_result(value):
    """Build an execute() result whose ``.scalar_one_or_none()`` returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


def _scalars_all_result(rows):
    """Build an execute() result whose ``.scalars().all()`` returns ``rows``."""
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=list(rows))
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


def _make_admin_app() -> FastAPI:
    """Mount only the email-providers router and inject a global_admin
    auth context via middleware so ``require_role("global_admin")``
    passes without going through the real auth pipeline.
    """
    app = FastAPI()

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = None
        request.state.role = "global_admin"
        request.state.email = "admin@example.com"
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    app.include_router(
        email_providers_router, prefix="/api/v2/admin/email-providers"
    )
    return app


# ---------------------------------------------------------------------------
# Sub-test A — webhook_secret persistence on PUT credentials
# ---------------------------------------------------------------------------


class TestPutCredentialsPersistsWebhookSecret:
    """PUT credentials with ``webhook_secret`` must persist it under
    ``config['<provider_key>_webhook_secret']``.

    UNFIXED OUTCOME: FAIL — the schema drops the field and the service
    never writes the config key. This failure proves the bug exists.

    Validates: Requirement 2.1 (admin GUI cannot store the secret)
    """

    def _build_app_with_capturing_db(self, provider) -> tuple[FastAPI, dict]:
        """Override ``get_db_session`` to hand back a mock DB whose
        single-row lookup returns ``provider`` and capture writes via a
        side-channel dict so the test can read what the service set.
        """
        captured: dict = {"flush_count": 0}

        def _override_db():
            db = AsyncMock()
            # Two execute calls expected: SELECT provider, then the
            # audit log write. Return the provider row first; subsequent
            # calls return an empty-but-shaped result.
            execute_results = [_scalar_one_result(provider)]
            empty = MagicMock()
            empty.rowcount = 0

            async def _execute(*_args, **_kwargs):
                if execute_results:
                    return execute_results.pop(0)
                return empty

            db.execute = AsyncMock(side_effect=_execute)

            async def _flush():
                captured["flush_count"] += 1
                # Snapshot the provider config at flush time so a later
                # read can't be confused by an in-place mutation.
                captured["config_after_flush"] = dict(provider.config or {})

            db.flush = AsyncMock(side_effect=_flush)
            db.refresh = AsyncMock()
            db.add = MagicMock()
            return db

        app = _make_admin_app()
        app.dependency_overrides[get_db_session] = _override_db
        return app, captured

    def test_brevo_put_persists_webhook_secret_to_config(self):
        provider = _make_provider_row(
            provider_key="brevo", config={"from_email": "x@y.com"}
        )
        app, captured = self._build_app_with_capturing_db(provider)
        client = TestClient(app)

        # Patch ``envelope_encrypt`` so the credentials blob doesn't
        # require the real master key, and ``write_audit_log`` so we
        # don't need an audit_log table or full DB.
        with patch(
            "app.modules.email_providers.service.envelope_encrypt",
            return_value=b"encrypted",
        ), patch(
            "app.modules.email_providers.service.write_audit_log",
            new=AsyncMock(),
        ):
            resp = client.put(
                "/api/v2/admin/email-providers/brevo/credentials",
                json={
                    "credentials": {"api_key": "x"},
                    "webhook_secret": "S",
                },
            )

        # The endpoint must accept the body. On unfixed code Pydantic
        # silently drops ``webhook_secret`` (no ``extra='forbid'``) so
        # the request still 200s — that's actually part of the bug:
        # the field is accepted by the wire but never persisted.
        assert resp.status_code == 200, resp.text

        # The actual contract: ``config['brevo_webhook_secret']`` must
        # equal ``"S"`` after the call.
        assert captured.get("flush_count", 0) >= 1, (
            "service must call db.flush() at least once to persist"
        )
        config_after = captured.get("config_after_flush") or {}
        assert config_after.get("brevo_webhook_secret") == "S", (
            "PUT credentials must persist webhook_secret to "
            f"config['brevo_webhook_secret'] = 'S'. "
            f"Actual config after flush: {config_after!r}"
        )
        # And the existing ``from_email`` key must survive.
        assert config_after.get("from_email") == "x@y.com"

    def test_sendgrid_put_persists_webhook_secret_to_config(self):
        provider = _make_provider_row(
            provider_key="sendgrid", config={"from_email": "x@y.com"}
        )
        app, captured = self._build_app_with_capturing_db(provider)
        client = TestClient(app)

        with patch(
            "app.modules.email_providers.service.envelope_encrypt",
            return_value=b"encrypted",
        ), patch(
            "app.modules.email_providers.service.write_audit_log",
            new=AsyncMock(),
        ):
            resp = client.put(
                "/api/v2/admin/email-providers/sendgrid/credentials",
                json={
                    "credentials": {"api_key": "x"},
                    "webhook_secret": "S",
                },
            )

        assert resp.status_code == 200, resp.text
        config_after = captured.get("config_after_flush") or {}
        assert config_after.get("sendgrid_webhook_secret") == "S", (
            "PUT credentials must persist webhook_secret to "
            f"config['sendgrid_webhook_secret'] = 'S'. "
            f"Actual config after flush: {config_after!r}"
        )
        assert config_after.get("from_email") == "x@y.com"


# ---------------------------------------------------------------------------
# Sub-test B — webhook_secret redaction on GET providers
# ---------------------------------------------------------------------------


class TestGetProvidersRedactsWebhookSecret:
    """GET ``/api/v2/admin/email-providers`` must replace any
    ``*_webhook_secret`` key in ``config`` with the literal ``"***"``
    before returning it; other config keys (``from_email``, ``from_name``,
    ``reply_to``, etc.) must pass through unchanged.

    UNFIXED OUTCOME: FAIL — no redaction logic exists today, so the
    raw secret would leak in the response. This failure locks in the
    post-fix security contract.

    Validates: Requirement 2.2 (secret never returned to frontend)
    """

    def _build_app_with_provider_list(
        self, providers
    ) -> FastAPI:
        def _override_db():
            db = AsyncMock()
            # ``list_email_providers`` calls execute() once and reads
            # ``.scalars().all()`` for every provider.
            db.execute = AsyncMock(return_value=_scalars_all_result(providers))
            db.flush = AsyncMock()
            db.refresh = AsyncMock()
            return db

        app = _make_admin_app()
        app.dependency_overrides[get_db_session] = _override_db
        return app

    def test_brevo_webhook_secret_redacted_to_triple_star(self):
        provider = _make_provider_row(
            provider_key="brevo",
            config={
                "brevo_webhook_secret": "S",
                "from_email": "x@y.com",
                "from_name": "Test Org",
            },
        )
        app = self._build_app_with_provider_list([provider])
        client = TestClient(app)

        resp = client.get("/api/v2/admin/email-providers")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "providers" in body
        brevo = next(
            (p for p in body["providers"] if p["provider_key"] == "brevo"),
            None,
        )
        assert brevo is not None, body
        config = brevo.get("config") or {}

        # The post-fix contract: the secret is redacted with the
        # sentinel string "***", not the raw value.
        assert config.get("brevo_webhook_secret") == "***", (
            "GET providers must redact config['brevo_webhook_secret'] "
            f"to '***'. Actual: {config.get('brevo_webhook_secret')!r}. "
            f"Full config: {config!r}"
        )
        # Pre-existing non-secret keys still pass through unchanged.
        assert config.get("from_email") == "x@y.com"
        assert config.get("from_name") == "Test Org"

    def test_sendgrid_webhook_secret_redacted_to_triple_star(self):
        provider = _make_provider_row(
            provider_key="sendgrid",
            config={
                "sendgrid_webhook_secret": "S",
                "from_email": "x@y.com",
            },
        )
        app = self._build_app_with_provider_list([provider])
        client = TestClient(app)

        resp = client.get("/api/v2/admin/email-providers")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        sg = next(
            (p for p in body["providers"] if p["provider_key"] == "sendgrid"),
            None,
        )
        assert sg is not None, body
        config = sg.get("config") or {}

        assert config.get("sendgrid_webhook_secret") == "***", (
            "GET providers must redact "
            "config['sendgrid_webhook_secret'] to '***'. "
            f"Actual: {config.get('sendgrid_webhook_secret')!r}. "
            f"Full config: {config!r}"
        )
        assert config.get("from_email") == "x@y.com"


# ---------------------------------------------------------------------------
# Sub-test C — webhook handler accepts when config secret is set (lock-in)
# ---------------------------------------------------------------------------


class TestWebhookHandlerAcceptsConfigStoredSecret:
    """With ``email_providers.config['brevo_webhook_secret']`` pre-seeded
    (simulating a direct SQL insert that bypasses the broken admin
    GUI), the Brevo bounce webhook handler must verify the HMAC-SHA256
    signature against that secret and return HTTP 200.

    UNFIXED OUTCOME: PASSES. The handler already reads from this
    config key per ``_candidate_provider_secrets``; this lock-in
    sub-test continues to pass post-fix and pins the contract that the
    fix must not break it.

    Validates: Requirement 2.3 (signed webhook is accepted once the
    secret is stored)
    """

    @pytest.mark.asyncio
    async def test_signed_brevo_webhook_returns_200_when_config_secret_set(self):
        from app.modules.notifications.router import brevo_bounce_webhook

        # The active Brevo provider row carries the webhook secret.
        provider = _make_provider_row(
            provider_key="brevo",
            config={"brevo_webhook_secret": "S"},
            is_active=True,
        )

        body = json.dumps(
            {"event": "hard_bounce", "email": "bad@example.com"}
        ).encode()
        sig = sign_webhook_payload(body, "S")

        # Mock DB: provider lookup returns the seeded row.
        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(
            return_value=_scalars_all_result([provider])
        )

        # Mock request with the signed body + Brevo signature header.
        req = AsyncMock()
        req.body = AsyncMock(return_value=body)
        req.json = AsyncMock(return_value=json.loads(body))
        req.headers = {"X-Brevo-Signature": sig}
        req.state = MagicMock()
        req.client = MagicMock()
        req.client.host = "127.0.0.1"

        # Patch ``flag_bounce`` so the handler doesn't attempt to write
        # to ``notification_log`` / ``bounced_addresses`` / customer
        # tables (we're locking in the signature acceptance, not the
        # downstream side-effects which other tests already cover).
        with patch(
            "app.modules.notifications.router.app_settings"
        ) as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            # Disable the env-var fallback so the only candidate is
            # the config-stored secret — this is exactly what we want
            # to lock in.
            ms.brevo_webhook_secret = ""
            resp = await brevo_bounce_webhook(request=req, db=db)

        assert resp.status_code == 200, (
            f"Webhook with valid signature against config-stored "
            f"secret must return 200, got {resp.status_code}. "
            f"Body: {resp.body!r}"
        )
        body_json = json.loads(resp.body)
        assert body_json["emails_processed"] == 1
        flag_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# Bug 2 PRESERVATION property tests — env-var fallback + non-webhook provider
# ---------------------------------------------------------------------------


class TestPreservation:
    """Bug 2 preservation tests — these MUST PASS on UNFIXED code.

    Property 2 of Bug 2 (per ``bugfix.md`` Reqs 4.7 and 4.10): the
    fix that adds GUI storage for ``brevo_webhook_secret`` /
    ``sendgrid_webhook_secret`` must NOT regress two existing
    behaviours:

      * **Env-var fallback (Req 4.7).** When
        ``email_providers.config`` carries no ``<provider>_webhook_secret``
        AND ``app_settings.<provider>_webhook_secret`` is set, the
        bounce webhook handler must continue to verify signatures
        against the env-var secret. This is the legacy one-release
        deprecation path that pre-dated the per-provider config
        column; it's already exercised by ``test_bounce_webhooks.py``
        but is pinned here too so the Bug 2 fix can't accidentally
        delete the fallback when it adds the GUI surface.

      * **Non-webhook provider untouched (Req 4.10).** ``custom_smtp``
        (and any future non-Brevo non-SendGrid provider) has no
        webhook concept. When an admin sends a PUT credentials
        request that happens to include a ``webhook_secret`` field
        for ``custom_smtp``, the server must silently drop it —
        nothing gets persisted under any ``*_webhook_secret`` key
        and nothing leaks back in the response. Today the schema
        drops the field for ALL providers (which is the bug for
        Brevo/SendGrid but is exactly the right behaviour for
        custom_smtp); post-fix, the schema accepts it for all
        providers but ``save_email_credentials`` only persists when
        ``provider_key in {"brevo", "sendgrid"}``. Either way, this
        test pins the contract that custom_smtp never grows a
        ``*_webhook_secret`` key.

    Validates: Requirements 4.7, 4.10
    """

    # ------------------------------------------------------------------
    # Sub-test: env-var fallback for Brevo
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_brevo_env_var_fallback_accepts_signed_webhook(self):
        """With ``email_providers.config`` empty (no brevo row carrying
        a webhook secret) AND ``app_settings.brevo_webhook_secret =
        "envS"``, a webhook signed with HMAC-SHA256(body, "envS")
        must verify and return HTTP 200.

        UNFIXED OUTCOME: PASS — the legacy env-var fallback is
        already implemented in ``_candidate_provider_secrets``. This
        test locks the contract so the Bug 2 fix can't regress it.

        Validates: Requirement 4.7
        """
        from app.modules.notifications.router import brevo_bounce_webhook

        env_secret = "envS"
        body = json.dumps(
            {"event": "hard_bounce", "email": "bounced@example.com"}
        ).encode()
        sig = sign_webhook_payload(body, env_secret)

        # ``email_providers.config`` is empty — no provider rows carry
        # a ``brevo_webhook_secret``. The candidate-secret lookup
        # therefore returns the env-var fallback as its only entry.
        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_all_result([]))

        req = AsyncMock()
        req.body = AsyncMock(return_value=body)
        req.json = AsyncMock(return_value=json.loads(body))
        req.headers = {"X-Brevo-Signature": sig}
        req.state = MagicMock()
        req.client = MagicMock()
        req.client.host = "127.0.0.1"

        with patch(
            "app.modules.notifications.router.app_settings"
        ) as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            ms.brevo_webhook_secret = env_secret
            resp = await brevo_bounce_webhook(request=req, db=db)

        assert resp.status_code == 200, (
            "Env-var fallback (app_settings.brevo_webhook_secret) "
            "must continue to verify signed webhooks when "
            "email_providers.config has no brevo_webhook_secret. "
            f"Got {resp.status_code}: {resp.body!r}"
        )
        body_json = json.loads(resp.body)
        assert body_json["emails_processed"] == 1
        flag_mock.assert_awaited_once()

    # ------------------------------------------------------------------
    # Sub-test: env-var fallback for SendGrid
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_sendgrid_env_var_fallback_accepts_signed_webhook(self):
        """SendGrid mirror of the Brevo env-var fallback test.

        With ``email_providers.config`` empty for SendGrid AND
        ``app_settings.sendgrid_webhook_secret = "envS"``, a webhook
        signed with HMAC-SHA256(body, "envS") and presented under the
        ``X-Twilio-Email-Event-Webhook-Signature`` header must verify
        and return 200.

        UNFIXED OUTCOME: PASS.

        Validates: Requirement 4.7
        """
        from app.modules.notifications.router import sendgrid_bounce_webhook

        env_secret = "envS"
        # SendGrid sends an array of event objects.
        body = json.dumps(
            [{"event": "bounce", "email": "bounced@example.com"}]
        ).encode()
        sig = sign_webhook_payload(body, env_secret)

        db = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(return_value=_scalars_all_result([]))

        req = AsyncMock()
        req.body = AsyncMock(return_value=body)
        req.json = AsyncMock(return_value=json.loads(body))
        req.headers = {"X-Twilio-Email-Event-Webhook-Signature": sig}
        req.state = MagicMock()
        req.client = MagicMock()
        req.client.host = "127.0.0.1"

        with patch(
            "app.modules.notifications.router.app_settings"
        ) as ms, patch(
            "app.modules.notifications.router.flag_bounce", new=AsyncMock()
        ) as flag_mock:
            ms.sendgrid_webhook_secret = env_secret
            resp = await sendgrid_bounce_webhook(request=req, db=db)

        assert resp.status_code == 200, (
            "Env-var fallback (app_settings.sendgrid_webhook_secret) "
            "must continue to verify signed webhooks when "
            "email_providers.config has no sendgrid_webhook_secret. "
            f"Got {resp.status_code}: {resp.body!r}"
        )
        body_json = json.loads(resp.body)
        assert body_json["emails_processed"] == 1
        flag_mock.assert_awaited_once()

    # ------------------------------------------------------------------
    # Sub-test: non-webhook provider (custom_smtp) silently ignores webhook_secret
    # ------------------------------------------------------------------

    def _build_app_with_capturing_db(self, provider) -> tuple[FastAPI, dict]:
        """Same helper shape as
        ``TestPutCredentialsPersistsWebhookSecret`` — wires a
        ``get_db_session`` override that hands back the seeded
        provider on the first execute() and snapshots the provider's
        config dict at flush time.
        """
        captured: dict = {"flush_count": 0}

        def _override_db():
            db = AsyncMock()
            execute_results = [_scalar_one_result(provider)]
            empty = MagicMock()
            empty.rowcount = 0

            async def _execute(*_args, **_kwargs):
                if execute_results:
                    return execute_results.pop(0)
                return empty

            db.execute = AsyncMock(side_effect=_execute)

            async def _flush():
                captured["flush_count"] += 1
                captured["config_after_flush"] = dict(provider.config or {})

            db.flush = AsyncMock(side_effect=_flush)
            db.refresh = AsyncMock()
            db.add = MagicMock()
            return db

        app = _make_admin_app()
        app.dependency_overrides[get_db_session] = _override_db
        return app, captured

    def test_custom_smtp_silently_ignores_webhook_secret(self):
        """PUT /api/v2/admin/email-providers/custom_smtp/credentials
        with ``webhook_secret`` in the body must:

          * Return 200 (the field is dropped, not rejected).
          * Persist NO ``*_webhook_secret`` key under
            ``email_providers.config`` (custom SMTP has no webhook
            concept).
          * Not surface the webhook secret value in the response
            payload.

        UNFIXED OUTCOME: PASS — today's schema drops ``webhook_secret``
        for ALL providers, so for ``custom_smtp`` this is already the
        correct behaviour. Post-fix this test must continue to pass:
        the fix only persists the field when ``provider_key in
        {"brevo", "sendgrid"}``; for ``custom_smtp`` the fix's service
        layer silently drops it (logged at DEBUG, no config write).

        Validates: Requirement 4.10
        """
        provider = _make_provider_row(
            provider_key="custom_smtp",
            config={"from_email": "x@y.com", "from_name": "Test Org"},
        )
        app, captured = self._build_app_with_capturing_db(provider)
        client = TestClient(app)

        with patch(
            "app.modules.email_providers.service.envelope_encrypt",
            return_value=b"encrypted",
        ), patch(
            "app.modules.email_providers.service.write_audit_log",
            new=AsyncMock(),
        ):
            resp = client.put(
                "/api/v2/admin/email-providers/custom_smtp/credentials",
                json={
                    "credentials": {
                        "smtp_login": "user",
                        "smtp_password": "pass",
                    },
                    "smtp_host": "smtp.example.com",
                    "smtp_port": 587,
                    "smtp_encryption": "tls",
                    "from_email": "x@y.com",
                    "webhook_secret": "S",
                },
            )

        assert resp.status_code == 200, resp.text

        # The field must be silently dropped: no ``*_webhook_secret``
        # key written under ``config`` for ``custom_smtp``.
        assert captured.get("flush_count", 0) >= 1, (
            "service must call db.flush() at least once"
        )
        config_after = captured.get("config_after_flush") or {}
        webhook_keys = [
            k for k in config_after.keys() if k.endswith("_webhook_secret")
        ]
        assert webhook_keys == [], (
            "custom_smtp must NOT grow any *_webhook_secret config "
            "key — webhook secrets only apply to brevo/sendgrid. "
            f"Found unexpected keys: {webhook_keys!r}. "
            f"Full config after flush: {config_after!r}"
        )
        # Pre-existing legitimate config keys still pass through.
        assert config_after.get("from_email") == "x@y.com"
        assert config_after.get("from_name") == "Test Org"

        # The response payload must not surface the webhook secret
        # value. Endpoint returns ``EmailProviderCredentialsResponse``
        # which has only ``{message, credentials_set}`` — neither
        # field can carry the secret — so this is a regression-pin
        # against future schema additions.
        body_json = resp.json()
        assert "webhook_secret" not in body_json
        assert "S" not in (body_json.get("message") or ""), (
            "response.message must not echo the webhook secret value"
        )
