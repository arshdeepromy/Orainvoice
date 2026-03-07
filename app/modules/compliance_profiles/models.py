"""SQLAlchemy ORM model for the compliance_profiles table.

Maps to the table created by migration 0012 and seeded by migration 0020.

**Validates: Requirement 5.2**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ComplianceProfile(Base):
    """Country-specific tax and regulatory configuration.

    Each profile defines the tax label, rates, date/number formats,
    currency, and optional tax number validation for a country.
    """

    __tablename__ = "compliance_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    country_code: Mapped[str] = mapped_column(
        String(2), unique=True, nullable=False, index=True,
    )
    country_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_label: Mapped[str] = mapped_column(String(20), nullable=False)
    default_tax_rates: Mapped[list] = mapped_column(JSONB, nullable=False)
    tax_number_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_number_regex: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_inclusive_default: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    date_format: Mapped[str] = mapped_column(String(20), nullable=False)
    number_format: Mapped[str] = mapped_column(String(20), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    report_templates: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False,
    )
    gdpr_applicable: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
