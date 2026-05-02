"""Pydantic schemas for Invoice module.

Requirements: 17.1, 17.3, 17.4, 17.5, 17.6
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ItemType(str, Enum):
    service = "service"
    part = "part"
    labour = "labour"


class InvoiceStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    issued = "issued"
    partially_paid = "partially_paid"
    paid = "paid"
    overdue = "overdue"
    voided = "voided"
    refunded = "refunded"
    partially_refunded = "partially_refunded"



class LineItemCreate(BaseModel):
    """Schema for creating a single invoice line item."""

    model_config = {"extra": "ignore"}  # Ignore extra fields from frontend

    item_type: ItemType = ItemType.service  # Default to service
    description: str = Field(..., min_length=1, max_length=2000)
    catalogue_item_id: uuid.UUID | None = None
    stock_item_id: uuid.UUID | None = None
    part_number: str | None = None
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)  # Made optional, can use rate
    rate: Decimal | None = Field(default=None, ge=0)  # Frontend sends this
    hours: Decimal | None = Field(default=None, ge=0)
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    discount_type: str | None = Field(default=None, pattern=r"^(percentage|fixed)$")
    discount_value: Decimal | None = Field(default=None, ge=0)
    is_gst_exempt: bool = False
    gst_inclusive: bool = False
    inclusive_price: Decimal | None = Field(default=None, ge=0)
    warranty_note: str | None = None
    sort_order: int = 0

    @field_validator("discount_type", mode="before")
    @classmethod
    def validate_discount_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("percentage", "fixed"):
            raise ValueError("discount_type must be 'percentage' or 'fixed'")
        return v
    
    def get_unit_price(self) -> Decimal:
        """Get unit price, preferring unit_price over rate."""
        if self.unit_price is not None:
            return self.unit_price
        if self.rate is not None:
            return self.rate
        return Decimal("0")


class VehicleItem(BaseModel):
    """Schema for a vehicle in the vehicles array."""

    model_config = {"extra": "ignore"}  # Frontend sends extra fields like odometer

    id: uuid.UUID | None = None
    rego: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    odometer: int | None = None

    @field_validator("id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class FluidUsageItem(BaseModel):
    """Schema for tracking fluid/oil usage against a vehicle (not invoiced)."""

    model_config = {"extra": "ignore"}

    stock_item_id: uuid.UUID
    catalogue_item_id: uuid.UUID
    litres: Decimal = Field(..., gt=0)
    item_name: str = ""


class InvoiceCreateRequest(BaseModel):
    """Request body for POST /api/v1/invoices."""

    model_config = {"extra": "ignore", "populate_by_name": True}  # Accept both field name and alias

    customer_id: uuid.UUID
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_odometer: int | None = None
    global_vehicle_id: uuid.UUID | None = Field(
        default=None, 
        description="Global vehicle UUID - if provided, auto-links customer to vehicle"
    )
    vehicle_service_due_date: date | None = Field(
        default=None,
        description="Next service due date — saved to the vehicle record"
    )
    vehicle_wof_expiry_date: date | None = Field(
        default=None,
        description="WOF expiry date — saved to the vehicle record"
    )
    vehicles: list[VehicleItem] | None = Field(
        default=None,
        description="List of vehicles associated with this invoice"
    )
    branch_id: uuid.UUID | None = None
    status: InvoiceStatus = InvoiceStatus.draft
    line_items: list[LineItemCreate] = Field(default_factory=list)
    fluid_usage: list[FluidUsageItem] = Field(
        default_factory=list,
        description="Oil/fluid usage to track against vehicle (not invoiced, just stock decrement)"
    )
    notes_internal: str | None = None
    notes_customer: str | None = Field(default=None, alias="customer_notes")
    terms_and_conditions: str | None = None
    issue_date: date | None = Field(default=None, description="Invoice date (defaults to today)")
    due_date: date | None = None
    payment_terms: str | None = Field(default=None, description="Payment terms e.g. due_on_receipt, net_15, net_30")
    discount_type: str | None = Field(default=None, pattern=r"^(percentage|fixed)$")
    discount_value: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="NZD", max_length=3, min_length=3)
    exchange_rate_to_nzd: Decimal | None = Field(default=None, gt=0)
    payment_gateway: str | None = Field(
        default=None,
        description="Payment gateway for this invoice (e.g. 'stripe', 'cash')",
    )

    @field_validator("global_vehicle_id", "branch_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None so Pydantic doesn't reject them as invalid UUIDs."""
        if v == "" or v is None:
            return None
        return v

    @field_validator("discount_type", mode="before")
    @classmethod
    def empty_discount_type_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class LineItemResponse(BaseModel):
    """Response schema for a single line item."""

    id: uuid.UUID
    item_type: str
    description: str
    catalogue_item_id: uuid.UUID | None = None
    stock_item_id: uuid.UUID | None = None
    part_number: str | None = None
    quantity: Decimal
    unit_price: Decimal
    hours: Decimal | None = None
    hourly_rate: Decimal | None = None
    discount_type: str | None = None
    discount_value: Decimal | None = None
    is_gst_exempt: bool
    warranty_note: str | None = None
    line_total: Decimal
    sort_order: int


class CustomerSummary(BaseModel):
    """Embedded customer info in invoice response."""
    id: str
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None
    display_name: str | None = None


class PaymentSummary(BaseModel):
    """Embedded payment info in invoice response."""
    id: str
    date: str | None = None
    amount: float
    method: str = "cash"
    recorded_by: str = ""
    note: str | None = None
    is_refund: bool = False
    refund_note: str | None = None


class CreditNoteSummary(BaseModel):
    """Embedded credit note info in invoice response."""
    id: str
    reference_number: str
    amount: float
    reason: str = ""
    created_at: str | None = None


class InvoiceResponse(BaseModel):
    """Response schema for a created invoice."""

    id: uuid.UUID
    org_id: uuid.UUID
    invoice_number: str | None = None
    customer_id: uuid.UUID
    customer: CustomerSummary | None = None
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_odometer: int | None = None
    branch_id: uuid.UUID | None = None
    status: str
    issue_date: date | None = None
    due_date: date | None = None
    payment_terms: str | None = None
    currency: str
    exchange_rate_to_nzd: Decimal = Decimal("1")
    subtotal: Decimal
    discount_amount: Decimal
    discount_type: str | None = None
    discount_value: Decimal | None = None
    gst_amount: Decimal
    total: Decimal
    total_nzd: Decimal | None = None
    amount_paid: Decimal
    balance_due: Decimal
    notes_internal: str | None = None
    notes_customer: str | None = None
    void_reason: str | None = None
    voided_at: datetime | None = None
    voided_by: uuid.UUID | None = None
    line_items: list[LineItemResponse] = Field(default_factory=list)
    payments: list[PaymentSummary] = Field(default_factory=list)
    credit_notes: list[CreditNoteSummary] = Field(default_factory=list)
    # Organisation details for invoice preview
    org_name: str | None = None
    org_address: str | None = None
    org_address_unit: str | None = None
    org_address_street: str | None = None
    org_address_city: str | None = None
    org_address_state: str | None = None
    org_address_country: str | None = None
    org_address_postcode: str | None = None
    org_phone: str | None = None
    org_email: str | None = None
    org_logo_url: str | None = None
    org_gst_number: str | None = None
    org_website: str | None = None
    invoice_template_id: str | None = None
    invoice_template_colours: dict | None = None
    vehicle: dict | None = None
    additional_vehicles: list[dict] = Field(default_factory=list)
    fluid_usage: list[dict] = Field(default_factory=list)
    payment_page_url: str | None = None
    payment_gateway: str | None = None
    attachment_count: int = 0
    customer_portal_token: str | None = None
    customer_enable_portal: bool = False
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class InvoiceCreateResponse(BaseModel):
    """Wrapper response for invoice creation."""

    invoice: InvoiceResponse
    message: str


class AddLineItemRequest(BaseModel):
    """Request body for adding a line item to an existing invoice."""

    item_type: ItemType
    description: str = Field(default="", max_length=2000)
    catalogue_item_id: uuid.UUID | None = None
    labour_rate_id: uuid.UUID | None = None
    part_number: str | None = None
    quantity: Decimal = Field(default=Decimal("1"), gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    hours: Decimal | None = Field(default=None, ge=0)
    hourly_rate: Decimal | None = Field(default=None, ge=0)
    discount_type: str | None = Field(default=None, pattern=r"^(percentage|fixed)$")
    discount_value: Decimal | None = Field(default=None, ge=0)
    is_gst_exempt: bool = False
    warranty_note: str | None = None
    sort_order: int | None = None

    @field_validator("unit_price", mode="before")
    @classmethod
    def validate_unit_price(cls, v: Decimal | None, info) -> Decimal | None:
        """unit_price can be None when catalogue_item_id or labour_rate_id will fill it."""
        return v


class LineItemModifyResponse(BaseModel):
    """Response after adding or removing a line item."""

    invoice: InvoiceResponse
    message: str


# ---------------------------------------------------------------------------
# Invoice lifecycle schemas (Task 10.3)
# ---------------------------------------------------------------------------


class IssueInvoiceResponse(BaseModel):
    """Response after issuing a draft invoice."""

    invoice: InvoiceResponse
    message: str


class VoidInvoiceRequest(BaseModel):
    """Request body for voiding an invoice."""

    reason: str = Field(..., min_length=1, max_length=1000)


class VoidInvoiceResponse(BaseModel):
    """Response after voiding an invoice."""

    invoice: InvoiceResponse
    message: str


class UpdateNotesRequest(BaseModel):
    """Request body for updating notes on an issued invoice."""

    notes_internal: str | None = None
    notes_customer: str | None = None


class UpdateNotesResponse(BaseModel):
    """Response after updating invoice notes."""

    invoice: InvoiceResponse
    message: str


class GetInvoiceResponse(BaseModel):
    """Response for getting a single invoice."""

    invoice: InvoiceResponse


# ---------------------------------------------------------------------------
# Invoice update schemas (Task 10.4)
# ---------------------------------------------------------------------------


class UpdateInvoiceRequest(BaseModel):
    """Request body for updating a draft invoice.

    invoice_number is explicitly excluded — it is system-assigned
    and immutable once set (Req 23.2).
    """

    model_config = {"extra": "ignore", "populate_by_name": True}

    customer_id: uuid.UUID | None = None
    vehicle_rego: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_year: int | None = None
    vehicle_odometer: int | None = None
    global_vehicle_id: uuid.UUID | None = None
    vehicle_service_due_date: date | None = None
    vehicle_wof_expiry_date: date | None = None
    vehicles: list[VehicleItem] | None = None
    branch_id: uuid.UUID | None = None
    status: InvoiceStatus | None = None
    line_items: list[LineItemCreate] | None = None
    fluid_usage: list[FluidUsageItem] | None = None
    notes_internal: str | None = None
    notes_customer: str | None = Field(default=None, alias="customer_notes")
    terms_and_conditions: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    payment_terms: str | None = None
    discount_type: str | None = Field(default=None, pattern=r"^(percentage|fixed)$")
    discount_value: Decimal | None = Field(default=None, ge=0)
    shipping_charges: Decimal | None = Field(default=None, ge=0)
    adjustment: Decimal | None = None
    payment_gateway: str | None = Field(
        default=None,
        description="Payment gateway for this invoice (e.g. 'stripe', 'cash')",
    )
    currency: str | None = Field(default=None, max_length=3, min_length=3)

    @field_validator("global_vehicle_id", "customer_id", "branch_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None so Pydantic doesn't reject them as invalid UUIDs."""
        if v == "" or v is None:
            return None
        return v

    @field_validator("discount_type", mode="before")
    @classmethod
    def empty_discount_type_to_none(cls, v):
        if v == "" or v is None:
            return None
        return v


class UpdateInvoiceResponse(BaseModel):
    """Response after updating an invoice."""

    invoice: InvoiceResponse
    message: str

# ---------------------------------------------------------------------------
# Credit note schemas (Task 10.5)
# Requirements: 20.1, 20.2, 20.3, 20.4
# ---------------------------------------------------------------------------


class CreditNoteItemCreate(BaseModel):
    """A single item being credited on the credit note."""

    description: str = Field(..., min_length=1, max_length=2000)
    amount: Decimal = Field(..., gt=0)


class CreditNoteCreateRequest(BaseModel):
    """Request body for POST /api/v1/invoices/{id}/credit-note."""

    amount: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=2000)
    items: list[CreditNoteItemCreate] = Field(default_factory=list)
    process_stripe_refund: bool = False


class CreditNoteResponse(BaseModel):
    """Response schema for a credit note."""

    id: uuid.UUID
    org_id: uuid.UUID
    invoice_id: uuid.UUID
    credit_note_number: str
    amount: Decimal
    reason: str
    items: list[dict]
    stripe_refund_id: str | None = None
    created_by: uuid.UUID
    created_at: datetime


class CreditNoteCreateResponse(BaseModel):
    """Wrapper response for credit note creation."""

    credit_note: CreditNoteResponse
    invoice: InvoiceResponse
    stripe_refund_prompted: bool = False
    message: str


class CreditNoteListResponse(BaseModel):
    """Response for listing credit notes for an invoice."""

    credit_notes: list[CreditNoteResponse]
    total_credited: Decimal



# ---------------------------------------------------------------------------
# Invoice search and filtering schemas (Task 10.6)
# Requirements: 21.1, 21.2, 21.3, 21.4
# ---------------------------------------------------------------------------


class InvoiceSearchResult(BaseModel):
    """A single row in the invoice search results list.

    Displays: invoice number, customer name, rego, total, status, issue date.
    Requirements: 21.4, 8.1
    """

    id: uuid.UUID
    invoice_number: str | None = None
    customer_name: str | None = None
    vehicle_rego: str | None = None
    total: Decimal
    status: str
    issue_date: date | None = None
    has_stripe_payment: bool = False
    attachment_count: int = 0


class InvoiceListResponse(BaseModel):
    """Paginated response for GET /api/v1/invoices.

    Requirements: 21.1, 21.2, 21.3, 21.4
    """

    invoices: list[InvoiceSearchResult]
    total: int
    limit: int
    offset: int

# ---------------------------------------------------------------------------
# Invoice duplication schemas (Task 10.7)
# Requirements: 22.1, 22.2
# ---------------------------------------------------------------------------


class DuplicateInvoiceResponse(BaseModel):
    """Response after duplicating an invoice as a new draft.

    Requirements: 22.1, 22.2
    """

    invoice: InvoiceResponse
    message: str

# ---------------------------------------------------------------------------
# NZ Tax Invoice Compliance schemas (Task 10.8)
# Requirements: 80.1, 80.2, 80.3
# ---------------------------------------------------------------------------

NZ_HIGH_VALUE_THRESHOLD = Decimal("1000.00")


class TaxComplianceIssue(BaseModel):
    """A single compliance issue found during validation."""

    field: str
    message: str
    requirement: str  # e.g. "80.1", "80.2"


class TaxComplianceResult(BaseModel):
    """Result of NZ tax invoice compliance validation.

    Requirements: 80.1, 80.2, 80.3
    """

    is_compliant: bool
    is_high_value: bool = False
    issues: list[TaxComplianceIssue] = Field(default_factory=list)
    document_label: str = "Tax Invoice"


class LineItemTaxDetail(BaseModel):
    """Tax detail for a single line item — distinguishes taxable vs GST-exempt.

    Requirements: 80.3
    """

    line_item_id: uuid.UUID
    description: str
    is_gst_exempt: bool
    line_total: Decimal
    gst_amount: Decimal  # 0 if exempt
    tax_label: str  # "GST 15%" or "GST Exempt"


# ---------------------------------------------------------------------------
# Recurring Schedule Schemas (Requirement 60)
# ---------------------------------------------------------------------------


class RecurringFrequency(str, Enum):
    weekly = "weekly"
    fortnightly = "fortnightly"
    monthly = "monthly"
    quarterly = "quarterly"
    annually = "annually"


class RecurringLineItem(BaseModel):
    """Line item template stored in a recurring schedule."""

    item_type: ItemType
    description: str = Field(..., max_length=2000)
    quantity: Decimal = Field(default=Decimal("1"), ge=0)
    unit_price: Decimal = Field(..., ge=0)
    hours: Decimal | None = None
    hourly_rate: Decimal | None = None
    is_gst_exempt: bool = False
    warranty_note: str | None = None
    discount_type: str | None = None
    discount_value: Decimal | None = None


class RecurringScheduleCreate(BaseModel):
    """Request body for creating a recurring invoice schedule.

    Requirements: 60.1
    """

    customer_id: uuid.UUID
    frequency: RecurringFrequency
    line_items: list[RecurringLineItem] = Field(..., min_length=1)
    next_due_date: date
    auto_issue: bool = False
    notes: str | None = None


class RecurringScheduleUpdate(BaseModel):
    """Request body for updating a recurring invoice schedule.

    Requirements: 60.3
    """

    frequency: RecurringFrequency | None = None
    line_items: list[RecurringLineItem] | None = None
    next_due_date: date | None = None
    auto_issue: bool | None = None
    notes: str | None = None


class RecurringScheduleResponse(BaseModel):
    """Response for a single recurring schedule.

    Requirements: 60.1, 60.3
    """

    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID
    frequency: str
    line_items: list[dict]
    auto_issue: bool
    is_active: bool
    next_due_date: date | None = None
    last_generated_at: datetime | None = None
    notes: str | None = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecurringScheduleListResponse(BaseModel):
    """Response for listing recurring schedules."""

    schedules: list[RecurringScheduleResponse]
    total: int


# ---------------------------------------------------------------------------
# Multi-Currency Schemas (Requirement 79)
# ---------------------------------------------------------------------------

# Supported currencies with their symbols
SUPPORTED_CURRENCIES: dict[str, str] = {
    "NZD": "$",
    "AUD": "A$",
    "USD": "US$",
    "GBP": "£",
    "EUR": "€",
    "JPY": "¥",
    "CAD": "C$",
    "SGD": "S$",
    "HKD": "HK$",
    "CNY": "¥",
    "FJD": "FJ$",
    "WST": "WS$",
    "TOP": "T$",
    "PGK": "K",
}


class CurrencyInfo(BaseModel):
    """Information about a single supported currency."""

    code: str = Field(..., min_length=3, max_length=3)
    symbol: str


class CurrencyConfig(BaseModel):
    """Multi-currency configuration stored in org settings.

    Requirements: 79.1, 79.2
    """

    multi_currency_enabled: bool = False
    allowed_currencies: list[str] = Field(default_factory=lambda: ["NZD"])

    @field_validator("allowed_currencies")
    @classmethod
    def validate_allowed_currencies(cls, v: list[str]) -> list[str]:
        if "NZD" not in v:
            v = ["NZD"] + v
        for code in v:
            if code not in SUPPORTED_CURRENCIES:
                raise ValueError(f"Unsupported currency: {code}")
        return v


class SupportedCurrenciesResponse(BaseModel):
    """Response listing all platform-supported currencies."""

    currencies: list[CurrencyInfo]


# ---------------------------------------------------------------------------
# Bulk Export & Archive schemas — Requirements: 31.1, 31.2, 31.3
# ---------------------------------------------------------------------------


class ExportFormat(str, Enum):
    """Supported bulk export formats."""

    csv = "csv"
    zip_pdf = "zip_pdf"


class BulkExportRequest(BaseModel):
    """Request to bulk-export invoices by date range.

    Requirements: 31.1
    """

    start_date: date = Field(..., description="Start of date range (inclusive)")
    end_date: date = Field(..., description="End of date range (inclusive)")
    format: ExportFormat = Field(
        ExportFormat.csv, description="Export format: csv or zip_pdf"
    )

    @field_validator("end_date")
    @classmethod
    def end_date_not_before_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must not be before start_date")
        return v


class BulkExportResponse(BaseModel):
    """Metadata returned alongside the file download."""

    invoice_count: int
    format: str
    filename: str


class BulkDeleteRequest(BaseModel):
    """Request to permanently delete invoices.

    Requirements: 31.2, 31.3
    """

    invoice_ids: list[uuid.UUID] = Field(
        ..., min_length=1, description="IDs of invoices to delete"
    )
    confirm: bool = Field(
        False,
        description="Must be true to proceed with irrecoverable deletion",
    )


class BulkDeleteResponse(BaseModel):
    """Confirmation of bulk deletion result.

    Requirements: 31.2
    """

    deleted_count: int
    estimated_space_recovered: str
    message: str


# ---------------------------------------------------------------------------
# PDF Generation & Email — Requirements: 32.1, 32.3, 32.4
# ---------------------------------------------------------------------------


class InvoiceEmailRequest(BaseModel):
    """POST /api/v1/invoices/{id}/email request body.

    Requirements: 32.3
    """

    recipient_email: str | None = Field(
        default=None,
        description="Override recipient email. Uses customer email if omitted.",
    )


class InvoiceEmailResponse(BaseModel):
    """POST /api/v1/invoices/{id}/email response.

    Requirements: 32.3
    """

    invoice_id: str
    invoice_number: str
    recipient_email: str
    pdf_size_bytes: int
    status: str


class SendReminderRequest(BaseModel):
    """POST /api/v1/invoices/{id}/send-reminder request body."""

    channel: str = Field(
        ...,
        description="Delivery channel: 'email' or 'sms'.",
    )


class SendReminderResponse(BaseModel):
    """POST /api/v1/invoices/{id}/send-reminder response."""

    status: str
    channel: str
    recipient: str
