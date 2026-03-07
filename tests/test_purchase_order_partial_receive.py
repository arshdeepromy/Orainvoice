"""Test: partial receiving tracks outstanding quantities correctly.

**Validates: Requirement 16.3 — Purchase Order Module**

Verifies that partial receiving:
- Updates quantity_received on lines without exceeding quantity_ordered
- Sets PO status to 'partial' when some but not all items received
- Tracks outstanding quantities (ordered - received)
- Rejects over-receiving beyond outstanding quantity
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.products.models import Product
from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.modules.purchase_orders.schemas import ReceiveGoodsRequest, ReceiveLine
from app.modules.purchase_orders.service import PurchaseOrderService


def _make_mock_db():
    mock_db = AsyncMock()

    async def fake_flush():
        pass

    def fake_add(obj):
        pass

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    return mock_db


def _make_product(org_id: uuid.UUID, stock_qty: Decimal = Decimal("0")) -> Product:
    return Product(
        id=uuid.uuid4(), org_id=org_id, name="Test Part",
        stock_quantity=stock_qty, sale_price=Decimal("20.00"),
    )


def _make_po(org_id: uuid.UUID, product: Product, qty: Decimal) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(), org_id=org_id, po_number="PO-00001",
        supplier_id=uuid.uuid4(), status="sent", total_amount=Decimal("0"),
    )
    line = PurchaseOrderLine(
        id=uuid.uuid4(), po_id=po.id, product_id=product.id,
        quantity_ordered=qty, quantity_received=Decimal("0"),
        unit_cost=Decimal("10.00"), line_total=qty * Decimal("10.00"),
    )
    po.lines = [line]
    po.total_amount = line.line_total
    return po


class TestPartialReceiving:
    """Validates: Requirement 16.3 — partial receiving tracks outstanding quantities."""

    @pytest.mark.asyncio
    async def test_partial_receive_sets_status_to_partial(self):
        """Receiving less than ordered sets PO status to 'partial'."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_qty=Decimal("5"))
        po = _make_po(org_id, product, qty=Decimal("20"))

        mock_db = _make_mock_db()

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
            lines=[ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("8"))],
        )

        result = await svc.receive_goods(org_id, po.id, payload)

        assert result.status == "partial"
        assert result.lines[0].quantity_received == Decimal("8")
        assert result.lines[0].quantity_ordered == Decimal("20")
        # Outstanding = 20 - 8 = 12
        outstanding = result.lines[0].quantity_ordered - result.lines[0].quantity_received
        assert outstanding == Decimal("12")

    @pytest.mark.asyncio
    async def test_second_partial_receive_accumulates(self):
        """A second partial receive adds to the existing received quantity."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_qty=Decimal("0"))
        po = _make_po(org_id, product, qty=Decimal("30"))
        # Simulate first partial receive already done
        po.lines[0].quantity_received = Decimal("10")
        po.status = "partial"

        mock_db = _make_mock_db()

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
            lines=[ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("15"))],
        )

        result = await svc.receive_goods(org_id, po.id, payload)

        assert result.status == "partial"
        assert result.lines[0].quantity_received == Decimal("25")
        outstanding = result.lines[0].quantity_ordered - result.lines[0].quantity_received
        assert outstanding == Decimal("5")

    @pytest.mark.asyncio
    async def test_final_receive_completes_po(self):
        """Receiving remaining outstanding quantity sets status to 'received'."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_qty=Decimal("0"))
        po = _make_po(org_id, product, qty=Decimal("10"))
        po.lines[0].quantity_received = Decimal("7")
        po.status = "partial"

        mock_db = _make_mock_db()

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
            lines=[ReceiveLine(line_id=po.lines[0].id, quantity=Decimal("3"))],
        )

        result = await svc.receive_goods(org_id, po.id, payload)

        assert result.status == "received"
        assert result.lines[0].quantity_received == Decimal("10")

    @pytest.mark.asyncio
    async def test_over_receive_raises_error(self):
        """Cannot receive more than the outstanding quantity."""
        org_id = uuid.uuid4()
        product = _make_product(org_id)
        po = _make_po(org_id, product, qty=Decimal("10"))
        po.lines[0].quantity_received = Decimal("8")

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

        with pytest.raises(ValueError, match="outstanding"):
            await svc.receive_goods(org_id, po.id, payload)
