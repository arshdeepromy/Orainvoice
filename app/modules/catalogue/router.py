"""Catalogue router — Service, Parts, and Labour Rate CRUD endpoints.

Requirements: 27.1, 27.2, 27.3, 28.1, 28.2, 28.3
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.catalogue.schemas import (
    ItemCreateRequest,
    ItemCreateResponse,
    ItemListResponse,
    ItemResponse,
    ItemUpdateRequest,
    ItemUpdateResponse,
    LabourRateCreateRequest,
    LabourRateCreateResponse,
    LabourRateListResponse,
    LabourRateResponse,
    LabourRateUpdateRequest,
    LabourRateResponse,
    PartCreateRequest,
    PartCreateResponse,
    PartListResponse,
    PartResponse,
    ServiceCreateRequest,
    ServiceCreateResponse,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdateRequest,
    ServiceUpdateResponse,
)
from app.modules.catalogue.service import (
    _compute_pricing,
    _part_to_dict,
    create_item,
    create_labour_rate,
    create_part,
    list_items,
    list_labour_rates,
    list_parts,
    update_item,
)
from app.modules.catalogue.models import ItemsCatalogue, PartsCatalogue

router = APIRouter()

ALLOWED_PACKAGING_TYPES = {"box", "carton", "pack", "bag", "pallet", "single"}


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


# ===========================================================================
# Items Catalogue endpoints — Requirements: 2.1, 2.2, 2.3, 2.4, 2.8, 2.9
# ===========================================================================


@router.get(
    "/items",
    response_model=ItemListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List items catalogue entries",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_items_endpoint(
    request: Request,
    active_only: bool = Query(False, description="Return only active items"),
    category: str | None = Query(None, description="Filter by category"),
    search: str | None = Query(None, description="Search items by name (case-insensitive)"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List items catalogue entries for the organisation.

    Supports filtering by active status, category, and name search.

    Requirements: 2.1, 2.5
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_items(
        db,
        org_id=org_uuid,
        active_only=active_only,
        category=category,
        search=search,
        limit=limit,
        offset=offset,
    )

    return ItemListResponse(
        items=[ItemResponse(**i) for i in result["items"]],
        total=result["total"],
    )


@router.post(
    "/items",
    response_model=ItemCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create an items catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def create_item_endpoint(
    payload: ItemCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new item in the organisation's catalogue.

    Requirements: 2.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        item_data = await create_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            name=payload.name,
            description=payload.description,
            default_price=payload.default_price,
            is_gst_exempt=payload.is_gst_exempt,
            gst_inclusive=getattr(payload, 'gst_inclusive', False),
            category=payload.category,
            is_active=payload.is_active,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return ItemCreateResponse(
        message="Item created",
        item=ItemResponse(**item_data),
    )


@router.put(
    "/items/{item_id}",
    response_model=ItemUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Item not found"},
    },
    summary="Update an items catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def update_item_endpoint(
    item_id: str,
    payload: ItemUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing items catalogue entry. Only provided fields
    are changed.

    Requirements: 2.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        item_uuid = uuid.UUID(item_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid item ID format"},
        )

    update_kwargs = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }

    try:
        item_data = await update_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            item_id=item_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    return ItemUpdateResponse(
        message="Item updated",
        item=ItemResponse(**item_data),
    )


@router.delete(
    "/items/{item_id}",
    status_code=200,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Item not found"},
    },
    summary="Hard-delete an items catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def delete_item_endpoint(
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete an item from the catalogue."""
    from sqlalchemy import select as _sel
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    try:
        item_uuid = uuid.UUID(item_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid item ID format"})
    result = await db.execute(
        _sel(ItemsCatalogue).where(ItemsCatalogue.id == item_uuid, ItemsCatalogue.org_id == org_uuid)
    )
    item = result.scalar_one_or_none()
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Item not found"})
    try:
        await db.delete(item)
        await db.flush()
    except Exception as exc:
        err_str = str(exc)
        if "ForeignKeyViolationError" in err_str or "foreign key" in err_str.lower():
            return JSONResponse(status_code=409, content={"detail": "Cannot delete: this item is referenced by existing invoices or bookings. Deactivate it instead."})
        raise
    return {"message": "Item deleted"}


# ===========================================================================
# Delete endpoints for services and parts
# ===========================================================================

@router.delete(
    "/services/{service_id}",
    status_code=200,
    summary="Hard-delete a service catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def delete_service_endpoint(
    service_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a service from the catalogue."""
    from sqlalchemy import select as _sel
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    try:
        item_uuid = uuid.UUID(service_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid service ID format"})
    result = await db.execute(
        _sel(ItemsCatalogue).where(ItemsCatalogue.id == item_uuid, ItemsCatalogue.org_id == org_uuid)
    )
    item = result.scalar_one_or_none()
    if not item:
        return JSONResponse(status_code=404, content={"detail": "Service not found"})
    try:
        await db.delete(item)
        await db.flush()
    except Exception as exc:
        err_str = str(exc)
        if "ForeignKeyViolationError" in err_str or "foreign key" in err_str.lower():
            return JSONResponse(status_code=409, content={"detail": "Cannot delete: this service is referenced by existing bookings or invoices. Deactivate it instead."})
        raise
    return {"message": "Service deleted"}


@router.delete(
    "/parts/{part_id}",
    status_code=200,
    summary="Hard-delete a parts catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def delete_part_endpoint(
    part_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a part from the catalogue."""
    from sqlalchemy import select as _sel
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})
    try:
        part_uuid = uuid.UUID(part_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid part ID format"})
    result = await db.execute(
        _sel(PartsCatalogue).where(PartsCatalogue.id == part_uuid, PartsCatalogue.org_id == org_uuid)
    )
    part = result.scalar_one_or_none()
    if not part:
        return JSONResponse(status_code=404, content={"detail": "Part not found"})
    try:
        await db.delete(part)
        await db.flush()
    except Exception as exc:
        err_str = str(exc)
        if "ForeignKeyViolationError" in err_str or "foreign key" in err_str.lower():
            return JSONResponse(status_code=409, content={"detail": "Cannot delete: this part is referenced by existing purchase orders or invoices. Deactivate it instead."})
        raise
    return {"message": "Part deleted"}


# ===========================================================================
# Legacy Service endpoints — backward compatibility
# ===========================================================================


@router.get(
    "/services",
    response_model=ServiceListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List service catalogue entries",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_services_endpoint(
    request: Request,
    active_only: bool = Query(False, description="Return only active services"),
    category: str | None = Query(None, description="Filter by category"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """Legacy proxy — list service catalogue entries for the organisation.

    Proxies to ``list_items()`` and returns the result using the legacy
    ``ServiceListResponse`` schema (key ``services`` instead of ``items``).

    Requirements: 2.6
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_items(
        db,
        org_id=org_uuid,
        active_only=active_only,
        category=category,
        limit=limit,
        offset=offset,
    )

    return ServiceListResponse(
        services=[ServiceResponse(**s) for s in result["items"]],
        total=result["total"],
    )


@router.post(
    "/services",
    response_model=ServiceCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create a service catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def create_service_endpoint(
    payload: ServiceCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Legacy proxy — create a new service in the organisation's catalogue.

    Proxies to ``create_item()`` and returns the result using the legacy
    ``ServiceCreateResponse`` schema.

    Requirements: 2.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        item_data = await create_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            name=payload.name,
            description=payload.description,
            default_price=payload.default_price,
            is_gst_exempt=payload.is_gst_exempt,
            gst_inclusive=getattr(payload, 'gst_inclusive', False),
            category=payload.category,
            is_active=payload.is_active,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return ServiceCreateResponse(
        message="Service created",
        service=ServiceResponse(**item_data),
    )


@router.put(
    "/services/{service_id}",
    response_model=ServiceUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Service not found"},
    },
    summary="Update a service catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def update_service_endpoint(
    service_id: str,
    payload: ServiceUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Legacy proxy — update an existing service catalogue entry.

    Proxies to ``update_item()`` and returns the result using the legacy
    ``ServiceUpdateResponse`` schema.

    Requirements: 2.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        svc_uuid = uuid.UUID(service_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid service ID format"},
        )

    update_kwargs = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }

    try:
        item_data = await update_item(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            item_id=svc_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 404 if "not found" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    return ServiceUpdateResponse(
        message="Service updated",
        service=ServiceResponse(**item_data),
    )


# ===========================================================================
# Parts Catalogue endpoints — Requirements: 28.1, 28.2
# ===========================================================================


@router.get(
    "/parts",
    response_model=PartListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List parts catalogue entries",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_parts_endpoint(
    request: Request,
    active_only: bool = Query(False, description="Return only active parts"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List parts catalogue entries for the organisation.

    Ad-hoc parts can be added directly on invoices without pre-loading
    (Req 28.2) — this endpoint returns only pre-loaded catalogue parts.

    Requirements: 28.1, 28.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_parts(
        db,
        org_id=org_uuid,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )

    return PartListResponse(
        parts=[PartResponse(**p) for p in result["parts"]],
        total=result["total"],
    )


@router.post(
    "/parts",
    response_model=PartCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create a parts catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def create_part_endpoint(
    payload: PartCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Pre-load a part into the organisation's catalogue.

    Parts can also be added ad-hoc per invoice without pre-loading
    (Req 28.2).

    Requirements: 28.1, 7.1, 7.5, 7.6
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Validate packaging_type against allowed values (Req 7.6)
    if payload.packaging_type is not None and payload.packaging_type not in ALLOWED_PACKAGING_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid packaging_type '{payload.packaging_type}'. Must be one of: {', '.join(sorted(ALLOWED_PACKAGING_TYPES))}",
        )

    # Validate qty_per_pack is positive when provided (Req 7.5)
    if payload.qty_per_pack is not None and payload.qty_per_pack <= 0:
        raise HTTPException(
            status_code=422,
            detail="qty_per_pack must be a positive integer",
        )

    # Validate total_packs is positive when provided (Req 7.5)
    if payload.total_packs is not None and payload.total_packs <= 0:
        raise HTTPException(
            status_code=422,
            detail="total_packs must be a positive integer",
        )

    try:
        part_data = await create_part(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            name=payload.name,
            part_number=payload.part_number,
            description=payload.description,
            part_type=payload.part_type,
            category_id=payload.category_id,
            brand=payload.brand,
            supplier_id=payload.supplier_id,
            default_price=payload.default_price,
            is_gst_exempt=getattr(payload, 'is_gst_exempt', False),
            gst_inclusive=getattr(payload, 'gst_inclusive', False),
            supplier=payload.supplier,
            is_active=payload.is_active,
            min_stock_threshold=payload.min_stock_threshold,
            reorder_quantity=payload.reorder_quantity,
            purchase_price=payload.purchase_price,
            packaging_type=payload.packaging_type,
            qty_per_pack=payload.qty_per_pack,
            total_packs=payload.total_packs,
            sell_price_per_unit=payload.sell_price_per_unit,
            gst_mode=payload.gst_mode,
            tyre_width=payload.tyre_width,
            tyre_profile=payload.tyre_profile,
            tyre_rim_dia=payload.tyre_rim_dia,
            tyre_load_index=payload.tyre_load_index,
            tyre_speed_index=payload.tyre_speed_index,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return PartCreateResponse(
        message="Part created",
        part=PartResponse(**part_data),
    )



@router.put(
    "/parts/{part_id}",
    response_model=PartResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Part not found"},
    },
    summary="Update a parts catalogue entry",
    dependencies=[require_role("org_admin")],
)
async def update_part_endpoint(
    part_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing part in the catalogue."""
    from sqlalchemy import select as _sel
    from sqlalchemy.orm import selectinload

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    result = await db.execute(
        _sel(PartsCatalogue)
        .where(PartsCatalogue.id == part_id, PartsCatalogue.org_id == org_uuid)
        .options(selectinload(PartsCatalogue.category), selectinload(PartsCatalogue.supplier))
    )
    part = result.scalar_one_or_none()
    if not part:
        return JSONResponse(status_code=404, content={"detail": "Part not found"})

    body = await request.json()

    # Validate packaging_type against allowed values (Req 7.6)
    if "packaging_type" in body and body["packaging_type"] is not None:
        if body["packaging_type"] not in ALLOWED_PACKAGING_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid packaging_type '{body['packaging_type']}'. Must be one of: {', '.join(sorted(ALLOWED_PACKAGING_TYPES))}",
            )

    # Validate qty_per_pack is positive when provided (Req 7.5)
    if "qty_per_pack" in body and body["qty_per_pack"] is not None:
        if int(body["qty_per_pack"]) <= 0:
            raise HTTPException(
                status_code=422,
                detail="qty_per_pack must be a positive integer",
            )

    # Validate total_packs is positive when provided (Req 7.5)
    if "total_packs" in body and body["total_packs"] is not None:
        if int(body["total_packs"]) <= 0:
            raise HTTPException(
                status_code=422,
                detail="total_packs must be a positive integer",
            )

    for field in ["name", "part_number", "description", "part_type", "brand",
                   "tyre_width", "tyre_profile", "tyre_rim_dia", "tyre_load_index", "tyre_speed_index"]:
        if field in body:
            setattr(part, field, body[field])
    from decimal import Decimal
    if "default_price" in body:
        part.default_price = Decimal(str(body["default_price"]))
    if "category_id" in body:
        part.category_id = uuid.UUID(body["category_id"]) if body["category_id"] else None
    if "supplier_id" in body:
        part.supplier_id = uuid.UUID(body["supplier_id"]) if body["supplier_id"] else None
    if "is_active" in body:
        part.is_active = body["is_active"]
    if "min_stock_threshold" in body:
        part.min_stock_threshold = int(body["min_stock_threshold"])
    if "reorder_quantity" in body:
        part.reorder_quantity = int(body["reorder_quantity"])

    # Handle new pricing fields (Req 7.2)
    if "purchase_price" in body:
        part.purchase_price = Decimal(str(body["purchase_price"])) if body["purchase_price"] is not None else None
    if "packaging_type" in body:
        part.packaging_type = body["packaging_type"]
    if "qty_per_pack" in body:
        part.qty_per_pack = int(body["qty_per_pack"]) if body["qty_per_pack"] is not None else None
    if "total_packs" in body:
        part.total_packs = int(body["total_packs"]) if body["total_packs"] is not None else None
    if "sell_price_per_unit" in body:
        part.sell_price_per_unit = Decimal(str(body["sell_price_per_unit"])) if body["sell_price_per_unit"] is not None else None
    if "gst_mode" in body:
        part.gst_mode = body["gst_mode"]

    # Recalculate derived fields server-side (Req 7.4)
    cost_per_unit, margin, margin_pct = _compute_pricing(
        part.purchase_price,
        part.qty_per_pack,
        part.total_packs,
        part.sell_price_per_unit,
    )
    part.cost_per_unit = cost_per_unit
    part.margin = margin
    part.margin_pct = margin_pct

    await db.flush()

    # Re-fetch with relationships
    result2 = await db.execute(
        _sel(PartsCatalogue).where(PartsCatalogue.id == part_id)
        .options(selectinload(PartsCatalogue.category), selectinload(PartsCatalogue.supplier))
    )
    updated = result2.scalar_one()
    return _part_to_dict(updated)


# ===========================================================================
# Labour Rate endpoints — Requirements: 28.3
# ===========================================================================


@router.get(
    "/labour-rates",
    response_model=LabourRateListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List labour rates",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_labour_rates_endpoint(
    request: Request,
    active_only: bool = Query(False, description="Return only active rates"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List configured labour rates for the organisation.

    Salespeople select from these rates when adding Labour line items
    to invoices (Req 28.3).

    Requirements: 28.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_labour_rates(
        db,
        org_id=org_uuid,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )

    return LabourRateListResponse(
        labour_rates=[LabourRateResponse(**r) for r in result["labour_rates"]],
        total=result["total"],
    )


@router.post(
    "/labour-rates",
    response_model=LabourRateCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create a labour rate",
    dependencies=[require_role("org_admin")],
)
async def create_labour_rate_endpoint(
    payload: LabourRateCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure a named labour rate with an hourly rate.

    Requirements: 28.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        rate_data = await create_labour_rate(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            name=payload.name,
            hourly_rate=payload.hourly_rate,
            is_active=payload.is_active,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return LabourRateCreateResponse(
        message="Labour rate created",
        labour_rate=LabourRateResponse(**rate_data),
    )


@router.put(
    "/labour-rates/{rate_id}",
    response_model=LabourRateCreateResponse,
    status_code=200,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Labour rate not found"},
    },
    summary="Update a labour rate",
    dependencies=[require_role("org_admin")],
)
async def update_labour_rate_endpoint(
    rate_id: uuid.UUID,
    payload: LabourRateUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing labour rate's name, hourly rate, or active status."""
    from app.modules.catalogue.service import update_labour_rate

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        rate_data = await update_labour_rate(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            rate_id=rate_id,
            name=payload.name,
            hourly_rate=payload.hourly_rate,
            is_active=payload.is_active,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400 if "not found" not in str(exc).lower() else 404,
            content={"detail": str(exc)},
        )

    return LabourRateCreateResponse(
        message="Labour rate updated",
        labour_rate=LabourRateResponse(**rate_data),
    )


@router.delete(
    "/labour-rates/{rate_id}",
    status_code=200,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Labour rate not found"},
    },
    summary="Permanently delete a labour rate",
    dependencies=[require_role("org_admin")],
)
async def delete_labour_rate_endpoint(
    rate_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a labour rate (hard delete)."""
    from app.modules.catalogue.service import delete_labour_rate

    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        await delete_labour_rate(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            rate_id=rate_id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return {"message": "Labour rate deleted"}

# ===========================================================================
# Part Categories endpoints
# ===========================================================================


@router.get(
    "/part-categories",
    summary="List part categories for the organisation",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_part_categories(
    request: Request,
    search: str = Query("", description="Search filter"),
    db: AsyncSession = Depends(get_db_session),
):
    """List part categories, optionally filtered by search term."""
    from sqlalchemy import select
    from app.modules.catalogue.models import PartCategory

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    stmt = select(PartCategory).where(PartCategory.org_id == org_uuid)
    if search.strip():
        stmt = stmt.where(PartCategory.name.ilike(f"%{search.strip()}%"))
    stmt = stmt.order_by(PartCategory.name)

    result = await db.execute(stmt)
    categories = result.scalars().all()
    return {
        "categories": [{"id": str(c.id), "name": c.name} for c in categories],
    }


@router.post(
    "/part-categories",
    status_code=201,
    summary="Create a part category",
    dependencies=[require_role("org_admin")],
)
async def create_part_category(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new part category. Returns existing if name already exists."""
    from sqlalchemy import select
    from app.modules.catalogue.models import PartCategory

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"detail": "Category name is required"})

    # Check if exists
    existing = await db.execute(
        select(PartCategory).where(PartCategory.org_id == org_uuid, PartCategory.name == name)
    )
    cat = existing.scalar_one_or_none()
    if cat:
        return {"id": str(cat.id), "name": cat.name, "created": False}

    cat = PartCategory(org_id=org_uuid, name=name)
    db.add(cat)
    await db.flush()
    return {"id": str(cat.id), "name": cat.name, "created": True}
