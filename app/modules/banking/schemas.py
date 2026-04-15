"""Pydantic v2 schemas for the banking module.

Covers Akahu connections, bank accounts, bank transactions,
reconciliation matching, and summary responses.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Akahu Connection schemas
# ---------------------------------------------------------------------------


class AkahuConnectionResponse(BaseModel):
    """Akahu connection with masked tokens — raw tokens never exposed."""

    id: uuid.UUID
    org_id: uuid.UUID
    access_token_masked: str | None = None
    token_expires_at: datetime | None = None
    is_active: bool
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Bank Account schemas
# ---------------------------------------------------------------------------


class BankAccountResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    akahu_account_id: str
    account_name: str
    account_number: str | None = None
    bank_name: str | None = None
    account_type: str | None = None
    balance: Decimal
    currency: str
    is_active: bool
    last_refreshed_at: datetime | None = None
    linked_gl_account_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankAccountListResponse(BaseModel):
    items: list[BankAccountResponse]
    total: int


class BankAccountLinkRequest(BaseModel):
    """Link a bank account to a GL account for reconciliation posting."""

    linked_gl_account_id: uuid.UUID


# ---------------------------------------------------------------------------
# Bank Transaction schemas
# ---------------------------------------------------------------------------


class BankTransactionResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bank_account_id: uuid.UUID
    akahu_transaction_id: str
    date: date
    description: str
    amount: Decimal
    balance: Decimal | None = None
    merchant_name: str | None = None
    category: str | None = None
    reconciliation_status: str
    matched_invoice_id: uuid.UUID | None = None
    matched_expense_id: uuid.UUID | None = None
    matched_journal_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BankTransactionListResponse(BaseModel):
    items: list[BankTransactionResponse]
    total: int


class BankTransactionMatchRequest(BaseModel):
    """Manually match a transaction to an invoice, expense, or journal entry."""

    matched_invoice_id: uuid.UUID | None = None
    matched_expense_id: uuid.UUID | None = None
    matched_journal_id: uuid.UUID | None = None


# ---------------------------------------------------------------------------
# Reconciliation Summary schemas
# ---------------------------------------------------------------------------


class ReconciliationSummaryResponse(BaseModel):
    """Match counts by status + last sync timestamp."""

    unmatched: int = 0
    matched: int = 0
    excluded: int = 0
    manual: int = 0
    total: int = 0
    last_sync_at: datetime | None = None
