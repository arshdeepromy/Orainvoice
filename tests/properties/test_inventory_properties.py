"""Comprehensive property-based tests for inventory properties.

Properties covered:
  P3 — Stock Movement Consistency: sum of movements equals current quantity
  P7 — Pricing Rule Determinism: same inputs always produce same price

**Validates: Requirements 3, 7**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import (
    PBT_SETTINGS,
    price_strategy,
    quantity_strategy,
    movement_type_strategy,
)

from app.modules.products.models import Product
from app.modules.stock.models import StockMovement
from app.modules.stock.service import StockService
from app.modules.pricing_rules.models import PricingRule
from app.modules.pricing_rules.service import PricingRuleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(initial_stock: Decimal = Decimal("0")) -> Product:
    return Product(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name="Test Product",
        stock_quantity=initial_stock,
        sale_price=Decimal("10.00"),
    )


def _make_rule(
    org_id, product_id, rule_type, priority, **kwargs,
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


def _build_pricing_mock_db(rules: list[PricingRule]) -> AsyncMock:
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


# ===========================================================================
# Property 3: Stock Movement Consistency
# ===========================================================================


class TestP3StockMovementConsistency:
    """Sum of all stock_movement quantity_changes equals current stock_quantity.

    **Validates: Requirements 3**
    """

    @given(
        initial_stock=st.decimals(
            min_value=Decimal("0"), max_value=Decimal("10000"),
            places=3, allow_nan=False, allow_infinity=False,
        ),
        operations=st.lists(
            st.tuples(movement_type_strategy, st.decimals(
                min_value=Decimal("-500"), max_value=Decimal("500"),
                places=3, allow_nan=False, allow_infinity=False,
            )),
            min_size=1,
            max_size=20,
        ),
    )
    @PBT_SETTINGS
    def test_movements_sum_equals_current_quantity(
        self, initial_stock: Decimal, operations: list,
    ) -> None:
        """P3: after N operations, sum of quantity_changes == stock_quantity."""
        import asyncio

        product = _make_product(Decimal("0"))
        movements: list[StockMovement] = []

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        svc = StockService(mock_db)

        async def run():
            if initial_stock != Decimal("0"):
                m = await svc._create_movement(product, initial_stock, "adjustment")
                movements.append(m)
            for move_type, qty in operations:
                m = await svc._create_movement(product, qty, move_type)
                movements.append(m)

        asyncio.run(run())

        total_change = sum(m.quantity_change for m in movements)
        assert product.stock_quantity == total_change

    @given(
        quantities=st.lists(
            st.decimals(
                min_value=Decimal("0.001"), max_value=Decimal("500"),
                places=3, allow_nan=False, allow_infinity=False,
            ),
            min_size=1,
            max_size=10,
        ),
    )
    @PBT_SETTINGS
    def test_decrement_then_increment_returns_to_original(
        self, quantities: list[Decimal],
    ) -> None:
        """P3: decrement + increment by same amounts returns to original."""
        import asyncio

        product = _make_product(Decimal("5000"))
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        svc = StockService(mock_db)
        original = product.stock_quantity

        async def run():
            for qty in quantities:
                await svc.decrement_stock(product, qty)
            for qty in quantities:
                await svc.increment_stock(product, qty)

        asyncio.run(run())
        assert product.stock_quantity == original


# ===========================================================================
# Property 7: Pricing Rule Determinism
# ===========================================================================


class TestP7PricingRuleDeterminism:
    """Pricing rule evaluation is deterministic for same inputs.

    **Validates: Requirements 7**
    """

    @given(
        base_price=price_strategy,
        customer_id=st.uuids(),
        quantity=quantity_strategy,
        eval_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
        override_price=price_strategy,
        priority=st.integers(min_value=0, max_value=100),
    )
    @PBT_SETTINGS
    def test_same_inputs_produce_same_price(
        self, base_price, customer_id, quantity, eval_date, override_price, priority,
    ) -> None:
        """P7: evaluating same context twice returns identical prices."""
        import asyncio

        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        rule = _make_rule(
            org_id, product_id, "customer_specific", priority,
            customer_id=customer_id, price_override=override_price,
        )
        mock_db = _build_pricing_mock_db([rule])
        svc = PricingRuleService(mock_db)

        async def run():
            r1 = await svc.evaluate_price(
                org_id, product_id, base_price,
                customer_id=customer_id, quantity=quantity, eval_date=eval_date,
            )
            r2 = await svc.evaluate_price(
                org_id, product_id, base_price,
                customer_id=customer_id, quantity=quantity, eval_date=eval_date,
            )
            assert r1.price == r2.price
            assert r1.rule_id == r2.rule_id

        asyncio.run(run())

    @given(
        base_price=price_strategy,
        discount=st.decimals(
            min_value=Decimal("1"), max_value=Decimal("99"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_discount_deterministic(self, base_price, discount) -> None:
        """P7: discount-based rules produce same price on repeated evaluation."""
        import asyncio

        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        rule = _make_rule(
            org_id, product_id, "trade_category", 10,
            discount_percent=discount,
        )
        mock_db = _build_pricing_mock_db([rule])
        svc = PricingRuleService(mock_db)

        async def run():
            r1 = await svc.evaluate_price(org_id, product_id, base_price)
            r2 = await svc.evaluate_price(org_id, product_id, base_price)
            assert r1.price == r2.price

        asyncio.run(run())
