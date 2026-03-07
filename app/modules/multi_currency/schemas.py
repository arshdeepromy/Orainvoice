"""Pydantic v2 schemas for multi-currency module CRUD.

**Validates: Requirement — MultiCurrency Module**
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class EnableCurrencyRequest(BaseModel):
    currency_code: str = Field(..., min_length=3, max_length=3)
    is_base: bool = False


class OrgCurrencyResponse(BaseModel):
    id: UUID
    org_id: UUID
    currency_code: str
    is_base: bool
    enabled: bool

    model_config = {"from_attributes": True}


class ExchangeRateCreate(BaseModel):
    base_currency: str = Field(..., min_length=3, max_length=3)
    target_currency: str = Field(..., min_length=3, max_length=3)
    rate: Decimal = Field(..., gt=0)
    effective_date: date


class ExchangeRateResponse(BaseModel):
    id: UUID
    base_currency: str
    target_currency: str
    rate: Decimal
    source: str
    effective_date: date
    created_at: datetime

    model_config = {"from_attributes": True}


class ExchangeGainLoss(BaseModel):
    """Result of an exchange gain/loss calculation."""
    invoice_currency: str
    base_currency: str
    invoice_rate: Decimal
    payment_rate: Decimal
    invoice_amount: Decimal
    base_amount_at_invoice: Decimal
    base_amount_at_payment: Decimal
    gain_loss: Decimal


class CurrencyFormat(BaseModel):
    """ISO 4217 currency formatting info."""
    code: str
    symbol: str
    decimal_places: int
    symbol_position: str  # "before" or "after"
    thousands_separator: str
    decimal_separator: str


class ConvertedAmount(BaseModel):
    """Result of a currency conversion."""
    original_amount: Decimal
    original_currency: str
    converted_amount: Decimal
    target_currency: str
    rate: Decimal
    effective_date: date
