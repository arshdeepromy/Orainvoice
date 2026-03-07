"""Tests for inventory stock operations.

**Validates: Requirement 9.3, 9.4, 9.5, 9.6**

Tests:
- Invoice issuance decrements stock, credit note increments stock
- Low stock alert triggers when quantity falls below threshold
- Zero stock blocks invoice line item when backorder disabled
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.products.models import Product
from app.modules.products.service import ProductService
from app.modules.stock.service import StockService


def _make_product(**kwargs) -> Product:
    """Create a Product instance for testing."""
    defaults = {
        "id": uuid.uuid4(),
        "org_id": uuid.uuid4(),
        "name": "Test Product",
        "stock_quantity": Decimal("100"),
        "sale_price": Decimal("10.00"),
        "low_stock_threshold": Decimal("10"),
        "allow_backorder": False,
    }
    defaults.update(kwargs)
    return Product(**defaults)


def _make_stock_service() -> StockService:
    """Create a StockService with mocked DB."""
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.add = MagicMock()
    return StockService(mock_db)


class TestInvoiceStockDecrement:
    """Invoice issuance decrements stock, credit note increments stock.

    **Validates: Requirement 9.3, 9.4**
    """

    @pytest.mark.asyncio
    async def test_invoice_issuance_decrements_stock(self):
        """When an invoice is issued, stock should be decremented."""
        product = _make_product(stock_quantity=Decimal("100"))
        svc = _make_stock_service()

        movement = await svc.decrement_stock(
            product, Decimal("5"),
            reference_type="invoice", reference_id=uuid.uuid4(),
        )

        assert product.stock_quantity == Decimal("95")
        assert movement.quantity_change == Decimal("-5")
        assert movement.resulting_quantity == Decimal("95")
        assert movement.movement_type == "sale"
        assert movement.reference_type == "invoice"

    @pytest.mark.asyncio
    async def test_credit_note_increments_stock(self):
        """When a credit note is issued, stock should be incremented."""
        product = _make_product(stock_quantity=Decimal("95"))
        svc = _make_stock_service()

        movement = await svc.increment_stock(
            product, Decimal("5"),
            movement_type="credit",
            reference_type="credit_note", reference_id=uuid.uuid4(),
        )

        assert product.stock_quantity == Decimal("100")
        assert movement.quantity_change == Decimal("5")
        assert movement.resulting_quantity == Decimal("100")
        assert movement.movement_type == "credit"

    @pytest.mark.asyncio
    async def test_multiple_invoice_lines_decrement_correctly(self):
        """Multiple line items on an invoice each decrement stock."""
        product = _make_product(stock_quantity=Decimal("50"))
        svc = _make_stock_service()
        invoice_id = uuid.uuid4()

        # Simulate 3 line items of different quantities
        await svc.decrement_stock(product, Decimal("10"), reference_type="invoice", reference_id=invoice_id)
        await svc.decrement_stock(product, Decimal("15"), reference_type="invoice", reference_id=invoice_id)
        await svc.decrement_stock(product, Decimal("5"), reference_type="invoice", reference_id=invoice_id)

        assert product.stock_quantity == Decimal("20")


class TestLowStockAlert:
    """Low stock alert triggers when quantity falls below threshold.

    **Validates: Requirement 9.5**
    """

    def test_low_stock_detected_at_threshold(self):
        """Alert triggers when stock equals the threshold."""
        product = _make_product(
            stock_quantity=Decimal("10"),
            low_stock_threshold=Decimal("10"),
        )
        svc = ProductService(AsyncMock())
        assert svc.check_low_stock(product) is True

    def test_low_stock_detected_below_threshold(self):
        """Alert triggers when stock is below the threshold."""
        product = _make_product(
            stock_quantity=Decimal("5"),
            low_stock_threshold=Decimal("10"),
        )
        svc = ProductService(AsyncMock())
        assert svc.check_low_stock(product) is True

    def test_no_alert_above_threshold(self):
        """No alert when stock is above the threshold."""
        product = _make_product(
            stock_quantity=Decimal("15"),
            low_stock_threshold=Decimal("10"),
        )
        svc = ProductService(AsyncMock())
        assert svc.check_low_stock(product) is False

    @pytest.mark.asyncio
    async def test_low_stock_after_decrement(self):
        """Alert triggers after a sale brings stock to threshold."""
        product = _make_product(
            stock_quantity=Decimal("15"),
            low_stock_threshold=Decimal("10"),
        )
        stock_svc = _make_stock_service()
        product_svc = ProductService(AsyncMock())

        assert product_svc.check_low_stock(product) is False

        await stock_svc.decrement_stock(product, Decimal("5"))

        assert product.stock_quantity == Decimal("10")
        assert product_svc.check_low_stock(product) is True


class TestZeroStockBlocking:
    """Zero stock blocks invoice line item when backorder disabled.

    **Validates: Requirement 9.6**
    """

    def test_zero_stock_blocks_when_backorder_disabled(self):
        """Cannot add to invoice when stock is zero and backorder off."""
        product = _make_product(
            stock_quantity=Decimal("0"),
            allow_backorder=False,
        )
        svc = ProductService(AsyncMock())
        assert svc.can_add_to_invoice(product, Decimal("1")) is False

    def test_insufficient_stock_blocks_when_backorder_disabled(self):
        """Cannot add quantity exceeding stock when backorder off."""
        product = _make_product(
            stock_quantity=Decimal("3"),
            allow_backorder=False,
        )
        svc = ProductService(AsyncMock())
        assert svc.can_add_to_invoice(product, Decimal("5")) is False

    def test_sufficient_stock_allows_when_backorder_disabled(self):
        """Can add when stock is sufficient even with backorder off."""
        product = _make_product(
            stock_quantity=Decimal("10"),
            allow_backorder=False,
        )
        svc = ProductService(AsyncMock())
        assert svc.can_add_to_invoice(product, Decimal("5")) is True

    def test_zero_stock_allowed_when_backorder_enabled(self):
        """Can add to invoice when stock is zero but backorder is on."""
        product = _make_product(
            stock_quantity=Decimal("0"),
            allow_backorder=True,
        )
        svc = ProductService(AsyncMock())
        assert svc.can_add_to_invoice(product, Decimal("10")) is True

    def test_negative_stock_allowed_when_backorder_enabled(self):
        """Backorder mode allows going negative."""
        product = _make_product(
            stock_quantity=Decimal("-5"),
            allow_backorder=True,
        )
        svc = ProductService(AsyncMock())
        assert svc.can_add_to_invoice(product, Decimal("10")) is True
