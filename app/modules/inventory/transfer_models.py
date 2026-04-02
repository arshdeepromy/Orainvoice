"""SQLAlchemy ORM model for inter-branch stock transfers.

Tables:
- stock_transfers: tracks inventory movements between branches (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class StockTransfer(Base):
    """Inter-branch stock transfer with state-machine lifecycle.

    Status transitions: pending → approved → shipped → received
    Cancellation allowed from pending, approved, or shipped.

    **Validates: Requirements 17.1**
    """

    __tablename__ = "stock_transfers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    from_branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False,
    )
    to_branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False,
    )
    stock_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stock_items.id"), nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="'pending'",
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    organisation = relationship("Organisation", backref="stock_transfers")
    from_branch = relationship(
        "Branch", foreign_keys=[from_branch_id], backref="transfers_out",
    )
    to_branch = relationship(
        "Branch", foreign_keys=[to_branch_id], backref="transfers_in",
    )
    stock_item = relationship("StockItem", backref="transfers")
    requester = relationship(
        "User", foreign_keys=[requested_by], backref="transfer_requests",
    )
    approver = relationship(
        "User", foreign_keys=[approved_by], backref="transfer_approvals",
    )
