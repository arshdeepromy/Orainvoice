"""Service layer for platform-level settings (encrypted key-value store).

Provides get/set/masked helpers for global credentials like Xero API keys.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str, envelope_encrypt
from app.modules.platform_settings.models import PlatformSetting


async def get_setting(db: AsyncSession, key: str) -> str | None:
    """Read a platform setting, decrypt, and return plaintext. None if not set."""
    stmt = select(PlatformSetting).where(PlatformSetting.key == key)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None or row.value_encrypted is None:
        return None
    return envelope_decrypt_str(row.value_encrypted)


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """Upsert a platform setting with envelope encryption."""
    stmt = select(PlatformSetting).where(PlatformSetting.key == key)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()

    encrypted = envelope_encrypt(value)

    if row is None:
        row = PlatformSetting(key=key, value_encrypted=encrypted, value={})
        db.add(row)
    else:
        row.value_encrypted = encrypted

    await db.flush()


async def get_masked(db: AsyncSession, key: str) -> str | None:
    """Return last 4 chars of a setting masked, e.g. '••••••••abcd'. None if not set."""
    plaintext = await get_setting(db, key)
    if plaintext is None:
        return None
    if len(plaintext) <= 4:
        return "••••••••" + plaintext
    return "••••••••" + plaintext[-4:]
