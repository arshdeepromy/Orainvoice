"""SQLAlchemy ORM models for the multi-currency module.

Maps to tables created by migration 0052: exchange_rates, org_currencies.

**Validates: Requirement — MultiCurrency Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ExchangeRate(Base):
    """An exchange rate between two currencies on a given date."""

    __tablename__ = "exchange_rates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False,
    )
    target_currency: Mapped[str] = mapped_column(
        String(3), nullable=False,
    )
    rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(50), server_default="manual", nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(
        Date, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class OrgCurrency(Base):
    """An enabled currency for an organisation."""

    __tablename__ = "org_currencies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False,
    )
    is_base: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
    )
