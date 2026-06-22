"""Property test for the Hours_Test predicate (design Property 22).

**Validates: Requirements 8.1, 8.5**
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.leave.rules.hours_test import (
    HoursTestInput,
    evaluate_hours_test,
)
from app.modules.leave.rules.registry import HoursTestBounds

_PBT = settings(max_examples=100, deadline=None)
_BOUNDS = HoursTestBounds(
    min_avg_hours_per_week=Decimal("10"),
    min_hours_every_week=Decimal("1"),
    min_hours_every_month=Decimal("40"),
)

_hours = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("80"), places=2, allow_nan=False,
    allow_infinity=False,
)


# Feature: leave-balances-eligibility, Property 22: Hours-test predicate
@_PBT
@given(
    weeks=st.lists(_hours, min_size=1, max_size=26),
    months=st.lists(_hours, min_size=1, max_size=6),
    period_weeks=st.integers(min_value=1, max_value=26),
)
def test_hours_test_predicate(weeks, months, period_weeks) -> None:
    total = sum(weeks, Decimal("0"))
    inp = HoursTestInput(
        weeks=tuple(weeks),
        months=tuple(months),
        total_hours=total,
        period_weeks=period_weeks,
    )
    result = evaluate_hours_test(inp, _BOUNDS)

    avg = total / Decimal(period_weeks)
    every_week_ok = all(w >= _BOUNDS.min_hours_every_week for w in weeks)
    every_month_ok = all(m >= _BOUNDS.min_hours_every_month for m in months)
    expected = (avg >= _BOUNDS.min_avg_hours_per_week) and (
        every_week_ok or every_month_ok
    )
    assert result.met is expected
    if not result.met:
        assert result.reason is not None


# Feature: leave-balances-eligibility, Property 22: Hours-test predicate (unavailable input)
@_PBT
@given(st.none())
def test_hours_test_none_is_not_met(_none) -> None:
    result = evaluate_hours_test(None, _BOUNDS)
    assert result.met is False
    assert result.reason == "no_worked_hours_data"
