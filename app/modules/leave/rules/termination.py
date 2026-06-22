"""Termination annual-holidays payout calculation (pure, representation only).

Implements the Holidays Act 2003 pre/post 12-month rule (R14):

  - ``casual_payg`` → 0 (annual holidays already paid each pay period).
  - service < 12 months → 8% of gross earnings.
  - service >= 12 months → remaining accrued annual-holiday hours converted to
    weeks × the greater of ordinary weekly pay or average weekly earnings.

This is **calculation only** — no payroll execution. The real payslip is still
produced by ``app/modules/payslips/termination.py``; this function anchors the
balances-view "what-if" display and the pre/post property tests.

**Validates: Requirements 14.1, 14.2, 14.3, 14.4**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

__all__ = ["TerminationPayout", "compute_termination_payout"]

# Holidays Act 2003 annual-holidays vest boundary (months) and PAYG rate.
_VEST_MONTHS = 12
_PAYG_RATE = Decimal("0.08")
_DEFAULT_WEEKLY_HOURS = Decimal("40")
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class TerminationPayout:
    rule_applied: str  # "pre_12mo_8pct" | "post_12mo_accrued" | "casual_payg_already_paid"
    amount: Decimal
    detail: dict = field(default_factory=dict)


def compute_termination_payout(
    *,
    continuous_service_months: int,
    gross_earnings: Decimal,
    remaining_accrued_hours: Decimal,
    ordinary_weekly_pay: Decimal,
    average_weekly_earnings: Decimal,
    holiday_pay_method: str,
    standard_hours_per_week: Decimal | None,
) -> TerminationPayout:
    """Pure termination annual-holidays payout. ``rule_applied`` matches the branch."""
    if holiday_pay_method == "casual_payg":
        return TerminationPayout(
            rule_applied="casual_payg_already_paid",
            amount=Decimal("0.00"),
            detail={"holiday_pay_method": holiday_pay_method},
        )

    if continuous_service_months < _VEST_MONTHS:
        amount = (Decimal(gross_earnings) * _PAYG_RATE).quantize(_CENTS)
        return TerminationPayout(
            rule_applied="pre_12mo_8pct",
            amount=amount,
            detail={
                "gross_earnings": str(gross_earnings),
                "rate": str(_PAYG_RATE),
                "continuous_service_months": continuous_service_months,
            },
        )

    weekly_hours = (
        Decimal(standard_hours_per_week)
        if standard_hours_per_week
        else _DEFAULT_WEEKLY_HOURS
    )
    if weekly_hours <= 0:
        weekly_hours = _DEFAULT_WEEKLY_HOURS
    weeks = Decimal(remaining_accrued_hours) / weekly_hours
    weekly_rate = max(Decimal(ordinary_weekly_pay), Decimal(average_weekly_earnings))
    amount = (weeks * weekly_rate).quantize(_CENTS)
    return TerminationPayout(
        rule_applied="post_12mo_accrued",
        amount=amount,
        detail={
            "remaining_accrued_hours": str(remaining_accrued_hours),
            "standard_hours_per_week": str(weekly_hours),
            "weeks": str(weeks),
            "ordinary_weekly_pay": str(ordinary_weekly_pay),
            "average_weekly_earnings": str(average_weekly_earnings),
            "weekly_rate_applied": str(weekly_rate),
            "continuous_service_months": continuous_service_months,
        },
    )
