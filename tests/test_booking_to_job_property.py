"""Property-based tests for booking-to-job workflow.

Feature: booking-to-job-workflow

Uses Hypothesis to verify correctness properties for the booking
conversion to job card with assignee support.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

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
from app.modules.bookings.service import convert_booking_to_job_card


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

convertible_statuses = st.sampled_from(["scheduled", "confirmed", "pending"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_booking(org_id, status="scheduled"):
    """Create a mock Booking with realistic attributes."""
    b = MagicMock(spec=Booking)
    b.id = uuid.uuid4()
    b.org_id = org_id
    b.customer_name = "Jane Doe"
    b.customer_email = "jane@example.com"
    b.customer_phone = "021-555-0100"
    b.vehicle_rego = "ABC123"
    b.service_type = "Full Service"
    b.notes = "Check brakes"
    b.status = status
    b.start_time = datetime.now(timezone.utc) + timedelta(days=1)
    b.end_time = b.start_time + timedelta(hours=1)
    b.converted_job_id = None
    b.converted_invoice_id = None
    b.created_at = datetime.now(timezone.utc)
    b.updated_at = datetime.now(timezone.utc)
    return b


# ---------------------------------------------------------------------------
# Property 7: Conversion creates job with correct assignee
# ---------------------------------------------------------------------------


class TestConversionCreatesJobWithCorrectAssignee:
    """Property 7: Conversion creates job with correct assignee.

    # Feature: booking-to-job-workflow, Property 7: Conversion creates job with correct assignee

    **Validates: Requirements 3.6**

    For any booking conversion request with an assigned_to value, the
    resulting job card has status = "open" and assigned_to equal to the
    requested value, and the booking's converted_job_id is set to the
    new job card's ID.
    """

    @given(
        assigned_to_id=st.builds(uuid.uuid4),
        booking_status=convertible_statuses,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_conversion_with_assignee(self, assigned_to_id, booking_status):
        """For any assigned_to UUID and convertible booking status, the
        created job card has status 'open', the correct assigned_to, and
        the booking's converted_job_id is set to the new job card ID."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card_id = uuid.uuid4()

        booking = _make_booking(org_id=org_id, status=booking_status)
        customer_id = uuid.uuid4()

        db = _mock_db()

        # First db.execute returns the booking, second returns customer_id
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = booking

        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer_id

        db.execute.side_effect = [booking_result, customer_result]

        with patch(
            "app.modules.job_cards.service.create_job_card",
            new_callable=AsyncMock,
            return_value={
                "id": job_card_id,
                "org_id": org_id,
                "customer_id": customer_id,
                "vehicle_rego": "ABC123",
                "status": "open",
                "description": "Full Service",
                "notes": "Check brakes",
                "assigned_to": assigned_to_id,
                "line_items": [],
                "created_by": user_id,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        ) as mock_create, patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await convert_booking_to_job_card(
                db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking.id,
                assigned_to=assigned_to_id,
            )

        # Property assertions:

        # 1. create_job_card was called with the correct assigned_to
        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["assigned_to"] == assigned_to_id, (
            f"Expected assigned_to={assigned_to_id}, got {call_kwargs['assigned_to']}"
        )

        # 2. The created job card has status "open"
        assert mock_create.return_value["status"] == "open", (
            "Job card should be created with status 'open'"
        )

        # 3. The booking's converted_job_id is set to the new job card's ID
        assert booking.converted_job_id == job_card_id, (
            f"Expected booking.converted_job_id={job_card_id}, "
            f"got {booking.converted_job_id}"
        )

        # 4. The result references the correct job card
        assert result["created_id"] == job_card_id
        assert result["target"] == "job_card"
