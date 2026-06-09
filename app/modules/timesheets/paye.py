"""PAYE Calculation Engine — Phase D Stub.

This module is a placeholder for the PAYE (Pay As You Earn) tax calculation
engine. Phase D is explicitly out of scope for the current spec — PAYE
calculations remain MANUAL until this module is fully implemented.

When implemented, this module will:
1. Consume Timesheet/Payslip hour band data.
2. Apply NZ IRD tax tables to compute PAYE deductions.
3. Calculate ACC levies, KiwiSaver contributions, student loan repayments.
4. Generate the deduction breakdown that feeds into PayslipDeductions.

Current state: All functions return placeholder values and log warnings.
The service layer should check `is_paye_engine_active()` before calling
any computation functions.

**Phase D — NOT specced. Do not develop beyond stubs.**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# Feature flag — controls whether the PAYE engine is used.
# When False, all PAYE entries are manual input by the org_admin.
_PAYE_ENGINE_ACTIVE = False


def is_paye_engine_active() -> bool:
    """Check if the automated PAYE engine is active.

    Returns False until Phase D is fully implemented and enabled.
    The org_admin manually enters PAYE amounts until this returns True.
    """
    return _PAYE_ENGINE_ACTIVE


@dataclass
class PAYEResult:
    """Result of a PAYE calculation for a single payslip."""
    gross_pay: Decimal = Decimal("0")
    paye_tax: Decimal = Decimal("0")
    acc_levy: Decimal = Decimal("0")
    kiwisaver_employee: Decimal = Decimal("0")
    kiwisaver_employer: Decimal = Decimal("0")
    student_loan: Decimal = Decimal("0")
    child_support: Decimal = Decimal("0")
    net_pay: Decimal = Decimal("0")
    warnings: list[str] | None = None


def compute_paye(
    *,
    gross_pay: Decimal,
    tax_code: str = "M",
    kiwisaver_employee_rate: Decimal = Decimal("3.00"),
    kiwisaver_employer_rate: Decimal = Decimal("3.00"),
    student_loan: bool = False,
    child_support_amount: Decimal = Decimal("0"),
    period_type: str = "fortnightly",
) -> PAYEResult:
    """Compute PAYE deductions for a payslip.

    STUB — returns zero deductions with a warning that manual entry is required.

    When Phase D is implemented, this will:
    1. Look up the applicable tax table for the tax_code.
    2. Apply progressive tax rates to gross_pay.
    3. Calculate ACC levy (fixed rate × earnings).
    4. Calculate KiwiSaver contributions (employee + employer).
    5. Apply student loan repayment threshold + rate.
    6. Apply fixed child_support_amount.
    7. Return net_pay = gross - all deductions.
    """
    if not _PAYE_ENGINE_ACTIVE:
        logger.warning(
            "PAYE engine is not active. Manual PAYE entry required for gross_pay=%s",
            gross_pay,
        )
        return PAYEResult(
            gross_pay=gross_pay,
            net_pay=gross_pay,  # No deductions applied when engine inactive
            warnings=["PAYE engine inactive — manual deduction entry required"],
        )

    # Placeholder computation (will be replaced with actual tax tables)
    # NZ PAYE rates for M tax code (simplified):
    # 0 - 14,000: 10.5%
    # 14,001 - 48,000: 17.5%
    # 48,001 - 70,000: 30%
    # 70,001 - 180,000: 33%
    # 180,001+: 39%
    #
    # These need to be annualised and then pro-rated to the period.
    # TODO: Implement full NZ IRD tax table computation.

    return PAYEResult(
        gross_pay=gross_pay,
        net_pay=gross_pay,
        warnings=["PAYE computation not yet implemented — placeholder"],
    )


# ===========================================================================
# IRD Payday Filing — Phase D Stub
# ===========================================================================


def is_ird_filing_active() -> bool:
    """Check if IRD payday filing integration is active.

    Returns False until Phase D IRD Gateway integration is implemented.
    """
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
    """Submit a payday filing to the IRD.

    STUB — returns an error indicating the feature is not yet active.

    When Phase D is implemented, this will:
    1. Build the EI (Employment Information) return XML/JSON.
    2. Submit via the IRD Gateway Services API.
    3. Handle response and return filing ID on success.
    """
    logger.warning("IRD payday filing is not yet implemented.")
    return IRDFilingResult(
        success=False,
        error="IRD payday filing integration is not yet active (Phase D)",
    )


# ===========================================================================
# Bank File Export — Phase D Stub
# ===========================================================================


def is_bank_export_active() -> bool:
    """Check if bank file export is active.

    Returns False until Phase D bank integration is implemented.
    """
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
    """Generate a bank direct credit batch file.

    STUB — returns an error indicating the feature is not yet active.

    When Phase D is implemented, this will:
    1. Validate all payment records have valid bank account numbers.
    2. Generate the direct credit file in the specified format.
    3. Supported formats: anz_direct_credit, westpac_bulk, bnz_autopay.
    4. Return the file content for download.
    """
    logger.warning("Bank file export is not yet implemented.")
    return BankExportResult(
        success=False,
        error="Bank file export is not yet active (Phase D)",
    )
