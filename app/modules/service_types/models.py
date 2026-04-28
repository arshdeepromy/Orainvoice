"""SQLAlchemy ORM models for service-type-scoped tables.

Tables:
- service_types: organisation-scoped service type definitions (RLS enabled)
- service_type_fields: configurable field definitions per service type (RLS enabled)
- job_card_service_type_values: filled-in field values on job cards (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ---------------------------------------------------------------------------
# Service Type
# ---------------------------------------------------------------------------


class ServiceType(Base):
    """Organisation-scoped service type definition."""

    __tablename__ = "service_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
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

    # Relationships
    fields: Mapped[list[ServiceTypeField]] = relationship(
        back_populates="service_type",
        cascade="all, delete-orphan",
        order_by="ServiceTypeField.display_order",
    )
    organisation = relationship("Organisation", backref="service_types")


# ---------------------------------------------------------------------------
# Service Type Field
# ---------------------------------------------------------------------------


class ServiceTypeField(Base):
    """Configurable field definition attached to a service type."""

    __tablename__ = "service_type_fields"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    service_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_types.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    service_type: Mapped[ServiceType] = relationship(back_populates="fields")


# ---------------------------------------------------------------------------
# Job Card Service Type Value
# ---------------------------------------------------------------------------


class JobCardServiceTypeValue(Base):
    """Filled-in field value for a service type on a job card."""

    __tablename__ = "job_card_service_type_values"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    job_card_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("service_type_fields.id"),
        nullable=False,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_array: Mapped[list | None] = mapped_column(JSONB, nullable=True)
