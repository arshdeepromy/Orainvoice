"""Property-based test for Property 10: PAYE bracket validation.

# Feature: payroll-tax-settings, Property 10: Invalid PAYE bracket sets are rejected and not persisted

Exercises ``app.modules.payroll_tax.validation.validate_config_fragment`` (task
3.1), which is a **pure** function over a sparse ``fragment`` dict. This is a
pure, in-memory Hypothesis test — no database, no service layer — mirroring the
pure validation property tests already in the repo (e.g.
``tests/test_branding_upload_validation_property.py``).

The property under test
------------------------
For the ``paye_brackets`` Tax_Field:

* A bracket set that violates **any** of the bracket rules is rejected — the
  validator returns a **non-empty** error list, and every returned error names
  the ``paye_brackets`` field. Because rejection means "SHALL NOT persist", a
  non-empty error list is the in-memory evidence that the submission cannot be
  saved.
* A well-formed bracket set is accepted — when the fragment carries only
  ``paye_brackets`` and the schedule is valid, the validator returns ``[]``.

The bracket rules (Req 7.1–7.5):

* 7.4 — at least one band (an empty set is rejected)
* 7.5 — every finite ``upper_limit`` strictly greater than zero
* 7.1 — finite ``upper_limit`` values strictly ascending
* 7.2 — exactly one open-ended top band, and it must be last
* 7.3 — every ``rate`` in ``[0, 1]`` inclusive

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.payroll_tax.validation import validate_config_fragment

# ---------------------------------------------------------------------------
# Building blocks.
# ---------------------------------------------------------------------------

# Rates strictly inside the permitted [0, 1] range, generated as exact Decimals
# (the validator coerces via ``Decimal(str(value))``).
_valid_rate = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1"),
    places=4,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _ascending_limits(draw, n: int) -> list[int]:
    """Generate ``n`` strictly ascending, strictly positive finite limits."""
    current = draw(st.integers(min_value=1, max_value=1000))
    limits: list[int] = []
    for _ in range(n):
        limits.append(current)
        current += draw(st.integers(min_value=1, max_value=5000))
    return limits


@st.composite
def _valid_brackets(draw) -> list[dict]:
    """A well-formed PAYE_Bracket_Set: ascending positive finite bands plus a
    single open-ended top band, all rates in ``[0, 1]`` (satisfies Req 7.1–7.5)."""
    n_finite = draw(st.integers(min_value=0, max_value=4))
    limits = draw(_ascending_limits(n_finite))
    bands = [
        {"upper_limit": limit, "rate": draw(_valid_rate)} for limit in limits
    ]
    bands.append({"upper_limit": None, "rate": draw(_valid_rate)})
    return bands


# ---------------------------------------------------------------------------
# Invalid bracket-set generators — each guaranteed to violate exactly one rule.
# ---------------------------------------------------------------------------


#: Violates Req 7.4: fewer than one band.
_empty_set = st.just([])


@st.composite
def _non_positive_finite_limit(draw) -> list[dict]:
    """Violates Req 7.5: a finite ``upper_limit`` that is not greater than zero."""
    bands = draw(_valid_brackets())
    # Insert a finite band with a non-positive limit ahead of the top band.
    bad_limit = draw(
        st.one_of(
            st.just(Decimal("0")),
            st.decimals(
                min_value=Decimal("-100000"),
                max_value=Decimal("-0.01"),
                places=2,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    bands.insert(0, {"upper_limit": bad_limit, "rate": draw(_valid_rate)})
    return bands


@st.composite
def _non_ascending_limits(draw) -> list[dict]:
    """Violates Req 7.1: finite ``upper_limit`` values not strictly ascending."""
    first = draw(st.integers(min_value=1, max_value=100000))
    # second <= first guarantees the pair is not strictly ascending.
    second = draw(st.integers(min_value=1, max_value=first))
    return [
        {"upper_limit": first, "rate": draw(_valid_rate)},
        {"upper_limit": second, "rate": draw(_valid_rate)},
        {"upper_limit": None, "rate": draw(_valid_rate)},
    ]


@st.composite
def _no_open_ended_top_band(draw) -> list[dict]:
    """Violates Req 7.2: no open-ended top band (every band is finite)."""
    n = draw(st.integers(min_value=1, max_value=4))
    limits = draw(_ascending_limits(n))
    return [{"upper_limit": limit, "rate": draw(_valid_rate)} for limit in limits]


@st.composite
def _multiple_open_ended_bands(draw) -> list[dict]:
    """Violates Req 7.2: more than one open-ended band."""
    bands = draw(_valid_brackets())
    bands.append({"upper_limit": None, "rate": draw(_valid_rate)})
    return bands


@st.composite
def _rate_out_of_range(draw) -> list[dict]:
    """Violates Req 7.3: a ``rate`` outside the inclusive range ``[0, 1]``."""
    bands = draw(_valid_brackets())
    bad_rate = draw(
        st.one_of(
            st.decimals(
                min_value=Decimal("1.0001"),
                max_value=Decimal("100"),
                places=4,
                allow_nan=False,
                allow_infinity=False,
            ),
            st.decimals(
                min_value=Decimal("-100"),
                max_value=Decimal("-0.0001"),
                places=4,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )
    # Corrupt the rate of an arbitrary band.
    index = draw(st.integers(min_value=0, max_value=len(bands) - 1))
    bands[index] = {**bands[index], "rate": bad_rate}
    return bands


_invalid_brackets = st.one_of(
    _empty_set,
    _non_positive_finite_limit(),
    _non_ascending_limits(),
    _no_open_ended_top_band(),
    _multiple_open_ended_bands(),
    _rate_out_of_range(),
)


# ---------------------------------------------------------------------------
# Property 10: Invalid PAYE bracket sets are rejected and not persisted.
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(brackets=_invalid_brackets)
def test_invalid_bracket_sets_are_rejected(brackets: list[dict]):
    """Property 10 (rejection half): invalid bracket sets yield a non-empty
    error list naming ``paye_brackets``, so the submission cannot be persisted.

    # Feature: payroll-tax-settings, Property 10: Invalid PAYE bracket sets are rejected and not persisted

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
    """
    errors = validate_config_fragment({"paye_brackets": brackets})
    assert errors, f"expected a validation error for invalid brackets: {brackets!r}"
    assert all(
        error.field == "paye_brackets" for error in errors
    ), f"every error must name the paye_brackets field: {errors!r}"
    assert all(
        error.message for error in errors
    ), "every error must carry a non-empty human-readable message"


@settings(max_examples=200, deadline=None)
@given(brackets=_valid_brackets())
def test_valid_bracket_sets_are_accepted(brackets: list[dict]):
    """Property 10 (acceptance half): a well-formed bracket set produces no
    errors when it is the only field in the fragment.

    # Feature: payroll-tax-settings, Property 10: Invalid PAYE bracket sets are rejected and not persisted

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**
    """
    errors = validate_config_fragment({"paye_brackets": brackets})
    assert errors == [], (
        f"expected no validation errors for a valid bracket set, got {errors!r} "
        f"for {brackets!r}"
    )
