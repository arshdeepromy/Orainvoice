"""Unit tests for ``app.modules.time_clock.service.report_running_late`` (G3).

Covers Phase 3 R14b / G3:

1. Endpoint accepts in-window report → SMS sent to manager + Redis snooze
   key set with `(minutes_late + 30) * 60` seconds TTL + audit row
   ``staff.reported_late`` written.
2. No in-window shift → :class:`NoUpcomingShiftError` (router → 422
   ``no_upcoming_shift``).
3. Per-shift rate limit (3/shift over 4h) → 4th call raises
   :class:`TooManyLateReportsError` (router → 429
   ``too_many_late_reports``).

Mirrors the patterns used by ``tests/unit/test_time_clock_service.py``.

**Validates: Requirements R14b — Staff Management Phase 3 (G3)**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure SQLAlchemy mappers are registered.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.service import (
    NoUpcomingShiftError,
    TooManyLateReportsError,
    report_running_late,
)


def _make_staff(
    *,
    org_id: uuid.UUID,
    phone: str | None = "+64211234567",
    first_name: str = "Jane",
    reporting_to: uuid.UUID | None = None,
) -> StaffMember:
    return StaffMember(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        name=f"{first_name} Doe",
        first_name=first_name,
        last_name="Doe",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        employee_id="EMP-001",
        phone=phone,
        self_service_clock_enabled=True,
        on_file_photo_url=None,
        employment_type="permanent",
        reporting_to=reporting_to,
    )


def _make_in_window_shift(*, org_id: uuid.UUID, staff_id: uuid.UUID) -> ScheduleEntry:
    """A shift starting 15 minutes from now."""
    start = datetime.now(timezone.utc) + timedelta(minutes=15)
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=start,
        end_time=start + timedelta(hours=8),
        entry_type="job",
        status="scheduled",
    )


class _FakeRedis:
    """In-memory Redis double covering ``incr``, ``expire``, and ``set``."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expires: dict[str, int] = {}
        self.values: dict[str, str] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expires[key] = ex
        return True


def _make_db(
    *,
    staff: StaffMember,
    shift: ScheduleEntry | None,
    manager: StaffMember | None = None,
    no_org_admin: bool = False,
) -> AsyncMock:
    """Build an :class:`AsyncMock` DB session.

    Resolves:
      - ``execute(select(ScheduleEntry)…)`` → the in-window shift (or empty).
      - ``execute(select(User)…)`` → simulates an org_admin lookup.
      - ``db.get(StaffMember, ...)`` → the manager (when set).
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _fake_get(model, key):
        if model is StaffMember and manager is not None and key == manager.id:
            return manager
        return None

    db.get = AsyncMock(side_effect=_fake_get)

    async def _fake_execute(stmt, params=None):
        result = MagicMock()
        rendered = str(stmt).lower()
        try:
            text_repr = (stmt.text or "").lower()
        except AttributeError:
            text_repr = ""

        # find_in_window_shift uses select(ScheduleEntry).
        if "schedule_entries" in rendered and "start_time" in rendered:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [shift] if shift else []
            result.scalars.return_value = scalars_mock
            return result

        # _resolve_running_late_recipient → org_admin lookup.
        if "users" in rendered and "org_admin" in rendered:
            if no_org_admin:
                result.scalar_one_or_none.return_value = None
            else:
                # Return a fake user object — but we don't go down this
                # path in the happy-path test (manager has phone).
                result.scalar_one_or_none.return_value = None
            return result

        # staff phone for org_admin fallback.
        if "staff_members" in rendered and "phone" in rendered:
            result.scalar_one_or_none.return_value = None
            return result

        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db


@pytest.fixture
def captured_audit():
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.service.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


@pytest.fixture
def captured_sms():
    sent: list[dict] = []

    async def _fake_send(db, *, to_phone, body, **kwargs):
        sent.append({"to_phone": to_phone, "body": body, **kwargs})
        return SimpleNamespace(ok=True, message_id="m1")

    with patch(
        "app.integrations.sms_sender.send_sms",
        side_effect=_fake_send,
    ):
        yield sent


class TestReportRunningLate:

    @pytest.mark.asyncio
    async def test_in_window_shift_sends_sms_and_snoozes(
        self, captured_audit, captured_sms,
    ):
        """Verify line 1: in-window report → manager SMS + snooze + audit."""
        org_id = uuid.uuid4()
        manager = _make_staff(org_id=org_id, first_name="Bob", phone="+64211111111")
        staff = _make_staff(
            org_id=org_id,
            first_name="Alice",
            reporting_to=manager.id,
        )
        shift = _make_in_window_shift(org_id=org_id, staff_id=staff.id)
        db = _make_db(staff=staff, shift=shift, manager=manager)
        redis = _FakeRedis()

        result = await report_running_late(
            db,
            org_id=org_id,
            staff=staff,
            minutes_late=20,
            reason="Traffic",
            redis=redis,
        )

        assert result["ok"] is True
        assert "snoozed_until" in result

        # SMS sent to the manager.
        assert len(captured_sms) == 1
        assert captured_sms[0]["to_phone"] == manager.phone
        assert "Alice" in captured_sms[0]["body"]
        assert "20 min" in captured_sms[0]["body"]
        assert "Traffic" in captured_sms[0]["body"]

        # Snooze key set with proper TTL: (minutes_late + 30) * 60.
        snooze_key = f"late:{shift.id}"
        assert snooze_key in redis.values
        assert redis.expires.get(snooze_key) == (20 + 30) * 60

        # Audit row written.
        actions = [a.get("action") for a in captured_audit]
        assert "staff.reported_late" in actions
        late_audit = next(
            a for a in captured_audit
            if a.get("action") == "staff.reported_late"
        )
        assert late_audit["after_value"]["minutes_late"] == 20
        assert late_audit["after_value"]["reason"] == "Traffic"

    @pytest.mark.asyncio
    async def test_no_in_window_shift_raises_no_upcoming(
        self, captured_audit, captured_sms,
    ):
        """Verify line 2: no in-window shift → NoUpcomingShiftError."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff=staff, shift=None)
        redis = _FakeRedis()

        with pytest.raises(NoUpcomingShiftError):
            await report_running_late(
                db,
                org_id=org_id,
                staff=staff,
                minutes_late=15,
                redis=redis,
            )

    @pytest.mark.asyncio
    async def test_rate_limit_3_per_shift(self, captured_audit, captured_sms):
        """Verify line 3: 4th call for the same shift raises TooManyLateReports."""
        org_id = uuid.uuid4()
        manager = _make_staff(org_id=org_id, phone="+64211111111")
        staff = _make_staff(org_id=org_id, reporting_to=manager.id)
        shift = _make_in_window_shift(org_id=org_id, staff_id=staff.id)
        db = _make_db(staff=staff, shift=shift, manager=manager)
        redis = _FakeRedis()

        # First 3 succeed.
        for _ in range(3):
            await report_running_late(
                db,
                org_id=org_id,
                staff=staff,
                minutes_late=10,
                redis=redis,
            )

        # 4th raises.
        with pytest.raises(TooManyLateReportsError):
            await report_running_late(
                db,
                org_id=org_id,
                staff=staff,
                minutes_late=10,
                redis=redis,
            )

    @pytest.mark.asyncio
    async def test_check_late_arrivals_skips_snoozed_shift(
        self, captured_audit, captured_sms,
    ):
        """Verify the check_late_arrivals task respects the snooze key.

        The check_late_arrivals task uses `redis.get(f'late:{shift_id}')`
        and skips when the key exists. This test verifies the snooze
        key set by report_running_late lands in the expected shape.
        """
        org_id = uuid.uuid4()
        manager = _make_staff(org_id=org_id, phone="+64211111111")
        staff = _make_staff(org_id=org_id, reporting_to=manager.id)
        shift = _make_in_window_shift(org_id=org_id, staff_id=staff.id)
        db = _make_db(staff=staff, shift=shift, manager=manager)
        redis = _FakeRedis()

        await report_running_late(
            db,
            org_id=org_id,
            staff=staff,
            minutes_late=15,
            redis=redis,
        )

        # The key the scheduled task checks: late:{shift_id}
        assert f"late:{shift.id}" in redis.values
