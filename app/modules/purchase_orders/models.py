"""SQLAlchemy ORM models for purchase_orders and purchase_order_lines tables.

Maps to tables created by migration 0035.

**Validates: Requirement 16 — Purchase Order Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

PO_STATUSES = ["draft", "sent", "partial", "received", "cancelled"]


class PurchaseOrder(Base):
    """Purchase order header linked to a supplier, optionally to a job/project."""

    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    po_number: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False,
    )
    expected_delivery: Mapped[date | None] = mapped_column(
        Date, nullable=True,
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    # Relationships
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        "PurchaseOrderLine", back_populates="purchase_order",
        cascade="all, delete-orphan", lazy="selectin",
    )


class PurchaseOrderLine(Base):
    """Individual line item on a purchase order."""

    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity_ordered: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False,
    )
    quantity_received: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), default=Decimal("0"), nullable=False,
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )

    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder", back_populates="lines",
    )
