"""SQLAlchemy ORM models for products and product_categories tables.

Maps to tables created by migrations 0025 (product_categories) and 0027 (products).

**Validates: Requirement 9.1, 9.2**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ProductCategory(Base):
    """Hierarchical product category with self-referencing parent_id."""

    __tablename__ = "product_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id"), nullable=True,
    )
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    # Relationships
    children: Mapped[list["ProductCategory"]] = relationship(
        "ProductCategory",
        back_populates="parent",
        lazy="selectin",
    )
    parent: Mapped["ProductCategory | None"] = relationship(
        "ProductCategory",
        back_populates="children",
        remote_side=[id],
        lazy="selectin",
    )
    products: Mapped[list["Product"]] = relationship(
        "Product", back_populates="category", lazy="noload",
    )


class Product(Base):
    """Product catalogue item with stock tracking.

    Supports SKU, barcode, pricing, stock levels, and supplier reference.
    """

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id"), nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(
        String(50), default="each", nullable=False,
    )
    sale_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    cost_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=True,
    )
    tax_applicable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tax_rate_override: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
    )
    stock_quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), default=Decimal("0"), nullable=False,
    )
    low_stock_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=Decimal("0"), nullable=True,
    )
    reorder_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), default=Decimal("0"), nullable=True,
    )
    allow_backorder: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True,
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    images: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    # Relationships
    category: Mapped["ProductCategory | None"] = relationship(
        "ProductCategory", back_populates="products", lazy="selectin",
    )
