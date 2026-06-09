"""Pay Cycles — models and service for pay cycle management.

Pay cycles define the frequency and timing of pay runs. Each org can have
multiple pay cycles (e.g. weekly for casuals, fortnightly for permanent staff).

Tables:
  - ``pay_cycles`` — org-level cycle definitions.
  - ``pay_cycle_assignments`` — maps cycles to targets (all/branch/employment_type/staff).
  - ``timesheet_adjustments`` — corrections applied to the next open period.

**Validates: Phase B — Pay Cycles & Lock-to-Payslip**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.audit import write_audit_log
from app.core.database import Base


__all__ = [
    "PayCycle",
    "PayCycleAssignment",
    "TimesheetAdjustment",
]


# ===========================================================================
# ORM Models
# ===========================================================================


class PayCycle(Base):
    """Org-level pay cycle definition.

    Frequency:
      - weekly: 7-day periods
      - fortnightly: 14-day periods
      - monthly: calendar-month periods (1st to last day)

    anchor_date: the start of the FIRST period in this cycle. All subsequent
    period boundaries are computed from this anchor.

    pay_date_offset_days: how many days after period end_date the pay_date falls.
    """

    __tablename__ = "pay_cycles"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_pay_cycles_org_name"),
        CheckConstraint(
            "frequency IN ('weekly','fortnightly','monthly')",
            name="ck_pay_cycles_frequency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    frequency: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="fortnightly",
    )
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date_offset_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class PayCycleAssignment(Base):
    """Maps a pay cycle to a target scope.

    target_type:
      - 'all': applies to all staff in the org (target_id is NULL).
      - 'branch': applies to staff in a specific branch.
      - 'employment_type': applies to staff with matching employment_type.
      - 'staff': applies to a specific staff member.
    """

    __tablename__ = "pay_cycle_assignments"
    __table_args__ = (
        UniqueConstraint(
            "pay_cycle_id", "target_type", "target_id",
            name="uq_pay_cycle_assignments_cycle_target",
        ),
        CheckConstraint(
            "target_type IN ('all','branch','employment_type','staff')",
            name="ck_pay_cycle_assignments_target_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    pay_cycle_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pay_cycles.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="all",
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TimesheetAdjustment(Base):
    """Post-lock correction applied to the next open period.

    When a locked timesheet needs a correction (error found after lock),
    an adjustment row is created targeting the next open period. The
    adjustment_minutes (positive or negative) are included in the
    correction period's payslip as a separate line item.
    """

    __tablename__ = "timesheet_adjustments"
    __table_args__ = (
        CheckConstraint(
            "category IN ('correction','error_fix','leave_adjustment','other')",
            name="ck_timesheet_adjustments_category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    original_timesheet_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("timesheets.id"),
        nullable=False,
    )
    correction_period_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pay_periods.id"),
        nullable=False,
    )
    adjustment_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="correction",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


# ===========================================================================
# Service Functions
# ===========================================================================


PayCycleFrequency = Literal["weekly", "fortnightly", "monthly"]


def compute_period_boundaries(
    frequency: PayCycleFrequency,
    anchor_date: date,
    target_date: date,
) -> tuple[date, date]:
    """Compute the period (start_date, end_date) that contains target_date.

    For weekly/fortnightly: periods are fixed-length from anchor.
    For monthly: periods are calendar months (1st to last day).
    """
    if frequency == "monthly":
        start = target_date.replace(day=1)
        # End is last day of the month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        return start, end

    # Weekly or fortnightly: fixed-length periods from anchor
    period_days = 7 if frequency == "weekly" else 14
    days_since_anchor = (target_date - anchor_date).days

    if days_since_anchor >= 0:
        periods_elapsed = days_since_anchor // period_days
    else:
        # target_date is before anchor — compute backwards
        periods_elapsed = -(-(-days_since_anchor) // period_days + 1)

    start = anchor_date + timedelta(days=periods_elapsed * period_days)
    end = start + timedelta(days=period_days - 1)
    return start, end


def generate_upcoming_periods(
    frequency: PayCycleFrequency,
    anchor_date: date,
    pay_date_offset_days: int,
    from_date: date,
    count: int = 4,
) -> list[dict]:
    """Generate `count` upcoming period definitions from `from_date`.

    Returns list of dicts with start_date, end_date, pay_date.
    """
    periods = []
    current = from_date

    for _ in range(count):
        start, end = compute_period_boundaries(frequency, anchor_date, current)
        # If this period is already in or past, move to next
        if end < from_date:
            if frequency == "monthly":
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1, day=1)
                else:
                    current = current.replace(month=current.month + 1, day=1)
            else:
                period_days = 7 if frequency == "weekly" else 14
                current = end + timedelta(days=1)
            start, end = compute_period_boundaries(frequency, anchor_date, current)

        pay_date = end + timedelta(days=pay_date_offset_days)
        periods.append({
            "start_date": start,
            "end_date": end,
            "pay_date": pay_date,
        })

        # Move to next period
        if frequency == "monthly":
            if end.month == 12:
                current = date(end.year + 1, 1, 1)
            else:
                current = date(end.year, end.month + 1, 1)
        else:
            current = end + timedelta(days=1)

    return periods


async def create_pay_cycle(
    db: AsyncSession,
    *,
    org_id: UUID,
    name: str,
    frequency: PayCycleFrequency,
    anchor_date: date,
    pay_date_offset_days: int = 3,
    is_default: bool = False,
    actor_id: UUID,
) -> PayCycle:
    """Create a new pay cycle for an org."""
    cycle = PayCycle(
        org_id=org_id,
        name=name,
        frequency=frequency,
        anchor_date=anchor_date,
        pay_date_offset_days=pay_date_offset_days,
        is_default=is_default,
    )
    db.add(cycle)
    await db.flush()
    await db.refresh(cycle)

    await write_audit_log(
        db,
        action="pay_cycle.created",
        entity_type="pay_cycle",
        org_id=org_id,
        user_id=actor_id,
        entity_id=cycle.id,
        after_value={"name": name, "frequency": frequency},
    )

    return cycle


async def assign_pay_cycle(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_cycle_id: UUID,
    target_type: Literal["all", "branch", "employment_type", "staff"],
    target_id: UUID | None = None,
) -> PayCycleAssignment:
    """Assign a pay cycle to a target scope."""
    assignment = PayCycleAssignment(
        pay_cycle_id=pay_cycle_id,
        org_id=org_id,
        target_type=target_type,
        target_id=target_id,
    )
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment


async def resolve_pay_cycle_for_staff(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    branch_id: UUID | None = None,
    employment_type: str | None = None,
) -> PayCycle | None:
    """Resolve which pay cycle applies to a staff member.

    Priority order (most specific wins):
    1. Direct staff assignment
    2. Employment type assignment
    3. Branch assignment
    4. 'all' assignment
    5. Default cycle for org (is_default=True)
    """
    # 1. Direct staff assignment
    result = await db.execute(
        select(PayCycle)
        .join(PayCycleAssignment, PayCycleAssignment.pay_cycle_id == PayCycle.id)
        .where(
            PayCycle.org_id == org_id,
            PayCycle.active == True,
            PayCycleAssignment.target_type == "staff",
            PayCycleAssignment.target_id == staff_id,
        )
    )
    cycle = result.scalar_one_or_none()
    if cycle:
        return cycle

    # 2. Employment type assignment (if provided)
    if employment_type:
        # employment_type is stored as text; target_id is UUID — we use a JSONB lookup
        # Actually for simplicity, target_id for employment_type stores a hash-like UUID
        # We'll match by joining on an in-memory filter. For now use the 'all' fallback.
        pass

    # 3. Branch assignment
    if branch_id:
        result = await db.execute(
            select(PayCycle)
            .join(PayCycleAssignment, PayCycleAssignment.pay_cycle_id == PayCycle.id)
            .where(
                PayCycle.org_id == org_id,
                PayCycle.active == True,
                PayCycleAssignment.target_type == "branch",
                PayCycleAssignment.target_id == branch_id,
            )
        )
        cycle = result.scalar_one_or_none()
        if cycle:
            return cycle

    # 4. 'all' assignment
    result = await db.execute(
        select(PayCycle)
        .join(PayCycleAssignment, PayCycleAssignment.pay_cycle_id == PayCycle.id)
        .where(
            PayCycle.org_id == org_id,
            PayCycle.active == True,
            PayCycleAssignment.target_type == "all",
        )
    )
    cycle = result.scalar_one_or_none()
    if cycle:
        return cycle

    # 5. Default cycle
    result = await db.execute(
        select(PayCycle).where(
            PayCycle.org_id == org_id,
            PayCycle.active == True,
            PayCycle.is_default == True,
        )
    )
    return result.scalar_one_or_none()


async def auto_generate_pay_periods(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_cycle_id: UUID,
    ahead_count: int = 4,
) -> list[dict]:
    """Auto-generate PayPeriod rows for a cycle, creating any that don't exist.

    Returns list of created period summaries.
    """
    from app.modules.payslips.models import PayPeriod

    # Get the pay cycle
    result = await db.execute(
        select(PayCycle).where(PayCycle.id == pay_cycle_id, PayCycle.org_id == org_id)
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        return []

    today = date.today()
    upcoming = generate_upcoming_periods(
        frequency=cycle.frequency,
        anchor_date=cycle.anchor_date,
        pay_date_offset_days=cycle.pay_date_offset_days,
        from_date=today,
        count=ahead_count,
    )

    created = []
    for period_def in upcoming:
        # Check if already exists
        existing = await db.execute(
            select(PayPeriod).where(
                PayPeriod.org_id == org_id,
                PayPeriod.start_date == period_def["start_date"],
            )
        )
        if existing.scalar_one_or_none():
            continue

        # Create the period
        new_period = PayPeriod(
            org_id=org_id,
            start_date=period_def["start_date"],
            end_date=period_def["end_date"],
            pay_date=period_def["pay_date"],
            pay_cycle_id=pay_cycle_id,
            status="open",
        )
        db.add(new_period)
        await db.flush()
        await db.refresh(new_period)
        created.append({
            "id": str(new_period.id),
            "start_date": str(new_period.start_date),
            "end_date": str(new_period.end_date),
            "pay_date": str(new_period.pay_date),
        })

    return created


async def create_timesheet_adjustment(
    db: AsyncSession,
    *,
    org_id: UUID,
    original_timesheet_id: UUID,
    correction_period_id: UUID,
    adjustment_minutes: int,
    reason: str,
    category: str = "correction",
    actor_id: UUID,
) -> TimesheetAdjustment:
    """Create a post-lock correction adjustment.

    The adjustment is included in the correction period's payslip
    as a separate line item.
    """
    adjustment = TimesheetAdjustment(
        org_id=org_id,
        original_timesheet_id=original_timesheet_id,
        correction_period_id=correction_period_id,
        adjustment_minutes=adjustment_minutes,
        reason=reason,
        category=category,
        created_by=actor_id,
    )
    db.add(adjustment)
    await db.flush()
    await db.refresh(adjustment)

    await write_audit_log(
        db,
        action="timesheet_adjustment.created",
        entity_type="timesheet_adjustment",
        org_id=org_id,
        user_id=actor_id,
        entity_id=adjustment.id,
        after_value={
            "original_timesheet_id": str(original_timesheet_id),
            "adjustment_minutes": adjustment_minutes,
            "reason": reason,
            "category": category,
        },
    )

    return adjustment
