"""Property-based test for Property 12: Validation errors identify the failing field.

# Feature: payroll-tax-settings, Property 12: Validation errors identify the failing field

Exercises ``app.modules.payroll_tax.validation.validate_config_fragment`` (task 3.1)
as a **pure, in-memory** function — no database, no event loop. This is a separate
test module from the bracket (task 3.2) and rate/cap/threshold/IETC/secondary
(task 3.3) property tests so the strategies and ``settings`` do not collide.

The property under test
------------------------
For *any* fragment submitted to ``validate_config_fragment`` — including
deliberately invalid ones — every :class:`FieldError` it returns must:

* name a **recognised Tax_Field** (one of the documented JSONB keys, or the
  synthetic ``"config"`` field used when the whole fragment is not an object); and
* carry a **non-empty, human-readable message** (Req 8.6).

In other words, the validator never emits an error against an unknown/blank
field name and never returns a blank message — even when the message-builder is
forced to fall back to the generic message (Req 8.7).

To make the property meaningful (rather than vacuously true on an all-valid
fragment that returns ``[]``), the generators below bias heavily toward
*invalid* fragments: out-of-range rates, non-ascending or open-band-less
brackets, non-positive caps, negative thresholds, mis-ordered IETC bounds,
incomplete secondary maps, unparseable junk values, and non-object fragments.

**Validates: Requirements 8.6**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.payroll_tax.schemas import SECONDARY_CODES, FieldError
from app.modules.payroll_tax.validation import validate_config_fragment

# ---------------------------------------------------------------------------
# The set of field names ``validate_config_fragment`` is allowed to name in a
# FieldError: the documented Tax_Field JSONB keys, plus the synthetic "config"
# field used when the fragment itself is not an object.
# ---------------------------------------------------------------------------

RECOGNISED_FIELDS: frozenset[str] = frozenset(
    {
        "paye_brackets",
        "secondary_rates",
        "acc_levy_rate",
        "acc_max_liable_earnings",
        "student_loan_rate",
        "student_loan_threshold",
        "ietc",
        "default_kiwisaver_employee_rate",
        "default_kiwisaver_employer_rate",
        "config",
    }
)


# ---------------------------------------------------------------------------
# Value strategies — a deliberately adversarial mix of valid, out-of-bounds,
# and outright junk values for each Tax_Field, so the validator is exercised
# across its whole error surface.
# ---------------------------------------------------------------------------

# Numbers that may be in-range, out-of-range, or extreme; emitted as float,
# int, or numeric string to also exercise the Decimal(str(...)) coercion path.
_numbers = st.one_of(
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False),
    st.integers(min_value=-1000, max_value=1_000_000),
    st.decimals(min_value=-5, max_value=5, places=4, allow_nan=False,
                allow_infinity=False).map(str),
)

# Junk values that cannot be parsed as numbers.
_junk = st.one_of(
    st.none(),
    st.text(max_size=8),
    st.booleans(),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=4), st.integers(), max_size=3),
)

_scalar_value = st.one_of(_numbers, _junk)


def _bracket():
    """A single PAYE bracket band; upper_limit may be a number, null, or junk."""
    return st.fixed_dictionaries(
        {
            "upper_limit": st.one_of(st.none(), _numbers, _junk),
            "rate": _scalar_value,
        }
    )


_brackets_value = st.one_of(
    st.lists(_bracket(), max_size=5),          # may lack/duplicate the open band
    st.just([]),                                # empty (Req 7.4)
    _junk,                                       # not a list at all
)

# Secondary map: possibly missing codes (Req 8.5) and/or out-of-range rates.
_secondary_value = st.one_of(
    st.dictionaries(
        st.sampled_from(SECONDARY_CODES + ("XX", "ZZ")),
        _scalar_value,
        max_size=7,
    ),
    _junk,
)

_ietc_value = st.one_of(
    st.fixed_dictionaries(
        {
            "amount": _scalar_value,
            "lower": _scalar_value,
            "abatement_start": _scalar_value,
            "abatement_rate": _scalar_value,
            "upper": _scalar_value,
        }
    ),
    st.dictionaries(st.text(max_size=6), _scalar_value, max_size=4),  # partial/odd
    _junk,
)

_FIELD_STRATEGIES: dict[str, st.SearchStrategy] = {
    "paye_brackets": _brackets_value,
    "secondary_rates": _secondary_value,
    "acc_levy_rate": _scalar_value,
    "acc_max_liable_earnings": _scalar_value,
    "student_loan_rate": _scalar_value,
    "student_loan_threshold": _scalar_value,
    "ietc": _ietc_value,
    "default_kiwisaver_employee_rate": _scalar_value,
    "default_kiwisaver_employer_rate": _scalar_value,
}


@st.composite
def _fragment(draw):
    """Generate a fragment, mostly an object with an adversarial subset of fields.

    With small probability the fragment is *not* a dict at all (to exercise the
    synthetic ``"config"`` field path). Otherwise it picks a non-empty subset of
    the recognised Tax_Fields and assigns each an adversarial value. A few
    unrecognised keys may also be sprinkled in — the validator must ignore them
    and never name them in an error.
    """
    if draw(st.integers(min_value=0, max_value=9)) == 0:
        # ~10% of the time: a non-object fragment (list, string, number, None).
        return draw(
            st.one_of(
                st.none(),
                st.integers(),
                st.text(max_size=8),
                st.lists(st.integers(), max_size=3),
            )
        )

    keys = draw(
        st.lists(
            st.sampled_from(list(_FIELD_STRATEGIES)),
            min_size=1,
            max_size=len(_FIELD_STRATEGIES),
            unique=True,
        )
    )
    fragment = {key: draw(_FIELD_STRATEGIES[key]) for key in keys}

    # Sprinkle in unrecognised keys the validator must ignore.
    for extra in draw(st.lists(st.text(max_size=5), max_size=2)):
        if extra not in _FIELD_STRATEGIES:
            fragment[extra] = draw(_scalar_value)

    return fragment


# ---------------------------------------------------------------------------
# Property 12: Validation errors identify the failing field.
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(fragment=_fragment())
def test_validation_errors_identify_the_failing_field(fragment):
    """Property 12: Validation errors identify the failing field.

    # Feature: payroll-tax-settings, Property 12: Validation errors identify the failing field

    For any fragment, every FieldError returned by ``validate_config_fragment``
    names a recognised Tax_Field and carries a non-empty message.

    **Validates: Requirements 8.6**
    """
    errors = validate_config_fragment(fragment)

    assert isinstance(errors, list)
    for error in errors:
        assert isinstance(error, FieldError)

        # Every error names a recognised Tax_Field (Req 8.6) — never an
        # unknown/blank field name.
        assert error.field in RECOGNISED_FIELDS, (
            f"error names unrecognised field {error.field!r}; "
            f"recognised fields are {sorted(RECOGNISED_FIELDS)}"
        )

        # Every error carries a non-empty, human-readable message (Req 8.6).
        assert isinstance(error.message, str)
        assert error.message.strip(), (
            f"error for field {error.field!r} has a blank message"
        )
