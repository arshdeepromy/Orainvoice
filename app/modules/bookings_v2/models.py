"""SQLAlchemy ORM models for bookings and booking_rules tables.

Maps to tables created by migration 0038.

**Validates: Requirement 19 — Booking Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

BOOKING_STATUSES = ["pending", "confirmed", "cancelled", "completed"]


class Booking(Base):
    """A customer booking / appointment for an organisation."""

    __tablename__ = "bookings"
    __table_args__ = ({"extend_existing": True},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_members.id"), nullable=True,
    )
    service_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True,
    )
    converted_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    converted_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class BookingRule(Base):
    """Configurable booking rules for an organisation (or per service type)."""

    __tablename__ = "booking_rules"
    __table_args__ = ({"extend_existing": True},)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    service_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False,
    )
    min_advance_hours: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False,
    )
    max_advance_days: Mapped[int] = mapped_column(
        Integer, default=90, nullable=False,
    )
    buffer_minutes: Mapped[int] = mapped_column(
        Integer, default=15, nullable=False,
    )
    available_days: Mapped[list] = mapped_column(
        JSONB, default=lambda: [1, 2, 3, 4, 5], nullable=False,
    )
    available_hours: Mapped[dict] = mapped_column(
        JSONB, default=lambda: {"start": "09:00", "end": "17:00"}, nullable=False,
    )
    max_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
