"""SQLAlchemy ORM model for the progress_claims table.

Maps to table created by migration 0047.

**Validates: Requirement — ProgressClaim Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CLAIM_STATUSES = ("draft", "submitted", "approved", "rejected")


class ProgressClaim(Base):
    """Construction progress claim against a project contract value."""

    __tablename__ = "progress_claims"
    __table_args__ = (
        UniqueConstraint("org_id", "project_id", "claim_number", name="uq_progress_claims_org_project_claim"),
        CheckConstraint("status IN ('draft', 'submitted', 'approved', 'rejected')", name="ck_progress_claims_status"),
        CheckConstraint("work_completed_to_date <= revised_contract_value", name="ck_progress_claims_work_within_contract"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    claim_number: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False,
    )
    variations_to_date: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False,
    )
    revised_contract_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False,
    )
    work_completed_to_date: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False,
    )
    work_completed_previous: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False,
    )
    work_completed_this_period: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False,
    )
    materials_on_site: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False,
    )
    retention_withheld: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False,
    )
    amount_due: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False,
    )
    completion_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False,
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
