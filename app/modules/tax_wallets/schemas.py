"""Pydantic schemas for the tax wallets module.

Requirements: 20.1, 22.1, 22.2, 23.1, 23.2
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TaxWalletResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    wallet_type: str
    balance: Decimal
    target_balance: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaxWalletListResponse(BaseModel):
    items: list[TaxWalletResponse]
    total: int


class WalletTransactionResponse(BaseModel):
    id: uuid.UUID
    wallet_id: uuid.UUID
    amount: Decimal
    transaction_type: str
    source_payment_id: uuid.UUID | None = None
    description: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WalletTransactionListResponse(BaseModel):
    items: list[WalletTransactionResponse]
    total: int


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class WalletDepositRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Deposit amount (must be positive)")
    description: str | None = Field(None, max_length=200)


class WalletWithdrawRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Withdrawal amount (must be positive)")
    description: str | None = Field(None, max_length=200)


# ---------------------------------------------------------------------------
# Summary / dashboard schemas
# ---------------------------------------------------------------------------


class WalletTrafficLight(BaseModel):
    wallet_type: str
    balance: Decimal
    obligation: Decimal
    shortfall: Decimal
    traffic_light: str  # "green" | "amber" | "red"
    next_due: date | None = None


class TaxWalletSummaryResponse(BaseModel):
    currency: str = "NZD"
    wallets: list[WalletTrafficLight]
    gst_wallet_balance: Decimal
    gst_owing: Decimal
    gst_shortfall: Decimal
    income_tax_wallet_balance: Decimal
    income_tax_estimate: Decimal
    income_tax_shortfall: Decimal
    next_gst_due: date | None = None
    next_income_tax_due: date | None = None
