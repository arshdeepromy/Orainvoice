"""Vehicle router — lookup, refresh, manual entry, linking, profile.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 15.1, 15.2, 15.3, 15.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Query
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
    OdometerHistoryEntry,
    OdometerReadingRequest,
    OdometerReadingResponse,
    OdometerReadingUpdateRequest,
    VehicleLinkRequest,
    VehicleLinkResponse,
    VehicleLookupNotFoundResponse,
    VehicleLookupResponse,
    VehicleLookupWithFallbackRequest,
    VehicleLookupWithFallbackResponse,
    VehicleProfileResponse,
    VehicleRefreshResponse,
    VehicleSearchResponse,
)
from app.modules.vehicles.service import (
    create_manual_vehicle,
    get_odometer_history,
    get_vehicle_profile,
    link_vehicle_to_customer,
    list_org_vehicles,
    lookup_vehicle,
    lookup_vehicle_with_abcd_fallback,
    record_odometer_reading,
    refresh_vehicle,
    search_vehicles,
    update_odometer_reading,
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
    "",
    summary="List org vehicles with linked customers",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_vehicles(
    request: Request,
    search: str | None = Query(None, description="Search by rego, make, or model"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
):
    """List all vehicles linked to the org via customer-vehicle associations.

    Returns paginated results with linked customer info.
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    result = await list_org_vehicles(
        db, org_id=org_uuid, search=search, page=page, page_size=page_size
    )
    return result


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


# ---------------------------------------------------------------------------
# Live Search & ABCD Fallback (MUST be before /{vehicle_id} route!)
# ---------------------------------------------------------------------------

@router.get(
    "/search",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Live search vehicles by registration",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_search(
    request: Request,
    q: str = Query(..., min_length=2, max_length=20, description="Search query (registration prefix)"),
    db: AsyncSession = Depends(get_db_session),
):
    """Live search for vehicles in global_vehicles database.
    
    Returns up to 10 matching vehicles by rego prefix.
    No API calls, no usage tracking - instant results for autocomplete.
    Also returns linked customers for each vehicle within the org.
    """
    org_uuid, _, _ = _extract_org_context(request)
    
    if len(q) < 2:
        return {"results": [], "total": 0}
    
    results = await search_vehicles(db, query=q, limit=10, org_id=org_uuid)
    
    return {"results": results, "total": len(results)}


@router.post(
    "/lookup-with-fallback",
    response_model=VehicleLookupWithFallbackResponse,
    responses={
        404: {"description": "Vehicle not found in Carjam"},
        429: {"description": "Carjam rate limit exceeded"},
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
        502: {"description": "Carjam service error"},
    },
    summary="Look up vehicle with ABCD → Basic fallback",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def vehicle_lookup_with_fallback(
    body: VehicleLookupWithFallbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Look up vehicle using ABCD-first strategy with automatic Basic fallback.
    
    Strategy:
    1. Check cache (global_vehicles) - if hit, return immediately (no cost)
    2. Try ABCD API (2 attempts, ~$0.05) - lower cost, adequate data
    3. If ABCD fails, automatically fallback to Basic API (~$0.15)
    
    This provides cost optimization while ensuring 100% success rate.
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    
    try:
        result = await lookup_vehicle_with_abcd_fallback(
            db,
            redis,
            rego=body.rego,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            ip_address=ip_address,
        )
    except CarjamNotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "detail": f"No vehicle found for registration '{body.rego}'. You can enter the details manually.",
                "rego": body.rego,
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
    
    return VehicleLookupWithFallbackResponse(**result)


# ---------------------------------------------------------------------------
# Odometer Reading Endpoints (MUST be before /{vehicle_id} route!)
# ---------------------------------------------------------------------------

@router.post(
    "/{vehicle_id}/odometer",
    response_model=OdometerReadingResponse,
    status_code=201,
    summary="Record a new odometer reading",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def post_odometer_reading(
    vehicle_id: uuid.UUID,
    body: OdometerReadingRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Record a new odometer reading for a vehicle."""
    org_uuid, user_uuid, ip_address = _extract_org_context(request)

    try:
        result = await record_odometer_reading(
            db,
            global_vehicle_id=vehicle_id,
            reading_km=body.reading_km,
            source=body.source,
            recorded_by=user_uuid,
            invoice_id=uuid.UUID(body.invoice_id) if body.invoice_id else None,
            org_id=org_uuid,
            notes=body.notes,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return OdometerReadingResponse(**result)


@router.get(
    "/{vehicle_id}/odometer-history",
    response_model=list[OdometerHistoryEntry],
    summary="Get odometer reading history",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_odometer_history_endpoint(
    vehicle_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get odometer reading history for a vehicle, newest first."""
    result = await get_odometer_history(db, global_vehicle_id=vehicle_id)
    return result


@router.put(
    "/{vehicle_id}/odometer/{reading_id}",
    summary="Correct an odometer reading",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def put_odometer_reading(
    vehicle_id: uuid.UUID,
    reading_id: uuid.UUID,
    body: OdometerReadingUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Correct an existing odometer reading (e.g. accidental wrong entry)."""
    _, user_uuid, _ = _extract_org_context(request)

    try:
        result = await update_odometer_reading(
            db,
            reading_id=reading_id,
            new_reading_km=body.reading_km,
            user_id=user_uuid or uuid.uuid4(),
            notes=body.notes,
        )
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return result


# ---------------------------------------------------------------------------
# Vehicle Profile (MUST be after /search and /lookup-with-fallback!)
# ---------------------------------------------------------------------------

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
