"""SQLAlchemy ORM models for trade_families and trade_categories tables.

Maps to the existing tables created by migration 0008 and seeded by
migrations 0018 (families) and 0019 (categories).

**Validates: Requirement 3.1, 3.4**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TradeFamily(Base):
    """Grouping of related trade categories.

    Each family has a slug, display name, icon, and display order.
    Country codes restrict which countries can see this family during signup.
    """

    __tablename__ = "trade_families"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    country_codes: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False, server_default=text("'[]'::jsonb"),
    )
    gated_features: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False, server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    # Relationships
    categories: Mapped[list["TradeCategory"]] = relationship(
        "TradeCategory", back_populates="family", lazy="selectin",
    )


class TradeCategory(Base):
    """A supported trade type with default configuration and seed data.

    Each category belongs to a TradeFamily and stores default services,
    products, terminology overrides, and recommended modules as JSONB.
    """

    __tablename__ = "trade_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trade_families.id"),
        nullable=False,
        index=True,
    )
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_template_layout: Mapped[str] = mapped_column(
        String(100), default="standard", nullable=False,
    )
    recommended_modules: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    terminology_overrides: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    default_services: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    default_products: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    default_expense_categories: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    default_job_templates: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    compliance_notes: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    seed_data_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_retired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    # Relationships
    family: Mapped["TradeFamily"] = relationship(
        "TradeFamily", back_populates="categories", lazy="selectin",
    )
