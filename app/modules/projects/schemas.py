"""Pydantic v2 schemas for project CRUD, profitability, and activity feed.

**Validates: Requirement 14.1 (Project Module)**
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Project CRUD schemas
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    customer_id: UUID | None = None
    description: str | None = None
    budget_amount: Decimal | None = None
    contract_value: Decimal | None = None
    revised_contract_value: Decimal | None = None
    retention_percentage: Decimal = Decimal("0")
    start_date: date | None = None
    target_end_date: date | None = None
    status: str = "active"


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    customer_id: UUID | None = None
    description: str | None = None
    budget_amount: Decimal | None = None
    contract_value: Decimal | None = None
    revised_contract_value: Decimal | None = None
    retention_percentage: Decimal | None = None
    start_date: date | None = None
    target_end_date: date | None = None
    status: str | None = None


class ProjectResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    customer_id: UUID | None = None
    description: str | None = None
    budget_amount: Decimal | None = None
    contract_value: Decimal | None = None
    revised_contract_value: Decimal | None = None
    retention_percentage: Decimal = Decimal("0")
    start_date: date | None = None
    target_end_date: date | None = None
    status: str
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int
    page: int = 1
    page_size: int = 50


# ---------------------------------------------------------------------------
# Profitability schemas
# ---------------------------------------------------------------------------

class ProfitabilityResponse(BaseModel):
    project_id: UUID
    revenue: Decimal = Decimal("0")
    expense_costs: Decimal = Decimal("0")
    labour_costs: Decimal = Decimal("0")
    total_costs: Decimal = Decimal("0")
    profit: Decimal = Decimal("0")
    margin_percentage: Decimal | None = None


# ---------------------------------------------------------------------------
# Progress schemas
# ---------------------------------------------------------------------------

class ProgressResponse(BaseModel):
    project_id: UUID
    contract_value: Decimal | None = None
    invoiced_amount: Decimal = Decimal("0")
    progress_percentage: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Activity feed schemas
# ---------------------------------------------------------------------------

class ActivityItem(BaseModel):
    entity_type: str  # "job", "quote", "invoice", "time_entry"
    entity_id: UUID
    title: str
    status: str | None = None
    created_at: datetime


class ActivityFeedResponse(BaseModel):
    project_id: UUID
    items: list[ActivityItem]
    total: int
