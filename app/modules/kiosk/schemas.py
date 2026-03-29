"""Pydantic request/response schemas for the kiosk check-in module.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

import re

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
