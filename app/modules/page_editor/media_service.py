"""Media service for the visual page editor module.

Handles image upload with MIME validation by content sniffing, WebP variant
generation via Pillow, paginated listing, and soft-delete with reference checks.

Uses db.flush() (not commit) since the session.begin() context manager auto-commits.

Requirements: 12.1, 12.2, 12.3, 12.4
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.page_editor.models import EditorMediaAsset, EditorPage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Base upload directory (matches project convention)
UPLOAD_BASE = Path(os.environ.get("UPLOAD_DIR", "/app/uploads"))
MEDIA_SUBDIR = "page-editor"

# Maximum upload size: 10 MB
MAX_UPLOAD_SIZE = 10_485_760

# Accepted MIME types (Requirements: 12.3)
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/svg+xml",
    "image/gif",
}

# WebP variant widths (Requirements: 12.1)
VARIANT_WIDTHS = [640, 960, 1280, 1920]

# Magic byte signatures for content sniffing
_MAGIC_SIGNATURES: list[tuple[bytes, str]] = [
    # JPEG: starts with FF D8 FF
    (b"\xff\xd8\xff", "image/jpeg"),
    # PNG: starts with 89 50 4E 47 0D 0A 1A 0A
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    # GIF87a / GIF89a
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    # WebP: starts with RIFF....WEBP
    (b"RIFF", "image/webp"),  # Further validated below
]

# SVG detection: look for XML/SVG markers in the first 1024 bytes
_SVG_MARKERS = [b"<svg", b"<?xml"]


# ---------------------------------------------------------------------------
# MIME detection by content sniffing
# ---------------------------------------------------------------------------


def sniff_mime_type(content: bytes) -> str | None:
    """Detect MIME type from file content magic bytes.

    Returns the detected MIME type string or None if unrecognised.
    Uses magic byte signatures rather than trusting filename extension.

    Requirements: 12.3
    """
    # Check binary magic signatures
    for signature, mime_type in _MAGIC_SIGNATURES:
        if content[:len(signature)] == signature:
            # Special case for WebP: verify RIFF....WEBP structure
            if mime_type == "image/webp":
                if len(content) >= 12 and content[8:12] == b"WEBP":
                    return "image/webp"
                # RIFF but not WEBP — skip
                continue
            return mime_type

    # Check for SVG (text-based format)
    # Look in the first 1024 bytes for SVG markers
    header = content[:1024]
    # Try decoding as UTF-8 for text-based detection
    try:
        header_text = header.decode("utf-8", errors="ignore").lower().strip()
        for marker in _SVG_MARKERS:
            if marker.decode("utf-8") in header_text:
                # Confirm it's actually SVG (has <svg tag somewhere)
                if b"<svg" in content[:4096].lower():
                    return "image/svg+xml"
    except (UnicodeDecodeError, ValueError):
        pass

    return None


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def upload_media(
    db: AsyncSession,
    file_content: bytes,
    filename: str,
    user_id: uuid.UUID,
) -> EditorMediaAsset:
    """Upload an image: validate MIME, save original, generate WebP variants, store metadata.

    Steps:
    1. Validate file size ≤ 10 MB → raise HTTPException(413) if too large
    2. Validate MIME type by content sniffing → raise HTTPException(415) if invalid
    3. Generate a UUID for the asset
    4. Save original to app_uploads/page-editor/{uuid}/{filename}
    5. If not SVG: open with Pillow, generate WebP variants at 640/960/1280/1920px
    6. Get image dimensions from Pillow
    7. Create EditorMediaAsset row with metadata
    8. flush + refresh
    9. Return the asset

    Requirements: 12.1, 12.3
    """
    # 1. Validate file size
    if len(file_content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is 10 MB ({MAX_UPLOAD_SIZE} bytes).",
        )

    # 2. Validate MIME type by content sniffing
    detected_mime = sniff_mime_type(file_content)
    if detected_mime is None or detected_mime not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                "Unsupported media type. Accepted formats: "
                "JPEG, PNG, WebP, SVG, GIF."
            ),
        )

    # 3. Generate a UUID for the asset
    asset_id = uuid.uuid4()

    # 4. Save original to app_uploads/page-editor/{uuid}/{filename}
    asset_dir = UPLOAD_BASE / MEDIA_SUBDIR / str(asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)

    original_path = asset_dir / filename
    original_path.write_bytes(file_content)

    # 5 & 6. Generate WebP variants and get dimensions (skip for SVG)
    variants: dict[str, str] = {}
    width: int | None = None
    height: int | None = None

    if detected_mime != "image/svg+xml":
        try:
            img = Image.open(BytesIO(file_content))
            width = img.width
            height = img.height

            # Generate WebP variants only for widths smaller than original
            for variant_width in VARIANT_WIDTHS:
                if variant_width >= img.width:
                    # Generate one variant at original width then stop
                    _generate_variant(img, img.width, asset_dir)
                    variants[f"{img.width}w"] = str(
                        asset_dir / f"{img.width}w.webp"
                    )
                    break
                else:
                    _generate_variant(img, variant_width, asset_dir)
                    variants[f"{variant_width}w"] = str(
                        asset_dir / f"{variant_width}w.webp"
                    )
        except Exception as e:
            logger.warning(
                "Failed to process image %s: %s", filename, str(e)
            )
            # Still save the original even if variant generation fails

    # 7. Create EditorMediaAsset row
    asset = EditorMediaAsset(
        id=asset_id,
        filename=filename,
        original_path=str(original_path),
        content_type=detected_mime,
        size_bytes=len(file_content),
        width=width,
        height=height,
        variants=variants,
        uploaded_by=user_id,
    )
    db.add(asset)

    # 8. flush + refresh
    await db.flush()
    await db.refresh(asset)

    # 9. Return the asset
    return asset


async def list_media(
    db: AsyncSession,
    search: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[EditorMediaAsset], int]:
    """List media assets, paginated, search by filename, exclude deleted.

    Requirements: 12.2
    """
    # Build conditions
    conditions = [EditorMediaAsset.deleted_at.is_(None)]

    if search:
        search_term = f"%{search}%"
        conditions.append(EditorMediaAsset.filename.ilike(search_term))

    where_clause = and_(*conditions)

    # Count total
    count_stmt = (
        select(func.count())
        .select_from(EditorMediaAsset)
        .where(where_clause)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Fetch assets
    query = (
        select(EditorMediaAsset)
        .where(where_clause)
        .order_by(EditorMediaAsset.uploaded_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    assets = list(result.scalars().all())

    return assets, total


async def delete_media(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> EditorMediaAsset:
    """Delete a media asset. Check for references first, reject with 409 if referenced.

    Steps:
    1. Load the asset by ID (raise 404 if not found)
    2. Check if asset ID is referenced in any page's draft_content or published_content
    3. If referenced → raise HTTPException(409)
    4. Set deleted_at = now
    5. flush + refresh
    6. Return the asset

    Requirements: 12.4
    """
    # 1. Load the asset by ID
    result = await db.execute(
        select(EditorMediaAsset).where(EditorMediaAsset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found.")

    if asset.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Media asset is already deleted.")

    # 2. Check if asset ID is referenced in any page's draft_content or published_content
    asset_id_str = str(asset_id)

    # Query all non-deleted pages and check if the asset ID appears in their content
    pages_result = await db.execute(
        select(EditorPage.page_key, EditorPage.title, EditorPage.draft_content, EditorPage.published_content).where(
            EditorPage.deleted_at.is_(None)
        )
    )
    pages = pages_result.all()

    for page in pages:
        page_key, page_title, draft_content, published_content = page

        # Check draft_content
        if draft_content is not None:
            draft_json = json.dumps(draft_content)
            if asset_id_str in draft_json:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete: image is used by {page_title}",
                )

        # Check published_content
        if published_content is not None:
            published_json = json.dumps(published_content)
            if asset_id_str in published_json:
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot delete: image is used by {page_title}",
                )

    # 3. Set deleted_at = now
    now = datetime.now(timezone.utc)
    asset.deleted_at = now

    # 4. flush + refresh
    await db.flush()
    await db.refresh(asset)

    # 5. Return the asset
    return asset


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_variant(img: Image.Image, target_width: int, output_dir: Path) -> None:
    """Generate a single WebP variant at the specified width.

    Maintains aspect ratio. Saves to output_dir/{width}w.webp.
    """
    ratio = target_width / img.width
    target_height = int(img.height * ratio)

    # Resize with high-quality resampling
    resized = img.resize((target_width, target_height), Image.LANCZOS)

    # Convert to RGB if necessary (e.g., RGBA PNGs, palette mode)
    if resized.mode in ("RGBA", "LA"):
        # Preserve alpha for WebP
        pass
    elif resized.mode not in ("RGB", "RGBA"):
        resized = resized.convert("RGB")

    variant_path = output_dir / f"{target_width}w.webp"
    resized.save(variant_path, "WEBP", quality=82)
