"""SQLAlchemy ORM models for discount tables.

Tables:
- discount_rules: loyalty/discount rules per org (RLS enabled)
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
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DiscountRule(Base):
    """Loyalty / discount rule for an organisation."""

    __tablename__ = "discount_rules"

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
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold_value: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    discount_type: Mapped[str] = mapped_column(String(10), nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "rule_type IN ('visit_count','spend_threshold','customer_tag')",
            name="ck_discount_rules_rule_type",
        ),
        CheckConstraint(
            "discount_type IN ('percentage','fixed')",
            name="ck_discount_rules_discount_type",
        ),
    )

    organisation = relationship("Organisation", backref="discount_rules")
