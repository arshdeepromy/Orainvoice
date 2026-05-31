"""Integration tests for the audit log writes from
``SchedulingService.bulk_create`` and ``SchedulingService.copy_week``.

Verifies that exactly one ``audit_log`` row is written per call, with
``action='schedule.bulk_created'`` (or ``'schedule.copied_week'``) and
the ``after_value`` payload is summary-only (no per-entry data).

**Validates: Roster Grid Editor — task A4 (R17.3).**
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.scheduling_v2.schemas import (
    BulkScheduleEntryCreateRequest,
    CopyWeekRequest,
    ScheduleEntryCreate,
)
from app.modules.scheduling_v2.service import SchedulingService

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
BASE_TIME = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _make_entry_payload(*, offset_hours: int = 0) -> ScheduleEntryCreate:
    return ScheduleEntryCreate(
        staff_id=STAFF_ID,
        title=f"Shift +{offset_hours}h",
        start_time=BASE_TIME + timedelta(hours=offset_hours),
        end_time=BASE_TIME + timedelta(hours=offset_hours + 2),
        entry_type="job",
    )


class _AuditCapturingDB:
    """Minimal fake AsyncSession that captures every audit_log INSERT.

    The ``write_audit_log`` helper calls ``session.execute(text(...),
    params)`` with the audit row's params. We capture the params dicts
    in ``self.audit_writes`` for the test to inspect.
    """

    def __init__(self, *, source_entries: list[ScheduleEntry] | None = None) -> None:
        self.audit_writes: list[dict] = []
        self.added: list[ScheduleEntry] = []
        self.deleted: list = []
        self._source_entries = source_entries or []
        self._select_calls = 0

    def add(self, entry):
        self.added.append(entry)

    async def flush(self):
        return None

    async def refresh(self, entry):
        if not getattr(entry, "id", None):
            entry.id = uuid.uuid4()
        if not getattr(entry, "status", None):
            entry.status = "scheduled"
        if not getattr(entry, "created_at", None):
            entry.created_at = datetime.now(timezone.utc)
        if not getattr(entry, "updated_at", None):
            entry.updated_at = datetime.now(timezone.utc)

    async def delete(self, entry):
        self.deleted.append(entry)

    @asynccontextmanager
    async def begin_nested(self):
        yield SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        # The audit-log helper uses raw SQL with INSERT INTO audit_log.
        if "INSERT INTO audit_log" in sql or "audit_log" in sql.lower() and "insert" in sql.lower():
            if params is not None:
                self.audit_writes.append(params)
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar.return_value = 0
            return result
        # The first SELECT in copy_week pulls source entries.
        if "select" in sql.lower():
            self._select_calls += 1
            result = MagicMock()
            if self._select_calls == 1 and self._source_entries:
                result.scalars.return_value.all.return_value = list(self._source_entries)
            else:
                result.scalars.return_value.all.return_value = []
            result.scalar.return_value = 0
            return result
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        return result


def _decode_after_value(params: dict) -> dict:
    raw = params.get("after_value")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


class TestBulkCreateAuditLog:
    @pytest.mark.asyncio
    async def test_bulk_create_writes_one_summary_audit_row(self):
        db = _AuditCapturingDB()
        svc = SchedulingService(db)

        # 3 entries: index 1 conflicts, indexes 0 and 2 succeed.
        entries = [
            _make_entry_payload(offset_hours=0),
            _make_entry_payload(offset_hours=2),
            _make_entry_payload(offset_hours=4),
        ]

        existing_conflict = ScheduleEntry(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            staff_id=STAFF_ID,
            title="Existing",
            start_time=BASE_TIME + timedelta(hours=2),
            end_time=BASE_TIME + timedelta(hours=4),
            entry_type="job",
            status="scheduled",
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )

        async def fake_detect_conflicts(org_id, staff_id, start_time, end_time, **kwargs):
            if start_time == BASE_TIME + timedelta(hours=2):
                return [existing_conflict]
            return []

        with patch.object(svc, "detect_conflicts", side_effect=fake_detect_conflicts):
            created, conflicts = await svc.bulk_create(
                ORG_ID,
                BulkScheduleEntryCreateRequest(entries=entries),
                user_id=USER_ID,
            )

        assert len(created) == 2
        assert len(conflicts) == 1

        # Exactly one audit row should have been written for bulk_create.
        bulk_rows = [
            p for p in db.audit_writes if p.get("action") == "schedule.bulk_created"
        ]
        assert len(bulk_rows) == 1
        row = bulk_rows[0]
        assert row["entity_type"] == "schedule_entry"
        assert row["entity_id"] is None
        assert row["org_id"] == str(ORG_ID)
        assert row["user_id"] == str(USER_ID)
        assert row["before_value"] is None

        after = _decode_after_value(row)
        assert after.get("created_count") == 2
        assert after.get("conflicts_count") == 1

        # Forbidden: no per-entry payload may appear in after_value.
        for key in after.keys():
            assert "entry" not in key.lower(), (
                f"after_value must not contain a per-entry key, found {key!r}"
            )
            assert "entries" not in key.lower(), (
                f"after_value must not contain a per-entry-list key, found {key!r}"
            )


class TestCopyWeekAuditLog:
    @pytest.mark.asyncio
    async def test_copy_week_writes_summary_with_source_target_overwrite(self):
        # Build a single source entry so bulk_create runs once.
        src = ScheduleEntry(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            staff_id=STAFF_ID,
            title="Source",
            start_time=BASE_TIME,
            end_time=BASE_TIME + timedelta(hours=2),
            entry_type="job",
            status="scheduled",
            created_at=BASE_TIME,
            updated_at=BASE_TIME,
        )

        db = _AuditCapturingDB(source_entries=[src])
        svc = SchedulingService(db)

        with patch.object(svc, "detect_conflicts", AsyncMock(return_value=[])):
            created, conflicts = await svc.copy_week(
                ORG_ID,
                CopyWeekRequest(
                    source_week_start=BASE_TIME.date(),
                    target_week_start=BASE_TIME.date() + timedelta(days=7),
                    overwrite_existing=False,
                ),
                user_id=USER_ID,
            )

        assert len(created) == 1
        assert conflicts == []

        copy_rows = [
            p for p in db.audit_writes if p.get("action") == "schedule.copied_week"
        ]
        assert len(copy_rows) == 1
        row = copy_rows[0]
        after = _decode_after_value(row)
        assert after.get("created_count") == 1
        assert after.get("conflicts_count") == 0
        assert after.get("source_week_start") == BASE_TIME.date().isoformat()
        assert after.get("target_week_start") == (
            BASE_TIME.date() + timedelta(days=7)
        ).isoformat()
        assert after.get("overwrite_existing") is False

        for key in after.keys():
            assert "entry" not in key.lower() or key in {
                "source_week_start",
                "target_week_start",
            }
            # The forbidden keys are exactly per-entry payloads — the
            # documented summary keys above are safe.
