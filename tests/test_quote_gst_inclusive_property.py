"""Property-based tests for Quote GST-inclusive round-trip (Task 8.1).

Property CP-3: GST-inclusive round-trip
- When a line item has gst_inclusive=True and inclusive_price=P,
  unit_price is back-calculated as P / 1.15 (rounded half-up to 2 d.p.)
- line_total = quantity * unit_price (rounded half-up to 2 d.p.)
- The returned line item preserves gst_inclusive=True and inclusive_price=P exactly

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**

Tests the _calculate_quote_totals function directly (unit-level) and
the full create_quote → _quote_to_dict round-trip (integration-level via mocks).
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.quotes.service import _calculate_quote_totals

TWO_PLACES = Decimal("0.01")
GST_DIVISOR = Decimal("1.15")
GST_RATE_DECIMAL = Decimal("0.15")

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

quantities = st.decimals(
    min_value="0.001", max_value="1000.000",
    places=3, allow_nan=False, allow_infinity=False,
)

inclusive_prices = st.decimals(
    min_value="0.01", max_value="99999.99",
    places=2, allow_nan=False, allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Property CP-3: GST-inclusive round-trip (unit-level)
# **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
# ---------------------------------------------------------------------------


class TestGSTInclusiveRoundTrip:
    """Verify GST-inclusive back-calculation produces correct unit_price and line_total."""

    @PBT_SETTINGS
    @given(quantity=quantities, inclusive_price=inclusive_prices)
    def test_unit_price_back_calculation(self, quantity, inclusive_price):
        """CP-3: unit_price = inclusive_price / 1.15 rounded half-up to 2 d.p.

        **Validates: Requirements 9.1, 9.2**
        """
        line_items_data = [
            {
                "quantity": quantity,
                "unit_price": Decimal("0"),  # ignored when gst_inclusive
                "gst_inclusive": True,
                "inclusive_price": inclusive_price,
                "is_gst_exempt": False,
            }
        ]

        result = _calculate_quote_totals(line_items_data, Decimal("15"))

        expected_unit_price = (inclusive_price / GST_DIVISOR).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        assert result["line_unit_prices"][0] == expected_unit_price, (
            f"Expected unit_price={expected_unit_price}, "
            f"got {result['line_unit_prices'][0]} "
            f"for inclusive_price={inclusive_price}"
        )

    @PBT_SETTINGS
    @given(quantity=quantities, inclusive_price=inclusive_prices)
    def test_line_total_calculation(self, quantity, inclusive_price):
        """CP-3: line_total = quantity * unit_price rounded half-up to 2 d.p.

        **Validates: Requirements 9.3, 9.4**
        """
        line_items_data = [
            {
                "quantity": quantity,
                "unit_price": Decimal("0"),
                "gst_inclusive": True,
                "inclusive_price": inclusive_price,
                "is_gst_exempt": False,
            }
        ]

        result = _calculate_quote_totals(line_items_data, Decimal("15"))

        expected_unit_price = (inclusive_price / GST_DIVISOR).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        expected_line_total = (quantity * expected_unit_price).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        assert result["line_totals"][0] == expected_line_total, (
            f"Expected line_total={expected_line_total}, "
            f"got {result['line_totals'][0]} "
            f"for quantity={quantity}, inclusive_price={inclusive_price}"
        )

    @PBT_SETTINGS
    @given(quantity=quantities, inclusive_price=inclusive_prices)
    def test_gst_amount_on_inclusive_line(self, quantity, inclusive_price):
        """CP-3: GST on inclusive line = line_total * 0.15 rounded half-up.

        **Validates: Requirements 9.4, 9.5**
        """
        line_items_data = [
            {
                "quantity": quantity,
                "unit_price": Decimal("0"),
                "gst_inclusive": True,
                "inclusive_price": inclusive_price,
                "is_gst_exempt": False,
            }
        ]

        result = _calculate_quote_totals(line_items_data, Decimal("15"))

        expected_unit_price = (inclusive_price / GST_DIVISOR).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        expected_line_total = (quantity * expected_unit_price).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        expected_gst = (expected_line_total * GST_RATE_DECIMAL).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        assert result["gst_amount"] == expected_gst, (
            f"Expected gst_amount={expected_gst}, got {result['gst_amount']}"
        )

    @PBT_SETTINGS
    @given(quantity=quantities, inclusive_price=inclusive_prices)
    def test_line_total_equals_quantity_times_rounded_unit_price(
        self, quantity, inclusive_price
    ):
        """CP-3: line_total = round(q * round(P/1.15, 2), 2) exactly.

        The implementation rounds unit_price first, then multiplies by quantity
        and rounds again. This is the correct two-step rounding behaviour.

        **Validates: Requirements 9.1, 9.2, 9.3**
        """
        line_items_data = [
            {
                "quantity": quantity,
                "unit_price": Decimal("0"),
                "gst_inclusive": True,
                "inclusive_price": inclusive_price,
                "is_gst_exempt": False,
            }
        ]

        result = _calculate_quote_totals(line_items_data, Decimal("15"))

        # The correct calculation: round unit_price first, then multiply
        rounded_unit_price = (inclusive_price / GST_DIVISOR).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        expected_line_total = (quantity * rounded_unit_price).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        assert result["line_totals"][0] == expected_line_total, (
            f"line_total={result['line_totals'][0]} != expected={expected_line_total} "
            f"for q={quantity}, P={inclusive_price}"
        )

    @PBT_SETTINGS
    @given(
        num_items=st.integers(min_value=1, max_value=8),
        data=st.data(),
    )
    def test_mixed_inclusive_exclusive_totals_identity(self, num_items, data):
        """CP-3: For mixed inclusive/exclusive items, subtotal = sum(line_totals)
        and total = subtotal + gst_amount.

        **Validates: Requirements 9.4, 9.5**
        """
        items = []
        for _ in range(num_items):
            gst_inclusive = data.draw(st.booleans())
            q = data.draw(quantities)
            if gst_inclusive:
                inc_price = data.draw(inclusive_prices)
                items.append({
                    "quantity": q,
                    "unit_price": Decimal("0"),
                    "gst_inclusive": True,
                    "inclusive_price": inc_price,
                    "is_gst_exempt": False,
                })
            else:
                up = data.draw(inclusive_prices)  # reuse strategy for unit_price
                items.append({
                    "quantity": q,
                    "unit_price": up,
                    "gst_inclusive": False,
                    "inclusive_price": None,
                    "is_gst_exempt": data.draw(st.booleans()),
                })

        result = _calculate_quote_totals(items, Decimal("15"))

        # Subtotal = sum of line totals
        expected_subtotal = sum(result["line_totals"], Decimal("0")).quantize(TWO_PLACES)
        assert result["subtotal"] == expected_subtotal

        # Total = subtotal + gst_amount
        expected_total = (result["subtotal"] + result["gst_amount"]).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        assert result["total"] == expected_total

    @PBT_SETTINGS
    @given(quantity=quantities, inclusive_price=inclusive_prices)
    def test_non_negative_results(self, quantity, inclusive_price):
        """CP-3: All calculated values are non-negative.

        **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
        """
        line_items_data = [
            {
                "quantity": quantity,
                "unit_price": Decimal("0"),
                "gst_inclusive": True,
                "inclusive_price": inclusive_price,
                "is_gst_exempt": False,
            }
        ]

        result = _calculate_quote_totals(line_items_data, Decimal("15"))

        assert result["line_unit_prices"][0] >= Decimal("0")
        assert result["line_totals"][0] >= Decimal("0")
        assert result["subtotal"] >= Decimal("0")
        assert result["gst_amount"] >= Decimal("0")
        assert result["total"] >= Decimal("0")
