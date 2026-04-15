"""SQLAlchemy ORM models for billing tables.

Tables:
- org_payment_methods: saved payment method metadata per organisation (RLS enabled)
- billing_receipts: record of each recurring billing charge
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrgPaymentMethod(Base):
    """Stripe payment method metadata stored locally for an organisation."""

    __tablename__ = "org_payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    stripe_payment_method_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
    brand: Mapped[str] = mapped_column(String(50), nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    exp_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    exp_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    expiry_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    __table_args__ = (
        Index("ix_org_payment_methods_org_id", "org_id"),
    )

    # Relationships
    organisation = relationship("Organisation", backref="payment_methods")


class BillingReceipt(Base):
    """Record of each recurring billing charge."""

    __tablename__ = "billing_receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    billing_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    billing_interval: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    # Breakdown (all in cents)
    plan_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    sms_overage_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    carjam_overage_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    storage_addon_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    subtotal_excl_gst_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    gst_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    processing_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Descriptive
    plan_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sms_overage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    carjam_overage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    storage_addon_gb: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Metadata
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="'nzd'"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'paid'"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_billing_receipts_org_id", "org_id"),
        Index("ix_billing_receipts_billing_date", "billing_date"),
    )

    # Relationships
    organisation = relationship("Organisation", backref="billing_receipts")
