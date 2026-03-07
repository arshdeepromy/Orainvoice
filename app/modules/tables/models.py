"""SQLAlchemy ORM models for floor_plans, restaurant_tables, and table_reservations.

Maps to tables created by migration 0043.

**Validates: Requirement — Table Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

TABLE_STATUSES = ("available", "occupied", "needs_cleaning", "reserved")

RESERVATION_STATUSES = ("confirmed", "seated", "completed", "cancelled", "no_show")


class FloorPlan(Base):
    """A visual floor plan layout for a restaurant/hospitality venue."""

    __tablename__ = "floor_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    name: Mapped[str] = mapped_column(
        String(100), default="Main Floor", nullable=False,
    )
    width: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("800"), nullable=False,
    )
    height: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("600"), nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class RestaurantTable(Base):
    """A table within a floor plan with position, size, and status."""

    __tablename__ = "restaurant_tables"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    table_number: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )
    seat_count: Mapped[int] = mapped_column(
        Integer, default=4, nullable=False,
    )
    position_x: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), nullable=False,
    )
    position_y: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), nullable=False,
    )
    width: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("100"), nullable=False,
    )
    height: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("100"), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="available", nullable=False,
    )
    merged_with_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurant_tables.id"), nullable=True,
    )
    floor_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("floor_plans.id"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TableReservation(Base):
    """A reservation for a specific table at a date/time."""

    __tablename__ = "table_reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurant_tables.id"), nullable=False,
    )
    customer_name: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    party_size: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    reservation_date: Mapped[date] = mapped_column(
        Date, nullable=False,
    )
    reservation_time: Mapped[time] = mapped_column(
        Time, nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(
        Integer, default=90, nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), default="confirmed", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
