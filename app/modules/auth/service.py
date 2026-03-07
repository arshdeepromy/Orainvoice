"""Business logic for authentication — login flow."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import write_audit_log
from app.core.ip_allowlist import get_org_ip_allowlist, is_ip_in_allowlist
from app.modules.auth.jwt import create_access_token, create_refresh_token
from app.modules.auth.models import Session, User
from app.modules.auth.password import verify_password
from app.integrations.google_oauth import GoogleUserInfo
from app.modules.auth.schemas import LoginRequest, MFARequiredResponse, TokenResponse

logger = logging.getLogger(__name__)

# Lockout thresholds
TEMP_LOCK_THRESHOLD = 5
TEMP_LOCK_MINUTES = 15
PERMANENT_LOCK_THRESHOLD = 10


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hash of the refresh token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def authenticate_user(
    db: AsyncSession,
    payload: LoginRequest,
    ip_address: str | None,
    device_type: str | None,
    browser: str | None,
) -> TokenResponse | MFARequiredResponse:
    """Validate credentials and return tokens or MFA challenge.

    Raises ``ValueError`` with a generic message on any failure so the
    caller can return a uniform 401 without leaking whether the email exists.

    Implements account lockout:
    - 5 consecutive failures → 15-minute temporary lock
    - 10 consecutive failures → permanent lock + email alert
    """
    # 1. Look up user by email
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        # Record failed login — no user_id available
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=payload.email,
            reason="unknown_email" if user is None else "no_password_set",
        )
        raise ValueError("Invalid credentials")

    if not user.is_active:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=payload.email,
            reason="account_inactive",
            user_id=user.id,
            org_id=user.org_id,
        )
        raise ValueError("Invalid credentials")

    # 1b. IP allowlist check (Requirement 6.1)
    if user.org_id and ip_address:
        ip_blocked = await check_ip_allowlist(
            db, org_id=user.org_id, ip_address=ip_address,
            user_id=user.id, email=user.email,
        )
        if ip_blocked:
            raise ValueError("IP address not authorised")

    # 2. Check account lockout
    now = datetime.now(timezone.utc)
    if user.locked_until is not None:
        if user.locked_until > now:
            await _audit_failed_login(
                db,
                ip_address=ip_address,
                email=payload.email,
                reason="account_temporarily_locked",
                user_id=user.id,
                org_id=user.org_id,
            )
            raise ValueError("Account temporarily locked")
        else:
            # Temporary lock has expired — clear it
            user.locked_until = None
            user.failed_login_count = 0

    # 3. Verify password
    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count = (user.failed_login_count or 0) + 1

        if user.failed_login_count >= PERMANENT_LOCK_THRESHOLD:
            # Permanent lock — deactivate account and send email
            user.locked_until = None
            user.is_active = False
            await _send_permanent_lockout_email(user.email)
            await _audit_failed_login(
                db,
                ip_address=ip_address,
                email=payload.email,
                reason="permanent_lockout_triggered",
                user_id=user.id,
                org_id=user.org_id,
            )
        elif user.failed_login_count >= TEMP_LOCK_THRESHOLD:
            # Temporary lock — 15 minutes
            user.locked_until = now + timedelta(minutes=TEMP_LOCK_MINUTES)
            await _audit_failed_login(
                db,
                ip_address=ip_address,
                email=payload.email,
                reason="temporary_lockout_triggered",
                user_id=user.id,
                org_id=user.org_id,
            )
        else:
            await _audit_failed_login(
                db,
                ip_address=ip_address,
                email=payload.email,
                reason="invalid_password",
                user_id=user.id,
                org_id=user.org_id,
            )
        raise ValueError("Invalid credentials")

    # 4. Check if MFA is configured
    mfa_methods = user.mfa_methods or []
    if mfa_methods:
        # Reset failed count on valid password (MFA still pending)
        user.failed_login_count = 0
        user.locked_until = None
        mfa_token = create_access_token_mfa_pending(user.id)
        method_types = [m.get("type", "unknown") for m in mfa_methods if isinstance(m, dict)]
        return MFARequiredResponse(
            mfa_required=True,
            mfa_token=mfa_token,
            mfa_methods=method_types,
        )

    # 5. Issue JWT pair
    access_token = create_access_token(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
        email=user.email,
    )
    refresh_token = create_refresh_token()

    # 6. Determine refresh token expiry
    if payload.remember_me:
        expires_delta = timedelta(days=settings.refresh_token_remember_days)
    else:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)

    expires_at = datetime.now(timezone.utc) + expires_delta

    # 7. Create session record
    # Enforce session limit before creating new session
    await enforce_session_limit(db=db, user_id=user.id)

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

    # 8. Reset lockout counters on successful login
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)

    # 9. Audit log — successful login
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.login_success",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "ip_address": ip_address,
            "device_type": device_type,
            "browser": browser,
            "remember_me": payload.remember_me,
        },
        ip_address=ip_address,
        device_info=f"{device_type}; {browser}" if device_type or browser else None,
    )

    # 10. Anomalous login detection (async, non-blocking)
    await _check_anomalous_login(
        db=db,
        user=user,
        ip_address=ip_address,
        device_type=device_type,
        browser=browser,
        login_time=now,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


def create_access_token_mfa_pending(user_id: uuid.UUID) -> str:
    """Create a short-lived token indicating MFA is still required."""
    from jose import jwt as jose_jwt

    now = datetime.now(timezone.utc)
    payload = {
        "user_id": str(user_id),
        "type": "mfa_pending",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jose_jwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


async def _audit_failed_login(
    db: AsyncSession,
    *,
    ip_address: str | None,
    email: str,
    reason: str,
    user_id: uuid.UUID | None = None,
    org_id: uuid.UUID | None = None,
) -> None:
    """Record a failed login attempt in the audit log."""
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="auth.login_failed",
        entity_type="user",
        entity_id=user_id,
        after_value={
            "email_attempted": email,
            "ip_address": ip_address,
            "reason": reason,
        },
        ip_address=ip_address,
    )


async def _send_permanent_lockout_email(email: str) -> None:
    """Send an email alert when an account is permanently locked.

    In production this dispatches via the notification infrastructure.
    For now we log the intent.
    """
    logger.warning(
        "Account permanently locked — unlock email queued for %s",
        email,
    )
    # TODO: Replace with Celery task dispatching a real email via
    # app.integrations.brevo once the Notification_Module is implemented.


async def check_ip_allowlist(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    ip_address: str,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
) -> bool:
    """Check if *ip_address* is blocked by the org's IP allowlist.

    Returns ``True`` if the IP is **blocked** (not in the allowlist),
    ``False`` if allowed or if allowlisting is not enabled.

    When blocked, logs the attempt in the audit log (Requirement 6.3).
    """
    from sqlalchemy import text

    # Fetch org settings without RLS (we need to read the org record directly)
    result = await db.execute(
        text("SELECT settings FROM organisations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    row = result.first()
    if not row:
        return False

    org_settings = row[0] if row[0] else {}
    allowlist = get_org_ip_allowlist(org_settings)

    if allowlist is None:
        # IP allowlisting not enabled for this org
        return False

    if is_ip_in_allowlist(ip_address, allowlist):
        return False

    # IP is blocked — log the attempt (Requirement 6.3)
    logger.warning(
        "IP allowlist blocked login: ip=%s org=%s user=%s",
        ip_address, org_id, email or user_id,
    )
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="auth.ip_blocked",
        entity_type="user",
        entity_id=user_id,
        after_value={
            "ip_address": ip_address,
            "email": email,
            "reason": "ip_not_in_allowlist",
            "allowlist": allowlist,
        },
        ip_address=ip_address,
    )
    return True


async def _check_anomalous_login(
    db: AsyncSession,
    *,
    user: User,
    ip_address: str | None,
    device_type: str | None,
    browser: str | None,
    login_time: datetime,
) -> None:
    """Detect anomalous login conditions and send an email alert if found.

    Checks:
    - New device type (never seen before for this user)
    - Unusual login time (outside 6am–11pm in user's typical pattern)

    GeoIP/country detection is skipped unless a GeoIP library is available.
    """
    from sqlalchemy import and_

    anomalies: list[str] = []

    # Fetch previous sessions for this user (last 90 days)
    ninety_days_ago = login_time - timedelta(days=90)
    prev_sessions_result = await db.execute(
        select(Session).where(
            and_(
                Session.user_id == user.id,
                Session.created_at >= ninety_days_ago,
            )
        )
    )
    prev_sessions = prev_sessions_result.scalars().all()

    if prev_sessions:
        # Check for new device type
        known_devices = {s.device_type for s in prev_sessions if s.device_type}
        if device_type and device_type not in known_devices and known_devices:
            anomalies.append(f"new_device:{device_type}")

        # Check for unusual login time (outside 6am–11pm)
        login_hour = login_time.hour
        if prev_sessions and (login_hour < 6 or login_hour >= 23):
            # Check if user has logged in at this hour before
            known_hours = {s.created_at.hour for s in prev_sessions if s.created_at}
            if login_hour not in known_hours:
                anomalies.append(f"unusual_time:{login_hour}:00")

    if anomalies:
        await _send_anomalous_login_alert(
            email=user.email,
            user_id=user.id,
            anomalies=anomalies,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )

        await write_audit_log(
            session=db,
            org_id=user.org_id,
            user_id=user.id,
            action="auth.anomalous_login_detected",
            entity_type="user",
            entity_id=user.id,
            after_value={
                "anomalies": anomalies,
                "ip_address": ip_address,
                "device_type": device_type,
                "browser": browser,
            },
            ip_address=ip_address,
        )


async def _send_anomalous_login_alert(
    *,
    email: str,
    user_id: uuid.UUID,
    anomalies: list[str],
    ip_address: str | None,
    device_type: str | None,
    browser: str | None,
) -> None:
    """Send an email alert about an anomalous login with a 'This wasn't me' link.

    In production this dispatches via the notification infrastructure.
    The 'This wasn't me' link points to the session invalidation endpoint.
    """
    logger.warning(
        "Anomalous login detected for %s — anomalies: %s, IP: %s, device: %s. "
        "Alert email with 'This wasn't me' link queued.",
        email,
        anomalies,
        ip_address,
        device_type,
    )
    # TODO: Replace with Celery task dispatching a real email via
    # app.integrations.brevo. The email should contain a signed link to
    # POST /api/v1/auth/sessions/invalidate-all?token=<signed_token>


async def invalidate_all_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> int:
    """Revoke all active sessions for a user ('This wasn't me' handler).

    Returns the number of sessions invalidated.
    """
    from sqlalchemy import and_

    result = await db.execute(
        select(Session).where(
            and_(
                Session.user_id == user_id,
                Session.is_revoked == False,  # noqa: E712
            )
        )
    )
    sessions = result.scalars().all()

    count = 0
    for sess in sessions:
        sess.is_revoked = True
        count += 1

    if count > 0:
        # Load user for audit
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        await write_audit_log(
            session=db,
            org_id=user.org_id if user else None,
            user_id=user_id,
            action="auth.all_sessions_invalidated",
            entity_type="user",
            entity_id=user_id,
            after_value={
                "sessions_revoked": count,
                "ip_address": ip_address,
                "trigger": "this_wasnt_me",
            },
            ip_address=ip_address,
        )

    return count


async def rotate_refresh_token(
    db: AsyncSession,
    refresh_token: str,
    ip_address: str | None = None,
    device_type: str | None = None,
    browser: str | None = None,
) -> TokenResponse:
    """Rotate a refresh token and return a new JWT pair.

    Implements refresh-token rotation with reuse detection:
    - Valid (non-revoked, non-expired) token → revoke old session, issue new pair
      with the same ``family_id``.
    - Already-revoked token (reuse) → revoke ALL sessions in the family and
      send an email alert to the user.  Raises ``ValueError``.
    - Unknown token → raises ``ValueError``.
    """
    token_hash = _hash_refresh_token(refresh_token)

    # --- 1. Try to find a valid (non-revoked, non-expired) session ----------
    from sqlalchemy import and_

    valid_result = await db.execute(
        select(Session).where(
            and_(
                Session.refresh_token_hash == token_hash,
                Session.is_revoked == False,  # noqa: E712
                Session.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    valid_session = valid_result.scalar_one_or_none()

    if valid_session is not None:
        # Happy path — rotate the token
        return await _do_rotation(db, valid_session, ip_address, device_type, browser)

    # --- 2. Token not valid — check if it exists at all (revoked?) ----------
    any_result = await db.execute(
        select(Session).where(Session.refresh_token_hash == token_hash)
    )
    revoked_session = any_result.scalar_one_or_none()

    if revoked_session is not None:
        # REUSE DETECTED — invalidate entire family
        await _invalidate_family(db, revoked_session.family_id)

        # Load user for email alert
        user_result = await db.execute(
            select(User).where(User.id == revoked_session.user_id)
        )
        user = user_result.scalar_one_or_none()

        if user:
            await _send_token_reuse_alert(user.email)

            await write_audit_log(
                session=db,
                org_id=revoked_session.org_id,
                user_id=revoked_session.user_id,
                action="auth.token_reuse_detected",
                entity_type="session",
                entity_id=revoked_session.id,
                after_value={
                    "family_id": str(revoked_session.family_id),
                    "ip_address": ip_address,
                },
                ip_address=ip_address,
            )

        raise ValueError("Token has been revoked")

    # --- 3. Token not found at all -----------------------------------------
    raise ValueError("Invalid refresh token")


async def _do_rotation(
    db: AsyncSession,
    current_session: Session,
    ip_address: str | None,
    device_type: str | None,
    browser: str | None,
) -> TokenResponse:
    """Revoke the current session and issue a new token pair."""
    # Revoke old session
    current_session.is_revoked = True

    # Load user for new access token claims
    user_result = await db.execute(
        select(User).where(User.id == current_session.user_id)
    )
    user = user_result.scalar_one()

    # Issue new tokens
    access_token = create_access_token(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
        email=user.email,
    )
    new_refresh_token = create_refresh_token()

    # Preserve the original expiry window
    new_session = Session(
        user_id=current_session.user_id,
        org_id=current_session.org_id,
        refresh_token_hash=_hash_refresh_token(new_refresh_token),
        family_id=current_session.family_id,
        device_type=device_type or current_session.device_type,
        browser=browser or current_session.browser,
        ip_address=ip_address,
        expires_at=current_session.expires_at,
    )
    db.add(new_session)

    await write_audit_log(
        session=db,
        org_id=current_session.org_id,
        user_id=current_session.user_id,
        action="auth.token_rotated",
        entity_type="session",
        entity_id=new_session.id,
        after_value={
            "family_id": str(current_session.family_id),
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


async def _invalidate_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    """Revoke ALL sessions sharing the given family_id."""
    from sqlalchemy import update

    await db.execute(
        update(Session)
        .where(Session.family_id == family_id)
        .values(is_revoked=True)
    )


async def _send_token_reuse_alert(email: str) -> None:
    """Send an email alert about potential token theft.

    In production this dispatches via the notification infrastructure
    (Brevo/SendGrid).  For now we log the intent so the flow is wired up
    and easily replaceable.
    """
    import logging

    logger = logging.getLogger(__name__)
    logger.warning(
        "Token reuse detected — security alert email queued for %s",
        email,
    )
    # TODO: Replace with Celery task dispatching a real email via
    # app.integrations.brevo once the Notification_Module is implemented.


async def authenticate_google(
    db: AsyncSession,
    google_user_info: GoogleUserInfo,
    ip_address: str | None,
    device_type: str | None,
    browser: str | None,
) -> TokenResponse | MFARequiredResponse:
    """Authenticate a user via Google OAuth.

    Looks up the user by email. If found, links the Google ID (if not
    already linked) and issues tokens. If not found, raises ValueError
    because self-registration via OAuth is not allowed — users must be
    invited first.
    """
    result = await db.execute(select(User).where(User.email == google_user_info.email))
    user = result.scalar_one_or_none()

    if user is None:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=google_user_info.email,
            reason="google_oauth_no_account",
        )
        raise ValueError("No account found for this email. Users must be invited first.")

    if not user.is_active:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=google_user_info.email,
            reason="account_inactive",
            user_id=user.id,
            org_id=user.org_id,
        )
        raise ValueError("Account is inactive")

    # IP allowlist check (Requirement 6.1)
    if user.org_id and ip_address:
        ip_blocked = await check_ip_allowlist(
            db, org_id=user.org_id, ip_address=ip_address,
            user_id=user.id, email=user.email,
        )
        if ip_blocked:
            raise ValueError("IP address not authorised")

    # Link Google OAuth ID if not already set
    if not user.google_oauth_id:
        user.google_oauth_id = google_user_info.google_id

    # Check if MFA is configured
    mfa_methods = user.mfa_methods or []
    if mfa_methods:
        mfa_token = create_access_token_mfa_pending(user.id)
        method_types = [m.get("type", "unknown") for m in mfa_methods if isinstance(m, dict)]
        return MFARequiredResponse(
            mfa_required=True,
            mfa_token=mfa_token,
            mfa_methods=method_types,
        )

    # Issue JWT pair
    access_token = create_access_token(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
        email=user.email,
    )
    refresh_token = create_refresh_token()

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    # Enforce session limit before creating new session
    await enforce_session_limit(db=db, user_id=user.id)

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

    # Update last_login_at
    user.last_login_at = datetime.now(timezone.utc)

    # Audit log — successful Google login
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.google_login_success",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "ip_address": ip_address,
            "device_type": device_type,
            "browser": browser,
            "google_id": google_user_info.google_id,
        },
        ip_address=ip_address,
        device_info=f"{device_type}; {browser}" if device_type or browser else None,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------------------------------------------------------------------
# Passkey (WebAuthn) helpers
# ---------------------------------------------------------------------------

async def _get_redis():
    """Get the shared Redis client."""
    from app.core.redis import redis_pool
    return redis_pool


def _get_rp():
    """Build a WebAuthn RelyingParty from settings."""
    from webauthn.types import RelyingParty
    return RelyingParty(
        id=settings.webauthn_rp_id,
        name=settings.webauthn_rp_name,
        icon=None,
    )


def _serialize_public_key(public_key) -> str:
    """Serialize a cryptography public key to base64-encoded DER."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )
    der_bytes = public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der_bytes).decode()


def _deserialize_public_key(public_key_b64: str):
    """Deserialize a base64-encoded DER public key."""
    from cryptography.hazmat.primitives.serialization import load_der_public_key
    der_bytes = base64.b64decode(public_key_b64)
    return load_der_public_key(der_bytes)


async def generate_passkey_register_options(
    user: User,
    device_name: str = "My Passkey",
) -> dict:
    """Generate WebAuthn registration options for a user.

    Stores the challenge in Redis with a 5-minute TTL.
    Returns the options dict to be sent to the client.
    """
    import webauthn
    from webauthn.types import Attestation

    rp = _get_rp()
    webauthn_user = webauthn.types.User(
        id=str(user.id).encode(),
        name=user.email,
        display_name=user.email,
        icon=None,
    )

    # Build exclude list from existing credentials
    existing_creds = user.passkey_credentials or []
    existing_keys = []
    for cred in existing_creds:
        if isinstance(cred, dict) and "credential_id" in cred:
            existing_keys.append(base64.b64decode(cred["credential_id"]))

    options, challenge_b64 = webauthn.create_webauthn_credentials(
        rp=rp,
        user=webauthn_user,
        existing_keys=existing_keys if existing_keys else None,
        attestation_request=Attestation.NoneAttestation,
    )

    # Store challenge in Redis with 5-min TTL
    redis = await _get_redis()
    challenge_key = f"webauthn:register:{user.id}"
    await redis.setex(challenge_key, 300, json.dumps({
        "challenge": challenge_b64,
        "device_name": device_name,
    }))

    return options


async def verify_passkey_registration(
    db: AsyncSession,
    user: User,
    credential_response: dict,
) -> dict:
    """Verify a WebAuthn registration response and store the credential.

    Expects credential_response with keys:
      - client_data_b64: base64-encoded clientDataJSON
      - attestation_b64: base64-encoded attestationObject
      - credential_id_b64: base64-encoded credential raw ID

    Returns the stored credential info dict.
    """
    import webauthn
    from webauthn.metadata import FIDOMetadata

    # Retrieve challenge from Redis
    redis = await _get_redis()
    challenge_key = f"webauthn:register:{user.id}"
    stored_data = await redis.get(challenge_key)
    if not stored_data:
        raise ValueError("Registration challenge expired or not found")

    stored = json.loads(stored_data)
    challenge_b64 = stored["challenge"]
    device_name = stored.get("device_name", "My Passkey")

    # Clean up the challenge
    await redis.delete(challenge_key)

    rp = _get_rp()
    # Use empty FIDO metadata (no attestation verification needed)
    fido_metadata = FIDOMetadata(entries=[], aaguid_map={}, cki_map={})

    client_data_b64 = credential_response.get("client_data_b64", "")
    attestation_b64 = credential_response.get("attestation_b64", "")
    credential_id_b64 = credential_response.get("credential_id_b64", "")

    if not client_data_b64 or not attestation_b64 or not credential_id_b64:
        raise ValueError("Missing required fields in credential response")

    result = webauthn.verify_create_webauthn_credentials(
        rp=rp,
        challenge_b64=challenge_b64,
        client_data_b64=client_data_b64,
        attestation_b64=attestation_b64,
        fido_metadata=fido_metadata,
    )

    # Serialize public key for storage
    public_key_b64 = _serialize_public_key(result.public_key)

    new_credential = {
        "credential_id": credential_id_b64,
        "public_key": public_key_b64,
        "public_key_alg": result.public_key_alg,
        "sign_count": result.sign_count,
        "device_name": device_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    existing_creds = list(user.passkey_credentials or [])
    existing_creds.append(new_credential)
    user.passkey_credentials = existing_creds

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.passkey_registered",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "credential_id": credential_id_b64,
            "device_name": device_name,
        },
    )

    return {
        "credential_id": credential_id_b64,
        "device_name": device_name,
    }


async def generate_passkey_login_options(
    db: AsyncSession,
    email: str,
) -> dict:
    """Generate WebAuthn authentication options for a user.

    Stores the challenge in Redis with a 5-minute TTL.
    Returns the options dict to be sent to the client.
    """
    import webauthn

    # Look up user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise ValueError("No account found or account inactive")

    existing_creds = user.passkey_credentials or []
    if not existing_creds:
        raise ValueError("No passkeys registered for this account")

    # Build allow list of credential IDs
    existing_keys = []
    for cred in existing_creds:
        if isinstance(cred, dict) and "credential_id" in cred:
            existing_keys.append(base64.b64decode(cred["credential_id"]))

    rp = _get_rp()
    options, challenge_b64 = webauthn.get_webauthn_credentials(
        rp=rp,
        existing_keys=existing_keys if existing_keys else None,
    )

    # Store challenge in Redis with 5-min TTL
    redis = await _get_redis()
    challenge_key = f"webauthn:login:{user.id}"
    await redis.setex(challenge_key, 300, json.dumps({
        "challenge": challenge_b64,
        "user_id": str(user.id),
    }))

    return options


async def verify_passkey_login(
    db: AsyncSession,
    email: str,
    credential_response: dict,
    ip_address: str | None = None,
    device_type: str | None = None,
    browser: str | None = None,
) -> TokenResponse:
    """Verify a WebAuthn authentication response and issue JWT tokens.

    Passkey login satisfies MFA — no additional MFA prompt is required
    (Requirement 2.9).

    Expects credential_response with keys:
      - client_data_b64: base64-encoded clientDataJSON
      - authenticator_b64: base64-encoded authenticatorData
      - signature_b64: base64-encoded signature
      - credential_id_b64: base64-encoded credential raw ID
    """
    import webauthn

    # Look up user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=email,
            reason="passkey_no_account" if user is None else "account_inactive",
            user_id=user.id if user else None,
            org_id=user.org_id if user else None,
        )
        raise ValueError("Authentication failed")

    # IP allowlist check (Requirement 6.1)
    if user.org_id and ip_address:
        ip_blocked = await check_ip_allowlist(
            db, org_id=user.org_id, ip_address=ip_address,
            user_id=user.id, email=user.email,
        )
        if ip_blocked:
            raise ValueError("IP address not authorised")

    # Retrieve challenge from Redis
    redis = await _get_redis()
    challenge_key = f"webauthn:login:{user.id}"
    stored_data = await redis.get(challenge_key)
    if not stored_data:
        raise ValueError("Authentication challenge expired or not found")

    stored = json.loads(stored_data)
    challenge_b64 = stored["challenge"]

    # Clean up the challenge
    await redis.delete(challenge_key)

    # Extract fields from credential response
    client_data_b64 = credential_response.get("client_data_b64", "")
    authenticator_b64 = credential_response.get("authenticator_b64", "")
    signature_b64 = credential_response.get("signature_b64", "")
    credential_id_b64 = credential_response.get("credential_id_b64", "")

    if not all([client_data_b64, authenticator_b64, signature_b64, credential_id_b64]):
        raise ValueError("Missing required fields in credential response")

    # Find the matching credential in user's stored passkeys
    existing_creds = user.passkey_credentials or []
    matched_cred = None
    matched_idx = None
    for idx, cred in enumerate(existing_creds):
        if isinstance(cred, dict) and cred.get("credential_id") == credential_id_b64:
            matched_cred = cred
            matched_idx = idx
            break

    if matched_cred is None:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=email,
            reason="passkey_credential_not_found",
            user_id=user.id,
            org_id=user.org_id,
        )
        raise ValueError("Authentication failed")

    stored_public_key = _deserialize_public_key(matched_cred["public_key"])
    stored_sign_count = matched_cred.get("sign_count", 0)
    pubkey_alg = matched_cred.get("public_key_alg", -7)  # default ES256

    rp = _get_rp()
    verification = webauthn.verify_get_webauthn_credentials(
        rp=rp,
        challenge_b64=challenge_b64,
        client_data_b64=client_data_b64,
        authenticator_b64=authenticator_b64,
        signature_b64=signature_b64,
        sign_count=stored_sign_count,
        pubkey_alg=pubkey_alg,
        pubkey=stored_public_key,
    )

    # Update sign count
    updated_creds = list(existing_creds)
    updated_creds[matched_idx] = {
        **matched_cred,
        "sign_count": verification.sign_count,
    }
    user.passkey_credentials = updated_creds

    # Passkey satisfies MFA — issue tokens directly (Requirement 2.9)
    access_token = create_access_token(
        user_id=user.id,
        org_id=user.org_id,
        role=user.role,
        email=user.email,
    )
    refresh_token = create_refresh_token()

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )

    # Enforce session limit before creating new session
    await enforce_session_limit(db=db, user_id=user.id)

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
        action="auth.passkey_login_success",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "ip_address": ip_address,
            "device_type": device_type,
            "browser": browser,
            "credential_id": credential_id_b64,
            "mfa_satisfied": True,
        },
        ip_address=ip_address,
        device_info=f"{device_type}; {browser}" if device_type or browser else None,
    )

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


# ---------------------------------------------------------------------------
# Session management (Task 4.7)
# ---------------------------------------------------------------------------


async def list_user_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    current_session_id: uuid.UUID | None = None,
) -> list[dict]:
    """Return all active (non-revoked, non-expired) sessions for a user.

    Each session dict includes a ``current`` flag indicating whether it
    matches the requesting session.
    """
    from sqlalchemy import and_

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Session).where(
            and_(
                Session.user_id == user_id,
                Session.is_revoked == False,  # noqa: E712
                Session.expires_at > now,
            )
        ).order_by(Session.last_activity_at.desc())
    )
    sessions = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "device_type": s.device_type,
            "browser": s.browser,
            "ip_address": str(s.ip_address) if s.ip_address else None,
            "last_activity_at": s.last_activity_at,
            "created_at": s.created_at,
            "current": s.id == current_session_id if current_session_id else False,
        }
        for s in sessions
    ]


async def terminate_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
    """Revoke a specific session owned by the user.

    Raises ``ValueError`` if the session doesn't exist, is already
    revoked, or belongs to a different user.
    """
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session_obj = result.scalar_one_or_none()

    if session_obj is None:
        raise ValueError("Session not found")

    if session_obj.user_id != user_id:
        raise ValueError("Session not found")

    if session_obj.is_revoked:
        raise ValueError("Session already revoked")

    session_obj.is_revoked = True

    # Load user for audit org_id
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    await write_audit_log(
        session=db,
        org_id=user.org_id if user else None,
        user_id=user_id,
        action="auth.session_terminated",
        entity_type="session",
        entity_id=session_id,
        after_value={
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )


async def enforce_session_limit(
    db: AsyncSession,
    user_id: uuid.UUID,
    max_sessions: int | None = None,
) -> int:
    """Ensure active sessions don't exceed the configured maximum.

    If the active session count is >= ``max_sessions``, revokes the
    oldest session(s) to make room for one new session.

    Returns the number of sessions revoked.
    """
    from sqlalchemy import and_

    if max_sessions is None:
        max_sessions = settings.max_sessions_per_user

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Session).where(
            and_(
                Session.user_id == user_id,
                Session.is_revoked == False,  # noqa: E712
                Session.expires_at > now,
            )
        ).order_by(Session.created_at.asc())
    )
    active_sessions = result.scalars().all()

    revoked = 0
    while len(active_sessions) - revoked >= max_sessions:
        active_sessions[revoked].is_revoked = True
        revoked += 1

    return revoked

# ---------------------------------------------------------------------------
# Password recovery (Task 4.8)
# ---------------------------------------------------------------------------

_RESET_TOKEN_EXPIRY_SECONDS = 3600  # 1 hour


def _hash_reset_token(token: str) -> str:
    """SHA-256 hash of a password reset token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def request_password_reset(
    db: AsyncSession,
    email: str,
    ip_address: str | None = None,
) -> None:
    """Request a password reset link.

    Generates a secure token, stores its hash in Redis with a 1-hour TTL,
    and sends a reset email.  Returns nothing — the caller MUST return
    an identical 200 response regardless of whether the email exists
    (Requirement 4.4 — prevent account enumeration).
    """
    from app.core.redis import redis_pool

    # Look up user — but never reveal whether they exist
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Audit the request regardless
    await write_audit_log(
        session=db,
        org_id=user.org_id if user else None,
        user_id=user.id if user else None,
        action="auth.password_reset_requested",
        entity_type="user",
        entity_id=user.id if user else None,
        after_value={
            "email": email,
            "ip_address": ip_address,
            "user_found": user is not None,
        },
        ip_address=ip_address,
    )

    if user is None or not user.is_active:
        # Silently return — uniform response
        return

    # Generate a secure reset token
    import secrets
    reset_token = secrets.token_urlsafe(48)
    token_hash = _hash_reset_token(reset_token)

    # Store token hash in Redis with 1-hour TTL, keyed by hash
    token_data = json.dumps({
        "user_id": str(user.id),
        "email": user.email,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await redis_pool.setex(
        f"password_reset:{token_hash}",
        _RESET_TOKEN_EXPIRY_SECONDS,
        token_data,
    )

    # Send reset email (mocked for now)
    await _send_password_reset_email(user.email, reset_token)


async def _send_password_reset_email(email: str, token: str) -> None:
    """Send a password reset email with the reset link.

    In production this dispatches via the notification infrastructure.
    For now we log the intent so the flow is wired up.
    """
    logger.info(
        "Password reset email queued for %s with token %s...",
        email,
        token[:8],
    )
    # TODO: Replace with Celery task dispatching a real email via
    # app.integrations.brevo once the Notification_Module is implemented.


async def complete_password_reset(
    db: AsyncSession,
    token: str,
    new_password: str,
    ip_address: str | None = None,
) -> None:
    """Complete a password reset using a valid reset token.

    Validates the token, checks the new password against HIBP,
    updates the password hash, and invalidates all active sessions.

    Raises ``ValueError`` on invalid/expired token or compromised password.
    """
    from app.core.redis import redis_pool
    from app.integrations.hibp import is_password_compromised
    from app.modules.auth.password import hash_password

    token_hash = _hash_reset_token(token)
    redis_key = f"password_reset:{token_hash}"

    # 1. Validate token
    stored_data = await redis_pool.get(redis_key)
    if stored_data is None:
        raise ValueError("Invalid or expired reset token")

    token_info = json.loads(stored_data if isinstance(stored_data, str) else stored_data.decode())
    user_id = uuid.UUID(token_info["user_id"])

    # 2. Load user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValueError("Invalid or expired reset token")

    # 3. Check new password against HIBP
    compromised = await is_password_compromised(new_password)
    if compromised:
        raise ValueError(
            "This password has appeared in a known data breach. Please choose a different password."
        )

    # 4. Update password
    user.password_hash = hash_password(new_password)

    # 5. Invalidate the reset token (delete from Redis)
    await redis_pool.delete(redis_key)

    # 6. Invalidate ALL active sessions (Requirement 4.3)
    sessions_revoked = await invalidate_all_sessions(
        db=db,
        user_id=user.id,
        ip_address=ip_address,
    )

    # 7. Audit log
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.password_reset_completed",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "ip_address": ip_address,
            "sessions_revoked": sessions_revoked,
        },
        ip_address=ip_address,
    )


async def reset_via_backup_code(
    db: AsyncSession,
    email: str,
    backup_code: str,
    new_password: str,
    ip_address: str | None = None,
) -> None:
    """Reset password using an MFA backup code.

    Allows account recovery when all MFA methods are unavailable.
    The backup code is consumed (marked as used) on success.

    Raises ``ValueError`` on invalid email, backup code, or compromised password.
    """
    from app.integrations.hibp import is_password_compromised
    from app.modules.auth.password import hash_password

    # 1. Look up user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise ValueError("Invalid credentials")

    # 2. Verify backup code
    backup_codes = user.backup_codes_hash or []
    matched = False
    for i, entry in enumerate(backup_codes):
        if isinstance(entry, dict) and not entry.get("used", False):
            import bcrypt as bcrypt_lib
            if bcrypt_lib.checkpw(
                backup_code.encode("utf-8"),
                entry["hash"].encode("utf-8"),
            ):
                # Mark as used
                updated_codes = list(backup_codes)
                updated_codes[i] = {**entry, "used": True}
                user.backup_codes_hash = updated_codes
                matched = True
                break

    if not matched:
        await write_audit_log(
            session=db,
            org_id=user.org_id,
            user_id=user.id,
            action="auth.password_reset_backup_failed",
            entity_type="user",
            entity_id=user.id,
            after_value={
                "ip_address": ip_address,
                "reason": "invalid_backup_code",
            },
            ip_address=ip_address,
        )
        raise ValueError("Invalid backup code")

    # 3. Check new password against HIBP
    compromised = await is_password_compromised(new_password)
    if compromised:
        raise ValueError(
            "This password has appeared in a known data breach. Please choose a different password."
        )

    # 4. Update password
    user.password_hash = hash_password(new_password)

    # 5. Invalidate ALL active sessions
    sessions_revoked = await invalidate_all_sessions(
        db=db,
        user_id=user.id,
        ip_address=ip_address,
    )

    # 6. Audit log
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.password_reset_via_backup_code",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "ip_address": ip_address,
            "sessions_revoked": sessions_revoked,
        },
        ip_address=ip_address,
    )


# ---------------------------------------------------------------------------
# Email verification / invitation (Task 4.11)
# ---------------------------------------------------------------------------

_INVITE_TOKEN_EXPIRY_SECONDS = 48 * 3600  # 48 hours


def _hash_invite_token(token: str) -> str:
    """SHA-256 hash of an invitation token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_invitation(
    db: AsyncSession,
    *,
    inviter_user_id: uuid.UUID,
    org_id: uuid.UUID,
    email: str,
    role: str,
    ip_address: str | None = None,
) -> dict:
    """Create a new user account via invitation and send a signup email.

    Generates a secure invitation token stored in Redis with a 48-hour TTL.
    The invited user record is created immediately with ``is_email_verified=False``
    and no password.

    Returns a dict with ``user_id`` and ``invitation_expires_at``.

    Raises ``ValueError`` if the email is already registered.
    """
    import secrets
    from app.core.redis import redis_pool

    # Validate role
    if role not in ("org_admin", "salesperson"):
        raise ValueError("Role must be 'org_admin' or 'salesperson'")

    # Check if email already exists
    result = await db.execute(select(User).where(User.email == email))
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise ValueError("A user with this email already exists")

    # Create user record (unverified, no password)
    new_user = User(
        org_id=org_id,
        email=email,
        role=role,
        is_active=True,
        is_email_verified=False,
        password_hash=None,
    )
    db.add(new_user)
    await db.flush()  # Get the generated ID

    # Generate secure invitation token
    invite_token = secrets.token_urlsafe(48)
    token_hash = _hash_invite_token(invite_token)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_INVITE_TOKEN_EXPIRY_SECONDS)

    token_data = json.dumps({
        "user_id": str(new_user.id),
        "email": email,
        "org_id": str(org_id),
        "created_at": now.isoformat(),
    })
    await redis_pool.setex(
        f"invite:{token_hash}",
        _INVITE_TOKEN_EXPIRY_SECONDS,
        token_data,
    )

    # Send invitation email
    await _send_invitation_email(email, invite_token)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=inviter_user_id,
        action="auth.user_invited",
        entity_type="user",
        entity_id=new_user.id,
        after_value={
            "invited_email": email,
            "role": role,
            "ip_address": ip_address,
            "expires_at": expires_at.isoformat(),
        },
        ip_address=ip_address,
    )

    return {
        "user_id": str(new_user.id),
        "invitation_expires_at": expires_at,
    }


async def verify_email_and_set_password(
    db: AsyncSession,
    *,
    token: str,
    new_password: str,
    ip_address: str | None = None,
    device_type: str | None = None,
    browser: str | None = None,
) -> dict:
    """Verify email via invitation token and set the user's password.

    Marks the user's email as verified, hashes and stores the password,
    and issues a JWT pair so the user is logged in immediately.

    Raises ``ValueError`` on invalid/expired token or compromised password.
    """
    from app.core.redis import redis_pool
    from app.integrations.hibp import is_password_compromised
    from app.modules.auth.password import hash_password

    token_hash = _hash_invite_token(token)
    redis_key = f"invite:{token_hash}"

    # 1. Validate token
    stored_data = await redis_pool.get(redis_key)
    if stored_data is None:
        raise ValueError("Invalid or expired invitation token")

    token_info = json.loads(
        stored_data if isinstance(stored_data, str) else stored_data.decode()
    )
    user_id = uuid.UUID(token_info["user_id"])

    # 2. Load user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("Invalid or expired invitation token")

    if user.is_email_verified:
        raise ValueError("Email has already been verified")

    # 3. Check password against HIBP
    compromised = await is_password_compromised(new_password)
    if compromised:
        raise ValueError(
            "This password has appeared in a known data breach. "
            "Please choose a different password."
        )

    # 4. Mark email as verified and set password
    user.is_email_verified = True
    user.password_hash = hash_password(new_password)

    # 5. Consume the invitation token
    await redis_pool.delete(redis_key)

    # 6. Issue JWT pair (user is now logged in)
    access_token = create_access_token(
        user_id=user.id,
        org_id=user.org_id,
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

    # 7. Audit log
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.email_verified",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "ip_address": ip_address,
            "device_type": device_type,
            "browser": browser,
        },
        ip_address=ip_address,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


async def resend_invitation(
    db: AsyncSession,
    *,
    resender_user_id: uuid.UUID,
    org_id: uuid.UUID,
    email: str,
    ip_address: str | None = None,
) -> dict:
    """Resend an invitation for a user whose previous invite has expired.

    Generates a new token with a fresh 48-hour TTL. Only works for users
    who belong to the same org and have not yet verified their email.

    Returns a dict with ``invitation_expires_at``.

    Raises ``ValueError`` if the user is not found, already verified,
    or belongs to a different org.
    """
    import secrets
    from app.core.redis import redis_pool

    # Look up user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        raise ValueError("No pending invitation found for this email")

    if user.org_id != org_id:
        raise ValueError("No pending invitation found for this email")

    if user.is_email_verified:
        raise ValueError("This user has already verified their email")

    # Generate new invitation token
    invite_token = secrets.token_urlsafe(48)
    token_hash = _hash_invite_token(invite_token)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_INVITE_TOKEN_EXPIRY_SECONDS)

    token_data = json.dumps({
        "user_id": str(user.id),
        "email": email,
        "org_id": str(org_id),
        "created_at": now.isoformat(),
    })
    await redis_pool.setex(
        f"invite:{token_hash}",
        _INVITE_TOKEN_EXPIRY_SECONDS,
        token_data,
    )

    # Send invitation email
    await _send_invitation_email(email, invite_token)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=resender_user_id,
        action="auth.invitation_resent",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "invited_email": email,
            "ip_address": ip_address,
            "expires_at": expires_at.isoformat(),
        },
        ip_address=ip_address,
    )

    return {
        "invitation_expires_at": expires_at,
    }


async def _send_invitation_email(email: str, token: str) -> None:
    """Send an invitation email with the secure signup link.

    In production this dispatches via the notification infrastructure
    (Brevo/SendGrid). For now we log the intent.
    """
    logger.info(
        "Invitation email queued for %s with token %s...",
        email,
        token[:8],
    )
    # TODO: Replace with Celery task dispatching a real email via
    # app.integrations.brevo once the Notification_Module is implemented.
