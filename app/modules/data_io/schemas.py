"""Pydantic schemas for the Data Import module.

Requirements: 69.1, 69.2, 69.3, 69.5
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Import request / response schemas
# ---------------------------------------------------------------------------


class FieldMapping(BaseModel):
    """Maps a CSV column header to a target model field."""

    csv_column: str = Field(..., description="Column header name from the CSV file")
    target_field: str = Field(..., description="Target model field name")


class ImportPreviewRequest(BaseModel):
    """Request body for import preview (sent alongside the CSV file upload).

    The field_mapping list tells the importer how CSV columns map to model
    fields. If omitted, the system attempts auto-mapping by matching CSV
    headers to known field names.
    """

    field_mapping: Optional[list[FieldMapping]] = Field(
        None,
        description="Optional explicit field mapping. Auto-detected if omitted.",
    )


class ImportRowError(BaseModel):
    """Describes a single validation error on an import row."""

    row_number: int = Field(..., description="1-based row number in the CSV")
    field: str = Field(..., description="Field that failed validation")
    value: str = Field(..., description="The invalid value")
    error: str = Field(..., description="Human-readable error description")


class ImportPreviewRow(BaseModel):
    """A single valid row ready for import."""

    row_number: int = Field(..., description="1-based row number in the CSV")
    data: dict = Field(..., description="Mapped field→value pairs")


class ImportPreviewResponse(BaseModel):
    """Response from the import preview endpoint.

    Shows valid rows that will be imported and error rows that will be
    skipped, allowing the user to review before committing.
    """

    total_rows: int = Field(..., description="Total rows parsed from CSV")
    valid_rows: list[ImportPreviewRow] = Field(
        default_factory=list, description="Rows that passed validation"
    )
    error_rows: list[ImportRowError] = Field(
        default_factory=list, description="Rows that failed validation"
    )
    detected_mapping: list[FieldMapping] = Field(
        default_factory=list,
        description="The field mapping used (auto-detected or user-provided)",
    )


class ImportCommitRequest(BaseModel):
    """Request body to commit a previewed import.

    Accepts the same field_mapping and the list of valid row numbers to
    import. The CSV file must be re-uploaded (stateless design).
    """

    field_mapping: list[FieldMapping] = Field(
        ..., description="Field mapping to apply"
    )
    skip_errors: bool = Field(
        True,
        description="If True, skip invalid rows and import valid ones. "
        "If False, abort on any error.",
    )


class ImportCommitResponse(BaseModel):
    """Response from the import commit endpoint."""

    imported_count: int = Field(..., description="Number of records imported")
    skipped_count: int = Field(..., description="Number of rows skipped due to errors")
    errors: list[ImportRowError] = Field(
        default_factory=list,
        description="Details of skipped rows (downloadable as CSV error report)",
    )

# ---------------------------------------------------------------------------
# Export schemas
# ---------------------------------------------------------------------------


class ExportParams(BaseModel):
    """Query parameters for CSV export endpoints.

    Requirements: 69.4
    """

    date_from: Optional[str] = Field(
        None, description="Start date filter (YYYY-MM-DD) — applies to invoices only"
    )
    date_to: Optional[str] = Field(
        None, description="End date filter (YYYY-MM-DD) — applies to invoices only"
    )


# ---------------------------------------------------------------------------
# JSON bulk import schemas
# ---------------------------------------------------------------------------


class BulkCustomerItem(BaseModel):
    """A single customer record in a JSON bulk import."""

    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    mobile_phone: Optional[str] = Field(None, max_length=50)
    work_phone: Optional[str] = Field(None, max_length=50)
    company_name: Optional[str] = Field(None, max_length=255)
    display_name: Optional[str] = Field(None, max_length=255)
    customer_type: Optional[str] = Field("individual", description="individual or business")
    salutation: Optional[str] = Field(None, max_length=20, description="Mr, Mrs, Ms, Dr, etc.")
    address: Optional[str] = Field(None, max_length=5000)
    billing_address: Optional[str] = Field(None, max_length=5000, description="Billing address as text")
    shipping_address: Optional[str] = Field(None, max_length=5000, description="Shipping address as text")
    currency: Optional[str] = Field(None, max_length=3, description="ISO 4217 currency code e.g. NZD")
    language: Optional[str] = Field(None, max_length=10, description="Preferred language e.g. en")
    payment_terms: Optional[str] = Field(None, max_length=50, description="due_on_receipt, net_15, net_30, net_60")
    company_id: Optional[str] = Field(None, max_length=100, description="Business registration number")
    notes: Optional[str] = Field(None, max_length=5000)
    remarks: Optional[str] = Field(None, max_length=5000)


class BulkVehicleItem(BaseModel):
    """A single vehicle record in a JSON bulk import."""

    rego: str = Field(..., min_length=1, max_length=20)
    make: Optional[str] = Field(None, max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    colour: Optional[str] = Field(None, max_length=50)
    body_type: Optional[str] = Field(None, max_length=50)
    fuel_type: Optional[str] = Field(None, max_length=50)
    engine_size: Optional[str] = Field(None, max_length=50)
    num_seats: Optional[int] = Field(None, ge=1, le=100)
    vin: Optional[str] = Field(None, max_length=17, description="Vehicle Identification Number")
    chassis: Optional[str] = Field(None, max_length=50)
    engine_no: Optional[str] = Field(None, max_length=50)
    transmission: Optional[str] = Field(None, max_length=100)
    country_of_origin: Optional[str] = Field(None, max_length=50)
    number_of_owners: Optional[int] = Field(None, ge=0, le=999)
    vehicle_type: Optional[str] = Field(None, max_length=50)
    power_kw: Optional[int] = Field(None, ge=0, le=9999, description="Power in kilowatts")
    tare_weight: Optional[int] = Field(None, ge=0, le=99999, description="Tare weight in kg")
    gross_vehicle_mass: Optional[int] = Field(None, ge=0, le=99999, description="GVM in kg")
    plate_type: Optional[str] = Field(None, max_length=20)
    submodel: Optional[str] = Field(None, max_length=150)
    second_colour: Optional[str] = Field(None, max_length=50)
    wof_expiry: Optional[str] = Field(None, description="WOF expiry date (YYYY-MM-DD)")
    registration_expiry: Optional[str] = Field(None, description="Registration expiry date (YYYY-MM-DD)")
    service_due_date: Optional[str] = Field(None, description="Service due date (YYYY-MM-DD)")
    date_first_registered_nz: Optional[str] = Field(None, description="Date first registered in NZ (YYYY-MM-DD)")
    odometer_last_recorded: Optional[int] = Field(None, ge=0, le=9999999, description="Last recorded odometer reading")


class BulkImportError(BaseModel):
    """Describes a validation error on a single item in a JSON bulk import."""

    index: int = Field(..., description="0-based index in the array")
    field: Optional[str] = Field(None, description="Field that failed validation")
    error: str = Field(..., description="Human-readable error description")


class BulkImportResponse(BaseModel):
    """Response from a JSON bulk import endpoint."""

    imported_count: int = Field(..., description="Number of records successfully imported")
    skipped_count: int = Field(..., description="Number of records skipped due to errors")
    total_submitted: int = Field(..., description="Total records in the upload")
    errors: list[BulkImportError] = Field(
        default_factory=list, description="Details of skipped records"
    )
