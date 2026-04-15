"""Pydantic schemas for the IRD Gateway module.

Provides request/response models for IRD credential management,
filing operations, and audit log queries.

Requirements: 25.1, 25.2, 28.1
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mask_credential(value: str | None) -> str | None:
    """Mask a credential for safe display in API responses."""
    if not value:
        return None
    if len(value) <= 8:
        return "****"
    return "****" + value[-4:]


def _is_masked(value: str | None) -> bool:
    """Detect if a value is a mask pattern (should not overwrite real creds)."""
    if not value:
        return False
    return value.startswith("****") or all(c == "*" for c in value)


def validate_ird_number(ird: str) -> bool:
    """Validate NZ IRD number using mod-11 check digit algorithm."""
    digits = [int(d) for d in ird.replace("-", "").replace(" ", "").strip() if d.isdigit()]
    if len(digits) not in (8, 9):
        return False
    if len(digits) == 8:
        digits = [0] + digits
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    weighted_sum = sum(d * w for d, w in zip(digits[:8], weights))
    remainder = weighted_sum % 11
    if remainder == 0:
        return digits[8] == 0
    if remainder == 1:
        return False
    check_digit = 11 - remainder
    return digits[8] == check_digit


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class IrdConnectRequest(BaseModel):
    """Request to connect IRD Gateway credentials."""

    ird_number: str
    username: str
    password: str
    environment: str = "sandbox"  # sandbox | production

    @field_validator("ird_number")
    @classmethod
    def validate_ird(cls, v: str) -> str:
        cleaned = re.sub(r"[\s-]", "", v)
        if not cleaned.isdigit():
            raise ValueError("IRD number must contain only digits (and optional hyphens/spaces)")
        if not validate_ird_number(v):
            raise ValueError("IRD number fails mod-11 check digit validation")
        return v

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in ("sandbox", "production"):
            raise ValueError("environment must be 'sandbox' or 'production'")
        return v


class IncomeTaxFileRequest(BaseModel):
    """Request to file an income tax return."""

    tax_year: int


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class IrdStatusResponse(BaseModel):
    """IRD connection status response."""

    connected: bool
    ird_number: str | None = None
    environment: str | None = None
    active_services: list[str] = []
    last_filing_at: datetime | None = None

    model_config = {"from_attributes": True}


class IrdPreflightResponse(BaseModel):
    """Preflight check result before GST filing."""

    period_id: uuid.UUID
    obligation_met: bool
    existing_return: bool
    period_start: Any = None
    period_end: Any = None
    gst_data: dict | None = None
    message: str = ""


class IrdFilingResponse(BaseModel):
    """Filing submission result."""

    success: bool
    filing_type: str
    status: str
    ird_reference: str | None = None
    message: str = ""
    error_code: str | None = None


class IrdFilingLogResponse(BaseModel):
    """Single filing log entry for audit trail."""

    id: uuid.UUID
    filing_type: str
    period_id: uuid.UUID | None = None
    status: str
    ird_reference: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IrdFilingLogListResponse(BaseModel):
    """Paginated filing log list."""

    items: list[IrdFilingLogResponse]
    total: int
