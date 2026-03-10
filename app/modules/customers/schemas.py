"""Pydantic schemas for the Customer module.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

# Enums for customer fields
CUSTOMER_TYPES = ["individual", "business"]
SALUTATIONS = ["Mr", "Mrs", "Ms", "Miss", "Dr", "Prof", ""]
PAYMENT_TERMS = ["due_on_receipt", "net_7", "net_15", "net_30", "net_45", "net_60", "net_90"]


class AddressSchema(BaseModel):
    """Structured address for billing/shipping."""
    
    street: Optional[str] = Field(None, max_length=500, description="Street address")
    city: Optional[str] = Field(None, max_length=100, description="City")
    state: Optional[str] = Field(None, max_length=100, description="State/Province/Region")
    postal_code: Optional[str] = Field(None, max_length=20, description="Postal/ZIP code")
    country: Optional[str] = Field(None, max_length=100, description="Country")


class ContactPersonSchema(BaseModel):
    """Additional contact person for a customer."""
    
    salutation: Optional[str] = Field(None, max_length=20)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    work_phone: Optional[str] = Field(None, max_length=50)
    mobile_phone: Optional[str] = Field(None, max_length=50)
    designation: Optional[str] = Field(None, max_length=100, description="Job title")
    is_primary: bool = Field(False, description="Is this the primary contact")


class CustomerCreateRequest(BaseModel):
    """POST /api/v1/customers request body.

    Comprehensive customer creation with all fields.
    Requirements: 11.4, 11.5
    """

    # Required fields
    first_name: str = Field(
        ..., min_length=1, max_length=100, description="Customer first name"
    )
    last_name: str = Field(
        ..., min_length=1, max_length=100, description="Customer last name"
    )
    email: str = Field(
        ..., max_length=255, description="Customer email address (required)"
    )
    mobile_phone: str = Field(
        ..., max_length=50, description="Mobile phone number (required)"
    )
    
    # Customer type and identity
    customer_type: Optional[str] = Field(
        "individual", description="Customer type: individual or business"
    )
    salutation: Optional[str] = Field(
        None, max_length=20, description="Salutation: Mr, Mrs, Ms, Dr, etc."
    )
    company_name: Optional[str] = Field(
        None, max_length=255, description="Company name (for business customers)"
    )
    display_name: Optional[str] = Field(
        None, max_length=255, description="Display name for invoices"
    )
    
    # Additional contact info
    work_phone: Optional[str] = Field(
        None, max_length=50, description="Work phone number"
    )
    phone: Optional[str] = Field(
        None, max_length=50, description="Legacy phone field (use mobile_phone)"
    )
    
    # Preferences
    currency: Optional[str] = Field(
        "NZD", max_length=3, description="ISO 4217 currency code"
    )
    language: Optional[str] = Field(
        "en", max_length=10, description="Preferred language code"
    )
    
    # Business/Tax settings
    tax_rate_id: Optional[str] = Field(
        None, description="Default tax rate UUID"
    )
    company_id: Optional[str] = Field(
        None, max_length=100, description="Business registration / company ID"
    )
    payment_terms: Optional[str] = Field(
        "due_on_receipt", description="Payment terms"
    )
    
    # Portal and payment options
    enable_bank_payment: Optional[bool] = Field(
        False, description="Allow bank account payment"
    )
    enable_portal: Optional[bool] = Field(
        False, description="Allow customer portal access"
    )
    
    # Addresses
    address: Optional[str] = Field(
        None, max_length=2000, description="Simple address string"
    )
    billing_address: Optional[AddressSchema] = Field(
        None, description="Structured billing address"
    )
    shipping_address: Optional[AddressSchema] = Field(
        None, description="Structured shipping address"
    )
    
    # Additional data
    contact_persons: Optional[list[ContactPersonSchema]] = Field(
        None, description="Additional contact persons"
    )
    custom_fields: Optional[dict] = Field(
        None, description="Custom fields key-value pairs"
    )
    
    # Notes
    notes: Optional[str] = Field(
        None, max_length=5000, description="Internal notes"
    )
    remarks: Optional[str] = Field(
        None, max_length=5000, description="Additional remarks"
    )


class CustomerUpdateRequest(BaseModel):
    """PUT /api/v1/customers/{id} request body.

    All fields optional — only provided fields are updated.
    Requirements: 11.5
    """

    # Identity fields
    first_name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Customer first name"
    )
    last_name: Optional[str] = Field(
        None, min_length=1, max_length=100, description="Customer last name"
    )
    customer_type: Optional[str] = Field(
        None, description="Customer type: individual or business"
    )
    salutation: Optional[str] = Field(
        None, max_length=20, description="Salutation"
    )
    company_name: Optional[str] = Field(
        None, max_length=255, description="Company name"
    )
    display_name: Optional[str] = Field(
        None, max_length=255, description="Display name"
    )
    
    # Contact info
    email: Optional[str] = Field(
        None, max_length=255, description="Customer email address"
    )
    phone: Optional[str] = Field(
        None, max_length=50, description="Phone number"
    )
    work_phone: Optional[str] = Field(
        None, max_length=50, description="Work phone"
    )
    mobile_phone: Optional[str] = Field(
        None, max_length=50, description="Mobile phone"
    )
    
    # Preferences
    currency: Optional[str] = Field(
        None, max_length=3, description="Currency code"
    )
    language: Optional[str] = Field(
        None, max_length=10, description="Language code"
    )
    
    # Business/Tax
    tax_rate_id: Optional[str] = Field(
        None, description="Tax rate UUID"
    )
    company_id: Optional[str] = Field(
        None, max_length=100, description="Company ID"
    )
    payment_terms: Optional[str] = Field(
        None, description="Payment terms"
    )
    
    # Options
    enable_bank_payment: Optional[bool] = Field(
        None, description="Allow bank payment"
    )
    enable_portal: Optional[bool] = Field(
        None, description="Allow portal access"
    )
    
    # Addresses
    address: Optional[str] = Field(
        None, max_length=2000, description="Simple address"
    )
    billing_address: Optional[AddressSchema] = Field(
        None, description="Billing address"
    )
    shipping_address: Optional[AddressSchema] = Field(
        None, description="Shipping address"
    )
    
    # Additional data
    contact_persons: Optional[list[ContactPersonSchema]] = Field(
        None, description="Contact persons"
    )
    custom_fields: Optional[dict] = Field(
        None, description="Custom fields"
    )
    
    # Notes
    notes: Optional[str] = Field(
        None, max_length=5000, description="Internal notes"
    )
    remarks: Optional[str] = Field(
        None, max_length=5000, description="Remarks"
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CustomerResponse(BaseModel):
    """Single customer in API responses.

    Requirements: 11.2, 11.5
    """

    id: str = Field(..., description="Customer UUID")
    
    # Identity
    customer_type: str = Field("individual", description="individual or business")
    salutation: Optional[str] = Field(None, description="Salutation")
    first_name: str = Field(..., description="First name")
    last_name: str = Field(..., description="Last name")
    company_name: Optional[str] = Field(None, description="Company name")
    display_name: Optional[str] = Field(None, description="Display name")
    
    # Contact
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    work_phone: Optional[str] = Field(None, description="Work phone")
    mobile_phone: Optional[str] = Field(None, description="Mobile phone")
    
    # Preferences
    currency: str = Field("NZD", description="Currency code")
    language: str = Field("en", description="Language code")
    
    # Business/Tax
    tax_rate_id: Optional[str] = Field(None, description="Tax rate UUID")
    company_id: Optional[str] = Field(None, description="Company ID")
    payment_terms: str = Field("due_on_receipt", description="Payment terms")
    
    # Options
    enable_bank_payment: bool = Field(False, description="Bank payment enabled")
    enable_portal: bool = Field(False, description="Portal access enabled")
    
    # Addresses
    address: Optional[str] = Field(None, description="Simple address")
    billing_address: Optional[dict] = Field(None, description="Billing address")
    shipping_address: Optional[dict] = Field(None, description="Shipping address")
    
    # Additional data
    contact_persons: list = Field(default_factory=list, description="Contact persons")
    custom_fields: dict = Field(default_factory=dict, description="Custom fields")
    
    # Notes
    notes: Optional[str] = Field(None, description="Internal notes")
    remarks: Optional[str] = Field(None, description="Remarks")
    
    # Status
    is_anonymised: bool = Field(False, description="Whether anonymised")
    
    # Timestamps
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class LinkedVehicleSummary(BaseModel):
    """A vehicle linked to a customer (for search results)."""
    
    id: str = Field(..., description="Global vehicle UUID")
    rego: str = Field(..., description="Registration number")
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    year: Optional[int] = Field(None, description="Vehicle year")
    colour: Optional[str] = Field(None, description="Vehicle colour")


class CustomerSearchResult(BaseModel):
    """Single search result in the dropdown.

    Requirements: 11.1, 11.2
    """

    id: str = Field(..., description="Customer UUID")
    customer_type: str = Field("individual", description="individual or business")
    first_name: str = Field(..., description="First name")
    last_name: str = Field(..., description="Last name")
    company_name: Optional[str] = Field(None, description="Company name")
    display_name: Optional[str] = Field(None, description="Display name")
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone number")
    mobile_phone: Optional[str] = Field(None, description="Mobile phone")
    work_phone: Optional[str] = Field(None, description="Work phone")
    receivables: float = Field(0.0, description="Total outstanding balance due (BCY)")
    unused_credits: float = Field(0.0, description="Total unused credit notes (BCY)")
    linked_vehicles: Optional[list[LinkedVehicleSummary]] = Field(
        None, description="Linked vehicles (when include_vehicles=true)"
    )


class CustomerListResponse(BaseModel):
    """GET /api/v1/customers response — search results or full list."""

    customers: list[CustomerSearchResult] = Field(
        default_factory=list, description="List of matching customers"
    )
    total: int = Field(0, description="Total number of results")
    has_exact_match: bool = Field(
        False,
        description="Whether an exact match was found (for 'Create new' hint)",
    )


class CustomerCreateResponse(BaseModel):
    """POST /api/v1/customers response."""

    message: str
    customer: CustomerResponse


class CustomerUpdateResponse(BaseModel):
    """PUT /api/v1/customers/{id} response."""

    message: str
    customer: CustomerResponse


# ---------------------------------------------------------------------------
# Task 7.2 — Customer profile, notify, and vehicle tagging schemas
# Requirements: 12.1, 12.2, 12.3
# ---------------------------------------------------------------------------


class CustomerNotifyRequest(BaseModel):
    """POST /api/v1/customers/{id}/notify request body.

    Send a one-off email or SMS from the customer profile.
    Requirements: 12.2
    """

    channel: Literal["email", "sms"] = Field(
        ..., description="Notification channel: 'email' or 'sms'"
    )
    subject: Optional[str] = Field(
        None,
        max_length=255,
        description="Email subject line (required for email, ignored for SMS)",
    )
    message: str = Field(
        ..., min_length=1, max_length=5000, description="Message body"
    )


class CustomerVehicleTagRequest(BaseModel):
    """POST /api/v1/customers/{id}/vehicles request body.

    Tag a vehicle to a customer.
    Requirements: 12.3
    """

    global_vehicle_id: Optional[str] = Field(
        None, description="UUID of a global vehicle to link"
    )
    org_vehicle_id: Optional[str] = Field(
        None, description="UUID of an org-scoped vehicle to link"
    )


class LinkedVehicleResponse(BaseModel):
    """A vehicle linked to a customer in the profile view."""

    id: str = Field(..., description="CustomerVehicle link UUID")
    rego: Optional[str] = Field(None, description="Registration number")
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    year: Optional[int] = Field(None, description="Vehicle year")
    colour: Optional[str] = Field(None, description="Vehicle colour")
    source: str = Field(..., description="'global' or 'org'")
    linked_at: str = Field(..., description="ISO 8601 link timestamp")


class InvoiceHistoryItem(BaseModel):
    """A single invoice in the customer's history."""

    id: str = Field(..., description="Invoice UUID")
    invoice_number: Optional[str] = Field(None, description="Invoice number")
    vehicle_rego: Optional[str] = Field(None, description="Vehicle rego")
    status: str = Field(..., description="Invoice status")
    issue_date: Optional[str] = Field(None, description="Issue date")
    total: str = Field(..., description="Invoice total (string for precision)")
    balance_due: str = Field(..., description="Outstanding balance")


class CustomerProfileResponse(BaseModel):
    """GET /api/v1/customers/{id} extended profile response.

    Requirements: 12.1
    """

    id: str
    # Identity
    customer_type: str = "individual"
    salutation: Optional[str] = None
    first_name: str
    last_name: str
    company_name: Optional[str] = None
    display_name: Optional[str] = None
    # Contact
    email: Optional[str] = None
    phone: Optional[str] = None
    work_phone: Optional[str] = None
    mobile_phone: Optional[str] = None
    # Preferences
    currency: str = "NZD"
    language: str = "en"
    # Business/Tax
    tax_rate_id: Optional[str] = None
    company_id: Optional[str] = None
    payment_terms: str = "due_on_receipt"
    # Options
    enable_bank_payment: bool = False
    enable_portal: bool = False
    # Addresses
    address: Optional[str] = None
    billing_address: Optional[dict] = Field(default_factory=dict)
    shipping_address: Optional[dict] = Field(default_factory=dict)
    # Additional data
    contact_persons: Optional[list] = Field(default_factory=list)
    custom_fields: Optional[dict] = Field(default_factory=dict)
    # Notes
    notes: Optional[str] = None
    remarks: Optional[str] = None
    # Status
    is_anonymised: bool = False
    # Timestamps
    created_at: str
    updated_at: str
    # Profile data
    vehicles: list[LinkedVehicleResponse] = Field(default_factory=list)
    invoices: list[InvoiceHistoryItem] = Field(default_factory=list)
    total_spend: str = Field("0.00", description="Total amount paid across all invoices")
    outstanding_balance: str = Field(
        "0.00", description="Sum of balance_due across non-voided invoices"
    )


class CustomerNotifyResponse(BaseModel):
    """POST /api/v1/customers/{id}/notify response."""

    message: str
    channel: str
    recipient: Optional[str] = None


class CustomerVehicleTagResponse(BaseModel):
    """POST /api/v1/customers/{id}/vehicles response."""

    message: str
    vehicle_link: LinkedVehicleResponse

# ---------------------------------------------------------------------------
# Task 7.3 — Customer record merging schemas
# Requirements: 12.4
# ---------------------------------------------------------------------------


class CustomerMergeRequest(BaseModel):
    """POST /api/v1/customers/{id}/merge request body.

    The target customer is identified by the URL path parameter.
    The source customer (to be merged into the target) is in the body.

    Requirements: 12.4
    """

    source_customer_id: str = Field(
        ..., description="UUID of the source customer to merge into the target"
    )
    preview_only: bool = Field(
        True,
        description="If True, return a preview of what will be merged without executing",
    )


class MergePreviewVehicle(BaseModel):
    """A vehicle that will be transferred during merge."""

    id: str
    rego: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    source: str = Field(..., description="'global' or 'org'")


class MergePreviewInvoice(BaseModel):
    """An invoice that will be transferred during merge."""

    id: str
    invoice_number: Optional[str] = None
    status: str
    total: str


class MergePreviewContactChanges(BaseModel):
    """Contact detail changes that will result from the merge."""

    email: Optional[str] = Field(None, description="Email that will be set (target kept, source fills gaps)")
    phone: Optional[str] = Field(None, description="Phone that will be set")
    address: Optional[str] = Field(None, description="Address that will be set")
    notes: Optional[str] = Field(None, description="Combined notes")


class CustomerMergePreview(BaseModel):
    """Preview of what a merge will combine.

    Requirements: 12.4
    """

    target_customer: CustomerResponse
    source_customer: CustomerResponse
    vehicles_to_transfer: list[MergePreviewVehicle] = Field(default_factory=list)
    invoices_to_transfer: list[MergePreviewInvoice] = Field(default_factory=list)
    contact_changes: MergePreviewContactChanges
    fleet_account_transfer: bool = Field(
        False, description="Whether a fleet account will be transferred"
    )


class CustomerMergeResponse(BaseModel):
    """POST /api/v1/customers/{id}/merge response.

    Requirements: 12.4
    """

    message: str
    preview: CustomerMergePreview
    merged: bool = Field(
        False, description="True if the merge was executed, False if preview only"
    )



# ---------------------------------------------------------------------------
# Task 7.3 — Customer record merging schemas
# Requirements: 12.4
# ---------------------------------------------------------------------------


class CustomerMergeRequest(BaseModel):
    """POST /api/v1/customers/{id}/merge request body.

    The target customer is identified by the URL path parameter.
    The source customer (to be merged into the target) is in the body.

    Requirements: 12.4
    """

    source_customer_id: str = Field(
        ..., description="UUID of the source customer to merge into the target"
    )
    preview_only: bool = Field(
        True,
        description="If True, return a preview of what will be merged without executing",
    )


class MergePreviewVehicle(BaseModel):
    """A vehicle that will be transferred during merge."""

    id: str
    rego: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    source: str = Field(..., description="'global' or 'org'")


class MergePreviewInvoice(BaseModel):
    """An invoice that will be transferred during merge."""

    id: str
    invoice_number: Optional[str] = None
    status: str
    total: str


class MergePreviewContactChanges(BaseModel):
    """Contact detail changes that will result from the merge."""

    email: Optional[str] = Field(None, description="Email that will be set (target kept, source fills gaps)")
    phone: Optional[str] = Field(None, description="Phone that will be set")
    address: Optional[str] = Field(None, description="Address that will be set")
    notes: Optional[str] = Field(None, description="Combined notes")


class CustomerMergePreview(BaseModel):
    """Preview of what a merge will combine.

    Requirements: 12.4
    """

    target_customer: CustomerResponse
    source_customer: CustomerResponse
    vehicles_to_transfer: list[MergePreviewVehicle] = Field(default_factory=list)
    invoices_to_transfer: list[MergePreviewInvoice] = Field(default_factory=list)
    contact_changes: MergePreviewContactChanges
    fleet_account_transfer: bool = Field(
        False, description="Whether a fleet account will be transferred"
    )


class CustomerMergeResponse(BaseModel):
    """POST /api/v1/customers/{id}/merge response.

    Requirements: 12.4
    """

    message: str
    preview: CustomerMergePreview
    merged: bool = Field(
        False, description="True if the merge was executed, False if preview only"
    )


# ---------------------------------------------------------------------------
# Task 7.4 — Privacy Act 2020 compliance schemas
# Requirements: 13.1, 13.2, 13.3
# ---------------------------------------------------------------------------


class CustomerAnonymiseResponse(BaseModel):
    """DELETE /api/v1/customers/{id} response.

    Requirements: 13.1, 13.2
    """

    message: str
    customer_id: str
    is_anonymised: bool = True
    invoices_preserved: int = Field(
        0, description="Number of linked invoices preserved with anonymised customer data"
    )


class CustomerExportResponse(BaseModel):
    """GET /api/v1/customers/{id}/export response.

    Full customer data export for Privacy Act 2020 compliance.
    Requirements: 13.3
    """

    customer: CustomerResponse
    vehicles: list[dict] = Field(default_factory=list, description="Linked vehicles")
    invoices: list[dict] = Field(default_factory=list, description="Invoice history with line items and payments")
    exported_at: str = Field(..., description="ISO 8601 export timestamp")


# ---------------------------------------------------------------------------
# Task 7.5 — Fleet account management schemas
# Requirements: 66.1, 66.2
# ---------------------------------------------------------------------------


class FleetAccountCreateRequest(BaseModel):
    """POST /api/v1/customers/fleet-accounts request body.

    Requirements: 66.1
    """

    name: str = Field(
        ..., min_length=1, max_length=255, description="Company/fleet name"
    )
    primary_contact_name: Optional[str] = Field(
        None, max_length=255, description="Primary contact person"
    )
    primary_contact_email: Optional[str] = Field(
        None, max_length=255, description="Primary contact email"
    )
    primary_contact_phone: Optional[str] = Field(
        None, max_length=50, description="Primary contact phone"
    )
    billing_address: Optional[str] = Field(
        None, max_length=2000, description="Billing address"
    )
    notes: Optional[str] = Field(
        None, max_length=5000, description="Internal notes"
    )
    pricing_overrides: Optional[dict] = Field(
        None,
        description="Fleet-specific pricing overrides keyed by catalogue item ID, e.g. {'<service_id>': {'price': '85.00'}}",
    )


class FleetAccountUpdateRequest(BaseModel):
    """PUT /api/v1/customers/fleet-accounts/{id} request body.

    All fields optional — only provided fields are updated.
    Requirements: 66.1
    """

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Company/fleet name"
    )
    primary_contact_name: Optional[str] = Field(
        None, max_length=255, description="Primary contact person"
    )
    primary_contact_email: Optional[str] = Field(
        None, max_length=255, description="Primary contact email"
    )
    primary_contact_phone: Optional[str] = Field(
        None, max_length=50, description="Primary contact phone"
    )
    billing_address: Optional[str] = Field(
        None, max_length=2000, description="Billing address"
    )
    notes: Optional[str] = Field(
        None, max_length=5000, description="Internal notes"
    )
    pricing_overrides: Optional[dict] = Field(
        None,
        description="Fleet-specific pricing overrides keyed by catalogue item ID",
    )


class FleetAccountResponse(BaseModel):
    """Single fleet account in API responses.

    Requirements: 66.1
    """

    id: str = Field(..., description="Fleet account UUID")
    name: str = Field(..., description="Company/fleet name")
    primary_contact_name: Optional[str] = Field(None, description="Primary contact person")
    primary_contact_email: Optional[str] = Field(None, description="Primary contact email")
    primary_contact_phone: Optional[str] = Field(None, description="Primary contact phone")
    billing_address: Optional[str] = Field(None, description="Billing address")
    notes: Optional[str] = Field(None, description="Internal notes")
    pricing_overrides: dict = Field(default_factory=dict, description="Fleet-specific pricing overrides")
    customer_count: int = Field(0, description="Number of customers in this fleet")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class FleetAccountListResponse(BaseModel):
    """GET /api/v1/customers/fleet-accounts response."""

    fleet_accounts: list[FleetAccountResponse] = Field(
        default_factory=list, description="List of fleet accounts"
    )
    total: int = Field(0, description="Total number of fleet accounts")


class FleetAccountCreateResponse(BaseModel):
    """POST /api/v1/customers/fleet-accounts response."""

    message: str
    fleet_account: FleetAccountResponse


class FleetAccountUpdateResponse(BaseModel):
    """PUT /api/v1/customers/fleet-accounts/{id} response."""

    message: str
    fleet_account: FleetAccountResponse


class FleetAccountDeleteResponse(BaseModel):
    """DELETE /api/v1/customers/fleet-accounts/{id} response."""

    message: str
    fleet_account_id: str
