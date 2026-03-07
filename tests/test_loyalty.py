"""Unit tests for the loyalty and memberships module.

Tests:
- 41.8: Paying invoice awards correct points based on earn rate
- 41.9: Tier discount auto-applied as separate line item

**Validates: Requirement 38 — Loyalty Module**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.loyalty.service import LoyaltyService


# ---------------------------------------------------------------------------
# Helpers — use MagicMock to avoid SQLAlchemy instrumentation issues
# ---------------------------------------------------------------------------

def _make_config(
    org_id: uuid.UUID,
    earn_rate: Decimal = Decimal("1.0"),
    redemption_rate: Decimal = Decimal("0.01"),
    is_active: bool = True,
) -> MagicMock:
    cfg = MagicMock()
    cfg.id = uuid.uuid4()
    cfg.org_id = org_id
    cfg.earn_rate = earn_rate
    cfg.redemption_rate = redemption_rate
    cfg.is_active = is_active
    return cfg


def _make_tier(
    org_id: uuid.UUID,
    name: str,
    threshold_points: int,
    discount_percent: Decimal = Decimal("0"),
) -> MagicMock:
    tier = MagicMock()
    tier.id = uuid.uuid4()
    tier.org_id = org_id
    tier.name = name
    tier.threshold_points = threshold_points
    tier.discount_percent = discount_percent
    tier.benefits = {}
    tier.display_order = 0
    return tier


# ---------------------------------------------------------------------------
# 41.8: Paying invoice awards correct points based on earn rate
# ---------------------------------------------------------------------------

class TestAwardPoints:
    """41.8: Paying invoice awards correct points based on earn rate."""

    @pytest.mark.asyncio
    async def test_awards_correct_points_default_rate(self) -> None:
        """1 point per $1 with default earn_rate=1.0."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        mock_db = MagicMock()
        # get_config returns active config
        config = _make_config(org_id, earn_rate=Decimal("1.0"))
        mock_result_config = MagicMock()
        mock_result_config.scalar_one_or_none.return_value = config

        # get_customer_balance returns 0
        mock_result_balance = MagicMock()
        mock_result_balance.scalar_one.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[mock_result_config, mock_result_balance])
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        svc = LoyaltyService(mock_db)
        txn = await svc.award_points(
            org_id, customer_id, Decimal("150.00"), invoice_id,
        )

        assert txn is not None
        assert txn.points == 150
        assert txn.transaction_type == "earn"
        assert txn.balance_after == 150
        assert txn.reference_type == "invoice"
        assert txn.reference_id == invoice_id

    @pytest.mark.asyncio
    async def test_awards_correct_points_custom_rate(self) -> None:
        """2 points per $1 with earn_rate=2.0."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        mock_db = MagicMock()
        config = _make_config(org_id, earn_rate=Decimal("2.0"))
        mock_result_config = MagicMock()
        mock_result_config.scalar_one_or_none.return_value = config
        mock_result_balance = MagicMock()
        mock_result_balance.scalar_one.return_value = 0

        mock_db.execute = AsyncMock(side_effect=[mock_result_config, mock_result_balance])
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        svc = LoyaltyService(mock_db)
        txn = await svc.award_points(org_id, customer_id, Decimal("75.50"))

        assert txn is not None
        assert txn.points == 151  # floor(75.50 * 2.0) = 151

    @pytest.mark.asyncio
    async def test_no_points_when_inactive(self) -> None:
        """No points awarded when loyalty is inactive."""
        org_id = uuid.uuid4()
        mock_db = MagicMock()
        config = _make_config(org_id, is_active=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = LoyaltyService(mock_db)
        txn = await svc.award_points(org_id, uuid.uuid4(), Decimal("100.00"))
        assert txn is None

    @pytest.mark.asyncio
    async def test_no_points_when_no_config(self) -> None:
        """No points awarded when loyalty is not configured."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = LoyaltyService(mock_db)
        txn = await svc.award_points(uuid.uuid4(), uuid.uuid4(), Decimal("100.00"))
        assert txn is None

    @pytest.mark.asyncio
    async def test_no_points_for_zero_total(self) -> None:
        """No points awarded for a zero-dollar invoice."""
        org_id = uuid.uuid4()
        mock_db = MagicMock()
        config = _make_config(org_id, earn_rate=Decimal("1.0"))
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = config
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = LoyaltyService(mock_db)
        txn = await svc.award_points(org_id, uuid.uuid4(), Decimal("0.00"))
        assert txn is None


# ---------------------------------------------------------------------------
# 41.9: Tier discount auto-applied as separate line item
# ---------------------------------------------------------------------------

class TestTierDiscount:
    """41.9: Tier discount auto-applied as separate line item."""

    @pytest.mark.asyncio
    async def test_gold_tier_discount_applied(self) -> None:
        """Gold tier customer gets 10% discount line item."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gold_tier = _make_tier(org_id, "Gold", 1000, Decimal("10.00"))

        mock_db = MagicMock()

        # get_customer_balance returns 1500 (qualifies for Gold)
        mock_result_balance = MagicMock()
        mock_result_balance.scalar_one.return_value = 1500

        # list_tiers returns tiers
        mock_result_tiers = MagicMock()
        mock_result_tiers.scalars.return_value.all.return_value = [gold_tier]

        mock_db.execute = AsyncMock(side_effect=[
            mock_result_balance,  # get_customer_balance
            mock_result_tiers,    # list_tiers (for check_tier_upgrade)
        ])

        svc = LoyaltyService(mock_db)
        line = await svc.auto_apply_tier_discount(
            org_id, customer_id, Decimal("500.00"),
        )

        assert line is not None
        assert line["description"] == "Gold Loyalty Discount"
        assert line["total"] == Decimal("-50.00")  # 10% of 500
        assert line["tier_name"] == "Gold"
        assert line["quantity"] == 1
        assert line["unit_price"] == Decimal("-50.00")

    @pytest.mark.asyncio
    async def test_no_discount_when_no_tier(self) -> None:
        """No discount when customer doesn't qualify for any tier."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        mock_db = MagicMock()
        mock_result_balance = MagicMock()
        mock_result_balance.scalar_one.return_value = 50  # low balance

        bronze_tier = _make_tier(org_id, "Bronze", 100, Decimal("5.00"))
        mock_result_tiers = MagicMock()
        mock_result_tiers.scalars.return_value.all.return_value = [bronze_tier]

        mock_db.execute = AsyncMock(side_effect=[
            mock_result_balance,
            mock_result_tiers,
        ])

        svc = LoyaltyService(mock_db)
        line = await svc.auto_apply_tier_discount(
            org_id, customer_id, Decimal("200.00"),
        )
        assert line is None

    @pytest.mark.asyncio
    async def test_no_discount_when_tier_has_zero_percent(self) -> None:
        """No discount when tier has 0% discount."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        tier = _make_tier(org_id, "Basic", 0, Decimal("0"))

        mock_db = MagicMock()
        mock_result_balance = MagicMock()
        mock_result_balance.scalar_one.return_value = 500

        mock_result_tiers = MagicMock()
        mock_result_tiers.scalars.return_value.all.return_value = [tier]

        mock_db.execute = AsyncMock(side_effect=[
            mock_result_balance,
            mock_result_tiers,
        ])

        svc = LoyaltyService(mock_db)
        line = await svc.auto_apply_tier_discount(
            org_id, customer_id, Decimal("100.00"),
        )
        assert line is None

    @pytest.mark.asyncio
    async def test_highest_qualifying_tier_selected(self) -> None:
        """When customer qualifies for multiple tiers, highest is selected."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        bronze = _make_tier(org_id, "Bronze", 100, Decimal("5.00"))
        silver = _make_tier(org_id, "Silver", 500, Decimal("7.50"))
        gold = _make_tier(org_id, "Gold", 1000, Decimal("10.00"))

        mock_db = MagicMock()
        mock_result_balance = MagicMock()
        mock_result_balance.scalar_one.return_value = 750  # qualifies for Silver

        mock_result_tiers = MagicMock()
        mock_result_tiers.scalars.return_value.all.return_value = [bronze, silver, gold]

        mock_db.execute = AsyncMock(side_effect=[
            mock_result_balance,
            mock_result_tiers,
        ])

        svc = LoyaltyService(mock_db)
        line = await svc.auto_apply_tier_discount(
            org_id, customer_id, Decimal("200.00"),
        )

        assert line is not None
        assert line["tier_name"] == "Silver"
        assert line["total"] == Decimal("-15.00")  # 7.5% of 200
