"""Service Types router — CRUD endpoints for plumbing/gas service type catalogue.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.service_types.schemas import (
    ServiceTypeCreateRequest,
    ServiceTypeListResponse,
    ServiceTypeResponse,
    ServiceTypeUpdateRequest,
)
from app.modules.service_types.service import (
    create_service_type,
    delete_service_type,
    get_service_type,
    list_service_types,
    update_service_type,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
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
# Service Type CRUD endpoints
# ===========================================================================


@router.get(
    "/",
    response_model=ServiceTypeListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List service types",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_service_types_endpoint(
    request: Request,
    active_only: bool = Query(False, description="Return only active service types"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db_session),
):
    """List service types for the organisation with pagination.

    Requirements: 2.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_service_types(
        db,
        org_id=org_uuid,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )

    return ServiceTypeListResponse(
        service_types=[ServiceTypeResponse(**st) for st in result["service_types"]],
        total=result["total"],
    )


@router.post(
    "/",
    response_model=ServiceTypeResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        409: {"description": "Duplicate name"},
    },
    summary="Create a service type",
    dependencies=[require_role("org_admin")],
)
async def create_service_type_endpoint(
    payload: ServiceTypeCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new service type with optional field definitions.

    Requirements: 2.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await create_service_type(
            db,
            org_id=org_uuid,
            name=payload.name,
            description=payload.description,
            is_active=payload.is_active,
            fields=[f.model_dump() for f in payload.fields],
        )
    except IntegrityError:
        return JSONResponse(
            status_code=409,
            content={"detail": "A service type with this name already exists"},
        )

    return ServiceTypeResponse(**result)


@router.get(
    "/{service_type_id}",
    response_model=ServiceTypeResponse,
    responses={
        400: {"description": "Invalid ID format"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        404: {"description": "Service type not found"},
    },
    summary="Get a service type",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_service_type_endpoint(
    service_type_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Fetch a single service type with its field definitions.

    Requirements: 2.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        st_uuid = uuid.UUID(service_type_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid service type ID format"},
        )

    try:
        result = await get_service_type(
            db,
            org_id=org_uuid,
            service_type_id=st_uuid,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return ServiceTypeResponse(**result)


@router.put(
    "/{service_type_id}",
    response_model=ServiceTypeResponse,
    responses={
        400: {"description": "Invalid ID format"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Service type not found"},
        409: {"description": "Duplicate name"},
    },
    summary="Update a service type",
    dependencies=[require_role("org_admin")],
)
async def update_service_type_endpoint(
    service_type_id: str,
    payload: ServiceTypeUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing service type. Only provided fields are changed.

    If ``fields`` is provided, performs full replacement of field definitions.

    Requirements: 2.4, 2.5
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        st_uuid = uuid.UUID(service_type_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid service type ID format"},
        )

    # Build kwargs — only include keys that were explicitly set
    update_kwargs: dict = {}
    if payload.name is not None:
        update_kwargs["name"] = payload.name
    if payload.description is not None:
        update_kwargs["description"] = payload.description
    if payload.is_active is not None:
        update_kwargs["is_active"] = payload.is_active
    if payload.fields is not None:
        update_kwargs["fields"] = [f.model_dump() for f in payload.fields]

    try:
        result = await update_service_type(
            db,
            org_id=org_uuid,
            service_type_id=st_uuid,
            **update_kwargs,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )
    except IntegrityError:
        return JSONResponse(
            status_code=409,
            content={"detail": "A service type with this name already exists"},
        )

    return ServiceTypeResponse(**result)


@router.delete(
    "/{service_type_id}",
    status_code=200,
    responses={
        400: {"description": "Invalid ID format"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Service type not found"},
        409: {"description": "Referenced by job cards"},
    },
    summary="Delete a service type",
    dependencies=[require_role("org_admin")],
)
async def delete_service_type_endpoint(
    service_type_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a service type if it is not referenced by any job cards.

    Returns 409 if the service type is referenced by existing job cards.

    Requirements: 2.6, 2.7
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        st_uuid = uuid.UUID(service_type_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid service type ID format"},
        )

    try:
        result = await delete_service_type(
            db,
            org_id=org_uuid,
            service_type_id=st_uuid,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    if result is not None:
        # Service type is referenced by job cards — return 409
        return JSONResponse(
            status_code=result["status"],
            content={"detail": result["detail"]},
        )

    return {"message": "Service type deleted"}
