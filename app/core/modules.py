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
    "b2b-fleet-management": ["vehicles"],
    "timesheets": ["staff", "scheduling"],
}

# Modules with OR-style dependencies (at least one must be enabled)
OR_DEPENDENCIES: dict[str, list[str]] = {
    "tipping": ["pos", "invoicing"],
    "expenses": ["jobs", "projects"],
}

# Core modules that are always enabled and cannot be disabled.
CORE_MODULES: set[str] = {"invoicing", "customers", "notifications"}

# Modules restricted to specific trade families. The module is hidden from the
# module list and setup guide for orgs whose ``tradeFamily`` does not match,
# and the enable endpoint rejects mismatched orgs with HTTP 403.
#
# This pattern is used instead of a ``trade_family_required`` column on
# ``module_registry`` to stay consistent with the setup-guide spec
# (.kiro/specs/setup-guide/design.md — "trade_family_gated not stored in DB").
TRADE_FAMILY_REQUIRED_MODULES: dict[str, str] = {
    "b2b-fleet-management": "automotive-transport",
}

# Standard error message returned when an org tries to enable a module whose
# trade-family restriction is not satisfied. Kept module-specific so the user
# sees plain language rather than a generic slug.
TRADE_FAMILY_REJECTION_MESSAGES: dict[str, str] = {
    "b2b-fleet-management": (
        "B2B Fleet Management is available only for automotive and "
        "transport organisations"
    ),
}

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


def get_all_dependents(module_slug: str) -> list[str]:
    """Return the full transitive list of modules that depend on *module_slug*.

    Walks the DEPENDENCY_GRAPH in reverse: if module A lists B as a dependency,
    then B's dependents include A.
    """
    # Build reverse graph
    reverse: dict[str, list[str]] = {}
    for mod, deps in DEPENDENCY_GRAPH.items():
        for dep in deps:
            reverse.setdefault(dep, []).append(mod)

    visited: set[str] = set()
    stack = list(reverse.get(module_slug, []))
    while stack:
        dep = stack.pop()
        if dep not in visited:
            visited.add(dep)
            stack.extend(reverse.get(dep, []))
    return list(visited)


def is_trade_family_satisfied(module_slug: str, org_trade_family: str | None) -> bool:
    """Return True if a module's trade-family restriction is satisfied.

    Pure function — suitable for property-based testing.

    A module is "satisfied" when either:
    - It has no entry in ``TRADE_FAMILY_REQUIRED_MODULES`` (unrestricted), OR
    - The org's trade family slug matches the required family for that module.

    Args:
        module_slug: The module slug being checked.
        org_trade_family: The org's trade family slug (e.g. ``"automotive-transport"``)
            or ``None`` if unknown.

    Returns:
        ``True`` if the module is allowed for this org's trade family,
        ``False`` if the module is restricted to a different trade family.
    """
    required = TRADE_FAMILY_REQUIRED_MODULES.get(module_slug)
    if required is None:
        return True
    return org_trade_family == required


async def fetch_org_trade_family(db, org_id: str | UUID) -> str | None:
    """Resolve the organisation's trade family slug.

    Joins ``organisations.trade_category_id`` → ``trade_categories.family_id``
    → ``trade_families.slug``. Returns ``None`` if the org has no trade
    category set or the lookup fails.

    Used by the module list / enable endpoints and the setup guide router
    to apply ``TRADE_FAMILY_REQUIRED_MODULES`` gating.

    Args:
        db: An ``AsyncSession``.
        org_id: The organisation UUID (string or ``UUID``).

    Returns:
        The trade family slug (e.g. ``"automotive-transport"``) or ``None``.
    """
    from sqlalchemy import text

    try:
        result = await db.execute(
            text(
                "SELECT tf.slug "
                "FROM organisations o "
                "JOIN trade_categories tc ON tc.id = o.trade_category_id "
                "JOIN trade_families tf ON tf.id = tc.family_id "
                "WHERE o.id = :org_id"
            ),
            {"org_id": str(org_id)},
        )
        row = result.fetchone()
        if row is None:
            return None
        return row[0]
    except Exception:
        logger.warning("Failed to resolve trade family for org %s", org_id)
        return None


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
        """Actually disable a module and all its transitive dependents."""
        if module_slug in CORE_MODULES:
            return

        # Disable all transitive dependents first
        all_dependents = get_all_dependents(module_slug)
        for dep in all_dependents:
            if dep not in CORE_MODULES and await self.is_enabled(org_id, dep):
                await self._set_enabled(org_id, dep, False, None)

        # Disable the module itself
        await self._set_enabled(org_id, module_slug, False, None)
        await self._invalidate_cache(org_id)

        # Module-disable cascade for the B2B Fleet Portal:
        # tear down all active fleet portal sessions for this org so
        # subsequent requests get the disabled-module 403 (Req 1.7,
        # 17.6 — sessions invalidated within 60 s; doing it in this
        # transaction makes the bound a few hundred ms instead).
        if module_slug == "b2b-fleet-management":
            try:
                await self._cascade_fleet_portal_disable(org_id)
            except Exception as exc:  # noqa: BLE001 — defensive
                logger.warning(
                    "fleet_portal disable cascade failed: %s", exc, exc_info=True
                )

    async def _cascade_fleet_portal_disable(self, org_id: str) -> int:
        """Delete every fleet portal session for the org. Returns count."""
        from sqlalchemy import delete, select as _select

        from app.modules.fleet_portal.models import PortalAccount
        from app.modules.portal.models import PortalSession

        # Find all portal_accounts in this org that are fleet portal users.
        ids_q = _select(PortalAccount.id).where(
            PortalAccount.org_id == org_id,
            PortalAccount.portal_user_role.in_(("fleet_admin", "driver")),
        )
        ids = [row[0] for row in (await self._db.execute(ids_q)).all()]
        if not ids:
            return 0

        res = await self._db.execute(
            delete(PortalSession).where(PortalSession.portal_account_id.in_(ids))
        )
        deleted = int(res.rowcount or 0)
        logger.info(
            "fleet_portal.module_disabled_cascade org_id=%s sessions_deleted=%d",
            org_id,
            deleted,
        )
        return deleted

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
        """Return all modules with their enabled state and plan availability for an org."""
        from app.modules.module_management.models import ModuleRegistry, OrgModule
        from app.modules.admin.models import Organisation

        # Try cache first
        try:
            cached = await redis_pool.get(_all_modules_key(org_id))
            if cached is not None:
                return json.loads(cached)
        except Exception:
            logger.warning("Redis read failed for all-modules cache")

        # Get the org's plan enabled_modules
        plan_modules: set[str] = set()
        try:
            stmt_org = select(Organisation).where(Organisation.id == org_id)
            result_org = await self._db.execute(stmt_org)
            org = result_org.scalar_one_or_none()
            if org and org.plan_id:
                from app.modules.admin.models import SubscriptionPlan
                stmt_plan = select(SubscriptionPlan.enabled_modules).where(
                    SubscriptionPlan.id == org.plan_id
                )
                result_plan = await self._db.execute(stmt_plan)
                row = result_plan.scalar_one_or_none()
                if row:
                    plan_modules = set(row) if isinstance(row, list) else set()
        except Exception:
            logger.warning("Failed to fetch plan modules for org %s", org_id)

        # Query all registry modules with org enablement
        stmt = select(ModuleRegistry)
        result = await self._db.execute(stmt)
        registry_modules = result.scalars().all()

        stmt_om = select(OrgModule).where(
            and_(OrgModule.org_id == org_id, OrgModule.is_enabled == True)  # noqa: E712
        )
        result_om = await self._db.execute(stmt_om)
        enabled_slugs = {om.module_slug for om in result_om.scalars().all()}

        # "all" in plan_modules means everything is available
        all_available = "all" in plan_modules

        modules = []
        for mod in registry_modules:
            is_core = mod.is_core
            is_enabled = is_core or mod.slug in enabled_slugs
            in_plan = is_core or all_available or mod.slug in plan_modules
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
                "dependents": get_all_dependents(mod.slug),
                "status": mod.status,
                "is_enabled": is_enabled,
                "in_plan": in_plan,
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
