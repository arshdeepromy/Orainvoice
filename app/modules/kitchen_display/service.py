"""Kitchen display service: order management, station routing, preparation tracking.

**Validates: Requirement — Kitchen Display Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.kitchen_display.models import KitchenOrder, KITCHEN_ORDER_STATUSES
from app.modules.kitchen_display.schemas import KitchenOrderCreate

# Default category → station mapping (configurable per org in future)
DEFAULT_STATION_MAP: dict[str, str] = {
    "grill": "grill",
    "fryer": "fry",
    "salad": "cold",
    "dessert": "cold",
    "beverage": "bar",
    "drink": "bar",
    "cocktail": "bar",
}

# Valid status transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["preparing"],
    "preparing": ["prepared", "pending"],
    "prepared": ["served"],
    "served": [],
}


class KitchenService:
    """Service layer for kitchen display order management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_pending_orders(
        self, org_id: uuid.UUID, *, skip: int = 0, limit: int = 100,
    ) -> tuple[list[KitchenOrder], int]:
        """Return orders with status 'pending' or 'preparing'."""
        stmt = select(KitchenOrder).where(
            and_(
                KitchenOrder.org_id == org_id,
                KitchenOrder.status.in_(["pending", "preparing"]),
            ),
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(KitchenOrder.created_at.asc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_orders_by_station(
        self, org_id: uuid.UUID, station: str, *, skip: int = 0, limit: int = 100,
    ) -> tuple[list[KitchenOrder], int]:
        """Return orders for a specific station, excluding served."""
        stmt = select(KitchenOrder).where(
            and_(
                KitchenOrder.org_id == org_id,
                KitchenOrder.station == station,
                KitchenOrder.status.in_(["pending", "preparing"]),
            ),
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0
        stmt = stmt.order_by(KitchenOrder.created_at.asc()).offset(skip).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def get_order(
        self, org_id: uuid.UUID, order_id: uuid.UUID,
    ) -> KitchenOrder | None:
        stmt = select(KitchenOrder).where(
            and_(KitchenOrder.org_id == org_id, KitchenOrder.id == order_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_order(
        self, org_id: uuid.UUID, payload: KitchenOrderCreate,
    ) -> KitchenOrder:
        order = KitchenOrder(
            org_id=org_id,
            pos_transaction_id=payload.pos_transaction_id,
            table_id=payload.table_id,
            item_name=payload.item_name,
            quantity=payload.quantity,
            modifications=payload.modifications,
            station=payload.station,
        )
        self.db.add(order)
        await self.db.flush()
        return order

    async def mark_prepared(
        self, org_id: uuid.UUID, order_id: uuid.UUID,
    ) -> KitchenOrder | None:
        """Mark an order item as prepared."""
        order = await self.get_order(org_id, order_id)
        if order is None:
            return None
        if order.status not in ("pending", "preparing"):
            return None
        order.status = "prepared"
        order.prepared_at = datetime.now(timezone.utc)
        await self.db.flush()
        return order

    async def update_status(
        self, org_id: uuid.UUID, order_id: uuid.UUID, new_status: str,
    ) -> KitchenOrder | None:
        """Update order status with transition validation."""
        if new_status not in KITCHEN_ORDER_STATUSES:
            return None
        order = await self.get_order(org_id, order_id)
        if order is None:
            return None
        allowed = VALID_TRANSITIONS.get(order.status, [])
        if new_status not in allowed:
            return None
        order.status = new_status
        if new_status == "prepared":
            order.prepared_at = datetime.now(timezone.utc)
        await self.db.flush()
        return order

    async def create_orders_from_transaction(
        self,
        org_id: uuid.UUID,
        pos_transaction_id: uuid.UUID,
        table_id: uuid.UUID | None,
        items: list[dict],
        station_map: dict[str, str] | None = None,
    ) -> list[KitchenOrder]:
        """Create kitchen orders from a POS transaction's line items.

        Each item dict should have: item_name, quantity, modifications (optional),
        category (optional, for station routing).
        """
        mapping = station_map or DEFAULT_STATION_MAP
        orders: list[KitchenOrder] = []
        for item in items:
            category = (item.get("category") or "").lower()
            station = mapping.get(category, "main")
            order = KitchenOrder(
                org_id=org_id,
                pos_transaction_id=pos_transaction_id,
                table_id=table_id,
                item_name=item["item_name"],
                quantity=item.get("quantity", 1),
                modifications=item.get("modifications"),
                station=station,
            )
            self.db.add(order)
            orders.append(order)
        await self.db.flush()
        return orders

    @staticmethod
    def route_to_station(
        category: str, station_map: dict[str, str] | None = None,
    ) -> str:
        """Determine the kitchen station for a product category."""
        mapping = station_map or DEFAULT_STATION_MAP
        return mapping.get(category.lower(), "main")

    @staticmethod
    def get_urgency_level(created_at: datetime) -> str:
        """Return urgency level based on elapsed time since order creation.

        - ``normal`` — less than 15 minutes (white)
        - ``warning`` — 15–30 minutes (amber)
        - ``critical`` — more than 30 minutes (red)
        """
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            # Assume UTC if naive
            elapsed = now - created_at.replace(tzinfo=timezone.utc)
        else:
            elapsed = now - created_at
        minutes = elapsed.total_seconds() / 60
        if minutes > 30:
            return "critical"
        if minutes > 15:
            return "warning"
        return "normal"
