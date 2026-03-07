"""Vehicle router — lookup, refresh, manual entry, linking, profile.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 15.1, 15.2, 15.3, 15.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.integrations.carjam import (
    CarjamError,
    CarjamNotFoundError,
    CarjamRateLimitError,
)
from app.modules.auth.rbac import require_role
from app.modules.vehicles.schemas import (
    ManualVehicleCreate,
    ManualVehicleResponse,
    VehicleLinkRequest,
    VehicleLinkResponse,
    VehicleLookupNotFoundResponse,
    VehicleLookupResponse,
    VehicleProfileResponse,
    VehicleRefreshResponse,
)
from app.modules.vehicles.service import (
    create_manual_vehicle,
    get_vehicle_profile,
    link_vehicle_to_customer,
    lookup_vehicle,
    refresh_vehicle,
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
    "/lookup/{rego}",
    response_model=VehicleLookupResponse,
    responses={
        404: {"model": VehicleLookupNotFoundResponse, "description": "Vehicle not found — suggest manual entry"},
        429: {"description": "Carjam rate limit exceeded"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Look up vehicle by registration (cache-first)",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_lookup(
    rego: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Look up a vehicle by NZ registration number.

    Cache-first strategy: checks Global_Vehicle_DB first. On cache miss,
    calls Carjam API, stores the result, and increments the org's Carjam
    usage counter.

    If Carjam returns no result, responds with 404 and suggests manual entry.
    If Carjam rate limit is exceeded, responds with 429.

    Requirements: 14.1, 14.2, 14.3, 14.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    rego_clean = rego.upper().strip()
    if not rego_clean:
        return JSONResponse(
            status_code=400,
            content={"detail": "Registration number is required"},
        )

    try:
        result = await lookup_vehicle(
            db,
            redis,
            rego=rego_clean,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            ip_address=ip_address,
        )
    except CarjamNotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "detail": f"No vehicle found for registration '{rego_clean}'. You can enter the details manually.",
                "rego": rego_clean,
                "suggest_manual_entry": True,
            },
        )
    except CarjamRateLimitError as exc:
        return JSONResponse(
            status_code=429,
            content={"detail": "Vehicle lookup rate limit exceeded. Please try again shortly."},
            headers={"Retry-After": str(exc.retry_after)},
        )
    except CarjamError as exc:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Vehicle lookup service error: {exc}"},
        )

    return VehicleLookupResponse(**result)


@router.post(
    "/{vehicle_id}/refresh",
    response_model=VehicleRefreshResponse,
    responses={
        404: {"description": "Vehicle not found in Global_Vehicle_DB"},
        429: {"description": "Carjam rate limit exceeded"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        502: {"description": "Carjam service error"},
    },
    summary="Force Carjam re-fetch for a vehicle",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_refresh(
    vehicle_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Force a new Carjam API call for an existing vehicle record.

    Updates the Global_Vehicle_DB record and charges the organisation
    for one lookup.

    Requirements: 14.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await refresh_vehicle(
            db,
            redis,
            vehicle_id=vehicle_id,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )
    except CarjamNotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "detail": "Carjam returned no result for this vehicle's registration.",
                "suggest_manual_entry": True,
            },
        )
    except CarjamRateLimitError as exc:
        return JSONResponse(
            status_code=429,
            content={"detail": "Vehicle lookup rate limit exceeded. Please try again shortly."},
            headers={"Retry-After": str(exc.retry_after)},
        )
    except CarjamError as exc:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Vehicle lookup service error: {exc}"},
        )

    return VehicleRefreshResponse(**result)


@router.post(
    "/manual",
    response_model=ManualVehicleResponse,
    status_code=201,
    responses={
        400: {"description": "Invalid input"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Create a manually entered vehicle",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_manual_entry(
    body: ManualVehicleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a vehicle record via manual entry.

    The record is stored in org_vehicles (not Global_Vehicle_DB) and
    marked as "manually entered". Used when Carjam returns no result.

    Requirements: 14.6, 14.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await create_manual_vehicle(
        db,
        org_id=org_uuid,
        user_id=user_uuid or uuid.uuid4(),
        rego=body.rego,
        make=body.make,
        model=body.model,
        year=body.year,
        colour=body.colour,
        body_type=body.body_type,
        fuel_type=body.fuel_type,
        engine_size=body.engine_size,
        num_seats=body.num_seats,
        ip_address=ip_address,
    )

    return ManualVehicleResponse(**result)


@router.post(
    "/{vehicle_id}/link",
    response_model=VehicleLinkResponse,
    status_code=201,
    responses={
        400: {"description": "Invalid input"},
        404: {"description": "Vehicle or customer not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Link a vehicle to a customer",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_link(
    vehicle_id: uuid.UUID,
    body: VehicleLinkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Link a global vehicle to a customer within the organisation.

    The same global vehicle can be linked to different customers across
    different organisations (Req 15.1) and to multiple customers within
    a single organisation (Req 15.2).

    Requirements: 15.1, 15.2
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        customer_uuid = uuid.UUID(body.customer_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid customer_id format"},
        )

    try:
        result = await link_vehicle_to_customer(
            db,
            vehicle_id=vehicle_id,
            customer_id=customer_uuid,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            odometer=body.odometer,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return VehicleLinkResponse(**result)


@router.get(
    "/{vehicle_id}",
    response_model=VehicleProfileResponse,
    responses={
        404: {"description": "Vehicle not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Vehicle profile with Carjam data, linked customers, service history",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_profile(
    vehicle_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get the full vehicle profile.

    Includes Carjam data, linked customers, odometer history, service
    history (all invoices for that rego), and WOF/rego expiry indicators
    (green >60d, amber 30-60d, red <30d).

    Requirements: 15.3, 15.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await get_vehicle_profile(
            db,
            vehicle_id=vehicle_id,
            org_id=org_uuid,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return VehicleProfileResponse(**result)
