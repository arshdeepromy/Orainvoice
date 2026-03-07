"""Dual-write support for V1 → V2 migration transition period.

During the rolling migration, V1 API endpoints that modify organisation
settings also write to the new V2 column structure. This ensures both
old (settings JSONB) and new (dedicated columns) stay in sync.

Once all orgs are fully migrated and V1 endpoints are deprecated, this
module can be removed.

**Validates: Requirement 7.4 — Dual-write strategy during transition**
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Mapping from V1 settings JSONB keys to V2 organisation columns.
V1_TO_V2_COLUMN_MAP: dict[str, str] = {
    "gst_number": "tax_label",  # not a direct map — handled specially
    "currency": "base_currency",
    "date_format": "date_format",
    "timezone": "timezone",
    "tax_rate": "default_tax_rate",
    "tax_inclusive": "tax_inclusive_default",
}


async def sync_v1_settings_to_v2(
    db: AsyncSession,
    org_id: uuid.UUID,
    updated_fields: dict[str, Any],
) -> list[str]:
    """Sync V1 settings updates to V2 organisation columns.

    Called after a V1 org settings update to keep the new dedicated
    columns in sync with the settings JSONB.

    Returns list of V2 columns that were updated.
    """
    v2_updates: dict[str, Any] = {}

    for v1_key, value in updated_fields.items():
        if v1_key == "currency" and value:
            v2_updates["base_currency"] = value
        elif v1_key == "date_format" and value:
            v2_updates["date_format"] = value
        elif v1_key == "timezone" and value:
            v2_updates["timezone"] = value
        elif v1_key == "tax_rate" and value is not None:
            v2_updates["default_tax_rate"] = float(value)
        elif v1_key == "tax_inclusive" and value is not None:
            v2_updates["tax_inclusive_default"] = bool(value)

    if not v2_updates:
        return []

    # Build dynamic SET clause
    set_clauses = ", ".join(f"{col} = :{col}" for col in v2_updates)
    query = f"UPDATE organisations SET {set_clauses} WHERE id = :org_id"
    params = {**v2_updates, "org_id": str(org_id)}

    await db.execute(text(query), params)

    synced = list(v2_updates.keys())
    logger.debug(
        "Dual-write: synced V1→V2 columns for org %s: %s", org_id, synced,
    )
    return synced


async def sync_v2_settings_to_v1(
    db: AsyncSession,
    org_id: uuid.UUID,
    updated_columns: dict[str, Any],
) -> list[str]:
    """Sync V2 column updates back to V1 settings JSONB.

    Called after a V2 org update to keep the legacy settings JSONB
    in sync during the transition period.

    Returns list of V1 settings keys that were updated.
    """
    v1_updates: dict[str, Any] = {}

    # Reverse mapping: V2 column → V1 settings key
    v2_to_v1 = {
        "base_currency": "currency",
        "date_format": "date_format",
        "timezone": "timezone",
        "default_tax_rate": "tax_rate",
        "tax_inclusive_default": "tax_inclusive",
    }

    for v2_col, value in updated_columns.items():
        v1_key = v2_to_v1.get(v2_col)
        if v1_key and value is not None:
            v1_updates[v1_key] = value

    if not v1_updates:
        return []

    # Update the settings JSONB by merging
    for key, value in v1_updates.items():
        await db.execute(
            text(
                """
                UPDATE organisations
                SET settings = COALESCE(settings, '{}'::jsonb) || :patch
                WHERE id = :org_id
                """
            ),
            {
                "org_id": str(org_id),
                "patch": f'{{"{key}": {_json_value(value)}}}',
            },
        )

    synced = list(v1_updates.keys())
    logger.debug(
        "Dual-write: synced V2→V1 settings for org %s: %s", org_id, synced,
    )
    return synced


def _json_value(value: Any) -> str:
    """Convert a Python value to a JSON literal string."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    return f'"{value}"'
