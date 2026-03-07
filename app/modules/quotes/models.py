"""SQLAlchemy ORM models for quote-scoped tables.

Tables:
- quotes: quote records per organisation (RLS enabled)
- quote_line_items: quote line items (RLS enabled)
- recurring_schedules: recurring invoice schedules per organisation (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------


class Quote(Base):
    """Organisation-scoped quote record."""

    __tablename__ = "quotes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    quote_number: Mapped[str] = mapped_column(String(50), nullable=False)
    vehicle_rego: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    vehicle_make: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    vehicle_model: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    vehicle_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
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
        CheckConstraint(
            "status IN ('draft','sent','accepted','declined','expired')",
            name="ck_quotes_status",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="quotes")
    customer = relationship("Customer", backref="quotes")
    created_by_user = relationship("User", backref="created_quotes")
    line_items: Mapped[list[QuoteLineItem]] = relationship(
        back_populates="quote",
        cascade="all, delete-orphan",
        order_by="QuoteLineItem.sort_order",
    )


# ---------------------------------------------------------------------------
# Quote Line Item
# ---------------------------------------------------------------------------


class QuoteLineItem(Base):
    """Quote line item (service, part, or labour)."""

    __tablename__ = "quote_line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, server_default="1"
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    hours: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    hourly_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    is_gst_exempt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    warranty_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('service','part','labour')",
            name="ck_quote_line_items_item_type",
        ),
    )

    # Relationships
    quote: Mapped[Quote] = relationship(back_populates="line_items")
    organisation = relationship("Organisation", backref="quote_line_items")


# ---------------------------------------------------------------------------
# Recurring Schedule
# ---------------------------------------------------------------------------


class RecurringSchedule(Base):
    """Organisation-scoped recurring invoice schedule."""

    __tablename__ = "recurring_schedules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    auto_issue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
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
        CheckConstraint(
            "frequency IN ('weekly','fortnightly','monthly','quarterly','annually')",
            name="ck_recurring_schedules_frequency",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="recurring_schedules")
    customer = relationship("Customer", backref="recurring_schedules")
    created_by_user = relationship("User", backref="created_recurring_schedules")
