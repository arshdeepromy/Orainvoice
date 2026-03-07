"""Pydantic schemas for Job Card module.

Requirements: 59.1, 59.2, 59.5
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class JobCardItemType(str, Enum):
    service = "service"
    part = "part"
    labour = "labour"


class JobCardStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    completed = "completed"
    invoiced = "invoiced"


class JobCardItemCreate(BaseModel):
    """Schema for creating a single job card line item."""

    item_type: JobCardItemType
    description: str = Field(..., min_length=1, max_length=500)
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal = Field(..., ge=0)
    is_gst_exempt: bool = False
    sort_order: int = 0


class JobCardCreate(BaseModel):
    """Request body for POST /api/v1/job-cards."""

    customer_id: uuid.UUID
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    description: str | None = None
    notes: str | None = None
    line_items: list[JobCardItemCreate] = Field(default_factory=list)


class JobCardUpdate(BaseModel):
    """Request body for PUT /api/v1/job-cards/{id}."""

    customer_id: uuid.UUID | None = None
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    status: JobCardStatus | None = None
    description: str | None = None
    notes: str | None = None
    line_items: list[JobCardItemCreate] | None = None


class JobCardItemResponse(BaseModel):
    """Response schema for a single job card line item."""

    id: uuid.UUID
    item_type: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    is_completed: bool
    line_total: Decimal
    sort_order: int


class JobCardResponse(BaseModel):
    """Response schema for a job card."""

    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    vehicle_rego: str | None = None
    status: str
    description: str | None = None
    notes: str | None = None
    line_items: list[JobCardItemResponse] = Field(default_factory=list)
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class JobCardCreateResponse(BaseModel):
    """Wrapper response for job card creation."""

    job_card: JobCardResponse
    message: str


class JobCardSearchResult(BaseModel):
    """Lightweight job card for list views."""

    id: uuid.UUID
    customer_name: str | None = None
    vehicle_rego: str | None = None
    status: str
    description: str | None = None
    created_at: datetime


class JobCardListResponse(BaseModel):
    """Paginated list of job cards."""

    job_cards: list[JobCardSearchResult]
    total: int
    limit: int
    offset: int

class JobCardConvertResponse(BaseModel):
    """Response after converting a job card to a draft invoice.

    Requirements: 59.3
    """

    job_card_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_status: str
    message: str


class JobCardCombineRequest(BaseModel):
    """Request body for combining multiple job cards into a single invoice.

    Requirements: 59.4
    """

    job_card_ids: list[uuid.UUID] = Field(..., min_length=1)


class JobCardCombineResponse(BaseModel):
    """Response after combining multiple job cards into a single invoice.

    Requirements: 59.4
    """

    job_card_ids: list[uuid.UUID]
    invoice_id: uuid.UUID
    invoice_status: str
    message: str
