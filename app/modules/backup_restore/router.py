"""Global-Admin-only FastAPI router for Cloud Backup & Restore.

Mounted at ``/api/v1/backup`` behind ``require_role("global_admin")`` (every
route, via the router-level dependency). The route surface composes the already
built building blocks:

* **destinations** — list (masked creds) / create / edit / set-primary /
  OAuth connect + callback-with-postMessage-handoff / connection test /
  residency notice + acknowledge / delete (``BackupConfigService`` +
  ``ResidencyService``).
* **backups** — history ``{items,total}`` with ``offset``/``limit`` / run-now
  (background task) / job status / job cancel (``BackupService`` +
  ``JobService``).
* **restore** — dry-run (returns the ``older_schema`` flag + both versions,
  read-only) / full (``confirm_older_schema``; background task) / per-org
  (background task) / browse a backup's per-org contents / job cancel
  (pre-apply only → 409 ``CancelNotAllowedError`` once the destructive apply has
  begun). There is deliberately **no** in-flight ``confirm-schema`` endpoint —
  the older-schema confirmation is a pre-submission gate resolved by the dry-run
  + ``confirm_older_schema`` (Req 10.5-10.7).
* **keys** — status / setup / rotate / recovery-kit export / bootstrap
  (``BackupKeyService``).
* **config** — get / update / notification test (``BackupConfigService`` +
  ``BackupService.send_test_notification``).
* **rehearsals** — history ``{items,total}`` / run-now (background task)
  (``RehearsalService``).

Cross-cutting guarantees (Req 1.2/1.3/9.1/9.10): non-``global_admin`` → 403,
missing/invalid token → 401 (the ``require_role`` dependency + auth middleware);
every list response is ``{items,total}``; credentials are masked in responses;
errors are caught and returned as clean detail strings (never a stack trace);
backups and restores run as FastAPI ``BackgroundTasks``. Request handlers use the
``get_db_session`` dependency (``session.begin()`` auto-commit) and ``flush()``
(never ``commit()``); the background tasks open their own short-lived
``async_session_factory`` session.

Requirements: 1.1, 1.2, 1.3, 9.1, 9.10, 10.6, 11.1, 12.1, 12.16, 12.17, 14.1,
15.1, 16.7, 16.12, 18.12, 26.1, 30.7
"""

from __future__ import annotations

import logging
import secrets
import uuid
import asyncio
import contextlib
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import async_session_factory, get_db_session
from app.modules.auth.rbac import require_role
from app.modules.backup_restore.config_service import (
    BackupConfigService,
    ConfigValidationError,
    PrimaryDestinationError,
    mask_config,
)
from app.modules.backup_restore.jobs import (
    JobNotFoundError,
    JobService,
    TERMINAL_STATUSES,
)
from app.modules.backup_restore.keys.key_service import (
    BackupKeyService,
    KeyBootstrapError,
    KeyMaterialMismatchError,
    KeyMaterialMissingError,
    KeySetupError,
    KeyVersionUnavailableError,
    PassphraseStrengthError,
)
from app.modules.backup_restore.models import (
    BACKUP_SCOPES,
    Backup,
    BackupDestination,
    BackupJob,
    RestoreJob,
    RestoreRehearsal,
)
from app.modules.backup_restore.residency import (
    DestinationNotFoundError,
    ResidencyService,
)
from app.modules.backup_restore.restore.dry_run import (
    AlembicTargetVersionReader,
    DryRunService,
)
from app.modules.backup_restore.restore.full_restore import (
    CancellationToken,
    CancelNotAllowedError,
)
from app.modules.backup_restore.schemas import (
    BackupResponse,
    BrowseEntityResponse,
    BrowseOrgResponse,
    ChannelResultResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    ConnectionTestResponse,
    DestinationCreateRequest,
    DestinationEditRequest,
    DestinationResponse,
    DeletionConfirmBody,
    DeletionChallengeResponse,
    DeletionJobAcceptedResponse,
    DeletionJobStatusResponse,
    DeletionRequestBody,
    DeletionResultResponse,
    DryRunRequest,
    DryRunResponse,
    DryRunStepResponse,
    FullRestoreRequest,
    JobAcceptedResponse,
    JobStatusResponse,
    KeyBootstrapRequest,
    KeyBootstrapResponse,
    KeyRotateResponse,
    KeySetupRequest,
    KeySetupResponse,
    KeyStatusResponse,
    ListResponse,
    NotificationTestResponse,
    OAuthConnectResponse,
    PerOrgRestoreRequest,
    RecoveryKitResponse,
    RehearsalResponse,
    ResidencyAckResponse,
    ResidencyNoticeResponse,
    RunBackupRequest,
    StorageUsageResponse,
)
from app.modules.backup_restore.service import BackupService

logger = logging.getLogger(__name__)

# Every route requires a global_admin (Req 1.1/1.2/1.3). Non-global_admin → 403,
# missing/invalid token → 401 (handled inside the dependency + auth middleware).
router = APIRouter(
    prefix="/api/v1/backup",
    tags=["backup-restore"],
    dependencies=[require_role("global_admin")],
)

# Public router (NO global_admin dependency) for endpoints reached by a top-level
# browser redirect that cannot carry the app's JWT — specifically the OAuth
# callback the provider (Google / Microsoft) redirects to. It is authenticated
# by the OAuth authorization code + state and exchanges the code server-side with
# the client secret; the auth middleware also treats this path as public.
public_router = APIRouter(
    prefix="/api/v1/backup",
    tags=["backup-restore"],
)

# In-process registry of pre-apply cancellation tokens for running full restores
# (Req 12.16). A running full-restore background task registers its token under
# the restore-job id; the cancel endpoint trips it while the job is still
# pre-apply, and the run loop stops with no data applied.
_RESTORE_CANCEL_TOKENS: dict[str, CancellationToken] = {}


# ===========================================================================
# Helpers
# ===========================================================================
def _actor_id(request: Request) -> Optional[str]:
    """The acting Global_Admin's user id from the validated request state."""
    return getattr(request.state, "user_id", None)


def _clean_detail(exc: Exception) -> str:
    """A short, stack-trace-free reason string for a caught error (Req 9.10)."""
    from app.modules.backup_restore.restore.per_org_restore import (
        humanize_restore_db_error,
    )

    friendly = humanize_restore_db_error(exc)
    if friendly:
        return friendly
    text = str(exc).strip()
    # Never leak a raw SQL statement / bound parameters into the user-facing
    # message; the full detail remains in the logs.
    text = text.split("[SQL:")[0].strip().rstrip(":").strip()
    return text or exc.__class__.__name__


def _destination_response(
    dest: BackupDestination, cfg_service: BackupConfigService
) -> DestinationResponse:
    """Build a destination response with every credential field masked (Req 30.2)."""
    config = cfg_service._decrypt_config(dest.config_encrypted)  # noqa: SLF001
    return DestinationResponse(
        id=dest.id,
        provider_type=dest.provider_type,
        display_name=dest.display_name,
        is_primary=dest.is_primary,
        is_immutable_copy=dest.is_immutable_copy,
        connection_state=dest.connection_state,
        residency=dest.residency,
        lock_window_days=dest.lock_window_days,
        config=mask_config(config),
        created_at=dest.created_at,
        updated_at=dest.updated_at,
    )


async def _load_backup(db: AsyncSession, backup_id: uuid.UUID) -> Backup:
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    backup = result.scalars().first()
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    return backup


# Representative org-scoped tables used to decide whether an organisation is
# "empty" for the purposes of the restore-as-new (clone) policy. If any of these
# hold a row for the org, identity-bearing data already exists and inserting
# fresh copies would violate unique keys (e.g. login email).
_ORG_PRESENCE_TABLES = ("users", "customers", "invoices")


async def _org_has_data(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Whether the organisation already contains identity-bearing data.

    Used to gate the restore-as-new (clone) policy, which only makes sense for a
    new/empty organisation — inserting fresh copies into one that already has
    users/customers/invoices would collide on unique keys such as login email.
    """
    clauses = " OR ".join(
        f"EXISTS (SELECT 1 FROM {tbl} WHERE org_id = :org)"
        for tbl in _ORG_PRESENCE_TABLES
    )
    try:
        result = await db.execute(text(f"SELECT {clauses}"), {"org": str(org_id)})
        return bool(result.scalar())
    except Exception:  # noqa: BLE001 - if the probe fails, do not block the restore
        logger.debug("org-presence probe failed for %s", org_id, exc_info=True)
        return False


async def _primary_destination(db: AsyncSession) -> BackupDestination:
    """Return the configured primary destination, or 409 if none exists."""
    result = await db.execute(
        select(BackupDestination)
        .where(BackupDestination.is_primary.is_(True))
        .limit(1)
    )
    dest = result.scalars().first()
    if dest is None:
        raise HTTPException(
            status_code=409,
            detail="No primary backup destination is configured.",
        )
    return dest


async def _resolve_bdk(
    db: AsyncSession,
    backup: Backup,
    *,
    recovery_kit: Optional[dict[str, Any]],
    passphrase: Optional[str],
) -> bytes:
    """Resolve the Backup_Data_Key for *backup* (seamless path or bootstrap).

    When recovery key material is supplied (fresh-deployment DR, Req 16.7) the
    BDK is unwrapped from the kit + passphrase; otherwise the seamless
    ``ENCRYPTION_MASTER_KEY`` path is used for the backup's recorded key version.
    """
    keys = BackupKeyService(db)
    if recovery_kit and passphrase:
        return await keys.bootstrap(recovery_kit, passphrase, version=backup.key_version)
    if backup.key_version is not None:
        return await keys.get_bdk(backup.key_version)
    _version, bdk = await keys.get_active_bdk()
    return bdk


async def _build_artifact_reader(
    db: AsyncSession,
    backup: Backup,
    *,
    recovery_kit: Optional[dict[str, Any]] = None,
    passphrase: Optional[str] = None,
):
    """Build a :class:`StorageArtifactReader` for *backup* from the primary
    destination + the resolved BDK (provider-agnostic, Req 3 / 16)."""
    from app.modules.backup_restore.restore.per_org_restore import StorageArtifactReader
    from app.modules.backup_restore.storage import resolve_adapter

    dest = await _primary_destination(db)
    cfg_service = BackupConfigService(db)
    config = cfg_service._decrypt_config(dest.config_encrypted)  # noqa: SLF001
    storage = resolve_adapter(dest.provider_type, config)
    bdk = await _resolve_bdk(
        db, backup, recovery_kit=recovery_kit, passphrase=passphrase
    )
    return StorageArtifactReader(storage, bdk, db, backup.id)


def _oauth_redirect_uri(request: Request, destination_id: uuid.UUID) -> str:
    """Build the OAuth callback URL.

    The provider (Google / Microsoft) requires the redirect_uri sent during the
    auth + token-exchange to EXACTLY match the URI the operator registered — and
    that is the public URL the browser used (e.g. https://devin.oraflows.co.nz),
    not the scheme/host the app sees behind a TLS-terminating proxy.

    Behind Cloudflare → nginx the app's own ``request.base_url`` reports
    ``http://<host>`` (the app isn't started with ``--proxy-headers``), which
    Google rejects for a non-localhost host. So honour the proxy's
    ``X-Forwarded-Proto`` / ``X-Forwarded-Host`` (falling back to the ``Host``
    header, then ``request.base_url``) to reconstruct the public origin.
    """
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded_proto and forwarded_host:
        # Take the first hop if a comma-separated chain is present.
        scheme = forwarded_proto.split(",")[0].strip()
        host = forwarded_host.split(",")[0].strip()
        base = f"{scheme}://{host}"
    else:
        base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/backup/destinations/{destination_id}/oauth/callback"


def _postmessage_html(payload: dict[str, Any]) -> str:
    """A tiny self-closing page that hands the OAuth result back to the opener.

    The SPA popup opener receives a ``backup-oauth`` message and refetches the
    destinations so the row flips to ``connected`` with no dead-end page
    (Req 2.5, frontend task 17.3).
    """
    import json

    data = json.dumps({"type": "backup-oauth", **payload})
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Backup authorization</title></head><body>"
        "<p>You can close this window.</p><script>"
        f"(function(){{var m={data};"
        "try{if(window.opener){window.opener.postMessage(m,'*');}}catch(e){}"
        "window.close();}})();"
        "</script></body></html>"
    )


def _job_status_response(view, job=None) -> JobStatusResponse:
    return JobStatusResponse(
        id=view.id,
        status=view.status,
        progress_pct=view.progress_pct,
        elapsed_seconds=view.elapsed_seconds,
        seconds_since_last_update=view.seconds_since_last_update,
        outcome_summary=getattr(job, "outcome_summary", None) if job is not None else None,
        error_message=getattr(job, "error_message", None) if job is not None else None,
        backup_id=getattr(job, "backup_id", None) if job is not None else None,
    )


# ===========================================================================
# Destinations
# ===========================================================================
@router.get("/destinations", response_model=ListResponse[DestinationResponse])
async def list_destinations(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> ListResponse[DestinationResponse]:
    """List configured destinations with credentials masked (Req 30.2)."""
    cfg_service = BackupConfigService(db)
    destinations = await cfg_service.list_destinations()
    total = len(destinations)
    page = destinations[offset : offset + limit]
    items = [_destination_response(d, cfg_service) for d in page]
    return ListResponse[DestinationResponse](items=items, total=total)


@router.post("/destinations", response_model=DestinationResponse, status_code=201)
async def create_destination(
    body: DestinationCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DestinationResponse:
    """Create a backup destination (credentials encrypted, Req 2.1 / 30.2)."""
    cfg_service = BackupConfigService(db)
    try:
        dest = await cfg_service.create_destination(
            provider_type=body.provider_type,
            display_name=body.display_name,
            config=body.config,
            residency=body.residency,
            is_immutable_copy=body.is_immutable_copy,
            lock_window_days=body.lock_window_days,
            actor_id=_actor_id(request),
        )
    except (ValueError, ConfigValidationError) as exc:
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    return _destination_response(dest, cfg_service)


@router.put("/destinations/{destination_id}", response_model=DestinationResponse)
async def edit_destination(
    destination_id: uuid.UUID,
    body: DestinationEditRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DestinationResponse:
    """Edit a destination, preserving masked credentials (Req 30.7)."""
    updates: dict[str, Any] = body.model_dump(exclude_unset=True)
    cfg_service = BackupConfigService(db)
    try:
        dest = await cfg_service.edit_destination(
            destination_id, updates, actor_id=_actor_id(request)
        )
    except DestinationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_clean_detail(exc))
    except (ValueError, ConfigValidationError) as exc:
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    return _destination_response(dest, cfg_service)


@router.post(
    "/destinations/{destination_id}/set-primary",
    response_model=ListResponse[DestinationResponse],
)
async def set_primary_destination(
    destination_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ListResponse[DestinationResponse]:
    """Atomically designate the primary destination (exactly-one-primary, Req 30.7)."""
    cfg_service = BackupConfigService(db)
    try:
        destinations = await cfg_service.set_primary(
            destination_id, actor_id=_actor_id(request)
        )
    except DestinationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_clean_detail(exc))
    except PrimaryDestinationError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    items = [_destination_response(d, cfg_service) for d in destinations]
    return ListResponse[DestinationResponse](items=items, total=len(items))


@router.delete("/destinations/{destination_id}", status_code=204)
async def delete_destination(
    destination_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a destination (the primary cannot be deleted directly)."""
    result = await db.execute(
        select(BackupDestination).where(BackupDestination.id == destination_id)
    )
    dest = result.scalars().first()
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    if dest.is_primary:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the primary destination; set another "
            "destination as primary first.",
        )
    await db.delete(dest)
    await db.flush()
    return None


@router.post(
    "/destinations/{destination_id}/test", response_model=ConnectionTestResponse
)
async def test_destination(
    destination_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ConnectionTestResponse:
    """Run a connection test against a destination (Req 2.7)."""
    from app.modules.backup_restore.storage import resolve_adapter
    from app.modules.backup_restore.storage.errors import StorageError

    result = await db.execute(
        select(BackupDestination).where(BackupDestination.id == destination_id)
    )
    dest = result.scalars().first()
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    cfg_service = BackupConfigService(db)
    config = cfg_service._decrypt_config(dest.config_encrypted)  # noqa: SLF001
    try:
        adapter = resolve_adapter(dest.provider_type, config)
        state = await adapter.connection_status()
        state_value = state.value if hasattr(state, "value") else str(state)
        if state_value == "connected":
            detail = "Connection test succeeded."
        elif state_value == "disconnected":
            detail = (
                "Not connected. Re-authorise the destination (click Connect) and try again."
            )
        else:
            detail = "Connection test failed."
    except StorageError as exc:
        state_value = "error"
        detail = _clean_detail(exc)
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace
        state_value = "error"
        detail = _clean_detail(exc)
    dest.connection_state = (
        state_value if state_value in ("connected", "disconnected", "error") else "error"
    )
    await db.flush()
    return ConnectionTestResponse(state=state_value, detail=detail)


@router.get(
    "/destinations/{destination_id}/storage",
    response_model=StorageUsageResponse,
)
async def get_destination_storage(
    destination_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> StorageUsageResponse:
    """Report a destination's total/used/available storage, if the provider
    exposes it (Google Drive, OneDrive). Object stores with no quota concept
    report ``reported=false``. Never errors the page: any provider/network
    failure resolves to ``reported=false``."""
    from app.modules.backup_restore.storage import resolve_adapter

    result = await db.execute(
        select(BackupDestination).where(BackupDestination.id == destination_id)
    )
    dest = result.scalars().first()
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    cfg_service = BackupConfigService(db)
    config = cfg_service._decrypt_config(dest.config_encrypted)  # noqa: SLF001
    try:
        adapter = resolve_adapter(dest.provider_type, config)
        usage = await adapter.storage_usage()
    except Exception:  # noqa: BLE001 - usage is best-effort, never fatal
        usage = None
    if usage is None:
        return StorageUsageResponse(reported=False)
    return StorageUsageResponse(
        reported=usage.total_bytes is not None or usage.used_bytes is not None,
        total_bytes=usage.total_bytes,
        used_bytes=usage.used_bytes,
        available_bytes=usage.available_bytes,
    )


@router.get(
    "/destinations/{destination_id}/residency",
    response_model=ResidencyNoticeResponse,
)
async def get_residency_notice(
    destination_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> ResidencyNoticeResponse:
    """Return the data-residency disclosure notice for a destination (Req 20)."""
    result = await db.execute(
        select(BackupDestination).where(BackupDestination.id == destination_id)
    )
    dest = result.scalars().first()
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    residency_service = ResidencyService(db)
    notice = residency_service.disclosure_notice(dest)
    acknowledged = await residency_service.is_acknowledged(dest.id)
    return ResidencyNoticeResponse(
        residency=notice.residency,
        destination_label=notice.destination_label,
        offshore_warning=notice.offshore_warning,
        requires_acknowledgement=notice.requires_acknowledgement,
        headline=notice.headline,
        body=notice.body,
        biometric_notice=notice.biometric_notice,
        text=notice.text,
        acknowledged=acknowledged,
    )


@router.post(
    "/destinations/{destination_id}/residency",
    response_model=ResidencyAckResponse,
)
async def acknowledge_residency(
    destination_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ResidencyAckResponse:
    """Persist a Global_Admin acknowledgement of a destination's residency (Req 20.3)."""
    actor = _actor_id(request)
    if not actor:
        raise HTTPException(status_code=401, detail="Authentication required")
    residency_service = ResidencyService(db)
    try:
        ack = await residency_service.record_acknowledgement(destination_id, actor)
    except DestinationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_clean_detail(exc))
    return ResidencyAckResponse(
        destination_id=ack.destination_id,
        acknowledged=True,
        acknowledged_at=ack.acknowledged_at,
    )


@router.get(
    "/destinations/{destination_id}/oauth/connect",
    response_model=OAuthConnectResponse,
)
async def oauth_connect(
    destination_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OAuthConnectResponse:
    """Build the provider authorization URL for the SPA popup (Req 2.5)."""
    result = await db.execute(
        select(BackupDestination).where(BackupDestination.id == destination_id)
    )
    dest = result.scalars().first()
    if dest is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    cfg_service = BackupConfigService(db)
    config = cfg_service._decrypt_config(dest.config_encrypted)  # noqa: SLF001
    provider = dest.provider_type
    client_id = config.get("client_id")
    if provider not in ("google_drive", "onedrive"):
        raise HTTPException(
            status_code=422, detail=f"Provider {provider!r} does not use OAuth."
        )
    if not client_id:
        raise HTTPException(
            status_code=422,
            detail="An OAuth client_id must be configured before connecting.",
        )
    redirect_uri = _oauth_redirect_uri(request, destination_id)
    state = secrets.token_urlsafe(24)
    if provider == "google_drive":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.file",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        authorization_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        )
    else:  # onedrive
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "offline_access Files.ReadWrite",
            "state": state,
        }
        authorization_url = (
            "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
            + urlencode(params)
        )
    return OAuthConnectResponse(authorization_url=authorization_url, state=state)


@public_router.get("/destinations/{destination_id}/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    destination_id: uuid.UUID,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """OAuth redirect handler: exchange the code, store the refresh token, hand
    off to the SPA via ``postMessage`` (no dead-end page, Req 2.5)."""
    if error or not code:
        return HTMLResponse(
            _postmessage_html(
                {"ok": False, "destination_id": str(destination_id),
                 "error": error or "authorization was not completed", "state": state}
            )
        )
    try:
        result = await db.execute(
            select(BackupDestination).where(BackupDestination.id == destination_id)
        )
        dest = result.scalars().first()
        if dest is None:
            raise ValueError("destination not found")
        cfg_service = BackupConfigService(db)
        config = cfg_service._decrypt_config(dest.config_encrypted)  # noqa: SLF001
        tokens = await _exchange_oauth_code(
            dest.provider_type,
            config,
            code=code,
            redirect_uri=_oauth_redirect_uri(request, destination_id),
        )
        await cfg_service.edit_destination(
            destination_id, {"config": tokens}, actor_id=_actor_id(request)
        )
        dest.connection_state = "connected"
        await db.flush()
        return HTMLResponse(
            _postmessage_html(
                {"ok": True, "destination_id": str(destination_id), "state": state}
            )
        )
    except Exception as exc:  # noqa: BLE001 - always hand a clean result to the popup
        logger.warning("OAuth callback failed for destination %s", destination_id)
        return HTMLResponse(
            _postmessage_html(
                {"ok": False, "destination_id": str(destination_id),
                 "error": _clean_detail(exc), "state": state}
            )
        )


async def _exchange_oauth_code(
    provider: str, config: dict[str, Any], *, code: str, redirect_uri: str
) -> dict[str, Any]:
    """Exchange an OAuth authorization code for tokens (Google / Microsoft)."""
    import httpx

    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError("OAuth client credentials are not configured.")

    if provider == "google_drive":
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    elif provider == "onedrive":
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": "offline_access Files.ReadWrite",
        }
    else:
        raise ValueError(f"provider {provider!r} does not use OAuth")

    async with httpx.AsyncClient(timeout=20.0) as http:
        resp = await http.post(token_url, data=data)
    if resp.status_code >= 400:
        raise ValueError("the provider rejected the authorization code")
    payload = resp.json()
    tokens: dict[str, Any] = {}
    if payload.get("refresh_token"):
        tokens["refresh_token"] = payload["refresh_token"]
    if payload.get("access_token"):
        tokens["access_token"] = payload["access_token"]
    if not tokens:
        raise ValueError("the provider returned no usable tokens")
    return tokens


# ===========================================================================
# Backups + jobs
# ===========================================================================
@router.get("/backups", response_model=ListResponse[BackupResponse])
async def list_backups(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> ListResponse[BackupResponse]:
    """Backup history ``{items,total}`` with ``offset``/``limit`` (Req 9.1)."""
    total = (
        await db.execute(select(func.count()).select_from(Backup))
    ).scalar_one()
    result = await db.execute(
        select(Backup).order_by(Backup.created_at.desc()).offset(offset).limit(limit)
    )
    rows = result.scalars().all()
    # Which of these backups were manually created (a manual backup_jobs row
    # references them) — only those are operator-deletable.
    page_ids = [b.id for b in rows]
    manual_ids: set[uuid.UUID] = set()
    if page_ids:
        manual_rows = await db.execute(
            text(
                """
                SELECT DISTINCT backup_id FROM backup_jobs
                WHERE backup_id = ANY(:ids) AND triggered_by = 'manual'
                """
            ),
            {"ids": [str(i) for i in page_ids]},
        )
        manual_ids = {r[0] for r in manual_rows.fetchall()}
    items = []
    for b in rows:
        item = BackupResponse.model_validate(b)
        item.is_manual = b.id in manual_ids
        items.append(item)
    return ListResponse[BackupResponse](items=items, total=total)


@router.get("/backups/{backup_id}/bundle")
async def download_backup_bundle(
    backup_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> FileResponse:
    """Download a backup as a single portable ``.tar`` bundle (DR / portability).

    Packages the backup's encrypted dump + manifest + every referenced File_Blob
    into one self-contained file (ciphertext only — the Recovery Kit/passphrase
    are never included). The bundle can be kept anywhere and later uploaded to a
    fresh server to restore without configuring a destination.
    """
    import os
    import shutil

    from starlette.background import BackgroundTask

    from app.modules.backup_restore.portable import BundleError, build_backup_bundle
    from app.modules.backup_restore.service import _resolve_primary_storage

    backup = await _load_backup(db, backup_id)
    primary, storage = await _resolve_primary_storage(db)
    if primary is None or storage is None:
        raise HTTPException(
            status_code=409, detail="No primary backup destination is configured."
        )
    try:
        tar_path = await build_backup_bundle(db, storage, backup)
    except BundleError as exc:
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace
        logger.warning("Backup bundle export failed for %s", backup_id, exc_info=True)
        raise HTTPException(status_code=500, detail=_clean_detail(exc))

    base_dir = os.path.dirname(tar_path)
    return FileResponse(
        tar_path,
        media_type="application/x-tar",
        filename=f"orainvoice-backup-{backup_id}.tar",
        background=BackgroundTask(shutil.rmtree, base_dir, ignore_errors=True),
    )


@router.post("/backups", response_model=JobAcceptedResponse, status_code=202)
async def run_backup_now(
    body: RunBackupRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> JobAcceptedResponse:
    """Trigger an immediate backup as a background task (Req 8.8)."""
    actor = _actor_id(request)
    cfg_service = BackupConfigService(db)
    config = await cfg_service.get_config()
    scope = body.scope or config.default_scope
    if scope not in BACKUP_SCOPES:
        raise HTTPException(
            status_code=422, detail=f"scope must be one of {sorted(BACKUP_SCOPES)}"
        )
    # Create + COMMIT the job row in its own transaction BEFORE scheduling the
    # background task. The request's get_db_session only commits during yield
    # teardown, which (FastAPI >= 0.106) runs AFTER background tasks — so creating
    # the job on `db` lets the task query it before it is committed, find nothing,
    # and silently exit, leaving the job stuck 'queued' forever.
    job_id = uuid.uuid4()
    async with async_session_factory() as jdb:
        async with jdb.begin():
            jdb.add(
                BackupJob(
                    id=job_id, status="queued", scope=scope, triggered_by="manual"
                )
            )
    background.add_task(_run_backup_task, str(job_id), scope, actor)
    return JobAcceptedResponse(job_id=job_id, status="queued")


async def _run_backup_task(job_id: str, scope: str, actor: Optional[str]) -> None:
    """Background entry: run the backup pipeline for the queued job."""
    try:
        async with async_session_factory() as db:
            async with db.begin():
                result = await db.execute(
                    select(BackupJob).where(BackupJob.id == uuid.UUID(job_id))
                )
                job = result.scalars().first()
                if job is None:
                    return
                service = BackupService(db)
                await service.run_backup(
                    scope=scope,
                    triggered_by="manual",
                    actor_id=uuid.UUID(actor) if actor else None,
                    job=job,
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background backup task failed for job %s", job_id)
        # The pipeline marks the job failed inside the run's transaction, but that
        # transaction is rolled back when the exception propagates out of the
        # `db.begin()` block above — leaving the job stuck at 'queued' and the UI
        # spinning forever. Record the terminal failure in a fresh, independent
        # transaction (the original is already rolled back here, so there is no
        # row-lock contention) so the status poll surfaces the error.
        try:
            async with async_session_factory() as db2:
                async with db2.begin():
                    row = (
                        await db2.execute(
                            select(BackupJob).where(BackupJob.id == uuid.UUID(job_id))
                        )
                    ).scalars().first()
                    if row is not None and row.status not in (
                        "completed",
                        "failed",
                        "cancelled",
                    ):
                        row.status = "failed"
                        row.finished_at = datetime.now(timezone.utc)
                        row.outcome_summary = "Backup failed"
                        row.error_message = str(exc)[:1000]
        except Exception:  # noqa: BLE001 - best effort; already logged above
            logger.exception(
                "Could not record terminal failure for backup job %s", job_id
            )


@router.get("/backups/jobs/{job_id}", response_model=JobStatusResponse)
async def get_backup_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> JobStatusResponse:
    """Return a backup job's live status (Req 13.3)."""
    jobs = JobService(db)
    try:
        job = await jobs.get_job(job_id, BackupJob)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Backup job not found")
    await jobs.enforce_progress_timeout(job)  # force-fail a stalled job (Req 13.5)
    return _job_status_response(jobs.status_of(job), job)


@router.post("/backups/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_backup_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> JobStatusResponse:
    """Cancel a backup job (best-effort, Req 13.1)."""
    jobs = JobService(db)
    try:
        job = await jobs.get_job(job_id, BackupJob)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Backup job not found")
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Job already {job.status}")
    job = await jobs.cancel(job)
    return _job_status_response(jobs.status_of(job), job)


# ---------------------------------------------------------------------------
# Manual backup deletion — gated behind an emailed 6-digit verification code.
# ---------------------------------------------------------------------------
@router.post("/backups/delete/request", response_model=DeletionChallengeResponse)
async def request_backup_deletion(
    body: DeletionRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> DeletionChallengeResponse:
    """Start a backup deletion: email the requesting admin a verification code.

    Validates that the selection is manually-created and not already removed,
    then sends a single-use 6-digit code that must be presented to
    ``/backups/delete/confirm``. No backup is touched here.
    """
    from app.core.audit import write_audit_log
    from app.modules.backup_restore.deletion import (
        NoDeletableBackupsError,
        all_manual_backup_ids,
        create_deletion_challenge,
    )

    actor = _actor_id(request)
    if not actor:
        raise HTTPException(
            status_code=401, detail="Could not identify the requesting user."
        )
    actor_uuid = uuid.UUID(actor)

    recipient = (
        await db.execute(
            text("SELECT email FROM users WHERE id = :id"), {"id": str(actor_uuid)}
        )
    ).scalar()
    if not recipient:
        raise HTTPException(
            status_code=400,
            detail="Your account has no email address to send the code to.",
        )

    if body.all_manual:
        ids = await all_manual_backup_ids(db)
    else:
        ids = body.backup_ids or []
    if not ids:
        raise HTTPException(
            status_code=400, detail="Select at least one backup to delete."
        )

    try:
        challenge = await create_deletion_challenge(
            db, requested_by=actor_uuid, recipient_email=recipient, backup_ids=ids
        )
    except NoDeletableBackupsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:  # email delivery failed
        raise HTTPException(status_code=502, detail=str(exc))

    with contextlib.suppress(Exception):
        await write_audit_log(
            db,
            action="backup.delete_requested",
            entity_type="backup",
            user_id=actor_uuid,
            after_value={"backup_count": challenge.backup_count},
            ip_address=request.client.host if request.client else None,
        )

    return DeletionChallengeResponse(
        challenge_id=challenge.challenge_id,
        expires_at=challenge.expires_at,
        recipient=challenge.recipient_masked,
        backup_count=challenge.backup_count,
    )


@router.post(
    "/backups/delete/confirm",
    response_model=DeletionJobAcceptedResponse,
    status_code=202,
)
async def confirm_backup_deletion(
    body: DeletionConfirmBody,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> DeletionJobAcceptedResponse:
    """Confirm a backup deletion with the emailed code; delete in the background.

    The code is verified (single-use) up front, then the deletion runs as a
    background task so the request returns immediately — deleting many backups
    can involve many provider round-trips and must not block the HTTP request
    (which can drop over a proxy/tunnel). The UI polls
    ``/backups/delete/jobs/{job_id}`` for the outcome. Deletion uses the same
    reference-counted engine as the retention pruner, so shared blobs are never
    orphaned.
    """
    from app.modules.backup_restore.deletion import (
        ChallengeNotFoundError,
        ChallengeUserMismatchError,
        InvalidCodeError,
        create_delete_job,
        verify_deletion_challenge,
    )

    actor = _actor_id(request)
    if not actor:
        raise HTTPException(
            status_code=401, detail="Could not identify the requesting user."
        )
    actor_uuid = uuid.UUID(actor)

    try:
        ids = await verify_deletion_challenge(
            challenge_id=body.challenge_id, code=body.code, user_id=actor_uuid
        )
    except ChallengeNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc))
    except ChallengeUserMismatchError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except InvalidCodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{exc} {exc.attempts_remaining} attempt(s) remaining.",
        )

    if not ids:
        raise HTTPException(status_code=400, detail="No backups to delete.")

    job_id = await create_delete_job(len(ids))
    background.add_task(
        _run_backup_delete_task,
        job_id,
        [str(i) for i in ids],
        actor,
        request.client.host if request.client else None,
    )
    return DeletionJobAcceptedResponse(
        job_id=job_id, requested=len(ids), status="running"
    )


async def _run_backup_delete_task(
    job_id: str,
    backup_ids: list[str],
    actor: Optional[str],
    ip_address: Optional[str],
) -> None:
    """Background entry: delete the authorised backups and record the outcome."""
    from app.core.audit import write_audit_log
    from app.modules.backup_restore.backup.prune import BlobPruner
    from app.modules.backup_restore.deletion import set_delete_job
    from app.modules.backup_restore.service import _resolve_primary_storage

    try:
        async with async_session_factory() as db:
            async with db.begin():
                primary, storage = await _resolve_primary_storage(db)
                if primary is None or storage is None:
                    raise RuntimeError(
                        "No primary backup destination is configured."
                    )
                pruner = BlobPruner(db, storage)
                outcome = await pruner.delete_specific(
                    [uuid.UUID(i) for i in backup_ids]
                )
                with contextlib.suppress(Exception):
                    await write_audit_log(
                        db,
                        action="backup.deleted",
                        entity_type="backup",
                        user_id=uuid.UUID(actor) if actor else None,
                        after_value={
                            "deleted": [str(i) for i in outcome.pruned_backup_ids],
                            "failed": [str(i) for i in outcome.failed_backup_ids],
                            "blobs_deleted": len(outcome.deleted_blob_hashes),
                        },
                        ip_address=ip_address,
                    )
        await set_delete_job(
            job_id,
            status="completed",
            deleted=len(outcome.pruned_backup_ids),
            failed=len(outcome.failed_backup_ids),
            blobs_deleted=len(outcome.deleted_blob_hashes),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Backup delete job %s failed", job_id, exc_info=True)
        from app.modules.backup_restore.deletion import set_delete_job as _set

        await _set(job_id, status="failed", error=_clean_detail(exc))


@router.get(
    "/backups/delete/jobs/{job_id}", response_model=DeletionJobStatusResponse
)
async def get_backup_delete_job(
    job_id: str, db: AsyncSession = Depends(get_db_session)
) -> DeletionJobStatusResponse:
    """Return the status/outcome of a background backup-deletion job."""
    from app.modules.backup_restore.deletion import get_delete_job

    data = await get_delete_job(job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Deletion job not found")
    return DeletionJobStatusResponse(
        status=data.get("status", "running"),
        requested=int(data.get("requested", 0)),
        deleted=int(data.get("deleted", 0)),
        failed=int(data.get("failed", 0)),
        blobs_deleted=int(data.get("blobs_deleted", 0)),
        error=data.get("error"),
    )


# ===========================================================================
# Restore
# ===========================================================================

# ---------------------------------------------------------------------------
# Upload a portable bundle and run a full destructive restore from it.
# ---------------------------------------------------------------------------
@router.post("/restore/upload", response_model=JobAcceptedResponse, status_code=202)
async def restore_from_upload(
    bundle: UploadFile = File(...),
    recovery_kit: str = Form(...),
    passphrase: str = Form(...),
    confirm_older_schema: bool = Form(False),
    request: Request = None,  # type: ignore[assignment]
    background: BackgroundTasks = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db_session),
) -> JobAcceptedResponse:
    """Upload a portable backup bundle + recovery kit + passphrase and trigger a
    full destructive restore.

    This is the fast‑DR path: spin up a fresh server, log in, upload the
    ``.tar`` bundle you downloaded from the History tab (or kept offline), supply
    the Recovery Kit JSON and passphrase, and restore immediately — no
    destination configuration or key setup required. The bundle contains only
    ciphertext; the BDK is unwrapped from the recovery kit + passphrase at
    restore time.

    The upload is streamed to disk (memory-safe for large bundles), unpacked,
    validated, and then a background task drives the **existing full-restore
    service** against the unpacked artifacts (pg_restore --clean, file restore,
    maintenance mode, HA fence). The UI polls the job for progress.
    """
    import json as _json
    import os
    import shutil
    import tempfile

    from app.modules.backup_restore.portable import BundleError, unpack_bundle

    actor = _actor_id(request)

    # Parse recovery_kit JSON
    try:
        kit = _json.loads(recovery_kit)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="recovery_kit must be valid JSON (the Recovery Kit file contents).",
        )
    if not passphrase or not passphrase.strip():
        raise HTTPException(status_code=400, detail="passphrase is required.")

    # Stream the upload to a temp file (memory-safe for multi-GB bundles).
    work_dir = tempfile.mkdtemp(prefix="ora-upload-")
    tar_path = os.path.join(work_dir, "upload.tar")
    try:
        with open(tar_path, "wb") as fh:
            while chunk := await bundle.read(8 * 1024 * 1024):
                fh.write(chunk)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400, detail=f"upload failed: {exc}"
        )

    # Unpack and validate structure.
    extract_dir = os.path.join(work_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    try:
        meta = unpack_bundle(tar_path, extract_dir)
    except BundleError as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc))

    # Validate the BDK can be unwrapped (fail fast with a clear message rather
    # than starting the restore and failing deep in the pipeline).
    try:
        keys = BackupKeyService(db)
        bdk = await keys.bootstrap(kit, passphrase, version=meta.key_version)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not unlock the backup with the supplied Recovery Kit + "
                f"passphrase: {exc}. Check that you are using the correct kit and "
                f"passphrase for key version {meta.key_version}."
            ),
        )

    # Create the restore job (independent commit so the background task finds it).
    job_id = uuid.uuid4()
    async with async_session_factory() as jdb:
        async with jdb.begin():
            jdb.add(
                RestoreJob(
                    id=job_id,
                    status="queued",
                    mode="full",
                    backup_id=None,  # no catalog row for an uploaded bundle
                    triggered_by="manual",
                )
            )

    background.add_task(
        _run_bundle_restore_task,
        str(job_id),
        extract_dir,
        work_dir,
        bdk.hex(),
        bool(confirm_older_schema),
        actor,
    )
    return JobAcceptedResponse(job_id=job_id, status="queued")


async def _run_bundle_restore_task(
    job_id: str,
    bundle_dir: str,
    work_dir: str,
    bdk_hex: str,
    confirm_older_schema: bool,
    actor: Optional[str],
) -> None:
    """Background: drive a full restore from an uploaded bundle (DR path)."""
    import shutil

    from app.modules.backup_restore.portable import BundleArtifactReader
    from app.modules.backup_restore.restore.full_restore import (
        AsyncpgRestoreValidator,
        CancellationToken,
        FullRestoreService,
        HAMaintenanceController,
        PgDumpSnapshotManager,
        PgRestoreApplier,
    )

    token = CancellationToken()
    _RESTORE_CANCEL_TOKENS[job_id] = token
    try:
        bdk = bytes.fromhex(bdk_hex)
        reader = BundleArtifactReader(bundle_dir, bdk)
        async with async_session_factory() as db:
            async with db.begin():
                job_row = (
                    await db.execute(
                        select(RestoreJob).where(RestoreJob.id == uuid.UUID(job_id))
                    )
                ).scalars().first()
                if job_row is None:
                    return
                fencer = await _build_standby_fencer(db)
                dsn = settings.database_url
                service = FullRestoreService(
                    db,
                    reader=reader,
                    target_version_reader=AlembicTargetVersionReader(db),
                    maintenance=HAMaintenanceController(db, actor),
                    fencer=fencer,
                    snapshot=PgDumpSnapshotManager(dsn),
                    applier=PgRestoreApplier(dsn),
                    validator=AsyncpgRestoreValidator(dsn),
                )
                await service.run(
                    job_row,
                    confirm_older_schema=confirm_older_schema,
                    cancel_token=token,
                )
    except Exception:  # noqa: BLE001 - FullRestoreService records failure itself
        logger.exception(
            "Background bundle-restore task failed for job %s", job_id
        )
    finally:
        _RESTORE_CANCEL_TOKENS.pop(job_id, None)
        # Clean up the uploaded/unpacked bundle from disk.
        shutil.rmtree(work_dir, ignore_errors=True)


@router.post("/restore/dry-run", response_model=DryRunResponse)
async def restore_dry_run(
    body: DryRunRequest, db: AsyncSession = Depends(get_db_session)
) -> DryRunResponse:
    """Validation-only dry-run: checksum + schema-compat (no writes, Req 11.1).

    Returns the ``older_schema`` flag + both migration versions so the wizard can
    present the older-schema confirmation gate before submitting a full restore
    (Req 10.6).
    """
    backup = await _load_backup(db, body.backup_id)
    try:
        reader = await _build_artifact_reader(
            db, backup, recovery_kit=body.recovery_kit, passphrase=body.passphrase
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - clean detail, no stack trace
        raise HTTPException(status_code=422, detail=_clean_detail(exc))

    service = DryRunService(reader, AlembicTargetVersionReader(db))
    restore_job = RestoreJob(
        status="queued", mode="dry_run", backup_id=backup.id, triggered_by="manual"
    )
    db.add(restore_job)
    await db.flush()
    result = await service.run(restore_job)
    await db.flush()
    return DryRunResponse(
        overall=result.overall,
        checksum_ok=result.checksum_ok,
        older_schema=result.older_schema,
        backup_version=result.backup_version,
        target_version=result.target_version,
        schema_outcome=result.schema.outcome if result.schema else None,
        schema_decision=result.schema.decision if result.schema else None,
        elapsed_seconds=result.elapsed_seconds,
        steps=[
            DryRunStepResponse(name=s.name, outcome=s.outcome, detail=s.detail)
            for s in result.steps
        ],
    )


@router.post("/restore/full", response_model=JobAcceptedResponse, status_code=202)
async def restore_full(
    body: FullRestoreRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> JobAcceptedResponse:
    """Launch a full-platform restore as a background task (Req 12.1)."""
    actor = _actor_id(request)
    backup = await _load_backup(db, body.backup_id)
    # Create + COMMIT the job row in its own transaction BEFORE scheduling the
    # background task. The request's get_db_session only commits on yield
    # teardown, which (FastAPI >= 0.106) runs AFTER background tasks — so creating
    # the job on `db` lets the task query it before it is committed, find nothing,
    # and silently exit, leaving the restore stuck 'queued'.
    job_id = uuid.uuid4()
    async with async_session_factory() as jdb:
        async with jdb.begin():
            jdb.add(
                RestoreJob(
                    id=job_id,
                    status="queued",
                    mode="full",
                    backup_id=backup.id,
                    triggered_by="manual",
                )
            )
    background.add_task(
        _run_full_restore_task,
        str(job_id),
        str(body.backup_id),
        bool(body.confirm_older_schema),
        actor,
        body.recovery_kit,
        body.passphrase,
    )
    return JobAcceptedResponse(job_id=job_id, status="queued")


async def _run_full_restore_task(
    job_id: str,
    backup_id: str,
    confirm_older_schema: bool,
    actor: Optional[str],
    recovery_kit: Optional[dict[str, Any]],
    passphrase: Optional[str],
) -> None:
    """Background entry: drive the canonical full-restore sequence (Req 12)."""
    from app.modules.backup_restore.restore.full_restore import (
        AsyncpgRestoreValidator,
        FullRestoreService,
        HAMaintenanceController,
        PgDumpSnapshotManager,
        PgRestoreApplier,
    )

    token = CancellationToken()
    _RESTORE_CANCEL_TOKENS[job_id] = token
    try:
        async with async_session_factory() as db:
            async with db.begin():
                backup = await _load_backup(db, uuid.UUID(backup_id))
                job_row = (
                    await db.execute(
                        select(RestoreJob).where(RestoreJob.id == uuid.UUID(job_id))
                    )
                ).scalars().first()
                if job_row is None:
                    return
                reader = await _build_artifact_reader(
                    db, backup, recovery_kit=recovery_kit, passphrase=passphrase
                )
                fencer = await _build_standby_fencer(db)
                dsn = settings.database_url
                service = FullRestoreService(
                    db,
                    reader=reader,
                    target_version_reader=AlembicTargetVersionReader(db),
                    maintenance=HAMaintenanceController(db, actor),
                    fencer=fencer,
                    snapshot=PgDumpSnapshotManager(dsn),
                    applier=PgRestoreApplier(dsn),
                    validator=AsyncpgRestoreValidator(dsn),
                )
                await service.run(
                    job_row,
                    confirm_older_schema=confirm_older_schema,
                    cancel_token=token,
                )
    except CancelNotAllowedError:
        logger.info("Full restore %s cancel refused (apply already started)", job_id)
    except Exception:  # noqa: BLE001 - the service records the job failure itself
        logger.exception("Background full-restore task failed for job %s", job_id)
    finally:
        _RESTORE_CANCEL_TOKENS.pop(job_id, None)


async def _build_standby_fencer(db: AsyncSession):
    """Build a standby fencer from HA config, or a no-op fencer when there is no
    standby to fence (single-node deployment)."""
    from app.modules.backup_restore.restore.full_restore import (
        ReplicationStandbyFencer,
        StandbyFencer,
    )
    from app.modules.ha.service import get_peer_db_url

    try:
        peer_url = await get_peer_db_url(db)
    except Exception:  # noqa: BLE001 - HA config is optional
        peer_url = None

    if not peer_url:
        class _NoStandbyFencer(StandbyFencer):
            async def fence(self) -> None:
                return None

            async def reseed(self) -> None:
                return None

            async def restore_ha(self) -> None:
                return None

        return _NoStandbyFencer()

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(peer_url)
    standby_session = async_sessionmaker(engine, expire_on_commit=False)()
    return ReplicationStandbyFencer(standby_session, settings.database_url)


@router.post("/restore/per-org", response_model=JobAcceptedResponse, status_code=202)
async def restore_per_org(
    body: PerOrgRestoreRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
) -> JobAcceptedResponse:
    """Launch a per-organisation restore as a background task (Req 14)."""
    actor = _actor_id(request)
    backup = await _load_backup(db, body.backup_id)
    # Gate the restore-as-new (clone) policy: it inserts fresh copies of the
    # backup's rows under the SAME organisation, so it only makes sense for an
    # empty organisation. Restoring it into one that already has data would
    # collide on unique keys (e.g. login email) and roll back. Reject early with
    # clear guidance instead of letting it fail mid-apply.
    from app.modules.backup_restore.restore.per_org_restore import ConflictPolicy

    try:
        policy = ConflictPolicy.from_value(body.conflict_policy)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown conflict policy {body.conflict_policy!r}.",
        )
    if policy is ConflictPolicy.RESTORE_AS_NEW and await _org_has_data(db, body.org_id):
        raise HTTPException(
            status_code=409,
            detail=(
                "“Insert as new copies” only works on an empty organisation, but "
                "this organisation already contains data. To recover deleted or "
                "changed records, use the Overwrite policy (it restores over "
                "existing data and re-creates anything that was deleted)."
            ),
        )
    # Create + COMMIT the job row in its own transaction BEFORE scheduling the
    # background task (see restore_full / run_backup_now — FastAPI >= 0.106 runs
    # background tasks before the request session commits, so the task would
    # otherwise find no job and the restore would stay stuck 'queued').
    job_id = uuid.uuid4()
    async with async_session_factory() as jdb:
        async with jdb.begin():
            jdb.add(
                RestoreJob(
                    id=job_id,
                    status="queued",
                    mode="per_org",
                    backup_id=backup.id,
                    target_org_id=body.org_id,
                    conflict_policy=body.conflict_policy,
                    triggered_by="manual",
                )
            )
    background.add_task(
        _run_per_org_restore_task,
        str(job_id),
        str(body.backup_id),
        str(body.org_id),
        body.conflict_policy,
        body.selected_tables,
        bool(body.restore_files),
        body.recovery_kit,
        body.passphrase,
    )
    return JobAcceptedResponse(job_id=job_id, status="queued")


async def _commit_restore_job_state(job_id: str, **fields: Any) -> None:
    """Persist Restore_Job fields in an INDEPENDENT, immediately-committed
    transaction so concurrent status polls see progress live (Req 13.2/13.3).

    Mirrors the backup pipeline's live-progress pattern: writing through a short
    separate session (not the apply's session) avoids holding a row lock for the
    whole restore and makes each update visible to the status endpoint at once.
    """
    try:
        async with async_session_factory() as s:
            async with s.begin():
                row = (
                    await s.execute(
                        select(RestoreJob).where(RestoreJob.id == uuid.UUID(job_id))
                    )
                ).scalars().first()
                if row is None:
                    return
                for key, value in fields.items():
                    setattr(row, key, value)
    except Exception:  # noqa: BLE001 - progress persistence is best-effort
        logger.debug("could not persist per-org restore progress", exc_info=True)


async def _run_per_org_restore_task(
    job_id: str,
    backup_id: str,
    org_id: str,
    conflict_policy: str,
    selected_tables: Optional[list[str]],
    restore_files: bool,
    recovery_kit: Optional[dict[str, Any]],
    passphrase: Optional[str],
) -> None:
    """Background entry: run the per-org restore with live progress + cancel."""
    from app.modules.backup_restore.restore.full_restore import CancellationToken
    from app.modules.backup_restore.restore.per_org_restore import (
        FilesystemFileRestoreSink,
        PerOrgRestoreService,
        RestoreCancelledError,
        SchemaModel,
        ScratchDbDumpExtractor,
        SqlAlchemyRestoreTarget,
    )

    # Register an in-memory cancel signal the cancel endpoint can trip while the
    # restore is running; the apply polls it and rolls back atomically.
    token = CancellationToken()
    _RESTORE_CANCEL_TOKENS[job_id] = token

    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def _on_progress(pct: int, message: str) -> None:
        await _commit_restore_job_state(
            job_id,
            status="running",
            progress_pct=max(0, min(100, pct)),
            last_progress_at=_now(),
            last_heartbeat_at=_now(),
            outcome_summary=message,
        )

    async def _heartbeat_loop() -> None:
        # Keep the job alive during long monotonic phases (extraction of a large
        # dump, file restore) that emit no percentage progress, so the status
        # endpoint's stall-timeout (Req 13.5) does not force-fail healthy work.
        try:
            while True:
                await asyncio.sleep(10)
                await _commit_restore_job_state(job_id, last_heartbeat_at=_now())
        except asyncio.CancelledError:
            pass

    heartbeat = asyncio.create_task(_heartbeat_loop())
    try:
        # If a cancel arrived while the job was still queued, never start it.
        async with async_session_factory() as s0:
            current = (
                await s0.execute(
                    select(RestoreJob.status).where(RestoreJob.id == uuid.UUID(job_id))
                )
            ).scalar()
        if current in ("cancelled", "failed", "completed"):
            return

        # Mark running immediately (independent commit) so a poller sees the job
        # leave 'queued' and start advancing right away.
        await _commit_restore_job_state(
            job_id,
            status="running",
            started_at=_now(),
            progress_pct=0,
            last_progress_at=_now(),
            last_heartbeat_at=_now(),
            outcome_summary="Starting per-organisation restore…",
        )

        async with async_session_factory() as db:
            async with db.begin():
                backup = await _load_backup(db, uuid.UUID(backup_id))
                reader = await _build_artifact_reader(
                    db, backup, recovery_kit=recovery_kit, passphrase=passphrase
                )
                schema = SchemaModel()
                target = SqlAlchemyRestoreTarget(db, schema)
                extractor = ScratchDbDumpExtractor(settings.database_url)
                sink = FilesystemFileRestoreSink()
                service = PerOrgRestoreService(
                    reader, target, extractor, sink, schema=schema
                )
                result = await service.restore(
                    org_id,
                    conflict_policy,
                    selected_tables=selected_tables,
                    restore_files=restore_files,
                    on_progress=_on_progress,
                    should_cancel=lambda: token.is_requested,
                )

        heartbeat.cancel()
        # Apply transaction committed — record terminal success.
        await _commit_restore_job_state(
            job_id,
            status="completed",
            finished_at=_now(),
            progress_pct=100,
            outcome_summary=(
                f"Per-org restore for {org_id} "
                f"({'succeeded' if result.succeeded else 'completed with file warnings'})"
            ),
        )
    except RestoreCancelledError:
        heartbeat.cancel()
        # Cooperative cancel: the apply rolled back, so nothing was applied.
        logger.info("Per-org restore job %s cancelled", job_id)
        await _commit_restore_job_state(
            job_id,
            status="cancelled",
            finished_at=_now(),
            outcome_summary="Per-org restore cancelled; no data was changed.",
        )
    except Exception as exc:  # noqa: BLE001
        heartbeat.cancel()
        # The apply transaction is rolled back here; record the terminal failure
        # in a fresh, committed transaction so the job reflects 'failed' instead
        # of staying stuck 'queued'/'running'.
        logger.warning("Per-org restore job %s failed", job_id, exc_info=True)
        await _run_per_org_restore_failed(job_id, exc)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        _RESTORE_CANCEL_TOKENS.pop(job_id, None)


async def _run_per_org_restore_failed(job_id: str, exc: Exception) -> None:
    """Record a per-org restore terminal failure in a fresh, committed transaction."""
    try:
        async with async_session_factory() as db2:
            async with db2.begin():
                row = (
                    await db2.execute(
                        select(RestoreJob).where(RestoreJob.id == uuid.UUID(job_id))
                    )
                ).scalars().first()
                if row is not None and row.status not in (
                    "completed",
                    "failed",
                    "cancelled",
                ):
                    row.status = "failed"
                    row.finished_at = datetime.now(timezone.utc)
                    row.outcome_summary = "Per-org restore failed"
                    row.error_message = _clean_detail(exc)[:1000]
    except Exception:  # noqa: BLE001 - best effort
        logger.exception(
            "Could not record terminal failure for per-org restore job %s", job_id
        )


@router.get("/restore/browse", response_model=ListResponse[BrowseOrgResponse])
async def browse_backup(
    backup_id: uuid.UUID = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> ListResponse[BrowseOrgResponse]:
    """Browse a backup's per-organisation contents from its manifest (Req 15.1)."""
    backup = await _load_backup(db, backup_id)
    try:
        reader = await _build_artifact_reader(db, backup)
        manifest = await reader.read_manifest()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    entries = manifest.envelope.per_org_index.entries
    total = len(entries)
    page = entries[offset : offset + limit]
    # Resolve current org display names for the page's org_ids so the wizard can
    # show names instead of raw UUIDs. Names are looked up live (not stored in the
    # manifest, which deliberately carries no customer-identifying catalog data).
    name_by_id: dict[str, str] = {}
    page_ids = [entry.org_id for entry in page]
    if page_ids:
        try:
            name_rows = await db.execute(
                text("SELECT id, name FROM organisations WHERE id = ANY(:ids)"),
                {"ids": page_ids},
            )
            name_by_id = {str(rid): name for rid, name in name_rows.fetchall()}
        except Exception:  # noqa: BLE001 - names are best-effort display sugar
            name_by_id = {}
    items = [
        BrowseOrgResponse(
            org_id=entry.org_id,
            org_name=name_by_id.get(str(entry.org_id)),
            entities=[
                BrowseEntityResponse(
                    entity_type=e.entity_type, record_count=e.record_count
                )
                for e in entry.entities
            ],
            logical_export_emitted=entry.logical_export_emitted,
        )
        for entry in page
    ]
    return ListResponse[BrowseOrgResponse](items=items, total=total)


@router.get("/restore/jobs/{job_id}", response_model=JobStatusResponse)
async def get_restore_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> JobStatusResponse:
    """Return a restore job's live status (Req 13.3).

    Lets the restore wizard poll a launched dry-run / full / per-org restore for
    progress and the terminal outcome (``completed`` with ``outcome_summary`` or
    ``failed`` with ``error_message``) instead of leaving the operator blind once
    the background task starts.
    """
    jobs = JobService(db)
    try:
        job = await jobs.get_job(job_id, RestoreJob)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Restore job not found")
    await jobs.enforce_progress_timeout(job)  # force-fail a stalled job (Req 13.5)
    return _job_status_response(jobs.status_of(job), job)


@router.post("/restore/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_restore_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db_session)
) -> JobStatusResponse:
    """Cancel a restore job.

    For a full restore the cancel is honoured only during the pre-apply phases;
    once the destructive apply has begun it is refused with HTTP 409 (Req 12.16,
    12.17). For dry-run / per-org jobs a queued or running job is cancelled
    best-effort.
    """
    jobs = JobService(db)
    try:
        job = await jobs.get_job(job_id, RestoreJob)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Restore job not found")
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Job already {job.status}")

    if job.mode == "full":
        # Transactionally re-read the apply boundary (Req 12.17).
        await db.refresh(job, attribute_names=["destructive_apply_started"])
        if job.destructive_apply_started:
            raise HTTPException(
                status_code=409,
                detail="The restore has begun its destructive apply and can no "
                "longer be safely cancelled.",
            )
        token = _RESTORE_CANCEL_TOKENS.get(str(job_id))
        if token is not None:
            token.request()  # the run loop stops at its next pre-apply checkpoint
        elif job.status == "queued":
            job = await jobs.cancel(job)
    else:
        # per-org / dry-run. A running job is cancelled cooperatively: trip the
        # in-memory token so the apply rolls back atomically and the task records
        # 'cancelled' itself. A still-queued job is cancelled directly so it
        # never starts.
        token = _RESTORE_CANCEL_TOKENS.get(str(job_id))
        if token is not None:
            token.request()
            if job.status == "queued":
                job = await jobs.cancel(job)
        else:
            job = await jobs.cancel(job)
    return _job_status_response(jobs.status_of(job))


# ===========================================================================
# Keys
# ===========================================================================
@router.get("/keys/status", response_model=KeyStatusResponse)
async def key_status(db: AsyncSession = Depends(get_db_session)) -> KeyStatusResponse:
    """Report this deployment's backup-key state (Req 16.12)."""
    status_dict = await BackupKeyService(db).get_key_status()
    return KeyStatusResponse(**status_dict)


@router.post("/keys/setup", response_model=KeySetupResponse, status_code=201)
async def key_setup(
    body: KeySetupRequest, db: AsyncSession = Depends(get_db_session)
) -> KeySetupResponse:
    """First-run key setup; returns the one-time Recovery Kit (Req 16.3/16.4)."""
    try:
        kit = await BackupKeyService(db).setup(body.passphrase)
    except PassphraseStrengthError as exc:
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    except KeySetupError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    return KeySetupResponse(recovery_kit=kit)


@router.post("/keys/rotate", response_model=KeyRotateResponse)
async def key_rotate(db: AsyncSession = Depends(get_db_session)) -> KeyRotateResponse:
    """Rotate the Backup_Data_Key, retaining prior versions (Req 16.10)."""
    try:
        new_version = await BackupKeyService(db).rotate()
    except KeySetupError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    except KeyMaterialMismatchError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    return KeyRotateResponse(active_version=new_version)


@router.get("/keys/recovery-kit", response_model=RecoveryKitResponse)
async def export_recovery_kit(
    db: AsyncSession = Depends(get_db_session),
) -> RecoveryKitResponse:
    """Re-export the Recovery Kit from retained wrapped material (Req 16.4)."""
    try:
        kit = await BackupKeyService(db).export_recovery_kit()
    except KeySetupError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    return RecoveryKitResponse(recovery_kit=kit)


@router.post("/keys/recovery-kit", response_model=RecoveryKitResponse)
async def export_recovery_kit_post(
    db: AsyncSession = Depends(get_db_session),
) -> RecoveryKitResponse:
    """Re-export the Recovery Kit (POST form, e.g. after a re-auth, Req 16.4)."""
    try:
        kit = await BackupKeyService(db).export_recovery_kit()
    except KeySetupError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    return RecoveryKitResponse(recovery_kit=kit)


@router.post("/keys/bootstrap", response_model=KeyBootstrapResponse)
async def key_bootstrap(
    body: KeyBootstrapRequest, db: AsyncSession = Depends(get_db_session)
) -> KeyBootstrapResponse:
    """Bootstrap key material on a fresh deployment from a Recovery Kit (Req 16.7)."""
    keys = BackupKeyService(db)
    try:
        await keys.bootstrap(body.recovery_kit, body.passphrase, body.version)
    except KeyMaterialMissingError as exc:
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    except (KeyMaterialMismatchError, KeyVersionUnavailableError) as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    except KeyBootstrapError as exc:
        raise HTTPException(status_code=409, detail=_clean_detail(exc))
    status_dict = await keys.get_key_status()
    return KeyBootstrapResponse(**status_dict)


# ===========================================================================
# Config
# ===========================================================================
@router.get("/config", response_model=ConfigResponse)
async def get_config(db: AsyncSession = Depends(get_db_session)) -> ConfigResponse:
    """Return the single-row backup configuration (Req 8)."""
    config = await BackupConfigService(db).get_config()
    return ConfigResponse.model_validate(config)


@router.put("/config", response_model=ConfigUpdateResponse)
async def update_config(
    body: ConfigUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ConfigUpdateResponse:
    """Update the backup configuration; surfaces non-blocking RPO warnings (Req 25.2)."""
    updates = body.model_dump(exclude_unset=True)
    cfg_service = BackupConfigService(db)
    try:
        result = await cfg_service.update_config(updates, actor_id=_actor_id(request))
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=_clean_detail(exc))
    return ConfigUpdateResponse(
        config=ConfigResponse.model_validate(result.config), warnings=result.warnings
    )


@router.post("/config/notifications/test", response_model=NotificationTestResponse)
async def test_notifications(
    db: AsyncSession = Depends(get_db_session),
) -> NotificationTestResponse:
    """Dispatch a test notification on each enabled channel (Req 18.12).

    Touches no backup/restore/config/job state.
    """
    results = await BackupService(db).send_test_notification()
    return NotificationTestResponse(
        results=[ChannelResultResponse(**r) for r in results]
    )


# ===========================================================================
# Rehearsals
# ===========================================================================
@router.get("/rehearsals", response_model=ListResponse[RehearsalResponse])
async def list_rehearsals(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db_session),
) -> ListResponse[RehearsalResponse]:
    """Restore-rehearsal history ``{items,total}`` (Req 26.1)."""
    total = (
        await db.execute(select(func.count()).select_from(RestoreRehearsal))
    ).scalar_one()
    result = await db.execute(
        select(RestoreRehearsal)
        .order_by(RestoreRehearsal.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.scalars().all()
    items = [RehearsalResponse.model_validate(r) for r in rows]
    return ListResponse[RehearsalResponse](items=items, total=total)


@router.post("/rehearsals", response_model=RehearsalResponse, status_code=202)
async def run_rehearsal_now(background: BackgroundTasks) -> RehearsalResponse:
    """Run a restore rehearsal now as a background task (Req 26.1).

    Returns a 202 placeholder immediately; the rehearsal runs in the background
    and its full record appears in the history list when complete.
    """
    background.add_task(_run_rehearsal_task)
    return RehearsalResponse(
        id=uuid.uuid4(),
        backup_id=None,
        result=None,
        measured_duration_seconds=None,
        scratch_env_id=None,
        teardown_status=None,
        created_at=datetime.now(timezone.utc),
    )


async def _run_rehearsal_task() -> None:
    """Background entry: run a restore rehearsal into an isolated scratch env."""
    from app.modules.backup_restore.restore.rehearsal import (
        PgScratchEnvironmentProvider,
        RehearsalService,
    )

    try:
        async with async_session_factory() as db:
            async with db.begin():

                async def reader_factory(backup: Backup):
                    return await _build_artifact_reader(db, backup)

                service = RehearsalService(
                    db,
                    scratch_provider=PgScratchEnvironmentProvider(settings.database_url),
                    reader_factory=reader_factory,
                )
                await service.run_rehearsal()
    except Exception:  # noqa: BLE001 - the service records the rehearsal row
        logger.exception("Background rehearsal task failed")
