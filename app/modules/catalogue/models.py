"""SQLAlchemy ORM models for catalogue-scoped tables.

Tables:
- items_catalogue: organisation-scoped items catalogue (RLS enabled)
- parts_catalogue: pre-loaded parts per organisation (RLS enabled)
- labour_rates: named hourly rates per organisation (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ItemsCatalogue(Base):
    """Organisation-scoped items catalogue entry."""

    __tablename__ = "items_catalogue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_gst_exempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="items_catalogue_entries")


# Backward-compatible alias — other modules still import ServiceCatalogue
# until they are updated in later tasks.
ServiceCatalogue = ItemsCatalogue


class PartsCatalogue(Base):
    """Organisation-scoped parts catalogue entry."""

    __tablename__ = "parts_catalogue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    part_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    current_stock: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    min_stock_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    reorder_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="parts_catalogue_items")
    part_suppliers: Mapped[list[PartSupplier]] = relationship(
        back_populates="part"
    )


class LabourRate(Base):
    """Organisation-scoped named labour rate."""

    __tablename__ = "labour_rates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    hourly_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="labour_rates")
