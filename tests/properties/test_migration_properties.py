"""Comprehensive property-based tests for migration properties.

Properties covered:
  P2 — V1 Migration Validity: migration produces valid V2 org

**Validates: Requirements 2**
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS, safe_text_strategy

from app.modules.migration.v1_migration_service import (
    V1MigrationService,
    V1_CORE_MODULES,
    NZ_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

org_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1, max_size=100,
).filter(lambda s: s.strip())

v1_org_st = st.fixed_dictionaries({
    "id": st.uuids(),
    "name": org_name_st,
    "settings": st.fixed_dictionaries({
        "gst_number": st.one_of(
            st.none(),
            st.from_regex(r"\d{2,3}-?\d{3}-?\d{3}", fullmatch=True),
        ),
        "phone": st.one_of(st.none(), st.text(min_size=5, max_size=20)),
        "email": st.one_of(st.none(), st.emails()),
    }),
})


# ---------------------------------------------------------------------------
# Mock DB
# ---------------------------------------------------------------------------

class MockMigrationDB:
    def __init__(self, org: dict) -> None:
        self._trade_cat_id = uuid.uuid4()
        self._compliance_id = uuid.uuid4()
        self._org = {
            "id": org["id"], "name": org["name"],
            "trade_category_id": None, "country_code": None,
            "base_currency": None, "locale": None,
            "tax_label": None, "default_tax_rate": None,
            "tax_inclusive_default": None, "date_format": None,
            "timezone": None, "compliance_profile_id": None,
            "setup_wizard_state": {},
        }
        self._modules: dict[str, bool] = {}

    async def execute(self, query, params=None):
        query_str = str(query) if not isinstance(query, str) else query
        if "SELECT id FROM trade_categories" in query_str:
            return _scalar_result(self._trade_cat_id)
        elif "SELECT id FROM compliance_profiles" in query_str:
            return _scalar_result(self._compliance_id)
        elif "UPDATE organisations" in query_str and params:
            for key in list(params.keys()):
                if key != "org_id" and key in self._org:
                    self._org[key] = params[key]
            if "setup_wizard_state" in (params or {}):
                self._org["setup_wizard_state"] = json.loads(params["setup_wizard_state"])
            return _scalar_result(None)
        elif "SELECT id FROM org_modules" in query_str:
            slug = params.get("slug", "")
            return _scalar_result(uuid.uuid4() if self._modules.get(slug) else None)
        elif "INSERT INTO org_modules" in query_str:
            slug = params.get("slug", "")
            self._modules[slug] = True
            return _scalar_result(None)
        return _scalar_result(None)

    @property
    def org_state(self) -> dict:
        return dict(self._org)

    @property
    def enabled_modules(self) -> set[str]:
        return {k for k, v in self._modules.items() if v}


def _scalar_result(value):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    mock.scalar.return_value = value
    mock.fetchall.return_value = []
    return mock


# ===========================================================================
# Property 2: V1 Migration Produces Valid V2 Org
# ===========================================================================


class TestP2V1MigrationValidity:
    """V1 migration produces valid V2 org with all required fields.

    **Validates: Requirements 2**
    """

    @given(org=v1_org_st)
    @PBT_SETTINGS
    def test_migration_populates_all_required_fields(self, org: dict) -> None:
        """P2: after migration, every required V2 field is non-None."""
        import asyncio

        async def _run():
            mock_db = MockMigrationDB(org)
            service = V1MigrationService(db=mock_db)
            result = await service.migrate_org(org["id"])

            state = mock_db.org_state
            assert state["country_code"] == NZ_DEFAULTS["country_code"]
            assert state["base_currency"] == NZ_DEFAULTS["base_currency"]
            assert state["locale"] == NZ_DEFAULTS["locale"]
            assert state["tax_label"] == NZ_DEFAULTS["tax_label"]
            assert float(state["default_tax_rate"]) == NZ_DEFAULTS["default_tax_rate"]
            assert state["tax_inclusive_default"] == NZ_DEFAULTS["tax_inclusive_default"]
            assert state["date_format"] == NZ_DEFAULTS["date_format"]
            assert state["timezone"] == NZ_DEFAULTS["timezone"]
            assert state["trade_category_id"] is not None
            assert state["compliance_profile_id"] is not None

            wizard = state["setup_wizard_state"]
            assert wizard["status"] == "completed"
            assert wizard["migrated_from_v1"] is True
            assert result["status"] == "completed"

        asyncio.run(_run())

    @given(org=v1_org_st)
    @PBT_SETTINGS
    def test_migration_enables_all_core_modules(self, org: dict) -> None:
        """P2: after migration, all V1 core modules are enabled."""
        import asyncio

        async def _run():
            mock_db = MockMigrationDB(org)
            service = V1MigrationService(db=mock_db)
            await service.migrate_org(org["id"])

            enabled = mock_db.enabled_modules
            for module in V1_CORE_MODULES:
                assert module in enabled, f"Core module '{module}' not enabled"

        asyncio.run(_run())

    @given(org=v1_org_st)
    @PBT_SETTINGS
    def test_migration_result_contains_required_keys(self, org: dict) -> None:
        """P2: migration result dict contains all expected keys."""
        import asyncio

        async def _run():
            mock_db = MockMigrationDB(org)
            service = V1MigrationService(db=mock_db)
            result = await service.migrate_org(org["id"])

            required_keys = {
                "org_id", "trade_category_id", "compliance_profile_id",
                "modules_enabled", "defaults_applied", "status",
            }
            assert required_keys.issubset(result.keys())

        asyncio.run(_run())
