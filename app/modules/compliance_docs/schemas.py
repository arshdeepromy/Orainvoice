"""Pydantic v2 schemas for compliance document CRUD.

**Validates: Requirement — Compliance Module**
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ComplianceDocumentCreate(BaseModel):
    document_type: str = Field(..., max_length=50)
    description: str | None = None
    file_key: str = Field(..., max_length=500)
    file_name: str = Field(..., max_length=255)
    expiry_date: date | None = None
    invoice_id: UUID | None = None
    job_id: UUID | None = None


class ComplianceDocumentResponse(BaseModel):
    id: UUID
    org_id: UUID
    document_type: str
    description: str | None = None
    file_key: str
    file_name: str
    expiry_date: date | None = None
    invoice_id: UUID | None = None
    job_id: UUID | None = None
    uploaded_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ComplianceDashboard(BaseModel):
    total_documents: int
    expiring_soon: int
    expired: int
    documents: list[ComplianceDocumentResponse]


class ExpiringDocumentsResponse(BaseModel):
    documents: list[ComplianceDocumentResponse]
    total: int
