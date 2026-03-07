"""Pydantic v2 schemas for the database migration tool.

Requirements: Requirement 7 — V1 Organisation Data Migration, Requirement 41
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MigrationMode = Literal["full", "live"]
MigrationStatus = Literal[
    "pending", "validating", "in_progress", "integrity_check",
    "completed", "failed", "rolled_back",
]
SourceFormat = Literal["csv", "json"]


class MigrationCreateRequest(BaseModel):
    org_id: str = Field(..., description="Target organisation ID")
    mode: MigrationMode = Field("full", description="Migration mode: full or live")
    source_format: SourceFormat = Field("json", description="Source data format")
    source_data: dict = Field(
        default_factory=dict,
        description="Source data keyed by entity type (customers, invoices, products, payments, jobs)",
    )
    description: str | None = None


class MigrationExecuteRequest(BaseModel):
    job_id: str = Field(..., description="Migration job ID to execute")


class MigrationRollbackRequest(BaseModel):
    job_id: str = Field(..., description="Migration job ID to rollback")
    reason: str = Field("Manual rollback", description="Reason for rollback")


class IntegrityCheckResult(BaseModel):
    passed: bool
    record_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    financial_totals: dict[str, float] = Field(default_factory=dict)
    reference_errors: list[str] = Field(default_factory=list)
    invoice_numbering_gaps: list[str] = Field(default_factory=list)


class MigrationJobResponse(BaseModel):
    id: str
    org_id: str
    mode: str
    status: str
    source_format: str
    description: str | None = None
    records_processed: int = 0
    records_total: int = 0
    progress_pct: float = 0.0
    integrity_check: IntegrityCheckResult | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class MigrationListResponse(BaseModel):
    jobs: list[MigrationJobResponse]
    total: int
