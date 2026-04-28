"""Job Card Attachment router — file upload and management endpoints.

Provides endpoints for uploading, listing, downloading, and deleting
file attachments on job cards.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.job_cards.attachment_service import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
    delete_attachment,
    download_attachment,
    get_attachment,
    list_attachments,
    upload_attachment,
)
from app.modules.job_cards.models import JobCard

router = APIRouter()

# Statuses that lock the job card from modifications
_LOCKED_STATUSES = {"completed", "invoiced"}


async def _check_job_card_not_locked(
    db: AsyncSession, org_id: uuid.UUID, job_card_id: uuid.UUID
) -> None:
    """Raise 403 if the job card is completed or invoiced."""
    from sqlalchemy import select

    result = await db.execute(
        select(JobCard.status).where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    status = result.scalar_one_or_none()
    if status is None:
        raise HTTPException(status_code=404, detail="Job card not found")
    if status in _LOCKED_STATUSES:
        raise HTTPException(
            status_code=403,
            detail=f"Job card is {status} and cannot be modified",
        )


def _extract_org_context(request: Request) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Extract org_id and user_id from request state."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None
    return org_uuid, user_uuid


@router.post(
    "/{job_card_id}/attachments",
    status_code=201,
    responses={
        201: {"description": "Attachment uploaded successfully"},
        400: {"description": "Invalid file type or empty file"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
        413: {"description": "File too large"},
        507: {"description": "Storage quota exceeded"},
    },
    summary="Upload a file attachment to a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def upload_attachment_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload a file attachment to a job card.

    Accepts images (JPEG, PNG, WebP, GIF) and PDFs up to 50MB.
    Files are compressed and encrypted at rest.

    Requirements: 7.1
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Block modifications on completed/invoiced job cards
    await _check_job_card_not_locked(db, org_uuid, job_card_id)

    # Read file content
    content = await file.read()

    # Validate file size (Requirement 3.1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is 50 MB, received {len(content) / (1024 * 1024):.1f} MB",
        )

    # Validate non-empty file
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Validate file type (Requirement 2.1, 2.2)
    mime_type = file.content_type or "application/octet-stream"
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{mime_type}'. Accepted types: JPEG, PNG, WebP, GIF, PDF",
        )

    filename = file.filename or "attachment"

    try:
        result = await upload_attachment(
            db=db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            file_content=content,
            filename=filename,
            mime_type=mime_type,
        )
    except ValueError as exc:
        # Job card not found or validation error
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException as exc:
        # StorageManager raises HTTP 413 for quota exceeded
        # Convert to 507 per API design
        if exc.status_code == 413 and isinstance(exc.detail, dict):
            if exc.detail.get("error") == "storage_quota_exceeded":
                raise HTTPException(
                    status_code=507,
                    detail=exc.detail.get("message", "Storage quota exceeded"),
                )
        raise

    return result


@router.get(
    "/{job_card_id}/attachments",
    responses={
        200: {"description": "List of attachments"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
    },
    summary="List all attachments for a job card",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_attachments_endpoint(
    job_card_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all attachments for a job card.

    Returns attachment metadata including uploader name.

    Requirements: 7.2
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    attachments = await list_attachments(
        db=db,
        org_id=org_uuid,
        job_card_id=job_card_id,
    )

    return {
        "attachments": attachments,
        "total": len(attachments),
    }


@router.get(
    "/{job_card_id}/attachments/{attachment_id}",
    responses={
        200: {"description": "File content"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required or access denied"},
        404: {"description": "Attachment not found"},
    },
    summary="Download a specific attachment",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def download_attachment_endpoint(
    job_card_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Download/view a specific attachment.

    Returns the file content with appropriate Content-Type header.

    Requirements: 7.3
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Get attachment metadata
    try:
        attachment = await get_attachment(
            db=db,
            org_id=org_uuid,
            job_card_id=job_card_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Download and decrypt file content
    try:
        content = download_attachment(
            org_id=org_uuid,
            file_key=attachment["file_key"],
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "access denied" in error_msg.lower():
            raise HTTPException(status_code=403, detail=error_msg)
        raise HTTPException(status_code=404, detail=error_msg)

    return Response(
        content=content,
        media_type=attachment["mime_type"],
        headers={
            "Content-Disposition": f'inline; filename="{attachment["file_name"]}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/{job_card_id}/attachments/{attachment_id}",
    responses={
        200: {"description": "Attachment deleted"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
        404: {"description": "Attachment not found"},
    },
    summary="Delete an attachment",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def delete_attachment_endpoint(
    job_card_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete an attachment from a job card.

    Removes the file from disk and decrements storage usage.

    Requirements: 7.4
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Block modifications on completed/invoiced job cards
    await _check_job_card_not_locked(db, org_uuid, job_card_id)

    try:
        result = await delete_attachment(
            db=db,
            org_id=org_uuid,
            user_id=user_uuid,
            job_card_id=job_card_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result
