"""Idempotent vesting applier.

For each newly-satisfied eligibility (``eligible=True`` with no prior vesting
record for ``(staff_id, leave_type_id)``), ``apply_vesting``:

  1. appends a ``leave_ledger`` row ``reason='accrual'`` with the vested hours
     for accruing rules (annual = ``standard_hours_per_week × 4``, 40h fallback,
     matching ``accrual.py::_process_anniversary``); non-accruing entitlements
     vest the note + notification only (no ledger row),
  2. updates ``leave_balances.accrued_hours`` (+ ``last_accrual_at``),
  3. inserts a ``leave_eligibility_notes`` row stamping ``rule_set_version``,
     ``milestone_key``, the hours-test condition, and ``vested_on``,
  4. creates the de-duped eligibility-onset in-app notification.

Idempotency: a prior accrual ledger row for ``(staff,type,occurred_at=vested_on)``
OR a prior eligibility note for ``(staff,type)`` short-circuits; the
``UNIQUE(staff_id, leave_type_id)`` note constraint enforces one onset note ever.
Uses ``flush()`` (never ``commit()``). ``create_in_app_notification`` is
exception-safe, so a notification failure never rolls back the vesting.

Only eligibility results whose ``leave_type_code`` maps to an existing org
``leave_types`` row are vested — day-one entitlements (public_holiday /
alternative_holiday / jury_service) have no leave-type row and are conceptually
available from day 1, so they are not persisted as notes/balances.

**Validates: Requirements 6.6, 9.1, 9.2, 9.4, 11.2, 12.1, 12.2, 12.4, 13.1, 13.2, 13.4**
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.in_app_notifications.service import create_in_app_notification
from app.modules.leave.models import (
    LeaveBalance,
    LeaveEligibilityNote,
    LeaveLedger,
    LeaveType,
)
from app.modules.leave.rules.eligibility import EligibilityResult
from app.modules.leave.rules.registry import RuleSet
from app.modules.leave.rules.service_period import StaffSnapshot

logger = logging.getLogger(__name__)

__all__ = ["VestingOutcome", "apply_vesting"]

_DEFAULT_WEEKLY_HOURS = Decimal("40")

_MILESTONE_LABEL = {
    "day_1": "day one",
    "six_months": "6 months continuous service",
    "twelve_months": "12 months continuous service",
}


@dataclass
class VestingOutcome:
    leave_type_id: uuid.UUID
    leave_type_code: str
    vested: bool
    accrued_hours: Decimal
    note_id: uuid.UUID | None
    notification_id: uuid.UUID | None


def _condition_text(
    leave_type_name: str, milestone_key: str, hours_test_met: bool | None, vested_on: date
) -> str:
    base = _MILESTONE_LABEL.get(milestone_key, milestone_key)
    parts = [base]
    if hours_test_met:
        parts.append("hours test met")
    return (
        f"{leave_type_name} vested — {' and '.join(parts)} reached on "
        f"{vested_on.isoformat()}"
    )


async def _load_leave_types_by_code(
    db: AsyncSession, org_id: uuid.UUID
) -> dict[str, LeaveType]:
    rows = (
        await db.execute(select(LeaveType).where(LeaveType.org_id == org_id))
    ).scalars().all()
    return {lt.code: lt for lt in rows}


async def apply_vesting(
    db: AsyncSession,
    *,
    snapshot: StaffSnapshot,
    results: list[EligibilityResult],
    evaluation_date: date,
    rule_set: RuleSet,
) -> list[VestingOutcome]:
    """Apply newly-satisfied eligibilities idempotently. Returns the outcomes."""
    outcomes: list[VestingOutcome] = []
    leave_types = await _load_leave_types_by_code(db, snapshot.org_id)
    rules_by_code = {r.leave_type_code: r for r in rule_set.rules}

    weekly_hours = (
        Decimal(snapshot.standard_hours_per_week)
        if snapshot.standard_hours_per_week
        else _DEFAULT_WEEKLY_HOURS
    )

    for result in results:
        if not result.eligible:
            continue
        leave_type = leave_types.get(result.leave_type_code)
        if leave_type is None:
            # Day-one entitlement / no org leave-type row — nothing to persist.
            continue

        # --- Idempotency: prior eligibility note short-circuits everything. ---
        existing_note = (
            await db.execute(
                select(LeaveEligibilityNote.id).where(
                    LeaveEligibilityNote.staff_id == snapshot.staff_id,
                    LeaveEligibilityNote.leave_type_id == leave_type.id,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing_note is not None:
            continue

        rule = rules_by_code.get(result.leave_type_code)
        accrues = bool(rule and rule.accrues)
        entitlement_weeks = (
            rule.entitlement_weeks if rule and rule.entitlement_weeks else None
        )

        accrued_hours = Decimal("0.00")

        # --- Ensure a balance row exists (create with zeros if missing). ------
        balance = (
            await db.execute(
                select(LeaveBalance).where(
                    LeaveBalance.staff_id == snapshot.staff_id,
                    LeaveBalance.leave_type_id == leave_type.id,
                )
            )
        ).scalar_one_or_none()
        if balance is None:
            balance = LeaveBalance(
                org_id=snapshot.org_id,
                staff_id=snapshot.staff_id,
                leave_type_id=leave_type.id,
                accrued_hours=Decimal("0"),
                used_hours=Decimal("0"),
                pending_hours=Decimal("0"),
                anniversary_date=snapshot.employment_start_date,
            )
            db.add(balance)
            await db.flush()

        # --- Accruing rule: append a ledger row (idempotent on occurred_at). --
        if accrues and entitlement_weeks is not None:
            already = (
                await db.execute(
                    select(LeaveLedger.id).where(
                        LeaveLedger.staff_id == snapshot.staff_id,
                        LeaveLedger.leave_type_id == leave_type.id,
                        LeaveLedger.reason == "accrual",
                        LeaveLedger.occurred_at == evaluation_date,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if already is None:
                accrued_hours = (weekly_hours * Decimal(entitlement_weeks)).quantize(
                    Decimal("0.01")
                )
                db.add(
                    LeaveLedger(
                        org_id=snapshot.org_id,
                        staff_id=snapshot.staff_id,
                        leave_type_id=leave_type.id,
                        delta_hours=accrued_hours,
                        reason="accrual",
                        request_id=None,
                        occurred_at=evaluation_date,
                        created_by=None,
                    )
                )
                balance.accrued_hours = Decimal(balance.accrued_hours) + accrued_hours
                balance.last_accrual_at = datetime.now(timezone.utc)
                balance.updated_at = datetime.now(timezone.utc)

        # --- Insert the eligibility note (one per staff×type ever). ----------
        hours_test_met = (
            result.hours_test.met if result.hours_test is not None else None
        )
        condition = _condition_text(
            leave_type.name, result.milestone_key, hours_test_met, evaluation_date
        )
        note = LeaveEligibilityNote(
            org_id=snapshot.org_id,
            staff_id=snapshot.staff_id,
            leave_type_id=leave_type.id,
            rule_set_version=result.rule_set_version,
            milestone_key=result.milestone_key,
            hours_test_met=hours_test_met,
            condition_text=condition,
            vested_on=evaluation_date,
        )
        db.add(note)
        await db.flush()

        # --- Eligibility-onset in-app notification (best-effort, de-duped). ---
        notification_id = await create_in_app_notification(
            db,
            org_id=snapshot.org_id,
            category="leave_eligibility",
            severity="info",
            title=f"{leave_type.name} now available",
            body=condition,
            audience_roles=["org_admin", "branch_admin"],
            link_url="/leave/balances",
            entity_type="leave_eligibility",
            entity_id=note.id,
        )

        outcomes.append(
            VestingOutcome(
                leave_type_id=leave_type.id,
                leave_type_code=leave_type.code,
                vested=True,
                accrued_hours=accrued_hours,
                note_id=note.id,
                notification_id=notification_id,
            )
        )

    return outcomes
