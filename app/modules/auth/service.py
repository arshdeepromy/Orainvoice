"""Business logic for authentication — login flow."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import write_audit_log
from app.core.ip_allowlist import get_org_ip_allowlist, is_ip_in_allowlist
from app.modules.auth.jwt import create_access_token, create_refresh_token
from app.modules.auth.models import Session, User, UserMfaMethod, UserPasskeyCredential
from app.modules.auth.password import verify_password
from app.integrations.google_oauth import GoogleUserInfo
from app.modules.auth.schemas import LoginRequest, MFAChallengeResponse, MFARequiredResponse, TokenResponse

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
) -> TokenResponse | MFAChallengeResponse:
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

    # 1a. Block unverified email accounts
    if not user.is_email_verified:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=payload.email,
            reason="email_not_verified",
            user_id=user.id,
            org_id=user.org_id,
        )
        raise ValueError("Please verify your email address before logging in. Check your inbox for the verification link.")

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

    # 4. Check if MFA is configured (normalised tables)
    from app.modules.auth.models import UserMfaMethod
    from app.modules.auth.mfa_service import _store_challenge_session

    mfa_stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.verified == True,  # noqa: E712
    )
    mfa_result = await db.execute(mfa_stmt)
    verified_methods = mfa_result.scalars().all()

    if verified_methods:
        # Reset failed count on valid password (MFA still pending)
        user.failed_login_count = 0
        user.locked_until = None
        # Generate a random mfa_token and store challenge session in Redis
        mfa_token = secrets.token_urlsafe(32)
        method_types = [m.method for m in verified_methods]
        default = next((m.method for m in verified_methods if m.is_default), None)
        sms_phone = next((m.phone_number for m in verified_methods if m.method == "sms" and m.phone_number), None)
        await _store_challenge_session(mfa_token, user.id, method_types, phone_number=sms_phone)
        return MFAChallengeResponse(
            mfa_required=True,
            mfa_token=mfa_token,
            methods=method_types,
            default_method=default,
        )

    # 5. Issue JWT pair
    # Global admins should not have org_id in their JWT (they access all orgs)
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
        branch_ids=user.branch_ids,
    )
    refresh_token = create_refresh_token()

    # 6. Determine refresh token expiry
    if user.role == "kiosk":
        expires_delta = timedelta(days=30)
    elif payload.remember_me:
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
    import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "user_id": str(user_id),
        "type": "mfa_pending",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(
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

    Uses the same SMTP email-provider infrastructure as other transactional
    emails.  Wrapped in a top-level try/except so a delivery failure never
    blocks the lockout process (Requirement 7.3).
    """
    try:
        import smtplib
        import json as _json
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from sqlalchemy import select as _select
        from app.modules.admin.models import EmailProvider
        from app.core.encryption import envelope_decrypt_str
        from app.core.database import async_session_factory

        support_url = f"{settings.frontend_base_url}/support"
        platform_name = "WorkshopPro NZ"
        reason = "Too many failed login attempts (10 consecutive failures)."

        subject = f"Your {platform_name} account has been locked"

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
          <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #1f2937; font-size: 24px; margin: 0;">{platform_name}</h1>
          </div>

          <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Your account has been permanently locked.
          </p>

          <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            <strong>Reason:</strong> {reason}
          </p>

          <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            If you did not make these login attempts, please contact our support
            team immediately to secure your account:
          </p>

          <div style="text-align: center; margin: 30px 0;">
            <a href="{support_url}"
               style="display: inline-block; padding: 14px 32px; background-color: #2563eb;
                      color: #ffffff; text-decoration: none; border-radius: 8px;
                      font-size: 16px; font-weight: 600;">
              Contact Support
            </a>
          </div>

          <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;" />

          <p style="color: #9ca3af; font-size: 12px; text-align: center;">
            {platform_name} — Workshop management made simple
          </p>
        </div>
        """

        text_body = (
            f"Your {platform_name} account has been locked.\n\n"
            f"Reason: {reason}\n\n"
            f"If you did not make these login attempts, please contact support "
            f"immediately to secure your account:\n"
            f"{support_url}\n"
        )

        async with async_session_factory() as session:
            provider_result = await session.execute(
                _select(EmailProvider)
                .where(
                    EmailProvider.is_active == True,
                    EmailProvider.credentials_set == True,
                )
                .order_by(EmailProvider.priority)
            )
            providers = list(provider_result.scalars().all())

        if not providers:
            logger.warning(
                "No active email provider configured — cannot send lockout email to %s",
                email,
            )
            return

        last_error = None
        for provider in providers:
            try:
                creds_json = envelope_decrypt_str(provider.credentials_encrypted)
                credentials = _json.loads(creds_json)

                smtp_host = provider.smtp_host
                smtp_port = provider.smtp_port or 587
                smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
                username = credentials.get("username") or credentials.get("api_key", "")
                password = credentials.get("password") or credentials.get("api_key", "")

                config = provider.config or {}
                from_email = config.get("from_email") or username
                from_name = config.get("from_name") or platform_name

                msg = MIMEMultipart("alternative")
                msg["From"] = f"{from_name} <{from_email}>"
                msg["To"] = email
                msg["Subject"] = subject
                msg.attach(MIMEText(text_body, "plain"))
                msg.attach(MIMEText(html_body, "html"))

                if smtp_encryption == "ssl":
                    server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
                else:
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                    if smtp_encryption == "tls":
                        server.starttls()

                if username and password:
                    server.login(username, password)

                server.sendmail(from_email, email, msg.as_string())
                server.quit()
                logger.info("Lockout email sent to %s via %s", email, provider.provider_key)
                return
            except Exception as e:
                last_error = e
                logger.warning(
                    "Email provider %s failed for lockout email to %s: %s",
                    provider.provider_key, email, e,
                )
                continue

        logger.warning(
            "All email providers failed for lockout email to %s: %s",
            email, last_error,
        )
    except Exception:
        logger.exception("Failed to send lockout email to %s", email)



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
    user = user_result.scalar_one_or_none()

    if user is None:
        raise ValueError("User no longer exists")

    # For non-global-admin users, verify their org still exists
    if user.role != "global_admin" and user.org_id:
        from app.modules.admin.models import Organisation
        org_result = await db.execute(
            select(Organisation.id).where(Organisation.id == user.org_id)
        )
        if org_result.scalar_one_or_none() is None:
            # Org was deleted — invalidate the entire session family
            await _invalidate_family(db, current_session.family_id)
            raise ValueError("Organisation no longer exists")

    # Issue new tokens
    # Global admins should not have org_id in their JWT (they access all orgs)
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
        branch_ids=user.branch_ids,
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

    # Note: we intentionally do NOT write an audit log for routine token
    # rotations.  At scale (10k+ users) this would generate thousands of
    # low-value rows per hour.  Security-relevant events (reuse detection,
    # login, logout) are still logged.

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
) -> TokenResponse | MFAChallengeResponse:
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

    # Check if MFA is configured (normalised tables)
    from app.modules.auth.models import UserMfaMethod
    from app.modules.auth.mfa_service import _store_challenge_session

    mfa_stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.verified == True,  # noqa: E712
    )
    mfa_result = await db.execute(mfa_stmt)
    verified_methods = mfa_result.scalars().all()

    if verified_methods:
        mfa_token = secrets.token_urlsafe(32)
        method_types = [m.method for m in verified_methods]
        default = next((m.method for m in verified_methods if m.is_default), None)
        sms_phone = next((m.phone_number for m in verified_methods if m.method == "sms" and m.phone_number), None)
        await _store_challenge_session(mfa_token, user.id, method_types, phone_number=sms_phone)
        return MFAChallengeResponse(
            mfa_required=True,
            mfa_token=mfa_token,
            methods=method_types,
            default_method=default,
        )

    # Issue JWT pair
    # Global admins should not have org_id in their JWT (they access all orgs)
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
        branch_ids=user.branch_ids,
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


def _bytes_to_base64url(b: bytes) -> str:
    """Encode bytes to base64url (no padding)."""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _base64url_to_bytes(s: str) -> bytes:
    """Decode base64url (with or without padding) to bytes."""
    s += "=" * (4 - len(s) % 4)
    return base64.urlsafe_b64decode(s)


async def generate_passkey_register_options(
    db: AsyncSession,
    user: User,
    device_name: str = "My Passkey",
) -> dict:
    """Generate WebAuthn registration options for a user.

    Uses py_webauthn v2.x ``generate_registration_options()`` and
    ``options_to_json()`` to produce options compatible with the browser
    WebAuthn API.  Enforces a 10-credential limit and stores the
    challenge in Redis with a 60 s TTL.
    """
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (
        AttestationConveyancePreference,
        PublicKeyCredentialDescriptor,
    )

    # --- enforce max 10 credentials ---
    result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.user_id == user.id,
        )
    )
    existing_creds: list[UserPasskeyCredential] = list(result.scalars().all())

    if len(existing_creds) >= 10:
        raise ValueError(
            "Maximum number of passkeys (10) reached. "
            "Remove an existing passkey to register a new one."
        )

    # Build exclude list from existing credential IDs
    exclude_credentials = [
        PublicKeyCredentialDescriptor(id=_base64url_to_bytes(cred.credential_id))
        for cred in existing_creds
    ] if existing_creds else None

    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.email,
        attestation=AttestationConveyancePreference.NONE,
        exclude_credentials=exclude_credentials,
        timeout=60000,
    )

    # options_to_json returns a JSON string; parse to dict for the response
    options_json = json.loads(options_to_json(options))

    # Store challenge in Redis with 60 s TTL (challenge is base64url in the options)
    redis = await _get_redis()
    challenge_key = f"webauthn:register:{user.id}"
    await redis.setex(challenge_key, 60, json.dumps({
        "challenge": options_json["challenge"],
        "device_name": device_name,
    }))

    return options_json


async def verify_passkey_registration(
    db: AsyncSession,
    user: User,
    credential_response: dict,
) -> dict:
    """Verify a WebAuthn registration response and store the credential.

    Uses py_webauthn v2.x ``verify_registration_response()``.
    The frontend sends ``client_data_b64``, ``attestation_b64``, and
    ``credential_id_b64`` — we reconstruct the credential dict that
    py_webauthn expects.
    """
    from webauthn import verify_registration_response

    # Retrieve challenge from Redis
    redis = await _get_redis()
    challenge_key = f"webauthn:register:{user.id}"
    stored_data = await redis.get(challenge_key)
    if not stored_data:
        raise ValueError("Registration challenge expired or not found")

    stored = json.loads(stored_data)
    challenge_b64url = stored["challenge"]
    device_name = stored.get("device_name", "My Passkey")

    # Clean up the challenge
    await redis.delete(challenge_key)

    client_data_b64 = credential_response.get("client_data_b64", "")
    attestation_b64 = credential_response.get("attestation_b64", "")
    credential_id_b64 = credential_response.get("credential_id_b64", "")

    if not client_data_b64 or not attestation_b64 or not credential_id_b64:
        raise ValueError("Missing required fields in credential response")

    # Build the credential dict that py_webauthn expects
    credential_dict = {
        "id": credential_id_b64,
        "rawId": credential_id_b64,
        "response": {
            "clientDataJSON": client_data_b64,
            "attestationObject": attestation_b64,
        },
        "type": "public-key",
        "clientExtensionResults": {},
    }

    verification = verify_registration_response(
        credential=credential_dict,
        expected_challenge=_base64url_to_bytes(challenge_b64url),
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        require_user_verification=False,
    )

    # Store credential using base64url encoding for consistency
    cred_id_b64url = _bytes_to_base64url(verification.credential_id)
    cred_public_key_b64url = _bytes_to_base64url(verification.credential_public_key)

    # --- Store credential in normalised table ---
    new_credential = UserPasskeyCredential(
        user_id=user.id,
        credential_id=cred_id_b64url,
        public_key=cred_public_key_b64url,
        public_key_alg=-7,  # ES256 (most common)
        sign_count=verification.sign_count,
        device_name=device_name,
    )
    db.add(new_credential)

    # --- Ensure a 'passkey' entry exists in user_mfa_methods ---
    mfa_result = await db.execute(
        select(UserMfaMethod).where(
            UserMfaMethod.user_id == user.id,
            UserMfaMethod.method == "passkey",
        )
    )
    passkey_method = mfa_result.scalar_one_or_none()
    if passkey_method is None:
        passkey_method = UserMfaMethod(
            user_id=user.id,
            method="passkey",
            verified=True,
            verified_at=datetime.now(timezone.utc),
        )
        db.add(passkey_method)
    elif not passkey_method.verified:
        passkey_method.verified = True
        passkey_method.verified_at = datetime.now(timezone.utc)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.passkey_registered",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "credential_id": cred_id_b64url,
            "device_name": device_name,
        },
    )

    return {
        "credential_id": cred_id_b64url,
        "device_name": device_name,
    }


async def generate_passkey_login_options(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Generate WebAuthn authentication options for a user.

    Uses py_webauthn v2.x ``generate_authentication_options()`` and
    ``options_to_json()``.  Stores the challenge in Redis with a 60 s TTL.
    """
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor

    # Look up user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise ValueError("No account found or account inactive")

    # Query non-flagged credentials from normalised table
    cred_result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.user_id == user.id,
            UserPasskeyCredential.flagged == False,  # noqa: E712
        )
    )
    credentials: list[UserPasskeyCredential] = list(cred_result.scalars().all())

    if not credentials:
        raise ValueError("No passkeys registered for this account")

    # Build allow list of credential IDs
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=_base64url_to_bytes(cred.credential_id))
        for cred in credentials
    ]

    options = generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow_credentials,
        timeout=60000,
    )

    options_json = json.loads(options_to_json(options))

    # Store challenge in Redis with 60s TTL
    redis = await _get_redis()
    challenge_key = f"webauthn:login:{user.id}"
    await redis.setex(challenge_key, 60, json.dumps({
        "challenge": options_json["challenge"],
        "user_id": str(user.id),
    }))

    return options_json



async def verify_passkey_login(
    db: AsyncSession,
    user_id: uuid.UUID,
    credential_response: dict,
    ip_address: str | None = None,
    device_type: str | None = None,
    browser: str | None = None,
) -> TokenResponse:
    """Verify a WebAuthn assertion response and issue JWT tokens.

    Uses py_webauthn v2.x ``verify_authentication_response()``.
    Implements clone detection: if the authenticator's sign count S' ≤
    stored sign count S (and S > 0), the credential is flagged and
    authentication is rejected.

    Passkey login satisfies MFA — no additional MFA prompt is required.

    Expects credential_response with keys:
      - credential_id: base64url-encoded credential raw ID
      - authenticator_data: base64url-encoded authenticatorData
      - client_data_json: base64url-encoded clientDataJSON
      - signature: base64url-encoded signature
      - user_handle: base64url-encoded userHandle (optional)
    """
    from webauthn import verify_authentication_response

    # Extract fields from credential response
    credential_id_b64 = credential_response.get("credential_id", "")
    authenticator_data_b64 = credential_response.get("authenticator_data", "")
    client_data_json_b64 = credential_response.get("client_data_json", "")
    signature_b64 = credential_response.get("signature", "")
    user_handle_b64 = credential_response.get("user_handle")

    if not all([credential_id_b64, authenticator_data_b64, client_data_json_b64, signature_b64]):
        raise ValueError("Missing required fields in credential response")

    # Look up credential from normalised table
    cred_result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.credential_id == credential_id_b64,
        )
    )
    matched_cred: UserPasskeyCredential | None = cred_result.scalar_one_or_none()

    if matched_cred is None:
        raise ValueError("Authentication failed")

    # Look up user
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        await _audit_failed_login(
            db,
            ip_address=ip_address,
            email=user.email if user else "unknown",
            reason="passkey_no_account" if user is None else "account_inactive",
            user_id=user.id if user else None,
            org_id=user.org_id if user else None,
        )
        raise ValueError("Authentication failed")

    # Verify credential belongs to this user
    if matched_cred.user_id != user.id:
        raise ValueError("Authentication failed")

    # Reject flagged credentials
    if matched_cred.flagged:
        await write_audit_log(
            session=db,
            org_id=user.org_id,
            user_id=user.id,
            action="auth.passkey_login_flagged_rejected",
            entity_type="user",
            entity_id=user.id,
            after_value={"credential_id": credential_id_b64},
            ip_address=ip_address,
        )
        raise ValueError(
            "Passkey credential flagged for security review. "
            "Please contact your administrator."
        )

    # IP allowlist check
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
    challenge_b64url = stored["challenge"]

    # Clean up the challenge
    await redis.delete(challenge_key)

    # Build the credential dict that py_webauthn v2.x expects
    credential_dict = {
        "id": credential_id_b64,
        "rawId": credential_id_b64,
        "response": {
            "authenticatorData": authenticator_data_b64,
            "clientDataJSON": client_data_json_b64,
            "signature": signature_b64,
        },
        "type": "public-key",
        "clientExtensionResults": {},
    }
    if user_handle_b64:
        credential_dict["response"]["userHandle"] = user_handle_b64

    verification = verify_authentication_response(
        credential=credential_dict,
        expected_challenge=_base64url_to_bytes(challenge_b64url),
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        credential_public_key=_base64url_to_bytes(matched_cred.public_key),
        credential_current_sign_count=matched_cred.sign_count,
        require_user_verification=False,
    )

    new_sign_count = verification.new_sign_count

    # Clone detection: if S' ≤ S and S > 0, flag credential and reject
    if matched_cred.sign_count > 0 and new_sign_count <= matched_cred.sign_count:
        matched_cred.flagged = True
        await db.flush()

        await write_audit_log(
            session=db,
            org_id=user.org_id,
            user_id=user.id,
            action="auth.passkey_clone_detected",
            entity_type="user",
            entity_id=user.id,
            after_value={
                "credential_id": credential_id_b64,
                "stored_sign_count": matched_cred.sign_count,
                "received_sign_count": new_sign_count,
            },
            ip_address=ip_address,
        )
        raise ValueError(
            "Passkey credential flagged for security review. "
            "Please contact your administrator."
        )

    # Update sign count (S' > S)
    matched_cred.sign_count = new_sign_count
    matched_cred.last_used_at = datetime.now(timezone.utc)
    await db.flush()

    # Passkey satisfies MFA — issue tokens directly
    # Global admins should not have org_id in their JWT (they access all orgs)
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
        branch_ids=user.branch_ids,
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
# Passkey management (Task 8.3)
# ---------------------------------------------------------------------------


async def list_passkey_credentials(
    db: AsyncSession,
    user: User,
) -> list[dict]:
    """Return all passkey credentials for a user.

    Queries the ``user_passkey_credentials`` table and returns a list of
    dicts with ``credential_id``, ``device_name``, ``created_at``, and
    ``last_used_at`` for each credential.

    Requirements: 13.1
    """
    result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.user_id == user.id,
        ).order_by(UserPasskeyCredential.created_at.desc())
    )
    credentials: list[UserPasskeyCredential] = list(result.scalars().all())

    return [
        {
            "credential_id": cred.credential_id,
            "device_name": cred.device_name,
            "created_at": cred.created_at,
            "last_used_at": cred.last_used_at,
        }
        for cred in credentials
    ]


async def rename_passkey(
    db: AsyncSession,
    user: User,
    credential_id: str,
    new_name: str,
) -> dict:
    """Rename a passkey credential's friendly name.

    Updates the ``device_name`` column on the matching
    ``UserPasskeyCredential`` row.  The new name is truncated to 50
    characters to respect the column constraint.

    Requirements: 13.2
    """
    new_name = new_name[:50]

    result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.user_id == user.id,
            UserPasskeyCredential.credential_id == credential_id,
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        raise ValueError("Passkey credential not found")

    cred.device_name = new_name
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.passkey_renamed",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "credential_id": credential_id,
            "device_name": new_name,
        },
    )

    return {
        "credential_id": cred.credential_id,
        "device_name": cred.device_name,
    }


async def remove_passkey(
    db: AsyncSession,
    user: User,
    credential_id: str,
    password: str,
) -> None:
    """Remove a passkey credential after password confirmation.

    1. Verify the user's password.
    2. Look up the credential in ``user_passkey_credentials``.
    3. Check the last-method guard: if passkey is the user's only
       verified MFA method and the organisation requires MFA, reject
       the removal.
    4. Delete the credential.  If no passkey credentials remain, also
       remove the ``passkey`` entry from ``user_mfa_methods``.

    Requirements: 13.3, 13.4, 13.5
    """
    from app.modules.admin.models import Organisation

    # 1. Verify password
    if not user.password_hash or not verify_password(password, user.password_hash):
        raise ValueError("Invalid password")

    # 2. Look up the credential
    result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.user_id == user.id,
            UserPasskeyCredential.credential_id == credential_id,
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        raise ValueError("Passkey credential not found")

    # 3. Count remaining passkey credentials (excluding the one being removed)
    count_result = await db.execute(
        select(UserPasskeyCredential).where(
            UserPasskeyCredential.user_id == user.id,
            UserPasskeyCredential.credential_id != credential_id,
        )
    )
    remaining_passkeys = len(count_result.scalars().all())

    # If this is the last passkey credential, check the last-method guard
    if remaining_passkeys == 0:
        # Count all other verified MFA methods (non-passkey)
        other_methods_result = await db.execute(
            select(UserMfaMethod).where(
                UserMfaMethod.user_id == user.id,
                UserMfaMethod.verified == True,  # noqa: E712
                UserMfaMethod.method != "passkey",
            )
        )
        other_verified_count = len(other_methods_result.scalars().all())

        if other_verified_count == 0:
            # Passkey is the only MFA method — check org policy
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
            if user.role == "global_admin":
                raise ValueError(
                    "Cannot disable the last MFA method. "
                    "At least one method is required for global administrators."
                )

    # 4. Delete the credential
    await db.delete(cred)

    # If no passkey credentials remain, remove the passkey MFA method entry
    if remaining_passkeys == 0:
        mfa_result = await db.execute(
            select(UserMfaMethod).where(
                UserMfaMethod.user_id == user.id,
                UserMfaMethod.method == "passkey",
            )
        )
        passkey_method = mfa_result.scalar_one_or_none()
        if passkey_method is not None:
            await db.delete(passkey_method)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.passkey_removed",
        entity_type="user",
        entity_id=user.id,
        after_value={"credential_id": credential_id},
    )


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

    Acquires a Redis distributed lock keyed on ``session_lock:{user_id}``
    before checking the session count to prevent race conditions from
    concurrent login attempts.

    If the active session count is >= ``max_sessions``, revokes the
    oldest session(s) to make room for one new session.

    Returns the number of sessions revoked.

    Raises ``ValueError`` if the lock cannot be acquired within 5 seconds.
    """
    from sqlalchemy import and_

    from app.core.redis import redis_pool

    lock_key = f"session_lock:{user_id}"
    lock = redis_pool.lock(lock_key, timeout=5, blocking_timeout=5)

    if not await lock.acquire():
        raise ValueError("Could not acquire session lock. Please try again.")

    try:
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
    finally:
        await lock.release()


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
        # Random delay to match real processing time — mitigates timing
        # side-channel that could reveal whether an email exists (REM-18).
        await asyncio.sleep(random.uniform(0.5, 1.5))
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

    # 2. Verify backup code (normalised table)
    import bcrypt as bcrypt_lib

    from app.modules.auth.models import UserBackupCode

    stmt = select(UserBackupCode).where(
        UserBackupCode.user_id == user.id,
        UserBackupCode.used == False,  # noqa: E712
    )
    bc_result = await db.execute(stmt)
    unused_codes = bc_result.scalars().all()

    matched = False
    for bc_entry in unused_codes:
        if bcrypt_lib.checkpw(
            backup_code.encode("utf-8"),
            bc_entry.code_hash.encode("utf-8"),
        ):
            bc_entry.used = True
            bc_entry.used_at = datetime.now(timezone.utc)
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
    if role not in ("org_admin", "salesperson", "kiosk"):
        raise ValueError("Role must be 'org_admin', 'salesperson', or 'kiosk'")

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
    from app.modules.admin.models import Organisation as _Org
    _org_r = await db.execute(select(_Org.name).where(_Org.id == org_id))
    _org_name = _org_r.scalar_one_or_none() or "your organisation"
    _base_url = getattr(settings, "frontend_base_url", "") or "http://localhost"
    await _send_invitation_email(
        email, invite_token, db=db, org_name=_org_name, base_url=_base_url,
    )

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
    # Global admins should not have org_id in their JWT (they access all orgs)
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
        branch_ids=user.branch_ids,
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
    from app.modules.admin.models import Organisation as _Org2
    _org_r2 = await db.execute(select(_Org2.name).where(_Org2.id == org_id))
    _org_name2 = _org_r2.scalar_one_or_none() or "your organisation"
    _base_url2 = getattr(settings, "frontend_base_url", "") or "http://localhost"
    await _send_invitation_email(
        email, invite_token, db=db, org_name=_org_name2, base_url=_base_url2,
    )

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


async def _get_email_providers(db: AsyncSession) -> list:
    """Return active email providers ordered by priority."""
    from app.modules.admin.models import EmailProvider
    result = await db.execute(
        select(EmailProvider)
        .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)
        .order_by(EmailProvider.priority)
    )
    return list(result.scalars().all())


async def _send_invitation_email(
    email: str,
    token: str,
    *,
    db: AsyncSession | None = None,
    org_name: str = "your organisation",
    base_url: str = "",
) -> None:
    """Send an invitation email with the secure signup link.

    Uses the active email provider configured by the global admin.
    Falls back to logging the URL in development if no provider is set.
    """
    import smtplib
    import json as _json
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    if not base_url:
        base_url = getattr(settings, "frontend_base_url", "") or "http://localhost"

    invite_url = f"{base_url}/verify-email?token={token}"

    subject = f"You've been invited to join {org_name} on OraInvoice"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1f2937; font-size: 24px; margin: 0;">You're Invited</h1>
      </div>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        Hi there,
      </p>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        You've been invited to join <strong>{org_name}</strong> on OraInvoice.
        Click the button below to set your password and get started.
      </p>

      <div style="text-align: center; margin: 30px 0;">
        <a href="{invite_url}"
           style="display: inline-block; padding: 14px 32px; background-color: #2563eb;
                  color: #ffffff; text-decoration: none; border-radius: 8px;
                  font-size: 16px; font-weight: 600;">
          Accept Invitation
        </a>
      </div>

      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
        Or copy and paste this link into your browser:<br/>
        <a href="{invite_url}" style="color: #2563eb; word-break: break-all;">{invite_url}</a>
      </p>

      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
        This invitation expires in 48 hours. If you didn't expect this email,
        you can safely ignore it.
      </p>

      <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;" />

      <p style="color: #9ca3af; font-size: 12px; text-align: center;">
        OraInvoice — Invoicing made simple
      </p>
    </div>
    """

    text_body = (
        f"You've been invited to join {org_name} on OraInvoice.\n\n"
        f"Click the link below to set your password and get started:\n"
        f"{invite_url}\n\n"
        f"This invitation expires in 48 hours.\n"
    )

    # Find active email provider
    if db is None:
        from app.core.database import async_session_factory
        async with async_session_factory() as session:
            providers = await _get_email_providers(session)
    else:
        providers = await _get_email_providers(db)

    if not providers:
        logger.warning(
            "No active email provider — cannot send invite to %s (token: %s...)",
            email, token[:8],
        )
        if settings.environment == "development":
            logger.warning("DEV INVITE URL: %s", invite_url)
        return

    from app.core.encryption import envelope_decrypt_str

    last_error = None
    for provider in providers:
        try:
            creds_json = envelope_decrypt_str(provider.credentials_encrypted)
            credentials = _json.loads(creds_json)

            smtp_host = provider.smtp_host
            smtp_port = provider.smtp_port or 587
            smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
            username = credentials.get("username") or credentials.get("api_key", "")
            password = credentials.get("password") or credentials.get("api_key", "")

            config = provider.config or {}
            from_email = config.get("from_email") or username
            from_name = config.get("from_name") or "OraInvoice"

            msg = MIMEMultipart("alternative")
            msg["From"] = f"{from_name} <{from_email}>"
            msg["To"] = email
            msg["Subject"] = subject
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, email, msg.as_string())
            server.quit()
            logger.info("Invitation email sent to %s via %s", email, provider.provider_key)
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "Email provider %s failed for invite to %s: %s",
                provider.provider_key, email, e,
            )
            continue

    logger.warning(
        "All email providers failed for invite to %s: %s (token: %s...)",
        email, last_error, token[:8],
    )
    if settings.environment == "development":
        logger.warning("DEV INVITE URL: %s", invite_url)


# ---------------------------------------------------------------------------
# Email verification for public signup (Req 8.7)
# ---------------------------------------------------------------------------

_VERIFY_TOKEN_EXPIRY_SECONDS = 48 * 3600  # 48 hours


async def create_email_verification_token(
    user_id: uuid.UUID,
    email: str,
) -> str:
    """Generate a verification token and store it in Redis.

    Returns the raw token (to be included in the verification URL).
    """
    from app.core.redis import redis_pool

    token = secrets.token_urlsafe(48)
    token_hash = _hash_invite_token(token)
    token_data = json.dumps({
        "user_id": str(user_id),
        "email": email,
        "type": "email_verification",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await redis_pool.setex(
        f"email_verify:{token_hash}",
        _VERIFY_TOKEN_EXPIRY_SECONDS,
        token_data,
    )
    return token


async def verify_signup_email(
    db: AsyncSession,
    *,
    token: str,
    ip_address: str | None = None,
    device_type: str | None = None,
    browser: str | None = None,
) -> dict:
    """Verify a signup email using the token from the verification link.

    Marks the user's email as verified and issues a JWT pair so the
    user is logged in immediately.

    Raises ``ValueError`` on invalid/expired token.
    """
    from app.core.redis import redis_pool

    token_hash = _hash_invite_token(token)
    redis_key = f"email_verify:{token_hash}"

    stored_data = await redis_pool.get(redis_key)
    if stored_data is None:
        raise ValueError("Invalid or expired verification link")

    token_info = json.loads(
        stored_data if isinstance(stored_data, str) else stored_data.decode()
    )
    user_id = uuid.UUID(token_info["user_id"])

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("Invalid or expired verification link")

    if user.is_email_verified:
        raise ValueError("Email has already been verified")

    # Mark email as verified
    user.is_email_verified = True

    # Consume the token
    await redis_pool.delete(redis_key)

    # Issue JWT pair
    token_org_id = None if user.role == "global_admin" else user.org_id
    access_token = create_access_token(
        user_id=user.id,
        org_id=token_org_id,
        role=user.role,
        email=user.email,
        branch_ids=user.branch_ids,
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
        action="auth.signup_email_verified",
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


async def send_verification_email(
    db,
    *,
    email: str,
    user_name: str,
    org_name: str,
    verification_token: str,
    base_url: str,
) -> None:
    """Send a welcome/verification email to a newly signed-up user.

    Uses the email_providers table (same as invoice/quote emails).
    Falls back to logging the verification URL if no provider is configured.
    """
    import smtplib
    import json as _json
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from sqlalchemy import select as _select
    from app.modules.admin.models import EmailProvider
    from app.core.encryption import envelope_decrypt_str

    verify_url = f"{base_url}/verify-email?token={verification_token}&type=signup"
    login_url = f"{base_url}/login"

    subject = "Welcome to OraInvoice — Verify your email"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1f2937; font-size: 24px; margin: 0;">Welcome to OraInvoice</h1>
      </div>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        Hi {user_name},
      </p>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        Thanks for signing up! Your organisation <strong>{org_name}</strong> has been created.
        Please verify your email address to activate your account.
      </p>

      <div style="text-align: center; margin: 30px 0;">
        <a href="{verify_url}"
           style="display: inline-block; padding: 14px 32px; background-color: #2563eb;
                  color: #ffffff; text-decoration: none; border-radius: 8px;
                  font-size: 16px; font-weight: 600;">
          Verify Email Address
        </a>
      </div>

      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
        Once verified, you can log in at:<br/>
        <a href="{login_url}" style="color: #2563eb;">{login_url}</a>
      </p>

      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
        This verification link expires in 48 hours. If you didn't create this account,
        you can safely ignore this email.
      </p>

      <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;" />

      <p style="color: #9ca3af; font-size: 12px; text-align: center;">
        OraInvoice — Invoicing made simple
      </p>
    </div>
    """

    text_body = (
        f"Hi {user_name},\n\n"
        f"Thanks for signing up! Your organisation {org_name} has been created.\n"
        f"Please verify your email address to activate your account.\n\n"
        f"Verify here: {verify_url}\n\n"
        f"Once verified, log in at: {login_url}\n\n"
        f"This link expires in 48 hours.\n"
    )

    # Find active email providers ordered by priority (same pattern as invoice emails)
    provider_result = await db.execute(
        _select(EmailProvider)
        .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())

    if not providers:
        logger.warning(
            "No active email provider configured — cannot send verification email to %s (token: %s...)",
            email,
            verification_token[:8],
        )
        if settings.environment == "development":
            logger.warning("DEV VERIFICATION URL: %s", verify_url)
        return

    # Try each provider in priority order until one succeeds
    last_error = None
    for provider in providers:
        try:
            creds_json = envelope_decrypt_str(provider.credentials_encrypted)
            credentials = _json.loads(creds_json)

            smtp_host = provider.smtp_host
            smtp_port = provider.smtp_port or 587
            smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
            username = credentials.get("username") or credentials.get("api_key", "")
            password = credentials.get("password") or credentials.get("api_key", "")

            config = provider.config or {}
            from_email = config.get("from_email") or username
            from_name = config.get("from_name") or "OraInvoice"

            msg = MIMEMultipart("alternative")
            msg["From"] = f"{from_name} <{from_email}>"
            msg["To"] = email
            msg["Subject"] = subject
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, email, msg.as_string())
            server.quit()
            logger.info("Verification email sent to %s via %s", email, provider.provider_key)
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "Email provider %s failed for verification email to %s: %s",
                provider.provider_key, email, e,
            )
            continue

    logger.warning(
        "All email providers failed for verification email to %s: %s (token: %s...)",
        email, last_error, verification_token[:8],
    )
    if settings.environment == "development":
        logger.warning("DEV VERIFICATION URL: %s", verify_url)


async def resend_verification_email(
    db: AsyncSession,
    *,
    email: str,
    base_url: str,
) -> dict:
    """Resend the verification email for a user who hasn't verified yet.

    Generates a new token and sends a fresh email.
    Returns a dict with status info.

    Raises ``ValueError`` if user not found or already verified.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        # Don't reveal whether the email exists
        return {"message": "If that email is registered, a verification link has been sent."}

    if user.is_email_verified:
        return {"message": "If that email is registered, a verification link has been sent."}

    # Get org name for the email
    from app.modules.admin.models import Organisation
    org_name = "your organisation"
    if user.org_id:
        org_result = await db.execute(
            select(Organisation.name).where(Organisation.id == user.org_id)
        )
        name = org_result.scalar_one_or_none()
        if name:
            org_name = name

    user_name = user.email.split("@")[0]

    token = await create_email_verification_token(user.id, user.email)
    await send_verification_email(
        db,
        email=user.email,
        user_name=user_name,
        org_name=org_name,
        verification_token=token,
        base_url=base_url,
    )

    return {"message": "If that email is registered, a verification link has been sent."}


async def send_receipt_email(
    db,
    *,
    email: str,
    user_name: str,
    org_name: str,
    plan_name: str,
    amount_cents: int,
    plan_amount_cents: int = 0,
    gst_amount_cents: int = 0,
    gst_percentage: float = 0,
    processing_fee_cents: int = 0,
    verification_token: str,
    base_url: str,
) -> None:
    """Send a receipt email with payment summary and verification link.

    Sent after successful payment confirmation for paid-plan signups.
    Uses the same email provider infrastructure as verification emails.

    Requirements: 4.1, 4.2
    """
    import smtplib
    import json as _json
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from sqlalchemy import select as _select
    from app.modules.admin.models import EmailProvider
    from app.core.encryption import envelope_decrypt_str

    verify_url = f"{base_url}/verify-email?token={verification_token}&type=signup"
    login_url = f"{base_url}/login"
    amount_display = f"${amount_cents / 100:.2f}"

    # Build breakdown rows for the receipt
    has_breakdown = plan_amount_cents > 0 and gst_amount_cents > 0
    if has_breakdown:
        plan_display = f"${plan_amount_cents / 100:.2f}"
        gst_display = f"${gst_amount_cents / 100:.2f}"
        fee_display = f"${processing_fee_cents / 100:.2f}"
        breakdown_html = f"""
          <tr>
            <td style="color: #6b7280; padding: 4px 0;">{plan_name} (monthly)</td>
            <td style="color: #1f2937; text-align: right; padding: 4px 0;">{plan_display}</td>
          </tr>
          <tr>
            <td style="color: #6b7280; padding: 4px 0;">GST ({gst_percentage}%)</td>
            <td style="color: #1f2937; text-align: right; padding: 4px 0;">{gst_display}</td>
          </tr>"""
        if processing_fee_cents > 0:
            breakdown_html += f"""
          <tr>
            <td style="color: #6b7280; padding: 4px 0;">Payment processing fee</td>
            <td style="color: #1f2937; text-align: right; padding: 4px 0;">{fee_display}</td>
          </tr>"""
        breakdown_html += f"""
          <tr style="border-top: 1px solid #e5e7eb;">
            <td style="color: #1f2937; padding: 8px 0 4px 0; font-weight: 600;">Total charged</td>
            <td style="color: #1f2937; text-align: right; padding: 8px 0 4px 0; font-weight: 600;">{amount_display} NZD</td>
          </tr>"""
        breakdown_text = (
            f"  {plan_name} (monthly): {plan_display}\n"
            f"  GST ({gst_percentage}%): {gst_display}\n"
            + (f"  Processing fee: {fee_display}\n" if processing_fee_cents > 0 else "")
            + f"  Total charged: {amount_display} NZD\n"
        )
    else:
        breakdown_html = f"""
          <tr>
            <td style="color: #6b7280; padding: 4px 0;">Plan</td>
            <td style="color: #1f2937; text-align: right; padding: 4px 0; font-weight: 600;">{plan_name}</td>
          </tr>
          <tr>
            <td style="color: #6b7280; padding: 4px 0;">Amount charged</td>
            <td style="color: #1f2937; text-align: right; padding: 4px 0; font-weight: 600;">{amount_display}</td>
          </tr>"""
        breakdown_text = (
            f"  Plan: {plan_name}\n"
            f"  Amount charged: {amount_display}\n"
        )

    subject = "OraInvoice — Payment receipt & email verification"

    html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1f2937; font-size: 24px; margin: 0;">Welcome to OraInvoice</h1>
      </div>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        Hi {user_name},
      </p>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        Thank you for your payment! Your organisation <strong>{org_name}</strong> has been created
        on the <strong>{plan_name}</strong> plan.
      </p>

      <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin: 20px 0;">
        <h2 style="color: #1f2937; font-size: 18px; margin: 0 0 12px 0;">Payment Summary</h2>
        <table style="width: 100%; border-collapse: collapse;">
          {breakdown_html}
        </table>
      </div>

      <p style="color: #374151; font-size: 16px; line-height: 1.6;">
        Please verify your email address to activate your account:
      </p>

      <div style="text-align: center; margin: 30px 0;">
        <a href="{verify_url}"
           style="display: inline-block; padding: 14px 32px; background-color: #2563eb;
                  color: #ffffff; text-decoration: none; border-radius: 8px;
                  font-size: 16px; font-weight: 600;">
          Verify Email &amp; Activate Account
        </a>
      </div>

      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
        Once verified, you can log in at:<br/>
        <a href="{login_url}" style="color: #2563eb;">{login_url}</a>
      </p>

      <p style="color: #6b7280; font-size: 14px; line-height: 1.6;">
        This verification link expires in 48 hours. If you didn't create this account,
        please contact support.
      </p>

      <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 30px 0;" />

      <p style="color: #9ca3af; font-size: 12px; text-align: center;">
        OraInvoice — Invoicing made simple
      </p>
    </div>
    """

    text_body = (
        f"Hi {user_name},\n\n"
        f"Thank you for your payment! Your organisation {org_name} has been created "
        f"on the {plan_name} plan.\n\n"
        f"Payment Summary\n"
        + breakdown_text
        + f"\nPlease verify your email to activate your account:\n"
        f"{verify_url}\n\n"
        f"Once verified, log in at: {login_url}\n\n"
        f"This link expires in 48 hours.\n"
    )

    # Find active email providers ordered by priority
    provider_result = await db.execute(
        _select(EmailProvider)
        .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())

    if not providers:
        logger.warning(
            "No active email provider configured — cannot send receipt email to %s (token: %s...)",
            email,
            verification_token[:8],
        )
        if settings.environment == "development":
            logger.warning("DEV VERIFICATION URL: %s", verify_url)
        return

    last_error = None
    for provider in providers:
        try:
            creds_json = envelope_decrypt_str(provider.credentials_encrypted)
            credentials = _json.loads(creds_json)

            smtp_host = provider.smtp_host
            smtp_port = provider.smtp_port or 587
            smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
            username = credentials.get("username") or credentials.get("api_key", "")
            password = credentials.get("password") or credentials.get("api_key", "")

            config = provider.config or {}
            from_email = config.get("from_email") or username
            from_name = config.get("from_name") or "OraInvoice"

            msg = MIMEMultipart("alternative")
            msg["From"] = f"{from_name} <{from_email}>"
            msg["To"] = email
            msg["Subject"] = subject
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, email, msg.as_string())
            server.quit()
            logger.info("Receipt email sent to %s via %s", email, provider.provider_key)
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "Email provider %s failed for receipt email to %s: %s",
                provider.provider_key, email, e,
            )
            continue

    logger.warning(
        "All email providers failed for receipt email to %s: %s (token: %s...)",
        email, last_error, verification_token[:8],
    )
    if settings.environment == "development":
        logger.warning("DEV VERIFICATION URL: %s", verify_url)
