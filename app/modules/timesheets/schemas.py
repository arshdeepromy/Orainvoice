"""Pydantic request/response schemas for the staff timesheets module.

All list responses use the ``{items, total}`` convention per safe-api-consumption.md.
Decimal fields represent hours (minutes / 60, rounded 2dp).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# --- Response schemas ---


class TimesheetSummary(BaseModel):
    id: UUID
    staff_id: UUID
    staff_name: str
    branch_name: str | None = None
    status: str
    rostered_hours: Decimal
    actual_hours: Decimal
    adjusted_hours: Decimal | None = None
    variance_hours: Decimal  # actual - rostered
    exception_count: int
    approved_by_name: str | None = None
    approved_at: datetime | None = None


class PeriodSummary(BaseModel):
    total_staff: int
    approved_count: int
    pending_count: int
    locked_count: int
    total_ordinary_hours: Decimal
    total_overtime_hours: Decimal
    total_public_holiday_hours: Decimal


class TimesheetListResponse(BaseModel):
    items: list[TimesheetSummary]
    total: int
    period_summary: PeriodSummary


class ClockedInEntry(BaseModel):
    id: UUID
    staff_id: UUID
    staff_name: str
    position: str | None = None
    clock_in_at: datetime
    elapsed_minutes: int
    on_break: bool = False
    break_started_at: datetime | None = None
    clock_in_branch_name: str
    clock_out_branch_name: str | None = None
    source: str  # kiosk, self_service_mobile, self_service_web, admin_manual
    clock_in_ip: str | None = None
    rostered_start: datetime | None = None
    punctuality: str | None = None  # on_time, late, early


class ClockedInResponse(BaseModel):
    items: list[ClockedInEntry]
    total: int


class TimesheetDetailEntry(BaseModel):
    """A single clock entry within a timesheet drill-in."""

    id: UUID
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    worked_minutes: int | None = None
    matched_minutes: int | None = None
    match_type: str | None = None  # exact, grace, rounded, unmatched
    schedule_entry_id: UUID | None = None
    schedule_start: datetime | None = None
    schedule_end: datetime | None = None
    branch_name: str | None = None
    source: str | None = None
    breaks: list[dict] = Field(default_factory=list)


class TimesheetDetailResponse(BaseModel):
    """Full detail for a single timesheet including its clock entries."""

    id: UUID
    staff_id: UUID
    staff_name: str
    pay_period_id: UUID
    period_start: str  # ISO date
    period_end: str
    branch_name: str | None = None
    status: str
    rostered_minutes: int
    actual_minutes: int
    adjusted_minutes: int | None = None
    ordinary_minutes: int
    overtime_minutes: int
    public_holiday_minutes: int
    exception_flags: list[dict] = Field(default_factory=list)
    notes: str | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    locked_at: datetime | None = None
    locked_by_name: str | None = None
    entries: list[TimesheetDetailEntry] = Field(default_factory=list)


# --- Request schemas ---


class AdjustRequest(BaseModel):
    adjusted_minutes: int = Field(..., ge=0)
    notes: str = Field(..., min_length=1, max_length=500)


class TimesheetSettingsRead(BaseModel):
    id: UUID
    org_id: UUID
    branch_id: UUID | None = None
    branch_name: str | None = None
    clock_rounding_minutes: int
    clock_rounding_direction: str
    early_grace_minutes: int
    late_grace_minutes: int
    match_policy: str
    auto_approve_threshold_minutes: int
    require_approval_before_lock: bool
    # Phase C — overtime & holidays
    daily_overtime_threshold_minutes: int = 480
    weekly_overtime_threshold_minutes: int = 2400
    overtime_rate_multiplier: Decimal = Decimal("1.50")
    break_rules: list = Field(default_factory=list)
    public_holiday_rate_multiplier: Decimal = Decimal("1.50")


class TimesheetSettingsUpdate(BaseModel):
    clock_rounding_minutes: int | None = Field(None, ge=1, le=30)
    clock_rounding_direction: Literal["nearest", "up", "down"] | None = None
    early_grace_minutes: int | None = Field(None, ge=0)
    late_grace_minutes: int | None = Field(None, ge=0)
    match_policy: Literal["pay_actual", "round_to_roster", "actual_rounded"] | None = None
    auto_approve_threshold_minutes: int | None = Field(None, ge=0)
    require_approval_before_lock: bool | None = None
    # Phase C — overtime & holidays
    daily_overtime_threshold_minutes: int | None = Field(None, ge=0)
    weekly_overtime_threshold_minutes: int | None = Field(None, ge=0)
    overtime_rate_multiplier: Decimal | None = Field(None, ge=Decimal("1.0"))
    break_rules: list | None = None
    public_holiday_rate_multiplier: Decimal | None = Field(None, ge=Decimal("1.0"))


class TimesheetSettingsResponse(BaseModel):
    org_default: TimesheetSettingsRead | None = None
    branch_overrides: list[TimesheetSettingsRead] = Field(default_factory=list)


class BulkActionResponse(BaseModel):
    affected_count: int
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)


# --- Weekly breakdown ("weekly lens" review aid) ---
#
# READ-ONLY review aid. A pay period that spans more than one ISO week
# (fortnightly / monthly) is split into per-week (Mon–Sun) buckets clamped to
# the period bounds, each carrying per-staff worked minutes and a week total.
# This NEVER touches pay-run / materialisation / payslip logic.


class WeeklyBreakdownStaffEntry(BaseModel):
    """Per-staff worked minutes within a single week bucket."""

    staff_id: UUID
    staff_name: str
    minutes: int


class WeeklyBreakdownWeek(BaseModel):
    """One ISO week (Mon–Sun) bucket clamped to the pay-period bounds.

    ``start_date`` / ``end_date`` are the CLAMPED bounds — the first and last
    buckets of a period may be partial weeks. ``iso_week`` is the ISO 8601 week
    number; ``week_index`` is the 1-based position within the period.
    """

    week_index: int
    iso_week: int
    start_date: date
    end_date: date
    total_minutes: int
    staff: list[WeeklyBreakdownStaffEntry] = Field(default_factory=list)


class WeeklyBreakdownResponse(BaseModel):
    """Pay period split into ISO-week buckets. ``multi_week`` = weeks > 1."""

    pay_period_id: UUID
    multi_week: bool
    weeks: list[WeeklyBreakdownWeek] = Field(default_factory=list)


# --- Attendance report (date-range "who worked + hours vs expected" view) ---
#
# READ-ONLY review aid for the Timesheets page "Attendance" tab. Aggregates
# raw clock attendance (``TimeClockEntry.worked_minutes``) per staff over an
# arbitrary [date_from, date_to] range (defaults to today), and compares each
# staff member's worked hours against their EXPECTED hours for that range. The
# expected figure is resolved per staff with this precedence:
#   1. ``scheduled``  — sum of ``schedule_entries`` overlapping the range
#   2. ``fixed``      — fixed-arrangement staff's availability_schedule hours
#   3. ``roster``     — rostered-arrangement staff's availability_schedule hours
#   4. ``none``       — no schedule/roster on file (expected_hours is null)
# This never touches pay-run / materialisation / payslip / timesheet state.


class AttendanceRow(BaseModel):
    staff_id: UUID
    staff_name: str
    position: str | None = None
    branch_name: str | None = None
    worked_hours: Decimal            # completed shifts only (clocked out)
    expected_hours: Decimal | None = None
    expected_source: str             # scheduled | fixed | roster | none
    variance_hours: Decimal | None = None  # worked - expected (null when no expectation)
    shift_count: int
    is_clocked_in: bool = False      # has an open (not-yet-clocked-out) shift in range
    last_clock_out_at: datetime | None = None
    # Pre-payroll review state (aggregated over the row's completed shifts).
    # ``pending_review_count`` = completed shifts not yet signed off; when it is
    # zero and ``reviewed_count`` > 0 the staff member's hours are fully reviewed.
    pending_review_count: int = 0
    reviewed_count: int = 0


class AttendanceSummary(BaseModel):
    total_staff: int
    total_worked_hours: Decimal
    total_expected_hours: Decimal
    clocked_in_count: int
    pending_review_count: int = 0  # completed shifts awaiting sign-off across all staff


class AttendanceResponse(BaseModel):
    items: list[AttendanceRow]
    total: int
    summary: AttendanceSummary
    date_from: str  # ISO date
    date_to: str    # ISO date


# --- Attendance drill-in (per-staff shift list + review/approve for payroll) ---
#
# Backs the expandable row on the Attendance tab. Lists every clock shift a
# staff member worked in the range so an admin can review the raw hours and
# sign them off ("approve") before they flow into the timesheet / pay run.
# Review state is stored per shift on ``TimeClockEntry.flags`` (``reviewed`` /
# ``reviewed_by`` / ``reviewed_at``) — the same JSONB container that already
# holds ``flagged_for_review``.


class AttendanceShift(BaseModel):
    id: UUID
    work_date: str                       # org-local YYYY-MM-DD of clock-in
    clock_in_at: datetime
    clock_out_at: datetime | None = None
    worked_hours: Decimal | None = None  # null while still clocked in
    branch_name: str | None = None
    source: str
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    is_open: bool = False                # not yet clocked out
    reviewed: bool = False               # signed off for payroll
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    flagged_for_review: bool = False     # follow-up marker (G10)
    review_reason: str | None = None


class AttendanceDetailResponse(BaseModel):
    staff_id: UUID
    staff_name: str
    position: str | None = None
    date_from: str
    date_to: str
    worked_hours: Decimal
    expected_hours: Decimal | None = None
    expected_source: str = "none"
    variance_hours: Decimal | None = None
    shifts: list[AttendanceShift] = Field(default_factory=list)
    pending_review_count: int = 0
    reviewed_count: int = 0


class ShiftReviewRequest(BaseModel):
    """Toggle the payroll sign-off (``reviewed``) on a single clock shift."""

    reviewed: bool = True


class ShiftReviewResponse(BaseModel):
    id: UUID
    reviewed: bool
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None


class AttendanceReviewAllResponse(BaseModel):
    affected_count: int
    pending_review_count: int
