"""Unit tests for Task 20.1 — inventory stock tracking.

Tests cover:
  - Schema validation for stock adjustment requests
  - get_stock_levels: listing with below_threshold_only filter
  - adjust_stock: manual adjustment with audit logging and validation
  - decrement_stock_for_invoice: auto-decrement on invoice part add
  - get_reorder_alerts: parts below minimum threshold
  - get_stock_report: combined report generation

Requirements: 62.1, 62.2, 62.3, 62.4, 62.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.catalogue.models import PartsCatalogue
from app.modules.inventory.models import StockMovement
from app.modules.inventory.schemas import (
    StockAdjustmentRequest,
    StockLevelResponse,
    ReorderAlertResponse,
    StockMovementResponse,
)
from app.modules.inventory.service import (
    adjust_stock,
    decrement_stock_for_invoice,
    get_reorder_alerts,
    get_stock_levels,
    get_stock_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_part(
    org_id=None,
    name="Brake Pad Set",
    part_number="BP-001",
    default_price=Decimal("45.00"),
    current_stock=20,
    min_stock_threshold=5,
    reorder_quantity=10,
    is_active=True,
):
    """Create a mock PartsCatalogue object with stock fields."""
    part = MagicMock(spec=PartsCatalogue)
    part.id = uuid.uuid4()
    part.org_id = org_id or uuid.uuid4()
    part.name = name
    part.part_number = part_number
    part.default_price = default_price
    part.current_stock = current_stock
    part.min_stock_threshold = min_stock_threshold
    part.reorder_quantity = reorder_quantity
    part.is_active = is_active
    part.created_at = datetime.now(timezone.utc)
    part.updated_at = datetime.now(timezone.utc)
    return part


def _make_movement(
    org_id=None,
    part_id=None,
    quantity_change=-2,
    reason="invoice",
    reference_id=None,
    recorded_by=None,
):
    """Create a mock StockMovement object."""
    mov = MagicMock(spec=StockMovement)
    mov.id = uuid.uuid4()
    mov.org_id = org_id or uuid.uuid4()
    mov.part_id = part_id or uuid.uuid4()
    mov.quantity_change = quantity_change
    mov.reason = reason
    mov.reference_id = reference_id
    mov.recorded_by = recorded_by or uuid.uuid4()
    mov.created_at = datetime.now(timezone.utc)
    return mov


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_count_result(count):
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestStockSchemas:
    """Test Pydantic schema validation for stock operations."""

    def test_adjustment_request_valid(self):
        req = StockAdjustmentRequest(quantity_change=10, reason="Restocked from supplier")
        assert req.quantity_change == 10
        assert req.reason == "Restocked from supplier"

    def test_adjustment_request_negative(self):
        req = StockAdjustmentRequest(quantity_change=-5, reason="Damaged stock removed")
        assert req.quantity_change == -5

    def test_adjustment_request_empty_reason_rejected(self):
        with pytest.raises(Exception):
            StockAdjustmentRequest(quantity_change=10, reason="")

    def test_stock_level_response_serialisation(self):
        resp = StockLevelResponse(
            part_id=str(uuid.uuid4()),
            part_name="Brake Pad",
            part_number="BP-001",
            current_stock=20,
            min_threshold=5,
            reorder_quantity=10,
            is_below_threshold=False,
        )
        assert resp.current_stock == 20
        assert resp.is_below_threshold is False

    def test_reorder_alert_response(self):
        resp = ReorderAlertResponse(
            part_id=str(uuid.uuid4()),
            part_name="Oil Filter",
            current_stock=2,
            min_threshold=5,
            reorder_quantity=20,
        )
        assert resp.current_stock == 2

    def test_movement_response(self):
        resp = StockMovementResponse(
            id=str(uuid.uuid4()),
            part_id=str(uuid.uuid4()),
            quantity_change=-3,
            reason="invoice",
            recorded_by=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        assert resp.quantity_change == -3


# ---------------------------------------------------------------------------
# get_stock_levels tests
# ---------------------------------------------------------------------------


class TestGetStockLevels:
    """Test get_stock_levels service function."""

    @pytest.mark.asyncio
    async def test_returns_all_active_parts(self):
        org_id = uuid.uuid4()
        parts = [_make_part(org_id=org_id), _make_part(org_id=org_id, name="Oil Filter")]
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result(parts),
        ])

        result = await get_stock_levels(db, org_id=org_id)
        assert result["total"] == 2
        assert len(result["stock_levels"]) == 2

    @pytest.mark.asyncio
    async def test_empty_catalogue(self):
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await get_stock_levels(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["stock_levels"] == []

    @pytest.mark.asyncio
    async def test_below_threshold_flag(self):
        """Parts at or below threshold should have is_below_threshold=True."""
        org_id = uuid.uuid4()
        low_part = _make_part(org_id=org_id, current_stock=3, min_stock_threshold=5)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([low_part]),
        ])

        result = await get_stock_levels(db, org_id=org_id)
        assert result["stock_levels"][0]["is_below_threshold"] is True


# ---------------------------------------------------------------------------
# adjust_stock tests
# ---------------------------------------------------------------------------


class TestAdjustStock:
    """Test adjust_stock service function."""

    @pytest.mark.asyncio
    @patch("app.modules.inventory.service.write_audit_log", new_callable=AsyncMock)
    async def test_positive_adjustment(self, mock_audit):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=10)

        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = part
        db.execute = AsyncMock(return_value=scalar_result)

        result = await adjust_stock(
            db,
            org_id=org_id,
            user_id=user_id,
            part_id=part.id,
            quantity_change=5,
            reason="Restocked",
        )

        assert part.current_stock == 15
        assert result["stock_level"]["current_stock"] == 15
        mock_audit.assert_called_once()
        db.add.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.inventory.service.write_audit_log", new_callable=AsyncMock)
    async def test_negative_adjustment(self, mock_audit):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=10)

        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = part
        db.execute = AsyncMock(return_value=scalar_result)

        result = await adjust_stock(
            db,
            org_id=org_id,
            user_id=user_id,
            part_id=part.id,
            quantity_change=-3,
            reason="Damaged",
        )

        assert part.current_stock == 7
        assert result["stock_level"]["current_stock"] == 7

    @pytest.mark.asyncio
    async def test_adjustment_below_zero_raises(self):
        org_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=2)

        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = part
        db.execute = AsyncMock(return_value=scalar_result)

        with pytest.raises(ValueError, match="cannot go below zero"):
            await adjust_stock(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                part_id=part.id,
                quantity_change=-5,
                reason="Too much",
            )

    @pytest.mark.asyncio
    async def test_part_not_found_raises(self):
        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=scalar_result)

        with pytest.raises(ValueError, match="not found"):
            await adjust_stock(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                part_id=uuid.uuid4(),
                quantity_change=5,
                reason="Test",
            )


# ---------------------------------------------------------------------------
# decrement_stock_for_invoice tests
# ---------------------------------------------------------------------------


class TestDecrementStockForInvoice:
    """Test auto-decrement when part added to invoice."""

    @pytest.mark.asyncio
    async def test_decrements_stock(self):
        org_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=20)

        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = part
        db.execute = AsyncMock(return_value=scalar_result)

        result = await decrement_stock_for_invoice(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            part_id=part.id,
            quantity=3,
            invoice_id=uuid.uuid4(),
        )

        assert result is not None
        assert part.current_stock == 17
        assert result["movement"]["reason"] == "invoice"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_decrement_floors_at_zero(self):
        """Stock should not go negative; floor at 0."""
        org_id = uuid.uuid4()
        part = _make_part(org_id=org_id, current_stock=2)

        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = part
        db.execute = AsyncMock(return_value=scalar_result)

        result = await decrement_stock_for_invoice(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            part_id=part.id,
            quantity=5,
            invoice_id=uuid.uuid4(),
        )

        assert part.current_stock == 0

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_part(self):
        """Ad-hoc parts without catalogue entry return None."""
        db = _mock_db_session()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=scalar_result)

        result = await decrement_stock_for_invoice(
            db,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            part_id=uuid.uuid4(),
            quantity=1,
            invoice_id=uuid.uuid4(),
        )

        assert result is None


# ---------------------------------------------------------------------------
# get_reorder_alerts tests
# ---------------------------------------------------------------------------


class TestGetReorderAlerts:
    """Test reorder alert generation."""

    @pytest.mark.asyncio
    async def test_returns_parts_below_threshold(self):
        org_id = uuid.uuid4()
        low_part = _make_part(org_id=org_id, name="Oil Filter", current_stock=2, min_stock_threshold=10)

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalars_result([low_part]))

        result = await get_reorder_alerts(db, org_id=org_id)
        assert result["total"] == 1
        assert result["alerts"][0]["part_name"] == "Oil Filter"

    @pytest.mark.asyncio
    async def test_no_alerts_when_all_stocked(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await get_reorder_alerts(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["alerts"] == []


# ---------------------------------------------------------------------------
# get_stock_report tests
# ---------------------------------------------------------------------------


class TestGetStockReport:
    """Test stock report generation."""

    @pytest.mark.asyncio
    async def test_report_includes_all_sections(self):
        org_id = uuid.uuid4()
        part_ok = _make_part(org_id=org_id, current_stock=20, min_stock_threshold=5)
        part_low = _make_part(
            org_id=org_id, name="Oil Filter", current_stock=2, min_stock_threshold=10
        )
        movement = _make_movement(org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalars_result([part_ok, part_low]),
            _mock_scalars_result([movement]),
        ])

        result = await get_stock_report(db, org_id=org_id)
        assert len(result["current_levels"]) == 2
        assert len(result["below_threshold"]) == 1
        assert result["below_threshold"][0]["part_name"] == "Oil Filter"
        assert len(result["movement_history"]) == 1

    @pytest.mark.asyncio
    async def test_report_empty_org(self):
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        result = await get_stock_report(db, org_id=uuid.uuid4())
        assert result["current_levels"] == []
        assert result["below_threshold"] == []
        assert result["movement_history"] == []
