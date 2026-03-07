"""Zapier-compatible REST API service with API key authentication and rate limiting.

Provides CRUD for invoices, customers, products via API key auth.
Rate limiting is enforced at 100 requests/min per org (configurable per credential).

**Validates: Requirement — Ecommerce Module**
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ecommerce.models import ApiCredential
from app.modules.ecommerce.schemas import (
    ApiCredentialCreate,
    ApiCredentialCreatedResponse,
    ApiCredentialResponse,
)

# In-memory rate limit store (production would use Redis)
_rate_limit_store: dict[str, list[float]] = {}

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key for storage."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _check_rate_limit(org_id: str, limit: int) -> bool:
    """Return True if the request is within the rate limit window (1 min)."""
    now = time.time()
    window_start = now - 60.0
    key = f"api_rate:{org_id}"

    timestamps = _rate_limit_store.get(key, [])
    # Prune old entries
    timestamps = [t for t in timestamps if t > window_start]
    if len(timestamps) >= limit:
        _rate_limit_store[key] = timestamps
        return False
    timestamps.append(now)
    _rate_limit_store[key] = timestamps
    return True


class ApiKeyService:
    """Manages API credentials and authentication."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_credential(
        self,
        org_id: uuid.UUID,
        data: ApiCredentialCreate,
    ) -> tuple[ApiCredential, str]:
        """Create a new API credential. Returns (model, raw_api_key)."""
        raw_key = f"ora_{secrets.token_urlsafe(32)}"
        hashed = _hash_api_key(raw_key)

        cred = ApiCredential(
            org_id=org_id,
            api_key_hash=hashed,
            name=data.name,
            scopes=data.scopes,
            rate_limit_per_minute=data.rate_limit_per_minute,
        )
        self.db.add(cred)
        await self.db.flush()
        return cred, raw_key

    async def list_credentials(
        self,
        org_id: uuid.UUID,
    ) -> tuple[list[ApiCredential], int]:
        count_stmt = (
            select(func.count())
            .select_from(ApiCredential)
            .where(ApiCredential.org_id == org_id)
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(ApiCredential)
            .where(ApiCredential.org_id == org_id)
            .order_by(ApiCredential.created_at.desc())
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows), int(total)

    async def revoke_credential(
        self,
        org_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> bool:
        stmt = select(ApiCredential).where(
            ApiCredential.id == credential_id,
            ApiCredential.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        cred = result.scalar_one_or_none()
        if cred is None:
            return False
        cred.is_active = False
        await self.db.flush()
        return True

    async def authenticate(self, raw_key: str) -> ApiCredential | None:
        """Validate an API key and return the credential if valid."""
        hashed = _hash_api_key(raw_key)
        stmt = select(ApiCredential).where(
            ApiCredential.api_key_hash == hashed,
            ApiCredential.is_active.is_(True),
        )
        result = await self.db.execute(stmt)
        cred = result.scalar_one_or_none()
        if cred is None:
            return None

        # Check rate limit
        if not _check_rate_limit(str(cred.org_id), cred.rate_limit_per_minute):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
            )

        # Update last_used_at
        cred.last_used_at = datetime.now(timezone.utc)
        await self.db.flush()
        return cred


def reset_rate_limit_store() -> None:
    """Reset the in-memory rate limit store (for testing)."""
    _rate_limit_store.clear()
