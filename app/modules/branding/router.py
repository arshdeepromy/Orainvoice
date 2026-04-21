"""Platform branding API router (Global Admin).

Endpoints:
- GET  /api/v2/admin/branding           — get platform branding
- PUT  /api/v2/admin/branding           — update platform branding
- POST /api/v2/admin/branding/upload-logo    — upload logo image
- POST /api/v2/admin/branding/upload-favicon — upload favicon image
- GET  /api/v1/public/branding/file/{file_id} — serve branding file (public)

**Validates: Requirement 1 — Platform Rebranding**
"""

from __future__ import annotations

import io
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.branding.schemas import BrandingResponse, BrandingUpdate, PublicBrandingResponse
from app.modules.branding.service import BrandingService

logger = logging.getLogger(__name__)

router = APIRouter()
public_router = APIRouter()

# ---------------------------------------------------------------------------
# Branding file storage config
# ---------------------------------------------------------------------------
BRANDING_UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/uploads")) / "branding"
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_FAVICON_SIZE = 512 * 1024  # 512 KB
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}
ALLOWED_FAVICON_TYPES = {
    **ALLOWED_IMAGE_TYPES,
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}
MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _process_image(content: bytes, ext: str, max_dim: int = 512) -> bytes:
    """Resize image if larger than max_dim, return optimised bytes."""
    if ext == ".svg":
        return content
    if ext == ".ico":
        return content
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content))
        if img.mode in ("RGBA", "P", "LA"):
            # Keep alpha for PNG/WebP
            if ext not in (".png", ".webp"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
                img = bg
        w, h = img.size
        if max(w, h) > max_dim:
            r = max_dim / max(w, h)
            img = img.resize((int(w * r), int(h * r)), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = "PNG" if ext == ".png" else "WEBP" if ext == ".webp" else "JPEG"
        save_kwargs = {"optimize": True}
        if fmt == "JPEG":
            save_kwargs["quality"] = 85
        img.save(buf, format=fmt, **save_kwargs)
        return buf.getvalue()
    except Exception:
        logger.warning("Image processing failed, storing original")
        return content


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------


@public_router.get("", response_model=PublicBrandingResponse, summary="Get public platform branding")
async def get_public_branding(db: AsyncSession = Depends(get_db_session)):
    """Public endpoint — no auth required. Returns branding for login/signup pages."""
    svc = BrandingService(db)
    branding = await svc.get_branding()
    if branding is None:
        return PublicBrandingResponse(
            platform_name="OraInvoice",
            primary_colour="#2563EB",
            secondary_colour="#1E40AF",
        )
    return PublicBrandingResponse.model_validate(branding)


@public_router.get(
    "/file/{file_id}",
    summary="Serve a branding file (logo/favicon)",
    responses={404: {"description": "File not found"}},
)
async def serve_branding_file(file_id: str):
    """Public endpoint — serves uploaded branding files (logos, favicons).

    No authentication required since these are public branding assets
    displayed on login pages, emails, and PDFs.
    """
    # Sanitise file_id to prevent path traversal
    safe_id = Path(file_id).name
    if safe_id != file_id or ".." in file_id:
        raise HTTPException(status_code=400, detail="Invalid file ID")

    fp = BRANDING_UPLOAD_DIR / safe_id
    if not fp.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Verify the resolved path is within the branding directory
    try:
        fp.resolve().relative_to(BRANDING_UPLOAD_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    ext = fp.suffix.lower()
    content_type = MIME_MAP.get(ext, "application/octet-stream")

    return Response(
        content=fp.read_bytes(),
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'inline; filename="{safe_id}"',
        },
    )


# ---------------------------------------------------------------------------
# Admin endpoints (require global_admin role — enforced by parent router)
# ---------------------------------------------------------------------------


@router.get("", response_model=BrandingResponse, summary="Get platform branding")
async def get_branding(db: AsyncSession = Depends(get_db_session)):
    svc = BrandingService(db)
    branding = await svc.get_branding()
    if branding is None:
        raise HTTPException(status_code=404, detail="Branding not configured")
    return BrandingResponse.model_validate(branding)


@router.put("", response_model=BrandingResponse, summary="Update platform branding")
async def update_branding(
    payload: BrandingUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    svc = BrandingService(db)
    try:
        branding = await svc.update_branding(
            platform_name=payload.platform_name,
            logo_url=payload.logo_url,
            favicon_url=payload.favicon_url,
            primary_colour=payload.primary_colour,
            secondary_colour=payload.secondary_colour,
            website_url=payload.website_url,
            signup_url=payload.signup_url,
            support_email=payload.support_email,
            terms_url=payload.terms_url,
            auto_detect_domain=payload.auto_detect_domain,
            platform_theme=payload.platform_theme,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return BrandingResponse.model_validate(branding)


@router.post(
    "/upload-logo",
    summary="Upload a logo image",
    responses={413: {"description": "File too large"}, 415: {"description": "Unsupported file type"}},
)
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload a logo image file. Accepts PNG, JPEG, WebP, SVG. Max 2 MB.

    The uploaded file is stored on disk and the branding ``logo_url`` is
    updated to point to the public serving endpoint.
    """
    return await _handle_branding_upload(
        file=file,
        db=db,
        request=request,
        field="logo_url",
        max_size=MAX_LOGO_SIZE,
        allowed_types=ALLOWED_IMAGE_TYPES,
        max_dim=512,
        label="logo",
    )


@router.post(
    "/upload-favicon",
    summary="Upload a favicon image",
    responses={413: {"description": "File too large"}, 415: {"description": "Unsupported file type"}},
)
async def upload_favicon(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload a favicon image file. Accepts PNG, JPEG, WebP, SVG, ICO. Max 512 KB.

    The uploaded file is stored on disk and the branding ``favicon_url`` is
    updated to point to the public serving endpoint.
    """
    return await _handle_branding_upload(
        file=file,
        db=db,
        request=request,
        field="favicon_url",
        max_size=MAX_FAVICON_SIZE,
        allowed_types=ALLOWED_FAVICON_TYPES,
        max_dim=128,
        label="favicon",
    )


async def _handle_branding_upload(
    *,
    file: UploadFile,
    db: AsyncSession,
    request: Request,
    field: str,
    max_size: int,
    allowed_types: dict[str, str],
    max_dim: int,
    label: str,
) -> dict:
    """Shared upload handler for logo and favicon."""
    content_type = file.content_type or ""
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Allowed: {', '.join(allowed_types.keys())}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {max_size // 1024} KB",
        )

    ext = allowed_types[content_type]
    processed = _process_image(content, ext, max_dim=max_dim)

    # Store file
    file_id = f"{uuid.uuid4().hex}{ext}"
    BRANDING_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = BRANDING_UPLOAD_DIR / file_id
    dest.write_bytes(processed)

    # Build the public URL
    # Use X-Forwarded-Proto + Host if behind a proxy, else fall back to request base
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    public_url = f"{proto}://{host}/api/v1/public/branding/file/{file_id}"

    # Update branding record
    svc = BrandingService(db)
    try:
        await svc.update_branding(**{field: public_url})
    except ValueError as exc:
        # Clean up the file if DB update fails
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "message": f"{label.capitalize()} uploaded successfully",
        "url": public_url,
        "file_id": file_id,
    }
