"""SQLAlchemy ORM model for the stock_movements table.

Maps to the table created by migration 0028.

**Validates: Requirement 9.7**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


# Valid movement types
MOVEMENT_TYPES = (
    "sale", "credit", "purchase", "adjustment",
    "transfer", "return", "stocktake",
)


class StockMovement(Base):
    """Record of a single stock quantity change.

    Every change to a product's stock_quantity is recorded here
    with the movement type, quantity delta, and resulting quantity.
    """

    __tablename__ = "stock_movements"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    movement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity_change: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False,
    )
    resulting_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False,
    )
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
