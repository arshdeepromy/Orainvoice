"""Stock Items router — CRUD endpoints for catalogue-to-inventory stock items.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.inventory.stock_items_schemas import (
    AdjustStockItemRequest,
    CreateLocationRequest,
    CreateStockItemRequest,
    LocationListResponse,
    LocationResponse,
    StockItemListResponse,
    StockItemResponse,
    UpdateStockItemRequest,
)
from app.modules.inventory.stock_items_service import (
    adjust_stock_item,
    create_location,
    create_stock_item,
    delete_location,
    delete_stock_item,
    list_locations,
    list_stock_items,
    list_stock_movement_log,
    list_usage_history,
    update_stock_item,
)

router = APIRouter()


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Extract org_id and user_id from request state."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None
    return org_uuid, user_uuid


@router.get(
    "",
    response_model=StockItemListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List stock items",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_stock_items_endpoint(
    request: Request,
    search: str | None = Query(None, description="Search by name, part number, brand, or barcode"),
    below_threshold_only: bool = Query(False, description="Only items below threshold"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List stock items with optional search and threshold filtering.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await list_stock_items(
        db,
        org_id=org_uuid,
        search=search,
        below_threshold_only=below_threshold_only,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=StockItemResponse,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Catalogue item not found or inactive"},
        409: {"description": "Item already in stock"},
    },
    summary="Add a catalogue item to stock",
    dependencies=[require_role("org_admin")],
)
async def create_stock_item_endpoint(
    payload: CreateStockItemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new stock item from a catalogue item.

    Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        return await create_stock_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            payload=payload,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "already in stock" in error_msg.lower():
            return JSONResponse(status_code=409, content={"detail": error_msg})
        if "not found" in error_msg.lower() or "inactive" in error_msg.lower():
            return JSONResponse(status_code=404, content={"detail": error_msg})
        return JSONResponse(status_code=400, content={"detail": error_msg})


@router.get(
    "/locations",
    response_model=LocationListResponse,
    summary="List inventory locations",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_locations_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all reusable inventory locations for the organisation."""
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    return await list_locations(db, org_id=org_uuid)


@router.post(
    "/locations",
    response_model=LocationResponse,
    status_code=201,
    summary="Create an inventory location",
    dependencies=[require_role("org_admin")],
)
async def create_location_endpoint(
    payload: CreateLocationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new reusable inventory location."""
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    try:
        return await create_location(db, org_id=org_uuid, payload=payload)
    except ValueError as exc:
        error_msg = str(exc)
        status = 409 if "already exists" in error_msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": error_msg})


@router.delete(
    "/locations/{location_id}",
    status_code=204,
    summary="Delete an inventory location",
    dependencies=[require_role("org_admin")],
)
async def delete_location_endpoint(
    location_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete an inventory location. Does not affect existing stock item location text."""
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    try:
        await delete_location(db, org_id=org_uuid, location_id=location_id)
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": error_msg})


@router.get(
    "/usage-history",
    summary="List inventory usage history (sales from invoices)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def usage_history_endpoint(
    request: Request,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    """List stock movements of type 'sale' showing what was used, on which vehicle, and linked invoice."""
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    return await list_usage_history(db, org_id=org_uuid, limit=limit, offset=offset)


@router.get(
    "/movement-log",
    summary="List all stock movements (audit log)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def movement_log_endpoint(
    request: Request,
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db_session),
):
    """Full audit log of all stock movements — purchases, adjustments, sales, reservations."""
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    return await list_stock_movement_log(db, org_id=org_uuid, limit=limit)


@router.put(
    "/{stock_item_id}",
    response_model=StockItemResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Stock item not found"},
    },
    summary="Update a stock item",
    dependencies=[require_role("org_admin")],
)
async def update_stock_item_endpoint(
    stock_item_id: uuid.UUID,
    payload: UpdateStockItemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update stock item metadata (barcode, supplier, thresholds).

    Requirements: 9.3, 9.4
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        return await update_stock_item(
            db,
            org_id=org_uuid,
            stock_item_id=stock_item_id,
            payload=payload,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": error_msg})


@router.delete(
    "/{stock_item_id}",
    status_code=204,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Stock item not found"},
    },
    summary="Remove a stock item from inventory",
    dependencies=[require_role("org_admin")],
)
async def delete_stock_item_endpoint(
    stock_item_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a stock item from inventory.

    Requirements: 1.4
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        await delete_stock_item(
            db,
            org_id=org_uuid,
            stock_item_id=stock_item_id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": error_msg})


@router.post(
    "/{stock_item_id}/adjust",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Stock item not found"},
    },
    summary="Adjust stock quantity for a stock item",
    dependencies=[require_role("org_admin")],
)
async def adjust_stock_item_endpoint(
    stock_item_id: uuid.UUID,
    payload: AdjustStockItemRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Adjust stock quantity with reason recorded in audit log."""
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        return await adjust_stock_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            stock_item_id=stock_item_id,
            payload=payload,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": error_msg})
