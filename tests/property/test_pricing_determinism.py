"""Property-based test: pricing rule evaluation determinism.

**Validates: Requirements 10.1, 10.2** — Property 7

For any product P and context C (customer, quantity, date), the pricing
rule evaluation always returns the same price. The evaluation is
deterministic given the same rule set and context.

Uses Hypothesis to generate random pricing contexts and rule sets,
then verifies that evaluating the same inputs twice yields identical results.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.pricing_rules.models import PricingRule
from app.modules.pricing_rules.service import PricingRuleService


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

price_strategy = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("10000"),
    places=2, allow_nan=False, allow_infinity=False,
)

quantity_strategy = st.decimals(
    min_value=Decimal("1"), max_value=Decimal("1000"),
    places=3, allow_nan=False, allow_infinity=False,
)

discount_strategy = st.decimals(
    min_value=Decimal("1"), max_value=Decimal("99"),
    places=2, allow_nan=False, allow_infinity=False,
)

rule_type_strategy = st.sampled_from([
    "customer_specific", "volume", "date_based", "trade_category",
])


def _make_rule(
    org_id: uuid.UUID,
    product_id: uuid.UUID,
    rule_type: str,
    priority: int,
    *,
    customer_id: uuid.UUID | None = None,
    min_quantity: Decimal | None = None,
    max_quantity: Decimal | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    price_override: Decimal | None = None,
    discount_percent: Decimal | None = None,
) -> PricingRule:
    """Create an in-memory PricingRule."""
    rule = PricingRule(
        id=uuid.uuid4(),
        org_id=org_id,
        product_id=product_id,
        rule_type=rule_type,
        priority=priority,
        customer_id=customer_id,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        start_date=start_date,
        end_date=end_date,
        price_override=price_override,
        discount_percent=discount_percent,
        is_active=True,
    )
    return rule


def _build_mock_db(rules: list[PricingRule]) -> AsyncMock:
    """Build a mock AsyncSession that returns the given rules from execute()."""
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
        # Sort rules by priority descending (matching the service query)
        sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)
        return FakeResult(sorted_rules)

    mock_db.execute = fake_execute
    return mock_db


class TestPricingRuleDeterminism:
    """For any product P and context C (customer, quantity, date), the
    pricing rule evaluation always returns the same price.

    **Validates: Requirements 10.1, 10.2**
    """

    @given(
        base_price=price_strategy,
        customer_id=st.uuids(),
        quantity=quantity_strategy,
        eval_date=st.dates(
            min_value=date(2020, 1, 1), max_value=date(2030, 12, 31),
        ),
        override_price=price_strategy,
        priority=st.integers(min_value=0, max_value=100),
    )
    @PBT_SETTINGS
    def test_same_inputs_produce_same_price(
        self,
        base_price: Decimal,
        customer_id: uuid.UUID,
        quantity: Decimal,
        eval_date: date,
        override_price: Decimal,
        priority: int,
    ) -> None:
        """Evaluating the same context twice with the same rules
        returns identical prices."""
        import asyncio

        org_id = uuid.uuid4()
        product_id = uuid.uuid4()

        rule = _make_rule(
            org_id, product_id, "customer_specific", priority,
            customer_id=customer_id, price_override=override_price,
        )

        mock_db = _build_mock_db([rule])
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
            assert r1.price == r2.price, (
                f"Non-deterministic: first={r1.price}, second={r2.price}"
            )
            assert r1.rule_id == r2.rule_id
            assert r1.is_base_price == r2.is_base_price

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        base_price=price_strategy,
        quantity=quantity_strategy,
        eval_date=st.dates(
            min_value=date(2020, 1, 1), max_value=date(2030, 12, 31),
        ),
        num_rules=st.integers(min_value=1, max_value=5),
        data=st.data(),
    )
    @PBT_SETTINGS
    def test_deterministic_with_multiple_rules(
        self,
        base_price: Decimal,
        quantity: Decimal,
        eval_date: date,
        num_rules: int,
        data,
    ) -> None:
        """With multiple rules of varying types and priorities,
        evaluation is still deterministic."""
        import asyncio

        org_id = uuid.uuid4()
        product_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        rules: list[PricingRule] = []
        for i in range(num_rules):
            rtype = data.draw(rule_type_strategy)
            prio = data.draw(st.integers(min_value=0, max_value=100))
            override = data.draw(price_strategy)

            kwargs: dict = {"price_override": override}
            if rtype == "customer_specific":
                kwargs["customer_id"] = customer_id
            elif rtype == "volume":
                kwargs["min_quantity"] = Decimal("1")
                kwargs["max_quantity"] = Decimal("999")
            elif rtype == "date_based":
                kwargs["start_date"] = date(2019, 1, 1)
                kwargs["end_date"] = date(2031, 12, 31)

            rules.append(_make_rule(org_id, product_id, rtype, prio, **kwargs))

        mock_db = _build_mock_db(rules)
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
            assert r1.price == r2.price, (
                f"Non-deterministic with {num_rules} rules: "
                f"first={r1.price}, second={r2.price}"
            )

        asyncio.get_event_loop().run_until_complete(run())

    @given(
        base_price=price_strategy,
        discount=discount_strategy,
    )
    @PBT_SETTINGS
    def test_discount_deterministic(
        self,
        base_price: Decimal,
        discount: Decimal,
    ) -> None:
        """Discount-based rules produce the same price on repeated evaluation."""
        import asyncio

        org_id = uuid.uuid4()
        product_id = uuid.uuid4()

        rule = _make_rule(
            org_id, product_id, "trade_category", 10,
            discount_percent=discount,
        )

        mock_db = _build_mock_db([rule])
        svc = PricingRuleService(mock_db)

        async def run():
            r1 = await svc.evaluate_price(org_id, product_id, base_price)
            r2 = await svc.evaluate_price(org_id, product_id, base_price)
            assert r1.price == r2.price

        asyncio.get_event_loop().run_until_complete(run())
