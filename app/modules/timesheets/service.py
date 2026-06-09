"""Staff timesheets service — CRUD, status transitions, lazy creation, bulk actions.

Transaction discipline: uses flush() + refresh() only. The session.begin()
context manager in get_db_session handles commit/rollback.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


async def materialise_missing_timesheets(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
) -> MaterialisationResult:
    """Sweep to create missing timesheets before pay-run cutoff.

    Queries staff with ScheduleEntry or approved LeaveRequest in the period
    but no Timesheet row. Creates Timesheet rows for them.
    Staff with NO clock, NO leave, NO schedule are flagged as no_activity
    (no row created).

    Placeholder implementation — the full query joining schedule_entries
    and leave_requests will be refined during integration testing.
    For now, creates timesheets for any staff with existing clock entries
    in the period who lack a timesheet.
    """
    from app.modules.time_clock.models import TimeClockEntry
    from app.modules.payslips.models import PayPeriod

    # Get the pay period boundaries
    period_result = await db.execute(
        select(PayPeriod).where(PayPeriod.id == pay_period_id)
    )
    period = period_result.scalar_one_or_none()
    if not period:
        return MaterialisationResult()

    # Find staff with clock entries in this period who lack a timesheet
    from sqlalchemy import and_, not_, exists

    # Staff IDs that already have a timesheet for this period
    has_timesheet = select(Timesheet.staff_id).where(
        Timesheet.pay_period_id == pay_period_id,
        Timesheet.org_id == org_id,
    )

    # Staff IDs with clock entries in this period
    staff_with_clocks = await db.execute(
        select(TimeClockEntry.staff_id).where(
            TimeClockEntry.org_id == org_id,
            TimeClockEntry.clock_in_at >= period.start_date,
            TimeClockEntry.clock_in_at < period.end_date,
            TimeClockEntry.staff_id.not_in(has_timesheet),
        ).distinct()
    )
    missing_staff_ids = [row[0] for row in staff_with_clocks.all()]

    result = MaterialisationResult()

    for staff_id in missing_staff_ids:
        timesheet = Timesheet(
            org_id=org_id,
            staff_id=staff_id,
            pay_period_id=pay_period_id,
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
