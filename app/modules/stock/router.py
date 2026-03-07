"""Stock movement API router.

Endpoints:
- GET  /api/v2/stock-movements       — list movements
- POST /api/v2/stock-adjustments     — manual adjustment
- POST /api/v2/stocktakes            — create/preview stocktake
- PUT  /api/v2/stocktakes/{id}/commit — commit stocktake

**Validates: Requirement 9.7, 9.8**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.products.service import ProductService
from app.modules.stock.schemas import (
    StockAdjustmentRequest,
    StockMovementListResponse,
    StockMovementResponse,
    StocktakeCreate,
)
from app.modules.stock.service import StockService

movements_router = APIRouter()
adjustments_router = APIRouter()
stocktakes_router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID | None:
    user_id = getattr(request.state, "user_id", None)
    return UUID(str(user_id)) if user_id else None


@movements_router.get(
    "", response_model=StockMovementListResponse, summary="List stock movements",
)
async def list_stock_movements(
    request: Request,
    product_id: UUID | None = Query(None),
    movement_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = StockService(db)
    movements, total = await svc.list_movements(
        org_id, product_id=product_id, movement_type=movement_type,
        page=page, page_size=page_size,
    )
    return StockMovementListResponse(
        movements=[StockMovementResponse.model_validate(m) for m in movements],
        total=total,
    )


@adjustments_router.post(
    "",
    response_model=StockMovementResponse,
    status_code=201,
    summary="Manual stock adjustment",
)
async def create_stock_adjustment(
    payload: StockAdjustmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    product_svc = ProductService(db)
    product = await product_svc.get_product(org_id, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    stock_svc = StockService(db)
    movement = await stock_svc.manual_adjustment(
        product, payload.quantity_change, payload.reason,
        performed_by=user_id, location_id=payload.location_id,
    )
    return StockMovementResponse.model_validate(movement)


@stocktakes_router.post(
    "", summary="Create stocktake (preview variance)",
)
async def create_stocktake(
    payload: StocktakeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    stock_svc = StockService(db)
    variance = await stock_svc.create_stocktake(
        org_id, payload.lines, location_id=payload.location_id,
    )
    return {"status": "preview", "lines": variance}


@stocktakes_router.put(
    "/{stocktake_id}/commit", summary="Commit stocktake adjustments",
)
async def commit_stocktake(
    stocktake_id: UUID,
    payload: StocktakeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)
    stock_svc = StockService(db)
    movements = await stock_svc.commit_stocktake(
        org_id, payload.lines,
        performed_by=user_id, location_id=payload.location_id,
    )
    return {
        "status": "committed",
        "adjustments_applied": len(movements),
        "movements": [StockMovementResponse.model_validate(m) for m in movements],
    }
