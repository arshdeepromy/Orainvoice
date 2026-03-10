"""Pydantic v2 schemas for module management API responses.

**Validates: Requirement 6**
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModuleResponse(BaseModel):
    """Single module with its enabled state for an organisation."""

    slug: str
    display_name: str
    description: str | None = None
    category: str | None = None
    is_core: bool = False
    dependencies: list[str] = Field(default_factory=list)
    status: str = "available"
    is_enabled: bool = False
    in_plan: bool = True

    model_config = {"from_attributes": True}


class ModuleListResponse(BaseModel):
    """List of all modules with enabled state."""

    modules: list[ModuleResponse]
    total: int


class EnableModuleResponse(BaseModel):
    """Response after enabling a module."""

    slug: str
    enabled: bool = True
    additionally_enabled: list[str] = Field(
        default_factory=list,
        description="Dependency modules that were auto-enabled",
    )
    message: str


class DisableModuleResponse(BaseModel):
    """Response after disabling a module or warning about dependents."""

    slug: str
    disabled: bool
    dependents: list[str] = Field(
        default_factory=list,
        description="Modules that depend on this module and are currently enabled",
    )
    warning: str | None = None
    message: str
