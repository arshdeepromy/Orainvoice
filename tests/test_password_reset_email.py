"""Unit tests for ``_send_password_reset_email`` (Phase 4 task 4.1 — C3).

Phase 0.5 shipped this function as a hand-rolled ``smtplib`` provider
loop (security hotfix — see commit on ``main`` tagged
``email-provider-unification: phase 0.5 …``). Phase 4 task 4.1 replaces
that loop with a single call to
:func:`app.integrations.email_sender.send_email`. These tests pin the
new contract:

  - Success path: with one active provider the function constructs the
    right ``EmailMessage`` (org_id is ``None`` per design row C3, the
    reset URL appears in both bodies, no attachments) and ``send_email``
    is awaited exactly once.
  - No-providers path: when ``send_email`` returns ``attempts=[]``,
    the function returns ``None`` without raising and emits a warning
    log line referencing the recipient.
  - Failover chain (``::test_failover_chain``): three active providers
    where the first two fail (SOFT_AUTH then SOFT_PROVIDER) and the
    third succeeds. Delivery must still complete and the function must
    return cleanly without raising. This exercises the full loop in
    ``send_email`` end-to-end (via ``dispatch_one_provider``) so a
    regression in failover wiring shows up here.

The function intentionally does NOT call ``log_email_sent`` (the
security-critical password-reset email path stays out of org
notification logs per the in-app-notifications design §4.2 carve-out)
and does NOT raise on failure (the ``request_password_reset`` endpoint
always returns the same generic "if your email is registered…"
response, so a delivery error must not leak signal back to the API
surface).

Validates: Requirements 8.1, 22.2, 22.3
"""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.integrations.email_sender import (
    EmailAttempt,
    FailureKind,
    SendResult,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row for the failover chain.

    Only the fields the unified-sender loop reads are populated.
    Credentials decryption is bypassed by patching
    ``dispatch_one_provider`` directly, so the encrypted blob never has
    to round-trip through ``envelope_decrypt_str``.
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSendPasswordResetEmail:
    """Pin the contract of the migrated ``_send_password_reset_email``."""

    @pytest.mark.asyncio
    async def test_success_path_calls_send_email_once_with_reset_url(self):
        """With a caller-provided session, the function builds the
        right ``EmailMessage`` and dispatches via the unified sender
        exactly once.

        Pins per design row C3:

        - ``EmailMessage.org_id is None`` — account-recovery path has
          no org context. The bounce-blocklist pre-check falls through
          to platform-wide rows.
        - Reset URL appears in both the HTML and plain-text bodies so
          the user can click through regardless of mail client.
        - Subject mentions the reset / password.
        - No attachments.
        - The caller's session is passed through directly (no call to
          ``async_session_factory``).

        Validates: Requirements 8.1, 22.2, 22.3
        """
        from app.modules.auth.service import _send_password_reset_email

        caller_session = AsyncMock()
        org_id = uuid.uuid4()
        token = "abc123def456"
        email = "user@example.com"

        send_email_stub = AsyncMock(
            return_value=SendResult(
                success=True,
                provider_key="brevo",
                transport="rest_api",
                message_id="<msg-1@example>",
                error=None,
                attempts=[
                    EmailAttempt(
                        provider_key="brevo",
                        transport="rest_api",
                        success=True,
                        message_id="<msg-1@example>",
                    )
                ],
            )
        )

        # Sentinel factory — must NOT be called when caller provides
        # a session.
        factory = MagicMock(side_effect=AssertionError(
            "async_session_factory must not be called when caller "
            "passes db"
        ))

        with patch(
            "app.core.database.async_session_factory",
            new=factory,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await _send_password_reset_email(
                email,
                token,
                db=caller_session,
                org_id=org_id,
                org_name="Acme Workshop",
            )

        # async_session_factory MUST NOT be called — the caller passed
        # a session and the function used it directly.
        factory.assert_not_called()

        # Exactly one dispatch.
        send_email_stub.assert_awaited_once()
        args, kwargs = send_email_stub.await_args

        # First positional arg is the caller's session.
        assert args[0] is caller_session

        # Second positional arg is the EmailMessage.
        message = args[1] if len(args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design row C3: account recovery is org-agnostic.
        assert message.org_id is None

        # Recipient on the message matches the function arg.
        assert message.to_email == email

        # Subject mentions the password / reset (with the org name).
        assert "Acme Workshop" in message.subject
        assert "reset" in message.subject.lower() or "password" in message.subject.lower()

        # Both bodies present and contain the reset URL with the token.
        expected_url_fragment = f"/reset-password?token={token}"
        assert message.html_body
        assert message.text_body
        assert expected_url_fragment in message.html_body
        assert expected_url_fragment in message.text_body

        # No attachments — password reset is link only.
        assert message.attachments == []

        # No org_sender_name override — the password-reset path does
        # not pass an org-branded From header (preserved from the
        # Phase 0.5 raw-smtplib version, which used the provider's
        # configured from_name).
        assert (
            "org_sender_name" not in kwargs
            or kwargs["org_sender_name"] is None
        )

    @pytest.mark.asyncio
    async def test_no_providers_logs_warning_and_does_not_crash(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When ``send_email`` returns ``attempts=[]`` (no active
        providers configured), the function returns ``None`` without
        raising and logs a warning that references the recipient.

        Validates: Requirements 8.1, 22.3
        """
        from app.modules.auth.service import _send_password_reset_email

        caller_session = AsyncMock()
        token = "abc123def456"
        email = "user@example.com"

        send_email_stub = AsyncMock(
            return_value=SendResult(
                success=False,
                provider_key=None,
                transport=None,
                message_id=None,
                error="No active email providers configured",
                attempts=[],
            )
        )

        with caplog.at_level(
            logging.WARNING, logger="app.modules.auth.service"
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _send_password_reset_email(
                email,
                token,
                db=caller_session,
                org_id=uuid.uuid4(),
                org_name="Acme Workshop",
            )

        # Function returns None, no crash.
        assert result is None

        # send_email was awaited once even though there were no
        # providers — the unified sender owns the empty-set check.
        send_email_stub.assert_awaited_once()

        # A warning was logged mentioning the recipient so an ops
        # follow-up is possible without leaking the token.
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and email in r.getMessage()
        ]
        assert warning_records, (
            "Expected a WARNING log line referencing the recipient "
            "when no email providers are active, got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
        )

    @pytest.mark.asyncio
    async def test_all_providers_fail_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ):
        """When every provider returns a soft failure, the function
        still returns ``None`` cleanly. The
        ``request_password_reset`` endpoint always returns the same
        generic "if your email is registered…" response either way,
        so a delivery error must not propagate up the stack.

        Validates: Requirement 22.3
        """
        from app.modules.auth.service import _send_password_reset_email

        caller_session = AsyncMock()
        token = "abc123def456"
        email = "user@example.com"

        send_email_stub = AsyncMock(
            return_value=SendResult(
                success=False,
                provider_key=None,
                transport=None,
                message_id=None,
                error="all providers returned 401",
                attempts=[
                    EmailAttempt(
                        provider_key="brevo",
                        transport="rest_api",
                        success=False,
                        failure_kind=FailureKind.SOFT_AUTH,
                        error="brevo REST 401",
                    ),
                    EmailAttempt(
                        provider_key="sendgrid",
                        transport="rest_api",
                        success=False,
                        failure_kind=FailureKind.SOFT_AUTH,
                        error="sendgrid REST 401",
                    ),
                ],
            )
        )

        with caplog.at_level(
            logging.WARNING, logger="app.modules.auth.service"
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _send_password_reset_email(
                email,
                token,
                db=caller_session,
                org_id=uuid.uuid4(),
                org_name="Acme Workshop",
            )

        assert result is None
        send_email_stub.assert_awaited_once()

        # Warning log line references the recipient (no token leak).
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and email in r.getMessage()
        ]
        assert warning_records, (
            "Expected a WARNING log line on total provider failure"
        )

    @pytest.mark.asyncio
    async def test_failover_chain(self) -> None:
        """3-provider chain: 2 of 3 providers fail, third succeeds.

        Drives the full ``send_email`` loop end-to-end (no mocking of
        the loop itself) — only ``dispatch_one_provider``,
        ``_load_active_providers``, and ``_check_bounce_blocklist`` are
        stubbed so no DB / network is required.

        Scenario:

        - Provider 1 (brevo, priority 1)    → REST 401 → SOFT_AUTH
        - Provider 2 (sendgrid, priority 2) → connection error → SOFT_PROVIDER
        - Provider 3 (custom_smtp, priority 3) → success

        Both soft failures must let the loop continue, and the third
        provider's successful attempt must drive
        ``_send_password_reset_email`` to return cleanly. The aggregate
        ``SendResult`` should reflect provider 3 as the winner.

        Validates: Requirements 8.1, 22.2, 22.3
        """
        from app.modules.auth.service import _send_password_reset_email

        provider1 = _make_provider("brevo", priority=1)
        provider2 = _make_provider("sendgrid", priority=2)
        provider3 = _make_provider("custom_smtp", priority=3)

        # Canned attempts the patched dispatch_one_provider returns in
        # priority order. Mirrors the 3-provider failover scenario in
        # ``tests/test_email_sender_failover.py`` (task 1.11).
        attempt1 = EmailAttempt(
            provider_key="brevo",
            transport="rest_api",
            success=False,
            error="brevo REST 401: invalid api key",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=12,
        )
        attempt2 = EmailAttempt(
            provider_key="sendgrid",
            transport="rest_api",
            success=False,
            error="ConnectError: network down",
            failure_kind=FailureKind.SOFT_PROVIDER,
            duration_ms=15,
        )
        attempt3 = EmailAttempt(
            provider_key="custom_smtp",
            transport="smtp",
            success=True,
            error=None,
            failure_kind=None,
            duration_ms=42,
            message_id="<reset-success@example>",
        )

        dispatch_stub = AsyncMock(
            side_effect=[attempt1, attempt2, attempt3]
        )
        load_providers_stub = AsyncMock(
            return_value=[provider1, provider2, provider3]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        caller_session = AsyncMock()
        token = "tok_failover_3p_xyz"
        email = "user@example.com"

        with patch(
            "app.integrations.email_sender.dispatch_one_provider",
            new=dispatch_stub,
        ), patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _send_password_reset_email(
                email,
                token,
                db=caller_session,
                org_id=uuid.uuid4(),
                org_name="Acme Workshop",
            )

        # 1. Best-effort contract: returns None, does NOT raise — even
        #    on failover the function must not propagate exceptions
        #    back to the password-reset endpoint.
        assert result is None

        # 2. Exactly three dispatches — the loop stopped after the
        #    success rather than continuing on to a phantom fourth
        #    attempt.
        assert dispatch_stub.await_count == 3

        # 3. Provider chain was loaded against the caller's session
        #    (the function used the caller's db, not a freshly opened
        #    session — the production execution path).
        load_providers_stub.assert_awaited_once()
        load_providers_stub.assert_awaited_with(caller_session)

        # 4. Bounce-blocklist pre-check fired exactly once and used
        #    the correct recipient. Per design row C3, the message
        #    has ``org_id=None`` so the blocklist call is also
        #    org-agnostic.
        blocklist_stub.assert_awaited_once()
        _bl_args, bl_kwargs = blocklist_stub.await_args
        assert bl_kwargs.get("org_id") is None
        assert bl_kwargs.get("email_address") == email
