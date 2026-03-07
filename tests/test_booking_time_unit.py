"""Unit tests for Task 19.4 — Booking & Time Tracking edge cases.

Additional coverage beyond test_bookings.py, test_booking_convert.py,
and test_time_tracking.py.

Validates: Requirements 64.1, 65.2
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Model imports for SQLAlchemy mapper resolution
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue, LabourRate  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.bookings.models import Booking  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem, TimeEntry

from app.modules.bookings.service import _get_calendar_range
from app.modules.time_tracking.service import (
    add_time_as_labour_line_item,
    stop_timer,
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


# ===========================================================================
# Calendar range edge cases (Requirement 64.1)
# ===========================================================================


class TestCalendarRangeEdgeCases:
    """Edge cases for _get_calendar_range not covered in test_bookings.py."""

    def test_day_view_midnight_boundary(self):
        """Day view at exactly midnight returns that day's full range."""
        ref = datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("day", ref)
        assert start == datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2025, 7, 2, 0, 0, 0, tzinfo=timezone.utc)
        assert (end - start) == timedelta(days=1)

    def test_week_view_year_boundary(self):
        """Week view spanning Dec 29 (Mon) → Jan 4 crosses year boundary."""
        # Dec 31, 2025 is a Wednesday
        ref = datetime(2025, 12, 31, 12, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("week", ref)
        assert start.weekday() == 0  # Monday
        assert start == datetime(2025, 12, 29, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
        assert (end - start) == timedelta(days=7)

    def test_month_view_february_non_leap(self):
        """February in a non-leap year (2025) spans 28 days."""
        ref = datetime(2025, 2, 15, 10, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("month", ref)
        assert start == datetime(2025, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2025, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert (end - start) == timedelta(days=28)

    def test_month_view_february_leap_year(self):
        """February in a leap year (2024) spans 29 days."""
        ref = datetime(2024, 2, 10, 8, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("month", ref)
        assert start == datetime(2024, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2024, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert (end - start) == timedelta(days=29)

    def test_default_view_when_no_date_param(self):
        """When date_param is None, uses current time (month view as default)."""
        before = datetime.now(timezone.utc)
        start, end = _get_calendar_range("month", None)
        after = datetime.now(timezone.utc)
        # start should be 1st of current month
        assert start.day == 1
        assert start.hour == 0
        assert start.minute == 0
        # end should be 1st of next month
        if before.month == 12:
            assert end.month == 1
            assert end.year == before.year + 1
        else:
            assert end.month == before.month + 1

    def test_week_view_on_monday(self):
        """Week view when ref is already Monday returns that Monday."""
        # June 16, 2025 is a Monday
        ref = datetime(2025, 6, 16, 9, 0, 0, tzinfo=timezone.utc)
        start, end = _get_calendar_range("week", ref)
        assert start == datetime(2025, 6, 16, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2025, 6, 23, 0, 0, 0, tzinfo=timezone.utc)


# ===========================================================================
# Time calculation edge cases (Requirement 65.2)
# ===========================================================================


class TestTimeCalculationEdgeCases:
    """Edge cases for timer duration and labour line item calculations."""

    @pytest.mark.asyncio
    async def test_very_short_timer_rounds_to_one_minute(self):
        """A timer < 1 minute should round to duration_minutes=1."""
        db = _mock_db()
        entry = MagicMock(spec=TimeEntry)
        entry.id = uuid.uuid4()
        entry.org_id = ORG_ID
        entry.user_id = USER_ID
        entry.job_card_id = JOB_CARD_ID
        entry.started_at = datetime.now(timezone.utc) - timedelta(seconds=15)
        entry.stopped_at = None
        entry.duration_minutes = None
        entry.notes = None

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

        # max(1, round(15/60)) = max(1, 0) = 1
        assert entry.duration_minutes == 1

    @pytest.mark.asyncio
    async def test_very_long_timer_eight_plus_hours(self):
        """An 8+ hour timer calculates correct duration_minutes."""
        db = _mock_db()
        entry = MagicMock(spec=TimeEntry)
        entry.id = uuid.uuid4()
        entry.org_id = ORG_ID
        entry.user_id = USER_ID
        entry.job_card_id = JOB_CARD_ID
        entry.started_at = datetime.now(timezone.utc) - timedelta(hours=8, minutes=30)
        entry.stopped_at = None
        entry.duration_minutes = None
        entry.notes = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = entry
        db.execute = AsyncMock(return_value=mock_result)

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            await stop_timer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
            )

        # 8h30m = 510 minutes
        assert entry.duration_minutes == 510

    @pytest.mark.asyncio
    async def test_labour_line_item_fractional_hours(self):
        """7 minutes → 0.12 hours, total = 0.12 * 100 = 12.00."""
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=7)

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

        # 7/60 = 0.1166... → rounds to 0.12
        assert result["hours"] == Decimal("0.12")
        assert result["line_total"] == Decimal("12.00")

    @pytest.mark.asyncio
    async def test_inactive_labour_rate_rejected(self):
        """Looking up an inactive labour rate raises ValueError."""
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=30)
        rate_id = uuid.uuid4()

        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        # Labour rate query returns None (inactive rate filtered out by is_active)
        mock_rate_result = MagicMock()
        mock_rate_result.scalars.return_value.first.return_value = None

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_rate_result]
        )

        with pytest.raises(ValueError, match="Labour rate not found or inactive"):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                labour_rate_id=rate_id,
            )


# ===========================================================================
# Timer → Job Card line item integration (Requirements 65.2)
# ===========================================================================


class TestTimerToJobCardLineItem:
    """Verify the created JobCardItem has correct attributes."""

    @pytest.mark.asyncio
    async def test_created_item_has_labour_type(self):
        """The JobCardItem added via add_time_as_labour must have item_type='labour'."""
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=45)

        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        mock_sort_result = MagicMock()
        mock_sort_result.scalar.return_value = 0

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_sort_result]
        )

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                hourly_rate_override=Decimal("90.00"),
            )

        # Inspect the JobCardItem that was added to the session
        db.add.assert_called_once()
        item = db.add.call_args[0][0]
        assert isinstance(item, JobCardItem)
        assert item.item_type == "labour"
        assert item.org_id == ORG_ID
        assert item.job_card_id == JOB_CARD_ID
        assert item.unit_price == Decimal("90.00")

    @pytest.mark.asyncio
    async def test_sort_order_increments_correctly(self):
        """sort_order should be max(existing) + 1."""
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=60)

        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        # Existing max sort_order is 5
        mock_sort_result = MagicMock()
        mock_sort_result.scalar.return_value = 5

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_sort_result]
        )

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                hourly_rate_override=Decimal("75.00"),
            )

        item = db.add.call_args[0][0]
        assert item.sort_order == 6

    @pytest.mark.asyncio
    async def test_sort_order_starts_at_one_when_empty(self):
        """sort_order should be 1 when no existing items (coalesce returns 0)."""
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=30)

        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        mock_sort_result = MagicMock()
        mock_sort_result.scalar.return_value = 0  # coalesce default

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_sort_result]
        )

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                hourly_rate_override=Decimal("50.00"),
            )

        item = db.add.call_args[0][0]
        assert item.sort_order == 1

    @pytest.mark.asyncio
    async def test_default_description_includes_minutes(self):
        """Default description should include the duration in minutes."""
        db = _mock_db()
        entry = _make_time_entry(stopped=True, duration_minutes=45)

        mock_entry_result = MagicMock()
        mock_entry_result.scalars.return_value.first.return_value = entry

        mock_sort_result = MagicMock()
        mock_sort_result.scalar.return_value = 0

        db.execute = AsyncMock(
            side_effect=[mock_entry_result, mock_sort_result]
        )

        with patch("app.modules.time_tracking.service.write_audit_log", new_callable=AsyncMock):
            await add_time_as_labour_line_item(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                job_card_id=JOB_CARD_ID,
                time_entry_id=entry.id,
                hourly_rate_override=Decimal("80.00"),
            )

        item = db.add.call_args[0][0]
        assert "45 min" in item.description
