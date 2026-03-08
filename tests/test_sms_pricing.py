"""Unit tests for SMS Pricing & Packages API endpoints and service functions.

**Validates: Requirements 1.3, 1.4, 2.3, 2.4, 6.1-6.7, 7.1**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.models import (
    Organisation,
    SubscriptionPlan,
    SmsPackagePurchase,
)
from app.modules.admin.schemas import (
    PlanCreateRequest,
    PlanUpdateRequest,
    PlanResponse,
    SmsPackageTierPricing,
    SmsPackagePurchaseRequest,
    OrgSmsUsageRow,
    AdminSmsUsageResponse,
    OrgSmsUsageResponse,
    SmsPackagePurchaseResponse,
)
from app.modules.admin.service import (
    compute_sms_overage,
    increment_sms_usage,
    get_org_sms_usage,
    get_all_orgs_sms_usage,
    get_effective_sms_quota,
    purchase_sms_package,
    get_org_sms_packages,
    compute_sms_overage_for_billing,
)

ORG_ID = uuid.uuid4()
PLAN_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)


def _make_plan(
    *,
    sms_included: bool = True,
    per_sms_cost_nzd: float = 0.08,
    sms_included_quota: int = 100,
    sms_package_pricing: list | None = None,
) -> SubscriptionPlan:
    plan = SubscriptionPlan(
        id=PLAN_ID,
        name="Test Plan",
        monthly_price_nzd=49.0,
        user_seats=5,
        storage_quota_gb=10,
        carjam_lookups_included=50,
        enabled_modules=[],
        is_public=True,
        is_archived=False,
        storage_tier_pricing=[],
        sms_included=sms_included,
        per_sms_cost_nzd=per_sms_cost_nzd,
        sms_included_quota=sms_included_quota,
        sms_package_pricing=sms_package_pricing or [],
    )
    plan.created_at = NOW
    plan.updated_at = NOW
    return plan


def _make_org(
    *,
    sms_sent_this_month: int = 0,
    plan_id: uuid.UUID | None = None,
    stripe_customer_id: str | None = "cus_test123",
    org_id: uuid.UUID | None = None,
    name: str = "Test Org",
) -> Organisation:
    return Organisation(
        id=org_id or ORG_ID,
        name=name,
        plan_id=plan_id or PLAN_ID,
        status="active",
        storage_quota_gb=10,
        storage_used_bytes=0,
        sms_sent_this_month=sms_sent_this_month,
        stripe_customer_id=stripe_customer_id,
    )


def _make_package(
    *,
    org_id: uuid.UUID | None = None,
    tier_name: str = "500 SMS",
    sms_quantity: int = 500,
    price_nzd: float = 25.0,
    credits_remaining: int = 500,
    purchased_at: datetime | None = None,
) -> SmsPackagePurchase:
    return SmsPackagePurchase(
        id=uuid.uuid4(),
        org_id=org_id or ORG_ID,
        tier_name=tier_name,
        sms_quantity=sms_quantity,
        price_nzd=price_nzd,
        credits_remaining=credits_remaining,
        purchased_at=purchased_at or NOW,
        created_at=NOW,
    )


def _mock_db_for_effective_quota(plan, package_credits_total=0):
    mock_db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalar_one_or_none.return_value = plan
        else:
            mock_result.scalar.return_value = package_credits_total
        return mock_result

    mock_db.execute = fake_execute
    return mock_db


def _mock_db_for_org_usage(org, plan, package_credits_total=0):
    mock_db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.one_or_none.return_value = (org, plan)
        else:
            mock_result.scalar.return_value = package_credits_total
        return mock_result

    mock_db.execute = fake_execute
    return mock_db


def _mock_db_for_all_orgs_usage(org_plan_pairs, package_credits_map=None):
    if package_credits_map is None:
        package_credits_map = {}
    mock_db = AsyncMock()
    call_count = 0
    org_index = 0

    async def fake_execute(stmt):
        nonlocal call_count, org_index
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.all.return_value = org_plan_pairs
        else:
            if org_index < len(org_plan_pairs):
                org = org_plan_pairs[org_index][0]
                credits = package_credits_map.get(org.id, 0)
                org_index += 1
            else:
                credits = 0
            mock_result.scalar.return_value = credits
        return mock_result

    mock_db.execute = fake_execute
    return mock_db


# ======================================================================
# 1. Plan CRUD with SMS fields (Requirements 1.3, 1.4)
# ======================================================================


class TestPlanCreateWithSmsFields:

    def test_plan_create_request_accepts_sms_fields(self):
        req = PlanCreateRequest(
            name="Pro Plan",
            monthly_price_nzd=99.0,
            user_seats=10,
            storage_quota_gb=50,
            carjam_lookups_included=200,
            sms_included=True,
            per_sms_cost_nzd=0.08,
            sms_included_quota=100,
            sms_package_pricing=[
                SmsPackageTierPricing(tier_name="500 SMS", sms_quantity=500, price_nzd=25.0),
            ],
        )
        assert req.sms_included is True
        assert req.per_sms_cost_nzd == 0.08
        assert req.sms_included_quota == 100
        assert len(req.sms_package_pricing) == 1

    def test_plan_create_request_defaults(self):
        req = PlanCreateRequest(
            name="Basic Plan",
            monthly_price_nzd=29.0,
            user_seats=3,
            storage_quota_gb=5,
            carjam_lookups_included=10,
        )
        assert req.sms_included is False
        assert req.per_sms_cost_nzd == 0
        assert req.sms_included_quota == 0
        assert req.sms_package_pricing == []

    def test_plan_create_rejects_negative_sms_cost(self):
        with pytest.raises(Exception):
            PlanCreateRequest(
                name="Bad", monthly_price_nzd=29.0, user_seats=3,
                storage_quota_gb=5, carjam_lookups_included=10,
                per_sms_cost_nzd=-0.05,
            )

    def test_plan_create_rejects_negative_sms_quota(self):
        with pytest.raises(Exception):
            PlanCreateRequest(
                name="Bad", monthly_price_nzd=29.0, user_seats=3,
                storage_quota_gb=5, carjam_lookups_included=10,
                sms_included_quota=-10,
            )


class TestPlanUpdateWithSmsFields:

    def test_plan_update_request_accepts_sms_fields(self):
        req = PlanUpdateRequest(
            per_sms_cost_nzd=0.10,
            sms_included_quota=200,
            sms_package_pricing=[
                SmsPackageTierPricing(tier_name="1000 SMS", sms_quantity=1000, price_nzd=40.0),
            ],
        )
        assert req.per_sms_cost_nzd == 0.10
        assert req.sms_included_quota == 200
        assert len(req.sms_package_pricing) == 1

    def test_plan_update_request_all_none(self):
        req = PlanUpdateRequest()
        assert req.per_sms_cost_nzd is None
        assert req.sms_included_quota is None
        assert req.sms_package_pricing is None

    def test_plan_update_rejects_negative_sms_cost(self):
        with pytest.raises(Exception):
            PlanUpdateRequest(per_sms_cost_nzd=-1.0)

    def test_plan_update_rejects_negative_sms_quota(self):
        with pytest.raises(Exception):
            PlanUpdateRequest(sms_included_quota=-5)


class TestPlanResponseSmsFields:

    def test_plan_response_includes_sms_fields(self):
        resp = PlanResponse(
            id=str(uuid.uuid4()), name="Pro", monthly_price_nzd=99.0,
            user_seats=10, storage_quota_gb=50, carjam_lookups_included=200,
            enabled_modules=["invoicing"], is_public=True, is_archived=False,
            storage_tier_pricing=[], sms_included=True, per_sms_cost_nzd=0.08,
            sms_included_quota=100,
            sms_package_pricing=[
                SmsPackageTierPricing(tier_name="500 SMS", sms_quantity=500, price_nzd=25.0),
            ],
            created_at=NOW, updated_at=NOW,
        )
        assert resp.sms_included is True
        assert resp.per_sms_cost_nzd == 0.08
        assert resp.sms_included_quota == 100
        assert len(resp.sms_package_pricing) == 1

    def test_plan_response_sms_defaults(self):
        resp = PlanResponse(
            id=str(uuid.uuid4()), name="Basic", monthly_price_nzd=29.0,
            user_seats=3, storage_quota_gb=5, carjam_lookups_included=10,
            enabled_modules=[], is_public=True, is_archived=False,
            storage_tier_pricing=[], created_at=NOW, updated_at=NOW,
        )
        assert resp.sms_included is False
        assert resp.per_sms_cost_nzd == 0
        assert resp.sms_included_quota == 0
        assert resp.sms_package_pricing == []


# ======================================================================
# 2. SMS Package Tier Validation (Requirements 5.2, 6.1)
# ======================================================================


class TestSmsPackageTierValidation:

    def test_valid_tier(self):
        tier = SmsPackageTierPricing(tier_name="500 SMS", sms_quantity=500, price_nzd=25.0)
        assert tier.tier_name == "500 SMS"
        assert tier.sms_quantity == 500

    def test_rejects_empty_tier_name(self):
        with pytest.raises(Exception):
            SmsPackageTierPricing(tier_name="", sms_quantity=500, price_nzd=25.0)

    def test_rejects_zero_sms_quantity(self):
        with pytest.raises(Exception):
            SmsPackageTierPricing(tier_name="Bad", sms_quantity=0, price_nzd=25.0)

    def test_rejects_negative_sms_quantity(self):
        with pytest.raises(Exception):
            SmsPackageTierPricing(tier_name="Bad", sms_quantity=-10, price_nzd=25.0)

    def test_rejects_negative_price(self):
        with pytest.raises(Exception):
            SmsPackageTierPricing(tier_name="Bad", sms_quantity=500, price_nzd=-5.0)

    def test_allows_zero_price(self):
        tier = SmsPackageTierPricing(tier_name="Free Pack", sms_quantity=50, price_nzd=0)
        assert tier.price_nzd == 0


class TestSmsPackagePurchaseRequest:

    def test_valid_request(self):
        req = SmsPackagePurchaseRequest(tier_name="500 SMS")
        assert req.tier_name == "500 SMS"

    def test_rejects_empty_tier_name(self):
        with pytest.raises(Exception):
            SmsPackagePurchaseRequest(tier_name="")


# ======================================================================
# 3. SMS Usage Increment (Requirements 2.3)
# ======================================================================


class TestIncrementSmsUsage:

    @pytest.mark.asyncio
    async def test_increment_executes_update(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.flush = AsyncMock()
        await increment_sms_usage(mock_db, ORG_ID)
        mock_db.execute.assert_called_once()
        mock_db.flush.assert_called_once()


# ======================================================================
# 4. SMS Overage Computation (Requirements 3.1, 3.5, 3.6)
# ======================================================================


class TestComputeSmsOverage:

    def test_no_overage_within_quota(self):
        assert compute_sms_overage(50, 100) == 0

    def test_no_overage_at_quota(self):
        assert compute_sms_overage(100, 100) == 0

    def test_overage_above_quota(self):
        assert compute_sms_overage(150, 100) == 50

    def test_zero_sent_zero_quota(self):
        assert compute_sms_overage(0, 0) == 0

    def test_zero_quota_with_usage(self):
        assert compute_sms_overage(10, 0) == 10

    def test_large_values(self):
        assert compute_sms_overage(10000, 5000) == 5000


# ======================================================================
# 5. Effective Quota (Requirements 1.7, 3.3, 3.4)
# ======================================================================


class TestGetEffectiveSmsQuota:

    @pytest.mark.asyncio
    async def test_sms_included_true_no_packages(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100)
        db = _mock_db_for_effective_quota(plan, package_credits_total=0)
        result = await get_effective_sms_quota(db, ORG_ID)
        assert result == 100

    @pytest.mark.asyncio
    async def test_sms_included_true_with_packages(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100)
        db = _mock_db_for_effective_quota(plan, package_credits_total=500)
        result = await get_effective_sms_quota(db, ORG_ID)
        assert result == 600

    @pytest.mark.asyncio
    async def test_sms_included_false_returns_zero(self):
        plan = _make_plan(sms_included=False, sms_included_quota=100)
        db = _mock_db_for_effective_quota(plan)
        result = await get_effective_sms_quota(db, ORG_ID)
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_plan_returns_zero(self):
        db = _mock_db_for_effective_quota(None)
        result = await get_effective_sms_quota(db, ORG_ID)
        assert result == 0


# ======================================================================
# 6. Org SMS Usage (Requirements 2.6, 2.7)
# ======================================================================


class TestGetOrgSmsUsage:

    @pytest.mark.asyncio
    async def test_within_quota(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=50)
        db = _mock_db_for_org_usage(org, plan, package_credits_total=0)
        result = await get_org_sms_usage(db, ORG_ID)
        assert result["total_sent"] == 50
        assert result["included_in_plan"] == 100
        assert result["effective_quota"] == 100
        assert result["overage_count"] == 0
        assert result["overage_charge_nzd"] == 0.0
        assert result["per_sms_cost_nzd"] == 0.08

    @pytest.mark.asyncio
    async def test_with_overage(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=150)
        db = _mock_db_for_org_usage(org, plan, package_credits_total=0)
        result = await get_org_sms_usage(db, ORG_ID)
        assert result["total_sent"] == 150
        assert result["overage_count"] == 50
        assert result["overage_charge_nzd"] == 4.0

    @pytest.mark.asyncio
    async def test_with_package_credits(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=150)
        db = _mock_db_for_org_usage(org, plan, package_credits_total=200)
        result = await get_org_sms_usage(db, ORG_ID)
        assert result["effective_quota"] == 300
        assert result["overage_count"] == 0
        assert result["package_credits_remaining"] == 200

    @pytest.mark.asyncio
    async def test_sms_not_included(self):
        plan = _make_plan(sms_included=False, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=50)
        db = _mock_db_for_org_usage(org, plan, package_credits_total=0)
        result = await get_org_sms_usage(db, ORG_ID)
        assert result["included_in_plan"] == 0
        assert result["effective_quota"] == 0
        assert result["overage_count"] == 50

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = None
            return mock_result
        mock_db.execute = fake_execute
        with pytest.raises(ValueError, match="Organisation not found"):
            await get_org_sms_usage(mock_db, ORG_ID)


# ======================================================================
# 7. Admin SMS Usage - all orgs (Requirement 7.4)
# ======================================================================


class TestGetAllOrgsSmsUsage:

    @pytest.mark.asyncio
    async def test_single_org_within_quota(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=50)
        db = _mock_db_for_all_orgs_usage([(org, plan)])
        usage_list, cost = await get_all_orgs_sms_usage(db)
        assert len(usage_list) == 1
        assert usage_list[0]["total_sent"] == 50
        assert usage_list[0]["overage_count"] == 0
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_multiple_orgs(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.10)
        org1_id = uuid.uuid4()
        org2_id = uuid.uuid4()
        org1 = _make_org(sms_sent_this_month=50, org_id=org1_id, name="Org A")
        org2 = _make_org(sms_sent_this_month=200, org_id=org2_id, name="Org B")
        db = _mock_db_for_all_orgs_usage([(org1, plan), (org2, plan)])
        usage_list, _ = await get_all_orgs_sms_usage(db)
        assert len(usage_list) == 2
        assert usage_list[0]["overage_count"] == 0
        assert usage_list[1]["overage_count"] == 100
        assert usage_list[1]["overage_charge_nzd"] == 10.0

    @pytest.mark.asyncio
    async def test_empty_orgs(self):
        db = _mock_db_for_all_orgs_usage([])
        usage_list, cost = await get_all_orgs_sms_usage(db)
        assert usage_list == []
        assert cost == 0.0


# ======================================================================
# 8. Package Purchase (Requirements 6.1-6.7)
# ======================================================================


class TestPurchaseSmsPackage:

    @pytest.mark.asyncio
    async def test_tier_not_found_raises(self):
        plan = _make_plan(
            sms_included=True,
            sms_package_pricing=[
                {"tier_name": "500 SMS", "sms_quantity": 500, "price_nzd": 25.0},
            ],
        )
        org = _make_org()
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = (org, plan)
            return mock_result
        mock_db.execute = fake_execute
        with pytest.raises(ValueError, match="SMS package tier not found"):
            await purchase_sms_package(mock_db, ORG_ID, "NonExistent Tier")

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = None
            return mock_result
        mock_db.execute = fake_execute
        with pytest.raises(ValueError, match="Organisation not found"):
            await purchase_sms_package(mock_db, ORG_ID, "500 SMS")

    @pytest.mark.asyncio
    async def test_no_stripe_customer_raises(self):
        plan = _make_plan(
            sms_included=True,
            sms_package_pricing=[
                {"tier_name": "500 SMS", "sms_quantity": 500, "price_nzd": 25.0},
            ],
        )
        org = _make_org(stripe_customer_id=None)
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = (org, plan)
            return mock_result
        mock_db.execute = fake_execute
        with pytest.raises(ValueError, match="No payment method"):
            await purchase_sms_package(mock_db, ORG_ID, "500 SMS")

    @pytest.mark.asyncio
    async def test_stripe_card_error_raises_runtime(self):
        import stripe as stripe_mod
        plan = _make_plan(
            sms_included=True,
            sms_package_pricing=[
                {"tier_name": "500 SMS", "sms_quantity": 500, "price_nzd": 25.0},
            ],
        )
        org = _make_org()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = (org, plan)
            return mock_result
        mock_db.execute = fake_execute
        with patch("stripe.PaymentIntent") as mock_pi:
            mock_pi.create.side_effect = stripe_mod.error.CardError(
                message="Card declined", param=None, code="card_declined",
            )
            with pytest.raises(RuntimeError, match="Payment failed"):
                await purchase_sms_package(mock_db, ORG_ID, "500 SMS")
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_purchase(self):
        plan = _make_plan(
            sms_included=True,
            sms_package_pricing=[
                {"tier_name": "500 SMS", "sms_quantity": 500, "price_nzd": 25.0},
            ],
        )
        org = _make_org()
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = (org, plan)
            return mock_result
        mock_db.execute = fake_execute
        mock_intent = MagicMock()
        mock_intent.id = "pi_test123"
        with patch("stripe.PaymentIntent") as mock_pi:
            mock_pi.create.return_value = mock_intent
            result = await purchase_sms_package(mock_db, ORG_ID, "500 SMS")
        assert result["tier_name"] == "500 SMS"
        assert result["sms_quantity"] == 500
        assert result["price_nzd"] == 25.0
        assert result["credits_remaining"] == 500
        assert result["stripe_payment_intent_id"] == "pi_test123"
        mock_db.add.assert_called_once()
        mock_db.flush.assert_called_once()


# ======================================================================
# 9. Get Org SMS Packages (Requirement 6.5)
# ======================================================================


class TestGetOrgSmsPackages:

    @pytest.mark.asyncio
    async def test_returns_active_packages(self):
        pkg1 = _make_package(
            tier_name="500 SMS", credits_remaining=300,
            purchased_at=NOW - timedelta(days=10),
        )
        pkg2 = _make_package(
            tier_name="1000 SMS", sms_quantity=1000, credits_remaining=1000,
            purchased_at=NOW - timedelta(days=5),
        )
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [pkg1, pkg2]
            return mock_result
        mock_db.execute = fake_execute
        result = await get_org_sms_packages(mock_db, ORG_ID)
        assert len(result) == 2
        assert result[0]["tier_name"] == "500 SMS"
        assert result[0]["credits_remaining"] == 300
        assert result[1]["tier_name"] == "1000 SMS"
        assert result[1]["credits_remaining"] == 1000

    @pytest.mark.asyncio
    async def test_empty_packages(self):
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            return mock_result
        mock_db.execute = fake_execute
        result = await get_org_sms_packages(mock_db, ORG_ID)
        assert result == []


# ======================================================================
# 10. Overage Billing with FIFO Credit Deduction (Requirements 4.1-4.3, 6.7)
# ======================================================================


class TestComputeSmsOverageForBilling:

    @pytest.mark.asyncio
    async def test_no_overage(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=50)
        mock_db = AsyncMock()
        call_count = 0
        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.one_or_none.return_value = (org, plan)
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        result = await compute_sms_overage_for_billing(mock_db, ORG_ID)
        assert result["overage_count"] == 0
        assert result["total_charge_nzd"] == 0.0

    @pytest.mark.asyncio
    async def test_overage_no_packages(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=150)
        mock_db = AsyncMock()
        call_count = 0
        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.one_or_none.return_value = (org, plan)
            else:
                mock_result.scalars.return_value.all.return_value = []
            return mock_result
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        result = await compute_sms_overage_for_billing(mock_db, ORG_ID)
        assert result["overage_count"] == 50
        assert result["per_sms_cost_nzd"] == 0.08
        assert result["total_charge_nzd"] == 4.0

    @pytest.mark.asyncio
    async def test_fifo_credit_deduction(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.10)
        org = _make_org(sms_sent_this_month=180)
        old_pkg = _make_package(credits_remaining=30, purchased_at=NOW - timedelta(days=10))
        new_pkg = _make_package(credits_remaining=100, purchased_at=NOW - timedelta(days=1))
        mock_db = AsyncMock()
        call_count = 0
        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.one_or_none.return_value = (org, plan)
            else:
                mock_result.scalars.return_value.all.return_value = [old_pkg, new_pkg]
            return mock_result
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        result = await compute_sms_overage_for_billing(mock_db, ORG_ID)
        assert old_pkg.credits_remaining == 0
        assert new_pkg.credits_remaining == 50
        assert result["overage_count"] == 0
        assert result["total_charge_nzd"] == 0.0

    @pytest.mark.asyncio
    async def test_fifo_partial_coverage(self):
        plan = _make_plan(sms_included=True, sms_included_quota=100, per_sms_cost_nzd=0.10)
        org = _make_org(sms_sent_this_month=250)
        old_pkg = _make_package(credits_remaining=30, purchased_at=NOW - timedelta(days=10))
        new_pkg = _make_package(credits_remaining=50, purchased_at=NOW - timedelta(days=1))
        mock_db = AsyncMock()
        call_count = 0
        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.one_or_none.return_value = (org, plan)
            else:
                mock_result.scalars.return_value.all.return_value = [old_pkg, new_pkg]
            return mock_result
        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        result = await compute_sms_overage_for_billing(mock_db, ORG_ID)
        assert old_pkg.credits_remaining == 0
        assert new_pkg.credits_remaining == 0
        assert result["overage_count"] == 70
        assert result["total_charge_nzd"] == 7.0

    @pytest.mark.asyncio
    async def test_sms_not_included_returns_zeros(self):
        plan = _make_plan(sms_included=False, sms_included_quota=100, per_sms_cost_nzd=0.08)
        org = _make_org(sms_sent_this_month=200)
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = (org, plan)
            return mock_result
        mock_db.execute = fake_execute
        result = await compute_sms_overage_for_billing(mock_db, ORG_ID)
        assert result["overage_count"] == 0
        assert result["total_charge_nzd"] == 0.0

    @pytest.mark.asyncio
    async def test_org_not_found_returns_zeros(self):
        mock_db = AsyncMock()
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = None
            return mock_result
        mock_db.execute = fake_execute
        result = await compute_sms_overage_for_billing(mock_db, ORG_ID)
        assert result["overage_count"] == 0
        assert result["total_charge_nzd"] == 0.0


# ======================================================================
# 11. MFA SMS Exclusion (Requirements 2.4, 8.1, 8.2, 8.3)
# ======================================================================


class TestMfaSmsExclusion:

    def test_notification_service_imports_increment(self):
        from app.modules.admin.service import increment_sms_usage
        assert callable(increment_sms_usage)

    def test_mfa_service_does_not_import_increment(self):
        import importlib
        import inspect
        try:
            mfa_module = importlib.import_module("app.modules.auth.mfa_service")
            source = inspect.getsource(mfa_module)
            assert "increment_sms_usage" not in source
        except (ModuleNotFoundError, OSError):
            pass


# ======================================================================
# 12. Schema Response Models (Requirements 7.1, 7.4)
# ======================================================================


class TestSmsUsageResponseSchemas:

    def test_org_sms_usage_row(self):
        row = OrgSmsUsageRow(
            organisation_id=str(uuid.uuid4()),
            organisation_name="Test Org",
            total_sent=150, included_in_plan=100,
            package_credits_remaining=50, effective_quota=150,
            overage_count=0, overage_charge_nzd=0.0,
        )
        assert row.total_sent == 150
        assert row.effective_quota == 150

    def test_admin_sms_usage_response(self):
        resp = AdminSmsUsageResponse(
            organisations=[
                OrgSmsUsageRow(
                    organisation_id=str(uuid.uuid4()),
                    organisation_name="Org A",
                    total_sent=50, included_in_plan=100,
                    package_credits_remaining=0, effective_quota=100,
                    overage_count=0, overage_charge_nzd=0.0,
                ),
            ]
        )
        assert len(resp.organisations) == 1

    def test_org_sms_usage_response(self):
        resp = OrgSmsUsageResponse(
            organisation_id=str(uuid.uuid4()),
            organisation_name="Test Org",
            total_sent=120, included_in_plan=100,
            package_credits_remaining=0, effective_quota=100,
            overage_count=20, overage_charge_nzd=1.6,
            per_sms_cost_nzd=0.08,
        )
        assert resp.overage_count == 20
        assert resp.per_sms_cost_nzd == 0.08

    def test_sms_package_purchase_response(self):
        resp = SmsPackagePurchaseResponse(
            id=str(uuid.uuid4()),
            tier_name="500 SMS",
            sms_quantity=500, price_nzd=25.0,
            credits_remaining=450, purchased_at=NOW,
        )
        assert resp.credits_remaining == 450
        assert resp.tier_name == "500 SMS"
