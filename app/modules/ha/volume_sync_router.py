"""API endpoints for rsync-based volume replication configuration and control.

All endpoints live under ``/volume-sync`` and inherit the ``global_admin``
role requirement from the parent HA admin router.

**Validates: Requirements 4.3, 4.4, 4.5, 5.6, 6.1, 6.2, 6.5**
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.ha.volume_sync_schemas import (
    VolumeSyncConfigRequest,
    VolumeSyncConfigResponse,
    VolumeSyncHistoryEntry,
    VolumeSyncStatusResponse,
    VolumeSyncTriggerResponse,
)
from app.modules.ha.volume_sync_service import VolumeSyncService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/volume-sync", tags=["HA Volume Sync"])


@router.get(
    "/config",
    response_model=VolumeSyncConfigResponse,
    summary="Get current rsync configuration",
    responses={
        404: {"description": "Volume sync not configured"},
    },
)
async def get_volume_sync_config(
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current rsync configuration, or 404 if not configured."""
    svc = VolumeSyncService()
    cfg = await svc.get_config(db)
    if cfg is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Volume sync not configured"},
        )
    return cfg


@router.put(
    "/config",
    response_model=VolumeSyncConfigResponse,
    summary="Create or update rsync configuration",
    responses={
        422: {"description": "Validation error"},
    },
)
async def update_volume_sync_config(
    payload: VolumeSyncConfigRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Upsert the rsync configuration.

    When ``enabled`` changes to True, starts the periodic background sync task.
    When ``enabled`` changes to False, stops it.

    Returns 422 if validation fails (empty SSH host, interval out of range).
    """
    svc = VolumeSyncService()
    try:
        # Check previous enabled state before saving
        old_cfg = await svc.get_config(db)
        was_enabled = old_cfg.enabled if old_cfg else False

        cfg = await svc.save_config(db, payload)

        # Start or stop the periodic sync task based on enabled state change
        if payload.enabled and not was_enabled:
            logger.info("Volume sync enabled — starting periodic sync task")
            await svc.start_periodic_sync(db)
        elif not payload.enabled and was_enabled:
            logger.info("Volume sync disabled — stopping periodic sync task")
            await svc.stop_periodic_sync()

        return cfg
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc)},
        )


@router.get(
    "/status",
    response_model=VolumeSyncStatusResponse,
    summary="Get current sync status",
)
async def get_volume_sync_status(
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current sync status including directory scan results."""
    svc = VolumeSyncService()
    return await svc.get_status(db)


@router.post(
    "/trigger",
    response_model=VolumeSyncTriggerResponse,
    summary="Trigger manual sync",
    responses={
        404: {"description": "Volume sync not configured"},
        409: {"description": "Sync already in progress"},
    },
)
async def trigger_volume_sync(
    db: AsyncSession = Depends(get_db_session),
):
    """Trigger an immediate manual sync.

    Returns 409 if a sync is already running.
    Returns 404 if volume sync is not configured.
    """
    svc = VolumeSyncService()
    # The service raises HTTPException(409) if already running
    # and HTTPException(404) if not configured
    history = await svc.trigger_sync(db)
    return VolumeSyncTriggerResponse(
        message="Sync triggered successfully",
        sync_id=str(history.id),
    )


@router.get(
    "/history",
    response_model=list[VolumeSyncHistoryEntry],
    summary="Get recent sync history",
)
async def get_volume_sync_history(
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Return recent sync history entries ordered by started_at descending."""
    svc = VolumeSyncService()
    return await svc.get_history(db, limit=limit)
