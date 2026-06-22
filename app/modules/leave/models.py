"""SQLAlchemy ORM models for the leave engine.

Maps 1:1 to the four tables created by migration ``0205_leave_schema``:
  - ``leave_types`` — per-org leave-type catalogue (statutory + custom).
  - ``leave_balances`` — per-staff × per-type rolling balance.
  - ``leave_requests`` — submission / approval state machine.
  - ``leave_ledger`` — append-only accrual + adjustment history.

Column lists, defaults, FK targets, and ON DELETE behaviour mirror the
migration so introspection (``Table.columns.keys()``) matches the live
schema. CHECK constraints declared at the DB layer (status / reason /
accrual enums + relationship_to_subject) are not duplicated here — the
service layer guards them and the DB enforces them on write.

**Validates: Requirements R1, R2, R3, R4 — Staff Management Phase 2**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = [
    "LeaveType",
    "LeaveBalance",
    "LeaveRequest",
    "LeaveLedger",
    "LeaveEligibilityNote",
]


class LeaveType(Base):
    """Per-org leave type catalogue (statutory + custom)."""

    __tablename__ = "leave_types"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_leave_types_org_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_paid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    accrual_method: Mapped[str] = mapped_column(Text, nullable=False)
    accrual_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True,
    )
    accrual_unit: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="hours",
    )
    carry_over_max: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True,
    )
    is_statutory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    requires_doctor_note: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    confidential_visibility: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LeaveBalance(Base):
    """Per-staff × per-leave-type rolling balance.

    ``accrued`` / ``used`` / ``pending`` are tracked separately so the
    available figure is `accrued - used - pending`. ``anniversary_date``
    seeds the accrual engine for ``accrual_method='anniversary'`` types.
    """

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "leave_type_id", name="uq_leave_balances_staff_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accrued_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0",
    )
    used_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0",
    )
    pending_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0",
    )
    anniversary_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_accrual_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class LeaveRequest(Base):
    """Submission / approval state machine for staff leave requests.

    ``relationship_to_subject`` is required (validated in the service
    layer) when ``leave_type.code='bereavement'``; ``partial_day_start_time``
    is populated only when the request fits in a single working day.
    """

    __tablename__ = "leave_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_types.id"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    hours_requested: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending",
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    relationship_to_subject: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    partial_day_start_time: Mapped[time | None] = mapped_column(
        Time, nullable=True,
    )
    attachment_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LeaveLedger(Base):
    """Append-only accrual + adjustment history.

    Service code MUST NEVER UPDATE or DELETE these rows — corrections
    write a new compensating row with the inverse ``delta_hours``. CHECK
    enum on ``reason`` is enforced at the DB layer (see migration 0205).
    """

    __tablename__ = "leave_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    delta_hours: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_requests.id"),
        nullable=True,
    )
    occurred_at: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class LeaveEligibilityNote(Base):
    """Append-only vesting record + Eligibility_Note store (migration 0226).

    One row per (staff, leave_type) onset — the ``UNIQUE(staff_id,
    leave_type_id)`` constraint enforces "one onset note ever" (R12.4 /
    R13.1) and underpins notification de-dup. ``rule_set_version`` stamps the
    rule-set that produced the vesting (R6.6). Service code MUST NEVER UPDATE
    or DELETE these rows (append-only, R13.4).
    """

    __tablename__ = "leave_eligibility_notes"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "leave_type_id",
            name="uq_leave_eligibility_notes_staff_type",
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
    leave_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_types.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rule_set_version: Mapped[str] = mapped_column(Text, nullable=False)
    milestone_key: Mapped[str] = mapped_column(Text, nullable=False)
    hours_test_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    condition_text: Mapped[str] = mapped_column(Text, nullable=False)
    vested_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
