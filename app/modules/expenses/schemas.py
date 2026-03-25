"""Pydantic v2 schemas for expense CRUD, mileage, and summary reports."""

from __future__ import annotations

from datetime import date as _date_type, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class ExpenseCreate(BaseModel):
    job_id: UUID | None = None
    project_id: UUID | None = None
    customer_id: UUID | None = None
    date: _date_type
    description: str = Field(..., min_length=1)
    amount: Decimal = Field(..., gt=0)
    tax_amount: Decimal = Decimal("0")
    category: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    receipt_file_key: str | None = None
    is_pass_through: bool = False
    is_billable: bool = False
    tax_inclusive: bool = False
    expense_type: str = "expense"


class ExpenseUpdate(BaseModel):
    job_id: UUID | None = None
    project_id: UUID | None = None
    customer_id: UUID | None = None
    date: _date_type | None = None
    description: str | None = Field(None, min_length=1)
    amount: Decimal | None = Field(None, gt=0)
    tax_amount: Decimal | None = None
    category: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    receipt_file_key: str | None = None
    is_pass_through: bool | None = None
    is_billable: bool | None = None
    tax_inclusive: bool | None = None


class ExpenseResponse(BaseModel):
    id: UUID
    org_id: UUID
    job_id: UUID | None = None
    project_id: UUID | None = None
    invoice_id: UUID | None = None
    customer_id: UUID | None = None
    date: _date_type
    description: str
    amount: Decimal
    tax_amount: Decimal = Decimal("0")
    category: str | None = None
    reference_number: str | None = None
    notes: str | None = None
    receipt_file_key: str | None = None
    is_pass_through: bool = False
    is_billable: bool = False
    is_invoiced: bool = False
    tax_inclusive: bool = False
    expense_type: str = "expense"
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExpenseListResponse(BaseModel):
    expenses: list[ExpenseResponse]
    total: int
    page: int = 1
    page_size: int = 50


class BulkExpenseCreate(BaseModel):
    expenses: list[ExpenseCreate]


class CategorySummary(BaseModel):
    category: str | None = None
    total_amount: Decimal = Decimal("0")
    count: int = 0


class ProjectSummary(BaseModel):
    project_id: UUID | None = None
    total_amount: Decimal = Decimal("0")
    count: int = 0


class JobSummary(BaseModel):
    job_id: UUID | None = None
    total_amount: Decimal = Decimal("0")
    count: int = 0


class ExpenseSummaryReport(BaseModel):
    total_amount: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")
    total_count: int = 0
    by_category: list[CategorySummary] = Field(default_factory=list)
    by_project: list[ProjectSummary] = Field(default_factory=list)
    by_job: list[JobSummary] = Field(default_factory=list)


class IncludeInInvoiceRequest(BaseModel):
    expense_ids: list[UUID]
    invoice_id: UUID


# Mileage schemas
class MileageRateCreate(BaseModel):
    start_date: _date_type | None = None
    rate_per_unit: Decimal = Field(..., gt=0)
    currency: str = "NZD"


class MileageRateResponse(BaseModel):
    id: UUID
    org_id: UUID
    start_date: _date_type | None = None
    rate_per_unit: Decimal
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MileagePreferenceUpdate(BaseModel):
    default_unit: str | None = None  # "km" or "mile"
    default_account: str | None = None
    rates: list[MileageRateCreate] = Field(default_factory=list)


class MileagePreferenceResponse(BaseModel):
    default_unit: str
    default_account: str | None = None
    rates: list[MileageRateResponse] = Field(default_factory=list)
