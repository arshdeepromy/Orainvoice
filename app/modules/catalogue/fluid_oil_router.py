"""Fluid/Oil products API router."""
from __future__ import annotations
import uuid
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse

from app.core.database import get_db_session
from app.modules.catalogue.fluid_oil_models import FluidOilProduct
from app.modules.catalogue.fluid_oil_schemas import FluidOilCreate, FluidOilResponse, FluidOilListResponse

router = APIRouter()


def _get_org_id(request: Request) -> uuid.UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return uuid.UUID(str(org_id))


def _get_user_id(request: Request) -> uuid.UUID | None:
    user_id = getattr(request.state, "user_id", None)
    return uuid.UUID(str(user_id)) if user_id else None


@router.get("", response_model=FluidOilListResponse, summary="List fluid/oil products")
async def list_products(
    request: Request,
    active_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    stmt = select(FluidOilProduct).where(FluidOilProduct.org_id == org_id)
    if active_only:
        stmt = stmt.where(FluidOilProduct.is_active.is_(True))
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0
    stmt = stmt.order_by(FluidOilProduct.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    products = list(result.scalars().all())
    return FluidOilListResponse(
        products=[FluidOilResponse.model_validate(p) for p in products],
        total=total,
    )


@router.post("", response_model=FluidOilResponse, status_code=201, summary="Create fluid/oil product")
async def create_product(
    payload: FluidOilCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    user_id = _get_user_id(request)

    # Auto-calculate derived fields
    total_volume = None
    cost_per_unit = None
    margin = None
    margin_pct = None

    if payload.qty_per_pack and payload.total_quantity:
        total_volume = payload.qty_per_pack * payload.total_quantity

    if payload.purchase_price and total_volume and total_volume > 0:
        cost_per_unit = payload.purchase_price / total_volume

    if payload.sell_price_per_unit and cost_per_unit:
        margin = payload.sell_price_per_unit - cost_per_unit
        if cost_per_unit > 0:
            margin_pct = (margin / cost_per_unit) * 100

    product = FluidOilProduct(
        org_id=org_id,
        fluid_type=payload.fluid_type,
        oil_type=payload.oil_type,
        grade=payload.grade,
        synthetic_type=payload.synthetic_type,
        product_name=payload.product_name,
        brand_name=payload.brand_name,
        description=payload.description,
        pack_size=payload.pack_size,
        qty_per_pack=payload.qty_per_pack,
        unit_type=payload.unit_type,
        container_type=payload.container_type,
        total_quantity=payload.total_quantity,
        total_volume=total_volume,
        purchase_price=payload.purchase_price,
        gst_mode=payload.gst_mode,
        cost_per_unit=cost_per_unit,
        sell_price_per_unit=payload.sell_price_per_unit,
        margin=margin,
        margin_pct=margin_pct,
        current_stock_volume=total_volume or Decimal("0"),
        created_by=user_id,
    )
    db.add(product)
    await db.flush()
    return FluidOilResponse.model_validate(product)


@router.delete("/{product_id}", status_code=200, summary="Delete fluid/oil product")
async def delete_product(
    product_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    try:
        pid = uuid.UUID(product_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid ID"})
    result = await db.execute(
        select(FluidOilProduct).where(FluidOilProduct.id == pid, FluidOilProduct.org_id == org_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse(status_code=404, content={"detail": "Product not found"})
    await db.delete(product)
    await db.flush()
    return {"message": "Product deleted"}


@router.put("/{product_id}/toggle-active", status_code=200, summary="Toggle active status")
async def toggle_active(
    product_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    try:
        pid = uuid.UUID(product_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid ID"})
    result = await db.execute(
        select(FluidOilProduct).where(FluidOilProduct.id == pid, FluidOilProduct.org_id == org_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse(status_code=404, content={"detail": "Product not found"})
    product.is_active = not product.is_active
    await db.flush()
    return FluidOilResponse.model_validate(product)


@router.put("/{product_id}", response_model=FluidOilResponse, summary="Update fluid/oil product")
async def update_product(
    product_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    try:
        pid = uuid.UUID(product_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid ID"})
    result = await db.execute(
        select(FluidOilProduct).where(FluidOilProduct.id == pid, FluidOilProduct.org_id == org_id)
    )
    product = result.scalar_one_or_none()
    if not product:
        return JSONResponse(status_code=404, content={"detail": "Product not found"})

    body = await request.json()
    for field in ["fluid_type", "oil_type", "grade", "synthetic_type", "product_name",
                   "brand_name", "description", "pack_size", "unit_type", "container_type", "gst_mode"]:
        if field in body:
            setattr(product, field, body[field])
    for nfield in ["qty_per_pack", "total_quantity", "purchase_price", "sell_price_per_unit"]:
        if nfield in body and body[nfield] is not None:
            setattr(product, nfield, Decimal(str(body[nfield])))

    # Recalculate derived fields
    if product.qty_per_pack and product.total_quantity:
        product.total_volume = product.qty_per_pack * product.total_quantity
    if product.purchase_price and product.total_volume and product.total_volume > 0:
        product.cost_per_unit = product.purchase_price / product.total_volume
    if product.sell_price_per_unit and product.cost_per_unit:
        product.margin = product.sell_price_per_unit - product.cost_per_unit
        if product.cost_per_unit > 0:
            product.margin_pct = (product.margin / product.cost_per_unit) * 100

    await db.flush()
    return FluidOilResponse.model_validate(product)
