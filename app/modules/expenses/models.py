"""SQLAlchemy ORM models for expenses, mileage_preferences, mileage_rates tables.

Maps to tables created by migrations 0034 and 0108.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, func, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

EXPENSE_CATEGORIES = [
    "materials", "travel", "subcontractor", "equipment",
    "fuel", "accommodation", "meals", "office", "other",
]


class Expense(Base):
    """Expense record linked to a job and/or project."""

    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_file_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_pass_through: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_billable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_invoiced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expense_type: Mapped[str] = mapped_column(String(20), default="expense", nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MileagePreference(Base):
    """Per-org mileage preferences (singleton)."""

    __tablename__ = "mileage_preferences"
    __table_args__ = (UniqueConstraint("org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    default_unit: Mapped[str] = mapped_column(String(10), default="km", nullable=False)
    default_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MileageRate(Base):
    """Mileage rate per org, optionally from a start date."""

    __tablename__ = "mileage_rates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rate_per_unit: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NZD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
