"""Pydantic v2 schemas for retention release CRUD.

**Validates: Requirement — Retention Module**
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class RetentionReleaseCreate(BaseModel):
    amount: Decimal = Field(..., gt=0)
    release_date: date
    payment_id: UUID | None = None
    notes: str | None = None


class RetentionReleaseResponse(BaseModel):
    id: UUID
    project_id: UUID
    amount: Decimal
    release_date: date
    payment_id: UUID | None = None
    notes: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RetentionSummary(BaseModel):
    project_id: UUID
    total_retention_withheld: Decimal
    total_retention_released: Decimal
    retention_balance: Decimal
    releases: list[RetentionReleaseResponse]
