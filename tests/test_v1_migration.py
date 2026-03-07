"""Tests for V1 organisation data migration.

Covers:
- 53.8: Migrated V1 org can access all previously available features without re-setup
- 53.9: V1 API endpoints continue to work identically after migration
- 53.10: Rollback script correctly reverts migration for specified orgs

**Validates: Requirements 7.1, 7.4, 7.5, 7.6**
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.migration.v1_migration_service import (
    V1MigrationService,
    V1_CORE_MODULES,
    NZ_DEFAULTS,
    TRADE_CATEGORY_SLUG,
)
from app.modules.migration.dual_write import (
    sync_v1_settings_to_v2,
    sync_v2_settings_to_v1,
)
from app.modules.migration.integrity_checks import (
    run_integrity_checks,
    MigrationIntegrityReport,
)


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------

class MockDB:
    """In-memory mock DB for migration tests."""

    def __init__(self) -> None:
        self._trade_cat_id = uuid.uuid4()
        self._compliance_id = uuid.uuid4()
        self._orgs: dict[str, dict] = {}
        self._modules: dict[str, dict[str, bool]] = {}
        self._executed_queries: list[str] = []

    def add_org(self, org_id: uuid.UUID, name: str = "Test Workshop") -> None:
        self._orgs[str(org_id)] = {
            "id": org_id,
            "name": name,
            "trade_category_id": None,
            "country_code": None,
            "base_currency": None,
            "locale": None,
            "tax_label": None,
            "default_tax_rate": None,
            "tax_inclusive_default": None,
            "date_format": None,
            "timezone": None,
            "compliance_profile_id": None,
            "setup_wizard_state": {},
            "settings": {},
        }
        self._modules[str(org_id)] = {}

    async def execute(self, query, params=None):
        query_str = str(query) if not isinstance(query, str) else query
        self._executed_queries.append(query_str)

        if "SELECT id FROM trade_categories" in query_str:
            return _scalar_result(self._trade_cat_id)
        elif "SELECT id FROM compliance_profiles" in query_str:
            return _scalar_result(self._compliance_id)
        elif "UPDATE organisations" in query_str and params:
            org_id = params.get("org_id")
            if org_id and org_id in self._orgs:
                org = self._orgs[org_id]
                # Handle rollback: SET ... = NULL pattern
                if "trade_category_id = NULL" in query_str:
                    org["trade_category_id"] = None
                    org["compliance_profile_id"] = None
                    org["country_code"] = None
                    org["setup_wizard_state"] = {}
                else:
                    for key in list(params.keys()):
                        if key != "org_id" and key in org:
                            org[key] = params[key]
                    if "setup_wizard_state" in params:
                        org["setup_wizard_state"] = json.loads(params["setup_wizard_state"])
                    if "settings" in params:
                        org["settings"] = json.loads(params["settings"]) if isinstance(params["settings"], str) else params["settings"]
            return _scalar_result(None)
        elif "SELECT id FROM org_modules" in query_str:
            org_id = params.get("org_id", "")
            slug = params.get("slug", "")
            modules = self._modules.get(org_id, {})
            return _scalar_result(uuid.uuid4() if modules.get(slug) else None)
        elif "INSERT INTO org_modules" in query_str:
            org_id = params.get("org_id", "")
            slug = params.get("slug", "")
            if org_id not in self._modules:
                self._modules[org_id] = {}
            self._modules[org_id][slug] = True
            return _scalar_result(None)
        elif "DELETE FROM org_modules" in query_str:
            org_id = params.get("org_id", "")
            slugs = params.get("slugs", [])
            if org_id in self._modules:
                for slug in slugs:
                    self._modules[org_id].pop(slug, None)
            return _scalar_result(None)
        elif "SELECT id, name" in query_str or "SELECT id FROM organisations" in query_str:
            # get_all_v1_orgs or rollback query
            unmigrated = [
                o for o in self._orgs.values()
                if o.get("trade_category_id") is None
            ]
            mock = MagicMock()
            mock.fetchall.return_value = [(o["id"], o["name"]) for o in unmigrated]
            return mock
        elif "SELECT COUNT" in query_str:
            return _scalar_result(len(self._orgs))

        return _scalar_result(None)


def _scalar_result(value):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalar.return_value = value
    mock.fetchall.return_value = []
    return mock


# ===========================================================================
# 53.8: Migrated V1 org can access all previously available features
# ===========================================================================


class TestMigratedOrgFeatureAccess:
    """Validates: Requirement 7.1 — migrated V1 org retains feature access."""

    @pytest.mark.asyncio
    async def test_migrated_org_has_all_core_modules_enabled(self):
        """After migration, all V1 core modules must be enabled so the
        org can access invoicing, customers, bookings, and notifications."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop A")

        service = V1MigrationService(db=db)
        result = await service.migrate_org(org_id)

        enabled = db._modules.get(str(org_id), {})
        for module in V1_CORE_MODULES:
            assert enabled.get(module) is True, (
                f"Module '{module}' not enabled after migration"
            )

    @pytest.mark.asyncio
    async def test_migrated_org_has_completed_wizard_state(self):
        """Migrated org should have setup_wizard_state = completed so
        the setup wizard is not shown again."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop B")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        org = db._orgs[str(org_id)]
        assert org["setup_wizard_state"]["status"] == "completed"
        assert org["setup_wizard_state"]["migrated_from_v1"] is True

    @pytest.mark.asyncio
    async def test_migrated_org_has_valid_trade_category(self):
        """Migrated org must have a trade_category_id pointing to
        'general-automotive'."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop C")

        service = V1MigrationService(db=db)
        result = await service.migrate_org(org_id)

        assert result["trade_category_id"] is not None
        assert result["trade_category_id"] == str(db._trade_cat_id)

    @pytest.mark.asyncio
    async def test_migrated_org_has_nz_defaults(self):
        """All NZ defaults must be applied to the migrated org."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop D")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        org = db._orgs[str(org_id)]
        assert org["country_code"] == "NZ"
        assert org["base_currency"] == "NZD"
        assert org["locale"] == "en-NZ"
        assert org["tax_label"] == "GST"
        assert float(org["default_tax_rate"]) == 15.0
        assert org["tax_inclusive_default"] is True
        assert org["date_format"] == "dd/MM/yyyy"
        assert org["timezone"] == "Pacific/Auckland"

    @pytest.mark.asyncio
    async def test_already_enabled_modules_not_duplicated(self):
        """If a module is already enabled, migration should not create
        a duplicate record."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop E")
        # Pre-enable invoicing
        db._modules[str(org_id)] = {"invoicing": True}

        service = V1MigrationService(db=db)
        result = await service.migrate_org(org_id)

        # invoicing should not be in the newly enabled list
        assert "invoicing" not in result["modules_enabled"]
        # But it should still be enabled
        assert db._modules[str(org_id)]["invoicing"] is True


# ===========================================================================
# 53.9: V1 API endpoints continue to work identically after migration
# ===========================================================================


class TestV1ApiDualWrite:
    """Validates: Requirement 7.4 — dual-write keeps V1 and V2 in sync."""

    @pytest.mark.asyncio
    async def test_v1_currency_update_syncs_to_v2_base_currency(self):
        """When V1 settings update 'currency', V2 'base_currency' column
        should also be updated."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id)

        synced = await sync_v1_settings_to_v2(
            db=db,
            org_id=org_id,
            updated_fields={"currency": "AUD"},
        )

        assert "base_currency" in synced

    @pytest.mark.asyncio
    async def test_v1_timezone_update_syncs_to_v2(self):
        """When V1 settings update 'timezone', V2 column should sync."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id)

        synced = await sync_v1_settings_to_v2(
            db=db,
            org_id=org_id,
            updated_fields={"timezone": "Australia/Sydney"},
        )

        assert "timezone" in synced

    @pytest.mark.asyncio
    async def test_v1_tax_rate_update_syncs_to_v2(self):
        """When V1 settings update 'tax_rate', V2 'default_tax_rate' syncs."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id)

        synced = await sync_v1_settings_to_v2(
            db=db,
            org_id=org_id,
            updated_fields={"tax_rate": 10.0},
        )

        assert "default_tax_rate" in synced

    @pytest.mark.asyncio
    async def test_v2_base_currency_update_syncs_to_v1_settings(self):
        """When V2 column 'base_currency' is updated, V1 settings
        'currency' key should also be updated."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id)

        synced = await sync_v2_settings_to_v1(
            db=db,
            org_id=org_id,
            updated_columns={"base_currency": "GBP"},
        )

        assert "currency" in synced

    @pytest.mark.asyncio
    async def test_no_sync_for_unrelated_fields(self):
        """Fields that don't have a V1↔V2 mapping should not be synced."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id)

        synced = await sync_v1_settings_to_v2(
            db=db,
            org_id=org_id,
            updated_fields={"org_name": "New Name", "phone": "123456"},
        )

        assert synced == []

    @pytest.mark.asyncio
    async def test_empty_update_produces_no_sync(self):
        """An empty update dict should produce no sync operations."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id)

        synced = await sync_v1_settings_to_v2(
            db=db,
            org_id=org_id,
            updated_fields={},
        )

        assert synced == []


# ===========================================================================
# 53.10: Rollback script correctly reverts migration for specified orgs
# ===========================================================================


class TestRollbackMigration:
    """Validates: Requirement 7.6 — rollback reverts migration cleanly."""

    @pytest.mark.asyncio
    async def test_rollback_reverts_trade_category_to_null(self):
        """After rollback, trade_category_id should be NULL."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop F")

        # Migrate first
        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        org = db._orgs[str(org_id)]
        assert org["trade_category_id"] is not None

        # Now rollback
        from scripts.rollback_v1_migration import rollback_org
        await rollback_org(db, org_id)

        org = db._orgs[str(org_id)]
        assert org["trade_category_id"] is None

    @pytest.mark.asyncio
    async def test_rollback_reverts_compliance_profile_to_null(self):
        """After rollback, compliance_profile_id should be NULL."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop G")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        from scripts.rollback_v1_migration import rollback_org
        await rollback_org(db, org_id)

        org = db._orgs[str(org_id)]
        assert org["compliance_profile_id"] is None

    @pytest.mark.asyncio
    async def test_rollback_reverts_country_code_to_null(self):
        """After rollback, country_code should be NULL."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop H")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        from scripts.rollback_v1_migration import rollback_org
        await rollback_org(db, org_id)

        org = db._orgs[str(org_id)]
        assert org["country_code"] is None

    @pytest.mark.asyncio
    async def test_rollback_resets_wizard_state(self):
        """After rollback, setup_wizard_state should be empty dict."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop I")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        from scripts.rollback_v1_migration import rollback_org
        await rollback_org(db, org_id)

        org = db._orgs[str(org_id)]
        assert org["setup_wizard_state"] == {} or org["setup_wizard_state"] == "{}"

    @pytest.mark.asyncio
    async def test_rollback_removes_core_modules(self):
        """After rollback, V1 core modules should be removed."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop J")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        # Verify modules were enabled
        modules = db._modules.get(str(org_id), {})
        assert len(modules) > 0

        from scripts.rollback_v1_migration import rollback_org
        await rollback_org(db, org_id)

        # Core modules should be removed
        modules = db._modules.get(str(org_id), {})
        for slug in V1_CORE_MODULES:
            assert slug not in modules, f"Module '{slug}' still present after rollback"

    @pytest.mark.asyncio
    async def test_rollback_returns_status(self):
        """Rollback should return a result dict with status."""
        db = MockDB()
        org_id = uuid.uuid4()
        db.add_org(org_id, "Workshop K")

        service = V1MigrationService(db=db)
        await service.migrate_org(org_id)

        from scripts.rollback_v1_migration import rollback_org
        result = await rollback_org(db, org_id)

        assert result["org_id"] == str(org_id)
        assert result["status"] == "rolled_back"
