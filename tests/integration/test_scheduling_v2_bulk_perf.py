"""Backend bulk-create timing test (D3).

Times ``SchedulingService.bulk_create`` over a 200-entry payload and
prints the elapsed wall-clock seconds. We do NOT hard-assert a
threshold — the spec (R19.4) calls for the number to be tracked
rather than baked into a brittle CI gate (timings vary wildly across
dev / Pi / CI runners).

Gated behind ``RUN_PERF=1`` so CI does not run it by default. Run
locally with:

    RUN_PERF=1 pytest tests/integration/test_scheduling_v2_bulk_perf.py -q -s

Validates: Roster Grid Editor — task D3 (R19.4).
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.scheduling_v2.schemas import (
    BulkScheduleEntryCreateRequest,
    ScheduleEntryCreate,
)
from app.modules.scheduling_v2.service import SchedulingService

ORG_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
BASE_TIME = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _make_mock_db() -> AsyncMock:
    """Mock async session matching the pattern used by the unit
    bulk-create suite — every DB op is a no-op so we time the
    Python-level orchestration cost only.
    """
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()
    mock_db.delete = AsyncMock()

    @asynccontextmanager
    async def fake_begin_nested():
        yield SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())

    mock_db.begin_nested = fake_begin_nested

    async def fake_execute(stmt, params=None):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        return result

    mock_db.execute = fake_execute

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


def _make_payload(n: int) -> BulkScheduleEntryCreateRequest:
    """Build a 200-entry payload with non-overlapping time windows."""
    entries: list[ScheduleEntryCreate] = []
    for i in range(n):
        # 30-minute spacing so detect_conflicts (mocked to []) won't
        # flag overlaps in the real path.
        start = BASE_TIME + timedelta(minutes=30 * i)
        end = start + timedelta(minutes=15)
        entries.append(
            ScheduleEntryCreate(
                staff_id=STAFF_ID,
                title=f"Shift {i}",
                start_time=start,
                end_time=end,
                entry_type="job",
            ),
        )
    return BulkScheduleEntryCreateRequest(entries=entries)


@pytest.mark.skipif(
    not os.getenv("RUN_PERF"),
    reason="Set RUN_PERF=1 to run the backend bulk-create perf test (D3)",
)
@pytest.mark.asyncio
async def test_bulk_create_200_entries_timing() -> None:
    mock_db = _make_mock_db()
    svc = SchedulingService(mock_db)
    payload = _make_payload(200)

    with patch.object(svc, "detect_conflicts", AsyncMock(return_value=[])):
        start = time.monotonic()
        created, conflicts = await svc.bulk_create(ORG_ID, payload)
        elapsed = time.monotonic() - start

    print(
        f"\n[D3] bulk_create(200 entries): elapsed={elapsed:.3f}s, "
        f"created={len(created)}, conflicts={len(conflicts)}",
    )

    # No hard threshold per the spec — the number is tracked, not
    # asserted. We still confirm the call succeeded end-to-end.
    assert len(created) + len(conflicts) == 200
    assert len(created) <= 200
