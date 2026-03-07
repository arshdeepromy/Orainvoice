"""Property-based test: offline transaction sync completeness.

**Validates: Requirements 22.7, 22.8** — Property 9

For any set of offline transactions T synced to the server, every
transaction in T results in either a created invoice/transaction or an
explicit error/conflict record. No transaction is silently dropped.

Uses Hypothesis to generate random sets of offline transactions with
varying product states and verifies the completeness invariant.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.pos.models import POSTransaction
from app.modules.pos.schemas import (
    OfflineTransaction,
    OfflineTransactionItem,
    SyncReport,
)
from app.modules.pos.service import POSService
from app.modules.products.models import Product


PBT_SETTINGS = h_settings(
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# Strategies
price_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

quantity_strategy = st.decimals(
    min_value=Decimal("0.1"),
    max_value=Decimal("50"),
    places=1,
    allow_nan=False,
    allow_infinity=False,
)

payment_method_strategy = st.sampled_from(["cash", "card", "split"])

# Product state: active with matching price, active with changed price,
# active with low stock, or inactive/deleted
product_state_strategy = st.sampled_from([
    "matching",
    "price_changed",
    "low_stock",
    "inactive",
])


def _make_product(
    product_id: uuid.UUID,
    org_id: uuid.UUID,
    sale_price: Decimal,
    stock_qty: Decimal,
    is_active: bool = True,
) -> Product:
    return Product(
        id=product_id,
        org_id=org_id,
        name=f"Product-{product_id.hex[:6]}",
        sale_price=sale_price,
        stock_quantity=stock_qty,
        is_active=is_active,
    )


def _build_offline_transaction(
    idx: int,
    product_ids: list[uuid.UUID],
    prices: list[Decimal],
    quantities: list[Decimal],
    payment_method: str,
) -> OfflineTransaction:
    """Build an OfflineTransaction from generated data."""
    items = []
    subtotal = Decimal("0")
    tax_total = Decimal("0")
    for pid, price, qty in zip(product_ids, prices, quantities):
        line_total = price * qty
        tax = (line_total * Decimal("0.15")).quantize(Decimal("0.01"))
        subtotal += line_total
        tax_total += tax
        items.append(OfflineTransactionItem(
            product_id=pid,
            product_name=f"Product-{pid.hex[:6]}",
            quantity=qty,
            price=price,
            tax_amount=tax,
        ))

    total = subtotal + tax_total
    return OfflineTransaction(
        offline_id=f"offline-{idx}-{uuid.uuid4().hex[:8]}",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=10 - idx),
        payment_method=payment_method,
        line_items=items,
        subtotal=subtotal,
        tax_amount=tax_total,
        total=total,
        cash_tendered=total + Decimal("10") if payment_method == "cash" else None,
        change_given=Decimal("10") if payment_method == "cash" else None,
    )


class TestOfflineSyncCompleteness:
    """For any set of offline transactions synced to the server, every
    transaction results in either a success or an explicit conflict/error
    record. No transaction is silently dropped.

    **Validates: Requirements 22.7, 22.8**
    """

    @given(
        num_transactions=st.integers(min_value=1, max_value=8),
        num_items_per_txn=st.integers(min_value=1, max_value=4),
        product_states=st.lists(
            product_state_strategy, min_size=1, max_size=4,
        ),
        prices=st.lists(price_strategy, min_size=1, max_size=4),
        quantities=st.lists(quantity_strategy, min_size=1, max_size=4),
        payment_methods=st.lists(payment_method_strategy, min_size=1, max_size=8),
    )
    @PBT_SETTINGS
    def test_every_offline_transaction_produces_result(
        self,
        num_transactions: int,
        num_items_per_txn: int,
        product_states: list[str],
        prices: list[Decimal],
        quantities: list[Decimal],
        payment_methods: list[str],
    ) -> None:
        """Every offline transaction produces either success, conflict,
        or failed — none are silently dropped."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Ensure we have enough items
        num_items = min(num_items_per_txn, len(product_states), len(prices), len(quantities))
        if num_items < 1:
            return

        # Create product IDs and products based on states
        product_ids = [uuid.uuid4() for _ in range(num_items)]
        products_map: dict[uuid.UUID, Product | None] = {}

        for i, pid in enumerate(product_ids):
            state = product_states[i % len(product_states)]
            price = prices[i % len(prices)]
            qty = quantities[i % len(quantities)]

            if state == "matching":
                products_map[pid] = _make_product(pid, org_id, price, Decimal("100"))
            elif state == "price_changed":
                # Current price differs from offline price
                products_map[pid] = _make_product(
                    pid, org_id, price + Decimal("5.00"), Decimal("100"),
                )
            elif state == "low_stock":
                products_map[pid] = _make_product(
                    pid, org_id, price, Decimal("0.1"),
                )
            elif state == "inactive":
                products_map[pid] = _make_product(
                    pid, org_id, price, Decimal("100"), is_active=False,
                )

        # Build offline transactions
        offline_txns = []
        for idx in range(num_transactions):
            pm = payment_methods[idx % len(payment_methods)]
            txn = _build_offline_transaction(
                idx, product_ids[:num_items],
                prices[:num_items], quantities[:num_items], pm,
            )
            offline_txns.append(txn)

        # Mock DB
        mock_db = AsyncMock()
        added_objects: list = []
        mock_db.add = lambda obj: added_objects.append(obj)
        mock_db.flush = AsyncMock()

        # Mock product lookups
        async def fake_execute(stmt):
            mock_result = MagicMock()
            # Extract product_id from the query by checking added products
            for pid, product in products_map.items():
                if product is not None and str(pid) in str(stmt):
                    mock_result.scalar_one_or_none.return_value = product
                    return mock_result
            mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_db.execute = fake_execute

        svc = POSService(mock_db)

        report: SyncReport = asyncio.get_event_loop().run_until_complete(
            svc.sync_offline_transactions(org_id, user_id, offline_txns),
        )

        # PROPERTY: every transaction has a result
        assert report.total == len(offline_txns), (
            f"Report total {report.total} != input count {len(offline_txns)}"
        )
        assert len(report.results) == len(offline_txns), (
            f"Results count {len(report.results)} != input count {len(offline_txns)}"
        )

        # PROPERTY: every result has a valid status
        valid_statuses = {"success", "conflict", "failed"}
        for result in report.results:
            assert result.status in valid_statuses, (
                f"Invalid status '{result.status}' for offline_id={result.offline_id}"
            )

        # PROPERTY: counts add up
        assert report.successes + report.conflicts + report.failures == report.total

        # PROPERTY: no offline_id is missing from results
        input_ids = {t.offline_id for t in offline_txns}
        result_ids = {r.offline_id for r in report.results}
        assert input_ids == result_ids, (
            f"Missing IDs: {input_ids - result_ids}, Extra IDs: {result_ids - input_ids}"
        )
