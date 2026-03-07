"""Test: booking respects min advance time and max advance window.

**Validates: Requirement 19 — Booking Module — Task 26.7**

Verifies that BookingService.create_booking() enforces min_advance_hours
and max_advance_days from booking rules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.bookings_v2.models import Booking, BookingRule
from app.modules.bookings_v2.schemas import BookingCreate
from app.modules.bookings_v2.service import BookingService


ORG_ID = uuid.uuid4()


def _make_rule(
    *,
    min_advance_hours: int = 2,
    max_advance_days: int = 30,
    duration_minutes: int = 60,
    buffer_minutes: int = 15,
    available_days: list | None = None,
) -> BookingRule:
    return BookingRule(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        service_type=None,
        duration_minutes=duration_minutes,
        min_advance_hours=min_advance_hours,
        max_advance_days=max_advance_days,
        buffer_minutes=buffer_minutes,
        available_days=available_days or [1, 2, 3, 4, 5, 6, 7],
        available_hours={"start": "09:00", "end": "17:00"},
    )


def _make_mock_db(rule: BookingRule | None = None):
    """Create a mock async DB session."""
    mock_db = AsyncMock()

    async def fake_execute(stmt):
        mock_result = MagicMock()
        # Return the rule for _get_rule queries, None for others
        mock_result.scalar_one_or_none.return_value = rule
        return mock_result

    mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


class TestBookingMinAdvanceTime:
    """Validates: booking respects min advance time."""

    @pytest.mark.asyncio
    async def test_booking_too_soon_rejected(self):
        """Booking within min_advance_hours is rejected."""
        rule = _make_rule(min_advance_hours=4)
        mock_db = _make_mock_db(rule)
        svc = BookingService(mock_db)

        # Try to book 1 hour from now (less than 4h min advance)
        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=1)
        payload = BookingCreate(
            customer_name="Test Customer",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        with pytest.raises(ValueError, match="at least 4 hours in advance"):
            await svc.create_booking(ORG_ID, payload)

    @pytest.mark.asyncio
    async def test_booking_after_min_advance_accepted(self):
        """Booking after min_advance_hours is accepted."""
        rule = _make_rule(min_advance_hours=2)
        mock_db = _make_mock_db(rule)
        svc = BookingService(mock_db)

        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=3)
        payload = BookingCreate(
            customer_name="Test Customer",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        booking = await svc.create_booking(ORG_ID, payload)
        assert booking.customer_name == "Test Customer"
        assert booking.status == "pending"

    @pytest.mark.asyncio
    async def test_booking_exactly_at_min_advance_accepted(self):
        """Booking exactly at min_advance_hours boundary is accepted."""
        rule = _make_rule(min_advance_hours=2)
        mock_db = _make_mock_db(rule)
        svc = BookingService(mock_db)

        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=2, minutes=1)
        payload = BookingCreate(
            customer_name="Test Customer",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        booking = await svc.create_booking(ORG_ID, payload)
        assert booking is not None


class TestBookingMaxAdvanceWindow:
    """Validates: booking respects max advance window."""

    @pytest.mark.asyncio
    async def test_booking_too_far_ahead_rejected(self):
        """Booking beyond max_advance_days is rejected."""
        rule = _make_rule(max_advance_days=30)
        mock_db = _make_mock_db(rule)
        svc = BookingService(mock_db)

        now = datetime.now(timezone.utc)
        start = now + timedelta(days=60)
        payload = BookingCreate(
            customer_name="Test Customer",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        with pytest.raises(ValueError, match="more than 30 days in advance"):
            await svc.create_booking(ORG_ID, payload)

    @pytest.mark.asyncio
    async def test_booking_within_max_advance_accepted(self):
        """Booking within max_advance_days is accepted."""
        rule = _make_rule(max_advance_days=90)
        mock_db = _make_mock_db(rule)
        svc = BookingService(mock_db)

        now = datetime.now(timezone.utc)
        start = now + timedelta(days=10, hours=3)
        payload = BookingCreate(
            customer_name="Test Customer",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        booking = await svc.create_booking(ORG_ID, payload)
        assert booking is not None

    @pytest.mark.asyncio
    async def test_booking_on_unavailable_day_rejected(self):
        """Booking on a day not in available_days is rejected."""
        # Only allow Monday (1) and Tuesday (2)
        rule = _make_rule(available_days=[1, 2])
        mock_db = _make_mock_db(rule)
        svc = BookingService(mock_db)

        # Find a Wednesday (isoweekday=3)
        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=5)
        # Adjust to next Wednesday
        while start.isoweekday() != 3:
            start += timedelta(days=1)

        payload = BookingCreate(
            customer_name="Test Customer",
            start_time=start,
            end_time=start + timedelta(hours=1),
        )

        with pytest.raises(ValueError, match="not available on this day"):
            await svc.create_booking(ORG_ID, payload)
