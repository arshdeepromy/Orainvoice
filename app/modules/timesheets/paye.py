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


# ---------------------------------------------------------------------------
# Resolved tax configuration value objects
# ---------------------------------------------------------------------------
#
# These dataclasses describe the fully-populated, calculation-ready tax
# configuration the PAYE engine will eventually be driven from. For now the
# engine still reads the legacy module constants directly (see task 1.2);
# this step only introduces the value objects and the ``SAFETY_NET`` instance
# built from those same constants, so behaviour is unchanged.


@dataclass(frozen=True)
class PAYEBracket:
    """One progressive income-tax band.

    ``upper_limit`` is the annual income ceiling of the band; ``None``
    marks the open-ended top band (previously ``Decimal("Infinity")``).
    """

    upper_limit: Decimal | None
    rate: Decimal


@dataclass(frozen=True)
class IETCParams:
    """Independent Earner Tax Credit parameters for the ``ME`` code."""

    amount: Decimal
    lower: Decimal
    abatement_start: Decimal
    abatement_rate: Decimal
    upper: Decimal


@dataclass(frozen=True)
class ResolvedTaxConfig:
    """Fully-populated, calculation-ready NZ payroll tax configuration.

    Every field is non-optional: construction is only ever via the
    resolution service or the :data:`SAFETY_NET` constant, so the engine
    can assume completeness.
    """

    paye_brackets: tuple[PAYEBracket, ...]
    secondary_rates: dict[str, Decimal]  # keys: SB, S, SH, ST, SA
    acc_levy_rate: Decimal
    acc_max_liable_earnings: Decimal
    student_loan_rate: Decimal
    student_loan_threshold: Decimal
    ietc: IETCParams
    default_kiwisaver_employee_rate: Decimal
    default_kiwisaver_employer_rate: Decimal
    tax_year_label: str


#: The hard-coded fallback configuration (the current 2024/25 constants),
#: used as the last-resort tier when neither an organisation override nor a
#: platform default value is available for a Tax_Field. Built from the legacy
#: module constants above, which remain the single source for this instance.
#: The open-ended top band is expressed with ``upper_limit=None`` (converted
#: from the legacy ``Decimal("Infinity")`` top band); the IETC upper bound
#: (48000) is extracted here from the inline literal in ``_ietc_annual``.
SAFETY_NET: ResolvedTaxConfig = ResolvedTaxConfig(
    paye_brackets=tuple(
        PAYEBracket(
            upper_limit=(None if upper == Decimal("Infinity") else upper),
            rate=rate,
        )
        for upper, rate in _INCOME_TAX_BRACKETS
    ),
    secondary_rates=dict(_SECONDARY_FLAT_RATES),
    acc_levy_rate=_ACC_LEVY_RATE,
    acc_max_liable_earnings=_ACC_MAX_LIABLE_EARNINGS,
    student_loan_rate=_STUDENT_LOAN_RATE,
    student_loan_threshold=_STUDENT_LOAN_ANNUAL_THRESHOLD,
    ietc=IETCParams(
        amount=_IETC_AMOUNT,
        lower=_IETC_LOWER,
        abatement_start=_IETC_ABATEMENT_START,
        abatement_rate=_IETC_ABATEMENT_RATE,
        upper=Decimal("48000"),
    ),
    default_kiwisaver_employee_rate=Decimal("3.00"),
    default_kiwisaver_employer_rate=Decimal("3.00"),
    tax_year_label="2024/25",
)


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


def _annual_income_tax(annual: Decimal, brackets: tuple[PAYEBracket, ...]) -> Decimal:
    """Progressive income tax on an annual taxable income.

    ``brackets`` come from the resolved tax configuration; a bracket whose
    ``upper_limit is None`` is the open-ended top band (treated as infinity),
    so the band ceiling is the income itself.
    """
    if annual <= 0:
        return Decimal("0")
    tax = Decimal("0")
    lower = Decimal("0")
    for bracket in brackets:
        if annual <= lower:
            break
        upper = bracket.upper_limit
        # ``None`` marks the open-ended top band: never cap below ``annual``.
        if upper is None or annual < upper:
            band_top = annual
        else:
            band_top = upper
        tax += (band_top - lower) * bracket.rate
        if upper is None:
            break
        lower = upper
    return tax


def _ietc_annual(annual: Decimal, ietc: IETCParams) -> Decimal:
    """Independent Earner Tax Credit for the ``ME`` code (annual)."""
    if annual < ietc.lower or annual > ietc.upper:
        return Decimal("0")
    credit = ietc.amount
    if annual > ietc.abatement_start:
        credit -= (annual - ietc.abatement_start) * ietc.abatement_rate
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
    kiwisaver_employee_rate: Decimal | None = None,
    kiwisaver_employer_rate: Decimal | None = None,
    config: ResolvedTaxConfig = SAFETY_NET,
) -> PAYEResult:
    """Compute PAYE / ACC / student loan / KiwiSaver for one pay period.

    ``period_days`` is the inclusive length of the pay period (7 for
    weekly, 14 for fortnightly, ~30/31 for monthly); it drives the
    annualisation factor so any cadence is supported.

    Every statutory rate is read from ``config`` (a fully-populated
    :class:`ResolvedTaxConfig`). It defaults to :data:`SAFETY_NET` — the
    hard-coded 2024/25 constants — so existing callers and tests produce
    identical numbers. When ``kiwisaver_employee_rate`` /
    ``kiwisaver_employer_rate`` is ``None`` the resolved
    ``default_kiwisaver_*_rate`` is used.
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
        annual_tax = annual_gross * config.secondary_rates[base_code]
    else:
        annual_tax = _annual_income_tax(annual_gross, config.paye_brackets)
        if base_code == "ME":
            ietc_annual = _ietc_annual(annual_gross, config.ietc)
            annual_tax -= ietc_annual
            ietc_period = ietc_annual / periods_per_year
        if annual_tax < 0:
            annual_tax = Decimal("0")
    paye_period = annual_tax / periods_per_year

    # ---- ACC earner levy (capped) ----
    acc_cap_period = config.acc_max_liable_earnings / periods_per_year
    acc_liable = gross if gross < acc_cap_period else acc_cap_period
    acc_period = acc_liable * config.acc_levy_rate

    # ---- Student loan (above pay-period threshold) ----
    student_loan_period = Decimal("0")
    if apply_student_loan:
        sl_threshold_period = config.student_loan_threshold / periods_per_year
        sl_liable = gross - sl_threshold_period
        if sl_liable > 0:
            student_loan_period = sl_liable * config.student_loan_rate

    # ---- KiwiSaver ----
    ks_employee = Decimal("0")
    ks_employer = Decimal("0")
    if kiwisaver_enrolled:
        emp_rate = (
            kiwisaver_employee_rate
            if kiwisaver_employee_rate is not None
            else config.default_kiwisaver_employee_rate
        )
        empr_rate = (
            kiwisaver_employer_rate
            if kiwisaver_employer_rate is not None
            else config.default_kiwisaver_employer_rate
        )
        ks_employee = gross * (Decimal(emp_rate or 0) / Decimal("100"))
        ks_employer = gross * (Decimal(empr_rate or 0) / Decimal("100"))

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
