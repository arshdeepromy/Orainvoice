"""Pydantic v2 schemas for staff CRUD, location assignment, and reporting.

**Validates: Requirement — Staff Module**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Staff member schemas
# ------------------------------------------------------------------

class StaffMemberCreate(BaseModel):
    user_id: UUID | None = None
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    position: str | None = None
    reporting_to: UUID | None = None
    shift_start: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    shift_end: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    role_type: str = Field(default="employee", pattern="^(employee|contractor)$")
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    availability_schedule: dict = Field(default_factory=dict)
    skills: list[str] = Field(default_factory=list)


class StaffMemberUpdate(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    position: str | None = None
    reporting_to: UUID | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    role_type: str | None = Field(None, pattern="^(employee|contractor)$")
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    is_active: bool | None = None
    availability_schedule: dict | None = None
    skills: list[str] | None = None


class LocationAssignmentResponse(BaseModel):
    id: UUID
    staff_id: UUID
    location_id: UUID
    assigned_at: datetime

    model_config = {"from_attributes": True}


class StaffMemberResponse(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID | None = None
    name: str
    first_name: str
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    employee_id: str | None = None
    position: str | None = None
    reporting_to: UUID | None = None
    reporting_to_name: str | None = None
    shift_start: str | None = None
    shift_end: str | None = None
    role_type: str
    hourly_rate: Decimal | None = None
    overtime_rate: Decimal | None = None
    is_active: bool
    availability_schedule: dict = Field(default_factory=dict)
    skills: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    location_assignments: list[LocationAssignmentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class StaffMemberListResponse(BaseModel):
    staff: list[StaffMemberResponse]
    total: int
    page: int = 1
    page_size: int = 50


class AssignToLocationRequest(BaseModel):
    location_id: UUID


class CreateStaffAccountRequest(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)


class UtilisationReport(BaseModel):
    staff_id: UUID
    staff_name: str
    billable_minutes: int = 0
    total_minutes: int = 0
    available_minutes: int = 0
    utilisation_percent: Decimal = Decimal("0")


class UtilisationReportResponse(BaseModel):
    staff: list[UtilisationReport]
    date_from: str
    date_to: str


class LabourCostEntry(BaseModel):
    staff_id: UUID
    staff_name: str
    total_minutes: int = 0
    hourly_rate: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")


class LabourCostResponse(BaseModel):
    entries: list[LabourCostEntry]
    total_cost: Decimal = Decimal("0")
    date_from: str
    date_to: str
