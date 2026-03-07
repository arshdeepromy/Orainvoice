"""Unit tests for Task 19.1 — Booking/Appointment CRUD.

Requirements: 64.1, 64.2, 64.3, 64.4
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem  # noqa: F401
from app.modules.bookings.models import Booking
from app.modules.bookings.service import (
    _get_calendar_range,
    _validate_status_transition,
    create_booking,
    delete_booking,
    get_booking,
    list_bookings,
    update_booking,
)
from app.modules.bookings.schemas import (
    BookingCreate,
    BookingStatus,
    BookingUpdate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_customer(org_id):
    cust = MagicMock()
    cust.id = uuid.uuid4()
    cust.org_id = org_id
    cust.first_name = "Jane"
    cust.last_name = "Smith"
    cust.email = "jane@example.com"
    cust.phone = "021555123"
    return cust


def _make_booking(org_id=None, status="scheduled"):
    b = MagicMock(spec=Booking)
    b.id = uuid.uuid4()
    b.org_id = org_id or uuid.uuid4()
    b.customer_id = uuid.uuid4()
    b.vehicle_rego = "ABC123"
    b.branch_id = None
    b.service_type = "Full Service"
    b.scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    b.duration_minutes = 60
    b.notes = None
    b.status = status
    b.reminder_sent = False
    b.assigned_to = None
    b.created_by = uuid.uuid4()
    b.created_at = datetime.now(timezone.utc)
    b.updated_at = datetime.now(timezone.utc)
    return b


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestBookingSchemas:
    """Test Pydantic schema validation for bookings."""

    def test_valid_status_values(self):
        assert BookingStatus.scheduled == "scheduled"
        assert BookingStatus.confirmed == "confirmed"
        assert BookingStatus.completed == "completed"
        assert BookingStatus.cancelled == "cancelled"
        assert BookingStatus.no_show == "no_show"

    def test_create_schema_defaults(self):
        payload = BookingCreate(
            customer_id=uuid.uuid4(),
            scheduled_at=datetime.now(timezone.utc),
        )
        assert payload.vehicle_rego is None
        assert payload.duration_minutes == 60
        assert payload.send_confirmation is False

    def test_create_schema_with_all_fields(self):
        cid = uuid.uuid4()
        bid = uuid.uuid4()
        aid = uuid.uuid4()
        dt = datetime.now(timezone.utc)
        payload = BookingCreate(
            customer_id=cid,
            vehicle_rego="XYZ789",
            branch_id=bid,
            service_type="WOF",
            scheduled_at=dt,
            duration_minutes=90,
            notes="Test note",
            assigned_to=aid,
            send_confirmation=True,
        )
        assert payload.customer_id == cid
        assert payload.duration_minutes == 90
        assert payload.send_confirmation is True

    def test_update_schema_all_optional(self):
        payload = BookingUpdate()
        assert payload.status is None
        assert payload.customer_id is None
        assert payload.scheduled_at is None

    def test_duration_min_validation(self):
        with pytest.raises(Exception):
            BookingCreate(
                customer_id=uuid.uuid4(),
                scheduled_at=datetime.now(timezone.utc),
                duration_minutes=5,  # below 15 min
            )


# ---------------------------------------------------------------------------
# Status transition tests
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    """Test booking status transition validation."""

    def test_scheduled_to_confirmed(self):
        _validate_status_transition("scheduled", "confirmed")

    def test_scheduled_to_cancelled(self):
        _validate_status_transition("scheduled", "cancelled")

    def test_scheduled_to_no_show(self):
        _validate_status_transition("scheduled", "no_show")

    def test_confirmed_to_completed(self):
        _validate_status_transition("confirmed", "completed")

    def test_confirmed_to_cancelled(self):
        _validate_status_transition("confirmed", "cancelled")

    def test_confirmed_to_no_show(self):
        _validate_status_transition("confirmed", "no_show")

    def test_completed_is_terminal(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("completed", "scheduled")

    def test_cancelled_is_terminal(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("cancelled", "scheduled")

    def test_no_show_is_terminal(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("no_show", "scheduled")

    def test_scheduled_to_completed_rejected(self):
        with pytest.raises(ValueError, match="Cannot transition"):
            _validate_status_transition("scheduled", "completed")


# ---------------------------------------------------------------------------
# Calendar range tests
# ---------------------------------------------------------------------------


class TestCalendarRange:
    """Test calendar range calculation for day/week/month views."""

    def test_day_view(self):
        ref = datetime(2025, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("day", ref)
        assert start == datetime(2025, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2025, 6, 16, 0, 0, 0, tzinfo=timezone.utc)

    def test_week_view_starts_monday(self):
        # June 15, 2025 is a Sunday (weekday=6)
        ref = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("week", ref)
        assert start.weekday() == 0  # Monday
        assert end - start == timedelta(days=7)

    def test_month_view(self):
        ref = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("month", ref)
        assert start == datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_month_view_december(self):
        ref = datetime(2025, 12, 15, 10, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("month", ref)
        assert start == datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Service function tests
# ---------------------------------------------------------------------------


class TestCreateBooking:
    """Test booking creation service."""

    @pytest.mark.asyncio
    async def test_create_booking_success(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_customer(org_id)
        scheduled = datetime.now(timezone.utc) + timedelta(days=1)

        db = _mock_db()

        # Mock customer lookup
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        db.execute = AsyncMock(side_effect=[cust_result])

        with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock):
            result = await create_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                vehicle_rego="XYZ789",
                service_type="WOF",
                scheduled_at=scheduled,
                duration_minutes=45,
                send_confirmation=True,
            )

        assert result["status"] == "scheduled"
        assert result["vehicle_rego"] == "XYZ789"
        assert result["service_type"] == "WOF"
        assert result["duration_minutes"] == 45
        assert result["customer_name"] == "Jane Smith"
        assert result["confirmation_sent"] is True

    @pytest.mark.asyncio
    async def test_create_booking_customer_not_found(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=cust_result)

        with pytest.raises(ValueError, match="Customer not found"):
            await create_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=uuid.uuid4(),
                scheduled_at=datetime.now(timezone.utc),
            )

    @pytest.mark.asyncio
    async def test_create_booking_minimal(self):
        """Create booking with only required fields."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_customer(org_id)
        scheduled = datetime.now(timezone.utc) + timedelta(hours=2)

        db = _mock_db()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer
        db.execute = AsyncMock(side_effect=[cust_result])

        with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock):
            result = await create_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer.id,
                scheduled_at=scheduled,
            )

        assert result["status"] == "scheduled"
        assert result["vehicle_rego"] is None
        assert result["service_type"] is None
        assert result["duration_minutes"] == 60


class TestGetBooking:
    """Test booking retrieval."""

    @pytest.mark.asyncio
    async def test_get_booking_success(self):
        org_id = uuid.uuid4()
        booking = _make_booking(org_id)

        db = _mock_db()

        # Mock join query returning (Booking, first_name, last_name)
        row = MagicMock()
        row.__getitem__ = lambda self, idx: [booking, "Jane", "Smith"][idx]
        result_mock = MagicMock()
        result_mock.first.return_value = row

        db.execute = AsyncMock(return_value=result_mock)

        result = await get_booking(db, org_id=org_id, booking_id=booking.id)

        assert result["id"] == booking.id
        assert result["status"] == "scheduled"
        assert result["customer_name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_get_booking_not_found(self):
        db = _mock_db()
        result_mock = MagicMock()
        result_mock.first.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Booking not found"):
            await get_booking(db, org_id=uuid.uuid4(), booking_id=uuid.uuid4())


class TestUpdateBooking:
    """Test booking update service."""

    @pytest.mark.asyncio
    async def test_update_status_transition(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id, status="scheduled")
        customer = _make_customer(org_id)

        db = _mock_db()

        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking

        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        db.execute = AsyncMock(side_effect=[booking_result, cust_result])

        with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock):
            result = await update_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking.id,
                updates={"status": "confirmed"},
            )

        assert result["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_update_invalid_transition_rejected(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id, status="scheduled")

        db = _mock_db()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=booking_result)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking.id,
                updates={"status": "completed"},
            )

    @pytest.mark.asyncio
    async def test_update_booking_not_found(self):
        db = _mock_db()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=booking_result)

        with pytest.raises(ValueError, match="Booking not found"):
            await update_booking(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                booking_id=uuid.uuid4(),
                updates={"notes": "test"},
            )

    @pytest.mark.asyncio
    async def test_update_notes_on_scheduled_booking(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id, status="scheduled")
        customer = _make_customer(org_id)

        db = _mock_db()

        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking

        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        db.execute = AsyncMock(side_effect=[booking_result, cust_result])

        with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock):
            result = await update_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking.id,
                updates={"notes": "Updated notes"},
            )

        assert result["notes"] == "Updated notes"


class TestDeleteBooking:
    """Test booking cancellation (soft delete)."""

    @pytest.mark.asyncio
    async def test_delete_booking_success(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id, status="scheduled")

        db = _mock_db()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=booking_result)

        with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock):
            result = await delete_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking.id,
            )

        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_delete_completed_booking_rejected(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id, status="completed")

        db = _mock_db()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking
        db.execute = AsyncMock(return_value=booking_result)

        with pytest.raises(ValueError, match="Cannot cancel"):
            await delete_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking.id,
            )

    @pytest.mark.asyncio
    async def test_delete_booking_not_found(self):
        db = _mock_db()
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=booking_result)

        with pytest.raises(ValueError, match="Booking not found"):
            await delete_booking(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                booking_id=uuid.uuid4(),
            )
