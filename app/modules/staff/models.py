"""SQLAlchemy ORM models for staff_members and related tables.

Maps to tables created by migrations:
  - 0036  — base ``staff_members`` + ``staff_location_assignments`` tables.
  - 0203  — Staff Phase 1: 22 new employment + payroll columns on
            ``staff_members``, plus the ``staff_pay_rates`` (audit ledger)
            and ``staff_roster_view_tokens`` (public viewer) tables.

**Validates: Requirement — Staff Module (R2, R3)**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

ROLE_TYPES = ["employee", "contractor"]

__all__ = [
    "ROLE_TYPES",
    "StaffMember",
    "StaffLocationAssignment",
    "StaffPayRate",
    "StaffRosterViewToken",
]


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
    first_name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reporting_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_members.id", ondelete="SET NULL"), nullable=True,
    )
    shift_start: Mapped[str | None] = mapped_column(String(5), nullable=True)
    shift_end: Mapped[str | None] = mapped_column(String(5), nullable=True)
    role_type: Mapped[str] = mapped_column(
        String(20), default="employee", nullable=False,
    )
    employment_basis: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="full_time",
    )
    working_arrangement: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="rostered",
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

    # ------------------------------------------------------------------
    # Phase 1 — employment record (migration 0203).
    # All columns added here mirror the migration 1:1.
    # ------------------------------------------------------------------
    employment_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    employment_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    employment_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="permanent",
    )
    standard_hours_per_week: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True,
    )
    tax_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    ird_number_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    student_loan: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    kiwisaver_enrolled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    kiwisaver_employee_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 2), nullable=True,
    )
    kiwisaver_employer_rate: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, server_default="3.00",
    )
    bank_account_number_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    probation_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    residency_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="citizen",
    )
    visa_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    self_service_clock_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    on_file_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    weekly_roster_email_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    weekly_roster_sms_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    last_pay_review_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    employment_agreement_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
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


class StaffPayRate(Base):
    """Pay-rate history ledger for a staff member.

    A new row is inserted on every rate change so the prior history is
    preserved (the live rate stays on ``staff_members`` for indexing).
    Mirrors migration 0203 §3.
    """

    __tablename__ = "staff_pay_rates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    hourly_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    overtime_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True,
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class StaffRosterViewToken(Base):
    """Public read-only roster viewer token.

    Issued when a roster SMS or email is sent so the recipient can open
    a token-gated view of the week without logging in. Tokens are
    revoked (``expires_at`` set to ``now()``) when the staff is
    deactivated, terminated, or hard-deleted (cascade).

    Mirrors migration 0203 §4 + design §3.1.1.
    """

    __tablename__ = "staff_roster_view_tokens"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "week_start",
            name="uq_staff_roster_view_tokens_staff_week",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(Text, nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
