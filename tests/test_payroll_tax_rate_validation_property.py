"""Property-based test for Property 11: rate / cap / threshold / IETC / secondary validation.

# Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

``app.modules.payroll_tax.validation.validate_config_fragment`` is a **pure**
function over a sparse ``fragment`` dict: it validates only the Tax_Fields that
are present and returns a list of
:class:`~app.modules.payroll_tax.schemas.FieldError` (``[]`` == valid). This is a
pure / in-memory property test (no database): it generates fragments that violate
each Req-8 rule and asserts the offending field is flagged, and generates valid
fragments and asserts they pass.

Rules exercised (one generator per rule):

* **Out-of-bounds fractional rates** (Req 8.1) — ``acc_levy_rate``,
  ``student_loan_rate``, each ``secondary_rates`` value, and
  ``ietc.abatement_rate`` must lie in ``[0, 1]``.
* **Out-of-bounds KiwiSaver percent defaults** (Req 8.1) —
  ``default_kiwisaver_employee_rate`` / ``default_kiwisaver_employer_rate`` must
  lie in ``[0, 100]``.
* **Non-positive ACC cap** (Req 8.2) — ``acc_max_liable_earnings`` must be
  ``> 0``.
* **Negative student-loan threshold** (Req 8.3) — ``student_loan_threshold``
  must be ``>= 0``.
* **Mis-ordered IETC bounds** (Req 8.4) — ``lower <= abatement_start <= upper``.
* **Incomplete secondary map** (Req 8.5) — a present ``secondary_rates`` must
  contain all of ``SB, S, SH, ST, SA``.

Each invalid fragment contains exactly the field under test (other Req-8 fields
absent), so the only possible error is for that field; we assert at least one
returned error names it. The valid generator builds every Req-8 field within its
permitted bounds and asserts ``validate_config_fragment`` returns ``[]``.

PAYE-bracket validation (Req 7) is the subject of a separate property
(Property 10, task 3.2) and is deliberately not exercised here.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.payroll_tax.schemas import SECONDARY_CODES
from app.modules.payroll_tax.validation import validate_config_fragment

# ---------------------------------------------------------------------------
# Hypothesis configuration — validation is a fast pure function.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=150, deadline=None)


# ---------------------------------------------------------------------------
# Value strategies. Numbers are emitted as strings so they round-trip exactly
# through the validator's ``Decimal(str(value))`` coercion (no float drift).
# ---------------------------------------------------------------------------


def _dec(lo: str, hi: str, places: int = 4) -> st.SearchStrategy[Decimal]:
    return st.decimals(
        min_value=Decimal(lo),
        max_value=Decimal(hi),
        places=places,
        allow_nan=False,
        allow_infinity=False,
    )


# --- valid values ----------------------------------------------------------
valid_rate = _dec("0", "1", 4).map(str)
valid_percent = _dec("0", "100", 2).map(str)
valid_acc_cap = _dec("0.01", "1000000", 2).map(str)
valid_sl_threshold = _dec("0", "500000", 2).map(str)
valid_amount = _dec("0", "5000", 2).map(str)
valid_bound = _dec("0", "200000", 2).map(str)

# --- out-of-bounds values --------------------------------------------------
# Strictly outside [0, 1] (either below 0 or above 1).
invalid_rate = st.one_of(
    _dec("-10000", "-0.0001", 4),
    _dec("1.0001", "10000", 4),
).map(str)

# Strictly outside [0, 100].
invalid_percent = st.one_of(
    _dec("-10000", "-0.01", 2),
    _dec("100.01", "100000", 2),
).map(str)

# ACC cap must be > 0; anything <= 0 is invalid.
invalid_acc_cap = _dec("-100000", "0", 2).map(str)

# Student-loan threshold must be >= 0; anything < 0 is invalid.
invalid_sl_threshold = _dec("-100000", "-0.01", 2).map(str)


# ---------------------------------------------------------------------------
# Composite strategies for the structured fields.
# ---------------------------------------------------------------------------


@st.composite
def valid_secondary(draw) -> dict:
    """A complete secondary map with every code present and in [0, 1]."""
    return {code: draw(valid_rate) for code in SECONDARY_CODES}


@st.composite
def incomplete_secondary(draw) -> dict:
    """A secondary map missing at least one required code (Req 8.5)."""
    codes = list(SECONDARY_CODES)
    # A proper subset of at most len-1 codes -> at least one code is missing.
    subset = draw(
        st.lists(
            st.sampled_from(codes),
            unique=True,
            min_size=0,
            max_size=len(codes) - 1,
        )
    )
    return {code: draw(valid_rate) for code in subset}


@st.composite
def secondary_with_bad_rate(draw) -> dict:
    """A complete secondary map where exactly one code has an out-of-bounds rate (Req 8.1)."""
    rates = {code: draw(valid_rate) for code in SECONDARY_CODES}
    bad_code = draw(st.sampled_from(list(SECONDARY_CODES)))
    rates[bad_code] = draw(invalid_rate)
    return rates


@st.composite
def valid_ietc(draw) -> dict:
    """IETC params with non-decreasing bounds and an in-range abatement rate."""
    bounds = draw(
        st.lists(_dec("0", "200000", 2), min_size=3, max_size=3).map(sorted)
    )
    lower, abatement_start, upper = bounds
    return {
        "amount": draw(valid_amount),
        "lower": str(lower),
        "abatement_start": str(abatement_start),
        "abatement_rate": draw(valid_rate),
        "upper": str(upper),
    }


@st.composite
def misordered_ietc(draw) -> dict:
    """IETC params whose bounds are NOT non-decreasing (Req 8.4).

    Three distinct values are drawn and arranged into an ordering that always
    breaks ``lower <= abatement_start <= upper`` (here ``lower`` is the largest),
    while keeping the abatement rate valid so the ordering rule is the sole
    cause of failure.
    """
    vals = draw(
        st.lists(_dec("0", "200000", 2), min_size=3, max_size=3, unique=True).map(
            sorted
        )
    )
    a, b, c = vals  # a < b < c
    # lower = c (largest) guarantees lower > abatement_start, breaking the order.
    return {
        "amount": draw(valid_amount),
        "lower": str(c),
        "abatement_start": str(a),
        "abatement_rate": draw(valid_rate),
        "upper": str(b),
    }


# ---------------------------------------------------------------------------
# Helper: assert at least one returned error names ``field``.
# ---------------------------------------------------------------------------


def _assert_flags(fragment: dict, field: str) -> None:
    errors = validate_config_fragment(fragment)
    assert errors, f"expected a validation error for {field!r}, got none: {fragment!r}"
    assert any(
        e.field == field for e in errors
    ), f"expected an error naming {field!r}, got fields {[e.field for e in errors]}"


# ---------------------------------------------------------------------------
# Invalid-value properties (Req 8.1, 8.2, 8.3, 8.4, 8.5).
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(value=invalid_rate, key=st.sampled_from(["acc_levy_rate", "student_loan_rate"]))
def test_out_of_bounds_fractional_rate_rejected(value: str, key: str):
    """Property 11: an out-of-bounds fractional rate is rejected (Req 8.1).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.1**
    """
    _assert_flags({key: value}, key)


@PBT_SETTINGS
@given(
    value=invalid_percent,
    key=st.sampled_from(
        ["default_kiwisaver_employee_rate", "default_kiwisaver_employer_rate"]
    ),
)
def test_out_of_bounds_kiwisaver_percent_rejected(value: str, key: str):
    """Property 11: an out-of-bounds KiwiSaver percent default is rejected (Req 8.1).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.1**
    """
    _assert_flags({key: value}, key)


@PBT_SETTINGS
@given(rates=secondary_with_bad_rate())
def test_out_of_bounds_secondary_rate_rejected(rates: dict):
    """Property 11: an out-of-bounds secondary rate is rejected (Req 8.1).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.1**
    """
    _assert_flags({"secondary_rates": rates}, "secondary_rates")


@PBT_SETTINGS
@given(rate=invalid_rate, ietc=valid_ietc())
def test_out_of_bounds_ietc_abatement_rate_rejected(rate: str, ietc: dict):
    """Property 11: an out-of-bounds IETC abatement rate is rejected (Req 8.1).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.1**
    """
    ietc = {**ietc, "abatement_rate": rate}
    _assert_flags({"ietc": ietc}, "ietc")


@PBT_SETTINGS
@given(value=invalid_acc_cap)
def test_non_positive_acc_cap_rejected(value: str):
    """Property 11: a non-positive ACC cap is rejected (Req 8.2).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.2**
    """
    _assert_flags({"acc_max_liable_earnings": value}, "acc_max_liable_earnings")


@PBT_SETTINGS
@given(value=invalid_sl_threshold)
def test_negative_student_loan_threshold_rejected(value: str):
    """Property 11: a negative student-loan threshold is rejected (Req 8.3).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.3**
    """
    _assert_flags({"student_loan_threshold": value}, "student_loan_threshold")


@PBT_SETTINGS
@given(ietc=misordered_ietc())
def test_misordered_ietc_bounds_rejected(ietc: dict):
    """Property 11: mis-ordered IETC bounds are rejected (Req 8.4).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.4**
    """
    _assert_flags({"ietc": ietc}, "ietc")


@PBT_SETTINGS
@given(rates=incomplete_secondary())
def test_incomplete_secondary_map_rejected(rates: dict):
    """Property 11: an incomplete secondary map is rejected (Req 8.5).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.5**
    """
    _assert_flags({"secondary_rates": rates}, "secondary_rates")


# ---------------------------------------------------------------------------
# Valid-fragment property: every Req-8 field within bounds passes (returns []).
# ---------------------------------------------------------------------------


@st.composite
def valid_fragment(draw) -> dict:
    """A fragment with every Req-8 field present and within its permitted bounds."""
    return {
        "acc_levy_rate": draw(valid_rate),
        "student_loan_rate": draw(valid_rate),
        "secondary_rates": draw(valid_secondary()),
        "ietc": draw(valid_ietc()),
        "default_kiwisaver_employee_rate": draw(valid_percent),
        "default_kiwisaver_employer_rate": draw(valid_percent),
        "acc_max_liable_earnings": draw(valid_acc_cap),
        "student_loan_threshold": draw(valid_sl_threshold),
    }


@PBT_SETTINGS
@given(fragment=valid_fragment())
def test_valid_rate_fragments_pass(fragment: dict):
    """Property 11: a fully valid Req-8 fragment passes validation (returns []).

    # Feature: payroll-tax-settings, Property 11: Invalid rates, caps, thresholds, IETC ordering, and secondary sets are rejected and not persisted

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
    """
    errors = validate_config_fragment(fragment)
    assert errors == [], f"valid fragment was rejected: {[ (e.field, e.message) for e in errors ]}"
