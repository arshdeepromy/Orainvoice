"""Integration tests for Notifications — SMS via Twilio, delivery tracking, bounce handling.

Tests the full flow from integration clients and async dispatch tasks through
to mocked API responses. All Twilio API calls are mocked — no real API calls
are made.

The original Brevo/SendGrid email-sending integration tests in this file
were retired in Phase 9 of the email-provider-unification spec
(task 10.2 / Requirement 23.2): the legacy ``EmailClient`` /
``SmtpConfig`` / ``send_org_email`` / ``get_email_client`` shims they
exercised no longer exist. Equivalent coverage of the unified path
lives in ``tests/test_email_sender_dispatch.py``,
``tests/test_email_sender_failover.py`` and
``tests/test_send_email_task_integration.py``.

The legacy notification-retry integration tests were retired in the same
spec (task 10.4 / Requirement 23.1): they exercised the dead
``MAX_RETRIES`` / ``RETRY_DELAYS`` / ``_get_retry_delay`` constants in
``app/tasks/notifications.py`` (no longer present — provider failover in
the unified sender replaces application-level retries). The DB-backed
notification retry path is now exercised in
``tests/test_scheduled_tasks.py``.

Requirements: 36.1-36.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.integrations.twilio_sms import (
    SMS_CHAR_LIMIT,
    SmsClient,
    SmsMessage,
    SmsSendResult,
    TwilioConfig,
    send_org_sms,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _twilio_config(**overrides) -> TwilioConfig:
    defaults = dict(
        account_sid="ACtest123456",
        auth_token="auth_token_test",
        sender_number="+6421000000",
    )
    defaults.update(overrides)
    return TwilioConfig(**defaults)


def _mock_httpx_client(response_json, status_code=200, headers=None):
    """Create a mock httpx.AsyncClient context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_json
    mock_response.text = str(response_json)
    mock_response.headers = headers or {}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, mock_response


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


# ===========================================================================
# 1. (Removed in Phase 9 — task 10.2 / Requirement 23.2)
#
# The Brevo and SendGrid email-sending integration tests that lived here
# exercised the legacy ``EmailClient`` / ``SmtpConfig`` shims in
# ``app/integrations/brevo.py``. Those shims have been deleted; equivalent
# coverage of the unified send path now lives in
# ``tests/test_email_sender_dispatch.py`` (provider dispatch matrix) and
# ``tests/test_email_sender_failover.py`` (priority-ordered failover).
# ===========================================================================


# ===========================================================================
# 3. SMS Sending via Twilio (Req 36.1, 36.3, 36.5, 36.6)
# ===========================================================================


class TestTwilioSmsSending:
    """Integration tests for SMS sending via Twilio REST API.

    Tests message construction, API call, org-level overrides, and char limit warning.
    Requirements: 36.1, 36.3, 36.5, 36.6
    """

    @pytest.mark.asyncio
    async def test_twilio_send_constructs_correct_api_call(self):
        """Twilio send calls the correct Messages.json endpoint with auth and payload."""
        config = _twilio_config()
        client = SmsClient(config)

        mock_http, _ = _mock_httpx_client({"sid": "SM_test_001", "status": "queued"})

        msg = SmsMessage(to_number="+6421999888", body="Your invoice INV-0042 is ready.")

        with patch("app.integrations.twilio_sms.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is True
        assert result.message_sid == "SM_test_001"

        call_kwargs = mock_http.post.call_args
        url = call_kwargs[0][0]
        assert "ACtest123456" in url
        assert "Messages.json" in url

        data = call_kwargs[1]["data"]
        assert data["To"] == "+6421999888"
        assert data["From"] == "+6421000000"
        assert "INV-0042" in data["Body"]

        # Verify basic auth
        auth = call_kwargs[1]["auth"]
        assert auth == ("ACtest123456", "auth_token_test")

    @pytest.mark.asyncio
    async def test_twilio_send_with_org_sender_override(self):
        """Org SMS uses global Twilio but overrides sender number (Req 36.3)."""
        config = _twilio_config()
        client = SmsClient(config)

        mock_http, _ = _mock_httpx_client({"sid": "SM_org_001"})

        msg = SmsMessage(
            to_number="+6421999888",
            body="Hello from My Workshop",
            from_number="+6421111111",
        )

        with patch("app.integrations.twilio_sms.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is True
        data = mock_http.post.call_args[1]["data"]
        assert data["From"] == "+6421111111"

    @pytest.mark.asyncio
    async def test_twilio_api_error_returns_failure(self):
        """Twilio API error returns SmsSendResult with success=False."""
        config = _twilio_config()
        client = SmsClient(config)

        mock_http, mock_resp = _mock_httpx_client({}, status_code=400)
        mock_resp.text = "Invalid phone number"

        msg = SmsMessage(to_number="invalid", body="Test")

        with patch("app.integrations.twilio_sms.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is False
        assert "400" in result.error

    @pytest.mark.asyncio
    async def test_twilio_no_sender_number_returns_failure(self):
        """Missing sender number returns failure without making API call."""
        config = TwilioConfig(account_sid="AC123", auth_token="tok", sender_number="")
        client = SmsClient(config)

        msg = SmsMessage(to_number="+6421999888", body="Test")
        result = await client.send(msg)

        assert result.success is False
        assert "No sender number" in result.error

    def test_sms_char_limit_constant(self):
        """SMS_CHAR_LIMIT is set to 160 for character limit warnings (Req 36.5)."""
        assert SMS_CHAR_LIMIT == 160

    def test_sms_body_exceeds_char_limit_detection(self):
        """Bodies exceeding 160 chars can be detected for warning (Req 36.5)."""
        short_body = "Your WOF expires soon."
        long_body = "A" * 161

        assert len(short_body) <= SMS_CHAR_LIMIT
        assert len(long_body) > SMS_CHAR_LIMIT


# ===========================================================================
# 4. Delivery Status Tracking (Req 35.1, 35.2)
# ===========================================================================


class TestDeliveryStatusTracking:
    """Integration tests for notification delivery status tracking.

    Tests status transitions: queued → sent → delivered/bounced/opened.
    Requirements: 35.1, 35.2
    """

    @pytest.mark.asyncio
    async def test_update_log_status_to_sent(self):
        """update_log_status transitions a log entry from queued to sent."""
        from app.modules.notifications.service import update_log_status
        from app.modules.notifications.models import NotificationLog

        mock_entry = MagicMock(spec=NotificationLog)
        mock_entry.id = uuid.uuid4()
        mock_entry.status = "queued"
        mock_entry.sent_at = None
        mock_entry.error_message = None

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_entry
        db.execute = AsyncMock(return_value=mock_result)
        db.refresh = AsyncMock()

        now = datetime.now(timezone.utc)
        await update_log_status(db, log_id=mock_entry.id, status="sent", sent_at=now)

        assert mock_entry.status == "sent"
        assert mock_entry.sent_at == now

    @pytest.mark.asyncio
    async def test_update_log_status_to_delivered(self):
        """update_log_status transitions a log entry to delivered."""
        from app.modules.notifications.service import update_log_status
        from app.modules.notifications.models import NotificationLog

        mock_entry = MagicMock(spec=NotificationLog)
        mock_entry.id = uuid.uuid4()
        mock_entry.status = "sent"

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_entry
        db.execute = AsyncMock(return_value=mock_result)
        db.refresh = AsyncMock()

        await update_log_status(db, log_id=mock_entry.id, status="delivered")

        assert mock_entry.status == "delivered"

    @pytest.mark.asyncio
    async def test_update_log_status_to_bounced(self):
        """update_log_status transitions a log entry to bounced with error message."""
        from app.modules.notifications.service import update_log_status
        from app.modules.notifications.models import NotificationLog

        mock_entry = MagicMock(spec=NotificationLog)
        mock_entry.id = uuid.uuid4()
        mock_entry.status = "sent"
        mock_entry.error_message = None

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_entry
        db.execute = AsyncMock(return_value=mock_result)
        db.refresh = AsyncMock()

        await update_log_status(
            db, log_id=mock_entry.id, status="bounced",
            error_message="550 Mailbox not found",
        )

        assert mock_entry.status == "bounced"
        assert mock_entry.error_message == "550 Mailbox not found"

    @pytest.mark.asyncio
    async def test_update_log_status_nonexistent_returns_none(self):
        """update_log_status returns None for a nonexistent log entry."""
        from app.modules.notifications.service import update_log_status

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_log_status(db, log_id=uuid.uuid4(), status="sent")
        assert result is None


# ===========================================================================
# 5. Bounce Handling (Req 35.3)
# ===========================================================================


class TestBounceHandling:
    """Integration tests for bounce handling — flagging bounced emails on customer records.

    Requirements: 35.3
    """

    @pytest.mark.asyncio
    async def test_flag_bounced_email_updates_customer_record(self):
        """flag_bounced_email_on_customer sets email_bounced=True on matching customers."""
        from app.modules.notifications.service import flag_bounced_email_on_customer

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute = AsyncMock(return_value=mock_result)

        org_id = uuid.uuid4()
        count = await flag_bounced_email_on_customer(
            db, org_id=org_id, email_address="bounced@example.com"
        )

        assert count == 1
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_flag_bounced_email_no_matching_customer(self):
        """flag_bounced_email_on_customer returns 0 when no customer matches."""
        from app.modules.notifications.service import flag_bounced_email_on_customer

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.rowcount = 0
        db.execute = AsyncMock(return_value=mock_result)

        count = await flag_bounced_email_on_customer(
            db, org_id=uuid.uuid4(), email_address="unknown@example.com"
        )

        assert count == 0

    @pytest.mark.asyncio
    async def test_flag_bounced_email_multiple_customers(self):
        """flag_bounced_email_on_customer can flag multiple customers with same email."""
        from app.modules.notifications.service import flag_bounced_email_on_customer

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        db.execute = AsyncMock(return_value=mock_result)

        count = await flag_bounced_email_on_customer(
            db, org_id=uuid.uuid4(), email_address="shared@example.com"
        )

        assert count == 3


# ===========================================================================
# 6. (Removed in Phase 9 — task 10.2 / Requirement 23.2)
#
# The ``send_org_email`` shim was deleted. The unified send path
# (``app.integrations.email_sender.send_email``) is exercised end-to-end
# through ``send_email_task`` in ``tests/test_send_email_task_integration.py``;
# the per-org-override behaviour the original tests asserted is covered
# by ``tests/test_email_sender_overrides.py``.
# ===========================================================================


# ===========================================================================
# 7. Org-Level SMS Sending (send_org_sms) (Req 36.3)
# ===========================================================================


class TestOrgLevelSmsSending:
    """Integration tests for send_org_sms — global Twilio with org overrides.

    Requirements: 36.3
    """

    @pytest.mark.asyncio
    async def test_send_org_sms_uses_global_config_with_org_override(self):
        """send_org_sms loads global Twilio config and applies org sender number."""
        mock_client = AsyncMock()
        mock_client.send = AsyncMock(
            return_value=SmsSendResult(success=True, message_sid="SM_org_sms_001")
        )

        with patch(
            "app.integrations.twilio_sms.get_sms_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await send_org_sms(
                _mock_db(),
                to_number="+6421999888",
                body="Your WOF expires soon",
                org_sender_number="+6421222333",
            )

        assert result.success is True
        sent_msg = mock_client.send.call_args[0][0]
        assert sent_msg.from_number == "+6421222333"

    @pytest.mark.asyncio
    async def test_send_org_sms_no_config_returns_failure(self):
        """send_org_sms returns failure when no Twilio config is stored."""
        with patch(
            "app.integrations.twilio_sms.get_sms_client",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await send_org_sms(
                _mock_db(),
                to_number="+6421999888",
                body="Test",
            )

        assert result.success is False
        assert "not configured" in result.error


# ===========================================================================
# 8. (Removed in Phase 9 — task 10.4 / Requirement 23.1)
#
# The legacy notification-retry tests asserted on ``MAX_RETRIES``,
# ``RETRY_DELAYS`` and ``_get_retry_delay`` from
# ``app.tasks.notifications``. Those constants were dead code post-
# Phase 2: the unified email sender's provider failover replaces
# application-level retries (a transient failure tries the next
# provider rather than retrying the same provider after a delay).
# Equivalent coverage of the new failover-based path lives in
# ``tests/test_email_sender_failover.py`` and
# ``tests/test_send_email_task_integration.py``. The remaining DB-
# backed retry path (rows in ``notification_log`` with
# ``status='queued'`` and ``retry_count > 0``) is owned by
# ``app.tasks.scheduled`` and is exercised in
# ``tests/test_scheduled_tasks.py``.
# ===========================================================================
