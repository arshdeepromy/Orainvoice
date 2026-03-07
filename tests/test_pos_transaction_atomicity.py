"""Test: POS transaction creates invoice, records payment, decrements stock atomically.

**Validates: Requirement 22.5 — Task 28.8**

Verifies that POSService.complete_transaction() creates a POS transaction
record and decrements stock for each line item within a single DB session.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.pos.models import POSTransaction
from app.modules.pos.schemas import TransactionCreateRequest, TransactionLineItem
from app.modules.pos.service import POSService
from app.modules.products.models import Product


ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()


def _make_product(
    product_id: uuid.UUID,
    sale_price: Decimal = Decimal("25.00"),
    stock_qty: Decimal = Decimal("100"),
) -> Product:
    return Product(
        id=product_id,
        org_id=ORG_ID,
        name="Test Product",
        sale_price=sale_price,
        stock_quantity=stock_qty,
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
                # Check both hyphenated and non-hyphenated UUID formats
                if str(pid) in stmt_str or pid.hex in stmt_str:
                    found = product
                    break
            mock_result.scalar_one_or_none.return_value = found
        except Exception:
            mock_result.scalar_one_or_none.return_value = None
        return mock_result

    mock_db.execute = fake_execute
    return mock_db


class TestPOSTransactionAtomicity:
    """Validates: POS transaction creates record and decrements stock."""

    @pytest.mark.asyncio
    async def test_complete_transaction_creates_record_and_decrements_stock(self):
        """A completed POS transaction creates a POSTransaction and
        decrements stock for each line item."""
        pid1 = uuid.uuid4()
        pid2 = uuid.uuid4()
        product1 = _make_product(pid1, Decimal("10.00"), Decimal("50"))
        product2 = _make_product(pid2, Decimal("20.00"), Decimal("30"))

        mock_db = _make_mock_db({pid1: product1, pid2: product2})
        svc = POSService(mock_db)

        payload = TransactionCreateRequest(
            session_id=SESSION_ID,
            payment_method="cash",
            line_items=[
                TransactionLineItem(
                    product_id=pid1,
                    product_name="Product 1",
                    quantity=Decimal("2"),
                    unit_price=Decimal("10.00"),
                    tax_amount=Decimal("3.00"),
                ),
                TransactionLineItem(
                    product_id=pid2,
                    product_name="Product 2",
                    quantity=Decimal("1"),
                    unit_price=Decimal("20.00"),
                    tax_amount=Decimal("3.00"),
                ),
            ],
            cash_tendered=Decimal("50.00"),
        )

        txn = await svc.complete_transaction(ORG_ID, USER_ID, payload)

        # Transaction record created
        assert isinstance(txn, POSTransaction)
        assert txn.org_id == ORG_ID
        assert txn.session_id == SESSION_ID
        assert txn.payment_method == "cash"
        assert txn.subtotal == Decimal("40.00")  # 10*2 + 20*1
        assert txn.tax_amount == Decimal("6.00")  # 3 + 3
        assert txn.total == Decimal("46.00")
        assert txn.is_offline_sync is False

        # Stock decremented atomically
        assert product1.stock_quantity == Decimal("48")  # 50 - 2
        assert product2.stock_quantity == Decimal("29")  # 30 - 1

    @pytest.mark.asyncio
    async def test_cash_change_calculated(self):
        """Cash payment calculates change correctly."""
        pid = uuid.uuid4()
        product = _make_product(pid, Decimal("15.00"), Decimal("100"))
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        payload = TransactionCreateRequest(
            payment_method="cash",
            line_items=[
                TransactionLineItem(
                    product_id=pid,
                    product_name="Product",
                    quantity=Decimal("1"),
                    unit_price=Decimal("15.00"),
                    tax_amount=Decimal("2.25"),
                ),
            ],
            cash_tendered=Decimal("20.00"),
        )

        txn = await svc.complete_transaction(ORG_ID, USER_ID, payload)
        assert txn.total == Decimal("17.25")
        assert txn.change_given == Decimal("2.75")

    @pytest.mark.asyncio
    async def test_card_payment_no_change(self):
        """Card payment does not calculate change."""
        pid = uuid.uuid4()
        product = _make_product(pid, Decimal("10.00"), Decimal("100"))
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        payload = TransactionCreateRequest(
            payment_method="card",
            line_items=[
                TransactionLineItem(
                    product_id=pid,
                    product_name="Product",
                    quantity=Decimal("1"),
                    unit_price=Decimal("10.00"),
                    tax_amount=Decimal("1.50"),
                ),
            ],
        )

        txn = await svc.complete_transaction(ORG_ID, USER_ID, payload)
        assert txn.change_given is None

    @pytest.mark.asyncio
    async def test_discount_and_tip_applied(self):
        """Order-level discount and tip are reflected in total."""
        pid = uuid.uuid4()
        product = _make_product(pid, Decimal("100.00"), Decimal("50"))
        mock_db = _make_mock_db({pid: product})
        svc = POSService(mock_db)

        payload = TransactionCreateRequest(
            payment_method="card",
            line_items=[
                TransactionLineItem(
                    product_id=pid,
                    product_name="Product",
                    quantity=Decimal("1"),
                    unit_price=Decimal("100.00"),
                    tax_amount=Decimal("15.00"),
                ),
            ],
            discount_amount=Decimal("10.00"),
            tip_amount=Decimal("5.00"),
        )

        txn = await svc.complete_transaction(ORG_ID, USER_ID, payload)
        # total = subtotal(100) + tax(15) - discount(10) + tip(5) = 110
        assert txn.total == Decimal("110.00")
        assert txn.discount_amount == Decimal("10.00")
        assert txn.tip_amount == Decimal("5.00")
