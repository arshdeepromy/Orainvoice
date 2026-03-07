"""Unit tests for pricing rules engine.

**Validates: Requirements 10.1, 10.2, 10.5**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.modules.pricing_rules.models import PricingRule
from app.modules.pricing_rules.service import PricingRuleService


def _make_rule(
    org_id: uuid.UUID,
    product_id: uuid.UUID,
    rule_type: str,
    priority: int,
    **kwargs,
) -> PricingRule:
    return PricingRule(
        id=uuid.uuid4(),
        org_id=org_id,
        product_id=product_id,
        rule_type=rule_type,
        priority=priority,
        is_active=True,
        **kwargs,
    )


def _build_mock_db(rules: list[PricingRule]) -> AsyncMock:
    mock_db = AsyncMock()

    class FakeScalars:
        def __init__(self, items):
            self._items = items
        def all(self):
            return self._items

    class FakeResult:
        def __init__(self, items):
            self._items = items
        def scalars(self):
            return FakeScalars(self._items)

    async def fake_execute(stmt):
        sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)
        return FakeResult(sorted_rules)

    mock_db.execute = fake_execute
    return mock_db


class TestCustomerSpecificOverridesVolume:
    """Customer-specific price overrides volume pricing when higher priority.

    **Validates: Requirements 10.1, 10.2**
    """

    @pytest.mark.asyncio
    async def test_customer_specific_wins_over_volume_when_higher_priority(self):
        """A customer-specific rule with higher priority should be selected
        over a volume rule with lower priority."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        base_price = Decimal("100.00")

        volume_rule = _make_rule(
            org_id, product_id, "volume", priority=5,
            min_quantity=Decimal("1"), max_quantity=Decimal("100"),
            price_override=Decimal("80.00"),
        )
        customer_rule = _make_rule(
            org_id, product_id, "customer_specific", priority=10,
            customer_id=customer_id,
            price_override=Decimal("75.00"),
        )

        mock_db = _build_mock_db([volume_rule, customer_rule])
        svc = PricingRuleService(mock_db)

        result = await svc.evaluate_price(
            org_id, product_id, base_price,
            customer_id=customer_id, quantity=Decimal("10"),
        )

        assert result.price == Decimal("75.00")
        assert result.rule_id == customer_rule.id
        assert result.rule_type == "customer_specific"
        assert result.is_base_price is False

    @pytest.mark.asyncio
    async def test_volume_wins_when_customer_specific_has_lower_priority(self):
        """When volume rule has higher priority, it should win."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        base_price = Decimal("100.00")

        volume_rule = _make_rule(
            org_id, product_id, "volume", priority=20,
            min_quantity=Decimal("1"), max_quantity=Decimal("100"),
            price_override=Decimal("80.00"),
        )
        customer_rule = _make_rule(
            org_id, product_id, "customer_specific", priority=5,
            customer_id=customer_id,
            price_override=Decimal("75.00"),
        )

        mock_db = _build_mock_db([volume_rule, customer_rule])
        svc = PricingRuleService(mock_db)

        result = await svc.evaluate_price(
            org_id, product_id, base_price,
            customer_id=customer_id, quantity=Decimal("10"),
        )

        assert result.price == Decimal("80.00")
        assert result.rule_id == volume_rule.id
        assert result.rule_type == "volume"

    @pytest.mark.asyncio
    async def test_no_matching_rules_returns_base_price(self):
        """When no rules match, the base sale price is returned."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        base_price = Decimal("100.00")

        # Customer-specific rule for a different customer
        rule = _make_rule(
            org_id, product_id, "customer_specific", priority=10,
            customer_id=uuid.uuid4(),
            price_override=Decimal("50.00"),
        )

        mock_db = _build_mock_db([rule])
        svc = PricingRuleService(mock_db)

        result = await svc.evaluate_price(
            org_id, product_id, base_price,
            customer_id=uuid.uuid4(), quantity=Decimal("1"),
        )

        assert result.price == base_price
        assert result.is_base_price is True
        assert result.rule_id is None


class TestDateBasedPricing:
    """Date-based pricing activates and deactivates on configured dates.

    **Validates: Requirements 10.1, 10.2**
    """

    @pytest.mark.asyncio
    async def test_date_based_rule_active_within_range(self):
        """A date-based rule matches when eval_date is within the range."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        base_price = Decimal("100.00")

        rule = _make_rule(
            org_id, product_id, "date_based", priority=10,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            price_override=Decimal("70.00"),
        )

        mock_db = _build_mock_db([rule])
        svc = PricingRuleService(mock_db)

        result = await svc.evaluate_price(
            org_id, product_id, base_price,
            eval_date=date(2025, 2, 15),
        )

        assert result.price == Decimal("70.00")
        assert result.rule_type == "date_based"
        assert result.is_base_price is False

    @pytest.mark.asyncio
    async def test_date_based_rule_inactive_before_start(self):
        """A date-based rule does NOT match before its start_date."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        base_price = Decimal("100.00")

        rule = _make_rule(
            org_id, product_id, "date_based", priority=10,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 8, 31),
            price_override=Decimal("70.00"),
        )

        mock_db = _build_mock_db([rule])
        svc = PricingRuleService(mock_db)

        result = await svc.evaluate_price(
            org_id, product_id, base_price,
            eval_date=date(2025, 5, 15),
        )

        assert result.price == base_price
        assert result.is_base_price is True

    @pytest.mark.asyncio
    async def test_date_based_rule_inactive_after_end(self):
        """A date-based rule does NOT match after its end_date."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        base_price = Decimal("100.00")

        rule = _make_rule(
            org_id, product_id, "date_based", priority=10,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 3, 31),
            price_override=Decimal("70.00"),
        )

        mock_db = _build_mock_db([rule])
        svc = PricingRuleService(mock_db)

        result = await svc.evaluate_price(
            org_id, product_id, base_price,
            eval_date=date(2025, 4, 1),
        )

        assert result.price == base_price
        assert result.is_base_price is True

    @pytest.mark.asyncio
    async def test_date_based_rule_active_on_boundary_dates(self):
        """A date-based rule matches on exact start_date and end_date."""
        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        base_price = Decimal("100.00")

        rule = _make_rule(
            org_id, product_id, "date_based", priority=10,
            start_date=date(2025, 6, 1),
            end_date=date(2025, 6, 30),
            price_override=Decimal("60.00"),
        )

        mock_db = _build_mock_db([rule])
        svc = PricingRuleService(mock_db)

        # On start_date
        r1 = await svc.evaluate_price(
            org_id, product_id, base_price, eval_date=date(2025, 6, 1),
        )
        assert r1.price == Decimal("60.00")

        # On end_date
        r2 = await svc.evaluate_price(
            org_id, product_id, base_price, eval_date=date(2025, 6, 30),
        )
        assert r2.price == Decimal("60.00")
