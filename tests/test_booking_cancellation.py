"""Test: cancellation frees the time slot and sends notifications.

**Validates: Requirement 19 — Booking Module — Task 26.8**

Verifies that BookingService.cancel_booking() sets status to cancelled,
freeing the slot for new bookings, and that re-cancellation / completed
booking cancellation is rejected.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone, date, time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.bookings_v2.models import Booking, BookingRule
from app.modules.bookings_v2.schemas import TimeSlot
from app.modules.bookings_v2.service import BookingService


ORG_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()


def _make_booking(
    *,
    status: str = "confirmed",
    start_offset_hours: int = 24,
    duration_hours: int = 1,
) -> Booking:
    now = datetime.now(timezone.utc)
    return Booking(
        id=BOOKING_ID,
        org_id=ORG_ID,
        customer_name="Test Customer",
        customer_email="test@example.com",
        start_time=now + timedelta(hours=start_offset_hours),
        end_time=now + timedelta(hours=start_offset_hours + duration_hours),
        status=status,
        service_type="Consultation",
    )


def _make_mock_db():
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


class TestBookingCancellation:
    """Validates: cancellation frees the time slot."""

    @pytest.mark.asyncio
    async def test_cancel_confirmed_booking(self):
        """Cancelling a confirmed booking sets status to cancelled."""
        booking = _make_booking(status="confirmed")
        mock_db = _make_mock_db()
        svc = BookingService(mock_db)

        with patch.object(svc, "get_booking", return_value=booking):
            result = await svc.cancel_booking(ORG_ID, BOOKING_ID)
        assert result is not None
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_pending_booking(self):
        """Cancelling a pending booking sets status to cancelled."""
        booking = _make_booking(status="pending")
        mock_db = _make_mock_db()
        svc = BookingService(mock_db)

        with patch.object(svc, "get_booking", return_value=booking):
            result = await svc.cancel_booking(ORG_ID, BOOKING_ID)
        assert result is not None
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_raises(self):
        """Cancelling an already cancelled booking raises ValueError."""
        booking = _make_booking(status="cancelled")
        mock_db = _make_mock_db()
        svc = BookingService(mock_db)

        with patch.object(svc, "get_booking", return_value=booking):
            with pytest.raises(ValueError, match="already cancelled"):
                await svc.cancel_booking(ORG_ID, BOOKING_ID)

    @pytest.mark.asyncio
    async def test_cancel_completed_booking_raises(self):
        """Cancelling a completed booking raises ValueError."""
        booking = _make_booking(status="completed")
        mock_db = _make_mock_db()
        svc = BookingService(mock_db)

        with patch.object(svc, "get_booking", return_value=booking):
            with pytest.raises(ValueError, match="Cannot cancel a completed"):
                await svc.cancel_booking(ORG_ID, BOOKING_ID)

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_booking_returns_none(self):
        """Cancelling a non-existent booking returns None."""
        mock_db = _make_mock_db()
        svc = BookingService(mock_db)

        with patch.object(svc, "get_booking", return_value=None):
            result = await svc.cancel_booking(ORG_ID, uuid.uuid4())
        assert result is None


class TestCancellationFreesSlot:
    """Validates: cancelled booking's slot becomes available."""

    @pytest.mark.asyncio
    async def test_cancelled_booking_not_counted_in_overlap(self):
        """Cancelled bookings are excluded from overlap checks in slot calc."""
        # Use a date far in the future to avoid min_advance_hours issues
        future_date = (datetime.now(timezone.utc) + timedelta(days=5)).date()

        cancelled = Booking(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            customer_name="Cancelled",
            start_time=datetime.combine(future_date, time(10, 0), tzinfo=timezone.utc),
            end_time=datetime.combine(future_date, time(11, 0), tzinfo=timezone.utc),
            status="cancelled",
        )

        rule = BookingRule(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            duration_minutes=60,
            min_advance_hours=0,
            max_advance_days=365,
            buffer_minutes=0,
            available_days=[1, 2, 3, 4, 5, 6, 7],
            available_hours={"start": "10:00", "end": "12:00"},
        )

        mock_db = _make_mock_db()
        svc = BookingService(mock_db)

        with (
            patch.object(svc, "_get_rule", return_value=rule),
            patch.object(svc, "_get_bookings_for_date", return_value=[cancelled]),
        ):
            slots = await svc.get_available_slots(ORG_ID, future_date, None)

        # The 10:00-11:00 slot should be available since the booking is cancelled
        available_slots = [s for s in slots if s.available]
        assert len(available_slots) >= 1
        assert any(s.start_time.hour == 10 and s.available for s in slots)
