"""Global Admin migration router — database migration tool endpoints.

All endpoints require the ``global_admin`` role.

**Validates: Requirement 7, Requirement 41**
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.admin.migration_schemas import (
    MigrationCreateRequest,
    MigrationExecuteRequest,
    MigrationJobResponse,
    MigrationRollbackRequest,
)
from app.modules.admin.migration_service import DataMigrationService
from app.modules.auth.rbac import require_role

router = APIRouter(dependencies=[Depends(require_role("global_admin"))])


def _get_service(db: AsyncSession = Depends(get_db_session)) -> DataMigrationService:
    return DataMigrationService(db=db)


@router.post(
    "",
    response_model=MigrationJobResponse,
    status_code=201,
    summary="Create a migration job",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
)
async def create_migration(
    payload: MigrationCreateRequest,
    request: Request,
    service: DataMigrationService = Depends(_get_service),
):
    """Create a new migration job for an organisation.

    The job is created in 'pending' status. Call POST /execute to start it.
    Requirement 7.1, 7.2.
    """
    user_id = getattr(request.state, "user_id", None)

    try:
        org_uuid = uuid.UUID(payload.org_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    try:
        result = await service.create_migration_job(
            org_id=org_uuid,
            mode=payload.mode,
            source_format=payload.source_format,
            source_data=payload.source_data,
            description=payload.description,
            created_by=uuid.UUID(user_id) if user_id else None,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return MigrationJobResponse(**result)


@router.post(
    "/execute",
    response_model=MigrationJobResponse,
    summary="Execute a migration job",
    responses={
        400: {"description": "Validation error or job not in valid state"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def execute_migration(
    payload: MigrationExecuteRequest,
    service: DataMigrationService = Depends(_get_service),
):
    """Execute a pending migration job.

    For 'full' mode, imports all data synchronously.
    For 'live' mode, starts dual-write period.
    Requirement 7.3, 7.4.
    """
    try:
        job_uuid = uuid.UUID(payload.job_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid job_id format"})

    try:
        # Validate source data first
        validation = await service.validate_source_data(job_uuid)
        if not validation["valid"]:
            return JSONResponse(
                status_code=400,
                content={"detail": "Validation failed", "errors": validation["errors"]},
            )

        # Get job to determine mode
        job = await service.get_job_status(job_uuid)
        if job is None:
            return JSONResponse(status_code=404, content={"detail": "Migration job not found"})

        if job["mode"] == "full":
            await service.execute_full_migration(job_uuid)
        else:
            await service.execute_live_migration(job_uuid)

        # Run integrity checks
        await service.run_integrity_checks(job_uuid)

        # Return updated status
        updated = await service.get_job_status(job_uuid)
        return MigrationJobResponse(**updated)

    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Migration failed: {exc}"})


@router.get(
    "/status",
    response_model=MigrationJobResponse,
    summary="Get migration job status",
    responses={
        400: {"description": "Invalid job_id"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def get_migration_status(
    job_id: str,
    service: DataMigrationService = Depends(_get_service),
):
    """Get the current status and progress of a migration job.

    Requirement 7.5, 7.7.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid job_id format"})

    result = await service.get_job_status(job_uuid)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Migration job not found"})

    return MigrationJobResponse(**result)


@router.post(
    "/rollback",
    summary="Rollback a migration",
    responses={
        400: {"description": "Validation error or already rolled back"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Migration job not found"},
    },
)
async def rollback_migration(
    payload: MigrationRollbackRequest,
    service: DataMigrationService = Depends(_get_service),
):
    """Rollback a migration, removing all migrated records.

    Pre-existing records are not affected.
    Requirement 7.6.
    """
    try:
        job_uuid = uuid.UUID(payload.job_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid job_id format"})

    try:
        result = await service.rollback_migration(job_uuid, reason=payload.reason)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return result
