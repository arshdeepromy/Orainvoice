"""Compliance document API router.

Endpoints:
- GET    /api/v2/compliance-docs              — list compliance documents (filtered)
- POST   /api/v2/compliance-docs/upload       — multipart file upload
- GET    /api/v2/compliance-docs/categories    — list categories
- POST   /api/v2/compliance-docs/categories    — create custom category
- GET    /api/v2/compliance-docs/badge-count   — expired + expiring-soon count
- GET    /api/v2/compliance-docs/expiring      — expiring documents
- GET    /api/v2/compliance-docs/dashboard     — compliance dashboard
- GET    /api/v2/compliance-docs/{doc_id}/download — stream file download
- PUT    /api/v2/compliance-docs/{doc_id}      — edit document metadata
- DELETE /api/v2/compliance-docs/{doc_id}      — delete document + file

**Validates: Requirements 2–6, 8, 12**
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.compliance_docs.file_storage import ComplianceFileStorage
from app.modules.compliance_docs.schemas import (
    BadgeCountResponse,
    CategoriesListResponse,
    CategoryResponse,
    ComplianceDocumentResponse,
    ComplianceDocumentUpdate,
    ComplianceDashboardResponse,
    DocumentListResponse,
    ExpiringDocumentsResponse,
)
from app.modules.compliance_docs.service import ComplianceService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# ---------------------------------------------------------------------------
# Static-path endpoints MUST be defined BEFORE /{doc_id} endpoints so that
# FastAPI does not treat "upload", "categories", "badge-count" as doc_id
# path parameters.
# ---------------------------------------------------------------------------


# --- Upload (Task 4.1) ----------------------------------------------------

@router.post(
    "/upload",
    response_model=ComplianceDocumentResponse,
    status_code=201,
    summary="Upload compliance document with file",
)
async def upload_compliance_document_with_file(
    request: Request,
    file: UploadFile = File(..., description="The compliance document file"),
    document_type: str = Form(..., description="Document category/type"),
    description: str | None = Form(None, description="Optional description"),
    expiry_date: date | None = Form(None, description="Optional expiry date (YYYY-MM-DD)"),
    invoice_id: UUID | None = Form(None, description="Optional linked invoice ID"),
    job_id: UUID | None = Form(None, description="Optional linked job ID"),
    category_name: str | None = Form(None, description="Optional custom category name"),
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a multipart file upload with metadata form fields.

    Delegates validation (MIME type, file size, magic bytes, double extension)
    to ``ComplianceService.upload_document_with_file()`` which uses
    ``ComplianceFileStorage``.

    Returns 201 with the created document on success.
    Returns 400 for invalid MIME type, oversized file, magic byte mismatch,
    or double extension.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 12.1, 12.4, 12.5**
    """
    org_id = _get_org_id(request)
    user_id = getattr(request.state, "user_id", None)

    metadata: dict = {
        "document_type": document_type,
        "description": description,
        "expiry_date": expiry_date,
        "invoice_id": invoice_id,
        "job_id": job_id,
    }

    svc = ComplianceService(db)
    doc = await svc.upload_document_with_file(
        org_id=org_id,
        file=file,
        metadata=metadata,
        uploaded_by=user_id,
    )
    return ComplianceDocumentResponse.model_validate(doc)


# --- Categories (Task 4.4) ------------------------------------------------

@router.get(
    "/categories",
    response_model=CategoriesListResponse,
    summary="List compliance document categories",
)
async def list_categories(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return predefined categories first, then org-specific custom categories.

    **Validates: Requirements 6.6**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    categories = await svc.get_categories(org_id)
    items = [CategoryResponse.model_validate(c) for c in categories]
    return CategoriesListResponse(items=items, total=len(items))


class _CreateCategoryRequest(BaseModel):
    name: str


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=201,
    summary="Create a custom compliance document category",
)
async def create_custom_category(
    payload: _CreateCategoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create an org-specific custom category.

    Returns 409 if a category with the same name already exists for this org.

    **Validates: Requirements 6.4, 6.5**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    category = await svc.create_custom_category(org_id, payload.name)
    return CategoryResponse.model_validate(category)


# --- Badge count (Task 4.4) -----------------------------------------------

@router.get(
    "/badge-count",
    response_model=BadgeCountResponse,
    summary="Get expired + expiring-soon document count",
)
async def get_badge_count(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the count of expired and expiring-soon documents for the org.

    **Validates: Requirements 8.5**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    count = await svc.get_badge_count(org_id)
    return BadgeCountResponse(count=count)


# --- Expiring documents (existing) ----------------------------------------

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


# --- Dashboard (Task 4.5 — enhanced) --------------------------------------

@router.get(
    "/dashboard",
    response_model=ComplianceDashboardResponse,
    summary="Compliance dashboard",
)
async def get_compliance_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return dashboard summary with valid_documents count.

    **Validates: Requirements 1.1–1.6**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    data = await svc.get_dashboard(org_id)
    return ComplianceDashboardResponse(
        total_documents=data["total_documents"],
        valid_documents=data.get("valid_documents", 0),
        expiring_soon=data["expiring_soon"],
        expired=data["expired"],
        documents=[ComplianceDocumentResponse.model_validate(d) for d in data["documents"]],
    )


# ---------------------------------------------------------------------------
# Dynamic-path endpoints (/{doc_id}/...) — MUST come AFTER static paths
# ---------------------------------------------------------------------------


# --- Download (Task 4.2) --------------------------------------------------

@router.get(
    "/{doc_id}/download",
    summary="Download compliance document file",
)
async def download_compliance_document(
    doc_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Stream the file from storage with correct Content-Type and
    Content-Disposition: attachment headers.

    Returns 403 if the document belongs to another org.
    Returns 404 if the file is missing from storage.

    **Validates: Requirements 4.1, 4.2, 4.3, 12.6**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)

    # Validates org ownership (403) and existence (404)
    doc = await svc.get_document_for_download(org_id, doc_id)

    storage = ComplianceFileStorage()
    stream, content_type = await storage.read_file(doc.file_key)

    return StreamingResponse(
        stream,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.file_name}"',
        },
    )


# --- Edit (Task 4.3) ------------------------------------------------------

@router.put(
    "/{doc_id}",
    response_model=ComplianceDocumentResponse,
    summary="Edit compliance document metadata",
)
async def edit_compliance_document(
    doc_id: UUID,
    payload: ComplianceDocumentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update document_type, description, and/or expiry_date.

    Validates org ownership — returns 403 if the document belongs to
    another organisation.

    **Validates: Requirements 5.1, 5.3**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)

    update_data = payload.model_dump(exclude_unset=True)
    doc = await svc.update_document(org_id, doc_id, update_data)
    return ComplianceDocumentResponse.model_validate(doc)


# --- Delete (Task 4.3) ----------------------------------------------------

@router.delete(
    "/{doc_id}",
    status_code=204,
    summary="Delete compliance document",
)
async def delete_compliance_document(
    doc_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete the document record and remove the file from storage.

    Validates org ownership — returns 403 if the document belongs to
    another organisation.

    **Validates: Requirements 5.2, 5.3**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    await svc.delete_document(org_id, doc_id)


# --- List documents (Task 4.5 — enhanced) ---------------------------------

@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List compliance documents",
)
async def list_compliance_documents(
    request: Request,
    search: str | None = Query(None, description="Text search across file_name, document_type, description"),
    status: str | None = Query(None, description="Filter by status: valid, expiring_soon, expired, no_expiry"),
    category: str | None = Query(None, description="Filter by document_type/category"),
    sort_by: str | None = Query(None, description="Sort column: document_type, file_name, expiry_date, created_at"),
    sort_dir: str | None = Query(None, description="Sort direction: asc or desc"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return filtered, sorted compliance documents wrapped in
    ``{ items: [...], total: N }`` per project convention.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
    """
    org_id = _get_org_id(request)
    svc = ComplianceService(db)
    documents, total = await svc.list_documents_filtered(
        org_id=org_id,
        search=search,
        status=status,
        category=category,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    items = [ComplianceDocumentResponse.model_validate(d) for d in documents]
    return DocumentListResponse(items=items, total=total)
