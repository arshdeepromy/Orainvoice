"""Pydantic v2 schemas for compliance document CRUD.

**Validates: Requirement — Compliance Module**
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ComplianceDocumentCreate(BaseModel):
    document_type: str = Field(..., max_length=50)
    description: str | None = None
    file_key: str = Field(..., max_length=500)
    file_name: str = Field(..., max_length=255)
    expiry_date: date | None = None
    invoice_id: UUID | None = None
    job_id: UUID | None = None


class ComplianceDocumentUpdate(BaseModel):
    document_type: str | None = None
    description: str | None = None
    expiry_date: date | None = None


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
    status: str = ""  # computed: 'valid', 'expiring_soon', 'expired', 'no_expiry'

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _compute_status(self) -> ComplianceDocumentResponse:
        """Compute document status from expiry_date.

        - no_expiry: expiry_date is None
        - expired: expiry_date < today
        - expiring_soon: expiry_date is within 30 days of today (inclusive)
        - valid: expiry_date is more than 30 days in the future
        """
        if self.expiry_date is None:
            self.status = "no_expiry"
        else:
            today = date.today()
            if self.expiry_date < today:
                self.status = "expired"
            elif self.expiry_date <= today + timedelta(days=30):
                self.status = "expiring_soon"
            else:
                self.status = "valid"
        return self


class ComplianceDashboardResponse(BaseModel):
    total_documents: int
    valid_documents: int
    expiring_soon: int
    expired: int
    documents: list[ComplianceDocumentResponse]


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    is_predefined: bool

    model_config = {"from_attributes": True}


class BadgeCountResponse(BaseModel):
    count: int


class CategoriesListResponse(BaseModel):
    items: list[CategoryResponse]
    total: int


class DocumentListResponse(BaseModel):
    items: list[ComplianceDocumentResponse]
    total: int


class ExpiringDocumentsResponse(BaseModel):
    documents: list[ComplianceDocumentResponse]
    total: int
