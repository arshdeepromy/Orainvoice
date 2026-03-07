"""Pydantic v2 schemas for job CRUD, status change, attachment upload, and templates.

**Validates: Requirement 11.1, 11.2, 11.3, 11.5, 11.7**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Job statuses and valid transitions
# ---------------------------------------------------------------------------

JOB_STATUSES = [
    "draft", "scheduled", "in_progress", "on_hold",
    "completed", "invoiced", "cancelled",
]

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["scheduled", "cancelled"],
    "scheduled": ["in_progress", "cancelled"],
    "in_progress": ["on_hold", "completed", "cancelled"],
    "on_hold": ["in_progress", "cancelled"],
    "completed": ["invoiced", "cancelled"],
    "invoiced": ["cancelled"],
    "cancelled": [],
}


# ---------------------------------------------------------------------------
# Staff assignment schemas
# ---------------------------------------------------------------------------

class JobStaffAssignmentCreate(BaseModel):
    user_id: UUID
    role: str = "assigned"


class JobStaffAssignmentResponse(BaseModel):
    id: UUID
    job_id: UUID
    user_id: UUID
    role: str
    assigned_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Attachment schemas
# ---------------------------------------------------------------------------

class JobAttachmentCreate(BaseModel):
    file_key: str = Field(..., min_length=1, max_length=500)
    file_name: str = Field(..., min_length=1, max_length=255)
    file_size: int = Field(..., gt=0)
    content_type: str | None = None


class JobAttachmentResponse(BaseModel):
    id: UUID
    job_id: UUID
    file_key: str
    file_name: str
    file_size: int
    content_type: str | None = None
    uploaded_by: UUID | None = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Status change schemas
# ---------------------------------------------------------------------------

class JobStatusChange(BaseModel):
    status: str = Field(..., description="Target status")
    notes: str | None = None


class JobStatusHistoryResponse(BaseModel):
    id: UUID
    job_id: UUID
    from_status: str | None = None
    to_status: str
    changed_by: UUID | None = None
    changed_at: datetime
    notes: str | None = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Job CRUD schemas
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    customer_id: UUID | None = None
    location_id: UUID | None = None
    project_id: UUID | None = None
    template_id: UUID | None = None
    description: str | None = None
    priority: str = "normal"
    site_address: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    checklist: list[dict] = Field(default_factory=list)
    internal_notes: str | None = None
    customer_notes: str | None = None


class JobUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    customer_id: UUID | None = None
    location_id: UUID | None = None
    project_id: UUID | None = None
    description: str | None = None
    priority: str | None = None
    site_address: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    checklist: list[dict] | None = None
    internal_notes: str | None = None
    customer_notes: str | None = None


class JobResponse(BaseModel):
    id: UUID
    org_id: UUID
    customer_id: UUID | None = None
    location_id: UUID | None = None
    project_id: UUID | None = None
    template_id: UUID | None = None
    converted_invoice_id: UUID | None = None
    job_number: str
    title: str
    description: str | None = None
    status: str
    priority: str
    site_address: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    checklist: list[dict] = Field(default_factory=list)
    internal_notes: str | None = None
    customer_notes: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    staff_assignments: list[JobStaffAssignmentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# Job template schemas
# ---------------------------------------------------------------------------

class JobTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    trade_category_slug: str | None = None
    description: str | None = None
    checklist: list[dict] = Field(default_factory=list)
    default_line_items: list[dict] = Field(default_factory=list)


class JobTemplateUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    trade_category_slug: str | None = None
    description: str | None = None
    checklist: list[dict] | None = None
    default_line_items: list[dict] | None = None
    is_active: bool | None = None


class JobTemplateResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    trade_category_slug: str | None = None
    description: str | None = None
    checklist: list[dict] = Field(default_factory=list)
    default_line_items: list[dict] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobTemplateListResponse(BaseModel):
    templates: list[JobTemplateResponse]
    total: int


# ---------------------------------------------------------------------------
# Convert to invoice schema
# ---------------------------------------------------------------------------

class ConvertToInvoiceRequest(BaseModel):
    """Optional overrides when converting a job to an invoice."""
    time_entries: list[dict] = Field(default_factory=list, description="Time entries as Labour items")
    expenses: list[dict] = Field(default_factory=list, description="Expenses as pass-through items")
    materials: list[dict] = Field(default_factory=list, description="Materials as Product items")


class ConvertToInvoiceResponse(BaseModel):
    job_id: UUID
    invoice_id: UUID
    line_items_count: int
    message: str
