"""SQLAlchemy ORM models for inventory-scoped tables.

Tables:
- part_suppliers: link table connecting parts to suppliers (RLS enabled)
- stock_items: explicitly stocked catalogue items with quantity tracking
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PartSupplier(Base):
    """Link table connecting parts to suppliers with pricing info."""

    __tablename__ = "part_suppliers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parts_catalogue.id"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    supplier_part_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    supplier_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    is_preferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    __table_args__ = (
        UniqueConstraint(
            "part_id", "supplier_id", name="uq_part_suppliers_part_supplier"
        ),
    )

    # Relationships
    part = relationship("PartsCatalogue", back_populates="part_suppliers")
    supplier = relationship("Supplier", backref="part_suppliers")


class StockItem(Base):
    """Explicitly stocked catalogue item with quantity tracking.

    Links a catalogue entry (part, tyre, or fluid) to the inventory system
    with its own quantity, thresholds, barcode, and optional supplier override.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
    """

    __tablename__ = "stock_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    catalogue_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    catalogue_type: Mapped[str] = mapped_column(
        String(10), nullable=False,
    )
    current_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0",
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0",
    )
    min_threshold: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0",
    )
    reorder_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False, server_default="0",
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True,
    )
    purchase_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True,
    )
    sell_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True,
    )
    cost_per_unit: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True,
    )
    barcode: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    location: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "catalogue_type IN ('part', 'tyre', 'fluid')",
            name="ck_stock_items_catalogue_type",
        ),
    )

    # Relationships
    branch = relationship("Branch")
    movements = relationship("StockMovement", back_populates="stock_item", lazy="dynamic")



class InventoryLocation(Base):
    """Reusable inventory location names scoped to an organisation."""

    __tablename__ = "inventory_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_inventory_locations_org_name"),
    )
