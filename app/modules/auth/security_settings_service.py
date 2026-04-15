"""Service for reading and updating org-level security settings.

Security settings are stored in the ``organisations.settings`` JSONB column
under namespaced keys (``mfa_policy``, ``password_policy``, ``lockout_policy``,
``session_policy``).  Missing keys fall back to schema defaults so that
existing orgs keep their current behaviour until an Org_Admin explicitly
configures new values.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.auth.security_settings_schemas import (
    OrgSecuritySettings,
    SecuritySettingsUpdate,
)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_security_settings(
    db: AsyncSession,
    org_id: UUID,
) -> OrgSecuritySettings:
    """Return the org's security settings, merged with defaults.

    If the org has no ``settings`` JSONB or the column is ``NULL`` / ``{}``,
    every field falls back to the Pydantic-defined default.
    """
    result = await db.execute(
        text("SELECT settings FROM organisations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    row = result.first()
    raw: dict = (row[0] if row and row[0] else {})

    # Extract only the security-related keys and let Pydantic fill defaults
    return OrgSecuritySettings(
        mfa_policy=raw.get("mfa_policy", {}),
        password_policy=raw.get("password_policy", {}),
        lockout_policy=raw.get("lockout_policy", {}),
        session_policy=raw.get("session_policy", {}),
    )


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_security_settings(
    db: AsyncSession,
    org_id: UUID,
    user_id: UUID,
    updates: SecuritySettingsUpdate,
    ip_address: str | None = None,
    device_info: str | None = None,
) -> OrgSecuritySettings:
    """Apply a partial update to the org's security settings.

    Only the sections present (non-``None``) in *updates* are overwritten;
    all other sections are preserved.  An audit log entry is written with
    before/after values for the changed sections.

    Returns the full, merged ``OrgSecuritySettings`` after persisting.
    """
    # 1. Read current raw JSONB ------------------------------------------------
    result = await db.execute(
        text("SELECT settings FROM organisations WHERE id = :org_id"),
        {"org_id": str(org_id)},
    )
    row = result.first()
    current_raw: dict = dict(row[0]) if row and row[0] else {}

    # 2. Capture before state (only the security keys) -------------------------
    before_value: dict = {}
    after_value: dict = {}

    # 3. Apply partial updates -------------------------------------------------
    updated_raw = dict(current_raw)  # shallow copy — we only replace top-level keys

    section_keys = ["mfa_policy", "password_policy", "lockout_policy", "session_policy"]
    for key in section_keys:
        section = getattr(updates, key, None)
        if section is not None:
            before_value[key] = current_raw.get(key, {})
            serialised = section.model_dump(mode="json")
            updated_raw[key] = serialised
            after_value[key] = serialised

    # 4. Persist ---------------------------------------------------------------
    await db.execute(
        text(
            "UPDATE organisations SET settings = :settings, updated_at = now() "
            "WHERE id = :org_id"
        ),
        {"settings": json.dumps(updated_raw), "org_id": str(org_id)},
    )

    await db.flush()

    # 5. Audit log -------------------------------------------------------------
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="org.security_settings_updated",
        entity_type="organisation",
        entity_id=org_id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
        device_info=device_info,
    )

    # 6. Re-read and return merged settings ------------------------------------
    return await get_security_settings(db, org_id)
