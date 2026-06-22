"""Property test for termination payout (design Property 29).

**Validates: Requirements 14.1, 14.2, 14.3, 14.4**
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.leave.rules.termination import compute_termination_payout

_PBT = settings(max_examples=100, deadline=None)

_money = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("1000000"), places=2,
    allow_nan=False, allow_infinity=False,
)
_hours = st.decimals(
    min_value=Decimal("0"), max_value=Decimal("2000"), places=2,
    allow_nan=False, allow_infinity=False,
)


# Feature: leave-balances-eligibility, Property 29: Termination payout pre/post twelve months and casual
@_PBT
@given(
    months=st.integers(min_value=0, max_value=60),
    gross=_money,
    accrued=_hours,
    owp=_money,
    awe=_money,
    method=st.sampled_from(["accrued", "casual_payg"]),
    weekly_hours=st.decimals(
        min_value=Decimal("1"), max_value=Decimal("60"), places=2,
        allow_nan=False, allow_infinity=False,
    ),
)
def test_termination_payout_branches(
    months, gross, accrued, owp, awe, method, weekly_hours
) -> None:
    out = compute_termination_payout(
        continuous_service_months=months,
        gross_earnings=gross,
        remaining_accrued_hours=accrued,
        ordinary_weekly_pay=owp,
        average_weekly_earnings=awe,
        holiday_pay_method=method,
        standard_hours_per_week=weekly_hours,
    )

    if method == "casual_payg":
        assert out.rule_applied == "casual_payg_already_paid"
        assert out.amount == Decimal("0.00")
    elif months < 12:
        assert out.rule_applied == "pre_12mo_8pct"
        assert out.amount == (gross * Decimal("0.08")).quantize(Decimal("0.01"))
    else:
        assert out.rule_applied == "post_12mo_accrued"
        weeks = accrued / weekly_hours
        rate = max(owp, awe)
        assert out.amount == (weeks * rate).quantize(Decimal("0.01"))
