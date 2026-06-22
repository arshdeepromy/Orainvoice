"""Canonical default leave-type catalogue + idempotent org seeding.

The statutory NZ leave types are the same for every organisation — they are
**law, not tenant data**. This module is the single source of truth for the
default ``leave_types`` rows so that:

  * new organisations get the full catalogue at provision time
    (:func:`ensure_default_leave_types`), and
  * the migration backfill and any future re-seed reference the exact same
    definitions.

Adding a new statutory type is a one-line edit to :data:`DEFAULT_LEAVE_TYPES`;
:func:`ensure_default_leave_types` only ever **inserts missing** codes (keyed on
the ``UNIQUE(org_id, code)`` constraint) — it never mutates an existing row, so
an org admin's customisations (rename, reorder, deactivate) are preserved.

The set mirrors the Holidays Act 2003 leave types surfaced in the reference
guide: annual holidays, sick, bereavement, family-violence, public holidays,
alternative (lieu) holidays, jury service, parental leave, plus the
universally-seeded unpaid + TOIL rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leave.models import LeaveType

__all__ = ["DefaultLeaveType", "DEFAULT_LEAVE_TYPES", "ensure_default_leave_types"]


@dataclass(frozen=True)
class DefaultLeaveType:
    code: str
    name: str
    is_paid: bool
    accrual_method: str  # anniversary|fixed_annual|per_period|unaccrued|event_based
    accrual_amount: Decimal | None
    accrual_unit: str  # hours|days
    carry_over_max: Decimal | None
    is_statutory: bool
    requires_doctor_note: bool
    confidential_visibility: bool
    display_order: int


# The canonical default catalogue. The first seven mirror the original
# ``0205_leave_schema`` backfill (kept at their original display_order so
# existing orgs are untouched); the final three are the statutory types that
# were previously missing from the configuration page.
DEFAULT_LEAVE_TYPES: tuple[DefaultLeaveType, ...] = (
    DefaultLeaveType(
        code="annual", name="Annual leave", is_paid=True,
        accrual_method="anniversary", accrual_amount=None, accrual_unit="hours",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=1,
    ),
    DefaultLeaveType(
        code="sick", name="Sick leave", is_paid=True,
        accrual_method="per_period", accrual_amount=Decimal("80.0"), accrual_unit="hours",
        carry_over_max=Decimal("160.0"), is_statutory=True, requires_doctor_note=True,
        confidential_visibility=False, display_order=2,
    ),
    DefaultLeaveType(
        code="bereavement", name="Bereavement leave", is_paid=True,
        accrual_method="event_based", accrual_amount=None, accrual_unit="days",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=3,
    ),
    DefaultLeaveType(
        code="family_violence", name="Family violence leave", is_paid=True,
        accrual_method="per_period", accrual_amount=Decimal("80.0"), accrual_unit="hours",
        carry_over_max=Decimal("80.0"), is_statutory=True, requires_doctor_note=False,
        confidential_visibility=True, display_order=4,
    ),
    DefaultLeaveType(
        code="public_holiday_alt", name="Alternative holiday", is_paid=True,
        accrual_method="event_based", accrual_amount=None, accrual_unit="days",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=5,
    ),
    DefaultLeaveType(
        code="unpaid", name="Unpaid leave", is_paid=False,
        accrual_method="unaccrued", accrual_amount=None, accrual_unit="hours",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=6,
    ),
    DefaultLeaveType(
        code="toil", name="Time off in lieu", is_paid=True,
        accrual_method="event_based", accrual_amount=None, accrual_unit="hours",
        carry_over_max=None, is_statutory=False, requires_doctor_note=False,
        confidential_visibility=False, display_order=7,
    ),
    # --- Statutory types previously missing from the catalogue ---------------
    DefaultLeaveType(
        code="public_holiday", name="Public holiday", is_paid=True,
        accrual_method="event_based", accrual_amount=None, accrual_unit="days",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=8,
    ),
    DefaultLeaveType(
        code="jury_service", name="Jury service", is_paid=False,
        accrual_method="unaccrued", accrual_amount=None, accrual_unit="hours",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=9,
    ),
    DefaultLeaveType(
        code="parental", name="Parental leave", is_paid=False,
        accrual_method="unaccrued", accrual_amount=None, accrual_unit="hours",
        carry_over_max=None, is_statutory=True, requires_doctor_note=False,
        confidential_visibility=False, display_order=10,
    ),
)


async def ensure_default_leave_types(
    db: AsyncSession, org_id: uuid.UUID
) -> list[uuid.UUID]:
    """Insert any missing default leave types for ``org_id`` (idempotent).

    Returns the ids of newly-created rows. Existing rows (matched by
    ``code``) are left exactly as-is — this never updates a row, so org
    customisations survive. Uses ``flush()`` (never ``commit()``) per the
    project's session contract.
    """
    existing_codes = set(
        (
            await db.execute(
                select(LeaveType.code).where(LeaveType.org_id == org_id)
            )
        ).scalars().all()
    )

    created: list[uuid.UUID] = []
    for spec in DEFAULT_LEAVE_TYPES:
        if spec.code in existing_codes:
            continue
        row = LeaveType(
            org_id=org_id,
            code=spec.code,
            name=spec.name,
            is_paid=spec.is_paid,
            accrual_method=spec.accrual_method,
            accrual_amount=spec.accrual_amount,
            accrual_unit=spec.accrual_unit,
            carry_over_max=spec.carry_over_max,
            is_statutory=spec.is_statutory,
            requires_doctor_note=spec.requires_doctor_note,
            confidential_visibility=spec.confidential_visibility,
            active=True,
            display_order=spec.display_order,
        )
        db.add(row)
        created.append(row.id)

    if created:
        await db.flush()
    return created
