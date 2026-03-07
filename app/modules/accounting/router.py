"""API router for accounting software integration (Xero & MYOB).

Endpoints:
  GET  /connections              — list connected accounting software
  POST /connect/{provider}       — initiate OAuth flow
  GET  /callback/{provider}      — OAuth callback
  POST /disconnect/{provider}    — disconnect provider
  POST /sync/{provider}          — manual retry sync
  GET  /sync-log                 — view sync log

Requirements: 68.1, 68.2, 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.accounting.schemas import (
    VALID_PROVIDERS,
    AccountingConnectionListResponse,
    AccountingConnectionResponse,
    OAuthRedirectResponse,
    SyncLogEntry,
    SyncLogListResponse,
    SyncStatusResponse,
)
from app.modules.accounting.service import (
    disconnect,
    get_sync_log,
    handle_oauth_callback,
    initiate_oauth,
    list_connections,
    retry_failed_syncs,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, str | None]:
    """Extract org_id and role from request state."""
    org_id = getattr(request.state, "org_id", None)
    role = getattr(request.state, "role", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
    except (ValueError, TypeError):
        return None, role
    return org_uuid, role


def _require_org_admin(request: Request) -> tuple[uuid.UUID, str] | JSONResponse:
    """Validate that the caller is an Org_Admin. Returns (org_uuid, role) or JSONResponse."""
    org_uuid, role = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage accounting integrations"},
        )
    return org_uuid, role


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/connections", response_model=AccountingConnectionListResponse)
async def list_connections_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all connected accounting software for the organisation.

    Org_Admin only.
    Requirements: 68.1, 68.2
    """
    auth = _require_org_admin(request)
    if isinstance(auth, JSONResponse):
        return auth
    org_uuid, _ = auth

    result = await list_connections(db, org_id=org_uuid)
    return AccountingConnectionListResponse(
        connections=[AccountingConnectionResponse(**c) for c in result["connections"]],
        total=result["total"],
    )


@router.post("/connect/{provider}", response_model=OAuthRedirectResponse)
async def connect_provider_endpoint(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Initiate OAuth flow to connect an accounting provider.

    Org_Admin only.
    Requirements: 68.1, 68.2
    """
    auth = _require_org_admin(request)
    if isinstance(auth, JSONResponse):
        return auth
    org_uuid, _ = auth

    if provider not in VALID_PROVIDERS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid provider. Must be one of: {', '.join(VALID_PROVIDERS)}"},
        )

    url = await initiate_oauth(db, org_id=org_uuid, provider=provider)
    if url is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Failed to generate authorization URL"},
        )

    return OAuthRedirectResponse(authorization_url=url)


@router.get("/callback/{provider}")
async def oauth_callback_endpoint(
    provider: str,
    request: Request,
    code: str = Query(..., description="Authorization code from provider"),
    state: str = Query("", description="State parameter for CSRF validation"),
    db: AsyncSession = Depends(get_db_session),
):
    """Handle OAuth callback from accounting provider.

    Exchanges the authorization code for tokens and stores them.
    Requirements: 68.1, 68.2
    """
    # Parse org_id from state
    org_uuid: uuid.UUID | None = None
    if state and ":" in state:
        try:
            org_uuid = uuid.UUID(state.split(":")[0])
        except (ValueError, IndexError):
            pass

    if org_uuid is None:
        # Fall back to request state (if user is authenticated)
        org_uuid, _ = _extract_org_context(request)

    if org_uuid is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Could not determine organisation from callback state"},
        )

    if provider not in VALID_PROVIDERS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid provider: {provider}"},
        )

    result = await handle_oauth_callback(
        db, org_id=org_uuid, provider=provider, code=code,
    )

    if isinstance(result, str):
        return JSONResponse(status_code=400, content={"detail": result})

    return AccountingConnectionResponse(**result)


@router.post("/disconnect/{provider}")
async def disconnect_provider_endpoint(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Disconnect an accounting provider.

    Org_Admin only.
    """
    auth = _require_org_admin(request)
    if isinstance(auth, JSONResponse):
        return auth
    org_uuid, _ = auth

    if provider not in VALID_PROVIDERS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid provider. Must be one of: {', '.join(VALID_PROVIDERS)}"},
        )

    disconnected = await disconnect(db, org_id=org_uuid, provider=provider)
    if not disconnected:
        return JSONResponse(
            status_code=404,
            content={"detail": f"No {provider} connection found"},
        )

    return JSONResponse(content={"message": f"{provider} disconnected successfully"})


@router.post("/sync/{provider}", response_model=SyncStatusResponse)
async def manual_sync_endpoint(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Manually retry failed syncs for a provider.

    Org_Admin only.
    Requirements: 68.6
    """
    auth = _require_org_admin(request)
    if isinstance(auth, JSONResponse):
        return auth
    org_uuid, _ = auth

    if provider not in VALID_PROVIDERS:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid provider. Must be one of: {', '.join(VALID_PROVIDERS)}"},
        )

    result = await retry_failed_syncs(db, org_id=org_uuid, provider=provider)
    return SyncStatusResponse(**result)


@router.get("/sync-log", response_model=SyncLogListResponse)
async def sync_log_endpoint(
    request: Request,
    provider: Optional[str] = Query(None, description="Filter by provider"),
    limit: int = Query(50, ge=1, le=200, description="Max entries to return"),
    db: AsyncSession = Depends(get_db_session),
):
    """View the accounting sync log.

    Org_Admin only.
    Requirements: 68.6
    """
    auth = _require_org_admin(request)
    if isinstance(auth, JSONResponse):
        return auth
    org_uuid, _ = auth

    result = await get_sync_log(db, org_id=org_uuid, provider=provider, limit=limit)
    return SyncLogListResponse(
        entries=[SyncLogEntry(**e) for e in result["entries"]],
        total=result["total"],
    )
