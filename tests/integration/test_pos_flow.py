"""Integration test: POS session flow end-to-end.

Flow: open session → complete transactions → process offline sync
      → close session → verify reconciliation.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.pos.models import POSSession, POSTransaction
from app.modules.pos.service import POSService
from app.modules.pos.schemas import (
    OfflineTransaction,
    OfflineTransactionItem,
    SessionCloseRequest,
    SessionOpenRequest,
    TransactionCreateRequest,
    TransactionLineItem,
)
from app.modules.products.models import Product


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(org_id, *, stock_quantity=100, sale_price=25.0):
    p = Product()
    p.id = uuid.uuid4()
    p.org_id = org_id
    p.name = "Coffee"
    p.sku = "COF-001"
    p.sale_price = Decimal(str(sale_price))
    p.stock_quantity = Decimal(str(stock_quantity))
    p.is_active = True
    return p


def _make_db_for_pos(*, product=None, session=None):
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    async def mock_execute(stmt, params=None):
        result = MagicMock()
        sql_str = str(stmt) if not isinstance(stmt, MagicMock) else ""

        if "pos_sessions" in sql_str.lower() and session is not None:
            result.scalar_one_or_none.return_value = session
        elif "products" in sql_str.lower() and product is not None:
            result.scalar_one_or_none.return_value = product
        else:
            result.scalar_one_or_none.return_value = None
            result.scalar.return_value = 0
            result.scalars.return_value.all.return_value = []
        return result

    db.execute = mock_execute
    return db


class TestPOSFlow:
    """End-to-end POS: open → transact → offline sync → close → reconcile."""

    @pytest.mark.asyncio
    async def test_open_session(self):
        """Opening a POS session creates a session record."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db = _make_db_for_pos()
        svc = POSService(db)

        session = await svc.open_session(
            org_id, user_id,
            SessionOpenRequest(opening_cash=Decimal("200.00")),
        )

        assert session.status == "open"
        assert session.opening_cash == Decimal("200.00")
        assert session.org_id == org_id
        assert db.add.called

    @pytest.mark.asyncio
    async def test_complete_transaction(self):
        """Completing a transaction creates a record and decrements stock."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        product = _make_product(org_id, stock_quantity=50, sale_price=25.0)
        db = _make_db_for_pos(product=product)
        svc = POSService(db)

        txn = await svc.complete_transaction(
            org_id, user_id,
            TransactionCreateRequest(
                payment_method="cash",
                line_items=[
                    TransactionLineItem(
                        product_id=product.id,
                        product_name="Coffee",
                        quantity=Decimal("2"),
                        unit_price=Decimal("25.00"),
                        tax_amount=Decimal("7.50"),
                    ),
                ],
                cash_tendered=Decimal("60.00"),
            ),
        )

        assert txn.payment_method == "cash"
        assert txn.subtotal == Decimal("50.00")
        assert txn.tax_amount == Decimal("7.50")
        assert txn.is_offline_sync is False

    @pytest.mark.asyncio
    async def test_offline_sync_no_conflicts(self):
        """Syncing offline transactions with no conflicts succeeds."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        product = _make_product(org_id, stock_quantity=100, sale_price=25.0)
        db = _make_db_for_pos(product=product)
        svc = POSService(db)

        offline_txns = [
            OfflineTransaction(
                offline_id="offline-001",
                timestamp=datetime.now(timezone.utc),
                payment_method="card",
                line_items=[
                    OfflineTransactionItem(
                        product_id=product.id,
                        product_name="Coffee",
                        quantity=Decimal("1"),
                        price=Decimal("25.00"),
                    ),
                ],
                subtotal=Decimal("25.00"),
                tax_amount=Decimal("3.75"),
                total=Decimal("28.75"),
            ),
        ]

        report = await svc.sync_offline_transactions(org_id, user_id, offline_txns)

        assert report.total == 1
        assert report.successes == 1
        assert report.conflicts == 0
        assert report.failures == 0

    @pytest.mark.asyncio
    async def test_offline_sync_detects_price_conflict(self):
        """Syncing detects price changes between offline and current price."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        product = _make_product(org_id, stock_quantity=100, sale_price=30.0)
        db = _make_db_for_pos(product=product)
        svc = POSService(db)

        offline_txns = [
            OfflineTransaction(
                offline_id="offline-002",
                timestamp=datetime.now(timezone.utc),
                payment_method="cash",
                line_items=[
                    OfflineTransactionItem(
                        product_id=product.id,
                        product_name="Coffee",
                        quantity=Decimal("1"),
                        price=Decimal("25.00"),  # Offline price differs
                    ),
                ],
                subtotal=Decimal("25.00"),
                tax_amount=Decimal("3.75"),
                total=Decimal("28.75"),
                cash_tendered=Decimal("30.00"),
            ),
        ]

        report = await svc.sync_offline_transactions(org_id, user_id, offline_txns)

        assert report.total == 1
        assert report.conflicts == 1
        assert report.results[0].status == "conflict"
        assert any(c.type == "price_changed" for c in report.results[0].conflicts)

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Closing a POS session records closing cash and timestamp."""
        org_id = uuid.uuid4()

        session = POSSession()
        session.id = uuid.uuid4()
        session.org_id = org_id
        session.user_id = uuid.uuid4()
        session.status = "open"
        session.opening_cash = Decimal("200.00")
        session.closing_cash = None
        session.closed_at = None

        db = _make_db_for_pos(session=session)
        svc = POSService(db)

        result = await svc.close_session(
            org_id,
            SessionCloseRequest(
                session_id=session.id,
                closing_cash=Decimal("350.00"),
            ),
        )

        assert result.status == "closed"
        assert result.closing_cash == Decimal("350.00")
        assert result.closed_at is not None

    @pytest.mark.asyncio
    async def test_cannot_close_already_closed_session(self):
        """Closing an already-closed session raises an error."""
        org_id = uuid.uuid4()

        session = POSSession()
        session.id = uuid.uuid4()
        session.org_id = org_id
        session.status = "closed"

        db = _make_db_for_pos(session=session)
        svc = POSService(db)

        with pytest.raises(ValueError, match="not open"):
            await svc.close_session(
                org_id,
                SessionCloseRequest(
                    session_id=session.id,
                    closing_cash=Decimal("100.00"),
                ),
            )
