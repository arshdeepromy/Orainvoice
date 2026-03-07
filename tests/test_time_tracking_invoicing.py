"""Test: invoiced time entries cannot be added to another invoice.

**Validates: Requirement 13.4** — double-billing prevention

Verifies that once time entries are marked as invoiced, attempting to
add them to another invoice raises AlreadyInvoicedError.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.time_tracking_v2.models import TimeEntry
from app.modules.time_tracking_v2.service import (
    AlreadyInvoicedError,
    TimeTrackingService,
)


ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
INVOICE_1 = uuid.uuid4()
INVOICE_2 = uuid.uuid4()


def _make_entry(
    is_invoiced: bool = False,
    invoice_id: uuid.UUID | None = None,
    hourly_rate: Decimal = Decimal("50.00"),
    duration_minutes: int = 60,
) -> TimeEntry:
    base = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
    return TimeEntry(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        user_id=USER_ID,
        start_time=base,
        end_time=base + timedelta(minutes=duration_minutes),
        duration_minutes=duration_minutes,
        is_billable=True,
        hourly_rate=hourly_rate,
        is_invoiced=is_invoiced,
        invoice_id=invoice_id,
        is_timer_active=False,
    )


def _mock_db_returning(entries: list[TimeEntry]):
    """Create a mock DB that returns the given entries."""
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = entries
    mock_result.scalars.return_value = mock_scalars

    async def fake_execute(stmt):
        return mock_result

    mock_db.execute = fake_execute

    async def fake_flush():
        pass

    mock_db.flush = fake_flush
    return mock_db


class TestDoubleBillingPrevention:
    """Invoiced time entries cannot be added to another invoice."""

    @pytest.mark.asyncio
    async def test_already_invoiced_entries_rejected(self):
        """Adding already-invoiced entries to a new invoice raises error."""
        entry = _make_entry(is_invoiced=True, invoice_id=INVOICE_1)
        mock_db = _mock_db_returning([entry])
        svc = TimeTrackingService(mock_db)

        with pytest.raises(AlreadyInvoicedError) as exc_info:
            await svc.add_to_invoice(ORG_ID, [entry.id], INVOICE_2)
        assert entry.id in exc_info.value.entry_ids

    @pytest.mark.asyncio
    async def test_uninvoiced_entries_accepted(self):
        """Adding uninvoiced entries to an invoice succeeds."""
        entry = _make_entry(
            is_invoiced=False, hourly_rate=Decimal("100.00"),
            duration_minutes=90,
        )
        mock_db = _mock_db_returning([entry])
        svc = TimeTrackingService(mock_db)

        result = await svc.add_to_invoice(ORG_ID, [entry.id], INVOICE_1)

        assert result["invoice_id"] == INVOICE_1
        assert result["entries_marked"] == 1
        assert result["line_items_created"] == 1
        assert entry.is_invoiced is True
        assert entry.invoice_id == INVOICE_1
        # 90 min = 1.5 hours × $100 = $150
        assert result["total_hours"] == Decimal("1.50")
        assert result["total_amount"] == Decimal("150.00")

    @pytest.mark.asyncio
    async def test_mixed_invoiced_and_uninvoiced_rejected(self):
        """If any entry in the batch is already invoiced, all are rejected."""
        invoiced = _make_entry(is_invoiced=True, invoice_id=INVOICE_1)
        uninvoiced = _make_entry(is_invoiced=False)
        mock_db = _mock_db_returning([invoiced, uninvoiced])
        svc = TimeTrackingService(mock_db)

        with pytest.raises(AlreadyInvoicedError):
            await svc.add_to_invoice(
                ORG_ID, [invoiced.id, uninvoiced.id], INVOICE_2,
            )
        # The uninvoiced entry should NOT have been marked
        assert uninvoiced.is_invoiced is False

    @pytest.mark.asyncio
    async def test_labour_line_items_calculation(self):
        """Line items are calculated as hours × rate."""
        entry = _make_entry(
            hourly_rate=Decimal("75.00"), duration_minutes=120,
        )
        entry.description = "Electrical work"
        mock_db = _mock_db_returning([entry])
        svc = TimeTrackingService(mock_db)

        result = await svc.add_to_invoice(ORG_ID, [entry.id], INVOICE_1)

        assert result["line_items_created"] == 1
        # 120 min = 2 hours × $75 = $150
        assert result["total_hours"] == Decimal("2.00")
        assert result["total_amount"] == Decimal("150.00")
