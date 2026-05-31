"""Unit tests for ``SchedulingService.bulk_create``.

**Validates: Roster Grid Editor — task A2 (R11.3, R11.4, R11.5).**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.scheduling_v2.schemas import (
    BulkScheduleEntryCreateRequest,
    BulkScheduleEntryResponse,
    ScheduleEntryCreate,
    ScheduleEntryResponse,
)
from app.modules.scheduling_v2.service import SchedulingService

ORG_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
BASE_TIME = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _make_entry_payload(*, offset_hours: int = 0, duration_hours: int = 2) -> ScheduleEntryCreate:
    return ScheduleEntryCreate(
        staff_id=STAFF_ID,
        title=f"Shift +{offset_hours}h",
        start_time=BASE_TIME + timedelta(hours=offset_hours),
        end_time=BASE_TIME + timedelta(hours=offset_hours + duration_hours),
        entry_type="job",
    )


def _make_existing_entry(*, offset_hours: int = 0, duration_hours: int = 2) -> ScheduleEntry:
    """Build a fully-populated ScheduleEntry (mimics a row already in the DB)."""
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        staff_id=STAFF_ID,
        title=f"Existing +{offset_hours}h",
        start_time=BASE_TIME + timedelta(hours=offset_hours),
        end_time=BASE_TIME + timedelta(hours=offset_hours + duration_hours),
        entry_type="job",
        status="scheduled",
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def _make_mock_db(*, conflicts_per_call: list[list[ScheduleEntry]] | None = None) -> AsyncMock:
    """Build a mock async session.

    ``conflicts_per_call`` — if provided, the i-th call to
    ``detect_conflicts`` returns ``conflicts_per_call[i]``. Other DB
    operations (``add``, ``flush``, ``refresh``, ``begin_nested``,
    ``execute``) are stubbed out.
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

    # write_audit_log calls db.execute with a SQL text — return a no-op
    async def fake_execute(stmt, params=None):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        return result

    mock_db.execute = fake_execute
    return mock_db


class TestBulkCreatePartialConflict:
    """5 entries where the 3rd overlaps an existing entry → 4 created, 1 conflict."""

    @pytest.mark.asyncio
    async def test_partial_conflict_keeps_remaining_entries(self):
        mock_db = _make_mock_db()
        existing = _make_existing_entry(offset_hours=4, duration_hours=2)

        # Patch detect_conflicts: only the 3rd entry (offset 4h, index=2)
        # collides with `existing`. Indexes 0/1/3/4 are clean.
        async def fake_detect_conflicts(org_id, staff_id, start_time, end_time, **kwargs):
            # Index 2 has start_time == BASE_TIME + 4h; conflict.
            if start_time == BASE_TIME + timedelta(hours=4):
                return [existing]
            return []

        svc = SchedulingService(mock_db)
        entries = [
            _make_entry_payload(offset_hours=0),
            _make_entry_payload(offset_hours=2),
            _make_entry_payload(offset_hours=4),  # conflict
            _make_entry_payload(offset_hours=6),
            _make_entry_payload(offset_hours=8),
        ]
        payload = BulkScheduleEntryCreateRequest(entries=entries)

        with patch.object(svc, "detect_conflicts", side_effect=fake_detect_conflicts):
            created, conflicts = await svc.bulk_create(ORG_ID, payload)

        assert len(created) == 4
        assert len(conflicts) == 1
        assert conflicts[0].index == 2
        # The attempted entry round-trips back unchanged.
        assert conflicts[0].attempted.start_time == BASE_TIME + timedelta(hours=4)
        # The conflict's conflicts_with array is populated.
        assert len(conflicts[0].conflicts_with) == 1


class TestBulkCreateInvalidEntry:
    """An entry with end_time <= start_time becomes a conflict-style failure."""

    @pytest.mark.asyncio
    async def test_invalid_end_before_start_lands_in_conflicts(self):
        mock_db = _make_mock_db()
        svc = SchedulingService(mock_db)

        bad = ScheduleEntryCreate(
            staff_id=STAFF_ID,
            title="bad",
            start_time=BASE_TIME + timedelta(hours=2),
            end_time=BASE_TIME + timedelta(hours=2),  # equal — invalid
            entry_type="job",
        )
        good = _make_entry_payload(offset_hours=4)
        payload = BulkScheduleEntryCreateRequest(entries=[bad, good])

        with patch.object(svc, "detect_conflicts", AsyncMock(return_value=[])):
            created, conflicts = await svc.bulk_create(ORG_ID, payload)

        assert len(created) == 1
        assert len(conflicts) == 1
        assert conflicts[0].index == 0
        assert conflicts[0].conflicts_with == []


class TestBulkCreatePydanticRoundTrip:
    """The response must round-trip through ``BulkScheduleEntryResponse``
    without losing keys (closes GAP-S7 for A2).
    """

    @pytest.mark.asyncio
    async def test_response_round_trips_through_schema(self):
        mock_db = _make_mock_db()
        svc = SchedulingService(mock_db)

        # Stub refresh so the ScheduleEntry has all required fields when
        # ScheduleEntryResponse.model_validate is called inside the
        # bulk_create's success path.
        def populate_entry(entry):
            entry.id = uuid.uuid4()
            entry.status = "scheduled"
            entry.created_at = BASE_TIME
            entry.updated_at = BASE_TIME

        async def fake_refresh(entry):
            populate_entry(entry)

        mock_db.refresh = fake_refresh

        entries = [_make_entry_payload(offset_hours=0), _make_entry_payload(offset_hours=4)]
        payload = BulkScheduleEntryCreateRequest(entries=entries)

        with patch.object(svc, "detect_conflicts", AsyncMock(return_value=[])):
            created, conflicts = await svc.bulk_create(ORG_ID, payload)

        # Build the response shape and round-trip it through the schema.
        response = BulkScheduleEntryResponse(
            created=[ScheduleEntryResponse.model_validate(e) for e in created],
            conflicts=conflicts,
        )
        raw = response.model_dump()
        round_tripped = BulkScheduleEntryResponse.model_validate(raw)
        assert round_tripped == response
        # Keys exist as expected.
        assert "created" in raw
        assert "conflicts" in raw
        assert isinstance(raw["created"], list)
        assert isinstance(raw["conflicts"], list)
