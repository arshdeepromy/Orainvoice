"""SQLAlchemy ORM models for the IRD Gateway module.

Tables:
- ird_filing_log: Audit log of all IRD Gateway interactions (RLS enabled)

Requirements: 28.1, 28.2, 28.3
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IrdFilingLog(Base):
    """Audit log entry for an IRD Gateway interaction.

    Records every SOAP request/response for compliance.
    Retained indefinitely (no automatic purging) per IRD requirements.
    """

    __tablename__ = "ird_filing_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    filing_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    request_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    ird_reference: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "filing_type IN ('gst','income_tax')",
            name="ck_ird_filing_log_type",
        ),
    )
