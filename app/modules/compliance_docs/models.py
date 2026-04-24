"""SQLAlchemy ORM model for the compliance_documents table.

Maps to table created by migration 0050.

**Validates: Requirement — Compliance Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
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


class ComplianceNotificationLog(Base):
    """Tracks which expiry notifications have been sent to prevent duplicates."""

    __tablename__ = "compliance_notification_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_documents.id", ondelete="CASCADE"), nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False,
    )
    threshold: Mapped[str] = mapped_column(
        String(10), nullable=False,
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("document_id", "threshold", name="uq_compliance_notif_doc_threshold"),
    )


class ComplianceDocumentCategory(Base):
    """Predefined (system-wide) and custom (org-specific) document categories."""

    __tablename__ = "compliance_document_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=True,
    )
    is_predefined: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("name", "org_id", name="uq_compliance_cat_name_org"),
    )
