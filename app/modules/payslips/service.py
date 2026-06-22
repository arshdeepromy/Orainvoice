"""Payslips service layer — generate / finalise / void / email / reopen.

Implements task B4 from ``.kiro/specs/staff-management-p4/tasks.md``.
This module owns the write-side of the payroll surface. Heavy lifting
(wage math, PDF render, encrypted PDF storage, termination payouts)
lives in sibling modules; this file orchestrates them.

Public surface:

  - :func:`generate_for_period` — one DRAFT per active staff. Auto-
    attaches recurring allowances per G4. Idempotent on re-run via
    the ``payslips`` UNIQUE ``(staff_id, pay_period_id)`` constraint.
  - :func:`recompute_payslip` — re-run the math on a draft after
    admin edits.
  - :func:`finalise_payslip` — render PDF, store encrypted, set
    ``status='finalised'``, audit ``payslip.finalised``.
  - :func:`void_payslip` — flip to ``voided``; refuses 409 when the
    parent period is finalised (admin must reopen first per G21).
  - :func:`email_payslip` — send PDF via :func:`send_email` with
    ``dlq_task_name='payslip_email'`` (R8).
  - :func:`bulk_finalise_period` — iterate drafts with
    ``SAVEPOINT`` per payslip so one failure doesn't abort the
    batch (R9).
  - :func:`reopen_pay_period` — G21 / R1a flow.
  - :func:`update_payslip_fields` — column-allowlist update with
    P4-N26 enforcement.

All write paths use ``await db.flush()`` + ``await db.refresh(obj)``;
never ``commit()`` (the request transaction is owned by
``get_db_session`` per project-overview.md).

**Validates: Requirements R1, R1a, R3, R4, R6, R8, R9 — Staff
Management Phase 4 task B4.**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.payslips.calc import (
    PayslipCalc,
    _resolve_allowance_quantity,
    compute_gross_ytd,
    compute_payslip,
)
from app.modules.payslips.models import (
    AllowanceType,
    PayPeriod,
    Payslip,
    PayslipAllowance,
    PayslipDeduction,
    PayslipReimbursement,
    StaffRecurringAllowance,
)
from app.modules.payslips.pdf import render_pdf
from app.modules.payslips.pdf_storage import store_payslip_pdf
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


__all__ = [
    "PayslipServiceError",
    "PayslipNotFoundError",
    "PayPeriodNotFoundError",
    "PayslipImmutableError",
    "PeriodAlreadyPaidError",
    "PeriodAlreadyOpenError",
    "PeriodFinalisedError",
    "StaffEmailMissingError",
    "PayslipNotFinalisedError",
    "generate_for_period",
    "recompute_payslip",
    "finalise_payslip",
    "void_payslip",
    "email_payslip",
    "bulk_finalise_period",
    "reopen_pay_period",
    "update_payslip_fields",
]


# ---------------------------------------------------------------------------
# Service-layer exceptions (router maps each to the documented HTTP code)
# ---------------------------------------------------------------------------


class PayslipServiceError(Exception):
    """Base class for all payslips service errors."""


class PayslipNotFoundError(PayslipServiceError):
    """Raised when a payslip_id doesn't exist or belongs to a
    different org. Router maps to HTTP 404.
    """


class PayPeriodNotFoundError(PayslipServiceError):
    """Raised when a pay_period_id doesn't exist or belongs to a
    different org. Router maps to HTTP 404.
    """


class PayslipImmutableError(PayslipServiceError):
    """Raised when an UPDATE/DELETE is attempted on a finalised
    payslip outside the column-allowlist (P4-N26). Router maps to
    HTTP 409.
    """


class PeriodAlreadyPaidError(PayslipServiceError):
    """Raised by :func:`reopen_pay_period` when the period is already
    in ``status='paid'``. Router maps to HTTP 409
    ``period_already_paid``.
    """


class PeriodAlreadyOpenError(PayslipServiceError):
    """Raised by :func:`reopen_pay_period` when the period is already
    ``status='open'``. Router maps to HTTP 422.
    """


class PeriodFinalisedError(PayslipServiceError):
    """Raised by :func:`void_payslip` when the parent pay_period is
    finalised — admin must reopen first per G21. Router maps to HTTP
    409.
    """


class StaffEmailMissingError(PayslipServiceError):
    """Raised by :func:`email_payslip` when the staff has no email
    address on file. Router maps to HTTP 422.
    """


class PayslipNotFinalisedError(PayslipServiceError):
    """Raised by :func:`email_payslip` when the payslip is still a
    draft. Router maps to HTTP 422.
    """


# ---------------------------------------------------------------------------
# Audit helpers (G12 + P4-N32 — redacted dicts only)
# ---------------------------------------------------------------------------


def _redacted_payslip_event(
    payslip: Payslip, *, action: str, **extra: Any,
) -> dict[str, Any]:
    """Build a redacted ``after_value`` dict for a payslip-event audit
    row per G12 + design §4.5.

    The base shape is ``{ payslip_id, staff_id, pay_period_id }``.
    Action-specific extras are appended via ``**extra`` — the caller
    is responsible for ensuring those keys are NOT in the forbidden
    set (gross_pay, net_pay, amount, ird_number, bank_account_number,
    paye, s27_lump_sum, recipient_email, etc.).
    """
    base: dict[str, Any] = {
        "payslip_id": str(payslip.id),
        "staff_id": str(payslip.staff_id),
        "pay_period_id": str(payslip.pay_period_id),
    }
    base.update(extra)
    return base


def _domain_only(email: str | None) -> str | None:
    """Return the domain tail of an email (``@example.com``) or
    ``None``. Used for the ``recipient_email_domain_only`` audit
    field (G12) so the full recipient address never lands in
    ``audit_log``.
    """
    if not email:
        return None
    if "@" not in email:
        return None
    _, _, tail = email.partition("@")
    return f"@{tail.strip().lower()}" if tail else None


# ---------------------------------------------------------------------------
# Internal: total recompute on a draft
# ---------------------------------------------------------------------------


def _apply_calc_to_payslip(payslip: Payslip, calc: PayslipCalc) -> None:
    """Copy the numeric outputs from a :class:`PayslipCalc` into the
    Payslip ORM row. Caller flushes + refreshes.
    """
    payslip.ordinary_hours = calc.ordinary_hours
    payslip.overtime_hours = calc.overtime_hours
    payslip.public_holiday_hours = calc.public_holiday_hours
    if calc.ordinary_rate is not None:
        payslip.ordinary_rate = calc.ordinary_rate
    if calc.overtime_rate is not None:
        payslip.overtime_rate = calc.overtime_rate
    if calc.public_holiday_rate is not None:
        payslip.public_holiday_rate = calc.public_holiday_rate
    payslip.gross_pay = calc.gross
    payslip.gross_ytd = calc.gross_ytd
    payslip.net_pay = calc.net


async def deduction_subtotals_for(
    db: AsyncSession,
    payslip_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Decimal]]:
    """Aggregate ``payslip_deductions`` into per-payslip, per-kind sums.

    Returns ``{ payslip_id: { kind: summed_amount, ... } }`` containing
    only the kinds present for each payslip — the router fills absent
    kinds from the schema's per-field zero defaults when it constructs
    ``PayslipDeductionSubtotals``. Derived purely from the existing
    deduction rows (the source of truth), so the subtotals can never
    drift from the lines.

    One grouped query regardless of how many payslips are passed (no
    N+1). The caller supplies ids drawn only from org-scoped payslip
    selects, and ``payslip_deductions`` is RLS-scoped, so no cross-org
    line is ever aggregated.
    """
    if not payslip_ids:
        return {}

    rows = (
        await db.execute(
            select(
                PayslipDeduction.payslip_id,
                PayslipDeduction.kind,
                func.sum(PayslipDeduction.amount),
            )
            .where(PayslipDeduction.payslip_id.in_(payslip_ids))
            .group_by(PayslipDeduction.payslip_id, PayslipDeduction.kind)
        )
    ).all()

    result: dict[uuid.UUID, dict[str, Decimal]] = {}
    for payslip_id, kind, amount in rows:
        result.setdefault(payslip_id, {})[kind] = amount or Decimal("0")
    return result


async def _attach_kiwisaver_lines(
    db: AsyncSession,
    *,
    payslip: Payslip,
    calc: PayslipCalc,
    staff: StaffMember,
) -> None:
    """Insert / refresh KiwiSaver employee + employer deduction rows
    (R6). Idempotent — re-running on a draft removes any prior
    auto-generated KiwiSaver rows first then inserts new ones with
    the freshly-computed amounts.
    """
    if not staff.kiwisaver_enrolled:
        return
    # Delete any existing auto-generated KiwiSaver rows for this
    # payslip — the labels are stable so we can safely identify ours.
    await db.execute(
        PayslipDeduction.__table__.delete().where(
            and_(
                PayslipDeduction.payslip_id == payslip.id,
                PayslipDeduction.kind.in_(
                    ("kiwisaver_employee", "kiwisaver_employer"),
                ),
            )
        )
    )
    if calc.kiwisaver_employee > 0:
        db.add(
            PayslipDeduction(
                payslip_id=payslip.id,
                kind="kiwisaver_employee",
                label="KiwiSaver employee contribution",
                amount=calc.kiwisaver_employee,
            )
        )
    if calc.kiwisaver_employer > 0:
        db.add(
            PayslipDeduction(
                payslip_id=payslip.id,
                kind="kiwisaver_employer",
                label="KiwiSaver employer contribution (informational)",
                amount=calc.kiwisaver_employer,
            )
        )
    await db.flush()


async def _attach_casual_8pct_line(
    db: AsyncSession,
    *,
    payslip: Payslip,
    calc: PayslipCalc,
) -> None:
    """Insert / refresh the casual-8% holiday-pay-as-you-go allowance
    line (R5). Removed entirely when ``calc.casual_8pct == 0`` per
    N17 (omit zero-amount lines).
    """
    # Delete any prior auto-generated casual-8pct line on this draft.
    await db.execute(
        PayslipAllowance.__table__.delete().where(
            and_(
                PayslipAllowance.payslip_id == payslip.id,
                PayslipAllowance.label.ilike("casual%8%"),
            )
        )
    )
    if calc.casual_8pct > 0:
        db.add(
            PayslipAllowance(
                payslip_id=payslip.id,
                allowance_type_id=None,
                label="Casual 8% holiday pay (s28)",
                quantity=Decimal("1"),
                unit="period",
                amount=calc.casual_8pct,
                taxable=True,
            )
        )
    await db.flush()


async def _attach_statutory_lines(
    db: AsyncSession,
    *,
    payslip: Payslip,
    calc: PayslipCalc,
) -> None:
    """Insert / refresh the auto-computed statutory deduction lines —
    PAYE income tax, ACC earner levy, and student-loan repayment.

    Idempotent: removes any prior auto-generated rows (identified by
    their stable labels) before inserting fresh amounts, so re-running
    on a draft never double-counts and never clobbers admin-entered
    deductions that use different labels.
    """
    auto_labels = (
        "PAYE income tax",
        "ACC earner levy",
        "Student loan repayment",
    )
    await db.execute(
        PayslipDeduction.__table__.delete().where(
            and_(
                PayslipDeduction.payslip_id == payslip.id,
                PayslipDeduction.label.in_(auto_labels),
            )
        )
    )
    if calc.paye > 0:
        db.add(
            PayslipDeduction(
                payslip_id=payslip.id,
                kind="paye",
                label="PAYE income tax",
                amount=calc.paye,
            )
        )
    if calc.acc_levy > 0:
        db.add(
            PayslipDeduction(
                payslip_id=payslip.id,
                kind="acc_levy",
                label="ACC earner levy",
                amount=calc.acc_levy,
            )
        )
    if calc.student_loan > 0:
        db.add(
            PayslipDeduction(
                payslip_id=payslip.id,
                kind="student_loan",
                label="Student loan repayment",
                amount=calc.student_loan,
            )
        )
    await db.flush()


async def recompute_payslip(
    db: AsyncSession,
    *,
    payslip: Payslip,
    staff: StaffMember,
    period: PayPeriod,
) -> PayslipCalc:
    """Re-run the math on a draft payslip after an admin edit.

    Updates the four numeric columns on ``payslips``, refreshes the
    auto-generated KiwiSaver + casual-8% lines, and returns the
    :class:`PayslipCalc`. Caller must flush after if they want the
    refresh-load to see the lines.
    """
    if payslip.status == "finalised":
        raise PayslipImmutableError(
            "payslip is finalised — only emailed_at may change",
        )
    # First pass — get the math without the auto-generated rows.
    calc = await compute_payslip(db, staff, period, payslip=payslip)
    # Attach / refresh KiwiSaver + casual-8% + statutory (PAYE/ACC/SL) rows.
    await _attach_kiwisaver_lines(db, payslip=payslip, calc=calc, staff=staff)
    await _attach_casual_8pct_line(db, payslip=payslip, calc=calc)
    await _attach_statutory_lines(db, payslip=payslip, calc=calc)
    # Second pass — recompute now that the lines are attached so the
    # totals reflect the freshly-inserted KiwiSaver / casual / statutory lines.
    calc = await compute_payslip(db, staff, period, payslip=payslip)
    _apply_calc_to_payslip(payslip, calc)
    await db.flush()
    await db.refresh(payslip)
    return calc


# ---------------------------------------------------------------------------
# Recurring allowance attach (G4)
# ---------------------------------------------------------------------------


async def _auto_attach_recurring_allowances(
    db: AsyncSession,
    *,
    payslip: Payslip,
    staff: StaffMember,
    period: PayPeriod,
) -> None:
    """Look up active recurring rules for the staff and attach a
    ``payslip_allowances`` row per match (G4 + R3.5).

    Skips rules whose allowance_type is missing or inactive. Skips
    rules that already have a corresponding row on the payslip
    (idempotent — re-generating drafts on the same period doesn't
    duplicate lines).
    """
    rules = (
        await db.execute(
            select(StaffRecurringAllowance)
            .where(
                StaffRecurringAllowance.staff_id == staff.id,
                StaffRecurringAllowance.active.is_(True),
            )
        )
    ).scalars().all()
    if not rules:
        return

    # Pre-load the allowance types in one round-trip.
    type_ids = {r.allowance_type_id for r in rules}
    types_by_id = {
        t.id: t
        for t in (
            await db.execute(
                select(AllowanceType).where(AllowanceType.id.in_(type_ids))
            )
        ).scalars().all()
    }

    # Pre-load existing allowance rows so we don't duplicate.
    existing_type_ids = {
        row.allowance_type_id
        for row in (
            await db.execute(
                select(PayslipAllowance.allowance_type_id).where(
                    PayslipAllowance.payslip_id == payslip.id,
                    PayslipAllowance.allowance_type_id.is_not(None),
                )
            )
        ).all()
    }

    for rule in rules:
        atype = types_by_id.get(rule.allowance_type_id)
        if atype is None or not atype.active:
            continue
        if rule.allowance_type_id in existing_type_ids:
            continue
        quantity, amount, _source = await _resolve_allowance_quantity(
            db,
            allowance_type=atype,
            recurring_rule=rule,
            staff_id=staff.id,
            period=period,
        )
        db.add(
            PayslipAllowance(
                payslip_id=payslip.id,
                allowance_type_id=atype.id,
                label=atype.name,
                quantity=quantity,
                unit=atype.unit,  # G18: copy unit at attach time
                amount=amount,
                taxable=bool(atype.taxable),
            )
        )
    await db.flush()


# ---------------------------------------------------------------------------
# generate_for_period
# ---------------------------------------------------------------------------


async def generate_for_period(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    staff_ids: list[uuid.UUID] | None = None,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> list[Payslip]:
    """Create one DRAFT payslip per active staff in ``staff_ids`` (or
    all active staff in the org when ``staff_ids`` is ``None``).

    Cycle-scoping: when ``staff_ids is None`` and the period carries a
    ``pay_cycle_id`` (a multi-cycle org), the bulk path is restricted to
    active staff whose RESOLVED pay cycle equals the period's cycle. A
    legacy period (``pay_cycle_id is None``) still drafts for all active
    staff, and an explicit ``staff_ids`` list is never cycle-filtered (the
    caller chose those staff deliberately — e.g. the termination path).

    Idempotent: re-running on a period with existing drafts is a
    no-op for those staff (UNIQUE on ``(staff_id, pay_period_id)``);
    only NEW drafts are created. Each draft has the recurring
    allowance lines auto-attached (G4) and the math run before
    return.

    Raises:
      :class:`PayPeriodNotFoundError` — period_id missing or wrong org.
    """
    period = await db.get(PayPeriod, period_id)
    if period is None or period.org_id != org_id:
        raise PayPeriodNotFoundError("pay_period not found")
    if period.status != "open":
        # We allow generation on open + finalised (admin reopen +
        # generate); only `paid` blocks generation.
        if period.status == "paid":
            raise PeriodAlreadyPaidError("period_already_paid")

    # Resolve staff list.
    base_stmt = select(StaffMember).where(
        StaffMember.org_id == org_id,
        StaffMember.is_active.is_(True),
    )
    if staff_ids:
        base_stmt = base_stmt.where(StaffMember.id.in_(staff_ids))
    staff_rows = list((await db.execute(base_stmt)).scalars().all())

    # Cycle-scope the bulk "generate for the whole period" path. When the
    # period belongs to a pay cycle AND the caller didn't name explicit
    # staff, restrict the active-staff list to staff whose RESOLVED pay
    # cycle matches this period's cycle — otherwise a multi-cycle org would
    # draft a payslip for every active staff regardless of cycle.
    #
    # When the caller passes explicit ``staff_ids`` (e.g. the termination
    # payout path) we deliberately DO NOT apply the cycle filter: the caller
    # has chosen exactly which staff to draft for. Likewise a legacy period
    # with ``pay_cycle_id is None`` preserves the original behaviour (all
    # active staff), so existing single-cycle orgs are unaffected.
    if period.pay_cycle_id is not None and staff_ids is None and staff_rows:
        # Local import avoids any import cycle (mirrors the codebase's
        # existing local-import style for cross-module service calls).
        from app.modules.timesheets.pay_cycles import (
            resolve_pay_cycles_for_staff_batch,
        )

        resolved = await resolve_pay_cycles_for_staff_batch(
            db, org_id=org_id, staff_members=staff_rows,
        )
        staff_rows = [
            staff
            for staff in staff_rows
            if (rc := resolved.get(staff.id)) is not None
            and rc.cycle.id == period.pay_cycle_id
        ]

    created: list[Payslip] = []

    for staff in staff_rows:
        # Try to insert; if UNIQUE violation, skip silently (P4-N28).
        # The insert is wrapped in a SAVEPOINT so a duplicate hit
        # only rolls back the failed insert (not the surrounding
        # transaction owned by ``get_db_session``).
        try:
            async with db.begin_nested():
                payslip = Payslip(
                    org_id=org_id,
                    staff_id=staff.id,
                    pay_period_id=period_id,
                    status="draft",
                    ordinary_hours=Decimal("0"),
                    overtime_hours=Decimal("0"),
                    public_holiday_hours=Decimal("0"),
                    ordinary_rate=staff.hourly_rate,
                    overtime_rate=staff.overtime_rate,
                    gross_pay=Decimal("0"),
                    gross_ytd=Decimal("0"),
                    net_pay=Decimal("0"),
                )
                db.add(payslip)
                await db.flush()
        except IntegrityError:
            # Duplicate (staff already has a draft for this period).
            existing = (
                await db.execute(
                    select(Payslip).where(
                        Payslip.staff_id == staff.id,
                        Payslip.pay_period_id == period_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                created.append(existing)
            continue

        await db.refresh(payslip)
        await _auto_attach_recurring_allowances(
            db, payslip=payslip, staff=staff, period=period,
        )
        await recompute_payslip(
            db, payslip=payslip, staff=staff, period=period,
        )

        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="payslip.generated",
            entity_type="payslip",
            entity_id=payslip.id,
            after_value=_redacted_payslip_event(
                payslip,
                action="payslip.generated",
                source="auto",
            ),
            ip_address=ip_address,
        )
        created.append(payslip)

    return created


# ---------------------------------------------------------------------------
# finalise_payslip
# ---------------------------------------------------------------------------


async def finalise_payslip(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payslip_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> Payslip:
    """Render the PDF, store it encrypted, set status='finalised', and
    audit the event.

    Re-computes the math one last time (defensive — admin may have
    edited the draft and the totals could be stale).

    Raises:
      :class:`PayslipNotFoundError` — payslip_id missing or wrong org.
      :class:`PayslipImmutableError` — already finalised/voided.
    """
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None or payslip.org_id != org_id:
        raise PayslipNotFoundError("payslip not found")
    if payslip.status == "finalised":
        raise PayslipImmutableError("payslip already finalised")
    if payslip.status == "voided":
        raise PayslipImmutableError("payslip is voided")

    # Final recompute before lock.
    staff = await db.get(StaffMember, payslip.staff_id)
    period = await db.get(PayPeriod, payslip.pay_period_id)
    if staff is None or period is None:
        raise PayslipNotFoundError("payslip context missing")
    await recompute_payslip(db, payslip=payslip, staff=staff, period=period)

    # Render + store the PDF.
    pdf_bytes = await render_pdf(db, payslip.id)
    file_key = store_payslip_pdf(
        pdf_bytes,
        org_id=str(org_id),
        payslip_id=str(payslip.id),
    )

    payslip.pdf_file_key = file_key
    payslip.status = "finalised"
    payslip.finalised_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(payslip)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payslip.finalised",
        entity_type="payslip",
        entity_id=payslip.id,
        after_value=_redacted_payslip_event(
            payslip,
            action="payslip.finalised",
            finalised_at=payslip.finalised_at.isoformat() if payslip.finalised_at else None,
            pdf_file_key=payslip.pdf_file_key,
        ),
        ip_address=ip_address,
    )
    return payslip


# ---------------------------------------------------------------------------
# void_payslip
# ---------------------------------------------------------------------------


async def void_payslip(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payslip_id: uuid.UUID,
    reason: str,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> Payslip:
    """Flip a payslip to ``status='voided'``.

    The parent pay_period must be ``open`` — when it's ``finalised``
    we refuse with HTTP 409 (admin reopens first via R1a / G21);
    when it's ``paid`` we also refuse (money's out, manual
    adjustment is the only path).

    Per design §4.2 this does NOT delete the encrypted PDF — auditors
    need the historical record.

    Raises:
      :class:`PayslipNotFoundError`.
      :class:`PeriodFinalisedError` — period needs reopening first.
      :class:`PeriodAlreadyPaidError` — period is paid.
    """
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None or payslip.org_id != org_id:
        raise PayslipNotFoundError("payslip not found")

    period = await db.get(PayPeriod, payslip.pay_period_id)
    if period is None:
        raise PayPeriodNotFoundError("pay_period not found")
    if period.status == "paid":
        raise PeriodAlreadyPaidError("period_already_paid")
    if period.status == "finalised":
        raise PeriodFinalisedError("period_finalised — reopen first")

    payslip.status = "voided"
    await db.flush()
    await db.refresh(payslip)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payslip.voided",
        entity_type="payslip",
        entity_id=payslip.id,
        after_value=_redacted_payslip_event(
            payslip,
            action="payslip.voided",
            reason=(reason or "")[:500],
        ),
        ip_address=ip_address,
    )
    return payslip


# ---------------------------------------------------------------------------
# email_payslip
# ---------------------------------------------------------------------------


async def email_payslip(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payslip_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> Payslip:
    """Send the rendered PDF as an email attachment via
    :func:`send_email`. Bumps ``emailed_at`` on success.

    Refuses 422 when the staff has no email address (R8.2) or the
    payslip is still a draft (no PDF to send).
    """
    from app.integrations.email_sender import (
        EmailAttachment,
        EmailMessage,
        send_email,
    )
    from app.modules.payslips.pdf_storage import read_payslip_pdf

    payslip = await db.get(Payslip, payslip_id)
    if payslip is None or payslip.org_id != org_id:
        raise PayslipNotFoundError("payslip not found")
    if payslip.status != "finalised":
        raise PayslipNotFinalisedError("payslip is not finalised")
    if not payslip.pdf_file_key:
        raise PayslipNotFinalisedError("payslip pdf missing")

    staff = await db.get(StaffMember, payslip.staff_id)
    if staff is None or not staff.email:
        raise StaffEmailMissingError("staff_email_missing")

    pdf_bytes = read_payslip_pdf(payslip.pdf_file_key, org_id=str(org_id))

    period = await db.get(PayPeriod, payslip.pay_period_id)
    period_label = (
        f"{period.start_date.isoformat()} to {period.end_date.isoformat()}"
        if period is not None
        else ""
    )
    filename = f"payslip-{payslip.id}.pdf"

    message = EmailMessage(
        to_email=staff.email,
        to_name=staff.name or "",
        subject=f"Your payslip — {period_label}",
        html_body=(
            "<p>Hi {name},</p>"
            "<p>Your payslip for <strong>{period}</strong> is attached.</p>"
            "<p>Retain this for your records — the figures are your "
            "official Wages Protection Act / Holidays Act s130A record.</p>"
        ).format(name=staff.first_name or staff.name or "there", period=period_label),
        text_body=(
            f"Your payslip for {period_label} is attached.\n"
            "Retain this for your records — the figures are your official "
            "Wages Protection Act / Holidays Act s130A record."
        ),
        attachments=[
            EmailAttachment(
                filename=filename,
                content=pdf_bytes,
                mime_type="application/pdf",
            )
        ],
        org_id=org_id,
    )
    result = await send_email(
        db,
        message,
        dlq_task_name="payslip_email",
        dlq_task_args={"payslip_id": str(payslip.id)},
    )
    if not result.success:
        # Caller's exception handler maps to 503 — surface the error.
        last = result.attempts[-1] if result.attempts else None
        raise PayslipServiceError(
            "email send failed: " + (last.error if last else "unknown")
        )

    payslip.emailed_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(payslip)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="payslip.emailed",
        entity_type="payslip",
        entity_id=payslip.id,
        after_value=_redacted_payslip_event(
            payslip,
            action="payslip.emailed",
            recipient_email_domain_only=_domain_only(staff.email),
        ),
        ip_address=ip_address,
    )
    return payslip


# ---------------------------------------------------------------------------
# bulk_finalise_period (R9)
# ---------------------------------------------------------------------------


async def bulk_finalise_period(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    email_all: bool = False,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict[str, Any]:
    """Finalise every draft in the period; optionally bulk-email.

    Each per-staff finalise wrapped in ``db.begin_nested()`` SAVEPOINT
    so a single failure (e.g. PDF render error) doesn't abort the
    batch (R9.4).

    Returns ``{ finalised: N, failed: [{staff_id, reason}, ...],
    emailed: M }``.
    """
    period = await db.get(PayPeriod, period_id)
    if period is None or period.org_id != org_id:
        raise PayPeriodNotFoundError("pay_period not found")

    drafts = list(
        (
            await db.execute(
                select(Payslip).where(
                    Payslip.org_id == org_id,
                    Payslip.pay_period_id == period_id,
                    Payslip.status == "draft",
                )
            )
        )
        .scalars()
        .all()
    )

    finalised_count = 0
    emailed_count = 0
    failures: list[dict[str, str]] = []

    for draft in drafts:
        try:
            async with db.begin_nested():
                await finalise_payslip(
                    db,
                    org_id=org_id,
                    payslip_id=draft.id,
                    user_id=user_id,
                    ip_address=ip_address,
                )
            finalised_count += 1
        except Exception as exc:  # noqa: BLE001 — we report per-staff.
            logger.warning(
                "bulk_finalise_period: staff=%s payslip=%s failed: %s",
                draft.staff_id,
                draft.id,
                exc,
            )
            failures.append(
                {"staff_id": str(draft.staff_id), "reason": str(exc)}
            )
            continue

        if email_all:
            try:
                async with db.begin_nested():
                    await email_payslip(
                        db,
                        org_id=org_id,
                        payslip_id=draft.id,
                        user_id=user_id,
                        ip_address=ip_address,
                    )
                emailed_count += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "bulk_finalise_period: email failed for staff=%s: %s",
                    draft.staff_id,
                    exc,
                )
                failures.append(
                    {"staff_id": str(draft.staff_id), "reason": f"email: {exc}"}
                )

    # Flip the period status to 'finalised' when every draft made it.
    if finalised_count == len(drafts) and drafts:
        period.status = "finalised"
        period.finalised_at = datetime.now(timezone.utc)
        await db.flush()
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="pay_period.finalised",
            entity_type="pay_period",
            entity_id=period.id,
            after_value={
                "pay_period_id": str(period.id),
                "finalised_at": (
                    period.finalised_at.isoformat() if period.finalised_at else None
                ),
                "drafts_finalised": finalised_count,
            },
            ip_address=ip_address,
        )

    return {
        "finalised": finalised_count,
        "failed": failures,
        "emailed": emailed_count,
    }


# ---------------------------------------------------------------------------
# reopen_pay_period (G21)
# ---------------------------------------------------------------------------


async def reopen_pay_period(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    period_id: uuid.UUID,
    reason: str,
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> PayPeriod:
    """Reopen a finalised pay period (R1a / G21).

    Refuses 409 ``period_already_paid`` when status is ``'paid'``;
    refuses 422 when already ``'open'``. Otherwise sets status='open',
    finalised_at=NULL, writes audit ``pay_period.reopened`` with
    ``{reopened_by, reason, originally_finalised_at}``.

    Existing finalised payslips inside the reopened period STAY
    locked (immutable per R3.4). The reopen only allows new
    compensating drafts or void+regen flows.
    """
    period = await db.get(PayPeriod, period_id)
    if period is None or period.org_id != org_id:
        raise PayPeriodNotFoundError("pay_period not found")
    if period.status == "paid":
        raise PeriodAlreadyPaidError("period_already_paid")
    if period.status == "open":
        raise PeriodAlreadyOpenError("period_already_open")

    originally_finalised_at = period.finalised_at
    period.status = "open"
    period.finalised_at = None
    await db.flush()
    await db.refresh(period)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="pay_period.reopened",
        entity_type="pay_period",
        entity_id=period.id,
        after_value={
            "pay_period_id": str(period.id),
            "reopened_by": str(user_id) if user_id else None,
            "reason": (reason or "")[:500],
            "originally_finalised_at": (
                originally_finalised_at.isoformat()
                if originally_finalised_at
                else None
            ),
        },
        ip_address=ip_address,
    )
    return period


# ---------------------------------------------------------------------------
# update_payslip_fields — column-allowlist (P4-N26 / B8)
# ---------------------------------------------------------------------------

#: Columns that are mutable on a ``status='finalised'`` payslip.
#: Per P4-N26, only ``emailed_at`` may be set after finalisation —
#: the email endpoint flips the timestamp without reopening.
_FINALISED_COLUMN_ALLOWLIST: frozenset[str] = frozenset({"emailed_at"})

#: Columns mutable on a ``status='draft'`` payslip via PATCH.
_DRAFT_COLUMN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "ordinary_hours",
        "overtime_hours",
        "public_holiday_hours",
        "ordinary_rate",
        "overtime_rate",
        "public_holiday_rate",
        "notes",
    }
)


async def update_payslip_fields(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    payslip_id: uuid.UUID,
    fields: dict[str, Any],
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> Payslip:
    """Apply a partial update to a payslip respecting the
    finalised / draft column allowlists (P4-N26 / B8).

    A ``status='finalised'`` payslip ONLY accepts updates to
    ``emailed_at`` (used internally by the email-payslip flow) —
    every other column triggers :class:`PayslipImmutableError`
    (HTTP 409).

    A ``status='voided'`` payslip is fully immutable.

    A ``status='draft'`` payslip accepts the documented edit
    surface (hours / rates / notes); the caller is expected to call
    :func:`recompute_payslip` afterwards to refresh totals.
    """
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None or payslip.org_id != org_id:
        raise PayslipNotFoundError("payslip not found")

    if payslip.status == "voided":
        raise PayslipImmutableError("payslip is voided")

    allowed = (
        _FINALISED_COLUMN_ALLOWLIST
        if payslip.status == "finalised"
        else _DRAFT_COLUMN_ALLOWLIST
    )
    rejected = [k for k in fields.keys() if k not in allowed]
    if rejected:
        raise PayslipImmutableError(
            "fields not allowed for this status: " + ", ".join(sorted(rejected))
        )

    for k, v in fields.items():
        setattr(payslip, k, v)

    await db.flush()
    await db.refresh(payslip)

    if payslip.status == "draft":
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="payslip.updated",
            entity_type="payslip",
            entity_id=payslip.id,
            after_value=_redacted_payslip_event(
                payslip,
                action="payslip.updated",
                fields_changed=sorted(fields.keys()),
            ),
            ip_address=ip_address,
        )
    return payslip


# Suppress "imported but unused" for symbols used solely as type hints
# inside subroutines.
_ = func
