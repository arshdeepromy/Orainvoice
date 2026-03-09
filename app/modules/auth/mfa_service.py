"""MFA enrolment, verification, and backup code business logic.

Supports TOTP (authenticator app), SMS OTP (Twilio), and email OTP.
Users can enrol in multiple MFA methods simultaneously with a fallback chain.
Global_Admin accounts are required to have MFA on every login.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt as bcrypt_lib
import pyotp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import write_audit_log
from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.auth.jwt import create_access_token, create_refresh_token
from app.modules.auth.models import Session, User
from app.modules.auth.schemas import MFAEnrolResponse, TokenResponse

logger = logging.getLogger(__name__)

# OTP code length and expiry
_OTP_LENGTH = 6
_OTP_EXPIRY_SECONDS = 300  # 5 minutes
_MAX_MFA_ATTEMPTS = 5
_BACKUP_CODE_COUNT = 10
_BACKUP_CODE_LENGTH = 8


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hash of the refresh token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_otp_code() -> str:
    """Generate a random 6-digit OTP code."""
    return "".join([str(secrets.randbelow(10)) for _ in range(_OTP_LENGTH)])


async def _store_otp_in_redis(user_id: uuid.UUID, method: str, code: str) -> None:
    """Store an OTP code in Redis with expiry for SMS/email verification."""
    from app.core.redis import redis_pool

    key = f"mfa:otp:{method}:{user_id}"
    await redis_pool.setex(key, _OTP_EXPIRY_SECONDS, code)


async def _get_otp_from_redis(user_id: uuid.UUID, method: str) -> str | None:
    """Retrieve a stored OTP code from Redis."""
    from app.core.redis import redis_pool

    key = f"mfa:otp:{method}:{user_id}"
    val = await redis_pool.get(key)
    if val is None:
        return None
    return val.decode() if isinstance(val, bytes) else val


async def _delete_otp_from_redis(user_id: uuid.UUID, method: str) -> None:
    """Delete an OTP code from Redis after use."""
    from app.core.redis import redis_pool

    key = f"mfa:otp:{method}:{user_id}"
    await redis_pool.delete(key)


async def _get_mfa_attempt_count(user_id: uuid.UUID) -> int:
    """Get the current MFA failure attempt count from Redis."""
    from app.core.redis import redis_pool

    key = f"mfa:attempts:{user_id}"
    val = await redis_pool.get(key)
    if val is None:
        return 0
    return int(val)


async def _increment_mfa_attempts(user_id: uuid.UUID) -> int:
    """Increment MFA failure counter. Returns new count."""
    from app.core.redis import redis_pool

    key = f"mfa:attempts:{user_id}"
    count = await redis_pool.incr(key)
    # Expire after 15 minutes
    await redis_pool.expire(key, 900)
    return count


async def _reset_mfa_attempts(user_id: uuid.UUID) -> None:
    """Reset MFA failure counter on success."""
    from app.core.redis import redis_pool

    key = f"mfa:attempts:{user_id}"
    await redis_pool.delete(key)


async def _send_sms_otp(phone_number: str, code: str) -> None:
    """Send an OTP code via Twilio SMS.

    In production this dispatches via the Twilio integration.
    For now we log the intent so the flow is wired up.
    """
    logger.info("SMS OTP queued for %s: code=%s", phone_number, code)
    # TODO: Replace with actual Twilio call once Notification_Module is implemented.


async def _send_email_otp(email: str, code: str) -> None:
    """Send an OTP code via email.

    In production this dispatches via the Brevo/SendGrid integration.
    For now we log the intent so the flow is wired up.
    """
    logger.info("Email OTP queued for %s: code=%s", email, code)
    # TODO: Replace with actual email send once Notification_Module is implemented.


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------

async def enrol_mfa(
    db: AsyncSession,
    user: User,
    method: str,
    phone_number: str | None = None,
) -> MFAEnrolResponse:
    """Start MFA enrolment for a given method.

    - TOTP: generates secret, returns QR code URI
    - SMS: stores phone number, sends verification code
    - Email: sends verification code to user's email
    """
    if method not in ("totp", "sms", "email"):
        raise ValueError(f"Unsupported MFA method: {method}")

    if method == "totp":
        return await _enrol_totp(db, user)
    elif method == "sms":
        if not phone_number:
            raise ValueError("phone_number is required for SMS MFA enrolment")
        return await _enrol_sms(db, user, phone_number)
    else:
        return await _enrol_email(db, user)


async def _enrol_totp(db: AsyncSession, user: User) -> MFAEnrolResponse:
    """Generate TOTP secret and return QR code URI."""
    secret = pyotp.random_base32()

    # Encrypt and store the secret
    encrypted_secret = envelope_encrypt(secret)

    # Store pending enrolment in the mfa_methods JSONB
    mfa_methods = list(user.mfa_methods or [])

    # Remove any existing unverified TOTP entry
    mfa_methods = [m for m in mfa_methods if not (
        isinstance(m, dict) and m.get("type") == "totp" and not m.get("verified")
    )]

    mfa_methods.append({
        "type": "totp",
        "verified": False,
        "secret_encrypted": encrypted_secret.hex(),
        "enrolled_at": datetime.now(timezone.utc).isoformat(),
    })
    user.mfa_methods = mfa_methods

    # Generate the otpauth:// URI for QR code
    totp = pyotp.TOTP(secret)
    qr_uri = totp.provisioning_uri(
        name=user.email,
        issuer_name=settings.app_name,
    )

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_enrol_started",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": "totp"},
    )

    return MFAEnrolResponse(
        method="totp",
        qr_uri=qr_uri,
        message="Scan the QR code with your authenticator app, then verify with a 6-digit code.",
    )


async def _enrol_sms(
    db: AsyncSession, user: User, phone_number: str
) -> MFAEnrolResponse:
    """Store phone number and send verification OTP via SMS."""
    mfa_methods = list(user.mfa_methods or [])

    # Remove any existing unverified SMS entry
    mfa_methods = [m for m in mfa_methods if not (
        isinstance(m, dict) and m.get("type") == "sms" and not m.get("verified")
    )]

    mfa_methods.append({
        "type": "sms",
        "phone": phone_number,
        "verified": False,
        "enrolled_at": datetime.now(timezone.utc).isoformat(),
    })
    user.mfa_methods = mfa_methods

    # Generate and send OTP
    code = _generate_otp_code()
    await _store_otp_in_redis(user.id, "sms", code)
    await _send_sms_otp(phone_number, code)

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_enrol_started",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": "sms", "phone": phone_number},
    )

    return MFAEnrolResponse(
        method="sms",
        message=f"A 6-digit code has been sent to {phone_number}. Enter it to complete enrolment.",
    )


async def _enrol_email(db: AsyncSession, user: User) -> MFAEnrolResponse:
    """Send verification OTP to user's email."""
    mfa_methods = list(user.mfa_methods or [])

    # Remove any existing unverified email entry
    mfa_methods = [m for m in mfa_methods if not (
        isinstance(m, dict) and m.get("type") == "email" and not m.get("verified")
    )]

    mfa_methods.append({
        "type": "email",
        "verified": False,
        "enrolled_at": datetime.now(timezone.utc).isoformat(),
    })
    user.mfa_methods = mfa_methods

    # Generate and send OTP
    code = _generate_otp_code()
    await _store_otp_in_redis(user.id, "email", code)
    await _send_email_otp(user.email, code)

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_enrol_started",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": "email"},
    )

    return MFAEnrolResponse(
        method="email",
        message="A 6-digit code has been sent to your email. Enter it to complete enrolment.",
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

async def verify_mfa(
    db: AsyncSession,
    mfa_token: str,
    code: str,
    method: str,
    ip_address: str | None = None,
    device_type: str | None = None,
    browser: str | None = None,
) -> TokenResponse:
    """Verify a 6-digit MFA code and issue JWT tokens on success.

    Supports TOTP, SMS, email, and backup code methods.
    Locks after 5 consecutive failures.
    """
    from jose import JWTError
    from jose import jwt as jose_jwt

    # Decode the mfa_token to get user_id
    try:
        payload = jose_jwt.decode(
            mfa_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        raise ValueError("Invalid or expired MFA token")

    if payload.get("type") != "mfa_pending":
        raise ValueError("Invalid MFA token type")

    user_id = uuid.UUID(payload["user_id"])

    # Check attempt count
    attempts = await _get_mfa_attempt_count(user_id)
    if attempts >= _MAX_MFA_ATTEMPTS:
        raise ValueError("MFA verification locked due to too many failed attempts. Try again later.")

    # Load user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("User not found or inactive")

    # Verify based on method
    if method == "totp":
        verified = await _verify_totp(user, code)
    elif method == "sms":
        verified = await _verify_otp_redis(user.id, "sms", code)
    elif method == "email":
        verified = await _verify_otp_redis(user.id, "email", code)
    elif method == "backup":
        verified = await _verify_backup_code(db, user, code)
    else:
        raise ValueError(f"Unsupported MFA method: {method}")

    if not verified:
        new_count = await _increment_mfa_attempts(user_id)
        await write_audit_log(
            session=db,
            org_id=user.org_id,
            user_id=user.id,
            action="auth.mfa_verify_failed",
            entity_type="user",
            entity_id=user.id,
            after_value={
                "method": method,
                "attempt_count": new_count,
                "ip_address": ip_address,
            },
            ip_address=ip_address,
        )
        if new_count >= _MAX_MFA_ATTEMPTS:
            raise ValueError("MFA verification locked due to too many failed attempts. Try again later.")
        raise ValueError("Invalid MFA code")

    # Success — reset attempts and mark method as verified if pending enrolment
    await _reset_mfa_attempts(user_id)
    await _mark_method_verified(user, method)

    # Issue JWT pair
    # Global admins should not have org_id in their JWT (they access all orgs)
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
    )
    refresh_token = create_refresh_token()

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )

    family_id = uuid.uuid4()
    session = Session(
        user_id=user.id,
        org_id=user.org_id,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        family_id=family_id,
        device_type=device_type,
        browser=browser,
        ip_address=ip_address,
        expires_at=expires_at,
    )
    db.add(session)

    user.last_login_at = datetime.now(timezone.utc)

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_verify_success",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "method": method,
            "ip_address": ip_address,
            "device_type": device_type,
            "browser": browser,
        },
        ip_address=ip_address,
        device_info=f"{device_type}; {browser}" if device_type or browser else None,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


async def _verify_totp(user: User, code: str) -> bool:
    """Verify a TOTP code against the user's stored encrypted secret."""
    mfa_methods = user.mfa_methods or []
    for m in mfa_methods:
        if isinstance(m, dict) and m.get("type") == "totp" and m.get("secret_encrypted"):
            try:
                encrypted_hex = m["secret_encrypted"]
                secret = envelope_decrypt_str(bytes.fromhex(encrypted_hex))
                totp = pyotp.TOTP(secret)
                if totp.verify(code, valid_window=1):
                    return True
            except Exception:
                logger.exception("Failed to verify TOTP code")
                continue
    return False


async def _verify_otp_redis(
    user_id: uuid.UUID, method: str, code: str
) -> bool:
    """Verify an OTP code stored in Redis (for SMS/email)."""
    stored_code = await _get_otp_from_redis(user_id, method)
    if stored_code is None:
        return False
    if secrets.compare_digest(stored_code, code):
        await _delete_otp_from_redis(user_id, method)
        return True
    return False


async def _verify_backup_code(
    db: AsyncSession, user: User, code: str
) -> bool:
    """Verify a backup code against stored hashed codes. Single-use."""
    backup_codes = user.backup_codes_hash or []
    for i, entry in enumerate(backup_codes):
        if isinstance(entry, dict) and not entry.get("used", False):
            if bcrypt_lib.checkpw(code.encode("utf-8"), entry["hash"].encode("utf-8")):
                # Mark as used
                updated_codes = list(backup_codes)
                updated_codes[i] = {**entry, "used": True}
                user.backup_codes_hash = updated_codes
                return True
    return False


async def _mark_method_verified(user: User, method: str) -> None:
    """Mark an MFA method as verified after successful code entry."""
    if method == "backup":
        return  # Backup codes don't need verification marking

    mfa_methods = list(user.mfa_methods or [])
    updated = False
    for i, m in enumerate(mfa_methods):
        if isinstance(m, dict) and m.get("type") == method and not m.get("verified"):
            mfa_methods[i] = {**m, "verified": True}
            updated = True
            break

    if updated:
        user.mfa_methods = mfa_methods


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------

async def generate_backup_codes(
    db: AsyncSession,
    user: User,
) -> list[str]:
    """Generate 10 single-use backup recovery codes.

    Each code is 8 random alphanumeric characters. Codes are hashed with
    bcrypt before storage. The plain codes are returned once for the user
    to save — they cannot be retrieved again.
    """
    plain_codes: list[str] = []
    hashed_entries: list[dict] = []

    for _ in range(_BACKUP_CODE_COUNT):
        code = secrets.token_hex(_BACKUP_CODE_LENGTH // 2).upper()
        plain_codes.append(code)
        hashed_entries.append({
            "hash": bcrypt_lib.hashpw(code.encode("utf-8"), bcrypt_lib.gensalt()).decode("utf-8"),
            "used": False,
        })

    user.backup_codes_hash = hashed_entries

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.backup_codes_generated",
        entity_type="user",
        entity_id=user.id,
        after_value={"count": _BACKUP_CODE_COUNT},
    )

    return plain_codes


# ---------------------------------------------------------------------------
# MFA policy helpers
# ---------------------------------------------------------------------------

def user_requires_mfa_setup(user: User, org_settings: dict | None = None) -> bool:
    """Check if a user needs to set up MFA before accessing the platform.

    Returns True if:
    - User is a Global_Admin (MFA always required)
    - Org has MFA set to mandatory and user has no verified MFA methods
    """
    # Global_Admin always requires MFA
    if user.role == "global_admin":
        verified = _get_verified_mfa_methods(user)
        return len(verified) == 0

    # Check org MFA policy
    if org_settings and org_settings.get("mfa_policy") == "mandatory":
        verified = _get_verified_mfa_methods(user)
        return len(verified) == 0

    return False


def user_has_verified_mfa(user: User) -> bool:
    """Check if the user has at least one verified MFA method."""
    return len(_get_verified_mfa_methods(user)) > 0


def _get_verified_mfa_methods(user: User) -> list[dict]:
    """Return list of verified MFA method entries."""
    mfa_methods = user.mfa_methods or []
    return [
        m for m in mfa_methods
        if isinstance(m, dict) and m.get("verified", False)
    ]
