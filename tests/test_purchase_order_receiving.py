"""Test: receiving goods creates stock movements and increments product quantities.

**Validates: Requirement 16.2 — Purchase Order Module**

Verifies that when goods are received against a purchase order:
- Stock movements are created via StockService
- Product stock quantities are incremented
- PO status transitions correctly (draft → partial → received)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.products.models import Product
from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.modules.purchase_orders.schemas import ReceiveGoodsRequest, ReceiveLine
from app.modules.purchase_orders.service import PurchaseOrderService
from app.modules.stock.models import StockMovement


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


def _make_product(org_id: uuid.UUID, stock_qty: Decimal = Decimal("10")) -> Product:
    """Create a Product instance for testing."""
    return Product(
        id=uuid.uuid4(),
        org_id=org_id,
        name="Test Widget",
        stock_quantity=stock_qty,
        sale_price=Decimal("25.00"),
        cost_price=Decimal("10.00"),
    )


def _make_po_with_lines(
    org_id: uuid.UUID,
    products: list[Product],
    quantities: list[Decimal],
    *,
    status: str = "sent",
) -> PurchaseOrder:
    """Create a PurchaseOrder with lines for testing."""
    po = PurchaseOrder(
        id=uuid.uuid4(),
        org_id=org_id,
        po_number="PO-00001",
        supplier_id=uuid.uuid4(),
        status=status,
        total_amount=Decimal("0"),
    )
    po.lines = []
    for product, qty in zip(products, quantities):
        line = PurchaseOrderLine(
            id=uuid.uuid4(),
            po_id=po.id,
            product_id=product.id,
            quantity_ordered=qty,
            quantity_received=Decimal("0"),
            unit_cost=Decimal("10.00"),
            line_total=qty * Decimal("10.00"),
        )
        po.lines.append(line)
    po.total_amount = sum(l.line_total for l in po.lines)
    return po


class TestReceiveGoodsCreatesStockMovements:
    """Validates: Requirement 16.2 — receiving goods creates stock movements."""

    @pytest.mark.asyncio
    async def test_full_receive_increments_stock_and_creates_movements(self):
        """Receiving all ordered quantities increments stock and sets status to received."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_qty=Decimal("10"))
        po = _make_po_with_lines(org_id, [product], [Decimal("5")])

        mock_db = _make_mock_db()

        # Mock get_purchase_order to return our PO
        async def fake_execute(stmt):
            mock_result = MagicMock()
            # Check if this is a product query or PO query
            stmt_str = str(stmt)
            if "products" in stmt_str:
                mock_result.scalar_one_or_none.return_value = product
            else:
                mock_result.scalar_one_or_none.return_value = po
            return mock_result

        mock_db.execute = fake_execute

        svc = PurchaseOrderService(mock_db)

        payload = ReceiveGoodsRequest(
            lines=[ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("5"))],
        )

        result = await svc.receive_goods(org_id, po.id, payload)

        assert result is not None
        assert result.status == "received"
        assert result.lines[0].quantity_received == Decimal("5")
        # Product stock should have been incremented
        assert product.stock_quantity == Decimal("15")

    @pytest.mark.asyncio
    async def test_receive_creates_stock_movement_with_correct_type(self):
        """Stock movement should have type 'receive' and reference the PO."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_qty=Decimal("0"))
        po = _make_po_with_lines(org_id, [product], [Decimal("20")])

        mock_db = _make_mock_db()
        created_movements: list = []

        original_add = mock_db.add

        def tracking_add(obj):
            original_add(obj)
            if isinstance(obj, StockMovement):
                created_movements.append(obj)

        mock_db.add = tracking_add

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "products" in stmt_str:
                mock_result.scalar_one_or_none.return_value = product
            else:
                mock_result.scalar_one_or_none.return_value = po
            return mock_result

        mock_db.execute = fake_execute

        svc = PurchaseOrderService(mock_db)
        payload = ReceiveGoodsRequest(
            lines=[ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("20"))],
        )

        await svc.receive_goods(org_id, po.id, payload)

        assert len(created_movements) == 1
        movement = created_movements[0]
        assert movement.movement_type == "receive"
        assert movement.reference_type == "purchase_order"
        assert movement.reference_id == po.id
        assert movement.quantity_change == Decimal("20")
        assert product.stock_quantity == Decimal("20")

    @pytest.mark.asyncio
    async def test_receive_on_cancelled_po_raises_error(self):
        """Cannot receive goods on a cancelled PO."""
        org_id = uuid.uuid4()
        product = _make_product(org_id)
        po = _make_po_with_lines(org_id, [product], [Decimal("5")], status="cancelled")

        mock_db = _make_mock_db()

        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = po
            return mock_result

        mock_db.execute = fake_execute

        svc = PurchaseOrderService(mock_db)
        payload = ReceiveGoodsRequest(
            lines=[ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("5"))],
        )

        with pytest.raises(ValueError, match="cancelled"):
            await svc.receive_goods(org_id, po.id, payload)

    @pytest.mark.asyncio
    async def test_receive_multiple_products(self):
        """Receiving multiple line items increments each product's stock."""
        org_id = uuid.uuid4()
        product_a = _make_product(org_id, stock_qty=Decimal("5"))
        product_a.name = "Widget A"
        product_b = _make_product(org_id, stock_qty=Decimal("3"))
        product_b.name = "Widget B"

        po = _make_po_with_lines(
            org_id, [product_a, product_b], [Decimal("10"), Decimal("7")],
        )

        mock_db = _make_mock_db()
        product_map = {product_a.id: product_a, product_b.id: product_b}
        product_query_results = iter([product_a, product_b])

        call_count = {"n": 0}

        async def fake_execute(stmt):
            mock_result = MagicMock()
            stmt_str = str(stmt)
            if "products" in stmt_str:
                mock_result.scalar_one_or_none.return_value = next(product_query_results)
            else:
                mock_result.scalar_one_or_none.return_value = po
            return mock_result

        mock_db.execute = fake_execute

        svc = PurchaseOrderService(mock_db)
        payload = ReceiveGoodsRequest(
            lines=[
                ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("10")),
                ReceiveLine(line_id=po.lines[1].id, quantity=Decimal("7")),
            ],
        )

        result = await svc.receive_goods(org_id, po.id, payload)

        assert result.status == "received"
        assert product_a.stock_quantity == Decimal("15")
        assert product_b.stock_quantity == Decimal("10")
