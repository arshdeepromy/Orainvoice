"""Booking router — CRUD endpoints with calendar view support.

Requirements: 64.1, 64.2, 64.3, 64.4
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.bookings.schemas import (
    BookingConvertResponse,
    BookingConvertTarget,
    BookingCreate,
    BookingCreateResponse,
    BookingListResponse,
    BookingResponse,
    BookingSearchResult,
    BookingUpdate,
)
from app.modules.bookings.service import (
    convert_booking_to_invoice,
    convert_booking_to_job_card,
    create_booking,
    delete_booking,
    get_booking,
    list_bookings,
    update_booking,
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
    response_model=BookingCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a new booking",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_booking_endpoint(
    payload: BookingCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new appointment linked to a customer and optional vehicle.

    Requirements: 64.2, 64.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await create_booking(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            customer_id=payload.customer_id,
            vehicle_rego=payload.vehicle_rego,
            branch_id=payload.branch_id,
            service_type=payload.service_type,
            service_catalogue_id=payload.service_catalogue_id,
            scheduled_at=payload.scheduled_at,
            duration_minutes=payload.duration_minutes,
            notes=payload.notes,
            assigned_to=payload.assigned_to,
            send_confirmation=payload.send_confirmation,
            send_email_confirmation=payload.send_email_confirmation,
            send_sms_confirmation=payload.send_sms_confirmation,
            reminder_offset_hours=payload.reminder_offset_hours,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    confirmation_sent = result.pop("confirmation_sent", False)
    booking_resp = BookingResponse(**result)

    return BookingCreateResponse(
        booking=booking_resp,
        message="Booking created successfully",
        confirmation_sent=confirmation_sent,
    )


@router.get(
    "",
    response_model=BookingListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List bookings (calendar view)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_bookings_endpoint(
    request: Request,
    view: str = Query(default="week", regex="^(day|week|month)$", description="Calendar view type"),
    date: datetime | None = Query(default=None, description="Reference date for the view"),
    status: str | None = Query(default=None, description="Filter by booking status"),
    branch_id: uuid.UUID | None = Query(default=None, description="Filter by branch"),
    db: AsyncSession = Depends(get_db_session),
):
    """List appointments for a calendar view (day/week/month).

    Requirements: 64.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_bookings(
        db,
        org_id=org_uuid,
        view=view,
        date_param=date,
        status=status,
        branch_id=branch_id,
    )

    return BookingListResponse(
        bookings=[BookingSearchResult(**b) for b in result["bookings"]],
        total=result["total"],
        view=result["view"],
        start_date=result["start_date"],
        end_date=result["end_date"],
    )


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Booking not found"},
    },
    summary="Get a single booking",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_booking_endpoint(
    booking_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single booking by ID."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_booking(db, org_id=org_uuid, booking_id=booking_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return BookingResponse(**result)


@router.put(
    "/{booking_id}",
    response_model=BookingResponse,
    responses={
        400: {"description": "Validation error or invalid status transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Booking not found"},
    },
    summary="Update a booking",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_booking_endpoint(
    booking_id: uuid.UUID,
    payload: BookingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a booking. Scheduled/confirmed bookings allow full edits;
    terminal statuses only allow notes updates.

    Requirements: 64.2
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
    for field in ("customer_id", "vehicle_rego", "branch_id",
                   "service_type", "scheduled_at", "duration_minutes",
                   "notes", "assigned_to"):
        val = getattr(payload, field, None)
        if val is not None:
            updates[field] = val

    try:
        result = await update_booking(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            booking_id=booking_id,
            updates=updates,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return BookingResponse(**result)


@router.post(
    "/{booking_id}/convert",
    response_model=BookingConvertResponse,
    responses={
        400: {"description": "Booking cannot be converted in current status"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Booking not found"},
    },
    summary="Convert booking to job card or draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def convert_booking_endpoint(
    booking_id: uuid.UUID,
    request: Request,
    target: BookingConvertTarget = Query(
        ..., description="Conversion target: 'job_card' or 'invoice'"
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """One-click conversion of a booking to a Job Card or Draft invoice.

    Pre-fills the created entity with appointment details (customer, vehicle,
    service type, notes). Transitions the booking to 'completed'.

    Requirements: 64.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        if target == BookingConvertTarget.job_card:
            result = await convert_booking_to_job_card(
                db,
                org_id=org_uuid,
                user_id=user_uuid,
                booking_id=booking_id,
                ip_address=ip_address,
            )
        else:
            result = await convert_booking_to_invoice(
                db,
                org_id=org_uuid,
                user_id=user_uuid,
                booking_id=booking_id,
                ip_address=ip_address,
            )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return BookingConvertResponse(**result)


@router.delete(
    "/{booking_id}",
    responses={
        400: {"description": "Cannot cancel booking in current status"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Booking not found"},
    },
    summary="Cancel a booking",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def delete_booking_endpoint(
    booking_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel a booking (soft delete via status change).

    Requirements: 64.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await delete_booking(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            booking_id=booking_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})

    return result
