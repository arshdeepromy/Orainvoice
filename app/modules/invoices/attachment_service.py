"""Service layer for invoice attachments.

Handles file upload, compression, encryption, storage quota enforcement,
and CRUD operations for invoice attachments.

Follows the same pattern as app/modules/job_cards/attachment_service.py.

Validates: Req 2.1–2.9, 3.1–3.5, 4.1–4.5, 5.1–5.4, 10.1–10.5
"""

from __future__ import annotations

import io
import os
import uuid
import zlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt, envelope_encrypt
from app.core.storage_manager import StorageManager
from app.modules.auth.models import User
from app.modules.invoices.attachment_models import InvoiceAttachment
from app.modules.invoices.models import Invoice


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UPLOAD_BASE = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
ATTACHMENT_CATEGORY = "invoice-attachments"

# Maximum file size: 20 MB
MAX_FILE_SIZE = 20 * 1024 * 1024

# Maximum attachments per invoice
MAX_ATTACHMENTS_PER_INVOICE = 5

# Accepted MIME types
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "application/pdf",
}

# Image extensions for compression
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Compression flags (matching uploads router / job card service)
COMP_ZLIB = b"\x01"
COMP_IMAGE = b"\x02"

# MIME type to extension mapping
MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}


# ---------------------------------------------------------------------------
# File helpers (compress, encrypt, store, read, delete)
# ---------------------------------------------------------------------------


def _compress_image(content: bytes, ext: str) -> tuple[bytes, str]:
    """Compress and resize an image.

    Resize to max 2048px on longest edge, convert to JPEG at 82% quality
    (except PNG which stays PNG).
    """
    from PIL import Image

    img = Image.open(io.BytesIO(content))

    # Convert RGBA/P/LA to RGB for JPEG output
    if img.mode in ("RGBA", "P", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = bg

    # Resize if larger than 2048px
    w, h = img.size
    if max(w, h) > 2048:
        r = 2048 / max(w, h)
        img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)

    buf = io.BytesIO()
    if ext.lower() == ".png":
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), ".png"

    # For all other image types, convert to JPEG
    img.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue(), ".jpg"


def _store_file(
    content: bytes,
    filename: str,
    org_id: str,
    mime_type: str,
) -> tuple[str, int]:
    """Compress, encrypt, and store a file on disk.

    Returns (file_key, file_size).
    """
    ext = MIME_TO_EXT.get(mime_type, Path(filename).suffix.lower() or ".bin")

    # Compress based on file type
    if ext in IMAGE_EXTS:
        try:
            processed, ext = _compress_image(content, ext)
            flag = COMP_IMAGE
        except Exception:
            # Fallback to zlib if image processing fails
            processed = zlib.compress(content, 6)
            flag = COMP_ZLIB
    else:
        # PDF and other files use zlib compression
        processed = zlib.compress(content, 6)
        flag = COMP_ZLIB

    # Encrypt the compressed content
    encrypted = envelope_encrypt(processed)

    # Generate unique file key
    file_key = f"{ATTACHMENT_CATEGORY}/{org_id}/{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_BASE / file_key
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Write flag byte + encrypted content
    dest.write_bytes(flag + encrypted)

    file_size = len(flag) + len(encrypted)
    return file_key, file_size


def _read_file(file_key: str) -> bytes:
    """Read, decrypt, and decompress a file from disk.

    Returns the original file content.
    """
    fp = UPLOAD_BASE / file_key
    if not fp.is_file():
        raise ValueError("File not found")

    # Validate path to prevent directory traversal
    try:
        fp.resolve().relative_to(UPLOAD_BASE.resolve())
    except ValueError:
        raise ValueError("Access denied")

    raw = fp.read_bytes()
    if len(raw) < 2:
        raise ValueError("Corrupt file")

    flag, blob = raw[0:1], raw[1:]

    # Decrypt
    try:
        decrypted = envelope_decrypt(blob)
    except Exception:
        raise ValueError("Decryption failed")

    # Decompress if needed
    if flag == COMP_ZLIB:
        return zlib.decompress(decrypted)
    else:
        # COMP_IMAGE: already decompressed image data
        return decrypted


def _delete_file(file_key: str) -> None:
    """Delete a file from disk."""
    fp = UPLOAD_BASE / file_key

    # Validate path to prevent directory traversal
    try:
        fp.resolve().relative_to(UPLOAD_BASE.resolve())
    except ValueError:
        raise ValueError("Access denied")

    if fp.is_file():
        fp.unlink()


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def upload_attachment(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    content: bytes,
    filename: str,
    mime_type: str,
) -> dict:
    """Upload a file attachment to an invoice.

    Validates file type and size, checks invoice exists and belongs to org,
    enforces max 5 attachments per invoice, compresses and encrypts the file,
    checks storage quota, creates the database record, and increments
    storage usage.

    Returns:
        dict with attachment metadata

    Raises:
        ValueError: Invalid file type, file too large, invoice not found,
                    or max attachments exceeded
        HTTPException: Storage quota exceeded (from StorageManager)
    """
    org_id_str = str(org_id)

    # Validate MIME type
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"Invalid file type '{mime_type}'. "
            "Accepted types: JPEG, PNG, WebP, GIF, PDF"
        )

    # Validate file size
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(
            f"File too large. Maximum size is 20 MB, "
            f"received {len(content) / (1024 * 1024):.1f} MB"
        )

    if not content:
        raise ValueError("Empty file")

    # Validate invoice exists and belongs to org
    result = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.org_id == org_id,
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found in this organisation")

    # Enforce max attachments per invoice
    count_result = await db.execute(
        select(func.count()).select_from(InvoiceAttachment).where(
            InvoiceAttachment.invoice_id == invoice_id,
            InvoiceAttachment.org_id == org_id,
        )
    )
    current_count = count_result.scalar() or 0
    if current_count >= MAX_ATTACHMENTS_PER_INVOICE:
        raise ValueError(
            f"Maximum {MAX_ATTACHMENTS_PER_INVOICE} attachments per invoice. "
            f"This invoice already has {current_count}."
        )

    # Store file (compress + encrypt)
    file_key, file_size = _store_file(content, filename, org_id_str, mime_type)

    # Check and enforce storage quota
    sm = StorageManager(db)
    await sm.enforce_quota(org_id_str, file_size)

    # Create attachment record
    attachment = InvoiceAttachment(
        invoice_id=invoice_id,
        org_id=org_id,
        file_key=file_key,
        file_name=filename,
        file_size=file_size,
        mime_type=mime_type,
        uploaded_by=user_id,
    )
    db.add(attachment)
    await db.flush()

    # Increment storage usage
    await sm.increment_usage(org_id_str, file_size)

    # Refresh to get server-generated values
    await db.refresh(attachment)

    return {
        "id": attachment.id,
        "invoice_id": attachment.invoice_id,
        "file_key": attachment.file_key,
        "file_name": attachment.file_name,
        "file_size": attachment.file_size,
        "mime_type": attachment.mime_type,
        "uploaded_by": attachment.uploaded_by,
        "created_at": attachment.created_at,
    }


async def list_attachments(
    db: AsyncSession,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> list[dict]:
    """List all attachments for an invoice with uploader name.

    Returns:
        List of attachment dicts ordered by sort_order then created_at,
        with uploaded_by_name included.
    """
    result = await db.execute(
        select(
            InvoiceAttachment.id,
            InvoiceAttachment.invoice_id,
            InvoiceAttachment.file_key,
            InvoiceAttachment.file_name,
            InvoiceAttachment.file_size,
            InvoiceAttachment.mime_type,
            InvoiceAttachment.uploaded_by,
            InvoiceAttachment.sort_order,
            InvoiceAttachment.created_at,
            User.first_name,
            User.last_name,
        )
        .join(User, User.id == InvoiceAttachment.uploaded_by, isouter=True)
        .where(
            InvoiceAttachment.invoice_id == invoice_id,
            InvoiceAttachment.org_id == org_id,
        )
        .order_by(InvoiceAttachment.sort_order, InvoiceAttachment.created_at)
    )

    attachments = []
    for row in result:
        first = row.first_name or ""
        last = row.last_name or ""
        uploader_name = f"{first} {last}".strip() or None

        attachments.append({
            "id": row.id,
            "invoice_id": row.invoice_id,
            "file_key": row.file_key,
            "file_name": row.file_name,
            "file_size": row.file_size,
            "mime_type": row.mime_type,
            "uploaded_by": row.uploaded_by,
            "uploaded_by_name": uploader_name,
            "sort_order": row.sort_order,
            "created_at": row.created_at,
        })

    return attachments


async def get_attachment(
    db: AsyncSession,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> dict:
    """Get a single attachment record.

    Returns:
        Attachment dict

    Raises:
        ValueError: Attachment not found
    """
    result = await db.execute(
        select(InvoiceAttachment).where(
            InvoiceAttachment.id == attachment_id,
            InvoiceAttachment.invoice_id == invoice_id,
            InvoiceAttachment.org_id == org_id,
        )
    )
    attachment = result.scalar_one_or_none()

    if attachment is None:
        raise ValueError("Attachment not found")

    return {
        "id": attachment.id,
        "invoice_id": attachment.invoice_id,
        "file_key": attachment.file_key,
        "file_name": attachment.file_name,
        "file_size": attachment.file_size,
        "mime_type": attachment.mime_type,
        "uploaded_by": attachment.uploaded_by,
        "sort_order": attachment.sort_order,
        "created_at": attachment.created_at,
    }


def download_attachment(org_id: uuid.UUID, file_key: str) -> bytes:
    """Download and decrypt an attachment file.

    Validates that the file_key belongs to the specified org to prevent
    unauthorized access.

    Returns:
        Decrypted file content as bytes

    Raises:
        ValueError: File not found, access denied, or decryption failed
    """
    org_id_str = str(org_id)

    # Validate file_key belongs to this org (security check)
    expected_prefix = f"{ATTACHMENT_CATEGORY}/{org_id_str}/"
    if not file_key.startswith(expected_prefix):
        raise ValueError("Access denied")

    return _read_file(file_key)


async def delete_attachment(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> dict:
    """Delete an attachment file and database record.

    Deletes the file from disk, removes the database record, and
    decrements the organisation's storage usage.

    Returns:
        dict with deletion confirmation and storage freed

    Raises:
        ValueError: Attachment not found
    """
    org_id_str = str(org_id)

    # Get attachment record
    result = await db.execute(
        select(InvoiceAttachment).where(
            InvoiceAttachment.id == attachment_id,
            InvoiceAttachment.invoice_id == invoice_id,
            InvoiceAttachment.org_id == org_id,
        )
    )
    attachment = result.scalar_one_or_none()

    if attachment is None:
        raise ValueError("Attachment not found")

    file_key = attachment.file_key
    file_size = attachment.file_size

    # Delete file from disk
    try:
        _delete_file(file_key)
    except ValueError:
        # File may already be deleted, continue with DB cleanup
        pass

    # Delete database record
    await db.delete(attachment)
    await db.flush()

    # Decrement storage usage
    sm = StorageManager(db)
    await sm.decrement_usage(org_id_str, file_size)

    return {
        "message": "Attachment deleted",
        "storage_freed_bytes": file_size,
    }


async def get_attachment_count(
    db: AsyncSession,
    org_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> int:
    """Return the number of attachments for an invoice."""
    result = await db.execute(
        select(func.count()).select_from(InvoiceAttachment).where(
            InvoiceAttachment.invoice_id == invoice_id,
            InvoiceAttachment.org_id == org_id,
        )
    )
    return result.scalar() or 0
