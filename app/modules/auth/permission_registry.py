"""Permission Registry — derives available permissions from module_registry.

Generates permission keys in the format ``{module_slug}.{action}`` for each
standard CRUD action, grouped by module. Custom role permissions are filtered
at evaluation time to exclude disabled modules.

**Validates: Requirements 4.1, 4.2, 4.4, 4.7**
"""

from __future__ import annotations

import json
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_pool
from app.modules.auth.security_settings_schemas import PermissionGroup, PermissionItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STANDARD_ACTIONS = ["create", "read", "update", "delete"]

_CACHE_KEY_PREFIX = "permissions:available"
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_key(org_id: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:{org_id}"


def _humanise(slug: str, action: str) -> str:
    """Build a human-readable label like 'Create Invoices'."""
    return f"{action.capitalize()} {slug.replace('_', ' ').title()}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_available_permissions(
    db: AsyncSession, org_id: UUID,
) -> list[PermissionGroup]:
    """Derive permissions from module_registry + org_modules for an org.

    Returns permission groups (one per enabled module), each containing
    ``{module_slug}.{action}`` keys for every standard action.

    Results are cached in Redis for ``_CACHE_TTL_SECONDS``.
    """
    org_id_str = str(org_id)

    # Try Redis cache first
    try:
        cached = await redis_pool.get(_cache_key(org_id_str))
        if cached is not None:
            data = json.loads(cached)
            return [PermissionGroup(**g) for g in data]
    except Exception:
        logger.warning("Redis read failed for permission cache, falling back to DB")

    # Query enabled modules for the org (core modules are always enabled)
    rows = await db.execute(
        text(
            """
            SELECT mr.slug, mr.display_name
            FROM module_registry mr
            WHERE mr.is_core = true
               OR mr.slug IN (
                   SELECT om.module_slug
                   FROM org_modules om
                   WHERE om.org_id = :org_id AND om.is_enabled = true
               )
            ORDER BY mr.display_name
            """
        ),
        {"org_id": org_id_str},
    )
    modules = rows.fetchall()

    groups: list[PermissionGroup] = []
    for row in modules:
        slug, display_name = row[0], row[1]
        permissions = [
            PermissionItem(
                key=f"{slug}.{action}",
                label=_humanise(slug, action),
            )
            for action in STANDARD_ACTIONS
        ]
        groups.append(PermissionGroup(
            module_slug=slug,
            module_name=display_name,
            permissions=permissions,
        ))

    # Cache the result
    try:
        serialized = [g.model_dump(mode="json") for g in groups]
        await redis_pool.setex(
            _cache_key(org_id_str),
            _CACHE_TTL_SECONDS,
            json.dumps(serialized),
        )
    except Exception:
        logger.warning("Redis write failed for permission cache")

    return groups


def evaluate_custom_role_permissions(
    role_permissions: list[str],
    disabled_modules: set[str],
) -> list[str]:
    """Filter out permissions belonging to disabled modules.

    Permission keys follow the ``{module_slug}.{action}`` format.
    Any permission whose module prefix is in *disabled_modules* is excluded
    from the returned list. The original *role_permissions* list is **not**
    mutated.

    **Validates: Requirements 4.4, 4.7**
    """
    return [
        perm for perm in role_permissions
        if perm.split(".")[0] not in disabled_modules
    ]
