"""Pydantic v2 schemas for feature flag CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Targeting rule schema
# ---------------------------------------------------------------------------

class TargetingRule(BaseModel):
    """A single targeting rule within a feature flag."""

    type: Literal[
        "org_override",
        "trade_category",
        "trade_family",
        "country",
        "plan_tier",
        "percentage",
    ]
    value: str = Field(..., description="Match value (org_id, slug, country code, tier name, or 0-100)")
    enabled: bool = Field(..., description="Value to return when this rule matches")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class FeatureFlagCreate(BaseModel):
    """Create a new feature flag."""

    key: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(default="Core", max_length=50)
    access_level: str = Field(default="all_users", max_length=50)
    dependencies: list[str] = Field(default_factory=list)
    default_value: bool = False
    is_active: bool = True
    targeting_rules: list[TargetingRule] = Field(default_factory=list)


class FeatureFlagUpdate(BaseModel):
    """Update an existing feature flag."""

    display_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = Field(None, max_length=50)
    access_level: str | None = Field(None, max_length=50)
    dependencies: list[str] | None = None
    default_value: bool | None = None
    is_active: bool | None = None
    targeting_rules: list[TargetingRule] | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class FeatureFlagResponse(BaseModel):
    """Full feature flag representation returned by the API."""

    id: UUID
    key: str
    display_name: str
    description: str | None = None
    category: str = "Core"
    access_level: str = "all_users"
    dependencies: list[str] = Field(default_factory=list)
    default_value: bool
    is_active: bool
    targeting_rules: list[TargetingRule]
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FeatureFlagListResponse(BaseModel):
    """Paginated list of feature flags."""

    flags: list[FeatureFlagResponse]
    total: int


class OrgFlagEvaluation(BaseModel):
    """A single evaluated flag for an org context."""

    key: str
    enabled: bool


class OrgFlagsResponse(BaseModel):
    """All active flags evaluated for the requesting org."""

    flags: list[OrgFlagEvaluation]
