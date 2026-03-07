"""Integration tests for Notifications — email via Brevo/SendGrid, SMS via Twilio, delivery tracking, bounce handling, retry logic.

Tests the full flow from integration clients and Celery tasks through to mocked API responses.
All Brevo/SendGrid/Twilio API calls are mocked — no real API calls are made.

Requirements: 33.1-33.3, 36.1-36.6, 37.1-37.3
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

from app.integrations.brevo import (
    EmailClient,
    EmailMessage,
    SendResult,
    SmtpConfig,
    send_org_email,
)
from app.integrations.twilio_sms import (
    SMS_CHAR_LIMIT,
    SmsClient,
    SmsMessage,
    SmsSendResult,
    TwilioConfig,
    send_org_sms,
)
from app.tasks.notifications import (
    MAX_RETRIES,
    RETRY_DELAYS,
    _get_retry_delay,
    send_email_task,
    send_sms_task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _brevo_config(**overrides) -> SmtpConfig:
    defaults = dict(
        provider="brevo",
        api_key="xkeysib-test-key",
        from_email="noreply@workshoppro.nz",
        from_name="WorkshopPro NZ",
        reply_to="support@workshoppro.nz",
    )
    defaults.update(overrides)
    return SmtpConfig(**defaults)


def _sendgrid_config(**overrides) -> SmtpConfig:
    defaults = dict(
        provider="sendgrid",
        api_key="SG.test-key",
        from_email="noreply@workshoppro.nz",
        from_name="WorkshopPro NZ",
        reply_to="support@workshoppro.nz",
    )
    defaults.update(overrides)
    return SmtpConfig(**defaults)


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
# 1. Email Sending via Brevo API (Req 33.1, 33.2, 33.3)
# ===========================================================================


class TestBrevoEmailSending:
    """Integration tests for email sending via Brevo transactional API.

    Tests payload construction, API call, response handling, and org-level overrides.
    Requirements: 33.1, 33.2, 33.3
    """

    @pytest.mark.asyncio
    async def test_brevo_send_constructs_correct_payload(self):
        """Brevo send constructs the correct API payload with sender, recipient, subject, and body."""
        config = _brevo_config()
        client = EmailClient(config)

        mock_http, _ = _mock_httpx_client({"messageId": "<brevo-msg-001>"})

        msg = EmailMessage(
            to_email="customer@example.com",
            to_name="Jane Doe",
            subject="Invoice INV-0042",
            html_body="<h1>Your invoice</h1>",
            text_body="Your invoice is ready.",
        )

        with patch("app.integrations.brevo.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is True
        assert result.message_id == "<brevo-msg-001>"
        assert result.provider == "brevo"

        # Verify API call details
        call_kwargs = mock_http.post.call_args
        assert call_kwargs[0][0] == "https://api.brevo.com/v3/smtp/email"
        payload = call_kwargs[1]["json"]
        assert payload["sender"]["email"] == "noreply@workshoppro.nz"
        assert payload["sender"]["name"] == "WorkshopPro NZ"
        assert payload["to"][0]["email"] == "customer@example.com"
        assert payload["subject"] == "Invoice INV-0042"
        assert payload["htmlContent"] == "<h1>Your invoice</h1>"
        assert payload["replyTo"]["email"] == "support@workshoppro.nz"

        # Verify API key header
        headers = call_kwargs[1]["headers"]
        assert headers["api-key"] == "xkeysib-test-key"

    @pytest.mark.asyncio
    async def test_brevo_send_with_org_sender_override(self):
        """Org emails use global infrastructure but display org sender name and reply-to (Req 33.3)."""
        config = _brevo_config()
        client = EmailClient(config)

        mock_http, _ = _mock_httpx_client({"messageId": "<brevo-org-001>"})

        msg = EmailMessage(
            to_email="customer@example.com",
            subject="Invoice from My Workshop",
            html_body="<p>Hello</p>",
            from_name="My Workshop Ltd",
            reply_to="billing@myworkshop.nz",
        )

        with patch("app.integrations.brevo.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is True
        payload = mock_http.post.call_args[1]["json"]
        assert payload["sender"]["name"] == "My Workshop Ltd"
        assert payload["replyTo"]["email"] == "billing@myworkshop.nz"

    @pytest.mark.asyncio
    async def test_brevo_api_error_returns_failure(self):
        """Brevo API error (non-200) returns SendResult with success=False."""
        config = _brevo_config()
        client = EmailClient(config)

        mock_http, mock_resp = _mock_httpx_client({}, status_code=403)
        mock_resp.text = "Forbidden"

        msg = EmailMessage(to_email="test@example.com", subject="Test")

        with patch("app.integrations.brevo.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is False
        assert "403" in result.error
        assert result.provider == "brevo"

    @pytest.mark.asyncio
    async def test_brevo_network_exception_returns_failure(self):
        """Network exception during Brevo send returns SendResult with error."""
        config = _brevo_config()
        client = EmailClient(config)

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=ConnectionError("DNS resolution failed"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        msg = EmailMessage(to_email="test@example.com", subject="Test")

        with patch("app.integrations.brevo.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is False
        assert "DNS resolution failed" in result.error


# ===========================================================================
# 2. Email Sending via SendGrid API (Req 33.1)
# ===========================================================================


class TestSendGridEmailSending:
    """Integration tests for email sending via SendGrid v3 API.

    Tests payload construction, API call, and response handling.
    Requirements: 33.1
    """

    @pytest.mark.asyncio
    async def test_sendgrid_send_constructs_correct_payload(self):
        """SendGrid send constructs the correct v3 mail/send payload."""
        config = _sendgrid_config()
        client = EmailClient(config)

        mock_http, mock_resp = _mock_httpx_client({}, status_code=202)
        mock_resp.headers = {"X-Message-Id": "sg-msg-001"}

        msg = EmailMessage(
            to_email="customer@example.com",
            to_name="John Smith",
            subject="Payment Received",
            html_body="<p>Thank you for your payment</p>",
            text_body="Thank you for your payment",
        )

        with patch("app.integrations.brevo.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is True
        assert result.message_id == "sg-msg-001"
        assert result.provider == "sendgrid"

        call_kwargs = mock_http.post.call_args
        assert call_kwargs[0][0] == "https://api.sendgrid.com/v3/mail/send"
        payload = call_kwargs[1]["json"]
        assert payload["from"]["email"] == "noreply@workshoppro.nz"
        assert payload["personalizations"][0]["to"][0]["email"] == "customer@example.com"
        assert payload["subject"] == "Payment Received"
        assert any(c["type"] == "text/html" for c in payload["content"])

        headers = call_kwargs[1]["headers"]
        assert "Bearer SG.test-key" in headers["Authorization"]

    @pytest.mark.asyncio
    async def test_sendgrid_api_error_returns_failure(self):
        """SendGrid API error returns SendResult with success=False."""
        config = _sendgrid_config()
        client = EmailClient(config)

        mock_http, mock_resp = _mock_httpx_client({}, status_code=401)
        mock_resp.text = "Unauthorized"

        msg = EmailMessage(to_email="test@example.com", subject="Test")

        with patch("app.integrations.brevo.httpx.AsyncClient", return_value=mock_http):
            result = await client.send(msg)

        assert result.success is False
        assert "401" in result.error
        assert result.provider == "sendgrid"

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_failure(self):
        """Unknown provider returns SendResult with error."""
        config = SmtpConfig(provider="mailchimp")
        client = EmailClient(config)

        msg = EmailMessage(to_email="test@example.com", subject="Test")
        result = await client.send(msg)

        assert result.success is False
        assert "Unknown provider" in result.error


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
# 6. Org-Level Email Sending (send_org_email) (Req 33.3)
# ===========================================================================


class TestOrgLevelEmailSending:
    """Integration tests for send_org_email — global infra with org overrides.

    Requirements: 33.3
    """

    @pytest.mark.asyncio
    async def test_send_org_email_uses_global_config_with_org_overrides(self):
        """send_org_email loads global SMTP config and applies org sender/reply-to."""
        config = _brevo_config()
        mock_client = AsyncMock()
        mock_client.send = AsyncMock(
            return_value=SendResult(success=True, message_id="org-msg-001", provider="brevo")
        )

        with patch(
            "app.integrations.brevo.get_email_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            result = await send_org_email(
                _mock_db(),
                to_email="customer@example.com",
                to_name="Jane",
                subject="Invoice",
                html_body="<p>Hi</p>",
                org_sender_name="My Workshop",
                org_reply_to="info@myworkshop.nz",
            )

        assert result.success is True
        sent_msg = mock_client.send.call_args[0][0]
        assert sent_msg.from_name == "My Workshop"
        assert sent_msg.reply_to == "info@myworkshop.nz"

    @pytest.mark.asyncio
    async def test_send_org_email_no_config_returns_failure(self):
        """send_org_email returns failure when no SMTP config is stored."""
        with patch(
            "app.integrations.brevo.get_email_client",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await send_org_email(
                _mock_db(),
                to_email="test@example.com",
                subject="Test",
            )

        assert result.success is False
        assert "not configured" in result.error


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
# 8. Notification Retry Logic (Req 37.1, 37.2, 37.3)
# ===========================================================================


class TestNotificationRetryLogic:
    """Integration tests for notification retry with exponential backoff.

    Req 37.1: Queue and dispatch all notifications asynchronously.
    Req 37.2: Retry up to 3 times with exponential backoff.
    Req 37.3: After 3 retries, mark as failed and log in Global Admin error log.
    """

    def test_max_retries_is_three(self):
        """MAX_RETRIES constant is set to 3 (Req 37.2)."""
        assert MAX_RETRIES == 3

    def test_retry_delays_are_exponential_backoff(self):
        """Retry delays follow exponential backoff: 60s, 300s, 900s (Req 37.2)."""
        assert RETRY_DELAYS == (60, 300, 900)

    def test_get_retry_delay_returns_correct_delays(self):
        """_get_retry_delay returns the correct delay for each retry attempt."""
        assert _get_retry_delay(0) == 60
        assert _get_retry_delay(1) == 300
        assert _get_retry_delay(2) == 900
        # Beyond configured delays, returns last value
        assert _get_retry_delay(5) == 900

    def test_email_task_success_returns_result(self):
        """Successful email send returns success result without retry."""
        send_result = {"success": True, "message_id": "msg-001"}

        with patch("app.tasks.notifications._run_async", return_value=send_result):
            # Push a fake request context so self.request.retries works
            send_email_task.push_request(retries=0)
            try:
                result = send_email_task(
                    org_id=str(uuid.uuid4()),
                    log_id=str(uuid.uuid4()),
                    to_email="test@example.com",
                    to_name="Test",
                    subject="Test Subject",
                    html_body="<p>Test</p>",
                    template_type="invoice_issued",
                )
            finally:
                send_email_task.pop_request()

        assert result["success"] is True
        assert result["message_id"] == "msg-001"

    def test_email_task_failure_triggers_retry(self):
        """Failed email send triggers retry with exponential backoff (Req 37.2)."""
        send_result = {"success": False, "error": "Connection timeout"}

        with patch("app.tasks.notifications._run_async", return_value=send_result):
            send_email_task.push_request(retries=0)
            try:
                with pytest.raises(Exception, match="Connection timeout"):
                    send_email_task(
                        org_id=str(uuid.uuid4()),
                        log_id=str(uuid.uuid4()),
                        to_email="test@example.com",
                        template_type="invoice_issued",
                    )
            finally:
                send_email_task.pop_request()

    def test_email_task_max_retries_marks_permanently_failed(self):
        """After MAX_RETRIES, email is marked as permanently failed (Req 37.3)."""
        send_result = {"success": False, "error": "Persistent failure"}
        mark_failed_result = None

        with patch("app.tasks.notifications._run_async", side_effect=[
            send_result,         # _send_email_async fails
            mark_failed_result,  # _mark_permanently_failed
        ]):
            send_email_task.push_request(retries=MAX_RETRIES)
            try:
                result = send_email_task(
                    org_id=str(uuid.uuid4()),
                    log_id=str(uuid.uuid4()),
                    to_email="test@example.com",
                    template_type="payment_overdue",
                )
            finally:
                send_email_task.pop_request()

        assert result["success"] is False
        assert result["permanently_failed"] is True
        assert "Persistent failure" in result["error"]

    def test_sms_task_success_returns_result(self):
        """Successful SMS send returns success result without retry."""
        send_result = {"success": True, "message_sid": "SM_001"}

        with patch("app.tasks.notifications._run_async", return_value=send_result):
            send_sms_task.push_request(retries=0)
            try:
                result = send_sms_task(
                    org_id=str(uuid.uuid4()),
                    log_id=str(uuid.uuid4()),
                    to_number="+6421999888",
                    body="Your invoice is ready",
                    template_type="invoice_issued",
                )
            finally:
                send_sms_task.pop_request()

        assert result["success"] is True
        assert result["message_sid"] == "SM_001"

    def test_sms_task_failure_triggers_retry(self):
        """Failed SMS send triggers retry with exponential backoff (Req 37.2)."""
        send_result = {"success": False, "error": "Twilio timeout"}

        with patch("app.tasks.notifications._run_async", return_value=send_result):
            send_sms_task.push_request(retries=0)
            try:
                with pytest.raises(Exception, match="Twilio timeout"):
                    send_sms_task(
                        org_id=str(uuid.uuid4()),
                        log_id=str(uuid.uuid4()),
                        to_number="+6421999888",
                        body="Test",
                        template_type="invoice_issued",
                    )
            finally:
                send_sms_task.pop_request()

    def test_sms_task_max_retries_marks_permanently_failed(self):
        """After MAX_RETRIES, SMS is marked as permanently failed (Req 37.3)."""
        send_result = {"success": False, "error": "Number unreachable"}
        mark_failed_result = None

        with patch("app.tasks.notifications._run_async", side_effect=[
            send_result,
            mark_failed_result,
        ]):
            send_sms_task.push_request(retries=MAX_RETRIES)
            try:
                result = send_sms_task(
                    org_id=str(uuid.uuid4()),
                    log_id=str(uuid.uuid4()),
                    to_number="+6421999888",
                    body="Test",
                    template_type="wof_expiry",
                )
            finally:
                send_sms_task.pop_request()

        assert result["success"] is False
        assert result["permanently_failed"] is True
        assert "Number unreachable" in result["error"]
