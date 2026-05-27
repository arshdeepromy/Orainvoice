"""Unit tests for ``_send_password_reset_email`` (Phase 0.5 hotfix).

Covers task 0.5.2 of the email-provider-unification spec:

  - Success path: with one active ``EmailProvider`` configured, the
    function builds a MIME message containing the reset URL and calls
    ``smtplib.SMTP.sendmail`` exactly once.
  - No-providers path: with the active-provider query returning ``[]``,
    the function returns ``None`` without raising and emits a warning
    log line. ``sendmail`` is never called.

The unified sender refactor in Phase 4 will replace this raw
``smtplib`` loop with a single ``send_email`` call. Until then this test
guards the security-hotfix code path so a regression is caught at the
test boundary.

Validates: Requirements 8.1, 22.1
"""

from __future__ import annotations

import logging
import uuid
from email import message_from_string
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_email_provider() -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row (raw SMTP transport)."""
    provider = MagicMock()
    provider.provider_key = "smtp-test"
    provider.smtp_host = "smtp.example.com"
    provider.smtp_port = 587
    provider.smtp_encryption = "tls"
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {
        "from_email": "noreply@example.com",
        "from_name": "OraInvoice",
    }
    provider.priority = 1
    return provider


class _FakeSMTP:
    """In-process replacement for ``smtplib.SMTP``.

    Captures the most recent ``sendmail`` arguments on class-level
    attributes so individual tests can inspect the resulting MIME
    message without any network activity. ``sendmail_call_count`` lets
    a test assert "called exactly once".
    """

    last_from: str | None = None
    last_to: str | None = None
    last_message: str | None = None
    sendmail_call_count: int = 0

    def __init__(self, host, port, timeout=None):  # noqa: D401
        self.host = host
        self.port = port

    def starttls(self):
        return None

    def login(self, username, password):
        return None

    def sendmail(self, from_email, to_email, message_str):
        type(self).last_from = from_email
        type(self).last_to = to_email
        type(self).last_message = message_str
        type(self).sendmail_call_count += 1

    def quit(self):
        return None

    @classmethod
    def reset(cls) -> None:
        cls.last_from = None
        cls.last_to = None
        cls.last_message = None
        cls.sendmail_call_count = 0


def _extract_bodies(raw_message: str) -> tuple[str, str, str]:
    """Pull subject, plain-text body and HTML body from a sent MIME message."""
    msg = message_from_string(raw_message)
    subject = msg["Subject"] or ""
    text_body = ""
    html_body = ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/plain" and not text_body:
            payload = part.get_payload(decode=True)
            text_body = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )
        elif ctype == "text/html" and not html_body:
            payload = part.get_payload(decode=True)
            html_body = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )
    return subject, text_body, html_body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSendPasswordResetEmail:
    """Phase 0.5 hotfix — confirm the password reset email is dispatched."""

    @pytest.mark.asyncio
    async def test_success_path_calls_sendmail_once_with_reset_url(self):
        """With an active provider, the function MIME-builds the message
        and calls ``sendmail`` exactly once. Subject and bodies must
        reference the reset URL.

        Validates: Requirements 8.1, 22.1
        """
        from app.modules.auth.service import _send_password_reset_email

        provider = _make_email_provider()
        db = AsyncMock()
        org_id = uuid.uuid4()
        token = "abc123def456"
        email = "user@example.com"

        _FakeSMTP.reset()

        with patch(
            "app.modules.auth.service._get_email_providers",
            new_callable=AsyncMock,
            return_value=[provider],
        ) as mock_get_providers, patch(
            "app.core.encryption.envelope_decrypt_str",
            return_value='{"username": "u", "password": "p"}',
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch("smtplib.SMTP", _FakeSMTP):
            await _send_password_reset_email(
                email,
                token,
                db=db,
                org_id=org_id,
                org_name="Acme Workshop",
            )

        # Provider lookup happened once (db was provided, so no
        # async_session_factory branch).
        mock_get_providers.assert_awaited_once_with(db)

        # sendmail called exactly once.
        assert _FakeSMTP.sendmail_call_count == 1
        assert _FakeSMTP.last_from == "noreply@example.com"
        assert _FakeSMTP.last_to == email
        assert _FakeSMTP.last_message is not None

        # The reset URL is built from frontend_base_url (or "http://localhost"
        # fallback) + "/reset-password?token=<token>". Both bodies must
        # reference the token so the user can actually click through.
        subject, text_body, html_body = _extract_bodies(_FakeSMTP.last_message)
        assert "Acme Workshop" in subject
        assert "password" in subject.lower() or "reset" in subject.lower()
        assert f"token={token}" in text_body
        assert "/reset-password" in text_body
        assert f"token={token}" in html_body
        assert "/reset-password" in html_body

    @pytest.mark.asyncio
    async def test_no_providers_logs_warning_and_does_not_crash(
        self, caplog: pytest.LogCaptureFixture
    ):
        """With no active providers, the function returns ``None``
        without raising. ``sendmail`` is never invoked and a warning
        log line is emitted so ops sees the misconfiguration.

        Validates: Requirements 8.1, 22.1
        """
        from app.modules.auth.service import _send_password_reset_email

        db = AsyncMock()
        token = "abc123def456"
        email = "user@example.com"

        _FakeSMTP.reset()

        with caplog.at_level(logging.WARNING, logger="app.modules.auth.service"), patch(
            "app.modules.auth.service._get_email_providers",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch("smtplib.SMTP", _FakeSMTP):
            result = await _send_password_reset_email(
                email,
                token,
                db=db,
                org_id=uuid.uuid4(),
                org_name="Acme Workshop",
            )

        # Function returns None, no crash.
        assert result is None

        # No SMTP traffic.
        assert _FakeSMTP.sendmail_call_count == 0
        assert _FakeSMTP.last_message is None

        # A warning was logged mentioning the recipient so an ops
        # follow-up is possible without leaking the token.
        warning_records = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and email in r.getMessage()
        ]
        assert warning_records, (
            "Expected a WARNING log line referencing the recipient when "
            "no email providers are active, got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
        )
