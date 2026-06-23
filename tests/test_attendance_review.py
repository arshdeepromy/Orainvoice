# Feature: staff-timesheets — Attendance tab review/approve drill-in
"""DB-backed example tests for the Attendance tab review/approve feature.

Exercises the new ``compute_attendance`` review counts plus
``compute_attendance_detail`` / ``set_shift_review`` / ``review_all_shifts``
(app.modules.timesheets.service) against the real dev Postgres database,
mirroring the DB-backed pattern in ``tests/test_timesheets_weekly_breakdown.py``
(fresh async engine per test, full ORM imports, a Branch for clock entries,
everything rolled back).

The org is seeded with the default ``timezone='UTC'`` (Organisation server
default) so org-local dates equal the UTC clock-entry dates — keeping the
range maths deterministic.

Asserts:
- ``compute_attendance`` reports ``pending_review_count`` / ``reviewed_count``
  per row and in the summary, and signing off a shift moves the needle.
- ``compute_attendance_detail`` lists every shift, excludes the still-open one
  from worked hours + review counts, and surfaces review state.
- ``set_shift_review`` refuses an open shift and an out-of-branch-scope shift.
- ``review_all_shifts`` signs off every completed shift and is idempotent.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests).
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.leave import models as _leave_models  # noqa: F401
from app.modules.time_clock import models as _time_clock_models  # noqa: F401
from app.modules.payslips import models as _payslip_models  # noqa: F401
from app.modules.timesheets import models as _timesheet_models  # noqa: F401
from app.modules.timesheets import pay_cycles as _pay_cycle_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.organisations.models import Branch
from app.modules.payslips.models import PayPeriod
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry
from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.service import (
    add_manual_shift,
    compute_attendance,
    compute_attendance_detail,
    edit_shift,
    review_all_shifts,
    set_shift_review,
    void_manual_shift,
)


_DAY1 = date(2026, 6, 2)   # Tuesday
_DAY2 = date(2026, 6, 3)   # Wednesday
_WEEK_START = date(2026, 6, 1)   # Monday
_WEEK_END = date(2026, 6, 7)     # Sunday
_PAY_DATE = date(2026, 6, 10)


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_org_and_branch(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    plan = SubscriptionPlan(
        name=f"attendance_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"attendance_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        timezone="UTC",  # pin so org-local dates == UTC clock-entry dates
        settings={},
    )
    session.add(org)
    await session.flush()

    branch = Branch(org_id=org.id, name="Test Branch", is_default=True)
    session.add(branch)
    await session.flush()
    return org.id, branch.id


async def _new_staff(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    working_arrangement: str = "rostered",
    availability_schedule: dict | None = None,
) -> StaffMember:
    staff = StaffMember(
        org_id=org_id,
        name=name,
        first_name=name.split()[0],
        employment_type="permanent",
        working_arrangement=working_arrangement,
        availability_schedule=availability_schedule or {},
        is_active=True,
        position="Technician",
    )
    session.add(staff)
    await session.flush()
    return staff


async def _new_clock_entry(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    branch_id: uuid.UUID,
    day: date,
    worked_minutes: int | None,
    open_shift: bool = False,
) -> TimeClockEntry:
    entry = TimeClockEntry(
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=datetime.combine(day, time(9, 0), tzinfo=timezone.utc),
        clock_out_at=None if open_shift else datetime.combine(day, time(17, 0), tzinfo=timezone.utc),
        source="admin_manual",
        worked_minutes=None if open_shift else worked_minutes,
        branch_id=branch_id,
    )
    session.add(entry)
    await session.flush()
    return entry


# ---------------------------------------------------------------------------
# Test 1: review counts in compute_attendance + summary, before/after sign-off.
# ---------------------------------------------------------------------------


async def _run_pending_then_reviewed() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Clocker One")
                e1 = await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=480,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=300,
                )

                res = await compute_attendance(
                    session, org_id=org_id, start_date=_DAY1, end_date=_DAY2,
                )
                assert res.total == 1
                row = res.items[0]
                assert row.staff_name == "Clocker One"
                assert float(row.worked_hours) == pytest.approx(13.0)  # 780 min
                assert row.shift_count == 2
                assert row.pending_review_count == 2
                assert row.reviewed_count == 0
                assert res.summary.pending_review_count == 2

                # Sign off one shift.
                actor = uuid.uuid4()
                entry, _name = await set_shift_review(
                    session, org_id=org_id, entry_id=e1.id, reviewed=True, actor_id=actor,
                )
                assert bool((entry.flags or {}).get("reviewed")) is True
                assert (entry.flags or {}).get("reviewed_by") == str(actor)

                res2 = await compute_attendance(
                    session, org_id=org_id, start_date=_DAY1, end_date=_DAY2,
                )
                row2 = res2.items[0]
                assert row2.pending_review_count == 1
                assert row2.reviewed_count == 1
                assert res2.summary.pending_review_count == 1

                # Un-sign restores the pending count.
                await set_shift_review(
                    session, org_id=org_id, entry_id=e1.id, reviewed=False, actor_id=actor,
                )
                res3 = await compute_attendance(
                    session, org_id=org_id, start_date=_DAY1, end_date=_DAY2,
                )
                assert res3.items[0].pending_review_count == 2
                assert res3.items[0].reviewed_count == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_attendance_pending_then_reviewed_counts():
    """Attendance rows expose pending/reviewed counts that track sign-off.

    **Validates: Attendance review — per-row + summary review counts.**
    """
    asyncio.run(_run_pending_then_reviewed())


# ---------------------------------------------------------------------------
# Test 2: detail lists shifts; open shift excluded from worked + review counts.
# ---------------------------------------------------------------------------


async def _run_detail_lists_shifts() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Detail Dana")
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=480,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=240,
                )
                # An open (still clocked-in) shift on day 2.
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=None, open_shift=True,
                )

                detail = await compute_attendance_detail(
                    session, org_id=org_id, staff_id=staff.id,
                    start_date=_DAY1, end_date=_DAY2,
                )
                assert detail.staff_name == "Detail Dana"
                assert detail.position == "Technician"
                assert len(detail.shifts) == 3
                # Worked hours = completed only (480 + 240 = 720 min = 12h).
                assert float(detail.worked_hours) == pytest.approx(12.0)
                # Two completed, unreviewed → pending 2, reviewed 0.
                assert detail.pending_review_count == 2
                assert detail.reviewed_count == 0

                open_shifts = [s for s in detail.shifts if s.is_open]
                assert len(open_shifts) == 1
                assert open_shifts[0].worked_hours is None
                assert open_shifts[0].reviewed is False
                # No matched scheduled shift was linked.
                assert all(s.scheduled_start is None for s in detail.shifts)
                # Shifts are ordered by clock-in.
                ins = [s.clock_in_at for s in detail.shifts]
                assert ins == sorted(ins)
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_attendance_detail_lists_shifts_open_excluded():
    """Detail lists every shift; the open one is excluded from worked + review.

    **Validates: Attendance review — drill-in shift list + open-shift handling.**
    """
    asyncio.run(_run_detail_lists_shifts())


# ---------------------------------------------------------------------------
# Test 3: set_shift_review guards — open shift + out-of-branch-scope.
# ---------------------------------------------------------------------------


async def _run_review_guards() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Guard Gary")
                open_entry = await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=None, open_shift=True,
                )
                done_entry = await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=480,
                )

                # Cannot review a shift that is still open.
                with pytest.raises(ValueError, match="shift_still_open"):
                    await set_shift_review(
                        session, org_id=org_id, entry_id=open_entry.id,
                        reviewed=True, actor_id=uuid.uuid4(),
                    )

                # Out-of-branch-scope caller is denied.
                with pytest.raises(ValueError, match="branch_access_denied"):
                    await set_shift_review(
                        session, org_id=org_id, entry_id=done_entry.id,
                        reviewed=True, actor_id=uuid.uuid4(),
                        branch_ids=[uuid.uuid4()],
                    )

                # Unknown entry → shift_not_found.
                with pytest.raises(ValueError, match="shift_not_found"):
                    await set_shift_review(
                        session, org_id=org_id, entry_id=uuid.uuid4(),
                        reviewed=True, actor_id=uuid.uuid4(),
                    )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_set_shift_review_guards():
    """set_shift_review refuses open shifts, out-of-scope branches, missing rows.

    **Validates: Attendance review — sign-off guard rails.**
    """
    asyncio.run(_run_review_guards())


# ---------------------------------------------------------------------------
# Test 4: review_all signs off every completed shift and is idempotent.
# ---------------------------------------------------------------------------


async def _run_review_all_idempotent() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Bulk Bella")
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=480,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=300,
                )
                # An open shift should NOT be counted/affected.
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=None, open_shift=True,
                )

                actor = uuid.uuid4()
                first = await review_all_shifts(
                    session, org_id=org_id, staff_id=staff.id,
                    start_date=_DAY1, end_date=_DAY2, actor_id=actor,
                )
                assert first["affected_count"] == 2

                detail = await compute_attendance_detail(
                    session, org_id=org_id, staff_id=staff.id,
                    start_date=_DAY1, end_date=_DAY2,
                )
                assert detail.pending_review_count == 0
                assert detail.reviewed_count == 2

                # Idempotent — already-reviewed shifts are skipped.
                second = await review_all_shifts(
                    session, org_id=org_id, staff_id=staff.id,
                    start_date=_DAY1, end_date=_DAY2, actor_id=actor,
                )
                assert second["affected_count"] == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_review_all_shifts_idempotent():
    """review_all signs off completed shifts only, and is idempotent.

    **Validates: Attendance review — bulk approve all + idempotency.**
    """
    asyncio.run(_run_review_all_idempotent())


# ---------------------------------------------------------------------------
# Test 5: fixed-hours staff show their weekly pattern times per shift even when
#         no rostered shift exists to match against.
# ---------------------------------------------------------------------------

# Mon 1 Jun 2026 is a Monday, so _DAY1 (2 Jun) = Tuesday, _DAY2 (3 Jun) = Wed.
_FIXED_PATTERN = {
    "tuesday": {"start": "09:00", "end": "17:00"},
    "wednesday": {"start": "08:30", "end": "16:30"},
}


async def _run_fixed_pattern_in_detail() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(
                    session, org_id=org_id, name="Fixed Fiona",
                    working_arrangement="fixed",
                    availability_schedule=_FIXED_PATTERN,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=480,  # Tuesday
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY2, worked_minutes=480,  # Wednesday
                )

                detail = await compute_attendance_detail(
                    session, org_id=org_id, staff_id=staff.id,
                    start_date=_DAY1, end_date=_DAY2,
                )
                by_date = {s.work_date: s for s in detail.shifts}
                tue = by_date[_DAY1.isoformat()]
                wed = by_date[_DAY2.isoformat()]
                # No rostered shift was linked → scheduled_* stays None, but the
                # fixed weekly pattern surfaces per weekday.
                assert tue.scheduled_start is None
                assert tue.pattern_start == "09:00"
                assert tue.pattern_end == "17:00"
                assert wed.pattern_start == "08:30"
                assert wed.pattern_end == "16:30"
                # Expected source for a fixed employee is the fixed pattern.
                assert detail.expected_source == "fixed"
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_fixed_staff_show_pattern_times_per_shift():
    """Fixed-hours staff show their weekly pattern per shift (no rostered match).

    **Validates: Attendance review — fixed-pattern fallback in shift drill-in.**
    """
    asyncio.run(_run_fixed_pattern_in_detail())


# ---------------------------------------------------------------------------
# Helpers for the day-level correction tests (need a PayPeriod + Timesheet).
# ---------------------------------------------------------------------------


async def _new_period(session, *, org_id, start, end, status="open") -> PayPeriod:
    period = PayPeriod(
        org_id=org_id, start_date=start, end_date=end,
        pay_date=_PAY_DATE, status=status,
    )
    session.add(period)
    await session.flush()
    return period


async def _new_timesheet(session, *, org_id, staff_id, period_id, branch_id=None,
                         status="open", rostered=0, actual=0) -> Timesheet:
    ts = Timesheet(
        org_id=org_id, staff_id=staff_id, pay_period_id=period_id,
        branch_id=branch_id, status=status,
        rostered_minutes=rostered, actual_minutes=actual, ordinary_minutes=actual,
    )
    session.add(ts)
    await session.flush()
    return ts


async def _reload_ts(session, ts_id):
    return (await session.execute(select(Timesheet).where(Timesheet.id == ts_id))).scalar_one()


async def _new_user(session, *, org_id) -> User:
    user = User(
        org_id=org_id,
        email=f"actor_{uuid.uuid4().hex[:10]}@example.com",
        role="org_admin",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# Test 6: editing clock times recomputes worked, resets review, flows to the
#         covering timesheet's actual_minutes.
# ---------------------------------------------------------------------------


async def _run_edit_times_flows_to_timesheet() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Clock Carl")
                period = await _new_period(session, org_id=org_id, start=_WEEK_START, end=_WEEK_END)
                ts = await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id, actual=480,
                )
                entry = await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=480,  # 09:00–17:00
                )
                # Sign it off, then edit → sign-off must reset.
                actor = uuid.uuid4()
                await set_shift_review(
                    session, org_id=org_id, entry_id=entry.id, reviewed=True, actor_id=actor,
                )

                # Correct clock-out to 18:00 → 9h worked (540 min).
                new_out = datetime.combine(_DAY1, time(18, 0), tzinfo=timezone.utc)
                new_in = datetime.combine(_DAY1, time(9, 0), tzinfo=timezone.utc)
                edited = await edit_shift(
                    session, org_id=org_id, entry_id=entry.id,
                    clock_in_at=new_in, clock_out_at=new_out,
                    reason="Forgot to clock out", actor_id=actor,
                )
                assert edited.worked_minutes == 540
                flags = edited.flags or {}
                # Original preserved; review sign-off reset.
                assert flags["adjustment"]["original"]["worked_minutes"] == 480
                assert flags["adjustment"]["reason"] == "Forgot to clock out"
                assert "reviewed" not in flags

                # Covering timesheet recomputed to the new worked total.
                ts_after = await _reload_ts(session, ts.id)
                assert ts_after.actual_minutes == 540
                assert ts_after.ordinary_minutes == 540
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_edit_times_recompute_and_flow_to_timesheet():
    """Editing clock times recomputes worked, resets review, updates the timesheet.

    **Validates: day-level adjust — time correction flows to payroll.**
    """
    asyncio.run(_run_edit_times_flows_to_timesheet())


# ---------------------------------------------------------------------------
# Test 7: a manual hours override for a FIXED staff member overrides just that
#         day; other days keep their scheduled hours.
# ---------------------------------------------------------------------------


async def _run_fixed_manual_override_per_day() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                # Tuesday + Wednesday 8h each = 960 min scheduled for the week.
                staff = await _new_staff(
                    session, org_id=org_id, name="Fixed Faye",
                    working_arrangement="fixed",
                    availability_schedule={
                        "tuesday": {"start": "09:00", "end": "17:00"},
                        "wednesday": {"start": "09:00", "end": "17:00"},
                    },
                )
                period = await _new_period(session, org_id=org_id, start=_WEEK_START, end=_WEEK_END)
                ts = await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id, rostered=960, actual=960,
                )

                # Override Tuesday to 6h (360 min); Wednesday stays scheduled 8h.
                actor = await _new_user(session, org_id=org_id)
                await add_manual_shift(
                    session, org_id=org_id, staff_id=staff.id, work_date=_DAY1,
                    worked_minutes=360, reason="Left early — agreed 6h",
                    actor_id=actor.id, branch_id=branch_id,
                )

                ts_after = await _reload_ts(session, ts.id)
                # 360 (Tue override) + 480 (Wed scheduled) = 840.
                assert ts_after.actual_minutes == 840

                # The manual entry shows up in the detail as an hours override.
                detail = await compute_attendance_detail(
                    session, org_id=org_id, staff_id=staff.id,
                    start_date=_DAY1, end_date=_DAY1,
                )
                assert len(detail.shifts) == 1
                s = detail.shifts[0]
                assert s.is_manual is True
                assert s.is_manual_hours is True
                assert float(s.worked_hours) == pytest.approx(6.0)
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_fixed_manual_hours_override_per_day():
    """A manual hours override replaces just that day for a fixed staff member.

    **Validates: day-level adjust — fixed per-day override + recompute.**
    """
    asyncio.run(_run_fixed_manual_override_per_day())


# ---------------------------------------------------------------------------
# Test 8: locked pay period blocks edits/adds; delete guards on manual-only.
# ---------------------------------------------------------------------------


async def _run_locked_and_delete_guards() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Lock Lena")
                period = await _new_period(
                    session, org_id=org_id, start=_WEEK_START, end=_WEEK_END,
                )
                await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id, status="locked",
                )
                entry = await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=_DAY1, worked_minutes=480,
                )

                # Editing within a locked period is refused.
                with pytest.raises(ValueError, match="shift_locked"):
                    await edit_shift(
                        session, org_id=org_id, entry_id=entry.id,
                        clock_in_at=datetime.combine(_DAY1, time(9, 0), tzinfo=timezone.utc),
                        clock_out_at=datetime.combine(_DAY1, time(18, 0), tzinfo=timezone.utc),
                        reason="too late", actor_id=uuid.uuid4(),
                    )

                # A real clock punch cannot be voided (only admin-added days).
                with pytest.raises(ValueError, match="not_manual"):
                    await void_manual_shift(
                        session, org_id=org_id, entry_id=entry.id, actor_id=uuid.uuid4(),
                    )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_locked_period_and_delete_guards():
    """Locked periods block edits; only admin-added days can be deleted.

    **Validates: day-level adjust — locked immutability + delete guard.**
    """
    asyncio.run(_run_locked_and_delete_guards())


# ---------------------------------------------------------------------------
# Test 9: add then delete a manual day round-trips the timesheet actual.
# ---------------------------------------------------------------------------


async def _run_add_then_delete_manual() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                staff = await _new_staff(session, org_id=org_id, name="Casual Cody")
                period = await _new_period(session, org_id=org_id, start=_WEEK_START, end=_WEEK_END)
                ts = await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id, actual=0,
                )

                actor = await _new_user(session, org_id=org_id)
                entry = await add_manual_shift(
                    session, org_id=org_id, staff_id=staff.id, work_date=_DAY1,
                    worked_minutes=300, reason="Covered a shift",
                    actor_id=actor.id, branch_id=branch_id,
                )
                ts_after = await _reload_ts(session, ts.id)
                assert ts_after.actual_minutes == 300

                await void_manual_shift(
                    session, org_id=org_id, entry_id=entry.id, actor_id=actor.id,
                )
                ts_final = await _reload_ts(session, ts.id)
                assert ts_final.actual_minutes == 0
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_add_then_delete_manual_roundtrip():
    """Adding then deleting a manual day round-trips the timesheet actual.

    **Validates: day-level adjust — manual add/delete recompute round-trip.**
    """
    asyncio.run(_run_add_then_delete_manual())
