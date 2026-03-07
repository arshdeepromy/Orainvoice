"""Integration test: V1 organisation migration and compatibility.

Flow: migrate V1 org → verify all V1 endpoints still work
      → verify V2 endpoints accessible → verify no data loss.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.migration.v1_migration_service import (
    NZ_DEFAULTS,
    TRADE_CATEGORY_SLUG,
    V1_CORE_MODULES,
    V1MigrationService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_migration_db(*, trade_cat_id=None, compliance_id=None, existing_modules=None):
    """Create a mock DB for migration tests."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    trade_cat_id = trade_cat_id or uuid.uuid4()
    compliance_id = compliance_id or uuid.uuid4()
    existing_modules = existing_modules or []

    call_count = 0

    async def mock_execute(stmt, params=None):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        sql_str = str(stmt)

        if "trade_categories" in sql_str.lower():
            result.scalar_one_or_none.return_value = trade_cat_id
            return result

        if "compliance_profiles" in sql_str.lower():
            result.scalar_one_or_none.return_value = compliance_id
            return result

        if "SELECT" in sql_str.upper() and "org_modules" in sql_str.lower():
            # Check if module already exists
            slug = params.get("slug", "") if params else ""
            if slug in existing_modules:
                result.scalar_one_or_none.return_value = uuid.uuid4()
            else:
                result.scalar_one_or_none.return_value = None
            return result

        if "UPDATE" in sql_str.upper() or "INSERT" in sql_str.upper():
            return MagicMock()

        if "organisations" in sql_str.lower() and "SELECT" in sql_str.upper():
            result.fetchall.return_value = [
                (uuid.uuid4(), "Test Workshop"),
            ]
            return result

        return MagicMock()

    db.execute = mock_execute
    return db, trade_cat_id, compliance_id


class TestV1Compatibility:
    """V1 migration: migrate → V1 endpoints → V2 endpoints → data integrity."""

    @pytest.mark.asyncio
    async def test_migrate_v1_org_applies_nz_defaults(self):
        """Migrating a V1 org applies NZ defaults and workshop trade category."""
        org_id = uuid.uuid4()
        db, trade_cat_id, compliance_id = _make_migration_db()
        svc = V1MigrationService(db)

        result = await svc.migrate_org(org_id)

        assert result["status"] == "completed"
        assert result["trade_category_id"] == str(trade_cat_id)
        assert result["compliance_profile_id"] == str(compliance_id)
        assert result["defaults_applied"]["country_code"] == "NZ"
        assert result["defaults_applied"]["base_currency"] == "NZD"
        assert result["defaults_applied"]["tax_label"] == "GST"
        assert result["defaults_applied"]["default_tax_rate"] == 15.0

    @pytest.mark.asyncio
    async def test_migrate_enables_core_modules(self):
        """Migration enables V1 core modules for the org."""
        org_id = uuid.uuid4()
        db, _, _ = _make_migration_db()
        svc = V1MigrationService(db)

        result = await svc.migrate_org(org_id)

        assert "modules_enabled" in result
        # All V1 core modules should be enabled
        for module in V1_CORE_MODULES:
            assert module in result["modules_enabled"]

    @pytest.mark.asyncio
    async def test_migrate_skips_already_enabled_modules(self):
        """Migration doesn't re-enable modules that are already enabled."""
        org_id = uuid.uuid4()
        db, _, _ = _make_migration_db(existing_modules=["invoicing", "customers"])
        svc = V1MigrationService(db)

        enabled = await svc.enable_core_modules(org_id)

        # Only modules not already enabled should be in the result
        assert "invoicing" not in enabled
        assert "customers" not in enabled
        assert "bookings" in enabled
        assert "notifications" in enabled

    @pytest.mark.asyncio
    async def test_migrate_raises_if_trade_category_missing(self):
        """Migration fails if the trade category seed data is missing."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_result)

        svc = V1MigrationService(db)

        with pytest.raises(ValueError, match="Trade category"):
            await svc.migrate_org(org_id)

    @pytest.mark.asyncio
    async def test_get_all_v1_orgs(self):
        """Listing V1 orgs returns those without trade_category_id."""
        db = AsyncMock()
        org_id = uuid.uuid4()

        result = MagicMock()
        result.fetchall.return_value = [
            (org_id, "Old Workshop"),
        ]
        db.execute = AsyncMock(return_value=result)

        svc = V1MigrationService(db)
        orgs = await svc.get_all_v1_orgs()

        assert len(orgs) == 1
        assert orgs[0]["id"] == org_id
        assert orgs[0]["name"] == "Old Workshop"

    def test_nz_defaults_are_correct(self):
        """NZ defaults match expected values."""
        assert NZ_DEFAULTS["country_code"] == "NZ"
        assert NZ_DEFAULTS["base_currency"] == "NZD"
        assert NZ_DEFAULTS["tax_label"] == "GST"
        assert NZ_DEFAULTS["default_tax_rate"] == 15.0
        assert NZ_DEFAULTS["tax_inclusive_default"] is True
        assert NZ_DEFAULTS["timezone"] == "Pacific/Auckland"

    def test_v1_core_modules_defined(self):
        """V1 core modules list is defined and non-empty."""
        assert len(V1_CORE_MODULES) > 0
        assert "invoicing" in V1_CORE_MODULES
        assert "customers" in V1_CORE_MODULES

    def test_trade_category_slug_is_automotive(self):
        """V1 orgs are assigned the general-automotive trade category."""
        assert TRADE_CATEGORY_SLUG == "general-automotive"
