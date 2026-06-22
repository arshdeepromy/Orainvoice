"""Unit tests for the PAYE engine (NZ 2024/25) + remaining Phase D stubs."""
import pytest
from decimal import Decimal

from app.modules.timesheets.paye import (
    is_paye_engine_active,
    is_ird_filing_active,
    is_bank_export_active,
    compute_paye,
    parse_tax_code,
    generate_bank_file,
)


class TestFeatureFlags:
    def test_paye_engine_active(self):
        # The PAYE engine is now implemented and active.
        assert is_paye_engine_active() is True

    def test_ird_filing_inactive(self):
        assert is_ird_filing_active() is False

    def test_bank_export_inactive(self):
        assert is_bank_export_active() is False


class TestParseTaxCode:
    def test_plain_primary(self):
        assert parse_tax_code("M") == ("M", False)

    def test_primary_with_student_loan(self):
        assert parse_tax_code("M SL") == ("M", True)

    def test_me_code(self):
        assert parse_tax_code("ME") == ("ME", False)

    def test_secondary(self):
        assert parse_tax_code("S") == ("S", False)
        assert parse_tax_code("SH SL") == ("SH", True)

    def test_unknown_falls_back_to_M(self):
        assert parse_tax_code("WT") == ("M", False)
        assert parse_tax_code(None) == ("M", False)


class TestComputePAYE:
    def test_primary_M_weekly_progressive(self):
        # $2,400/week → annualised ~$125,228; PAYE ≈ $598/week.
        r = compute_paye(gross_pay=Decimal("2400"), tax_code="M", period_days=7)
        assert r.paye_tax == Decimal("598.00")
        assert r.acc_levy == Decimal("38.40")  # 1.6% × 2400
        assert r.student_loan == Decimal("0.00")

    def test_acc_levy_rate(self):
        r = compute_paye(gross_pay=Decimal("1000"), tax_code="M", period_days=7)
        assert r.acc_levy == Decimal("16.00")  # 1.6% × 1000

    def test_secondary_flat_rate_S(self):
        # Secondary 'S' is a flat 17.5%.
        r = compute_paye(gross_pay=Decimal("1000"), tax_code="S", period_days=7)
        assert r.paye_tax == Decimal("175.00")

    def test_student_loan_above_threshold(self):
        # Weekly SL threshold ≈ $24,128 / 52.18 ≈ $462.4; 12% over.
        r = compute_paye(
            gross_pay=Decimal("1000"), tax_code="M SL", period_days=7,
            student_loan=True,
        )
        assert r.student_loan > Decimal("60.00")
        assert r.student_loan < Decimal("70.00")

    def test_no_student_loan_when_not_flagged(self):
        r = compute_paye(gross_pay=Decimal("1000"), tax_code="M", period_days=7)
        assert r.student_loan == Decimal("0.00")

    def test_kiwisaver_enrolled(self):
        r = compute_paye(
            gross_pay=Decimal("1000"), tax_code="M", period_days=7,
            kiwisaver_enrolled=True,
            kiwisaver_employee_rate=Decimal("3.00"),
            kiwisaver_employer_rate=Decimal("3.00"),
        )
        assert r.kiwisaver_employee == Decimal("30.00")
        assert r.kiwisaver_employer == Decimal("30.00")

    def test_kiwisaver_zero_when_not_enrolled(self):
        r = compute_paye(gross_pay=Decimal("1000"), tax_code="M", period_days=7)
        assert r.kiwisaver_employee == Decimal("0.00")

    def test_net_pay_subtracts_statutory_and_employee_kiwisaver(self):
        r = compute_paye(
            gross_pay=Decimal("1000"), tax_code="M", period_days=7,
            kiwisaver_enrolled=True,
        )
        expected = (Decimal("1000") - r.paye_tax - r.acc_levy
                    - r.student_loan - r.kiwisaver_employee)
        assert r.net_pay == expected

    def test_total_to_ird(self):
        r = compute_paye(gross_pay=Decimal("1000"), tax_code="M SL", period_days=7,
                         student_loan=True)
        assert r.total_to_ird == r.paye_tax + r.acc_levy + r.student_loan

    def test_fortnightly_is_double_weekly_roughly(self):
        wk = compute_paye(gross_pay=Decimal("1200"), tax_code="M", period_days=7)
        fn = compute_paye(gross_pay=Decimal("2400"), tax_code="M", period_days=14)
        # Same annualised income → fortnightly PAYE ≈ 2× weekly PAYE.
        assert abs(fn.paye_tax - wk.paye_tax * 2) < Decimal("0.05")

    def test_zero_gross(self):
        r = compute_paye(gross_pay=Decimal("0"), tax_code="M", period_days=7)
        assert r.paye_tax == Decimal("0.00")
        assert r.net_pay == Decimal("0.00")


class TestBankExportStub:
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
