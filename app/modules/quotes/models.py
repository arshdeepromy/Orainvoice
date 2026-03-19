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
    discount_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, server_default="percentage"
    )
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    shipping_charges: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    adjustment: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    acceptance_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    converted_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
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
            "status IN ('draft','sent','accepted','declined','expired','converted')",
            name="ck_quotes_status",
        ),
        {"extend_existing": True},
    )

    # Relationships removed — V2 model is authoritative for this table


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
        {"extend_existing": True},
    )

    # Relationships removed — V2 model is authoritative for this table


# ---------------------------------------------------------------------------
# Recurring Schedule
# ---------------------------------------------------------------------------


class RecurringSchedule(Base):
    """Organisation-scoped recurring invoice schedule.

    NOTE: The authoritative model lives in app/modules/recurring_invoices/models.py.
    This duplicate exists only for legacy import compatibility.  Both use
    extend_existing=True so SQLAlchemy merges them into a single mapper.
    The column definitions here MUST match the actual DB schema.
    """

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
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_generation_date: Mapped[date] = mapped_column(Date, nullable=False)
    auto_issue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    auto_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'active'"
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
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'cancelled')",
            name="ck_recurring_schedules_status",
        ),
        {"extend_existing": True},
    )
