"""Comprehensive property-based tests for POS properties.

Properties covered:
  P9 — Offline Transaction Sync Completeness: every transaction produces
       success or conflict

**Validates: Requirements 9**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS, price_strategy

from app.modules.pos.models import POSTransaction
from app.modules.pos.schemas import (
    OfflineTransaction,
    OfflineTransactionItem,
    SyncReport,
)
from app.modules.pos.service import POSService
from app.modules.products.models import Product


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

quantity_st = st.decimals(
    min_value=Decimal("0.1"), max_value=Decimal("50"),
    places=1, allow_nan=False, allow_infinity=False,
)

payment_method_st = st.sampled_from(["cash", "card", "split"])

product_state_st = st.sampled_from(["matching", "price_changed", "low_stock", "inactive"])


def _make_product(pid, org_id, sale_price, stock_qty, is_active=True):
    return Product(
        id=pid, org_id=org_id, name=f"Product-{pid.hex[:6]}",
        sale_price=sale_price, stock_quantity=stock_qty, is_active=is_active,
    )


def _build_offline_txn(idx, product_ids, prices, quantities, payment_method):
    items = []
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for pid, price, qty in zip(product_ids, prices, quantities):
        line_total = price * qty
        tax = (line_total * Decimal("0.15")).quantize(Decimal("0.01"))
        subtotal += line_total
        tax_total += tax
        items.append(OfflineTransactionItem(
            product_id=pid, product_name=f"Product-{pid.hex[:6]}",
            quantity=qty, price=price, tax_amount=tax,
        ))
    total = subtotal + tax_total
    return OfflineTransaction(
        offline_id=f"offline-{idx}-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=10 - idx),
        payment_method=payment_method,
        line_items=items,
        subtotal=subtotal, tax_amount=tax_total, total=total,
        cash_tendered=total + Decimal("10") if payment_method == "cash" else None,
        change_given=Decimal("10") if payment_method == "cash" else None,
    )


# ===========================================================================
# Property 9: Offline Transaction Sync Completeness
# ===========================================================================


class TestP9OfflineSyncCompleteness:
    """Every offline transaction produces success, conflict, or failed.

    **Validates: Requirements 9**
    """

    @given(
        num_transactions=st.integers(min_value=1, max_value=8),
        num_items=st.integers(min_value=1, max_value=4),
        product_states=st.lists(product_state_st, min_size=1, max_size=4),
        prices=st.lists(price_strategy, min_size=1, max_size=4),
        quantities=st.lists(quantity_st, min_size=1, max_size=4),
        payment_methods=st.lists(payment_method_st, min_size=1, max_size=8),
    )
    @PBT_SETTINGS
    def test_every_transaction_produces_result(
        self, num_transactions, num_items, product_states, prices, quantities,
        payment_methods,
    ) -> None:
        """P9: every offline transaction has a result — none silently dropped."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        actual_items = min(num_items, len(product_states), len(prices), len(quantities))
        if actual_items < 1:
            return

        product_ids = [uuid.uuid4() for _ in range(actual_items)]
        products_map: dict[uuid.UUID, Product | None] = {}

        for i, pid in enumerate(product_ids):
            state = product_states[i % len(product_states)]
            price = prices[i % len(prices)]
            qty = quantities[i % len(quantities)]
            if state == "matching":
                products_map[pid] = _make_product(pid, org_id, price, Decimal("100"))
            elif state == "price_changed":
                products_map[pid] = _make_product(pid, org_id, price + Decimal("5"), Decimal("100"))
            elif state == "low_stock":
                products_map[pid] = _make_product(pid, org_id, price, Decimal("0.1"))
            elif state == "inactive":
                products_map[pid] = _make_product(pid, org_id, price, Decimal("100"), False)

        offline_txns = []
        for idx in range(num_transactions):
            pm = payment_methods[idx % len(payment_methods)]
            txn = _build_offline_txn(
                idx, product_ids[:actual_items],
                prices[:actual_items], quantities[:actual_items], pm,
            )
            offline_txns.append(txn)

        mock_db = AsyncMock()
        mock_db.add = lambda obj: None
        mock_db.flush = AsyncMock()

        async def fake_execute(stmt):
            result = MagicMock()
            for pid, product in products_map.items():
                if product is not None and str(pid) in str(stmt):
                    result.scalar_one_or_none.return_value = product
                    return result
            result.scalar_one_or_none.return_value = None
            return result

        mock_db.execute = fake_execute
        svc = POSService(mock_db)

        report: SyncReport = asyncio.run(
            svc.sync_offline_transactions(org_id, user_id, offline_txns),
        )

        assert report.total == len(offline_txns)
        assert len(report.results) == len(offline_txns)

        valid_statuses = {"success", "conflict", "failed"}
        for result in report.results:
            assert result.status in valid_statuses

        assert report.successes + report.conflicts + report.failures == report.total

        input_ids = {t.offline_id for t in offline_txns}
        result_ids = {r.offline_id for r in report.results}
        assert input_ids == result_ids
