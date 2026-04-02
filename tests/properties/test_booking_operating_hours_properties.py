"""Property-based tests for booking operating hours validation (P13).

Feature: branch-management-complete, Property 13: Booking operating hours validation

For any branch with operating_hours configured and any booking with
start_time/end_time, the booking SHALL be accepted only if it falls
entirely within the branch's operating hours for that day of the week.

**Validates: Requirements 3.4**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _operating_hours_strategy():
    """Generate operating hours dicts with open/close times."""
    hour_pair = st.tuples(
        st.integers(min_value=0, max_value=20),  # open hour
        st.integers(min_value=1, max_value=23),  # close hour
    ).filter(lambda t: t[0] < t[1])

    return st.fixed_dictionaries({
        day: st.one_of(
            st.just(None),  # closed
            hour_pair.map(lambda t: {"open": f"{t[0]:02d}:00", "close": f"{t[1]:02d}:00"}),
        )
        for day in _DAYS
    }).map(lambda d: {k: v for k, v in d.items() if v is not None})


def _make_scalar_result(value):
    """Create a mock DB result that returns value from scalar_one_or_none."""
    result_mock = AsyncMock()
    result_mock.scalar_one_or_none.return_value = value
    return result_mock


def _make_db_mock(value):
    """Create a mock DB that returns value from execute().scalar_one_or_none()."""
    from unittest.mock import MagicMock
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = value
    db.execute.return_value = result_mock
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestP13BookingOperatingHoursValidation:
    """Property 13: Booking operating hours validation.

    **Validates: Requirements 3.4**
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        branch_id=st.uuids(),
        open_hour=st.integers(min_value=6, max_value=14),
        close_hour=st.integers(min_value=15, max_value=22),
        booking_hour=st.integers(min_value=0, max_value=23),
        duration=st.integers(min_value=15, max_value=120),
    )
    def test_booking_within_hours_accepted(
        self,
        branch_id: uuid.UUID,
        open_hour: int,
        close_hour: int,
        booking_hour: int,
        duration: int,
    ) -> None:
        """P13: Bookings entirely within operating hours are accepted."""
        from app.core.branch_validation import validate_booking_operating_hours

        # Create a Monday booking
        scheduled_at = datetime(2025, 1, 6, booking_hour, 0)  # Monday
        booking_end_minutes = booking_hour * 60 + duration
        open_minutes = open_hour * 60
        close_minutes = close_hour * 60

        operating_hours = {"monday": {"open": f"{open_hour:02d}:00", "close": f"{close_hour:02d}:00"}}

        db = _make_db_mock(operating_hours)

        if booking_hour * 60 >= open_minutes and booking_end_minutes <= close_minutes:
            # Should succeed — booking is within hours
            asyncio.get_event_loop().run_until_complete(
                validate_booking_operating_hours(db, branch_id, scheduled_at, duration)
            )
        else:
            # Should fail — booking is outside hours
            with pytest.raises(ValueError, match="outside branch operating hours"):
                asyncio.get_event_loop().run_until_complete(
                    validate_booking_operating_hours(db, branch_id, scheduled_at, duration)
                )

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        branch_id=st.uuids(),
        booking_hour=st.integers(min_value=8, max_value=16),
        duration=st.integers(min_value=15, max_value=60),
    )
    def test_booking_on_closed_day_rejected(
        self,
        branch_id: uuid.UUID,
        booking_hour: int,
        duration: int,
    ) -> None:
        """P13: Bookings on days the branch is closed are rejected."""
        from app.core.branch_validation import validate_booking_operating_hours

        # Monday booking, but branch only open on Tuesday
        scheduled_at = datetime(2025, 1, 6, booking_hour, 0)  # Monday
        operating_hours = {"tuesday": {"open": "08:00", "close": "17:00"}}

        db = _make_db_mock(operating_hours)

        with pytest.raises(ValueError, match="outside branch operating hours"):
            asyncio.get_event_loop().run_until_complete(
                validate_booking_operating_hours(db, branch_id, scheduled_at, duration)
            )

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        branch_id=st.uuids(),
        booking_hour=st.integers(min_value=8, max_value=16),
        duration=st.integers(min_value=15, max_value=60),
    )
    def test_no_operating_hours_always_accepted(
        self,
        branch_id: uuid.UUID,
        booking_hour: int,
        duration: int,
    ) -> None:
        """P13: When no operating hours configured, all bookings are accepted."""
        from app.core.branch_validation import validate_booking_operating_hours

        scheduled_at = datetime(2025, 1, 6, booking_hour, 0)

        db = _make_db_mock({})
        # Empty dict = no operating hours configured

        # Should not raise
        asyncio.get_event_loop().run_until_complete(
            validate_booking_operating_hours(db, branch_id, scheduled_at, duration)
        )
