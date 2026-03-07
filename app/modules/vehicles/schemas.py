"""Pydantic schemas for the Vehicle module.

Requirements: 14.1, 14.2, 14.3, 14.4, 15.1, 15.2, 15.3, 15.4
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class VehicleLookupResponse(BaseModel):
    """GET /api/v1/vehicles/lookup/{rego} response.

    Returns vehicle data from Global_Vehicle_DB (cache hit) or Carjam API
    (cache miss). Includes a ``source`` field indicating where the data
    came from.

    Requirements: 14.1, 14.2, 14.3, 14.4
    """

    id: str = Field(..., description="Global vehicle UUID")
    rego: str = Field(..., description="Registration number (normalised uppercase)")
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    year: Optional[int] = Field(None, description="Year of manufacture")
    colour: Optional[str] = Field(None, description="Vehicle colour")
    body_type: Optional[str] = Field(None, description="Body type")
    fuel_type: Optional[str] = Field(None, description="Fuel type")
    engine_size: Optional[str] = Field(None, description="Engine size")
    seats: Optional[int] = Field(None, description="Number of seats")
    wof_expiry: Optional[str] = Field(None, description="WOF expiry date (ISO)")
    rego_expiry: Optional[str] = Field(None, description="Registration expiry date (ISO)")
    odometer: Optional[int] = Field(None, description="Last recorded odometer")
    last_pulled_at: str = Field(..., description="ISO 8601 timestamp of last Carjam pull")
    source: str = Field(
        ...,
        description="'cache' if from Global_Vehicle_DB, 'carjam' if freshly fetched",
    )


class VehicleLookupNotFoundResponse(BaseModel):
    """Response when Carjam returns no result — suggest manual entry.

    Requirements: 14.6
    """

    detail: str = Field(..., description="Error message")
    rego: str = Field(..., description="The rego that was looked up")
    suggest_manual_entry: bool = Field(
        True, description="Frontend should show manual entry form"
    )


class ManualVehicleCreate(BaseModel):
    """POST /api/v1/vehicles/manual request body.

    Requirements: 14.6, 14.7
    """

    rego: str = Field(..., min_length=1, max_length=20, description="Registration number")
    make: Optional[str] = Field(None, max_length=100, description="Vehicle make")
    model: Optional[str] = Field(None, max_length=100, description="Vehicle model")
    year: Optional[int] = Field(None, ge=1900, le=2100, description="Year of manufacture")
    colour: Optional[str] = Field(None, max_length=50, description="Vehicle colour")
    body_type: Optional[str] = Field(None, max_length=50, description="Body type")
    fuel_type: Optional[str] = Field(None, max_length=50, description="Fuel type")
    engine_size: Optional[str] = Field(None, max_length=50, description="Engine size")
    num_seats: Optional[int] = Field(None, ge=1, description="Number of seats")


class ManualVehicleResponse(BaseModel):
    """Response for a manually entered vehicle (stored in org_vehicles).

    Requirements: 14.7
    """

    id: str = Field(..., description="Org vehicle UUID")
    org_id: str = Field(..., description="Organisation UUID")
    rego: str = Field(..., description="Registration number")
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    colour: Optional[str] = None
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    engine_size: Optional[str] = None
    num_seats: Optional[int] = None
    is_manual_entry: bool = Field(True, description="Always true for manual entries")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")


class VehicleRefreshResponse(BaseModel):
    """Response for POST /api/v1/vehicles/{id}/refresh.

    Requirements: 14.5
    """

    id: str = Field(..., description="Global vehicle UUID")
    rego: str = Field(..., description="Registration number")
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    colour: Optional[str] = None
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    engine_size: Optional[str] = None
    seats: Optional[int] = None
    wof_expiry: Optional[str] = None
    rego_expiry: Optional[str] = None
    odometer: Optional[int] = None
    last_pulled_at: str = Field(..., description="ISO 8601 timestamp of Carjam pull")
    source: str = Field("carjam", description="Always 'carjam' for refresh")


# ---------------------------------------------------------------------------
# Vehicle Linking (Req 15.1, 15.2)
# ---------------------------------------------------------------------------


class VehicleLinkRequest(BaseModel):
    """POST /api/v1/vehicles/{id}/link request body.

    Links a global vehicle to a customer within the org.

    Requirements: 15.1, 15.2
    """

    customer_id: str = Field(..., description="Customer UUID to link the vehicle to")
    odometer: Optional[int] = Field(None, ge=0, description="Current odometer reading at time of link")


class VehicleLinkResponse(BaseModel):
    """Response for POST /api/v1/vehicles/{id}/link.

    Requirements: 15.1, 15.2
    """

    id: str = Field(..., description="CustomerVehicle link UUID")
    vehicle_id: str = Field(..., description="Global vehicle UUID")
    customer_id: str = Field(..., description="Customer UUID")
    customer_name: str = Field(..., description="Customer full name")
    odometer_at_link: Optional[int] = Field(None, description="Odometer at time of link")
    linked_at: str = Field(..., description="ISO 8601 timestamp")


# ---------------------------------------------------------------------------
# Vehicle Profile (Req 15.3, 15.4)
# ---------------------------------------------------------------------------


class ExpiryIndicator(BaseModel):
    """WOF or rego expiry with colour indicator.

    Requirements: 15.4
    """

    date: Optional[str] = Field(None, description="Expiry date (ISO)")
    days_remaining: Optional[int] = Field(None, description="Days until expiry (negative = expired)")
    indicator: str = Field(
        ...,
        description="'green' (>60d), 'amber' (30-60d), 'red' (<30d or expired)",
    )


class LinkedCustomerSummary(BaseModel):
    """Summary of a customer linked to a vehicle."""

    id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class ServiceHistoryEntry(BaseModel):
    """A single invoice in the vehicle's service history."""

    invoice_id: str
    invoice_number: Optional[str] = None
    status: str
    issue_date: Optional[str] = None
    total: str
    odometer: Optional[int] = None
    customer_name: str
    description: Optional[str] = Field(None, description="First line item description")


class VehicleProfileResponse(BaseModel):
    """GET /api/v1/vehicles/{id} response — full vehicle profile.

    Requirements: 15.3, 15.4
    """

    id: str = Field(..., description="Global vehicle UUID")
    rego: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    colour: Optional[str] = None
    body_type: Optional[str] = None
    fuel_type: Optional[str] = None
    engine_size: Optional[str] = None
    seats: Optional[int] = None
    odometer: Optional[int] = None
    last_pulled_at: Optional[str] = None
    wof_expiry: ExpiryIndicator
    rego_expiry: ExpiryIndicator
    linked_customers: list[LinkedCustomerSummary] = Field(default_factory=list)
    service_history: list[ServiceHistoryEntry] = Field(default_factory=list)
