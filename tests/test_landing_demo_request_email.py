"""Failover integration tests for ``submit_demo_request`` (A13).

This file pins the Phase 3 task 3.13 contract:
``submit_demo_request`` (``app/modules/landing/router.py``) was migrated
from a hand-rolled ``smtplib`` provider loop to a single
:func:`app.integrations.email_sender.send_email` call. The unified
sender owns failover, error classification, and per-attempt + total
time budgets.

Per the per-site variation table in
``.kiro/specs/email-provider-unification/design.md`` row A13, the demo
request is a **public form** with no organisation context:

1. Walk the active provider chain in priority order, skipping
   ``SOFT_AUTH`` failures and succeeding on the next provider.
2. Build the :class:`~app.integrations.email_sender.EmailMessage` with
   ``EmailMessage.org_id=None`` (no org context — bounce-blocklist
   pre-check falls through to platform-wide rows).
3. Do **not** pass ``org_sender_name``; the From header reads as the
   provider's configured name.
4. Do **not** call ``log_email_sent`` (the notification log is
   org-scoped).
5. Do **not** fire ``create_in_app_notification`` on failure (no org
   admin to notify; in-app notifications are org-scoped).
6. On total failure, return HTTP 500 to the public form caller
   (Requirement 6.7).
7. The honeypot path still short-circuits before any provider work.

Patches (kept self-contained — no imports from other test files):

- ``app.integrations.email_sender._load_active_providers`` returns the
  mocked provider rows in priority order.
- ``app.integrations.email_sender._check_bounce_blocklist`` returns
  ``(False, None)`` so the message reaches the dispatch loop.
- ``app.integrations.email_sender.envelope_decrypt_str`` returns canned
  credentials.
- ``httpx.AsyncClient`` is replaced with an in-process fake whose
  responses depend on the URL hit.

Validates: Requirements 6.1, 6.7
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.landing.schemas import (
    DemoRequestPayload,
    DemoRequestResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db() -> AsyncMock:
    """Mock async session — the unified sender opens no transactions."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _mock_redis() -> AsyncMock:
    """Mock async Redis client. INCR returns 1 (well under the limit)."""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    return redis


def _make_request(client_ip: str = "127.0.0.1") -> MagicMock:
    """Mock a FastAPI Request with the fields ``submit_demo_request`` reads."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = client_ip
    return request


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active EmailProvider row.

    The two REST dispatchers
    (``_dispatch_brevo_rest`` / ``_dispatch_sendgrid_rest``) only read
    ``credentials_set``, ``credentials_encrypted``, ``provider_key``,
    and ``config['from_email']``. The blob bytes are opaque because we
    patch ``envelope_decrypt_str`` to return canned credentials.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.priority = priority
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {
        "from_email": "noreply@example.com",
        "from_name": "OraInvoice",
    }
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


def _valid_payload(**overrides) -> DemoRequestPayload:
    """Build a valid demo request payload with sensible defaults."""
    base = {
        "full_name": "John Smith",
        "business_name": "Smith Auto",
        "email": "john@smithauto.co.nz",
        "phone": "+6421234567",
        "message": "Interested in a demo for our workshop.",
    }
    base.update(overrides)
    return DemoRequestPayload(**base)


# ---------------------------------------------------------------------------
# Fake httpx client
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response``."""

    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        headers: dict | None = None,
        json_body: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_body = json_body

    def json(self) -> dict:
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FailoverFakeClient:
    """In-process replacement for ``httpx.AsyncClient`` (failover scenario).

    Brevo (priority 1) returns 401 — drives ``SOFT_AUTH`` and the loop
    continues. SendGrid (priority 2) returns 202 with an
    ``X-Message-Id`` header — success.
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []
    posted_headers: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self) -> "_FailoverFakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        type(self).posted_headers.append(headers or {})
        if url == self.BREVO_URL:
            return _FakeResponse(
                401,
                text='{"code":"unauthorized","message":"invalid api key"}',
                headers={"content-type": "application/json"},
                json_body={"code": "unauthorized", "message": "invalid api key"},
            )
        if url == self.SENDGRID_URL:
            return _FakeResponse(
                202,
                text="",
                headers={"X-Message-Id": "msg-demo-request-1"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


class _AllFail401Client(_FailoverFakeClient):
    """Variant where every URL returns 401 — drives total auth failure."""

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        type(self).posted_headers.append(headers or {})
        return _FakeResponse(
            401,
            text='{"code":"unauthorized","message":"invalid api key"}',
            headers={"content-type": "application/json"},
            json_body={
                "code": "unauthorized",
                "message": "invalid api key",
            },
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA13DemoRequestFailover:
    """End-to-end failover for ``submit_demo_request`` (task 3.13).

    With Brevo at priority 1 and SendGrid at priority 2,
    ``submit_demo_request`` must walk past the Brevo 401 (``SOFT_AUTH``),
    succeed on SendGrid (202), and return ``DemoRequestResponse`` with
    ``success=True`` — proving the migration to the unified sender did
    not lose the failover guarantees the legacy hand-rolled loop already
    provided.

    Validates: Requirements 6.1, 6.7
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_returns_200(self) -> None:
        """Brevo 401 → SendGrid 202 → both URLs hit, response success.

        Pins the contract that the migrated ``submit_demo_request``:

        1. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). Failure on the first must NOT abort the
           chain.
        2. Returns a ``DemoRequestResponse`` with ``success=True`` and
           the standard 24-hour confirmation message — i.e. an HTTP 200
           response shape, not a JSONResponse 500.

        Validates: Requirements 6.1, 6.7
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()
        payload = _valid_payload()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)
        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        _FailoverFakeClient.posted_urls = []
        _FailoverFakeClient.posted_payloads = []
        _FailoverFakeClient.posted_headers = []

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _FailoverFakeClient,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        # 1. Returned the 200-shape success response (not a JSONResponse).
        assert isinstance(result, DemoRequestResponse)
        assert result.success is True
        assert "24 hours" in result.message

        # 2. Both REST endpoints were hit in priority order — Brevo
        #    first (401, SOFT_AUTH), then SendGrid (202, success).
        assert _FailoverFakeClient.posted_urls == [
            _FailoverFakeClient.BREVO_URL,
            _FailoverFakeClient.SENDGRID_URL,
        ]

        # 3. Provider chain was loaded once and the bounce-blocklist
        #    pre-check fired exactly once.
        load_providers_stub.assert_awaited_once()
        blocklist_stub.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_500(self) -> None:
        """When every provider returns ``SOFT_AUTH`` ``submit_demo_request``
        SHALL surface HTTP 500 to the caller.

        Per Requirement 6.7 the public demo form has no org context so
        there is no in-app notification to fire and no notification_log
        entry to write — the only failure surface is the HTTP response
        status.

        Validates: Requirement 6.7
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()
        payload = _valid_payload()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)
        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []
        _AllFail401Client.posted_headers = []

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _AllFail401Client,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        # 1. HTTP 500 JSONResponse — not a 200 DemoRequestResponse.
        assert not isinstance(result, DemoRequestResponse)
        assert result.status_code == 500
        body = json.loads(result.body)
        assert body["success"] is False

        # 2. Both providers were attempted (chain not short-circuited
        #    by a HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

    @pytest.mark.asyncio
    async def test_no_active_providers_returns_500(self) -> None:
        """Empty Active_Provider_Set returns HTTP 500 to the caller.

        ``send_email`` returns ``success=False`` with ``attempts=[]``
        when no providers are configured. The migrated
        ``submit_demo_request`` MUST translate that into HTTP 500
        rather than silently returning a 200 success.

        Validates: Requirement 6.7
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()
        payload = _valid_payload()

        load_providers_stub = AsyncMock(return_value=[])
        blocklist_stub = AsyncMock(return_value=(False, None))

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        assert not isinstance(result, DemoRequestResponse)
        assert result.status_code == 500
        body = json.loads(result.body)
        assert body["success"] is False


class TestA13DemoRequestEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A13 in
    ``design.md``: ``EmailMessage.org_id`` MUST be ``None`` (public
    form), no ``org_sender_name`` is passed, no attachments, recipient
    is the platform demo-request inbox.

    Validates: Requirement 6.1, 6.7
    """

    @pytest.mark.asyncio
    async def test_email_message_has_no_org_context(self) -> None:
        """The migration plumbs ``org_id=None`` and no ``org_sender_name``.

        Per the per-site variation table row A13 in design.md:
        ``submit_demo_request`` is a public form, so the unified sender
        must be called with ``EmailMessage.org_id=None`` and no
        ``org_sender_name`` keyword (the From header should fall back
        to the provider's configured name).

        Validates: Requirements 6.1, 6.7
        """
        from app.modules.landing.router import (
            DEMO_REQUEST_RECIPIENT,
            submit_demo_request,
        )

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()
        payload = _valid_payload()

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.modules.landing.router.send_email",
            new=send_email_stub,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        # Endpoint returned the success-shape response.
        assert isinstance(result, DemoRequestResponse)
        assert result.success is True

        send_email_stub.assert_awaited_once()
        args, kwargs = send_email_stub.await_args

        # send_email signature: (db, message, *, org_sender_name=...)
        # Public form: no org_sender_name, no org_reply_to.
        assert kwargs.get("org_sender_name") is None
        assert kwargs.get("org_reply_to") is None

        # Positional: db, message
        message = args[1] if len(args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design Per-Site Migration Patterns row A13:
        # org_id = None (public form, no org context).
        assert message.org_id is None
        assert message.to_email == DEMO_REQUEST_RECIPIENT
        assert message.attachments == []

        # Subject incorporates the form fields so the recipient inbox
        # can scan the queue at a glance.
        assert "John Smith" in message.subject
        assert "Smith Auto" in message.subject

        # Body carries the form fields verbatim so the platform owner
        # can act on the lead without bouncing through any UI.
        assert "John Smith" in message.text_body
        assert "Smith Auto" in message.text_body
        assert "john@smithauto.co.nz" in message.text_body

    @pytest.mark.asyncio
    async def test_failure_does_not_log_email_or_fire_in_app_notif(
        self,
    ) -> None:
        """No log_email_sent and no in-app notification on failure.

        Public form ⇒ no org context ⇒ nothing to log against and no
        org admin to notify. The only failure surface is the HTTP 500
        response.

        Validates: Requirement 6.7
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()
        payload = _valid_payload()

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=False,
            provider_key=None,
            transport=None,
            message_id=None,
            error="all providers failed",
            attempts=[],
        )

        log_email_stub = AsyncMock()
        in_app_stub = AsyncMock()

        with patch(
            "app.modules.landing.router.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.modules.in_app_notifications.service.create_in_app_notification",
            new=in_app_stub,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        # Failure surface = HTTP 500 response only.
        assert not isinstance(result, DemoRequestResponse)
        assert result.status_code == 500

        # No notification_log entry — public form has no org_id.
        log_email_stub.assert_not_awaited()

        # No in-app notification — no org admin to notify.
        in_app_stub.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_honeypot_short_circuits_before_send(self) -> None:
        """Honeypot path returns success without invoking the sender.

        The honeypot guard pre-existed the migration and must continue
        to short-circuit before any provider lookup or send. Without
        this regression test it would be easy for a future refactor to
        accidentally call ``send_email`` for spam submissions.
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        request = _make_request()
        payload = _valid_payload(website="http://spam.example.com")

        send_email_stub = AsyncMock()

        with patch(
            "app.modules.landing.router.send_email",
            new=send_email_stub,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        assert isinstance(result, DemoRequestResponse)
        assert result.success is True
        # No DB lookup, no Redis rate-limit check, no send.
        db.execute.assert_not_called()
        redis.incr.assert_not_called()
        send_email_stub.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rate_limit_short_circuits_before_send(self) -> None:
        """Rate-limited request returns 429 without invoking the sender.

        Like the honeypot path, the rate limit must short-circuit
        before any unified-sender work. Pin this so a future tweak to
        the order of operations does not accidentally make us load the
        provider chain on every blocked attempt.
        """
        from app.modules.landing.router import submit_demo_request

        db = _mock_db()
        redis = _mock_redis()
        # Simulate the 6th request from this IP in the last hour.
        redis.incr = AsyncMock(return_value=6)
        request = _make_request()
        payload = _valid_payload()

        send_email_stub = AsyncMock()

        with patch(
            "app.modules.landing.router.send_email",
            new=send_email_stub,
        ):
            result = await submit_demo_request(payload, request, db, redis)

        # 429 JSONResponse, not a 200 DemoRequestResponse.
        assert not isinstance(result, DemoRequestResponse)
        assert result.status_code == 429
        send_email_stub.assert_not_awaited()
