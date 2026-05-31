"""Timesheet approval service: week-totals computation, lock check, TOIL accrual.

Implements task B5 from `.kiro/specs/staff-management-p3`. Public surface:

  - :func:`compute_week_totals` — aggregates ``time_clock_entries`` +
    ``break_records`` + ``schedule_entries`` × public holidays for a
    staff/week pair. Splits ``total_worked_minutes`` into
    ``ordinary_minutes`` + ``total_overtime_minutes`` using the org's
    ``overtime_policy`` daily + weekly thresholds (G1). Appends
    ``unapproved_overtime: {minutes}min — no overtime_request was approved``
    to the resulting notes when ``require_pre_approval=true`` and there's
    overtime not covered by an approved ``overtime_requests`` row (G1.5).
    Returns a dict ready for upsert into ``timesheet_approvals``.
  - :func:`approve_week` — upserts ``timesheet_approvals`` with
    ``status='approved'``; when the org's ``overtime_handling`` is
    ``'toil'`` or ``'employee_chooses'`` (with ``toil_choice='toil'``)
    AND the week has positive ``total_overtime_minutes``, grants the
    overtime to the staff's ``toil`` leave balance via a
    ``leave_ledger`` row ``reason='toil_accrual'`` (R11.1, X3 fix —
    the enum value is forward-pre-included in Phase 2's
    ``leave_ledger.reason`` CHECK).
    **The org's ``overtime_handling`` is read directly via the typed
    column on ``organisations`` (P3-N4)** — NOT via
    ``get_org_settings()``. The model does not yet declare
    ``overtime_handling`` as a typed field, so we fall back to a raw
    SQL select on the column.
  - :func:`reopen_week` — sets ``status='edited_after_approval'`` so
    the manual-edit flow's ``lock_check`` returns ``False`` again.
    Writes audit ``timesheet.reopened``.
  - :func:`recompute_after_edit` — convenience helper for the manual
    edit flow (R9.5 / G16). Re-runs ``compute_week_totals``, updates
    the row's totals + flips ``status`` to ``'edited_after_approval'``
    when it was previously ``'approved'``. Writes audit
    ``timesheet.recomputed_after_edit``.
  - :func:`lock_check` — re-exports the read-only gate from
    :mod:`app.modules.time_clock.service` so callers don't have to
    cross-import. Scope: only ``time_clock_entries`` are locked
    (G7) — the existing ``time_tracking_v2`` billable timer is not
    touched by approval.

**G7 — `time_entries` table is NOT touched by approval.** The existing
``time_tracking_v2`` module owns its own ``is_invoiced`` lock at
``app/modules/time_tracking_v2/service.py:172-184``. Phase 3 does not
add a second lock against that table. ``approve_week`` writes only to
``timesheet_approvals`` (and conditionally ``leave_ledger`` /
``leave_balances`` on TOIL accrual).

Project conventions (project-overview.md):
  - All write paths use ``await db.flush()`` then
    ``await db.refresh(obj)`` (P1-N15) — never ``commit()`` because
    ``get_db_session`` runs the transaction with ``session.begin()``.
  - Audit rows go through :func:`app.core.audit.write_audit_log`
    against the ``audit_log`` table (P3-N2: singular).

**Validates: Requirements R9, R10, R11 — Staff Management Phase 3 task B5**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.leave.models import LeaveBalance, LeaveLedger, LeaveType
from app.modules.time_clock.models import (
    OvertimeRequest,
    TimeClockEntry,
    TimesheetApproval,
)
from app.modules.time_clock.service import (
    LockedWeekError,
    TimeClockServiceError,
    lock_check as _service_lock_check,
)


logger = logging.getLogger(__name__)


__all__ = [
    "TimesheetApprovalNotFoundError",
    "ToilChoiceRequiredError",
    "InvalidToilChoiceError",
    "compute_week_totals",
    "approve_week",
    "reopen_week",
    "recompute_after_edit",
    "lock_check",
    "LockedWeekError",
]


# ---------------------------------------------------------------------------
# Service-layer exceptions
# ---------------------------------------------------------------------------


class TimesheetApprovalNotFoundError(TimeClockServiceError):
    """Raised by :func:`reopen_week` when no approval row exists for
    the staff/week pair. Router maps to HTTP 404.
    """


class ToilChoiceRequiredError(TimeClockServiceError):
    """Raised by :func:`approve_week` when the org's
    ``overtime_handling='employee_chooses'`` but the caller did not
    supply a ``toil_choice``. Router maps to HTTP 422 per R11.2.
    """


class InvalidToilChoiceError(TimeClockServiceError):
    """Raised by :func:`approve_week` when ``toil_choice`` is supplied
    with an invalid value (must be ``'pay_cash'`` or ``'toil'``).
    Router maps to HTTP 422.
    """


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# G1 — documented defaults, mirrored from migration 0207's JSONB block.
_DEFAULT_WEEKLY_THRESHOLD_MINUTES = 2400  # 40h
_DEFAULT_DAILY_THRESHOLD_MINUTES = 480  # 8h
_DEFAULT_REQUIRE_PRE_APPROVAL = False

# Phase 2 default — kept here as a defensive fallback if the column is
# somehow NULL (the CHECK enum + DEFAULT 'pay_cash' makes this nearly
# impossible, but the helper guards against it).
_DEFAULT_OVERTIME_HANDLING = "pay_cash"


# ---------------------------------------------------------------------------
# Public lock_check re-export (G7 scope — time_clock_entries only)
# ---------------------------------------------------------------------------


async def lock_check(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    when_dt: datetime | date,
) -> bool:
    """Return ``True`` when the staff/date falls inside an approved
    timesheet week (G7 — ``time_clock_entries`` only).

    Thin wrapper around :func:`app.modules.time_clock.service.lock_check`
    so callers in this module don't have to cross-import. The service
    helper is the single source of truth for the SQL query — keeping
    it there avoids drift between the manual-edit path and the
    approval router.
    """
    return await _service_lock_check(
        db, org_id=org_id, staff_id=staff_id, when_dt=when_dt,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _week_end(week_start: date) -> date:
    """Return the inclusive end of a 7-day week starting at
    ``week_start``. Phase 3 weeks are Monday→Sunday by NZ convention,
    but the helper is callable with any starting day; the only
    constraint is that the returned date is exactly 6 days after.
    """
    return week_start + timedelta(days=6)


def _entry_date(entry: TimeClockEntry) -> date:
    """Bucket an entry into a calendar day for the daily-overtime
    band-counting. Uses the UTC date of ``clock_in_at`` — this is the
    same convention used elsewhere in the time_clock module (see
    :func:`service.lock_check`). A future iteration could honour the
    org timezone here for the day-boundary; documented but out of
    scope for task B5.
    """
    when = entry.clock_in_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).date()


async def _load_overtime_policy(
    db: AsyncSession, org_id: uuid.UUID,
) -> dict[str, Any]:
    """Return the org's ``overtime_policy`` JSONB dict.

    Reads the column directly via SQL because the ``Organisation`` ORM
    model does not yet declare ``overtime_policy`` as a typed field
    (the migration adds the JSONB column but the ORM extension is out
    of scope for task B5). Falls back to the documented default block
    when the column is unset.
    """
    result = await db.execute(
        text(
            "SELECT overtime_policy FROM organisations WHERE id = :org_id"
        ),
        {"org_id": str(org_id)},
    )
    row = result.scalar_one_or_none()
    if row is None or not isinstance(row, dict):
        return {}
    return row


async def _load_overtime_handling(
    db: AsyncSession, org_id: uuid.UUID,
) -> str:
    """Return the org's ``overtime_handling`` typed column value
    (P3-N4 — typed text column, NOT a JSONB key).

    Reads the column directly via SQL because the ``Organisation`` ORM
    model does not yet declare ``overtime_handling`` as a typed field.
    The migration (Phase 2's ``0205_leave_schema``) adds the column
    with a CHECK enum + ``DEFAULT 'pay_cash'``, so the fallback here
    only triggers in pathological "row not found" cases (e.g. a
    just-deleted org).
    """
    result = await db.execute(
        text(
            "SELECT overtime_handling FROM organisations "
            "WHERE id = :org_id"
        ),
        {"org_id": str(org_id)},
    )
    row = result.scalar_one_or_none()
    if not row or not isinstance(row, str):
        return _DEFAULT_OVERTIME_HANDLING
    return row


async def _load_org_country_code(
    db: AsyncSession, org_id: uuid.UUID,
) -> str:
    """Return the org's ``country_code`` (default ``'NZ'`` when unset).

    Used to drive the public-holiday lookup. Phase 1 + Phase 2 follow
    the same NZ default — see :mod:`app.modules.leave.public_holidays`
    for the same fallback pattern.
    """
    result = await db.execute(
        text(
            "SELECT country_code FROM organisations WHERE id = :org_id"
        ),
        {"org_id": str(org_id)},
    )
    row = result.scalar_one_or_none()
    if not row:
        return "NZ"
    return str(row)


async def _load_week_entries(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    week_end: date,
) -> list[TimeClockEntry]:
    """Return all ``time_clock_entries`` whose ``clock_in_at`` falls
    inside ``[week_start, week_end + 1 day)`` for the given staff.

    Open entries (``clock_out_at IS NULL``) are included so a staff
    member who is mid-shift on Sunday evening still appears — but
    the totals computation skips entries with ``worked_minutes=NULL``
    (open shifts contribute zero).
    """
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(
        week_end + timedelta(days=1), time.min, tzinfo=timezone.utc,
    )
    stmt = (
        select(TimeClockEntry)
        .where(
            and_(
                TimeClockEntry.org_id == org_id,
                TimeClockEntry.staff_id == staff_id,
                TimeClockEntry.clock_in_at >= start_dt,
                TimeClockEntry.clock_in_at < end_dt,
            ),
        )
        .order_by(TimeClockEntry.clock_in_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_week_scheduled_minutes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    week_end: date,
) -> int:
    """Return the sum of scheduled minutes for the staff in the week.

    Iterates ``schedule_entries`` rows whose ``start_time`` falls in
    the week. Cancelled entries are excluded via the same
    ``status.in_(['scheduled', 'completed'])`` positive set used by
    :mod:`app.modules.time_clock.service` (P3-N7).
    """
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(
        week_end + timedelta(days=1), time.min, tzinfo=timezone.utc,
    )
    stmt = text(
        """
        SELECT COALESCE(
            SUM(EXTRACT(EPOCH FROM (end_time - start_time)) / 60), 0
        )::int AS minutes
        FROM schedule_entries
        WHERE org_id = :org_id
          AND staff_id = :staff_id
          AND start_time >= :start_dt
          AND start_time < :end_dt
          AND status IN ('scheduled', 'completed')
          AND entry_type IN ('job', 'booking', 'other')
        """
    )
    result = await db.execute(
        stmt,
        {
            "org_id": str(org_id),
            "staff_id": str(staff_id),
            "start_dt": start_dt,
            "end_dt": end_dt,
        },
    )
    minutes = result.scalar_one_or_none()
    return int(minutes or 0)


async def _load_public_holiday_dates(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    week_start: date,
    week_end: date,
) -> set[date]:
    """Return the set of public-holiday dates inside the week for the
    org's country_code. Falls back to an empty set when the
    public-holiday data is unavailable (e.g. Phase 2 migration not
    applied).

    Uses :func:`app.modules.leave.public_holidays.load_public_holidays_in_range`
    which is cached via Redis with a 1h TTL — so repeated calls in
    the same approval batch are cheap.
    """
    try:
        from app.modules.leave.public_holidays import (
            load_public_holidays_in_range,
        )

        country_code = await _load_org_country_code(db, org_id)
        holidays = await load_public_holidays_in_range(
            db,
            org_id,
            week_start,
            week_end,
            country_code=country_code,
        )
        return {h.holiday_date for h in holidays}
    except Exception:  # noqa: BLE001 — best-effort; fall through.
        logger.debug(
            "compute_week_totals: public-holiday lookup failed",
            exc_info=True,
        )
        return set()


async def _load_approved_overtime_minutes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    week_end: date,
) -> int:
    """Return the sum of ``proposed_extra_minutes`` from approved
    ``overtime_requests`` covering this week's shifts (G1.5).

    Phase 3 ties an overtime request to a specific
    ``schedule_entry_id`` (nullable). For coverage purposes:
      - requests with a ``schedule_entry_id`` count when that
        schedule entry's ``start_time`` falls in the week,
      - requests with no ``schedule_entry_id`` (free-form OT for the
        week) count when the request was created in or before the
        week's end date.
    """
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(
        week_end + timedelta(days=1), time.min, tzinfo=timezone.utc,
    )
    # Tied-to-schedule path.
    tied_stmt = text(
        """
        SELECT COALESCE(SUM(o.proposed_extra_minutes), 0)::int AS m
        FROM overtime_requests o
        JOIN schedule_entries s ON s.id = o.schedule_entry_id
        WHERE o.org_id = :org_id
          AND o.staff_id = :staff_id
          AND o.status = 'approved'
          AND s.start_time >= :start_dt
          AND s.start_time < :end_dt
        """
    )
    tied_minutes = (
        await db.execute(
            tied_stmt,
            {
                "org_id": str(org_id),
                "staff_id": str(staff_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
    ).scalar_one_or_none() or 0

    # Free-form path — approved requests with no schedule link, decided
    # on or before the week's end date.
    free_stmt = text(
        """
        SELECT COALESCE(SUM(o.proposed_extra_minutes), 0)::int AS m
        FROM overtime_requests o
        WHERE o.org_id = :org_id
          AND o.staff_id = :staff_id
          AND o.status = 'approved'
          AND o.schedule_entry_id IS NULL
          AND COALESCE(o.decided_at, o.created_at) >= :start_dt
          AND COALESCE(o.decided_at, o.created_at) < :end_dt
        """
    )
    free_minutes = (
        await db.execute(
            free_stmt,
            {
                "org_id": str(org_id),
                "staff_id": str(staff_id),
                "start_dt": start_dt,
                "end_dt": end_dt,
            },
        )
    ).scalar_one_or_none() or 0

    return int(tied_minutes) + int(free_minutes)


def _split_overtime(
    *,
    daily_minutes_by_day: dict[date, int],
    week_worked: int,
    daily_threshold: int,
    weekly_threshold: int,
) -> tuple[int, int]:
    """Split ``week_worked`` into ``(daily_overtime, weekly_overtime)``
    per the G1 / R6a.4 algorithm.

    Returns a 2-tuple ``(daily_ot, weekly_ot)``. The caller sums them
    for ``total_overtime_minutes``.
    """
    daily_ot = 0
    for _day, mins in daily_minutes_by_day.items():
        if mins > daily_threshold:
            daily_ot += mins - daily_threshold

    weekly_ot_candidate = max(0, week_worked - weekly_threshold)
    # Avoid double-count: if some of the weekly excess has already
    # been captured by the daily band, only the remainder counts.
    weekly_ot = max(0, weekly_ot_candidate - daily_ot)

    return daily_ot, weekly_ot


# ---------------------------------------------------------------------------
# Public API: compute_week_totals
# ---------------------------------------------------------------------------


async def compute_week_totals(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
) -> dict[str, Any]:
    """Aggregate a week's worth of clock + break + schedule data and
    return a dict ready for upsert into ``timesheet_approvals`` (G1).

    The returned dict has keys matching the ``timesheet_approvals``
    columns:
      - ``week_start``, ``week_end``,
      - ``total_worked_minutes``, ``total_scheduled_minutes``,
      - ``total_overtime_minutes``, ``total_break_minutes``,
      - ``ordinary_minutes``, ``public_holiday_minutes``,
      - ``notes`` (None or a string carrying the
        ``unapproved_overtime`` warning per G1.5).

    The split applies the org's ``overtime_policy``:
      1. ``daily_overtime`` = sum of ``max(0, day_worked - daily_threshold)``
         per day in the week.
      2. ``weekly_overtime`` = ``max(0, max(0, week_worked - weekly_threshold) - daily_overtime)``
         (the second ``max`` avoids double-counting per R6a.4).
      3. ``total_overtime = daily + weekly``.
      4. ``ordinary = week_worked - total_overtime - public_holiday``.

    G1.5 — when the org's ``require_pre_approval=true`` AND there's
    overtime not covered by approved ``overtime_requests``, the
    ``notes`` field carries
    ``"unapproved_overtime: {minutes}min — no overtime_request was approved"``
    so the approval-queue UI can render the warning chip.

    Note: ``worked_minutes`` on a closed entry is already net of
    ``break_minutes`` (set by
    :func:`app.modules.time_clock.service._compute_worked_minutes`).
    Open entries (no ``clock_out_at``) contribute zero — they're shown
    in the Hours tab but don't count toward approved totals until
    closed.
    """
    week_end = _week_end(week_start)

    entries = await _load_week_entries(
        db,
        org_id=org_id,
        staff_id=staff_id,
        week_start=week_start,
        week_end=week_end,
    )

    holiday_dates = await _load_public_holiday_dates(
        db, org_id=org_id, week_start=week_start, week_end=week_end,
    )

    # Per-day buckets — we need this for both the daily-OT band and
    # the public-holiday split.
    daily_minutes_by_day: dict[date, int] = {}
    week_worked = 0
    week_break_minutes = 0
    public_holiday_minutes = 0

    for entry in entries:
        if entry.worked_minutes is None:
            # Open entry — ignore for totals.
            continue
        bucket = _entry_date(entry)
        worked = int(entry.worked_minutes or 0)
        daily_minutes_by_day[bucket] = (
            daily_minutes_by_day.get(bucket, 0) + worked
        )
        week_worked += worked
        week_break_minutes += int(entry.break_minutes or 0)
        if bucket in holiday_dates:
            public_holiday_minutes += worked

    # G1 — apply daily + weekly thresholds with double-count guard.
    policy = await _load_overtime_policy(db, org_id)
    daily_threshold = int(
        policy.get(
            "daily_threshold_minutes", _DEFAULT_DAILY_THRESHOLD_MINUTES,
        )
    )
    weekly_threshold = int(
        policy.get(
            "weekly_threshold_minutes", _DEFAULT_WEEKLY_THRESHOLD_MINUTES,
        )
    )
    require_pre_approval = bool(
        policy.get("require_pre_approval", _DEFAULT_REQUIRE_PRE_APPROVAL)
    )

    daily_ot, weekly_ot = _split_overtime(
        daily_minutes_by_day=daily_minutes_by_day,
        week_worked=week_worked,
        daily_threshold=daily_threshold,
        weekly_threshold=weekly_threshold,
    )
    total_overtime_minutes = daily_ot + weekly_ot

    # Public-holiday minutes are ordinary-time pay-uplift territory in
    # Phase 4; we only carry the count here so payroll can see the
    # split. Subtract them from ordinary so the four buckets sum
    # correctly: ordinary + overtime + public_holiday == week_worked.
    ordinary_minutes = max(
        0, week_worked - total_overtime_minutes - public_holiday_minutes,
    )

    total_scheduled_minutes = await _load_week_scheduled_minutes(
        db,
        org_id=org_id,
        staff_id=staff_id,
        week_start=week_start,
        week_end=week_end,
    )

    # G1.5 — unapproved-overtime warning.
    notes: str | None = None
    if require_pre_approval and total_overtime_minutes > 0:
        approved_minutes = await _load_approved_overtime_minutes(
            db,
            org_id=org_id,
            staff_id=staff_id,
            week_start=week_start,
            week_end=week_end,
        )
        unapproved = max(0, total_overtime_minutes - approved_minutes)
        if unapproved > 0:
            notes = (
                f"unapproved_overtime: {unapproved}min — "
                "no overtime_request was approved"
            )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "total_worked_minutes": week_worked,
        "total_scheduled_minutes": total_scheduled_minutes,
        "total_overtime_minutes": total_overtime_minutes,
        "total_break_minutes": week_break_minutes,
        "ordinary_minutes": ordinary_minutes,
        "public_holiday_minutes": public_holiday_minutes,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Internal: load existing approval row (for upsert)
# ---------------------------------------------------------------------------


async def _load_approval(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
) -> TimesheetApproval | None:
    """Return the existing ``timesheet_approvals`` row for the
    staff/week pair (UNIQUE on ``(staff_id, week_start)``) or
    ``None``. Always scoped by ``org_id`` so cross-tenant lookups
    surface as a miss.
    """
    stmt = (
        select(TimesheetApproval)
        .where(
            and_(
                TimesheetApproval.org_id == org_id,
                TimesheetApproval.staff_id == staff_id,
                TimesheetApproval.week_start == week_start,
            ),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _approval_to_dict(approval: TimesheetApproval) -> dict[str, Any]:
    """Serialise a :class:`TimesheetApproval` for the audit log."""
    return {
        "id": str(approval.id),
        "staff_id": str(approval.staff_id),
        "week_start": approval.week_start.isoformat(),
        "week_end": approval.week_end.isoformat(),
        "status": approval.status,
        "total_worked_minutes": approval.total_worked_minutes,
        "total_scheduled_minutes": approval.total_scheduled_minutes,
        "total_overtime_minutes": approval.total_overtime_minutes,
        "total_break_minutes": approval.total_break_minutes,
        "ordinary_minutes": approval.ordinary_minutes,
        "public_holiday_minutes": approval.public_holiday_minutes,
        "toil_choice": approval.toil_choice,
        "approved_by": (
            str(approval.approved_by) if approval.approved_by else None
        ),
        "approved_at": (
            approval.approved_at.isoformat() if approval.approved_at else None
        ),
        "notes": approval.notes,
    }


# ---------------------------------------------------------------------------
# Internal: TOIL accrual
# ---------------------------------------------------------------------------


async def _grant_toil_accrual(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    overtime_minutes: int,
    week_end: date,
    user_id: uuid.UUID | None,
    ip_address: str | None,
) -> LeaveLedger | None:
    """Write a ``leave_ledger`` row ``reason='toil_accrual'`` granting
    the overtime hours to the staff's ``toil`` leave balance (R11.1).

    The ``toil`` leave_type_id is guaranteed to exist for every org
    per Phase 2 R10.1 (cross-phase X2). Returns ``None`` defensively
    when the type is missing — that should only happen on an org
    where the Phase 2 migration backfill has not yet run.

    Idempotency: keyed on
    ``(staff_id, leave_type_id, reason='toil_accrual', occurred_at=week_end)``
    — the same pattern as the public-holiday extension writer in
    :mod:`app.modules.leave.public_holidays`. Re-running approve_week
    on a week that already wrote a toil_accrual ledger row is a no-op.
    """
    if overtime_minutes <= 0:
        return None

    lt_stmt = select(LeaveType).where(
        LeaveType.org_id == org_id,
        LeaveType.code == "toil",
    )
    leave_type: LeaveType | None = (
        await db.execute(lt_stmt)
    ).scalar_one_or_none()
    if leave_type is None:
        logger.warning(
            "approvals._grant_toil_accrual: org=%s missing 'toil' "
            "leave type — TOIL accrual skipped",
            org_id,
        )
        return None

    # Idempotency guard.
    exists_stmt = (
        select(LeaveLedger.id)
        .where(
            and_(
                LeaveLedger.staff_id == staff_id,
                LeaveLedger.leave_type_id == leave_type.id,
                LeaveLedger.reason == "toil_accrual",
                LeaveLedger.occurred_at == week_end,
            ),
        )
        .limit(1)
    )
    if (
        await db.execute(exists_stmt)
    ).scalar_one_or_none() is not None:
        return None

    granted_hours = Decimal(overtime_minutes) / Decimal(60)

    ledger = LeaveLedger(
        org_id=org_id,
        staff_id=staff_id,
        leave_type_id=leave_type.id,
        delta_hours=granted_hours,
        reason="toil_accrual",
        request_id=None,
        occurred_at=week_end,
        created_by=user_id,
    )
    db.add(ledger)

    # Bump the matching balance row (Phase 2's R10.1 backfill ensures
    # one exists for every active staff × every statutory type).
    bal_stmt = select(LeaveBalance).where(
        and_(
            LeaveBalance.staff_id == staff_id,
            LeaveBalance.leave_type_id == leave_type.id,
        ),
    )
    balance: LeaveBalance | None = (
        await db.execute(bal_stmt)
    ).scalar_one_or_none()
    if balance is not None:
        balance.accrued_hours = (
            Decimal(balance.accrued_hours) + granted_hours
        )
        balance.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(ledger)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="toil.accrued",
        entity_type="leave_ledger",
        entity_id=ledger.id,
        after_value={
            "staff_id": str(staff_id),
            "leave_type_id": str(leave_type.id),
            "delta_hours": str(granted_hours),
            "occurred_at": week_end.isoformat(),
            "source": "timesheet_approval",
        },
        ip_address=ip_address,
    )
    return ledger


# ---------------------------------------------------------------------------
# Public API: approve_week
# ---------------------------------------------------------------------------


async def approve_week(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    approved_by: uuid.UUID,
    toil_choice: str | None = None,
    extra_notes: str | None = None,
    ip_address: str | None = None,
) -> TimesheetApproval:
    """Compute totals, upsert ``timesheet_approvals`` with
    ``status='approved'``, lock the week's ``time_clock_entries`` from
    further edit, and (when applicable) accrue TOIL.

    G7 — only ``time_clock_entries`` are locked. The ``time_entries``
    billable timer in ``time_tracking_v2`` is not touched by this
    flow.

    R11 — TOIL accrual:
      - When the org's ``overtime_handling='toil'`` AND the week has
        positive ``total_overtime_minutes`` → write a ``leave_ledger``
        row ``reason='toil_accrual'`` and bump the matching
        ``leave_balances.accrued_hours``. ``toil_choice`` is ignored
        in this mode (the choice is org-level, not per-week).
      - When the org's ``overtime_handling='employee_chooses'`` →
        ``toil_choice`` is REQUIRED (R11.2). The caller passes
        ``'pay_cash'`` or ``'toil'``. When ``'toil'`` → accrue as
        above; when ``'pay_cash'`` → don't accrue (Phase 4 payslip
        will pay the hours).
      - When the org's ``overtime_handling='pay_cash'`` →
        ``toil_choice`` is ignored; nothing is written to the leave
        ledger (R11.3 — Phase 4 picks up ``total_overtime_minutes``
        from the approval row).

    Args:
      org_id: tenant org.
      staff_id: subject staff member.
      week_start: Monday of the approved week.
      approved_by: ``users.id`` of the manager clicking Approve.
      toil_choice: only meaningful when org's
        ``overtime_handling='employee_chooses'``. Must be
        ``'pay_cash'`` or ``'toil'``.
      extra_notes: optional admin-supplied note carried into the
        approval row's ``notes`` column. Concatenated after any
        ``unapproved_overtime`` G1.5 warning.

    Returns:
      The freshly-upserted :class:`TimesheetApproval` row.

    Raises:
      :class:`ToilChoiceRequiredError`: when org policy is
        ``employee_chooses`` and ``toil_choice`` is ``None``.
      :class:`InvalidToilChoiceError`: when ``toil_choice`` is set to
        anything other than ``'pay_cash'`` / ``'toil'``.
    """
    overtime_handling = await _load_overtime_handling(db, org_id)

    if toil_choice is not None and toil_choice not in ("pay_cash", "toil"):
        raise InvalidToilChoiceError(
            f"invalid_toil_choice: {toil_choice!r}"
        )
    if overtime_handling == "employee_chooses" and toil_choice is None:
        raise ToilChoiceRequiredError("toil_choice_required")

    totals = await compute_week_totals(
        db, org_id=org_id, staff_id=staff_id, week_start=week_start,
    )

    notes = totals["notes"]
    if extra_notes:
        notes = (
            f"{notes}\n{extra_notes}" if notes else extra_notes
        )

    approval = await _load_approval(
        db, org_id=org_id, staff_id=staff_id, week_start=week_start,
    )
    before_value: dict[str, Any] | None = None
    now = datetime.now(timezone.utc)

    if approval is None:
        approval = TimesheetApproval(
            org_id=org_id,
            staff_id=staff_id,
            week_start=totals["week_start"],
            week_end=totals["week_end"],
            status="approved",
            total_worked_minutes=totals["total_worked_minutes"],
            total_scheduled_minutes=totals["total_scheduled_minutes"],
            total_overtime_minutes=totals["total_overtime_minutes"],
            total_break_minutes=totals["total_break_minutes"],
            ordinary_minutes=totals["ordinary_minutes"],
            public_holiday_minutes=totals["public_holiday_minutes"],
            toil_choice=toil_choice,
            approved_by=approved_by,
            approved_at=now,
            notes=notes,
        )
        db.add(approval)
    else:
        before_value = _approval_to_dict(approval)
        approval.week_end = totals["week_end"]
        approval.status = "approved"
        approval.total_worked_minutes = totals["total_worked_minutes"]
        approval.total_scheduled_minutes = totals["total_scheduled_minutes"]
        approval.total_overtime_minutes = totals["total_overtime_minutes"]
        approval.total_break_minutes = totals["total_break_minutes"]
        approval.ordinary_minutes = totals["ordinary_minutes"]
        approval.public_holiday_minutes = totals["public_holiday_minutes"]
        approval.toil_choice = toil_choice
        approval.approved_by = approved_by
        approval.approved_at = now
        approval.notes = notes

    await db.flush()
    await db.refresh(approval)

    # R11 — TOIL accrual decision.
    should_accrue_toil = (
        overtime_handling == "toil"
        or (
            overtime_handling == "employee_chooses"
            and toil_choice == "toil"
        )
    )
    if should_accrue_toil and approval.total_overtime_minutes > 0:
        await _grant_toil_accrual(
            db,
            org_id=org_id,
            staff_id=staff_id,
            overtime_minutes=approval.total_overtime_minutes,
            week_end=approval.week_end,
            user_id=approved_by,
            ip_address=ip_address,
        )

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=approved_by,
        action="timesheet.approved",
        entity_type="timesheet_approval",
        entity_id=approval.id,
        before_value=before_value,
        after_value=_approval_to_dict(approval),
        ip_address=ip_address,
    )
    return approval


# ---------------------------------------------------------------------------
# Public API: reopen_week
# ---------------------------------------------------------------------------


async def reopen_week(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TimesheetApproval:
    """Set ``timesheet_approvals.status='edited_after_approval'`` so
    ``lock_check`` returns ``False`` and the manual-edit flow is
    unblocked (R9.4).

    Note: per the G16 state machine, ``edited_after_approval`` is the
    "reopened" state; the row is no longer ``'approved'`` so
    :func:`lock_check` (which only matches ``status='approved'``)
    returns ``False``.

    Raises:
      :class:`TimesheetApprovalNotFoundError`: when no approval row
        exists for the staff/week pair.
    """
    approval = await _load_approval(
        db, org_id=org_id, staff_id=staff_id, week_start=week_start,
    )
    if approval is None:
        raise TimesheetApprovalNotFoundError("timesheet_approval_not_found")

    before = _approval_to_dict(approval)
    approval.status = "edited_after_approval"
    await db.flush()
    await db.refresh(approval)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="timesheet.reopened",
        entity_type="timesheet_approval",
        entity_id=approval.id,
        before_value=before,
        after_value=_approval_to_dict(approval),
        ip_address=ip_address,
    )
    return approval


# ---------------------------------------------------------------------------
# Public API: recompute_after_edit (R9.5 / G16)
# ---------------------------------------------------------------------------


async def recompute_after_edit(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TimesheetApproval | None:
    """Re-run :func:`compute_week_totals` and update the
    ``timesheet_approvals`` row when one exists (R9.5 / G16).

    Called by the manual-edit flow on any ``time_clock_entries``
    write that lands inside an approval window. When the edit hits a
    week that has an approval row in any state:
      - ``'approved'`` → flips to ``'edited_after_approval'`` and
        re-computes totals (G16).
      - ``'edited_after_approval'`` → re-computes totals (status
        stays the same).
      - ``'pending'`` / ``'rejected'`` → re-computes totals (status
        stays the same).

    Returns ``None`` when no approval row exists (the edit was on a
    week that's never been approved — no-op).
    """
    approval = await _load_approval(
        db, org_id=org_id, staff_id=staff_id, week_start=week_start,
    )
    if approval is None:
        return None

    before = _approval_to_dict(approval)
    totals = await compute_week_totals(
        db, org_id=org_id, staff_id=staff_id, week_start=week_start,
    )

    # G16 — flip the status when the row was previously approved.
    if approval.status == "approved":
        approval.status = "edited_after_approval"

    approval.week_end = totals["week_end"]
    approval.total_worked_minutes = totals["total_worked_minutes"]
    approval.total_scheduled_minutes = totals["total_scheduled_minutes"]
    approval.total_overtime_minutes = totals["total_overtime_minutes"]
    approval.total_break_minutes = totals["total_break_minutes"]
    approval.ordinary_minutes = totals["ordinary_minutes"]
    approval.public_holiday_minutes = totals["public_holiday_minutes"]
    # Refresh notes — preserve any extra admin-typed notes is out of
    # scope here; the recompute is driven by an underlying entry edit
    # so the regenerated G1.5 warning is the right answer.
    approval.notes = totals["notes"]

    await db.flush()
    await db.refresh(approval)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="timesheet.recomputed_after_edit",
        entity_type="timesheet_approval",
        entity_id=approval.id,
        before_value=before,
        after_value=_approval_to_dict(approval),
        ip_address=ip_address,
    )
    return approval
