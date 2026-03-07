"""SQLAlchemy ORM models for staff_members and staff_location_assignments tables.

Maps to tables created by migration 0036.

**Validates: Requirement — Staff Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Numeric, String, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

ROLE_TYPES = ["employee", "contractor"]


class StaffMember(Base):
    """Staff member or contractor belonging to an organisation."""

    __tablename__ = "staff_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisations.id"), nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role_type: Mapped[str] = mapped_column(
        String(20), default="employee", nullable=False,
    )
    hourly_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    overtime_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
    )
    availability_schedule: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False,
    )
    skills: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    # Relationships
    location_assignments: Mapped[list["StaffLocationAssignment"]] = relationship(
        "StaffLocationAssignment", back_populates="staff_member",
        cascade="all, delete-orphan", lazy="selectin",
    )


class StaffLocationAssignment(Base):
    """Assignment of a staff member to a location."""

    __tablename__ = "staff_location_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_members.id", ondelete="CASCADE"), nullable=False,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # Relationships
    staff_member: Mapped["StaffMember"] = relationship(
        "StaffMember", back_populates="location_assignments",
    )
