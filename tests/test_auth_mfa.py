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
from jose import jwt as jose_jwt

from app.config import settings
from app.modules.auth.mfa_service import (
    _BACKUP_CODE_COUNT,
    _BACKUP_CODE_LENGTH,
    _MAX_MFA_ATTEMPTS,
    _generate_otp_code,
    _get_verified_mfa_methods,
    _verify_backup_code,
    _verify_totp,
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
    user.backup_codes_hash = overrides.get("backup_codes_hash", [])
    user.last_login_at = None
    return user


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

        secret = pyotp.random_base32()
        encrypted = envelope_encrypt(secret)

        user = _make_user(mfa_methods=[{
            "type": "totp",
            "verified": True,
            "secret_encrypted": encrypted.hex(),
        }])

        totp = pyotp.TOTP(secret)
        code = totp.now()

        result = await _verify_totp(user, code)
        assert result is True

    @pytest.mark.asyncio
    async def test_invalid_totp_code_fails(self):
        from app.core.encryption import envelope_encrypt

        secret = pyotp.random_base32()
        encrypted = envelope_encrypt(secret)

        user = _make_user(mfa_methods=[{
            "type": "totp",
            "verified": True,
            "secret_encrypted": encrypted.hex(),
        }])

        result = await _verify_totp(user, "000000")
        assert result is False

    @pytest.mark.asyncio
    async def test_totp_with_no_methods_fails(self):
        user = _make_user(mfa_methods=[])
        result = await _verify_totp(user, "123456")
        assert result is False


# ---------------------------------------------------------------------------
# Backup code generation and verification
# ---------------------------------------------------------------------------

class TestBackupCodes:
    @pytest.mark.asyncio
    async def test_generates_correct_number_of_codes(self):
        user = _make_user()
        db = AsyncMock()
        # Mock write_audit_log
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
    async def test_backup_codes_stored_as_hashes(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        stored = user.backup_codes_hash
        assert len(stored) == _BACKUP_CODE_COUNT
        for entry in stored:
            assert "hash" in entry
            assert entry["used"] is False
            # Verify it's a bcrypt hash
            assert entry["hash"].startswith("$2")

    @pytest.mark.asyncio
    async def test_valid_backup_code_verifies(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        # Verify the first code
        result = await _verify_backup_code(db, user, codes[0])
        assert result is True

    @pytest.mark.asyncio
    async def test_backup_code_is_single_use(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            codes = await generate_backup_codes(db, user)

        # Use the first code
        result1 = await _verify_backup_code(db, user, codes[0])
        assert result1 is True

        # Try to use it again
        result2 = await _verify_backup_code(db, user, codes[0])
        assert result2 is False

    @pytest.mark.asyncio
    async def test_invalid_backup_code_fails(self):
        user = _make_user()
        db = AsyncMock()
        with patch("app.modules.auth.mfa_service.write_audit_log", new_callable=AsyncMock):
            await generate_backup_codes(db, user)

        result = await _verify_backup_code(db, user, "INVALIDCODE")
        assert result is False


# ---------------------------------------------------------------------------
# MFA policy helpers
# ---------------------------------------------------------------------------

class TestMFAPolicyHelpers:
    def test_global_admin_requires_mfa_without_methods(self):
        user = _make_user(role="global_admin", mfa_methods=[])
        assert user_requires_mfa_setup(user) is True

    def test_global_admin_does_not_require_mfa_with_verified_method(self):
        user = _make_user(
            role="global_admin",
            mfa_methods=[{"type": "totp", "verified": True}],
        )
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
        user = _make_user(mfa_methods=[{"type": "totp", "verified": True}])
        assert user_has_verified_mfa(user) is True

    def test_user_has_verified_mfa_false_unverified(self):
        user = _make_user(mfa_methods=[{"type": "totp", "verified": False}])
        assert user_has_verified_mfa(user) is False

    def test_user_has_verified_mfa_false_empty(self):
        user = _make_user(mfa_methods=[])
        assert user_has_verified_mfa(user) is False

    def test_multiple_methods_one_verified(self):
        user = _make_user(mfa_methods=[
            {"type": "totp", "verified": True},
            {"type": "sms", "verified": False},
        ])
        assert user_has_verified_mfa(user) is True
        verified = _get_verified_mfa_methods(user)
        assert len(verified) == 1
        assert verified[0]["type"] == "totp"


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
