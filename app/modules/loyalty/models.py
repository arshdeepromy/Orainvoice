"""SQLAlchemy ORM models for the loyalty and memberships module.

Maps to tables created by migration 0053: loyalty_config, loyalty_tiers,
loyalty_transactions.

**Validates: Requirement 38 — Loyalty Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LoyaltyConfig(Base):
    """Per-organisation loyalty programme configuration."""

    __tablename__ = "loyalty_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False,
    )
    earn_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), server_default="1.0", nullable=False,
    )
    redemption_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), server_default="0.01", nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class LoyaltyTier(Base):
    """A membership tier within an organisation's loyalty programme."""

    __tablename__ = "loyalty_tiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    threshold_points: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), server_default="0", nullable=False,
    )
    benefits: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )


class LoyaltyTransaction(Base):
    """A single loyalty point earn or redeem event."""

    __tablename__ = "loyalty_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    transaction_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    points: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    balance_after: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    reference_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
