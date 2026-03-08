"""Business logic for Email Providers."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.admin.models import EmailProvider

logger = logging.getLogger(__name__)


async def list_email_providers(db: AsyncSession) -> dict:
    """Return all email providers and identify the active one."""
    result = await db.execute(
        select(EmailProvider).order_by(EmailProvider.display_name)
    )
    providers = result.scalars().all()
    active_key = None
    provider_list = []
    for p in providers:
        provider_list.append(_provider_to_dict(p))
        if p.is_active:
            active_key = p.provider_key
    return {"providers": provider_list, "active_provider": active_key}


async def activate_email_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Set a provider as the active email provider (only one at a time)."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    # Deactivate all others
    await db.execute(update(EmailProvider).values(is_active=False))
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
    """Deactivate a provider."""
    result = await db.execute(
        select(EmailProvider).where(EmailProvider.provider_key == provider_key)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    provider.is_active = False
    await db.flush()
    await db.refresh(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.email_provider_deactivated",
        entity_type="email_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key},
        ip_address=ip_address,
    )
    return _provider_to_dict(provider)


async def save_email_credentials(
    db: AsyncSession,
    *,
    provider_key: str,
    credentials: dict,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
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
        "is_active": p.is_active,
        "credentials_set": p.credentials_set,
        "config": p.config or {},
        "setup_guide": p.setup_guide,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
