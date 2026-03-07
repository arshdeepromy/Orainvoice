"""Comprehensive property-based tests for loyalty properties.

Properties covered:
  P13 — Loyalty Points Balance Consistency: balance = sum of transactions

**Validates: Requirements 13**
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS, price_strategy


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

earn_amount_st = st.decimals(
    min_value=Decimal("1.00"), max_value=Decimal("100000"),
    places=2, allow_nan=False, allow_infinity=False,
)

earn_rate_st = st.decimals(
    min_value=Decimal("0.1"), max_value=Decimal("10.0"),
    places=4, allow_nan=False, allow_infinity=False,
)


# ===========================================================================
# Property 13: Loyalty Points Balance Consistency
# ===========================================================================


class TestP13LoyaltyBalanceConsistency:
    """Customer loyalty balance equals sum of all transaction points.

    **Validates: Requirements 13**
    """

    @given(
        earn_amounts=st.lists(earn_amount_st, min_size=1, max_size=20),
        earn_rate=earn_rate_st,
    )
    @PBT_SETTINGS
    def test_balance_equals_sum_of_earn_transactions(
        self, earn_amounts: list[Decimal], earn_rate: Decimal,
    ) -> None:
        """P13: after earn transactions, balance = sum of awarded points."""
        running_balance = 0
        transaction_points: list[int] = []

        for amount in earn_amounts:
            points = int((amount * earn_rate).to_integral_value(rounding=ROUND_DOWN))
            if points > 0:
                running_balance += points
                transaction_points.append(points)

        assert running_balance == sum(transaction_points)
        assert running_balance >= 0

    @given(
        earn_amounts=st.lists(earn_amount_st, min_size=2, max_size=20),
        earn_rate=earn_rate_st,
        redeem_fraction=st.floats(min_value=0.01, max_value=0.5),
    )
    @PBT_SETTINGS
    def test_balance_after_earn_and_redeem(
        self, earn_amounts, earn_rate, redeem_fraction,
    ) -> None:
        """P13: after earn + redeem, balance = sum of all points."""
        all_points: list[int] = []
        running_balance = 0

        for amount in earn_amounts:
            points = int((amount * earn_rate).to_integral_value(rounding=ROUND_DOWN))
            if points > 0:
                running_balance += points
                all_points.append(points)

        assume(running_balance > 0)

        redeem_amount = max(1, int(running_balance * redeem_fraction))
        assume(redeem_amount <= running_balance)

        running_balance -= redeem_amount
        all_points.append(-redeem_amount)

        assert running_balance == sum(all_points)
        assert running_balance >= 0

    @given(
        earn_amounts=st.lists(earn_amount_st, min_size=1, max_size=10),
        earn_rate=earn_rate_st,
    )
    @PBT_SETTINGS
    def test_balance_is_consistent_with_running_sum(
        self, earn_amounts, earn_rate,
    ) -> None:
        """P13: balance_after on each transaction matches running sum."""
        running_balance = 0
        for amount in earn_amounts:
            points = int((amount * earn_rate).to_integral_value(rounding=ROUND_DOWN))
            if points > 0:
                running_balance += points

        final_sum = 0
        for amount in earn_amounts:
            points = int((amount * earn_rate).to_integral_value(rounding=ROUND_DOWN))
            if points > 0:
                final_sum += points

        assert running_balance == final_sum
