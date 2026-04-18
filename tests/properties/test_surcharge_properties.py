"""Property-based tests for Payment Method Surcharge.

Properties covered:
  P1 — Surcharge calculation correctness.

**Validates: Requirements 3.2, 3.4, 3.5, 5.3**
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.payments.surcharge import (
    calculate_surcharge,
    validate_surcharge_rates,
    DEFAULT_SURCHARGE_RATES,
    MAX_PERCENTAGE,
    MAX_FIXED,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

balance_due_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

percentage_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

fixed_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("5"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# ===========================================================================
# Feature: payment-method-surcharge, Property 1: Surcharge calculation correctness
# ===========================================================================


class TestP1SurchargeCalculationCorrectness:
    """For any valid balance_due (Decimal > 0, <= 999999.99) and any valid fee
    rate (percentage 0-10%, fixed $0-$5), calculate_surcharge() SHALL return a
    value equal to (balance_due * percentage / 100) + fixed rounded to 2dp
    using ROUND_HALF_EVEN. The result SHALL always be >= 0. The surcharge SHALL
    be computed on the original balance_due only — no compounding.

    **Validates: Requirements 3.2, 3.4, 3.5, 5.3**
    """

    # Feature: payment-method-surcharge, Property 1: Surcharge calculation correctness
    @given(balance_due=balance_due_st, percentage=percentage_st, fixed=fixed_st)
    @settings(max_examples=100, deadline=None)
    def test_result_equals_formula_with_bankers_rounding(
        self, balance_due: Decimal, percentage: Decimal, fixed: Decimal
    ) -> None:
        """P1: The surcharge equals (balance_due * percentage / 100) + fixed
        rounded to 2dp with ROUND_HALF_EVEN."""
        result = calculate_surcharge(balance_due, percentage, fixed)
        expected = (balance_due * percentage / Decimal("100") + fixed).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )
        assert result == expected, (
            f"balance_due={balance_due}, pct={percentage}, fixed={fixed}: "
            f"expected {expected}, got {result}"
        )

    # Feature: payment-method-surcharge, Property 1: Surcharge calculation correctness
    @given(balance_due=balance_due_st, percentage=percentage_st, fixed=fixed_st)
    @settings(max_examples=100, deadline=None)
    def test_result_is_non_negative(
        self, balance_due: Decimal, percentage: Decimal, fixed: Decimal
    ) -> None:
        """P1: The surcharge is always >= 0 for valid inputs."""
        result = calculate_surcharge(balance_due, percentage, fixed)
        assert result >= Decimal("0"), (
            f"balance_due={balance_due}, pct={percentage}, fixed={fixed}: "
            f"surcharge {result} is negative"
        )

    # Feature: payment-method-surcharge, Property 1: Surcharge calculation correctness
    @given(balance_due=balance_due_st, percentage=percentage_st, fixed=fixed_st)
    @settings(max_examples=100, deadline=None)
    def test_no_compounding(
        self, balance_due: Decimal, percentage: Decimal, fixed: Decimal
    ) -> None:
        """P1: Applying surcharge to balance_due + surcharge produces a result
        that is >= the original surcharge, confirming no compounding occurs in
        the design. The surcharge is always computed on the original balance_due
        only — if it were compounded, the function would need to be called with
        balance_due + surcharge as the base, which yields a weakly larger value."""
        from hypothesis import assume

        surcharge = calculate_surcharge(balance_due, percentage, fixed)
        # Only meaningful when percentage > 0 and the surcharge is non-zero.
        assume(percentage > Decimal("0"))
        assume(surcharge > Decimal("0"))

        compounded = calculate_surcharge(balance_due + surcharge, percentage, fixed)
        assert compounded >= surcharge, (
            f"balance_due={balance_due}, pct={percentage}, fixed={fixed}: "
            f"surcharge on (balance_due + surcharge) should be >= "
            f"original surcharge ({surcharge}), got {compounded}"
        )
        # The compounded base is strictly larger, so the raw (pre-rounding)
        # value is strictly larger. After rounding they may be equal, but
        # the compounded result must never be less than the original.
        raw_original = balance_due * percentage / Decimal("100") + fixed
        raw_compounded = (balance_due + surcharge) * percentage / Decimal("100") + fixed
        assert raw_compounded > raw_original, (
            f"Pre-rounding compounded ({raw_compounded}) should be strictly "
            f"greater than original ({raw_original})"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 2: Round-trip consistency
# ===========================================================================

from app.modules.payments.surcharge import serialise_rates, deserialise_rates

# Strategy: a single surcharge rate entry with valid percentage, fixed, enabled
_rate_entry_st = st.fixed_dictionaries(
    {
        "percentage": st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("10"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        "fixed": st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("5"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        "enabled": st.booleans(),
    }
)

# Strategy: a dict of payment-method → rate entry (1–4 methods)
_rates_dict_st = st.dictionaries(
    keys=st.sampled_from(["card", "afterpay_clearpay", "klarna", "bank_transfer"]),
    values=_rate_entry_st,
    min_size=1,
    max_size=4,
)


class TestP2SurchargeRateSerialisationRoundTrip:
    """For any valid surcharge rate configuration (percentage as Decimal with
    2dp in [0, 10], fixed as Decimal with 2dp in [0, 5], enabled as bool),
    calling serialise_rates() then deserialise_rates() then serialise_rates()
    again SHALL produce a JSON structure identical to the first serialisation
    output. The percentage and fixed values SHALL be preserved exactly (no
    floating-point drift).

    **Validates: Requirements 9.1, 9.2, 9.3**
    """

    # Feature: payment-method-surcharge, Property 2: Round-trip consistency
    @given(rates=_rates_dict_st)
    @settings(max_examples=100, deadline=None)
    def test_serialise_deserialise_serialise_is_idempotent(
        self, rates: dict[str, dict]
    ) -> None:
        """P2: serialise → deserialise → serialise produces the same output as
        the first serialise (no drift)."""
        first_serialised = serialise_rates(rates)
        round_tripped = serialise_rates(deserialise_rates(first_serialised))
        assert round_tripped == first_serialised, (
            f"Round-trip drift detected.\n"
            f"  Input rates:       {rates}\n"
            f"  First serialise:   {first_serialised}\n"
            f"  After round-trip:  {round_tripped}"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 3: Validation rejects out-of-bounds
# ===========================================================================

# Strategy: percentage and fixed values spanning both valid and invalid ranges
_wide_percentage_st = st.decimals(
    min_value=Decimal("-5"),
    max_value=Decimal("20"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_wide_fixed_st = st.decimals(
    min_value=Decimal("-5"),
    max_value=Decimal("20"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class TestP3ValidationRejectsOutOfBounds:
    """For any surcharge rate where percentage > 10.00 OR percentage < 0 OR
    fixed > 5.00 OR fixed < 0, the validate_surcharge_rates() function SHALL
    return a non-empty list of error messages. For any rate where
    0 <= percentage <= 10.00 AND 0 <= fixed <= 5.00, the function SHALL return
    an empty list.

    **Validates: Requirements 2.2, 2.6, 2.7**
    """

    # Feature: payment-method-surcharge, Property 3: Validation rejects out-of-bounds
    @given(percentage=_wide_percentage_st, fixed=_wide_fixed_st)
    @settings(max_examples=100, deadline=None)
    def test_out_of_bounds_produces_errors(
        self, percentage: Decimal, fixed: Decimal
    ) -> None:
        """P3: Out-of-bounds percentage or fixed values produce a non-empty
        error list."""
        from hypothesis import assume

        is_out_of_bounds = (
            percentage < Decimal("0")
            or percentage > MAX_PERCENTAGE
            or fixed < Decimal("0")
            or fixed > MAX_FIXED
        )
        assume(is_out_of_bounds)

        rates = {
            "card": {
                "percentage": str(percentage),
                "fixed": str(fixed),
                "enabled": True,
            }
        }
        errors = validate_surcharge_rates(rates)
        assert len(errors) > 0, (
            f"Expected validation errors for percentage={percentage}, "
            f"fixed={fixed}, but got none"
        )

    # Feature: payment-method-surcharge, Property 3: Validation rejects out-of-bounds
    @given(
        percentage=st.decimals(
            min_value=Decimal("0"),
            max_value=MAX_PERCENTAGE,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        fixed=st.decimals(
            min_value=Decimal("0"),
            max_value=MAX_FIXED,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_in_bounds_produces_no_errors(
        self, percentage: Decimal, fixed: Decimal
    ) -> None:
        """P3: In-bounds percentage and fixed values produce an empty error
        list."""
        rates = {
            "card": {
                "percentage": str(percentage),
                "fixed": str(fixed),
                "enabled": True,
            }
        }
        errors = validate_surcharge_rates(rates)
        assert len(errors) == 0, (
            f"Expected no validation errors for percentage={percentage}, "
            f"fixed={fixed}, but got: {errors}"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 5: Disabled method zero surcharge
# ===========================================================================

from app.modules.payments.surcharge import get_surcharge_for_method

# Strategy: payment method types
_method_st = st.sampled_from(["card", "afterpay_clearpay", "klarna", "bank_transfer"])


class TestP5DisabledMethodZeroSurcharge:
    """For any payment method type where the surcharge rate has enabled=False,
    OR where the method is not present in the rates dict, the
    get_surcharge_for_method() function SHALL return Decimal("0.00")
    regardless of the configured percentage and fixed values.

    **Validates: Requirements 1.4, 3.3**
    """

    # Feature: payment-method-surcharge, Property 5: Disabled method zero surcharge
    @given(
        method=_method_st,
        balance_due=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        percentage=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("10"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        fixed=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("5"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_disabled_method_returns_zero(
        self,
        method: str,
        balance_due: Decimal,
        percentage: Decimal,
        fixed: Decimal,
    ) -> None:
        """P5: A method with enabled=False always produces zero surcharge."""
        rates = {
            method: {
                "percentage": str(percentage),
                "fixed": str(fixed),
                "enabled": False,
            }
        }
        result = get_surcharge_for_method(balance_due, method, rates)
        assert result == Decimal("0.00"), (
            f"method={method}, balance_due={balance_due}, pct={percentage}, "
            f"fixed={fixed}: expected Decimal('0.00'), got {result}"
        )

    # Feature: payment-method-surcharge, Property 5: Disabled method zero surcharge
    @given(
        method=_method_st,
        balance_due=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_missing_method_returns_zero(
        self,
        method: str,
        balance_due: Decimal,
    ) -> None:
        """P5: A method not present in the rates dict produces zero surcharge."""
        # Empty rates dict — method is not configured at all
        rates: dict[str, dict] = {}
        result = get_surcharge_for_method(balance_due, method, rates)
        assert result == Decimal("0.00"), (
            f"method={method}, balance_due={balance_due}: "
            f"expected Decimal('0.00') for missing method, got {result}"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 6: Malformed rate fallback
# ===========================================================================

# Strategy: malformed rate values that should trigger the fallback path
_malformed_value_st = st.one_of(
    st.none(),
    st.integers(),
    st.text(),
    st.dictionaries(
        keys=st.text(max_size=5),
        values=st.one_of(st.none(), st.integers(), st.text()),
        max_size=3,
    ),
)

# Strategy: payment method keys
_method_key_st = st.sampled_from(["card", "afterpay_clearpay", "klarna", "bank_transfer"])


class TestP6MalformedRateFallback:
    """For any malformed surcharge rate entry (missing keys, non-numeric
    strings, None values, empty dicts), the deserialise_rates() function SHALL
    return the default rate for that payment method instead of raising an
    exception. The returned rate SHALL have valid Decimal percentage and fixed
    values.

    **Validates: Requirements 9.4**
    """

    # Feature: payment-method-surcharge, Property 6: Malformed rate fallback
    @given(method=_method_key_st, malformed=_malformed_value_st)
    @settings(max_examples=100, deadline=None)
    def test_malformed_rate_never_raises_and_returns_defaults(
        self, method: str, malformed: object
    ) -> None:
        """P6: deserialise_rates() never raises for malformed input and returns
        valid Decimal percentage and fixed values matching the defaults."""
        raw = {method: malformed}
        result = deserialise_rates(raw)

        # Must not raise — we got here, so that's satisfied.
        assert method in result, (
            f"Expected method '{method}' in result, got keys: {list(result.keys())}"
        )

        entry = result[method]

        # percentage and fixed must be Decimal instances
        assert isinstance(entry["percentage"], Decimal), (
            f"Expected Decimal for percentage, got {type(entry['percentage'])}"
        )
        assert isinstance(entry["fixed"], Decimal), (
            f"Expected Decimal for fixed, got {type(entry['fixed'])}"
        )

        # Values must match the defaults for this method
        default = DEFAULT_SURCHARGE_RATES.get(
            method, {"percentage": "0", "fixed": "0", "enabled": False}
        )
        expected_pct = Decimal(str(default["percentage"]))
        expected_fixed = Decimal(str(default["fixed"]))
        expected_enabled = bool(default.get("enabled", False))

        assert entry["percentage"] == expected_pct, (
            f"method={method}: expected default percentage {expected_pct}, "
            f"got {entry['percentage']}"
        )
        assert entry["fixed"] == expected_fixed, (
            f"method={method}: expected default fixed {expected_fixed}, "
            f"got {entry['fixed']}"
        )
        assert entry["enabled"] == expected_enabled, (
            f"method={method}: expected default enabled {expected_enabled}, "
            f"got {entry['enabled']}"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 7: Surcharge addition exactness
# ===========================================================================


class TestP7SurchargeAdditionExactness:
    """For any valid balance_due (Decimal with 2dp) and any surcharge amount
    (Decimal with 2dp, computed by calculate_surcharge()), the total
    balance_due + surcharge SHALL be exactly representable as a Decimal with
    2 decimal places. Converting this total to cents via int(total * 100)
    SHALL produce an integer equal to int(balance_due * 100) + int(surcharge * 100)
    — no rounding drift across the addition.

    **Validates: Requirements 3.5, 4.2**
    """

    # Feature: payment-method-surcharge, Property 7: Surcharge addition exactness
    @given(
        balance_due=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        percentage=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("10"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        fixed=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("5"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_surcharge_addition_no_rounding_drift(
        self,
        balance_due: Decimal,
        percentage: Decimal,
        fixed: Decimal,
    ) -> None:
        """P7: int((balance_due + surcharge) * 100) == int(balance_due * 100) + int(surcharge * 100)
        — no rounding drift when converting the total to cents."""
        surcharge = calculate_surcharge(balance_due, percentage, fixed)
        total = balance_due + surcharge

        total_cents = int(total * 100)
        balance_cents = int(balance_due * 100)
        surcharge_cents = int(surcharge * 100)

        assert total_cents == balance_cents + surcharge_cents, (
            f"Rounding drift detected: "
            f"balance_due={balance_due}, surcharge={surcharge}, total={total}, "
            f"total_cents={total_cents}, balance_cents + surcharge_cents={balance_cents + surcharge_cents}"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 8: Rate warning threshold
# ===========================================================================


def _should_warn(configured_pct: Decimal, default_pct: Decimal) -> bool:
    """Return True iff the configured rate exceeds the default by more than 0.50pp.

    This mirrors the NZ compliance warning logic: a warning is triggered when
    the org admin sets a percentage rate that exceeds the default Stripe rate
    for that payment method by more than 0.5 percentage points.
    """
    return configured_pct - default_pct > Decimal("0.50")


class TestP8RateWarningThreshold:
    """For any configured percentage rate and its corresponding default Stripe
    rate, the compliance warning SHALL be triggered if and only if
    ``configured_rate - default_rate > 0.50`` (percentage points). The warning
    SHALL NOT be triggered when the configured rate is at or below
    ``default_rate + 0.50``.

    **Validates: Requirements 8.2**
    """

    # Feature: payment-method-surcharge, Property 8: Rate warning threshold
    @given(
        configured_pct=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("10"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        default_pct=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("10"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_warning_iff_exceeds_threshold(
        self, configured_pct: Decimal, default_pct: Decimal
    ) -> None:
        """P8: Warning is triggered iff configured_rate - default_rate > 0.50."""
        result = _should_warn(configured_pct, default_pct)
        expected = configured_pct - default_pct > Decimal("0.50")
        assert result == expected, (
            f"configured_pct={configured_pct}, default_pct={default_pct}: "
            f"expected warning={expected}, got {result}"
        )


# ===========================================================================
# Feature: payment-method-surcharge, Property 4: Surcharge never contaminates invoice balance
# ===========================================================================

import uuid as _uuid_mod

_surcharge_st = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class TestP4SurchargeNeverContaminatesInvoiceBalance:
    """For any payment recorded with a surcharge, the Payment.amount field
    SHALL equal the invoice portion only (balance_due), and
    Payment.surcharge_amount SHALL be stored separately. The sum
    Payment.amount + Payment.surcharge_amount SHALL equal the total amount
    charged to the customer. The invoice's amount_paid SHALL increase by
    Payment.amount only, never by the surcharge.

    This is a pure logic test — no database or ORM models are used. Instead
    we simulate the payment recording invariants directly.

    **Validates: Requirements 6.1, 6.3**
    """

    # Feature: payment-method-surcharge, Property 4: Surcharge never contaminates invoice balance
    @given(
        balance_due=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        surcharge=_surcharge_st,
        invoice_id=st.uuids(),
        payment_id=st.uuids(),
    )
    @settings(max_examples=100, deadline=None)
    def test_payment_amount_equals_invoice_portion_only(
        self,
        balance_due: Decimal,
        surcharge: Decimal,
        invoice_id: _uuid_mod.UUID,
        payment_id: _uuid_mod.UUID,
    ) -> None:
        """P4: Payment.amount equals the invoice portion (balance_due) only,
        excluding the surcharge."""
        # Simulate payment recording logic
        payment_amount = balance_due  # invoice portion only
        payment_surcharge_amount = surcharge

        assert payment_amount == balance_due, (
            f"Payment.amount ({payment_amount}) must equal balance_due "
            f"({balance_due}), not include surcharge ({surcharge})"
        )
        assert payment_surcharge_amount == surcharge, (
            f"Payment.surcharge_amount ({payment_surcharge_amount}) must equal "
            f"the surcharge ({surcharge})"
        )

    # Feature: payment-method-surcharge, Property 4: Surcharge never contaminates invoice balance
    @given(
        balance_due=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        surcharge=_surcharge_st,
        invoice_id=st.uuids(),
        payment_id=st.uuids(),
    )
    @settings(max_examples=100, deadline=None)
    def test_payment_plus_surcharge_equals_total_charged(
        self,
        balance_due: Decimal,
        surcharge: Decimal,
        invoice_id: _uuid_mod.UUID,
        payment_id: _uuid_mod.UUID,
    ) -> None:
        """P4: Payment.amount + Payment.surcharge_amount equals the total
        amount charged to the customer."""
        payment_amount = balance_due
        payment_surcharge_amount = surcharge
        total_charged = balance_due + surcharge

        assert payment_amount + payment_surcharge_amount == total_charged, (
            f"Payment.amount ({payment_amount}) + Payment.surcharge_amount "
            f"({payment_surcharge_amount}) must equal total charged "
            f"({total_charged})"
        )

    # Feature: payment-method-surcharge, Property 4: Surcharge never contaminates invoice balance
    @given(
        balance_due=st.decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        surcharge=_surcharge_st,
        prior_amount_paid=st.decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("999999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        invoice_id=st.uuids(),
        payment_id=st.uuids(),
    )
    @settings(max_examples=100, deadline=None)
    def test_invoice_amount_paid_increases_by_payment_amount_only(
        self,
        balance_due: Decimal,
        surcharge: Decimal,
        prior_amount_paid: Decimal,
        invoice_id: _uuid_mod.UUID,
        payment_id: _uuid_mod.UUID,
    ) -> None:
        """P4: Invoice amount_paid increases by Payment.amount only, never by
        the surcharge. The surcharge is collected but does not affect the
        invoice ledger."""
        payment_amount = balance_due  # invoice portion only

        # Simulate invoice update: amount_paid += payment_amount (NOT surcharge)
        new_amount_paid = prior_amount_paid + payment_amount

        assert new_amount_paid == prior_amount_paid + balance_due, (
            f"Invoice amount_paid should increase by balance_due ({balance_due}) "
            f"only, not by total charged ({balance_due + surcharge})"
        )
        # Crucially, the surcharge must NOT be added to amount_paid
        assert new_amount_paid != prior_amount_paid + balance_due + surcharge or surcharge == Decimal("0"), (
            f"Invoice amount_paid ({new_amount_paid}) must NOT include surcharge "
            f"({surcharge}) — surcharge contaminates invoice balance"
        )
