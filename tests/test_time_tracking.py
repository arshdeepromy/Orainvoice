"""Unit tests for Task 19.3 — Employee Time Tracking.

Requirements: 65.1, 65.2, 65.3
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Model imports to ensure all ORM models are registered
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue, LabourRate  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.customers.models import Customer  # noqa: F401
from app.modules.bookings.models import Booking  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem, TimeEntry

from app.modules.time_tracking.service import (
    start_timer,
    stop_timer,
    get_time_entries,
    add_time_as_labour_line_item,
    get_employee_hours_report,
    _time_entry_to_dict,
)
from app.modules.time_tracking.schemas import (
    TimerStartRequest,
    TimerStopRequest,
    TimeEntryResponse,
    AddTimeAsLabourRequest,
    EmployeeHoursEntry,
    EmployeeHoursReportResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
JOB_CARD_ID = uuid.uuid4()


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_job_card(org_id=None, status="open"):
    jc = MagicMock(spec=JobCard)
    jc.id = JOB_CARD_ID
    jc.org_id = org_id or ORG_ID
    jc.status = status
    return jc


def _make_time_entry(
    stopped=False,
    duration_minutes=60,
    org_id=None,
    user_id=None,
    job_card_id=None,
):
    entry = MagicMock(spec=TimeEntry)
    entry.id = uuid.uuid4()
    entry.org_id = org_id or ORG_ID
    entry.user_id = user_id or USER_ID
    entry.job_card_id = job_card_id or JOB_CARD_ID
    entry.started_at = datetime.now(timezone.utc) - timedelta(minutes=duration_minutes)
    entry.stopped_at = datetime.now(timezone.utc) if stopped else None
    entry.duration_minutes = duration_minutes if stopped else None
    entry.hourly_rate = None
    entry.notes = None
    entry.created_at = datetime.now(timezone.utc)
    return entry


def _make_labour_rate(org_id=None, hourly_rate=Decimal("85.00")):
    rate = MagicMock(spec=LabourRate)
    rate.id = uuid.uuid4()
    rate.org_id = org_id or ORG_ID
    rate.name = "Standard"
    rate.hourly_rate = hourly_rate
    rate.is_active = True
    return rate


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestTimeTrackingSchemas:
    """Test Pydantic schema validation for time tracking."""

    def test_timer_start_request_defaults(self):
        req = TimerStartRequest()
        assert req.notes is None

    def test_timer_start_request_with_notes(self):
        req = TimerStartRequest(notes="Starting brake job")
        assert req.notes == "Starting brake job"

    def test_timer_stop_request_defaults(self):
        req = TimerStopRequest()
        assert req.notes is None

    def test_time_entry_response(self):
        now = datetime.now(timezone.utc)
        resp = TimeEntryResponse(
            id=uuid.uuid4(),
            job_card_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            started_at=now,
            stopped_at=now,
            duration_minutes=45,
            hourly_rate=Decimal("85.00"),
            notes="Test",
            created_at=now,
        )
        assert resp.duration_minutes == 45

    def test_add_time_as_labour_request(self):
        req = AddTimeAsLabourRequest(
            time_entry_id=uuid.uuid4(),
            labour_rate_id=uuid.uuid4(),
        )
        assert req.hourly_rate_override is None

    def test_employee_hours_entry(self):
        entry = EmployeeHoursEntry(
            user_id=uuid.uuid4(),
            total_minutes=120,
            total_hours=Decimal("2.00"),
            entry_count=3,
        )
        assert entry.total_hours == Decimal("2.00")

    def test_employee_hours_report_response(self):
        now = datetime.now(timezone.utc)
        resp = EmployeeHoursReportResponse(
            entries=[],
            start_date=now,
            end_date=now,
            total_hours=Decimal("0.00"),
        )
        assert resp.total_hours == Decimal("0.00")


# ---------------------------------------------------------------------------
# Service: start_timer
# ---------------------------------------------------------------------------


class TestStartTimer:
    """Test start_timer service function."""

    @pytest.mark.asyncio
    async def test_start_timer_success(self):
        db = _mock_db()
        jc = _make_job_card()

        # First execute: find job card
        # Second execute: check for existing active timer (none found)
        mock_jc_result = MagicMock()
        mock_jc_result.scalars.return_value.first.return_value = jc

        mock_no_timer = MagicMock()
        mock_no_timer.scalars.return_value.first.return_value = None

        db.execute = AsyncMock(side_effect=[mock_jc_result, mock_no_timer])

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            result = await start_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )

        assert result["job_card_id"] == JOB_CARD_ID
        assert result["user_id"] == USER_ID
        assert result["stopped_at"] is None
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_timer_job_card_not_found(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Job card not found"):
            await start_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_start_timer_invoiced_job_card_rejected(self):
        db = _mock_db()
        jc = _make_job_card(status="invoiced")

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = jc
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Cannot start timer on an invoiced job card"):
            await start_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )

    @pytest.mark.asyncio
    async def test_start_timer_duplicate_active_timer_rejected(self):
        db = _mock_db()
        jc = _make_job_card()
        existing_entry = _make_time_entry(stopped=False)

        mock_jc_result = MagicMock()
        mock_jc_result.scalars.return_value.first.return_value = jc

        mock_existing = MagicMock()
        mock_existing.scalars.return_value.first.return_value = existing_entry

        db.execute = AsyncMock(side_effect=[mock_jc_result, mock_existing])

        with pytest.raises(ValueError, match="Active timer already exists"):
            await start_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )


# ---------------------------------------------------------------------------
# Service: stop_timer
# ---------------------------------------------------------------------------


class TestStopTimer:
    """Test stop_timer service function."""

    @pytest.mark.asyncio
    async def test_stop_timer_success(self):
        db = _mock_db()
        entry = _make_time_entry(stopped=False, duration_minutes=30)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            result = await stop_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )

        assert result["stopped_at"] is not None
        assert result["duration_minutes"] is not None
        assert result["duration_minutes"] >= 1

    @pytest.mark.asyncio
    async def test_stop_timer_no_active_timer(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="No active timer found"):
            await stop_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )

    @pytest.mark.asyncio
    async def test_stop_timer_with_notes(self):
        db = _mock_db()
        entry = _make_time_entry(stopped=False, duration_minutes=15)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            result = await stop_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                notes="Finished brake pads",
            )

        assert entry.notes == "Finished brake pads"


# ---------------------------------------------------------------------------
# Service: add_time_as_labour_line_item
# ---------------------------------------------------------------------------


class TestAddTimeAsLabour:
    """Test add_time_as_labour_line_item service function."""

    @pytest.mark.asyncio
    async def test_add_with_labour_rate_id(self):
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=90)
        rate = _make_labour_rate(hourly_rate=Decimal("80.00"))

        # execute calls: 1) find time entry, 2) find labour rate, 3) max sort_order
        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        mock_rate_result = MagicMock()
        mock_rate_result.scalars.return_value.first.return_value = rate

        mock_sort_result = MagicMock()
        mock_sort_result.scalar.return_value = 2

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_rate_result, mock_sort_result]
        )

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            result = await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                labour_rate_id=rate.id,
            )

        # 90 min = 1.50 hours, 1.50 * 80 = 120.00
        assert result["hours"] == Decimal("1.50")
        assert result["hourly_rate"] == Decimal("80.00")
        assert result["line_total"] == Decimal("120.00")
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_with_hourly_rate_override(self):
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=60)

        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        mock_sort_result = MagicMock()
        mock_sort_result.scalar.return_value = 0

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_sort_result]
        )

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            result = await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                hourly_rate_override=Decimal("100.00"),
            )

        # 60 min = 1.00 hours, 1.00 * 100 = 100.00
        assert result["hours"] == Decimal("1.00")
        assert result["line_total"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_add_active_timer_rejected(self):
        db = _mock_db()
        entry = _make_time_entry(stopped=False)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="stop it first"):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                hourly_rate_override=Decimal("50.00"),
            )

    @pytest.mark.asyncio
    async def test_add_no_rate_provided_rejected(self):
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=30)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Hourly rate required"):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
            )

    @pytest.mark.asyncio
    async def test_add_time_entry_not_found(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="Time entry not found"):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=uuid.uuid4(),
                hourly_rate_override=Decimal("50.00"),
            )


# ---------------------------------------------------------------------------
# Service: get_employee_hours_report
# ---------------------------------------------------------------------------


class TestEmployeeHoursReport:
    """Test get_employee_hours_report service function."""

    @pytest.mark.asyncio
    async def test_report_with_entries(self):
        db = _mock_db()
        user1 = uuid.uuid4()
        user2 = uuid.uuid4()

        row1 = MagicMock()
        row1.user_id = user1
        row1.total_minutes = 120
        row1.entry_count = 3

        row2 = MagicMock()
        row2.user_id = user2
        row2.total_minutes = 60
        row2.entry_count = 1

        mock_result = MagicMock()
        mock_result.all.return_value = [row1, row2]
        db.execute = AsyncMock(return_value=mock_result)

        start = datetime.now(timezone.utc) - timedelta(days=7)
        end = datetime.now(timezone.utc)

        result = await get_employee_hours_report(
            db,
            org_id=ORG_ID,
            start_date=start,
            end_date=end,
        )

        assert len(result["entries"]) == 2
        assert result["entries"][0]["total_minutes"] == 120
        assert result["entries"][0]["total_hours"] == Decimal("2.00")
        assert result["entries"][1]["total_minutes"] == 60
        assert result["entries"][1]["total_hours"] == Decimal("1.00")
        assert result["total_hours"] == Decimal("3.00")

    @pytest.mark.asyncio
    async def test_report_empty(self):
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        start = datetime.now(timezone.utc) - timedelta(days=7)
        end = datetime.now(timezone.utc)

        result = await get_employee_hours_report(
            db,
            org_id=ORG_ID,
            start_date=start,
            end_date=end,
        )

        assert len(result["entries"]) == 0
        assert result["total_hours"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Helper: _time_entry_to_dict
# ---------------------------------------------------------------------------


class TestTimeEntryToDict:
    """Test the _time_entry_to_dict helper."""

    def test_converts_all_fields(self):
        entry = _make_time_entry(stopped=True, duration_minutes=45)
        entry.hourly_rate = Decimal("85.00")
        entry.notes = "Test note"

        result = _time_entry_to_dict(entry)

        assert result["id"] == entry.id
        assert result["job_card_id"] == entry.job_card_id
        assert result["user_id"] == entry.user_id
        assert result["duration_minutes"] == 45
        assert result["hourly_rate"] == Decimal("85.00")
        assert result["notes"] == "Test note"

    def test_active_timer_has_no_stopped_at(self):
        entry = _make_time_entry(stopped=False)
        result = _time_entry_to_dict(entry)
        assert result["stopped_at"] is None
        assert result["duration_minutes"] is None
