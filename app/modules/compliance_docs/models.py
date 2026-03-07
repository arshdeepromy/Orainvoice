"""SQLAlchemy ORM model for the compliance_documents table.

Maps to table created by migration 0050.

**Validates: Requirement — Compliance Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComplianceDocument(Base):
    """A compliance or certification document uploaded by an organisation."""

    __tablename__ = "compliance_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    document_type: Mapped[str] = mapped_column(
        String(50), nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    file_key: Mapped[str] = mapped_column(
        String(500), nullable=False,
    )
    file_name: Mapped[str] = mapped_column(
        String(255), nullable=False,
    )
    expiry_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
