"""Test: retention details appear on progress claim PDF.

**Validates: Requirement — Retention Module, Task 37.7**
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.progress_claims.pdf import generate_progress_claim_pdf


class TestRetentionOnProgressClaimPDF:
    """Verify retention information is rendered in the progress claim PDF."""

    def test_retention_withheld_appears_in_pdf(self) -> None:
        """Retention withheld amount should be visible in the PDF output."""
        claim = {
            "claim_number": 3,
            "contract_value": Decimal("500000"),
            "variations_to_date": Decimal("25000"),
            "revised_contract_value": Decimal("525000"),
            "work_completed_to_date": Decimal("200000"),
            "work_completed_previous": Decimal("150000"),
            "work_completed_this_period": Decimal("50000"),
            "materials_on_site": Decimal("5000"),
            "retention_withheld": Decimal("5000"),
            "amount_due": Decimal("50000"),
            "completion_percentage": Decimal("38.10"),
            "status": "draft",
            "created_at": "2024-08-01T10:00:00Z",
        }

        pdf_bytes = generate_progress_claim_pdf(claim, org_name="Test Org", project_name="Test Project")
        content = pdf_bytes.decode("utf-8")

        # Retention withheld line should be present
        assert "Retention Withheld" in content
        assert "5,000.00" in content

    def test_zero_retention_still_shows_line(self) -> None:
        """Even with zero retention, the line should appear in the PDF."""
        claim = {
            "claim_number": 1,
            "contract_value": Decimal("100000"),
            "variations_to_date": Decimal("0"),
            "revised_contract_value": Decimal("100000"),
            "work_completed_to_date": Decimal("30000"),
            "work_completed_previous": Decimal("0"),
            "work_completed_this_period": Decimal("30000"),
            "materials_on_site": Decimal("0"),
            "retention_withheld": Decimal("0"),
            "amount_due": Decimal("30000"),
            "completion_percentage": Decimal("30.00"),
            "status": "draft",
            "created_at": "2024-06-01T10:00:00Z",
        }

        pdf_bytes = generate_progress_claim_pdf(claim)
        content = pdf_bytes.decode("utf-8")

        assert "Retention Withheld" in content
        assert "0.00" in content

    def test_pdf_contains_amount_due_after_retention(self) -> None:
        """Amount due should reflect retention deduction."""
        claim = {
            "claim_number": 2,
            "contract_value": Decimal("200000"),
            "variations_to_date": Decimal("10000"),
            "revised_contract_value": Decimal("210000"),
            "work_completed_to_date": Decimal("80000"),
            "work_completed_previous": Decimal("40000"),
            "work_completed_this_period": Decimal("40000"),
            "materials_on_site": Decimal("3000"),
            "retention_withheld": Decimal("4000"),
            "amount_due": Decimal("39000"),
            "completion_percentage": Decimal("38.10"),
            "status": "approved",
            "created_at": "2024-07-15T10:00:00Z",
        }

        pdf_bytes = generate_progress_claim_pdf(claim, org_name="Builder Co")
        content = pdf_bytes.decode("utf-8")

        assert "AMOUNT DUE THIS CLAIM" in content
        assert "39,000.00" in content
        assert "4,000.00" in content
