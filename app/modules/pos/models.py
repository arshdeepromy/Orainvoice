"""SQLAlchemy ORM models for pos_sessions and pos_transactions tables.

Maps to tables created by migrations 0039 and 0040.

**Validates: Requirement 22 — POS Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SESSION_STATUSES = ("open", "closed")

PAYMENT_METHODS = ("cash", "card", "split")

SYNC_STATUSES = ("pending", "synced", "conflict", "failed")


class POSSession(Base):
    """A POS session opened by a user at a location."""

    __tablename__ = "pos_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    opening_cash: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    closing_cash: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="open", nullable=False,
    )


class POSTransaction(Base):
    """A single POS transaction, optionally synced from offline."""

    __tablename__ = "pos_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_sessions.id"), nullable=True,
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True,
    )
    table_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    offline_transaction_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    payment_method: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    tip_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), nullable=False,
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )
    cash_tendered: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True,
    )
    change_given: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True,
    )
    is_offline_sync: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    sync_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
    )
    sync_conflicts: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
