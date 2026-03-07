"""SQLAlchemy ORM model for the retention_releases table.

Maps to table created by migration 0049.

**Validates: Requirement — Retention Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RetentionRelease(Base):
    """A retention release against a construction project."""

    __tablename__ = "retention_releases"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_retention_releases_positive_amount"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False,
    )
    release_date: Mapped[date] = mapped_column(
        Date, nullable=False,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
