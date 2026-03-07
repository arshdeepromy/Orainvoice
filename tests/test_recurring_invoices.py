"""Tests for recurring invoices module: schedule CRUD, generation, date advancement.

**Validates: Recurring Module — Tasks 34.6, 34.7**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.recurring_invoices.models import RecurringSchedule
from app.modules.recurring_invoices.service import RecurringService
from app.modules.recurring_invoices.schemas import (
    RecurringScheduleCreate,
    RecurringScheduleUpdate,
    LineItemSchema,
)

ORG_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_schedule(
    *,
    frequency: str = "monthly",
    start_date: date | None = None,
    end_date: date | None = None,
    next_generation_date: date | None = None,
    status: str = "active",
    line_items: list | None = None,
) -> RecurringSchedule:
    """Create a RecurringSchedule instance for testing."""
    s = RecurringSchedule(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        customer_id=CUSTOMER_ID,
        line_items=line_items or [{"description": "Service", "quantity": "1", "unit_price": "100.00"}],
        frequency=frequency,
        start_date=start_date or date(2025, 1, 1),
        end_date=end_date,
        next_generation_date=next_generation_date or date(2025, 1, 1),
        auto_issue=False,
        auto_email=False,
        status=status,
    )
    return s


def _make_mock_db(single: RecurringSchedule | None = None):
    """Create a mock async DB session."""
    mock_db = AsyncMock()
    if single is not None:
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = single
            mock_result.scalar.return_value = 1
            mock_result.scalars.return_value.all.return_value = [single]
            return mock_result
        mock_db.execute = fake_execute
    else:
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar.return_value = 0
            mock_result.scalars.return_value.all.return_value = []
            return mock_result
        mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


# ======================================================================
# Task 34.6: Recurring invoice generates on correct date and advances
#             next_generation_date
# ======================================================================


class TestAdvanceNextDate:
    """Verify advance_next_date correctly advances for each frequency."""

    def test_weekly_advances_7_days(self):
        schedule = _make_schedule(
            frequency="weekly",
            next_generation_date=date(2025, 3, 1),
        )
        RecurringService.advance_next_date(schedule)
        assert schedule.next_generation_date == date(2025, 3, 8)
        assert schedule.status == "active"

    def test_fortnightly_advances_14_days(self):
        schedule = _make_schedule(
            frequency="fortnightly",
            next_generation_date=date(2025, 3, 1),
        )
        RecurringService.advance_next_date(schedule)
        assert schedule.next_generation_date == date(2025, 3, 15)
        assert schedule.status == "active"

    def test_monthly_advances_1_month(self):
        schedule = _make_schedule(
            frequency="monthly",
            next_generation_date=date(2025, 1, 31),
        )
        RecurringService.advance_next_date(schedule)
        assert schedule.next_generation_date == date(2025, 2, 28)
        assert schedule.status == "active"

    def test_quarterly_advances_3_months(self):
        schedule = _make_schedule(
            frequency="quarterly",
            next_generation_date=date(2025, 1, 15),
        )
        RecurringService.advance_next_date(schedule)
        assert schedule.next_generation_date == date(2025, 4, 15)
        assert schedule.status == "active"

    def test_annually_advances_1_year(self):
        schedule = _make_schedule(
            frequency="annually",
            next_generation_date=date(2025, 6, 1),
        )
        RecurringService.advance_next_date(schedule)
        assert schedule.next_generation_date == date(2026, 6, 1)
        assert schedule.status == "active"

    def test_advance_past_end_date_marks_completed(self):
        schedule = _make_schedule(
            frequency="monthly",
            next_generation_date=date(2025, 12, 15),
            end_date=date(2025, 12, 31),
        )
        RecurringService.advance_next_date(schedule)
        # Next would be 2026-01-15, which exceeds end_date
        assert schedule.next_generation_date == date(2026, 1, 15)
        assert schedule.status == "completed"

    def test_advance_exactly_on_end_date_stays_active(self):
        schedule = _make_schedule(
            frequency="monthly",
            next_generation_date=date(2025, 11, 15),
            end_date=date(2025, 12, 15),
        )
        RecurringService.advance_next_date(schedule)
        # Next is exactly 2025-12-15 which equals end_date, not past it
        assert schedule.next_generation_date == date(2025, 12, 15)
        assert schedule.status == "active"

    def test_no_end_date_never_completes(self):
        schedule = _make_schedule(
            frequency="annually",
            next_generation_date=date(2025, 1, 1),
            end_date=None,
        )
        RecurringService.advance_next_date(schedule)
        assert schedule.next_generation_date == date(2026, 1, 1)
        assert schedule.status == "active"


class TestGenerateInvoice:
    """Verify generate_invoice produces correct invoice data."""

    @pytest.mark.asyncio
    async def test_generate_invoice_draft_by_default(self):
        schedule = _make_schedule(
            line_items=[{"description": "Hosting", "quantity": "1", "unit_price": "50.00"}],
        )
        schedule.auto_issue = False
        db = _make_mock_db()
        svc = RecurringService(db)
        invoice_data = await svc.generate_invoice(schedule)
        assert invoice_data["status"] == "draft"
        assert invoice_data["customer_id"] == str(CUSTOMER_ID)
        assert invoice_data["source"] == "recurring"
        assert len(invoice_data["line_items"]) == 1

    @pytest.mark.asyncio
    async def test_generate_invoice_auto_issue(self):
        schedule = _make_schedule()
        schedule.auto_issue = True
        db = _make_mock_db()
        svc = RecurringService(db)
        invoice_data = await svc.generate_invoice(schedule)
        assert invoice_data["status"] == "issued"


class TestCreateSchedule:
    """Verify schedule creation."""

    @pytest.mark.asyncio
    async def test_create_schedule_sets_fields(self):
        db = _make_mock_db()
        svc = RecurringService(db)
        payload = RecurringScheduleCreate(
            customer_id=CUSTOMER_ID,
            line_items=[LineItemSchema(description="Service", quantity=Decimal("1"), unit_price=Decimal("100.00"))],
            frequency="monthly",
            start_date=date(2025, 2, 1),
        )
        schedule = await svc.create_schedule(ORG_ID, payload)
        assert schedule.org_id == ORG_ID
        assert schedule.customer_id == CUSTOMER_ID
        assert schedule.frequency == "monthly"
        assert schedule.next_generation_date == date(2025, 2, 1)
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_schedule_custom_next_date(self):
        db = _make_mock_db()
        svc = RecurringService(db)
        payload = RecurringScheduleCreate(
            customer_id=CUSTOMER_ID,
            line_items=[LineItemSchema(description="Service", quantity=Decimal("1"), unit_price=Decimal("100.00"))],
            frequency="weekly",
            start_date=date(2025, 2, 1),
            next_generation_date=date(2025, 2, 15),
        )
        schedule = await svc.create_schedule(ORG_ID, payload)
        assert schedule.next_generation_date == date(2025, 2, 15)


class TestDeleteSchedule:
    """Verify soft-delete (cancellation) of schedules."""

    @pytest.mark.asyncio
    async def test_delete_sets_cancelled(self):
        existing = _make_schedule(status="active")
        db = _make_mock_db(single=existing)
        svc = RecurringService(db)
        result = await svc.delete_schedule(ORG_ID, existing.id)
        assert result is True
        assert existing.status == "cancelled"

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        db = _make_mock_db(single=None)
        svc = RecurringService(db)
        result = await svc.delete_schedule(ORG_ID, uuid.uuid4())
        assert result is False


# ======================================================================
# Task 34.7: Editing template does not affect previously generated invoices
# ======================================================================


class TestTemplateEditIsolation:
    """Verify that updating a schedule's line_items does not retroactively
    change invoices that were already generated from the old template."""

    @pytest.mark.asyncio
    async def test_generated_invoice_is_snapshot_of_template(self):
        """Invoice data is a snapshot at generation time, not a live reference."""
        original_items = [
            {"description": "Monthly Hosting", "quantity": "1", "unit_price": "50.00"},
        ]
        schedule = _make_schedule(line_items=original_items)
        db = _make_mock_db()
        svc = RecurringService(db)

        # Generate invoice from original template
        invoice_data = await svc.generate_invoice(schedule)
        generated_items = invoice_data["line_items"]

        # Now update the schedule's line_items (simulating a template edit)
        schedule.line_items = [
            {"description": "Premium Hosting", "quantity": "1", "unit_price": "150.00"},
        ]

        # The previously generated invoice data should still have the old items
        assert generated_items == original_items
        assert generated_items[0]["description"] == "Monthly Hosting"
        assert generated_items[0]["unit_price"] == "50.00"

        # The schedule now has the new items
        assert schedule.line_items[0]["description"] == "Premium Hosting"

    @pytest.mark.asyncio
    async def test_successive_generations_use_current_template(self):
        """Each generation uses the template as it exists at generation time."""
        schedule = _make_schedule(
            line_items=[{"description": "Basic Plan", "quantity": "1", "unit_price": "25.00"}],
        )
        db = _make_mock_db()
        svc = RecurringService(db)

        # First generation
        invoice_1 = await svc.generate_invoice(schedule)
        assert invoice_1["line_items"][0]["description"] == "Basic Plan"

        # Edit template
        schedule.line_items = [
            {"description": "Pro Plan", "quantity": "1", "unit_price": "75.00"},
        ]

        # Second generation uses updated template
        invoice_2 = await svc.generate_invoice(schedule)
        assert invoice_2["line_items"][0]["description"] == "Pro Plan"

        # First invoice is unchanged
        assert invoice_1["line_items"][0]["description"] == "Basic Plan"
        assert invoice_1["line_items"][0]["unit_price"] == "25.00"
