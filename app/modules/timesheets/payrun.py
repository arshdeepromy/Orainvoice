"""Pay Run service — lock-to-payslip integration.

When timesheets transition to 'locked', this service:
1. Freezes hour bands on the timesheet.
2. Generates payslip drafts with hour band line items.
3. Populates timesheet.payslip_id for the locked timesheet.
4. Triggers leave accrual computation.

Phase B implementation per design § Phase B Architecture Notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.pay_cycles import TimesheetAdjustment


class PayRunScopingError(Exception):
    """Raised when a pay run cannot be scoped to a single pay cycle.

    The pay run derives its staff scope from the period's ``pay_cycle_id``
    (materialisation is cycle-scoped). A period that is missing or has a
    ``NULL`` ``pay_cycle_id`` cannot be scoped, so the run is refused (REQ 8.5).

    ``code`` is a machine-readable reason (``pay_period_missing_cycle``) the
    route maps to HTTP 422.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class PayRunSummary:
    """Summary of a pay run generation."""
    pay_period_id: UUID
    total_timesheets: int = 0
    payslips_generated: int = 0
    errors: list[dict] = field(default_factory=list)
    adjustments_included: int = 0
    # Staff skipped because their hours for this period aren't fully reviewed
    # (signed off) on the Attendance tab yet — each entry is
    # ``{"staff_id": str, "pending": int}``.
    skipped_pending_review: list[dict] = field(default_factory=list)


async def generate_payslip_draft(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    org_id: UUID,
    actor_id: UUID,
) -> UUID | None:
    """Generate (or refresh) a payslip draft from a locked timesheet.

    Returns the payslip_id. If a draft already exists for the staff/period
    it is recomputed with the latest math (so re-running a pay run refreshes
    drafts); a finalised payslip is left untouched.
    """
    from app.modules.payslips.models import Payslip

    if timesheet.status != "locked":
        return None

    # Resolve any existing payslip — via the timesheet link first, then by
    # the staff/period pair (the UNIQUE key).
    payslip = None
    if timesheet.payslip_id is not None:
        payslip = await db.get(Payslip, timesheet.payslip_id)
    if payslip is None:
        existing = await db.execute(
            select(Payslip).where(
                Payslip.staff_id == timesheet.staff_id,
                Payslip.pay_period_id == timesheet.pay_period_id,
            )
        )
        payslip = existing.scalar_one_or_none()

    if payslip is None:
        # Create draft payslip. Hours are seeded from the locked timesheet's
        # classified minutes; recompute_payslip (below) then derives the final
        # hour bands, rates, and money via the shared payslip math.
        payslip = Payslip(
            org_id=org_id,
            staff_id=timesheet.staff_id,
            pay_period_id=timesheet.pay_period_id,
            ordinary_hours=Decimal(str(timesheet.ordinary_minutes or 0)) / Decimal("60"),
            overtime_hours=Decimal(str(timesheet.overtime_minutes or 0)) / Decimal("60"),
            public_holiday_hours=Decimal(str(timesheet.public_holiday_minutes or 0)) / Decimal("60"),
            status="draft",
        )
        db.add(payslip)
        await db.flush()
        await db.refresh(payslip)

    # Link timesheet to payslip
    timesheet.payslip_id = payslip.id
    await db.flush()
    await db.refresh(timesheet)

    # Compute (or recompute) real wages on the draft: hours × rate, recurring
    # allowances, KiwiSaver, casual 8%, and the statutory PAYE / ACC /
    # student-loan deductions — via the shared payslip math. Finalised
    # payslips are immutable and skipped.
    if payslip.status == "draft":
        from app.modules.payslips.models import PayPeriod
        from app.modules.payslips.service import (
            _auto_attach_recurring_allowances,
            recompute_payslip,
        )
        from app.modules.staff.models import StaffMember

        staff = await db.get(StaffMember, timesheet.staff_id)
        period = await db.get(PayPeriod, timesheet.pay_period_id)
        if staff is not None and period is not None:
            await _auto_attach_recurring_allowances(
                db, payslip=payslip, staff=staff, period=period,
            )
            await recompute_payslip(
                db, payslip=payslip, staff=staff, period=period,
            )

    return payslip.id


async def run_pay_period(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
    actor_id: UUID,
) -> PayRunSummary:
    """Run payslip generation for a period, driven by weekly Attendance sign-offs.

    Review/approval is decoupled from the pay cycle: hours are reviewed and
    signed off weekly on the Attendance tab (per-shift ``reviewed`` flag), for
    all staff regardless of cadence. The pay run then simply consumes those
    approved hours — there is no separate per-cycle approve/lock step.

    Steps:
    1. Null-cycle guard (REQ 8.5) — a period must belong to a cycle.
    2. Materialise any missing timesheets for the period's cycle staff.
    3. For each not-yet-locked timesheet, recompute its hours from the reviewed
       shifts and — if every completed shift in the period has been signed off
       on Attendance — auto-lock it (the approval of record). Staff with
       un-reviewed shifts are skipped and reported in ``skipped_pending_review``.
    4. Generate payslip drafts for all locked timesheets.
    5. Include any timesheet_adjustments targeting this period.
    """
    from app.modules.payslips.models import PayPeriod
    from app.modules.time_clock.models import TimeClockEntry
    from app.modules.timesheets.service import (
        _org_zoneinfo,
        materialise_missing_timesheets,
        recompute_timesheets_for_staff_date,
    )

    # Null-cycle guard: the pay run scopes staff via the period's cycle, so a
    # missing or cycle-less period cannot proceed (REQ 8.5).
    period = await db.get(PayPeriod, pay_period_id)
    if period is None or period.pay_cycle_id is None:
        raise PayRunScopingError("pay_period_missing_cycle")

    summary = PayRunSummary(pay_period_id=pay_period_id)

    # 2. Ensure timesheets exist for the period's cycle staff (clock-active +
    #    fixed-arrangement). Cycle-scoped inside materialise.
    await materialise_missing_timesheets(
        db, org_id=org_id, pay_period_id=pay_period_id, include_all_active=False,
    )

    # Org-local → UTC window for the review-completeness query.
    tz = await _org_zoneinfo(db, org_id)
    start_dt = datetime.combine(period.start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_dt = datetime.combine(
        period.end_date + timedelta(days=1), time.min, tzinfo=tz
    ).astimezone(timezone.utc)

    result = await db.execute(
        select(Timesheet).where(
            Timesheet.org_id == org_id,
            Timesheet.pay_period_id == pay_period_id,
        )
    )
    timesheets = list(result.scalars().all())
    summary.total_timesheets = len(timesheets)

    for ts in timesheets:
        # 3. Auto-lock review-complete timesheets from the weekly Attendance
        #    sign-offs. Already-locked timesheets pass straight to generation.
        if ts.status != "locked":
            # Refresh payable hours from the reviewed shifts.
            await recompute_timesheets_for_staff_date(
                db, org_id=org_id, staff_id=ts.staff_id, work_date=period.start_date,
            )
            # Count completed, non-voided shifts NOT yet signed off in the period.
            pending = (
                await db.execute(
                    select(func.count())
                    .select_from(TimeClockEntry)
                    .where(
                        TimeClockEntry.org_id == org_id,
                        TimeClockEntry.staff_id == ts.staff_id,
                        TimeClockEntry.clock_in_at >= start_dt,
                        TimeClockEntry.clock_in_at < end_dt,
                        TimeClockEntry.clock_out_at.isnot(None),
                        func.coalesce(TimeClockEntry.flags["voided"].astext, "false") != "true",
                        func.coalesce(TimeClockEntry.flags["reviewed"].astext, "false") != "true",
                    )
                )
            ).scalar() or 0

            if pending > 0:
                summary.skipped_pending_review.append(
                    {"staff_id": str(ts.staff_id), "pending": int(pending)}
                )
                continue

            # Approved on Attendance → auto-approve + lock (the gate the pay run
            # consumes). Hours were just recomputed from the reviewed shifts.
            now = datetime.now(timezone.utc)
            ts.status = "locked"
            ts.approved_by = actor_id
            ts.approved_at = now
            ts.locked_by = actor_id
            ts.locked_at = now
            ts.updated_at = now
            await db.flush()
            await db.refresh(ts)

        try:
            payslip_id = await generate_payslip_draft(
                db, timesheet=ts, org_id=org_id, actor_id=actor_id,
            )
            if payslip_id:
                summary.payslips_generated += 1
        except Exception as e:
            summary.errors.append({
                "timesheet_id": str(ts.id),
                "staff_id": str(ts.staff_id),
                "error": str(e),
            })

    # Check for adjustments targeting this period
    adj_result = await db.execute(
        select(TimesheetAdjustment).where(
            TimesheetAdjustment.org_id == org_id,
            TimesheetAdjustment.correction_period_id == pay_period_id,
        )
    )
    adjustments = list(adj_result.scalars().all())
    summary.adjustments_included = len(adjustments)

    await write_audit_log(
        db,
        action="payrun.generated",
        entity_type="pay_period",
        org_id=org_id,
        user_id=actor_id,
        entity_id=pay_period_id,
        after_value={
            "timesheets_processed": summary.total_timesheets,
            "payslips_generated": summary.payslips_generated,
            "adjustments_included": summary.adjustments_included,
            "skipped_pending_review": len(summary.skipped_pending_review),
            "errors": len(summary.errors),
        },
    )

    return summary
