"""Schema validation tests for the bulk + copy-week scheduling schemas.

**Validates: Roster Grid Editor — task A1 (R11.1, R11.2).**
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.modules.scheduling_v2.schemas import (
    BulkConflictItem,
    BulkScheduleEntryCreateRequest,
    BulkScheduleEntryResponse,
    CopyWeekRequest,
    ScheduleEntryCreate,
)


def _make_entry(offset_minutes: int = 0) -> dict:
    """Return a JSON-shaped ScheduleEntryCreate payload."""
    base = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc) + timedelta(
        minutes=offset_minutes,
    )
    return {
        "start_time": base.isoformat(),
        "end_time": (base + timedelta(hours=2)).isoformat(),
        "title": "Test shift",
        "entry_type": "job",
    }


class TestBulkScheduleEntryCreateRequestBoundaries:
    """The bulk request must reject 0 entries and >200 entries; 200 is
    the documented hard cap.
    """

    def test_bulk_request_rejects_zero_entries(self):
        with pytest.raises(ValidationError) as exc_info:
            BulkScheduleEntryCreateRequest(entries=[])
        # The error must point at the entries field's min_length.
        msg = str(exc_info.value)
        assert "entries" in msg
        assert "at least 1" in msg or "min_length" in msg or "too_short" in msg

    def test_bulk_request_accepts_exactly_200_entries(self):
        entries = [_make_entry(i) for i in range(200)]
        req = BulkScheduleEntryCreateRequest(entries=entries)
        assert len(req.entries) == 200
        assert all(isinstance(e, ScheduleEntryCreate) for e in req.entries)

    def test_bulk_request_rejects_201_entries(self):
        entries = [_make_entry(i) for i in range(201)]
        with pytest.raises(ValidationError) as exc_info:
            BulkScheduleEntryCreateRequest(entries=entries)
        msg = str(exc_info.value)
        assert "entries" in msg
        assert "at most 200" in msg or "max_length" in msg or "too_long" in msg


class TestCopyWeekRequest:
    def test_default_overwrite_existing_is_false(self):
        req = CopyWeekRequest(
            source_week_start=date(2026, 6, 1),
            target_week_start=date(2026, 6, 8),
        )
        assert req.overwrite_existing is False

    def test_overwrite_existing_can_be_true(self):
        req = CopyWeekRequest(
            source_week_start=date(2026, 6, 1),
            target_week_start=date(2026, 6, 8),
            overwrite_existing=True,
        )
        assert req.overwrite_existing is True


class TestBulkScheduleEntryResponseDefaults:
    def test_default_response_has_empty_arrays(self):
        resp = BulkScheduleEntryResponse()
        assert resp.created == []
        assert resp.conflicts == []

    def test_bulk_conflict_item_default_conflicts_with_is_empty_list(self):
        attempted = ScheduleEntryCreate(**_make_entry())
        item = BulkConflictItem(index=0, attempted=attempted)
        assert item.conflicts_with == []
