"""Tests for progress claims module.

**Validates: Requirement — ProgressClaim Module**

- Approving a claim generates an invoice for the correct amount
- Auto-calculation of derived fields
- Validation of cumulative invariant
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.progress_claims.models import ProgressClaim
from app.modules.progress_claims.schemas import ProgressClaimCreate, ProgressClaimUpdate
from app.modules.progress_claims.service import ProgressClaimService


def _make_mock_db():
    """Create a mock async DB session."""
    mock_db = AsyncMock()
    added_objects: list = []

    async def fake_flush():
        pass

    def fake_add(obj):
        added_objects.append(obj)

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    mock_db._added = added_objects
    return mock_db


def _make_claim(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    claim_number: int = 1,
    contract_value: Decimal = Decimal("100000.00"),
    variations_to_date: Decimal = Decimal("5000.00"),
    work_completed_to_date: Decimal = Decimal("30000.00"),
    work_completed_previous: Decimal = Decimal("10000.00"),
    materials_on_site: Decimal = Decimal("2000.00"),
    retention_withheld: Decimal = Decimal("1000.00"),
    status: str = "submitted",
) -> ProgressClaim:
    """Create a ProgressClaim instance for testing."""
    revised = contract_value + variations_to_date
    this_period = work_completed_to_date - work_completed_previous
    amount_due = this_period + materials_on_site - retention_withheld
    pct = (work_completed_to_date / revised * 100).quantize(Decimal("0.01"))

    return ProgressClaim(
        id=uuid.uuid4(),
        org_id=org_id,
        project_id=project_id,
        claim_number=claim_number,
        contract_value=contract_value,
        variations_to_date=variations_to_date,
        revised_contract_value=revised,
        work_completed_to_date=work_completed_to_date,
        work_completed_previous=work_completed_previous,
        work_completed_this_period=this_period,
        materials_on_site=materials_on_site,
        retention_withheld=retention_withheld,
        amount_due=amount_due,
        completion_percentage=pct,
        status=status,
        created_at=datetime.now(timezone.utc),
    )


class TestApproveClaimGeneratesInvoice:
    """Validates: approving a claim generates an invoice for the correct amount."""

    @pytest.mark.asyncio
    async def test_approve_submitted_claim_generates_invoice(self):
        """Approving a submitted claim sets status to approved and generates invoice_id."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        claim = _make_claim(org_id, project_id, status="submitted")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = claim

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = ProgressClaimService(mock_db)
        result = await svc.approve_claim(org_id, claim.id)

        assert result["status"] == "approved"
        assert result["invoice_id"] is not None
        assert result["amount_due"] == claim.amount_due
        assert claim.status == "approved"
        assert claim.approved_at is not None
        assert claim.invoice_id == result["invoice_id"]

    @pytest.mark.asyncio
    async def test_approve_draft_claim_generates_invoice(self):
        """Approving a draft claim also works (direct approval)."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        claim = _make_claim(org_id, project_id, status="draft")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = claim

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = ProgressClaimService(mock_db)
        result = await svc.approve_claim(org_id, claim.id)

        assert result["status"] == "approved"
        assert result["invoice_id"] is not None

    @pytest.mark.asyncio
    async def test_approve_already_approved_claim_raises(self):
        """Cannot approve an already approved claim."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        claim = _make_claim(org_id, project_id, status="approved")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = claim

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = ProgressClaimService(mock_db)
        with pytest.raises(ValueError, match="Cannot approve"):
            await svc.approve_claim(org_id, claim.id)

    @pytest.mark.asyncio
    async def test_invoice_amount_matches_claim_amount_due(self):
        """The generated invoice amount matches the claim's amount_due."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        # Specific amounts: 20000 this period + 2000 materials - 1000 retention = 21000
        claim = _make_claim(
            org_id, project_id,
            work_completed_to_date=Decimal("30000.00"),
            work_completed_previous=Decimal("10000.00"),
            materials_on_site=Decimal("2000.00"),
            retention_withheld=Decimal("1000.00"),
            status="submitted",
        )
        expected_amount = Decimal("21000.00")
        assert claim.amount_due == expected_amount

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = claim

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = ProgressClaimService(mock_db)
        result = await svc.approve_claim(org_id, claim.id)

        assert result["amount_due"] == expected_amount


class TestProgressClaimCalculations:
    """Test auto-calculation of derived fields."""

    def test_revised_contract_value(self):
        calc = ProgressClaimService.calculate_fields(
            contract_value=Decimal("100000"),
            variations_to_date=Decimal("5000"),
            work_completed_to_date=Decimal("30000"),
            work_completed_previous=Decimal("10000"),
            materials_on_site=Decimal("0"),
            retention_withheld=Decimal("0"),
        )
        assert calc["revised_contract_value"] == Decimal("105000")

    def test_work_completed_this_period(self):
        calc = ProgressClaimService.calculate_fields(
            contract_value=Decimal("100000"),
            variations_to_date=Decimal("0"),
            work_completed_to_date=Decimal("50000"),
            work_completed_previous=Decimal("20000"),
            materials_on_site=Decimal("0"),
            retention_withheld=Decimal("0"),
        )
        assert calc["work_completed_this_period"] == Decimal("30000")

    def test_amount_due_with_retention(self):
        calc = ProgressClaimService.calculate_fields(
            contract_value=Decimal("100000"),
            variations_to_date=Decimal("0"),
            work_completed_to_date=Decimal("50000"),
            work_completed_previous=Decimal("20000"),
            materials_on_site=Decimal("5000"),
            retention_withheld=Decimal("3000"),
        )
        # amount_due = 30000 + 5000 - 3000 = 32000
        assert calc["amount_due"] == Decimal("32000")

    def test_completion_percentage(self):
        calc = ProgressClaimService.calculate_fields(
            contract_value=Decimal("100000"),
            variations_to_date=Decimal("0"),
            work_completed_to_date=Decimal("50000"),
            work_completed_previous=Decimal("0"),
            materials_on_site=Decimal("0"),
            retention_withheld=Decimal("0"),
        )
        assert calc["completion_percentage"] == Decimal("50.00")

    def test_validate_cumulative_within_contract(self):
        # Should not raise
        ProgressClaimService.validate_cumulative_not_exceeding_contract(
            Decimal("50000"), Decimal("100000"),
        )

    def test_validate_cumulative_exceeds_contract(self):
        with pytest.raises(ValueError, match="exceeds revised contract value"):
            ProgressClaimService.validate_cumulative_not_exceeding_contract(
                Decimal("110000"), Decimal("100000"),
            )
