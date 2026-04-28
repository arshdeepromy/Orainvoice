"""SQLAlchemy ORM models for job-card-scoped tables.

Tables:
- job_cards: job card / work order records per organisation (RLS enabled)
- job_card_items: job card line items (RLS enabled)

Note: time_entries is owned by app.modules.time_tracking_v2.models.
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
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Job Card
# ---------------------------------------------------------------------------


class JobCard(Base):
    """Organisation-scoped job card / work order."""

    __tablename__ = "job_cards"

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
    vehicle_rego: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="open"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_members.id", ondelete="SET NULL"), nullable=True
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
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    service_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_types.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open','in_progress','completed','invoiced')",
            name="ck_job_cards_status",
        ),
    )

    # Relationships
    organisation = relationship("Organisation", backref="job_cards")
    branch = relationship("Branch")
    customer = relationship("Customer", backref="job_cards")
    assigned_staff = relationship(
        "StaffMember", foreign_keys=[assigned_to], backref="assigned_job_cards"
    )
    created_by_user = relationship(
        "User", foreign_keys=[created_by], backref="created_job_cards"
    )
    items: Mapped[list[JobCardItem]] = relationship(
        back_populates="job_card",
        cascade="all, delete-orphan",
        order_by="JobCardItem.sort_order",
    )
    service_type = relationship("ServiceType")


# ---------------------------------------------------------------------------
# Job Card Item
# ---------------------------------------------------------------------------


class JobCardItem(Base):
    """Job card line item (service, part, or labour)."""

    __tablename__ = "job_card_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    job_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    catalogue_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items_catalogue.id"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 3), nullable=False, server_default="1"
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    is_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('service','part','labour')",
            name="ck_job_card_items_item_type",
        ),
    )

    # Relationships
    job_card: Mapped[JobCard] = relationship(back_populates="items")
    organisation = relationship("Organisation", backref="job_card_items")


# Re-export TimeEntry from the authoritative v2 module for backward compatibility
from app.modules.time_tracking_v2.models import TimeEntry  # noqa: F401, E402


