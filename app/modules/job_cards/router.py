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
    AssignJobRequest,
    AssignJobResponse,
    CompleteJobResponse,
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
    TimeEntryResponse,
    TimerStatusResponse,
)
from app.modules.job_cards.service import (
    assign_job,
    combine_job_cards_to_invoice,
    complete_job,
    convert_job_card_to_invoice,
    create_job_card,
    get_job_card,
    get_timer_entries,
    list_job_cards,
    start_timer,
    stop_timer,
    update_job_card,
)

router = APIRouter()


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)
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
            service_type_id=payload.service_type_id,
            service_type_values=payload.service_type_values,
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
        branch_id=getattr(request.state, "branch_id", None),
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
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error loading job card: {exc}"},
        )

    # Separate line_items for schema conversion; pass everything else through
    line_items_raw = result.pop("line_items", [])
    try:
        return JobCardResponse(
            **result,
            line_items=[JobCardItemResponse(**li) for li in line_items_raw],
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error serializing job card: {exc}"},
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
    if payload.service_type_id is not None:
        updates["service_type_id"] = payload.service_type_id
    if payload.service_type_values is not None:
        updates["service_type_values"] = payload.service_type_values

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


@router.post(
    "/{job_card_id}/timer/start",
    response_model=TimeEntryResponse,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Not assigned to this job"},
        404: {"description": "Job card not found"},
        409: {"description": "Timer already running"},
    },
    summary="Start a timer on a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def start_timer_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new time entry with started_at set to the current server timestamp.

    Requirements: 7.1, 7.3, 7.6
    """
    org_uuid, user_uuid, _ = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)

    try:
        result = await start_timer(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            role=role or "",
        )
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        error_msg = str(exc)
        if "already running" in error_msg.lower():
            status_code = 409
        elif "not found" in error_msg.lower():
            status_code = 404
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return TimeEntryResponse(**result)


@router.post(
    "/{job_card_id}/timer/stop",
    response_model=TimeEntryResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Not assigned to this job"},
        404: {"description": "No active timer or job card not found"},
    },
    summary="Stop the active timer on a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def stop_timer_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Stop the active time entry, setting stopped_at and calculating duration_minutes.

    Requirements: 7.2, 7.4, 7.6
    """
    org_uuid, user_uuid, _ = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)

    try:
        result = await stop_timer(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            role=role or "",
        )
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        error_msg = str(exc)
        if "no active timer" in error_msg.lower():
            status_code = 404
        elif "not found" in error_msg.lower():
            status_code = 404
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return TimeEntryResponse(**result)


@router.get(
    "/{job_card_id}/timer",
    response_model=TimerStatusResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get all time entries for a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_timer_entries_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all time entries for a job card with an active timer flag.

    Requirements: 7.5, 7.6
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await get_timer_entries(
        db,
        org_id=org_uuid,
        job_card_id=job_card_id,
    )

    return TimerStatusResponse(
        entries=[TimeEntryResponse(**e) for e in result["entries"]],
        is_active=result["is_active"],
    )

@router.post(
    "/{job_card_id}/complete",
    response_model=CompleteJobResponse,
    responses={
        400: {"description": "Invalid status transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Job card not found"},
        500: {"description": "Invoice creation failed"},
    },
    summary="Complete a job and create a draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def complete_job_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Stop any active timer, mark job as completed, and auto-create a draft invoice.

    Requirements: 6.3, 8.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)

    try:
        result = await complete_job(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            role=role or "",
            ip_address=ip_address,
        )
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            status_code = 404
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Invoice creation failed: {exc}"},
        )

    return CompleteJobResponse(**result)


@router.put(
    "/{job_card_id}/assign",
    response_model=AssignJobResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Not allowed to assign to another user"},
        404: {"description": "Job card not found"},
    },
    summary="Assign or reassign a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def assign_job_endpoint(
    job_card_id: uuid.UUID,
    payload: AssignJobRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Assign or reassign a job card to a staff member.

    Non-admin users can only assign to themselves. Admins can assign to any
    active staff member. An optional takeover_note records the reassignment
    reason with the previous assignee's name and timestamp.

    Requirements: 8.5, 8.6, 8.7, 8.8
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)

    try:
        result = await assign_job(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            role=role or "",
            new_assignee_id=payload.new_assignee_id,
            takeover_note=payload.takeover_note,
        )
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"detail": str(exc)})
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            status_code = 404
        else:
            status_code = 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    jc_resp = JobCardResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[JobCardItemResponse(**li) for li in result["line_items"]],
    )

    return AssignJobResponse(job_card=jc_resp)


