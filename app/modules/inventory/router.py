"""Inventory router — Stock tracking, reorder alerts, and stock reports.

Requirements: 62.1, 62.2, 62.3, 62.4, 62.5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.inventory.schemas import (
    FluidReorderAlertListResponse,
    FluidStockAdjustmentRequest,
    FluidStockLevelListResponse,
    ReorderAlertListResponse,
    StockAdjustmentRequest,
    StockAdjustmentResponse,
    StockLevelListResponse,
    StockReportResponse,
)
from app.modules.inventory.service import (
    adjust_fluid_stock,
    adjust_stock,
    get_fluid_reorder_alerts,
    get_fluid_stock_levels,
    get_reorder_alerts,
    get_stock_levels,
    get_stock_report,
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


@router.get(
    "/stock",
    response_model=StockLevelListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List stock levels for all parts",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_stock_levels_endpoint(
    request: Request,
    below_threshold_only: bool = Query(False, description="Only parts below threshold"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List stock levels for all active parts in the organisation.

    Requirements: 62.1, 62.4
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await get_stock_levels(
        db,
        org_id=org_uuid,
        below_threshold_only=below_threshold_only,
        limit=limit,
        offset=offset,
    )
    return result


@router.put(
    "/stock/{part_id}",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Part not found"},
    },
    summary="Manually adjust stock level for a part",
    dependencies=[require_role("org_admin")],
)
async def adjust_stock_endpoint(
    request: Request,
    part_id: uuid.UUID,
    body: StockAdjustmentRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Manually adjust stock level with reason recorded in audit log.

    Requirements: 62.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await adjust_stock(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            part_id=part_id,
            quantity_change=body.quantity_change,
            reason=body.reason,
            ip_address=ip_address,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return {"message": "Stock adjusted successfully", **result}


@router.get(
    "/stock/reorder-alerts",
    response_model=ReorderAlertListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get parts needing reorder",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def reorder_alerts_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get parts where current stock is at or below the minimum threshold.

    Requirements: 62.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await get_reorder_alerts(db, org_id=org_uuid)


@router.get(
    "/stock/report",
    response_model=StockReportResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Stock report with levels, alerts, and movement history",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def stock_report_endpoint(
    request: Request,
    movement_limit: int = Query(50, ge=1, le=200, description="Max movement records"),
    db: AsyncSession = Depends(get_db_session),
):
    """Generate stock report: current levels, parts below threshold, movement history.

    Requirements: 62.4
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await get_stock_report(db, org_id=org_uuid, movement_limit=movement_limit)


# ---------------------------------------------------------------------------
# Fluid / Oil stock endpoints — Requirements: 4.1, 4.2, 4.3, 4.5
# ---------------------------------------------------------------------------


@router.get(
    "/fluid-stock",
    response_model=FluidStockLevelListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List fluid/oil stock levels",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_fluid_stock_levels_endpoint(
    request: Request,
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List stock levels for all active fluid/oil products in the organisation.

    Requirements: 4.1, 4.5
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await get_fluid_stock_levels(db, org_id=org_uuid, limit=limit, offset=offset)


@router.get(
    "/fluid-stock/reorder-alerts",
    response_model=FluidReorderAlertListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get fluids/oils needing reorder",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def fluid_reorder_alerts_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get fluid/oil products where current stock is at or below the minimum threshold.

    Requirements: 4.3, 4.5
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await get_fluid_reorder_alerts(db, org_id=org_uuid)


@router.put(
    "/fluid-stock/{product_id}",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Product not found"},
    },
    summary="Adjust fluid/oil stock volume",
    dependencies=[require_role("org_admin")],
)
async def adjust_fluid_stock_endpoint(
    request: Request,
    product_id: uuid.UUID,
    body: FluidStockAdjustmentRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Manually adjust fluid/oil stock volume with reason recorded in audit log.

    Requirements: 4.2, 4.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await adjust_fluid_stock(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            product_id=product_id,
            volume_change=body.volume_change,
            reason=body.reason,
            ip_address=ip_address,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return {"message": "Fluid stock adjusted successfully", **result}


# ---------------------------------------------------------------------------
# Supplier management endpoints — Requirements: 63.1, 63.2, 63.3
# ---------------------------------------------------------------------------

from fastapi.responses import Response

from app.modules.inventory.schemas import (
    PartSupplierLink,
    PartSupplierLinkResponse,
    PurchaseOrderRequest,
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
)
from app.modules.inventory.service import (
    create_supplier,
    generate_purchase_order_pdf,
    link_part_to_supplier,
    list_suppliers,
)


@router.get(
    "/suppliers",
    response_model=SupplierListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List suppliers",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_suppliers_endpoint(
    request: Request,
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List all suppliers for the organisation.

    Requirements: 63.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await list_suppliers(db, org_id=org_uuid, limit=limit, offset=offset)


@router.post(
    "/suppliers",
    response_model=SupplierResponse,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create a supplier",
    dependencies=[require_role("org_admin")],
)
async def create_supplier_endpoint(
    request: Request,
    body: SupplierCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new supplier record.

    Requirements: 63.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    return await create_supplier(
        db,
        org_id=org_uuid,
        name=body.name,
        contact_name=body.contact_name,
        email=body.email,
        phone=body.phone,
        address=body.address,
        account_number=body.account_number,
    )


@router.post(
    "/suppliers/{supplier_id}/link-part",
    response_model=PartSupplierLinkResponse,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Supplier or part not found"},
    },
    summary="Link a part to a supplier",
    dependencies=[require_role("org_admin")],
)
async def link_part_to_supplier_endpoint(
    request: Request,
    supplier_id: uuid.UUID,
    body: PartSupplierLink,
    db: AsyncSession = Depends(get_db_session),
):
    """Link a part to a supplier with supplier-specific part number and cost.

    Requirements: 63.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        return await link_part_to_supplier(
            db,
            org_id=org_uuid,
            supplier_id=supplier_id,
            part_id=uuid.UUID(body.part_id),
            supplier_part_number=body.supplier_part_number,
            supplier_cost=body.supplier_cost,
            is_preferred=body.is_preferred,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        return JSONResponse(status_code=status, content={"detail": str(exc)})


@router.post(
    "/purchase-orders",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "Purchase order PDF"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Supplier not found"},
    },
    summary="Generate purchase order PDF",
    dependencies=[require_role("org_admin")],
)
async def generate_purchase_order_endpoint(
    request: Request,
    body: PurchaseOrderRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a purchase order PDF for a supplier.

    Requirements: 63.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        pdf_bytes = await generate_purchase_order_pdf(
            db,
            org_id=org_uuid,
            supplier_id=uuid.UUID(body.supplier_id),
            items=[item.model_dump() for item in body.items],
            notes=body.notes,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=purchase_order.pdf"},
    )
