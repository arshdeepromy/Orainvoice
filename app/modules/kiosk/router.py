"""Kiosk router — self-service check-in endpoint for tablet kiosks.

Requirements: 3.7, 6.5
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.modules.auth.rbac import require_role
from app.modules.kiosk.schemas import KioskCheckInRequest, KioskCheckInResponse
from app.modules.kiosk.service import kiosk_check_in

router = APIRouter()

# Kiosk-specific rate limit: 30 requests per minute per kiosk user.
_KIOSK_RATE_LIMIT = 30
_WINDOW = 60


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
    response_model=KioskCheckInResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
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
    payload: KioskCheckInRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Process a walk-in customer check-in from a kiosk tablet.

    Orchestrates customer lookup/creation, optional vehicle lookup/creation
    (via Carjam with manual fallback), and vehicle-customer linking in a
    single atomic operation.

    Requirements: 3.7, 6.5
    """
    org_uuid, user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await kiosk_check_in(
        db,
        redis,
        org_id=org_uuid,
        user_id=user_uuid or uuid.uuid4(),
        data=payload,
        ip_address=ip_address,
    )

    return result
