"""Pydantic request/response schemas for the kiosk check-in module.

Requirements: 2.4, 3.1, 3.2, 3.3, 3.4, 6.2, 6.3, 7.1, 7.2, 7.3, 9.5
"""

from __future__ import annotations

import re
import uuid as _uuid

from pydantic import BaseModel, Field, field_validator


class KioskCheckInRequest(BaseModel):
    """POST /api/v1/kiosk/check-in request body.

    Collects customer name, phone, optional email, and optional vehicle
    registration for walk-in check-in at a kiosk tablet.
    """

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=7)
    email: str | None = Field(None)
    vehicle_rego: str | None = Field(None)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Strip formatting chars and ensure at least 7 digits remain."""
        digits = re.sub(r"[\s\-\+\(\)]", "", v)
        if len(digits) < 7 or not digits.isdigit():
            raise ValueError("Phone must contain at least 7 digits")
        return v.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        """Basic email format check; lowercase and strip whitespace."""
        if v is None:
            return None
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.strip().lower()

    @field_validator("vehicle_rego")
    @classmethod
    def validate_rego(cls, v: str | None) -> str | None:
        """Strip whitespace, uppercase, and coerce empty strings to None."""
        if v is None or v.strip() == "":
            return None
        return v.strip().upper()


class KioskCheckInResponse(BaseModel):
    """Successful check-in response returned to the kiosk frontend."""

    customer_first_name: str
    is_new_customer: bool
    vehicle_linked: bool


# ---------------------------------------------------------------------------
# Vehicle lookup schemas (Requirement 2.4, 7.1)
# ---------------------------------------------------------------------------


class KioskVehicleLookupRequest(BaseModel):
    """POST /kiosk/vehicle-lookup request body."""

    rego: str = Field(..., min_length=1, max_length=10)

    @field_validator("rego")
    @classmethod
    def clean_rego(cls, v: str) -> str:
        """Strip whitespace and uppercase the registration number."""
        return v.strip().upper()


class KioskVehicleLookupResponse(BaseModel):
    """POST /kiosk/vehicle-lookup response body."""

    id: str  # global_vehicle_id
    rego: str
    make: str | None
    model: str | None
    body_type: str | None
    year: int | None
    colour: str | None
    wof_expiry: str | None
    cof_expiry: str | None = Field(None, description="COF expiry date (ISO)")
    inspection_type: str | None = Field(None, description="'wof', 'cof', or null")
    rego_expiry: str | None
    odometer: int | None
    source: str  # "cache" | "carjam" | "manual"


# ---------------------------------------------------------------------------
# Customer lookup schemas (Requirement 9.5)
# ---------------------------------------------------------------------------


class KioskCustomerMatch(BaseModel):
    """Single customer match returned by the customer lookup endpoint."""

    id: str
    first_name: str
    last_name: str
    phone: str | None
    email: str | None


class KioskCustomerLookupResponse(BaseModel):
    """GET /kiosk/customer-lookup response body."""

    items: list[KioskCustomerMatch]
    total: int


# ---------------------------------------------------------------------------
# Enhanced check-in schemas (Requirements 6.2, 6.3, 7.2, 7.3)
# ---------------------------------------------------------------------------


class KioskVehicleEntry(BaseModel):
    """A single vehicle entry within the V2 check-in request."""

    global_vehicle_id: str
    odometer_km: int | None = None

    @field_validator("global_vehicle_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Ensure global_vehicle_id is a valid UUID string."""
        try:
            _uuid.UUID(v)
        except (ValueError, AttributeError):
            raise ValueError("global_vehicle_id must be a valid UUID")
        return v


class KioskCheckInRequestV2(BaseModel):
    """POST /kiosk/check-in (v2) request body.

    Extends the original check-in with multi-vehicle support and
    existing customer auto-fill.
    """

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=7)
    email: str | None = None
    vehicles: list[KioskVehicleEntry] = Field(default_factory=list)
    existing_customer_id: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Strip formatting chars and ensure at least 7 digits remain."""
        digits = re.sub(r"[\s\-\+\(\)]", "", v)
        if len(digits) < 7 or not digits.isdigit():
            raise ValueError("Phone must contain at least 7 digits")
        return v.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        """Basic email format check; lowercase and strip whitespace."""
        if v is None:
            return None
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Invalid email format")
        return v.strip().lower()


class KioskCheckInResponseV2(BaseModel):
    """POST /kiosk/check-in (v2) response body."""

    customer_first_name: str
    is_new_customer: bool
    vehicles_linked: int
