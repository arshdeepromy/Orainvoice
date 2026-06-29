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
from dataclasses import dataclass
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
    delete,
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
    "PayCycleValidationError",
    "EMPLOYMENT_TYPE_NS",
    "employment_type_target_id",
    "set_staff_pay_cycle",
    "ResolvedCycle",
    "resolve_pay_cycle_for_staff",
    "resolve_pay_cycles_for_staff_batch",
]


# ===========================================================================
# Service exceptions
# ===========================================================================


class PayCycleValidationError(Exception):
    """Raised when a staff-level cycle assignment fails validation.

    Mirrors the ``DuplicateStaffError`` / ``MinimumWageBelowThresholdError``
    pattern in ``app/modules/staff/service.py``: it carries a machine-readable
    ``code`` so the staff routers can map it to an HTTP 422 response body.

    ``code`` ∈ {``"pay_cycle_not_found"``, ``"pay_cycle_inactive"``}:
      - ``pay_cycle_not_found`` — the selected cycle id does not belong to the
        Org_User's organisation (REQ 2.4).
      - ``pay_cycle_inactive`` — the selected cycle exists in the org but is
        inactive (REQ 2.5).

    Validates: Requirements 2.4, 2.5.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


# ===========================================================================
# Employment-type target-id encoding (Decision 3)
# ===========================================================================

# Fixed namespace constant for employment-type assignment target ids. The
# employment type (text: permanent / casual / fixed_term) is encoded as a
# deterministic UUIDv5 so ``pay_cycle_assignments.target_id`` stays UUID-typed
# and the ``UNIQUE(pay_cycle_id, target_type, target_id)`` constraint remains
# meaningful (one cycle per employment type). The same string always maps to
# the same UUID, so the write-side and resolve-side agree without a lookup
# table.
EMPLOYMENT_TYPE_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def employment_type_target_id(employment_type: str) -> uuid.UUID:
    """Deterministically map an employment-type string to a UUIDv5 target id."""
    return uuid.uuid5(EMPLOYMENT_TYPE_NS, employment_type)


# ===========================================================================
# Resolution result type (Decision 4)
# ===========================================================================


@dataclass
class ResolvedCycle:
    """The pay cycle that applies to a staff member after resolution.

    ``is_default`` is ``True`` only when the staff member matched nothing more
    specific than the org Default_Cycle (REQ 5.2). It is ``False`` for matches at
    the staff, employment_type, branch, or ``all`` levels.
    """

    cycle: "PayCycle"
    is_default: bool


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


async def update_pay_cycle(
    db: AsyncSession,
    *,
    org_id: UUID,
    cycle_id: UUID,
    name: str,
    frequency: PayCycleFrequency,
    anchor_date: date,
    pay_date_offset_days: int = 3,
    is_default: bool = False,
    actor_id: UUID,
) -> PayCycle:
    """Update an existing pay cycle for an org.

    Loads the cycle scoped to ``org_id`` (so one org can never edit another's
    cycle), applies the new field values, and audits the before/after. When the
    cycle is promoted to the org Default_Cycle, every *other* cycle in the org
    has its ``is_default`` cleared so there is never more than one default.

    Raises :class:`PayCycleValidationError` with code ``pay_cycle_not_found``
    when no cycle with ``cycle_id`` exists for the org.
    """
    cycle = (
        await db.execute(
            select(PayCycle).where(
                PayCycle.id == cycle_id, PayCycle.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise PayCycleValidationError("pay_cycle_not_found")

    before = {
        "name": cycle.name,
        "frequency": cycle.frequency,
        "anchor_date": str(cycle.anchor_date),
        "pay_date_offset_days": cycle.pay_date_offset_days,
        "is_default": cycle.is_default,
    }

    cycle.name = name
    cycle.frequency = frequency
    cycle.anchor_date = anchor_date
    cycle.pay_date_offset_days = pay_date_offset_days
    cycle.is_default = is_default

    # Exactly one default per org: clear the flag on every other cycle when this
    # one becomes the default.
    if is_default:
        others = (
            await db.execute(
                select(PayCycle).where(
                    PayCycle.org_id == org_id, PayCycle.id != cycle_id,
                )
            )
        ).scalars().all()
        for other in others:
            if other.is_default:
                other.is_default = False

    await db.flush()
    await db.refresh(cycle)

    await write_audit_log(
        db,
        action="pay_cycle.updated",
        entity_type="pay_cycle",
        org_id=org_id,
        user_id=actor_id,
        entity_id=cycle.id,
        before_value=before,
        after_value={
            "name": name,
            "frequency": frequency,
            "anchor_date": str(anchor_date),
            "pay_date_offset_days": pay_date_offset_days,
            "is_default": is_default,
        },
    )

    return cycle


async def assign_pay_cycle(
    db: AsyncSession,
    *,
    org_id: UUID,
    pay_cycle_id: UUID,
    target_type: Literal["all", "branch", "employment_type", "staff"],
    target_id: UUID | str | None = None,
) -> PayCycleAssignment:
    """Assign a pay cycle to a target scope.

    For ``target_type='employment_type'`` the caller (the
    ``/pay-cycles/{id}/assignments/`` route) passes the **raw employment-type
    string** (``permanent`` / ``casual`` / ``fixed_term``); this service encodes
    it to the deterministic UUIDv5 target id via
    :func:`employment_type_target_id` so the write-side and the resolve-side
    agree on the same target id without a lookup table (Decision 3). For all
    other target types ``target_id`` is stored as-is (``staff`` → ``staff_id``,
    ``branch`` → ``branch_id``, ``all`` → ``None``).

    Validates: Requirements 8.1 (employment-type encoding path).
    """
    if target_type == "employment_type" and target_id is not None:
        encoded_target_id: UUID | None = employment_type_target_id(str(target_id))
    else:
        encoded_target_id = target_id  # type: ignore[assignment]

    assignment = PayCycleAssignment(
        pay_cycle_id=pay_cycle_id,
        org_id=org_id,
        target_type=target_type,
        target_id=encoded_target_id,
    )
    db.add(assignment)
    await db.flush()
    await db.refresh(assignment)
    return assignment


async def set_staff_pay_cycle(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_id: UUID,
    pay_cycle_id: UUID | None,
) -> PayCycleAssignment | None:
    """Set (or clear) a staff member's staff-level pay-cycle assignment.

    Uses **delete-then-insert** replace semantics so that, after any call, at
    most one ``target_type='staff'`` assignment exists for the staff member
    (REQ 3.1, 3.4). This is preferred over an upsert-on-conflict because the
    ``UNIQUE`` key is ``(pay_cycle_id, target_type, target_id)``: switching a
    staff member from cycle A to cycle B changes ``pay_cycle_id``, so an
    ``ON CONFLICT`` would not match the old row and would leave A behind,
    producing two staff-level rows.

    Behaviour:
      - Always delete every existing staff-level assignment for this staff
        member first.
      - ``pay_cycle_id is None`` → leave zero rows; the staff member resolves to
        the org Default_Cycle (REQ 2.3, 3.3). Flush and return ``None``.
      - Otherwise validate the cycle belongs to the org and is active, raising
        :class:`PayCycleValidationError` (``pay_cycle_not_found`` /
        ``pay_cycle_inactive``) when it does not (REQ 2.4, 2.5), then insert
        exactly one assignment.

    Re-assigning the same cycle (delete the row, insert an equivalent one) is
    idempotent and reports success (REQ 3.2).

    Validates: Requirements 2.1-2.5, 3.1-3.4.
    """
    # 1. Always remove any existing staff-level assignment(s) for this staff.
    await db.execute(
        delete(PayCycleAssignment).where(
            PayCycleAssignment.org_id == org_id,
            PayCycleAssignment.target_type == "staff",
            PayCycleAssignment.target_id == staff_id,
        )
    )

    # 2. Clearing the cycle => leave zero assignments (resolves to default).
    if pay_cycle_id is None:
        await db.flush()
        return None

    # 3. Validate the cycle belongs to the org AND is active.
    cycle = (
        await db.execute(
            select(PayCycle).where(
                PayCycle.id == pay_cycle_id,
                PayCycle.org_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if cycle is None:
        raise PayCycleValidationError("pay_cycle_not_found")
    if not cycle.active:
        raise PayCycleValidationError("pay_cycle_inactive")

    # 4. Insert the single new assignment.
    assignment = PayCycleAssignment(
        org_id=org_id,
        pay_cycle_id=pay_cycle_id,
        target_type="staff",
        target_id=staff_id,
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
    """Resolve which pay cycle applies to a single staff member.

    Priority order (most specific wins): staff → employment_type → branch →
    ``all`` → org Default_Cycle. Returns the first matching **active** cycle, or
    ``None`` when nothing matches and the org has no active default (REQ
    4.1-4.6).

    This is a thin wrapper over the same in-memory priority logic the batch
    resolver uses (:func:`resolve_pay_cycles_for_staff_batch`), so the
    single-staff and batch paths cannot diverge (Decision 4). Callers that
    already know the staff member's branch pass it via ``branch_id``; the batch
    resolver instead derives the branch from the staff member's primary
    ``StaffLocationAssignment``.

    Resolution is hardened against duplicate/legacy assignment rows: each level's
    assignment is picked deterministically (ordered by ``created_at`` then
    ``pay_cycle_id``) and the function never raises on duplicates. Inactive
    cycles are excluded at every level — an assignment pointing at an inactive
    cycle is skipped and resolution falls through to the next level (REQ 4.5).

    Validates: Requirements 4.1-4.6, 9.1.
    """
    maps = await _load_org_cycle_maps(db, org_id=org_id)
    resolved = _resolve_from_maps(
        maps,
        staff_id=staff_id,
        employment_type=employment_type,
        branch_id=branch_id,
    )
    return resolved.cycle if resolved is not None else None


async def resolve_pay_cycles_for_staff_batch(
    db: AsyncSession,
    *,
    org_id: UUID,
    staff_members: list,
) -> dict[UUID, "ResolvedCycle | None"]:
    """Resolve the applicable pay cycle for many staff members at once.

    Precomputes the org's assignment maps (active cycles, staff /
    employment_type / branch maps, the ``all`` cycle, the default cycle, and each
    staff member's branch from their primary ``StaffLocationAssignment``) in a
    fixed number of queries, then applies the priority order in memory for every
    staff member — avoiding the N+1 that calling the single resolver per staff
    would incur (Decision 4).

    A staff member's branch comes from their **primary** location assignment: a
    staff member with zero or ambiguous (multiple distinct) location assignments
    skips the branch level and falls through to ``all`` / default.

    Returns a mapping of ``staff_id -> ResolvedCycle | None``. ``ResolvedCycle``
    carries ``is_default=True`` only when the staff member matched nothing more
    specific than the org Default_Cycle (REQ 5.2); the value is ``None`` when
    nothing matches and the org has no active default (REQ 5.3, 4.6).

    Validates: Requirements 4.1-4.6, 5.2, 5.3, 9.1.
    """
    maps = await _load_org_cycle_maps(db, org_id=org_id)
    staff_ids = [s.id for s in staff_members]
    staff_branch = await _load_staff_branches(db, staff_ids=staff_ids)

    resolved: dict[UUID, "ResolvedCycle | None"] = {}
    for staff in staff_members:
        resolved[staff.id] = _resolve_from_maps(
            maps,
            staff_id=staff.id,
            employment_type=getattr(staff, "employment_type", None),
            branch_id=staff_branch.get(staff.id),
        )
    return resolved


@dataclass
class _OrgCycleMaps:
    """Precomputed org-level lookup maps used by the resolution logic."""

    active_cycles_by_id: dict[UUID, PayCycle]
    staff_assignments: dict[UUID, UUID]
    emptype_assignments: dict[UUID, UUID]
    branch_assignments: dict[UUID, UUID]
    all_cycle_id: UUID | None
    default_cycle: PayCycle | None


async def _load_org_cycle_maps(db: AsyncSession, *, org_id: UUID) -> _OrgCycleMaps:
    """Build the org's active-cycle and assignment maps in a fixed # of queries.

    Active cycles and assignments are loaded once; assignments are ordered by
    ``created_at`` then ``pay_cycle_id`` so the deterministic "first" assignment
    wins per target when legacy duplicates exist (Decision 3). Cycles referenced
    by an assignment but not present in ``active_cycles_by_id`` (inactive) are
    simply skipped at resolution time, never raising.
    """
    # Active cycles for the org (active-only — every level requires active).
    cycle_rows = (
        await db.execute(
            select(PayCycle)
            .where(PayCycle.org_id == org_id, PayCycle.active == True)  # noqa: E712
            .order_by(PayCycle.created_at.asc(), PayCycle.id.asc())
        )
    ).scalars().all()
    active_cycles_by_id: dict[UUID, PayCycle] = {c.id: c for c in cycle_rows}
    default_cycle = next((c for c in cycle_rows if c.is_default), None)

    # All assignments for the org, ordered for a deterministic first-wins pick.
    assignment_rows = (
        await db.execute(
            select(PayCycleAssignment)
            .where(PayCycleAssignment.org_id == org_id)
            .order_by(
                PayCycleAssignment.created_at.asc(),
                PayCycleAssignment.pay_cycle_id.asc(),
            )
        )
    ).scalars().all()

    staff_assignments: dict[UUID, UUID] = {}
    emptype_assignments: dict[UUID, UUID] = {}
    branch_assignments: dict[UUID, UUID] = {}
    all_cycle_id: UUID | None = None
    for a in assignment_rows:
        if a.target_type == "staff" and a.target_id is not None:
            staff_assignments.setdefault(a.target_id, a.pay_cycle_id)
        elif a.target_type == "employment_type" and a.target_id is not None:
            emptype_assignments.setdefault(a.target_id, a.pay_cycle_id)
        elif a.target_type == "branch" and a.target_id is not None:
            branch_assignments.setdefault(a.target_id, a.pay_cycle_id)
        elif a.target_type == "all":
            if all_cycle_id is None:
                all_cycle_id = a.pay_cycle_id

    return _OrgCycleMaps(
        active_cycles_by_id=active_cycles_by_id,
        staff_assignments=staff_assignments,
        emptype_assignments=emptype_assignments,
        branch_assignments=branch_assignments,
        all_cycle_id=all_cycle_id,
        default_cycle=default_cycle,
    )


async def _load_staff_branches(
    db: AsyncSession, *, staff_ids: list[UUID]
) -> dict[UUID, UUID | None]:
    """Derive each staff member's branch from their location assignments.

    A staff member with exactly one distinct location assignment resolves to that
    location id; zero or ambiguous (multiple distinct) assignments resolve to
    ``None`` so the branch level is skipped (Decision 3 branch-level note).
    """
    if not staff_ids:
        return {}

    # Local import avoids a circular import (staff.service imports this module).
    from app.modules.staff.models import StaffLocationAssignment

    rows = (
        await db.execute(
            select(
                StaffLocationAssignment.staff_id,
                StaffLocationAssignment.location_id,
            ).where(StaffLocationAssignment.staff_id.in_(staff_ids))
        )
    ).all()

    locations: dict[UUID, set[UUID]] = {}
    for staff_id, location_id in rows:
        locations.setdefault(staff_id, set()).add(location_id)

    return {
        staff_id: (next(iter(locs)) if len(locs) == 1 else None)
        for staff_id, locs in locations.items()
    }


def _resolve_from_maps(
    maps: _OrgCycleMaps,
    *,
    staff_id: UUID,
    employment_type: str | None,
    branch_id: UUID | None,
) -> "ResolvedCycle | None":
    """Apply the resolution priority order in memory against precomputed maps.

    Priority: staff → employment_type → branch → ``all`` → default. The first
    level whose matching assignment points at an **active** cycle wins; an
    assignment to an inactive cycle is skipped (the cycle id is absent from
    ``active_cycles_by_id``) and resolution falls through to the next level
    rather than short-circuiting to ``None`` (REQ 4.5). Returns ``None`` only
    when no level matches and the org has no active default.
    """
    active = maps.active_cycles_by_id

    # 1. Staff level.
    cycle_id = maps.staff_assignments.get(staff_id)
    if cycle_id is not None and cycle_id in active:
        return ResolvedCycle(active[cycle_id], is_default=False)

    # 2. Employment-type level.
    if employment_type:
        cycle_id = maps.emptype_assignments.get(
            employment_type_target_id(employment_type)
        )
        if cycle_id is not None and cycle_id in active:
            return ResolvedCycle(active[cycle_id], is_default=False)

    # 3. Branch level.
    if branch_id is not None:
        cycle_id = maps.branch_assignments.get(branch_id)
        if cycle_id is not None and cycle_id in active:
            return ResolvedCycle(active[cycle_id], is_default=False)

    # 4. 'all' level.
    if maps.all_cycle_id is not None and maps.all_cycle_id in active:
        return ResolvedCycle(active[maps.all_cycle_id], is_default=False)

    # 5. Default cycle.
    if maps.default_cycle is not None:
        return ResolvedCycle(maps.default_cycle, is_default=True)

    # 6. Nothing matches and no default.
    return None


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
        # Check if already exists — cycle-scoped (Decision 5). The 0225
        # migration relaxed the uniqueness key from (org_id, start_date) to
        # (org_id, pay_cycle_id, start_date), so two active cycles may share a
        # start_date (REQ 8.3). The existence check must therefore be scoped to
        # this cycle, otherwise a second cycle's period sharing a start_date
        # with an already-generated cycle would be incorrectly skipped.
        existing = await db.execute(
            select(PayPeriod).where(
                PayPeriod.org_id == org_id,
                PayPeriod.pay_cycle_id == pay_cycle_id,
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
