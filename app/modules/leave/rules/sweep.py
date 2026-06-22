"""Scheduled eligibility sweep + on-demand single-staff evaluator.

``evaluate_leave_eligibility_task`` is the daily WRITE task: it walks every active
staff in every org with ``staff_management`` enabled, builds a ``StaffSnapshot``,
resolves the rule-set for today, evaluates eligibility, and applies vesting
idempotently. Per-org RLS is set per the staff's org; repeat-day runs are no-ops
(the applier's note/ledger idempotency guards).

``evaluate_one_staff`` is the on-demand path called from the staff service when a
staff member is created or their ``employment_start_date`` is set/changed, so
day-one entitlements and already-passed milestones vest immediately rather than
waiting for the nightly tick.

**Validates: Requirements 5.4, 6.3, 7.4, 8.5, 9.5, 9.7, 10.1, 10.4, 12.1, 13.1**
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leave.rules.eligibility import evaluate_eligibility
from app.modules.leave.rules.hours_test import aggregate_hours_test_input
from app.modules.leave.rules.registry import NoApplicableRuleSet, resolve_rule_set
from app.modules.leave.rules.service_period import StaffSnapshot
from app.modules.leave.rules.vesting import VestingOutcome, apply_vesting

logger = logging.getLogger(__name__)

__all__ = ["build_staff_snapshot", "evaluate_one_staff", "evaluate_leave_eligibility_task"]


def _fixed_term_months(staff) -> int | None:
    if (staff.employment_type or "") != "fixed_term":
        return None
    start = getattr(staff, "employment_start_date", None)
    end = getattr(staff, "employment_end_date", None)
    if start is None or end is None:
        return None
    return (end.year - start.year) * 12 + (end.month - start.month)


async def build_staff_snapshot(
    db: AsyncSession, staff, *, evaluation_date: date
) -> StaffSnapshot:
    """Assemble the pure-core ``StaffSnapshot`` from a ``StaffMember`` ORM row."""
    hours_input = await aggregate_hours_test_input(
        db, staff_id=staff.id, evaluation_date=evaluation_date
    )
    return StaffSnapshot(
        staff_id=staff.id,
        org_id=staff.org_id,
        employment_start_date=getattr(staff, "employment_start_date", None),
        employment_type=staff.employment_type or "",
        standard_hours_per_week=getattr(staff, "standard_hours_per_week", None),
        holiday_pay_method=getattr(staff, "holiday_pay_method", "accrued") or "accrued",
        fixed_term_months=_fixed_term_months(staff),
        hours_test_input=hours_input,
    )


async def evaluate_one_staff(
    db: AsyncSession, staff_id: uuid.UUID, today: date
) -> list[VestingOutcome]:
    """Evaluate + vest a single staff member (on-demand). Idempotent."""
    from app.modules.staff.models import StaffMember

    staff = await db.get(StaffMember, staff_id)
    if staff is None:
        return []
    snapshot = await build_staff_snapshot(db, staff, evaluation_date=today)
    try:
        rule_set = resolve_rule_set(today)
    except NoApplicableRuleSet:
        logger.warning(
            "evaluate_one_staff: no applicable rule-set for %s (staff=%s)",
            today, staff_id,
        )
        return []
    results = evaluate_eligibility(snapshot, today, rule_set)
    return await apply_vesting(
        db,
        snapshot=snapshot,
        results=results,
        evaluation_date=today,
        rule_set=rule_set,
    )


async def evaluate_leave_eligibility_task() -> dict:
    """Daily sweep across all active staff in all staff-management orgs.

    Mirrors the ``accrue_leave`` task: per-org session with RLS bounded to the
    tenant, per-staff SAVEPOINT so one failure doesn't poison the batch. Repeat
    runs are idempotent no-ops.
    """
    from sqlalchemy import select

    from app.core.database import _set_rls_org_id, async_session_factory
    from app.modules.admin.models import Organisation
    from app.modules.module_management.models import OrgModule
    from app.modules.staff.models import StaffMember

    today = date.today()
    summary = {"orgs_processed": 0, "staff_processed": 0, "vested": 0, "errors": 0}

    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    select(Organisation.id)
                    .join(OrgModule, OrgModule.org_id == Organisation.id)
                    .where(
                        OrgModule.module_slug == "staff_management",
                        OrgModule.is_enabled.is_(True),
                    )
                )
                org_ids = [row[0] for row in (await session.execute(stmt)).all()]
    except Exception as exc:
        logger.exception("evaluate_leave_eligibility: failed to load orgs: %s", exc)
        return {"error": str(exc)}

    if not org_ids:
        return summary

    for org_id in org_ids:
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    await _set_rls_org_id(session, str(org_id))
                    staff_list = list(
                        (
                            await session.execute(
                                select(StaffMember).where(
                                    StaffMember.org_id == org_id,
                                    StaffMember.is_active.is_(True),
                                )
                            )
                        ).scalars().all()
                    )
                    for staff in staff_list:
                        summary["staff_processed"] += 1
                        try:
                            savepoint = await session.begin_nested()
                        except Exception:
                            summary["errors"] += 1
                            continue
                        try:
                            outcomes = await evaluate_one_staff(
                                session, staff.id, today
                            )
                            summary["vested"] += len(outcomes)
                        except Exception as exc:
                            await savepoint.rollback()
                            summary["errors"] += 1
                            logger.warning(
                                "evaluate_leave_eligibility: org=%s staff=%s error=%s",
                                org_id, staff.id, exc,
                            )
            summary["orgs_processed"] += 1
        except Exception:
            logger.exception(
                "evaluate_leave_eligibility: org=%s batch failed", org_id
            )
            summary["errors"] += 1

    logger.info(
        "evaluate_leave_eligibility: orgs=%d staff=%d vested=%d errors=%d",
        summary["orgs_processed"], summary["staff_processed"],
        summary["vested"], summary["errors"],
    )
    return summary
