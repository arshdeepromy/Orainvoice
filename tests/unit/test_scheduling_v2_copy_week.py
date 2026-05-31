"""Unit tests for ``SchedulingService.copy_week``.

**Validates: Roster Grid Editor — task A3 (R8.4, R8.5, R8.6, R8.7, R8.9, R14.2).**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.scheduling_v2.schemas import (
    BulkScheduleEntryResponse,
    CopyWeekRequest,
    ScheduleEntryResponse,
)
from app.modules.scheduling_v2.service import SchedulingService

ORG_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
SOURCE_WEEK_START = date(2026, 6, 1)  # Monday
TARGET_WEEK_START = date(2026, 6, 8)  # Monday + 7 days
SOURCE_DT_BASE = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _make_source_entry(
    *,
    offset_hours: int = 0,
    duration_hours: int = 2,
    title: str = "Existing shift",
    description: str | None = "desc",
    notes: str | None = "notes",
    entry_type: str = "job",
    status: str = "completed",  # ensure copy resets to 'scheduled'
    recurrence_group_id: uuid.UUID | None = None,
) -> ScheduleEntry:
    if recurrence_group_id is None:
        recurrence_group_id = uuid.uuid4()  # source IS recurring; copy must clear
    e = ScheduleEntry(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_id=STAFF_ID,
        title=title,
        description=description,
        notes=notes,
        start_time=SOURCE_DT_BASE + timedelta(hours=offset_hours),
        end_time=SOURCE_DT_BASE + timedelta(hours=offset_hours + duration_hours),
        entry_type=entry_type,
        status=status,
        recurrence_group_id=recurrence_group_id,
        created_at=SOURCE_DT_BASE,
        updated_at=SOURCE_DT_BASE,
    )
    return e


def _make_mock_db(*, sources: list[ScheduleEntry]) -> AsyncMock:
    """Build a mock async session whose first ``execute`` returns the
    source entries; subsequent ``execute`` calls (audit log INSERT)
    return an empty result.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.delete = AsyncMock()

    @asynccontextmanager
    async def fake_begin_nested():
        yield SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())

    mock_db.begin_nested = fake_begin_nested

    call_count = {"n": 0}

    async def fake_execute(stmt, params=None):
        call_count["n"] += 1
        result = MagicMock()
        # First call is the SELECT for source entries.
        if call_count["n"] == 1:
            result.scalars.return_value.all.return_value = list(sources)
        else:
            result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        return result

    mock_db.execute = fake_execute

    # Populate created entries when refresh is called inside bulk_create.
    async def fake_refresh(entry):
        if not getattr(entry, "id", None):
            entry.id = uuid.uuid4()
        if not getattr(entry, "status", None):
            entry.status = "scheduled"
        if not getattr(entry, "created_at", None):
            entry.created_at = datetime.now(timezone.utc)
        if not getattr(entry, "updated_at", None):
            entry.updated_at = datetime.now(timezone.utc)

    mock_db.refresh = fake_refresh
    return mock_db


class TestCopyWeekValidation:
    @pytest.mark.asyncio
    async def test_zero_delta_raises_value_error(self):
        mock_db = _make_mock_db(sources=[])
        svc = SchedulingService(mock_db)
        with pytest.raises(ValueError, match="multiple of 7 days"):
            await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=SOURCE_WEEK_START,
                    target_week_start=SOURCE_WEEK_START,
                ),
            )

    @pytest.mark.asyncio
    async def test_non_seven_day_delta_raises_value_error(self):
        mock_db = _make_mock_db(sources=[])
        svc = SchedulingService(mock_db)
        with pytest.raises(ValueError, match="multiple of 7 days"):
            await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=SOURCE_WEEK_START,
                    target_week_start=SOURCE_WEEK_START + timedelta(days=3),
                ),
            )

    @pytest.mark.asyncio
    async def test_fourteen_day_delta_is_accepted(self):
        mock_db = _make_mock_db(sources=[])
        svc = SchedulingService(mock_db)
        # No sources → no creates, no conflicts; just verifies the
        # delta validation accepts a 14-day shift.
        created, conflicts = await svc.copy_week(
            ORG_ID,
            CopyWeekRequest(
                source_week_start=SOURCE_WEEK_START,
                target_week_start=SOURCE_WEEK_START + timedelta(days=14),
            ),
        )
        assert created == []
        assert conflicts == []


class TestCopyWeekPreservesDurationAndMetadata:
    """For every created entry: duration + metadata match the source,
    ``recurrence_group_id`` is None, and ``status`` defaults to
    ``'scheduled'`` (R8.4 / R8.5 / R8.6 / R14.2).
    """

    @pytest.mark.asyncio
    @given(
        offset_minutes=st.integers(min_value=0, max_value=60 * 24 * 6),
        duration_minutes=st.integers(min_value=15, max_value=60 * 8),
    )
    @settings(max_examples=25, deadline=None)
    async def test_property_preserves_duration_and_metadata(
        self, offset_minutes, duration_minutes,
    ):
        source_start = SOURCE_DT_BASE + timedelta(minutes=offset_minutes)
        source_end = source_start + timedelta(minutes=duration_minutes)
        src = ScheduleEntry(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            staff_id=STAFF_ID,
            title="prop title",
            description="prop description",
            notes="prop notes",
            start_time=source_start,
            end_time=source_end,
            entry_type="booking",
            status="completed",
            recurrence_group_id=uuid.uuid4(),
            created_at=SOURCE_DT_BASE,
            updated_at=SOURCE_DT_BASE,
        )

        mock_db = _make_mock_db(sources=[src])
        svc = SchedulingService(mock_db)

        with patch.object(svc, "detect_conflicts", AsyncMock(return_value=[])):
            created, conflicts = await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=SOURCE_WEEK_START,
                    target_week_start=TARGET_WEEK_START,
                ),
            )

        assert conflicts == []
        assert len(created) == 1
        copy = created[0]
        # Duration preserved.
        assert (copy.end_time - copy.start_time) == (src.end_time - src.start_time)
        # Time shifted by exactly +7 days.
        assert copy.start_time - src.start_time == timedelta(days=7)
        assert copy.end_time - src.end_time == timedelta(days=7)
        # Metadata preserved.
        assert copy.entry_type == src.entry_type
        assert copy.title == src.title
        assert copy.description == src.description
        assert copy.notes == src.notes
        assert copy.staff_id == src.staff_id
        # recurrence_group_id forced to None.
        assert copy.recurrence_group_id is None
        # status defaults to 'scheduled' (set on row creation).
        assert copy.status == "scheduled"


class TestCopyWeekOverwriteDeletesTargets:
    @pytest.mark.asyncio
    async def test_overwrite_deletes_overlapping_target_entries(self):
        src = _make_source_entry(offset_hours=0, duration_hours=2)
        existing_target = _make_source_entry(
            offset_hours=24 * 7,  # week +1 already has an entry
            duration_hours=2,
            title="Existing Target",
            recurrence_group_id=None,
        )
        existing_target.start_time = src.start_time + timedelta(days=7)
        existing_target.end_time = src.end_time + timedelta(days=7)

        mock_db = _make_mock_db(sources=[src])
        svc = SchedulingService(mock_db)

        # detect_conflicts called twice during overwrite — once for
        # the deletion pass (returns the existing target) and again
        # inside bulk_create (returns empty so the insert succeeds).
        seen_calls = {"n": 0}

        async def fake_detect_conflicts(org_id, staff_id, start_time, end_time, **kwargs):
            seen_calls["n"] += 1
            if seen_calls["n"] == 1:
                return [existing_target]
            return []

        with patch.object(svc, "detect_conflicts", side_effect=fake_detect_conflicts):
            created, conflicts = await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=SOURCE_WEEK_START,
                    target_week_start=TARGET_WEEK_START,
                    overwrite_existing=True,
                ),
            )

        # Existing target was deleted before insert.
        mock_db.delete.assert_awaited_with(existing_target)
        assert len(created) == 1
        assert conflicts == []


class TestCopyWeekSkipOnConflict:
    @pytest.mark.asyncio
    async def test_no_overwrite_skips_when_target_conflicts(self):
        src = _make_source_entry(offset_hours=0, duration_hours=2)
        existing_target = _make_source_entry(
            offset_hours=24 * 7,
            duration_hours=2,
            title="Existing Target",
            recurrence_group_id=None,
        )

        mock_db = _make_mock_db(sources=[src])
        svc = SchedulingService(mock_db)

        async def fake_detect_conflicts(org_id, staff_id, start_time, end_time, **kwargs):
            return [existing_target]

        with patch.object(svc, "detect_conflicts", side_effect=fake_detect_conflicts):
            created, conflicts = await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=SOURCE_WEEK_START,
                    target_week_start=TARGET_WEEK_START,
                    overwrite_existing=False,
                ),
            )

        # No created entries — the source was skipped.
        assert created == []
        assert len(conflicts) == 1
        # Existing target was NOT deleted.
        mock_db.delete.assert_not_awaited()


class TestCopyWeekResponseRoundTrip:
    @pytest.mark.asyncio
    async def test_response_round_trips_through_schema(self):
        src = _make_source_entry(offset_hours=0, duration_hours=2)
        mock_db = _make_mock_db(sources=[src])
        svc = SchedulingService(mock_db)

        with patch.object(svc, "detect_conflicts", AsyncMock(return_value=[])):
            created, conflicts = await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=SOURCE_WEEK_START,
                    target_week_start=TARGET_WEEK_START,
                ),
            )

        response = BulkScheduleEntryResponse(
            created=[ScheduleEntryResponse.model_validate(e) for e in created],
            conflicts=conflicts,
        )
        raw = response.model_dump()
        round_tripped = BulkScheduleEntryResponse.model_validate(raw)
        assert round_tripped == response
