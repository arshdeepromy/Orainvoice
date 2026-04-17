"""SQLAlchemy ORM models for invoice-scoped tables.

Tables:
- invoices: invoice records per organisation (RLS enabled)
- line_items: invoice line items (RLS enabled)
- credit_notes: credit notes linked to invoices (RLS enabled)
- invoice_sequences: gap-free invoice numbering per org
- quote_sequences: gap-free quote numbering per org
- credit_note_sequences: gap-free credit note numbering per org
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Sequence tables for gap-free numbering
# ---------------------------------------------------------------------------


class InvoiceSequence(Base):
    """Per-org counter for gap-free invoice numbering."""

    __tablename__ = "invoice_sequences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=False,
        unique=True,
    )
    last_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    organisation = relationship("Organisation", backref="invoice_sequence")


class QuoteSequence(Base):
    """Per-org counter for gap-free quote numbering."""

    __tablename__ = "quote_sequences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=False,
        unique=True,
    )
    last_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    organisation = relationship("Organisation", backref="quote_sequence")


class CreditNoteSequence(Base):
    """Per-org counter for gap-free credit note numbering."""

    __tablename__ = "credit_note_sequences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=False,
        unique=True,
    )
    last_number: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    organisation = relationship("Organisation", backref="credit_note_sequence")


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


class Invoice(Base):
    """Organisation-scoped invoice record."""

    __tablename__ = "invoices"

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
    invoice_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
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
    vehicle_odometer: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="NZD"
    )
    exchange_rate_to_nzd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default="1.000000"
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    discount_type: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    discount_value: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    balance_due: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    notes_internal: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_customer: Mapped[str | None] = mapped_column(Text, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    recurring_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    job_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    payment_page_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    invoice_data_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
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
            "status IN ('draft','issued','partially_paid','paid','overdue','voided','refunded','partially_refunded')",
            name="ck_invoices_status",
        ),
        CheckConstraint(
            "discount_type IN ('percentage','fixed')",
            name="ck_invoices_discount_type",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="invoices")
    customer = relationship("Customer", backref="invoices")
    branch = relationship("Branch", backref="invoices")
    created_by_user = relationship(
        "User", foreign_keys=[created_by], backref="created_invoices"
    )
    voided_by_user = relationship(
        "User", foreign_keys=[voided_by], backref="voided_invoices"
    )
    line_items: Mapped[list[LineItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="LineItem.sort_order",
    )
    credit_notes: Mapped[list[CreditNote]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Line Item
# ---------------------------------------------------------------------------


class LineItem(Base):
    """Invoice line item (service, part, or labour)."""

    __tablename__ = "line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    catalogue_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    part_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
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
    discount_type: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )
    discount_value: Mapped[Decimal | None] = mapped_column(
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('service','part','labour')",
            name="ck_line_items_item_type",
        ),
        CheckConstraint(
            "discount_type IN ('percentage','fixed')",
            name="ck_line_items_discount_type",
        ),
    )

    # Relationships
    invoice: Mapped[Invoice] = relationship(back_populates="line_items")
    organisation = relationship("Organisation", backref="line_items")


# ---------------------------------------------------------------------------
# Credit Note
# ---------------------------------------------------------------------------


class CreditNote(Base):
    """Credit note linked to an invoice."""

    __tablename__ = "credit_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    credit_note_number: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    stripe_refund_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    organisation = relationship("Organisation", backref="credit_notes")
    invoice: Mapped[Invoice] = relationship(back_populates="credit_notes")
    created_by_user = relationship("User", backref="created_credit_notes")
