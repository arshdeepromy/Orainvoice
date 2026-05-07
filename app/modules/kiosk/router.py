"""Kiosk router — self-service check-in endpoint for tablet kiosks.

Requirements: 3.7, 6.5
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.modules.auth.rbac import require_role
from app.modules.kiosk.schemas import (
    KioskCheckInRequestV2,
    KioskCheckInResponseV2,
    KioskCustomerLookupResponse,
    KioskVehicleLookupRequest,
    KioskVehicleLookupResponse,
)
from app.modules.kiosk.service import (
    customer_lookup_for_kiosk,
    kiosk_check_in_v2,
    lookup_vehicle_for_kiosk,
)

router = APIRouter()

# Kiosk-specific rate limit: 30 requests per minute per kiosk user.
_KIOSK_RATE_LIMIT = 30
_WINDOW = 60


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


async def _check_kiosk_rate_limit(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> None:
    """Enforce 30 requests/minute per kiosk user.

    Uses a Redis sorted-set sliding window, matching the pattern used by
    the global rate-limit middleware but with a kiosk-specific key and
    stricter limit.

    Requirements: 6.5
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        return

    key = f"rl:kiosk:{user_id}"
    now = time.time()
    window_start = now - _WINDOW

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zcard(key)
    results = await pipe.execute()
    count: int = results[1]

    if count >= _KIOSK_RATE_LIMIT:
        oldest = await redis.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(oldest[0][1] + _WINDOW - now) + 1
        else:
            retry_after = 1
        from fastapi import HTTPException
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(max(retry_after, 1))},
        )

    pipe2 = redis.pipeline()
    pipe2.zadd(key, {f"{now}": now})
    pipe2.expire(key, _WINDOW + 5)
    await pipe2.execute()


@router.post(
    "/check-in",
    response_model=KioskCheckInResponseV2,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
        404: {"description": "Customer not found"},
        422: {"description": "Validation error"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Kiosk walk-in check-in",
    dependencies=[
        require_role("kiosk"),
        Depends(_check_kiosk_rate_limit),
    ],
)
async def check_in(
    payload: KioskCheckInRequestV2,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Process a walk-in customer check-in from a kiosk tablet.

    Accepts customer details with an optional list of vehicle entries
    (each with global_vehicle_id and optional odometer_km). Links all
    vehicles to the customer and records odometer readings.

    Backward compatible: when vehicles list is empty, behaves like the
    original check-in endpoint.

    Requirements: 7.2, 7.3
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await kiosk_check_in_v2(
        db,
        org_id=org_uuid,
        user_id=user_uuid or uuid.uuid4(),
        data=payload,
        ip_address=ip_address,
    )

    return result


@router.post(
    "/vehicle-lookup",
    response_model=KioskVehicleLookupResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
        404: {"description": "Vehicle not found"},
        422: {"description": "Validation error"},
        429: {"description": "Rate limit exceeded"},
        502: {"description": "Vehicle lookup service error"},
    },
    summary="Kiosk vehicle registration lookup",
    dependencies=[
        require_role("kiosk"),
        Depends(_check_kiosk_rate_limit),
    ],
)
async def vehicle_lookup(
    payload: KioskVehicleLookupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Look up a vehicle by registration number for kiosk check-in.

    Performs a cascading lookup: org_vehicles → global_vehicles → CarJam API.
    Returns vehicle details for display on the kiosk summary screen.

    Requirements: 7.1, 7.4
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await lookup_vehicle_for_kiosk(
        db,
        redis,
        rego=payload.rego,
        org_id=org_uuid,
    )

    return result


@router.get(
    "/customer-lookup",
    response_model=KioskCustomerLookupResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
        422: {"description": "At least one of phone or email required"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Kiosk customer auto-fill lookup",
    dependencies=[
        require_role("kiosk"),
        Depends(_check_kiosk_rate_limit),
    ],
)
async def customer_lookup(
    request: Request,
    phone: str | None = Query(None, description="Customer phone number (exact match)"),
    email: str | None = Query(None, description="Customer email (case-insensitive match)"),
    db: AsyncSession = Depends(get_db_session),
):
    """Look up customers by phone or email for kiosk auto-fill.

    Returns up to 5 matching customers within the organisation. At least one
    of phone or email must be provided.

    Requirements: 7.1, 9.5, 9.7
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await customer_lookup_for_kiosk(
        db,
        org_id=org_uuid,
        phone=phone,
        email=email,
    )

    return result
