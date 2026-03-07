"""Unit tests for Task 16.1 — subscription plan management.

Tests cover:
  - Schema validation for PlanCreateRequest, PlanUpdateRequest, PlanResponse
  - Service functions: create_plan, list_plans, get_plan, update_plan, archive_plan
  - Duplicate name prevention, archived plan edit rejection, archive idempotency
  - Storage tier pricing configuration
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401

from app.modules.admin.models import SubscriptionPlan
from app.modules.admin.schemas import (
    PlanCreateRequest,
    PlanListResponse,
    PlanResponse,
    PlanUpdateRequest,
    StorageTierPricing,
)
from app.modules.admin.service import (
    archive_plan,
    create_plan,
    get_plan,
    list_plans,
    update_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan_model(
    plan_id=None,
    name="Starter",
    monthly_price_nzd=49.00,
    user_seats=5,
    storage_quota_gb=5,
    carjam_lookups_included=100,
    enabled_modules=None,
    is_public=True,
    is_archived=False,
    storage_tier_pricing=None,
):
    """Create a mock SubscriptionPlan ORM object."""
    plan = MagicMock(spec=SubscriptionPlan)
    plan.id = plan_id or uuid.uuid4()
    plan.name = name
    plan.monthly_price_nzd = monthly_price_nzd
    plan.user_seats = user_seats
    plan.storage_quota_gb = storage_quota_gb
    plan.carjam_lookups_included = carjam_lookups_included
    plan.enabled_modules = enabled_modules or []
    plan.is_public = is_public
    plan.is_archived = is_archived
    plan.storage_tier_pricing = storage_tier_pricing or []
    plan.created_at = datetime.now(timezone.utc)
    plan.updated_at = datetime.now(timezone.utc)
    return plan


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    """Create a mock result that returns values from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPlanSchemas:
    """Test Pydantic schema validation for plan management."""

    def test_create_request_valid(self):
        req = PlanCreateRequest(
            name="Pro",
            monthly_price_nzd=99.00,
            user_seats=10,
            storage_quota_gb=20,
            carjam_lookups_included=500,
            enabled_modules=["invoices", "payments"],
            is_public=True,
        )
        assert req.name == "Pro"
        assert req.monthly_price_nzd == 99.00
        assert req.user_seats == 10
        assert req.storage_tier_pricing == []

    def test_create_request_with_storage_tiers(self):
        req = PlanCreateRequest(
            name="Enterprise",
            monthly_price_nzd=199.00,
            user_seats=50,
            storage_quota_gb=100,
            carjam_lookups_included=2000,
            storage_tier_pricing=[
                StorageTierPricing(tier_name="10 GB", size_gb=10, price_nzd_per_month=5.00),
                StorageTierPricing(tier_name="50 GB", size_gb=50, price_nzd_per_month=20.00),
            ],
        )
        assert len(req.storage_tier_pricing) == 2
        assert req.storage_tier_pricing[0].tier_name == "10 GB"

    def test_create_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            PlanCreateRequest(
                name="",
                monthly_price_nzd=49.00,
                user_seats=5,
                storage_quota_gb=5,
                carjam_lookups_included=100,
            )

    def test_create_request_zero_seats_rejected(self):
        with pytest.raises(Exception):
            PlanCreateRequest(
                name="Bad",
                monthly_price_nzd=49.00,
                user_seats=0,
                storage_quota_gb=5,
                carjam_lookups_included=100,
            )

    def test_create_request_negative_price_rejected(self):
        with pytest.raises(Exception):
            PlanCreateRequest(
                name="Bad",
                monthly_price_nzd=-10.00,
                user_seats=5,
                storage_quota_gb=5,
                carjam_lookups_included=100,
            )

    def test_update_request_all_optional(self):
        req = PlanUpdateRequest()
        assert req.name is None
        assert req.monthly_price_nzd is None
        assert req.user_seats is None

    def test_update_request_partial(self):
        req = PlanUpdateRequest(name="Updated", monthly_price_nzd=79.00)
        assert req.name == "Updated"
        assert req.monthly_price_nzd == 79.00
        assert req.storage_quota_gb is None

    def test_plan_response_model(self):
        now = datetime.now(timezone.utc)
        resp = PlanResponse(
            id=str(uuid.uuid4()),
            name="Starter",
            monthly_price_nzd=49.00,
            user_seats=5,
            storage_quota_gb=5,
            carjam_lookups_included=100,
            enabled_modules=["invoices"],
            is_public=True,
            is_archived=False,
            storage_tier_pricing=[],
            created_at=now,
            updated_at=now,
        )
        assert resp.name == "Starter"
        assert resp.is_archived is False

    def test_plan_list_response(self):
        now = datetime.now(timezone.utc)
        plan = PlanResponse(
            id=str(uuid.uuid4()),
            name="Starter",
            monthly_price_nzd=49.00,
            user_seats=5,
            storage_quota_gb=5,
            carjam_lookups_included=100,
            enabled_modules=[],
            is_public=True,
            is_archived=False,
            storage_tier_pricing=[],
            created_at=now,
            updated_at=now,
        )
        resp = PlanListResponse(plans=[plan], total=1)
        assert resp.total == 1
        assert len(resp.plans) == 1


# ---------------------------------------------------------------------------
# Service tests — create_plan
# ---------------------------------------------------------------------------

class TestCreatePlan:
    """Test create_plan service function."""

    @pytest.mark.asyncio
    async def test_successful_creation(self):
        db = _mock_db_session()
        # No duplicate name
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            result = await create_plan(
                db,
                name="Pro",
                monthly_price_nzd=99.00,
                user_seats=10,
                storage_quota_gb=20,
                carjam_lookups_included=500,
                enabled_modules=["invoices", "payments"],
                is_public=True,
                storage_tier_pricing=[{"tier_name": "10 GB", "size_gb": 10, "price_nzd_per_month": 5.0}],
            )

        assert result["name"] == "Pro"
        assert result["monthly_price_nzd"] == 99.00
        assert result["user_seats"] == 10
        assert result["is_archived"] is False
        assert len(result["storage_tier_pricing"]) == 1
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_name_rejected(self):
        db = _mock_db_session()
        existing_plan = _make_plan_model(name="Pro")
        db.execute = AsyncMock(return_value=_mock_scalar_result(existing_plan))

        with pytest.raises(ValueError, match="already exists"):
            await create_plan(
                db,
                name="Pro",
                monthly_price_nzd=99.00,
                user_seats=10,
                storage_quota_gb=20,
                carjam_lookups_included=500,
                enabled_modules=[],
            )

    @pytest.mark.asyncio
    async def test_private_plan_creation(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            result = await create_plan(
                db,
                name="Private Plan",
                monthly_price_nzd=149.00,
                user_seats=20,
                storage_quota_gb=50,
                carjam_lookups_included=1000,
                enabled_modules=["invoices"],
                is_public=False,
            )

        assert result["is_public"] is False


# ---------------------------------------------------------------------------
# Service tests — list_plans
# ---------------------------------------------------------------------------

class TestListPlans:
    """Test list_plans service function."""

    @pytest.mark.asyncio
    async def test_list_excludes_archived_by_default(self):
        db = _mock_db_session()
        active_plan = _make_plan_model(name="Active")
        db.execute = AsyncMock(return_value=_mock_scalars_result([active_plan]))

        result = await list_plans(db)

        assert len(result) == 1
        assert result[0]["name"] == "Active"

    @pytest.mark.asyncio
    async def test_list_includes_archived_when_requested(self):
        db = _mock_db_session()
        plans = [
            _make_plan_model(name="Active"),
            _make_plan_model(name="Old", is_archived=True),
        ]
        db.execute = AsyncMock(return_value=_mock_scalars_result(plans))

        result = await list_plans(db, include_archived=True)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await list_plans(db)

        assert result == []


# ---------------------------------------------------------------------------
# Service tests — get_plan
# ---------------------------------------------------------------------------

class TestGetPlan:
    """Test get_plan service function."""

    @pytest.mark.asyncio
    async def test_get_existing_plan(self):
        db = _mock_db_session()
        plan = _make_plan_model(name="Starter")
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        result = await get_plan(db, plan.id)

        assert result is not None
        assert result["name"] == "Starter"

    @pytest.mark.asyncio
    async def test_get_nonexistent_plan(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        result = await get_plan(db, uuid.uuid4())

        assert result is None


# ---------------------------------------------------------------------------
# Service tests — update_plan
# ---------------------------------------------------------------------------

class TestUpdatePlan:
    """Test update_plan service function."""

    @pytest.mark.asyncio
    async def test_successful_update(self):
        db = _mock_db_session()
        plan = _make_plan_model(name="Starter", monthly_price_nzd=49.00)
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            result = await update_plan(
                db,
                plan.id,
                updates={"monthly_price_nzd": 59.00},
            )

        assert result["monthly_price_nzd"] == 59.00

    @pytest.mark.asyncio
    async def test_update_nonexistent_plan(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="not found"):
            await update_plan(db, uuid.uuid4(), updates={"name": "New"})

    @pytest.mark.asyncio
    async def test_update_archived_plan_rejected(self):
        db = _mock_db_session()
        plan = _make_plan_model(is_archived=True)
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with pytest.raises(ValueError, match="archived"):
            await update_plan(db, plan.id, updates={"name": "New"})

    @pytest.mark.asyncio
    async def test_update_no_valid_fields(self):
        db = _mock_db_session()
        plan = _make_plan_model()
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with pytest.raises(ValueError, match="No valid fields"):
            await update_plan(db, plan.id, updates={})

    @pytest.mark.asyncio
    async def test_update_storage_tier_pricing(self):
        db = _mock_db_session()
        plan = _make_plan_model(storage_tier_pricing=[])
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        new_tiers = [{"tier_name": "10 GB", "size_gb": 10, "price_nzd_per_month": 5.0}]

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            result = await update_plan(
                db,
                plan.id,
                updates={"storage_tier_pricing": new_tiers},
            )

        assert result["storage_tier_pricing"] == new_tiers

    @pytest.mark.asyncio
    async def test_update_duplicate_name_rejected(self):
        db = _mock_db_session()
        plan = _make_plan_model(name="Starter")
        other_plan = _make_plan_model(name="Pro")

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalar_result(plan)
            return _mock_scalar_result(other_plan)

        db.execute = mock_execute

        with pytest.raises(ValueError, match="already exists"):
            await update_plan(db, plan.id, updates={"name": "Pro"})


# ---------------------------------------------------------------------------
# Service tests — archive_plan
# ---------------------------------------------------------------------------

class TestArchivePlan:
    """Test archive_plan service function."""

    @pytest.mark.asyncio
    async def test_successful_archive(self):
        db = _mock_db_session()
        plan = _make_plan_model(is_archived=False)
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock):
            result = await archive_plan(db, plan.id)

        assert result["is_archived"] is True

    @pytest.mark.asyncio
    async def test_archive_nonexistent_plan(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="not found"):
            await archive_plan(db, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_archive_already_archived(self):
        db = _mock_db_session()
        plan = _make_plan_model(is_archived=True)
        db.execute = AsyncMock(return_value=_mock_scalar_result(plan))

        with pytest.raises(ValueError, match="already archived"):
            await archive_plan(db, plan.id)
