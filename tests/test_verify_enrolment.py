"""Unit tests for verify_enrolment() — Task 2.2.

Tests cover:
  - TOTP: valid code marks method verified, invalid code rejected
  - SMS: valid OTP marks method verified, OTP consumed
  - Email: valid OTP marks method verified, OTP consumed
  - Invalid/expired OTP rejection
  - No pending enrolment error
  - Unsupported method error
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pyotp
import pytest

from app.core.encryption import envelope_encrypt
from app.modules.auth.mfa_service import verify_enrolment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(**overrides) -> MagicMock:
    """Create a mock User object with sensible defaults."""
    user = MagicMock()
    user.id = overrides.get("id", uuid.uuid4())
    user.org_id = overrides.get("org_id", uuid.uuid4())
    user.email = overrides.get("email", "test@workshop.nz")
    user.role = overrides.get("role", "org_admin")
    user.is_active = overrides.get("is_active", True)
    return user


def _make_pending_mfa_record(method: str, user_id: uuid.UUID, **overrides) -> MagicMock:
    """Create a mock UserMfaMethod record representing a pending enrolment."""
    record = MagicMock()
    record.user_id = user_id
    record.method = method
    record.verified = False
    record.verified_at = None
    record.phone_number = overrides.get("phone_number", None)
    record.secret_encrypted = overrides.get("secret_encrypted", None)
    return record


def _mock_db_with_pending(pending_record):
    """Create a mock AsyncSession that returns the given pending record."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = pending_record
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _mock_db_no_pending():
    """Create a mock AsyncSession that returns no pending record."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# TOTP enrolment verification
# ---------------------------------------------------------------------------

class TestVerifyEnrolmentTOTP:
    @pytest.mark.asyncio
    async def test_valid_totp_code_marks_verified(self):
        """Valid TOTP code within ±1 window marks method as verified."""
        secret = pyotp.random_base32()
        encrypted = envelope_encrypt(secret)
        user = _make_user()

        pending = _make_pending_mfa_record(
            "totp", user.id, secret_encrypted=encrypted,
        )
        db = _mock_db_with_pending(pending)

        totp = pyotp.TOTP(secret)
        code = totp.now()

        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            await verify_enrolment(db, user, "totp", code)

        assert pending.verified is True
        assert pending.verified_at is not None
        assert isinstance(pending.verified_at, datetime)

    @pytest.mark.asyncio
    async def test_invalid_totp_code_rejected(self):
        """Invalid TOTP code raises ValueError."""
        secret = pyotp.random_base32()
        encrypted = envelope_encrypt(secret)
        user = _make_user()

        pending = _make_pending_mfa_record(
            "totp", user.id, secret_encrypted=encrypted,
        )
        db = _mock_db_with_pending(pending)

        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Invalid TOTP code"):
                await verify_enrolment(db, user, "totp", "000000")

        # Method should remain unverified
        assert pending.verified is False

    @pytest.mark.asyncio
    async def test_totp_no_secret_raises_error(self):
        """Missing encrypted secret raises ValueError."""
        user = _make_user()
        pending = _make_pending_mfa_record("totp", user.id, secret_encrypted=None)
        db = _mock_db_with_pending(pending)

        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="No TOTP secret found"):
                await verify_enrolment(db, user, "totp", "123456")


# ---------------------------------------------------------------------------
# SMS enrolment verification
# ---------------------------------------------------------------------------

class TestVerifyEnrolmentSMS:
    @pytest.mark.asyncio
    async def test_valid_sms_otp_marks_verified(self):
        """Valid SMS OTP marks method as verified and consumes OTP."""
        user = _make_user()
        pending = _make_pending_mfa_record(
            "sms", user.id, phone_number="+64211234567",
        )
        db = _mock_db_with_pending(pending)

        with (
            patch("app.modules.auth.mfa_service._get_otp_from_redis", new_callable=AsyncMock, return_value="123456"),
            patch("app.modules.auth.mfa_service._delete_otp_from_redis", new_callable=AsyncMock) as mock_delete,
            patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock),
        ):
            await verify_enrolment(db, user, "sms", "123456")

        assert pending.verified is True
        assert pending.verified_at is not None
        mock_delete.assert_awaited_once_with(user.id, "sms")

    @pytest.mark.asyncio
    async def test_invalid_sms_otp_rejected(self):
        """Wrong SMS OTP raises ValueError."""
        user = _make_user()
        pending = _make_pending_mfa_record("sms", user.id, phone_number="+64211234567")
        db = _mock_db_with_pending(pending)

        with (
            patch("app.modules.auth.mfa_service._get_otp_from_redis", new_callable=AsyncMock, return_value="123456"),
            patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="Invalid or expired verification code"):
                await verify_enrolment(db, user, "sms", "999999")

        assert pending.verified is False

    @pytest.mark.asyncio
    async def test_expired_sms_otp_rejected(self):
        """Expired (missing from Redis) SMS OTP raises ValueError."""
        user = _make_user()
        pending = _make_pending_mfa_record("sms", user.id, phone_number="+64211234567")
        db = _mock_db_with_pending(pending)

        with (
            patch("app.modules.auth.mfa_service._get_otp_from_redis", new_callable=AsyncMock, return_value=None),
            patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="Invalid or expired verification code"):
                await verify_enrolment(db, user, "sms", "123456")


# ---------------------------------------------------------------------------
# Email enrolment verification
# ---------------------------------------------------------------------------

class TestVerifyEnrolmentEmail:
    @pytest.mark.asyncio
    async def test_valid_email_otp_marks_verified(self):
        """Valid email OTP marks method as verified and consumes OTP."""
        user = _make_user()
        pending = _make_pending_mfa_record("email", user.id)
        db = _mock_db_with_pending(pending)

        with (
            patch("app.modules.auth.mfa_service._get_otp_from_redis", new_callable=AsyncMock, return_value="654321"),
            patch("app.modules.auth.mfa_service._delete_otp_from_redis", new_callable=AsyncMock) as mock_delete,
            patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock),
        ):
            await verify_enrolment(db, user, "email", "654321")

        assert pending.verified is True
        assert pending.verified_at is not None
        mock_delete.assert_awaited_once_with(user.id, "email")

    @pytest.mark.asyncio
    async def test_invalid_email_otp_rejected(self):
        """Wrong email OTP raises ValueError."""
        user = _make_user()
        pending = _make_pending_mfa_record("email", user.id)
        db = _mock_db_with_pending(pending)

        with (
            patch("app.modules.auth.mfa_service._get_otp_from_redis", new_callable=AsyncMock, return_value="654321"),
            patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock),
        ):
            with pytest.raises(ValueError, match="Invalid or expired verification code"):
                await verify_enrolment(db, user, "email", "111111")

        assert pending.verified is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestVerifyEnrolmentEdgeCases:
    @pytest.mark.asyncio
    async def test_no_pending_enrolment_raises_error(self):
        """No pending enrolment record raises ValueError."""
        user = _make_user()
        db = _mock_db_no_pending()

        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="No pending totp enrolment found"):
                await verify_enrolment(db, user, "totp", "123456")

    @pytest.mark.asyncio
    async def test_unsupported_method_raises_error(self):
        """Unsupported method type raises ValueError."""
        user = _make_user()
        db = AsyncMock()

        with pytest.raises(ValueError, match="Unsupported MFA method"):
            await verify_enrolment(db, user, "passkey", "123456")

    @pytest.mark.asyncio
    async def test_audit_log_written_on_success(self):
        """Successful verification writes an audit log entry."""
        user = _make_user()
        pending = _make_pending_mfa_record("email", user.id)
        db = _mock_db_with_pending(pending)

        with (
            patch("app.modules.auth.mfa_service._get_otp_from_redis", new_callable=AsyncMock, return_value="123456"),
            patch("app.modules.auth.mfa_service._delete_otp_from_redis", new_callable=AsyncMock),
            patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock) as mock_audit,
        ):
            await verify_enrolment(db, user, "email", "123456")

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "auth.mfa_enrol_verified"
        assert call_kwargs["after_value"]["method"] == "email"
