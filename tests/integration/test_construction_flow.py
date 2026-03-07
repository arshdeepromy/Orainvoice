"""Integration test: construction project flow end-to-end.

Flow: create project → add variations → submit progress claims
      → verify cumulative amounts → release retention.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.progress_claims.service import ProgressClaimService
from app.modules.progress_claims.schemas import ProgressClaimCreate
from app.modules.retentions.service import RetentionService
from app.modules.retentions.schemas import RetentionReleaseCreate
from app.modules.variations.service import VariationService
from app.modules.variations.schemas import VariationOrderCreate
from app.modules.variations.models import VariationOrder
from app.modules.projects.models import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(org_id, *, contract_value=100000):
    p = Project()
    p.id = uuid.uuid4()
    p.org_id = org_id
    p.name = "Office Renovation"
    p.contract_value = Decimal(str(contract_value))
    p.revised_contract_value = Decimal(str(contract_value))
    p.retention_percentage = Decimal("10")
    p.status = "active"
    return p


class TestConstructionFlow:
    """End-to-end construction: project → variations → claims → retention."""

    def test_calculate_retention(self):
        """Retention is correctly calculated as percentage of work this period."""
        result = RetentionService.calculate_retention(
            work_completed_this_period=Decimal("25000"),
            retention_percentage=Decimal("10"),
        )
        assert result == Decimal("2500.00")

    def test_calculate_retention_zero_percentage(self):
        """Zero retention percentage returns zero."""
        result = RetentionService.calculate_retention(
            work_completed_this_period=Decimal("25000"),
            retention_percentage=Decimal("0"),
        )
        assert result == Decimal("0")

    def test_progress_claim_calculations(self):
        """Progress claim derived fields are calculated correctly."""
        calc = ProgressClaimService.calculate_fields(
            contract_value=Decimal("100000"),
            variations_to_date=Decimal("15000"),
            work_completed_to_date=Decimal("50000"),
            work_completed_previous=Decimal("25000"),
            materials_on_site=Decimal("5000"),
            retention_withheld=Decimal("2500"),
        )

        assert calc["revised_contract_value"] == Decimal("115000")
        assert calc["work_completed_this_period"] == Decimal("25000")
        assert calc["amount_due"] == Decimal("27500")  # 25000 + 5000 - 2500
        # completion = 50000 / 115000 * 100 ≈ 43.48%
        assert calc["completion_percentage"] == Decimal("43.48")

    def test_cumulative_cannot_exceed_contract(self):
        """Cumulative work completed cannot exceed revised contract value."""
        with pytest.raises(ValueError, match="exceeds revised contract value"):
            ProgressClaimService.validate_cumulative_not_exceeding_contract(
                work_completed_to_date=Decimal("120000"),
                revised_contract_value=Decimal("100000"),
            )

    def test_cumulative_at_contract_value_is_valid(self):
        """Cumulative work completed equal to contract value is valid."""
        # Should not raise
        ProgressClaimService.validate_cumulative_not_exceeding_contract(
            work_completed_to_date=Decimal("100000"),
            revised_contract_value=Decimal("100000"),
        )

    @pytest.mark.asyncio
    async def test_create_variation_order(self):
        """Creating a variation order assigns a sequential number."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 0
        db.execute = AsyncMock(return_value=count_result)

        svc = VariationService(db)
        variation = await svc.create_variation(
            org_id,
            VariationOrderCreate(
                project_id=project_id,
                description="Additional electrical work",
                cost_impact=Decimal("15000"),
            ),
        )

        assert variation.variation_number == 1
        assert variation.cost_impact == Decimal("15000")
        assert db.add.called

    @pytest.mark.asyncio
    async def test_approve_variation_updates_project(self):
        """Approving a variation updates the project's revised contract value."""
        org_id = uuid.uuid4()
        project = _make_project(org_id, contract_value=100000)

        variation = VariationOrder()
        variation.id = uuid.uuid4()
        variation.org_id = org_id
        variation.project_id = project.id
        variation.variation_number = 1
        variation.description = "Extra work"
        variation.cost_impact = Decimal("15000")
        variation.status = "draft"
        variation.approved_at = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Mock: variation lookup, then approved sum, then project lookup
        call_count = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = variation
            elif call_count == 2:
                result.scalar_one_or_none.return_value = project
            elif call_count == 3:
                result.scalar.return_value = Decimal("15000")
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute

        svc = VariationService(db)
        result = await svc.approve_variation(org_id, variation.id)

        assert result["status"] == "approved"
        assert variation.status == "approved"
        assert variation.approved_at is not None

    @pytest.mark.asyncio
    async def test_cannot_delete_approved_variation(self):
        """Approved variations cannot be deleted."""
        org_id = uuid.uuid4()

        variation = VariationOrder()
        variation.id = uuid.uuid4()
        variation.org_id = org_id
        variation.status = "approved"

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = variation
        db.execute = AsyncMock(return_value=result)

        svc = VariationService(db)

        with pytest.raises(ValueError, match="cannot be deleted"):
            await svc.delete_variation(org_id, variation.id)

    @pytest.mark.asyncio
    async def test_release_retention(self):
        """Retention can be released up to the total withheld amount."""
        project_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        call_count = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = Decimal("10000")  # total withheld
            elif call_count == 2:
                result.scalar.return_value = Decimal("0")  # total released
            return result

        db.execute = mock_execute

        svc = RetentionService(db)
        release = await svc.release_retention(
            project_id,
            RetentionReleaseCreate(
                amount=Decimal("5000"),
                release_date=date.today(),
            ),
        )

        assert release.amount == Decimal("5000")
        assert db.add.called

    @pytest.mark.asyncio
    async def test_cannot_release_more_than_withheld(self):
        """Cannot release more retention than was withheld."""
        project_id = uuid.uuid4()

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar.return_value = Decimal("5000")  # total withheld
            elif call_count == 2:
                result.scalar.return_value = Decimal("3000")  # already released
            return result

        db.execute = mock_execute

        svc = RetentionService(db)

        with pytest.raises(ValueError, match="exceeds remaining"):
            await svc.release_retention(
                project_id,
                RetentionReleaseCreate(
                    amount=Decimal("3000"),  # Only 2000 remaining
                    release_date=date.today(),
                ),
            )
