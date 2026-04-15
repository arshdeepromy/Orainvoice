"""Custom Roles Service — CRUD for org-level custom roles.

Manages built-in role listing alongside custom roles, with audit logging
for all mutations.

**Validates: Requirements 4.3, 4.5, 4.8, 4.9, 4.10**
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUILT_IN_ROLE_SLUGS = frozenset({
    "global_admin",
    "org_admin",
    "branch_admin",
    "location_manager",
    "salesperson",
    "staff_member",
    "kiosk",
    "franchise_admin",
})

BUILT_IN_ROLE_NAMES: dict[str, str] = {
    "global_admin": "Global Admin",
    "org_admin": "Organisation Admin",
    "branch_admin": "Branch Admin",
    "location_manager": "Location Manager",
    "salesperson": "Salesperson",
    "staff_member": "Staff Member",
    "kiosk": "Kiosk",
    "franchise_admin": "Franchise Admin",
}

# Roles that require specific modules to be enabled.
# Roles not listed here are always available (e.g. org_admin, salesperson, staff_member).
ROLE_REQUIRED_MODULES: dict[str, str] = {
    "branch_admin": "branch_management",
    "location_manager": "branch_management",
    "franchise_admin": "franchise",
    "kiosk": "pos",
}


def _slugify(name: str) -> str:
    """Convert a role name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def list_roles(db: AsyncSession, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """List built-in roles + custom roles for an org, with user counts.

    Filters out built-in roles whose required module is not enabled
    for the org (e.g. branch_admin hidden when branch_management is off).
    Global_admin is always excluded from org-level listings.

    Returns a list of dicts matching the RoleResponse schema shape.
    """
    from app.core.modules import ModuleService

    org_id_str = str(org_id)

    # Determine which modules are enabled for this org
    svc = ModuleService(db)
    all_modules = await svc.get_all_modules_for_org(org_id_str)
    enabled_slugs = {m["slug"] for m in (all_modules or []) if m.get("is_enabled")}

    # Built-in roles with user counts
    built_in_rows = await db.execute(
        text(
            """
            SELECT u.role, COUNT(*) AS cnt
            FROM users u
            WHERE u.org_id = :org_id
              AND u.role IS NOT NULL
              AND u.custom_role_id IS NULL
            GROUP BY u.role
            """
        ),
        {"org_id": org_id_str},
    )
    user_counts_by_role: dict[str, int] = {}
    for row in built_in_rows.fetchall():
        user_counts_by_role[row[0]] = row[1]

    from app.modules.auth.rbac import ROLE_PERMISSIONS

    roles: list[dict[str, Any]] = []
    for slug in sorted(BUILT_IN_ROLE_SLUGS):
        # Always exclude global_admin from org-level role listings
        if slug == "global_admin":
            continue
        # Filter out roles whose required module is not enabled
        required_module = ROLE_REQUIRED_MODULES.get(slug)
        if required_module and required_module not in enabled_slugs:
            continue
        roles.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"builtin.{slug}")),
            "org_id": org_id_str,
            "name": BUILT_IN_ROLE_NAMES.get(slug, slug),
            "slug": slug,
            "description": None,
            "permissions": ROLE_PERMISSIONS.get(slug, []),
            "is_system": True,
            "user_count": user_counts_by_role.get(slug, 0),
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
        })

    # Custom roles with user counts
    custom_rows = await db.execute(
        text(
            """
            SELECT cr.id, cr.org_id, cr.name, cr.slug, cr.description,
                   cr.permissions, cr.is_system, cr.created_at,
                   COUNT(u.id) AS user_count
            FROM custom_roles cr
            LEFT JOIN users u ON u.custom_role_id = cr.id
            WHERE cr.org_id = :org_id
            GROUP BY cr.id
            ORDER BY cr.name
            """
        ),
        {"org_id": org_id_str},
    )
    for row in custom_rows.fetchall():
        perms = row[5] if isinstance(row[5], list) else []
        roles.append({
            "id": str(row[0]),
            "org_id": str(row[1]),
            "name": row[2],
            "slug": row[3],
            "description": row[4],
            "permissions": perms,
            "is_system": row[6],
            "user_count": row[8],
            "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
        })

    return roles


async def create_custom_role(
    db: AsyncSession,
    org_id: uuid.UUID,
    name: str,
    permissions: list[str],
    description: str | None = None,
    created_by: uuid.UUID | None = None,
    ip_address: str | None = None,
    device_info: str | None = None,
) -> dict[str, Any]:
    """Create a new custom role for an org.

    Returns the created role as a dict.
    """
    import json

    role_id = uuid.uuid4()
    slug = _slugify(name)
    now = datetime.now(timezone.utc)

    await db.execute(
        text(
            """
            INSERT INTO custom_roles (id, org_id, name, slug, description,
                                      permissions, is_system, created_by,
                                      created_at, updated_at)
            VALUES (:id, :org_id, :name, :slug, :description,
                    :permissions, false, :created_by, :created_at, :updated_at)
            """
        ),
        {
            "id": str(role_id),
            "org_id": str(org_id),
            "name": name,
            "slug": slug,
            "description": description,
            "permissions": json.dumps(permissions),
            "created_by": str(created_by) if created_by else None,
            "created_at": now,
            "updated_at": now,
        },
    )
    await db.flush()

    # Write audit log
    await write_audit_log(
        db,
        action="org.custom_role_created",
        entity_type="custom_role",
        org_id=org_id,
        user_id=created_by,
        entity_id=role_id,
        after_value={"name": name, "slug": slug, "permissions": permissions},
        ip_address=ip_address,
        device_info=device_info,
    )

    return {
        "id": str(role_id),
        "org_id": str(org_id),
        "name": name,
        "slug": slug,
        "description": description,
        "permissions": permissions,
        "is_system": False,
        "user_count": 0,
        "created_at": now.isoformat(),
    }


async def update_custom_role(
    db: AsyncSession,
    role_id: uuid.UUID,
    name: str | None = None,
    permissions: list[str] | None = None,
    description: str | None = None,
    updated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
    device_info: str | None = None,
) -> dict[str, Any]:
    """Update an existing custom role.

    Returns the updated role as a dict. Raises ValueError if role not found
    or is a system role.
    """
    import json

    # Fetch existing role
    result = await db.execute(
        text("SELECT * FROM custom_roles WHERE id = :id"),
        {"id": str(role_id)},
    )
    row = result.fetchone()
    if row is None:
        raise ValueError("Custom role not found")

    # Map columns
    col_names = result.keys()
    existing = dict(zip(col_names, row))

    if existing["is_system"]:
        raise ValueError("Cannot modify built-in role")

    before_value: dict[str, Any] = {
        "name": existing["name"],
        "permissions": existing["permissions"],
        "description": existing["description"],
    }

    # Build SET clause dynamically
    updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if name is not None:
        updates["name"] = name
        updates["slug"] = _slugify(name)
    if permissions is not None:
        updates["permissions"] = json.dumps(permissions)
    if description is not None:
        updates["description"] = description

    set_parts = ", ".join(f"{k} = :{k}" for k in updates)
    params = {**updates, "id": str(role_id)}

    await db.execute(
        text(f"UPDATE custom_roles SET {set_parts} WHERE id = :id"),
        params,
    )
    await db.flush()

    # Re-fetch for return
    result2 = await db.execute(
        text("SELECT * FROM custom_roles WHERE id = :id"),
        {"id": str(role_id)},
    )
    updated_row = result2.fetchone()
    updated = dict(zip(result2.keys(), updated_row))

    after_value: dict[str, Any] = {
        "name": updated["name"],
        "permissions": updated["permissions"],
        "description": updated["description"],
    }

    await write_audit_log(
        db,
        action="org.custom_role_updated",
        entity_type="custom_role",
        org_id=updated["org_id"],
        user_id=updated_by,
        entity_id=role_id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
        device_info=device_info,
    )

    perms = updated["permissions"]
    if isinstance(perms, str):
        perms = json.loads(perms)

    return {
        "id": str(updated["id"]),
        "org_id": str(updated["org_id"]),
        "name": updated["name"],
        "slug": updated["slug"],
        "description": updated["description"],
        "permissions": perms if isinstance(perms, list) else [],
        "is_system": updated["is_system"],
        "user_count": 0,
        "created_at": updated["created_at"].isoformat()
        if hasattr(updated["created_at"], "isoformat")
        else str(updated["created_at"]),
    }


async def delete_custom_role(
    db: AsyncSession,
    role_id: uuid.UUID,
    deleted_by: uuid.UUID | None = None,
    ip_address: str | None = None,
    device_info: str | None = None,
) -> None:
    """Delete a custom role.

    Raises ValueError if the role is built-in or has assigned users.
    """
    # Fetch existing role
    result = await db.execute(
        text("SELECT * FROM custom_roles WHERE id = :id"),
        {"id": str(role_id)},
    )
    row = result.fetchone()
    if row is None:
        raise ValueError("Custom role not found")

    col_names = result.keys()
    existing = dict(zip(col_names, row))

    if existing["is_system"]:
        raise ValueError("Cannot delete built-in role")

    # Check for assigned users
    user_count_result = await db.execute(
        text("SELECT COUNT(*) FROM users WHERE custom_role_id = :role_id"),
        {"role_id": str(role_id)},
    )
    user_count = user_count_result.scalar() or 0
    if user_count > 0:
        raise ValueError(f"Role is assigned to {user_count} users")

    # Delete
    await db.execute(
        text("DELETE FROM custom_roles WHERE id = :id"),
        {"id": str(role_id)},
    )
    await db.flush()

    await write_audit_log(
        db,
        action="org.custom_role_deleted",
        entity_type="custom_role",
        org_id=existing["org_id"],
        user_id=deleted_by,
        entity_id=role_id,
        before_value={
            "name": existing["name"],
            "slug": existing["slug"],
            "permissions": existing["permissions"],
        },
        ip_address=ip_address,
        device_info=device_info,
    )
