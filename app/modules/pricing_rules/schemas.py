"""Pydantic v2 schemas for pricing rule CRUD.

**Validates: Requirement 10.1, 10.2, 10.5**
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


VALID_RULE_TYPES = {"customer_specific", "volume", "date_based", "trade_category"}


class PricingRuleCreate(BaseModel):
    product_id: UUID | None = None
    rule_type: str = Field(..., pattern=r"^(customer_specific|volume|date_based|trade_category)$")
    priority: int = Field(default=0, ge=0)
    customer_id: UUID | None = None
    customer_tag: str | None = None
    min_quantity: Decimal | None = None
    max_quantity: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    price_override: Decimal | None = None
    discount_percent: Decimal | None = Field(None, ge=0, le=100)

    @model_validator(mode="after")
    def _validate_rule_fields(self) -> "PricingRuleCreate":
        if self.price_override is None and self.discount_percent is None:
            raise ValueError("Either price_override or discount_percent is required")
        if self.rule_type == "customer_specific" and self.customer_id is None:
            raise ValueError("customer_id is required for customer_specific rules")
        if self.rule_type == "volume":
            if self.min_quantity is None and self.max_quantity is None:
                raise ValueError("min_quantity or max_quantity required for volume rules")
        if self.rule_type == "date_based":
            if self.start_date is None and self.end_date is None:
                raise ValueError("start_date or end_date required for date_based rules")
        return self


class PricingRuleUpdate(BaseModel):
    product_id: UUID | None = None
    rule_type: str | None = Field(None, pattern=r"^(customer_specific|volume|date_based|trade_category)$")
    priority: int | None = Field(None, ge=0)
    customer_id: UUID | None = None
    customer_tag: str | None = None
    min_quantity: Decimal | None = None
    max_quantity: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    price_override: Decimal | None = None
    discount_percent: Decimal | None = Field(None, ge=0, le=100)
    is_active: bool | None = None


class PricingRuleResponse(BaseModel):
    id: UUID
    org_id: UUID
    product_id: UUID | None = None
    rule_type: str
    priority: int
    customer_id: UUID | None = None
    customer_tag: str | None = None
    min_quantity: Decimal | None = None
    max_quantity: Decimal | None = None
    start_date: date | None = None
    end_date: date | None = None
    price_override: Decimal | None = None
    discount_percent: Decimal | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PricingRuleListResponse(BaseModel):
    rules: list[PricingRuleResponse]
    total: int


class EvaluatedPrice(BaseModel):
    """Result of pricing rule evaluation."""
    price: Decimal
    rule_id: UUID | None = None
    rule_type: str | None = None
    is_base_price: bool = False


class ConflictWarning(BaseModel):
    """Warning about overlapping pricing rules."""
    existing_rule_id: UUID
    conflict_description: str
