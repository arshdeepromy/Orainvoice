"""Staff timesheets service — CRUD, status transitions, lazy creation, bulk actions.

Transaction discipline: uses flush() + refresh() only. The session.begin()
context manager in get_db_session handles commit/rollback.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.audit import write_audit_log
from app.modules.timesheets.models import Timesheet, TimesheetSettings


# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"pending_approval"},
    "pending_approval": {"approved", "open"},  # open = withdraw/reject
    "approved": {"locked", "open"},  # open = reopen/reject
    "locked": set(),  # terminal in Phase A
}


async def get_or_create_timesheet(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    pay_period_id: UUID,
    branch_id: UUID | None = None,
) -> Timesheet:
    """Get existing timesheet or create one (lazy creation trigger).

    Returns existing if UNIQUE(staff_id, pay_period_id) already satisfied,
    otherwise creates with status='open' and default zero minutes.
    """
    result = await db.execute(
        select(Timesheet).where(
            Timesheet.staff_id == staff_id,
            Timesheet.pay_period_id == pay_period_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing

    timesheet = Timesheet(
        org_id=org_id,
        staff_id=staff_id,
        pay_period_id=pay_period_id,
        branch_id=branch_id,
        status="open",
    )
    db.add(timesheet)
    await db.flush()
    await db.refresh(timesheet)
    return timesheet


async def transition_status(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    new_status: str,
    actor_id: UUID,
    org_id: UUID,
) -> Timesheet:
    """Transition a timesheet to a new status with validation and audit.

    Raises ValueError if the transition is invalid.
    """
    current = timesheet.status
    if new_status not in VALID_TRANSITIONS.get(current, set()):
        raise ValueError(
            f"Invalid status transition: {current} \u2192 {new_status}"
        )

    before_status = timesheet.status
    timesheet.status = new_status
    timesheet.updated_at = datetime.now(timezone.utc)

    if new_status == "approved":
        timesheet.approved_by = actor_id
        timesheet.approved_at = datetime.now(timezone.utc)
    elif new_status == "locked":
        timesheet.locked_by = actor_id
        timesheet.locked_at = datetime.now(timezone.utc)
    elif new_status == "open":
        # Reset approval fields on reject/reopen
        timesheet.approved_by = None
        timesheet.approved_at = None

    await db.flush()
    await db.refresh(timesheet)

    await write_audit_log(
        db,
        action=f"timesheet.{new_status}",
        entity_type="timesheet",
        org_id=org_id,
        user_id=actor_id,
        entity_id=timesheet.id,
        before_value={"status": before_status},
        after_value={"status": new_status},
    )

    return timesheet


async def adjust_timesheet(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    adjusted_minutes: int,
    notes: str,
    actor_id: UUID,
    org_id: UUID,
) -> Timesheet:
    """Set adjusted_minutes on a timesheet with audit trail.

    Only allowed when status is 'open' or 'pending_approval'.
    Raises ValueError if timesheet is approved or locked.
    """
    if timesheet.status in ("approved", "locked"):
        raise ValueError(
            f"Cannot adjust a timesheet in status '{timesheet.status}'"
        )

    before = timesheet.adjusted_minutes
    timesheet.adjusted_minutes = adjusted_minutes
    timesheet.notes = notes
    timesheet.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(timesheet)

    await write_audit_log(
        db,
        action="timesheet.adjusted",
        entity_type="timesheet",
        org_id=org_id,
        user_id=actor_id,
        entity_id=timesheet.id,
        before_value={"adjusted_minutes": before},
        after_value={"adjusted_minutes": adjusted_minutes, "notes": notes},
    )

    return timesheet


async def bulk_approve(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
    actor_id: UUID,
    threshold_minutes: int = 0,
    branch_ids: list[UUID] | None = None,
) -> dict:
    """Approve all 'clean' timesheets (no exceptions, within variance threshold).

    Returns {"affected_count": N, "skipped_count": M}.
    """
    query = select(Timesheet).where(
        Timesheet.org_id == org_id,
        Timesheet.pay_period_id == pay_period_id,
        Timesheet.status.in_(["open", "pending_approval"]),
    )
    if branch_ids:
        query = query.where(Timesheet.branch_id.in_(branch_ids))

    result = await db.execute(query)
    timesheets = list(result.scalars().all())

    affected = 0
    skipped = 0

    for ts in timesheets:
        # Skip if has exceptions
        if ts.exception_flags and len(ts.exception_flags) > 0:
            skipped += 1
            continue
        # Skip if variance exceeds threshold (when threshold > 0)
        if threshold_minutes > 0:
            variance = abs(ts.actual_minutes - ts.rostered_minutes)
            if variance > threshold_minutes:
                skipped += 1
                continue
        # Approve
        ts.status = "approved"
        ts.approved_by = actor_id
        ts.approved_at = datetime.now(timezone.utc)
        ts.updated_at = datetime.now(timezone.utc)
        affected += 1

    if affected > 0:
        await db.flush()

    return {"affected_count": affected, "skipped_count": skipped}


async def bulk_lock(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
    actor_id: UUID,
    branch_ids: list[UUID] | None = None,
) -> dict:
    """Lock all approved timesheets for a period.

    Returns {"affected_count": N, "skipped_count": M}.
    """
    query = select(Timesheet).where(
        Timesheet.org_id == org_id,
        Timesheet.pay_period_id == pay_period_id,
        Timesheet.status == "approved",
    )
    if branch_ids:
        query = query.where(Timesheet.branch_id.in_(branch_ids))

    result = await db.execute(query)
    timesheets = list(result.scalars().all())

    affected = 0
    for ts in timesheets:
        ts.status = "locked"
        ts.locked_by = actor_id
        ts.locked_at = datetime.now(timezone.utc)
        ts.updated_at = datetime.now(timezone.utc)
        affected += 1

    if affected > 0:
        await db.flush()

    return {"affected_count": affected, "skipped_count": 0}


@dataclass
class MaterialisationResult:
    """Result of the sweep that creates missing timesheets."""
    created_count: int = 0
    no_activity_staff: list[UUID] = field(default_factory=list)


# Map Python ``datetime.weekday()`` (Mon=0..Sun=6) onto the lowercase
# weekday keys used by ``staff.availability_schedule``.
_WEEKDAY_KEYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def _parse_hhmm(value: str | None) -> int | None:
    """Parse an ``"HH:MM"`` string into minutes-since-midnight."""
    if not value or ":" not in value:
        return None
    try:
        h, m = value.split(":", 1)
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def compute_fixed_rostered_minutes(
    availability_schedule: dict | None,
    start_date,
    end_date,
) -> int:
    """Sum the fixed work-day minutes across a pay period.

    Walks each calendar day in ``[start_date, end_date]`` inclusive and,
    for every day whose weekday has a configured ``{start, end}`` entry in
    ``availability_schedule``, adds the shift duration. This makes a staff
    member's configured work days + hours the single source of truth for
    rostered hours when their working arrangement is ``fixed``.

    Overnight shifts (end <= start) are treated as wrapping past midnight.
    """
    if not isinstance(availability_schedule, dict) or not availability_schedule:
        # Guard against NULL/empty and against legacy rows where the JSONB value
        # is a scalar (e.g. a JSON string) rather than the expected weekday map.
        return 0

    from datetime import timedelta

    total = 0
    cursor = start_date
    while cursor <= end_date:
        key = _WEEKDAY_KEYS[cursor.weekday()]
        entry = availability_schedule.get(key)
        if isinstance(entry, dict):
            start_min = _parse_hhmm(entry.get("start"))
            end_min = _parse_hhmm(entry.get("end"))
            if start_min is not None and end_min is not None:
                duration = end_min - start_min
                if duration <= 0:
                    # Overnight shift wraps to the next day.
                    duration += 24 * 60
                total += duration
        cursor += timedelta(days=1)

    return total


def _build_week_buckets(start_date, end_date):
    """Split ``[start_date, end_date]`` into ISO-week (Mon–Sun) buckets.

    Each bucket is clamped to the period bounds, so the first and last buckets
    may be partial weeks. Returns a list of
    ``(week_index, iso_week, bucket_start, bucket_end)`` tuples where
    ``week_index`` is 1-based and ``iso_week`` is the ISO 8601 week number
    (matching the frontend ``isoWeek`` helper / Python ``date.isocalendar()``).
    """
    from datetime import timedelta

    buckets: list[tuple[int, int, "object", "object"]] = []
    if start_date is None or end_date is None or start_date > end_date:
        return buckets

    week_index = 0
    cursor = start_date
    while cursor <= end_date:
        # Monday of the week containing ``cursor``; Sunday is +6 days.
        monday = cursor - timedelta(days=cursor.weekday())
        sunday = monday + timedelta(days=6)
        bucket_start = max(monday, start_date)
        bucket_end = min(sunday, end_date)
        week_index += 1
        iso_week = bucket_start.isocalendar()[1]
        buckets.append((week_index, iso_week, bucket_start, bucket_end))
        cursor = sunday + timedelta(days=1)

    return buckets


async def compute_weekly_breakdown(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
    branch_ids: list[UUID] | None = None,
):
    """Split a pay period into per-week per-staff worked-minute subtotals.

    READ-ONLY review aid ("weekly lens"). Lets managers see weekly granularity
    inside a multi-week (fortnightly / monthly) period without a separate period
    system. This never reads or writes pay-run / materialisation / payslip state.

    Steps:
      1. Load the ``PayPeriod``; return an empty result if missing.
      2. Build ISO-week (Mon–Sun) buckets clamped to the period bounds.
      3. The period's staff = staff with a ``Timesheet`` row for this period.
         When ``branch_ids`` is provided (branch-scoped caller) the timesheet
         set is filtered to those branches — an empty list yields no staff.
      4. Per staff per bucket, the worked minutes are:
         - the sum of ``TimeClockEntry.worked_minutes`` (NULL treated as 0) for
           clock-ins whose date falls in the clamped bucket; OR
         - for ``fixed`` working-arrangement staff with NO clock entries in the
           bucket, their schedule-derived rostered minutes
           (``compute_fixed_rostered_minutes``) — mirroring how materialisation
           seeds fixed staff. When a fixed staff member HAS clock entries in the
           bucket, the clock sum is preferred.
      5. Each bucket carries ``total_minutes`` (sum across staff) and a ``staff``
         list; zero-minute staff are omitted from a week to keep it tidy, but the
         week bucket is always kept (even when its total is 0).
    """
    from datetime import timedelta

    from app.modules.payslips.models import PayPeriod
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry
    from app.modules.timesheets.schemas import (
        WeeklyBreakdownResponse,
        WeeklyBreakdownStaffEntry,
        WeeklyBreakdownWeek,
    )

    # 1. Load the period.
    period = await db.get(PayPeriod, pay_period_id)
    if period is None or period.org_id != org_id:
        return WeeklyBreakdownResponse(
            pay_period_id=pay_period_id, multi_week=False, weeks=[],
        )

    # 2. ISO-week buckets clamped to the period.
    buckets = _build_week_buckets(period.start_date, period.end_date)

    # 3. The period's staff = staff with a Timesheet row (branch-scoped).
    ts_query = select(Timesheet.staff_id).where(
        Timesheet.org_id == org_id,
        Timesheet.pay_period_id == pay_period_id,
    )
    if branch_ids is not None:
        # A scoped caller restricts to their branches. An empty list yields no
        # rows (in_([]) is always-false) — the secure "show nothing" default.
        ts_query = ts_query.where(Timesheet.branch_id.in_(branch_ids))
    staff_rows = await db.execute(ts_query.distinct())
    staff_ids = {row[0] for row in staff_rows.all()}

    if not staff_ids:
        return WeeklyBreakdownResponse(
            pay_period_id=pay_period_id,
            multi_week=len(buckets) > 1,
            weeks=[
                WeeklyBreakdownWeek(
                    week_index=wi,
                    iso_week=iso,
                    start_date=bs,
                    end_date=be,
                    total_minutes=0,
                    staff=[],
                )
                for (wi, iso, bs, be) in buckets
            ],
        )

    # Resolve staff names + working arrangement + schedule.
    staff_result = await db.execute(
        select(StaffMember).where(StaffMember.id.in_(staff_ids))
    )
    staff_map = {s.id: s for s in staff_result.scalars().all()}

    # Fetch every clock entry for these staff across the whole period range
    # once, then bucket in Python by the clock-in date. The period range is
    # inclusive of end_date, so the upper bound is the day AFTER end_date.
    entries_by_staff: dict[UUID, list] = {sid: [] for sid in staff_ids}
    if period.start_date is not None and period.end_date is not None:
        clock_result = await db.execute(
            select(TimeClockEntry).where(
                TimeClockEntry.org_id == org_id,
                TimeClockEntry.staff_id.in_(staff_ids),
                TimeClockEntry.clock_in_at >= period.start_date,
                TimeClockEntry.clock_in_at < period.end_date + timedelta(days=1),
            )
        )
        for ce in clock_result.scalars().all():
            entries_by_staff.setdefault(ce.staff_id, []).append(ce)

    # 4 + 5. Build each week bucket.
    weeks: list[WeeklyBreakdownWeek] = []
    for (week_index, iso_week, bucket_start, bucket_end) in buckets:
        staff_entries: list[WeeklyBreakdownStaffEntry] = []
        week_total = 0
        for staff_id in staff_ids:
            staff = staff_map.get(staff_id)
            entries = entries_by_staff.get(staff_id, [])

            in_bucket = [
                e for e in entries
                if e.clock_in_at is not None
                and bucket_start <= e.clock_in_at.date() <= bucket_end
            ]
            has_clock = len(in_bucket) > 0
            minutes = sum((e.worked_minutes or 0) for e in in_bucket)

            # Fixed-arrangement staff with NO clock entries in the bucket fall
            # back to their schedule-derived rostered minutes for the week.
            if (
                not has_clock
                and staff is not None
                and staff.working_arrangement == "fixed"
            ):
                minutes = compute_fixed_rostered_minutes(
                    staff.availability_schedule, bucket_start, bucket_end,
                )

            if minutes > 0:
                staff_entries.append(
                    WeeklyBreakdownStaffEntry(
                        staff_id=staff_id,
                        staff_name=(getattr(staff, "name", None) or "Unknown"),
                        minutes=minutes,
                    )
                )
                week_total += minutes

        # Stable, readable ordering by staff name.
        staff_entries.sort(key=lambda e: e.staff_name.lower())

        weeks.append(
            WeeklyBreakdownWeek(
                week_index=week_index,
                iso_week=iso_week,
                start_date=bucket_start,
                end_date=bucket_end,
                total_minutes=week_total,
                staff=staff_entries,
            )
        )

    return WeeklyBreakdownResponse(
        pay_period_id=pay_period_id,
        multi_week=len(weeks) > 1,
        weeks=weeks,
    )


async def materialise_missing_timesheets(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
    include_all_active: bool = False,
) -> MaterialisationResult:
    """Sweep to create missing timesheets before pay-run cutoff.

    Two sources feed materialisation by default:
      1. Staff with clock entries in the period but no timesheet row.
      2. Staff whose ``working_arrangement`` is ``fixed`` — their
         configured work days + hours (``availability_schedule``) are
         the single source of truth, so a timesheet is created (and its
         ``rostered_minutes`` seeded from the schedule) even without any
         clock punch or roster entry.

    When ``include_all_active`` is True (the "Generate Timesheets"
    manual action), a third source is added: EVERY active staff member
    without a timesheet for the period, regardless of working
    arrangement. Rostered / casual staff get a zero-hours timesheet the
    admin can fill in via the Adjust flow; fixed staff still seed from
    their schedule. This lets payroll be run for staff who never clock
    in.

    Staff with NO clock, NO fixed arrangement, NO activity are left as
    no_activity (no row created) unless ``include_all_active`` is set.

    **Cycle scoping (per-staff-pay-cycle, REQ 6.1-6.4, 9.2).** When the
    ``PayPeriod`` carries a ``pay_cycle_id``, materialisation is scoped to
    that cycle: every candidate active staff member is gathered exactly as
    before (clock / fixed sources, and all active when ``include_all_active``),
    their applicable cycle is batch-resolved once via
    :func:`resolve_pay_cycles_for_staff_batch`, and a timesheet row is created
    **only** for staff whose resolved cycle id equals the period's
    ``pay_cycle_id``. Staff with no resolved cycle, or a cycle that differs from
    the period's, are simply out of scope for this cycle — they are skipped and
    are NOT reported as ``no_activity``. When ``pay_cycle_id`` is ``NULL``
    (a legacy period that predates multi-cycle support), the original
    single-cycle behaviour is preserved exactly so old periods are unaffected
    (REQ 9.2).
    """
    from app.modules.time_clock.models import TimeClockEntry
    from app.modules.payslips.models import PayPeriod
    from app.modules.staff.models import StaffMember
    from app.modules.timesheets.pay_cycles import (
        resolve_pay_cycles_for_staff_batch,
    )

    # Get the pay period boundaries
    period_result = await db.execute(
        select(PayPeriod).where(PayPeriod.id == pay_period_id)
    )
    period = period_result.scalar_one_or_none()
    if not period:
        return MaterialisationResult()

    # Staff IDs that already have a timesheet for this period
    has_timesheet = select(Timesheet.staff_id).where(
        Timesheet.pay_period_id == pay_period_id,
        Timesheet.org_id == org_id,
    )

    # Source 1: staff IDs with clock entries in this period (no timesheet yet).
    # The period range is inclusive of end_date, so the upper bound is the day
    # AFTER end_date — otherwise clock-ins on the final day are missed.
    from datetime import timedelta

    staff_with_clocks = await db.execute(
        select(TimeClockEntry.staff_id).where(
            TimeClockEntry.org_id == org_id,
            TimeClockEntry.clock_in_at >= period.start_date,
            TimeClockEntry.clock_in_at < period.end_date + timedelta(days=1),
            TimeClockEntry.staff_id.not_in(has_timesheet),
        ).distinct()
    )
    clock_staff_ids = {row[0] for row in staff_with_clocks.all()}

    # Source 2: active fixed-arrangement staff (schedule is source of truth)
    fixed_staff_result = await db.execute(
        select(StaffMember).where(
            StaffMember.org_id == org_id,
            StaffMember.is_active == True,  # noqa: E712
            StaffMember.working_arrangement == "fixed",
            StaffMember.id.not_in(has_timesheet),
        )
    )
    staff_map: dict = {s.id: s for s in fixed_staff_result.scalars().all()}

    result = MaterialisationResult()

    # Need StaffMember rows for any clock-only staff to read their arrangement
    clock_only_ids = clock_staff_ids - set(staff_map.keys())
    if clock_only_ids:
        rows = await db.execute(
            select(StaffMember).where(StaffMember.id.in_(clock_only_ids))
        )
        staff_map.update({s.id: s for s in rows.scalars().all()})

    # Source 3 (manual "Generate Timesheets"): every active staff member
    # without a timesheet, regardless of working arrangement. Rostered /
    # casual staff get a zero-hours row to fill in via Adjust; fixed staff
    # still seed from their schedule in the loop below.
    if include_all_active:
        all_active = await db.execute(
            select(StaffMember).where(
                StaffMember.org_id == org_id,
                StaffMember.is_active == True,  # noqa: E712
                StaffMember.id.not_in(has_timesheet),
            )
        )
        staff_map.update({s.id: s for s in all_active.scalars().all()})

    all_staff_ids = clock_staff_ids | set(staff_map.keys())

    # Cycle-scoped membership (per-staff-pay-cycle). When the period belongs to
    # a specific pay cycle, batch-resolve every candidate's applicable cycle once
    # and keep only those whose resolved cycle id matches the period's
    # pay_cycle_id (REQ 6.1-6.4). A NULL pay_cycle_id is a legacy period whose
    # behaviour must be preserved exactly (REQ 9.2), so resolved_cycle_by_staff
    # is left None and no filtering is applied.
    resolved_cycle_by_staff = None
    if period.pay_cycle_id is not None:
        candidates = [
            staff_map[sid] for sid in all_staff_ids if sid in staff_map
        ]
        resolved_cycle_by_staff = await resolve_pay_cycles_for_staff_batch(
            db, org_id=org_id, staff_members=candidates
        )

    for staff_id in all_staff_ids:
        # Cycle-scope filter: skip staff whose resolved cycle differs from (or is
        # absent for) the period's cycle. Excluded staff are out of scope for
        # this cycle and are deliberately NOT recorded as no_activity.
        if resolved_cycle_by_staff is not None:
            resolved = resolved_cycle_by_staff.get(staff_id)
            if resolved is None or resolved.cycle.id != period.pay_cycle_id:
                continue

        staff = staff_map.get(staff_id)
        rostered = 0
        is_fixed = staff is not None and staff.working_arrangement == "fixed"
        # Seed rostered minutes from the fixed schedule (source of truth).
        if is_fixed:
            rostered = compute_fixed_rostered_minutes(
                staff.availability_schedule,
                period.start_date,
                period.end_date,
            )
        timesheet = Timesheet(
            org_id=org_id,
            staff_id=staff_id,
            pay_period_id=pay_period_id,
            rostered_minutes=rostered,
            # Fixed-arrangement staff are paid their configured hours even
            # without clock punches. Seed actual + ordinary from the roster
            # so the timesheet (a) approves cleanly with zero clock variance
            # and (b) flows a non-zero payslip through the pay run. Clock-
            # only staff keep 0 here — the aggregation engine fills their
            # actual/ordinary minutes from the matched clock entries.
            actual_minutes=rostered if is_fixed else 0,
            ordinary_minutes=rostered if is_fixed else 0,
            status="open",
        )
        db.add(timesheet)
        result.created_count += 1

    if result.created_count > 0:
        await db.flush()

    return result


async def get_settings_for_branch(
    db: AsyncSession,
    *,
    org_id: UUID,
    branch_id: UUID | None = None,
) -> TimesheetSettings | None:
    """Get settings for a specific branch, falling back to org-wide default.

    Priority: branch-specific > org-wide (branch_id=NULL).
    Returns None if no settings configured.
    """
    if branch_id:
        # Try branch-specific first
        result = await db.execute(
            select(TimesheetSettings).where(
                TimesheetSettings.org_id == org_id,
                TimesheetSettings.branch_id == branch_id,
            )
        )
        branch_settings = result.scalar_one_or_none()
        if branch_settings:
            return branch_settings

    # Fall back to org-wide
    result = await db.execute(
        select(TimesheetSettings).where(
            TimesheetSettings.org_id == org_id,
            TimesheetSettings.branch_id == None,  # noqa: E711
        )
    )
    return result.scalar_one_or_none()


def _minutes_to_hours(minutes: int) -> Decimal:
    """Convert integer minutes to a 2dp Decimal of hours."""
    return Decimal(str(round((minutes or 0) / 60, 2)))


async def compute_attendance(
    db: AsyncSession,
    *,
    org_id: UUID,
    start_date=None,
    end_date=None,
    branch_ids: list[UUID] | None = None,
):
    """Per-staff worked-hours-vs-expected attendance over [start_date, end_date].

    READ-ONLY review aid for the Timesheets page "Attendance" tab. The row set is
    every staff member with clock activity (worked or currently clocked in) in
    the inclusive date range, branch-scoped via ``branch_ids`` (None = all
    branches; ``[]`` = scoped caller with no branches → empty result).

    ``start_date``/``end_date`` are interpreted in the **organisation's local
    timezone** (``organisations.timezone``, default ``Pacific/Auckland``) — NOT
    UTC — so "today" for an NZ org maps to the correct UTC window even though
    ``time_clock_entries`` are stored in UTC. When omitted, both default to the
    org-local "today".

    For each staff member:
      * ``worked`` = sum of ``TimeClockEntry.worked_minutes`` for COMPLETED
        (clocked-out) entries whose ``clock_in_at`` falls in the range.
      * ``expected`` = scheduled minutes (``schedule_entries`` clamped to the
        range) when any exist; else the fixed/rostered minutes derived from the
        staff member's ``availability_schedule`` (``compute_fixed_rostered_minutes``).
      * ``variance`` = worked − expected (null when there is no expectation).
      * ``is_clocked_in`` = the staff member has an OPEN entry in the range.

    Never reads or writes pay-run / materialisation / payslip / timesheet state.
    """
    from datetime import datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo

    from sqlalchemy import text as _sql_text

    from app.modules.organisations.models import Branch
    from app.modules.scheduling_v2.models import ScheduleEntry
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry
    from app.modules.timesheets.schemas import (
        AttendanceResponse,
        AttendanceRow,
        AttendanceSummary,
    )

    # Resolve the organisation's local timezone (clock entries are stored in
    # UTC, but "today"/ranges are meaningful in the org's local calendar day).
    tz_row = (
        await db.execute(
            _sql_text("SELECT timezone FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
    ).first()
    tz_name = (tz_row[0] if tz_row else None) or "Pacific/Auckland"
    try:
        org_tz = ZoneInfo(tz_name)
    except Exception:
        org_tz = ZoneInfo("UTC")

    today_local = datetime.now(org_tz).date()
    start_date = start_date or today_local
    end_date = end_date or start_date

    # Convert the org-local inclusive date range to a UTC [start, end) window.
    start_dt = datetime.combine(start_date, time.min, tzinfo=org_tz).astimezone(timezone.utc)
    end_dt = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=org_tz
    ).astimezone(timezone.utc)

    def _empty() -> AttendanceResponse:
        return AttendanceResponse(
            items=[],
            total=0,
            summary=AttendanceSummary(
                total_staff=0,
                total_worked_hours=Decimal("0"),
                total_expected_hours=Decimal("0"),
                clocked_in_count=0,
            ),
            date_from=start_date.isoformat(),
            date_to=end_date.isoformat(),
        )

    # A scoped caller with no assigned branches sees nothing (secure default).
    if branch_ids is not None and not branch_ids:
        return _empty()

    # 1. Clock entries in range (branch-scoped).
    entry_q = select(TimeClockEntry).where(
        TimeClockEntry.org_id == org_id,
        TimeClockEntry.clock_in_at >= start_dt,
        TimeClockEntry.clock_in_at < end_dt,
    )
    if branch_ids is not None:
        entry_q = entry_q.where(TimeClockEntry.branch_id.in_(branch_ids))
    entries = (await db.execute(entry_q)).scalars().all()

    by_staff: dict[UUID, list] = {}
    for e in entries:
        if (e.flags or {}).get("voided"):
            continue  # soft-voided manual entries don't count
        by_staff.setdefault(e.staff_id, []).append(e)
    if not by_staff:
        return _empty()

    staff_ids = set(by_staff)

    # Resolve staff (name / position / arrangement / schedule).
    staff_map = {
        s.id: s
        for s in (
            await db.execute(select(StaffMember).where(StaffMember.id.in_(staff_ids)))
        ).scalars().all()
    }

    # Resolve branch names for any branch referenced by an entry.
    branch_id_set = {
        e.branch_id for ents in by_staff.values() for e in ents if e.branch_id
    }
    branch_map: dict[UUID, str] = {}
    if branch_id_set:
        branch_map = {
            b.id: b.name
            for b in (
                await db.execute(select(Branch).where(Branch.id.in_(branch_id_set)))
            ).scalars().all()
        }

    # 2. Scheduled minutes per staff (work shifts overlapping the range, clamped).
    scheduled_minutes: dict[UUID, int] = {}
    sched_rows = (
        await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.org_id == org_id,
                ScheduleEntry.staff_id.in_(staff_ids),
                ScheduleEntry.status != "cancelled",
                ScheduleEntry.entry_type.notin_(["leave", "break"]),
                ScheduleEntry.start_time < end_dt,
                ScheduleEntry.end_time > start_dt,
            )
        )
    ).scalars().all()
    for se in sched_rows:
        clamped_start = max(se.start_time, start_dt)
        clamped_end = min(se.end_time, end_dt)
        mins = int((clamped_end - clamped_start).total_seconds() // 60)
        if mins > 0 and se.staff_id is not None:
            scheduled_minutes[se.staff_id] = scheduled_minutes.get(se.staff_id, 0) + mins

    # 3. Build rows.
    rows: list[AttendanceRow] = []
    total_worked = 0
    total_expected = 0
    clocked_in_count = 0
    total_pending_review = 0

    for staff_id, ents in by_staff.items():
        staff = staff_map.get(staff_id)
        completed = [e for e in ents if e.clock_out_at is not None]
        open_entries = [e for e in ents if e.clock_out_at is None]
        worked = sum((e.worked_minutes or 0) for e in completed)
        is_in = len(open_entries) > 0
        last_out = max((e.clock_out_at for e in completed), default=None)

        # Pre-payroll review state: a completed shift is "pending" until an
        # admin signs it off (``flags.reviewed``). Open shifts aren't counted
        # (they can't be reviewed until clock-out).
        reviewed_count = sum(
            1 for e in completed if bool((e.flags or {}).get("reviewed"))
        )
        pending_review_count = len(completed) - reviewed_count
        total_pending_review += pending_review_count

        sched = scheduled_minutes.get(staff_id, 0)
        if sched > 0:
            expected = sched
            source = "scheduled"
        else:
            roster = compute_fixed_rostered_minutes(
                getattr(staff, "availability_schedule", None), start_date, end_date,
            )
            if roster > 0:
                expected = roster
                source = (
                    "fixed"
                    if getattr(staff, "working_arrangement", None) == "fixed"
                    else "roster"
                )
            else:
                expected = 0
                source = "none"

        # Branch name = the most recent entry's branch (best-effort).
        branch_name = None
        for e in sorted(ents, key=lambda x: (x.clock_in_at or start_dt), reverse=True):
            if e.branch_id and e.branch_id in branch_map:
                branch_name = branch_map[e.branch_id]
                break

        rows.append(
            AttendanceRow(
                staff_id=staff_id,
                staff_name=(getattr(staff, "name", None) or "Unknown"),
                position=getattr(staff, "position", None),
                branch_name=branch_name,
                worked_hours=_minutes_to_hours(worked),
                expected_hours=_minutes_to_hours(expected) if source != "none" else None,
                expected_source=source,
                variance_hours=_minutes_to_hours(worked - expected) if source != "none" else None,
                shift_count=len(ents),
                is_clocked_in=is_in,
                last_clock_out_at=last_out,
                pending_review_count=pending_review_count,
                reviewed_count=reviewed_count,
            )
        )
        total_worked += worked
        total_expected += expected
        if is_in:
            clocked_in_count += 1

    rows.sort(key=lambda r: r.staff_name.lower())

    return AttendanceResponse(
        items=rows,
        total=len(rows),
        summary=AttendanceSummary(
            total_staff=len(rows),
            total_worked_hours=_minutes_to_hours(total_worked),
            total_expected_hours=_minutes_to_hours(total_expected),
            clocked_in_count=clocked_in_count,
            pending_review_count=total_pending_review,
        ),
        date_from=start_date.isoformat(),
        date_to=end_date.isoformat(),
    )


def _org_local_window(tz_name: str | None, start_date, end_date):
    """Resolve the org timezone and the UTC [start, end) window for a local
    inclusive date range. Shared by the attendance detail/review helpers."""
    from datetime import datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo

    try:
        org_tz = ZoneInfo(tz_name or "Pacific/Auckland")
    except Exception:
        org_tz = ZoneInfo("UTC")
    today_local = datetime.now(org_tz).date()
    start_date = start_date or today_local
    end_date = end_date or start_date
    start_dt = datetime.combine(start_date, time.min, tzinfo=org_tz).astimezone(timezone.utc)
    end_dt = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=org_tz
    ).astimezone(timezone.utc)
    return org_tz, start_date, end_date, start_dt, end_dt


async def compute_attendance_detail(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    start_date=None,
    end_date=None,
    branch_ids: list[UUID] | None = None,
):
    """Per-staff shift list for the Attendance drill-in (review/approve view).

    Lists every clock shift the staff member has in the org-local date range,
    each annotated with its matched scheduled shift (when linked) and its
    pre-payroll review state (``flags.reviewed``). Branch-scoped via
    ``branch_ids`` (None = all branches). READ-ONLY.
    """
    from sqlalchemy import text as _sql_text

    from app.modules.auth.models import User
    from app.modules.organisations.models import Branch
    from app.modules.scheduling_v2.models import ScheduleEntry
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry
    from app.modules.timesheets.schemas import (
        AttendanceDetailResponse,
        AttendanceShift,
    )

    tz_row = (
        await db.execute(
            _sql_text("SELECT timezone FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
    ).first()
    org_tz, start_date, end_date, start_dt, end_dt = _org_local_window(
        tz_row[0] if tz_row else None, start_date, end_date
    )

    staff = await db.get(StaffMember, staff_id)
    staff_name = (getattr(staff, "name", None) or "Unknown") if staff else "Unknown"

    # Scoped caller with no branches → nothing.
    if branch_ids is not None and not branch_ids:
        return AttendanceDetailResponse(
            staff_id=staff_id, staff_name=staff_name,
            position=getattr(staff, "position", None),
            date_from=start_date.isoformat(), date_to=end_date.isoformat(),
            worked_hours=Decimal("0"),
        )

    entry_q = select(TimeClockEntry).where(
        TimeClockEntry.org_id == org_id,
        TimeClockEntry.staff_id == staff_id,
        TimeClockEntry.clock_in_at >= start_dt,
        TimeClockEntry.clock_in_at < end_dt,
    )
    if branch_ids is not None:
        entry_q = entry_q.where(TimeClockEntry.branch_id.in_(branch_ids))
    entries = (
        await db.execute(entry_q.order_by(TimeClockEntry.clock_in_at))
    ).scalars().all()
    # Voided manual entries are soft-deleted — exclude from the drill-in.
    entries = [e for e in entries if not (e.flags or {}).get("voided")]

    # Resolve branch names.
    branch_id_set = {e.branch_id for e in entries if e.branch_id}
    branch_map: dict[UUID, str] = {}
    if branch_id_set:
        branch_map = {
            b.id: b.name
            for b in (
                await db.execute(select(Branch).where(Branch.id.in_(branch_id_set)))
            ).scalars().all()
        }

    # Resolve matched scheduled shifts.
    sched_id_set = {e.scheduled_entry_id for e in entries if e.scheduled_entry_id}
    sched_map: dict[UUID, ScheduleEntry] = {}
    if sched_id_set:
        sched_map = {
            s.id: s
            for s in (
                await db.execute(select(ScheduleEntry).where(ScheduleEntry.id.in_(sched_id_set)))
            ).scalars().all()
        }

    # Resolve reviewer names.
    reviewer_ids = {
        UUID(str((e.flags or {}).get("reviewed_by")))
        for e in entries
        if (e.flags or {}).get("reviewed_by")
    }
    reviewer_map: dict[UUID, str] = {}
    if reviewer_ids:
        reviewer_map = {
            u.id: (getattr(u, "full_name", None) or getattr(u, "email", None))
            for u in (
                await db.execute(select(User).where(User.id.in_(reviewer_ids)))
            ).scalars().all()
        }

    shifts: list[AttendanceShift] = []
    worked = 0
    reviewed_count = 0
    pending_review_count = 0
    avail = getattr(staff, "availability_schedule", None)
    _wd_keys = (
        "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday", "sunday",
    )
    for e in entries:
        flags = e.flags or {}
        is_open = e.clock_out_at is None
        reviewed = bool(flags.get("reviewed"))
        sched = sched_map.get(e.scheduled_entry_id) if e.scheduled_entry_id else None
        local_date = e.clock_in_at.astimezone(org_tz).date()
        # Fixed/rostered weekly pattern for this weekday (no rostered shift to
        # match against → still show what was expected per the pattern).
        day_pat = avail.get(_wd_keys[local_date.weekday()]) if isinstance(avail, dict) else None
        pattern_start = day_pat.get("start") if isinstance(day_pat, dict) else None
        pattern_end = day_pat.get("end") if isinstance(day_pat, dict) else None
        reviewer_uid = flags.get("reviewed_by")
        reviewer_name = None
        if reviewer_uid:
            try:
                reviewer_name = reviewer_map.get(UUID(str(reviewer_uid)))
            except (ValueError, TypeError):
                reviewer_name = None
        if not is_open:
            worked += e.worked_minutes or 0
            if reviewed:
                reviewed_count += 1
            else:
                pending_review_count += 1
        adj = flags.get("adjustment") if isinstance(flags.get("adjustment"), dict) else None
        orig = adj.get("original") if isinstance(adj, dict) else None
        orig_worked = orig.get("worked_minutes") if isinstance(orig, dict) else None

        def _parse_dt(v):
            if not v:
                return None
            try:
                return datetime.fromisoformat(v)
            except (ValueError, TypeError):
                return None

        corrected_in = _parse_dt(adj.get("corrected_clock_in_at")) if isinstance(adj, dict) else None
        corrected_out = _parse_dt(adj.get("corrected_clock_out_at")) if isinstance(adj, dict) else None
        shifts.append(
            AttendanceShift(
                id=e.id,
                work_date=local_date.isoformat(),
                clock_in_at=e.clock_in_at,
                clock_out_at=e.clock_out_at,
                worked_hours=_minutes_to_hours(e.worked_minutes or 0) if not is_open else None,
                branch_name=branch_map.get(e.branch_id) if e.branch_id else None,
                source=e.source,
                scheduled_start=getattr(sched, "start_time", None),
                scheduled_end=getattr(sched, "end_time", None),
                pattern_start=pattern_start,
                pattern_end=pattern_end,
                is_open=is_open,
                reviewed=reviewed,
                reviewed_by_name=reviewer_name,
                reviewed_at=flags.get("reviewed_at"),
                flagged_for_review=bool(flags.get("flagged_for_review")),
                review_reason=flags.get("review_reason"),
                edited=adj is not None,
                edit_reason=adj.get("reason") if isinstance(adj, dict) else None,
                original_worked_hours=_minutes_to_hours(orig_worked) if isinstance(orig_worked, int) else None,
                corrected_clock_in_at=corrected_in,
                corrected_clock_out_at=corrected_out,
                is_manual=bool(flags.get("manual_entry")),
                is_manual_hours=bool(flags.get("manual_hours")),
                break_minutes=e.break_minutes or 0,
            )
        )

    # Expected hours for the range (scheduled overlap → fixed/roster fallback).
    sched_minutes = 0
    sched_rows = (
        await db.execute(
            select(ScheduleEntry).where(
                ScheduleEntry.org_id == org_id,
                ScheduleEntry.staff_id == staff_id,
                ScheduleEntry.status != "cancelled",
                ScheduleEntry.entry_type.notin_(["leave", "break"]),
                ScheduleEntry.start_time < end_dt,
                ScheduleEntry.end_time > start_dt,
            )
        )
    ).scalars().all()
    for se in sched_rows:
        clamped = int(
            (min(se.end_time, end_dt) - max(se.start_time, start_dt)).total_seconds() // 60
        )
        if clamped > 0:
            sched_minutes += clamped
    if sched_minutes > 0:
        expected = sched_minutes
        source = "scheduled"
    else:
        roster = compute_fixed_rostered_minutes(
            getattr(staff, "availability_schedule", None), start_date, end_date,
        )
        if roster > 0:
            expected = roster
            source = "fixed" if getattr(staff, "working_arrangement", None) == "fixed" else "roster"
        else:
            expected = 0
            source = "none"

    return AttendanceDetailResponse(
        staff_id=staff_id,
        staff_name=staff_name,
        position=getattr(staff, "position", None),
        working_arrangement=getattr(staff, "working_arrangement", None),
        date_from=start_date.isoformat(),
        date_to=end_date.isoformat(),
        worked_hours=_minutes_to_hours(worked),
        expected_hours=_minutes_to_hours(expected) if source != "none" else None,
        expected_source=source,
        variance_hours=_minutes_to_hours(worked - expected) if source != "none" else None,
        shifts=shifts,
        pending_review_count=pending_review_count,
        reviewed_count=reviewed_count,
    )


async def set_shift_review(
    db: AsyncSession,
    *,
    org_id: UUID,
    entry_id: UUID,
    reviewed: bool,
    actor_id: UUID,
    branch_ids: list[UUID] | None = None,
):
    """Sign off (or un-sign) a single clock shift for payroll.

    Writes ``reviewed`` / ``reviewed_by`` / ``reviewed_at`` onto the entry's
    ``flags`` JSONB. Returns the updated entry. Raises ValueError when the
    shift is missing, out of branch scope, or still open (not clocked out).
    """
    from app.modules.auth.models import User
    from app.modules.time_clock.models import TimeClockEntry

    entry = (
        await db.execute(
            select(TimeClockEntry).where(
                TimeClockEntry.id == entry_id,
                TimeClockEntry.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise ValueError("shift_not_found")
    if branch_ids is not None and entry.branch_id not in branch_ids:
        raise ValueError("branch_access_denied")
    if entry.clock_out_at is None:
        raise ValueError("shift_still_open")

    flags = dict(entry.flags or {})
    before = bool(flags.get("reviewed"))
    if reviewed:
        flags["reviewed"] = True
        flags["reviewed_by"] = str(actor_id)
        flags["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    else:
        flags.pop("reviewed", None)
        flags.pop("reviewed_by", None)
        flags.pop("reviewed_at", None)
    entry.flags = flags
    flag_modified(entry, "flags")
    await db.flush()
    await db.refresh(entry)

    await write_audit_log(
        db,
        action="timesheet.shift_reviewed" if reviewed else "timesheet.shift_unreviewed",
        entity_type="time_clock_entry",
        org_id=org_id,
        user_id=actor_id,
        entity_id=entry.id,
        before_value={"reviewed": before},
        after_value={"reviewed": reviewed},
    )

    reviewer_name = None
    if reviewed:
        reviewer = await db.get(User, actor_id)
        reviewer_name = (
            getattr(reviewer, "full_name", None) or getattr(reviewer, "email", None)
        ) if reviewer else None
    return entry, reviewer_name


async def review_all_shifts(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    start_date=None,
    end_date=None,
    actor_id: UUID,
    branch_ids: list[UUID] | None = None,
) -> dict:
    """Sign off every completed (clocked-out) shift for a staff member in range.

    Returns ``{"affected_count": N, "pending_review_count": M}``. Already-reviewed
    and still-open shifts are skipped.
    """
    from sqlalchemy import text as _sql_text

    from app.modules.time_clock.models import TimeClockEntry

    tz_row = (
        await db.execute(
            _sql_text("SELECT timezone FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
    ).first()
    _, _, _, start_dt, end_dt = _org_local_window(
        tz_row[0] if tz_row else None, start_date, end_date
    )

    if branch_ids is not None and not branch_ids:
        return {"affected_count": 0, "pending_review_count": 0}

    q = select(TimeClockEntry).where(
        TimeClockEntry.org_id == org_id,
        TimeClockEntry.staff_id == staff_id,
        TimeClockEntry.clock_in_at >= start_dt,
        TimeClockEntry.clock_in_at < end_dt,
        TimeClockEntry.clock_out_at.isnot(None),
    )
    if branch_ids is not None:
        q = q.where(TimeClockEntry.branch_id.in_(branch_ids))
    entries = (await db.execute(q)).scalars().all()

    now_iso = datetime.now(timezone.utc).isoformat()
    affected = 0
    pending = 0
    for e in entries:
        flags = dict(e.flags or {})
        if flags.get("reviewed"):
            continue
        flags["reviewed"] = True
        flags["reviewed_by"] = str(actor_id)
        flags["reviewed_at"] = now_iso
        e.flags = flags
        flag_modified(e, "flags")
        affected += 1

    if affected > 0:
        await db.flush()
        await write_audit_log(
            db,
            action="timesheet.shifts_reviewed_bulk",
            entity_type="staff_member",
            org_id=org_id,
            user_id=actor_id,
            entity_id=staff_id,
            before_value={},
            after_value={"affected_count": affected},
        )

    return {"affected_count": affected, "pending_review_count": pending}


# ---------------------------------------------------------------------------
# Day-level corrections (per-shift edit / manual add) + timesheet recompute.
#
# Adjustment is symmetric with approval: it happens at the shift (day) level on
# the Attendance tab, not as a blunt whole-period override. Clock-based staff
# correct clock times (worked recomputed); fixed/casual staff get a direct
# "set hours" override or an admin-added day. Every change preserves the
# original on ``flags.adjustment``, is audited, resets the shift's review
# sign-off, and triggers a recompute of any covering (non-locked) timesheet so
# the corrected hours flow to payroll. Locked pay periods are immutable.
# ---------------------------------------------------------------------------


async def _org_zoneinfo(db: AsyncSession, org_id: UUID):
    from zoneinfo import ZoneInfo
    from sqlalchemy import text as _sql_text

    row = (
        await db.execute(
            _sql_text("SELECT timezone FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
    ).first()
    name = (row[0] if row else None) or "Pacific/Auckland"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


async def _is_locked_for(db: AsyncSession, org_id: UUID, staff_id: UUID, work_date) -> bool:
    """True when a LOCKED timesheet for this staff covers ``work_date``."""
    from app.modules.payslips.models import PayPeriod

    row = (
        await db.execute(
            select(Timesheet.id)
            .join(PayPeriod, PayPeriod.id == Timesheet.pay_period_id)
            .where(
                Timesheet.org_id == org_id,
                Timesheet.staff_id == staff_id,
                Timesheet.status == "locked",
                PayPeriod.start_date <= work_date,
                PayPeriod.end_date >= work_date,
            )
        )
    ).first()
    return row is not None


async def recompute_timesheets_for_staff_date(
    db: AsyncSession, *, org_id: UUID, staff_id: UUID, work_date
) -> None:
    """Re-derive actual/ordinary minutes for any non-locked timesheet whose pay
    period covers ``work_date``.

    Source of truth:
      * clock-based staff → sum of ``TimeClockEntry.worked_minutes`` in period;
      * fixed staff → per-day schedule, with admin ``manual_hours`` entries
        overriding that specific day.
    Overtime / public-holiday minutes are preserved; ordinary is the remainder.
    """
    from datetime import timedelta

    from app.modules.payslips.models import PayPeriod
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry

    staff = await db.get(StaffMember, staff_id)
    is_fixed = getattr(staff, "working_arrangement", None) == "fixed"
    avail = getattr(staff, "availability_schedule", None)
    tz = await _org_zoneinfo(db, org_id)

    periods = (
        await db.execute(
            select(PayPeriod).where(
                PayPeriod.org_id == org_id,
                PayPeriod.start_date <= work_date,
                PayPeriod.end_date >= work_date,
            )
        )
    ).scalars().all()

    touched = False
    for period in periods:
        ts = (
            await db.execute(
                select(Timesheet).where(
                    Timesheet.org_id == org_id,
                    Timesheet.staff_id == staff_id,
                    Timesheet.pay_period_id == period.id,
                )
            )
        ).scalar_one_or_none()
        if ts is None or ts.status == "locked":
            continue

        entries = (
            await db.execute(
                select(TimeClockEntry).where(
                    TimeClockEntry.org_id == org_id,
                    TimeClockEntry.staff_id == staff_id,
                    TimeClockEntry.clock_in_at >= period.start_date,
                    TimeClockEntry.clock_in_at < period.end_date + timedelta(days=1),
                )
            )
        ).scalars().all()

        if is_fixed:
            manual_by_date: dict = {}
            for e in entries:
                ef = e.flags or {}
                if ef.get("manual_hours") and not ef.get("voided"):
                    d = e.clock_in_at.astimezone(tz).date()
                    manual_by_date[d] = manual_by_date.get(d, 0) + (e.worked_minutes or 0)
            total = 0
            cursor = period.start_date
            while cursor <= period.end_date:
                if cursor in manual_by_date:
                    total += manual_by_date[cursor]
                else:
                    total += compute_fixed_rostered_minutes(avail, cursor, cursor)
                cursor += timedelta(days=1)
            actual = total
        else:
            actual = sum(
                (e.worked_minutes or 0)
                for e in entries
                if e.clock_out_at is not None and not (e.flags or {}).get("voided")
            )

        ts.actual_minutes = actual
        ts.ordinary_minutes = max(
            0, actual - (ts.overtime_minutes or 0) - (ts.public_holiday_minutes or 0)
        )
        ts.updated_at = datetime.now(timezone.utc)
        touched = True

    if touched:
        await db.flush()


async def edit_shift(
    db: AsyncSession,
    *,
    org_id: UUID,
    entry_id: UUID,
    reason: str,
    actor_id: UUID,
    clock_in_at=None,
    clock_out_at=None,
    break_minutes: int | None = None,
    worked_minutes: int | None = None,
    branch_ids: list[UUID] | None = None,
):
    """Correct a single shift's effective hours.

    The raw clock punch (``clock_in_at`` / ``clock_out_at``) is **immutable
    evidence** (enforced by a DB trigger), so corrections are stored as an
    overlay: the corrected effective times live on ``flags.adjustment`` and the
    computed/overridden ``worked_minutes`` is updated. Provide corrected clock
    times (worked is recomputed from them) OR a direct ``worked_minutes``
    override. Preserves the original, audits, resets the review sign-off, and
    recomputes covering timesheets."""
    from app.modules.time_clock.models import TimeClockEntry

    entry = (
        await db.execute(
            select(TimeClockEntry).where(
                TimeClockEntry.id == entry_id,
                TimeClockEntry.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise ValueError("shift_not_found")
    if branch_ids is not None and entry.branch_id not in branch_ids:
        raise ValueError("branch_access_denied")
    if entry.clock_out_at is None:
        # Open shifts have no settled duration to correct yet.
        raise ValueError("shift_still_open")

    tz = await _org_zoneinfo(db, org_id)
    old_date = entry.clock_in_at.astimezone(tz).date()
    if await _is_locked_for(db, org_id, entry.staff_id, old_date):
        raise ValueError("shift_locked")

    flags = dict(entry.flags or {})
    if not isinstance(flags.get("adjustment"), dict):
        flags["adjustment"] = {
            "original": {
                "clock_in_at": entry.clock_in_at.isoformat() if entry.clock_in_at else None,
                "clock_out_at": entry.clock_out_at.isoformat() if entry.clock_out_at else None,
                "break_minutes": entry.break_minutes,
                "worked_minutes": entry.worked_minutes,
            }
        }

    before_worked = entry.worked_minutes
    adj = flags["adjustment"]

    if worked_minutes is not None:
        # Direct hours override (fixed/casual). Raw punch untouched.
        if break_minutes is not None:
            entry.break_minutes = break_minutes
        entry.worked_minutes = worked_minutes
        adj["mode"] = "hours"
        adj.pop("corrected_clock_in_at", None)
        adj.pop("corrected_clock_out_at", None)
    else:
        # Time correction (clock staff): compute worked from the corrected
        # times, store them as an overlay (NOT on the immutable columns).
        if clock_in_at is None or clock_out_at is None:
            raise ValueError("times_required")
        if clock_out_at <= clock_in_at:
            raise ValueError("invalid_times")
        bm = break_minutes if break_minutes is not None else (entry.break_minutes or 0)
        worked = int((clock_out_at - clock_in_at).total_seconds() // 60) - bm
        if worked < 0:
            raise ValueError("break_exceeds_shift")
        entry.break_minutes = bm
        entry.worked_minutes = worked
        adj["mode"] = "times"
        adj["corrected_clock_in_at"] = clock_in_at.isoformat()
        adj["corrected_clock_out_at"] = clock_out_at.isoformat()

    adj["by"] = str(actor_id)
    adj["at"] = datetime.now(timezone.utc).isoformat()
    adj["reason"] = reason
    flags["adjustment"] = adj
    for k in ("reviewed", "reviewed_by", "reviewed_at"):
        flags.pop(k, None)
    entry.flags = flags
    flag_modified(entry, "flags")
    await db.flush()
    await db.refresh(entry)

    await write_audit_log(
        db,
        action="timesheet.shift_edited",
        entity_type="time_clock_entry",
        org_id=org_id,
        user_id=actor_id,
        entity_id=entry.id,
        before_value={"worked_minutes": before_worked},
        after_value={"worked_minutes": entry.worked_minutes, "reason": reason},
    )

    await recompute_timesheets_for_staff_date(
        db, org_id=org_id, staff_id=entry.staff_id, work_date=old_date
    )
    return entry


async def add_manual_shift(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    work_date,
    reason: str,
    actor_id: UUID,
    clock_in_at=None,
    clock_out_at=None,
    break_minutes: int = 0,
    worked_minutes: int | None = None,
    branch_id: UUID | None = None,
    branch_ids: list[UUID] | None = None,
):
    """Add a worked day for a staff member who didn't clock (fixed/casual).
    Provide clock times OR a direct ``worked_minutes`` hours value."""
    from datetime import time, timedelta

    from app.modules.organisations.models import Branch
    from app.modules.staff.models import StaffMember
    from app.modules.time_clock.models import TimeClockEntry

    staff = await db.get(StaffMember, staff_id)
    if staff is None or staff.org_id != org_id:
        raise ValueError("staff_not_found")

    # Resolve a branch (new time_clock_entries rows require branch_id).
    if branch_id is None:
        branch = (
            await db.execute(
                select(Branch).where(Branch.org_id == org_id, Branch.is_default == True)  # noqa: E712
            )
        ).scalars().first()
        if branch is None:
            branch = (
                await db.execute(select(Branch).where(Branch.org_id == org_id))
            ).scalars().first()
        branch_id = branch.id if branch else None
    if branch_id is None:
        raise ValueError("no_branch")
    if branch_ids is not None and branch_id not in branch_ids:
        raise ValueError("branch_access_denied")
    if await _is_locked_for(db, org_id, staff_id, work_date):
        raise ValueError("shift_locked")

    tz = await _org_zoneinfo(db, org_id)
    manual_hours = worked_minutes is not None
    if manual_hours:
        ci = datetime.combine(work_date, time(9, 0), tzinfo=tz).astimezone(timezone.utc)
        co = ci + timedelta(minutes=worked_minutes + (break_minutes or 0))
        worked = worked_minutes
    else:
        if clock_in_at is None or clock_out_at is None:
            raise ValueError("times_required")
        if clock_out_at <= clock_in_at:
            raise ValueError("invalid_times")
        bm = break_minutes or 0
        worked = int((clock_out_at - clock_in_at).total_seconds() // 60) - bm
        if worked < 0:
            raise ValueError("break_exceeds_shift")
        ci, co = clock_in_at, clock_out_at

    now_iso = datetime.now(timezone.utc).isoformat()
    new_flags: dict = {
        "manual_entry": True,
        "adjustment": {"by": str(actor_id), "at": now_iso, "reason": reason},
    }
    if manual_hours:
        new_flags["manual_hours"] = True

    entry = TimeClockEntry(
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=ci,
        clock_out_at=co,
        source="admin_manual",
        break_minutes=break_minutes or 0,
        worked_minutes=worked,
        branch_id=branch_id,
        created_by=actor_id,
        flags=new_flags,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)

    await write_audit_log(
        db,
        action="timesheet.shift_added",
        entity_type="time_clock_entry",
        org_id=org_id,
        user_id=actor_id,
        entity_id=entry.id,
        before_value={},
        after_value={
            "work_date": work_date.isoformat(),
            "worked_minutes": worked,
            "manual_hours": manual_hours,
            "reason": reason,
        },
    )

    await recompute_timesheets_for_staff_date(
        db, org_id=org_id, staff_id=staff_id, work_date=work_date
    )
    return entry


async def void_manual_shift(
    db: AsyncSession,
    *,
    org_id: UUID,
    entry_id: UUID,
    actor_id: UUID,
    branch_ids: list[UUID] | None = None,
):
    """Remove an admin-added manual shift.

    ``time_clock_entries`` rows cannot be deleted (DB trigger), so removal is a
    soft-void: the row is flagged ``voided`` and its ``worked_minutes`` zeroed
    so it no longer counts. Only admin-added manual entries can be voided —
    never a real clock punch."""
    from app.modules.time_clock.models import TimeClockEntry

    entry = (
        await db.execute(
            select(TimeClockEntry).where(
                TimeClockEntry.id == entry_id,
                TimeClockEntry.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise ValueError("shift_not_found")
    if not (entry.flags or {}).get("manual_entry"):
        raise ValueError("not_manual")
    if branch_ids is not None and entry.branch_id not in branch_ids:
        raise ValueError("branch_access_denied")

    tz = await _org_zoneinfo(db, org_id)
    work_date = entry.clock_in_at.astimezone(tz).date()
    if await _is_locked_for(db, org_id, entry.staff_id, work_date):
        raise ValueError("shift_locked")

    staff_id = entry.staff_id
    flags = dict(entry.flags or {})
    flags["voided"] = True
    flags["voided_by"] = str(actor_id)
    flags["voided_at"] = datetime.now(timezone.utc).isoformat()
    for k in ("reviewed", "reviewed_by", "reviewed_at"):
        flags.pop(k, None)
    entry.flags = flags
    entry.worked_minutes = 0
    flag_modified(entry, "flags")
    await db.flush()

    await write_audit_log(
        db,
        action="timesheet.shift_voided",
        entity_type="time_clock_entry",
        org_id=org_id,
        user_id=actor_id,
        entity_id=entry_id,
        before_value={"work_date": work_date.isoformat()},
        after_value={"voided": True},
    )

    await recompute_timesheets_for_staff_date(
        db, org_id=org_id, staff_id=staff_id, work_date=work_date
    )
