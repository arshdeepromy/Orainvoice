"""Routers for the public landing page endpoints.

Public endpoints (no auth):
- POST /api/v1/public/demo-request
- GET  /api/v1/public/privacy-policy

Admin endpoints (global_admin only):
- PUT  /api/v1/admin/privacy-policy
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.encryption import envelope_decrypt_str
from app.core.redis import get_redis
from app.modules.admin.models import EmailProvider
from app.modules.auth.rbac import require_role
from app.core.audit import write_audit_log
from app.modules.landing.schemas import (
    DemoRequestPayload,
    DemoRequestResponse,
    PrivacyPolicyResponse,
    PrivacyPolicyUpdatePayload,
    PrivacyPolicyUpdateResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public router — no auth required
# ---------------------------------------------------------------------------

public_router = APIRouter()

DEMO_REQUEST_RECIPIENT = "arshdeep.romy@gmail.com"
RATE_LIMIT_MAX = 5
RATE_LIMIT_TTL = 3600  # 1 hour in seconds


@public_router.post(
    "/demo-request",
    response_model=DemoRequestResponse,
)
async def submit_demo_request(
    payload: DemoRequestPayload,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Accept a demo request form submission and send an email notification.

    - Honeypot check: if ``website`` is non-empty, silently accept (200) without
      sending an email.
    - Rate limiting: max 5 requests per IP per hour via Redis.  If Redis is
      unavailable the request is allowed through (fail-open).
    - Email: sent via the first active ``EmailProvider`` with credentials,
      ordered by priority.  Falls over to the next provider on error.
    """
    client_ip = request.client.host if request.client else "unknown"

    # ------------------------------------------------------------------
    # 1. Honeypot — silent rejection
    # ------------------------------------------------------------------
    if payload.website:
        return DemoRequestResponse(
            success=True,
            message="Thank you! Our team will be in touch within 24 hours to schedule your demo.",
        )

    # ------------------------------------------------------------------
    # 2. Redis rate limiting (fail-open if Redis unavailable)
    # ------------------------------------------------------------------
    rate_limited = await _check_rate_limit(redis, client_ip)
    if rate_limited:
        return JSONResponse(
            status_code=429,
            content={"success": False, "message": "Too many requests. Please try again later."},
        )

    # ------------------------------------------------------------------
    # 3. Query active email providers ordered by priority
    # ------------------------------------------------------------------
    provider_result = await db.execute(
        select(EmailProvider)
        .where(
            EmailProvider.is_active == True,  # noqa: E712
            EmailProvider.credentials_set == True,  # noqa: E712
        )
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())

    if not providers:
        logger.error("No active email provider configured — cannot send demo request email")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Email service not configured"},
        )

    # ------------------------------------------------------------------
    # 4. Build MIME email
    # ------------------------------------------------------------------
    now_utc = datetime.now(timezone.utc)
    subject = f"New Demo Request from {payload.full_name} — {payload.business_name}"
    body = (
        "New demo request received:\n"
        "\n"
        f"Name: {payload.full_name}\n"
        f"Business: {payload.business_name}\n"
        f"Email: {payload.email}\n"
        f"Phone: {payload.phone or 'Not provided'}\n"
        "\n"
        "Message:\n"
        f"{payload.message or 'No message provided'}\n"
        "\n"
        "---\n"
        "Sent from OraInvoice Landing Page\n"
        f"IP: {client_ip}\n"
        f"Timestamp: {now_utc.isoformat()}\n"
    )

    # ------------------------------------------------------------------
    # 5. Send with failover across providers
    # ------------------------------------------------------------------
    last_error: Exception | None = None
    for provider in providers:
        try:
            creds_json = envelope_decrypt_str(provider.credentials_encrypted)
            credentials = json.loads(creds_json)

            smtp_host = provider.smtp_host
            smtp_port = provider.smtp_port or 587
            smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
            username = credentials.get("username") or credentials.get("api_key", "")
            password = credentials.get("password") or credentials.get("api_key", "")

            config = provider.config or {}
            from_email = config.get("from_email") or username
            from_name = config.get("from_name") or "OraInvoice"

            msg = MIMEMultipart("mixed")
            msg["From"] = f"{from_name} <{from_email}>"
            msg["To"] = DEMO_REQUEST_RECIPIENT
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, DEMO_REQUEST_RECIPIENT, msg.as_string())
            server.quit()

            logger.info(
                "Demo request email sent via %s for %s (%s)",
                provider.provider_key,
                payload.full_name,
                payload.email,
            )
            return DemoRequestResponse(
                success=True,
                message="Thank you! Our team will be in touch within 24 hours to schedule your demo.",
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Email provider %s failed for demo request: %s",
                provider.provider_key,
                exc,
            )
            continue

    logger.error("All email providers failed for demo request. Last error: %s", last_error)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Failed to send email"},
    )


async def _check_rate_limit(redis: aioredis.Redis, client_ip: str) -> bool:
    """Return True if the client IP has exceeded the demo request rate limit.

    Uses a simple INCR + EXPIRE pattern.  If Redis is unavailable the request
    is allowed through (fail-open) and a warning is logged.
    """
    key = f"demo_request_rate:{client_ip}"
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, RATE_LIMIT_TTL)
        return current > RATE_LIMIT_MAX
    except Exception:
        logger.warning("Redis unavailable for rate limiting — allowing request through (fail-open)")
        return False


@public_router.get(
    "/privacy-policy",
    response_model=PrivacyPolicyResponse,
)
async def get_privacy_policy(
    db: AsyncSession = Depends(get_db_session),
):
    """Return the custom privacy policy content from platform_settings.

    If no custom policy has been saved, returns ``{ content: null, last_updated: null }``.
    No authentication required.
    """
    row = await db.execute(
        sa_text(
            "SELECT value, updated_at FROM platform_settings WHERE key = :k"
        ),
        {"k": "privacy_policy"},
    )
    result = row.first()

    if result is None:
        return PrivacyPolicyResponse(content=None, last_updated=None)

    value = result[0] if isinstance(result[0], dict) else json.loads(result[0])
    updated_at = result[1]

    return PrivacyPolicyResponse(
        content=value.get("content"),
        last_updated=updated_at.isoformat() if updated_at else None,
    )


# ---------------------------------------------------------------------------
# Admin router — global_admin only
# ---------------------------------------------------------------------------

admin_router = APIRouter(dependencies=[require_role("global_admin")])


@admin_router.put(
    "/privacy-policy",
    response_model=PrivacyPolicyUpdateResponse,
)
async def update_privacy_policy(
    payload: PrivacyPolicyUpdatePayload,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create or update the custom privacy policy content.

    Upserts into ``platform_settings`` with key ``privacy_policy``.
    Requires ``global_admin`` role (enforced by router dependency).

    Requirements 21.1, 21.2, 21.3, 21.7.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    new_val = {
        "content": payload.content,
        "updated_by": user_id,
    }

    # ------------------------------------------------------------------
    # Upsert: check if key exists, then UPDATE or INSERT
    # ------------------------------------------------------------------
    row = await db.execute(
        sa_text(
            "SELECT value, version FROM platform_settings "
            "WHERE key = :k FOR UPDATE"
        ),
        {"k": "privacy_policy"},
    )
    existing = row.first()

    if existing:
        old_version = existing[1] or 1
        new_version = old_version + 1
        await db.execute(
            sa_text(
                "UPDATE platform_settings SET value = :v, version = :ver, "
                "updated_at = now() WHERE key = :k"
            ),
            {
                "k": "privacy_policy",
                "v": json.dumps(new_val),
                "ver": new_version,
            },
        )
    else:
        new_version = 1
        await db.execute(
            sa_text(
                "INSERT INTO platform_settings (key, value, version, updated_at) "
                "VALUES (:k, :v, :ver, now())"
            ),
            {
                "k": "privacy_policy",
                "v": json.dumps(new_val),
                "ver": new_version,
            },
        )

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    await write_audit_log(
        db,
        action="platform_settings.update_privacy_policy",
        entity_type="platform_settings",
        entity_id=None,
        user_id=user_id,
        ip_address=ip_address,
        after_value={
            "version": new_version,
            "content_length": len(payload.content),
        },
    )

    # Flush (auto-committed by session.begin()) and fetch the timestamp
    await db.flush()

    ts_row = await db.execute(
        sa_text("SELECT updated_at FROM platform_settings WHERE key = :k"),
        {"k": "privacy_policy"},
    )
    updated_at = ts_row.scalar_one()

    return PrivacyPolicyUpdateResponse(
        success=True,
        last_updated=updated_at.isoformat(),
    )
