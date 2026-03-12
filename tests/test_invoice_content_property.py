"""Property-based tests for invoice content from job card conversion.

Feature: booking-to-job-workflow

Property 19: Invoice includes job items and labour time
— For any completed job card with line items and time entries, the generated
invoice contains line items matching the job card's items, plus a labour line
item whose quantity reflects the total accumulated duration_minutes.

Validates: Requirements 6.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
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
from app.modules.suppliers.models import Supplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem, TimeEntry  # noqa: F401
from app.modules.bookings.models import Booking  # noqa: F401

from app.modules.job_cards.service import convert_job_card_to_invoice


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

line_item_st = st.fixed_dictionaries({
    "id": st.builds(uuid.uuid4),
    "item_type": st.sampled_from(["service", "part"]),
    "description": st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z"))),
    "quantity": st.decimals(min_value=1, max_value=100, places=2, allow_nan=False, allow_infinity=False),
    "unit_price": st.decimals(min_value=0, max_value=5000, places=2, allow_nan=False, allow_infinity=False),
    "is_completed": st.just(False),
    "line_total": st.decimals(min_value=0, max_value=500000, places=2, allow_nan=False, allow_infinity=False),
    "sort_order": st.integers(min_value=0, max_value=20),
})

time_entry_st = st.integers(min_value=1, max_value=480)  # duration in minutes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Property 19: Invoice includes job items and labour time
# ---------------------------------------------------------------------------


class TestInvoiceContentProperty:
    """Property 19: Invoice includes job items and labour time.

    # Feature: booking-to-job-workflow, Property 19: Invoice includes job items and labour time

    **Validates: Requirements 6.6**

    For any completed job card with N line items and M completed time entries
    totalling T minutes, the generated invoice contains:
    - N line items matching the job card items (same type, description, qty, price)
    - 1 labour line item with quantity = ceil(T / 60) hours (when T > 0)
    """

    @PBT_SETTINGS
    @given(
        line_items=st.lists(line_item_st, min_size=1, max_size=5),
        durations=st.lists(time_entry_st, min_size=1, max_size=3),
    )
    @pytest.mark.asyncio
    async def test_invoice_includes_job_items_and_labour(self, line_items, durations):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # Build the job card dict that get_job_card would return
        jc_dict = {
            "id": job_card_id,
            "org_id": org_id,
            "customer_id": customer_id,
            "vehicle_rego": "TEST123",
            "status": "completed",
            "description": "Test job",
            "notes": None,
            "line_items": line_items,
            "created_by": user_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        # Build time entries
        total_minutes = sum(durations)
        now = datetime.now(timezone.utc)
        entries = []
        for i, dur in enumerate(durations):
            started = now - timedelta(minutes=total_minutes - sum(durations[:i]))
            stopped = started + timedelta(minutes=dur)
            entries.append({
                "id": uuid.uuid4(),
                "org_id": org_id,
                "job_card_id": job_card_id,
                "user_id": user_id,
                "started_at": started,
                "stopped_at": stopped,
                "duration_minutes": dur,
                "hourly_rate": None,
                "notes": None,
                "created_at": now,
            })

        timer_data = {"entries": entries, "is_active": False}

        # Track what create_invoice receives
        captured_line_items = []
        fake_invoice_id = uuid.uuid4()

        async def fake_create_invoice(db, **kwargs):
            captured_line_items.extend(kwargs.get("line_items_data", []))
            return {"id": fake_invoice_id, "status": "draft"}

        # Mock job card for the status transition
        mock_jc = MagicMock(spec=JobCard)
        mock_jc.id = job_card_id
        mock_jc.status = "completed"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_jc

        db = _mock_db()
        db.execute.return_value = mock_result

        with patch(
            "app.modules.job_cards.service.get_job_card",
            new_callable=AsyncMock,
            return_value=jc_dict,
        ), patch(
            "app.modules.job_cards.service.get_timer_entries",
            new_callable=AsyncMock,
            return_value=timer_data,
        ), patch(
            "app.modules.invoices.service.create_invoice",
            side_effect=fake_create_invoice,
        ), patch(
            "app.modules.job_cards.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await convert_job_card_to_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card_id,
            )

        # Verify result
        assert result["invoice_id"] == fake_invoice_id

        # Verify job card items are present
        non_labour = [li for li in captured_line_items if li["item_type"] != "labour"]
        assert len(non_labour) == len(line_items)
        for orig, copied in zip(line_items, non_labour):
            assert copied["item_type"] == orig["item_type"]
            assert copied["description"] == orig["description"]
            assert copied["quantity"] == orig["quantity"]
            assert copied["unit_price"] == orig["unit_price"]

        # Verify labour line item
        labour_items = [li for li in captured_line_items if li["item_type"] == "labour"]
        assert len(labour_items) == 1
        labour = labour_items[0]
        assert f"{total_minutes} minutes" in labour["description"]
        expected_hours = Decimal(str(total_minutes)) / Decimal("60")
        expected_hours = expected_hours.quantize(Decimal("0.01"))
        assert labour["quantity"] == expected_hours

    @PBT_SETTINGS
    @given(
        line_items=st.lists(line_item_st, min_size=1, max_size=3),
    )
    @pytest.mark.asyncio
    async def test_invoice_no_labour_when_no_time_entries(self, line_items):
        """When a job card has no time entries, the invoice should contain
        only the job card items and no labour line item."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        jc_dict = {
            "id": job_card_id,
            "org_id": org_id,
            "customer_id": customer_id,
            "vehicle_rego": "TEST456",
            "status": "completed",
            "description": "Test job no time",
            "notes": None,
            "line_items": line_items,
            "created_by": user_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        timer_data = {"entries": [], "is_active": False}

        captured_line_items = []
        fake_invoice_id = uuid.uuid4()

        async def fake_create_invoice(db, **kwargs):
            captured_line_items.extend(kwargs.get("line_items_data", []))
            return {"id": fake_invoice_id, "status": "draft"}

        mock_jc = MagicMock(spec=JobCard)
        mock_jc.id = job_card_id
        mock_jc.status = "completed"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_jc

        db = _mock_db()
        db.execute.return_value = mock_result

        with patch(
            "app.modules.job_cards.service.get_job_card",
            new_callable=AsyncMock,
            return_value=jc_dict,
        ), patch(
            "app.modules.job_cards.service.get_timer_entries",
            new_callable=AsyncMock,
            return_value=timer_data,
        ), patch(
            "app.modules.invoices.service.create_invoice",
            side_effect=fake_create_invoice,
        ), patch(
            "app.modules.job_cards.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await convert_job_card_to_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card_id,
            )

        # No labour line items
        labour_items = [li for li in captured_line_items if li["item_type"] == "labour"]
        assert len(labour_items) == 0
        # All job card items present
        assert len(captured_line_items) == len(line_items)
