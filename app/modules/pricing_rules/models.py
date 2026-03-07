"""SQLAlchemy ORM model for the pricing_rules table.

Maps to the table created by migration 0029.

**Validates: Requirement 10.1, 10.2**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PricingRule(Base):
    """Configurable pricing rule that overrides base product pricing.

    Rule types:
    - customer_specific: fixed price for a specific customer
    - volume: price breaks at quantity thresholds (min/max_quantity)
    - date_based: promotional pricing with start/end dates
    - trade_category: different base prices per trade category

    Higher priority number = higher precedence.
    """

    __tablename__ = "pricing_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True,
    )
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    customer_tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    min_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True,
    )
    max_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3), nullable=True,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    price_override: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True,
    )
    discount_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )
