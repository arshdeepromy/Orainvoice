"""Setup wizard API router.

Endpoints:
- POST /api/v2/setup-wizard/step/{step_number}  — submit or skip a step
- GET  /api/v2/setup-wizard/progress             — get wizard progress
- POST /api/v2/setup-wizard/upload-logo          — upload org logo (stored in PostgreSQL)

**Validates: Requirement 5.1, 5.6, 5.8**
"""

from __future__ import annotations

import io
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.admin.models import Organisation
from app.modules.setup_wizard.schemas import (
    StepResult,
    WizardProgressResponse,
    WizardStepRequest,
)
from app.modules.setup_wizard.service import SetupWizardService

logger = logging.getLogger(__name__)

router = APIRouter()

# Logo upload constraints
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}
MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _get_org_id(request: Request) -> uuid.UUID:
    """Extract org_id from the request state (set by auth/tenant middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return uuid.UUID(str(org_id))


@router.post(
    "/step/{step_number}",
    response_model=StepResult,
    summary="Submit or skip a wizard step",
)
async def submit_wizard_step(
    step_number: int,
    payload: WizardStepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StepResult:
    """Process a setup wizard step.

    Send ``skip: true`` to skip the step with defaults.
    """
    org_id = _get_org_id(request)
    svc = SetupWizardService(db)

    try:
        if payload.skip:
            return await svc.skip_step(org_id, step_number)
        return await svc.process_step(org_id, step_number, payload.data)
    except ValueError as exc:
        import logging
        logging.getLogger(__name__).error(
            "Wizard step %s ValueError for org %s: %s", step_number, org_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            "Wizard step %s unexpected error for org %s: %s", step_number, org_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/progress",
    response_model=WizardProgressResponse | None,
    summary="Get wizard completion state",
)
async def get_wizard_progress(
    request: Request,
    create: bool = True,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current wizard progress for the authenticated org.

    If ``create=false``, returns 404 when no progress record exists
    instead of auto-creating one. Useful for checking whether the org
    has ever interacted with the wizard.
    """
    org_id = _get_org_id(request)
    svc = SetupWizardService(db)

    if not create:
        progress = await svc.get_progress(org_id)
        if progress is None:
            raise HTTPException(status_code=404, detail="No wizard progress found")
    else:
        progress = await svc.get_or_create_progress(org_id)

    return WizardProgressResponse(
        org_id=progress.org_id,
        steps={
            f"step_{i}": getattr(progress, f"step_{i}_complete")
            for i in range(1, 8)
        },
        wizard_completed=progress.wizard_completed,
        completed_at=progress.completed_at,
        created_at=progress.created_at,
        updated_at=progress.updated_at,
    )


def _process_logo(content: bytes, ext: str, max_dim: int = 512) -> bytes:
    """Resize logo image if larger than max_dim, return optimised bytes."""
    if ext == ".svg":
        return content
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(content))
        if img.mode in ("RGBA", "P", "LA"):
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
        save_kwargs: dict = {"optimize": True}
        if fmt == "JPEG":
            save_kwargs["quality"] = 85
        img.save(buf, format=fmt, **save_kwargs)
        return buf.getvalue()
    except Exception:
        logger.warning("Logo image processing failed, storing original")
        return content


@router.post(
    "/upload-logo",
    summary="Upload org logo (stored in PostgreSQL)",
    responses={
        413: {"description": "File too large"},
        415: {"description": "Unsupported file type"},
    },
)
async def upload_org_logo(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Upload an org-level logo image. Stored as BYTEA in the organisations table.

    Accepts PNG, JPEG, WebP, SVG. Max 2 MB. Returns the public serving URL
    which is also saved into the org's JSONB settings as ``logo_url``.
    """
    org_id = _get_org_id(request)

    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Allowed: {', '.join(ALLOWED_IMAGE_TYPES.keys())}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_LOGO_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {MAX_LOGO_SIZE // 1024} KB",
        )

    ext = ALLOWED_IMAGE_TYPES[content_type]
    processed = _process_logo(content, ext)
    filename = file.filename or f"logo{ext}"

    # Store in organisations table BYTEA columns
    await db.execute(
        update(Organisation)
        .where(Organisation.id == org_id)
        .values(
            logo_data=processed,
            logo_content_type=content_type,
            logo_filename=filename,
        )
    )

    # Also update the logo_url in org settings JSONB to point to the DB-backed endpoint
    import json as _json
    from sqlalchemy import text
    public_url = f"/api/v2/setup-wizard/org-logo/{org_id}"
    await db.execute(
        text(
            "UPDATE organisations "
            "SET settings = settings || CAST(:patch AS jsonb) "
            "WHERE id = :oid"
        ),
        {"patch": _json.dumps({"logo_url": public_url}), "oid": str(org_id)},
    )

    await db.flush()

    return {
        "message": "Logo uploaded successfully",
        "url": public_url,
    }


@router.get(
    "/org-logo/{org_id}",
    summary="Serve org logo from PostgreSQL",
    responses={404: {"description": "Logo not found"}},
)
async def serve_org_logo(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
):
    """Public endpoint — serves the org logo stored in PostgreSQL BYTEA column.

    No authentication required since logos are displayed on invoices,
    public payment pages, quotes, and PDFs.
    """
    result = await db.execute(
        select(
            Organisation.logo_data,
            Organisation.logo_content_type,
            Organisation.logo_filename,
        ).where(Organisation.id == org_id)
    )
    row = result.one_or_none()

    if row is None or row.logo_data is None:
        raise HTTPException(status_code=404, detail="Logo not found")

    return Response(
        content=row.logo_data,
        media_type=row.logo_content_type or "image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
