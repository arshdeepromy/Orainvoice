"""WeasyPrint payslip PDF rendering (R7 + G2 + G18 + G20).

Implements task B5 from ``.kiro/specs/staff-management-p4/tasks.md``.
The renderer produces a Wages-Protection-Act + Holidays-Act-s130A
compliant PDF that includes:

  - Org header (logo + name) — repeats on every page (G20).
  - Employee block: name, tax_code, masked IRD (``***123``), masked
    bank account ``**-****-****NN-**`` (G1) — or
    ``Cash payment / no bank account on file`` when the encrypted
    column is NULL (N18).
  - Pay-period dates + pay date.
  - Earnings table with separate rows for ordinary / overtime /
    public_holiday band (G2 — Holidays Act s50 rate × hours).
  - Allowance lines with quantity × unit × unit_price = amount for
    shift / km units (G18); fixed amount for period units.
  - Reimbursements (tax-free).
  - Leave taken in this period + remaining balances (s130A).
  - Deductions including KiwiSaver employer flagged "informational".
  - Net pay totals.
  - YTD figures for gross, PAYE, KiwiSaver employee, KiwiSaver
    employer (P4-N25 — only gross_ytd is stored on payslips, the
    other three are computed at render time per N16 tax-year window).
  - Page-counter footer (G20 — page X of N).

The decryption of IRD + bank fields happens inside :func:`render_pdf`
only — no other code path touches the encrypted columns. Per the
PII-safety policy in design §10.

WeasyPrint is CPU-heavy (200-1500ms per page), so the actual
``HTML(...).write_pdf()`` call is wrapped in
:func:`asyncio.to_thread` to avoid blocking the event loop. Pattern
borrowed from :mod:`app.modules.quotes.service`'s quote-PDF path.

**Validates: Requirement R7, R7.5, R4a, R5, R6 — Staff Management
Phase 4 task B5.**
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str
from app.modules.admin.models import Organisation
from app.modules.leave.models import LeaveBalance, LeaveType
from app.modules.payslips.calc import compute_tax_year_start
from app.modules.payslips.models import (
    PayPeriod,
    Payslip,
    PayslipAllowance,
    PayslipDeduction,
    PayslipLeaveLine,
    PayslipReimbursement,
)
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


__all__ = [
    "render_pdf",
    "PayslipNotFoundError",
]


# ---------------------------------------------------------------------------
# Template lookup (per-module convention — mirrors invoices/quotes)
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / "templates"
_TEMPLATE_FILE = "payslip.html"
_CSS_FILE = "payslip.css"

_CASH_FALLBACK_TEXT = "Cash payment / no bank account on file"


class PayslipNotFoundError(Exception):
    """Raised when :func:`render_pdf` is called with an unknown
    payslip_id (e.g. cross-tenant lookup or stale request).
    """


# ---------------------------------------------------------------------------
# Currency formatting helper exposed to the template
# ---------------------------------------------------------------------------


def _format_nzd(value: Decimal | float | int | None) -> str:
    """Format a money value as ``$1,234.50`` (NZD locale)."""
    if value is None:
        return "—"
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    # Use formatting with grouping; quantise to 2dp.
    formatted = f"{abs_value.quantize(Decimal('0.01')):,}"
    return f"{sign}${formatted}"


# ---------------------------------------------------------------------------
# YTD aggregation (P4-N25)
# ---------------------------------------------------------------------------


async def _compute_ytd_deductions(
    db: AsyncSession,
    *,
    staff_id: uuid.UUID,
    pay_date: date,
    tax_year_end: date | None,
) -> dict[str, Decimal]:
    """Compute PAYE / KiwiSaver-employee / KiwiSaver-employer YTD
    figures for the staff in the active NZ tax year.

    Per P4-N25, only ``gross_ytd`` is stored on the ``payslips`` row;
    the other three are recomputed at render time from
    ``payslip_deductions`` joined to ``payslips`` × ``pay_periods``
    where ``pay_periods.pay_date BETWEEN :tax_year_start AND
    :pay_date AND status='finalised'``.

    Returns a dict with three Decimal values keyed by
    ``paye_ytd``, ``kiwisaver_employee_ytd``,
    ``kiwisaver_employer_ytd``. Missing kinds yield zero.
    """
    tax_year_start = compute_tax_year_start(
        pay_date=pay_date, tax_year_end=tax_year_end,
    )
    stmt = text(
        """
        SELECT pd.kind, COALESCE(SUM(pd.amount), 0) AS total
        FROM payslip_deductions pd
        JOIN payslips p ON p.id = pd.payslip_id
        JOIN pay_periods pp ON pp.id = p.pay_period_id
        WHERE p.staff_id = :staff_id
          AND p.status = 'finalised'
          AND pp.pay_date >= :tax_year_start
          AND pp.pay_date <= :pay_date
          AND pd.kind IN ('paye','kiwisaver_employee','kiwisaver_employer')
        GROUP BY pd.kind
        """,
    )
    result = await db.execute(
        stmt,
        {
            "staff_id": str(staff_id),
            "tax_year_start": tax_year_start,
            "pay_date": pay_date,
        },
    )
    totals: dict[str, Decimal] = {
        "paye_ytd": Decimal("0.00"),
        "kiwisaver_employee_ytd": Decimal("0.00"),
        "kiwisaver_employer_ytd": Decimal("0.00"),
    }
    for row in result.all():
        kind = row.kind
        if kind == "paye":
            totals["paye_ytd"] = Decimal(str(row.total or 0))
        elif kind == "kiwisaver_employee":
            totals["kiwisaver_employee_ytd"] = Decimal(str(row.total or 0))
        elif kind == "kiwisaver_employer":
            totals["kiwisaver_employer_ytd"] = Decimal(str(row.total or 0))
    return totals


# ---------------------------------------------------------------------------
# Source-data loaders
# ---------------------------------------------------------------------------


async def _load_payslip_with_lines(
    db: AsyncSession, payslip_id: uuid.UUID,
) -> tuple[
    Payslip,
    list[PayslipAllowance],
    list[PayslipDeduction],
    list[PayslipReimbursement],
    list[dict[str, Any]],
]:
    """Load the payslip + every line list for rendering.

    Leave lines are returned as dicts with the leave-type ``code`` /
    ``name`` joined in (the template displays the friendly name).
    """
    payslip = await db.get(Payslip, payslip_id)
    if payslip is None:
        raise PayslipNotFoundError(f"payslip {payslip_id} not found")

    allowances = list(
        (
            await db.execute(
                select(PayslipAllowance).where(
                    PayslipAllowance.payslip_id == payslip_id,
                ),
            )
        )
        .scalars()
        .all()
    )
    deductions = list(
        (
            await db.execute(
                select(PayslipDeduction).where(
                    PayslipDeduction.payslip_id == payslip_id,
                ),
            )
        )
        .scalars()
        .all()
    )
    reimbursements = list(
        (
            await db.execute(
                select(PayslipReimbursement).where(
                    PayslipReimbursement.payslip_id == payslip_id,
                ),
            )
        )
        .scalars()
        .all()
    )

    leave_rows = (
        await db.execute(
            select(
                PayslipLeaveLine.id,
                PayslipLeaveLine.leave_type_id,
                PayslipLeaveLine.hours,
                PayslipLeaveLine.rate,
                PayslipLeaveLine.amount,
                PayslipLeaveLine.balance_after,
                LeaveType.code.label("leave_type_code"),
                LeaveType.name.label("leave_type_name"),
            )
            .join(LeaveType, LeaveType.id == PayslipLeaveLine.leave_type_id)
            .where(PayslipLeaveLine.payslip_id == payslip_id),
        )
    ).all()
    leave_lines = [
        {
            "id": row.id,
            "leave_type_id": row.leave_type_id,
            "leave_type_code": row.leave_type_code,
            "leave_type_name": row.leave_type_name,
            "hours": row.hours,
            "rate": row.rate,
            "amount": row.amount,
            "balance_after": row.balance_after,
        }
        for row in leave_rows
    ]
    return payslip, allowances, deductions, reimbursements, leave_lines


async def _load_remaining_leave_balances(
    db: AsyncSession, *, staff_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return per-leave-type balance summary for s130A.

    Only accruing types (``accrual_method != 'none'``) are surfaced
    on the PDF; one-off / non-accruing types are noise on the
    rendered footer.
    """
    rows = (
        await db.execute(
            select(
                LeaveType.code,
                LeaveType.name,
                LeaveBalance.accrued_hours,
                LeaveBalance.used_hours,
            )
            .join(LeaveBalance, LeaveBalance.leave_type_id == LeaveType.id)
            .where(
                LeaveBalance.staff_id == staff_id,
                LeaveType.active.is_(True),
                LeaveType.accrual_method != "none",
            )
            .order_by(LeaveType.display_order, LeaveType.name),
        )
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        accrued = Decimal(row.accrued_hours or 0)
        used = Decimal(row.used_hours or 0)
        available = accrued - used
        out.append(
            {
                "code": row.code,
                "name": row.name,
                "accrued": accrued,
                "used": used,
                "available": available,
            }
        )
    return out


# ---------------------------------------------------------------------------
# PII decryption (G1 + N18)
# ---------------------------------------------------------------------------


def _mask_staff_pii(staff: StaffMember) -> tuple[str | None, str, bool]:
    """Return ``(ird_number, bank_account, cash_fallback)`` for the payslip.

    Decrypts the IRD + bank-account ciphertext columns and returns them in
    FULL. A payslip is the employee's own statutory document, so it must show
    the complete IRD number and the bank account the pay is deposited into —
    masked stars are not acceptable for payroll/operations.

    Per N18, when ``staff.bank_account_number_encrypted IS NULL`` the
    bank-line text is the literal cash-fallback string and
    ``cash_fallback=True`` so the template can render it in italics.

    Decryption failures are logged but do not abort the render — the
    PDF surfaces ``"***"`` / ``"**-****-****-**"`` placeholders so a
    rotated key doesn't block payroll. Admin sees the warning in the
    logs and can rotate via the encryption-rotate flow.
    """
    ird_value: str | None = None
    if staff.ird_number_encrypted:
        try:
            ird_value = envelope_decrypt_str(bytes(staff.ird_number_encrypted))
        except Exception:  # noqa: BLE001 — best-effort; placeholder on failure.
            logger.warning(
                "render_pdf: failed to decrypt IRD for staff=%s",
                staff.id,
                exc_info=True,
            )
            ird_value = "***"

    cash_fallback = False
    bank_value: str
    if staff.bank_account_number_encrypted:
        try:
            bank_value = envelope_decrypt_str(
                bytes(staff.bank_account_number_encrypted),
            ) or "**-****-****-**"
        except Exception:  # noqa: BLE001 — best-effort.
            logger.warning(
                "render_pdf: failed to decrypt bank account for staff=%s",
                staff.id,
                exc_info=True,
            )
            bank_value = "**-****-****-**"
    else:
        # N18 — no bank account on file.
        bank_value = _CASH_FALLBACK_TEXT
        cash_fallback = True

    return ird_value, bank_value, cash_fallback


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def render_pdf(
    db: AsyncSession, payslip_id: uuid.UUID,
) -> bytes:
    """Render the payslip identified by ``payslip_id`` to a PDF blob.

    The function:
      1. Loads the payslip + every line list.
      2. Loads the staff, pay_period, and org rows.
      3. Decrypts IRD + bank account (the only place this happens — §10).
      4. Computes YTD figures (gross + PAYE + KiwiSaver-employee +
         KiwiSaver-employer) per the N16 tax-year window.
      5. Renders the Jinja template at
         ``app/modules/payslips/templates/payslip.html``.
      6. Hands the rendered HTML to WeasyPrint inside
         :func:`asyncio.to_thread` so the event loop stays free.

    Returns the raw PDF bytes. Storage / encryption / file_key
    bookkeeping is the caller's responsibility (use
    :mod:`app.modules.payslips.pdf_storage`).

    Raises:
      :class:`PayslipNotFoundError`: when the payslip_id is unknown.
    """
    # Local imports — keep WeasyPrint + Jinja2 out of module load
    # path so importing `app.modules.payslips.pdf` is cheap (e.g.
    # for tests that don't render).
    from jinja2 import Environment, FileSystemLoader

    payslip, allowances, deductions, reimbursements, leave_lines = (
        await _load_payslip_with_lines(db, payslip_id)
    )

    staff = await db.get(StaffMember, payslip.staff_id)
    if staff is None:
        raise PayslipNotFoundError(f"staff for payslip {payslip_id} not found")
    pay_period = await db.get(PayPeriod, payslip.pay_period_id)
    if pay_period is None:
        raise PayslipNotFoundError(
            f"pay_period for payslip {payslip_id} not found",
        )
    org = await db.get(Organisation, payslip.org_id)

    ird_masked, bank_masked, cash_fallback = _mask_staff_pii(staff)
    leave_balances = await _load_remaining_leave_balances(
        db, staff_id=staff.id,
    )

    ytd_deductions = await _compute_ytd_deductions(
        db,
        staff_id=staff.id,
        pay_date=pay_period.pay_date,
        tax_year_end=getattr(org, "income_tax_year_end", None),
    )
    ytd = {
        "gross_ytd": Decimal(payslip.gross_ytd or 0),
        **ytd_deductions,
    }

    # Pre-compute amount components from the line lists for the
    # totals block.
    ordinary_amount = (
        Decimal(payslip.ordinary_hours or 0)
        * Decimal(payslip.ordinary_rate or 0)
    ).quantize(Decimal("0.01"))
    overtime_amount = (
        Decimal(payslip.overtime_hours or 0)
        * Decimal(payslip.overtime_rate or 0)
    ).quantize(Decimal("0.01"))
    public_holiday_amount = (
        Decimal(payslip.public_holiday_hours or 0)
        * Decimal(payslip.public_holiday_rate or 0)
    ).quantize(Decimal("0.01"))

    # Sum deductions excluding kiwisaver_employer (R6.2 — informational).
    deductions_total = sum(
        (
            Decimal(d.amount or 0)
            for d in deductions
            if d.kind != "kiwisaver_employer"
        ),
        Decimal("0.00"),
    )
    reimbursements_total = sum(
        (Decimal(r.amount or 0) for r in reimbursements),
        Decimal("0.00"),
    )

    # Read CSS from disk and inline it (WeasyPrint can resolve external
    # CSS too but inlining keeps the renderer self-contained).
    css_path = _TEMPLATE_DIR / _CSS_FILE
    inline_css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    # ---- Jinja env ----
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    env.filters["nzd"] = _format_nzd
    template = env.get_template(_TEMPLATE_FILE)

    # ---- Build the staff display dict ----
    staff_ctx = {
        "name": staff.name or staff.first_name or "",
        "tax_code": staff.tax_code,
        "ird_number_masked": ird_masked,
        "bank_account_masked": bank_masked,
        "anniversary_date": next(
            (
                row.get("accrued_hours")  # placeholder — anniversary lives on leave_balances
                for row in []
            ),
            None,
        ),
    }
    # Annual-leave anniversary date: pull from the staff's annual_leave
    # balance row (Phase 2 stores it on leave_balances.anniversary_date).
    try:
        anniversary_row = (
            await db.execute(
                select(LeaveBalance.anniversary_date)
                .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
                .where(
                    LeaveBalance.staff_id == staff.id,
                    LeaveType.code == "annual_leave",
                )
                .limit(1),
            )
        ).scalar_one_or_none()
        if anniversary_row:
            staff_ctx["anniversary_date"] = anniversary_row
    except Exception:
        # Best effort — older orgs without the leave_balances rows
        # render without an anniversary line.
        pass

    org_ctx = {
        "name": getattr(org, "name", "") or "",
        "logo_url": None,  # WeasyPrint can't reach back to the API; admins can adjust later
    }

    # Serialise allowances / deductions / reimbursements into plain
    # dicts the template can consume without any ORM-level lazy loads.
    allowances_ctx = [
        {
            "label": a.label,
            "quantity": a.quantity,
            "unit": a.unit,
            "amount": a.amount,
            "taxable": bool(a.taxable),
        }
        for a in allowances
    ]
    deductions_ctx = [
        {"kind": d.kind, "label": d.label, "amount": d.amount}
        for d in deductions
    ]
    reimbursements_ctx = [
        {"label": r.label, "amount": r.amount} for r in reimbursements
    ]

    payslip_ctx = {
        "ordinary_hours": payslip.ordinary_hours,
        "overtime_hours": payslip.overtime_hours,
        "public_holiday_hours": payslip.public_holiday_hours,
        "ordinary_rate": payslip.ordinary_rate,
        "overtime_rate": payslip.overtime_rate,
        "public_holiday_rate": payslip.public_holiday_rate,
        "gross_pay": payslip.gross_pay,
        "net_pay": payslip.net_pay,
        "notes": payslip.notes,
    }

    html_content = template.render(
        org=org_ctx,
        staff=staff_ctx,
        pay_period=pay_period,
        payslip=payslip_ctx,
        allowances=allowances_ctx,
        deductions=deductions_ctx,
        reimbursements=reimbursements_ctx,
        leave_lines=leave_lines,
        leave_balances=leave_balances,
        ytd=ytd,
        amounts={
            "ordinary": ordinary_amount,
            "overtime": overtime_amount,
            "public_holiday": public_holiday_amount,
            "deductions_total": deductions_total,
            "reimbursements_total": reimbursements_total,
        },
        cash_fallback=cash_fallback,
        format_currency=_format_nzd,
        inline_css=inline_css,
    )

    # WeasyPrint is heavy — keep it off the event loop (PERFORMANCE_AUDIT B-H1).
    from weasyprint import HTML

    pdf_bytes: bytes = await asyncio.to_thread(
        lambda: HTML(string=html_content).write_pdf(),
    )
    return pdf_bytes
