"""Unit tests for Task 23.2 — integration configuration (Carjam & Stripe).

Tests cover:
  - Carjam config schemas (request/response validation)
  - Stripe config schemas (request/response validation)
  - Generic GET integration config (non-secret fields only)
  - save_carjam_config service function
  - save_stripe_config service function
  - get_integration_config service function (secrets never returned)
  - test_carjam_connection service function
  - test_stripe_connection service function
  - Envelope encryption of credentials
  - Audit logging for config changes
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.models import IntegrationConfig
from app.modules.admin.schemas import (
    CarjamConfigRequest,
    CarjamConfigResponse,
    CarjamTestResponse,
    IntegrationConfigGetResponse,
    StripeConfigRequest,
    StripeConfigResponse,
    StripeTestResponse,
)
from app.modules.admin.service import (
    get_integration_config,
    save_carjam_config,
    save_stripe_config,
    test_carjam_connection,
    test_stripe_connection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db_session():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestCarjamConfigSchemas:
    """Test Pydantic schema validation for Carjam config."""

    def test_valid_carjam_config_request(self):
        req = CarjamConfigRequest(
            api_key="test-api-key-12345",
            endpoint_url="https://api.carjam.co.nz/v1",
            per_lookup_cost_nzd=0.15,
            global_rate_limit_per_minute=60,
        )
        assert req.api_key == "test-api-key-12345"
        assert req.endpoint_url == "https://api.carjam.co.nz/v1"
        assert req.per_lookup_cost_nzd == 0.15
        assert req.global_rate_limit_per_minute == 60

    def test_carjam_config_requires_api_key(self):
        with pytest.raises(Exception):
            CarjamConfigRequest(
                api_key="",
                endpoint_url="https://api.carjam.co.nz/v1",
                per_lookup_cost_nzd=0.15,
                global_rate_limit_per_minute=60,
            )

    def test_carjam_config_requires_positive_rate_limit(self):
        with pytest.raises(Exception):
            CarjamConfigRequest(
                api_key="key123",
                endpoint_url="https://api.carjam.co.nz/v1",
                per_lookup_cost_nzd=0.15,
                global_rate_limit_per_minute=0,
            )

    def test_carjam_config_cost_cannot_be_negative(self):
        with pytest.raises(Exception):
            CarjamConfigRequest(
                api_key="key123",
                endpoint_url="https://api.carjam.co.nz/v1",
                per_lookup_cost_nzd=-1.0,
                global_rate_limit_per_minute=60,
            )

    def test_carjam_config_response(self):
        resp = CarjamConfigResponse(
            message="Carjam configuration saved",
            endpoint_url="https://api.carjam.co.nz/v1",
            per_lookup_cost_nzd=0.15,
            global_rate_limit_per_minute=60,
            api_key_last4="2345",
            is_verified=False,
        )
        assert resp.api_key_last4 == "2345"
        assert resp.is_verified is False

    def test_carjam_test_response(self):
        resp = CarjamTestResponse(
            success=True,
            message="Carjam connection verified successfully.",
        )
        assert resp.success is True


class TestStripeConfigSchemas:
    """Test Pydantic schema validation for Stripe config."""

    def test_valid_stripe_config_request(self):
        req = StripeConfigRequest(
            platform_account_id="acct_1234567890",
            webhook_endpoint="https://workshoppro.nz/api/v1/payments/stripe/webhook",
            signing_secret="whsec_test_secret_123",
        )
        assert req.platform_account_id == "acct_1234567890"
        assert req.signing_secret == "whsec_test_secret_123"

    def test_stripe_config_requires_account_id(self):
        with pytest.raises(Exception):
            StripeConfigRequest(
                platform_account_id="",
                webhook_endpoint="https://example.com/webhook",
                signing_secret="whsec_test",
            )

    def test_stripe_config_response(self):
        resp = StripeConfigResponse(
            message="Stripe configuration saved",
            platform_account_last4="7890",
            webhook_endpoint="https://workshoppro.nz/webhook",
            is_verified=False,
        )
        assert resp.platform_account_last4 == "7890"

    def test_stripe_test_response(self):
        resp = StripeTestResponse(
            success=False,
            message="Stripe connection test failed",
            error="No Stripe config",
        )
        assert resp.success is False


class TestIntegrationConfigGetResponse:
    """Test the generic GET response schema."""

    def test_unconfigured_integration(self):
        resp = IntegrationConfigGetResponse(
            name="carjam",
            is_verified=False,
            updated_at=None,
            config={},
        )
        assert resp.name == "carjam"
        assert resp.config == {}

    def test_configured_integration(self):
        resp = IntegrationConfigGetResponse(
            name="stripe",
            is_verified=True,
            updated_at=datetime.now(timezone.utc),
            config={"webhook_endpoint": "https://example.com", "platform_account_id_last4": "7890"},
        )
        assert resp.is_verified is True
        assert "webhook_endpoint" in resp.config


# ---------------------------------------------------------------------------
# Service tests — save_carjam_config
# ---------------------------------------------------------------------------

class TestSaveCarjamConfig:
    """Test save_carjam_config service function."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_creates_new_config(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await save_carjam_config(
            db,
            api_key="test-key-abcd",
            endpoint_url="https://api.carjam.co.nz/v1",
            per_lookup_cost_nzd=0.15,
            global_rate_limit_per_minute=60,
            updated_by=uuid.uuid4(),
        )

        assert result["endpoint_url"] == "https://api.carjam.co.nz/v1"
        assert result["per_lookup_cost_nzd"] == 0.15
        assert result["global_rate_limit_per_minute"] == 60
        assert result["api_key_last4"] == "abcd"
        assert result["is_verified"] is False
        db.add.assert_called_once()
        mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_updates_existing_config(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        existing = MagicMock(spec=IntegrationConfig)
        existing.name = "carjam"
        existing.config_encrypted = b"old_data"
        existing.is_verified = True

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing))

        result = await save_carjam_config(
            db,
            api_key="new-key-wxyz",
            endpoint_url="https://api.carjam.co.nz/v2",
            per_lookup_cost_nzd=0.20,
            global_rate_limit_per_minute=120,
            updated_by=uuid.uuid4(),
        )

        assert result["api_key_last4"] == "wxyz"
        assert result["is_verified"] is False
        assert existing.config_encrypted == b"encrypted_data"
        assert existing.is_verified is False
        db.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_short_api_key_last4(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await save_carjam_config(
            db,
            api_key="ab",
            endpoint_url="https://api.carjam.co.nz/v1",
            per_lookup_cost_nzd=0.10,
            global_rate_limit_per_minute=30,
            updated_by=uuid.uuid4(),
        )

        assert result["api_key_last4"] == "ab"

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_audit_log_does_not_contain_full_key(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        await save_carjam_config(
            db,
            api_key="super-secret-key-1234",
            endpoint_url="https://api.carjam.co.nz/v1",
            per_lookup_cost_nzd=0.15,
            global_rate_limit_per_minute=60,
            updated_by=uuid.uuid4(),
            ip_address="10.0.0.1",
        )

        audit_call = mock_audit.call_args
        after_value = audit_call.kwargs["after_value"]
        assert "super-secret-key-1234" not in json.dumps(after_value)
        assert after_value["api_key_last4"] == "1234"


# ---------------------------------------------------------------------------
# Service tests — save_stripe_config
# ---------------------------------------------------------------------------

class TestSaveStripeConfig:
    """Test save_stripe_config service function."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_creates_new_config(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await save_stripe_config(
            db,
            platform_account_id="acct_1234567890",
            webhook_endpoint="https://workshoppro.nz/webhook",
            signing_secret="whsec_test_secret",
            updated_by=uuid.uuid4(),
        )

        assert result["platform_account_last4"] == "7890"
        assert result["webhook_endpoint"] == "https://workshoppro.nz/webhook"
        assert result["is_verified"] is False
        db.add.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_updates_existing_config(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        existing = MagicMock(spec=IntegrationConfig)
        existing.name = "stripe"
        existing.config_encrypted = b"old_data"
        existing.is_verified = True

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing))

        result = await save_stripe_config(
            db,
            platform_account_id="acct_new_account",
            webhook_endpoint="https://new.endpoint.com/webhook",
            signing_secret="whsec_new_secret",
            updated_by=uuid.uuid4(),
        )

        assert result["is_verified"] is False
        assert existing.config_encrypted == b"encrypted_data"
        db.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.core.encryption.envelope_encrypt")
    async def test_audit_log_does_not_contain_signing_secret(self, mock_encrypt, mock_audit):
        mock_encrypt.return_value = b"encrypted_data"
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        await save_stripe_config(
            db,
            platform_account_id="acct_1234567890",
            webhook_endpoint="https://workshoppro.nz/webhook",
            signing_secret="whsec_super_secret_value",
            updated_by=uuid.uuid4(),
        )

        audit_call = mock_audit.call_args
        after_value = audit_call.kwargs["after_value"]
        assert "whsec_super_secret_value" not in json.dumps(after_value)
        assert "signing_secret" not in after_value


# ---------------------------------------------------------------------------
# Service tests — get_integration_config
# ---------------------------------------------------------------------------

class TestGetIntegrationConfig:
    """Test get_integration_config service function."""

    @pytest.mark.asyncio
    async def test_unknown_integration_returns_none(self):
        db = _mock_db_session()
        result = await get_integration_config(db, name="unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_unconfigured_integration_returns_empty(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await get_integration_config(db, name="carjam")
        assert result is not None
        assert result["name"] == "carjam"
        assert result["is_verified"] is False
        assert result["config"] == {}

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_carjam_config_returns_safe_fields_only(self, mock_decrypt):
        config_data = {
            "api_key": "super-secret-api-key",
            "endpoint_url": "https://api.carjam.co.nz/v1",
            "per_lookup_cost_nzd": 0.15,
            "global_rate_limit_per_minute": 60,
        }
        mock_decrypt.return_value = json.dumps(config_data)

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.name = "carjam"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="carjam")

        assert result["name"] == "carjam"
        assert result["is_verified"] is True
        config = result["config"]
        # Safe fields present
        assert config["endpoint_url"] == "https://api.carjam.co.nz/v1"
        assert config["per_lookup_cost_nzd"] == 0.15
        assert config["global_rate_limit_per_minute"] == 60
        # Secret masked
        assert config["api_key_last4"] == "-key"
        # Full secret NOT present
        assert "api_key" not in config or config.get("api_key") != "super-secret-api-key"

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_stripe_config_returns_safe_fields_only(self, mock_decrypt):
        config_data = {
            "platform_account_id": "acct_1234567890",
            "webhook_endpoint": "https://workshoppro.nz/webhook",
            "signing_secret": "whsec_test_secret_value",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.name = "stripe"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = False
        config_row.updated_at = datetime(2024, 7, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="stripe")

        config = result["config"]
        assert config["webhook_endpoint"] == "https://workshoppro.nz/webhook"
        assert config["platform_account_id_last4"] == "7890"
        assert config["signing_secret_last4"] == "alue"
        # Full secrets NOT present
        assert "platform_account_id" not in config
        assert "signing_secret" not in config

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_smtp_config_returns_safe_fields_only(self, mock_decrypt):
        config_data = {
            "provider": "brevo",
            "api_key": "xkeysib-secret-key",
            "host": "smtp.brevo.com",
            "port": 587,
            "username": "user",
            "password": "pass",
            "domain": "workshoppro.nz",
            "from_email": "noreply@workshoppro.nz",
            "from_name": "WorkshopPro",
            "reply_to": "support@workshoppro.nz",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.name = "smtp"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 5, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="smtp")

        config = result["config"]
        assert config["provider"] == "brevo"
        assert config["domain"] == "workshoppro.nz"
        assert config["from_email"] == "noreply@workshoppro.nz"
        assert config["api_key_last4"] == "-key"
        # Full api_key NOT present
        assert "xkeysib-secret-key" not in json.dumps(config)

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_twilio_config_returns_safe_fields_only(self, mock_decrypt):
        config_data = {
            "account_sid": "AC1234567890abcdef",
            "auth_token": "secret_auth_token",
            "sender_number": "+64211234567",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.name = "twilio"
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = True
        config_row.updated_at = datetime(2024, 8, 1, tzinfo=timezone.utc)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await get_integration_config(db, name="twilio")

        config = result["config"]
        assert config["sender_number"] == "+64211234567"
        assert config["account_sid_last4"] == "cdef"
        # Full secrets NOT present
        assert "secret_auth_token" not in json.dumps(config)


# ---------------------------------------------------------------------------
# Service tests — test_carjam_connection
# ---------------------------------------------------------------------------

class TestCarjamConnection:
    """Test test_carjam_connection service function."""

    @pytest.mark.asyncio
    async def test_no_config_returns_failure(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await test_carjam_connection(
            db, admin_user_id=uuid.uuid4()
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_successful_connection(self, mock_audit, mock_decrypt):
        config_data = {
            "api_key": "test-key",
            "endpoint_url": "https://api.carjam.co.nz/v1",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = False

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        # Mock httpx to return 404 (API reachable, no vehicle for TEST000)
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await test_carjam_connection(
                db, admin_user_id=uuid.uuid4()
            )

        assert result["success"] is True
        assert config_row.is_verified is True

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_unauthorized_returns_failure(self, mock_decrypt):
        config_data = {
            "api_key": "bad-key",
            "endpoint_url": "https://api.carjam.co.nz/v1",
        }
        mock_decrypt.return_value = json.dumps(config_data)

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.config_encrypted = b"encrypted"

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await test_carjam_connection(
                db, admin_user_id=uuid.uuid4()
            )

        assert result["success"] is False
        assert "401" in result["message"]


# ---------------------------------------------------------------------------
# Service tests — test_stripe_connection
# ---------------------------------------------------------------------------

class TestStripeConnection:
    """Test test_stripe_connection service function."""

    @pytest.mark.asyncio
    async def test_no_config_returns_failure(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await test_stripe_connection(
            db, admin_user_id=uuid.uuid4()
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    async def test_missing_account_id_returns_failure(self, mock_decrypt):
        mock_decrypt.return_value = json.dumps({
            "platform_account_id": "",
            "webhook_endpoint": "https://example.com",
            "signing_secret": "whsec_test",
        })

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.config_encrypted = b"encrypted"

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        result = await test_stripe_connection(
            db, admin_user_id=uuid.uuid4()
        )
        assert result["success"] is False
        assert "incomplete" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("app.core.encryption.envelope_decrypt_str")
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_successful_stripe_connection(self, mock_audit, mock_decrypt):
        mock_decrypt.return_value = json.dumps({
            "platform_account_id": "acct_1234567890",
            "webhook_endpoint": "https://workshoppro.nz/webhook",
            "signing_secret": "whsec_test",
        })

        config_row = MagicMock(spec=IntegrationConfig)
        config_row.config_encrypted = b"encrypted"
        config_row.is_verified = False

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config_row))

        with patch("stripe.Account") as mock_account_cls:
            mock_account_cls.retrieve.return_value = {"id": "acct_1234567890"}

            result = await test_stripe_connection(
                db, admin_user_id=uuid.uuid4()
            )

        assert result["success"] is True
        assert config_row.is_verified is True


# ---------------------------------------------------------------------------
# Encryption integration test
# ---------------------------------------------------------------------------

class TestEncryptionIntegration:
    """Verify credentials are actually encrypted before storage."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_carjam_config_is_encrypted(self, mock_audit):
        """Verify that envelope_encrypt is called with the config JSON."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with patch("app.core.encryption.envelope_encrypt") as mock_encrypt:
            mock_encrypt.return_value = b"encrypted_blob"

            await save_carjam_config(
                db,
                api_key="secret-key",
                endpoint_url="https://api.carjam.co.nz",
                per_lookup_cost_nzd=0.15,
                global_rate_limit_per_minute=60,
                updated_by=uuid.uuid4(),
            )

            mock_encrypt.assert_called_once()
            call_arg = mock_encrypt.call_args[0][0]
            parsed = json.loads(call_arg)
            assert parsed["api_key"] == "secret-key"

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_stripe_config_is_encrypted(self, mock_audit):
        """Verify that envelope_encrypt is called with the config JSON."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with patch("app.core.encryption.envelope_encrypt") as mock_encrypt:
            mock_encrypt.return_value = b"encrypted_blob"

            await save_stripe_config(
                db,
                platform_account_id="acct_test",
                webhook_endpoint="https://example.com/webhook",
                signing_secret="whsec_secret",
                updated_by=uuid.uuid4(),
            )

            mock_encrypt.assert_called_once()
            call_arg = mock_encrypt.call_args[0][0]
            parsed = json.loads(call_arg)
            assert parsed["signing_secret"] == "whsec_secret"
