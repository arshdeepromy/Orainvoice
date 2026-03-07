"""Variation order API router.

Endpoints:
- GET    /api/v2/variations                       — list (paginated/filterable)
- POST   /api/v2/variations                       — create
- GET    /api/v2/variations/{id}                  — get
- PUT    /api/v2/variations/{id}                  — update
- DELETE /api/v2/variations/{id}                  — delete (non-approved only)
- PUT    /api/v2/variations/{id}/approve          — approve
- GET    /api/v2/variations/register/{project_id} — variation register

**Validates: Requirement 29 — Variation Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.variations.schemas import (
    VariationOrderCreate,
    VariationOrderListResponse,
    VariationOrderResponse,
    VariationOrderUpdate,
)
from app.modules.variations.service import VariationService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("", response_model=VariationOrderListResponse, summary="List variation orders")
async def list_variations(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    project_id: UUID | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    variations, total = await svc.list_variations(
        org_id, page=page, page_size=page_size,
        project_id=project_id, status=status,
    )
    return VariationOrderListResponse(
        variations=[VariationOrderResponse.model_validate(v) for v in variations],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=VariationOrderResponse, status_code=201, summary="Create variation order")
async def create_variation(
    payload: VariationOrderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    variation = await svc.create_variation(org_id, payload)
    return VariationOrderResponse.model_validate(variation)


@router.get("/register/{project_id}", summary="Get variation register for project")
async def get_variation_register(
    project_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    return await svc.get_variation_register(org_id, project_id)


@router.get("/{variation_id}", response_model=VariationOrderResponse, summary="Get variation order")
async def get_variation(
    variation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    variation = await svc.get_variation(org_id, variation_id)
    if variation is None:
        raise HTTPException(status_code=404, detail="Variation order not found")
    return VariationOrderResponse.model_validate(variation)


@router.put("/{variation_id}", response_model=VariationOrderResponse, summary="Update variation order")
async def update_variation(
    variation_id: UUID,
    payload: VariationOrderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    try:
        variation = await svc.update_variation(org_id, variation_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if variation is None:
        raise HTTPException(status_code=404, detail="Variation order not found")
    return VariationOrderResponse.model_validate(variation)


@router.delete("/{variation_id}", status_code=204, summary="Delete variation order")
async def delete_variation(
    variation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    try:
        await svc.delete_variation(org_id, variation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.put("/{variation_id}/approve", summary="Approve variation order")
async def approve_variation(
    variation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = VariationService(db)
    try:
        result = await svc.approve_variation(org_id, variation_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result


@router.get("/{variation_id}/pdf", summary="Download variation order PDF")
async def download_variation_pdf(
    variation_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    from fastapi.responses import Response
    from app.modules.variations.pdf import generate_variation_order_pdf

    org_id = _get_org_id(request)
    svc = VariationService(db)
    variation = await svc.get_variation(org_id, variation_id)
    if variation is None:
        raise HTTPException(status_code=404, detail="Variation order not found")

    variation_dict = VariationOrderResponse.model_validate(variation).model_dump()
    pdf_bytes = generate_variation_order_pdf(variation_dict)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=variation-order-{variation.variation_number}.pdf"},
    )
