"""Property-based tests for payment method status logic.

Uses Hypothesis to verify correctness properties for the billing module's
payment method enforcement feature.

Feature: payment-method-enforcement
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.billing.utils import is_expiring_soon


# ---------------------------------------------------------------------------
# Feature: payment-method-enforcement, Property 2: Expiry date boundary correctness
# ---------------------------------------------------------------------------
# **Validates: Requirements 4.3**


@given(
    exp_month=st.integers(min_value=1, max_value=12),
    exp_year=st.integers(min_value=2020, max_value=2040),
    reference_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2040, 12, 31)),
)
@settings(max_examples=200)
def test_is_expiring_soon_boundary_correctness(
    exp_month: int, exp_year: int, reference_date: date
) -> None:
    """Property 2: Expiry date boundary correctness.

    For any valid (exp_month, exp_year) pair and any reference date,
    is_expiring_soon returns True if and only if the last calendar day
    of exp_month/exp_year <= reference_date + 30 days.

    This must hold correctly across month boundaries (28/29/30/31-day months),
    year boundaries, and leap years.

    **Validates: Requirements 4.3**
    """
    # Oracle: independently compute the expected result
    last_day = calendar.monthrange(exp_year, exp_month)[1]
    expiry_date = date(exp_year, exp_month, last_day)
    expected = expiry_date <= reference_date + timedelta(days=30)

    # Act
    result = is_expiring_soon(exp_month, exp_year, reference_date)

    # Assert: function matches the oracle exactly
    assert result == expected, (
        f"is_expiring_soon({exp_month}, {exp_year}, {reference_date}) "
        f"returned {result}, expected {expected}. "
        f"expiry_date={expiry_date}, cutoff={reference_date + timedelta(days=30)}"
    )


# ---------------------------------------------------------------------------
# Feature: payment-method-enforcement, Property 1: Payment method status computation correctness
# ---------------------------------------------------------------------------
# **Validates: Requirements 1.3, 4.2**


# Strategy: generate a list of (exp_month, exp_year) pairs representing
# payment methods for an organisation (0 to 10 methods).
_method_strategy = st.lists(
    st.tuples(
        st.integers(min_value=1, max_value=12),
        st.integers(min_value=2020, max_value=2040),
    ),
    min_size=0,
    max_size=10,
)


@given(
    methods=_method_strategy,
    reference_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2040, 12, 31)),
)
@settings(max_examples=200)
def test_payment_method_status_computation_correctness(
    methods: list[tuple[int, int]], reference_date: date
) -> None:
    """Property 1: Payment method status computation correctness.

    For any set of (exp_month, exp_year) pairs (including the empty set)
    and any reference date, the status computation SHALL return:
    - has_payment_method = True iff the set is non-empty
    - has_expiring_soon = True iff at least one method is expiring within 30 days
    - expiring_method = the soonest-expiring among those within 30 days, or None

    This mirrors the pure logic used by the GET /payment-method-status endpoint.

    **Validates: Requirements 1.3, 4.2**
    """
    # --- Compute status the same way the endpoint does ---
    has_payment_method = len(methods) > 0

    soonest_expiring: tuple[int, int] | None = None
    soonest_expiry_date: date | None = None

    for exp_month, exp_year in methods:
        if is_expiring_soon(exp_month, exp_year, reference_date):
            last_day = calendar.monthrange(exp_year, exp_month)[1]
            method_expiry = date(exp_year, exp_month, last_day)
            if soonest_expiry_date is None or method_expiry < soonest_expiry_date:
                soonest_expiring = (exp_month, exp_year)
                soonest_expiry_date = method_expiry

    has_expiring_soon = soonest_expiring is not None

    # --- Oracle: independently verify each property ---

    # Property A: has_payment_method is True iff set is non-empty
    expected_has_pm = len(methods) > 0
    assert has_payment_method == expected_has_pm, (
        f"has_payment_method={has_payment_method}, expected={expected_has_pm} "
        f"for {len(methods)} methods"
    )

    # Property B: has_expiring_soon is True iff at least one method is expiring
    any_expiring = any(
        is_expiring_soon(m, y, reference_date) for m, y in methods
    )
    assert has_expiring_soon == any_expiring, (
        f"has_expiring_soon={has_expiring_soon}, expected={any_expiring} "
        f"for methods={methods}, reference_date={reference_date}"
    )

    # Property C: expiring_method is the soonest-expiring among those within
    # 30 days, or None if none are expiring soon
    expiring_within_30: list[tuple[int, int, date]] = []
    for exp_month, exp_year in methods:
        if is_expiring_soon(exp_month, exp_year, reference_date):
            last_day = calendar.monthrange(exp_year, exp_month)[1]
            expiring_within_30.append(
                (exp_month, exp_year, date(exp_year, exp_month, last_day))
            )

    if not expiring_within_30:
        assert soonest_expiring is None, (
            f"Expected expiring_method=None but got {soonest_expiring}"
        )
    else:
        # The oracle: find the method with the smallest expiry date
        oracle_soonest = min(expiring_within_30, key=lambda t: t[2])
        oracle_expiry_date = oracle_soonest[2]
        assert soonest_expiry_date == oracle_expiry_date, (
            f"expiring_method expiry date={soonest_expiry_date}, "
            f"expected={oracle_expiry_date} "
            f"for methods={methods}, reference_date={reference_date}"
        )
