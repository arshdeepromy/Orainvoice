"""Pydantic v2 schemas for POS sessions, transactions, and offline sync.

**Validates: Requirement 22 — POS Module**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Session schemas
# ---------------------------------------------------------------------------


class SessionOpenRequest(BaseModel):
    location_id: UUID | None = None
    opening_cash: Decimal = Field(default=Decimal("0"), ge=0)


class SessionCloseRequest(BaseModel):
    session_id: UUID
    closing_cash: Decimal = Field(ge=0)


class SessionResponse(BaseModel):
    id: UUID
    org_id: UUID
    location_id: UUID | None = None
    user_id: UUID
    opened_at: datetime
    closed_at: datetime | None = None
    opening_cash: Decimal
    closing_cash: Decimal | None = None
    status: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Transaction line item
# ---------------------------------------------------------------------------


class TransactionLineItem(BaseModel):
    product_id: UUID
    product_name: str
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)


# ---------------------------------------------------------------------------
# Transaction schemas
# ---------------------------------------------------------------------------


class TransactionCreateRequest(BaseModel):
    session_id: UUID | None = None
    customer_id: UUID | None = None
    table_id: UUID | None = None
    payment_method: str = Field(pattern="^(cash|card|split)$")
    line_items: list[TransactionLineItem] = Field(min_length=1)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    tip_amount: Decimal = Field(default=Decimal("0"), ge=0)
    cash_tendered: Decimal | None = None


class TransactionResponse(BaseModel):
    id: UUID
    org_id: UUID
    session_id: UUID | None = None
    invoice_id: UUID | None = None
    customer_id: UUID | None = None
    table_id: UUID | None = None
    offline_transaction_id: str | None = None
    payment_method: str
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    tip_amount: Decimal
    total: Decimal
    cash_tendered: Decimal | None = None
    change_given: Decimal | None = None
    is_offline_sync: bool
    sync_status: str | None = None
    sync_conflicts: dict | None = None
    created_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Offline sync schemas
# ---------------------------------------------------------------------------


class OfflineTransactionItem(BaseModel):
    product_id: UUID
    product_name: str
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0)


class OfflineTransaction(BaseModel):
    offline_id: str
    timestamp: datetime
    customer_id: UUID | None = None
    payment_method: str = Field(pattern="^(cash|card|split)$")
    line_items: list[OfflineTransactionItem] = Field(min_length=1)
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    tip_amount: Decimal = Field(default=Decimal("0"), ge=0)
    total: Decimal
    cash_tendered: Decimal | None = None
    change_given: Decimal | None = None


class OfflineSyncRequest(BaseModel):
    transactions: list[OfflineTransaction] = Field(min_length=1)


class SyncConflictDetail(BaseModel):
    type: str
    product_id: UUID | None = None
    detail: str = ""


class SyncResultItem(BaseModel):
    offline_id: str
    status: str  # "success", "conflict", "failed"
    invoice_id: UUID | None = None
    transaction_id: UUID | None = None
    conflicts: list[SyncConflictDetail] = Field(default_factory=list)
    error: str | None = None


class SyncReport(BaseModel):
    total: int
    successes: int
    conflicts: int
    failures: int
    results: list[SyncResultItem]


class SyncStatusResponse(BaseModel):
    pending_count: int
    synced_count: int
    conflict_count: int
    failed_count: int
