"""V1 Organisation Migration Service.

Provides utilities to migrate existing V1 (NZ workshop) organisations to the
universal platform schema by backfilling new columns and enabling core modules.

**Validates: Requirement 7.1, 7.4, 7.5**
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# V1 core modules that every existing workshop org should have enabled.
V1_CORE_MODULES: list[str] = [
    "invoicing",
    "customers",
    "bookings",
    "notifications",
]

# NZ defaults applied to V1 orgs during migration.
NZ_DEFAULTS: dict[str, Any] = {
    "country_code": "NZ",
    "base_currency": "NZD",
    "locale": "en-NZ",
    "tax_label": "GST",
    "default_tax_rate": 15.0,
    "tax_inclusive_default": True,
    "date_format": "dd/MM/yyyy",
    "timezone": "Pacific/Auckland",
}

TRADE_CATEGORY_SLUG = "general-automotive"


class V1MigrationService:
    """Service for migrating V1 organisations to the V2 universal schema."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def migrate_org(self, org_id: uuid.UUID) -> dict[str, Any]:
        """Backfill all new columns for a single V1 organisation.

        Returns a result dict with migration details.
        """
        logger.info("Starting V1 migration for org %s", org_id)

        # 1. Look up the trade category ID for 'general-automotive'
        trade_cat_row = await self.db.execute(
            text("SELECT id FROM trade_categories WHERE slug = :slug"),
            {"slug": TRADE_CATEGORY_SLUG},
        )
        trade_cat = trade_cat_row.scalar_one_or_none()
        if trade_cat is None:
            raise ValueError(
                f"Trade category '{TRADE_CATEGORY_SLUG}' not found. "
                "Ensure seed migrations have been run."
            )

        # 2. Look up the NZ compliance profile
        cp_row = await self.db.execute(
            text("SELECT id FROM compliance_profiles WHERE country_code = 'NZ'"),
        )
        compliance_profile_id = cp_row.scalar_one_or_none()

        # 3. Update the organisation with NZ defaults
        await self.db.execute(
            text(
                """
                UPDATE organisations
                SET trade_category_id = :trade_category_id,
                    country_code = :country_code,
                    base_currency = :base_currency,
                    locale = :locale,
                    tax_label = :tax_label,
                    default_tax_rate = :default_tax_rate,
                    tax_inclusive_default = :tax_inclusive_default,
                    date_format = :date_format,
                    timezone = :timezone,
                    compliance_profile_id = :compliance_profile_id,
                    setup_wizard_state = :setup_wizard_state
                WHERE id = :org_id
                """
            ),
            {
                "org_id": str(org_id),
                "trade_category_id": str(trade_cat),
                "country_code": NZ_DEFAULTS["country_code"],
                "base_currency": NZ_DEFAULTS["base_currency"],
                "locale": NZ_DEFAULTS["locale"],
                "tax_label": NZ_DEFAULTS["tax_label"],
                "default_tax_rate": NZ_DEFAULTS["default_tax_rate"],
                "tax_inclusive_default": NZ_DEFAULTS["tax_inclusive_default"],
                "date_format": NZ_DEFAULTS["date_format"],
                "timezone": NZ_DEFAULTS["timezone"],
                "compliance_profile_id": str(compliance_profile_id) if compliance_profile_id else None,
                "setup_wizard_state": json.dumps({
                    "status": "completed",
                    "migrated_from_v1": True,
                    "migrated_at": datetime.now(timezone.utc).isoformat(),
                }),
            },
        )

        # 4. Enable core modules
        modules_enabled = await self.enable_core_modules(org_id)

        result = {
            "org_id": str(org_id),
            "trade_category_id": str(trade_cat),
            "compliance_profile_id": str(compliance_profile_id) if compliance_profile_id else None,
            "modules_enabled": modules_enabled,
            "defaults_applied": NZ_DEFAULTS,
            "status": "completed",
        }
        logger.info("V1 migration completed for org %s", org_id)
        return result

    async def enable_core_modules(
        self, org_id: uuid.UUID, modules: list[str] | None = None,
    ) -> list[str]:
        """Enable V1 core modules for an organisation.

        Inserts records into org_modules for each module slug, skipping
        any that are already enabled.

        Returns the list of module slugs that were newly enabled.
        """
        module_slugs = modules or V1_CORE_MODULES
        enabled: list[str] = []

        for slug in module_slugs:
            # Check if already enabled
            existing = await self.db.execute(
                text(
                    "SELECT id FROM org_modules "
                    "WHERE org_id = :org_id AND module_slug = :slug"
                ),
                {"org_id": str(org_id), "slug": slug},
            )
            if existing.scalar_one_or_none() is not None:
                continue

            await self.db.execute(
                text(
                    """
                    INSERT INTO org_modules (id, org_id, module_slug, is_enabled, enabled_at)
                    VALUES (:id, :org_id, :slug, true, :now)
                    ON CONFLICT (org_id, module_slug) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org_id": str(org_id),
                    "slug": slug,
                    "now": datetime.now(timezone.utc),
                },
            )
            enabled.append(slug)

        logger.info(
            "Enabled %d modules for org %s: %s",
            len(enabled), org_id, enabled,
        )
        return enabled

    async def get_all_v1_orgs(self) -> list[dict[str, Any]]:
        """Return all organisations that haven't been migrated yet.

        V1 orgs are identified by having no trade_category_id set, or
        setup_wizard_state not containing 'migrated_from_v1'.
        """
        result = await self.db.execute(
            text(
                """
                SELECT id, name
                FROM organisations
                WHERE trade_category_id IS NULL
                   OR NOT (setup_wizard_state->>'migrated_from_v1')::boolean IS TRUE
                """
            )
        )
        rows = result.fetchall()
        return [{"id": row[0], "name": row[1]} for row in rows]
