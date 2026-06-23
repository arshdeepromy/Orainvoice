"""Unit tests for ``app.modules.time_clock.service`` (task B3).

Covers task B3 from `.kiro/specs/staff-management-p3`:

1. Kiosk lookup happy path — returns staff identity dict.
2. Kiosk lookup → 422 when no active staff matches the employee_id.
3. Kiosk lookup G12 rate-limit — 11th call within 60s raises
   :class:`KioskLookupRateLimitedError` and writes
   ``kiosk.lookup_rate_limited`` audit row with the SHA-256 hash
   (raw employee_id never logged).
4. Kiosk in/out round-trip — clock-in inserts row with
   ``source='kiosk'`` + ``scheduled_entry_id`` matched + audit
   ``time_clock.in``; clock-out updates the open row, computes
   ``worked_minutes`` per R3.7, audit ``time_clock.out``.
5. Kiosk action without ``photo_file_key`` → :class:`PhotoRequiredError`.
6. Self-service in/out — refuses 403 when
   ``self_service_clock_enabled=false``; succeeds when enabled.
7. Self-service photo policy — refuses with
   :class:`PhotoRequiredError` when
   ``self_service_require_photo=true`` and key missing.
8. Auto-match scheduled_entry — picks the schedule_entries row whose
   window contains the clock-in time (R3.8).
9. Admin manual entry — inserts ``source='admin_manual'``, audit
   ``time_clock.added`` with ``after_value``.
10. Admin manual entry refuses :class:`LockedWeekError` when the
    ``clock_in_at`` falls inside an approved week (R9.3).
11. ``worked_minutes`` calc handles break deduction correctly (R3.7).
12. Admin manual update writes ``before_value`` + ``after_value``
    (R5.4 / P3-N5).

The DB session is mocked with ``AsyncMock`` following the same pattern
used by Phase 2's ``tests/unit/test_leave_request_workflow.py``.

**Validates: Requirements R3, R4, R5, R8, R9 — Staff Management Phase 3 task B3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure auth.User and admin.Organisation mappers are registered before
# any StaffMember mapper config kicks in. SQLAlchemy resolves
# string-name relationships at first instance creation, and StaffMember
# / Organisation reference each other; importing both up-front avoids
# the ``KeyError: 'Organisation'`` that otherwise surfaces deep inside
# the mapper init.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry, TimesheetApproval
from app.modules.time_clock.service import (
    EmployeeNotFoundError,
    InvalidActionError,
    KioskLookupRateLimitedError,
    LockedWeekError,
    PhotoRequiredError,
    SelfServiceDisabledError,
    StaffNotFoundError,
    TimeClockEntryNotFoundError,
    _compute_worked_minutes,
    _hash_employee_id,
    admin_manual_entry,
    kiosk_clock_action,
    lookup_for_kiosk,
    self_service_clock_action,
    update_manual_entry,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_staff(
    *,
    org_id: uuid.UUID,
    employee_id: str = "EMP-001",
    self_service: bool = False,
    is_active: bool = True,
    **kwargs,
) -> StaffMember:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        role_type="employee",
        is_active=is_active,
        availability_schedule={},
        skills=[],
        employee_id=employee_id,
        self_service_clock_enabled=self_service,
        on_file_photo_url="https://uploads/staff/jane.jpg",
        employment_type="permanent",
    )
    defaults.update(kwargs)
    return StaffMember(**defaults)


def _make_schedule_entry(
    *,
    staff_id: uuid.UUID,
    org_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
    entry_type: str = "job",
    status: str = "scheduled",
) -> ScheduleEntry:
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=start_time,
        end_time=end_time,
        entry_type=entry_type,
        status=status,
    )


class _FakeRedis:
    """In-memory Redis double covering ``incr`` + ``expire`` (the only
    two ops :func:`_check_kiosk_lookup_rate_limit` calls). Keeps state
    so a sequence of calls trips the budget at the same point a real
    Redis would.
    """

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = seconds
        return True


def _make_db(
    *,
    staff_by_id: dict[uuid.UUID, StaffMember] | None = None,
    staff_by_employee_id: StaffMember | None = None,
    open_entry: TimeClockEntry | None = None,
    schedule_entries: list[ScheduleEntry] | None = None,
    locked_week_for: tuple[uuid.UUID, datetime.date] | None = None,
    clock_in_policy: dict | None = None,
    branches: list[SimpleNamespace] | None = None,
    entry_by_id: dict[uuid.UUID, TimeClockEntry] | None = None,
    on_leave_type_name: str | None = None,
) -> AsyncMock:
    """Build an :class:`AsyncMock` DB session covering every code path
    the service uses.

    Arguments are knobs for what each query should return. The fake
    inspects ``stmt`` (best-effort — using string repr) to dispatch to
    the right return value.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
    db._added: list = []
    db.add.side_effect = lambda obj: db._added.append(obj)

    staff_by_id = staff_by_id or {}
    entry_by_id = entry_by_id or {}

    async def _fake_get(model, key):
        if model is StaffMember:
            return staff_by_id.get(key)
        if model is TimeClockEntry:
            return entry_by_id.get(key)
        return None

    db.get = AsyncMock(side_effect=_fake_get)

    async def _fake_execute(stmt, params=None):
        result = MagicMock()
        # Default .first() to None so the org-timezone lookup and the
        # clock-in on-leave check (both use .first()) are no-ops unless a
        # specific branch below overrides them.
        result.first.return_value = None
        rendered = str(stmt).lower()
        # Plain text() statements expose .text — use that when set.
        try:
            text_repr = (stmt.text or "").lower()
        except AttributeError:
            text_repr = ""

        # 1. text("SELECT clock_in_policy ...")
        if "clock_in_policy" in text_repr:
            result.scalar_one_or_none.return_value = (
                clock_in_policy if clock_in_policy is not None else {}
            )
            return result
        # 2. text("SELECT lat, lng, geofence_radius_metres FROM branches ...")
        if "geofence_radius_metres" in text_repr:
            rows = branches or []
            result.all.return_value = rows
            return result
        # 3. select(StaffMember) — by employee_id (lookup_for_kiosk).
        if "staff_members" in rendered and "employee_id" in rendered:
            result.scalar_one_or_none.return_value = staff_by_employee_id
            return result
        # 4. select(TimeClockEntry) — open-entry lookup.
        if (
            "time_clock_entries" in rendered
            and "clock_out_at is null" in rendered
        ):
            result.scalar_one_or_none.return_value = open_entry
            return result
        # 5. select(ScheduleEntry) — auto-match window.
        if "schedule_entries" in rendered:
            rows = schedule_entries or []
            wrapped = [
                SimpleNamespace(id=r.id, start_time=r.start_time)
                for r in rows
            ]
            result.all.return_value = wrapped
            return result
        # 6. select(TimesheetApproval) — lock_check.
        if "timesheet_approvals" in rendered:
            if locked_week_for is not None:
                result.scalar_one_or_none.return_value = uuid.uuid4()
            else:
                result.scalar_one_or_none.return_value = None
            return result
        # 7. select(LeaveType.name JOIN leave_requests) — clock-in leave gate.
        if "leave_requests" in rendered:
            result.first.return_value = (
                (on_leave_type_name,) if on_leave_type_name is not None else None
            )
            return result
        # Default — empty.
        result.scalar_one_or_none.return_value = None
        result.all.return_value = []
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db


@pytest.fixture
def captured_audit():
    """Capture ``write_audit_log`` calls for assertion."""
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.service.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestComputeWorkedMinutes:
    """Pure-function checks for R3.7 worked_minutes formula."""

    def test_simple_8h_no_break(self):
        clock_in = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        clock_out = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)
        assert _compute_worked_minutes(
            clock_in_at=clock_in,
            clock_out_at=clock_out,
            break_minutes=0,
        ) == 480

    def test_meal_break_deducted(self):
        clock_in = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        clock_out = datetime(2026, 6, 1, 17, 30, tzinfo=timezone.utc)
        # Elapsed 510 min; break 30 min → 480 worked.
        assert _compute_worked_minutes(
            clock_in_at=clock_in,
            clock_out_at=clock_out,
            break_minutes=30,
        ) == 480

    def test_break_larger_than_elapsed_floors_at_zero(self):
        clock_in = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        clock_out = datetime(2026, 6, 1, 9, 5, tzinfo=timezone.utc)
        assert _compute_worked_minutes(
            clock_in_at=clock_in,
            clock_out_at=clock_out,
            break_minutes=30,
        ) == 0

    def test_negative_break_treated_as_zero(self):
        clock_in = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        clock_out = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)
        # A negative break should be clamped to 0 — not credited extra.
        assert _compute_worked_minutes(
            clock_in_at=clock_in,
            clock_out_at=clock_out,
            break_minutes=-15,
        ) == 480


class TestEmployeeIdHash:
    """SHA-256 hash truncation — kept stable across runs (G12)."""

    def test_hash_is_deterministic_and_truncated(self):
        h1 = _hash_employee_id("EMP-001")
        h2 = _hash_employee_id("EMP-001")
        assert h1 == h2
        assert len(h1) == 16
        # Different inputs hash to different prefixes.
        assert _hash_employee_id("EMP-002") != h1


# ---------------------------------------------------------------------------
# Kiosk lookup
# ---------------------------------------------------------------------------


class TestKioskLookup:

    @pytest.mark.asyncio
    async def test_returns_staff_identity_when_match(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff_by_employee_id=staff)
        redis = _FakeRedis()

        result = await lookup_for_kiosk(
            db,
            org_id=org_id,
            employee_id="EMP-001",
            redis=redis,
        )

        assert result["staff_id"] == staff.id
        assert result["first_name"] == "Jane"
        assert result["on_file_photo_url"] == "https://uploads/staff/jane.jpg"
        assert result["currently_clocked_in"] is False
        # No audit row on the success path.
        assert captured_audit == []

    @pytest.mark.asyncio
    async def test_currently_clocked_in_when_open_entry_exists(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        open_entry = TimeClockEntry(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            clock_in_at=datetime.now(timezone.utc),
            source="kiosk",
            clock_in_photo_url="key",
            break_minutes=0,
            flags={},
        )
        db = _make_db(staff_by_employee_id=staff, open_entry=open_entry)

        result = await lookup_for_kiosk(
            db,
            org_id=org_id,
            employee_id="EMP-001",
            redis=_FakeRedis(),
        )
        assert result["currently_clocked_in"] is True

    @pytest.mark.asyncio
    async def test_no_match_raises_employee_not_found(self, captured_audit):
        org_id = uuid.uuid4()
        db = _make_db(staff_by_employee_id=None)

        with pytest.raises(EmployeeNotFoundError):
            await lookup_for_kiosk(
                db,
                org_id=org_id,
                employee_id="EMP-NONEXISTENT",
                redis=_FakeRedis(),
            )

    @pytest.mark.asyncio
    async def test_g12_rate_limit_trips_at_11th_call_with_audit(
        self, captured_audit
    ):
        """G12: 11th lookup for the same (org_id, employee_id) within
        60s returns 429 and writes the rate-limit audit row.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff_by_employee_id=staff)
        redis = _FakeRedis()

        # First 10 — all succeed.
        for _ in range(10):
            await lookup_for_kiosk(
                db,
                org_id=org_id,
                employee_id="EMP-001",
                redis=redis,
            )

        # 11th — rate-limit error + audit row.
        with pytest.raises(KioskLookupRateLimitedError) as exc:
            await lookup_for_kiosk(
                db,
                org_id=org_id,
                employee_id="EMP-001",
                redis=redis,
            )
        assert exc.value.retry_after_seconds == 60
        # Audit row written with hashed identifier — never raw code.
        rate_audits = [
            a for a in captured_audit
            if a.get("action") == "kiosk.lookup_rate_limited"
        ]
        assert len(rate_audits) == 1
        after = rate_audits[0]["after_value"]
        # Hash, not raw employee_id.
        assert after["employee_id_hash"] == _hash_employee_id("EMP-001")
        assert "EMP-001" not in str(after)
        assert after["retry_after"] == 60

    @pytest.mark.asyncio
    async def test_org_policy_overrides_default_budget(self, captured_audit):
        """``clock_in_policy.kiosk_employee_id_rate_limit`` overrides
        the default 10/min budget per R6.1.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(
            staff_by_employee_id=staff,
            clock_in_policy={"kiosk_employee_id_rate_limit": 3},
        )
        redis = _FakeRedis()

        # 3 OK, 4th fails.
        for _ in range(3):
            await lookup_for_kiosk(
                db, org_id=org_id, employee_id="EMP-001", redis=redis,
            )
        with pytest.raises(KioskLookupRateLimitedError):
            await lookup_for_kiosk(
                db, org_id=org_id, employee_id="EMP-001", redis=redis,
            )


# ---------------------------------------------------------------------------
# Kiosk clock action — in/out round-trip
# ---------------------------------------------------------------------------


class TestKioskClockAction:

    @pytest.mark.asyncio
    async def test_clock_in_blocked_when_on_leave(self, captured_audit):
        """Clock-in is refused with OnLeaveError carrying the leave type when
        the staff member has approved leave covering today."""
        from app.modules.time_clock.service import OnLeaveError

        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(
            staff_by_id={staff.id: staff},
            on_leave_type_name="Parental leave",
        )

        with pytest.raises(OnLeaveError) as exc:
            await kiosk_clock_action(
                db,
                org_id=org_id,
                staff_id=staff.id,
                action="in",
                photo_file_key="kiosk-photo-key",
            )
        assert exc.value.leave_type_name == "Parental leave"

    @pytest.mark.asyncio
    async def test_clock_in_inserts_kiosk_row_with_audit(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff_by_id={staff.id: staff})

        entry = await kiosk_clock_action(
            db,
            org_id=org_id,
            staff_id=staff.id,
            action="in",
            photo_file_key="kiosk-photo-key",
        )

        assert entry.source == "kiosk"
        assert entry.clock_in_photo_url == "kiosk-photo-key"
        assert entry.clock_out_at is None
        assert entry.worked_minutes is None
        assert entry.break_minutes == 0
        assert any(
            a.get("action") == "time_clock.in" for a in captured_audit
        )

    @pytest.mark.asyncio
    async def test_clock_in_then_out_round_trip_computes_worked_minutes(
        self, captured_audit
    ):
        """End-to-end: clock in, then a synthetic clock-out 8h later
        with 30min break-minutes → worked_minutes = 450 (480 - 30).
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)

        # Step 1 — clock in.
        db_in = _make_db(staff_by_id={staff.id: staff})
        in_entry = await kiosk_clock_action(
            db_in,
            org_id=org_id,
            staff_id=staff.id,
            action="in",
            photo_file_key="in-photo",
        )

        # Force a known clock_in_at for deterministic worked_minutes.
        in_entry.clock_in_at = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        in_entry.break_minutes = 30  # simulate a meal break recorded mid-shift

        # Step 2 — clock out 8h30m later. The service uses datetime.now
        # internally; patch it so the test is deterministic.
        clock_out_at = datetime(2026, 6, 1, 17, 30, tzinfo=timezone.utc)
        db_out = _make_db(
            staff_by_id={staff.id: staff},
            open_entry=in_entry,
        )
        with patch(
            "app.modules.time_clock.service.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = clock_out_at
            # Keep the rest of the datetime API working.
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)

            out_entry = await kiosk_clock_action(
                db_out,
                org_id=org_id,
                staff_id=staff.id,
                action="out",
                photo_file_key="out-photo",
            )

        assert out_entry.id == in_entry.id  # same row, updated
        assert out_entry.clock_out_at == clock_out_at
        assert out_entry.clock_out_photo_url == "out-photo"
        # 510 elapsed - 30 break = 480 worked.
        assert out_entry.worked_minutes == 480
        actions = [a.get("action") for a in captured_audit]
        assert "time_clock.in" in actions
        assert "time_clock.out" in actions

    @pytest.mark.asyncio
    async def test_clock_in_auto_matches_scheduled_entry(self, captured_audit):
        """R3.8 — auto-match the schedule_entries row whose window
        contains the clock-in moment.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        now = datetime.now(timezone.utc)
        # Window: now - 30min → now + 7h30m. Clock-in is inside it.
        sched = _make_schedule_entry(
            staff_id=staff.id,
            org_id=org_id,
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(hours=7, minutes=30),
        )
        # An older shift earlier in the day — outside the window.
        sched_outside = _make_schedule_entry(
            staff_id=staff.id,
            org_id=org_id,
            start_time=now - timedelta(hours=10),
            end_time=now - timedelta(hours=2),
        )
        db = _make_db(
            staff_by_id={staff.id: staff},
            # Only the matching shift surfaces because the SQL query
            # filters on start_time <= when <= end_time.
            schedule_entries=[sched],
        )

        entry = await kiosk_clock_action(
            db,
            org_id=org_id,
            staff_id=staff.id,
            action="in",
            photo_file_key="key",
        )

        assert entry.scheduled_entry_id == sched.id

    @pytest.mark.asyncio
    async def test_clock_action_missing_photo_raises(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff_by_id={staff.id: staff})

        with pytest.raises(PhotoRequiredError):
            await kiosk_clock_action(
                db,
                org_id=org_id,
                staff_id=staff.id,
                action="in",
                photo_file_key="",
            )

    @pytest.mark.asyncio
    async def test_clock_in_when_already_open_raises(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        open_entry = TimeClockEntry(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            clock_in_at=datetime.now(timezone.utc),
            source="kiosk",
            clock_in_photo_url="prev-key",
            break_minutes=0,
            flags={},
        )
        db = _make_db(
            staff_by_id={staff.id: staff},
            open_entry=open_entry,
        )

        with pytest.raises(InvalidActionError, match="already_clocked_in"):
            await kiosk_clock_action(
                db,
                org_id=org_id,
                staff_id=staff.id,
                action="in",
                photo_file_key="key",
            )

    @pytest.mark.asyncio
    async def test_clock_out_with_no_open_entry_raises(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff_by_id={staff.id: staff}, open_entry=None)

        with pytest.raises(InvalidActionError, match="not_clocked_in"):
            await kiosk_clock_action(
                db,
                org_id=org_id,
                staff_id=staff.id,
                action="out",
                photo_file_key="key",
            )

    @pytest.mark.asyncio
    async def test_unknown_staff_raises(self, captured_audit):
        org_id = uuid.uuid4()
        db = _make_db(staff_by_id={})

        with pytest.raises(StaffNotFoundError):
            await kiosk_clock_action(
                db,
                org_id=org_id,
                staff_id=uuid.uuid4(),
                action="in",
                photo_file_key="key",
            )


# ---------------------------------------------------------------------------
# Self-service action
# ---------------------------------------------------------------------------


class TestSelfServiceClockAction:

    @pytest.mark.asyncio
    async def test_refuses_when_self_service_disabled(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, self_service=False)
        db = _make_db(staff_by_id={staff.id: staff})

        with pytest.raises(SelfServiceDisabledError):
            await self_service_clock_action(
                db,
                org_id=org_id,
                staff_id=staff.id,
                action="in",
                photo_file_key="key",
            )

    @pytest.mark.asyncio
    async def test_refuses_when_photo_required_and_missing(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, self_service=True)
        db = _make_db(
            staff_by_id={staff.id: staff},
            clock_in_policy={"self_service_require_photo": True},
        )

        with pytest.raises(PhotoRequiredError):
            await self_service_clock_action(
                db,
                org_id=org_id,
                staff_id=staff.id,
                action="in",
                photo_file_key=None,
            )

    @pytest.mark.asyncio
    async def test_in_out_round_trip_when_enabled(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, self_service=True)

        # ---- clock in ----
        db_in = _make_db(
            staff_by_id={staff.id: staff},
            clock_in_policy={"self_service_require_photo": True},
        )
        in_entry = await self_service_clock_action(
            db_in,
            org_id=org_id,
            staff_id=staff.id,
            action="in",
            photo_file_key="ss-photo-in",
            source="self_service_mobile",
        )
        assert in_entry.source == "self_service_mobile"
        assert in_entry.clock_in_photo_url == "ss-photo-in"

        # ---- clock out ----
        in_entry.clock_in_at = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        in_entry.break_minutes = 0
        clock_out_at = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)
        db_out = _make_db(
            staff_by_id={staff.id: staff},
            open_entry=in_entry,
            clock_in_policy={"self_service_require_photo": True},
        )
        with patch(
            "app.modules.time_clock.service.datetime"
        ) as mock_datetime:
            mock_datetime.now.return_value = clock_out_at
            mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
            out_entry = await self_service_clock_action(
                db_out,
                org_id=org_id,
                staff_id=staff.id,
                action="out",
                photo_file_key="ss-photo-out",
                source="self_service_web",
            )
        assert out_entry.id == in_entry.id
        assert out_entry.worked_minutes == 480

    @pytest.mark.asyncio
    async def test_photo_optional_when_policy_says_so(self, captured_audit):
        """``self_service_require_photo=false`` allows action without
        photo_file_key.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id, self_service=True)
        db = _make_db(
            staff_by_id={staff.id: staff},
            clock_in_policy={"self_service_require_photo": False},
        )
        entry = await self_service_clock_action(
            db,
            org_id=org_id,
            staff_id=staff.id,
            action="in",
            photo_file_key=None,
        )
        assert entry.clock_in_photo_url is None


# ---------------------------------------------------------------------------
# Admin manual entry
# ---------------------------------------------------------------------------


class TestAdminManualEntry:

    @pytest.mark.asyncio
    async def test_manual_create_writes_audit(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db = _make_db(staff_by_id={staff.id: staff})

        clock_in = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        clock_out = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)

        entry = await admin_manual_entry(
            db,
            org_id=org_id,
            staff_id=staff.id,
            clock_in_at=clock_in,
            clock_out_at=clock_out,
            break_minutes=30,
            notes="back-dated edit",
            created_by=uuid.uuid4(),
        )

        assert entry.source == "admin_manual"
        assert entry.notes == "back-dated edit"
        assert entry.worked_minutes == 450  # 480 - 30
        assert any(
            a.get("action") == "time_clock.added" for a in captured_audit
        )
        added_audit = next(
            a for a in captured_audit
            if a.get("action") == "time_clock.added"
        )
        assert added_audit["after_value"]["source"] == "admin_manual"

    @pytest.mark.asyncio
    async def test_manual_create_in_locked_week_raises(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        clock_in = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        db = _make_db(
            staff_by_id={staff.id: staff},
            locked_week_for=(staff.id, clock_in.date()),
        )

        with pytest.raises(LockedWeekError):
            await admin_manual_entry(
                db,
                org_id=org_id,
                staff_id=staff.id,
                clock_in_at=clock_in,
                clock_out_at=clock_in + timedelta(hours=8),
            )

    @pytest.mark.asyncio
    async def test_update_writes_before_and_after_audit(self, captured_audit):
        """R5.4 / P3-N5 — manual edit audit row carries both
        ``before_value`` and ``after_value``.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        existing = TimeClockEntry(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            clock_in_at=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            clock_out_at=datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc),
            source="admin_manual",
            break_minutes=0,
            worked_minutes=480,
            notes="initial",
            flags={},
        )
        db = _make_db(
            staff_by_id={staff.id: staff},
            entry_by_id={existing.id: existing},
        )

        updated = await update_manual_entry(
            db,
            org_id=org_id,
            entry_id=existing.id,
            updates={"break_minutes": 30, "notes": "added meal break"},
            user_id=uuid.uuid4(),
        )

        assert updated.break_minutes == 30
        assert updated.notes == "added meal break"
        assert updated.worked_minutes == 450  # recomputed
        edited_audit = next(
            a for a in captured_audit
            if a.get("action") == "time_clock.edited"
        )
        assert edited_audit["before_value"]["break_minutes"] == 0
        assert edited_audit["before_value"]["worked_minutes"] == 480
        assert edited_audit["after_value"]["break_minutes"] == 30
        assert edited_audit["after_value"]["worked_minutes"] == 450
        assert edited_audit["before_value"]["notes"] == "initial"
        assert edited_audit["after_value"]["notes"] == "added meal break"

    @pytest.mark.asyncio
    async def test_update_unknown_entry_raises(self, captured_audit):
        org_id = uuid.uuid4()
        db = _make_db(entry_by_id={})

        with pytest.raises(TimeClockEntryNotFoundError):
            await update_manual_entry(
                db,
                org_id=org_id,
                entry_id=uuid.uuid4(),
                updates={"notes": "x"},
            )
