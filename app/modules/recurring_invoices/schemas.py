"""Pydantic v2 schemas for the recurring invoices module.

**Validates: Recurring Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LineItemSchema(BaseModel):
    """A single line item within a recurring schedule template."""
    description: str
    quantity: Decimal = Field(default=Decimal("1"), ge=0)
    unit_price: Decimal = Field(ge=0)
    tax_rate: Decimal | None = None


class RecurringScheduleCreate(BaseModel):
    """Payload to create a new recurring schedule."""
    customer_id: uuid.UUID
    line_items: list[LineItemSchema] = Field(min_length=1)
    frequency: Literal["weekly", "fortnightly", "monthly", "quarterly", "annually"]
    start_date: date
    end_date: date | None = None
    next_generation_date: date | None = None
    auto_issue: bool = False
    auto_email: bool = False


class RecurringScheduleUpdate(BaseModel):
    """Payload to update an existing recurring schedule."""
    customer_id: uuid.UUID | None = None
    line_items: list[LineItemSchema] | None = None
    frequency: Literal["weekly", "fortnightly", "monthly", "quarterly", "annually"] | None = None
    start_date: date | None = None
    end_date: date | None = None
    next_generation_date: date | None = None
    auto_issue: bool | None = None
    auto_email: bool | None = None
    status: Literal["active", "paused", "completed", "cancelled"] | None = None


class RecurringScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    line_items: list[dict]
    frequency: str
    start_date: date
    end_date: date | None = None
    next_generation_date: date
    auto_issue: bool
    auto_email: bool
    status: str
    created_at: datetime
    updated_at: datetime


class RecurringScheduleListResponse(BaseModel):
    schedules: list[RecurringScheduleResponse]
    total: int


class RecurringDashboardResponse(BaseModel):
    """Dashboard summary for recurring schedules."""
    active_count: int
    paused_count: int
    due_today: int
    due_this_week: int
