"""SQLAlchemy ORM model for the recurring_schedules table.

Maps to the table created by migration 0046.

**Validates: Recurring Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RecurringSchedule(Base):
    """A recurring invoice schedule that generates invoices on a cadence."""

    __tablename__ = "recurring_schedules"
    __table_args__ = (
        CheckConstraint(
            "frequency IN ('weekly', 'fortnightly', 'monthly', 'quarterly', 'annually')",
            name="ck_recurring_schedules_frequency",
        ),
        CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'cancelled')",
            name="ck_recurring_schedules_status",
        ),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False,
    )
    line_items: Mapped[list] = mapped_column(
        JSONB, server_default="'[]'::jsonb", nullable=False,
    )
    frequency: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    start_date: Mapped[date] = mapped_column(
        Date, nullable=False,
    )
    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
    )
    next_generation_date: Mapped[date] = mapped_column(
        Date, nullable=False,
    )
    auto_issue: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    auto_email: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="'active'", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
