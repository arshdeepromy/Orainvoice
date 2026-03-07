"""SQLAlchemy ORM model for kitchen_orders table.

Maps to table created by migration 0044.

**Validates: Requirement — Kitchen Display Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

KITCHEN_ORDER_STATUSES = ("pending", "preparing", "prepared", "served")


class KitchenOrder(Base):
    """An individual order item routed to a kitchen station."""

    __tablename__ = "kitchen_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    pos_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_transactions.id"), nullable=True,
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurant_tables.id"), nullable=True,
    )
    item_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    quantity: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
    )
    modifications: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    station: Mapped[str] = mapped_column(
        String(50), default="main", nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
