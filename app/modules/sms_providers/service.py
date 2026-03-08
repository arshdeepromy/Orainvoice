"""Business logic for SMS Verification Providers."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.admin.models import SmsVerificationProvider

logger = logging.getLogger(__name__)


async def list_sms_providers(db: AsyncSession) -> dict:
    """Return all SMS providers and the computed fallback chain."""
    result = await db.execute(
        select(SmsVerificationProvider).order_by(SmsVerificationProvider.priority)
    )
    providers = result.scalars().all()

    provider_list = []
    chain = []
    for p in providers:
        provider_list.append(_provider_to_dict(p))
        if p.is_active:
            chain.append({
                "provider_key": p.provider_key,
                "display_name": p.display_name,
                "priority": p.priority,
            })

    # Default provider goes first in chain, then remaining by priority
    chain.sort(key=lambda x: (0 if any(
        p.is_default and p.provider_key == x["provider_key"] for p in providers
    ) else 1, x["priority"]))

    return {"providers": provider_list, "fallback_chain": chain}


async def update_sms_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    is_active: bool | None = None,
    is_default: bool | None = None,
    priority: int | None = None,
    config: dict | None = None,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Update an SMS provider's settings."""
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == provider_key
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    before = _provider_to_dict(provider)

    if is_active is not None:
        provider.is_active = is_active
        # If deactivating the default, unset default
        if not is_active and provider.is_default:
            provider.is_default = False

    if is_default is not None and is_default:
        # Clear existing default first
        await db.execute(
            update(SmsVerificationProvider).values(is_default=False)
        )
        provider.is_default = True
        # Activating as default also activates the provider
        if not provider.is_active:
            provider.is_active = True

    if priority is not None:
        provider.priority = priority

    if config is not None:
        provider.config = config

    await db.flush()
    await db.refresh(provider)

    after = _provider_to_dict(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.sms_provider_updated",
        entity_type="sms_verification_provider",
        entity_id=provider.id,
        before_value=before,
        after_value=after,
        ip_address=ip_address,
    )

    return after


async def save_provider_credentials(
    db: AsyncSession,
    *,
    provider_key: str,
    credentials: dict,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Save encrypted credentials for a provider."""
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == provider_key
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    encrypted = envelope_encrypt(json.dumps(credentials))
    provider.credentials_encrypted = encrypted
    provider.credentials_set = True
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.sms_provider_credentials_saved",
        entity_type="sms_verification_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key, "credentials_set": True},
        ip_address=ip_address,
    )

    return {"credentials_set": True}


async def get_provider_credentials(
    db: AsyncSession, provider_key: str
) -> dict | None:
    """Decrypt and return credentials for a provider (internal use)."""
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == provider_key
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None or not provider.credentials_set or provider.credentials_encrypted is None:
        return None
    return json.loads(envelope_decrypt_str(provider.credentials_encrypted))


def _provider_to_dict(p: SmsVerificationProvider) -> dict:
    """Convert a provider ORM instance to a serialisable dict."""
    return {
        "id": str(p.id),
        "provider_key": p.provider_key,
        "display_name": p.display_name,
        "description": p.description,
        "icon": p.icon,
        "is_active": p.is_active,
        "is_default": p.is_default,
        "priority": p.priority,
        "credentials_set": p.credentials_set,
        "config": p.config or {},
        "setup_guide": p.setup_guide,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
