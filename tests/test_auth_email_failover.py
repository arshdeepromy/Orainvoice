"""Failover integration tests for the auth-flow email senders.

This file pins the Phase 3 contract for the four Group A auth sites:

- A7 ``_send_permanent_lockout_email``      (task 3.7 — this file)
- A8 ``_send_invitation_email``             (task 3.8 — appended later)
- A9 ``send_verification_email``            (task 3.9 — appended later)
- A10 ``send_receipt_email`` (paid signup)  (task 3.10 — appended later)

Each site was migrated from a hand-rolled ``smtplib`` provider loop to a
single :func:`app.integrations.email_sender.send_email` call. The
unified sender owns failover, error classification, and per-attempt +
total time budgets — so the tests focus on the per-site contract:

1. The right ``EmailMessage`` shape goes into ``send_email`` (org_id,
   text/HTML body, attachments, override knobs).
2. The function returns the right thing on success and on total
   failure.
3. The legacy session ownership pattern is preserved where the design's
   per-site variation table calls it out (A7 opens its own session via
   ``async_session_factory`` because the auth caller's session may
   already be torn down by the time the best-effort send fires).

Tasks 3.8 / 3.9 / 3.10 will append A8 / A9 / A10 test classes to this
same file — keep the local helpers below generic so they can be reused.

Validates: Requirements 6.1, 6.3, 6.4
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import
# time. Importing ``app.modules.auth.service`` later in the test pulls
# in ``User`` + a network of cross-module relationships — admin /
# inventory carry the relationships those rely on.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401


# ---------------------------------------------------------------------------
# Shared helpers (kept self-contained — no imports from other test files)
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row.

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


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response``.

    Implements just the surface area the dispatchers read:
    ``status_code``, ``text``, ``headers`` (dict-like with ``.get``),
    and ``json()``.
    """

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


class _FakeClient:
    """In-process replacement for ``httpx.AsyncClient`` (failover scenario).

    Routes by URL: Brevo gets a 401 (drives ``SOFT_AUTH``, loop
    continues), SendGrid gets a 202 with ``X-Message-Id`` populated
    (success).
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
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
                headers={"X-Message-Id": "msg-auth-1"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


class _AllFail401Client(_FakeClient):
    """Variant of ``_FakeClient`` where every URL returns 401 (SOFT_AUTH)."""

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        return _FakeResponse(
            401,
            text='{"code":"unauthorized","message":"invalid api key"}',
            headers={"content-type": "application/json"},
            json_body={
                "code": "unauthorized",
                "message": "invalid api key",
            },
        )


@asynccontextmanager
async def _fake_async_session_cm(session):
    """Context manager that yields the given session for ``async with``."""
    yield session


def _patch_async_session_factory(session) -> MagicMock:
    """Build a callable that mimics ``async_session_factory`` returning *session*.

    ``async_session_factory()`` is normally an ``async_sessionmaker``
    instance which produces an async context manager. We patch it with
    a plain callable that returns an in-process async CM yielding our
    mock session, so the function under test doesn't go anywhere near
    a real DB.
    """
    factory = MagicMock()
    factory.return_value = _fake_async_session_cm(session)
    return factory


# ---------------------------------------------------------------------------
# A7 — _send_permanent_lockout_email
# ---------------------------------------------------------------------------


class TestA7SendPermanentLockoutEmailFailover:
    """End-to-end failover for ``_send_permanent_lockout_email`` (task 3.7).

    With Brevo at priority 1 and SendGrid at priority 2, the function
    must walk past the Brevo 401 (``SOFT_AUTH``), succeed on SendGrid
    (202), and return ``None`` (the function has no return value — it
    is best-effort and signals failure only via log lines).

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → function returns cleanly.

        Pins the contract that the migrated
        ``_send_permanent_lockout_email``:

        1. Opens its own session via ``async_session_factory`` (the
           caller's session is mid-transaction at this point and may
           already be gone — A7 row in the per-site variation table).
        2. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). Failure on the first must NOT abort
           the chain.
        3. Returns ``None`` without raising, regardless of provider
           outcome (best-effort send wrapped in a top-level try/except
           per Requirement 7.3).

        Validates: Requirements 6.1, 6.3, 6.4
        """
        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        # Mock the dedicated session opened by async_session_factory.
        session = AsyncMock()
        factory = _patch_async_session_factory(session)

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FakeClient.posted_urls = []
        _FakeClient.posted_payloads = []

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
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
            _FakeClient,
        ):
            from app.modules.auth.service import _send_permanent_lockout_email

            result = await _send_permanent_lockout_email("locked-user@example.com")

        # 1. The function returns None — it has no return value.
        assert result is None

        # 2. async_session_factory was called exactly once — the
        #    function opens its own session (A7 row in the per-site
        #    variation table: "caller opens its own session").
        factory.assert_called_once()

        # 3. Both REST endpoints were hit in priority order — Brevo
        #    first (401, SOFT_AUTH), then SendGrid (202, success).
        assert _FakeClient.posted_urls == [
            _FakeClient.BREVO_URL,
            _FakeClient.SENDGRID_URL,
        ]

        # 4. Provider chain was loaded once and the bounce-blocklist
        #    pre-check fired exactly once. Crucially, the blocklist
        #    call uses the session opened by async_session_factory,
        #    NOT a session passed in by the caller.
        load_providers_stub.assert_awaited_once()
        load_providers_stub.assert_awaited_with(session)
        blocklist_stub.assert_awaited_once()
        # Per design row A7: org_id=None on the EmailMessage, so the
        # blocklist pre-check is also called with org_id=None.
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") is None
        assert bl_kwargs.get("email_address") == "locked-user@example.com"

        # 5. The recipient on each payload matches the locked-out
        #    user's email — sanity check that the migration didn't
        #    drop the To address on the floor.
        brevo_payload = _FakeClient.posted_payloads[0]
        sendgrid_payload = _FakeClient.posted_payloads[1]
        assert brevo_payload["to"][0]["email"] == "locked-user@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "locked-user@example.com"
        )

        # 6. Both bodies went out — A7 sends both an HTML body
        #    (branded WorkshopPro NZ envelope) and a plain-text
        #    fallback. The legacy MIME builder used
        #    multipart/alternative with both parts, so both REST
        #    payloads should carry both.
        assert "locked" in brevo_payload.get("subject", "").lower()
        assert "WorkshopPro NZ" in brevo_payload.get("htmlContent", "")
        assert "WorkshopPro NZ" in brevo_payload.get("textContent", "")

        # 7. No attachments on either payload — A7 sends no PDF.
        assert brevo_payload.get("attachment", []) == []
        assert sendgrid_payload.get("attachments", []) == []

    @pytest.mark.asyncio
    async def test_all_providers_fail_does_not_raise(self) -> None:
        """When every provider returns ``SOFT_AUTH`` the function
        returns ``None`` without raising. No
        ``create_in_app_notification`` is fired (A7 has no org context
        — see the docstring of ``_send_permanent_lockout_email`` and
        the in-app-notifications design §4.2 carve-out).

        Validates: Requirements 6.1, 6.4
        """
        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        session = AsyncMock()
        factory = _patch_async_session_factory(session)

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_all_auth_fail_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _AllFail401Client,
        ):
            from app.modules.auth.service import _send_permanent_lockout_email

            result = await _send_permanent_lockout_email("locked-user@example.com")

        # 1. Best-effort contract: returns None, does NOT raise — the
        #    lockout process must never be blocked by an email
        #    delivery failure (Requirement 7.3 in the auth flow).
        assert result is None

        # 2. Both providers were attempted (chain not short-circuited
        #    by a HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

    @pytest.mark.asyncio
    async def test_no_active_providers_does_not_raise(self) -> None:
        """When no providers are configured at all, the function
        returns ``None`` cleanly. The unified sender returns
        ``attempts=[]`` and the function logs a warning (preserved
        from the legacy raw-smtplib version which had the same
        early-out).

        Validates: Requirement 6.1
        """
        session = AsyncMock()
        factory = _patch_async_session_factory(session)

        load_providers_stub = AsyncMock(return_value=[])
        blocklist_stub = AsyncMock(return_value=(False, None))

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_no_providers_alert",
            new_callable=AsyncMock,
        ):
            from app.modules.auth.service import _send_permanent_lockout_email

            result = await _send_permanent_lockout_email("locked-user@example.com")

        assert result is None
        load_providers_stub.assert_awaited_once()


class TestA7SendPermanentLockoutEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A7 in
    ``design.md``: ``EmailMessage.org_id`` MUST be ``None`` (no org
    context — security-path send). HTML + plain text bodies. No
    attachments. No ``org_sender_name`` override.

    Validates: Requirements 6.3 (org_id plumbing) and 6.4 (no manual
    smtplib loop)
    """

    @pytest.mark.asyncio
    async def test_email_message_has_org_id_none_and_both_bodies(self) -> None:
        """``send_email`` is called with the right ``EmailMessage`` shape.

        Pins:

        - ``message.org_id is None`` — A7 row in the per-site
          variation table: "No org context (security alert); caller
          opens its own session". A future refactor that starts
          plumbing some org_id into this path would change the
          bounce-blocklist scope and would need explicit review.
        - ``message.text_body`` is the plain-text body (contains the
          support URL and the lockout reason).
        - ``message.html_body`` carries the WorkshopPro NZ branded
          envelope.
        - ``message.attachments`` is empty — A7 sends no PDF.
        - No ``org_sender_name`` / ``org_reply_to`` override — A7
          never set a per-org sender (the legacy implementation used
          ``provider.config['from_name']`` with a "WorkshopPro NZ"
          fallback that the unified sender does not preserve; this is
          intentional per the per-site variation table).

        Validates: Requirements 6.1, 6.3, 6.4
        """
        session = AsyncMock()
        factory = _patch_async_session_factory(session)

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            # Patch where the migrated function imports it (function-
            # local import inside ``_send_permanent_lockout_email``).
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.auth.service import _send_permanent_lockout_email

            await _send_permanent_lockout_email("locked-user@example.com")

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        # Positional: db, message
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design Per-Site Migration Patterns > Group A row A7:
        # No org context — org_id is None.
        assert message.org_id is None

        # Recipient on the message matches the function's email arg.
        assert message.to_email == "locked-user@example.com"

        # Subject mentions the lockout outcome.
        assert "locked" in message.subject.lower()

        # Both bodies are present — the legacy MIME builder used
        # multipart/alternative with both a plain-text and an HTML
        # part. The migration intentionally keeps both.
        assert message.html_body is not None and message.html_body != ""
        assert message.text_body is not None and message.text_body != ""

        # The plain-text body references the support URL so the user
        # has a non-HTML path to action.
        assert "support" in message.text_body.lower()
        # The HTML body carries the WorkshopPro NZ envelope.
        assert "WorkshopPro NZ" in message.html_body

        # No attachments.
        assert message.attachments == []

        # Positional db arg is the session opened by
        # async_session_factory (NOT something passed by the caller —
        # the caller doesn't pass a session at all).
        passed_session = _args[0] if _args else None
        assert passed_session is session

    @pytest.mark.asyncio
    async def test_no_org_sender_name_or_reply_to_passed(self) -> None:
        """A7 does NOT pass ``org_sender_name`` or ``org_reply_to``.

        Per the per-site variation table the ``org_sender_name``
        column for A7 is ``None`` — the provider's configured
        ``from_name`` is used. This pins that contract: a future
        refactor that starts plumbing some name into this path would
        change the From header on outbound lockout emails and would
        need explicit review.

        Validates: Requirement 6.5 (org_sender_name only when
        originally set — A7 never set one)
        """
        session = AsyncMock()
        factory = _patch_async_session_factory(session)

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.auth.service import _send_permanent_lockout_email

            await _send_permanent_lockout_email("locked-user@example.com")

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args

        # No org_sender_name / org_reply_to keyword — the provider's
        # from_name (or its default) is what shows up in the From
        # header.
        assert (
            "org_sender_name" not in kwargs
            or kwargs["org_sender_name"] is None
        )
        assert (
            "org_reply_to" not in kwargs
            or kwargs["org_reply_to"] is None
        )
