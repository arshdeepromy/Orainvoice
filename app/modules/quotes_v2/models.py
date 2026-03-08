"""SQLAlchemy ORM model for the quotes table.

Maps to table created by migration 0031.

**Validates: Requirement 12.1, 12.2, 12.7**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


QUOTE_STATUSES = ["draft", "sent", "accepted", "declined", "expired", "converted"]


class Quote(Base):
    """Quote / estimate with versioning and conversion tracking."""

    __tablename__ = "quotes"
    __table_args__ = ({"extend_existing": True},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    quote_number: Mapped[str] = mapped_column(String(50), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False,
    )
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Line items stored as JSONB array
    line_items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # Versioning
    version_number: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False,
    )
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quotes.id"), nullable=True,
    )

    # Conversion tracking
    converted_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    # Public acceptance
    acceptance_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
