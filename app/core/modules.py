"""Module selection and dependency service.

Manages per-organisation module enablement with dependency resolution and
Redis caching. Core modules (invoicing, customers, notifications) are always
considered enabled and cannot be disabled.

**Validates: Requirement 6**
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependency graph — maps module slug → list of required dependency slugs.
# Requirement 6.5
# ---------------------------------------------------------------------------

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "pos": ["inventory"],
    "kitchen_display": ["tables", "pos"],
    "tipping": [],  # requires pos OR invoicing (handled specially)
    "progress_claims": ["projects"],
    "retentions": ["progress_claims"],
    "variations": ["progress_claims"],
    "expenses": ["jobs"],  # requires jobs (OR projects, handled specially)
    "purchase_orders": ["inventory"],
    "staff": ["scheduling"],
    "ecommerce": ["inventory"],
}

# Modules with OR-style dependencies (at least one must be enabled)
OR_DEPENDENCIES: dict[str, list[str]] = {
    "tipping": ["pos", "invoicing"],
    "expenses": ["jobs", "projects"],
}

# Core modules that are always enabled and cannot be disabled.
CORE_MODULES: set[str] = {"invoicing", "customers", "notifications"}

# Redis cache key pattern and TTL
_CACHE_KEY_PREFIX = "module:enabled"
_CACHE_TTL_SECONDS = 60


def _cache_key(org_id: str, module_slug: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:{org_id}:{module_slug}"


def _all_modules_key(org_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:{org_id}:__all__"


def get_all_dependencies(module_slug: str) -> list[str]:
    """Return the full transitive dependency list for a module.

    Resolves the standard DEPENDENCY_GRAPH (AND-style deps). OR-style
    dependencies are not auto-enabled — they are checked separately.
    """
    visited: set[str] = set()
    stack = list(DEPENDENCY_GRAPH.get(module_slug, []))
    while stack:
        dep = stack.pop()
        if dep not in visited:
            visited.add(dep)
            stack.extend(DEPENDENCY_GRAPH.get(dep, []))
    return list(visited)


class ModuleService:
    """Manages module enablement per organisation with Redis caching."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enable_module(self, org_id: str, module_slug: str, enabled_by: str | None = None) -> list[str]:
        """Enable a module for an org, auto-enabling AND-style dependencies.

        Returns the list of additionally enabled dependency module slugs.
        """
        additionally_enabled: list[str] = []

        # Resolve transitive AND-dependencies
        deps = get_all_dependencies(module_slug)
        for dep in deps:
            if not await self.is_enabled(org_id, dep):
                await self._set_enabled(org_id, dep, True, enabled_by)
                additionally_enabled.append(dep)

        # Enable the module itself
        if not await self.is_enabled(org_id, module_slug):
            await self._set_enabled(org_id, module_slug, True, enabled_by)

        # Invalidate cache
        await self._invalidate_cache(org_id)

        return additionally_enabled

    async def disable_module(self, org_id: str, module_slug: str) -> list[str]:
        """Check which enabled modules depend on *module_slug*.

        Returns the list of dependent module slugs that are currently enabled.
        Does NOT actually disable anything — the caller should confirm with
        the user first.
        """
        if module_slug in CORE_MODULES:
            return []  # Core modules cannot be disabled

        dependents: list[str] = []
        for mod, deps in DEPENDENCY_GRAPH.items():
            if module_slug in deps and await self.is_enabled(org_id, mod):
                dependents.append(mod)

        # Also check OR-dependencies: if this module is the ONLY satisfied
        # OR-dep for another module, that module is a dependent.
        for mod, or_deps in OR_DEPENDENCIES.items():
            if module_slug in or_deps and await self.is_enabled(org_id, mod):
                # Check if any other OR-dep is still enabled
                other_enabled = False
                for other in or_deps:
                    if other != module_slug and await self.is_enabled(org_id, other):
                        other_enabled = True
                        break
                if not other_enabled and mod not in dependents:
                    dependents.append(mod)

        return dependents

    async def force_disable_module(self, org_id: str, module_slug: str) -> None:
        """Actually disable a module (after user confirmation)."""
        if module_slug in CORE_MODULES:
            return
        await self._set_enabled(org_id, module_slug, False, None)
        await self._invalidate_cache(org_id)

    async def is_enabled(self, org_id: str, module_slug: str) -> bool:
        """Check if a module is enabled for an org. Uses Redis cache."""
        if module_slug in CORE_MODULES:
            return True

        # Try Redis cache first
        try:
            cached = await redis_pool.get(_cache_key(org_id, module_slug))
            if cached is not None:
                return cached == "1"
        except Exception:
            logger.warning("Redis read failed for module check, falling back to DB")

        # Fall back to DB
        enabled = await self._check_db(org_id, module_slug)

        # Cache the result
        try:
            await redis_pool.setex(
                _cache_key(org_id, module_slug),
                _CACHE_TTL_SECONDS,
                "1" if enabled else "0",
            )
        except Exception:
            logger.warning("Redis write failed for module cache")

        return enabled

    async def get_all_modules_for_org(self, org_id: str) -> list[dict]:
        """Return all modules with their enabled state for an org."""
        from app.modules.module_management.models import ModuleRegistry, OrgModule

        # Try cache first
        try:
            cached = await redis_pool.get(_all_modules_key(org_id))
            if cached is not None:
                return json.loads(cached)
        except Exception:
            logger.warning("Redis read failed for all-modules cache")

        # Query all registry modules with org enablement
        stmt = select(ModuleRegistry)
        result = await self._db.execute(stmt)
        registry_modules = result.scalars().all()

        stmt_org = select(OrgModule).where(
            and_(OrgModule.org_id == org_id, OrgModule.is_enabled == True)  # noqa: E712
        )
        result_org = await self._db.execute(stmt_org)
        enabled_slugs = {om.module_slug for om in result_org.scalars().all()}

        modules = []
        for mod in registry_modules:
            is_core = mod.is_core
            is_enabled = is_core or mod.slug in enabled_slugs
            deps = mod.dependencies or []
            if isinstance(deps, str):
                try:
                    deps = json.loads(deps)
                except (ValueError, TypeError):
                    deps = []
            modules.append({
                "slug": mod.slug,
                "display_name": mod.display_name,
                "description": mod.description,
                "category": mod.category,
                "is_core": is_core,
                "dependencies": deps if isinstance(deps, list) else [],
                "status": mod.status,
                "is_enabled": is_enabled,
            })

        # Cache
        try:
            await redis_pool.setex(
                _all_modules_key(org_id),
                _CACHE_TTL_SECONDS,
                json.dumps(modules),
            )
        except Exception:
            logger.warning("Redis write failed for all-modules cache")

        return modules

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _check_db(self, org_id: str, module_slug: str) -> bool:
        """Check the DB for module enablement."""
        from app.modules.module_management.models import OrgModule

        stmt = select(OrgModule).where(
            and_(
                OrgModule.org_id == org_id,
                OrgModule.module_slug == module_slug,
                OrgModule.is_enabled == True,  # noqa: E712
            )
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _set_enabled(
        self, org_id: str, module_slug: str, enabled: bool, enabled_by: str | None
    ) -> None:
        """Insert or update the org_modules row."""
        from app.modules.module_management.models import OrgModule

        stmt = select(OrgModule).where(
            and_(
                OrgModule.org_id == org_id,
                OrgModule.module_slug == module_slug,
            )
        )
        result = await self._db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.is_enabled = enabled
            if enabled and enabled_by:
                existing.enabled_by = enabled_by
        else:
            new_record = OrgModule(
                org_id=org_id,
                module_slug=module_slug,
                is_enabled=enabled,
                enabled_by=enabled_by,
            )
            self._db.add(new_record)

        await self._db.flush()

    async def _invalidate_cache(self, org_id: str) -> None:
        """Invalidate all module cache entries for an org."""
        try:
            # Delete the all-modules cache
            await redis_pool.delete(_all_modules_key(org_id))
            # Delete individual module keys via pattern scan
            pattern = f"{_CACHE_KEY_PREFIX}:{org_id}:*"
            cursor = 0
            while True:
                cursor, keys = await redis_pool.scan(cursor, match=pattern, count=100)
                if keys:
                    await redis_pool.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            logger.warning("Redis cache invalidation failed for org %s", org_id)
