"""Purchase order API router.

Endpoints:
- GET    /api/v2/purchase-orders              — list (paginated/filterable)
- POST   /api/v2/purchase-orders              — create
- GET    /api/v2/purchase-orders/{id}         — get
- PUT    /api/v2/purchase-orders/{id}         — update
- POST   /api/v2/purchase-orders/{id}/receive — receive goods
- PUT    /api/v2/purchase-orders/{id}/send    — send PO to supplier
- GET    /api/v2/purchase-orders/{id}/pdf     — generate PDF

**Validates: Requirement 16 — Purchase Order Module**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.purchase_orders.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderListResponse,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    ReceiveGoodsRequest,
)
from app.modules.purchase_orders.service import PurchaseOrderService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=PurchaseOrderListResponse, summary="List purchase orders")
async def list_purchase_orders(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    supplier_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PurchaseOrderService(db)
    pos, total = await svc.list_purchase_orders(
        org_id, page=page, page_size=page_size,
        status=status, supplier_id=supplier_id,
    )
    return PurchaseOrderListResponse(
        purchase_orders=[PurchaseOrderResponse.model_validate(po) for po in pos],
        total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=PurchaseOrderResponse, status_code=201, summary="Create purchase order")
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = PurchaseOrderService(db)
    po = await svc.create_purchase_order(org_id, payload, created_by=user_id)
    return PurchaseOrderResponse.model_validate(po)


@router.get("/{po_id}", response_model=PurchaseOrderResponse, summary="Get purchase order")
async def get_purchase_order(
    po_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PurchaseOrderService(db)
    po = await svc.get_purchase_order(org_id, po_id)
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return PurchaseOrderResponse.model_validate(po)


@router.put("/{po_id}", response_model=PurchaseOrderResponse, summary="Update purchase order")
async def update_purchase_order(
    po_id: UUID,
    payload: PurchaseOrderUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PurchaseOrderService(db)
    try:
        po = await svc.update_purchase_order(org_id, po_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return PurchaseOrderResponse.model_validate(po)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

@router.post("/{po_id}/receive", response_model=PurchaseOrderResponse, summary="Receive goods")
async def receive_goods(
    po_id: UUID,
    payload: ReceiveGoodsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    svc = PurchaseOrderService(db)
    try:
        po = await svc.receive_goods(org_id, po_id, payload, performed_by=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return PurchaseOrderResponse.model_validate(po)


@router.put("/{po_id}/send", response_model=PurchaseOrderResponse, summary="Send PO to supplier")
async def send_purchase_order(
    po_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PurchaseOrderService(db)
    try:
        po = await svc.send_purchase_order(org_id, po_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if po is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return PurchaseOrderResponse.model_validate(po)


@router.get("/{po_id}/pdf", summary="Generate PO PDF")
async def generate_pdf(
    po_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = PurchaseOrderService(db)
    try:
        pdf_data = await svc.generate_pdf(org_id, po_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return pdf_data
