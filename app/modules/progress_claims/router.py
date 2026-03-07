"""Progress claim API router.

Endpoints:
- GET    /api/v2/progress-claims              — list (paginated/filterable)
- POST   /api/v2/progress-claims              — create
- GET    /api/v2/progress-claims/{id}         — get
- PUT    /api/v2/progress-claims/{id}         — update
- POST   /api/v2/progress-claims/{id}/approve — approve (generates invoice)

**Validates: Requirement — ProgressClaim Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.progress_claims.schemas import (
    ProgressClaimCreate,
    ProgressClaimListResponse,
    ProgressClaimResponse,
    ProgressClaimUpdate,
)
from app.modules.progress_claims.service import ProgressClaimService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("", response_model=ProgressClaimListResponse, summary="List progress claims")
async def list_claims(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProgressClaimService(db)
    claims, total = await svc.list_claims(
        org_id, page=page, page_size=page_size,
        project_id=project_id, status=status,
    )
    return ProgressClaimListResponse(
        claims=[ProgressClaimResponse.model_validate(c) for c in claims],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=ProgressClaimResponse, status_code=201, summary="Create progress claim")
async def create_claim(
    payload: ProgressClaimCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProgressClaimService(db)
    try:
        claim = await svc.create_claim(org_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return ProgressClaimResponse.model_validate(claim)


@router.get("/{claim_id}", response_model=ProgressClaimResponse, summary="Get progress claim")
async def get_claim(
    claim_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProgressClaimService(db)
    claim = await svc.get_claim(org_id, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Progress claim not found")
    return ProgressClaimResponse.model_validate(claim)


@router.put("/{claim_id}", response_model=ProgressClaimResponse, summary="Update progress claim")
async def update_claim(
    claim_id: UUID,
    payload: ProgressClaimUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProgressClaimService(db)
    try:
        claim = await svc.update_claim(org_id, claim_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if claim is None:
        raise HTTPException(status_code=404, detail="Progress claim not found")
    return ProgressClaimResponse.model_validate(claim)


@router.post("/{claim_id}/approve", summary="Approve progress claim")
async def approve_claim(
    claim_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProgressClaimService(db)
    try:
        result = await svc.approve_claim(org_id, claim_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result


@router.get("/{claim_id}/pdf", summary="Download progress claim PDF")
async def download_claim_pdf(
    claim_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    from fastapi.responses import Response
    from app.modules.progress_claims.pdf import generate_progress_claim_pdf

    org_id = _get_org_id(request)
    svc = ProgressClaimService(db)
    claim = await svc.get_claim(org_id, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Progress claim not found")

    claim_dict = ProgressClaimResponse.model_validate(claim).model_dump()
    pdf_bytes = generate_progress_claim_pdf(claim_dict)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=progress-claim-{claim.claim_number}.pdf"},
    )
