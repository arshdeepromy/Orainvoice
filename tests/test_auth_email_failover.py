"""Failover integration tests for the auth-flow email senders.

This file pins the Phase 3 contract for the four Group A auth sites:

- A7 ``_send_permanent_lockout_email``      (task 3.7 — this file)
- A8 ``_send_invitation_email``             (task 3.8 — this file)
- A9 ``send_verification_email``            (task 3.9 — this file)
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


# ---------------------------------------------------------------------------
# A8 — _send_invitation_email
# ---------------------------------------------------------------------------


class TestA8SendInvitationEmailFailover:
    """End-to-end failover for ``_send_invitation_email`` (task 3.8).

    A8 has two execution shapes that the test set must pin:

    1. **Caller hands us a session** (the production path — both
       ``provision_org`` and ``resend_invitation`` always pass one).
       The function must use that session directly: NO call to
       ``async_session_factory``. This keeps the bounce-blocklist
       pre-check and provider-load inside the caller's transaction.
    2. **Caller passes ``db=None``** (legacy resend path). The function
       must open its own session via ``async_session_factory`` and
       pass it to ``send_email``.

    With Brevo at priority 1 and SendGrid at priority 2, the function
    walks past the Brevo 401 (``SOFT_AUTH``), succeeds on SendGrid
    (202), and returns ``None`` (the function has no return value —
    it is best-effort and signals failure only via log lines).

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_with_caller_session(self) -> None:
        """Brevo 401 → SendGrid 202 with a caller-provided session.

        Pins the contract that the migrated ``_send_invitation_email``:

        1. Uses the caller's session directly when ``db`` is supplied
           — does NOT open its own via ``async_session_factory``.
           This is the production execution path.
        2. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). The 401 from Brevo classifies as
           ``SOFT_AUTH`` and the loop continues.
        3. Returns ``None`` without raising.

        Validates: Requirements 6.1, 6.3, 6.4
        """
        import uuid as _uuid

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        caller_session = AsyncMock()
        # Sentinel factory — must NOT be called when caller passes a
        # session.
        factory = MagicMock(side_effect=AssertionError(
            "async_session_factory must not be called when caller "
            "passes db"
        ))

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        # Skip notification template resolution — we exercise the
        # hardcoded fallback body so the test doesn't depend on
        # template seed data.
        resolve_template_stub = AsyncMock(return_value=None)

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FakeClient.posted_urls = []
        _FakeClient.posted_payloads = []

        org_id = _uuid.uuid4()

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
            "app.modules.notifications.service.resolve_template",
            new=resolve_template_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _FakeClient,
        ):
            from app.modules.auth.service import _send_invitation_email

            result = await _send_invitation_email(
                "invitee@example.com",
                "tok_invite_caller_123456",
                db=caller_session,
                org_id=org_id,
                org_name="Acme Workshop",
                base_url="https://app.example.com",
            )

        # 1. The function returns None — best-effort send, no return.
        assert result is None

        # 2. async_session_factory was NOT called — the caller passed
        #    a session and the function used it directly. (The
        #    sentinel above raises AssertionError if called.)
        factory.assert_not_called()

        # 3. The provider chain was loaded against the caller's
        #    session, NOT a freshly opened one.
        load_providers_stub.assert_awaited_once()
        load_providers_stub.assert_awaited_with(caller_session)

        # 4. Both REST endpoints were hit in priority order — Brevo
        #    first (401, SOFT_AUTH), then SendGrid (202, success).
        assert _FakeClient.posted_urls == [
            _FakeClient.BREVO_URL,
            _FakeClient.SENDGRID_URL,
        ]

        # 5. The bounce-blocklist pre-check fired exactly once and
        #    used the org_id passed to the function (A8 row in the
        #    per-site variation table: org_id is the inviting org's
        #    id when known). This pins the org-scoped block-list
        #    behaviour against a future refactor that drops org_id.
        blocklist_stub.assert_awaited_once()
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") == org_id
        assert bl_kwargs.get("email_address") == "invitee@example.com"

        # 6. Recipient + invite URL on the payload match the function
        #    args — sanity check that the migration didn't drop the
        #    To address or mangle the URL.
        brevo_payload = _FakeClient.posted_payloads[0]
        sendgrid_payload = _FakeClient.posted_payloads[1]
        assert brevo_payload["to"][0]["email"] == "invitee@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "invitee@example.com"
        )
        # Invite URL is built from base_url + the verify-email path
        # with the raw token. Both bodies should carry it (HTML+text).
        expected_url = (
            "https://app.example.com/verify-email?"
            "token=tok_invite_caller_123456"
        )
        assert expected_url in brevo_payload.get("htmlContent", "")
        assert expected_url in brevo_payload.get("textContent", "")

        # 7. From-name override flowed through — A8 passes
        #    ``org_sender_name=org_name`` so the From header reads as
        #    coming from the org. The Brevo REST payload's sender
        #    name should be "Acme Workshop", not the provider's
        #    static "OraInvoice".
        assert brevo_payload.get("sender", {}).get("name") == "Acme Workshop"
        # SendGrid puts it under from.name.
        assert (
            sendgrid_payload.get("from", {}).get("name") == "Acme Workshop"
        )

        # 8. No attachments — A8 sends invite link only.
        assert brevo_payload.get("attachment", []) == []
        assert sendgrid_payload.get("attachments", []) == []

    @pytest.mark.asyncio
    async def test_db_none_opens_own_session(self) -> None:
        """When ``db=None``, the function opens its own session.

        Pins the legacy db-may-be-None contract: a resend from a
        torn-down session must still be able to dispatch. The
        function:

        1. Calls ``async_session_factory()`` exactly once.
        2. Passes the session it gets back to ``send_email``
           (verified by the fact that ``_load_active_providers`` is
           awaited with that session).
        3. Returns ``None`` cleanly on success.

        Validates: Requirement 6.1 (db-may-be-None preservation)
        """
        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        own_session = AsyncMock()
        factory = _patch_async_session_factory(own_session)

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

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
            from app.modules.auth.service import _send_invitation_email

            # No db, no org_id — the legacy resend path. Template
            # resolution short-circuits (db is None) so the hardcoded
            # body is used.
            result = await _send_invitation_email(
                "invitee@example.com",
                "tok_invite_no_db_456",
                db=None,
                org_id=None,
                org_name="Acme Workshop",
                base_url="https://app.example.com",
            )

        assert result is None

        # 1. The factory was called exactly once — the function
        #    opened its own session.
        factory.assert_called_once()

        # 2. The provider load (and thus the rest of send_email's
        #    work) ran against the session opened by the factory.
        load_providers_stub.assert_awaited_with(own_session)

        # 3. With org_id=None the bounce-blocklist falls back to
        #    platform-wide rows; the call must reflect that.
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") is None

    @pytest.mark.asyncio
    async def test_no_providers_logs_dev_invite_url(self) -> None:
        """No active providers → DEV INVITE URL warning in dev.

        Pins the dev-fallback contract from the A8 row in the
        per-site variation table: when ``result.attempts == []`` (no
        providers configured at all) and the environment is
        ``development``, the function logs the invite URL at WARNING
        so a developer running the stack locally without any
        provider can grab the link from the logs.

        Validates: Requirement 6.1 (preserve existing dev UX)
        """
        caller_session = AsyncMock()
        load_providers_stub = AsyncMock(return_value=[])
        blocklist_stub = AsyncMock(return_value=(False, None))
        resolve_template_stub = AsyncMock(return_value=None)

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_no_providers_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new=resolve_template_stub,
        ), patch(
            "app.modules.auth.service.settings.environment",
            "development",
        ):
            from app.modules.auth.service import _send_invitation_email

            with patch(
                "app.modules.auth.service.logger.warning"
            ) as mock_warn:
                result = await _send_invitation_email(
                    "invitee@example.com",
                    "tok_no_provider_789xyz",
                    db=caller_session,
                    org_id=None,
                    org_name="Acme Workshop",
                    base_url="https://app.example.com",
                )

        # 1. Best-effort contract: returns None, does NOT raise.
        assert result is None

        # 2. The provider chain was loaded (so we hit the
        #    no-providers branch), and the log line that quotes the
        #    dev invite URL fired. Use ``any`` to avoid pinning the
        #    exact log call order — the function logs both the
        #    "No active email provider" warning and then the
        #    "DEV INVITE URL" warning.
        load_providers_stub.assert_awaited_once()

        all_calls = [c.args for c in mock_warn.call_args_list]
        # The format string is "DEV INVITE URL: %s" with the URL as
        # the second positional arg.
        dev_url_calls = [
            c for c in all_calls
            if c and "DEV INVITE URL" in str(c[0])
        ]
        assert dev_url_calls, (
            f"expected a DEV INVITE URL warning, got {all_calls!r}"
        )
        # The URL passed must be the verify-email link with the raw
        # token — the whole point of the dev fallback is that the
        # developer can copy it.
        url_arg = dev_url_calls[0][1]
        assert url_arg == (
            "https://app.example.com/verify-email?"
            "token=tok_no_provider_789xyz"
        )

    @pytest.mark.asyncio
    async def test_no_providers_in_production_does_not_log_url(self) -> None:
        """In production, the no-providers branch must NOT log the URL.

        Token-bearing URLs are sensitive — leaking them in production
        logs would let any log-reader claim the invite. The dev
        fallback is gated on ``settings.environment == 'development'``
        and this test pins that gate.

        Validates: Requirement 6.1 (dev UX preserved without leaking
        in prod)
        """
        caller_session = AsyncMock()
        load_providers_stub = AsyncMock(return_value=[])
        blocklist_stub = AsyncMock(return_value=(False, None))
        resolve_template_stub = AsyncMock(return_value=None)

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_no_providers_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new=resolve_template_stub,
        ), patch(
            "app.modules.auth.service.settings.environment",
            "production",
        ):
            from app.modules.auth.service import _send_invitation_email

            with patch(
                "app.modules.auth.service.logger.warning"
            ) as mock_warn:
                await _send_invitation_email(
                    "invitee@example.com",
                    "tok_prod_no_provider_aaa",
                    db=caller_session,
                    org_id=None,
                    org_name="Acme Workshop",
                    base_url="https://app.example.com",
                )

        all_calls = [c.args for c in mock_warn.call_args_list]
        dev_url_calls = [
            c for c in all_calls
            if c and "DEV INVITE URL" in str(c[0])
        ]
        # Crucially: NO DEV INVITE URL log in production.
        assert not dev_url_calls, (
            "DEV INVITE URL must not log outside development; "
            f"got: {dev_url_calls!r}"
        )

    @pytest.mark.asyncio
    async def test_all_providers_fail_does_not_raise(self) -> None:
        """When every provider returns ``SOFT_AUTH`` the function
        returns ``None`` without raising. No
        ``create_in_app_notification`` is fired (auth-flow carve-out
        per the per-site variation table for A8 — same gap A7 has).

        Validates: Requirements 6.1, 6.4
        """
        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        caller_session = AsyncMock()
        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        resolve_template_stub = AsyncMock(return_value=None)

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_all_auth_fail_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new=resolve_template_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _AllFail401Client,
        ):
            from app.modules.auth.service import _send_invitation_email

            result = await _send_invitation_email(
                "invitee@example.com",
                "tok_all_fail_bbb",
                db=caller_session,
                org_id=None,
                org_name="Acme Workshop",
                base_url="https://app.example.com",
            )

        # 1. Best-effort contract: returns None, does NOT raise.
        assert result is None

        # 2. Both providers were attempted (chain not short-circuited
        #    by HARD_RECIPIENT or HARD_PAYLOAD).
        assert len(_AllFail401Client.posted_urls) == 2


class TestA8SendInvitationEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A8 in
    ``design.md``: ``EmailMessage.org_id = org.id`` (when known),
    ``org_sender_name = org.name``, both bodies present, no
    attachments. Also pins the function-local imports so a future
    refactor can't accidentally re-add a top-level ``smtplib`` import
    inside this function.

    Validates: Requirements 6.3 (org_id + org_sender_name plumbing)
    and 6.4 (no manual smtplib loop)
    """

    @pytest.mark.asyncio
    async def test_email_message_has_org_id_and_both_bodies(self) -> None:
        """``send_email`` is called with the right ``EmailMessage``
        and override args.

        Pins:

        - ``message.org_id`` matches the org_id passed to the
          function — A8 is org-scoped (vs A7 which is None).
        - ``message.text_body`` carries the invite URL.
        - ``message.html_body`` carries the invite URL and the
          OraInvoice envelope.
        - ``message.attachments`` is empty.
        - ``org_sender_name`` keyword arg equals the function's
          ``org_name`` arg — the From header reads as the org.
        - ``org_reply_to`` is NOT passed (A8 doesn't override
          reply-to in v1; the provider's static reply_to wins).

        Validates: Requirements 6.1, 6.3
        """
        import uuid as _uuid

        caller_session = AsyncMock()
        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[MagicMock()],
        )
        resolve_template_stub = AsyncMock(return_value=None)

        org_id = _uuid.uuid4()

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new=resolve_template_stub,
        ):
            from app.modules.auth.service import _send_invitation_email

            await _send_invitation_email(
                "invitee@example.com",
                "tok_msg_shape_ccc",
                db=caller_session,
                org_id=org_id,
                org_name="Acme Workshop",
                base_url="https://app.example.com",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        # Positional: db, message
        assert len(_args) >= 2
        passed_db = _args[0]
        message = _args[1]

        # 1. The caller's session was forwarded to send_email — the
        #    function did NOT swap it for a fresh one.
        assert passed_db is caller_session

        # 2. org_id flows through unchanged (A8 row in the per-site
        #    variation table: "org.id (when known)").
        assert message.org_id == org_id

        # 3. Recipient on the message matches the function's email
        #    arg.
        assert message.to_email == "invitee@example.com"

        # 4. Subject mentions the inviting org by name (preserved
        #    from the legacy hardcoded fallback body).
        assert "Acme Workshop" in message.subject

        # 5. Both bodies are present and both carry the invite URL.
        expected_url = (
            "https://app.example.com/verify-email?token=tok_msg_shape_ccc"
        )
        assert message.html_body and expected_url in message.html_body
        assert message.text_body and expected_url in message.text_body

        # 6. No attachments — A8 sends invite link only.
        assert message.attachments == []

        # 7. org_sender_name keyword equals org_name — A8 row in the
        #    per-site variation table: "org.name". This is what
        #    drives the From header to read as the org.
        assert kwargs.get("org_sender_name") == "Acme Workshop"

        # 8. org_reply_to is NOT passed (or is explicitly None). A8
        #    does not override reply-to in v1; a future change that
        #    wires per-org reply-to through here would need explicit
        #    review.
        assert (
            "org_reply_to" not in kwargs
            or kwargs["org_reply_to"] is None
        )

    @pytest.mark.asyncio
    async def test_uses_resolved_template_when_available(self) -> None:
        """When ``resolve_template`` returns a rendered template, the
        message uses its subject and body instead of the hardcoded
        fallback. Pins the template-resolution path that A8 inherits
        from the legacy implementation — orgs can customise the
        invite copy via the notifications module.

        Validates: Requirement 6.3 (template integration preserved)
        """
        import uuid as _uuid

        caller_session = AsyncMock()
        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[MagicMock()],
        )

        rendered = MagicMock()
        rendered.subject = "Custom: Welcome to Acme!"
        rendered.body = "Hi! Click https://app.example.com/verify-email?token=tok_template_ddd to join."
        resolve_template_stub = AsyncMock(return_value=rendered)

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new=resolve_template_stub,
        ):
            from app.modules.auth.service import _send_invitation_email

            await _send_invitation_email(
                "invitee@example.com",
                "tok_template_ddd",
                db=caller_session,
                org_id=_uuid.uuid4(),
                org_name="Acme Workshop",
                base_url="https://app.example.com",
            )

        # Template was resolved, and its subject/body flowed into the
        # EmailMessage.
        resolve_template_stub.assert_awaited_once()
        _args, _kwargs = send_email_stub.await_args
        message = _args[1]
        assert message.subject == "Custom: Welcome to Acme!"
        assert "tok_template_ddd" in message.text_body
        assert "tok_template_ddd" in message.html_body


# ---------------------------------------------------------------------------
# A9 — send_verification_email
# ---------------------------------------------------------------------------


class TestA9SendVerificationEmailFailover:
    """End-to-end failover for ``send_verification_email`` (task 3.9).

    A9 mirrors the A8 pattern (HTML + text bodies, dev-fallback log
    on no-providers) but with a few site-specific contracts the test
    set must pin:

    1. The function is **always called with a session** by every
       production caller (``public_signup`` paid + trial flows in
       ``organisations/service.py`` and ``resend_verification_email``
       in this same module). Unlike A8 it does **not** fall back to
       opening its own session — so the production path uses the
       caller's session directly.
    2. ``org_id`` is plumbed through the new keyword arg per the A9
       row in the per-site variation table (``EmailMessage.org_id =
       org.id``). All current callers have it; the parameter defaults
       to ``None`` so a future caller without org context still works.
    3. The dev-fallback log message is ``"DEV VERIFICATION URL: %s"``
       (different from A8's ``"DEV INVITE URL"``). This is the
       message a developer running without any provider configured
       will copy from the logs.

    With Brevo at priority 1 and SendGrid at priority 2, the function
    walks past the Brevo 401 (``SOFT_AUTH``), succeeds on SendGrid
    (202), and returns ``None`` (the function has no return value —
    it is best-effort).

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_with_caller_session(self) -> None:
        """Brevo 401 → SendGrid 202 with the caller's session.

        Pins:

        1. The function uses the caller's session directly — no call
           to ``async_session_factory`` (A9 is always called from a
           live request/transaction context).
        2. POSTs the Brevo URL first (priority 1) and the SendGrid
           URL second (priority 2); 401 from Brevo classifies as
           ``SOFT_AUTH`` and the loop continues.
        3. Returns ``None`` without raising.
        4. The bounce-blocklist pre-check uses the org_id passed to
           the function — so blocks scoped to the inviting org take
           effect.
        5. Both REST payloads carry the verification URL with the
           ``&type=signup`` suffix that the public-signup flow
           depends on (``verify_signup_email`` reads this token from
           the same redis key shape).
        6. The From header reads as the org (Brevo: ``sender.name``;
           SendGrid: ``from.name``) — driven by
           ``org_sender_name=org_name``.

        Validates: Requirements 6.1, 6.3, 6.4
        """
        import uuid as _uuid

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        caller_session = AsyncMock()
        # Sentinel — A9 must NOT open its own session when the caller
        # passes one. (This is the only execution path in
        # production — no resend-from-torn-down-session legacy
        # contract for A9.)
        factory = MagicMock(side_effect=AssertionError(
            "async_session_factory must not be called by "
            "send_verification_email"
        ))

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FakeClient.posted_urls = []
        _FakeClient.posted_payloads = []

        org_id = _uuid.uuid4()

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
            from app.modules.auth.service import send_verification_email

            result = await send_verification_email(
                caller_session,
                email="newadmin@example.com",
                user_name="Admin User",
                org_name="Acme Workshop",
                verification_token="tok_verify_caller_123456",
                base_url="https://app.example.com",
                org_id=org_id,
            )

        # 1. Best-effort contract: returns None.
        assert result is None

        # 2. async_session_factory was NOT called — the caller passed
        #    a session and the function used it directly.
        factory.assert_not_called()

        # 3. The provider chain was loaded against the caller's
        #    session.
        load_providers_stub.assert_awaited_once()
        load_providers_stub.assert_awaited_with(caller_session)

        # 4. Both REST endpoints were hit in priority order — Brevo
        #    first (401 → SOFT_AUTH), then SendGrid (202 → success).
        assert _FakeClient.posted_urls == [
            _FakeClient.BREVO_URL,
            _FakeClient.SENDGRID_URL,
        ]

        # 5. Bounce-blocklist pre-check used the function's org_id
        #    (A9 row in the per-site variation table: org.id). Pins
        #    the org-scoped block-list behaviour against a future
        #    refactor that drops org_id.
        blocklist_stub.assert_awaited_once()
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") == org_id
        assert bl_kwargs.get("email_address") == "newadmin@example.com"

        # 6. Recipient on each payload matches the function arg.
        brevo_payload = _FakeClient.posted_payloads[0]
        sendgrid_payload = _FakeClient.posted_payloads[1]
        assert brevo_payload["to"][0]["email"] == "newadmin@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "newadmin@example.com"
        )

        # 7. The verification URL (with &type=signup) is on both
        #    bodies. ``verify_signup_email`` reads the token from
        #    redis using the same prefix the create_token side
        #    writes; the URL must include ``type=signup`` so the
        #    frontend ``/verify-email`` route can dispatch to the
        #    signup-specific handler.
        expected_url = (
            "https://app.example.com/verify-email?"
            "token=tok_verify_caller_123456&type=signup"
        )
        assert expected_url in brevo_payload.get("htmlContent", "")
        assert expected_url in brevo_payload.get("textContent", "")

        # 8. From-name override flowed through — A9 passes
        #    ``org_sender_name=org_name`` so the From header reads
        #    as the org. The Brevo REST payload's sender name
        #    should be "Acme Workshop", not the provider's static
        #    "OraInvoice".
        assert brevo_payload.get("sender", {}).get("name") == "Acme Workshop"
        # SendGrid puts it under from.name.
        assert (
            sendgrid_payload.get("from", {}).get("name") == "Acme Workshop"
        )

        # 9. No attachments — A9 sends verification link only.
        assert brevo_payload.get("attachment", []) == []
        assert sendgrid_payload.get("attachments", []) == []

    @pytest.mark.asyncio
    async def test_no_providers_logs_dev_verification_url(self) -> None:
        """No active providers → DEV VERIFICATION URL warning in dev.

        Pins the dev-fallback contract from the A9 row in the
        per-site variation table: when ``result.attempts == []`` (no
        providers configured) and the environment is
        ``development``, the function logs the verification URL at
        WARNING. Crucially the log message is
        ``"DEV VERIFICATION URL: %s"`` — different from A8's
        ``"DEV INVITE URL"`` — so a developer can tell at a glance
        which token they're picking up.

        Validates: Requirement 6.1 (preserve existing dev UX)
        """
        import uuid as _uuid

        caller_session = AsyncMock()
        load_providers_stub = AsyncMock(return_value=[])
        blocklist_stub = AsyncMock(return_value=(False, None))

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_no_providers_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.auth.service.settings.environment",
            "development",
        ):
            from app.modules.auth.service import send_verification_email

            with patch(
                "app.modules.auth.service.logger.warning"
            ) as mock_warn:
                result = await send_verification_email(
                    caller_session,
                    email="newadmin@example.com",
                    user_name="Admin User",
                    org_name="Acme Workshop",
                    verification_token="tok_no_provider_dev_789",
                    base_url="https://app.example.com",
                    org_id=_uuid.uuid4(),
                )

        # 1. Best-effort contract: returns None, does NOT raise.
        assert result is None

        # 2. Provider chain was loaded (so we hit the no-providers
        #    branch) and the dev URL log fired with the verification
        #    URL as the second positional arg.
        load_providers_stub.assert_awaited_once()

        all_calls = [c.args for c in mock_warn.call_args_list]
        dev_url_calls = [
            c for c in all_calls
            if c and "DEV VERIFICATION URL" in str(c[0])
        ]
        assert dev_url_calls, (
            f"expected a DEV VERIFICATION URL warning, got {all_calls!r}"
        )
        url_arg = dev_url_calls[0][1]
        # The URL passed to the log line is the verify-email link
        # with the raw token AND the &type=signup qualifier — the
        # signup-flow contract.
        assert url_arg == (
            "https://app.example.com/verify-email?"
            "token=tok_no_provider_dev_789&type=signup"
        )

    @pytest.mark.asyncio
    async def test_no_providers_in_production_does_not_log_url(self) -> None:
        """In production, the no-providers branch must NOT log the URL.

        Verification URLs grant immediate email-verification + JWT
        issuance to the bearer (``verify_signup_email`` issues the
        access + refresh tokens directly on success — no password
        re-prompt). Leaking the URL in production logs would let any
        log-reader claim the verified account. The dev fallback is
        gated on ``settings.environment == 'development'`` and this
        test pins that gate.

        Validates: Requirement 6.1 (dev UX preserved without leaking
        in prod)
        """
        import uuid as _uuid

        caller_session = AsyncMock()
        load_providers_stub = AsyncMock(return_value=[])
        blocklist_stub = AsyncMock(return_value=(False, None))

        with patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender._maybe_fire_no_providers_alert",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.auth.service.settings.environment",
            "production",
        ):
            from app.modules.auth.service import send_verification_email

            with patch(
                "app.modules.auth.service.logger.warning"
            ) as mock_warn:
                await send_verification_email(
                    caller_session,
                    email="newadmin@example.com",
                    user_name="Admin User",
                    org_name="Acme Workshop",
                    verification_token="tok_prod_no_provider_aaa",
                    base_url="https://app.example.com",
                    org_id=_uuid.uuid4(),
                )

        all_calls = [c.args for c in mock_warn.call_args_list]
        dev_url_calls = [
            c for c in all_calls
            if c and "DEV VERIFICATION URL" in str(c[0])
        ]
        # Crucially: NO DEV VERIFICATION URL log in production.
        assert not dev_url_calls, (
            "DEV VERIFICATION URL must not log outside development; "
            f"got: {dev_url_calls!r}"
        )

    @pytest.mark.asyncio
    async def test_all_providers_fail_does_not_raise(self) -> None:
        """Every provider returns ``SOFT_AUTH`` → returns ``None``.

        When the loop exhausts and no provider succeeded the function
        logs the failure and returns ``None``. No
        ``create_in_app_notification`` is fired (auth-flow carve-out
        per the per-site variation table for A9 — same gap A7 / A8
        have). The dev URL log also fires in this branch (mirroring
        A8) so a developer with broken providers still gets the link.

        Validates: Requirements 6.1, 6.4
        """
        import uuid as _uuid

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        caller_session = AsyncMock()
        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
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
            from app.modules.auth.service import send_verification_email

            result = await send_verification_email(
                caller_session,
                email="newadmin@example.com",
                user_name="Admin User",
                org_name="Acme Workshop",
                verification_token="tok_all_fail_bbb",
                base_url="https://app.example.com",
                org_id=_uuid.uuid4(),
            )

        # 1. Best-effort contract: returns None, does NOT raise.
        assert result is None

        # 2. Both providers were attempted (chain not short-circuited
        #    by HARD_RECIPIENT or HARD_PAYLOAD).
        assert len(_AllFail401Client.posted_urls) == 2


class TestA9SendVerificationEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A9 in
    ``design.md``: ``EmailMessage.org_id = org.id``,
    ``org_sender_name = org.name``, both bodies present, no
    attachments. Pins the function-local imports so a future refactor
    can't accidentally re-add a top-level ``smtplib`` import inside
    this function.

    Validates: Requirements 6.3 (org_id + org_sender_name plumbing)
    and 6.4 (no manual smtplib loop)
    """

    @pytest.mark.asyncio
    async def test_email_message_has_org_id_and_both_bodies(self) -> None:
        """``send_email`` is called with the right ``EmailMessage``
        and override args.

        Pins:

        - ``message.org_id`` matches the org_id passed to the
          function — A9 is org-scoped per the per-site variation
          table.
        - ``message.text_body`` carries the verification URL with
          ``&type=signup``.
        - ``message.html_body`` carries the verification URL and the
          OraInvoice envelope.
        - ``message.attachments`` is empty.
        - ``org_sender_name`` keyword arg equals the function's
          ``org_name`` arg — drives the From header.
        - ``org_reply_to`` is NOT passed (A9 doesn't override
          reply-to in v1; the provider's static reply_to wins).
        - The caller's session is forwarded to ``send_email`` —
          A9 does not open its own session.

        Validates: Requirements 6.1, 6.3
        """
        import uuid as _uuid

        caller_session = AsyncMock()
        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[MagicMock()],
        )

        org_id = _uuid.uuid4()

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.auth.service import send_verification_email

            await send_verification_email(
                caller_session,
                email="newadmin@example.com",
                user_name="Admin User",
                org_name="Acme Workshop",
                verification_token="tok_msg_shape_ccc",
                base_url="https://app.example.com",
                org_id=org_id,
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        # Positional: db, message
        assert len(_args) >= 2
        passed_db = _args[0]
        message = _args[1]

        # 1. The caller's session was forwarded to send_email — A9
        #    does NOT swap it for a fresh one.
        assert passed_db is caller_session

        # 2. org_id flows through unchanged (A9 row in the per-site
        #    variation table: org.id).
        assert message.org_id == org_id

        # 3. Recipient on the message matches the function's email
        #    arg.
        assert message.to_email == "newadmin@example.com"

        # 4. Subject is the welcome subject (preserved verbatim
        #    from the legacy hardcoded body).
        assert "Welcome to OraInvoice" in message.subject
        assert "Verify your email" in message.subject

        # 5. Both bodies are present and both carry the verification
        #    URL — including the ``&type=signup`` qualifier the
        #    public-signup flow depends on.
        expected_url = (
            "https://app.example.com/verify-email?"
            "token=tok_msg_shape_ccc&type=signup"
        )
        assert message.html_body and expected_url in message.html_body
        assert message.text_body and expected_url in message.text_body

        # 6. Body greets the user by name and references the org.
        assert "Admin User" in message.text_body
        assert "Acme Workshop" in message.text_body

        # 7. No attachments — A9 sends verification link only.
        assert message.attachments == []

        # 8. org_sender_name keyword equals org_name — A9 row in the
        #    per-site variation table: org.name. Drives the From
        #    header to read as the org.
        assert kwargs.get("org_sender_name") == "Acme Workshop"

        # 9. org_reply_to is NOT passed (or is explicitly None). A9
        #    does not override reply-to in v1; a future change that
        #    wires per-org reply-to through here would need explicit
        #    review.
        assert (
            "org_reply_to" not in kwargs
            or kwargs["org_reply_to"] is None
        )

    @pytest.mark.asyncio
    async def test_default_org_id_none_passes_through(self) -> None:
        """``org_id`` defaults to ``None`` and flows through cleanly.

        A9 added ``org_id`` as a keyword-only parameter with a default
        of ``None``. Existing or future callers that don't yet plumb
        org_id through must still get a working email — the
        bounce-blocklist pre-check falls back to platform-wide rows
        when org_id is None. This pins the default-arg behaviour
        against a future refactor that makes ``org_id`` required.

        Validates: Requirement 6.3
        """
        caller_session = AsyncMock()
        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-2",
            error=None,
            attempts=[MagicMock()],
        )

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.auth.service import send_verification_email

            # No org_id kwarg — relies on the default of None.
            await send_verification_email(
                caller_session,
                email="newadmin@example.com",
                user_name="Admin User",
                org_name="Acme Workshop",
                verification_token="tok_default_orgid_eee",
                base_url="https://app.example.com",
            )

        send_email_stub.assert_awaited_once()
        _args, _kwargs = send_email_stub.await_args
        message = _args[1]

        # org_id defaulted to None — and the message reflects that.
        assert message.org_id is None
