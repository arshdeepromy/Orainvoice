"""Compliance document API router.

Endpoints:
- GET    /api/v2/compliance-docs              — list compliance documents
- POST   /api/v2/compliance-docs              — upload compliance document
- GET    /api/v2/compliance-docs/expiring     — expiring documents
- GET    /api/v2/compliance-docs/dashboard    — compliance dashboard

**Validates: Requirement — Compliance Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.compliance_docs.schemas import (
    ComplianceDocumentCreate,
    ComplianceDocumentResponse,
    ComplianceDashboard,
    ExpiringDocumentsResponse,
)
from app.modules.compliance_docs.service import ComplianceService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get(
    "",
    response_model=list[ComplianceDocumentResponse],
    summary="List compliance documents",
)
async def list_compliance_documents(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    docs = await svc.list_documents(org_id)
    return [ComplianceDocumentResponse.model_validate(d) for d in docs]


@router.post(
    "",
    response_model=ComplianceDocumentResponse,
    status_code=201,
    summary="Upload compliance document",
)
async def upload_compliance_document(
    payload: ComplianceDocumentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)
    svc = ComplianceService(db)
    doc = await svc.upload_document(org_id, payload, uploaded_by=user_id)
    return ComplianceDocumentResponse.model_validate(doc)


@router.get(
    "/expiring",
    response_model=ExpiringDocumentsResponse,
    summary="List expiring compliance documents",
)
async def list_expiring_documents(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    docs = await svc.check_expiry(org_id, days_ahead=days)
    return ExpiringDocumentsResponse(
        documents=[ComplianceDocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.get(
    "/dashboard",
    response_model=ComplianceDashboard,
    summary="Compliance dashboard",
)
async def get_compliance_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    data = await svc.get_dashboard(org_id)
    return ComplianceDashboard(
        total_documents=data["total_documents"],
        expiring_soon=data["expiring_soon"],
        expired=data["expired"],
        documents=[ComplianceDocumentResponse.model_validate(d) for d in data["documents"]],
    )
