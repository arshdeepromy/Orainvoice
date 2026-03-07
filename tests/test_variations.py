"""Tests for variation orders module.

**Validates: Requirement 29 — Variation Module**

- Approved variations cannot be deleted
- Offsetting variation required to reverse approved changes
- CRUD operations and approval workflow
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.variations.models import VariationOrder
from app.modules.variations.schemas import VariationOrderCreate, VariationOrderUpdate
from app.modules.variations.service import VariationService


def _make_mock_db():
    """Create a mock async DB session."""
    mock_db = AsyncMock()
    added_objects: list = []

    async def fake_flush():
        pass

    def fake_add(obj):
        added_objects.append(obj)

    async def fake_delete(obj):
        pass

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    mock_db.delete = fake_delete
    mock_db._added = added_objects
    return mock_db


def _make_variation(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    variation_number: int = 1,
    cost_impact: Decimal = Decimal("5000.00"),
    status: str = "draft",
    description: str = "Test variation",
) -> VariationOrder:
    """Create a VariationOrder instance for testing."""
    v = VariationOrder(
        id=uuid.uuid4(),
        org_id=org_id,
        project_id=project_id,
        variation_number=variation_number,
        description=description,
        cost_impact=cost_impact,
        status=status,
        created_at=datetime.now(timezone.utc),
    )
    if status == "approved":
        v.approved_at = datetime.now(timezone.utc)
    if status == "submitted":
        v.submitted_at = datetime.now(timezone.utc)
    return v


class TestApprovedVariationCannotBeDeleted:
    """Validates: Requirement 29.5 — approved variations cannot be deleted."""

    @pytest.mark.asyncio
    async def test_delete_approved_variation_raises_error(self):
        """Deleting an approved variation raises ValueError with offsetting message."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="approved")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        with pytest.raises(ValueError, match="Approved variations cannot be deleted"):
            await svc.delete_variation(org_id, variation.id)

    @pytest.mark.asyncio
    async def test_delete_approved_variation_suggests_offsetting(self):
        """Error message suggests creating an offsetting variation."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="approved")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        with pytest.raises(ValueError, match="offsetting variation"):
            await svc.delete_variation(org_id, variation.id)

    @pytest.mark.asyncio
    async def test_delete_draft_variation_succeeds(self):
        """Draft variations can be deleted."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="draft")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        # Should not raise
        await svc.delete_variation(org_id, variation.id)

    @pytest.mark.asyncio
    async def test_delete_submitted_variation_succeeds(self):
        """Submitted (not yet approved) variations can be deleted."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="submitted")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        # Should not raise
        await svc.delete_variation(org_id, variation.id)

    @pytest.mark.asyncio
    async def test_delete_rejected_variation_succeeds(self):
        """Rejected variations can be deleted."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="rejected")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        # Should not raise
        await svc.delete_variation(org_id, variation.id)


class TestVariationApproval:
    """Test variation approval workflow."""

    @pytest.mark.asyncio
    async def test_approve_submitted_variation(self):
        """Approving a submitted variation sets status and approved_at."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="submitted")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        # Mock for get_variation and _update_project_revised_value
        call_count = [0]
        async def fake_execute(stmt):
            call_count[0] += 1
            if call_count[0] <= 1:
                return mock_result
            # For project lookup and sum queries, return None/0
            mock_scalar = MagicMock()
            mock_scalar.scalar_one_or_none.return_value = None
            mock_scalar.scalar.return_value = Decimal("0")
            return mock_scalar

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        result = await svc.approve_variation(org_id, variation.id)

        assert result["status"] == "approved"
        assert result["cost_impact"] == Decimal("5000.00")
        assert variation.status == "approved"
        assert variation.approved_at is not None

    @pytest.mark.asyncio
    async def test_approve_already_approved_raises(self):
        """Cannot approve an already approved variation."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="approved")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        with pytest.raises(ValueError, match="Cannot approve"):
            await svc.approve_variation(org_id, variation.id)


class TestVariationUpdate:
    """Test variation update restrictions."""

    @pytest.mark.asyncio
    async def test_update_draft_variation_succeeds(self):
        """Draft variations can be updated."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="draft")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        payload = VariationOrderUpdate(description="Updated description")
        result = await svc.update_variation(org_id, variation.id, payload)

        assert result is not None
        assert result.description == "Updated description"

    @pytest.mark.asyncio
    async def test_update_approved_variation_raises(self):
        """Approved variations cannot be updated."""
        org_id = uuid.uuid4()
        project_id = uuid.uuid4()
        variation = _make_variation(org_id, project_id, status="approved")

        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = variation

        async def fake_execute(stmt):
            return mock_result

        mock_db.execute = fake_execute

        svc = VariationService(mock_db)
        payload = VariationOrderUpdate(description="Should fail")
        with pytest.raises(ValueError, match="Only draft variations"):
            await svc.update_variation(org_id, variation.id, payload)
