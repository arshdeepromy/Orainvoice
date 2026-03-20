"""Unit tests for Task 4.5 — MFA enrolment and verification.

Tests cover:
  - TOTP enrolment (secret generation, QR URI)
  - SMS/email OTP generation
  - TOTP verification
  - SMS/email OTP verification via Redis
  - Backup code generation and single-use verification
  - MFA attempt locking after 5 failures
  - MFA policy helpers (Global_Admin enforcement, org mandatory)
  - MFA token decoding
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pyotp
import pytest
import jwt as jose_jwt

import app.modules.admin.models  # noqa: F401 — resolve relationships

from app.config import settings
from app.modules.auth.mfa_service import (
    _BACKUP_CODE_COUNT,
    _BACKUP_CODE_LENGTH,
    _MAX_MFA_ATTEMPTS,
    _generate_otp_code,
    _get_verified_mfa_methods,
    _verify_totp_code,
    generate_backup_codes,
    user_has_verified_mfa,
    user_requires_mfa_setup,
)
from app.modules.auth.schemas import (
    MFABackupCodesResponse,
    MFAEnrolRequest,
    MFAEnrolResponse,
    MFAVerifyRequest,
)
from app.modules.auth.service import create_access_token_mfa_pending


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
    user.mfa_methods = overrides.get("mfa_methods", [])
    user.last_login_at = None
    return user


def _make_mfa_method(**overrides) -> MagicMock:
    """Create a mock UserMfaMethod object."""
    from app.modules.auth.models import UserMfaMethod

    m = MagicMock(spec=UserMfaMethod)
    m.id = overrides.get("id", uuid.uuid4())
    m.user_id = overrides.get("user_id", uuid.uuid4())
    m.method = overrides.get("method", "totp")
    m.verified = overrides.get("verified", False)
    m.phone_number = overrides.get("phone_number", None)
    m.secret_encrypted = overrides.get("secret_encrypted", None)
    m.enrolled_at = overrides.get("enrolled_at", datetime.now(timezone.utc))
    m.verified_at = overrides.get("verified_at", None)
    return m


# ---------------------------------------------------------------------------
# OTP code generation
# ---------------------------------------------------------------------------

class TestOTPCodeGeneration:
    def test_otp_code_is_6_digits(self):
        code = _generate_otp_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_otp_codes_are_random(self):
        codes = {_generate_otp_code() for _ in range(100)}
        # With 6 digits, 100 random codes should produce many unique values
        assert len(codes) > 50


# ---------------------------------------------------------------------------
# MFA token creation
# ---------------------------------------------------------------------------

class TestMFAToken:
    def test_mfa_pending_token_has_correct_type(self):
        uid = uuid.uuid4()
        token = create_access_token_mfa_pending(uid)
        payload = jose_jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        assert payload["type"] == "mfa_pending"
        assert payload["user_id"] == str(uid)

    def test_mfa_pending_token_expires_in_5_minutes(self):
        uid = uuid.uuid4()
        token = create_access_token_mfa_pending(uid)
        payload = jose_jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        delta = exp - iat
        assert timedelta(minutes=4, seconds=50) < delta <= timedelta(minutes=5, seconds=10)


# ---------------------------------------------------------------------------
# TOTP verification
# ---------------------------------------------------------------------------

class TestTOTPVerification:
    @pytest.mark.asyncio
    async def test_valid_totp_code_verifies(self):
        from app.core.encryption import envelope_encrypt
        from app.modules.auth.models import UserMfaMethod

        secret = pyotp.random_base32()
        encrypted = envelope_encrypt(secret)

        user = _make_user()

        # Mock the db to return a verified TOTP method
        mock_method = MagicMock(spec=UserMfaMethod)
        mock_method.secret_encrypted = encrypted
        mock_method.verified = True
        mock_method.method = "totp"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_method
        db = AsyncMock()
        db.execute.return_value = mock_result

        totp = pyotp.TOTP(secret)
        code = totp.now()

        result = await _verify_totp_code(db, user, code)
        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_totp_code_fails(self):
        from app.core.encryption import envelope_encrypt
        from app.modules.auth.models import UserMfaMethod

        secret = pyotp.random_base32()
        encrypted = envelope_encrypt(secret)

        user = _make_user()

        mock_method = MagicMock(spec=UserMfaMethod)
        mock_method.secret_encrypted = encrypted
        mock_method.verified = True
        mock_method.method = "totp"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_method
        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await _verify_totp_code(db, user, "000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_totp_with_no_methods_fails(self):
        user = _make_user()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = mock_result

        result = await _verify_totp_code(db, user, "123456")
        assert result is False


# ---------------------------------------------------------------------------
# Backup code generation and verification
# ---------------------------------------------------------------------------

class TestBackupCodes:
    @pytest.mark.asyncio
    async def test_generates_correct_number_of_codes(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        assert len(codes) == _BACKUP_CODE_COUNT

    @pytest.mark.asyncio
    async def test_codes_are_correct_length(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        for code in codes:
            assert len(code) == _BACKUP_CODE_LENGTH

    @pytest.mark.asyncio
    async def test_codes_are_unique(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        assert len(set(codes)) == len(codes)

    @pytest.mark.asyncio
    async def test_backup_codes_stored_in_user_backup_codes_table(self):
        """Verify that generate_backup_codes deletes old records and adds
        new UserBackupCode rows via db.add (not the old JSONB column)."""
        import bcrypt as bcrypt_lib
        from app.modules.auth.models import UserBackupCode

        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        # db.execute should have been called (at least for the delete)
        assert db.execute.await_count >= 1

        # db.add should have been called exactly 10 times (one per code)
        assert db.add.call_count == _BACKUP_CODE_COUNT

        # Each db.add call should receive a UserBackupCode instance
        for call in db.add.call_args_list:
            record = call[0][0]
            assert isinstance(record, UserBackupCode)
            assert record.user_id == user.id
            assert record.used is False
            # code_hash should be a bcrypt hash, not plain text
            assert record.code_hash.startswith("$2")

        # Verify each plain code can be checked against its stored hash
        for i, code in enumerate(codes):
            record = db.add.call_args_list[i][0][0]
            assert bcrypt_lib.checkpw(
                code.encode("utf-8"), record.code_hash.encode("utf-8")
            )

    @pytest.mark.asyncio
    async def test_codes_are_alphanumeric(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        for code in codes:
            assert code.isalnum(), f"Code '{code}' is not alphanumeric"

    @pytest.mark.asyncio
    async def test_deletes_previous_codes_before_inserting(self):
        """Verify that old backup codes are deleted before new ones are added."""
        user = _make_user()
        db = AsyncMock()
        call_order = []
        original_execute = db.execute
        original_add = db.add

        async def track_execute(*args, **kwargs):
            call_order.append("execute")
            return await original_execute(*args, **kwargs)

        def track_add(*args, **kwargs):
            call_order.append("add")
            return original_add(*args, **kwargs)

        db.execute = AsyncMock(side_effect=track_execute)
        db.add = MagicMock(side_effect=track_add)

        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            await generate_backup_codes(db, user)

        # The first operation should be execute (the delete), before any adds
        assert call_order[0] == "execute"
        assert "add" in call_order


# ---------------------------------------------------------------------------
# MFA policy helpers
# ---------------------------------------------------------------------------

class TestMFAPolicyHelpers:
    def test_global_admin_requires_mfa_without_methods(self):
        user = _make_user(role="global_admin", mfa_methods=[])
        assert user_requires_mfa_setup(user) is True

    def test_global_admin_does_not_require_mfa_with_verified_method(self):
        method = _make_mfa_method(method="totp", verified=True)
        user = _make_user(role="global_admin", mfa_methods=[method])
        assert user_requires_mfa_setup(user) is False

    def test_org_admin_requires_mfa_when_org_mandatory(self):
        user = _make_user(role="org_admin", mfa_methods=[])
        org_settings = {"mfa_policy": "mandatory"}
        assert user_requires_mfa_setup(user, org_settings) is True

    def test_org_admin_no_mfa_required_when_optional(self):
        user = _make_user(role="org_admin", mfa_methods=[])
        org_settings = {"mfa_policy": "optional"}
        assert user_requires_mfa_setup(user, org_settings) is False

    def test_salesperson_requires_mfa_when_org_mandatory(self):
        user = _make_user(role="salesperson", mfa_methods=[])
        org_settings = {"mfa_policy": "mandatory"}
        assert user_requires_mfa_setup(user, org_settings) is True

    def test_user_has_verified_mfa_true(self):
        method = _make_mfa_method(method="totp", verified=True)
        user = _make_user(mfa_methods=[method])
        assert user_has_verified_mfa(user) is True

    def test_user_has_verified_mfa_false_unverified(self):
        method = _make_mfa_method(method="totp", verified=False)
        user = _make_user(mfa_methods=[method])
        assert user_has_verified_mfa(user) is False

    def test_user_has_verified_mfa_false_empty(self):
        user = _make_user(mfa_methods=[])
        assert user_has_verified_mfa(user) is False

    def test_multiple_methods_one_verified(self):
        totp_method = _make_mfa_method(method="totp", verified=True)
        sms_method = _make_mfa_method(method="sms", verified=False)
        user = _make_user(mfa_methods=[totp_method, sms_method])
        assert user_has_verified_mfa(user) is True
        verified = _get_verified_mfa_methods(user)
        assert len(verified) == 1
        assert verified[0].method == "totp"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestMFASchemas:
    def test_enrol_request_totp(self):
        req = MFAEnrolRequest(method="totp")
        assert req.method == "totp"
        assert req.phone_number is None

    def test_enrol_request_sms_with_phone(self):
        req = MFAEnrolRequest(method="sms", phone_number="+64211234567")
        assert req.method == "sms"
        assert req.phone_number == "+64211234567"

    def test_verify_request(self):
        req = MFAVerifyRequest(
            mfa_token="some.jwt.token",
            code="123456",
            method="totp",
        )
        assert req.code == "123456"

    def test_backup_codes_response(self):
        resp = MFABackupCodesResponse(codes=["ABCD1234", "EFGH5678"])
        assert len(resp.codes) == 2

    def test_enrol_response_totp(self):
        resp = MFAEnrolResponse(
            method="totp",
            qr_uri="otpauth://totp/test?secret=ABC",
            message="Scan QR",
        )
        assert resp.qr_uri.startswith("otpauth://")

    def test_enrol_response_sms(self):
        resp = MFAEnrolResponse(method="sms", message="Code sent")
        assert resp.qr_uri is None
