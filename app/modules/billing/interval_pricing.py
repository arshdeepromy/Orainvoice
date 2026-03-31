"""Pure pricing functions for flexible billing intervals.

All monetary calculations use Decimal with ROUND_HALF_UP rounding.
No side effects — these functions are safe to call from any context.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

BillingInterval = Literal["weekly", "fortnightly", "monthly", "annual"]

INTERVAL_PERIODS_PER_YEAR: dict[str, int] = {
    "weekly": 52,
    "fortnightly": 26,
    "monthly": 12,
    "annual": 1,
}

_ALL_INTERVALS = list(INTERVAL_PERIODS_PER_YEAR.keys())

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0")
_TWELVE = Decimal("12")
_HUNDRED = Decimal("100")


def compute_effective_price(
    base_monthly_price: Decimal,
    interval: BillingInterval,
    discount_percent: Decimal,
) -> Decimal:
    """Compute the per-cycle effective price for a billing interval.

    Formula:
        annualised = base_monthly_price × 12
        per_cycle  = annualised / periods_per_year
        effective  = per_cycle × (1 − discount_percent / 100)
        rounded to 2 decimal places (ROUND_HALF_UP)

    Returns Decimal("0") for free plans (base_monthly_price == 0).
    """
    if base_monthly_price == _ZERO:
        return _ZERO

    periods = Decimal(INTERVAL_PERIODS_PER_YEAR[interval])
    per_cycle = base_monthly_price * _TWELVE / periods
    effective = per_cycle * (_HUNDRED - discount_percent) / _HUNDRED
    return effective.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_savings_amount(
    base_monthly_price: Decimal,
    interval: BillingInterval,
    discount_percent: Decimal,
) -> Decimal:
    """Savings per cycle = undiscounted interval price − effective price."""
    undiscounted = compute_effective_price(base_monthly_price, interval, _ZERO)
    effective = compute_effective_price(base_monthly_price, interval, discount_percent)
    return (undiscounted - effective).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_equivalent_monthly(
    effective_price: Decimal,
    interval: BillingInterval,
) -> Decimal:
    """Convert a per-cycle effective price back to its monthly equivalent.

    equivalent_monthly = effective_price × periods_per_year / 12
    """
    periods = Decimal(INTERVAL_PERIODS_PER_YEAR[interval])
    return (effective_price * periods / _TWELVE).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )


def validate_interval_config(config: list[dict]) -> list[dict]:
    """Validate interval configuration.

    Rules:
    - At least one interval must be enabled.
    - Each discount_percent must be in [0, 100].

    Returns the normalised config on success.
    Raises ValueError on invalid input.
    """
    if not config:
        raise ValueError("Interval config must not be empty.")

    has_enabled = False
    for item in config:
        discount = item.get("discount_percent", 0)
        if discount < 0 or discount > 100:
            raise ValueError(
                f"Discount percent must be between 0 and 100, got {discount}."
            )
        if item.get("enabled", False):
            has_enabled = True

    if not has_enabled:
        raise ValueError("At least one billing interval must be enabled.")

    return config


def build_default_interval_config() -> list[dict]:
    """Return the default config: monthly enabled at 0% discount, others disabled."""
    return [
        {
            "interval": interval,
            "enabled": interval == "monthly",
            "discount_percent": 0,
        }
        for interval in _ALL_INTERVALS
    ]


def apply_coupon_to_interval_price(
    effective_price: Decimal,
    coupon_discount_type: str,
    coupon_discount_value: Decimal,
) -> Decimal:
    """Apply a coupon discount on top of the interval effective price.

    - percentage: round(price × (1 − value / 100), 2)
    - fixed:      max(0, round(price − value, 2))
    """
    if coupon_discount_type == "percentage":
        result = effective_price * (_HUNDRED - coupon_discount_value) / _HUNDRED
    elif coupon_discount_type in ("fixed", "fixed_amount"):
        result = effective_price - coupon_discount_value
        if result < _ZERO:
            result = _ZERO
    else:
        return effective_price

    return result.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def convert_coupon_duration_to_cycles(
    duration_months: int,
    interval: BillingInterval,
) -> int:
    """Convert coupon duration_months to equivalent billing cycles.

    cycles = duration_months × periods_per_year / 12, rounded to nearest int.
    """
    periods = INTERVAL_PERIODS_PER_YEAR[interval]
    return round(duration_months * periods / 12)

def compute_interval_duration(
    interval: BillingInterval,
) -> "timedelta | relativedelta":
    """Return the duration for a billing interval.

    - weekly: timedelta(days=7)
    - fortnightly: timedelta(days=14)
    - monthly: relativedelta(months=1)
    - annual: relativedelta(years=1)
    """
    from datetime import timedelta

    from dateutil.relativedelta import relativedelta

    _INTERVAL_DURATIONS: dict[str, timedelta | relativedelta] = {
        "weekly": timedelta(days=7),
        "fortnightly": timedelta(days=14),
        "monthly": relativedelta(months=1),
        "annual": relativedelta(years=1),
    }
    return _INTERVAL_DURATIONS[interval]


def normalise_to_mrr(
    effective_price: Decimal,
    interval: BillingInterval,
) -> Decimal:
    """Normalise an interval effective price to monthly equivalent for MRR.

    MRR = effective_price × periods_per_year / 12
    """
    periods = Decimal(INTERVAL_PERIODS_PER_YEAR[interval])
    return (effective_price * periods / _TWELVE).quantize(
        _TWO_PLACES, rounding=ROUND_HALF_UP
    )
