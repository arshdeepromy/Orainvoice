"""Tests for tipping module: tip recording, allocation, and summary reports.

**Validates: Requirement 24 — Tipping Module — Tasks 33.8, 33.9**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.tipping.models import Tip, TipAllocation
from app.modules.tipping.service import TippingService
from app.modules.tipping.schemas import (
    TipCreate,
    TipAllocateRequest,
    TipAllocationCreate,
    TipEvenSplitRequest,
)

ORG_ID = uuid.uuid4()
TXN_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
STAFF_A = uuid.uuid4()
STAFF_B = uuid.uuid4()
STAFF_C = uuid.uuid4()


def _make_tip(
    *,
    amount: Decimal = Decimal("15.00"),
    payment_method: str = "card",
    pos_transaction_id: uuid.UUID | None = None,
    invoice_id: uuid.UUID | None = None,
    allocations: list[TipAllocation] | None = None,
    created_at: datetime | None = None,
) -> Tip:
    tip = Tip(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        pos_transaction_id=pos_transaction_id or TXN_ID,
        invoice_id=invoice_id,
        amount=amount,
        payment_method=payment_method,
        created_at=created_at or datetime.now(timezone.utc),
    )
    tip.allocations = allocations or []
    return tip


def _make_mock_db(single: Tip | None = None):
    """Create a mock async DB session."""
    mock_db = AsyncMock()
    if single is not None:
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = single
            return mock_result
        mock_db.execute = fake_execute
    else:
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            return mock_result
        mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.delete = AsyncMock()
    return mock_db


# ======================================================================
# Task 33.8: Tip is recorded with correct amount and allocated to staff
# ======================================================================


class TestTipRecording:
    """Verify that tips are recorded with correct amounts."""

    @pytest.mark.asyncio
    async def test_record_tip_pos_transaction(self):
        """A tip recorded against a POS transaction has the correct amount and method."""
        db = _make_mock_db()
        svc = TippingService(db)
        payload = TipCreate(
            pos_transaction_id=TXN_ID,
            amount=Decimal("12.50"),
            payment_method="card",
        )
        tip = await svc.record_tip(ORG_ID, payload)
        assert tip.amount == Decimal("12.50")
        assert tip.payment_method == "card"
        assert tip.pos_transaction_id == TXN_ID
        assert tip.org_id == ORG_ID
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_tip_invoice(self):
        """A tip recorded against an invoice has the correct invoice_id."""
        db = _make_mock_db()
        svc = TippingService(db)
        payload = TipCreate(
            invoice_id=INVOICE_ID,
            amount=Decimal("5.00"),
            payment_method="card",
        )
        tip = await svc.record_tip(ORG_ID, payload)
        assert tip.invoice_id == INVOICE_ID
        assert tip.amount == Decimal("5.00")
        assert tip.pos_transaction_id is None


class TestTipAllocationCustom:
    """Verify custom tip allocation to staff members."""

    @pytest.mark.asyncio
    async def test_allocate_custom_amounts(self):
        """Custom allocation distributes tip to staff with specified amounts."""
        tip = _make_tip(amount=Decimal("15.00"))
        db = _make_mock_db(single=tip)
        svc = TippingService(db)

        payload = TipAllocateRequest(allocations=[
            TipAllocationCreate(staff_member_id=STAFF_A, amount=Decimal("10.00")),
            TipAllocationCreate(staff_member_id=STAFF_B, amount=Decimal("5.00")),
        ])
        result = await svc.allocate_to_staff(ORG_ID, tip.id, payload)
        assert result is not None
        # Verify add was called for each allocation
        assert db.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_allocate_rejects_mismatched_total(self):
        """Allocation total must equal tip amount."""
        tip = _make_tip(amount=Decimal("15.00"))
        db = _make_mock_db(single=tip)
        svc = TippingService(db)

        payload = TipAllocateRequest(allocations=[
            TipAllocationCreate(staff_member_id=STAFF_A, amount=Decimal("10.00")),
            TipAllocationCreate(staff_member_id=STAFF_B, amount=Decimal("3.00")),
        ])
        with pytest.raises(ValueError, match="Allocation total"):
            await svc.allocate_to_staff(ORG_ID, tip.id, payload)

    @pytest.mark.asyncio
    async def test_allocate_not_found(self):
        """Allocation returns None for non-existent tip."""
        db = _make_mock_db(single=None)
        svc = TippingService(db)
        payload = TipAllocateRequest(allocations=[
            TipAllocationCreate(staff_member_id=STAFF_A, amount=Decimal("10.00")),
        ])
        result = await svc.allocate_to_staff(ORG_ID, uuid.uuid4(), payload)
        assert result is None


class TestTipAllocationEvenSplit:
    """Verify even split allocation across staff members."""

    @pytest.mark.asyncio
    async def test_even_split_two_staff(self):
        """Even split divides tip equally between two staff."""
        tip = _make_tip(amount=Decimal("20.00"))
        db = _make_mock_db(single=tip)
        svc = TippingService(db)

        payload = TipEvenSplitRequest(staff_member_ids=[STAFF_A, STAFF_B])
        result = await svc.allocate_even_split(ORG_ID, tip.id, payload)
        assert result is not None
        # Two allocations should be added
        assert db.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_even_split_three_staff_rounding(self):
        """Even split handles rounding for non-divisible amounts."""
        tip = _make_tip(amount=Decimal("10.00"))
        db = _make_mock_db(single=tip)
        svc = TippingService(db)

        payload = TipEvenSplitRequest(staff_member_ids=[STAFF_A, STAFF_B, STAFF_C])
        result = await svc.allocate_even_split(ORG_ID, tip.id, payload)
        assert result is not None
        # Verify the amounts add up correctly
        # 10.00 / 3 = 3.33 per person, last gets 3.34
        add_calls = db.add.call_args_list
        amounts = []
        for call in add_calls:
            obj = call[0][0]
            if isinstance(obj, TipAllocation):
                amounts.append(obj.amount)
        assert sum(amounts) == Decimal("10.00")

    @pytest.mark.asyncio
    async def test_even_split_not_found(self):
        """Even split returns None for non-existent tip."""
        db = _make_mock_db(single=None)
        svc = TippingService(db)
        payload = TipEvenSplitRequest(staff_member_ids=[STAFF_A])
        result = await svc.allocate_even_split(ORG_ID, uuid.uuid4(), payload)
        assert result is None


# ======================================================================
# Task 33.9: Tip summary report shows correct totals per staff member
# ======================================================================


def _make_summary_mock_db(
    total_tips: Decimal = Decimal("50.00"),
    total_count: int = 3,
    staff_rows: list | None = None,
):
    """Create a mock DB that returns summary query results."""
    mock_db = AsyncMock()
    call_count = 0

    async def fake_execute(stmt):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            # Total tips query
            row = MagicMock()
            row.__getitem__ = lambda self, idx: [total_tips, total_count][idx]
            mock_result.one.return_value = row
        else:
            # Staff summary query
            rows = staff_rows or []
            mock_result.all.return_value = rows
        return mock_result

    mock_db.execute = fake_execute
    mock_db.flush = AsyncMock()
    return mock_db


class TestTipSummaryReport:
    """Verify tip summary report returns correct totals per staff member."""

    @pytest.mark.asyncio
    async def test_summary_totals(self):
        """Summary returns correct total tips and count."""
        staff_row_a = MagicMock()
        staff_row_a.staff_member_id = STAFF_A
        staff_row_a.total_tips = Decimal("30.00")
        staff_row_a.tip_count = 2

        staff_row_b = MagicMock()
        staff_row_b.staff_member_id = STAFF_B
        staff_row_b.total_tips = Decimal("20.00")
        staff_row_b.tip_count = 1

        db = _make_summary_mock_db(
            total_tips=Decimal("50.00"),
            total_count=3,
            staff_rows=[staff_row_a, staff_row_b],
        )
        svc = TippingService(db)
        summary = await svc.get_tip_summary(ORG_ID)

        assert summary["total_tips"] == Decimal("50.00")
        assert summary["total_count"] == 3
        assert len(summary["staff_summaries"]) == 2

    @pytest.mark.asyncio
    async def test_summary_per_staff_totals(self):
        """Summary shows correct per-staff totals and averages."""
        staff_row = MagicMock()
        staff_row.staff_member_id = STAFF_A
        staff_row.total_tips = Decimal("30.00")
        staff_row.tip_count = 3

        db = _make_summary_mock_db(
            total_tips=Decimal("30.00"),
            total_count=3,
            staff_rows=[staff_row],
        )
        svc = TippingService(db)
        summary = await svc.get_tip_summary(ORG_ID)

        staff_a = summary["staff_summaries"][0]
        assert staff_a["staff_member_id"] == STAFF_A
        assert staff_a["total_tips"] == Decimal("30.00")
        assert staff_a["tip_count"] == 3
        assert staff_a["average_tip"] == Decimal("10.00")

    @pytest.mark.asyncio
    async def test_summary_with_date_filter(self):
        """Summary accepts date range filters."""
        from datetime import date

        db = _make_summary_mock_db(
            total_tips=Decimal("25.00"),
            total_count=2,
            staff_rows=[],
        )
        svc = TippingService(db)
        summary = await svc.get_tip_summary(
            ORG_ID,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
        )
        assert summary["total_tips"] == Decimal("25.00")
        assert summary["start_date"] == date(2025, 1, 1)
        assert summary["end_date"] == date(2025, 1, 31)

    @pytest.mark.asyncio
    async def test_summary_with_staff_filter(self):
        """Summary accepts staff_id filter."""
        staff_row = MagicMock()
        staff_row.staff_member_id = STAFF_B
        staff_row.total_tips = Decimal("15.00")
        staff_row.tip_count = 2

        db = _make_summary_mock_db(
            total_tips=Decimal("15.00"),
            total_count=2,
            staff_rows=[staff_row],
        )
        svc = TippingService(db)
        summary = await svc.get_tip_summary(ORG_ID, staff_id=STAFF_B)

        assert len(summary["staff_summaries"]) == 1
        assert summary["staff_summaries"][0]["staff_member_id"] == STAFF_B

    @pytest.mark.asyncio
    async def test_summary_empty(self):
        """Summary returns zeros when no tips exist."""
        db = _make_summary_mock_db(
            total_tips=Decimal("0"),
            total_count=0,
            staff_rows=[],
        )
        svc = TippingService(db)
        summary = await svc.get_tip_summary(ORG_ID)

        assert summary["total_tips"] == Decimal("0")
        assert summary["total_count"] == 0
        assert summary["staff_summaries"] == []
