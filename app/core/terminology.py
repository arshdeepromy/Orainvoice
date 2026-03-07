"""Terminology resolution service.

Resolves trade-specific labels for an organisation by merging three layers:
    DEFAULT_TERMS → trade category overrides → org-level overrides

The org-level overrides have the highest priority, allowing individual
organisations to customise any label beyond what their trade category defines.

**Validates: Requirement 4**
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 120
CACHE_KEY_PREFIX = "terminology:"

# ---------------------------------------------------------------------------
# Default terminology map — generic labels used when no override exists.
# ---------------------------------------------------------------------------

DEFAULT_TERMS: dict[str, str] = {
    "asset_label": "Asset",
    "work_unit_label": "Job",
    "customer_label": "Customer",
    "line_item_service": "Service",
    "line_item_product": "Product",
    "line_item_labour": "Labour",
}


class TerminologyService:
    """Resolves the merged terminology map for an organisation.

    Merge priority (last wins):
        1. ``DEFAULT_TERMS`` — generic fallback labels
        2. Trade category ``terminology_overrides`` JSON column
        3. ``org_terminology_overrides`` table rows (org-level)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_terminology_map(self, org_id: str) -> dict[str, str]:
        """Return the fully-merged terminology map for *org_id*.

        Results are cached in Redis for ``CACHE_TTL_SECONDS``.
        """
        cache_key = f"{CACHE_KEY_PREFIX}{org_id}"

        # 1. Try Redis cache
        try:
            import json as _json

            cached = await redis_pool.get(cache_key)
            if cached is not None:
                return _json.loads(cached)
        except Exception:
            logger.warning("Redis read failed for terminology org=%s", org_id)

        # 2. Build from DB
        terms = dict(DEFAULT_TERMS)

        # 2a. Apply trade category overrides
        try:
            row = await self.db.execute(
                text(
                    "SELECT tc.terminology_overrides "
                    "FROM organisations o "
                    "JOIN trade_categories tc ON o.trade_category_id = tc.id "
                    "WHERE o.id = :org_id"
                ),
                {"org_id": org_id},
            )
            cat_row = row.first()
            if cat_row and cat_row.terminology_overrides:
                overrides = cat_row.terminology_overrides
                if isinstance(overrides, str):
                    import json as _json
                    overrides = _json.loads(overrides)
                terms.update(overrides)
        except Exception:
            logger.warning("Failed to load trade category overrides for org=%s", org_id)

        # 2b. Apply org-level overrides (highest priority)
        try:
            result = await self.db.execute(
                text(
                    "SELECT generic_key, custom_label "
                    "FROM org_terminology_overrides "
                    "WHERE org_id = :org_id"
                ),
                {"org_id": org_id},
            )
            for override_row in result.fetchall():
                terms[override_row.generic_key] = override_row.custom_label
        except Exception:
            logger.warning("Failed to load org terminology overrides for org=%s", org_id)

        # 3. Cache result
        try:
            import json as _json

            await redis_pool.setex(cache_key, CACHE_TTL_SECONDS, _json.dumps(terms))
        except Exception:
            logger.warning("Redis write failed for terminology org=%s", org_id)

        return terms

    async def set_org_overrides(
        self, org_id: str, overrides: dict[str, str]
    ) -> dict[str, str]:
        """Upsert org-level terminology overrides and return the new merged map.

        Parameters
        ----------
        org_id:
            The organisation UUID.
        overrides:
            Mapping of ``generic_key`` → ``custom_label`` to set.
        """
        for key, label in overrides.items():
            await self.db.execute(
                text(
                    "INSERT INTO org_terminology_overrides (id, org_id, generic_key, custom_label) "
                    "VALUES (gen_random_uuid(), :org_id, :key, :label) "
                    "ON CONFLICT (org_id, generic_key) "
                    "DO UPDATE SET custom_label = EXCLUDED.custom_label"
                ),
                {"org_id": org_id, "key": key, "label": label},
            )

        # Invalidate cache
        await self._invalidate_cache(org_id)

        # Return fresh merged map
        return await self.get_terminology_map(org_id)

    async def _invalidate_cache(self, org_id: str) -> None:
        """Remove cached terminology for an org."""
        try:
            await redis_pool.delete(f"{CACHE_KEY_PREFIX}{org_id}")
        except Exception:
            logger.warning("Redis cache invalidation failed for terminology org=%s", org_id)
