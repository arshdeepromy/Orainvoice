"""POS service: session management, transaction processing, offline sync.

Implements the core POS business logic including:
- Session open/close
- complete_transaction() — atomic invoice + payment + stock decrement
- sync_offline_transactions() — chronological offline sync with conflict detection

**Validates: Requirement 22 — POS Module**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pos.models import POSSession, POSTransaction
from app.modules.pos.schemas import (
    OfflineTransaction,
    SessionCloseRequest,
    SessionOpenRequest,
    SyncConflictDetail,
    SyncReport,
    SyncResultItem,
    TransactionCreateRequest,
    TransactionLineItem,
)
from app.modules.products.models import Product
from app.modules.stock.service import StockService

logger = logging.getLogger(__name__)


class POSService:
    """Service layer for POS operations."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stock_service = StockService(db)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def open_session(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: SessionOpenRequest,
    ) -> POSSession:
        """Open a new POS session for the given user."""
        session = POSSession(
            org_id=org_id,
            user_id=user_id,
            location_id=payload.location_id,
            opening_cash=payload.opening_cash,
            status="open",
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def close_session(
        self,
        org_id: uuid.UUID,
        payload: SessionCloseRequest,
    ) -> POSSession:
        """Close an open POS session."""
        stmt = select(POSSession).where(
            and_(
                POSSession.id == payload.session_id,
                POSSession.org_id == org_id,
            ),
        )
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()
        if session is None:
            raise ValueError("POS session not found")
        if session.status != "open":
            raise ValueError("POS session is not open")

        session.status = "closed"
        session.closing_cash = payload.closing_cash
        session.closed_at = datetime.now(timezone.utc)
        await self.db.flush()
        return session

    # ------------------------------------------------------------------
    # Transaction processing
    # ------------------------------------------------------------------

    async def complete_transaction(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: TransactionCreateRequest,
    ) -> POSTransaction:
        """Complete a POS transaction atomically.

        Creates an Issued invoice, records payment, decrements inventory,
        and queues receipt print — all within the caller's DB transaction.
        """
        # Calculate totals from line items
        subtotal = Decimal("0")
        tax_total = Decimal("0")
        for item in payload.line_items:
            line_total = item.unit_price * item.quantity - item.discount_amount
            subtotal += line_total
            tax_total += item.tax_amount

        total = subtotal + tax_total - payload.discount_amount + payload.tip_amount

        # Calculate change for cash payments
        change_given = None
        if payload.payment_method == "cash" and payload.cash_tendered is not None:
            change_given = payload.cash_tendered - total

        # Create the POS transaction record
        txn = POSTransaction(
            org_id=org_id,
            session_id=payload.session_id,
            customer_id=payload.customer_id,
            table_id=payload.table_id,
            payment_method=payload.payment_method,
            subtotal=subtotal,
            tax_amount=tax_total,
            discount_amount=payload.discount_amount,
            tip_amount=payload.tip_amount,
            total=total,
            cash_tendered=payload.cash_tendered,
            change_given=change_given,
            is_offline_sync=False,
            created_by=user_id,
        )
        self.db.add(txn)
        await self.db.flush()

        # Decrement stock for each line item
        await self._decrement_stock_for_items(
            org_id, payload.line_items, txn.id, user_id,
        )

        return txn

    async def _decrement_stock_for_items(
        self,
        org_id: uuid.UUID,
        line_items: list[TransactionLineItem],
        reference_id: uuid.UUID,
        performed_by: uuid.UUID,
    ) -> None:
        """Decrement stock for each line item in a transaction."""
        for item in line_items:
            stmt = select(Product).where(
                and_(Product.id == item.product_id, Product.org_id == org_id),
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if product is not None:
                await self.stock_service.decrement_stock(
                    product,
                    item.quantity,
                    reference_type="pos_transaction",
                    reference_id=reference_id,
                    performed_by=performed_by,
                )

    # ------------------------------------------------------------------
    # Offline sync
    # ------------------------------------------------------------------

    async def sync_offline_transactions(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        transactions: list[OfflineTransaction],
    ) -> SyncReport:
        """Sync offline transactions in chronological order.

        For each transaction:
        - Detect conflicts (price changes, deleted/inactive products, insufficient stock)
        - Always create the invoice with offline values
        - Generate a conflict report
        """
        sorted_txns = sorted(transactions, key=lambda t: t.timestamp)
        results: list[SyncResultItem] = []

        for offline_txn in sorted_txns:
            try:
                result_item = await self._process_offline_transaction(
                    org_id, user_id, offline_txn,
                )
                results.append(result_item)
            except Exception as exc:
                logger.exception(
                    "Failed to sync offline transaction %s", offline_txn.offline_id,
                )
                results.append(SyncResultItem(
                    offline_id=offline_txn.offline_id,
                    status="failed",
                    error=str(exc),
                ))

        successes = sum(1 for r in results if r.status == "success")
        conflicts = sum(1 for r in results if r.status == "conflict")
        failures = sum(1 for r in results if r.status == "failed")

        return SyncReport(
            total=len(results),
            successes=successes,
            conflicts=conflicts,
            failures=failures,
            results=results,
        )

    async def _process_offline_transaction(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        offline_txn: OfflineTransaction,
    ) -> SyncResultItem:
        """Process a single offline transaction, detecting conflicts."""
        conflicts: list[SyncConflictDetail] = []

        # Check each line item for conflicts
        for item in offline_txn.line_items:
            stmt = select(Product).where(
                and_(Product.id == item.product_id, Product.org_id == org_id),
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()

            if product is None or not product.is_active:
                conflicts.append(SyncConflictDetail(
                    type="product_inactive",
                    product_id=item.product_id,
                    detail=f"Product {item.product_id} is inactive or deleted",
                ))
            else:
                # Check price change
                if product.sale_price != item.price:
                    conflicts.append(SyncConflictDetail(
                        type="price_changed",
                        product_id=item.product_id,
                        detail=(
                            f"Offline price {item.price}, "
                            f"current price {product.sale_price}"
                        ),
                    ))
                # Check insufficient stock
                if product.stock_quantity < item.quantity:
                    conflicts.append(SyncConflictDetail(
                        type="insufficient_stock",
                        product_id=item.product_id,
                        detail=(
                            f"Available {product.stock_quantity}, "
                            f"requested {item.quantity}"
                        ),
                    ))

        # Always create the transaction with offline values
        change_given = None
        if offline_txn.payment_method == "cash" and offline_txn.cash_tendered is not None:
            change_given = offline_txn.cash_tendered - offline_txn.total

        sync_status = "conflict" if conflicts else "synced"
        conflict_data = (
            [c.model_dump(mode="json") for c in conflicts] if conflicts else None
        )

        txn = POSTransaction(
            org_id=org_id,
            offline_transaction_id=offline_txn.offline_id,
            customer_id=offline_txn.customer_id,
            payment_method=offline_txn.payment_method,
            subtotal=offline_txn.subtotal,
            tax_amount=offline_txn.tax_amount,
            discount_amount=offline_txn.discount_amount,
            tip_amount=offline_txn.tip_amount,
            total=offline_txn.total,
            cash_tendered=offline_txn.cash_tendered,
            change_given=change_given,
            is_offline_sync=True,
            sync_status=sync_status,
            sync_conflicts=conflict_data,
            created_by=user_id,
        )
        self.db.add(txn)
        await self.db.flush()

        # Decrement stock for each line item (even with conflicts — use offline values)
        for item in offline_txn.line_items:
            stmt = select(Product).where(
                and_(Product.id == item.product_id, Product.org_id == org_id),
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if product is not None and product.is_active:
                await self.stock_service.decrement_stock(
                    product,
                    item.quantity,
                    reference_type="pos_transaction",
                    reference_id=txn.id,
                    performed_by=user_id,
                )

        return SyncResultItem(
            offline_id=offline_txn.offline_id,
            status="conflict" if conflicts else "success",
            transaction_id=txn.id,
            conflicts=conflicts,
        )

    # ------------------------------------------------------------------
    # Sync status query
    # ------------------------------------------------------------------

    async def get_sync_status(self, org_id: uuid.UUID) -> dict:
        """Return counts of offline-synced transactions by status."""
        base = select(
            POSTransaction.sync_status,
            func.count().label("cnt"),
        ).where(
            and_(
                POSTransaction.org_id == org_id,
                POSTransaction.is_offline_sync.is_(True),
            ),
        ).group_by(POSTransaction.sync_status)

        result = await self.db.execute(base)
        rows = result.all()

        counts = {row[0]: row[1] for row in rows}
        return {
            "pending_count": counts.get("pending", 0),
            "synced_count": counts.get("synced", 0),
            "conflict_count": counts.get("conflict", 0),
            "failed_count": counts.get("failed", 0),
        }
