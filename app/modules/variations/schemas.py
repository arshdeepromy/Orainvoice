"""Pydantic v2 schemas for variation order CRUD.

**Validates: Requirement 29 — Variation Module**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class VariationOrderCreate(BaseModel):
    project_id: UUID
    description: str = Field(..., min_length=1)
    cost_impact: Decimal


class VariationOrderUpdate(BaseModel):
    description: str | None = Field(None, min_length=1)
    cost_impact: Decimal | None = None


class VariationOrderResponse(BaseModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    variation_number: int
    description: str
    cost_impact: Decimal
    status: str
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VariationOrderListResponse(BaseModel):
    variations: list[VariationOrderResponse]
    total: int
    page: int = 1
    page_size: int = 50
