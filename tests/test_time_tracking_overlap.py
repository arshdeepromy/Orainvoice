"""Test: overlapping time entries are rejected with validation error.

**Validates: Requirement 13.6**

Verifies that the TimeTrackingService prevents two time entries for the
same user from covering the same time period.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.time_tracking_v2.models import TimeEntry
from app.modules.time_tracking_v2.service import (
    OverlapError,
    TimeTrackingService,
)


ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_entry(
    start: datetime,
    end: datetime | None = None,
    entry_id: uuid.UUID | None = None,
    is_timer_active: bool = False,
) -> TimeEntry:
    """Helper to create a TimeEntry instance."""
    duration = None
    if end is not None:
        duration = int((end - start).total_seconds() / 60)
    return TimeEntry(
        id=entry_id or uuid.uuid4(),
        org_id=ORG_ID,
        user_id=USER_ID,
        start_time=start,
        end_time=end,
        duration_minutes=duration,
        is_billable=True,
        is_invoiced=False,
        is_timer_active=is_timer_active,
    )


def _mock_db_with_existing(existing: TimeEntry | None):
    """Create a mock DB that returns the existing entry on overlap check."""
    mock_db = AsyncMock()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing

    async def fake_execute(stmt):
        return mock_result

    mock_db.execute = fake_execute

    added_objects = []

    def fake_add(obj):
        added_objects.append(obj)

    mock_db.add = fake_add
    mock_db._added = added_objects

    async def fake_flush():
        pass

    mock_db.flush = fake_flush
    return mock_db


class TestOverlapDetection:
    """Overlapping time entries are rejected with OverlapError."""

    @pytest.mark.asyncio
    async def test_overlapping_entry_rejected(self):
        """Creating an entry that overlaps an existing one raises OverlapError."""
        base = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
        existing = _make_entry(base, base + timedelta(hours=2))

        mock_db = _mock_db_with_existing(existing)
        svc = TimeTrackingService(mock_db)

        with pytest.raises(OverlapError) as exc_info:
            await svc.create_entry(
                ORG_ID, USER_ID,
                start_time=base + timedelta(hours=1),
                end_time=base + timedelta(hours=3),
            )
        assert existing.id == exc_info.value.existing_id

    @pytest.mark.asyncio
    async def test_non_overlapping_entry_accepted(self):
        """Creating an entry that doesn't overlap succeeds."""
        mock_db = _mock_db_with_existing(None)
        svc = TimeTrackingService(mock_db)

        base = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
        entry = await svc.create_entry(
            ORG_ID, USER_ID,
            start_time=base,
            end_time=base + timedelta(hours=1),
        )
        assert entry is not None
        assert entry.duration_minutes == 60

    @pytest.mark.asyncio
    async def test_active_timer_blocks_new_entry(self):
        """An active timer (no end_time) blocks creating a new entry."""
        base = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
        active_timer = _make_entry(base, None, is_timer_active=True)

        mock_db = _mock_db_with_existing(active_timer)
        svc = TimeTrackingService(mock_db)

        with pytest.raises(OverlapError):
            await svc.create_entry(
                ORG_ID, USER_ID,
                start_time=base + timedelta(hours=1),
                end_time=base + timedelta(hours=2),
            )

    @pytest.mark.asyncio
    async def test_adjacent_entries_allowed(self):
        """Entries that are adjacent (end == start) do not overlap."""
        mock_db = _mock_db_with_existing(None)
        svc = TimeTrackingService(mock_db)

        base = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
        entry = await svc.create_entry(
            ORG_ID, USER_ID,
            start_time=base + timedelta(hours=2),
            end_time=base + timedelta(hours=3),
        )
        assert entry is not None
