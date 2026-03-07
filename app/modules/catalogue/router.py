"""Catalogue router — Service, Parts, and Labour Rate CRUD endpoints.

Requirements: 27.1, 27.2, 27.3, 28.1, 28.2, 28.3
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.catalogue.schemas import (
    LabourRateCreateRequest,
    LabourRateCreateResponse,
    LabourRateListResponse,
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
    create_labour_rate,
    create_part,
    create_service,
    get_service,
    list_labour_rates,
    list_parts,
    list_services,
    update_service,
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
    """List service catalogue entries for the organisation.

    When ``active_only`` is True, inactive services are hidden — used by
    invoice creation to show only available services (Req 27.2).
    All services (including inactive) are returned by default for
    catalogue management and historical display.

    Requirements: 27.1, 27.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_services(
        db,
        org_id=org_uuid,
        active_only=active_only,
        category=category,
        limit=limit,
        offset=offset,
    )

    return ServiceListResponse(
        services=[ServiceResponse(**s) for s in result["services"]],
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
    """Create a new service in the organisation's catalogue.

    Requirements: 27.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        service_data = await create_service(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            name=payload.name,
            description=payload.description,
            default_price=payload.default_price,
            is_gst_exempt=payload.is_gst_exempt,
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
        service=ServiceResponse(**service_data),
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
    """Update an existing service catalogue entry. Only provided fields
    are changed. Use the ``is_active`` toggle to deactivate a service
    (Req 27.2 — hidden from invoice creation but retained for history).

    Requirements: 27.1, 27.2
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
        service_data = await update_service(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            service_id=svc_uuid,
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
        service=ServiceResponse(**service_data),
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

    Requirements: 28.1
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        part_data = await create_part(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            name=payload.name,
            part_number=payload.part_number,
            default_price=payload.default_price,
            supplier=payload.supplier,
            is_active=payload.is_active,
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
