"""API router for accounting software integration (Xero & MYOB).

Endpoints:
  GET  /                         — get all accounting integration data (dashboard view)
  GET  /connections              — list connected accounting software
  POST /connect/{provider}       — initiate OAuth flow
  GET  /callback/{provider}      — OAuth callback
  POST /disconnect/{provider}    — disconnect provider
  POST /sync/{provider}          — manual retry sync
  POST /sync/{entry_id}/retry    — retry a specific failed sync
  GET  /sync-log                 — view sync log

Requirements: 68.1, 68.2, 68.3, 68.4, 68.5, 68.6
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.accounting.schemas import (
    VALID_PROVIDERS,
    AccountingConnectionListResponse,
    AccountingConnectionResponse,
    AccountingDashboardResponse,
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

import logging

_logger = logging.getLogger(__name__)

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


def _request_base_url(request: Request) -> str:
    """Derive the public-facing base URL from the incoming request.

    Checks multiple sources in order:
    1. ``Origin`` header (present on POST/CORS requests)
    2. ``X-Forwarded-Proto`` + ``Host`` headers (set by reverse proxy)
    3. The request URL's scheme + host as final fallback
    """
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")

    # nginx sets Host and X-Forwarded-Proto
    host = request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto", "https")
    if host:
        return f"{proto}://{host}".rstrip("/")

    # Final fallback
    from urllib.parse import urlparse
    parsed = urlparse(str(request.url))
    return f"{parsed.scheme}://{parsed.netloc}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=AccountingDashboardResponse, dependencies=[require_role("org_admin")])
async def get_accounting_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get consolidated accounting integration data for dashboard view.

    Returns connection status for both Xero and MYOB, plus recent sync log.
    Org_Admin only.
    Requirements: 68.1, 68.2, 68.6
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Get connections
    connections_result = await list_connections(db, org_id=org_uuid)
    connections_by_provider = {
        c["provider"]: c for c in connections_result["connections"]
    }

    # Get sync log (last 50 entries)
    sync_log_result = await get_sync_log(db, org_id=org_uuid, provider=None, limit=50)

    # Build response
    xero_conn = connections_by_provider.get("xero", {})
    myob_conn = connections_by_provider.get("myob", {})

    from app.modules.accounting.schemas import AccountingConnectionDetail, SyncLogEntryDashboard

    return AccountingDashboardResponse(
        xero=AccountingConnectionDetail(
            provider="xero",
            connected=xero_conn.get("is_connected", False),
            account_name=xero_conn.get("account_name"),
            connected_at=xero_conn.get("created_at"),
            last_sync_at=xero_conn.get("last_sync_at"),
            sync_status=xero_conn.get("sync_status", "idle"),
            error_message=xero_conn.get("error_message"),
        ),
        myob=AccountingConnectionDetail(
            provider="myob",
            connected=myob_conn.get("is_connected", False),
            account_name=myob_conn.get("account_name"),
            connected_at=myob_conn.get("created_at"),
            last_sync_at=myob_conn.get("last_sync_at"),
            sync_status=myob_conn.get("sync_status", "idle"),
            error_message=myob_conn.get("error_message"),
        ),
        sync_log=[
            SyncLogEntryDashboard(
                id=entry["id"],
                provider=entry["provider"],
                entity_type=entry["entity_type"],
                entity_id=entry["entity_id"],
                entity_ref=entry.get("external_id") or entry["entity_id"],
                status="success" if entry["status"] == "synced" else "failed",
                error_message=entry.get("error_message"),
                synced_at=entry["created_at"],
            )
            for entry in sync_log_result["entries"]
        ],
    )


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

    url = await initiate_oauth(db, org_id=org_uuid, provider=provider, base_url=_request_base_url(request))
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

    base = _request_base_url(request)
    _logger.info(
        "OAuth callback: host=%s proto=%s base_url=%s",
        request.headers.get("host"),
        request.headers.get("x-forwarded-proto"),
        base,
    )

    result = await handle_oauth_callback(
        db, org_id=org_uuid, provider=provider, code=code, base_url=base,
    )

    # Redirect the browser back to the frontend accounting settings page
    # instead of returning raw JSON (this is a browser redirect from Xero).
    if isinstance(result, str):
        # Error — redirect with error query param
        from urllib.parse import quote
        return RedirectResponse(
            url=f"{base}/settings/accounting?error={quote(result)}",
            status_code=302,
        )

    return RedirectResponse(
        url=f"{base}/settings/accounting?connected={provider}",
        status_code=302,
    )


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


@router.post("/sync/{entry_id}/retry")
async def retry_sync_entry_endpoint(
    entry_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Retry a specific failed sync entry.

    Org_Admin only.
    Requirements: 68.6
    """
    auth = _require_org_admin(request)
    if isinstance(auth, JSONResponse):
        return auth
    org_uuid, _ = auth

    try:
        entry_uuid = uuid.UUID(entry_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid entry ID format"},
        )

    # Look up the failed sync entry and retry it
    from app.modules.accounting.service import _reconstruct_entity_data, sync_entity
    from app.modules.accounting.models import AccountingSyncLog
    from sqlalchemy import select

    stmt = select(AccountingSyncLog).where(
        AccountingSyncLog.id == entry_uuid,
        AccountingSyncLog.org_id == org_uuid,
        AccountingSyncLog.status == "failed",
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Failed sync entry not found"},
        )

    entity_data = await _reconstruct_entity_data(
        db, org_id=org_uuid, entity_type=entry.entity_type, entity_id=entry.entity_id,
    )
    if entity_data is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Could not find {entry.entity_type} {entry.entity_id} in database"},
        )

    sync_result = await sync_entity(
        db,
        org_id=org_uuid,
        provider=entry.provider,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        entity_data=entity_data,
    )
    return JSONResponse(content=sync_result)


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
