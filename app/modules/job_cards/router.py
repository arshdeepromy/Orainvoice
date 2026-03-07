"""Job Card router — CRUD endpoints.

Requirements: 59.1, 59.2, 59.5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.job_cards.schemas import (
    JobCardCombineRequest,
    JobCardCombineResponse,
    JobCardConvertResponse,
    JobCardCreate,
    JobCardCreateResponse,
    JobCardItemResponse,
    JobCardListResponse,
    JobCardResponse,
    JobCardSearchResult,
    JobCardUpdate,
)
from app.modules.job_cards.service import (
    combine_job_cards_to_invoice,
    convert_job_card_to_invoice,
    create_job_card,
    get_job_card,
    list_job_cards,
    update_job_card,
)

router = APIRouter()


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = request.client.host if request.client else None
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


@router.post(
    "",
    response_model=JobCardCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a new job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_job_card_endpoint(
    payload: JobCardCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new job card linked to a customer and vehicle.

    Requirements: 59.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    line_items_data = [
        {
            "item_type": li.item_type.value,
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "sort_order": li.sort_order,
        }
        for li in payload.line_items
    ]

    try:
        result = await create_job_card(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            customer_id=payload.customer_id,
            vehicle_rego=payload.vehicle_rego,
            description=payload.description,
            notes=payload.notes,
            line_items_data=line_items_data,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    jc_resp = JobCardResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[JobCardItemResponse(**li) for li in result["line_items"]],
    )

    return JobCardCreateResponse(
        job_card=jc_resp,
        message="Job card created successfully",
    )


@router.get(
    "",
    response_model=JobCardListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List and search job cards",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_job_cards_endpoint(
    request: Request,
    search: str | None = Query(default=None, description="Search by rego, customer name, or description"),
    status: str | None = Query(default=None, description="Filter by job card status"),
    active_only: bool = Query(default=False, description="Show only Open and In Progress job cards"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Search and filter job cards with pagination.

    Use active_only=true for the Salesperson dashboard work queue.

    Requirements: 59.5
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_job_cards(
        db,
        org_id=org_uuid,
        search=search,
        status=status,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )

    return JobCardListResponse(
        job_cards=[JobCardSearchResult(**jc) for jc in result["job_cards"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@router.post(
    "/combine",
    response_model=JobCardCombineResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Job card not found"},
    },
    summary="Combine multiple job cards into a single invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def combine_job_cards_endpoint(
    payload: JobCardCombineRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Combine multiple completed job cards into a single Draft invoice.

    All job cards must be completed and belong to the same customer.

    Requirements: 59.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await combine_job_cards_to_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_ids=payload.job_card_ids,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    await db.commit()

    return JobCardCombineResponse(**result)


@router.get(
    "/{job_card_id}",
    response_model=JobCardResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Job card not found"},
    },
    summary="Get a single job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_job_card_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single job card by ID."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_job_card(db, org_id=org_uuid, job_card_id=job_card_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return JobCardResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[JobCardItemResponse(**li) for li in result["line_items"]],
    )


@router.put(
    "/{job_card_id}",
    response_model=JobCardResponse,
    responses={
        400: {"description": "Validation error or invalid status transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Job card not found"},
    },
    summary="Update a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_job_card_endpoint(
    job_card_id: uuid.UUID,
    payload: JobCardUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a job card. Open/In Progress cards allow full edits;
    others only allow notes updates and status transitions.

    Status transitions: Open → In Progress → Completed → Invoiced.

    Requirements: 59.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    updates: dict = {}
    if payload.status is not None:
        updates["status"] = payload.status.value
    if payload.customer_id is not None:
        updates["customer_id"] = payload.customer_id
    if payload.vehicle_rego is not None:
        updates["vehicle_rego"] = payload.vehicle_rego
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.notes is not None:
        updates["notes"] = payload.notes
    if payload.line_items is not None:
        updates["line_items"] = [
            {
                "item_type": li.item_type.value,
                "description": li.description,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "sort_order": li.sort_order,
            }
            for li in payload.line_items
        ]

    try:
        result = await update_job_card(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            updates=updates,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return JobCardResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[JobCardItemResponse(**li) for li in result["line_items"]],
    )


@router.post(
    "/{job_card_id}/convert",
    response_model=JobCardConvertResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error or invalid status"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Job card not found"},
    },
    summary="Convert a completed job card to a draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def convert_job_card_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """One-click conversion of a completed job card to a Draft invoice
    pre-filled with all job card line items.

    Requirements: 59.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await convert_job_card_to_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    await db.commit()

    return JobCardConvertResponse(**result)
