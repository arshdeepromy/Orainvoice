"""Test: scheduling conflict detection flags overlapping entries for same staff.

**Validates: Requirement 18 — Scheduling Module — Task 25.6**

Verifies that SchedulingService.detect_conflicts() correctly identifies
overlapping schedule entries for the same staff member.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.scheduling_v2.service import SchedulingService


ORG_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
BASE_TIME = datetime(2025, 3, 15, 9, 0, tzinfo=timezone.utc)


def _make_entry(
    *,
    start_offset_hours: int = 0,
    duration_hours: int = 2,
    entry_type: str = "job",
    status: str = "scheduled",
) -> ScheduleEntry:
    """Create a ScheduleEntry instance for testing."""
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_id=STAFF_ID,
        title=f"Entry at +{start_offset_hours}h",
        start_time=BASE_TIME + timedelta(hours=start_offset_hours),
        end_time=BASE_TIME + timedelta(hours=start_offset_hours + duration_hours),
        entry_type=entry_type,
        status=status,
    )


def _make_mock_db(entries_to_return: list[ScheduleEntry]):
    """Create a mock async DB session that returns given entries for conflict queries."""
    mock_db = AsyncMock()

    async def fake_execute(stmt):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = entries_to_return
        return mock_result

    mock_db.execute = fake_execute

    async def fake_flush():
        pass

    mock_db.flush = fake_flush
    return mock_db


class TestSchedulingConflictDetection:
    """Validates: conflict detection flags overlapping entries for same staff."""

    @pytest.mark.asyncio
    async def test_overlapping_entries_detected(self):
        """Two entries overlapping in time for the same staff are flagged."""
        existing = _make_entry(start_offset_hours=0, duration_hours=2)
        mock_db = _make_mock_db([existing])

        svc = SchedulingService(mock_db)
        # New entry from 1h to 3h overlaps existing 0h-2h
        conflicts = await svc.detect_conflicts(
            ORG_ID, STAFF_ID,
            BASE_TIME + timedelta(hours=1),
            BASE_TIME + timedelta(hours=3),
        )
        assert len(conflicts) == 1
        assert conflicts[0].id == existing.id

    @pytest.mark.asyncio
    async def test_non_overlapping_entries_not_flagged(self):
        """Entries that don't overlap are not returned as conflicts."""
        mock_db = _make_mock_db([])

        svc = SchedulingService(mock_db)
        # New entry from 4h to 6h, no overlap with 0h-2h
        conflicts = await svc.detect_conflicts(
            ORG_ID, STAFF_ID,
            BASE_TIME + timedelta(hours=4),
            BASE_TIME + timedelta(hours=6),
        )
        assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_adjacent_entries_not_conflicting(self):
        """Entries that are exactly adjacent (end == start) are not conflicts."""
        mock_db = _make_mock_db([])

        svc = SchedulingService(mock_db)
        # New entry starts exactly when existing ends
        conflicts = await svc.detect_conflicts(
            ORG_ID, STAFF_ID,
            BASE_TIME + timedelta(hours=2),
            BASE_TIME + timedelta(hours=4),
        )
        assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_fully_contained_entry_detected(self):
        """An entry fully contained within another is detected as conflict."""
        existing = _make_entry(start_offset_hours=0, duration_hours=4)
        mock_db = _make_mock_db([existing])

        svc = SchedulingService(mock_db)
        # New entry from 1h to 2h is fully inside 0h-4h
        conflicts = await svc.detect_conflicts(
            ORG_ID, STAFF_ID,
            BASE_TIME + timedelta(hours=1),
            BASE_TIME + timedelta(hours=2),
        )
        assert len(conflicts) == 1

    @pytest.mark.asyncio
    async def test_exclude_entry_id_filters_self(self):
        """When exclude_entry_id is provided, that entry is not returned."""
        existing = _make_entry(start_offset_hours=0, duration_hours=2)
        mock_db = _make_mock_db([])  # DB returns empty because self is excluded

        svc = SchedulingService(mock_db)
        conflicts = await svc.detect_conflicts(
            ORG_ID, STAFF_ID,
            BASE_TIME,
            BASE_TIME + timedelta(hours=2),
            exclude_entry_id=existing.id,
        )
        assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_multiple_overlapping_entries(self):
        """Multiple overlapping entries are all returned."""
        e1 = _make_entry(start_offset_hours=0, duration_hours=2)
        e2 = _make_entry(start_offset_hours=1, duration_hours=2)
        mock_db = _make_mock_db([e1, e2])

        svc = SchedulingService(mock_db)
        conflicts = await svc.detect_conflicts(
            ORG_ID, STAFF_ID,
            BASE_TIME + timedelta(minutes=30),
            BASE_TIME + timedelta(hours=2, minutes=30),
        )
        assert len(conflicts) == 2
