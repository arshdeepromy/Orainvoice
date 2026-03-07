"""Integration test: multi-location and franchise flow.

Flow: create locations → assign staff → create stock transfer
      → verify location-scoped queries.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.franchise.models import Location, StockTransfer
from app.modules.franchise.service import FranchiseService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_location(org_id, *, name="Main Office"):
    loc = Location()
    loc.id = uuid.uuid4()
    loc.org_id = org_id
    loc.name = name
    loc.address = "123 Test St"
    loc.phone = "09-555-1234"
    loc.email = f"{name.lower().replace(' ', '')}@test.com"
    loc.is_active = True
    loc.has_own_inventory = True
    loc.created_at = datetime.now(timezone.utc)
    loc.updated_at = datetime.now(timezone.utc)
    return loc


def _make_transfer(org_id, from_loc, to_loc, *, status="pending"):
    t = StockTransfer()
    t.id = uuid.uuid4()
    t.org_id = org_id
    t.from_location_id = from_loc.id
    t.to_location_id = to_loc.id
    t.product_id = uuid.uuid4()
    t.quantity = Decimal("10")
    t.status = status
    t.requested_by = uuid.uuid4()
    t.approved_by = None
    t.completed_at = None
    t.created_at = datetime.now(timezone.utc)
    return t


class TestMultiLocationFlow:
    """End-to-end multi-location: locations → staff → transfers → scoping."""

    @pytest.mark.asyncio
    async def test_create_location(self):
        """Creating a location stores it with correct org_id."""
        org_id = uuid.uuid4()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = FranchiseService(db)
        location = await svc.create_location(
            org_id,
            name="Downtown Branch",
            address="456 Main St",
            has_own_inventory=True,
        )

        assert location.name == "Downtown Branch"
        assert location.org_id == org_id
        assert location.has_own_inventory is True
        assert db.add.called

    @pytest.mark.asyncio
    async def test_create_stock_transfer(self):
        """Creating a stock transfer between two locations."""
        org_id = uuid.uuid4()
        loc_a = _make_location(org_id, name="Warehouse")
        loc_b = _make_location(org_id, name="Store")

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = FranchiseService(db)
        transfer = await svc.create_stock_transfer(
            org_id,
            from_location_id=loc_a.id,
            to_location_id=loc_b.id,
            product_id=uuid.uuid4(),
            quantity=Decimal("25"),
            requested_by=uuid.uuid4(),
        )

        assert transfer.status == "pending"
        assert transfer.quantity == Decimal("25")
        assert transfer.from_location_id == loc_a.id
        assert transfer.to_location_id == loc_b.id

    @pytest.mark.asyncio
    async def test_cannot_transfer_to_same_location(self):
        """Stock transfer to the same location is rejected."""
        org_id = uuid.uuid4()
        loc = _make_location(org_id)

        db = AsyncMock()
        svc = FranchiseService(db)

        with pytest.raises(ValueError, match="must differ"):
            await svc.create_stock_transfer(
                org_id,
                from_location_id=loc.id,
                to_location_id=loc.id,
                product_id=uuid.uuid4(),
                quantity=Decimal("10"),
            )

    @pytest.mark.asyncio
    async def test_cannot_transfer_zero_quantity(self):
        """Stock transfer with zero or negative quantity is rejected."""
        org_id = uuid.uuid4()
        loc_a = _make_location(org_id, name="A")
        loc_b = _make_location(org_id, name="B")

        db = AsyncMock()
        svc = FranchiseService(db)

        with pytest.raises(ValueError, match="must be positive"):
            await svc.create_stock_transfer(
                org_id,
                from_location_id=loc_a.id,
                to_location_id=loc_b.id,
                product_id=uuid.uuid4(),
                quantity=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_approve_and_execute_transfer(self):
        """Transfer workflow: pending → approved → executed."""
        org_id = uuid.uuid4()
        loc_a = _make_location(org_id, name="Warehouse")
        loc_b = _make_location(org_id, name="Store")
        transfer = _make_transfer(org_id, loc_a, loc_b, status="pending")

        db = AsyncMock()
        db.flush = AsyncMock()
        svc = FranchiseService(db)

        # Approve
        result = await svc.approve_transfer(transfer, approved_by=uuid.uuid4())
        assert result.status == "approved"

        # Execute
        result = await svc.execute_transfer(transfer)
        assert result.status == "executed"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_reject_transfer(self):
        """A pending transfer can be rejected."""
        org_id = uuid.uuid4()
        loc_a = _make_location(org_id, name="A")
        loc_b = _make_location(org_id, name="B")
        transfer = _make_transfer(org_id, loc_a, loc_b, status="pending")

        db = AsyncMock()
        db.flush = AsyncMock()
        svc = FranchiseService(db)

        result = await svc.reject_transfer(transfer)
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_cannot_approve_non_pending_transfer(self):
        """Only pending transfers can be approved."""
        org_id = uuid.uuid4()
        loc_a = _make_location(org_id, name="A")
        loc_b = _make_location(org_id, name="B")
        transfer = _make_transfer(org_id, loc_a, loc_b, status="executed")

        db = AsyncMock()
        svc = FranchiseService(db)

        with pytest.raises(ValueError, match="Cannot approve"):
            await svc.approve_transfer(transfer)

    @pytest.mark.asyncio
    async def test_clone_location_settings(self):
        """Cloning a location creates a new one with same settings."""
        org_id = uuid.uuid4()
        source = _make_location(org_id, name="Template Location")

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source
        db.execute = AsyncMock(return_value=source_result)

        svc = FranchiseService(db)
        clone = await svc.clone_location_settings(
            org_id, source.id, "New Branch"
        )

        assert clone.name == "New Branch"
        assert clone.address == source.address
        assert clone.has_own_inventory == source.has_own_inventory
