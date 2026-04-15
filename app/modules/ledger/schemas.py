"""Pydantic v2 schemas for the double-entry general ledger module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Account schemas
# ---------------------------------------------------------------------------


class AccountCreate(BaseModel):
    code: str
    name: str
    account_type: str
    sub_type: str | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    tax_code: str | None = None
    xero_account_code: str | None = None


class AccountUpdate(BaseModel):
    name: str | None = None
    sub_type: str | None = None
    description: str | None = None
    is_active: bool | None = None
    parent_id: uuid.UUID | None = None
    tax_code: str | None = None
    xero_account_code: str | None = None


class AccountResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    code: str
    name: str
    account_type: str
    sub_type: str | None = None
    description: str | None = None
    is_system: bool
    is_active: bool
    parent_id: uuid.UUID | None = None
    tax_code: str | None = None
    xero_account_code: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    total: int


# ---------------------------------------------------------------------------
# Journal Line schemas
# ---------------------------------------------------------------------------


class JournalLineCreate(BaseModel):
    account_id: uuid.UUID
    debit: Decimal
    credit: Decimal
    description: str | None = None


class JournalLineResponse(BaseModel):
    id: uuid.UUID
    journal_entry_id: uuid.UUID
    org_id: uuid.UUID
    account_id: uuid.UUID
    debit: Decimal
    credit: Decimal
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Journal Entry schemas
# ---------------------------------------------------------------------------


class JournalEntryCreate(BaseModel):
    entry_date: date
    description: str
    reference: str | None = None
    source_type: str = "manual"
    lines: list[JournalLineCreate]


class JournalEntryResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    entry_number: str
    entry_date: date
    description: str
    reference: str | None = None
    source_type: str
    source_id: uuid.UUID | None = None
    period_id: uuid.UUID | None = None
    is_posted: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    lines: list[JournalLineResponse] = []

    model_config = ConfigDict(from_attributes=True)


class JournalEntryListResponse(BaseModel):
    items: list[JournalEntryResponse]
    total: int


# ---------------------------------------------------------------------------
# Accounting Period schemas
# ---------------------------------------------------------------------------


class AccountingPeriodCreate(BaseModel):
    period_name: str
    start_date: date
    end_date: date


class AccountingPeriodResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    period_name: str
    start_date: date
    end_date: date
    is_closed: bool
    closed_by: uuid.UUID | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccountingPeriodListResponse(BaseModel):
    items: list[AccountingPeriodResponse]
    total: int


# ---------------------------------------------------------------------------
# GST Filing Period schemas
# ---------------------------------------------------------------------------


class GstPeriodGenerateRequest(BaseModel):
    period_type: str  # two_monthly, six_monthly, annual
    tax_year: int  # e.g. 2026 means Apr 2025 – Mar 2026


class GstPeriodReadyRequest(BaseModel):
    """Body is empty but kept for forward-compatibility."""
    pass


class GstFilingPeriodResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    period_type: str
    period_start: date
    period_end: date
    due_date: date
    status: str
    filed_at: datetime | None = None
    filed_by: uuid.UUID | None = None
    ird_reference: str | None = None
    return_data: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GstFilingPeriodListResponse(BaseModel):
    items: list[GstFilingPeriodResponse]
    total: int
