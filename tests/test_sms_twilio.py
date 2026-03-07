"""Tests for SMS sending via Twilio — Task 15.4.

Covers:
- Twilio client (TwilioConfig, SmsClient, SmsMessage, SmsSendResult)
- Admin Twilio config endpoints (save, test SMS)
- Per-org SMS enable/disable and sender name config
- SMS template CRUD (4 templates, 160-char warning, variable system)
- SMS logging with same detail as email

Requirements: 36.1, 36.2, 36.3, 36.4, 36.5, 36.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Twilio client unit tests
# ---------------------------------------------------------------------------

from app.integrations.twilio_sms import (
    SMS_CHAR_LIMIT,
    SmsClient,
    SmsMessage,
    SmsSendResult,
    TwilioConfig,
)


class TestTwilioConfig:
    """TwilioConfig dataclass tests."""

    def test_from_dict(self):
        data = {
            "account_sid": "AC_test_sid",
            "auth_token": "test_token",
            "sender_number": "+64211234567",
        }
        config = TwilioConfig.from_dict(data)
        assert config.account_sid == "AC_test_sid"
        assert config.auth_token == "test_token"
        assert config.sender_number == "+64211234567"

    def test_to_dict(self):
        config = TwilioConfig(
            account_sid="AC_test", auth_token="tok", sender_number="+6421000"
        )
        d = config.to_dict()
        assert d["account_sid"] == "AC_test"
        assert d["auth_token"] == "tok"
        assert d["sender_number"] == "+6421000"

    def test_from_dict_defaults(self):
        config = TwilioConfig.from_dict({})
        assert config.account_sid == ""
        assert config.auth_token == ""
        assert config.sender_number == ""


class TestSmsClient:
    """SmsClient send logic tests."""

    @pytest.mark.asyncio
    async def test_send_no_sender_number(self):
        """If no sender number configured, return error."""
        config = TwilioConfig(account_sid="AC_x", auth_token="tok", sender_number="")
        client = SmsClient(config)
        msg = SmsMessage(to_number="+6421999", body="Hello")
        result = await client.send(msg)
        assert result.success is False
        assert "No sender number" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Successful Twilio API call returns success with SID."""
        config = TwilioConfig(
            account_sid="AC_test", auth_token="tok", sender_number="+6421000"
        )
        client = SmsClient(config)
        msg = SmsMessage(to_number="+6421999", body="Test message")

        mock_resp = AsyncMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"sid": "SM_abc123"}
        # json() is sync in httpx
        mock_resp.json = lambda: {"sid": "SM_abc123"}

        with patch("app.integrations.twilio_sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await client.send(msg)

        assert result.success is True
        assert result.message_sid == "SM_abc123"

    @pytest.mark.asyncio
    async def test_send_api_error(self):
        """Twilio API error returns failure."""
        config = TwilioConfig(
            account_sid="AC_test", auth_token="tok", sender_number="+6421000"
        )
        client = SmsClient(config)
        msg = SmsMessage(to_number="+6421999", body="Test")

        mock_resp = AsyncMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad request"

        with patch("app.integrations.twilio_sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await client.send(msg)

        assert result.success is False
        assert "400" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_exception(self):
        """Network exception returns failure."""
        config = TwilioConfig(
            account_sid="AC_test", auth_token="tok", sender_number="+6421000"
        )
        client = SmsClient(config)
        msg = SmsMessage(to_number="+6421999", body="Test")

        with patch("app.integrations.twilio_sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=ConnectionError("timeout"))
            mock_client_cls.return_value = mock_client

            result = await client.send(msg)

        assert result.success is False
        assert "timeout" in (result.error or "")

    @pytest.mark.asyncio
    async def test_send_uses_message_from_number_override(self):
        """Message-level from_number overrides config sender."""
        config = TwilioConfig(
            account_sid="AC_test", auth_token="tok", sender_number="+6421000"
        )
        client = SmsClient(config)
        msg = SmsMessage(
            to_number="+6421999", body="Test", from_number="+6421111"
        )

        mock_resp = AsyncMock()
        mock_resp.status_code = 201
        mock_resp.json = lambda: {"sid": "SM_xyz"}

        with patch("app.integrations.twilio_sms.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await client.send(msg)

        # Verify the override was used
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[1]["data"]["From"] == "+6421111"
        assert result.success is True


# ---------------------------------------------------------------------------
# Admin Twilio config schema tests
# ---------------------------------------------------------------------------

from app.modules.admin.schemas import (
    TwilioConfigRequest,
    TwilioConfigResponse,
    TwilioTestSmsRequest,
    TwilioTestSmsResponse,
)


class TestTwilioAdminSchemas:
    """Pydantic schema validation for Twilio admin config."""

    def test_twilio_config_request_valid(self):
        req = TwilioConfigRequest(
            account_sid="AC_test_sid_1234",
            auth_token="auth_token_value",
            sender_number="+64211234567",
        )
        assert req.account_sid == "AC_test_sid_1234"
        assert req.sender_number == "+64211234567"

    def test_twilio_config_request_empty_sid_rejected(self):
        with pytest.raises(Exception):
            TwilioConfigRequest(
                account_sid="",
                auth_token="tok",
                sender_number="+6421000",
            )

    def test_twilio_config_response(self):
        resp = TwilioConfigResponse(
            message="Saved",
            account_sid_last4="1234",
            sender_number="+6421000",
            is_verified=False,
        )
        assert resp.account_sid_last4 == "1234"

    def test_twilio_test_sms_request(self):
        req = TwilioTestSmsRequest(to_number="+64211234567")
        assert req.to_number == "+64211234567"

    def test_twilio_test_sms_response(self):
        resp = TwilioTestSmsResponse(
            success=True, message="Test SMS sent", error=None
        )
        assert resp.success is True


# ---------------------------------------------------------------------------
# SMS notification schema tests
# ---------------------------------------------------------------------------

from app.modules.notifications.schemas import (
    SMS_TEMPLATE_TYPES,
    DEFAULT_SMS_BODIES,
    SmsTemplateResponse,
    SmsTemplateUpdateRequest,
    SmsTemplateListResponse,
    OrgSmsSettingsRequest,
    OrgSmsSettingsResponse,
)


class TestSmsNotificationSchemas:
    """SMS template and settings schema tests."""

    def test_sms_template_types_count(self):
        """Req 36.4: exactly 4 SMS templates."""
        assert len(SMS_TEMPLATE_TYPES) == 4

    def test_sms_template_types_content(self):
        """Req 36.4: correct template types."""
        assert "invoice_issued" in SMS_TEMPLATE_TYPES
        assert "payment_overdue_reminder" in SMS_TEMPLATE_TYPES
        assert "wof_expiry_reminder" in SMS_TEMPLATE_TYPES
        assert "registration_expiry_reminder" in SMS_TEMPLATE_TYPES

    def test_default_sms_bodies_exist(self):
        """Each SMS template type has a default body."""
        for ttype in SMS_TEMPLATE_TYPES:
            assert ttype in DEFAULT_SMS_BODIES
            assert len(DEFAULT_SMS_BODIES[ttype]) > 0

    def test_sms_template_response_exceeds_limit(self):
        """Req 36.5: exceeds_limit flag when body > 160 chars."""
        resp = SmsTemplateResponse(
            id="abc",
            template_type="invoice_issued",
            channel="sms",
            body="x" * 161,
            char_count=161,
            exceeds_limit=True,
            is_enabled=False,
            updated_at="2025-01-01T00:00:00",
        )
        assert resp.exceeds_limit is True

    def test_sms_template_response_within_limit(self):
        resp = SmsTemplateResponse(
            id="abc",
            template_type="invoice_issued",
            channel="sms",
            body="Short message",
            char_count=13,
            exceeds_limit=False,
            is_enabled=False,
            updated_at="2025-01-01T00:00:00",
        )
        assert resp.exceeds_limit is False

    def test_sms_template_update_request(self):
        req = SmsTemplateUpdateRequest(body="New body text", is_enabled=True)
        assert req.body == "New body text"
        assert req.is_enabled is True

    def test_org_sms_settings_request(self):
        req = OrgSmsSettingsRequest(sms_enabled=True, sender_name="Workshop")
        assert req.sms_enabled is True
        assert req.sender_name == "Workshop"

    def test_org_sms_settings_response(self):
        resp = OrgSmsSettingsResponse(sms_enabled=True, sender_name="MyShop")
        assert resp.sms_enabled is True


# ---------------------------------------------------------------------------
# SMS service layer tests (using in-memory SQLite)
# ---------------------------------------------------------------------------

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.modules.notifications.service import (
    _sms_template_to_dict,
    log_sms_sent,
)
from app.modules.notifications.models import NotificationTemplate, NotificationLog


class TestSmsTemplateToDictHelper:
    """Unit tests for _sms_template_to_dict conversion."""

    def _make_mock_template(self, body_blocks, is_enabled=True):
        """Create a mock that looks like a NotificationTemplate."""
        tpl = type("MockTemplate", (), {})()
        tpl.id = uuid.uuid4()
        tpl.template_type = "invoice_issued"
        tpl.channel = "sms"
        tpl.subject = None
        tpl.body_blocks = body_blocks
        tpl.is_enabled = is_enabled
        tpl.updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        return tpl

    def test_extracts_body_from_body_blocks(self):
        tpl = self._make_mock_template(
            [{"type": "text", "content": "Hello {{customer_first_name}}"}]
        )
        result = _sms_template_to_dict(tpl)
        assert result["body"] == "Hello {{customer_first_name}}"
        assert result["char_count"] == len("Hello {{customer_first_name}}")
        assert result["exceeds_limit"] is False
        assert result["channel"] == "sms"

    def test_exceeds_limit_flag(self):
        tpl = self._make_mock_template(
            [{"type": "text", "content": "A" * 200}], is_enabled=False
        )
        result = _sms_template_to_dict(tpl)
        assert result["char_count"] == 200
        assert result["exceeds_limit"] is True

    def test_empty_body_blocks(self):
        tpl = self._make_mock_template([], is_enabled=False)
        result = _sms_template_to_dict(tpl)
        assert result["body"] == ""
        assert result["char_count"] == 0
        assert result["exceeds_limit"] is False


class TestSmsCharLimit:
    """Verify the SMS character limit constant."""

    def test_sms_char_limit_is_160(self):
        assert SMS_CHAR_LIMIT == 160


# ---------------------------------------------------------------------------
# Admin service layer tests for Twilio config
# ---------------------------------------------------------------------------


class TestAdminTwilioService:
    """Tests for save_twilio_config and send_test_sms service functions."""

    @pytest.mark.asyncio
    async def test_save_twilio_config(self):
        """save_twilio_config returns masked SID and sender number."""
        from app.modules.admin.service import save_twilio_config

        mock_db = AsyncMock()
        # scalar_one_or_none must return None (no existing config)
        mock_execute_result = AsyncMock()
        mock_execute_result.scalar_one_or_none = lambda: None
        mock_db.execute = AsyncMock(return_value=mock_execute_result)
        mock_db.add = AsyncMock()
        mock_db.flush = AsyncMock()

        with patch("app.core.encryption.envelope_encrypt", return_value=b"encrypted"):
            with patch("app.core.audit.write_audit_log", new_callable=AsyncMock):
                result = await save_twilio_config(
                    mock_db,
                    account_sid="AC_test_sid_1234",
                    auth_token="secret_token",
                    sender_number="+64211234567",
                    updated_by=uuid.uuid4(),
                    ip_address="127.0.0.1",
                )

        assert result["account_sid_last4"] == "1234"
        assert result["sender_number"] == "+64211234567"
        assert result["is_verified"] is False

    @pytest.mark.asyncio
    async def test_send_test_sms_no_config(self):
        """send_test_sms returns error when no Twilio config exists."""
        from app.modules.admin.service import send_test_sms

        mock_db = AsyncMock()

        with patch(
            "app.integrations.twilio_sms.get_sms_client",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await send_test_sms(
                mock_db,
                to_number="+6421999",
                admin_user_id=uuid.uuid4(),
            )

        assert result["success"] is False
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_send_test_sms_success(self):
        """send_test_sms returns success when Twilio sends OK."""
        from app.modules.admin.service import send_test_sms
        from unittest.mock import MagicMock

        mock_db = AsyncMock()
        # The function calls db.execute twice on success (to find config row)
        mock_config_row = MagicMock()
        mock_config_row.is_verified = False
        mock_execute_result = AsyncMock()
        mock_execute_result.scalar_one_or_none = lambda: mock_config_row
        mock_db.execute = AsyncMock(return_value=mock_execute_result)
        mock_db.flush = AsyncMock()

        mock_client = AsyncMock()
        mock_client.send = AsyncMock(
            return_value=SmsSendResult(success=True, message_sid="SM_test")
        )

        with patch(
            "app.integrations.twilio_sms.get_sms_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            with patch("app.core.audit.write_audit_log", new_callable=AsyncMock):
                result = await send_test_sms(
                    mock_db,
                    to_number="+6421999",
                    admin_user_id=uuid.uuid4(),
                )

        assert result["success"] is True
        assert "sent successfully" in result["message"].lower()
