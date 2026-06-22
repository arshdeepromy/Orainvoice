"""Property-based tests for the blocking visa-expiry onboarding validator.

Property 13 — Visa types require a valid future expiry date (blocking).

The function under test is ``validate_visa_expiry(residency_type, expiry_date,
today=None)`` in ``app.modules.staff.onboarding_validation``. It returns
``True`` (the field is **acceptable**, submission may proceed) iff:

  * the residency type is NOT a visa type (``citizen`` / ``permanent_resident``
    / ``other``) — any (or no) date is fine; OR
  * the residency type IS a visa type (``work_visa`` / ``student_visa``) AND an
    expiry date is provided AND that date is strictly in the future
    (``expiry_date > today``).

For a visa type, a missing, past-dated, or current-dated (== today) value
returns ``False`` — the submit handler maps that to a **blocking**
``errors.visa_expiry_date`` (code ``visa_expiry_invalid``) so the form cannot
be submitted until a valid future date is supplied (R8.2, R8.3).

**Validates: Requirements 8.2, 8.3**
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import (
    _VISA_RESIDENCY_TYPES,
    validate_visa_expiry,
)

# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

# The five residency-type options exposed by the onboarding form (R8.1).
_RESIDENCY_TYPES = (
    "citizen",
    "permanent_resident",
    "work_visa",
    "student_visa",
    "other",
)
_VISA_TYPES = ("work_visa", "student_visa")
_NON_VISA_TYPES = ("citizen", "permanent_resident", "other")

# Sanity-check our local copy of the visa-type set matches the module's.
assert frozenset(_VISA_TYPES) == _VISA_RESIDENCY_TYPES

# A fixed, deterministic "today" injected into every call so the tests do not
# depend on the wall clock.
_TODAY = date(2026, 1, 15)


def _expected_valid(residency_type: str, expiry_date: object, today: date) -> bool:
    """Independent re-implementation of the documented truth table (oracle)."""
    if residency_type not in _VISA_TYPES:
        return True
    if expiry_date is None:
        return False
    d = expiry_date.date() if isinstance(expiry_date, datetime) else expiry_date
    if not isinstance(d, date):
        return False
    return d > today


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_PAST_DATES = st.dates(min_value=date(1990, 1, 1), max_value=_TODAY - timedelta(days=1))
_FUTURE_DATES = st.dates(min_value=_TODAY + timedelta(days=1), max_value=date(2099, 12, 31))

# expiry_date ∈ {past, today, future, None}.
_EXPIRY_DATES = st.one_of(
    _PAST_DATES,
    st.just(_TODAY),
    _FUTURE_DATES,
    st.none(),
)


# ===========================================================================
# Feature: staff-onboarding-link, Property 13: Visa types require a valid
# future expiry date (blocking)
# ===========================================================================


class TestProperty13VisaExpiryBlocking:
    """``validate_visa_expiry`` implements the documented truth table over
    residency_type × {past, today, future, None} expiry dates, returns a plain
    ``bool`` (never raises), and treats a missing/past/current-dated visa date
    as INVALID so the submit handler blocks on it (R8.2, R8.3)."""

    @given(
        residency_type=st.sampled_from(_RESIDENCY_TYPES),
        expiry_date=_EXPIRY_DATES,
    )
    @settings(max_examples=300, deadline=None)
    def test_matches_documented_truth_table(
        self, residency_type: str, expiry_date: object
    ) -> None:
        """For every (residency_type, expiry_date) combo the result matches the
        independently-computed oracle and is always a plain ``bool``."""
        result = validate_visa_expiry(residency_type, expiry_date, today=_TODAY)
        assert isinstance(result, bool)
        assert result == _expected_valid(residency_type, expiry_date, _TODAY)

    @given(
        residency_type=st.sampled_from(_VISA_TYPES),
        expiry_date=_PAST_DATES,
    )
    @settings(max_examples=200, deadline=None)
    def test_visa_type_with_past_date_is_invalid(
        self, residency_type: str, expiry_date: date
    ) -> None:
        """Visa type + past expiry → invalid (blocks submission)."""
        assert validate_visa_expiry(residency_type, expiry_date, today=_TODAY) is False

    @given(residency_type=st.sampled_from(_VISA_TYPES))
    @settings(max_examples=100, deadline=None)
    def test_visa_type_today_is_invalid(self, residency_type: str) -> None:
        """Visa type + expiry == today → invalid (boundary: ``>`` not ``>=``)."""
        assert validate_visa_expiry(residency_type, _TODAY, today=_TODAY) is False

    @given(
        residency_type=st.sampled_from(_VISA_TYPES),
        expiry_date=_FUTURE_DATES,
    )
    @settings(max_examples=200, deadline=None)
    def test_visa_type_future_date_is_valid(
        self, residency_type: str, expiry_date: date
    ) -> None:
        """Visa type + strictly-future expiry → valid (accepted)."""
        assert validate_visa_expiry(residency_type, expiry_date, today=_TODAY) is True

    @given(residency_type=st.sampled_from(_VISA_TYPES))
    @settings(max_examples=100, deadline=None)
    def test_visa_type_missing_date_is_invalid(self, residency_type: str) -> None:
        """Visa type + no expiry date → invalid (a date is required)."""
        assert validate_visa_expiry(residency_type, None, today=_TODAY) is False

    @given(
        residency_type=st.sampled_from(_NON_VISA_TYPES),
        expiry_date=_EXPIRY_DATES,
    )
    @settings(max_examples=200, deadline=None)
    def test_non_visa_type_always_valid_regardless_of_date(
        self, residency_type: str, expiry_date: object
    ) -> None:
        """Non-visa residency types are always valid, for any (or no) date."""
        assert validate_visa_expiry(residency_type, expiry_date, today=_TODAY) is True

    # --- Total / never-raises invariant -------------------------------------

    @given(
        residency_type=st.sampled_from(_RESIDENCY_TYPES),
        expiry_date=_EXPIRY_DATES,
    )
    @settings(max_examples=200, deadline=None)
    def test_validator_returns_bool_never_raises(
        self, residency_type: str, expiry_date: object
    ) -> None:
        """The validator is total: it always returns a plain ``bool`` and never
        raises for ordinary input."""
        result = validate_visa_expiry(residency_type, expiry_date, today=_TODAY)
        assert result in (True, False)

    # --- Targeted examples / edge cases -------------------------------------

    def test_work_visa_one_day_past_is_invalid(self) -> None:
        """Work visa expiring yesterday → invalid."""
        assert validate_visa_expiry("work_visa", _TODAY - timedelta(days=1), today=_TODAY) is False

    def test_student_visa_far_past_is_invalid(self) -> None:
        """Student visa long expired → invalid."""
        assert validate_visa_expiry("student_visa", date(2000, 1, 1), today=_TODAY) is False

    def test_work_visa_tomorrow_is_valid(self) -> None:
        """Work visa expiring tomorrow → valid."""
        assert validate_visa_expiry("work_visa", _TODAY + timedelta(days=1), today=_TODAY) is True

    def test_citizen_with_past_date_is_valid(self) -> None:
        """Citizen never carries a visa expiry → valid even with a past date."""
        assert validate_visa_expiry("citizen", date(2000, 1, 1), today=_TODAY) is True

    def test_datetime_expiry_is_normalised_to_date(self) -> None:
        """A ``datetime`` expiry is normalised to its date component."""
        future_dt = datetime(2030, 1, 1, 9, 30, tzinfo=timezone.utc)
        assert validate_visa_expiry("work_visa", future_dt, today=_TODAY) is True

    def test_default_today_uses_wall_clock_without_raising(self) -> None:
        """Omitting ``today`` defaults to ``date.today()`` and still returns a bool."""
        result = validate_visa_expiry("work_visa", date(2000, 1, 1))
        assert result is False  # a year-2000 expiry is past for any real "today"
