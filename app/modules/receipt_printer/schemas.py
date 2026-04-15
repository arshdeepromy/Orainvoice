"""Pydantic v2 schemas for receipt printer configuration and print jobs.

**Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# Pattern for new writes — accepts legacy 'network' which gets mapped
_CONNECTION_TYPE_PATTERN = r"^(usb|bluetooth|network|star_webprnt|epson_epos|generic_http|browser_print)$"

# Legacy mapping: 'network' → 'generic_http' for new writes
_LEGACY_CONNECTION_MAP = {"network": "generic_http"}


class PrinterConfigCreate(BaseModel):
    name: str = Field(max_length=100)
    connection_type: str = Field(pattern=_CONNECTION_TYPE_PATTERN)
    address: str | None = None
    paper_width: int = Field(default=80, ge=30, le=120)
    is_default: bool = False
    is_kitchen_printer: bool = False
    location_id: UUID | None = None

    @field_validator("connection_type", mode="after")
    @classmethod
    def _map_legacy_connection_type(cls, v: str) -> str:
        return _LEGACY_CONNECTION_MAP.get(v, v)


class PrinterConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    connection_type: str | None = Field(default=None, pattern=_CONNECTION_TYPE_PATTERN)
    address: str | None = None
    paper_width: int | None = Field(default=None, ge=30, le=120)
    is_default: bool | None = None
    is_kitchen_printer: bool | None = None
    is_active: bool | None = None

    @field_validator("connection_type", mode="after")
    @classmethod
    def _map_legacy_connection_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _LEGACY_CONNECTION_MAP.get(v, v)


class PrinterConfigResponse(BaseModel):
    id: UUID
    org_id: UUID
    location_id: UUID | None = None
    name: str
    connection_type: str
    address: str | None = None
    paper_width: int
    is_default: bool
    is_kitchen_printer: bool
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PrintJobCreate(BaseModel):
    printer_id: UUID | None = None
    job_type: str = Field(default="receipt", pattern="^(receipt|kitchen|report)$")
    payload: dict


class PrintJobResponse(BaseModel):
    id: UUID
    org_id: UUID
    printer_id: UUID | None = None
    job_type: str
    payload: dict
    status: str
    retry_count: int
    error_details: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class TestPrintRequest(BaseModel):
    printer_id: UUID
