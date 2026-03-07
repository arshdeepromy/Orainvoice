"""Pydantic v2 schemas for progress claim CRUD.

**Validates: Requirement — ProgressClaim Module**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ProgressClaimCreate(BaseModel):
    project_id: UUID
    contract_value: Decimal = Field(..., gt=0)
    variations_to_date: Decimal = Decimal("0")
    work_completed_to_date: Decimal = Field(..., ge=0)
    work_completed_previous: Decimal = Decimal("0")
    materials_on_site: Decimal = Decimal("0")
    retention_withheld: Decimal = Decimal("0")


class ProgressClaimUpdate(BaseModel):
    contract_value: Decimal | None = Field(None, gt=0)
    variations_to_date: Decimal | None = None
    work_completed_to_date: Decimal | None = Field(None, ge=0)
    work_completed_previous: Decimal | None = None
    materials_on_site: Decimal | None = None
    retention_withheld: Decimal | None = None


class ProgressClaimResponse(BaseModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    claim_number: int
    contract_value: Decimal
    variations_to_date: Decimal
    revised_contract_value: Decimal
    work_completed_to_date: Decimal
    work_completed_previous: Decimal
    work_completed_this_period: Decimal
    materials_on_site: Decimal
    retention_withheld: Decimal
    amount_due: Decimal
    completion_percentage: Decimal
    status: str
    invoice_id: UUID | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProgressClaimListResponse(BaseModel):
    claims: list[ProgressClaimResponse]
    total: int
    page: int = 1
    page_size: int = 50
