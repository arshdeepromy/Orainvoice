"""Redis cache warming on application startup.

Pre-loads frequently accessed, rarely-changing data into Redis so that
the first requests after deployment don't hit the database.

Warmed data:
- Trade categories (all active)
- Module registry (all modules)
- Compliance profiles (all countries)
- Feature flags (all active)

Requirements: 43 (performance management)
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

# Cache key prefixes and TTLs (seconds)
TRADE_CATEGORIES_KEY = "cache:trade_categories:all"
MODULE_REGISTRY_KEY = "cache:module_registry:all"
COMPLIANCE_PROFILES_KEY = "cache:compliance_profiles:all"
FEATURE_FLAGS_KEY = "cache:feature_flags:all"

CACHE_TTL = 300  # 5 minutes


async def warm_trade_categories(session: AsyncSession) -> int:
    """Load all active trade categories into Redis."""
    result = await session.execute(
        text(
            "SELECT id, slug, display_name, family_id, "
            "recommended_modules, terminology_overrides "
            "FROM trade_categories WHERE is_active = true"
        )
    )
    rows = result.mappings().all()
    if not rows:
        return 0

    data = []
    for row in rows:
        data.append({
            "id": str(row["id"]),
            "slug": row["slug"],
            "display_name": row["display_name"],
            "family_id": str(row["family_id"]),
            "recommended_modules": row["recommended_modules"],
            "terminology_overrides": row["terminology_overrides"],
        })

    await redis_pool.set(TRADE_CATEGORIES_KEY, json.dumps(data), ex=CACHE_TTL)
    return len(data)


async def warm_module_registry(session: AsyncSession) -> int:
    """Load all module registry entries into Redis."""
    result = await session.execute(
        text(
            "SELECT id, slug, display_name, category, is_core, "
            "dependencies, status "
            "FROM module_registry"
        )
    )
    rows = result.mappings().all()
    if not rows:
        return 0

    data = []
    for row in rows:
        data.append({
            "id": str(row["id"]),
            "slug": row["slug"],
            "display_name": row["display_name"],
            "category": row["category"],
            "is_core": row["is_core"],
            "dependencies": row["dependencies"],
            "status": row["status"],
        })

    await redis_pool.set(MODULE_REGISTRY_KEY, json.dumps(data), ex=CACHE_TTL)
    return len(data)


async def warm_compliance_profiles(session: AsyncSession) -> int:
    """Load all compliance profiles into Redis."""
    result = await session.execute(
        text(
            "SELECT id, country_code, country_name, tax_label, "
            "default_tax_rates, currency_code, date_format "
            "FROM compliance_profiles"
        )
    )
    rows = result.mappings().all()
    if not rows:
        return 0

    data = []
    for row in rows:
        data.append({
            "id": str(row["id"]),
            "country_code": row["country_code"],
            "country_name": row["country_name"],
            "tax_label": row["tax_label"],
            "default_tax_rates": row["default_tax_rates"],
            "currency_code": row["currency_code"],
            "date_format": row["date_format"],
        })

    await redis_pool.set(COMPLIANCE_PROFILES_KEY, json.dumps(data), ex=CACHE_TTL)
    return len(data)


async def warm_feature_flags(session: AsyncSession) -> int:
    """Load all active feature flags into Redis."""
    result = await session.execute(
        text(
            "SELECT id, key, display_name, default_value, "
            "is_active, targeting_rules "
            "FROM feature_flags WHERE is_active = true"
        )
    )
    rows = result.mappings().all()
    if not rows:
        return 0

    data = []
    for row in rows:
        data.append({
            "id": str(row["id"]),
            "key": row["key"],
            "display_name": row["display_name"],
            "default_value": row["default_value"],
            "is_active": row["is_active"],
            "targeting_rules": row["targeting_rules"],
        })

    await redis_pool.set(FEATURE_FLAGS_KEY, json.dumps(data), ex=CACHE_TTL)
    return len(data)


async def warm_all_caches() -> dict[str, int]:
    """Run all cache warming tasks. Called on app startup.

    Returns a dict of {cache_name: record_count} for logging.
    """
    results: dict[str, int] = {}

    try:
        async with async_session_factory() as session:
            results["trade_categories"] = await warm_trade_categories(session)
            results["module_registry"] = await warm_module_registry(session)
            results["compliance_profiles"] = await warm_compliance_profiles(session)
            results["feature_flags"] = await warm_feature_flags(session)

        logger.info("Cache warming complete: %s", results)
    except Exception as exc:
        # Cache warming failure should not prevent app startup
        logger.warning("Cache warming failed (non-fatal): %s", exc)
        results["error"] = str(exc)  # type: ignore[assignment]

    return results
