"""Business logic for Email Providers."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import select
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
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Save encrypted credentials and optional config for a provider."""
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
