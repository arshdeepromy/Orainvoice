"""Payslip wage math — single source of truth.

Implements task B3 from ``.kiro/specs/staff-management-p4/tasks.md``.
This module is the only place that computes a payslip's hour bands,
allowance amounts, KiwiSaver deductions, gross, and net. Both the
draft-generation flow in :mod:`app.modules.payslips.service` and the
final-payslip generation inside
:mod:`app.modules.payslips.termination` call into here so the math
stays consistent across every entry point.

Public surface:

  - :data:`PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER` (G2) — Holidays Act s50
    "time-and-a-half" baseline. Admin can override the resulting rate
    on a draft via :attr:`Payslip.public_holiday_rate`.
  - :class:`PayslipCalc` — dataclass returned by :func:`compute_payslip`
    with every numeric component the service / PDF / audit need.
  - :func:`compute_payslip` — the orchestrator. Loads the staff +
    period source data (timesheet_approvals, leave_lines, allowances,
    deductions), runs the math, and returns a :class:`PayslipCalc`.
  - :func:`_resolve_allowance_quantity` — G18 unit semantics with the
    concrete shift-count SQL per N20 (cross-phase X1: joins
    ``schedule_entries`` to ``timesheet_approvals`` on the week range,
    NOT a non-existent per-entry FK).
  - :func:`compute_gross_ytd` — N16 rolling tax-year sum used by
    every draft generation.

**Validates: Requirements R3, R4, R4a, R5, R6 — Staff Management
Phase 4 task B3.**
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Organisation
from app.modules.payslips.models import (
    AllowanceType,
    PayPeriod,
    Payslip,
    PayslipAllowance,
    PayslipDeduction,
    PayslipReimbursement,
    StaffRecurringAllowance,
)
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


__all__ = [
    "PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER",
    "PayslipCalc",
    "compute_payslip",
    "compute_gross_ytd",
    "compute_tax_year_start",
    "_resolve_allowance_quantity",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Holidays Act s50 "time-and-a-half" baseline applied to public-holiday
#: hours when admin has not overridden the rate on the draft (G2).
PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER: Decimal = Decimal("1.5")

#: Casual 8% holiday-pay-as-you-go rate (R5 — Holidays Act s28).
CASUAL_HOLIDAY_PAY_RATE: Decimal = Decimal("0.08")

#: Quantize target for currency-style fields. The DB columns are
#: ``numeric(12, 2)`` / ``numeric(10, 2)`` so we keep two decimal places
#: end-to-end to avoid 0.005 rounding drift.
_CENTS = Decimal("0.01")

#: NZ tax year fallback when the org row has no ``income_tax_year_end``
#: configured. 1 April → 31 March is the IRD default.
_DEFAULT_TAX_YEAR_END_MONTH = 3
_DEFAULT_TAX_YEAR_END_DAY = 31


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PayslipCalc:
    """Result of :func:`compute_payslip`.

    All fields are ``Decimal`` quantised to cents. The ``allowances``
    / ``deductions`` / ``reimbursements`` / ``leave_lines`` lists carry
    plain dicts ready for ``payslip_*`` row construction by the caller
    — :mod:`app.modules.payslips.service` translates them into ORM
    inserts inside the same transaction.
    """

    ordinary_hours: Decimal = Decimal(0)
    overtime_hours: Decimal = Decimal(0)
    public_holiday_hours: Decimal = Decimal(0)

    ordinary_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    public_holiday_rate: Decimal | None = None

    ordinary: Decimal = Decimal(0)
    overtime: Decimal = Decimal(0)
    public_holiday: Decimal = Decimal(0)

    allowances_taxable: Decimal = Decimal(0)
    allowances_non_taxable: Decimal = Decimal(0)
    casual_8pct: Decimal = Decimal(0)

    gross: Decimal = Decimal(0)
    gross_ytd: Decimal = Decimal(0)

    # Statutory deductions computed by the PAYE engine (period amounts).
    paye: Decimal = Decimal(0)
    acc_levy: Decimal = Decimal(0)
    student_loan: Decimal = Decimal(0)
    annualised_gross: Decimal = Decimal(0)

    deductions_total: Decimal = Decimal(0)
    reimbursements_total: Decimal = Decimal(0)
    net: Decimal = Decimal(0)

    kiwisaver_employee: Decimal = Decimal(0)
    kiwisaver_employer: Decimal = Decimal(0)

    # Pre-built dicts for the line-table inserts. Each dict matches the
    # corresponding ``payslip_*`` Pydantic Create schema field set so
    # the service can pass them straight through.
    allowances: list[dict[str, Any]] = field(default_factory=list)
    deductions: list[dict[str, Any]] = field(default_factory=list)
    reimbursements: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tax-year helpers (N16)
# ---------------------------------------------------------------------------


def compute_tax_year_start(*, pay_date: date, tax_year_end: date | None) -> date:
    """Return the start date of the NZ tax year that contains
    ``pay_date`` (N16).

    The NZ tax year runs 1 April → 31 March by default. ``tax_year_end``
    is read from ``organisations.income_tax_year_end`` (a date column
    where only the month/day matter — the year is conceptual). When
    the org has not set a custom end date we fall back to ``31 March``.

    Concretely: for ``pay_date = 5 April 2026`` and the default
    1 April / 31 March year, the start is ``1 April 2026`` (this
    payslip is in the new tax year). For ``pay_date = 28 March 2026``
    the start is ``1 April 2025`` (still in the prior year). The
    helper only ever returns a 1-April date because the NZ year end is
    immediately followed by the new year start the next day.
    """
    if tax_year_end is not None:
        end_month = tax_year_end.month
        end_day = tax_year_end.day
    else:
        end_month = _DEFAULT_TAX_YEAR_END_MONTH
        end_day = _DEFAULT_TAX_YEAR_END_DAY

    # The "year start" is one day after the end date. Compute that
    # naively against pay_date.year and adjust for January wrap.
    start_month = end_month + 1 if end_month < 12 else 1
    start_day = 1
    candidate = date(pay_date.year, start_month, start_day)
    if pay_date >= candidate:
        return candidate
    # pay_date is before the candidate start → the active year started
    # in the prior calendar year.
    return date(pay_date.year - 1, start_month, start_day)


# ---------------------------------------------------------------------------
# Quantize helpers
# ---------------------------------------------------------------------------


def _q(value: Decimal | int | float | str | None) -> Decimal:
    """Normalise ``value`` to a 2-dp Decimal. ``None``/missing → ``0``."""
    if value is None:
        return Decimal("0.00")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(_CENTS)


# ---------------------------------------------------------------------------
# Allowance quantity resolution (G18)
# ---------------------------------------------------------------------------


async def _count_approved_shifts(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> int:
    """Return the count of approved completed shifts for ``staff_id``
    inside ``[period_start, period_end]`` (G18 ``unit='shift'``).

    A "shift" is one ``schedule_entries`` row that:
      - falls inside ``[period_start, period_end + 1 day)``,
      - belongs to ``staff_id``,
      - has ``entry_type IN ('job','booking','other')``,
      - has ``status='completed'``,
      - falls inside an APPROVED week —
        ``timesheet_approvals.status='approved'`` covering the
        ``schedule_entries.start_time::date``.

    Cross-phase X1 fix: the join is on the week range, NOT on a
    per-entry FK (timesheet_approvals is week-based with UNIQUE
    ``(staff_id, week_start)`` — see P3 §3.1).
    """
    stmt = text(
        """
        SELECT COUNT(DISTINCT se.id)::int AS n
        FROM schedule_entries se
        JOIN timesheet_approvals ta
          ON ta.staff_id = se.staff_id
         AND se.start_time::date BETWEEN ta.week_start AND ta.week_end
        WHERE se.staff_id = :staff_id
          AND se.start_time >= :period_start
          AND se.start_time <  :period_end_plus_one_day
          AND se.entry_type IN ('job','booking','other')
          AND se.status = 'completed'
          AND ta.status = 'approved'
        """,
    )
    from datetime import datetime, time, timedelta, timezone

    period_start_dt = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    period_end_plus_one = datetime.combine(
        period_end + timedelta(days=1), time.min, tzinfo=timezone.utc,
    )
    result = await db.execute(
        stmt,
        {
            "staff_id": str(staff_id),
            "period_start": period_start_dt,
            "period_end_plus_one_day": period_end_plus_one,
        },
    )
    return int(result.scalar_one_or_none() or 0)


async def _resolve_allowance_quantity(
    db: AsyncSession,
    *,
    allowance_type: AllowanceType,
    recurring_rule: StaffRecurringAllowance | None,
    staff_id: uuid.UUID,
    period: PayPeriod,
) -> tuple[Decimal, Decimal, str]:
    """Return ``(quantity, amount, source_tag)`` for a recurring or
    auto-attached allowance line per G18.

    Semantics (from design §4.2):
      - ``unit='period'`` → quantity = 1; amount = override or
        default_amount.
      - ``unit='shift'``  → quantity = count of approved shifts in
        the period; amount = quantity × (override or default_amount).
      - ``unit='km'``     → quantity = recurring_rule.quantity (often
        0 — admin fills km on draft); amount = quantity × default.

    ``source_tag`` is one of ``'fixed'``, ``'shift_count'``,
    ``'km_entered'`` — matches :class:`AllowanceQuantityResolution`
    so the draft editor UI can render a tooltip explaining the
    derivation.
    """
    unit = (allowance_type.unit or "period").lower()
    base = (
        recurring_rule.amount
        if recurring_rule is not None and recurring_rule.amount is not None
        else allowance_type.default_amount
    )
    base_decimal = _q(base) if base is not None else Decimal("0.00")

    if unit == "period":
        return Decimal("1"), base_decimal, "fixed"

    if unit == "shift":
        n_shifts = await _count_approved_shifts(
            db,
            staff_id=staff_id,
            period_start=period.start_date,
            period_end=period.end_date,
        )
        quantity = Decimal(n_shifts)
        amount = (quantity * base_decimal).quantize(_CENTS)
        return quantity, amount, "shift_count"

    if unit == "km":
        raw_q = (
            recurring_rule.quantity
            if recurring_rule is not None and recurring_rule.quantity is not None
            else Decimal("0")
        )
        quantity = _q(raw_q)
        amount = (quantity * base_decimal).quantize(_CENTS)
        return quantity, amount, "km_entered"

    # Unknown unit — defensive fallback to fixed/period semantics.
    logger.warning(
        "calc._resolve_allowance_quantity: unknown unit=%s on allowance_type %s, "
        "treating as 'period'", unit, allowance_type.id,
    )
    return Decimal("1"), base_decimal, "fixed"


# ---------------------------------------------------------------------------
# Org overtime_handling helper (X4)
# ---------------------------------------------------------------------------


async def _resolve_overtime_handling(
    db: AsyncSession, org_id: uuid.UUID,
) -> str:
    """Return the org's ``overtime_handling`` typed-column value
    (cross-phase X4).

    P2-N5 + P3-N4 settled this as a typed text column on
    ``organisations``. The earlier ``_org_setting('overtime_handling',
    ...)`` JSONB-fallback helper was dead code and has been removed.
    The ``Organisation`` ORM model does not yet declare
    ``overtime_handling`` as a typed field, so we read directly via
    SQL — the ORM ``db.get(Organisation, ...)`` would fetch the row
    object but accessing ``.overtime_handling`` would raise
    ``AttributeError``. Use raw SQL until the ORM extension lands.
    """
    result = await db.execute(
        text(
            "SELECT overtime_handling FROM organisations "
            "WHERE id = :org_id"
        ),
        {"org_id": str(org_id)},
    )
    row = result.scalar_one_or_none()
    if not row or not isinstance(row, str):
        return "pay_cash"
    return row


# ---------------------------------------------------------------------------
# YTD helper (N16)
# ---------------------------------------------------------------------------


async def compute_gross_ytd(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    pay_date: date,
    tax_year_end: date | None,
    exclude_payslip_id: uuid.UUID | None = None,
) -> Decimal:
    """Return the staff's running YTD gross within the current NZ tax
    year (N16).

    ``gross_ytd = SUM(payslips.gross_pay) WHERE staff_id=:s AND
    status='finalised' AND pay_periods.pay_date BETWEEN
    :tax_year_start AND :pay_date``.

    Recomputed on every draft generation — never cached forever — so
    it stays correct across tax-year boundaries even when a draft
    generated on 5 April covers a period ending 28 March.

    ``exclude_payslip_id`` lets the caller exclude the draft itself
    (the draft is not yet finalised, so it would not be counted, but
    callers may pass this defensively when the draft has been
    pre-flushed with status='finalised' for unusual repair flows).
    """
    tax_year_start = compute_tax_year_start(
        pay_date=pay_date, tax_year_end=tax_year_end,
    )
    stmt = (
        select(Payslip.gross_pay, PayPeriod.pay_date)
        .join(PayPeriod, PayPeriod.id == Payslip.pay_period_id)
        .where(
            Payslip.staff_id == staff_id,
            Payslip.status == "finalised",
            PayPeriod.pay_date >= tax_year_start,
            PayPeriod.pay_date <= pay_date,
        )
    )
    if exclude_payslip_id is not None:
        stmt = stmt.where(Payslip.id != exclude_payslip_id)
    rows = (await db.execute(stmt)).all()
    total = Decimal("0")
    for row in rows:
        total += _q(row.gross_pay)
    return total.quantize(_CENTS)


# ---------------------------------------------------------------------------
# Hours aggregation
# ---------------------------------------------------------------------------


async def _aggregate_period_hours(
    db: AsyncSession,
    *,
    staff: StaffMember,
    period: PayPeriod,
) -> tuple[Decimal, Decimal, Decimal]:
    """Return ``(ordinary_hours, overtime_hours, public_holiday_hours)``
    for the staff member over the pay period.

    Two sources, in priority order:

      1. **Staff-timesheets surface** (the active system) — one
         :class:`~app.modules.timesheets.models.Timesheet` row per
         staff per pay period carries classified
         ``ordinary``/``overtime``/``public_holiday`` minutes. When a
         row exists for ``(staff, period)`` it is the source of truth.
         If the classified bands are all zero we fall back, in order,
         to: the configured rostered minutes (for ``fixed``-arrangement
         staff, who are paid their configured hours even without clock
         punches), then the effective worked minutes
         (``adjusted`` override, else ``actual``) treated as ordinary.

      2. **Legacy week-based ``timesheet_approvals``** — used only when
         no Timesheet row exists for the period (orgs that have not yet
         adopted the staff-timesheets surface). Sums every approved week
         whose ``[week_start, week_end]`` intersects the period.

    Note (legacy path): an approved week could span two pay periods. In
    that case BOTH periods would attribute the full week's hours to
    themselves on naive aggregation. Phase 4 accepts this small
    edge-case bias as documented under R12 / P4-N30 — the wage variance
    report (R12) surfaces any anomaly.
    """
    from app.modules.timesheets.models import Timesheet

    sixty = Decimal(60)

    # --- Source 1: staff-timesheets surface (active system) ---
    ts_row = (
        await db.execute(
            select(Timesheet).where(
                Timesheet.staff_id == staff.id,
                Timesheet.pay_period_id == period.id,
            )
        )
    ).scalar_one_or_none()

    if ts_row is not None:
        ordinary_min = ts_row.ordinary_minutes or 0
        overtime_min = ts_row.overtime_minutes or 0
        ph_min = ts_row.public_holiday_minutes or 0

        if ordinary_min == 0 and overtime_min == 0 and ph_min == 0:
            # No classified bands. Fixed-arrangement staff are paid
            # their configured rostered hours even without any clock
            # punches; everyone else falls back to the effective worked
            # minutes (adjusted override, else actual) as ordinary.
            arrangement = getattr(staff, "working_arrangement", None)
            rostered = ts_row.rostered_minutes or 0
            if arrangement == "fixed" and rostered > 0:
                ordinary_min = rostered
            else:
                effective = (
                    ts_row.adjusted_minutes
                    if ts_row.adjusted_minutes is not None
                    else ts_row.actual_minutes
                ) or 0
                ordinary_min = effective

        ordinary_hours = (Decimal(ordinary_min) / sixty).quantize(_CENTS)
        overtime_hours = (Decimal(overtime_min) / sixty).quantize(_CENTS)
        public_holiday_hours = (Decimal(ph_min) / sixty).quantize(_CENTS)
        return ordinary_hours, overtime_hours, public_holiday_hours

    # --- Source 2: legacy week-based timesheet_approvals ---
    stmt = text(
        """
        SELECT
            COALESCE(SUM(ordinary_minutes), 0)::int          AS ordinary_minutes,
            COALESCE(SUM(total_overtime_minutes), 0)::int    AS overtime_minutes,
            COALESCE(SUM(public_holiday_minutes), 0)::int    AS public_holiday_minutes
        FROM timesheet_approvals
        WHERE staff_id = :staff_id
          AND status = 'approved'
          AND week_start <= :period_end
          AND week_end   >= :period_start
        """,
    )
    result = await db.execute(
        stmt,
        {
            "staff_id": str(staff.id),
            "period_start": period.start_date,
            "period_end": period.end_date,
        },
    )
    row = result.one_or_none()
    if row is None:
        return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    ordinary_hours = (Decimal(row.ordinary_minutes or 0) / sixty).quantize(_CENTS)
    overtime_hours = (Decimal(row.overtime_minutes or 0) / sixty).quantize(_CENTS)
    public_holiday_hours = (
        Decimal(row.public_holiday_minutes or 0) / sixty
    ).quantize(_CENTS)
    return ordinary_hours, overtime_hours, public_holiday_hours


# ---------------------------------------------------------------------------
# compute_payslip — orchestrator
# ---------------------------------------------------------------------------


async def compute_payslip(
    db: AsyncSession,
    staff: StaffMember,
    period: PayPeriod,
    *,
    payslip: Payslip | None = None,
) -> PayslipCalc:
    """Single-source-of-truth computation for a payslip.

    Reads:
      - approved ``timesheet_approvals`` for the period → ordinary +
        overtime + public-holiday hour bands.
      - Existing ``payslip_allowances`` rows attached to the draft (if
        ``payslip`` is provided) — admin manual additions live here.
      - Existing ``payslip_deductions`` rows attached to the draft
        (PAYE, ACC, etc. — admin-entered).
      - Existing ``payslip_reimbursements`` rows.
      - ``staff.kiwisaver_*_rate`` for the auto-deduction lines.
      - ``staff.employment_type`` to decide whether the casual 8%
        line applies (R5).
      - The org's ``income_tax_year_end`` for the YTD window (N16).

    Writes nothing. The caller (service layer) decides whether to
    INSERT new rows for KiwiSaver / casual-8pct or to UPDATE the
    draft with the totals.

    ``payslip`` is optional — when ``None`` (e.g. previewing for a
    new draft) the calc returns a "fresh" projection with no
    existing allowance/deduction/reimbursement lines reflected. When
    provided, the calc uses the line lists already attached to that
    payslip as the source.
    """
    org_id = staff.org_id

    # ---------------- Hour bands ----------------
    ordinary_hours, overtime_hours, public_holiday_hours = (
        await _aggregate_period_hours(db, staff=staff, period=period)
    )

    ordinary_rate = _q(staff.hourly_rate) if staff.hourly_rate is not None else None
    overtime_rate = (
        _q(staff.overtime_rate)
        if staff.overtime_rate is not None
        else (
            (ordinary_rate * Decimal("1.5")).quantize(_CENTS)
            if ordinary_rate is not None
            else None
        )
    )

    # G2 — public_holiday_rate: admin override on draft wins; else
    # default to ordinary × 1.5 (Holidays Act s50). When ordinary_rate
    # is unknown we leave the rate as None and the band contributes
    # zero to gross — Phase 4 cannot compute money without an
    # underlying rate.
    if payslip is not None and payslip.public_holiday_rate is not None:
        public_holiday_rate = _q(payslip.public_holiday_rate)
    elif ordinary_rate is not None:
        public_holiday_rate = (
            ordinary_rate * PUBLIC_HOLIDAY_DEFAULT_MULTIPLIER
        ).quantize(_CENTS)
    else:
        public_holiday_rate = None

    ordinary = (
        (ordinary_hours * ordinary_rate).quantize(_CENTS)
        if ordinary_rate is not None
        else Decimal("0.00")
    )
    overtime = (
        (overtime_hours * overtime_rate).quantize(_CENTS)
        if overtime_rate is not None
        else Decimal("0.00")
    )
    public_holiday = (
        (public_holiday_hours * public_holiday_rate).quantize(_CENTS)
        if public_holiday_rate is not None
        else Decimal("0.00")
    )

    # ---------------- Allowances + reimbursements + deductions ----------------
    allowances: list[dict[str, Any]] = []
    reimbursements: list[dict[str, Any]] = []
    deductions: list[dict[str, Any]] = []

    if payslip is not None:
        # Pull existing line rows in their respective tables.
        a_rows = (
            await db.execute(
                select(PayslipAllowance).where(
                    PayslipAllowance.payslip_id == payslip.id,
                )
            )
        ).scalars().all()
        for a in a_rows:
            allowances.append(
                {
                    "id": a.id,
                    "allowance_type_id": a.allowance_type_id,
                    "label": a.label,
                    "quantity": _q(a.quantity),
                    "unit": a.unit,
                    "amount": _q(a.amount),
                    "taxable": bool(a.taxable),
                }
            )
        r_rows = (
            await db.execute(
                select(PayslipReimbursement).where(
                    PayslipReimbursement.payslip_id == payslip.id,
                )
            )
        ).scalars().all()
        for r in r_rows:
            reimbursements.append(
                {
                    "id": r.id,
                    "label": r.label,
                    "amount": _q(r.amount),
                }
            )
        d_rows = (
            await db.execute(
                select(PayslipDeduction).where(
                    PayslipDeduction.payslip_id == payslip.id,
                )
            )
        ).scalars().all()
        for d in d_rows:
            deductions.append(
                {
                    "id": d.id,
                    "kind": d.kind,
                    "label": d.label,
                    "amount": _q(d.amount),
                }
            )

    allowances_taxable = Decimal("0.00")
    allowances_non_taxable = Decimal("0.00")
    for a in allowances:
        if a.get("taxable"):
            allowances_taxable += _q(a["amount"])
        else:
            allowances_non_taxable += _q(a["amount"])

    # ---------------- Casual 8% (R5) ----------------
    casual_8pct = Decimal("0.00")
    if (staff.employment_type or "").lower() == "casual":
        # R5 — auto-attach 8% on wages-only earnings (excluding the
        # 8% line itself, to avoid recursion). Wages-only here is
        # ordinary + overtime + public_holiday + taxable allowances
        # ALREADY attached BUT excluding any prior casual_8pct line
        # (so re-running is idempotent).
        prior_8pct_total = Decimal("0.00")
        for a in allowances:
            if a.get("label") and "casual" in str(a["label"]).lower():
                prior_8pct_total += _q(a["amount"])
        wages_only = (
            ordinary + overtime + public_holiday + allowances_taxable
            - prior_8pct_total
        )
        if wages_only > 0:
            casual_8pct = (wages_only * CASUAL_HOLIDAY_PAY_RATE).quantize(_CENTS)
        # N17 — when casual employee has zero wages-only earnings, the
        # 8% line is OMITTED rather than $0.00. We only add the line
        # when casual_8pct > 0.

    # ---------------- Gross composition ----------------
    gross = (
        ordinary
        + overtime
        + public_holiday
        + allowances_taxable
        + casual_8pct
    ).quantize(_CENTS)

    # ---------------- KiwiSaver (R6) ----------------
    kiwisaver_employee = Decimal("0.00")
    kiwisaver_employer = Decimal("0.00")
    if staff.kiwisaver_enrolled:
        emp_rate = _q(staff.kiwisaver_employee_rate) / Decimal(100)
        empl_rate = _q(staff.kiwisaver_employer_rate) / Decimal(100)
        kiwisaver_employee = (gross * emp_rate).quantize(_CENTS)
        kiwisaver_employer = (gross * empl_rate).quantize(_CENTS)

    # ---------------- Statutory deductions: PAYE / ACC / student loan ----------------
    # The PAYE engine annualises the period gross, applies the NZ
    # progressive brackets (or secondary flat rate) for the staff's tax
    # code, adds the ACC earner levy, and computes student-loan
    # repayments. These are attached as deduction lines by the service
    # layer (mirroring KiwiSaver) so they flow into net pay.
    from app.modules.timesheets.paye import compute_paye

    period_days = (period.end_date - period.start_date).days + 1
    paye_result = compute_paye(
        gross_pay=gross,
        tax_code=getattr(staff, "tax_code", None) or "M",
        period_days=period_days,
        student_loan=bool(getattr(staff, "student_loan", False)),
        kiwisaver_enrolled=bool(staff.kiwisaver_enrolled),
        kiwisaver_employee_rate=(
            _q(staff.kiwisaver_employee_rate)
            if staff.kiwisaver_employee_rate is not None
            else Decimal("3")
        ),
        kiwisaver_employer_rate=(
            _q(staff.kiwisaver_employer_rate)
            if staff.kiwisaver_employer_rate is not None
            else Decimal("3")
        ),
    )
    paye = paye_result.paye_tax
    acc_levy = paye_result.acc_levy
    student_loan = paye_result.student_loan
    annualised_gross = paye_result.annualised_gross

    # ---------------- Net composition ----------------
    deductions_total = Decimal("0.00")
    for d in deductions:
        if d.get("kind") == "kiwisaver_employer":
            # R6.2 — informational, NOT subtracted from gross.
            continue
        deductions_total += _q(d["amount"])

    reimbursements_total = sum(
        (_q(r["amount"]) for r in reimbursements), Decimal("0.00"),
    )

    net = (gross - deductions_total + reimbursements_total).quantize(_CENTS)

    # ---------------- YTD ----------------
    org_row = await db.get(Organisation, org_id)
    tax_year_end = getattr(org_row, "income_tax_year_end", None) if org_row else None
    gross_ytd_prior = await compute_gross_ytd(
        db,
        staff_id=staff.id,
        pay_date=period.pay_date,
        tax_year_end=tax_year_end,
        exclude_payslip_id=payslip.id if payslip is not None else None,
    )
    # Include this period's gross in the rolling YTD only when the
    # caller passed in a pre-finalised payslip (uncommon). For the
    # standard draft-generation flow, gross_ytd is the running total
    # of FINALISED payslips up to and including this pay_date, and the
    # current draft contributes to YTD only after it is finalised.
    gross_ytd = gross_ytd_prior

    return PayslipCalc(
        ordinary_hours=ordinary_hours,
        overtime_hours=overtime_hours,
        public_holiday_hours=public_holiday_hours,
        ordinary_rate=ordinary_rate,
        overtime_rate=overtime_rate,
        public_holiday_rate=public_holiday_rate,
        ordinary=ordinary,
        overtime=overtime,
        public_holiday=public_holiday,
        allowances_taxable=allowances_taxable,
        allowances_non_taxable=allowances_non_taxable,
        casual_8pct=casual_8pct,
        gross=gross,
        gross_ytd=gross_ytd,
        paye=paye,
        acc_levy=acc_levy,
        student_loan=student_loan,
        annualised_gross=annualised_gross,
        deductions_total=deductions_total,
        reimbursements_total=reimbursements_total,
        net=net,
        kiwisaver_employee=kiwisaver_employee,
        kiwisaver_employer=kiwisaver_employer,
        allowances=allowances,
        deductions=deductions,
        reimbursements=reimbursements,
    )


# ---------------------------------------------------------------------------
# Public re-export for the X4 helper (callers can use this if they
# need overtime_handling separately from compute_payslip — e.g. the
# bulk-finalise progress page).
# ---------------------------------------------------------------------------


async def get_overtime_handling(
    db: AsyncSession, org_id: uuid.UUID,
) -> str:
    """Return the org's ``overtime_handling`` typed-column value.

    Thin public wrapper around :func:`_resolve_overtime_handling` so
    callers don't need to import the underscore-prefixed helper.
    """
    return await _resolve_overtime_handling(db, org_id)


# Suppress "imported but unused" — the symbol is part of the public
# surface re-exported via __all__ even though no in-module call site
# references it. This keeps mypy / pyflakes quiet.
_ = and_
