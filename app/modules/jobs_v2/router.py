"""Job API router.

Endpoints:
- GET    /api/v2/jobs                         — list (paginated/filterable)
- POST   /api/v2/jobs                         — create
- GET    /api/v2/jobs/{id}                    — get
- PUT    /api/v2/jobs/{id}                    — update
- PUT    /api/v2/jobs/{id}/status             — change status
- POST   /api/v2/jobs/{id}/attachments        — upload attachment
- GET    /api/v2/jobs/{id}/attachments        — list attachments
- POST   /api/v2/jobs/{id}/convert-to-invoice — convert to invoice
- GET    /api/v2/jobs/{id}/history            — status history

Template endpoints:
- GET    /api/v2/job-templates                — list templates
- POST   /api/v2/job-templates                — create template
- PUT    /api/v2/job-templates/{id}           — update template
- DELETE /api/v2/job-templates/{id}           — soft-delete template

**Validates: Requirement 11**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.jobs_v2.schemas import (
    ConvertToInvoiceRequest,
    ConvertToInvoiceResponse,
    JobAttachmentCreate,
    JobAttachmentResponse,
    JobCreate,
    JobListResponse,
    JobResponse,
    JobStatusChange,
    JobStatusHistoryResponse,
    JobUpdate,
)
from app.modules.jobs_v2.service import InvalidStatusTransition, JobService

router = APIRouter()
templates_router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    """Extract org_id from request state (set by auth middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    """Extract user_id from request state if available."""
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=JobListResponse, summary="List jobs")
async def list_jobs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    customer_id: UUID | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    jobs, total = await svc.list_jobs(
        org_id, page=page, page_size=page_size,
        status=status, customer_id=customer_id, search=search,
    )
    return JobListResponse(
        jobs=[JobResponse.model_validate(j) for j in jobs],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=JobResponse, status_code=201, summary="Create job")
async def create_job(
    payload: JobCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = JobService(db)
    job = await svc.create_job(org_id, payload, created_by=user_id)
    return JobResponse.model_validate(job)


@router.get("/{job_id}", response_model=JobResponse, summary="Get job")
async def get_job(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    job = await svc.get_job(org_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


@router.put("/{job_id}", response_model=JobResponse, summary="Update job")
async def update_job(
    job_id: UUID,
    payload: JobUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    job = await svc.update_job(org_id, job_id, payload)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# Status change
# ---------------------------------------------------------------------------

@router.put("/{job_id}/status", response_model=JobResponse, summary="Change job status")
async def change_status(
    job_id: UUID,
    payload: JobStatusChange,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = JobService(db)
    try:
        job = await svc.change_status(
            org_id, job_id, payload.status,
            changed_by=user_id, notes=payload.notes,
        )
    except InvalidStatusTransition as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JobResponse.model_validate(job)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

@router.post(
    "/{job_id}/attachments",
    response_model=JobAttachmentResponse,
    status_code=201,
    summary="Upload attachment",
)
async def add_attachment(
    job_id: UUID,
    payload: JobAttachmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = JobService(db)
    try:
        attachment = await svc.add_attachment(
            org_id, job_id, payload, uploaded_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JobAttachmentResponse.model_validate(attachment)


@router.get(
    "/{job_id}/attachments",
    response_model=list[JobAttachmentResponse],
    summary="List attachments",
)
async def list_attachments(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    try:
        attachments = await svc.list_attachments(org_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [JobAttachmentResponse.model_validate(a) for a in attachments]


# ---------------------------------------------------------------------------
# Convert to invoice
# ---------------------------------------------------------------------------

@router.post(
    "/{job_id}/convert-to-invoice",
    response_model=ConvertToInvoiceResponse,
    summary="Convert job to invoice",
)
async def convert_to_invoice(
    job_id: UUID,
    payload: ConvertToInvoiceRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = JobService(db)
    try:
        result = await svc.convert_to_invoice(
            org_id, job_id, payload, changed_by=user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ConvertToInvoiceResponse(
        job_id=result["job_id"],
        invoice_id=result["invoice_id"],
        line_items_count=result["line_items_count"],
        message="Job converted to invoice successfully",
    )


# ---------------------------------------------------------------------------
# Status history
# ---------------------------------------------------------------------------

@router.get(
    "/{job_id}/history",
    response_model=list[JobStatusHistoryResponse],
    summary="Get job status history",
)
async def get_status_history(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    try:
        history = await svc.get_status_history(org_id, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [JobStatusHistoryResponse.model_validate(h) for h in history]


# ---------------------------------------------------------------------------
# Job templates
# ---------------------------------------------------------------------------

from app.modules.jobs_v2.schemas import (
    JobTemplateCreate,
    JobTemplateListResponse,
    JobTemplateResponse,
    JobTemplateUpdate,
)


@templates_router.get("", response_model=JobTemplateListResponse, summary="List job templates")
async def list_templates(
    request: Request,
    trade_category_slug: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    templates, total = await svc.list_templates(
        org_id, trade_category_slug=trade_category_slug,
    )
    return JobTemplateListResponse(
        templates=[JobTemplateResponse.model_validate(t) for t in templates],
        total=total,
    )


@templates_router.post(
    "", response_model=JobTemplateResponse, status_code=201, summary="Create job template",
)
async def create_template(
    payload: JobTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    template = await svc.create_template(org_id, payload)
    return JobTemplateResponse.model_validate(template)


@templates_router.put(
    "/{template_id}", response_model=JobTemplateResponse, summary="Update job template",
)
async def update_template(
    template_id: UUID,
    payload: JobTemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    template = await svc.update_template(org_id, template_id, payload)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return JobTemplateResponse.model_validate(template)


@templates_router.delete(
    "/{template_id}", status_code=204, summary="Soft-delete job template",
)
async def delete_template(
    template_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = JobService(db)
    deleted = await svc.delete_template(org_id, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
