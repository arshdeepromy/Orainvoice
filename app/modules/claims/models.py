"""SQLAlchemy ORM models for customer claims and returns.

Tables:
- customer_claims: claim records per organisation
- claim_actions: claim timeline / audit actions
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimType(str, Enum):
    WARRANTY = "warranty"
    DEFECT = "defect"
    SERVICE_REDO = "service_redo"
    EXCHANGE = "exchange"
    REFUND_REQUEST = "refund_request"


class ClaimStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class ResolutionType(str, Enum):
    FULL_REFUND = "full_refund"
    PARTIAL_REFUND = "partial_refund"
    CREDIT_NOTE = "credit_note"
    EXCHANGE = "exchange"
    REDO_SERVICE = "redo_service"
    NO_ACTION = "no_action"


# ---------------------------------------------------------------------------
# Valid status transitions
# ---------------------------------------------------------------------------

VALID_CLAIM_TRANSITIONS: dict[str, set[str]] = {
    "open": {"investigating"},
    "investigating": {"approved", "rejected"},
    "approved": {"resolved"},
    "rejected": {"resolved"},
    "resolved": set(),
}


# ---------------------------------------------------------------------------
# CustomerClaim
# ---------------------------------------------------------------------------


class CustomerClaim(Base):
    """Organisation-scoped customer claim record."""

    __tablename__ = "customer_claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )

    # Source references (at least one required via CHECK constraint)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=True
    )
    job_card_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_cards.id"), nullable=True
    )
    line_item_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    # Claim details
    reference: Mapped[str | None] = mapped_column(
        String(50), nullable=True, unique=False,
        comment="Human-readable claim reference, e.g. CLM-00001",
    )
    claim_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="open"
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Resolution details
    resolution_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    resolution_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Downstream entity references
    refund_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    credit_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_notes.id"), nullable=True
    )
    return_movement_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    warranty_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("job_cards.id"), nullable=True
    )

    # Cost tracking
    cost_to_business: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0"
    )
    cost_breakdown: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}',
    )

    # Audit
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

    # Relationships
    organisation = relationship("Organisation", backref="claims")
    branch = relationship("Branch")
    customer = relationship("Customer", backref="claims")
    invoice = relationship("Invoice", backref="claims")
    job_card = relationship("JobCard", foreign_keys=[job_card_id])
    warranty_job = relationship("JobCard", foreign_keys=[warranty_job_id])
    refund = relationship("Payment")
    credit_note = relationship("CreditNote")
    actions: Mapped[list["ClaimAction"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# ClaimAction
# ---------------------------------------------------------------------------


class ClaimAction(Base):
    """Claim timeline action record."""

    __tablename__ = "claim_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer_claims.id", ondelete="CASCADE"),
        nullable=False,
    )

    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    performed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    claim: Mapped[CustomerClaim] = relationship(back_populates="actions")
    performed_by_user = relationship("User")
