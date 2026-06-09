"""Unit tests for the PAYE stub module (Phase D)."""
import pytest
from decimal import Decimal

from app.modules.timesheets.paye import (
    is_paye_engine_active,
    is_ird_filing_active,
    is_bank_export_active,
    compute_paye,
    generate_bank_file,
)


class TestPAYEStub:
    """Tests verifying Phase D stubs behave correctly."""

    def test_paye_engine_inactive(self):
        assert is_paye_engine_active() is False

    def test_ird_filing_inactive(self):
        assert is_ird_filing_active() is False

    def test_bank_export_inactive(self):
        assert is_bank_export_active() is False

    def test_compute_paye_returns_no_deductions(self):
        result = compute_paye(gross_pay=Decimal("2000"))
        assert result.gross_pay == Decimal("2000")
        assert result.net_pay == Decimal("2000")  # No deductions
        assert result.paye_tax == Decimal("0")
        assert result.warnings is not None
        assert "inactive" in result.warnings[0].lower() or "manual" in result.warnings[0].lower()

    def test_compute_paye_with_all_params(self):
        result = compute_paye(
            gross_pay=Decimal("3500"),
            tax_code="M",
            kiwisaver_employee_rate=Decimal("3.00"),
            kiwisaver_employer_rate=Decimal("3.00"),
            student_loan=True,
            child_support_amount=Decimal("100"),
            period_type="fortnightly",
        )
        # Engine inactive — all deductions are 0
        assert result.paye_tax == Decimal("0")
        assert result.kiwisaver_employee == Decimal("0")
        assert result.student_loan == Decimal("0")

    def test_bank_file_export_returns_error(self):
        result = generate_bank_file(
            org_name="Test Workshop",
            bank_account="02-1234-5678901-00",
            payments=[{"staff_id": "abc", "amount": 2000}],
            pay_date="2026-06-15",
        )
        assert result.success is False
        assert result.error is not None
        assert "not yet active" in result.error.lower()
