"""Live Database Migration router — zero-downtime database migration endpoints.

All endpoints require the ``global_admin`` role.

**Validates: Requirements 1.1, 1.2, 2.3, 3.1, 5.5, 8.1, 9.1, 10.4, 12.1**
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.modules.admin.live_migration_schemas import (
    ConnectionValidateRequest,
    ConnectionValidateResponse,
    CutoverRequest,
    MigrationJobDetail,
    MigrationJobSummary,
    MigrationStartRequest,
    MigrationStatusResponse,
    RollbackRequest,
)
from app.modules.admin.live_migration_service import LiveMigrationService
from app.modules.auth.rbac import require_role

router = APIRouter(dependencies=[require_role("global_admin")])


def _get_service(
    db: AsyncSession = Depends(get_db_session),
    redis: aioredis.Redis = Depends(get_redis),
) -> LiveMigrationService:
    return LiveMigrationService(db=db, redis=redis)


@router.post(
    "/validate",
    response_model=ConnectionValidateResponse,
    summary="Validate target database connection",
    responses={
        400: {"description": "Invalid connection string or unreachable target"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def validate_connection(
    payload: ConnectionValidateRequest,
    service: LiveMigrationService = Depends(_get_service),
):
    """Validate format, connectivity, PG version, privileges, and emptiness."""
    try:
        result = await service.validate_connection(
            conn_str=payload.connection_string,
            ssl_mode=payload.ssl_mode,
        )
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Validation failed: {exc}"})


@router.post(
    "/start",
    summary="Start a live database migration",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        409: {"description": "Migration already in progress"},
    },
)
async def start_migration(
    payload: MigrationStartRequest,
    request: Request,
    service: LiveMigrationService = Depends(_get_service),
):
    """Start the migration pipeline as a background task."""
    user_id = uuid.UUID(request.state.user_id)
    try:
        job_id = await service.start_migration(
            conn_str=payload.connection_string,
            ssl_mode=payload.ssl_mode,
            batch_size=payload.batch_size,
            user_id=user_id,
        )
        return {"job_id": job_id}
    except ValueError as exc:
        msg = str(exc)
        if "already in progress" in msg.lower():
            return JSONResponse(status_code=409, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Failed to start migration: {exc}"})


@router.get(
    "/status/{job_id}",
    response_model=MigrationStatusResponse,
    summary="Get migration job status",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def get_status(
    job_id: str,
    service: LiveMigrationService = Depends(_get_service),
):
    """Poll current migration progress."""
    try:
        return await service.get_status(job_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Failed to get status: {exc}"})


@router.post(
    "/cutover/{job_id}",
    summary="Confirm cutover to target database",
    responses={
        400: {"description": "Invalid confirmation or job not ready"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def cutover(
    job_id: str,
    payload: CutoverRequest,
    request: Request,
    service: LiveMigrationService = Depends(_get_service),
):
    """Confirm cutover — requires confirmation_text == 'CONFIRM CUTOVER'."""
    user_id = uuid.UUID(request.state.user_id)
    try:
        await service.cutover(job_id=job_id, user_id=user_id)
        return {"detail": "Cutover completed successfully"}
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Cutover failed: {exc}"})


@router.post(
    "/rollback/{job_id}",
    summary="Rollback to source database",
    responses={
        400: {"description": "Rollback window expired or invalid state"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def rollback(
    job_id: str,
    payload: RollbackRequest,
    request: Request,
    service: LiveMigrationService = Depends(_get_service),
):
    """Rollback to the source database within the 24-hour window."""
    user_id = uuid.UUID(request.state.user_id)
    try:
        await service.rollback(job_id=job_id, user_id=user_id, reason=payload.reason)
        return {"detail": "Rollback completed successfully"}
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Rollback failed: {exc}"})


@router.post(
    "/cancel/{job_id}",
    summary="Cancel an in-progress migration",
    responses={
        400: {"description": "Migration not in a cancellable state"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def cancel_migration(
    job_id: str,
    request: Request,
    service: LiveMigrationService = Depends(_get_service),
):
    """Cancel a migration that is currently in progress."""
    user_id = uuid.UUID(request.state.user_id)
    try:
        await service.cancel_migration(job_id=job_id, user_id=user_id)
        return {"detail": "Migration cancelled successfully"}
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Cancellation failed: {exc}"})


@router.get(
    "/history",
    response_model=list[MigrationJobSummary],
    summary="List past migration jobs",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def get_history(
    service: LiveMigrationService = Depends(_get_service),
):
    """Return a list of all past migration jobs."""
    try:
        return await service.get_history()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Failed to get history: {exc}"})


@router.get(
    "/history/{job_id}",
    response_model=MigrationJobDetail,
    summary="Get full details of a past migration job",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def get_job_detail(
    job_id: str,
    service: LiveMigrationService = Depends(_get_service),
):
    """Return full details for a specific migration job."""
    try:
        return await service.get_job_detail(job_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Failed to get job detail: {exc}"})
