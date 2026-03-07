"""Tests: offline sync conflict detection and handling.

**Validates: Requirement 22.7, 22.8 — Tasks 28.9, 28.10**

- 28.9: offline sync with price change uses offline price and records discrepancy
- 28.10: offline sync with insufficient stock allows negative stock and flags discrepancy
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.pos.models import POSTransaction
from app.modules.pos.schemas import (
    OfflineTransaction,
    OfflineTransactionItem,
)
from app.modules.pos.service import POSService
from app.modules.products.models import Product


ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_product(
    product_id: uuid.UUID,
    sale_price: Decimal = Decimal("25.00"),
    stock_qty: Decimal = Decimal("100"),
    is_active: bool = True,
) -> Product:
    return Product(
        id=product_id,
        org_id=ORG_ID,
        name="Test Product",
        sale_price=sale_price,
        stock_quantity=stock_qty,
        is_active=is_active,
    )


def _make_mock_db(products: dict[uuid.UUID, Product]):
    mock_db = AsyncMock()
    added_objects: list = []
    mock_db.add = lambda obj: added_objects.append(obj)
    mock_db.flush = AsyncMock()
    mock_db._added = added_objects

    async def fake_execute(stmt):
        mock_result = MagicMock()
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            stmt_str = str(compiled)
            found = None
            for pid, product in products.items():
                if str(pid) in stmt_str or pid.hex in stmt_str:
                    found = product
                    break
            mock_result.scalar_one_or_none.return_value = found
        except Exception:
            mock_result.scalar_one_or_none.return_value = None
        return mock_result

    mock_db.execute = fake_execute
    return mock_db


def _make_offline_txn(
    offline_id: str,
    product_id: uuid.UUID,
    price: Decimal,
    quantity: Decimal,
) -> OfflineTransaction:
    subtotal = price * quantity
    tax = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    return OfflineTransaction(
        offline_id=offline_id,
        timestamp=datetime.now(timezone.utc),
        payment_method="cash",
        line_items=[
            OfflineTransactionItem(
                product_id=product_id,
                product_name="Test Product",
                quantity=quantity,
                price=price,
                tax_amount=tax,
            ),
        ],
        subtotal=subtotal,
        tax_amount=tax,
        total=subtotal + tax,
        cash_tendered=subtotal + tax + Decimal("10"),
        change_given=Decimal("10"),
    )


class TestOfflineSyncPriceChange:
    """Validates: offline sync with price change uses offline price
    and records discrepancy.

    **Validates: Requirement 22.8**
    """

    @pytest.mark.asyncio
    async def test_price_change_creates_transaction_with_offline_price(self):
        """When a product price changed since the offline transaction,
        the transaction is created with the offline price and a
        price_changed conflict is recorded."""
        pid = uuid.uuid4()
        offline_price = Decimal("20.00")
        current_price = Decimal("25.00")  # Price changed on server

        product = _make_product(pid, current_price, Decimal("100"))
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        offline_txn = _make_offline_txn("txn-price-1", pid, offline_price, Decimal("2"))
        report = await svc.sync_offline_transactions(ORG_ID, USER_ID, [offline_txn])

        assert report.total == 1
        assert report.conflicts == 1
        assert report.successes == 0

        result = report.results[0]
        assert result.status == "conflict"
        assert result.offline_id == "txn-price-1"

        # Verify price_changed conflict is recorded
        price_conflicts = [c for c in result.conflicts if c.type == "price_changed"]
        assert len(price_conflicts) == 1
        assert price_conflicts[0].product_id == pid
        assert "20.00" in price_conflicts[0].detail
        assert "25.00" in price_conflicts[0].detail

        # Transaction was still created (with offline values)
        created_txns = [
            obj for obj in mock_db._added if isinstance(obj, POSTransaction)
        ]
        assert len(created_txns) == 1
        txn = created_txns[0]
        assert txn.subtotal == offline_price * Decimal("2")
        assert txn.is_offline_sync is True
        assert txn.sync_status == "conflict"

    @pytest.mark.asyncio
    async def test_matching_price_no_conflict(self):
        """When the product price matches the offline price, no conflict."""
        pid = uuid.uuid4()
        price = Decimal("20.00")

        product = _make_product(pid, price, Decimal("100"))
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        offline_txn = _make_offline_txn("txn-match-1", pid, price, Decimal("1"))
        report = await svc.sync_offline_transactions(ORG_ID, USER_ID, [offline_txn])

        assert report.total == 1
        assert report.successes == 1
        assert report.conflicts == 0

        result = report.results[0]
        assert result.status == "success"
        assert len(result.conflicts) == 0


class TestOfflineSyncInsufficientStock:
    """Validates: offline sync with insufficient stock allows negative
    stock and flags discrepancy.

    **Validates: Requirement 22.8**
    """

    @pytest.mark.asyncio
    async def test_insufficient_stock_flags_conflict_and_decrements(self):
        """When stock is insufficient, the transaction is created,
        stock is decremented (allowing negative), and an
        insufficient_stock conflict is recorded."""
        pid = uuid.uuid4()
        price = Decimal("15.00")
        available_stock = Decimal("3")
        requested_qty = Decimal("5")

        product = _make_product(pid, price, available_stock)
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        offline_txn = _make_offline_txn("txn-stock-1", pid, price, requested_qty)
        report = await svc.sync_offline_transactions(ORG_ID, USER_ID, [offline_txn])

        assert report.total == 1
        assert report.conflicts == 1

        result = report.results[0]
        assert result.status == "conflict"

        # Verify insufficient_stock conflict
        stock_conflicts = [c for c in result.conflicts if c.type == "insufficient_stock"]
        assert len(stock_conflicts) == 1
        assert stock_conflicts[0].product_id == pid
        assert "3" in stock_conflicts[0].detail
        assert "5" in stock_conflicts[0].detail

        # Stock was still decremented (allowing negative)
        assert product.stock_quantity == available_stock - requested_qty
        assert product.stock_quantity == Decimal("-2")

    @pytest.mark.asyncio
    async def test_sufficient_stock_no_conflict(self):
        """When stock is sufficient, no insufficient_stock conflict."""
        pid = uuid.uuid4()
        price = Decimal("15.00")
        available_stock = Decimal("10")
        requested_qty = Decimal("3")

        product = _make_product(pid, price, available_stock)
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        offline_txn = _make_offline_txn("txn-stock-ok", pid, price, requested_qty)
        report = await svc.sync_offline_transactions(ORG_ID, USER_ID, [offline_txn])

        assert report.total == 1
        assert report.successes == 1
        assert report.conflicts == 0

        # Stock decremented normally
        assert product.stock_quantity == Decimal("7")
