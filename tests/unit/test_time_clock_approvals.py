"""Unit tests for ``app.modules.time_clock.approvals`` (task B5).

Covers task B5 from `.kiro/specs/staff-management-p3`:

1. ``compute_week_totals`` overtime split — daily-only (4× 9h, daily
   threshold 480, weekly 2400 → 4h overtime even though weekly < 40h).
2. ``compute_week_totals`` double-count guard — 5× 10h = 50h, daily
   threshold 480, weekly 2400 → daily_ot=10h, weekly_ot=0, total_ot=10h.
3. ``compute_week_totals`` weekly-only — 6× 8h = 48h with daily ≤ 8h
   → daily_ot=0, weekly_ot=8h.
4. ``compute_week_totals`` G1.5 unapproved-overtime warning when
   ``require_pre_approval=true`` and no approved ``overtime_requests``
   covers the actual overtime.
5. ``compute_week_totals`` skips the warning when an approved request
   covers the overtime.
6. ``approve_week`` creates a new row with ``status='approved'`` and
   the totals carried from compute.
7. After ``approve_week`` → ``lock_check`` returns ``True`` for an
   entry inside the week.
8. After ``reopen_week`` → ``lock_check`` returns ``False`` (status
   flipped to ``edited_after_approval``).
9. G16 — ``recompute_after_edit`` on a previously-approved row flips
   status to ``edited_after_approval`` and re-computes totals; an
   audit row is written.
10. G7 — ``approve_week`` does NOT touch the ``time_entries`` (billable
    timer) table; only ``timesheet_approvals`` (and conditionally
    ``leave_ledger`` for TOIL).
11. R11.1 — TOIL accrual: when org's ``overtime_handling='toil'`` and
    overtime > 0 → a ``leave_ledger`` row is written with
    ``reason='toil_accrual'``.
12. R11.2 — ``employee_chooses`` requires ``toil_choice``; raises
    :class:`ToilChoiceRequiredError` when omitted.

The DB session is mocked with ``AsyncMock`` following the same pattern
used by ``tests/unit/test_time_clock_service.py``. The
``load_public_holidays_in_range`` helper from
:mod:`app.modules.leave.public_holidays` is patched to a no-op so the
tests don't need a Redis double — public-holiday minutes default to
zero in every test (matching the project's "Phase 2 may not be
applied" defensive fallback).

**Validates: Requirements R9, R10, R11 — Staff Management Phase 3 task B5**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import ORM modules so SQLAlchemy resolves the string-name
# relationships (``Organisation``, ``User``) when instantiating
# TimeClockEntry / TimesheetApproval / LeaveLedger objects below.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401

from app.modules.leave.models import LeaveBalance, LeaveLedger, LeaveType
from app.modules.time_clock.approvals import (
    InvalidToilChoiceError,
    ToilChoiceRequiredError,
    TimesheetApprovalNotFoundError,
    _split_overtime,
    approve_week,
    compute_week_totals,
    lock_check,
    recompute_after_edit,
    reopen_week,
)
from app.modules.time_clock.models import (
    TimeClockEntry,
    TimesheetApproval,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


_WEEK_START = date(2026, 6, 1)  # Monday
_WEEK_END = date(2026, 6, 7)  # Sunday


def _make_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    day: date,
    worked_minutes: int,
    break_minutes: int = 0,
    closed: bool = True,
) -> TimeClockEntry:
    """Build a closed :class:`TimeClockEntry` whose ``clock_in_at``
    falls on ``day`` at 09:00 UTC and whose ``worked_minutes`` is the
    given value (meal-break-deducted, since the closed-shift writer in
    :mod:`service` always stores the net figure).
    """
    clock_in_at = datetime.combine(
        day, datetime.min.time(), tzinfo=timezone.utc,
    ).replace(hour=9)
    if closed:
        clock_out_at = clock_in_at + timedelta(
            minutes=worked_minutes + break_minutes,
        )
    else:
        clock_out_at = None
    return TimeClockEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=clock_in_at,
        clock_out_at=clock_out_at,
        source="kiosk",
        clock_in_photo_url="key",
        break_minutes=break_minutes,
        flags={},
        worked_minutes=worked_minutes if closed else None,
    )


class _MockDB:
    """Shared async-mock DB session for the approvals tests.

    Knobs:
      - ``entries``: list of TimeClockEntry returned by week-load.
      - ``overtime_policy``: dict for the ``SELECT overtime_policy`` text query.
      - ``overtime_handling``: string for the typed-column read.
      - ``country_code``: string for the country_code read.
      - ``approval``: existing TimesheetApproval (None to simulate first approve).
      - ``approved_overtime_minutes``: returned by the
        ``SELECT SUM(...) FROM overtime_requests`` paths (split between
        tied + free, but the test wires the same value for both for
        simplicity — first call returns the value, second returns 0).
      - ``scheduled_minutes``: returned by the schedule_entries SUM.
      - ``locked_week_for``: tuple ``(staff_id, week_start)`` to
        synthesise an approved row visible to lock_check.
      - ``leave_type_toil``: LeaveType('toil') row returned by the TOIL
        accrual lookup; ``None`` to simulate a missing TOIL type.
      - ``leave_balance``: LeaveBalance row for the staff × toil pair.
    """

    def __init__(
        self,
        *,
        entries: list[TimeClockEntry] | None = None,
        overtime_policy: dict | None = None,
        overtime_handling: str = "pay_cash",
        country_code: str = "NZ",
        approval: TimesheetApproval | None = None,
        approved_overtime_minutes: int = 0,
        scheduled_minutes: int = 0,
        locked_week_for: tuple[uuid.UUID, date] | None = None,
        leave_type_toil: LeaveType | None = None,
        leave_balance: LeaveBalance | None = None,
        existing_toil_ledger: bool = False,
    ) -> None:
        self.entries = entries or []
        self.overtime_policy = overtime_policy or {}
        self.overtime_handling = overtime_handling
        self.country_code = country_code
        self.approval = approval
        self.approved_overtime_minutes = approved_overtime_minutes
        self.scheduled_minutes = scheduled_minutes
        self.locked_week_for = locked_week_for
        self.leave_type_toil = leave_type_toil
        self.leave_balance = leave_balance
        self.existing_toil_ledger = existing_toil_ledger

        # Tracking state.
        self.added: list = []
        self.executed_text_queries: list[str] = []
        self._overtime_query_count = 0  # tied vs free dispatch
        self._lock_check_first_call_used = False

    def make_session(self) -> AsyncMock:
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: self.added.append(obj))
        db.get = AsyncMock(side_effect=self._fake_get)
        db.execute = AsyncMock(side_effect=self._fake_execute)
        return db

    async def _fake_get(self, model, key):
        return None  # approvals.py never uses db.get for ORM lookups.

    async def _fake_execute(self, stmt, params=None):
        result = MagicMock()
        rendered = str(stmt).lower()
        try:
            text_repr = (stmt.text or "").lower()
        except AttributeError:
            text_repr = ""

        if text_repr:
            self.executed_text_queries.append(text_repr)

        # 1. text("SELECT overtime_policy ...")
        if "overtime_policy" in text_repr:
            result.scalar_one_or_none.return_value = self.overtime_policy
            return result

        # 2. text("SELECT overtime_handling ...")
        if "overtime_handling" in text_repr:
            result.scalar_one_or_none.return_value = self.overtime_handling
            return result

        # 3. text("SELECT country_code ...")
        if "country_code" in text_repr:
            result.scalar_one_or_none.return_value = self.country_code
            return result

        # 4. text(SELECT SUM ... schedule_entries ...)
        if "schedule_entries" in text_repr and "sum" in text_repr:
            result.scalar_one_or_none.return_value = self.scheduled_minutes
            return result

        # 5. text(SELECT SUM ... overtime_requests ...)
        if "overtime_requests" in text_repr:
            self._overtime_query_count += 1
            if self._overtime_query_count == 1:
                # Tied path returns the configured value.
                result.scalar_one_or_none.return_value = (
                    self.approved_overtime_minutes
                )
            else:
                # Free-form path — zero in tests for simplicity.
                result.scalar_one_or_none.return_value = 0
            return result

        # 6. select(TimeClockEntry) — week-load.
        if (
            "time_clock_entries" in rendered
            and "clock_in_at" in rendered
        ):
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = self.entries
            result.scalars.return_value = scalars_mock
            return result

        # 7. select(TimesheetApproval) — lock_check OR _load_approval.
        if "timesheet_approvals" in rendered and "week_start" in rendered:
            # lock_check selects only ``.id`` and filters with
            # ``week_start <= :date AND week_end >= :date``.
            # _load_approval selects the full row and filters with
            # ``week_start = :week_start``.
            is_lock_check = (
                "week_end" in rendered
                and "<=" in rendered
                and ">=" in rendered
            )
            if is_lock_check:
                if self.locked_week_for is not None:
                    result.scalar_one_or_none.return_value = uuid.uuid4()
                else:
                    result.scalar_one_or_none.return_value = None
                return result
            # _load_approval path — full row.
            result.scalar_one_or_none.return_value = self.approval
            return result

        # 8. select(LeaveType) — toil lookup.
        if "leave_types" in rendered and "code" in rendered:
            result.scalar_one_or_none.return_value = self.leave_type_toil
            return result

        # 9. select(LeaveLedger.id) — idempotency guard.
        if "leave_ledger" in rendered and "id" in rendered:
            result.scalar_one_or_none.return_value = (
                uuid.uuid4() if self.existing_toil_ledger else None
            )
            return result

        # 10. select(LeaveBalance) — for the toil balance bump.
        if "leave_balances" in rendered:
            result.scalar_one_or_none.return_value = self.leave_balance
            return result

        # Default — empty.
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        result.all.return_value = []
        return result


@pytest.fixture
def captured_audit():
    """Capture ``write_audit_log`` calls inside the approvals module."""
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.approvals.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


@pytest.fixture
def stub_public_holidays():
    """Patch the public-holiday loader to an empty list so tests don't
    need a Redis double. Defaults match the production "Phase 2 not
    yet applied to org" fallback in ``_load_public_holiday_dates``.
    """
    async def _empty_loader(*args, **kwargs):
        return []

    with patch(
        "app.modules.leave.public_holidays.load_public_holidays_in_range",
        side_effect=_empty_loader,
    ):
        yield


# ---------------------------------------------------------------------------
# Pure helper — _split_overtime
# ---------------------------------------------------------------------------


class TestSplitOvertime:
    """Pure-function checks for the G1 / R6a.4 algorithm."""

    def test_daily_only_4x_9h_with_8h_threshold(self):
        """Spec example: 9h × 4 days = 36h, daily=480 → 4h daily OT
        even though weekly < 40h.
        """
        days = {
            date(2026, 6, 1): 540,  # 9h
            date(2026, 6, 2): 540,
            date(2026, 6, 3): 540,
            date(2026, 6, 4): 540,
        }
        daily_ot, weekly_ot = _split_overtime(
            daily_minutes_by_day=days,
            week_worked=2160,  # 36h
            daily_threshold=480,
            weekly_threshold=2400,
        )
        assert daily_ot == 240  # 1h × 4 days
        assert weekly_ot == 0
        assert daily_ot + weekly_ot == 240

    def test_double_count_guard_5x_10h(self):
        """Spec example: 10h × 5 days = 50h, daily=480, weekly=2400 →
        daily_ot=600, weekly_ot=max(0, 3000-2400-600)=0, total=600.
        """
        days = {
            date(2026, 6, 1): 600,  # 10h
            date(2026, 6, 2): 600,
            date(2026, 6, 3): 600,
            date(2026, 6, 4): 600,
            date(2026, 6, 5): 600,
        }
        daily_ot, weekly_ot = _split_overtime(
            daily_minutes_by_day=days,
            week_worked=3000,  # 50h
            daily_threshold=480,
            weekly_threshold=2400,
        )
        assert daily_ot == 600  # 2h × 5 days
        assert weekly_ot == 0  # already captured by daily band
        assert daily_ot + weekly_ot == 600

    def test_weekly_only_when_no_day_exceeds_daily(self):
        """6 days × 8h = 48h with daily threshold 8h → 0 daily OT,
        8h weekly OT (no double-count to subtract).
        """
        days = {
            date(2026, 6, 1): 480,
            date(2026, 6, 2): 480,
            date(2026, 6, 3): 480,
            date(2026, 6, 4): 480,
            date(2026, 6, 5): 480,
            date(2026, 6, 6): 480,
        }
        daily_ot, weekly_ot = _split_overtime(
            daily_minutes_by_day=days,
            week_worked=2880,  # 48h
            daily_threshold=480,
            weekly_threshold=2400,
        )
        assert daily_ot == 0
        assert weekly_ot == 480  # 8h above 40h
        assert daily_ot + weekly_ot == 480

    def test_below_thresholds_no_overtime(self):
        days = {date(2026, 6, 1): 480}
        daily_ot, weekly_ot = _split_overtime(
            daily_minutes_by_day=days,
            week_worked=480,
            daily_threshold=480,
            weekly_threshold=2400,
        )
        assert daily_ot == 0
        assert weekly_ot == 0


# ---------------------------------------------------------------------------
# compute_week_totals
# ---------------------------------------------------------------------------


class TestComputeWeekTotals:

    @pytest.mark.asyncio
    async def test_overtime_split_4x_9h_daily_only(
        self, captured_audit, stub_public_holidays,
    ):
        """9h × 4 days, daily=480, weekly=2400 → 4h overtime even
        though weekly under 40h. Spec verify line.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
                "require_pre_approval": False,
            },
        )
        db = mock.make_session()

        totals = await compute_week_totals(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )

        assert totals["total_worked_minutes"] == 2160  # 36h
        assert totals["total_overtime_minutes"] == 240  # 4h
        assert totals["ordinary_minutes"] == 1920  # 32h
        assert totals["public_holiday_minutes"] == 0
        assert totals["notes"] is None
        assert totals["week_start"] == _WEEK_START
        assert totals["week_end"] == _WEEK_END

    @pytest.mark.asyncio
    async def test_overtime_split_5x_10h_no_double_count(
        self, captured_audit, stub_public_holidays,
    ):
        """5× 10h = 50h, daily=480, weekly=2400 → daily_ot=10h,
        weekly_ot=0, total_ot=10h. Spec verify line.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=600,
            )
            for i in range(5)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
        )
        db = mock.make_session()

        totals = await compute_week_totals(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )

        assert totals["total_worked_minutes"] == 3000  # 50h
        assert totals["total_overtime_minutes"] == 600  # 10h
        assert totals["ordinary_minutes"] == 2400  # exactly 40h
        # Sums add up.
        assert (
            totals["ordinary_minutes"]
            + totals["total_overtime_minutes"]
            + totals["public_holiday_minutes"]
            == totals["total_worked_minutes"]
        )

    @pytest.mark.asyncio
    async def test_unapproved_overtime_warning_when_pre_approval_required(
        self, captured_audit, stub_public_holidays,
    ):
        """G1.5 — when require_pre_approval=true and there's overtime
        not covered by an approved overtime_request, the notes carry
        an ``unapproved_overtime`` marker.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,  # 9h × 4 days = 4h OT
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
                "require_pre_approval": True,
            },
            approved_overtime_minutes=0,  # nothing approved
        )
        db = mock.make_session()

        totals = await compute_week_totals(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )

        assert totals["total_overtime_minutes"] == 240
        assert totals["notes"] is not None
        assert "unapproved_overtime" in totals["notes"]
        assert "240min" in totals["notes"]

    @pytest.mark.asyncio
    async def test_no_warning_when_request_covers_overtime(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,  # 9h × 4 days = 4h OT
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
                "require_pre_approval": True,
            },
            approved_overtime_minutes=300,  # covers the 240min OT
        )
        db = mock.make_session()

        totals = await compute_week_totals(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )

        assert totals["total_overtime_minutes"] == 240
        assert totals["notes"] is None

    @pytest.mark.asyncio
    async def test_open_entry_excluded_from_totals(
        self, captured_audit, stub_public_holidays,
    ):
        """Open entries (worked_minutes IS NULL) contribute zero —
        they show in the Hours tab but don't count toward approval.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        closed = _make_entry(
            org_id=org_id, staff_id=staff_id,
            day=_WEEK_START, worked_minutes=480,
        )
        open_entry = _make_entry(
            org_id=org_id, staff_id=staff_id,
            day=_WEEK_START + timedelta(days=1),
            worked_minutes=0, closed=False,
        )
        mock = _MockDB(
            entries=[closed, open_entry],
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
        )
        db = mock.make_session()

        totals = await compute_week_totals(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )

        assert totals["total_worked_minutes"] == 480
        assert totals["total_overtime_minutes"] == 0


# ---------------------------------------------------------------------------
# approve_week + lock_check round-trip
# ---------------------------------------------------------------------------


class TestApproveWeek:

    @pytest.mark.asyncio
    async def test_creates_approved_row(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        approver_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=480,
            )
            for i in range(5)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_handling="pay_cash",
        )
        db = mock.make_session()

        approval = await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=approver_id,
        )

        assert approval.status == "approved"
        assert approval.approved_by == approver_id
        assert approval.total_worked_minutes == 2400
        assert approval.total_overtime_minutes == 0
        assert any(
            a.get("action") == "timesheet.approved"
            for a in captured_audit
        )
        # No leave_ledger row should have been added on pay_cash.
        added_ledgers = [
            o for o in mock.added if isinstance(o, LeaveLedger)
        ]
        assert added_ledgers == []

    @pytest.mark.asyncio
    async def test_approve_then_lock_check_returns_true_for_entry_in_week(
        self, captured_audit, stub_public_holidays,
    ):
        """Spec verify: approve a week, attempt PUT on a clock entry
        inside → 409. The PUT path's gate is :func:`lock_check`.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        # Pretend an approved row already exists.
        mock = _MockDB(
            entries=[],
            locked_week_for=(staff_id, _WEEK_START),
        )
        db = mock.make_session()

        when_inside = datetime.combine(
            _WEEK_START + timedelta(days=2),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        is_locked = await lock_check(
            db, org_id=org_id, staff_id=staff_id, when_dt=when_inside,
        )
        assert is_locked is True

    @pytest.mark.asyncio
    async def test_reopen_then_lock_check_returns_false(
        self, captured_audit, stub_public_holidays,
    ):
        """Spec verify: reopen → edit allowed. After reopen, the row
        carries ``status='edited_after_approval'`` so the SQL gate
        in :func:`lock_check` (which filters on
        ``status='approved'``) doesn't match → returns False.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        existing = TimesheetApproval(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            status="approved",
            total_worked_minutes=2400,
            total_overtime_minutes=0,
            total_break_minutes=0,
            ordinary_minutes=2400,
            public_holiday_minutes=0,
        )
        mock = _MockDB(
            entries=[],
            approval=existing,
            # No locked_week_for — so lock_check returns False below.
        )
        db = mock.make_session()

        reopened = await reopen_week(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )
        assert reopened.status == "edited_after_approval"

        # Now lock_check should return False — even within the same week.
        when_inside = datetime.combine(
            _WEEK_START + timedelta(days=2),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        is_locked = await lock_check(
            db, org_id=org_id, staff_id=staff_id, when_dt=when_inside,
        )
        assert is_locked is False
        assert any(
            a.get("action") == "timesheet.reopened"
            for a in captured_audit
        )

    @pytest.mark.asyncio
    async def test_reopen_unknown_week_raises(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        mock = _MockDB(approval=None)
        db = mock.make_session()

        with pytest.raises(TimesheetApprovalNotFoundError):
            await reopen_week(
                db, org_id=org_id, staff_id=staff_id,
                week_start=_WEEK_START,
            )

    @pytest.mark.asyncio
    async def test_g16_recompute_after_edit_flips_status(
        self, captured_audit, stub_public_holidays,
    ):
        """G16 — the manual-edit flow re-runs compute_week_totals;
        when the row was previously approved, the recompute helper
        flips status to ``edited_after_approval`` and audits.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        existing = TimesheetApproval(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            week_end=_WEEK_END,
            status="approved",
            total_worked_minutes=2400,
            total_overtime_minutes=0,
            total_break_minutes=0,
            ordinary_minutes=2400,
            public_holiday_minutes=0,
        )
        # Simulate the underlying entry edit boosting worked_minutes.
        new_entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,  # was 480
            )
            for i in range(5)
        ]
        mock = _MockDB(
            entries=new_entries,
            approval=existing,
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
        )
        db = mock.make_session()

        result = await recompute_after_edit(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )

        assert result is not None
        assert result.status == "edited_after_approval"
        assert result.total_worked_minutes == 2700  # 5× 9h
        assert result.total_overtime_minutes == 300  # 5× 1h
        assert any(
            a.get("action") == "timesheet.recomputed_after_edit"
            for a in captured_audit
        )

    @pytest.mark.asyncio
    async def test_recompute_no_approval_row_is_noop(
        self, captured_audit, stub_public_holidays,
    ):
        """When the staff/week has no approval row, recompute is a
        no-op — returns None and writes no audit.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        mock = _MockDB(approval=None, entries=[])
        db = mock.make_session()

        result = await recompute_after_edit(
            db, org_id=org_id, staff_id=staff_id, week_start=_WEEK_START,
        )
        assert result is None
        # No audit row written.
        assert all(
            a.get("action") != "timesheet.recomputed_after_edit"
            for a in captured_audit
        )

    @pytest.mark.asyncio
    async def test_g7_approve_does_not_touch_time_entries(
        self, captured_audit, stub_public_holidays,
    ):
        """G7 — approve_week must not write to the ``time_entries``
        billable timer table. Verify by inspecting every text() query
        the service ran during approval — none of them target
        ``time_entries`` (singular), which is the time_tracking_v2
        table. Only ``time_clock_entries`` (plural) is touched.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        approver_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=480,
            )
            for i in range(5)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_handling="pay_cash",
        )
        db = mock.make_session()

        await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=approver_id,
        )

        # No text query referenced the billable-timer table by name.
        # Phase 3 must not write to ``time_entries`` (the
        # time_tracking_v2 table); only ``time_clock_entries`` (the
        # attendance table) is mentioned anywhere in the SQL.
        for q in mock.executed_text_queries:
            # The schedule_entries SUM is fine; check no direct
            # time_entries reference (using a word-boundary heuristic
            # by looking for `time_entries ` or ` time_entries(` etc.).
            assert "from time_entries" not in q
            assert "update time_entries" not in q
            assert "insert into time_entries" not in q


# ---------------------------------------------------------------------------
# TOIL accrual
# ---------------------------------------------------------------------------


class TestToilAccrual:

    @pytest.mark.asyncio
    async def test_overtime_handling_toil_writes_leave_ledger_row(
        self, captured_audit, stub_public_holidays,
    ):
        """R11.1 — when org's overtime_handling='toil' and the week
        has positive overtime, a leave_ledger row reason='toil_accrual'
        is written (and the matching balance bumped).
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        approver_id = uuid.uuid4()
        toil_type = LeaveType(
            id=uuid.uuid4(),
            org_id=org_id,
            code="toil",
            name="Time off in lieu",
            is_paid=True,
            accrual_method="event_based",
            accrual_unit="hours",
            is_statutory=False,
        )
        balance = LeaveBalance(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff_id,
            leave_type_id=toil_type.id,
            accrued_hours=Decimal("0"),
            used_hours=Decimal("0"),
            pending_hours=Decimal("0"),
        )
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,  # 9h × 4 days = 4h OT
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
            overtime_handling="toil",
            leave_type_toil=toil_type,
            leave_balance=balance,
        )
        db = mock.make_session()

        approval = await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=approver_id,
        )

        assert approval.total_overtime_minutes == 240  # 4h
        # Leave ledger row added with reason='toil_accrual' for 4h.
        added_ledgers = [
            o for o in mock.added if isinstance(o, LeaveLedger)
        ]
        assert len(added_ledgers) == 1
        ledger = added_ledgers[0]
        assert ledger.reason == "toil_accrual"
        assert ledger.delta_hours == Decimal("240") / Decimal("60")
        assert ledger.leave_type_id == toil_type.id
        # Balance bumped by 4 hours.
        assert balance.accrued_hours == Decimal("4")
        # Audit row for the accrual.
        assert any(
            a.get("action") == "toil.accrued" for a in captured_audit
        )

    @pytest.mark.asyncio
    async def test_pay_cash_does_not_write_leave_ledger(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_handling="pay_cash",
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
        )
        db = mock.make_session()

        approval = await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=uuid.uuid4(),
        )
        assert approval.total_overtime_minutes == 240
        added_ledgers = [
            o for o in mock.added if isinstance(o, LeaveLedger)
        ]
        assert added_ledgers == []

    @pytest.mark.asyncio
    async def test_employee_chooses_requires_toil_choice(
        self, captured_audit, stub_public_holidays,
    ):
        """R11.2 — when org's overtime_handling='employee_chooses',
        toil_choice is REQUIRED.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        mock = _MockDB(
            entries=[],
            overtime_handling="employee_chooses",
        )
        db = mock.make_session()

        with pytest.raises(ToilChoiceRequiredError):
            await approve_week(
                db,
                org_id=org_id,
                staff_id=staff_id,
                week_start=_WEEK_START,
                approved_by=uuid.uuid4(),
                toil_choice=None,
            )

    @pytest.mark.asyncio
    async def test_employee_chooses_pay_cash_does_not_write_ledger(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_handling="employee_chooses",
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
        )
        db = mock.make_session()

        approval = await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=uuid.uuid4(),
            toil_choice="pay_cash",
        )
        assert approval.toil_choice == "pay_cash"
        added_ledgers = [
            o for o in mock.added if isinstance(o, LeaveLedger)
        ]
        assert added_ledgers == []

    @pytest.mark.asyncio
    async def test_employee_chooses_toil_writes_ledger(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        toil_type = LeaveType(
            id=uuid.uuid4(),
            org_id=org_id,
            code="toil",
            name="Time off in lieu",
            is_paid=True,
            accrual_method="event_based",
            accrual_unit="hours",
            is_statutory=False,
        )
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_handling="employee_chooses",
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
            leave_type_toil=toil_type,
        )
        db = mock.make_session()

        approval = await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=uuid.uuid4(),
            toil_choice="toil",
        )
        assert approval.toil_choice == "toil"
        added_ledgers = [
            o for o in mock.added if isinstance(o, LeaveLedger)
        ]
        assert len(added_ledgers) == 1
        assert added_ledgers[0].reason == "toil_accrual"

    @pytest.mark.asyncio
    async def test_invalid_toil_choice_raises(
        self, captured_audit, stub_public_holidays,
    ):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        mock = _MockDB(
            entries=[],
            overtime_handling="employee_chooses",
        )
        db = mock.make_session()

        with pytest.raises(InvalidToilChoiceError):
            await approve_week(
                db,
                org_id=org_id,
                staff_id=staff_id,
                week_start=_WEEK_START,
                approved_by=uuid.uuid4(),
                toil_choice="banana",
            )

    @pytest.mark.asyncio
    async def test_idempotent_no_ledger_row_when_already_accrued(
        self, captured_audit, stub_public_holidays,
    ):
        """Re-running approve_week (e.g. admin clicks Approve twice)
        should not write a duplicate toil_accrual ledger row.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        toil_type = LeaveType(
            id=uuid.uuid4(),
            org_id=org_id,
            code="toil",
            name="Time off in lieu",
            is_paid=True,
            accrual_method="event_based",
            accrual_unit="hours",
            is_statutory=False,
        )
        entries = [
            _make_entry(
                org_id=org_id, staff_id=staff_id,
                day=_WEEK_START + timedelta(days=i),
                worked_minutes=540,
            )
            for i in range(4)
        ]
        mock = _MockDB(
            entries=entries,
            overtime_handling="toil",
            overtime_policy={
                "daily_threshold_minutes": 480,
                "weekly_threshold_minutes": 2400,
            },
            leave_type_toil=toil_type,
            existing_toil_ledger=True,  # idempotency guard hits
        )
        db = mock.make_session()

        await approve_week(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=_WEEK_START,
            approved_by=uuid.uuid4(),
        )
        added_ledgers = [
            o for o in mock.added if isinstance(o, LeaveLedger)
        ]
        assert added_ledgers == []
