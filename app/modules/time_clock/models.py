"""SQLAlchemy ORM models for the time-clock + scheduling-ops surface.

Maps 1:1 to the six tables created by migration
``0207_time_clock_schema``:

  - ``time_clock_entries`` — kiosk / self-service / admin-manual in-out
    events. The JSONB column on this table is named ``flags`` (NOT
    ``metadata``) because SQLAlchemy ``DeclarativeBase`` reserves the
    ``metadata`` attribute name on the class — declaring a column
    literal called ``metadata`` would raise ``InvalidRequestError`` at
    import time. See migration 0207 inline comment + tasks B1 + P3-N3.
  - ``break_records`` — child of ``time_clock_entries``; ``ON DELETE
    CASCADE`` so admin hard-deletes don't leave orphan break rows.
  - ``timesheet_approvals`` — week-level approval state machine. The
    status enum includes ``'edited_after_approval'`` (G16) so admin
    manual edits inside an already-approved week can flip the row
    without losing its approval lineage. UNIQUE on
    ``(staff_id, week_start)``.
  - ``overtime_requests`` — 3-state pre-approval flow.
  - ``shift_swap_requests`` — 5-state machine including the new
    ``'awaiting_manager'`` state (G8) reachable when the org's
    ``clock_in_policy.shift_swap_requires_manager_approval`` toggle is
    on.
  - ``shift_cover_requests`` — 4-state open-broadcast cover model.

Column lists, defaults, FK targets, and ON DELETE behaviour mirror the
migration so introspection (``Table.columns.keys()``) matches the live
schema. CHECK constraints declared at the DB layer (status / source /
break_type / toil_choice enums + the kiosk-photo guard) are not
duplicated here — the service layer guards them and the DB enforces
them on write.

No ORM relationships are declared (mirrors ``app/modules/leave/models.py``)
to keep the models lean and avoid import-time graph cycles with the
scheduling, staff, and auth modules.

**Validates: Requirements R3, R4, R6, R12, R14 — Staff Management Phase 3**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = [
    "TimeClockEntry",
    "BreakRecord",
    "TimesheetApproval",
    "OvertimeRequest",
    "ShiftSwapRequest",
    "ShiftCoverRequest",
]


# Literal type aliases — kept here so service + schema layers can import
# the canonical enum lists from a single place. The DB-side CHECK
# constraints in migration 0207 are the source of truth; these mirrors
# exist to surface the enums at the type-checker level.
TimeClockSource = Literal[
    "kiosk", "self_service_mobile", "self_service_web", "admin_manual",
]
BreakType = Literal["rest_paid", "meal_unpaid"]
TimesheetStatus = Literal[
    "pending", "approved", "rejected", "edited_after_approval",
]
ToilChoice = Literal["pay_cash", "toil"]
OvertimeStatus = Literal["pending", "approved", "rejected"]
# G8 — 'awaiting_manager' is the new state when manager approval is
# required by clock_in_policy.shift_swap_requires_manager_approval.
ShiftSwapStatus = Literal[
    "pending", "awaiting_manager", "accepted", "rejected", "cancelled",
]
ShiftCoverStatus = Literal["open", "accepted", "cancelled", "expired"]


class TimeClockEntry(Base):
    """Kiosk / self-service / admin-manual clock-in / clock-out event.

    A row represents one shift's worth of attendance — created on
    clock-in and updated on clock-out. ``worked_minutes`` is computed
    by the service layer at clock-out time (elapsed minus
    ``break_minutes``) so the ``timesheet_approvals`` aggregator can
    sum it directly without re-walking ``break_records``.

    The ``flags`` JSONB column (G10) holds soft markers like
    ``flagged_for_review`` and ``review_reason`` written by the Hours
    tab "Flag for follow-up" action. **Column literal name is**
    ``flags`` **— NOT** ``metadata`` **—** because SQLAlchemy
    ``DeclarativeBase`` reserves the ``metadata`` attribute on the
    class for the table-collection registry.
    """

    __tablename__ = "time_clock_entries"
    __table_args__ = (
        CheckConstraint(
            "source IN ('kiosk','self_service_mobile','self_service_web','admin_manual')",
            name="ck_time_clock_entries_source",
        ),
        CheckConstraint(
            "source <> 'kiosk' OR clock_in_photo_url IS NOT NULL",
            name="ck_time_clock_entries_kiosk_photo",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    clock_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    clock_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    clock_in_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    clock_out_photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    clock_in_lat: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True,
    )
    clock_in_lng: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True,
    )
    clock_out_lat: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True,
    )
    clock_out_lng: Mapped[Decimal | None] = mapped_column(
        Numeric(9, 6), nullable=True,
    )
    scheduled_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("schedule_entries.id"),
        nullable=True,
    )
    break_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    worked_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # G10 — JSONB soft-flags container. See module docstring + migration
    # 0207 for the naming rationale. ``default=dict`` populates the
    # client-side default on ORM-level inserts; ``server_default``
    # mirrors the migration's ``DEFAULT '{}'::jsonb`` so direct INSERTs
    # (e.g. raw SQL or fixture loaders) get the same shape.
    flags: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class BreakRecord(Base):
    """Per-entry break log; cascade-deleted with the parent clock entry.

    ``break_type`` is one of ``rest_paid`` (10-min ERA-mandated rest)
    or ``meal_unpaid`` (30-min meal break that deducts from
    ``worked_minutes``). ``minutes`` is set on break-end and used by
    the parent ``TimeClockEntry.break_minutes`` aggregator when
    ``break_type='meal_unpaid'`` only.
    """

    __tablename__ = "break_records"
    __table_args__ = (
        CheckConstraint(
            "break_type IN ('rest_paid','meal_unpaid')",
            name="ck_break_records_break_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    time_clock_entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("time_clock_entries.id", ondelete="CASCADE"),
        nullable=False,
    )
    break_type: Mapped[str] = mapped_column(Text, nullable=False)
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TimesheetApproval(Base):
    """Week-level approval state machine.

    Status enum (G16):
      - ``pending``  — week not yet approved.
      - ``approved`` — manager has signed off; ``time_clock_entries``
        edits inside the window are locked (G7 — only this table is
        locked, ``time_entries`` billable timer is not touched).
      - ``rejected`` — manager refused; week reopens for staff edit.
      - ``edited_after_approval`` — admin manual edit hit the window
        after approval; totals were re-computed and an audit row
        written.

    UNIQUE on ``(staff_id, week_start)`` because a staff member has at
    most one approval row per week.

    ``ordinary_minutes`` / ``total_overtime_minutes`` /
    ``public_holiday_minutes`` are the breakdown produced by
    ``compute_week_totals`` (design §4.2, G1) using the org's
    ``overtime_policy`` thresholds.
    """

    __tablename__ = "timesheet_approvals"
    __table_args__ = (
        UniqueConstraint(
            "staff_id", "week_start",
            name="uq_timesheet_approvals_staff_week",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','edited_after_approval')",
            name="ck_timesheet_approvals_status",
        ),
        CheckConstraint(
            "toil_choice IS NULL OR toil_choice IN ('pay_cash','toil')",
            name="ck_timesheet_approvals_toil_choice",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending",
    )
    total_worked_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    total_scheduled_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
    )
    total_overtime_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    total_break_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    ordinary_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    public_holiday_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    toil_choice: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OvertimeRequest(Base):
    """Pre-approval request for working extra minutes on a shift.

    3-state machine (``pending``, ``approved``, ``rejected``). When
    the org's ``overtime_policy.require_pre_approval`` toggle is on,
    ``compute_week_totals`` cross-checks approved request minutes
    against actual worked overtime and appends an
    ``unapproved_overtime`` note to the resulting approval row when
    the actual exceeds the approved (G1.5).
    """

    __tablename__ = "overtime_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')",
            name="ck_overtime_requests_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    staff_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    schedule_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("schedule_entries.id"),
        nullable=True,
    )
    proposed_extra_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending",
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
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


class ShiftSwapRequest(Base):
    """Staff-to-staff shift swap with optional manager approval gate.

    5-state machine (G8): ``pending`` → ``awaiting_manager`` →
    ``accepted`` (or ``rejected`` / ``cancelled`` from any
    pre-terminal state). The ``awaiting_manager`` state is only
    reachable when the org's
    ``clock_in_policy.shift_swap_requires_manager_approval`` toggle is
    on; otherwise the auto-approve path skips straight from
    ``pending`` to ``accepted`` on target acceptance.
    """

    __tablename__ = "shift_swap_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','awaiting_manager','accepted','rejected','cancelled')",
            name="ck_shift_swap_requests_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    requester_staff_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    target_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=True,
    )
    schedule_entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("schedule_entries.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending",
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class ShiftCoverRequest(Base):
    """Open-broadcast cover request for an unwanted shift.

    4-state machine: ``open`` → ``accepted`` (or ``cancelled`` /
    ``expired`` from ``open``). Eligibility filtering at broadcast
    time and re-checking at claim time live in
    ``app/modules/time_clock/cover.py`` per design §4 + G6.
    """

    __tablename__ = "shift_cover_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open','accepted','cancelled','expired')",
            name="ck_shift_cover_requests_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False,
    )
    schedule_entry_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("schedule_entries.id"),
        nullable=False,
    )
    requester_staff_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="open",
    )
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("staff_members.id"),
        nullable=True,
    )
    broadcast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
