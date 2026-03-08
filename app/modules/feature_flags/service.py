"""Feature flag CRUD service with Redis caching.

Handles database persistence, Redis caching (60s TTL), cache invalidation
on flag toggle, and fallback to default_value on Redis/DB errors.

**Validates: Requirement 2**
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.feature_flags import OrgContext, evaluate_flag, evaluate_flags_bulk
from app.core.redis import redis_pool
from app.modules.feature_flags.models import FeatureFlag
from app.modules.feature_flags.schemas import (
    FeatureFlagCreate,
    FeatureFlagResponse,
    FeatureFlagUpdate,
    OrgFlagEvaluation,
    TargetingRule,
)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
CACHE_KEY_PREFIX = "flag:"


class FeatureFlagCRUDService:
    """Service layer for feature flag CRUD and evaluation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_flags(self) -> tuple[list[FeatureFlagResponse], int]:
        """Return all feature flags."""
        result = await self.db.execute(
            select(FeatureFlag).order_by(FeatureFlag.created_at.desc())
        )
        flags = result.scalars().all()
        responses = [self._to_response(f) for f in flags]
        return responses, len(responses)

    async def create_flag(
        self,
        payload: FeatureFlagCreate,
        *,
        created_by: str | None = None,
        ip_address: str | None = None,
    ) -> FeatureFlagResponse:
        """Create a new feature flag."""
        # Check uniqueness
        existing = await self.db.execute(
            select(FeatureFlag).where(FeatureFlag.key == payload.key)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Feature flag with key '{payload.key}' already exists")

        flag = FeatureFlag(
            key=payload.key,
            display_name=payload.display_name,
            description=payload.description,
            category=payload.category,
            access_level=payload.access_level,
            dependencies=payload.dependencies,
            default_value=payload.default_value,
            is_active=payload.is_active,
            targeting_rules=[r.model_dump() for r in payload.targeting_rules],
            created_by=uuid.UUID(created_by) if created_by else None,
        )
        self.db.add(flag)
        await self.db.flush()

        await write_audit_log(
            self.db,
            action="feature_flag.created",
            entity_type="feature_flag",
            entity_id=flag.id,
            user_id=created_by,
            after_value={"key": flag.key, "is_active": flag.is_active, "default_value": flag.default_value},
            ip_address=ip_address,
        )

        return self._to_response(flag)

    async def update_flag(
        self,
        key: str,
        payload: FeatureFlagUpdate,
        *,
        updated_by: str | None = None,
        ip_address: str | None = None,
    ) -> FeatureFlagResponse:
        """Update an existing feature flag and invalidate cache."""
        result = await self.db.execute(
            select(FeatureFlag).where(FeatureFlag.key == key)
        )
        flag = result.scalar_one_or_none()
        if not flag:
            raise ValueError(f"Feature flag '{key}' not found")

        before = {"is_active": flag.is_active, "default_value": flag.default_value}

        updates = payload.model_dump(exclude_none=True)
        if "targeting_rules" in updates and updates["targeting_rules"] is not None:
            updates["targeting_rules"] = [
                r.model_dump() if isinstance(r, TargetingRule) else r
                for r in updates["targeting_rules"]
            ]

        for attr, value in updates.items():
            setattr(flag, attr, value)

        if updated_by:
            flag.updated_by = uuid.UUID(updated_by)

        await self.db.flush()

        # Invalidate Redis cache for this flag
        await self._invalidate_cache(key)

        await write_audit_log(
            self.db,
            action="feature_flag.updated",
            entity_type="feature_flag",
            entity_id=flag.id,
            user_id=updated_by,
            before_value=before,
            after_value={"is_active": flag.is_active, "default_value": flag.default_value},
            ip_address=ip_address,
        )

        return self._to_response(flag)

    async def archive_flag(
        self,
        key: str,
        *,
        archived_by: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Archive a feature flag (set is_active=False) and invalidate cache."""
        result = await self.db.execute(
            select(FeatureFlag).where(FeatureFlag.key == key)
        )
        flag = result.scalar_one_or_none()
        if not flag:
            raise ValueError(f"Feature flag '{key}' not found")

        before_active = flag.is_active
        flag.is_active = False
        await self.db.flush()

        await self._invalidate_cache(key)

        await write_audit_log(
            self.db,
            action="feature_flag.archived",
            entity_type="feature_flag",
            entity_id=flag.id,
            user_id=archived_by,
            before_value={"is_active": before_active},
            after_value={"is_active": False},
            ip_address=ip_address,
        )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    async def evaluate_single(self, flag_key: str, org_context: OrgContext) -> bool:
        """Evaluate a single flag with Redis caching and fallback."""
        cache_key = f"{CACHE_KEY_PREFIX}{flag_key}:{org_context.org_id}"

        # 1. Try Redis cache
        try:
            cached = await redis_pool.get(cache_key)
            if cached is not None:
                return cached == "1"
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Redis read failed for flag %s, falling back to DB: %s", flag_key, exc)

        # 2. Load from DB
        try:
            result = await self.db.execute(
                select(FeatureFlag).where(FeatureFlag.key == flag_key)
            )
            flag = result.scalar_one_or_none()
        except (ConnectionError, OSError) as exc:
            logger.warning("DB read failed for flag %s, returning False: %s", flag_key, exc)
            return False

        if not flag:
            return False

        # 3. Evaluate
        value = evaluate_flag(
            is_active=flag.is_active,
            default_value=flag.default_value,
            targeting_rules=flag.targeting_rules or [],
            org_context=org_context,
        )

        # 4. Cache result
        try:
            await redis_pool.setex(cache_key, CACHE_TTL_SECONDS, "1" if value else "0")
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Redis write failed for flag %s: %s", flag_key, exc)

        return value

    async def evaluate_all_for_org(self, org_id: str) -> list[OrgFlagEvaluation]:
        """Evaluate all active flags for an org, building context from DB.

        Uses ``evaluate_flags_bulk`` from the core evaluation engine to ensure
        consistency with the middleware, which also delegates to ``evaluate_flag``.
        """
        # Build org context — fetch org details
        org_context = await self._build_org_context(org_id)

        try:
            result = await self.db.execute(
                select(FeatureFlag).where(FeatureFlag.is_active == True)  # noqa: E712
            )
            flags = result.scalars().all()
        except (ConnectionError, OSError) as exc:
            logger.warning("DB read failed when listing flags for org %s: %s", org_id, exc)
            return []

        # Convert ORM objects to dicts for the pure bulk evaluation function
        flag_dicts = [
            {
                "key": flag.key,
                "is_active": flag.is_active,
                "default_value": flag.default_value,
                "targeting_rules": flag.targeting_rules or [],
            }
            for flag in flags
        ]

        bulk_results = evaluate_flags_bulk(flags=flag_dicts, org_context=org_context)

        return [
            OrgFlagEvaluation(key=key, enabled=value)
            for key, value in bulk_results.items()
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _build_org_context(self, org_id: str) -> OrgContext:
        """Build an OrgContext from the organisations table."""
        from sqlalchemy import text

        try:
            result = await self.db.execute(
                text(
                    "SELECT trade_category_id, country_code "
                    "FROM organisations WHERE id = :org_id"
                ),
                {"org_id": org_id},
            )
            row = result.first()
        except (ConnectionError, OSError) as exc:
            logger.warning("Failed to build org context for %s: %s", org_id, exc)
            return OrgContext(org_id=org_id)

        if not row:
            return OrgContext(org_id=org_id)

        # Resolve trade category and family slugs if available
        trade_cat_slug = None
        trade_fam_slug = None
        if row.trade_category_id:
            try:
                cat_result = await self.db.execute(
                    text(
                        "SELECT tc.slug AS cat_slug, tf.slug AS fam_slug "
                        "FROM trade_categories tc "
                        "JOIN trade_families tf ON tc.family_id = tf.id "
                        "WHERE tc.id = :cat_id"
                    ),
                    {"cat_id": str(row.trade_category_id)},
                )
                cat_row = cat_result.first()
                if cat_row:
                    trade_cat_slug = cat_row.cat_slug
                    trade_fam_slug = cat_row.fam_slug
            except (ConnectionError, OSError) as exc:
                logger.warning("Failed to resolve trade category for org %s: %s", org_id, exc)

        return OrgContext(
            org_id=org_id,
            trade_category_slug=trade_cat_slug,
            trade_family_slug=trade_fam_slug,
            country_code=row.country_code if hasattr(row, "country_code") else None,
        )

    async def _invalidate_cache(self, flag_key: str) -> None:
        """Delete all cached evaluations for a flag and all middleware per-org caches.

        Invalidates two cache layers:
        1. Per-flag evaluation cache: ``flag:{flag_key}:*`` keys
        2. Middleware per-org cache: ``ff:*`` keys (ensures propagation within 5s)
        """
        try:
            # 1. Invalidate per-flag evaluation cache (flag:{key}:*)
            pattern = f"{CACHE_KEY_PREFIX}{flag_key}:*"
            cursor = 0
            while True:
                cursor, keys = await redis_pool.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis_pool.delete(*keys)
                if cursor == 0:
                    break
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Redis cache invalidation failed for flag %s: %s", flag_key, exc)

        try:
            # 2. Invalidate middleware per-org cache (ff:*)
            from app.middleware.feature_flags import _CACHE_KEY_PREFIX as MW_CACHE_PREFIX

            mw_pattern = f"{MW_CACHE_PREFIX}*"
            cursor = 0
            while True:
                cursor, keys = await redis_pool.scan(cursor, match=mw_pattern, count=100)
                if keys:
                    await redis_pool.delete(*keys)
                if cursor == 0:
                    break
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Redis middleware cache invalidation failed for flag %s: %s", flag_key, exc)


    @staticmethod
    def _to_response(flag: FeatureFlag) -> FeatureFlagResponse:
        """Convert a SQLAlchemy model to a Pydantic response."""
        rules = flag.targeting_rules or []
        return FeatureFlagResponse(
            id=flag.id,
            key=flag.key,
            display_name=flag.display_name,
            description=flag.description,
            category=flag.category,
            access_level=flag.access_level,
            dependencies=flag.dependencies or [],
            default_value=flag.default_value,
            is_active=flag.is_active,
            targeting_rules=[TargetingRule(**r) for r in rules],
            created_by=flag.created_by,
            updated_by=flag.updated_by,
            created_at=flag.created_at,
            updated_at=flag.updated_at,
        )
