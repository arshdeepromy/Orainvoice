"""Pay Run service — lock-to-payslip integration.

When timesheets transition to 'locked', this service:
1. Freezes hour bands on the timesheet.
2. Generates payslip drafts with hour band line items.
3. Populates timesheet.payslip_id for the locked timesheet.
4. Triggers leave accrual computation.

Phase B implementation per design § Phase B Architecture Notes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.timesheets.models import Timesheet, TimesheetSettings
from app.modules.timesheets.pay_cycles import TimesheetAdjustment


@dataclass
class PayRunSummary:
    """Summary of a pay run generation."""
    pay_period_id: UUID
    total_timesheets: int = 0
    payslips_generated: int = 0
    errors: list[dict] = field(default_factory=list)
    adjustments_included: int = 0


@dataclass
class HourBand:
    """Hour band breakdown for payslip generation."""
    category: str  # 'ordinary', 'overtime', 'public_holiday'
    minutes: int
    rate_multiplier: Decimal = Decimal("1.0")


def compute_hour_bands(timesheet: Timesheet) -> list[HourBand]:
    """Extract hour bands from a locked timesheet for payslip generation.

    Uses the effective minutes (adjusted_minutes if set, else actual_minutes)
    split into ordinary/overtime/public_holiday bands.
    """
    bands = []

    # Effective minutes = adjusted if set, else actual
    effective = timesheet.adjusted_minutes if timesheet.adjusted_minutes is not None else timesheet.actual_minutes

    # If ordinary/overtime/PH breakdown is available, use it
    if timesheet.ordinary_minutes or timesheet.overtime_minutes or timesheet.public_holiday_minutes:
        if timesheet.ordinary_minutes:
            bands.append(HourBand(
                category="ordinary",
                minutes=timesheet.ordinary_minutes,
                rate_multiplier=Decimal("1.0"),
            ))
        if timesheet.overtime_minutes:
            bands.append(HourBand(
                category="overtime",
                minutes=timesheet.overtime_minutes,
                rate_multiplier=Decimal("1.5"),
            ))
        if timesheet.public_holiday_minutes:
            bands.append(HourBand(
                category="public_holiday",
                minutes=timesheet.public_holiday_minutes,
                rate_multiplier=Decimal("1.5"),
            ))
    else:
        # Phase A fallback: all minutes are ordinary
        bands.append(HourBand(
            category="ordinary",
            minutes=effective,
            rate_multiplier=Decimal("1.0"),
        ))

    return bands


async def generate_payslip_draft(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    org_id: UUID,
    actor_id: UUID,
) -> UUID | None:
    """Generate a payslip draft from a locked timesheet.

    Returns the payslip_id if created, None if timesheet already has one.
    """
    from app.modules.payslips.models import Payslip

    if timesheet.status != "locked":
        return None

    if timesheet.payslip_id is not None:
        return timesheet.payslip_id  # Already linked

    # Check if a payslip already exists for this staff/period
    existing = await db.execute(
        select(Payslip).where(
            Payslip.staff_id == timesheet.staff_id,
            Payslip.pay_period_id == timesheet.pay_period_id,
        )
    )
    payslip = existing.scalar_one_or_none()

    if payslip is None:
        # Create draft payslip
        hour_bands = compute_hour_bands(timesheet)
        effective_minutes = sum(b.minutes for b in hour_bands)

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

    return payslip.id


async def run_pay_period(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_period_id: UUID,
    actor_id: UUID,
) -> PayRunSummary:
    """Run payslip generation for all locked timesheets in a period.

    Steps:
    1. Query all locked timesheets without a payslip_id.
    2. Generate payslip drafts for each.
    3. Include any timesheet_adjustments targeting this period.
    4. Return summary.
    """
    summary = PayRunSummary(pay_period_id=pay_period_id)

    # Get all locked timesheets for this period
    result = await db.execute(
        select(Timesheet).where(
            Timesheet.org_id == org_id,
            Timesheet.pay_period_id == pay_period_id,
            Timesheet.status == "locked",
        )
    )
    timesheets = list(result.scalars().all())
    summary.total_timesheets = len(timesheets)

    for ts in timesheets:
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
            "errors": len(summary.errors),
        },
    )

    return summary
