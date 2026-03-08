"""SQLAlchemy ORM models for inventory-scoped tables.

Tables:
- part_suppliers: link table connecting parts to suppliers (RLS enabled)
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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
