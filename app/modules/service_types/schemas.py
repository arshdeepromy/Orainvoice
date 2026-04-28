"""Pydantic schemas for the Service Types module.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.5
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared / nested schemas
# ---------------------------------------------------------------------------


class ServiceTypeFieldDefinition(BaseModel):
    """Field definition used in create/update requests.

    Requirements: 4.5 — whitespace-only labels are rejected.
    """

    label: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Field label (whitespace stripped, must not be blank)",
    )
    field_type: Literal["text", "select", "multi_select", "number"] = Field(
        ..., description="Type of input field"
    )
    display_order: int = Field(0, ge=0, description="Sort order for display")
    is_required: bool = Field(False, description="Whether the field is required")
    options: Optional[list[str]] = Field(
        None,
        description="Predefined options for select/multi_select fields",
    )

    @field_validator("label", mode="before")
    @classmethod
    def strip_and_reject_blank_label(cls, v: str) -> str:
        """Strip whitespace and reject whitespace-only labels.

        Validates: Requirements 4.5
        """
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Label must not be empty or whitespace-only")
        return v


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ServiceTypeCreateRequest(BaseModel):
    """POST /api/v1/service-types request body.

    Requirements: 2.1
    """

    name: str = Field(
        ..., min_length=1, max_length=255, description="Service type name"
    )
    description: Optional[str] = Field(
        None, max_length=2000, description="Optional description"
    )
    is_active: bool = Field(True, description="Whether the service type is active")
    fields: list[ServiceTypeFieldDefinition] = Field(
        default_factory=list,
        description="Additional info field definitions",
    )


class ServiceTypeUpdateRequest(BaseModel):
    """PUT /api/v1/service-types/{id} request body.

    All fields optional — only provided fields are updated.
    ``fields`` = None means no change; ``fields`` = [] means remove all.

    Requirements: 2.4, 2.5
    """

    name: Optional[str] = Field(
        None, min_length=1, max_length=255, description="Service type name"
    )
    description: Optional[str] = Field(
        None, max_length=2000, description="Optional description"
    )
    is_active: Optional[bool] = Field(
        None, description="Active/inactive toggle"
    )
    fields: Optional[list[ServiceTypeFieldDefinition]] = Field(
        None,
        description="Field definitions (None = no change, [] = remove all)",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ServiceTypeFieldResponse(BaseModel):
    """Single field definition in API responses."""

    id: str = Field(..., description="Field UUID")
    label: str = Field(..., description="Field label")
    field_type: str = Field(..., description="Field type")
    display_order: int = Field(..., description="Display order")
    is_required: bool = Field(..., description="Whether the field is required")
    options: Optional[list[str]] = Field(None, description="Predefined options")


class ServiceTypeResponse(BaseModel):
    """Single service type in API responses.

    Requirements: 2.1, 2.3
    """

    id: str = Field(..., description="Service type UUID")
    name: str = Field(..., description="Service type name")
    description: Optional[str] = Field(None, description="Description")
    is_active: bool = Field(..., description="Active/inactive status")
    fields: list[ServiceTypeFieldResponse] = Field(
        default_factory=list, description="Additional info field definitions"
    )
    created_at: str = Field(..., description="ISO 8601 creation timestamp")
    updated_at: str = Field(..., description="ISO 8601 last update timestamp")


class ServiceTypeListResponse(BaseModel):
    """GET /api/v1/service-types response.

    Requirements: 2.2
    """

    service_types: list[ServiceTypeResponse] = Field(
        default_factory=list, description="List of service types"
    )
    total: int = Field(0, description="Total number of results")
