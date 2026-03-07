"""Unit tests for Task 15.1 — Email sending infrastructure.

Tests cover:
  - SmtpConfig dataclass creation and serialisation
  - EmailClient provider dispatch (brevo, sendgrid, smtp, unknown)
  - Org-level email overrides (sender name, reply-to)
  - SMTP config save/update via admin service
  - Test email sending via admin service
  - Schema validation for SmtpConfigRequest
  - Admin endpoint routing

Requirements: 33.1, 33.2, 33.3
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.integrations.brevo import (
    EmailClient,
    EmailMessage,
    SendResult,
    SmtpConfig,
    send_org_email,
)
from app.modules.admin.schemas import (
    SmtpConfigRequest,
    SmtpConfigResponse,
    SmtpTestEmailResponse,
)
from app.modules.admin.service import (
    save_smtp_config,
    send_test_email,
)


# ---------------------------------------------------------------------------
# SmtpConfig tests
# ---------------------------------------------------------------------------


class TestSmtpConfig:
    def test_from_dict_defaults(self):
        config = SmtpConfig.from_dict({})
        assert config.provider == "smtp"
        assert config.port == 587
        assert config.api_key == ""
        assert config.from_email == ""

    def test_from_dict_full(self):
        data = {
            "provider": "brevo",
            "api_key": "xkeysib-abc123",
            "host": "",
            "port": 587,
            "domain": "workshoppro.nz",
            "from_email": "noreply@workshoppro.nz",
            "from_name": "WorkshopPro NZ",
            "reply_to": "support@workshoppro.nz",
        }
        config = SmtpConfig.from_dict(data)
        assert config.provider == "brevo"
        assert config.api_key == "xkeysib-abc123"
        assert config.domain == "workshoppro.nz"
        assert config.from_name == "WorkshopPro NZ"

    def test_to_dict_roundtrip(self):
        original = {
            "provider": "sendgrid",
            "api_key": "SG.test",
            "host": "",
            "port": 587,
            "username": "",
            "password": "",
            "domain": "example.com",
            "from_email": "no-reply@example.com",
            "from_name": "Test",
            "reply_to": "reply@example.com",
        }
        config = SmtpConfig.from_dict(original)
        result = config.to_dict()
        assert result == original


# ---------------------------------------------------------------------------
# EmailClient tests
# ---------------------------------------------------------------------------


class TestEmailClient:
    def _make_config(self, provider: str = "brevo") -> SmtpConfig:
        return SmtpConfig(
            provider=provider,
            api_key="test-key",
            domain="test.com",
            from_email="noreply@test.com",
            from_name="Test Platform",
            reply_to="reply@test.com",
        )

    def _make_message(self, **overrides) -> EmailMessage:
        defaults = {
            "to_email": "user@example.com",
            "to_name": "Test User",
            "subject": "Test Subject",
            "html_body": "<p>Hello</p>",
            "text_body": "Hello",
        }
        defaults.update(overrides)
        return EmailMessage(**defaults)

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_error(self):
        config = self._make_config(provider="unknown_provider")
        client = EmailClient(config)
        result = await client.send(self._make_message())
        assert result.success is False
        assert "Unknown provider" in result.error

    @pytest.mark.asyncio
    async def test_brevo_success(self):
        config = self._make_config(provider="brevo")
        client = EmailClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"messageId": "msg-123"}

        with patch("app.integrations.brevo.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_client_instance

            result = await client.send(self._make_message())

        assert result.success is True
        assert result.message_id == "msg-123"
        assert result.provider == "brevo"

    @pytest.mark.asyncio
    async def test_brevo_api_error(self):
        config = self._make_config(provider="brevo")
        client = EmailClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("app.integrations.brevo.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_client_instance

            result = await client.send(self._make_message())

        assert result.success is False
        assert "400" in result.error

    @pytest.mark.asyncio
    async def test_sendgrid_success(self):
        config = self._make_config(provider="sendgrid")
        client = EmailClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 202
        mock_response.headers = {"X-Message-Id": "sg-456"}

        with patch("app.integrations.brevo.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_client_instance

            result = await client.send(self._make_message())

        assert result.success is True
        assert result.message_id == "sg-456"
        assert result.provider == "sendgrid"

    @pytest.mark.asyncio
    async def test_sendgrid_api_error(self):
        config = self._make_config(provider="sendgrid")
        client = EmailClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("app.integrations.brevo.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_client_instance

            result = await client.send(self._make_message())

        assert result.success is False
        assert "403" in result.error

    @pytest.mark.asyncio
    async def test_smtp_success(self):
        config = self._make_config(provider="smtp")
        config.host = "smtp.test.com"
        config.port = 587
        client = EmailClient(config)

        with patch("app.integrations.brevo.smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = await client.send(self._make_message())

        assert result.success is True
        assert result.provider == "smtp"

    @pytest.mark.asyncio
    async def test_smtp_connection_error(self):
        config = self._make_config(provider="smtp")
        config.host = "bad-host.test.com"
        client = EmailClient(config)

        with patch("app.integrations.brevo.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.side_effect = ConnectionRefusedError("Connection refused")

            result = await client.send(self._make_message())

        assert result.success is False
        assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_org_sender_override(self):
        """Org emails use global infra but display org sender name and reply-to (Req 33.3)."""
        config = self._make_config(provider="brevo")
        client = EmailClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"messageId": "msg-org"}

        with patch("app.integrations.brevo.httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.return_value = mock_client_instance

            msg = self._make_message(
                from_name="Bob's Workshop",
                reply_to="bob@bobsworkshop.nz",
            )
            result = await client.send(msg)

            # Verify the API call used org overrides
            call_args = mock_client_instance.post.call_args
            payload = call_args.kwargs.get("json") or call_args[1].get("json")
            assert payload["sender"]["name"] == "Bob's Workshop"
            assert payload["replyTo"]["email"] == "bob@bobsworkshop.nz"

        assert result.success is True

    @pytest.mark.asyncio
    async def test_brevo_exception_handling(self):
        config = self._make_config(provider="brevo")
        client = EmailClient(config)

        with patch("app.integrations.brevo.httpx.AsyncClient") as mock_httpx:
            mock_httpx.side_effect = Exception("Network error")
            result = await client.send(self._make_message())

        assert result.success is False
        assert "Network error" in result.error


# ---------------------------------------------------------------------------
# send_org_email tests
# ---------------------------------------------------------------------------


class TestSendOrgEmail:
    @pytest.mark.asyncio
    async def test_no_config_returns_error(self):
        """When no SMTP config exists, send_org_email returns an error."""
        mock_db = AsyncMock()

        with patch("app.integrations.brevo.get_email_client", return_value=None):
            result = await send_org_email(
                mock_db,
                to_email="customer@example.com",
                subject="Invoice",
                html_body="<p>Invoice</p>",
            )

        assert result.success is False
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_org_overrides_applied(self):
        """Org sender name and reply-to are passed to the email client (Req 33.3)."""
        mock_client = AsyncMock()
        mock_client.send.return_value = SendResult(success=True, provider="brevo")

        with patch("app.integrations.brevo.get_email_client", return_value=mock_client):
            result = await send_org_email(
                AsyncMock(),
                to_email="customer@example.com",
                subject="Invoice",
                html_body="<p>Invoice</p>",
                org_sender_name="Acme Workshop",
                org_reply_to="acme@workshop.nz",
            )

        assert result.success is True
        sent_msg = mock_client.send.call_args[0][0]
        assert sent_msg.from_name == "Acme Workshop"
        assert sent_msg.reply_to == "acme@workshop.nz"


# ---------------------------------------------------------------------------
# Admin service: save_smtp_config tests
# ---------------------------------------------------------------------------


class TestSaveSmtpConfig:
    @pytest.mark.asyncio
    async def test_invalid_provider_raises(self):
        mock_db = AsyncMock()
        with pytest.raises(ValueError, match="Provider must be one of"):
            await save_smtp_config(
                mock_db,
                provider="invalid",
                api_key="key",
                host="",
                port=587,
                username="",
                password="",
                domain="test.com",
                from_email="noreply@test.com",
                from_name="Test",
                reply_to="",
                updated_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_creates_new_config(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch("app.core.encryption.envelope_encrypt", return_value=b"encrypted"), \
             patch("app.core.audit.write_audit_log", new_callable=AsyncMock):
            result = await save_smtp_config(
                mock_db,
                provider="brevo",
                api_key="xkeysib-test",
                host="",
                port=587,
                username="",
                password="",
                domain="workshoppro.nz",
                from_email="noreply@workshoppro.nz",
                from_name="WorkshopPro NZ",
                reply_to="support@workshoppro.nz",
                updated_by=uuid.uuid4(),
            )

        assert result["provider"] == "brevo"
        assert result["domain"] == "workshoppro.nz"
        assert result["is_verified"] is False
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_config(self):
        mock_db = AsyncMock()
        existing_config = MagicMock()
        existing_config.config_encrypted = b"old"
        existing_config.is_verified = True
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_config
        mock_db.execute.return_value = mock_result

        with patch("app.core.encryption.envelope_encrypt", return_value=b"new_encrypted"), \
             patch("app.core.audit.write_audit_log", new_callable=AsyncMock):
            result = await save_smtp_config(
                mock_db,
                provider="sendgrid",
                api_key="SG.new",
                host="",
                port=587,
                username="",
                password="",
                domain="new.com",
                from_email="noreply@new.com",
                from_name="New Platform",
                reply_to="",
                updated_by=uuid.uuid4(),
            )

        assert result["provider"] == "sendgrid"
        assert result["is_verified"] is False
        assert existing_config.config_encrypted == b"new_encrypted"
        mock_db.add.assert_not_called()


# ---------------------------------------------------------------------------
# Admin service: send_test_email tests
# ---------------------------------------------------------------------------


class TestSendTestEmail:
    @pytest.mark.asyncio
    async def test_no_config_returns_failure(self):
        mock_db = AsyncMock()

        with patch("app.integrations.brevo.get_email_client", return_value=None):
            result = await send_test_email(
                mock_db,
                admin_email="admin@test.com",
                admin_user_id=uuid.uuid4(),
            )

        assert result["success"] is False
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_successful_test_email_marks_verified(self):
        mock_db = AsyncMock()
        mock_client = AsyncMock()
        mock_client.config = SmtpConfig(provider="brevo", domain="test.com")
        mock_client.send.return_value = SendResult(
            success=True, message_id="test-123", provider="brevo"
        )

        # Mock the config row lookup for marking verified
        mock_config_row = MagicMock()
        mock_config_row.is_verified = False
        mock_config_result = MagicMock()
        mock_config_result.scalar_one_or_none.return_value = mock_config_row
        mock_db.execute.return_value = mock_config_result

        with patch("app.integrations.brevo.get_email_client", return_value=mock_client), \
             patch("app.core.audit.write_audit_log", new_callable=AsyncMock):
            result = await send_test_email(
                mock_db,
                admin_email="admin@test.com",
                admin_user_id=uuid.uuid4(),
            )

        assert result["success"] is True
        assert mock_config_row.is_verified is True

    @pytest.mark.asyncio
    async def test_failed_test_email(self):
        mock_db = AsyncMock()
        mock_client = AsyncMock()
        mock_client.config = SmtpConfig(provider="smtp", domain="test.com")
        mock_client.send.return_value = SendResult(
            success=False, error="Connection refused", provider="smtp"
        )

        with patch("app.integrations.brevo.get_email_client", return_value=mock_client):
            result = await send_test_email(
                mock_db,
                admin_email="admin@test.com",
                admin_user_id=uuid.uuid4(),
            )

        assert result["success"] is False
        assert result["error"] == "Connection refused"


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestSmtpSchemas:
    def test_request_requires_domain(self):
        with pytest.raises(Exception):
            SmtpConfigRequest(
                from_email="noreply@test.com",
                from_name="Test",
                domain="",  # min_length=1
            )

    def test_request_requires_from_email(self):
        with pytest.raises(Exception):
            SmtpConfigRequest(
                domain="test.com",
                from_email="",  # min_length=1
                from_name="Test",
            )

    def test_request_requires_from_name(self):
        with pytest.raises(Exception):
            SmtpConfigRequest(
                domain="test.com",
                from_email="noreply@test.com",
                from_name="",  # min_length=1
            )

    def test_valid_request(self):
        req = SmtpConfigRequest(
            provider="brevo",
            api_key="xkeysib-test",
            domain="workshoppro.nz",
            from_email="noreply@workshoppro.nz",
            from_name="WorkshopPro NZ",
            reply_to="support@workshoppro.nz",
        )
        assert req.provider == "brevo"
        assert req.domain == "workshoppro.nz"

    def test_request_defaults(self):
        req = SmtpConfigRequest(
            domain="test.com",
            from_email="noreply@test.com",
            from_name="Test",
        )
        assert req.provider == "smtp"
        assert req.port == 587
        assert req.api_key == ""
        assert req.reply_to == ""

    def test_response_schema(self):
        resp = SmtpConfigResponse(
            message="Saved",
            provider="brevo",
            domain="test.com",
            from_email="noreply@test.com",
            from_name="Test",
            reply_to="reply@test.com",
            is_verified=False,
        )
        assert resp.is_verified is False

    def test_test_email_response_schema(self):
        resp = SmtpTestEmailResponse(
            success=True,
            message="Test email sent",
            provider="brevo",
        )
        assert resp.success is True
        assert resp.error is None
