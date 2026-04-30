"""Invoice Attachment router — file upload and management endpoints.

Provides endpoints for uploading, listing, downloading, and deleting
file attachments on invoices.

Validates: Req 2.1–2.9, 3.1–3.5, 4.1–4.5, 5.1–5.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.invoices.attachment_service import (
    ALLOWED_MIME_TYPES,
    MAX_FILE_SIZE,
    delete_attachment,
    download_attachment,
    get_attachment,
    list_attachments,
    upload_attachment,
)
from app.modules.invoices.models import Invoice

router = APIRouter()

# Invoice statuses that block attachment deletion
_DELETE_BLOCKED_STATUSES = {"issued", "paid", "partially_paid", "overdue"}


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
    "/{invoice_id}/attachments",
    status_code=201,
    responses={
        201: {"description": "Attachment uploaded successfully"},
        400: {"description": "Invalid file type or empty file"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
        413: {"description": "File too large"},
        507: {"description": "Storage quota exceeded"},
    },
    summary="Upload a file attachment to an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def upload_attachment_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload a file attachment to an invoice.

    Accepts images (JPEG, PNG, WebP, GIF) and PDFs up to 20MB.
    Files are compressed and encrypted at rest.

    Validates: Req 2.1–2.9
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is 20 MB, received {len(content) / (1024 * 1024):.1f} MB",
        )

    # Validate non-empty file
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Validate file type
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
            invoice_id=invoice_id,
            content=content,
            filename=filename,
            mime_type=mime_type,
        )
    except ValueError as exc:
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
    "/{invoice_id}/attachments",
    responses={
        200: {"description": "List of attachments"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
    },
    summary="List all attachments for an invoice",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_attachments_endpoint(
    invoice_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all attachments for an invoice.

    Returns attachment metadata including uploader name.

    Validates: Req 3.1–3.5
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
        invoice_id=invoice_id,
    )

    return {
        "attachments": attachments,
        "total": len(attachments),
    }


@router.get(
    "/{invoice_id}/attachments/{attachment_id}",
    responses={
        200: {"description": "File content"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required or access denied"},
        404: {"description": "Attachment not found"},
    },
    summary="Download a specific invoice attachment",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def download_attachment_endpoint(
    invoice_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Download/view a specific invoice attachment.

    Returns the file content with appropriate Content-Type header.
    Images and PDFs use Content-Disposition: inline for browser preview.
    Other types use Content-Disposition: attachment for download.

    Validates: Req 4.1–4.5
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
            invoice_id=invoice_id,
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

    # Determine Content-Disposition: inline for images/PDFs, attachment for others
    mime_type = attachment["mime_type"]
    if mime_type.startswith("image/") or mime_type == "application/pdf":
        disposition = f'inline; filename="{attachment["file_name"]}"'
    else:
        disposition = f'attachment; filename="{attachment["file_name"]}"'

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/{invoice_id}/attachments/{attachment_id}",
    responses={
        200: {"description": "Attachment deleted"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required or invoice not draft"},
        404: {"description": "Attachment not found"},
    },
    summary="Delete an invoice attachment",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def delete_attachment_endpoint(
    invoice_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete an attachment from an invoice.

    Only allowed on draft invoices. Returns 403 for issued/paid invoices.
    Removes the file from disk and decrements storage usage.

    Validates: Req 5.1–5.4
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Check invoice status — only allow deletion on draft invoices
    result = await db.execute(
        select(Invoice.status).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_uuid,
        )
    )
    invoice_status = result.scalar_one_or_none()
    if invoice_status is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice_status != "draft":
        raise HTTPException(
            status_code=403,
            detail=f"Cannot delete attachments on {invoice_status} invoices. Only draft invoices allow attachment deletion.",
        )

    try:
        delete_result = await delete_attachment(
            db=db,
            org_id=org_uuid,
            user_id=user_uuid,
            invoice_id=invoice_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return delete_result
