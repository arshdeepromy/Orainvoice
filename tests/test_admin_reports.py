"""Tests for global admin report endpoints (Task 22.2).

Covers:
- get_mrr_report service function
- get_org_overview_report service function
- get_carjam_cost_report service function
- get_churn_report service function
- get_vehicle_db_stats service function
- Schema validation for all report responses

Requirements: 46.1, 46.2, 46.3, 46.4, 46.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.admin.models import GlobalVehicle, Organisation, SubscriptionPlan
from app.modules.admin.schemas import (
    CarjamCostReportResponse,
    ChurnOrgRow,
    ChurnReportResponse,
    MrrMonthTrend,
    MrrPlanBreakdown,
    MrrReportResponse,
    OrgOverviewResponse,
    OrgOverviewRow,
    VehicleDbStatsResponse,
)
from app.modules.admin.service import (
    get_carjam_cost_report,
    get_churn_report,
    get_mrr_report,
    get_org_overview_report,
    get_vehicle_db_stats,
)
from app.modules.auth.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(
    name: str = "Starter",
    monthly_price: float = 49.0,
    carjam_included: int = 100,
    **overrides,
) -> MagicMock:
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = overrides.get("id", uuid.uuid4())
    plan.name = name
    plan.monthly_price_nzd = monthly_price
    plan.user_seats = 5
    plan.storage_quota_gb = 10
    plan.carjam_lookups_included = carjam_included
    return plan


def _make_org(
    plan: MagicMock,
    name: str = "Test Workshop",
    status: str = "active",
    carjam_lookups: int = 0,
    storage_used: int = 0,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    org = MagicMock(spec=Organisation)
    org.id = uuid.uuid4()
    org.name = name
    org.plan_id = plan.id
    org.status = status
    org.storage_quota_gb = plan.storage_quota_gb
    org.storage_used_bytes = storage_used
    org.carjam_lookups_this_month = carjam_lookups
    org.trial_ends_at = None
    org.created_at = created_at or datetime.now(timezone.utc) - timedelta(days=30)
    org.updated_at = updated_at or datetime.now(timezone.utc)
    return org


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_execute_result(rows):
    """Create a mock result that returns rows from .all()."""
    result = MagicMock()
    result.all.return_value = rows
    return result


def _mock_scalar_result(value):
    """Create a mock result that returns a scalar value."""
    result = MagicMock()
    result.scalar.return_value = value
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# MRR Report — Requirement 46.2
# ---------------------------------------------------------------------------


class TestMrrReport:
    """Tests for get_mrr_report."""

    @pytest.mark.asyncio
    async def test_mrr_empty_platform(self):
        """MRR is zero when no organisations exist."""
        db = _mock_db()
        # First call: per-org query returns empty
        # Subsequent calls: month-over-month queries return 0
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),  # per-org rows
                _mock_scalar_result(0),    # month 1
                _mock_scalar_result(0),    # month 2
                _mock_scalar_result(0),    # month 3
                _mock_scalar_result(0),    # month 4
                _mock_scalar_result(0),    # month 5
                _mock_scalar_result(0),    # month 6
            ]
        )

        result = await get_mrr_report(db)

        assert result["total_mrr_nzd"] == 0.0
        assert result["plan_breakdown"] == []
        assert result["interval_breakdown"] == []
        assert len(result["month_over_month"]) == 6

    @pytest.mark.asyncio
    async def test_mrr_with_active_orgs(self):
        """MRR reflects active orgs × plan price (monthly interval, 0% discount)."""
        db = _mock_db()
        plan_id = uuid.uuid4()
        monthly_config = [{"interval": "monthly", "enabled": True, "discount_percent": 0}]

        # Two orgs on Pro plan at $99, both monthly
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([
                    (uuid.uuid4(), "monthly", plan_id, "Pro", 99.0, monthly_config),
                    (uuid.uuid4(), "monthly", plan_id, "Pro", 99.0, monthly_config),
                ]),
                _mock_scalar_result(198.0),  # month 1
                _mock_scalar_result(198.0),  # month 2
                _mock_scalar_result(198.0),  # month 3
                _mock_scalar_result(198.0),  # month 4
                _mock_scalar_result(198.0),  # month 5
                _mock_scalar_result(198.0),  # month 6
            ]
        )

        result = await get_mrr_report(db)

        assert result["total_mrr_nzd"] == 198.0
        assert len(result["plan_breakdown"]) == 1
        assert result["plan_breakdown"][0]["plan_name"] == "Pro"
        assert result["plan_breakdown"][0]["active_orgs"] == 2
        assert result["plan_breakdown"][0]["mrr_nzd"] == 198.0
        # Interval breakdown: all monthly
        assert len(result["interval_breakdown"]) == 1
        assert result["interval_breakdown"][0]["interval"] == "monthly"
        assert result["interval_breakdown"][0]["org_count"] == 2

    @pytest.mark.asyncio
    async def test_mrr_multiple_plans(self):
        """MRR sums across multiple plans."""
        db = _mock_db()
        plan_id_basic = uuid.uuid4()
        plan_id_pro = uuid.uuid4()
        monthly_config = [{"interval": "monthly", "enabled": True, "discount_percent": 0}]

        # 3 orgs on Basic ($29) + 2 orgs on Pro ($99), all monthly
        org_rows = [
            (uuid.uuid4(), "monthly", plan_id_basic, "Basic", 29.0, monthly_config),
            (uuid.uuid4(), "monthly", plan_id_basic, "Basic", 29.0, monthly_config),
            (uuid.uuid4(), "monthly", plan_id_basic, "Basic", 29.0, monthly_config),
            (uuid.uuid4(), "monthly", plan_id_pro, "Pro", 99.0, monthly_config),
            (uuid.uuid4(), "monthly", plan_id_pro, "Pro", 99.0, monthly_config),
        ]

        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result(org_rows),
                *[_mock_scalar_result(285.0) for _ in range(6)],
            ]
        )

        result = await get_mrr_report(db)

        assert result["total_mrr_nzd"] == 285.0  # 3*29 + 2*99
        assert len(result["plan_breakdown"]) == 2

    @pytest.mark.asyncio
    async def test_mrr_month_over_month_has_six_entries(self):
        """Month-over-month trend always has 6 entries."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result([]),
                *[_mock_scalar_result(0) for _ in range(6)],
            ]
        )

        result = await get_mrr_report(db)
        assert len(result["month_over_month"]) == 6
        for entry in result["month_over_month"]:
            assert "month" in entry
            assert "mrr_nzd" in entry

    @pytest.mark.asyncio
    async def test_mrr_normalises_across_intervals(self):
        """MRR normalises annual/weekly orgs to monthly equivalent.

        Requirements 12.1, 12.2, 12.3.
        """
        db = _mock_db()
        plan_id = uuid.uuid4()
        interval_config = [
            {"interval": "weekly", "enabled": True, "discount_percent": 0},
            {"interval": "monthly", "enabled": True, "discount_percent": 0},
            {"interval": "annual", "enabled": True, "discount_percent": 10},
        ]

        # Base monthly price = $120
        # Monthly org: effective=$120, MRR=$120
        # Weekly org: effective=120*12/52=$27.69, MRR=27.69*52/12=$120
        # Annual org (10% discount): effective=120*12/1*0.9=$1296, MRR=1296/12=$108
        org_rows = [
            (uuid.uuid4(), "monthly", plan_id, "Pro", 120.0, interval_config),
            (uuid.uuid4(), "weekly", plan_id, "Pro", 120.0, interval_config),
            (uuid.uuid4(), "annual", plan_id, "Pro", 120.0, interval_config),
        ]

        db.execute = AsyncMock(
            side_effect=[
                _mock_execute_result(org_rows),
                *[_mock_scalar_result(0) for _ in range(6)],
            ]
        )

        result = await get_mrr_report(db)

        # Total MRR: ~120 (weekly normalised) + 120 (monthly) + 108 (annual) ≈ 347.99
        # Small rounding from weekly: effective=27.69, MRR=27.69*52/12=119.99
        assert abs(result["total_mrr_nzd"] - 348.0) < 0.1
        assert len(result["plan_breakdown"]) == 1
        assert result["plan_breakdown"][0]["active_orgs"] == 3

        # Interval breakdown should have 3 entries
        assert len(result["interval_breakdown"]) == 3
        intervals_by_name = {ib["interval"]: ib for ib in result["interval_breakdown"]}
        assert intervals_by_name["monthly"]["org_count"] == 1
        assert intervals_by_name["monthly"]["mrr_nzd"] == 120.0
        assert intervals_by_name["weekly"]["org_count"] == 1
        assert abs(intervals_by_name["weekly"]["mrr_nzd"] - 120.0) < 0.1
        assert intervals_by_name["annual"]["org_count"] == 1
        assert intervals_by_name["annual"]["mrr_nzd"] == 108.0


# ---------------------------------------------------------------------------
# Organisation Overview Report — Requirement 46.3
# ---------------------------------------------------------------------------


class TestOrgOverviewReport:
    """Tests for get_org_overview_report."""

    @pytest.mark.asyncio
    async def test_overview_empty(self):
        """Empty platform returns empty list."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_execute_result([]))

        result = await get_org_overview_report(db)
        assert result["total"] == 0
        assert result["organisations"] == []

    @pytest.mark.asyncio
    async def test_overview_includes_org_details(self):
        """Overview includes plan name, storage, carjam usage, and last login."""
        db = _mock_db()
        plan = _make_plan(name="Enterprise", monthly_price=199.0)
        org = _make_org(plan, name="Big Workshop", carjam_lookups=42, storage_used=1024000)
        last_login = datetime.now(timezone.utc) - timedelta(hours=2)

        db.execute = AsyncMock(
            return_value=_mock_execute_result([
                (org, "Enterprise", last_login),
            ])
        )

        result = await get_org_overview_report(db)

        assert result["total"] == 1
        row = result["organisations"][0]
        assert row["organisation_name"] == "Big Workshop"
        assert row["plan_name"] == "Enterprise"
        assert row["billing_status"] == "active"
        assert row["carjam_lookups_this_month"] == 42
        assert row["storage_used_bytes"] == 1024000
        assert row["last_login_at"] == last_login

    @pytest.mark.asyncio
    async def test_overview_trial_status(self):
        """Trial orgs show correct trial_status."""
        db = _mock_db()
        plan = _make_plan()
        org = _make_org(plan, name="Trial Shop", status="trial")
        org.trial_ends_at = datetime.now(timezone.utc) + timedelta(days=7)

        db.execute = AsyncMock(
            return_value=_mock_execute_result([(org, "Starter", None)])
        )

        result = await get_org_overview_report(db)
        assert result["organisations"][0]["trial_status"] == "trial"

    @pytest.mark.asyncio
    async def test_overview_expired_trial(self):
        """Expired trial shows 'expired' trial_status."""
        db = _mock_db()
        plan = _make_plan()
        org = _make_org(plan, name="Expired Trial", status="trial")
        org.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)

        db.execute = AsyncMock(
            return_value=_mock_execute_result([(org, "Starter", None)])
        )

        result = await get_org_overview_report(db)
        assert result["organisations"][0]["trial_status"] == "expired"


# ---------------------------------------------------------------------------
# Carjam Cost Report — Requirement 46.1
# ---------------------------------------------------------------------------


class TestCarjamCostReport:
    """Tests for get_carjam_cost_report."""

    @pytest.mark.asyncio
    async def test_cost_report_empty(self):
        """No orgs means zero cost and revenue."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(0),       # total lookups
                _mock_execute_result([]),      # per-org revenue
            ]
        )

        with patch(
            "app.modules.admin.service.get_carjam_per_lookup_cost",
            new_callable=AsyncMock,
            return_value=0.15,
        ):
            result = await get_carjam_cost_report(db)

        assert result["total_lookups"] == 0
        assert result["total_cost_nzd"] == 0.0
        assert result["total_revenue_nzd"] == 0.0
        assert result["net_nzd"] == 0.0

    @pytest.mark.asyncio
    async def test_cost_report_with_overage(self):
        """Overage lookups generate revenue."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(80),       # total lookups
                _mock_execute_result([
                    (80, 50),  # org with 80 lookups, 50 included
                ]),
            ]
        )

        with patch(
            "app.modules.admin.service.get_carjam_per_lookup_cost",
            new_callable=AsyncMock,
            return_value=0.15,
        ):
            result = await get_carjam_cost_report(db)

        assert result["total_lookups"] == 80
        assert result["total_cost_nzd"] == round(80 * 0.15, 2)
        # Overage = 80 - 50 = 30 lookups
        assert result["total_revenue_nzd"] == round(30 * 0.15, 2)

    @pytest.mark.asyncio
    async def test_cost_report_no_overage(self):
        """No overage means zero revenue but still has cost."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(50),       # total lookups
                _mock_execute_result([
                    (50, 200),  # org with 50 lookups, 200 included
                ]),
            ]
        )

        with patch(
            "app.modules.admin.service.get_carjam_per_lookup_cost",
            new_callable=AsyncMock,
            return_value=0.15,
        ):
            result = await get_carjam_cost_report(db)

        assert result["total_lookups"] == 50
        assert result["total_cost_nzd"] == round(50 * 0.15, 2)
        assert result["total_revenue_nzd"] == 0.0

    @pytest.mark.asyncio
    async def test_cost_report_net_calculation(self):
        """Net = revenue - cost."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(100),
                _mock_execute_result([
                    (60, 50),   # 10 overage
                    (40, 100),  # 0 overage
                ]),
            ]
        )

        with patch(
            "app.modules.admin.service.get_carjam_per_lookup_cost",
            new_callable=AsyncMock,
            return_value=0.15,
        ):
            result = await get_carjam_cost_report(db)

        expected_cost = round(100 * 0.15, 2)
        expected_revenue = round(10 * 0.15, 2)
        assert result["net_nzd"] == round(expected_revenue - expected_cost, 2)


# ---------------------------------------------------------------------------
# Churn Report — Requirement 46.5
# ---------------------------------------------------------------------------


class TestChurnReport:
    """Tests for get_churn_report."""

    @pytest.mark.asyncio
    async def test_churn_empty(self):
        """No churned orgs returns empty list."""
        db = _mock_db()
        db.execute = AsyncMock(return_value=_mock_execute_result([]))

        result = await get_churn_report(db)
        assert result["total"] == 0
        assert result["churned_organisations"] == []

    @pytest.mark.asyncio
    async def test_churn_includes_suspended(self):
        """Suspended orgs appear in churn report."""
        db = _mock_db()
        plan = _make_plan(name="Pro")
        org = _make_org(plan, name="Suspended Shop", status="suspended")

        db.execute = AsyncMock(
            return_value=_mock_execute_result([(org, "Pro")])
        )

        result = await get_churn_report(db)
        assert result["total"] == 1
        assert result["churned_organisations"][0]["status"] == "suspended"
        assert result["churned_organisations"][0]["plan_name"] == "Pro"

    @pytest.mark.asyncio
    async def test_churn_includes_deleted(self):
        """Deleted orgs appear in churn report."""
        db = _mock_db()
        plan = _make_plan()
        org = _make_org(plan, name="Deleted Shop", status="deleted")

        db.execute = AsyncMock(
            return_value=_mock_execute_result([(org, "Starter")])
        )

        result = await get_churn_report(db)
        assert result["total"] == 1
        assert result["churned_organisations"][0]["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_churn_duration_calculation(self):
        """Subscription duration is calculated correctly."""
        db = _mock_db()
        plan = _make_plan()
        created = datetime.now(timezone.utc) - timedelta(days=90)
        updated = datetime.now(timezone.utc)
        org = _make_org(
            plan, name="Old Shop", status="suspended",
            created_at=created, updated_at=updated,
        )

        db.execute = AsyncMock(
            return_value=_mock_execute_result([(org, "Starter")])
        )

        result = await get_churn_report(db)
        assert result["total"] == 1
        duration = result["churned_organisations"][0]["subscription_duration_days"]
        assert duration == 90


# ---------------------------------------------------------------------------
# Vehicle DB Stats — Requirement 46.4
# ---------------------------------------------------------------------------


class TestVehicleDbStats:
    """Tests for get_vehicle_db_stats."""

    @pytest.mark.asyncio
    async def test_stats_empty(self):
        """Empty DB returns zero stats."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(0),  # total records
                _mock_scalar_result(0),  # total lookups
            ]
        )

        result = await get_vehicle_db_stats(db)
        assert result["total_records"] == 0
        assert result["total_lookups_all_orgs"] == 0
        assert result["cache_hit_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_with_records_and_lookups(self):
        """Stats reflect actual vehicle records and lookups."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(100),  # total records
                _mock_scalar_result(50),   # total lookups
            ]
        )

        result = await get_vehicle_db_stats(db)
        assert result["total_records"] == 100
        assert result["total_lookups_all_orgs"] == 50
        assert 0.0 <= result["cache_hit_rate"] <= 1.0

    @pytest.mark.asyncio
    async def test_stats_cache_hit_rate_zero_lookups(self):
        """Cache hit rate is 0 when no lookups."""
        db = _mock_db()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(50),  # records exist
                _mock_scalar_result(0),   # no lookups
            ]
        )

        result = await get_vehicle_db_stats(db)
        assert result["cache_hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# Schema Validation
# ---------------------------------------------------------------------------


class TestReportSchemas:
    """Validate Pydantic schemas for report responses."""

    def test_mrr_report_response(self):
        resp = MrrReportResponse(
            total_mrr_nzd=198.0,
            plan_breakdown=[
                MrrPlanBreakdown(
                    plan_id=str(uuid.uuid4()),
                    plan_name="Pro",
                    active_orgs=2,
                    mrr_nzd=198.0,
                )
            ],
            month_over_month=[
                MrrMonthTrend(month="2024-01", mrr_nzd=198.0),
            ],
        )
        assert resp.total_mrr_nzd == 198.0

    def test_org_overview_response(self):
        resp = OrgOverviewResponse(
            organisations=[
                OrgOverviewRow(
                    organisation_id=str(uuid.uuid4()),
                    organisation_name="Test",
                    plan_name="Starter",
                    signup_date=datetime.now(timezone.utc),
                    trial_status="active",
                    billing_status="active",
                    storage_used_bytes=0,
                    storage_quota_gb=10,
                    carjam_lookups_this_month=0,
                )
            ],
            total=1,
        )
        assert resp.total == 1

    def test_carjam_cost_response(self):
        resp = CarjamCostReportResponse(
            total_lookups=100,
            total_cost_nzd=15.0,
            total_revenue_nzd=4.5,
            net_nzd=-10.5,
            per_lookup_cost_nzd=0.15,
        )
        assert resp.net_nzd == -10.5

    def test_churn_report_response(self):
        resp = ChurnReportResponse(
            churned_organisations=[
                ChurnOrgRow(
                    organisation_id=str(uuid.uuid4()),
                    organisation_name="Gone Shop",
                    plan_name="Basic",
                    status="suspended",
                    signup_date=datetime.now(timezone.utc),
                    churned_at=datetime.now(timezone.utc),
                    subscription_duration_days=90,
                )
            ],
            total=1,
        )
        assert resp.total == 1

    def test_vehicle_db_stats_response(self):
        resp = VehicleDbStatsResponse(
            total_records=500,
            total_lookups_all_orgs=200,
            cache_hit_rate=0.714,
        )
        assert resp.total_records == 500
