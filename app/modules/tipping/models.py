"""SQLAlchemy ORM models for tips and tip_allocations tables.

Maps to tables created by migration 0045.

**Validates: Requirement 24 — Tipping Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Tip(Base):
    """A tip recorded against a POS transaction or invoice."""

    __tablename__ = "tips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True,
    )
    pos_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pos_transactions.id"), nullable=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # Relationships
    allocations: Mapped[list["TipAllocation"]] = relationship(
        "TipAllocation", back_populates="tip",
        cascade="all, delete-orphan", lazy="selectin",
    )


class TipAllocation(Base):
    """Allocation of a tip amount to a specific staff member."""

    __tablename__ = "tip_allocations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tips.id", ondelete="CASCADE"), nullable=False,
    )
    staff_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # Relationships
    tip: Mapped["Tip"] = relationship("Tip", back_populates="allocations")
