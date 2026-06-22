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
from app.modules.customers.consent import current_consent_text
from app.modules.customers.exceptions import RemindersConsentRequiredError
from app.modules.organisations.service import get_org_settings
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
from app.modules.time_clock import service as clock_service
from app.modules.time_clock.schemas import (
    KioskClockActionRequest,
    KioskClockActionResponse,
    KioskLookupRequest,
    KioskLookupResponse,
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

    user_agent = (request.headers.get("user-agent") or "")[:500] or None

    try:
        result = await kiosk_check_in_v2(
            db,
            org_id=org_uuid,
            user_id=user_uuid or uuid.uuid4(),
            data=payload,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except RemindersConsentRequiredError:
        # Defence-in-depth: the kiosk path always supplies a consent_record,
        # so the gate never fires here. If it somehow does, surface a 500 and
        # let session.begin() roll back the whole check-in (Req 1.16).
        return JSONResponse(
            status_code=500,
            content={"error": "consent_persistence_failed"},
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


@router.get(
    "/consent-text",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Kiosk reminder-consent banner text + version",
    dependencies=[
        require_role("kiosk"),
        Depends(_check_kiosk_rate_limit),
    ],
)
async def consent_text(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the reminder-consent banner text and its version for the kiosk.

    The text is a backend constant (``current_consent_text()``); the
    ``{workshop_name}`` placeholder is substituted server-side with the org's
    name so the frontend never sees the placeholder. Gated by the same
    ``require_role("kiosk")`` + rate-limit pattern as every other kiosk route.

    Requirements: 6.3
    """
    org_uuid, _user_uuid, _ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    text, version = current_consent_text()
    settings = await get_org_settings(db, org_id=org_uuid)
    workshop_name = (settings or {}).get("org_name") or "your workshop"
    text = text.replace("{workshop_name}", workshop_name)

    return {"text": text, "version": version}


# ---------------------------------------------------------------------------
# Staff clock-in surface (Phase 3 task B9)
# ---------------------------------------------------------------------------
#
# Two endpoints layered on the existing kiosk JWT (the role-`kiosk`
# tablet token), gated by the SAME ``dependencies=[require_role("kiosk"),
# Depends(_check_kiosk_rate_limit)]`` pattern as ``POST /check-in`` above
# (P3-N9 — the dependency-level 30/min/kiosk-user limit runs FIRST and
# returns ``{"detail":"Rate limit exceeded"}``; the inline G12 check
# inside :func:`lookup_for_kiosk` runs SECOND and returns the distinct
# ``{"detail":"kiosk_lookup_rate_limited"}`` body when a specific
# ``(org_id, employee_id)`` pair is being enumerated). Routes are NOT in
# ``PUBLIC_PATHS`` / ``PUBLIC_PREFIXES`` — the kiosk JWT is required.
#
# Validates: Requirements R3 — Staff Management Phase 3 task B9.


def _translate_clock_service_error(
    exc: clock_service.TimeClockServiceError,
) -> JSONResponse:
    """Map :mod:`app.modules.time_clock.service` exceptions to documented
    HTTP envelopes for the kiosk surface (R3).

    Mirrors the translator at :mod:`app.modules.time_clock.router` —
    duplicated here (not imported) because the kiosk surface only
    needs the kiosk-flavoured subset and the time_clock router uses
    ``HTTPException`` while this function returns a JSONResponse for
    consistency with the rest of the kiosk router.
    """
    if isinstance(exc, clock_service.KioskLookupRateLimitedError):
        return JSONResponse(
            status_code=429,
            content={"detail": "kiosk_lookup_rate_limited"},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    if isinstance(exc, clock_service.EmployeeNotFoundError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "employee_not_found",
                "message": (
                    "Employee code not recognised. Please see your manager."
                ),
            },
        )
    if isinstance(exc, clock_service.PhotoRequiredError):
        return JSONResponse(
            status_code=422, content={"detail": "photo_required"},
        )
    if isinstance(exc, clock_service.InvalidActionError):
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc) or "invalid_action"},
        )
    if isinstance(exc, clock_service.StaffNotFoundError):
        return JSONResponse(
            status_code=404, content={"detail": "staff_not_found"},
        )
    # Unknown subclass — surface as 500 so it shows up in logs.
    return JSONResponse(
        status_code=500,
        content={
            "detail": "time_clock_service_error",
            "message": str(exc),
        },
    )


@router.post(
    "/clock/lookup",
    response_model=KioskLookupResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
        422: {"description": "Employee code not recognised"},
        429: {
            "description": (
                "Rate limit exceeded — either the global 30/min/kiosk-user "
                "cap (``Rate limit exceeded``) or the per-(org, employee_id) "
                "G12 cap (``kiosk_lookup_rate_limited``)"
            ),
        },
    },
    summary="Kiosk staff lookup by employee_id",
    dependencies=[
        require_role("kiosk"),
        Depends(_check_kiosk_rate_limit),
    ],
)
async def clock_lookup(
    payload: KioskLookupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
):
    """Resolve an ``employee_id`` to a kiosk-ready staff identity (R3).

    Two-layer rate limit (P3-N9):
      - ``_check_kiosk_rate_limit`` (dependency) caps the kiosk-user
        at 30 lookups/min — returns ``{"detail":"Rate limit exceeded"}``.
      - The inline G12 limit inside :func:`lookup_for_kiosk` caps a
        specific ``(org_id, sha256(employee_id))`` pair at 10 hits/min
        — returns ``{"detail":"kiosk_lookup_rate_limited"}`` with
        ``Retry-After: 60``.

    The raw ``employee_id`` is SHA-256-hashed before any Redis or
    audit write — see :func:`app.modules.time_clock.service._hash_employee_id`.
    """
    org_uuid, _user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        result = await clock_service.lookup_for_kiosk(
            db,
            org_id=org_uuid,
            employee_id=payload.employee_id,
            redis=redis,
            ip_address=ip_address,
        )
    except clock_service.TimeClockServiceError as exc:
        return _translate_clock_service_error(exc)

    return KioskLookupResponse(
        staff_id=result["staff_id"],
        first_name=result["first_name"],
        on_file_photo_url=result.get("on_file_photo_url"),
        currently_clocked_in=result["currently_clocked_in"],
    )


@router.post(
    "/clock/action",
    response_model=KioskClockActionResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Kiosk role required"},
        404: {"description": "Staff not found"},
        409: {"description": "Invalid action sequence (already in / not in)"},
        422: {"description": "photo_required"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Kiosk staff clock-in or clock-out",
    dependencies=[
        require_role("kiosk"),
        Depends(_check_kiosk_rate_limit),
    ],
)
async def clock_action(
    payload: KioskClockActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Insert a clock-in row or close the open one (R3.5–R3.8).

    ``photo_file_key`` is mandatory — the kiosk app must POST the
    captured photo to ``/api/v2/uploads/clock-photos`` first and pass
    the returned ``file_key`` here. The DB CHECK
    ``ck_time_clock_entries_kiosk_photo`` is the integrity backstop.

    On clock-in the response surfaces the on-file + just-taken photo
    URLs for the side-by-side confirmation screen (R3.9).
    """
    org_uuid, _user_uuid, ip_address = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Derive branch_id from kiosk user's JWT branch_ids[0] (Req 11.2).
    branch_ids_raw = getattr(request.state, "branch_ids", []) or []
    kiosk_branch_id: uuid.UUID | None = None
    if branch_ids_raw:
        try:
            kiosk_branch_id = uuid.UUID(str(branch_ids_raw[0]))
        except (ValueError, TypeError, IndexError):
            pass

    # Fallback: a kiosk user with no branch scope (empty ``branch_ids``) would
    # otherwise insert a NULL ``branch_id`` and trip the
    # ``ck_tce_branch_id_new_rows`` CHECK (new rows require a branch), surfacing
    # to staff as a misleading "clock-in/out state out of sync" 409. Resolve the
    # org's default branch instead so clock-in works without manual branch setup.
    if kiosk_branch_id is None:
        from sqlalchemy import select

        from app.modules.organisations.models import Branch

        kiosk_branch_id = (
            await db.execute(
                select(Branch.id)
                .where(Branch.org_id == org_uuid, Branch.is_default.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if kiosk_branch_id is None:
            # No default flagged — fall back to any branch in the org.
            kiosk_branch_id = (
                await db.execute(
                    select(Branch.id)
                    .where(Branch.org_id == org_uuid)
                    .order_by(Branch.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    try:
        entry = await clock_service.kiosk_clock_action(
            db,
            org_id=org_uuid,
            staff_id=payload.staff_id,
            action=payload.action,
            photo_file_key=payload.photo_file_key,
            ip_address=ip_address,
            branch_id=kiosk_branch_id,
        )
    except clock_service.TimeClockServiceError as exc:
        return _translate_clock_service_error(exc)

    # Resolve on-file photo for the confirmation screen — best-effort;
    # the kiosk surface tolerates a missing photo (the side-by-side
    # comparison just shows a placeholder for the on-file slot).
    on_file_photo_url: str | None = None
    try:
        from app.modules.staff.models import StaffMember

        staff = await db.get(StaffMember, payload.staff_id)
        if staff is not None:
            on_file_photo_url = staff.on_file_photo_url
    except Exception:  # noqa: BLE001 - photo lookup is best-effort.
        on_file_photo_url = None

    just_taken_photo_url = (
        entry.clock_out_photo_url if payload.action == "out"
        else entry.clock_in_photo_url
    )

    return KioskClockActionResponse(
        time_clock_entry_id=entry.id,
        action=payload.action,
        clock_in_at=entry.clock_in_at,
        clock_out_at=entry.clock_out_at,
        worked_minutes=entry.worked_minutes,
        on_file_photo_url=on_file_photo_url,
        just_taken_photo_url=just_taken_photo_url,
    )
