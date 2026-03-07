"""Pydantic v2 schemas for terminology endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TerminologyMapResponse(BaseModel):
    """Merged terminology map for the authenticated organisation."""

    terms: dict[str, str] = Field(
        ..., description="Mapping of generic_key → resolved label"
    )


class TerminologyOverrideRequest(BaseModel):
    """Request body for setting org-level terminology overrides."""

    overrides: dict[str, str] = Field(
        ...,
        description="Mapping of generic_key → custom_label to upsert",
        min_length=1,
    )
