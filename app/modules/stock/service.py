"""Stock service: decrement, increment, adjustment, stocktake.

All stock mutations create a StockMovement record and update
the product's stock_quantity atomically within the same transaction.

**Validates: Requirement 9.3, 9.4, 9.7, 9.8**
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product
from app.modules.stock.models import StockMovement
from app.modules.stock.schemas import StocktakeLineItem


class StockService:
    """Service layer for stock movements and stocktakes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Core stock mutation helpers
    # ------------------------------------------------------------------

    async def _create_movement(
        self,
        product: Product,
        quantity_change: Decimal,
        movement_type: str,
        *,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        notes: str | None = None,
        performed_by: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
    ) -> StockMovement:
        """Create a stock movement and update product quantity atomically."""
        product.stock_quantity = product.stock_quantity + quantity_change
        resulting = product.stock_quantity

        movement = StockMovement(
            org_id=product.org_id,
            product_id=product.id,
            location_id=location_id or product.location_id,
            movement_type=movement_type,
            quantity_change=quantity_change,
            resulting_quantity=resulting,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=notes,
            performed_by=performed_by,
        )
        self.db.add(movement)
        await self.db.flush()
        return movement

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def decrement_stock(
        self,
        product: Product,
        quantity: Decimal,
        *,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        performed_by: uuid.UUID | None = None,
    ) -> StockMovement:
        """Decrement stock (e.g. invoice issuance). Quantity should be positive."""
        return await self._create_movement(
            product,
            -abs(quantity),
            "sale",
            reference_type=reference_type,
            reference_id=reference_id,
            performed_by=performed_by,
        )

    async def increment_stock(
        self,
        product: Product,
        quantity: Decimal,
        *,
        movement_type: str = "credit",
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        performed_by: uuid.UUID | None = None,
    ) -> StockMovement:
        """Increment stock (e.g. credit note, purchase receive)."""
        return await self._create_movement(
            product,
            abs(quantity),
            movement_type,
            reference_type=reference_type,
            reference_id=reference_id,
            performed_by=performed_by,
        )

    async def manual_adjustment(
        self,
        product: Product,
        quantity_change: Decimal,
        reason: str,
        *,
        performed_by: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
    ) -> StockMovement:
        """Manual stock adjustment with reason note."""
        return await self._create_movement(
            product,
            quantity_change,
            "adjustment",
            notes=reason,
            performed_by=performed_by,
            location_id=location_id,
        )

    async def create_stocktake(
        self,
        org_id: uuid.UUID,
        lines: list[StocktakeLineItem],
        *,
        performed_by: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
    ) -> list[dict]:
        """Preview a stocktake: calculate variance for each line.

        Does NOT apply adjustments — call commit_stocktake() for that.
        """
        variance_report: list[dict] = []
        for line in lines:
            stmt = select(Product).where(
                and_(Product.id == line.product_id, Product.org_id == org_id),
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if product is None:
                continue
            variance = line.counted_quantity - product.stock_quantity
            variance_report.append({
                "product_id": str(product.id),
                "product_name": product.name,
                "system_quantity": product.stock_quantity,
                "counted_quantity": line.counted_quantity,
                "variance": variance,
            })
        return variance_report

    async def commit_stocktake(
        self,
        org_id: uuid.UUID,
        lines: list[StocktakeLineItem],
        *,
        performed_by: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
    ) -> list[StockMovement]:
        """Commit a stocktake: apply adjustments for each variance."""
        movements: list[StockMovement] = []
        for line in lines:
            stmt = select(Product).where(
                and_(Product.id == line.product_id, Product.org_id == org_id),
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if product is None:
                continue
            variance = line.counted_quantity - product.stock_quantity
            if variance != Decimal("0"):
                movement = await self._create_movement(
                    product,
                    variance,
                    "stocktake",
                    notes=f"Stocktake: counted {line.counted_quantity}, system {product.stock_quantity - variance}",
                    performed_by=performed_by,
                    location_id=location_id,
                )
                movements.append(movement)
        return movements

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def list_movements(
        self,
        org_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        movement_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[StockMovement], int]:
        """List stock movements with optional filters."""
        stmt = select(StockMovement).where(StockMovement.org_id == org_id)

        if product_id is not None:
            stmt = stmt.where(StockMovement.product_id == product_id)
        if movement_type is not None:
            stmt = stmt.where(StockMovement.movement_type == movement_type)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(StockMovement.created_at.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_movement_sum(
        self, product_id: uuid.UUID,
    ) -> Decimal:
        """Sum all quantity_change values for a product."""
        stmt = select(func.sum(StockMovement.quantity_change)).where(
            StockMovement.product_id == product_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar() or Decimal("0")
