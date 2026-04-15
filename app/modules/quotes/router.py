"""Quote router — CRUD endpoints.

Requirements: 58.1, 58.2, 58.4, 58.6
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.quotes.schemas import (
    QuoteConvertResponse,
    QuoteCreate,
    QuoteCreateResponse,
    QuoteLineItemResponse,
    QuoteListResponse,
    QuoteResponse,
    QuoteSearchResult,
    QuoteSendResponse,
    QuoteUpdate,
)
from app.modules.quotes.service import (
    convert_quote_to_invoice,
    create_quote,
    delete_quote,
    get_quote,
    list_quotes,
    send_quote,
    update_quote,
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
    response_model=QuoteCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a new quote",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def create_quote_endpoint(
    payload: QuoteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new quote with customer, vehicle, and line items.

    Assigns a sequential quote number with the org's configurable prefix.
    Calculates subtotal, GST, and total automatically.

    Requirements: 58.1, 58.4, 58.6
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
            "hours": li.hours,
            "hourly_rate": li.hourly_rate,
            "is_gst_exempt": li.is_gst_exempt,
            "warranty_note": li.warranty_note,
            "sort_order": li.sort_order,
        }
        for li in payload.line_items
    ]

    try:
        result = await create_quote(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            customer_id=payload.customer_id,
            vehicle_rego=payload.vehicle_rego,
            vehicle_make=payload.vehicle_make,
            vehicle_model=payload.vehicle_model,
            vehicle_year=payload.vehicle_year,
            validity_days=payload.validity_days,
            line_items_data=line_items_data,
            notes=payload.notes,
            terms=payload.terms,
            subject=payload.subject,
            project_id=payload.project_id,
            discount_type=payload.discount_type,
            discount_value=payload.discount_value,
            shipping_charges=payload.shipping_charges,
            adjustment=payload.adjustment,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception:
        await db.rollback()
        raise

    quote_resp = QuoteResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[QuoteLineItemResponse(**li) for li in result["line_items"]],
    )

    return QuoteCreateResponse(
        quote=quote_resp,
        message="Quote created successfully",
    )


@router.get(
    "",
    response_model=QuoteListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List and search quotes",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_quotes_endpoint(
    request: Request,
    search: str | None = Query(default=None, description="Search by quote number, rego, or customer name"),
    status: str | None = Query(default=None, description="Filter by quote status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """Search and filter quotes with pagination."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_quotes(
        db,
        org_id=org_uuid,
        search=search,
        status=status,
        limit=limit,
        offset=offset,
        branch_id=getattr(request.state, "branch_id", None),
    )

    return QuoteListResponse(
        quotes=[QuoteSearchResult(**q) for q in result["quotes"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


@router.get(
    "/{quote_id}",
    response_model=QuoteResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Quote not found"},
    },
    summary="Get a single quote",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_quote_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retrieve a single quote by ID."""
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_quote(db, org_id=org_uuid, quote_id=quote_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return QuoteResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[QuoteLineItemResponse(**li) for li in result["line_items"]],
    )


@router.put(
    "/{quote_id}",
    response_model=QuoteResponse,
    responses={
        400: {"description": "Validation error or invalid status transition"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Quote not found"},
    },
    summary="Update a quote",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def update_quote_endpoint(
    quote_id: uuid.UUID,
    payload: QuoteUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a quote. Draft quotes allow full edits; others only allow
    status transitions and notes updates.

    Requirements: 58.2
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
    if payload.vehicle_make is not None:
        updates["vehicle_make"] = payload.vehicle_make
    if payload.vehicle_model is not None:
        updates["vehicle_model"] = payload.vehicle_model
    if payload.vehicle_year is not None:
        updates["vehicle_year"] = payload.vehicle_year
    if payload.project_id is not None:
        updates["project_id"] = payload.project_id
    if payload.validity_days is not None:
        updates["validity_days"] = payload.validity_days
    if payload.notes is not None:
        updates["notes"] = payload.notes
    if payload.terms is not None:
        updates["terms"] = payload.terms
    if payload.subject is not None:
        updates["subject"] = payload.subject
    if payload.discount_type is not None:
        updates["discount_type"] = payload.discount_type
    if payload.discount_value is not None:
        updates["discount_value"] = payload.discount_value
    if payload.shipping_charges is not None:
        updates["shipping_charges"] = payload.shipping_charges
    if payload.adjustment is not None:
        updates["adjustment"] = payload.adjustment
    if payload.line_items is not None:
        updates["line_items"] = [
            {
                "item_type": li.item_type.value,
                "description": li.description,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "hours": li.hours,
                "hourly_rate": li.hourly_rate,
                "is_gst_exempt": li.is_gst_exempt,
                "warranty_note": li.warranty_note,
                "sort_order": li.sort_order,
            }
            for li in payload.line_items
        ]

    try:
        result = await update_quote(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            quote_id=quote_id,
            updates=updates,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})
    except Exception:
        await db.rollback()
        raise

    return QuoteResponse(
        **{k: v for k, v in result.items() if k != "line_items"},
        line_items=[QuoteLineItemResponse(**li) for li in result["line_items"]],
    )



@router.post(
    "/{quote_id}/send",
    response_model=QuoteSendResponse,
    responses={
        400: {"description": "Quote cannot be sent in current status"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Quote not found"},
    },
    summary="Send quote to customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def send_quote_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a branded PDF quote and email it to the customer.

    Transitions the quote from Draft to Sent status.

    Requirements: 58.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await send_quote(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            quote_id=quote_id,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})
    except Exception:
        await db.rollback()
        raise

    return QuoteSendResponse(**result)


@router.post(
    "/{quote_id}/convert",
    response_model=QuoteConvertResponse,
    responses={
        400: {"description": "Quote cannot be converted in current status"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Quote not found"},
    },
    summary="Convert quote to draft invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def convert_quote_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """One-click conversion of a quote to a Draft invoice pre-filled
    with all quote details (customer, vehicle, line items).

    Requirements: 58.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await convert_quote_to_invoice(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            quote_id=quote_id,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})
    except Exception:
        await db.rollback()
        raise

    return QuoteConvertResponse(**result)


@router.delete(
    "/{quote_id}",
    responses={
        400: {"description": "Quote cannot be deleted in current status"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Quote not found"},
    },
    summary="Delete a quote",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def delete_quote_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a quote. Only draft, declined, or expired quotes can be deleted."""
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await delete_quote(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            quote_id=quote_id,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        error_msg = str(exc)
        status_code = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status_code, content={"detail": error_msg})
    except Exception:
        await db.rollback()
        raise

    return result
