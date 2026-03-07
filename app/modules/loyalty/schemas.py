"""Pydantic v2 schemas for the loyalty and memberships module.

**Validates: Requirement 38 — Loyalty Module**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# --- Config ---

class LoyaltyConfigUpdate(BaseModel):
    earn_rate: Decimal = Field(ge=0, default=Decimal("1.0"))
    redemption_rate: Decimal = Field(gt=0, default=Decimal("0.01"))
    is_active: bool = True


class LoyaltyConfigResponse(BaseModel):
    id: UUID
    org_id: UUID
    earn_rate: Decimal
    redemption_rate: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Tiers ---

class LoyaltyTierCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    threshold_points: int = Field(..., ge=0)
    discount_percent: Decimal = Field(ge=0, le=100, default=Decimal("0"))
    benefits: dict = Field(default_factory=dict)
    display_order: int = 0


class LoyaltyTierResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    threshold_points: int
    discount_percent: Decimal
    benefits: dict
    display_order: int

    model_config = {"from_attributes": True}


# --- Transactions / Balance ---

class LoyaltyTransactionResponse(BaseModel):
    id: UUID
    org_id: UUID
    customer_id: UUID
    transaction_type: str
    points: int
    balance_after: int
    reference_type: str | None = None
    reference_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerBalanceResponse(BaseModel):
    customer_id: UUID
    total_points: int
    current_tier: LoyaltyTierResponse | None = None
    next_tier: LoyaltyTierResponse | None = None
    points_to_next_tier: int | None = None
    transactions: list[LoyaltyTransactionResponse] = []


# --- Redeem ---

class RedeemPointsRequest(BaseModel):
    customer_id: UUID
    points: int = Field(..., gt=0)
    reference_type: str | None = None
    reference_id: UUID | None = None
