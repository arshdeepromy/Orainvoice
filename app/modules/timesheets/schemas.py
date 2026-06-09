"""Pydantic request/response schemas for the staff timesheets module.

All list responses use the ``{items, total}`` convention per safe-api-consumption.md.
Decimal fields represent hours (minutes / 60, rounded 2dp).
"""
from __future__ import annotations

from datetime import datetime
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


class TimesheetSettingsUpdate(BaseModel):
    clock_rounding_minutes: int | None = Field(None, ge=1, le=30)
    clock_rounding_direction: Literal["nearest", "up", "down"] | None = None
    early_grace_minutes: int | None = Field(None, ge=0)
    late_grace_minutes: int | None = Field(None, ge=0)
    match_policy: Literal["pay_actual", "round_to_roster", "actual_rounded"] | None = None
    auto_approve_threshold_minutes: int | None = Field(None, ge=0)
    require_approval_before_lock: bool | None = None


class TimesheetSettingsResponse(BaseModel):
    org_default: TimesheetSettingsRead | None = None
    branch_overrides: list[TimesheetSettingsRead] = Field(default_factory=list)


class BulkActionResponse(BaseModel):
    affected_count: int
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)
