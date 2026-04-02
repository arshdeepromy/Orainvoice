"""Purchase order service: CRUD, receive_goods, partial_receive, generate_pdf.

**Validates: Requirement 16 — Purchase Order Module**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product
from app.modules.purchase_orders.models import PurchaseOrder, PurchaseOrderLine
from app.modules.purchase_orders.schemas import (
    POLineCreate,
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
    ReceiveGoodsRequest,
)
from app.modules.stock.service import StockService


class PurchaseOrderService:
    """Service layer for purchase order management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _next_po_number(self, org_id: uuid.UUID) -> str:
        """Generate the next PO number for the org."""
        stmt = (
            select(func.count())
            .select_from(PurchaseOrder)
            .where(PurchaseOrder.org_id == org_id)
        )
        count = (await self.db.execute(stmt)).scalar() or 0
        return f"PO-{count + 1:05d}"

    def _recalculate_total(self, po: PurchaseOrder) -> None:
        """Recalculate PO total_amount from line totals."""
        po.total_amount = sum(
            (line.line_total for line in po.lines), Decimal("0"),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_purchase_orders(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        supplier_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> tuple[list[PurchaseOrder], int]:
        """List POs with pagination and filtering."""
        stmt = select(PurchaseOrder).where(PurchaseOrder.org_id == org_id)
        if branch_id is not None:
            stmt = stmt.where(PurchaseOrder.branch_id == branch_id)
        if status is not None:
            stmt = stmt.where(PurchaseOrder.status == status)
        if supplier_id is not None:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(PurchaseOrder.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all()), total

    async def create_purchase_order(
        self,
        org_id: uuid.UUID,
        payload: PurchaseOrderCreate,
        *,
        created_by: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> PurchaseOrder:
        """Create a new purchase order with line items."""
        # Validate branch is active if provided (Req 2.2)
        if branch_id is not None:
            from app.core.branch_validation import validate_branch_active
            await validate_branch_active(self.db, branch_id)

        po_number = await self._next_po_number(org_id)
        po = PurchaseOrder(
            org_id=org_id,
            po_number=po_number,
            supplier_id=payload.supplier_id,
            job_id=payload.job_id,
            project_id=payload.project_id,
            expected_delivery=payload.expected_delivery,
            notes=payload.notes,
            created_by=created_by,
            branch_id=branch_id,
        )
        self.db.add(po)
        await self.db.flush()

        for line_data in payload.lines:
            line = PurchaseOrderLine(
                po_id=po.id,
                product_id=line_data.product_id,
                catalogue_item_id=line_data.catalogue_item_id,
                description=line_data.description,
                quantity_ordered=line_data.quantity_ordered,
                unit_cost=line_data.unit_cost,
                line_total=line_data.quantity_ordered * line_data.unit_cost,
            )
            self.db.add(line)
            po.lines.append(line)

        self._recalculate_total(po)
        await self.db.flush()
        # Refresh to ensure lines are loaded in async context (avoid greenlet error)
        await self.db.refresh(po, ["lines"])
        return po

    async def get_purchase_order(
        self, org_id: uuid.UUID, po_id: uuid.UUID,
    ) -> PurchaseOrder | None:
        """Get a single PO by ID."""
        stmt = select(PurchaseOrder).where(
            and_(PurchaseOrder.org_id == org_id, PurchaseOrder.id == po_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_purchase_order(
        self, org_id: uuid.UUID, po_id: uuid.UUID, payload: PurchaseOrderUpdate,
    ) -> PurchaseOrder | None:
        """Update an existing PO (only draft/sent)."""
        po = await self.get_purchase_order(org_id, po_id)
        if po is None:
            return None
        if po.status not in ("draft", "sent"):
            raise ValueError(f"Cannot update PO in '{po.status}' status")

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(po, field, value)
        await self.db.flush()
        return po

    async def send_purchase_order(
        self, org_id: uuid.UUID, po_id: uuid.UUID,
    ) -> PurchaseOrder | None:
        """Mark PO as sent to supplier."""
        po = await self.get_purchase_order(org_id, po_id)
        if po is None:
            return None
        if po.status != "draft":
            raise ValueError("Only draft POs can be sent")
        po.status = "sent"
        await self.db.flush()
        return po

    # ------------------------------------------------------------------
    # Receive goods
    # ------------------------------------------------------------------

    async def receive_goods(
        self,
        org_id: uuid.UUID,
        po_id: uuid.UUID,
        payload: ReceiveGoodsRequest,
        *,
        performed_by: uuid.UUID | None = None,
    ) -> PurchaseOrder | None:
        """Receive goods against PO lines, creating stock movements."""
        po = await self.get_purchase_order(org_id, po_id)
        if po is None:
            return None
        if po.status in ("cancelled", "received"):
            raise ValueError(f"Cannot receive goods on a '{po.status}' PO")

        stock_svc = StockService(self.db)
        line_map = {line.id: line for line in po.lines}

        for recv in payload.lines:
            line = line_map.get(recv.line_id)
            if line is None:
                raise ValueError(f"PO line {recv.line_id} not found")

            outstanding = line.quantity_ordered - line.quantity_received
            if recv.quantity > outstanding:
                raise ValueError(
                    f"Cannot receive {recv.quantity} for line {recv.line_id}; "
                    f"only {outstanding} outstanding"
                )

            # Update line received quantity
            line.quantity_received = line.quantity_received + recv.quantity

            # Increment stock via StockService (only for products table items)
            if line.product_id is not None:
                product_stmt = select(Product).where(Product.id == line.product_id)
                product_result = await self.db.execute(product_stmt)
                product = product_result.scalar_one_or_none()
                if product is not None:
                    await stock_svc.increment_stock(
                        product,
                        recv.quantity,
                        movement_type="receive",
                        reference_type="purchase_order",
                        reference_id=po.id,
                        performed_by=performed_by,
                    )

        # Update PO status based on received quantities
        self._update_po_status(po)
        await self.db.flush()
        return po

    def _update_po_status(self, po: PurchaseOrder) -> None:
        """Update PO status based on line received quantities."""
        if not po.lines:
            return
        all_received = all(
            line.quantity_received >= line.quantity_ordered for line in po.lines
        )
        any_received = any(
            line.quantity_received > Decimal("0") for line in po.lines
        )
        if all_received:
            po.status = "received"
        elif any_received:
            po.status = "partial"

    # ------------------------------------------------------------------
    # PDF generation
    # ------------------------------------------------------------------

    async def generate_pdf(
        self, org_id: uuid.UUID, po_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Generate PO PDF data with org branding.

        Returns a dict with PDF content metadata. In production this would
        render an HTML template and convert to PDF via weasyprint/wkhtmltopdf.
        """
        po = await self.get_purchase_order(org_id, po_id)
        if po is None:
            raise ValueError("Purchase order not found")

        lines_data = []
        for line in po.lines:
            lines_data.append({
                "product_id": str(line.product_id),
                "description": line.description or "",
                "quantity_ordered": float(line.quantity_ordered),
                "quantity_received": float(line.quantity_received),
                "unit_cost": float(line.unit_cost),
                "line_total": float(line.line_total),
            })

        return {
            "po_number": po.po_number,
            "supplier_id": str(po.supplier_id),
            "status": po.status,
            "expected_delivery": str(po.expected_delivery) if po.expected_delivery else None,
            "total_amount": float(po.total_amount),
            "notes": po.notes,
            "lines": lines_data,
            "org_id": str(org_id),
            "generated": True,
        }
