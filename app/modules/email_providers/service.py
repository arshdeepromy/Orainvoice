"""Business logic for Email Providers."""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_encrypt
from app.integrations.email_sender import (
    EmailMessage,
    FailureKind,
    dispatch_one_provider,
)
from app.modules.admin.models import EmailProvider

logger = logging.getLogger(__name__)


# Custom HTTP header that Brevo / SendGrid must echo on every webhook
# call, carrying the per-provider token an admin generated through the
# OraInvoice GUI. Same header name across both providers so the admin
# learns one flow.
WEBHOOK_TOKEN_HEADER: str = "X-OraInvoice-Webhook-Token"

# Set of provider keys for which webhook auth is supported. Both
# providers' bounce webhooks land on a public URL inside this app and
# must carry the token; SMTP-only providers (mailgun, ses, gmail,
# outlook, custom_smtp) have no webhook concept.
WEBHOOK_TOKEN_PROVIDERS: set[str] = {"brevo", "sendgrid"}


async def list_email_providers(db: AsyncSession) -> dict:
    """Return all email providers, the active set, and the highest-priority active key.

    Phase 5 (task 5.3) extension: the response now exposes
    ``active_providers: list[str]`` — every active provider key in
    ``priority ASC`` order — so the admin UI can render a multi-active
    failover chain. The legacy ``active_provider: str | None`` field is
    retained for one release as the first element of that list (or
    ``None`` when no provider is active).
    """
    result = await db.execute(
        select(EmailProvider).order_by(EmailProvider.display_name)
    )
    providers = result.scalars().all()

    # Compute the active set ordered by priority ASC (lower priority value =
    # tried first). ``priority`` is nullable on legacy rows; treat NULL as
    # the default priority of 1 so failover ordering is deterministic.
    active_sorted = sorted(
        (p for p in providers if p.is_active),
        key=lambda p: getattr(p, "priority", 1) or 1,
    )
    active_keys = [p.provider_key for p in active_sorted]

    return {
        "providers": [_provider_to_dict(p) for p in providers],
        "active_provider": active_keys[0] if active_keys else None,
        "active_providers": active_keys,
    }


async def activate_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Activate a provider without deactivating any other row.

    Phase 5 (task 5.1) rewrite. Per Requirement 9.1, this endpoint must
    set ``is_active=True`` on the named row only and must NOT touch any
    other row's flag — multi-active failover is the whole point of the
    new sender. The function is idempotent (Req 9.2): if the row is
    already active, it returns the current state without writing an
    audit-log entry. The audit action name is ``email_provider_activated``
    (Req 9.7), replacing the legacy ``set_as_only_active``-style name.

    For defence-in-depth and to mirror :func:`deactivate_email_provider`
    we acquire ``SELECT ... FOR UPDATE`` on the target row. Activating a
    single row can never violate the "≥1 active" invariant on its own,
    but matching the lock pattern keeps the two handlers symmetric and
    serialises an admin who is hammering both buttons in quick succession.
    """
    result = await db.execute(
        select(EmailProvider)
        .where(EmailProvider.provider_key == provider_key)
        .with_for_update()
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    if provider.is_active:
        # Already active — idempotent return, no audit-log entry.
        return _provider_to_dict(provider)

    provider.is_active = True
    await db.flush()
    await db.refresh(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_activated",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key},
        ip_address=ip_address,
    )
    return _provider_to_dict(provider)


async def deactivate_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Deactivate a provider, refusing to leave the platform with zero active senders.

    Phase 5 (task 5.2) rewrite. The race we're guarding against is two
    admin tabs each clicking Deactivate on the last two active providers
    in the same second: without locking, both reads pass the "≥1 must
    remain" guard, both writes commit, and outbound email goes dark. The
    fix (per design Concurrency > Activate / Deactivate, Req 9.3) is to
    acquire ``SELECT ... FOR UPDATE`` over every row in the
    Active_Provider_Set so concurrent calls serialise on PG row locks.

    Behaviour:

    1. Lock every active row, look up the target inside that set.
    2. If the target is not in the active set, fall back to an unlocked
       lookup. ``None`` returned to the router signals 404; an existing
       (already-inactive) row is returned idempotently so the UI's retry
       button is harmless.
    3. If deactivating the target would leave ``remaining_after`` empty,
       raise ``HTTPException(409)`` with the exact admin-facing copy
       from Req 9.4.
    4. Otherwise flip ``is_active=False``, flush, write the audit log.
    """
    locked = await db.execute(
        select(EmailProvider)
        .where(EmailProvider.is_active.is_(True))
        .with_for_update()
    )
    active_set = list(locked.scalars().all())

    target = next(
        (p for p in active_set if p.provider_key == provider_key), None
    )

    if target is None:
        # Not in the active set. Re-fetch unlocked to distinguish 404
        # (no row at all) from idempotent no-op (already inactive).
        existing_result = await db.execute(
            select(EmailProvider).where(
                EmailProvider.provider_key == provider_key
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is None:
            return None  # router converts to HTTP 404
        return _provider_to_dict(existing)

    remaining_after = [p for p in active_set if p.provider_key != provider_key]
    if not remaining_after:
        raise HTTPException(
            status_code=409,
            detail=(
                "Activate another provider before deactivating this one — "
                "at least one active email provider is required for "
                "outbound mail."
            ),
        )

    target.is_active = False
    await db.flush()
    await db.refresh(target)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_deactivated",
        entity_type="email_provider",
        entity_id=target.id,
        after_value={"provider_key": provider_key},
        ip_address=ip_address,
    )
    return _provider_to_dict(target)


async def save_email_credentials(
    db: AsyncSession,
    *,
    provider_key: str,
    credentials: dict,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_encryption: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
    webhook_secret: str | None = None,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Save encrypted credentials and optional config for a provider.

    The legacy ``webhook_secret`` keyword arg is retained for backwards
    compatibility but is now a no-op: webhook auth has moved from
    HMAC-signed payloads (which Brevo doesn't actually support — it
    only offers Basic Auth or a custom-header static token) to a
    server-generated per-provider token via
    :func:`regenerate_webhook_token` and the
    ``POST /api/v2/admin/email-providers/{key}/webhook-token/regenerate``
    endpoint. Old API callers that still send ``webhook_secret`` get
    a 200 + warning log; they should migrate to the regenerate flow.
    """
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    encrypted = envelope_encrypt(json.dumps(credentials))
    provider.credentials_encrypted = encrypted
    provider.credentials_set = True

    if smtp_host is not None:
        provider.smtp_host = smtp_host
    if smtp_port is not None:
        provider.smtp_port = smtp_port
    if smtp_encryption is not None and hasattr(provider, 'smtp_encryption'):
        provider.smtp_encryption = smtp_encryption

    config = dict(provider.config or {})
    if from_email is not None:
        config["from_email"] = from_email
    if from_name is not None:
        config["from_name"] = from_name
    if reply_to is not None:
        config["reply_to"] = reply_to

    # Legacy webhook_secret arg is ignored. The new flow generates a
    # server-side token via regenerate_webhook_token() — Brevo and
    # SendGrid don't sign payloads, only carry static auth headers,
    # which made HMAC verification a dead path.
    if webhook_secret is not None and webhook_secret.strip():
        logger.warning(
            "save_email_credentials: ignoring deprecated webhook_secret "
            "field for provider_key=%s — use POST /webhook-token/regenerate",
            provider_key,
        )

    provider.config = config

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_credentials_saved",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key, "credentials_set": True},
        ip_address=ip_address,
    )
    return {"credentials_set": True}


# ---------------------------------------------------------------------------
# Webhook token (Brevo / SendGrid bounce webhook auth)
# ---------------------------------------------------------------------------


def _token_config_key(provider_key: str) -> str:
    """Return the ``email_providers.config`` JSON key that stores the
    webhook token for a given provider."""
    return f"{provider_key}_webhook_token"


def _token_set_at_key(provider_key: str) -> str:
    """JSON key for the timestamp of the most-recent token regeneration.
    Surfaced in the admin GUI so an operator can sanity-check whether
    a given provider's token is fresh after a rotation."""
    return f"{provider_key}_webhook_token_set_at"


async def regenerate_webhook_token(
    db: AsyncSession,
    *,
    provider_key: str,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Generate a fresh webhook auth token for a provider.

    The token is generated server-side (admins never paste one in;
    Brevo / SendGrid don't issue one — we issue ours and the admin
    pastes it into the provider's webhook UI under "Token
    Authentication" or "Custom Header"). Stored in
    ``email_providers.config['<provider>_webhook_token']`` plus a
    ``_webhook_token_set_at`` timestamp for the GUI's freshness
    indicator.

    Returns:
        ``{"token": "<plaintext>", "header_name": "X-OraInvoice-...",
        "set_at": "<ISO-8601>"}`` on success — the **only time** the
        plaintext token is ever returned. After this single response
        the GUI is responsible for showing it to the admin and
        encouraging them to copy it; subsequent reads of the provider
        config will redact it to ``"***"``.

        ``None`` when the provider row doesn't exist.

    Raises:
        ``HTTPException(400)`` if the provider isn't one of the
        webhook-supporting kinds (Brevo / SendGrid). SMTP-only
        providers have no webhook to authenticate.
    """
    if provider_key not in WEBHOOK_TOKEN_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider '{provider_key}' has no bounce webhook — "
                f"webhook tokens are only supported for "
                f"{sorted(WEBHOOK_TOKEN_PROVIDERS)}."
            ),
        )

    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    # 32 random bytes → 43 URL-safe base64 characters → ~256 bits of
    # entropy. Plenty for a static-token webhook auth header.
    token = secrets.token_urlsafe(32)
    set_at = datetime.now(timezone.utc).isoformat()

    config = dict(provider.config or {})
    config[_token_config_key(provider_key)] = token
    config[_token_set_at_key(provider_key)] = set_at
    # Best-effort cleanup of the legacy *_webhook_secret keys so the
    # GUI's redaction logic never has to display a stale "***" alongside
    # a fresh token. Safe even if the keys aren't present.
    config.pop(f"{provider_key}_webhook_secret", None)
    provider.config = config

    await db.flush()
    await db.refresh(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_webhook_token_regenerated",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key, "set_at": set_at},
        ip_address=ip_address,
    )

    return {
        "token": token,
        "header_name": WEBHOOK_TOKEN_HEADER,
        "set_at": set_at,
    }


async def get_webhook_config(
    db: AsyncSession,
    *,
    provider_key: str,
    base_url: str,
) -> dict | None:
    """Return the webhook URL, header name, and configuration status.

    Used by the admin GUI to render the "Webhook configuration" panel.
    Never returns the token plaintext — callers must regenerate to see
    a token (intentional: the GUI shows tokens once and only once).

    The webhook URL is computed from ``base_url`` (typically the
    incoming request's ``Origin`` header per
    ``extract_request_base_url``, falling back to
    ``settings.frontend_base_url``) joined with the bounce-webhook
    path for the provider.

    Returns ``None`` when the provider row doesn't exist; raises
    ``HTTPException(400)`` for non-webhook-supporting providers.
    """
    if provider_key not in WEBHOOK_TOKEN_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Provider '{provider_key}' has no bounce webhook."
            ),
        )

    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    config = provider.config or {}
    token_value = config.get(_token_config_key(provider_key))
    set_at = config.get(_token_set_at_key(provider_key))

    return {
        "webhook_url": (
            f"{base_url.rstrip('/')}"
            f"/api/v1/notifications/webhooks/{provider_key}-bounce"
        ),
        "header_name": WEBHOOK_TOKEN_HEADER,
        "token_configured": bool(token_value),
        "token_set_at": set_at,
    }


def _provider_to_dict(p: EmailProvider) -> dict:
    """Convert an EmailProvider ORM instance to a serialisable dict."""
    return {
        "id": str(p.id),
        "provider_key": p.provider_key,
        "display_name": p.display_name,
        "description": p.description,
        "smtp_host": p.smtp_host,
        "smtp_port": p.smtp_port,
        "smtp_encryption": getattr(p, 'smtp_encryption', None),
        "priority": getattr(p, 'priority', 1) or 1,
        "is_active": p.is_active,
        "credentials_set": p.credentials_set,
        "config": p.config or {},
        "setup_guide": p.setup_guide,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def test_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    to_email: str | None = None,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Send a test email using the specified provider.

    Phase 3 (task 3.15) refactor: delegates to the unified
    :func:`app.integrations.email_sender.dispatch_one_provider` helper so
    SMTP and REST transports live in exactly one module
    (``app/integrations/email_sender.py``). The wire contract of
    ``POST /api/v2/admin/email-providers/{key}/test`` is unchanged: the
    ``{success, message, error}`` shape and the
    ``admin.email_provider_test_sent`` audit-log call are preserved.
    """
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return {"success": False, "message": "Provider not found", "error": "Provider not found"}

    if not provider.credentials_set or not provider.credentials_encrypted:
        return {
            "success": False,
            "message": "Credentials not configured",
            "error": "Please configure credentials first",
        }

    if not to_email:
        return {"success": False, "message": "No recipient email", "error": "Recipient email required"}

    subject = f"Test Email from {provider.display_name}"
    text_body = (
        "This is a test email sent from your email provider configuration.\n\n"
        f"Provider: {provider.display_name}\n\n"
        "If you received this email, your email provider is configured correctly!"
    )
    message = EmailMessage(
        to_email=to_email,
        subject=subject,
        text_body=text_body,
    )

    attempt = await dispatch_one_provider(db, provider, message)

    if attempt.success:
        await write_audit_log(
            session=db,
            org_id=None,
            user_id=admin_user_id,
            action="admin.email_provider_test_sent",
            entity_type="email_provider",
            entity_id=provider.id,
            after_value={
                "provider_key": provider_key,
                "to_email": to_email,
                "success": True,
            },
            ip_address=ip_address,
        )
        return {"success": True, "message": f"Test email sent to {to_email}"}

    # Failure path. Map the FailureKind back to the user-facing
    # message/error pair the legacy implementation produced so the admin
    # UI's existing copy keeps working.
    error_text = attempt.error or "Failed to send test email"
    if attempt.failure_kind == FailureKind.SOFT_AUTH:
        if "credentials not configured" in error_text or "decrypt credentials" in error_text:
            # Decryption failures or missing credentials surface as their
            # own message (mirrors the legacy "Failed to decrypt
            # credentials" / "Credentials not configured" branches).
            if "decrypt credentials" in error_text:
                return {
                    "success": False,
                    "message": "Failed to decrypt credentials",
                    "error": error_text,
                }
            return {
                "success": False,
                "message": "Credentials not configured",
                "error": error_text,
            }
        return {
            "success": False,
            "message": "Authentication failed",
            "error": error_text,
        }
    if attempt.failure_kind == FailureKind.SOFT_PROVIDER and attempt.transport == "":
        # Pre-dispatch config error from dispatch_one_provider (e.g.
        # "missing from_email"). Surface as a config message.
        return {
            "success": False,
            "message": "Provider configuration error",
            "error": error_text,
        }
    return {
        "success": False,
        "message": "Failed to send test email",
        "error": error_text,
    }


async def update_email_provider_priority(
    db: AsyncSession,
    *,
    provider_key: str,
    priority: int,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> int | None:
    """Update the priority of an email provider."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None
    
    old_priority = getattr(provider, 'priority', 1)
    if hasattr(provider, 'priority'):
        provider.priority = priority
    await db.flush()
    
    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_priority_updated",
        entity_type="email_provider",
        entity_id=provider.id,
        before_value={"priority": old_priority},
        after_value={"priority": priority},
        ip_address=ip_address,
    )
    
    return priority


# ---------------------------------------------------------------------------
# Delivery Health (Phase 8c, task 9.9)
# ---------------------------------------------------------------------------


async def get_delivery_health(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    offset: int = 0,
    limit: int = 100,
) -> dict:
    """Return Delivery Health stats + paginated recent bounces.

    The aggregate stats query the ``notification_log`` table because
    that's where bounces have ``provider_key`` plus a precise
    ``bounced_at`` timestamp; the bounce-table on the page itself is
    sourced from ``bounced_addresses`` so admins see one row per
    address (with ``hit_count`` aggregating duplicates) regardless of
    how many notification log rows the address has bounced from.

    When ``org_id`` is non-None, the queries are scoped to that org
    plus the platform-wide rows (``org_id IS NULL``). When
    ``org_id is None`` (the ``global_admin`` path), every row is
    visible. Note that RLS additionally applies for non-superuser
    sessions; this function trusts the caller to have established the
    correct scope.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_

    from app.modules.notifications.models import (
        BouncedAddress,
        NotificationLog,
    )

    now = datetime.now(timezone.utc)
    windows = {
        "last_24h": now - timedelta(hours=24),
        "last_7d": now - timedelta(days=7),
        "last_30d": now - timedelta(days=30),
    }

    # ── 1. Aggregate stats: bounced notification_log rows per window ────
    stats: dict[str, dict] = {}
    for label, since in windows.items():
        # Total in the window.
        total_stmt = select(func.count(NotificationLog.id)).where(
            NotificationLog.bounced_at.is_not(None),
            NotificationLog.bounced_at >= since,
        )
        if org_id is not None:
            total_stmt = total_stmt.where(NotificationLog.org_id == org_id)
        total = (await db.execute(total_stmt)).scalar() or 0

        # Per-provider breakdown — exclude rows where provider_key is
        # NULL (legacy, pre-Phase-2 rows).
        per_provider_stmt = (
            select(
                NotificationLog.provider_key,
                func.count(NotificationLog.id),
            )
            .where(
                NotificationLog.bounced_at.is_not(None),
                NotificationLog.bounced_at >= since,
                NotificationLog.provider_key.is_not(None),
            )
            .group_by(NotificationLog.provider_key)
        )
        if org_id is not None:
            per_provider_stmt = per_provider_stmt.where(
                NotificationLog.org_id == org_id
            )
        rows = (await db.execute(per_provider_stmt)).all()
        by_provider = {pk: cnt for pk, cnt in rows if pk}

        stats[label] = {"total": int(total), "by_provider": by_provider}

    # ── 2. Recent bounces from bounced_addresses ────────────────────────
    base = select(BouncedAddress)
    if org_id is not None:
        base = base.where(
            or_(
                BouncedAddress.org_id == org_id,
                BouncedAddress.org_id.is_(None),
            )
        )
    count_total = (
        await db.execute(
            select(func.count(BouncedAddress.id)).select_from(base.subquery())
        )
    ).scalar() or 0

    rows_stmt = (
        base.order_by(BouncedAddress.last_seen_at.desc())
        .offset(max(0, offset))
        .limit(min(500, max(1, limit)))
    )
    bounce_rows = list((await db.execute(rows_stmt)).scalars().all())

    # ── 3. Decorate rows with linked customer/user IDs + provider_key ──
    recent: list[dict] = []
    if bounce_rows:
        addresses = {row.email_address.lower() for row in bounce_rows}
        # Customer lookup (org-scoped per row).
        from app.modules.auth.models import User
        from app.modules.customers.models import Customer

        cust_lookup: dict[tuple[uuid.UUID | None, str], uuid.UUID] = {}
        cust_stmt = select(Customer.id, Customer.org_id, Customer.email).where(
            func.lower(Customer.email).in_(addresses)
        )
        for cid, coid, cemail in (await db.execute(cust_stmt)).all():
            cust_lookup[(coid, (cemail or "").lower())] = cid

        user_lookup: dict[tuple[uuid.UUID | None, str], uuid.UUID] = {}
        user_stmt = select(User.id, User.org_id, User.email).where(
            func.lower(User.email).in_(addresses)
        )
        for uid, uoid, uemail in (await db.execute(user_stmt)).all():
            user_lookup[(uoid, (uemail or "").lower())] = uid

        # Latest provider_key per address (for the org or platform-wide).
        # Use a single query keyed on the per-address most-recent log row.
        provider_lookup: dict[tuple[uuid.UUID | None, str], str] = {}
        log_stmt = select(
            NotificationLog.org_id,
            NotificationLog.recipient,
            NotificationLog.provider_key,
            NotificationLog.bounced_at,
        ).where(
            NotificationLog.bounced_at.is_not(None),
            NotificationLog.provider_key.is_not(None),
            func.lower(NotificationLog.recipient).in_(addresses),
        )
        for loid, recip, pkey, bts in (await db.execute(log_stmt)).all():
            key = (loid, (recip or "").lower())
            existing = provider_lookup.get(key)
            if existing is None:
                provider_lookup[key] = pkey
            # Latest by bounced_at — but a stable arbitrary pick is
            # fine for the UI's "most recent provider that bounced".
            # We're not comparing timestamps here to keep the lookup
            # simple; the UI just needs A provider, not THE provider.

        for row in bounce_rows:
            lower_addr = row.email_address.lower()
            recent.append(
                {
                    "id": str(row.id),
                    "org_id": str(row.org_id) if row.org_id else None,
                    "email_address": row.email_address,
                    "bounce_kind": row.bounce_kind,
                    "reason": row.reason,
                    "first_seen_at": row.first_seen_at,
                    "last_seen_at": row.last_seen_at,
                    "hit_count": row.hit_count,
                    "expires_at": row.expires_at,
                    "linked_customer_id": (
                        str(cust_lookup[(row.org_id, lower_addr)])
                        if (row.org_id, lower_addr) in cust_lookup
                        else None
                    ),
                    "linked_user_id": (
                        str(user_lookup[(row.org_id, lower_addr)])
                        if (row.org_id, lower_addr) in user_lookup
                        else None
                    ),
                    "provider_key": (
                        provider_lookup.get((row.org_id, lower_addr))
                        or provider_lookup.get((None, lower_addr))
                    ),
                }
            )

    return {
        "stats": stats,
        "recent_bounces": recent,
        "total": int(count_total),
    }


async def clear_bounced_address(
    db: AsyncSession,
    *,
    bounce_id: uuid.UUID,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> bool:
    """Delete a single ``bounced_addresses`` row.

    Returns ``True`` when a row was actually deleted (the next send to
    that address will go through), ``False`` when no row matched
    (already cleared, or never existed). Writes an audit-log entry on
    success so admin actions stay traceable.
    """
    from app.modules.notifications.models import BouncedAddress

    fetch = await db.execute(
        select(BouncedAddress).where(BouncedAddress.id == bounce_id)
    )
    row = fetch.scalar_one_or_none()
    if row is None:
        return False

    snapshot = {
        "email_address": row.email_address,
        "bounce_kind": row.bounce_kind,
        "org_id": str(row.org_id) if row.org_id else None,
    }

    await db.delete(row)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=row.org_id,
        user_id=admin_user_id,
        action="admin.bounced_address_cleared",
        entity_type="bounced_address",
        entity_id=bounce_id,
        before_value=snapshot,
        after_value=None,
        ip_address=ip_address,
    )
    return True
