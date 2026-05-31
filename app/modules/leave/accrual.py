"""Leave accrual engine — Phase 2 task B4.

Daily entry point :func:`accrue_for_staff` walks every active leave
balance for one staff member and dispatches to the per-method handlers
described in the design document (§4.1):

  - **anniversary** → :func:`_process_anniversary` (annual leave grant
    on each anniversary date).
  - **per_period** + ``code='sick'`` → :func:`_process_sick_yearly`
    (80h sick on each Phase 2 anniversary, capped at carry_over_max).
  - **per_period** + ``code='family_violence'`` →
    :func:`_process_family_violence_yearly` (80h on anniversary, no
    carry-over — capped at 80h).

Idempotency is enforced everywhere: each handler runs a SELECT on
``leave_ledger`` keyed on ``(staff_id, leave_type_id, reason='accrual',
occurred_at)`` BEFORE inserting a new ledger row. Running the daily job
twice on the same UTC day is a no-op for the second run.

Casual filter
-------------

Staff with ``employment_type='casual'`` skip the annual-leave
anniversary path entirely (they're paid 8% pay-as-you-go on each pay
run — see R7). Sick + family_violence still apply pro-rata since the
formula references ``standard_hours_per_week`` directly.

Days-to-hours conversion
------------------------

The 6 statutory leave types ship with ``accrual_unit='hours'`` so the
amount is taken at face value. Custom org-defined types may use
``accrual_unit='days'`` — :func:`days_to_hours` converts using the
staff's standard working day (``standard_hours_per_week / 5``, with an
8h fallback when the staff record's hours-per-week is NULL).

Leap-year edges
---------------

:func:`anniversary_in_year` handles the ``employment_start_date =
Feb 29`` case by returning Feb 28 in non-leap years (per STAFF-010 in
requirements.md).

**Validates: Requirements R5, R6, R7, R10 — Staff Management Phase 2 task B4**
"""

from __future__ import annotations

import logging
import uuid
from calendar import isleap
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leave.models import LeaveBalance, LeaveLedger, LeaveType
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


__all__ = [
    "accrue_for_staff",
    "anniversary_in_year",
    "days_to_hours",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def days_to_hours(
    accrual_amount_days: Decimal, staff: StaffMember
) -> Decimal:
    """Convert a days-based accrual amount into balance hours.

    Working day = ``staff.standard_hours_per_week / 5`` rounded to 2dp.
    Falls back to 8h/day when ``standard_hours_per_week`` is NULL —
    matches the industry default and keeps unit conversion consistent
    with the bereavement-cap logic in :mod:`app.modules.leave.service`.
    """
    if staff.standard_hours_per_week:
        std_day = (Decimal(staff.standard_hours_per_week) / Decimal(5)).quantize(
            Decimal("0.01")
        )
        return (Decimal(accrual_amount_days) * std_day).quantize(Decimal("0.01"))
    return (Decimal(accrual_amount_days) * Decimal(8)).quantize(Decimal("0.01"))


def anniversary_in_year(start_date: date, year: int) -> date:
    """Return the anniversary of ``start_date`` falling in ``year``.

    Leap-year safe: if ``start_date`` is Feb 29 and ``year`` is not a
    leap year, returns Feb 28 (the last day of February).
    """
    if start_date.month == 2 and start_date.day == 29 and not isleap(year):
        return date(year, 2, 28)
    return start_date.replace(year=year)


def _std_weekly_hours(staff: StaffMember) -> Decimal:
    """Resolve weekly standard hours, falling back to 40h."""
    if staff.standard_hours_per_week:
        return Decimal(staff.standard_hours_per_week)
    return Decimal(40)


async def _ledger_row_exists(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    leave_type_id: uuid.UUID,
    occurred_at: date,
) -> bool:
    """Return True when an ``accrual`` ledger row already exists for the
    given (staff, leave_type, occurred_at) triple. Used by every per-
    method handler before inserting a new row.
    """
    stmt = (
        select(LeaveLedger.id)
        .where(
            LeaveLedger.staff_id == staff_id,
            LeaveLedger.leave_type_id == leave_type_id,
            LeaveLedger.reason == "accrual",
            LeaveLedger.occurred_at == occurred_at,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _load_balances_with_types(
    db: AsyncSession, staff_id: uuid.UUID
) -> list[tuple[LeaveBalance, LeaveType]]:
    """Return every (balance, leave_type) pair for the staff member."""
    stmt = (
        select(LeaveBalance, LeaveType)
        .join(LeaveType, LeaveBalance.leave_type_id == LeaveType.id)
        .where(LeaveBalance.staff_id == staff_id)
    )
    result = await db.execute(stmt)
    return list(result.all())


def _resolve_anniversary_date(
    staff: StaffMember, balance: LeaveBalance, today: date
) -> date | None:
    """Resolve the anniversary date for the current accrual cycle.

    ``balance.anniversary_date`` is seeded from
    ``staff.employment_start_date`` by the migration backfill. We use
    this anchor to compute the most recent anniversary on or before
    ``today``. Returns None when the staff has no employment start
    date.
    """
    anchor = balance.anniversary_date or staff.employment_start_date
    if anchor is None:
        return None
    # Years since start (inclusive on the anniversary date itself).
    years = today.year - anchor.year
    if years < 0:
        return None
    candidate = anniversary_in_year(anchor, anchor.year + years)
    if candidate > today:
        # We've not hit this year's anniversary yet — fall back to last year.
        if years == 0:
            return None
        candidate = anniversary_in_year(anchor, anchor.year + years - 1)
    return candidate


# ---------------------------------------------------------------------------
# Per-method handlers
# ---------------------------------------------------------------------------


async def _process_anniversary(
    db: AsyncSession,
    staff: StaffMember,
    balance: LeaveBalance,
    leave_type: LeaveType,
    today: date,
) -> LeaveLedger | None:
    """Annual-leave grant on the staff's anniversary.

    Granted amount = ``staff.standard_hours_per_week × 4`` (i.e. 4 weeks
    of leave per the Holidays Act minimum, scaled to the staff's actual
    hours). Casual staff are filtered out at the caller — this helper
    runs only for permanent / fixed-term workers. Idempotency is keyed
    on ``occurred_at == anniversary_date``.
    """
    anniversary = _resolve_anniversary_date(staff, balance, today)
    if anniversary is None:
        return None
    if anniversary != today:
        # Only grant on the anniversary itself; the daily task catches
        # late runs because anniversary == today on exactly one day per
        # year.
        return None

    if await _ledger_row_exists(
        db,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        occurred_at=anniversary,
    ):
        return None

    # Compute the grant. ``accrual_unit='days'`` types route through
    # days_to_hours so a custom 5-day type at a 40h/wk staff = 40h.
    if leave_type.accrual_unit == "days" and leave_type.accrual_amount is not None:
        granted = days_to_hours(leave_type.accrual_amount, staff)
    elif leave_type.accrual_amount is not None:
        granted = Decimal(leave_type.accrual_amount).quantize(Decimal("0.01"))
    else:
        # Default for the statutory annual leave row: 4 × weekly hours.
        granted = (_std_weekly_hours(staff) * Decimal(4)).quantize(
            Decimal("0.01")
        )

    ledger = LeaveLedger(
        org_id=staff.org_id,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        delta_hours=granted,
        reason="accrual",
        request_id=None,
        occurred_at=anniversary,
        created_by=None,
    )
    db.add(ledger)
    balance.accrued_hours = Decimal(balance.accrued_hours) + granted
    balance.last_accrual_at = datetime.now(timezone.utc)
    balance.updated_at = datetime.now(timezone.utc)

    # Apply carry-over cap (Holidays Act s16: minimum 4 weeks rolls over;
    # employer policy may cap above that — captured here when
    # ``carry_over_max`` is set).
    if leave_type.carry_over_max is not None:
        cap = Decimal(leave_type.carry_over_max)
        net = Decimal(balance.accrued_hours) - Decimal(balance.used_hours)
        if net > cap:
            overflow = net - cap
            db.add(
                LeaveLedger(
                    org_id=staff.org_id,
                    staff_id=staff.id,
                    leave_type_id=leave_type.id,
                    delta_hours=-overflow,
                    reason="manual_adjustment",
                    request_id=None,
                    occurred_at=anniversary,
                    created_by=None,
                )
            )
            balance.accrued_hours = Decimal(balance.accrued_hours) - overflow

    return ledger


async def _process_sick_yearly(
    db: AsyncSession,
    staff: StaffMember,
    balance: LeaveBalance,
    leave_type: LeaveType,
    today: date,
) -> LeaveLedger | None:
    """Sick leave grant on each Phase 2 anniversary.

    Phase 2 simplification: rather than implementing the full Holidays
    Act 6-month gate as an alternate path (P3 will refine), Phase 2
    grants ``standard_hours_per_week × 2`` (= 80h for a 40h/wk staff)
    on each anniversary, capped at ``carry_over_max=160h`` (Holidays
    Act s67). The 6-month gate is enforced by the migration backfill —
    new staff start with 0 sick hours and only see their first grant on
    the first anniversary at-or-after 6 months.
    """
    anniversary = _resolve_anniversary_date(staff, balance, today)
    if anniversary is None or anniversary != today:
        return None

    if await _ledger_row_exists(
        db,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        occurred_at=anniversary,
    ):
        return None

    granted = (_std_weekly_hours(staff) * Decimal(2)).quantize(Decimal("0.01"))

    # Apply cap: if accrued + granted > carry_over_max, scale down.
    if leave_type.carry_over_max is not None:
        cap = Decimal(leave_type.carry_over_max)
        new_total = (
            Decimal(balance.accrued_hours)
            - Decimal(balance.used_hours)
            + granted
        )
        if new_total > cap:
            granted = cap - (
                Decimal(balance.accrued_hours) - Decimal(balance.used_hours)
            )
            if granted <= 0:
                return None

    ledger = LeaveLedger(
        org_id=staff.org_id,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        delta_hours=granted,
        reason="accrual",
        request_id=None,
        occurred_at=anniversary,
        created_by=None,
    )
    db.add(ledger)
    balance.accrued_hours = Decimal(balance.accrued_hours) + granted
    balance.last_accrual_at = datetime.now(timezone.utc)
    balance.updated_at = datetime.now(timezone.utc)
    return ledger


async def _process_family_violence_yearly(
    db: AsyncSession,
    staff: StaffMember,
    balance: LeaveBalance,
    leave_type: LeaveType,
    today: date,
) -> LeaveLedger | None:
    """Family-violence leave grant on each anniversary.

    Same shape as sick leave, but the statute does NOT allow carry-over
    — unused hours expire at anniversary, so each grant brings the
    balance up to the annual entitlement (at most ``standard_hours_per_week
    × 2 = 80h`` for a 40h/wk staff). Idempotency keyed on
    ``occurred_at`` per usual.
    """
    anniversary = _resolve_anniversary_date(staff, balance, today)
    if anniversary is None or anniversary != today:
        return None

    if await _ledger_row_exists(
        db,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        occurred_at=anniversary,
    ):
        return None

    target = (_std_weekly_hours(staff) * Decimal(2)).quantize(Decimal("0.01"))

    # No carry-over. Compute delta to bring net (accrued - used) back up
    # to the annual entitlement; never below zero.
    current_net = Decimal(balance.accrued_hours) - Decimal(balance.used_hours)
    if current_net >= target:
        # Already at or above cap (e.g. an admin pre-funded). Nothing to grant.
        return None
    granted = target - current_net

    ledger = LeaveLedger(
        org_id=staff.org_id,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        delta_hours=granted,
        reason="accrual",
        request_id=None,
        occurred_at=anniversary,
        created_by=None,
    )
    db.add(ledger)
    balance.accrued_hours = Decimal(balance.accrued_hours) + granted
    balance.last_accrual_at = datetime.now(timezone.utc)
    balance.updated_at = datetime.now(timezone.utc)
    return ledger


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


async def accrue_for_staff(
    db: AsyncSession,
    staff: StaffMember,
    today: date,
) -> list[LeaveLedger]:
    """Process all accrual types for one staff member.

    Walks every ``(balance, leave_type)`` pair for the staff and
    dispatches based on ``leave_type.accrual_method`` and ``code``.
    Casual staff skip the annual-leave anniversary path; sick +
    family_violence still accrue pro-rata.

    Returns the list of ledger rows written this run (empty on a
    repeat-day idempotent run).
    """
    written: list[LeaveLedger] = []
    pairs = await _load_balances_with_types(db, staff.id)
    is_casual = (staff.employment_type or "").lower() == "casual"

    for balance, leave_type in pairs:
        if not leave_type.active:
            continue

        ledger: LeaveLedger | None = None

        if leave_type.accrual_method == "anniversary":
            if is_casual:
                # Casual staff are paid 8% pay-as-you-go on each pay run
                # — no annual-leave accrual rows.
                continue
            ledger = await _process_anniversary(
                db, staff, balance, leave_type, today
            )
        elif (
            leave_type.accrual_method == "per_period"
            and leave_type.code == "sick"
        ):
            ledger = await _process_sick_yearly(
                db, staff, balance, leave_type, today
            )
        elif (
            leave_type.accrual_method == "per_period"
            and leave_type.code == "family_violence"
        ):
            ledger = await _process_family_violence_yearly(
                db, staff, balance, leave_type, today
            )
        # Other methods (event_based, unaccrued, fixed_annual) are not
        # processed by the daily task — they accrue at request time
        # (event_based) or never (unaccrued).

        if ledger is not None:
            written.append(ledger)

    if written:
        await db.flush()

    return written
