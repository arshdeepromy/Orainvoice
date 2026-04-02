"""SQLAlchemy ORM models for booking-scoped tables.

Tables:
- bookings: appointment / booking records per organisation (RLS enabled)

The actual DB schema was created by migration 0038 (drop+recreate) and
enhanced by migration 0081 (new columns).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Booking(Base):
    """Organisation-scoped appointment / booking record.

    Matches the actual DB schema from migration 0038 + 0081 + 0082.
    """

    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    # Customer info (stored directly, not FK)
    customer_name: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    customer_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    customer_phone: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_members.id"), nullable=True
    )
    vehicle_rego: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    service_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_token: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    converted_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    converted_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Columns from migration 0081
    service_catalogue_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("items_catalogue.id"), nullable=True
    )
    service_price: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    send_email_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    send_sms_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    reminder_offset_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 1), nullable=True
    )
    reminder_scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reminder_cancelled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    booking_data_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
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

    __table_args__ = (
        {"extend_existing": True},
    )
