"""Surcharge calculation engine.

Pure functions for computing payment method surcharges.
No database or I/O dependencies — all inputs are passed explicitly.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_EVEN

logger = logging.getLogger(__name__)

# Default NZ Stripe Connect fee rates
DEFAULT_SURCHARGE_RATES: dict[str, dict] = {
    "card": {"percentage": "2.90", "fixed": "0.30", "enabled": True},
    "afterpay_clearpay": {"percentage": "6.00", "fixed": "0.30", "enabled": True},
    "klarna": {"percentage": "5.99", "fixed": "0.00", "enabled": True},
    "bank_transfer": {"percentage": "1.00", "fixed": "0.00", "enabled": True},
}

# Validation limits
MAX_PERCENTAGE = Decimal("10.00")
MAX_FIXED = Decimal("5.00")


def calculate_surcharge(
    balance_due: Decimal,
    percentage: Decimal,
    fixed: Decimal,
) -> Decimal:
    """Compute surcharge amount using banker's rounding.

    Uses the **gross-up** formula so the merchant nets the original
    ``balance_due`` after Stripe's processing fee is deducted from the
    gross charge. Naive ``balance × p + fixed`` causes a small but
    systematic shortfall: Stripe charges its fee on
    ``balance + surcharge`` (the gross), not on ``balance``. The
    delta is approximately ``balance × p²`` per transaction — small
    per charge, but compounding monthly across an org's volume.

    Gross-up derivation (assuming Stripe's fee schedule matches the
    surcharge schedule, i.e. the merchant is recovering exactly the
    cost of acceptance, NZ Commerce Commission compliant)::

        gross = balance + surcharge
        stripe_fee = gross × p + fixed
        net = gross − stripe_fee = balance   (target)

        ⇒ surcharge = (balance × p + fixed) / (1 − p)

    The non-compounding invariant still holds: the surcharge is
    derived from the **original** ``balance_due``, not from a
    recursive application to itself.

    Edge case: when ``percentage >= 100%`` the gross-up is
    mathematically undefined (would require infinite surcharge to
    recover). ``MAX_PERCENTAGE = 10%`` keeps the denominator at
    ``≥ 0.90`` so this is unreachable for any configured rate, but
    we still guard explicitly.
    """
    pct_decimal = percentage / Decimal("100")
    if pct_decimal >= Decimal("1"):
        # Defensive fallback — return the naive surcharge so we never
        # divide by zero or a negative number even if a future config
        # ever bypasses validation. Caller will still display *something*
        # rather than crashing.
        raw = balance_due * pct_decimal + fixed
    else:
        numerator = balance_due * pct_decimal + fixed
        denominator = Decimal("1") - pct_decimal
        raw = numerator / denominator
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def get_surcharge_for_method(
    balance_due: Decimal,
    payment_method_type: str,
    surcharge_rates: dict[str, dict],
) -> Decimal:
    """Get the surcharge amount for a specific payment method.

    Returns Decimal("0.00") if the method is not configured or disabled.
    """
    rate = surcharge_rates.get(payment_method_type)
    if not rate or not rate.get("enabled", False):
        return Decimal("0.00")
    pct = Decimal(str(rate.get("percentage", "0")))
    fixed = Decimal(str(rate.get("fixed", "0")))
    return calculate_surcharge(balance_due, pct, fixed)


def validate_surcharge_rates(rates: dict[str, dict]) -> list[str]:
    """Validate surcharge rate configuration. Returns list of error messages."""
    errors = []
    for method, rate in rates.items():
        try:
            pct = Decimal(str(rate.get("percentage", "0")))
            fixed = Decimal(str(rate.get("fixed", "0")))
        except Exception:
            errors.append(f"{method}: invalid numeric values")
            continue
        if pct < 0:
            errors.append(f"{method}: percentage must not be negative")
        if pct > MAX_PERCENTAGE:
            errors.append(f"{method}: percentage must not exceed {MAX_PERCENTAGE}%")
        if fixed < 0:
            errors.append(f"{method}: fixed fee must not be negative")
        if fixed > MAX_FIXED:
            errors.append(f"{method}: fixed fee must not exceed ${MAX_FIXED}")
    return errors


def serialise_rates(rates: dict[str, dict]) -> dict[str, dict]:
    """Serialise surcharge rates to JSON-safe format with string decimals."""
    result = {}
    for method, rate in rates.items():
        result[method] = {
            "percentage": f"{Decimal(str(rate.get('percentage', '0'))):.2f}",
            "fixed": f"{Decimal(str(rate.get('fixed', '0'))):.2f}",
            "enabled": bool(rate.get("enabled", False)),
        }
    return result


def deserialise_rates(
    raw: dict[str, dict],
    defaults: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Deserialise surcharge rates from JSON, falling back to defaults on error."""
    if defaults is None:
        defaults = DEFAULT_SURCHARGE_RATES
    result = {}
    for method, rate in raw.items():
        try:
            result[method] = {
                "percentage": Decimal(str(rate["percentage"])),
                "fixed": Decimal(str(rate["fixed"])),
                "enabled": bool(rate.get("enabled", False)),
            }
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "Malformed surcharge rate for %s, using default: %s", method, exc,
            )
            default = defaults.get(method, {"percentage": "0", "fixed": "0", "enabled": False})
            result[method] = {
                "percentage": Decimal(str(default["percentage"])),
                "fixed": Decimal(str(default["fixed"])),
                "enabled": bool(default.get("enabled", False)),
            }
    return result
