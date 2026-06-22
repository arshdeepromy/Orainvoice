"""Property-based test: emergency contact is all-or-nothing.

# Feature: staff-onboarding-link, Property 7: Emergency contact is all-or-nothing

**Validates: Requirements 4.3**

R4.3 requires that, on onboarding submit, the emergency contact *name* and
emergency contact *phone* are validated as a pair: both provided, or both
empty. The pure validator ``validate_emergency_contact(name, phone)``
(``app/modules/staff/onboarding_validation.py``) returns ``True`` exactly when
the two fields agree on presence and ``False`` otherwise, where **presence**
means "non-empty after stripping whitespace" — so ``None``, ``""`` and
whitespace-only strings (e.g. ``"   "``) all count as *empty*.

This is a pure, side-effect-free check, so it is exercised directly with no
database. We draw both fields from a mix of "empty-ish" values (``None``, the
empty string, whitespace-only strings) and genuinely present text, and assert
the result matches the all-or-nothing rule for every combination.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import validate_emergency_contact

# ---------------------------------------------------------------------------
# Hypothesis settings (≥100 iterations) — pure in-memory validation.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

# Values that count as ABSENT (empty after strip): None, "", and whitespace.
_absent_values = st.one_of(
    st.none(),
    st.just(""),
    st.text(alphabet=" \t\r\n\f\v", min_size=1, max_size=8),
)

# Values that count as PRESENT: text that is non-empty after stripping. We
# build them as optional surrounding whitespace around a non-whitespace core
# so the stripped result is guaranteed non-empty.
_present_values = st.builds(
    lambda pad_l, core, pad_r: f"{pad_l}{core}{pad_r}",
    st.text(alphabet=" \t", max_size=3),
    st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp")),
        min_size=1,
        max_size=20,
    ).filter(lambda s: s.strip() != ""),
    st.text(alphabet=" \t", max_size=3),
)

# Either kind of value for either field.
_any_value = st.one_of(_absent_values, _present_values)


def _is_present(value: object) -> bool:
    """Reference notion of presence: non-empty after strip; None ⇒ absent."""
    if value is None:
        return False
    return str(value).strip() != ""


# ---------------------------------------------------------------------------
# Property 7: Emergency contact is all-or-nothing
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(name=_any_value, phone=_any_value)
def test_emergency_contact_all_or_nothing(name: object, phone: object) -> None:
    """validate_emergency_contact is True iff name/phone agree on presence.

    Property 7 — for any (name, phone) drawn from present / empty / whitespace
    / None combinations, the validator returns ``True`` exactly when both are
    present or both are empty, and ``False`` when exactly one is present.

    **Validates: Requirements 4.3**
    """
    expected = _is_present(name) == _is_present(phone)
    assert validate_emergency_contact(name, phone) is expected


@PBT_SETTINGS
@given(name=_present_values, phone=_present_values)
def test_both_present_is_valid(name: str, phone: str) -> None:
    """Both fields present (after strip) ⇒ valid pairing.

    **Validates: Requirements 4.3**
    """
    assert validate_emergency_contact(name, phone) is True


@PBT_SETTINGS
@given(name=_absent_values, phone=_absent_values)
def test_both_empty_is_valid(name: object, phone: object) -> None:
    """Both fields empty (None / "" / whitespace) ⇒ valid pairing.

    **Validates: Requirements 4.3**
    """
    assert validate_emergency_contact(name, phone) is True


@PBT_SETTINGS
@given(present=_present_values, absent=_absent_values)
def test_exactly_one_present_is_invalid(present: str, absent: object) -> None:
    """Exactly one field present ⇒ invalid, in either field position.

    **Validates: Requirements 4.3**
    """
    assert validate_emergency_contact(present, absent) is False
    assert validate_emergency_contact(absent, present) is False
