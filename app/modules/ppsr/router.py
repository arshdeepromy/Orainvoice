"""PPSR module HTTP router.

Implements every endpoint from ``.kiro/specs/ppsr-module/design.md``
§5. The router is a thin translation layer:

  - Auth / org-context resolution comes from middleware
    (``request.state.user_id`` / ``request.state.org_id`` /
    ``request.state.role``) populated by :class:`AuthMiddleware`.
  - Module gating is handled by :class:`ModuleMiddleware` for the
    ``/api/v2/ppsr`` prefix; the service also defends in depth via
    :meth:`ModuleService.is_enabled`.
  - All business logic + audit writes live in :class:`PpsrService`.

This file does NOT register itself — task C6 wires it into
``app/main.py`` and the module-gate middleware map.

Refs: tasks.md C5; requirements R4 / R5 / R6 / R8.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.integrations.carjam import CarjamError, CarjamRateLimitError
from app.modules.ppsr.exceptions import (
    PpsrCarjamNotConfiguredError,
    PpsrOwnerLookupsDisabledError,
    PpsrQuotaExceededError,
    PpsrS241PurposeRequiredError,
    PpsrSearchForbiddenError,
    PpsrSearchForgottenError,
    PpsrSearchNotFoundError,
)
from app.modules.ppsr.schemas import (
    PpsrLinkVehicleRequest,
    PpsrQuotaResponse,
    PpsrSearchListResponse,
    PpsrSearchRequest,
    PpsrSearchResult,
)
from app.modules.ppsr.service import PpsrService

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v2/ppsr", tags=["ppsr"])


# ---------------------------------------------------------------------------
# Request-state helpers
# ---------------------------------------------------------------------------
#
# AuthMiddleware populates ``request.state.{user_id, org_id, role}``
# (see ``app/middleware/auth.py:262-265``). The helpers below mirror
# the ``leave`` / ``staff`` routers — raise HTTP 401 when a required
# value is missing, raise HTTP 403 when an org-scoped endpoint is
# called by a global admin (no org_id set).


def _get_user_id(request: Request) -> UUID:
    """Resolve the authenticated user UUID from middleware state.

    Raises ``HTTP 401`` when no user is attached to the request — this
    happens when the JWT verification middleware bailed out before
    populating ``request.state.user_id``.
    """

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return UUID(str(user_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Authentication required") from exc


def _get_org_id_required(request: Request) -> UUID:
    """Resolve the org context — raise HTTP 403 ``ppsr_requires_org_context``
    when missing (G8: global-admin gate).

    Per design §5: "every PPSR router raises HTTPException(403,
    'ppsr_requires_org_context') when current_user.org_id is None."
    Global admins (no org membership) cannot use the PPSR module —
    they consume PPSR data via the Audit Log admin screen instead.
    """

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=403, detail="ppsr_requires_org_context")
    try:
        return UUID(str(org_id))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=403, detail="ppsr_requires_org_context") from exc


def _get_role(request: Request) -> str:
    return str(getattr(request.state, "role", "") or "")


def _build_current_user(request: Request) -> Any:
    """Adapter: build the lightweight "current_user" object the service
    expects from request-state primitives.

    :class:`PpsrService` reads only ``current_user.id``,
    ``current_user.role`` and (for audit-log defaults)
    ``current_user.org_id``. We avoid a full ``User`` row load — the
    service only needs identity + role for ownership / admin checks.
    """

    class _CurrentUser:
        __slots__ = ("id", "role", "org_id")

        def __init__(self, *, user_id: UUID, role: str, org_id: UUID | None) -> None:
            self.id = user_id
            self.role = role
            self.org_id = org_id

    user_id = _get_user_id(request)
    role = _get_role(request)
    raw_org_id = getattr(request.state, "org_id", None)
    org_uuid: UUID | None
    try:
        org_uuid = UUID(str(raw_org_id)) if raw_org_id else None
    except (ValueError, TypeError):
        org_uuid = None
    return _CurrentUser(user_id=user_id, role=role, org_id=org_uuid)


def _is_admin(request: Request) -> bool:
    """``org_admin`` is the only role that can forget / list-all-users.

    Global admins are never reachable here because
    :func:`_get_org_id_required` would already have raised 403.
    """

    return _get_role(request) == "org_admin"


# ---------------------------------------------------------------------------
# Exception → HTTP status mapping helpers
# ---------------------------------------------------------------------------


def _raise_forgotten(exc: PpsrSearchForgottenError) -> None:
    """Map :class:`PpsrSearchForgottenError` → HTTP 410 (G29)."""

    raise HTTPException(
        status_code=410,
        detail={
            "detail": "search_forgotten",
            "forgotten_at": exc.forgotten_at.isoformat(),
        },
    )


def _raise_carjam_rate_limit(exc: CarjamRateLimitError) -> None:
    """Map :class:`CarjamRateLimitError` → HTTP 429 with Retry-After header."""

    retry_after = max(int(getattr(exc, "retry_after", 1) or 1), 1)
    raise HTTPException(
        status_code=429,
        detail={"detail": "carjam_rate_limit", "retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )


# ---------------------------------------------------------------------------
# POST /search
# ---------------------------------------------------------------------------


@router.post(
    "/search",
    response_model=PpsrSearchResult,
    responses={
        200: {"description": "PPSR search result (cached or fresh)"},
        402: {"description": "PPSR quota exceeded"},
        403: {"description": "Module disabled / global-admin gate"},
        422: {"description": "CarJam not configured / s241 missing"},
        429: {"description": "CarJam upstream rate limit"},
        502: {"description": "CarJam upstream error"},
    },
    summary="Run a PPSR check (cache-first)",
)
async def post_search(
    payload: PpsrSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> PpsrSearchResult:
    """Perform a PPSR search — cache hit when within TTL, otherwise
    fresh CarJam call (per design §4.2).

    Maps service-layer exceptions to the HTTP statuses agreed in
    design §5. The service handles audit logging, quota increment,
    encryption, and vehicle linking; this endpoint is a translation
    layer only.
    """

    org_id = _get_org_id_required(request)
    user_id = _get_user_id(request)
    current_user = _build_current_user(request)

    service = PpsrService(db, redis)
    try:
        result = await service.search(
            org_id=org_id,
            user_id=user_id,
            current_user=current_user,
            rego=payload.rego,
            options=payload.to_options(),
            force_refresh=payload.force_refresh,
        )
    except PpsrCarjamNotConfiguredError:
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "carjam_not_configured",
                "help_url": "/admin/integrations",
            },
        )
    except PpsrQuotaExceededError as exc:
        raise HTTPException(
            status_code=402,
            detail={
                "detail": "ppsr_quota_exceeded",
                "used": exc.used,
                "included": exc.included,
            },
        )
    except PpsrS241PurposeRequiredError:
        raise HTTPException(
            status_code=422,
            detail={"detail": "s241_purpose_required"},
        )
    except PpsrOwnerLookupsDisabledError:
        raise HTTPException(
            status_code=422,
            detail={"detail": "s241_not_authorised"},
        )
    except CarjamRateLimitError as exc:
        _raise_carjam_rate_limit(exc)
    except CarjamError as exc:
        logger.warning("CarJam upstream error during PPSR search: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"detail": "carjam_upstream_error"},
        )

    return result


# ---------------------------------------------------------------------------
# GET /searches  (history list)
# ---------------------------------------------------------------------------


@router.get(
    "/searches",
    response_model=PpsrSearchListResponse,
    summary="List PPSR search history",
)
async def list_searches(
    request: Request,
    rego: str | None = Query(None, description="Filter by rego (exact, uppercase)"),
    match: str | None = Query(
        None,
        description="Filter by money-owing match value (Y/PY/M/PM/U/N)",
    ),
    user_id: UUID | None = Query(
        None,
        description="Filter by user (admin only — non-admins see only their own)",
    ),
    date_from: datetime | None = Query(None, description="Earliest created_at"),
    date_to: datetime | None = Query(None, description="Latest created_at"),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> PpsrSearchListResponse:
    """Paginated history list (denormalised summary only — never the
    encrypted blob; G31).

    The service force-filters non-admins to their own searches and
    applies the documented ``offset`` / ``limit`` clamps (1..100).
    """

    org_id = _get_org_id_required(request)
    current_user = _build_current_user(request)

    service = PpsrService(db, redis)
    return await service.list_searches(
        org_id=org_id,
        current_user=current_user,
        rego=rego,
        match=match,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# GET /searches/{id}  (detail)
# ---------------------------------------------------------------------------


@router.get(
    "/searches/{search_id}",
    response_model=PpsrSearchResult,
    responses={
        200: {"description": "Decrypted PPSR detail"},
        403: {"description": "Module disabled / global-admin gate / not owner"},
        404: {"description": "Search not found"},
        410: {"description": "Search payload forgotten (G29)"},
    },
    summary="Get a saved PPSR search detail",
)
async def get_search(
    search_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> PpsrSearchResult:
    """Decrypt + return the full saved PPSR result (R6.2).

    Returns ``HTTP 410`` when ``forgotten_at`` is set on the row so
    the frontend can render a "(payload forgotten)" state without
    losing the audit trail (G26 / G29).
    """

    _get_org_id_required(request)
    current_user = _build_current_user(request)

    service = PpsrService(db, redis)
    try:
        return await service.get_search(search_id, current_user)
    except PpsrSearchNotFoundError:
        raise HTTPException(status_code=404, detail="search_not_found")
    except PpsrSearchForbiddenError:
        raise HTTPException(status_code=403, detail="forbidden")
    except PpsrSearchForgottenError as exc:
        _raise_forgotten(exc)


# ---------------------------------------------------------------------------
# GET /searches/{id}/export  (PDF)
# ---------------------------------------------------------------------------


@router.get(
    "/searches/{search_id}/export",
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "PPSR PDF export",
        },
        403: {"description": "Module disabled / global-admin gate / not owner"},
        404: {"description": "Search not found"},
        410: {"description": "Search payload forgotten (G29)"},
    },
    summary="Export a saved PPSR search as PDF",
)
async def export_search(
    search_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Render + stream the saved PPSR result as a PDF (R6.3).

    Delegates rendering to :func:`PpsrService.render_pdf` (which
    internally calls :mod:`app.modules.ppsr.pdf`). Returns ``HTTP 410``
    when the row's payload was forgotten (G29).
    """

    _get_org_id_required(request)
    current_user = _build_current_user(request)

    service = PpsrService(db, redis)
    try:
        pdf_bytes = await service.render_pdf(search_id, current_user)
    except PpsrSearchNotFoundError:
        raise HTTPException(status_code=404, detail="search_not_found")
    except PpsrSearchForbiddenError:
        raise HTTPException(status_code=403, detail="forbidden")
    except PpsrSearchForgottenError as exc:
        _raise_forgotten(exc)

    # Try to surface the rego in the filename — fall back to the search
    # id when the row can't be re-fetched cheaply (the renderer already
    # validated it exists).
    filename = f"ppsr_{search_id}.pdf"
    try:
        from sqlalchemy import select

        from app.modules.ppsr.models import PpsrSearch

        result = await db.execute(
            select(PpsrSearch.rego).where(PpsrSearch.id == search_id),
        )
        rego = result.scalar_one_or_none()
        if rego:
            filename = f"ppsr_{rego}.pdf"
    except Exception:  # pragma: no cover — filename is best-effort
        pass

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---------------------------------------------------------------------------
# DELETE /searches/{id}/forget  (admin-only payload wipe)
# ---------------------------------------------------------------------------


@router.delete(
    "/searches/{search_id}/forget",
    status_code=204,
    responses={
        204: {"description": "Payload wiped"},
        403: {"description": "Org-admin role required / global-admin gate"},
        404: {"description": "Search not found"},
    },
    summary="Forget (wipe) a PPSR search payload — org_admin only",
)
async def forget_search(
    search_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> Response:
    """Admin-only payload wipe (R6.4 / G26 / G29).

    Belt-and-braces: the service also enforces ``org_admin`` via
    :meth:`PpsrService._is_admin`, but we surface the 403 here too so
    the frontend never even reaches the service for non-admins.
    """

    _get_org_id_required(request)
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="org_admin_required")

    current_user = _build_current_user(request)

    service = PpsrService(db, redis)
    try:
        await service.forget_search(search_id, current_user)
    except PpsrSearchNotFoundError:
        raise HTTPException(status_code=404, detail="search_not_found")
    except PpsrSearchForbiddenError:
        # The service raises this when the role check inside the service
        # layer disagrees — defence-in-depth keeps it as 403.
        raise HTTPException(status_code=403, detail="forbidden")

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /searches/{id}/link-vehicle
# ---------------------------------------------------------------------------


@router.post(
    "/searches/{search_id}/link-vehicle",
    responses={
        200: {"description": "Search linked to vehicle"},
        403: {"description": "Module disabled / global-admin gate / not owner"},
        404: {"description": "Search not found"},
    },
    summary="Link a PPSR search to an OrgVehicle row (G23)",
)
async def link_vehicle(
    search_id: UUID,
    payload: PpsrLinkVehicleRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> dict[str, str]:
    """Bind a saved PPSR search to an :class:`OrgVehicle` row so the
    vehicle profile can surface the latest check (G23).

    Ownership is enforced inside the service: org_admin may link any
    org search; non-admins can only link their own.
    """

    _get_org_id_required(request)
    current_user = _build_current_user(request)

    service = PpsrService(db, redis)
    try:
        await service.link_vehicle(
            search_id=search_id,
            org_vehicle_id=payload.org_vehicle_id,
            current_user=current_user,
        )
    except PpsrSearchNotFoundError:
        raise HTTPException(status_code=404, detail="search_not_found")
    except PpsrSearchForbiddenError:
        raise HTTPException(status_code=403, detail="forbidden")

    return {
        "status": "linked",
        "search_id": str(search_id),
        "org_vehicle_id": str(payload.org_vehicle_id),
    }


# ---------------------------------------------------------------------------
# GET /quota
# ---------------------------------------------------------------------------


@router.get(
    "/quota",
    response_model=PpsrQuotaResponse,
    summary="Current org PPSR quota usage",
)
async def get_quota(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> PpsrQuotaResponse:
    """Return ``{ used, included, hidden_plate_used,
    hidden_plate_included, resets_at }`` (G44).

    Powers the quota strip on the search page (design §6.1a).
    """

    org_id = _get_org_id_required(request)
    service = PpsrService(db, redis)
    return await service.get_quota(org_id)


__all__ = ["router"]
