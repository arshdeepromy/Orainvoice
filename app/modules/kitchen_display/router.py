"""Kitchen display API router — order management and WebSocket.

Endpoints (all under /api/v2/kitchen):
- GET /orders — list pending/preparing orders
- POST /orders — create a kitchen order
- GET /orders/{id} — get a single order
- PUT /orders/{id}/status — update order status
- PUT /orders/{id}/prepared — mark order as prepared
- GET /stations/{station}/orders — orders for a specific station
- WS /ws/kitchen/{org_id}/{station} — real-time updates

**Validates: Requirement — Kitchen Display Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.kitchen_display.schemas import (
    KitchenOrderCreate,
    KitchenOrderListResponse,
    KitchenOrderResponse,
    KitchenOrderStatusUpdate,
)
from app.modules.kitchen_display.service import KitchenService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("/orders", response_model=KitchenOrderListResponse, summary="List pending orders")
async def list_pending_orders(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    orders, total = await svc.get_pending_orders(org_id, skip=skip, limit=limit)
    return KitchenOrderListResponse(
        orders=[KitchenOrderResponse.model_validate(o) for o in orders],
        total=total,
    )


@router.post("/orders", response_model=KitchenOrderResponse, status_code=201, summary="Create kitchen order")
async def create_order(
    payload: KitchenOrderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    order = await svc.create_order(org_id, payload)
    return KitchenOrderResponse.model_validate(order)


@router.get("/orders/{order_id}", response_model=KitchenOrderResponse, summary="Get kitchen order")
async def get_order(
    order_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    order = await svc.get_order(org_id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Kitchen order not found")
    return KitchenOrderResponse.model_validate(order)


@router.put("/orders/{order_id}/status", response_model=KitchenOrderResponse, summary="Update order status")
async def update_order_status(
    order_id: UUID,
    payload: KitchenOrderStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    order = await svc.update_status(org_id, order_id, payload.status)
    if order is None:
        raise HTTPException(status_code=400, detail="Invalid status transition or order not found")
    return KitchenOrderResponse.model_validate(order)


@router.put("/orders/{order_id}/prepared", response_model=KitchenOrderResponse, summary="Mark order prepared")
async def mark_prepared(
    order_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    order = await svc.mark_prepared(org_id, order_id)
    if order is None:
        raise HTTPException(status_code=400, detail="Cannot mark as prepared or order not found")
    return KitchenOrderResponse.model_validate(order)


@router.get(
    "/stations/{station}/orders",
    response_model=KitchenOrderListResponse,
    summary="List orders by station",
)
async def list_orders_by_station(
    station: str,
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    orders, total = await svc.get_orders_by_station(org_id, station, skip=skip, limit=limit)
    return KitchenOrderListResponse(
        orders=[KitchenOrderResponse.model_validate(o) for o in orders],
        total=total,
    )


# --- Bulk creation from POS transaction (station routing) ---
from app.modules.kitchen_display.schemas import KitchenOrderBulkCreate
from app.modules.kitchen_display.redis_pubsub import publish_kitchen_event


@router.post(
    "/orders/bulk",
    response_model=list[KitchenOrderResponse],
    status_code=201,
    summary="Create kitchen orders from POS transaction with station routing",
)
async def create_orders_bulk(
    payload: KitchenOrderBulkCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = KitchenService(db)
    items = [item.model_dump() for item in payload.items]
    orders = await svc.create_orders_from_transaction(
        org_id,
        payload.pos_transaction_id,
        payload.table_id,
        items,
        station_map=payload.station_map,
    )
    responses = [KitchenOrderResponse.model_validate(o) for o in orders]
    # Publish events for each station
    for resp in responses:
        await publish_kitchen_event(
            str(org_id),
            resp.station,
            "order_created",
            {"order": resp.model_dump(mode="json")},
        )
    return responses
