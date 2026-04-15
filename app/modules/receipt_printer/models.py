"""SQLAlchemy ORM models for printer_configs and print_jobs tables.

Maps to tables created by migrations 0041 and 0042.

**Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CONNECTION_TYPES = ("usb", "bluetooth", "network", "star_webprnt", "epson_epos", "generic_http", "browser_print")
JOB_TYPES = ("receipt", "kitchen", "report")
JOB_STATUSES = ("pending", "printing", "completed", "failed")


class PrinterConfig(Base):
    """A configured receipt/kitchen printer for an organisation."""

    __tablename__ = "printer_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    connection_type: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paper_width: Mapped[int] = mapped_column(
        Integer, default=80, nullable=False,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    is_kitchen_printer: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class PrintJob(Base):
    """A queued print job dispatched to a printer."""

    __tablename__ = "print_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    printer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("printer_configs.id"), nullable=True,
    )
    job_type: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False,
    )
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
