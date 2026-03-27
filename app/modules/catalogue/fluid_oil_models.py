"""SQLAlchemy ORM model for fluid_oil_products table."""
from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class FluidOilProduct(Base):
    __tablename__ = "fluid_oil_products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    fluid_type: Mapped[str] = mapped_column(String(10), nullable=False)
    oil_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    grade: Mapped[str | None] = mapped_column(String(50), nullable=True)
    synthetic_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pack_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    qty_per_pack: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit_type: Mapped[str] = mapped_column(String(10), default="litre", nullable=False)
    container_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    total_volume: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gst_mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cost_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    sell_price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    margin: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    margin_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    current_stock_volume: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    min_stock_volume: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    reorder_volume: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
