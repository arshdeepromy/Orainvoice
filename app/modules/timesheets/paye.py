"""PAYE Calculation Engine — NZ income tax, ACC earner levy, student loan.

Computes the statutory deductions for a single pay period using the
**2024/25** New Zealand rates (effective 31 July 2024). The engine
annualises the period's gross, applies the progressive income-tax
brackets (or the flat secondary-code rate), adds the ACC earner levy
(capped), applies student-loan repayments above the pay-period
threshold, and pro-rates everything back to the period.

Scope / accuracy notes:
  - Primary codes ``M`` and ``ME`` use the progressive brackets; ``ME``
    additionally applies the Independent Earner Tax Credit (IETC).
  - Secondary codes ``SB / S / SH / ST / SA`` use the flat rate that
    matches the employee's expected total income band.
  - ACC earner levy is shown SEPARATELY from income tax (on a real IR
    PAYE deduction the two are combined; we split them so the payslip
    can show the breakdown the way employers reconcile it).
  - KiwiSaver employee/employer are computed here too for a single
    source of truth, though the payslip service attaches them as their
    own lines.
  - This is a faithful periodic-annualisation calculation, not a
    byte-for-byte reproduction of the IR340/IR341 fortnightly tables;
    cents may differ by rounding. Figures are suitable for payslip
    display and net-pay computation.

**Validates: Staff Timesheets — D1 PAYE engine.**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

# The automated PAYE engine is now active: the payslip math auto-computes
# PAYE / ACC / student loan instead of relying on manual admin entry.
_PAYE_ENGINE_ACTIVE = True


def is_paye_engine_active() -> bool:
    """Return True when the automated PAYE engine computes deductions."""
    return _PAYE_ENGINE_ACTIVE


# ---------------------------------------------------------------------------
# 2024/25 NZ statutory constants
# ---------------------------------------------------------------------------

#: Days in an average year — used to annualise a period's gross and to
#: pro-rate annual figures (thresholds, caps) back to the period.
_DAYS_PER_YEAR = Decimal("365.25")

#: Progressive annual income-tax brackets (upper bound, marginal rate)
#: for the 2024/25 tax year (composite year, rates effective 31 Jul 2024).
_INCOME_TAX_BRACKETS: list[tuple[Decimal, Decimal]] = [
    (Decimal("15600"), Decimal("0.105")),
    (Decimal("53500"), Decimal("0.175")),
    (Decimal("78100"), Decimal("0.30")),
    (Decimal("180000"), Decimal("0.33")),
    (Decimal("Infinity"), Decimal("0.39")),
]

#: Flat annual rates for secondary tax codes (employee's OTHER income
#: already uses their primary code; this income is taxed at one rate).
_SECONDARY_FLAT_RATES: dict[str, Decimal] = {
    "SB": Decimal("0.105"),
    "S": Decimal("0.175"),
    "SH": Decimal("0.30"),
    "ST": Decimal("0.33"),
    "SA": Decimal("0.39"),
}

#: ACC earner levy (2024/25): 1.60% on liable earnings up to the cap.
_ACC_LEVY_RATE = Decimal("0.016")
_ACC_MAX_LIABLE_EARNINGS = Decimal("142283")

#: Student loan (2024/25): 12% on earnings above the repayment threshold.
_STUDENT_LOAN_RATE = Decimal("0.12")
_STUDENT_LOAN_ANNUAL_THRESHOLD = Decimal("24128")

#: Independent Earner Tax Credit (IETC) — applies to the ``ME`` code.
#: $520/yr for income $24,000–$44,000, abating 13c per $1 over $44,000
#: (fully abated at $48,000).
_IETC_AMOUNT = Decimal("520")
_IETC_LOWER = Decimal("24000")
_IETC_ABATEMENT_START = Decimal("44000")
_IETC_ABATEMENT_RATE = Decimal("0.13")

_CENTS = Decimal("0.01")

_PRIMARY_CODES = {"M", "ME"}
_SECONDARY_CODES = set(_SECONDARY_FLAT_RATES.keys())


@dataclass
class PAYEResult:
    """Result of a PAYE calculation for a single pay period.

    All amounts are for the period (not annualised) and quantised to
    cents. ``total_to_ird`` = ``paye_tax`` + ``acc_levy`` +
    ``student_loan`` (the statutory amounts remitted to Inland Revenue;
    KiwiSaver employee is also remitted to IR but is the employee's
    savings, surfaced separately).
    """

    gross_pay: Decimal = Decimal("0.00")
    tax_code: str = "M"
    annualised_gross: Decimal = Decimal("0.00")
    paye_tax: Decimal = Decimal("0.00")
    ietc_credit: Decimal = Decimal("0.00")
    acc_levy: Decimal = Decimal("0.00")
    student_loan: Decimal = Decimal("0.00")
    kiwisaver_employee: Decimal = Decimal("0.00")
    kiwisaver_employer: Decimal = Decimal("0.00")
    total_to_ird: Decimal = Decimal("0.00")
    net_pay: Decimal = Decimal("0.00")
    warnings: list[str] = field(default_factory=list)


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _annual_income_tax(annual: Decimal) -> Decimal:
    """Progressive income tax on an annual taxable income."""
    if annual <= 0:
        return Decimal("0")
    tax = Decimal("0")
    lower = Decimal("0")
    for upper, rate in _INCOME_TAX_BRACKETS:
        if annual <= lower:
            break
        band_top = annual if annual < upper else upper
        tax += (band_top - lower) * rate
        lower = upper
    return tax


def _ietc_annual(annual: Decimal) -> Decimal:
    """Independent Earner Tax Credit for the ``ME`` code (annual)."""
    if annual < _IETC_LOWER or annual > Decimal("48000"):
        return Decimal("0")
    credit = _IETC_AMOUNT
    if annual > _IETC_ABATEMENT_START:
        credit -= (annual - _IETC_ABATEMENT_START) * _IETC_ABATEMENT_RATE
    return credit if credit > 0 else Decimal("0")


def parse_tax_code(tax_code: str | None) -> tuple[str, bool]:
    """Split a raw tax code into ``(base_code, has_student_loan)``.

    Handles forms like ``"M"``, ``"M SL"``, ``"ME"``, ``"SB SL"``,
    ``"S"``. Unknown/empty codes default to ``"M"``.
    """
    if not tax_code:
        return "M", False
    tokens = tax_code.upper().replace("-", " ").split()
    has_sl = "SL" in tokens
    base = next((t for t in tokens if t != "SL"), "M")
    if base not in _PRIMARY_CODES and base not in _SECONDARY_CODES:
        # Unrecognised (e.g. WT, STC, ND, CAE) — fall back to M so we
        # still produce a sensible estimate rather than zero tax.
        base = "M"
    return base, has_sl


def compute_paye(
    *,
    gross_pay: Decimal,
    tax_code: str = "M",
    period_days: int = 14,
    student_loan: bool = False,
    kiwisaver_enrolled: bool = False,
    kiwisaver_employee_rate: Decimal = Decimal("3.00"),
    kiwisaver_employer_rate: Decimal = Decimal("3.00"),
) -> PAYEResult:
    """Compute PAYE / ACC / student loan / KiwiSaver for one pay period.

    ``period_days`` is the inclusive length of the pay period (7 for
    weekly, 14 for fortnightly, ~30/31 for monthly); it drives the
    annualisation factor so any cadence is supported.
    """
    gross = Decimal(gross_pay or 0)
    if gross < 0:
        gross = Decimal("0")
    days = Decimal(period_days if period_days and period_days > 0 else 14)
    periods_per_year = _DAYS_PER_YEAR / days

    base_code, code_has_sl = parse_tax_code(tax_code)
    apply_student_loan = bool(student_loan or code_has_sl)
    warnings: list[str] = []

    annual_gross = gross * periods_per_year

    # ---- Income tax (PAYE) ----
    ietc_period = Decimal("0")
    if base_code in _SECONDARY_CODES:
        annual_tax = annual_gross * _SECONDARY_FLAT_RATES[base_code]
    else:
        annual_tax = _annual_income_tax(annual_gross)
        if base_code == "ME":
            ietc_annual = _ietc_annual(annual_gross)
            annual_tax -= ietc_annual
            ietc_period = ietc_annual / periods_per_year
        if annual_tax < 0:
            annual_tax = Decimal("0")
    paye_period = annual_tax / periods_per_year

    # ---- ACC earner levy (capped) ----
    acc_cap_period = _ACC_MAX_LIABLE_EARNINGS / periods_per_year
    acc_liable = gross if gross < acc_cap_period else acc_cap_period
    acc_period = acc_liable * _ACC_LEVY_RATE

    # ---- Student loan (above pay-period threshold) ----
    student_loan_period = Decimal("0")
    if apply_student_loan:
        sl_threshold_period = _STUDENT_LOAN_ANNUAL_THRESHOLD / periods_per_year
        sl_liable = gross - sl_threshold_period
        if sl_liable > 0:
            student_loan_period = sl_liable * _STUDENT_LOAN_RATE

    # ---- KiwiSaver ----
    ks_employee = Decimal("0")
    ks_employer = Decimal("0")
    if kiwisaver_enrolled:
        ks_employee = gross * (Decimal(kiwisaver_employee_rate or 0) / Decimal("100"))
        ks_employer = gross * (Decimal(kiwisaver_employer_rate or 0) / Decimal("100"))

    paye_q = _q(paye_period)
    acc_q = _q(acc_period)
    sl_q = _q(student_loan_period)
    ks_emp_q = _q(ks_employee)
    ks_empr_q = _q(ks_employer)

    total_to_ird = paye_q + acc_q + sl_q
    net = gross - paye_q - acc_q - sl_q - ks_emp_q

    return PAYEResult(
        gross_pay=_q(gross),
        tax_code=f"{base_code}{' SL' if apply_student_loan else ''}",
        annualised_gross=_q(annual_gross),
        paye_tax=paye_q,
        ietc_credit=_q(ietc_period),
        acc_levy=acc_q,
        student_loan=sl_q,
        kiwisaver_employee=ks_emp_q,
        kiwisaver_employer=ks_empr_q,
        total_to_ird=_q(total_to_ird),
        net_pay=_q(net),
        warnings=warnings,
    )


# ===========================================================================
# IRD Payday Filing — Phase D Stub (unchanged)
# ===========================================================================


def is_ird_filing_active() -> bool:
    """Check if IRD payday filing integration is active."""
    return False


@dataclass
class IRDFilingResult:
    """Result of an IRD payday filing submission."""
    success: bool = False
    filing_id: str | None = None
    error: str | None = None


async def submit_payday_filing(
    *,
    org_ird_number: str,
    pay_period_end: str,
    employee_lines: list[dict],
) -> IRDFilingResult:
    """Submit a payday filing to the IRD (stub)."""
    logger.warning("IRD payday filing is not yet implemented.")
    return IRDFilingResult(
        success=False,
        error="IRD payday filing integration is not yet active (Phase D)",
    )


# ===========================================================================
# Bank File Export — Phase D Stub (unchanged)
# ===========================================================================


def is_bank_export_active() -> bool:
    """Check if bank file export is active."""
    return False


@dataclass
class BankExportResult:
    """Result of a bank file export generation."""
    success: bool = False
    file_content: bytes | None = None
    filename: str | None = None
    total_amount: Decimal = Decimal("0")
    record_count: int = 0
    error: str | None = None


def generate_bank_file(
    *,
    org_name: str,
    bank_account: str,
    payments: list[dict],
    pay_date: str,
    format: str = "anz_direct_credit",
) -> BankExportResult:
    """Generate a bank direct credit batch file (stub)."""
    logger.warning("Bank file export is not yet implemented.")
    return BankExportResult(
        success=False,
        error="Bank file export is not yet active (Phase D)",
    )
