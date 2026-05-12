"""Quote Attachment router — file upload and management endpoints.

Provides endpoints for uploading, listing, downloading, and deleting
file attachments on quotes.

Direct port of app/modules/invoices/attachment_router.py with:
- invoice_id → quote_id
- Invoice → Quote
- InvoiceAttachment → QuoteAttachment
- Error mapping: draft-only delete → 403

Validates: Requirements 3.1–3.10, 4.1–4.3, 5.3–5.5, 12.1–12.4, 14.1–14.5
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.quotes import attachment_service

router = APIRouter()


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
    "/{quote_id}/attachments",
    status_code=201,
    responses={
        201: {"description": "Attachment uploaded successfully"},
        400: {"description": "Invalid file type or max attachments exceeded"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
        404: {"description": "Quote not found"},
        413: {"description": "File too large"},
        507: {"description": "Storage quota exceeded"},
    },
    summary="Upload a file attachment to a quote",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def upload_attachment_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload a file attachment to a quote.

    Accepts images (JPEG, PNG, WebP, GIF) and PDFs up to 20MB.
    Maximum 5 attachments per quote.
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Read file content
    content = await file.read()
    filename = file.filename or "attachment"
    content_type = file.content_type or "application/octet-stream"

    try:
        result = await attachment_service.upload_attachment(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            quote_id=quote_id,
            content=content,
            filename=filename,
            mime_type=content_type,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "File too large" in error_msg:
            raise HTTPException(status_code=413, detail=error_msg)
        elif "Invalid file type" in error_msg:
            raise HTTPException(status_code=400, detail=error_msg)
        elif "Maximum" in error_msg:
            raise HTTPException(status_code=400, detail=error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    except HTTPException:
        # StorageManager raises HTTPException for quota exceeded (507)
        raise

    return {"attachment": result}


@router.get(
    "/{quote_id}/attachments",
    responses={
        200: {"description": "List of attachments"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
    },
    summary="List all attachments for a quote",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def list_attachments_endpoint(
    quote_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all attachments for a quote.

    Returns attachment metadata including uploader name.
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    attachments = await attachment_service.list_attachments(
        db,
        org_id=org_uuid,
        quote_id=quote_id,
    )

    return {
        "attachments": attachments,
        "total": len(attachments),
    }


@router.get(
    "/{quote_id}/attachments/{attachment_id}",
    responses={
        200: {"description": "File content"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required or access denied"},
        404: {"description": "Attachment not found"},
    },
    summary="Download a specific quote attachment",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def download_attachment_endpoint(
    quote_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Download/view a specific quote attachment.

    Returns the file content with appropriate Content-Type header.
    Images and PDFs use Content-Disposition: inline for browser preview.
    Other types use Content-Disposition: attachment for download.
    """
    org_uuid, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Get attachment metadata
    try:
        attachment = await attachment_service.get_attachment(
            db,
            org_id=org_uuid,
            quote_id=quote_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Download and decrypt file content
    try:
        file_bytes = attachment_service.download_attachment(
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
        content=file_bytes,
        media_type=mime_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/{quote_id}/attachments/{attachment_id}",
    responses={
        200: {"description": "Attachment deleted"},
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required or quote not draft"},
        404: {"description": "Attachment not found"},
    },
    summary="Delete a quote attachment",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def delete_attachment_endpoint(
    quote_id: uuid.UUID,
    attachment_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete an attachment from a quote.

    Only allowed on draft quotes. Returns 403 for non-draft quotes.
    Removes the file from disk and decrements storage usage.
    """
    org_uuid, user_uuid = _extract_org_context(request)
    if not org_uuid or not user_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        delete_result = await attachment_service.delete_attachment(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            quote_id=quote_id,
            attachment_id=attachment_id,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "draft" in error_msg.lower():
            raise HTTPException(status_code=403, detail=error_msg)
        elif "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)

    return {
        "deleted": True,
        "storage_freed_bytes": delete_result["storage_freed_bytes"],
    }
