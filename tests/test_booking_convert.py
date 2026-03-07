"""Unit tests for Task 19.2 — Booking conversion to Job Card or Invoice.

Requirements: 64.5
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Model imports required for SQLAlchemy relationship resolution
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
from app.modules.bookings.schemas import (
    BookingConvertResponse,
    BookingConvertTarget,
)
from app.modules.bookings.service import (
    convert_booking_to_invoice,
    convert_booking_to_job_card,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_booking(org_id=None, status="scheduled", customer_id=None):
    b = MagicMock(spec=Booking)
    b.id = uuid.uuid4()
    b.org_id = org_id or uuid.uuid4()
    b.customer_id = customer_id or uuid.uuid4()
    b.vehicle_rego = "ABC123"
    b.service_type = "Full Service"
    b.notes = "Check brakes"
    b.status = status
    b.branch_id = None
    b.scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    b.duration_minutes = 60
    b.reminder_sent = False
    b.assigned_to = None
    b.created_by = uuid.uuid4()
    b.created_at = datetime.now(timezone.utc)
    b.updated_at = datetime.now(timezone.utc)
    return b


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestBookingConvertSchemas:
    """Test conversion-related Pydantic schemas."""

    def test_convert_target_values(self):
        assert BookingConvertTarget.job_card.value == "job_card"
        assert BookingConvertTarget.invoice.value == "invoice"

    def test_convert_response_schema(self):
        resp = BookingConvertResponse(
            booking_id=uuid.uuid4(),
            target="job_card",
            created_id=uuid.uuid4(),
            message="Booking converted to job card",
        )
        assert resp.target == "job_card"
        assert resp.message == "Booking converted to job card"


# ---------------------------------------------------------------------------
# Service tests — convert to job card
# ---------------------------------------------------------------------------


class TestConvertBookingToJobCard:
    """Test convert_booking_to_job_card service function."""

    @pytest.mark.asyncio
    async def test_convert_scheduled_booking_to_job_card(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="scheduled")
        job_card_id = uuid.uuid4()

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with patch(
            "app.modules.job_cards.service.create_job_card",
            new_callable=AsyncMock,
            return_value={"id": job_card_id, "status": "open"},
        ) as mock_create, patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await convert_booking_to_job_card(
                db, org_id=org_id, user_id=user_id, booking_id=booking.id
            )

        assert result["booking_id"] == booking.id
        assert result["target"] == "job_card"
        assert result["created_id"] == job_card_id
        assert booking.status == "completed"
        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["customer_id"] == booking.customer_id
        assert call_kwargs["vehicle_rego"] == "ABC123"
        assert call_kwargs["description"] == "Full Service"
        assert call_kwargs["notes"] == "Check brakes"

    @pytest.mark.asyncio
    async def test_convert_confirmed_booking_to_job_card(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="confirmed")
        job_card_id = uuid.uuid4()

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with patch(
            "app.modules.job_cards.service.create_job_card",
            new_callable=AsyncMock,
            return_value={"id": job_card_id, "status": "open"},
        ), patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await convert_booking_to_job_card(
                db, org_id=org_id, user_id=user_id, booking_id=booking.id
            )

        assert result["target"] == "job_card"
        assert booking.status == "completed"

    @pytest.mark.asyncio
    async def test_convert_completed_booking_rejected(self):
        org_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="completed")

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Only scheduled or confirmed"):
            await convert_booking_to_job_card(
                db, org_id=org_id, user_id=uuid.uuid4(), booking_id=booking.id
            )

    @pytest.mark.asyncio
    async def test_convert_cancelled_booking_rejected(self):
        org_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="cancelled")

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Only scheduled or confirmed"):
            await convert_booking_to_job_card(
                db, org_id=org_id, user_id=uuid.uuid4(), booking_id=booking.id
            )

    @pytest.mark.asyncio
    async def test_convert_not_found_booking(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await convert_booking_to_job_card(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                booking_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_convert_booking_without_customer_rejected(self):
        org_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="scheduled")
        booking.customer_id = None

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="must have a customer"):
            await convert_booking_to_job_card(
                db, org_id=org_id, user_id=uuid.uuid4(), booking_id=booking.id
            )


# ---------------------------------------------------------------------------
# Service tests — convert to invoice
# ---------------------------------------------------------------------------


class TestConvertBookingToInvoice:
    """Test convert_booking_to_invoice service function."""

    @pytest.mark.asyncio
    async def test_convert_scheduled_booking_to_invoice(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="scheduled")
        invoice_id = uuid.uuid4()

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value={"id": invoice_id, "status": "draft"},
        ) as mock_create, patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await convert_booking_to_invoice(
                db, org_id=org_id, user_id=user_id, booking_id=booking.id
            )

        assert result["booking_id"] == booking.id
        assert result["target"] == "invoice"
        assert result["created_id"] == invoice_id
        assert booking.status == "completed"
        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["customer_id"] == booking.customer_id
        assert call_kwargs["vehicle_rego"] == "ABC123"
        assert call_kwargs["status"] == "draft"
        assert call_kwargs["notes_internal"] == "Check brakes"

    @pytest.mark.asyncio
    async def test_convert_confirmed_booking_to_invoice(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="confirmed")
        invoice_id = uuid.uuid4()

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with patch(
            "app.modules.invoices.service.create_invoice",
            new_callable=AsyncMock,
            return_value={"id": invoice_id, "status": "draft"},
        ), patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await convert_booking_to_invoice(
                db, org_id=org_id, user_id=user_id, booking_id=booking.id
            )

        assert result["target"] == "invoice"
        assert booking.status == "completed"

    @pytest.mark.asyncio
    async def test_convert_no_show_booking_to_invoice_rejected(self):
        org_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="no_show")

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Only scheduled or confirmed"):
            await convert_booking_to_invoice(
                db, org_id=org_id, user_id=uuid.uuid4(), booking_id=booking.id
            )

    @pytest.mark.asyncio
    async def test_convert_invoice_not_found(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="not found"):
            await convert_booking_to_invoice(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                booking_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_convert_invoice_without_customer_rejected(self):
        org_id = uuid.uuid4()
        booking = _make_booking(org_id=org_id, status="confirmed")
        booking.customer_id = None

        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = booking
        db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="must have a customer"):
            await convert_booking_to_invoice(
                db, org_id=org_id, user_id=uuid.uuid4(), booking_id=booking.id
            )
