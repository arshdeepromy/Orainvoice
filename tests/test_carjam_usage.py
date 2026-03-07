"""Unit tests for Task 8.5 — Carjam usage monitoring.

Tests cover:
  - compute_carjam_overage: correct overage calculation
  - get_carjam_per_lookup_cost: reads from integration_configs, falls back to default
  - get_all_orgs_carjam_usage: returns usage table for all non-deleted orgs
  - get_org_carjam_usage: returns usage for a single org
  - Schema validation for admin and org responses
  - Validates: Requirements 16.1, 16.4
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.admin.models import (
    IntegrationConfig,
    Organisation,
    SubscriptionPlan,
)
from app.modules.admin.schemas import (
    AdminCarjamUsageResponse,
    OrgCarjamUsageRow,
)
from app.modules.admin.service import (
    _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD,
    compute_carjam_overage,
    get_all_orgs_carjam_usage,
    get_carjam_per_lookup_cost,
    get_org_carjam_usage,
)
from app.modules.organisations.schemas import OrgCarjamUsageResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(carjam_included=100, **overrides):
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = overrides.get("id", uuid.uuid4())
    plan.name = overrides.get("name", "Starter")
    plan.carjam_lookups_included = carjam_included
    return plan


def _make_org(name="Test Workshop", carjam_lookups=50, plan_id=None, **overrides):
    org = MagicMock(spec=Organisation)
    org.id = overrides.get("id", uuid.uuid4())
    org.name = name
    org.carjam_lookups_this_month = carjam_lookups
    org.plan_id = plan_id or uuid.uuid4()
    org.status = overrides.get("status", "active")
    return org


def _mock_db_session():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# compute_carjam_overage
# ---------------------------------------------------------------------------


class TestComputeCarjamOverage:
    def test_no_overage_when_under_limit(self):
        assert compute_carjam_overage(50, 100) == 0

    def test_no_overage_when_at_limit(self):
        assert compute_carjam_overage(100, 100) == 0

    def test_overage_when_over_limit(self):
        assert compute_carjam_overage(150, 100) == 50

    def test_zero_lookups(self):
        assert compute_carjam_overage(0, 100) == 0

    def test_zero_included(self):
        assert compute_carjam_overage(10, 0) == 10


# ---------------------------------------------------------------------------
# get_carjam_per_lookup_cost
# ---------------------------------------------------------------------------


class TestGetCarjamPerLookupCost:
    @pytest.mark.asyncio
    async def test_returns_default_when_no_config(self):
        """Falls back to default when no carjam integration_config exists."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        cost = await get_carjam_per_lookup_cost(db)
        assert cost == _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD

    @pytest.mark.asyncio
    async def test_reads_cost_from_encrypted_config(self):
        """Reads per_lookup_cost_nzd from decrypted integration config."""
        config_data = json.dumps({"per_lookup_cost_nzd": 0.25, "api_key": "test"})

        config = MagicMock(spec=IntegrationConfig)
        config.name = "carjam"
        config.config_encrypted = b"fake_encrypted"

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config))

        with patch(
            "app.core.encryption.envelope_decrypt_str",
            return_value=config_data,
        ):
            cost = await get_carjam_per_lookup_cost(db)

        assert cost == 0.25

    @pytest.mark.asyncio
    async def test_falls_back_on_decrypt_error(self):
        """Returns default if decryption fails."""
        config = MagicMock(spec=IntegrationConfig)
        config.config_encrypted = b"bad_data"

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(config))

        with patch(
            "app.core.encryption.envelope_decrypt_str",
            side_effect=Exception("decrypt failed"),
        ):
            cost = await get_carjam_per_lookup_cost(db)

        assert cost == _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD


# ---------------------------------------------------------------------------
# get_all_orgs_carjam_usage
# ---------------------------------------------------------------------------


class TestGetAllOrgsCarjamUsage:
    @pytest.mark.asyncio
    async def test_returns_usage_for_all_orgs(self):
        """Req 16.1: Returns usage table for all non-deleted orgs."""
        plan = _make_plan(carjam_included=100)
        org1 = _make_org(name="Workshop A", carjam_lookups=80)
        org2 = _make_org(name="Workshop B", carjam_lookups=150)

        db = _mock_db_session()

        # Mock the per-lookup cost query (first execute call)
        cost_result = _mock_scalar_result(None)
        # Mock the orgs query (second execute call)
        orgs_result = MagicMock()
        orgs_result.all.return_value = [(org1, plan), (org2, plan)]

        db.execute = AsyncMock(side_effect=[cost_result, orgs_result])

        usage_list, per_lookup_cost = await get_all_orgs_carjam_usage(db)

        assert per_lookup_cost == _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD
        assert len(usage_list) == 2

        # Workshop A: 80 lookups, 100 included → 0 overage
        assert usage_list[0]["organisation_name"] == "Workshop A"
        assert usage_list[0]["total_lookups"] == 80
        assert usage_list[0]["included_in_plan"] == 100
        assert usage_list[0]["overage_count"] == 0
        assert usage_list[0]["overage_charge_nzd"] == 0.0

        # Workshop B: 150 lookups, 100 included → 50 overage
        assert usage_list[1]["organisation_name"] == "Workshop B"
        assert usage_list[1]["total_lookups"] == 150
        assert usage_list[1]["included_in_plan"] == 100
        assert usage_list[1]["overage_count"] == 50
        assert usage_list[1]["overage_charge_nzd"] == round(50 * _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD, 2)

    @pytest.mark.asyncio
    async def test_empty_when_no_orgs(self):
        db = _mock_db_session()
        cost_result = _mock_scalar_result(None)
        orgs_result = MagicMock()
        orgs_result.all.return_value = []
        db.execute = AsyncMock(side_effect=[cost_result, orgs_result])

        usage_list, per_lookup_cost = await get_all_orgs_carjam_usage(db)
        assert usage_list == []


# ---------------------------------------------------------------------------
# get_org_carjam_usage
# ---------------------------------------------------------------------------


class TestGetOrgCarjamUsage:
    @pytest.mark.asyncio
    async def test_returns_usage_for_single_org(self):
        """Req 16.4: Returns usage for a single org."""
        plan = _make_plan(carjam_included=200)
        org = _make_org(name="My Workshop", carjam_lookups=250)

        db = _mock_db_session()
        cost_result = _mock_scalar_result(None)
        org_result = MagicMock()
        org_result.one_or_none.return_value = (org, plan)
        db.execute = AsyncMock(side_effect=[cost_result, org_result])

        usage = await get_org_carjam_usage(db, org.id)

        assert usage["organisation_name"] == "My Workshop"
        assert usage["total_lookups"] == 250
        assert usage["included_in_plan"] == 200
        assert usage["overage_count"] == 50
        assert usage["overage_charge_nzd"] == round(50 * _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD, 2)
        assert usage["per_lookup_cost_nzd"] == _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        db = _mock_db_session()
        cost_result = _mock_scalar_result(None)
        org_result = MagicMock()
        org_result.one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[cost_result, org_result])

        with pytest.raises(ValueError, match="Organisation not found"):
            await get_org_carjam_usage(db, uuid.uuid4())


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestCarjamUsageSchemas:
    def test_org_carjam_usage_row(self):
        row = OrgCarjamUsageRow(
            organisation_id=str(uuid.uuid4()),
            organisation_name="Test",
            total_lookups=120,
            included_in_plan=100,
            overage_count=20,
            overage_charge_nzd=3.0,
        )
        assert row.overage_count == 20

    def test_admin_response(self):
        resp = AdminCarjamUsageResponse(
            per_lookup_cost_nzd=0.15,
            organisations=[],
        )
        assert resp.per_lookup_cost_nzd == 0.15
        assert resp.organisations == []

    def test_org_response(self):
        resp = OrgCarjamUsageResponse(
            organisation_id=str(uuid.uuid4()),
            organisation_name="Workshop",
            total_lookups=50,
            included_in_plan=100,
            overage_count=0,
            overage_charge_nzd=0.0,
            per_lookup_cost_nzd=0.15,
        )
        assert resp.overage_count == 0
