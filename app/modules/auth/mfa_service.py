"""MFA enrolment, verification, and backup code business logic.

Supports TOTP (authenticator app), SMS OTP (Connexus), and email OTP.
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
from sqlalchemy import delete, select, update
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
_OTP_EXPIRY_SMS = 300  # 5 minutes for SMS
_OTP_EXPIRY_EMAIL = 600  # 10 minutes for email
_OTP_EXPIRY_SECONDS = _OTP_EXPIRY_SMS  # default / legacy alias
_MAX_MFA_ATTEMPTS = 5
_BACKUP_CODE_COUNT = 10
_BACKUP_CODE_LENGTH = 8


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hash of the refresh token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_otp_code() -> str:
    """Generate a random 6-digit OTP code."""
    return "".join([str(secrets.randbelow(10)) for _ in range(_OTP_LENGTH)])


async def _store_otp_in_redis(user_id: uuid.UUID, method: str, code: str, ttl: int | None = None) -> None:
    """Store an OTP code in Redis with expiry for SMS/email verification."""
    from app.core.redis import redis_pool

    key = f"mfa:otp:{method}:{user_id}"
    if ttl is None:
        ttl = _OTP_EXPIRY_EMAIL if method == "email" else _OTP_EXPIRY_SMS
    await redis_pool.setex(key, ttl, code)


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


# ---------------------------------------------------------------------------
# MFA challenge session (Redis-based)
# ---------------------------------------------------------------------------

_CHALLENGE_TTL = 300  # 5 minutes
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = 900  # 15 minutes


async def _store_challenge_session(
    mfa_token: str, user_id: uuid.UUID, methods: list[str],
    phone_number: str | None = None,
) -> None:
    """Store an MFA challenge session in Redis keyed by sha256(mfa_token)."""
    import json

    from app.core.redis import redis_pool

    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    key = f"mfa:challenge:{token_hash}"
    data_dict: dict = {"user_id": str(user_id), "methods": methods}
    if phone_number:
        data_dict["phone_number"] = phone_number
    data = json.dumps(data_dict)
    await redis_pool.setex(key, _CHALLENGE_TTL, data)


async def _get_challenge_session(mfa_token: str) -> dict | None:
    """Retrieve an MFA challenge session from Redis. Returns None if expired/missing."""
    import json

    from app.core.redis import redis_pool

    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    key = f"mfa:challenge:{token_hash}"
    val = await redis_pool.get(key)
    if val is None:
        return None
    raw = val.decode() if isinstance(val, bytes) else val
    return json.loads(raw)


async def _delete_challenge_session(mfa_token: str) -> None:
    """Delete an MFA challenge session from Redis after successful verification."""
    from app.core.redis import redis_pool

    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    key = f"mfa:challenge:{token_hash}"
    await redis_pool.delete(key)


class OTPRateLimitExceeded(Exception):
    """Raised when OTP send rate limit is exceeded.

    Carries ``retry_after`` seconds so the caller can include a
    ``Retry-After`` header in the HTTP 429 response.
    """

    def __init__(self, retry_after: int, message: str | None = None):
        self.retry_after = retry_after
        super().__init__(
            message or "Too many code requests. Please wait before requesting a new code."
        )


async def check_otp_rate_limit(user_id: uuid.UUID, method: str) -> None:
    """Enforce OTP send rate limit: 5 per method per 15 minutes.

    Uses a Redis counter keyed by method and user_id.
    Raises ``OTPRateLimitExceeded`` (with ``retry_after`` seconds) if the
    limit is exceeded.

    Requirements: 9.1, 9.2, 9.3
    """
    from app.core.redis import redis_pool

    key = f"mfa:rate:{method}:{user_id}"
    val = await redis_pool.get(key)
    count = int(val) if val else 0

    if count >= _RATE_LIMIT_MAX:
        # Determine how many seconds remain on the rate-limit window
        ttl = await redis_pool.ttl(key)
        retry_after = max(ttl, 1)  # at least 1 second
        raise OTPRateLimitExceeded(retry_after=retry_after)

    pipe = redis_pool.pipeline()
    pipe.incr(key)
    pipe.expire(key, _RATE_LIMIT_WINDOW)
    await pipe.execute()


async def send_challenge_otp(
    db: AsyncSession,
    user_id: uuid.UUID,
    method: str,
    mfa_token: str,
) -> None:
    """Send an OTP for the selected method during the MFA login challenge.

    Validates the mfa_token against Redis, checks rate limit, then sends
    the OTP via the configured MFA default SMS provider or email.

    Requirements: 6.3, 6.4, 9.1
    """
    from app.modules.auth.models import UserMfaMethod

    if method not in ("sms", "email"):
        raise ValueError(f"Cannot send challenge OTP for method: {method}")

    # Validate the challenge session
    session_data = await _get_challenge_session(mfa_token)
    if session_data is None:
        raise ValueError("Invalid or expired MFA token")

    session_user_id = uuid.UUID(session_data["user_id"])
    if session_user_id != user_id:
        raise ValueError("Invalid or expired MFA token")

    if method not in session_data.get("methods", []):
        raise ValueError(f"Method '{method}' is not available for this challenge")

    # Enforce rate limit
    await check_otp_rate_limit(user_id, method)

    # Look up the verified method to get phone number (SMS) or email
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("User not found or inactive")

    # Generate and send OTP
    code = _generate_otp_code()

    if method == "sms":
        # Get phone number from the verified SMS method
        stmt = select(UserMfaMethod).where(
            UserMfaMethod.user_id == user_id,
            UserMfaMethod.method == "sms",
            UserMfaMethod.verified == True,  # noqa: E712
        )
        mfa_result = await db.execute(stmt)
        sms_method = mfa_result.scalar_one_or_none()
        if sms_method is None or not sms_method.phone_number:
            raise ValueError("No verified SMS method found")
        await _store_otp_in_redis(user_id, "sms", code)
        await _send_sms_otp(db, sms_method.phone_number, code)
    else:
        # Email — send to user's registered email
        await _store_otp_in_redis(user_id, "email", code)
        await _send_email_otp(db, user.email, code)


async def _get_platform_name(db: AsyncSession) -> str:
    """Resolve the platform display name from the branding table.

    Falls back to ``"OraInvoice"`` if no branding row exists.
    """
    from app.modules.branding.models import PlatformBranding

    result = await db.execute(
        select(PlatformBranding).order_by(PlatformBranding.created_at).limit(1)
    )
    branding = result.scalar_one_or_none()
    return branding.platform_name if branding else "OraInvoice"


async def _resolve_mfa_sms_provider(db: AsyncSession):
    """Resolve the SMS provider configured as the MFA default.

    Uses the same selection logic as the ``/auth/mfa/provider-config``
    endpoint: checks the ``mfa_default`` flag in provider config first,
    then falls back to ``is_default``, then first active provider.

    Returns the ``SmsVerificationProvider`` row or ``None``.
    """
    from app.modules.admin.models import SmsVerificationProvider

    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.is_active == True,  # noqa: E712
        )
    )
    providers = result.scalars().all()

    mfa_provider = None
    for p in providers:
        if p.config and p.config.get("mfa_default"):
            mfa_provider = p
            break

    if mfa_provider is None:
        for p in providers:
            if p.is_default:
                mfa_provider = p
                break
        if mfa_provider is None and providers:
            mfa_provider = providers[0]

    logger.info(
        "MFA SMS provider resolution: %d active providers, selected=%s (key=%s, mfa_default=%s, is_default=%s)",
        len(providers),
        mfa_provider.display_name if mfa_provider else None,
        mfa_provider.provider_key if mfa_provider else None,
        mfa_provider.config.get("mfa_default") if mfa_provider and mfa_provider.config else None,
        mfa_provider.is_default if mfa_provider else None,
    )

    return mfa_provider


async def _send_sms_otp(db: AsyncSession, phone_number: str, code: str) -> None:
    """Send an OTP code via the configured MFA SMS provider.

    Resolves the MFA default provider (respecting the ``mfa_default``
    flag), then dispatches via the appropriate client.  For Firebase,
    this is a no-op because the frontend sends the SMS client-side.

    Raises ``RuntimeError`` on delivery failure so the caller can
    surface a user-friendly error.
    """
    import json

    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import SmsVerificationProvider

    provider = await _resolve_mfa_sms_provider(db)
    if provider is None:
        raise RuntimeError("SMS provider is not configured or active")

    # Firebase Phone Auth sends SMS client-side via the JS SDK —
    # the backend should not attempt to send an OTP.
    if provider.provider_key == "firebase_phone_auth":
        logger.info(
            "MFA default is Firebase Phone Auth — skipping server-side OTP send for %s",
            phone_number,
        )
        return

    # Server-side send via Connexus (or any future server-side provider)
    from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
    from app.integrations.sms_types import SmsMessage

    creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
    if provider.config and provider.config.get("token_refresh_interval_seconds"):
        creds["token_refresh_interval_seconds"] = provider.config["token_refresh_interval_seconds"]
    config = ConnexusConfig.from_dict(creds)
    client = ConnexusSmsClient(config)

    platform_name = await _get_platform_name(db)

    try:
        sms = SmsMessage(to_number=phone_number, body=f"Your {platform_name} verification code is: {code}")
        send_result = await client.send(sms)
        if not send_result.success:
            logger.error("SMS delivery failed for %s: %s", phone_number, send_result.error)
            raise RuntimeError("SMS could not be delivered. Please try again.")
    finally:
        await client.close()


async def _send_email_otp(db: AsyncSession, email: str, code: str) -> None:
    """Send an OTP code via the active EmailProvider (highest priority).

    Resolves the active ``EmailProvider`` with the highest priority,
    decrypts its SMTP credentials, and sends a branded OTP email.
    Falls back to the legacy ``IntegrationConfig`` SMTP entry if no
    ``EmailProvider`` is active.

    Raises ``RuntimeError`` if no email provider is configured.
    """
    import json
    import smtplib
    import ssl
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import EmailProvider

    # Resolve the active provider with highest priority (lowest number = highest priority)
    stmt = (
        select(EmailProvider)
        .where(
            EmailProvider.is_active == True,  # noqa: E712
            EmailProvider.credentials_set == True,  # noqa: E712
        )
        .order_by(EmailProvider.priority)
        .limit(1)
    )
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()

    if provider is None or not provider.credentials_encrypted:
        raise RuntimeError("No active email provider configured. Please set up an email provider in admin settings.")

    # Decrypt credentials
    try:
        creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
    except Exception:
        logger.exception("Failed to decrypt email provider credentials for %s", provider.provider_key)
        raise RuntimeError("Email provider credentials could not be decrypted")

    smtp_host = provider.smtp_host
    smtp_port = provider.smtp_port or 587
    smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
    username = creds.get("username") or creds.get("api_key", "")
    password = creds.get("password") or creds.get("api_key", "")

    config = provider.config or {}
    from_email = config.get("from_email", "noreply@oraflows.co.nz")
    from_name = config.get("from_name", "OraInvoice")

    if not smtp_host:
        # Fallback hosts for known providers
        _default_hosts = {
            "brevo": "smtp-relay.brevo.com",
            "sendgrid": "smtp.sendgrid.net",
            "gmail": "smtp.gmail.com",
            "outlook": "smtp.office365.com",
            "mailgun": "smtp.mailgun.org",
        }
        smtp_host = _default_hosts.get(provider.provider_key)
        if not smtp_host:
            raise RuntimeError(f"SMTP host not configured for email provider '{provider.display_name}'")

    platform_name = await _get_platform_name(db)

    # Build the email
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = email
    msg["Subject"] = f"Your {platform_name} verification code"

    text_body = (
        f"Your {platform_name} verification code is: {code}\n\n"
        "This code expires in 10 minutes. If you did not request this, please ignore this email."
    )
    html_body = (
        f'<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px">'
        f'<h2 style="color:#2563EB;margin-bottom:16px">{platform_name}</h2>'
        f'<p>Your verification code is:</p>'
        f'<p style="font-size:32px;font-weight:bold;letter-spacing:4px;color:#1E40AF;'
        f'background:#F0F4FF;padding:16px;border-radius:8px;text-align:center">{code}</p>'
        f'<p style="color:#6B7280;font-size:14px">This code expires in 10 minutes.<br>'
        f'If you did not request this, please ignore this email.</p></div>'
    )
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    # Send via SMTP
    try:
        if smtp_encryption == "ssl":
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            if smtp_encryption == "tls":
                server.starttls(context=ssl.create_default_context())

        if username and password:
            server.login(username, password)

        server.sendmail(from_email, email, msg.as_string())
        server.quit()
        logger.info("Email OTP sent to %s via %s", email, provider.provider_key)
    except Exception:
        logger.exception("Failed to send email OTP to %s via %s", email, provider.provider_key)
        raise RuntimeError("Verification email could not be sent. Please try again.")


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

    - TOTP: generates RFC 6238 secret (30s step, SHA-1), returns QR URI + plain secret
    - SMS: validates phone, sends OTP via configured MFA provider (Firebase or Connexus)
    - Email: sends 6-digit OTP to registered email, stores OTP in Redis (600s TTL)

    Stores a pending (unverified) record in the ``user_mfa_methods`` table.
    SMS and email enrolment are subject to OTP rate limiting.
    """
    if method not in ("totp", "sms", "email"):
        raise ValueError(f"Unsupported MFA method: {method}")

    # Rate-limit OTP sends for SMS/email enrolment
    if method in ("sms", "email"):
        await check_otp_rate_limit(user.id, method)

    if method == "totp":
        return await _enrol_totp(db, user)
    elif method == "sms":
        if not phone_number:
            raise ValueError("phone_number is required for SMS MFA enrolment")
        return await _enrol_sms(db, user, phone_number)
    else:
        return await _enrol_email(db, user)


async def _enrol_totp(db: AsyncSession, user: User) -> MFAEnrolResponse:
    """Generate TOTP secret (RFC 6238, 30s step, SHA-1) and return QR URI + plain secret.

    Creates or replaces a pending (unverified) ``UserMfaMethod`` record.
    """
    from app.modules.auth.models import UserMfaMethod

    secret = pyotp.random_base32()

    # Encrypt the secret for storage
    encrypted_secret = envelope_encrypt(secret)

    # Upsert: remove any existing unverified TOTP entry for this user
    existing_stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == "totp",
        UserMfaMethod.verified == False,  # noqa: E712
    )
    result = await db.execute(existing_stmt)
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    # Create pending enrolment record
    mfa_record = UserMfaMethod(
        user_id=user.id,
        method="totp",
        verified=False,
        secret_encrypted=encrypted_secret,
    )
    db.add(mfa_record)

    # Generate the otpauth:// URI for QR code (RFC 6238: 30s step, SHA-1)
    totp = pyotp.TOTP(secret)
    platform_name = await _get_platform_name(db)
    qr_uri = totp.provisioning_uri(
        name=user.email,
        issuer_name=platform_name,
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
        secret=secret,
        message="Scan the QR code with your authenticator app, then verify with a 6-digit code.",
    )


async def _enrol_sms(
    db: AsyncSession, user: User, phone_number: str
) -> MFAEnrolResponse:
    """Validate phone number, send 6-digit OTP, store OTP in Redis (300s TTL).

    Creates or replaces a pending (unverified) ``UserMfaMethod`` record.
    When the MFA default provider is Firebase, the OTP is NOT sent
    server-side — the response includes ``provider`` and ``firebase_config``
    so the frontend can use the Firebase JS SDK to send the SMS.
    """
    import json

    from app.core.encryption import envelope_decrypt_str
    from app.modules.auth.models import UserMfaMethod

    # Remove any existing unverified SMS entry for this user
    existing_stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == "sms",
        UserMfaMethod.verified == False,  # noqa: E712
    )
    result = await db.execute(existing_stmt)
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    # Create pending enrolment record with phone number
    mfa_record = UserMfaMethod(
        user_id=user.id,
        method="sms",
        verified=False,
        phone_number=phone_number,
    )
    db.add(mfa_record)

    # Resolve the MFA default provider
    provider = await _resolve_mfa_sms_provider(db)
    is_firebase = provider and provider.provider_key == "firebase_phone_auth"
    logger.info(
        "SMS MFA enrol: resolved provider=%s, is_firebase=%s",
        provider.provider_key if provider else None,
        is_firebase,
    )

    # Generate and store OTP only for non-Firebase providers.
    # Firebase Phone Auth generates and verifies its own codes client-side.
    if not is_firebase:
        code = _generate_otp_code()
        await _store_otp_in_redis(user.id, "sms", code)

    # For non-Firebase providers, send the OTP server-side
    if not is_firebase:
        await _send_sms_otp(db, phone_number, code)

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_enrol_started",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": "sms", "phone": phone_number},
    )

    # Build response with provider info
    firebase_config = None
    provider_key = provider.provider_key if provider else None
    if is_firebase and provider.credentials_encrypted:
        try:
            creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
            firebase_config = {
                "apiKey": creds.get("api_key", ""),
                "projectId": creds.get("project_id", ""),
                "appId": creds.get("app_id", ""),
                "authDomain": f"{creds.get('project_id', '')}.firebaseapp.com",
            }
        except Exception:
            logger.exception("Failed to decrypt Firebase credentials for MFA enrolment")

    # If Firebase is the provider but we couldn't build the config, that's
    # an error — we already skipped the server-side send above.
    if is_firebase and not firebase_config:
        raise RuntimeError(
            "Firebase is the MFA default but credentials could not be loaded. "
            "Please contact your administrator."
        )

    message = (
        f"Use your authenticator to verify {phone_number}."
        if is_firebase
        else f"A 6-digit code has been sent to {phone_number}. Enter it to complete enrolment."
    )

    return MFAEnrolResponse(
        method="sms",
        message=message,
        provider=provider_key,
        firebase_config=firebase_config,
        phone_number=phone_number if is_firebase else None,
    )


async def _enrol_email(db: AsyncSession, user: User) -> MFAEnrolResponse:
    """Send 6-digit OTP to user's registered email, store OTP in Redis (600s TTL).

    Creates or replaces a pending (unverified) ``UserMfaMethod`` record.
    """
    from app.modules.auth.models import UserMfaMethod

    # Remove any existing unverified email entry for this user
    existing_stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == "email",
        UserMfaMethod.verified == False,  # noqa: E712
    )
    result = await db.execute(existing_stmt)
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.flush()

    # Create pending enrolment record
    mfa_record = UserMfaMethod(
        user_id=user.id,
        method="email",
        verified=False,
    )
    db.add(mfa_record)

    # Generate and send OTP (600s TTL for email)
    code = _generate_otp_code()
    await _store_otp_in_redis(user.id, "email", code)
    await _send_email_otp(db, user.email, code)

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
# Enrolment verification
# ---------------------------------------------------------------------------

async def verify_enrolment(
    db: AsyncSession,
    user: User,
    method: str,
    code: str,
) -> None:
    """Verify an enrolment code and activate the MFA method.

    - TOTP: decrypt stored secret, validate code with pyotp (±1 window tolerance),
      mark verified=True, persist encrypted secret.
    - SMS/Email: validate code against Redis OTP, consume OTP on success,
      mark verified=True. Phone number for SMS is already persisted during enrolment.
    - Raises ValueError for invalid/expired codes or missing pending enrolment.

    Requirements: 1.3, 1.4, 2.3, 2.4, 3.3, 3.4
    """
    from app.modules.auth.models import UserMfaMethod

    if method not in ("totp", "sms", "email"):
        raise ValueError(f"Unsupported MFA method: {method}")

    # Look up the pending (unverified) enrolment record
    stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == method,
        UserMfaMethod.verified == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    pending = result.scalar_one_or_none()
    if pending is None:
        raise ValueError(f"No pending {method} enrolment found for this user")

    # Verify the code based on method type
    if method == "totp":
        await _verify_totp_enrolment(pending, code)
    else:
        # SMS or Email — validate against Redis OTP
        await _verify_otp_enrolment(user.id, method, code)

    # Mark the method as verified
    now = datetime.now(timezone.utc)
    pending.verified = True
    pending.verified_at = now

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_enrol_verified",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": method},
    )


async def _verify_totp_enrolment(pending, code: str) -> None:
    """Validate a TOTP code against the pending enrolment's encrypted secret.

    Uses pyotp with valid_window=1 (±1 time step tolerance).
    Raises ValueError if the code is invalid.
    """
    if not pending.secret_encrypted:
        raise ValueError("No TOTP secret found for pending enrolment")

    try:
        secret = envelope_decrypt_str(pending.secret_encrypted)
    except Exception:
        logger.exception("Failed to decrypt TOTP secret for enrolment verification")
        raise ValueError("Failed to verify TOTP code")

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        raise ValueError("Invalid TOTP code")


async def _verify_otp_enrolment(user_id: uuid.UUID, method: str, code: str) -> None:
    """Validate an OTP code from Redis for SMS/email enrolment.

    Consumes (deletes) the OTP on success.
    Raises ValueError if the code is invalid or expired.
    """
    stored_code = await _get_otp_from_redis(user_id, method)
    if stored_code is None:
        raise ValueError("Invalid or expired verification code")

    if not secrets.compare_digest(stored_code, code):
        raise ValueError("Invalid or expired verification code")

    # Consume the OTP so it cannot be reused
    await _delete_otp_from_redis(user_id, method)


# ---------------------------------------------------------------------------
# MFA status and method management
# ---------------------------------------------------------------------------

_ALL_MFA_METHODS = ("totp", "sms", "email", "passkey")


async def get_user_mfa_status(
    db: AsyncSession,
    user: User,
) -> list["MFAMethodStatus"]:
    """Return the status of all 4 MFA method types for a user.

    Queries ``user_mfa_methods`` for verified records and returns an
    ``MFAMethodStatus`` entry for each of the four method types (totp,
    sms, email, passkey).  SMS entries include a masked phone number
    (e.g. ``"***1234"``).

    Requirements: 4.4
    """
    from app.modules.auth.models import UserMfaMethod
    from app.modules.auth.schemas import MFAMethodStatus

    stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.verified == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    verified_records = {r.method: r for r in result.scalars().all()}

    statuses: list[MFAMethodStatus] = []
    for method in _ALL_MFA_METHODS:
        record = verified_records.get(method)
        if record:
            masked_phone = None
            if method == "sms" and record.phone_number:
                masked_phone = "***" + record.phone_number[-4:]
            statuses.append(
                MFAMethodStatus(
                    method=method,
                    enabled=True,
                    verified_at=record.verified_at,
                    phone_number=masked_phone,
                    is_default=record.is_default,
                )
            )
        else:
            statuses.append(MFAMethodStatus(method=method, enabled=False))

    return statuses


async def disable_mfa_method(
    db: AsyncSession,
    user: User,
    method: str,
    password: str,
) -> None:
    """Disable (remove) an MFA method after password confirmation.

    1. Verify the user's password with bcrypt.
    2. Check the last-method guard: if the organisation requires MFA and
       this is the user's only remaining verified method, reject.
    3. Delete the ``UserMfaMethod`` record (cascading removal of the
       TOTP encrypted secret and SMS phone number stored on the record).

    Requirements: 4.5, 4.6, 7.1, 7.2, 7.3, 7.4
    """
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import UserMfaMethod
    from app.modules.auth.password import verify_password

    # 1. Verify password
    if not user.password_hash or not verify_password(password, user.password_hash):
        raise ValueError("Invalid password")

    # 2. Look up the verified method record
    stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == method,
        UserMfaMethod.verified == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    mfa_record = result.scalar_one_or_none()
    if mfa_record is None:
        raise ValueError(f"MFA method '{method}' is not enabled")

    # 3. Last-method guard — check org MFA policy
    all_verified_stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.verified == True,  # noqa: E712
    )
    all_result = await db.execute(all_verified_stmt)
    verified_count = len(all_result.scalars().all())

    if verified_count <= 1:
        # Check if org requires MFA
        if user.org_id:
            org_result = await db.execute(
                select(Organisation).where(Organisation.id == user.org_id)
            )
            org = org_result.scalar_one_or_none()
            if org and org.settings.get("mfa_policy") == "mandatory":
                raise ValueError(
                    "Cannot disable the last MFA method. "
                    "At least one method is required by your organisation."
                )
        # Global admins always require MFA
        if user.role == "global_admin":
            raise ValueError(
                "Cannot disable the last MFA method. "
                "At least one method is required for global administrators."
            )

    # 4. Delete the method record (TOTP secret and SMS phone number are on the record)
    await db.delete(mfa_record)

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_method_disabled",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": method},
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
    firebase_verified: bool = False,
) -> TokenResponse:
    """Verify a 6-digit MFA code and issue JWT tokens on success.

    Uses Redis-based challenge sessions (not JWT mfa_token).
    Supports TOTP, SMS, email, and backup code methods.
    Locks after 5 consecutive failures.

    Requirements: 6.5, 6.6, 6.7
    """
    # Validate the challenge session from Redis
    session_data = await _get_challenge_session(mfa_token)
    if session_data is None:
        raise ValueError("Invalid or expired MFA token")

    user_id = uuid.UUID(session_data["user_id"])

    # Validate that the requested method is allowed for this challenge session.
    # Backup codes are always permitted as a recovery fallback regardless of
    # which methods were originally offered.
    allowed_methods = session_data.get("methods", [])
    if method != "backup" and allowed_methods and method not in allowed_methods:
        raise ValueError(f"MFA method '{method}' is not enabled for this account")

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
    if firebase_verified and method == "sms":
        verified = True  # Firebase JS SDK already verified the code client-side
    elif method == "totp":
        verified = await _verify_totp_code(db, user, code)
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

    # Success — reset attempts, delete challenge session
    await _reset_mfa_attempts(user_id)
    await _delete_challenge_session(mfa_token)

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


async def _verify_totp_code(db: AsyncSession, user: User, code: str) -> bool:
    """Verify a TOTP code against the user's stored encrypted secret (normalised table)."""
    from app.modules.auth.models import UserMfaMethod

    stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == "totp",
        UserMfaMethod.verified == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    totp_method = result.scalar_one_or_none()
    if totp_method is None or not totp_method.secret_encrypted:
        return False

    try:
        secret = envelope_decrypt_str(totp_method.secret_encrypted)
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except Exception:
        logger.exception("Failed to verify TOTP code")
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
    """Verify a backup code against stored hashed codes (normalised table). Single-use.

    Iterates ``user_backup_codes`` where ``used=False``, bcrypt checks,
    marks ``used=True`` and sets ``used_at`` on match.

    Requirements: 5.6, 6.5
    """
    from app.modules.auth.models import UserBackupCode

    stmt = select(UserBackupCode).where(
        UserBackupCode.user_id == user.id,
        UserBackupCode.used == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    unused_codes = result.scalars().all()

    for backup_code in unused_codes:
        if bcrypt_lib.checkpw(code.encode("utf-8"), backup_code.code_hash.encode("utf-8")):
            backup_code.used = True
            backup_code.used_at = datetime.now(timezone.utc)
            return True
    return False


async def _mark_method_verified(db: AsyncSession, user: User, method: str) -> None:
    """Mark an MFA method as verified after successful code entry (normalised table)."""
    if method == "backup":
        return  # Backup codes don't need verification marking

    from app.modules.auth.models import UserMfaMethod

    stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == method,
        UserMfaMethod.verified == False,  # noqa: E712
    )
    result = await db.execute(stmt)
    pending = result.scalar_one_or_none()
    if pending:
        pending.verified = True
        pending.verified_at = datetime.now(timezone.utc)


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

    Steps:
    1. Delete all existing UserBackupCode records for the user (invalidate
       previous set).
    2. Generate exactly 10 new codes, hash each with bcrypt.
    3. Store new UserBackupCode records with code_hash and used=False.
    4. Write audit log entry.
    5. Return plain-text codes exactly once.

    Requirements: 5.1, 5.2, 5.3
    """
    from app.modules.auth.models import UserBackupCode

    # 1. Invalidate (delete) all previous backup codes for this user
    await db.execute(
        delete(UserBackupCode).where(UserBackupCode.user_id == user.id)
    )

    # 2. Generate 10 alphanumeric codes, hash each with bcrypt
    plain_codes: list[str] = []
    for _ in range(_BACKUP_CODE_COUNT):
        code = secrets.token_hex(_BACKUP_CODE_LENGTH // 2).upper()
        plain_codes.append(code)

        code_hash = bcrypt_lib.hashpw(
            code.encode("utf-8"), bcrypt_lib.gensalt()
        ).decode("utf-8")

        db.add(UserBackupCode(
            user_id=user.id,
            code_hash=code_hash,
            used=False,
        ))

    # 3. Write audit log entry
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.backup_codes_generated",
        entity_type="user",
        entity_id=user.id,
        after_value={"count": _BACKUP_CODE_COUNT},
    )

    # 4. Return plain-text codes exactly once
    return plain_codes



# ---------------------------------------------------------------------------
# MFA policy helpers
# ---------------------------------------------------------------------------

async def user_requires_mfa_setup(user: User, db: AsyncSession, org_settings: dict | None = None) -> bool:
    """Check if a user needs to set up MFA before accessing the platform.

    Returns True if:
    - User is a Global_Admin (MFA always required)
    - Org has MFA set to mandatory and user has no verified MFA methods

    Queries the normalised ``user_mfa_methods`` table.
    """
    if user.role == "global_admin":
        verified = await _get_verified_mfa_methods(user, db)
        return len(verified) == 0

    if org_settings and org_settings.get("mfa_policy") == "mandatory":
        verified = await _get_verified_mfa_methods(user, db)
        return len(verified) == 0

    return False


async def user_has_verified_mfa(user: User, db: AsyncSession) -> bool:
    """Check if the user has at least one verified MFA method (normalised table)."""
    return len(await _get_verified_mfa_methods(user, db)) > 0


async def _get_verified_mfa_methods(user: User, db: AsyncSession) -> list:
    """Return list of verified MFA method records from the normalised table."""
    from sqlalchemy import select
    from app.modules.auth.models import UserMfaMethod

    result = await db.execute(
        select(UserMfaMethod).where(
            UserMfaMethod.user_id == user.id,
            UserMfaMethod.verified.is_(True),
        )
    )
    return list(result.scalars().all())

async def set_default_mfa_method(
    db: AsyncSession,
    user: User,
    method: str,
) -> None:
    """Set a verified MFA method as the user's default.

    Clears is_default on all other methods for this user, then sets
    the chosen method as default.  Raises ValueError if the method
    is not enrolled/verified.
    """
    from app.modules.auth.models import UserMfaMethod

    # Verify the method exists and is verified
    result = await db.execute(
        select(UserMfaMethod).where(
            UserMfaMethod.user_id == user.id,
            UserMfaMethod.method == method,
            UserMfaMethod.verified == True,  # noqa: E712
        )
    )
    target = result.scalar_one_or_none()
    if target is None:
        raise ValueError(f"Method '{method}' is not enabled")

    # Clear all defaults for this user
    await db.execute(
        update(UserMfaMethod)
        .where(UserMfaMethod.user_id == user.id)
        .values(is_default=False)
    )

    # Set the chosen method as default
    target.is_default = True
    await db.flush()

