"""FastAPI router for the visual page editor module.

Admin endpoints (mounted at ``/api/v2/admin/page-editor``) are guarded by the
``global_admin`` role and cover page CRUD, draft/publish workflow, revisions,
page settings, redirects, and media management. Mutating operations write an
append-only audit log entry.

A sibling public router (``public_router``) exposes the page resolve endpoint,
preview-token endpoint, sitemap, and robots.txt (implemented in Task 4.2).

Requirements: 13.1, 13.2, 13.3, 13.6
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import redis.asyncio as aioredis
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.database import async_session_factory, get_db_session
from app.core.redis import get_redis
from app.config import settings
from app.modules.auth.models import User
from app.modules.page_editor import media_service as media_svc
from app.modules.page_editor import service as page_svc
from app.modules.page_editor.models import EditorPage
from app.modules.page_editor.schemas import (
    CreatePageRequest,
    CreateRedirectRequest,
    EditingLock,
    MediaAsset,
    PageDetail,
    PageOrigin,
    PageSettingsRequest,
    PageSummary,
    PublicPageData,
    PublishRequest,
    PublishState,
    RedirectData,
    RedirectItem,
    RevisionSummary,
    SaveDraftRequest,
)

logger = logging.getLogger(__name__)

# Admin router — all endpoints require global_admin
router = APIRouter()


# ---------------------------------------------------------------------------
# Request-state helpers
# ---------------------------------------------------------------------------


def _extract_actor(request: Request) -> tuple[uuid.UUID | None, str | None, str | None]:
    """Return (user_id, ip_address, user_agent) from request state/headers."""
    user_id_raw = getattr(request.state, "user_id", None)
    try:
        user_id = uuid.UUID(user_id_raw) if user_id_raw else None
    except (ValueError, TypeError):
        user_id = None
    ip_address = getattr(request.state, "client_ip", None)
    user_agent = request.headers.get("user-agent")
    return user_id, ip_address, user_agent


async def _actor_email(db: AsyncSession, request: Request) -> str | None:
    """Return the acting user's email, reading state first and falling back to DB."""
    email = getattr(request.state, "email", None)
    if email:
        return email
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    return user.email if user is not None else None


async def _audit(
    db: AsyncSession,
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    before_value: dict[str, Any] | None = None,
    after_value: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry for an editor action (Requirement 13.6)."""
    user_id, ip_address, user_agent = _extract_actor(request)
    try:
        await write_audit_log(
            session=db,
            org_id=None,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_value=before_value,
            after_value=after_value,
            ip_address=ip_address,
            device_info=user_agent,
        )
    except Exception:  # pragma: no cover - audit should never break the request
        logger.exception("Failed to write audit log for action=%s", action)


async def _audit_out_of_band(
    request: Request,
    *,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID | None = None,
    after_value: dict[str, Any] | None = None,
) -> None:
    """Write an audit entry using a fresh session (for 403 denials).

    The regular session may already have been rolled back when a 403 is
    raised, so we open a new session to guarantee the audit row lands.
    """
    user_id_raw = getattr(request.state, "user_id", None)
    try:
        user_id = uuid.UUID(user_id_raw) if user_id_raw else None
    except (ValueError, TypeError):
        user_id = None
    ip_address = getattr(request.state, "client_ip", None)
    user_agent = request.headers.get("user-agent")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await write_audit_log(
                    session=session,
                    org_id=None,
                    user_id=user_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    after_value=after_value,
                    ip_address=ip_address,
                    device_info=user_agent,
                )
    except Exception:  # pragma: no cover
        logger.exception("Failed to write out-of-band audit log for action=%s", action)


# ---------------------------------------------------------------------------
# Global-admin guard with audit logging for denials (Requirement 13.3)
# ---------------------------------------------------------------------------


async def require_global_admin_with_audit(request: Request) -> None:
    """Dependency: require ``global_admin`` role; log an audit entry on denial.

    AuthMiddleware + RBACMiddleware usually stop non-global-admins before we
    reach the route, but we add a defence-in-depth check here and ensure an
    audit entry is written for every denial against an editor endpoint.
    """
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)

    if not user_id or not role:
        raise HTTPException(status_code=401, detail="Authentication required")

    if role != "global_admin":
        await _audit_out_of_band(
            request,
            action="page_editor.access_denied",
            entity_type="page_editor",
            after_value={
                "path": request.url.path,
                "method": request.method,
                "role": role,
            },
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied. Required role(s): global_admin",
        )


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _page_to_summary(page: EditorPage) -> PageSummary:
    state = page_svc._compute_publish_state(page)
    return PageSummary(
        page_key=page.page_key,
        title=page.title,
        page_slug=page.page_slug,
        page_origin=PageOrigin(page.page_origin),
        publish_state=PublishState(state),
        noindex=page.noindex,
        published_at=page.published_at,
        draft_updated_at=page.draft_updated_at,
        published_version=page.published_version,
        deleted_at=page.deleted_at,
    )


def _page_to_detail(page: EditorPage, editing_lock: dict | None = None) -> PageDetail:
    detail = PageDetail.model_validate(page)
    if editing_lock is not None:
        # Parse opened_at from ISO string if needed
        from datetime import datetime as _dt

        opened_at_raw = editing_lock.get("opened_at", "")
        try:
            opened_at = _dt.fromisoformat(opened_at_raw) if opened_at_raw else _dt.utcnow()
        except (ValueError, TypeError):
            opened_at = _dt.utcnow()
        detail.editing_lock = EditingLock(
            user_email=editing_lock.get("user_email", ""),
            opened_at=opened_at,
        )
    return detail


# ---------------------------------------------------------------------------
# Pages: list / create / read / draft / publish / preview / delete / undelete
# ---------------------------------------------------------------------------


@router.get(
    "/pages",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List managed pages (paginated, searchable, filterable)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def list_pages_endpoint(
    search: str | None = Query(default=None, description="Filter by title or slug substring"),
    origin: str | None = Query(
        default=None,
        description="Filter by page origin: 'hand-coded' or 'editor-created'",
    ),
    state: str | None = Query(
        default=None,
        description="Filter by publish state: 'never-published', 'published', 'draft-ahead'",
    ),
    include_deleted: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return paginated list of managed pages. Requirements: 3.1, 3.10, 3.11, 10.2."""
    pages, total = await page_svc.list_pages(
        db,
        search=search,
        origin=origin,
        state=state,
        include_deleted=include_deleted,
        offset=offset,
        limit=limit,
    )
    return {
        "items": [_page_to_summary(p).model_dump(mode="json") for p in pages],
        "total": total,
    }


@router.post(
    "/pages",
    response_model=PageDetail,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        409: {"description": "Slug conflict"},
        422: {"description": "Invalid slug or payload"},
    },
    summary="Create a new editor page",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def create_page_endpoint(
    payload: CreatePageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PageDetail:
    """Create an editor-only page. Requirements: 8.1, 8.2, 8.3, 8.4, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    page = await page_svc.create_page(db, payload, user_id=user_id)
    await _audit(
        db,
        request,
        action="page_editor.page_created",
        entity_type="editor_page",
        entity_id=page.page_key,
        after_value={
            "page_key": page.page_key,
            "page_slug": page.page_slug,
            "title": page.title,
            "template": payload.template,
        },
    )
    return _page_to_detail(page)


@router.get(
    "/pages/{page_key}",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
    },
    summary="Get page detail (with concurrent-edit lock info)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def get_page_endpoint(
    page_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> PageDetail:
    """Load a page. Acquires/refreshes the Redis editing lock and reports any
    different holder via ``editing_lock``. Requirements: 2.1, 3.1, 3.12, 13.6.
    """
    page = await page_svc.get_page(db, page_key)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    user_id, _, _ = _extract_actor(request)
    editing_lock: dict | None = None
    if user_id is not None:
        user_email = await _actor_email(db, request) or ""
        try:
            editing_lock = await page_svc.acquire_editor_lock(
                redis, page_key, user_id, user_email
            )
        except Exception:
            logger.exception("Failed to acquire editor lock for page %s", page_key)
            editing_lock = None

    await _audit(
        db,
        request,
        action="page_editor.page_opened",
        entity_type="editor_page",
        entity_id=page_key,
    )
    return _page_to_detail(page, editing_lock=editing_lock)


@router.put(
    "/pages/{page_key}/draft",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
        410: {"description": "Page has been deleted"},
        413: {"description": "Draft exceeds 1 MB"},
    },
    summary="Save draft content for a page",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def save_draft_endpoint(
    page_key: str,
    payload: SaveDraftRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
) -> PageDetail:
    """Save draft content. Requirements: 2.3, 2.4, 2.5, 3.6, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    page = await page_svc.save_draft(db, page_key, payload.content, user_id=user_id)

    # Refresh the editor lock on every draft save
    try:
        await page_svc.refresh_editor_lock(redis, page_key, user_id)
    except Exception:
        logger.exception("Failed to refresh editor lock for page %s", page_key)

    await _audit(
        db,
        request,
        action="page_editor.draft_saved",
        entity_type="editor_page",
        entity_id=page_key,
    )
    return _page_to_detail(page)


@router.post(
    "/pages/{page_key}/publish",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
        410: {"description": "Page has been deleted"},
        422: {"description": "No draft content to publish"},
    },
    summary="Publish a page (with optional note)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def publish_page_endpoint(
    page_key: str,
    payload: PublishRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PageDetail:
    """Publish the current draft. Requirements: 4.2, 4.3, 4.4, 5.1, 5.2, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    page = await page_svc.publish_page(
        db, page_key, user_id=user_id, note=payload.note
    )
    await _audit(
        db,
        request,
        action="page_editor.page_published",
        entity_type="editor_page",
        entity_id=page_key,
        after_value={
            "page_key": page_key,
            "published_version": page.published_version,
            "note": payload.note,
        },
    )
    return _page_to_detail(page)


@router.post(
    "/pages/{page_key}/preview",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
    },
    summary="Generate a tokenised preview URL (60-minute expiry)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def generate_preview_endpoint(
    page_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return a short-lived preview token and URL. Requirements: 4.1, 13.4, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    page = await page_svc.get_page(db, page_key)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    token = page_svc.generate_preview_token(
        page_key=page_key,
        user_id=user_id,
        secret=settings.jwt_secret,
    )
    await _audit(
        db,
        request,
        action="page_editor.preview_generated",
        entity_type="editor_page",
        entity_id=page_key,
    )
    return {
        "token": token,
        "preview_url": f"/api/v2/public/pages/preview/{token}",
        "expires_in_seconds": 3600,
    }


@router.get(
    "/pages/{page_key}/revisions",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List revisions for a page (newest first)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def list_revisions_endpoint(
    page_key: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return paginated revision history. Requirements: 5.1, 5.4."""
    revisions, total = await page_svc.list_revisions(
        db, page_key, offset=offset, limit=limit
    )
    items = [RevisionSummary.model_validate(r).model_dump(mode="json") for r in revisions]
    return {"items": items, "total": total}


@router.post(
    "/pages/{page_key}/revisions/{version}/revert",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page or revision not found"},
    },
    summary="Revert to a previous revision (draft-only — does not publish)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def revert_revision_endpoint(
    page_key: str,
    version: int,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PageDetail:
    """Copy a revision's content into draft. Requirements: 5.6, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    page = await page_svc.revert_to_revision(db, page_key, version, user_id=user_id)
    await _audit(
        db,
        request,
        action="page_editor.revision_reverted",
        entity_type="editor_page",
        entity_id=page_key,
        after_value={"reverted_to_version": version},
    )
    return _page_to_detail(page)


@router.put(
    "/pages/{page_key}/settings",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
        409: {"description": "Slug conflict or hand-coded slug change"},
        410: {"description": "Page has been deleted"},
    },
    summary="Update page settings, SEO metadata, and (optionally) slug",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def update_settings_endpoint(
    page_key: str,
    payload: PageSettingsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PageDetail:
    """Update SEO/settings; slug change auto-creates a 301 redirect.
    Requirements: 6.1, 6.7, 6.8, 6.10, 13.6.
    """
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    before = await page_svc.get_page(db, page_key)
    before_slug = before.page_slug if before is not None else None

    page = await page_svc.update_page_settings(
        db, page_key, payload, user_id=user_id
    )

    audit_action = "page_editor.page_settings_updated"
    if before_slug is not None and page.page_slug != before_slug:
        audit_action = "page_editor.page_slug_changed"

    await _audit(
        db,
        request,
        action=audit_action,
        entity_type="editor_page",
        entity_id=page_key,
        before_value={"page_slug": before_slug} if before_slug else None,
        after_value={
            "page_slug": page.page_slug,
            "title": page.title,
            "noindex": page.noindex,
        },
    )
    return _page_to_detail(page)


@router.delete(
    "/pages/{page_key}",
    status_code=204,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
        409: {"description": "Hand-coded pages cannot be deleted"},
        410: {"description": "Page is already deleted"},
    },
    summary="Soft-delete an editor-created page",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def delete_page_endpoint(
    page_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete. Hand-coded pages rejected with 409.
    Requirements: 10.1, 10.5, 13.6.
    """
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    await page_svc.soft_delete_page(db, page_key, user_id=user_id)
    await _audit(
        db,
        request,
        action="page_editor.page_deleted",
        entity_type="editor_page",
        entity_id=page_key,
    )
    return None


@router.post(
    "/pages/{page_key}/undelete",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
        409: {"description": "Slug now in use by another page"},
    },
    summary="Restore a soft-deleted page",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def undelete_page_endpoint(
    page_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PageDetail:
    """Restore a soft-deleted page. Requirements: 10.6, 13.6."""
    page = await page_svc.undelete_page(db, page_key)
    await _audit(
        db,
        request,
        action="page_editor.page_undeleted",
        entity_type="editor_page",
        entity_id=page_key,
    )
    return _page_to_detail(page)


@router.post(
    "/pages/{page_key}/revert-to-fallback",
    response_model=PageDetail,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Page not found"},
        409: {"description": "Not a hand-coded page"},
    },
    summary="Clear published content so the React fallback page renders again",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def revert_to_fallback_endpoint(
    page_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PageDetail:
    """Revert a hand-coded page to its fallback by clearing published_content
    (and the current draft). Requirements: 10.5, 13.6.
    """
    page = await page_svc.get_page(db, page_key)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    if page.page_origin != "hand-coded":
        raise HTTPException(
            status_code=409,
            detail="Revert to fallback is only available for hand-coded pages.",
        )

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    page.published_content = None
    page.published_version = None
    page.draft_content = None
    page.updated_at = now
    await db.flush()
    await db.refresh(page)
    page_svc.invalidate_sitemap_cache()

    await _audit(
        db,
        request,
        action="page_editor.reverted_to_fallback",
        entity_type="editor_page",
        entity_id=page_key,
    )
    return _page_to_detail(page)


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------


@router.get(
    "/redirects",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List redirects (paginated)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def list_redirects_endpoint(
    include_deleted: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return paginated redirects list. Requirements: 11.1, 11.3."""
    redirects, total = await page_svc.list_redirects(
        db, include_deleted=include_deleted, offset=offset, limit=limit
    )
    items = [RedirectItem.model_validate(r).model_dump(mode="json") for r in redirects]
    return {"items": items, "total": total}


@router.post(
    "/redirects",
    response_model=RedirectItem,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        409: {"description": "Conflicting slug or existing redirect"},
        422: {"description": "Invalid payload or self-redirect"},
    },
    summary="Create a redirect",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def create_redirect_endpoint(
    payload: CreateRedirectRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RedirectItem:
    """Create a slug redirect. Requirements: 11.1, 11.2, 11.5, 11.6, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    redirect = await page_svc.create_redirect(
        db,
        from_slug=payload.from_slug,
        to_slug_or_url=payload.to_slug_or_url,
        status_code=payload.status_code,
        user_id=user_id,
    )
    await _audit(
        db,
        request,
        action="page_editor.redirect_created",
        entity_type="editor_page_redirect",
        entity_id=redirect.id,
        after_value={
            "from_slug": redirect.from_slug,
            "to_slug_or_url": redirect.to_slug_or_url,
            "status_code": redirect.status_code,
        },
    )
    return RedirectItem.model_validate(redirect)


@router.delete(
    "/redirects/{redirect_id}",
    status_code=204,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Redirect not found"},
        410: {"description": "Redirect already deleted"},
    },
    summary="Soft-delete a redirect",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def delete_redirect_endpoint(
    redirect_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete a redirect. Requirements: 11.3, 11.7, 13.6."""
    redirect = await page_svc.soft_delete_redirect(db, redirect_id)
    await _audit(
        db,
        request,
        action="page_editor.redirect_deleted",
        entity_type="editor_page_redirect",
        entity_id=redirect.id,
        after_value={
            "from_slug": redirect.from_slug,
            "to_slug_or_url": redirect.to_slug_or_url,
        },
    )
    return None


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------


@router.post(
    "/media",
    response_model=MediaAsset,
    status_code=201,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        413: {"description": "File too large (max 10 MB)"},
        415: {"description": "Unsupported media type"},
    },
    summary="Upload a media asset (multipart/form-data)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def upload_media_endpoint(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
) -> MediaAsset:
    """Upload an image. Requirements: 12.1, 12.3, 13.6."""
    user_id, _, _ = _extract_actor(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    content = await file.read()
    filename = file.filename or f"upload-{uuid.uuid4().hex}"

    asset = await media_svc.upload_media(
        db, file_content=content, filename=filename, user_id=user_id
    )
    await _audit(
        db,
        request,
        action="page_editor.media_uploaded",
        entity_type="editor_media_asset",
        entity_id=asset.id,
        after_value={
            "filename": asset.filename,
            "content_type": asset.content_type,
            "size_bytes": asset.size_bytes,
        },
    )
    return MediaAsset.model_validate(asset)


@router.get(
    "/media",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List media assets (paginated, searchable)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def list_media_endpoint(
    search: str | None = Query(default=None, description="Filter by filename substring"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return paginated media list. Requirements: 12.2."""
    assets, total = await media_svc.list_media(
        db, search=search, offset=offset, limit=limit
    )
    items = [MediaAsset.model_validate(a).model_dump(mode="json") for a in assets]
    return {"items": items, "total": total}


@router.delete(
    "/media/{asset_id}",
    status_code=204,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Media asset not found"},
        409: {"description": "Asset is referenced by a page"},
        410: {"description": "Asset already deleted"},
    },
    summary="Soft-delete a media asset (rejects if referenced by any page)",
    dependencies=[Depends(require_global_admin_with_audit)],
)
async def delete_media_endpoint(
    asset_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete media. Requirements: 12.4, 13.6."""
    asset = await media_svc.delete_media(db, asset_id)
    await _audit(
        db,
        request,
        action="page_editor.media_deleted",
        entity_type="editor_media_asset",
        entity_id=asset.id,
        after_value={"filename": asset.filename},
    )
    return None


# ---------------------------------------------------------------------------
# Public router — no authentication required
# ---------------------------------------------------------------------------

public_router = APIRouter()


def _page_to_public(page: EditorPage) -> PublicPageData:
    """Serialize an EditorPage to the public-facing PublicPageData shape."""
    return PublicPageData(
        page_key=page.page_key,
        page_slug=page.page_slug,
        title=page.title,
        published_content=page.published_content,
        seo=page.seo,
        noindex=page.noindex,
        page_origin=PageOrigin(page.page_origin),
    )


def _request_host(request: Request) -> str:
    """Resolve the canonical host for sitemap/robots output.

    Prefers the request's ``Host`` header (trusted behind nginx) then falls
    back to ``request.url.hostname``. The scheme/port are not included since
    the generator emits ``https://{host}`` directly.
    """
    host_header = request.headers.get("host")
    if host_header:
        # Strip any port component so generated URLs stay clean
        return host_header.split(":", 1)[0]
    return request.url.hostname or "localhost"


@public_router.get(
    "/api/v2/public/pages/resolve",
    responses={
        200: {
            "description": "Page or redirect resolved",
            "content": {
                "application/json": {
                    "examples": {
                        "page": {
                            "summary": "Page found",
                            "value": {
                                "type": "page",
                                "data": {
                                    "page_key": "workshop",
                                    "page_slug": "/workshop",
                                    "title": "Workshop Management",
                                    "published_content": {"content": [], "root": {"props": {}}},
                                    "seo": None,
                                    "noindex": False,
                                    "page_origin": "hand-coded",
                                },
                            },
                        },
                        "redirect": {
                            "summary": "Redirect found",
                            "value": {
                                "type": "redirect",
                                "status_code": 301,
                                "target": "/new-slug",
                            },
                        },
                    }
                }
            },
        },
        404: {"description": "Page not found"},
    },
    summary="Resolve a public slug to page content or a redirect",
)
async def resolve_public_page_endpoint(
    slug: str = Query(..., description="Page slug to resolve, e.g. /workshop"),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Resolve a public slug. Redirects take priority over page records.

    Flow (Requirements: 7.2, 11.4, 11.5):
      1. Check for an active redirect on ``slug`` (one hop only).
      2. Otherwise load an active ``EditorPage`` by slug with published content.
      3. Otherwise return 404.
    """
    # 1. Redirect check (active redirects only, one hop max)
    redirect = await page_svc.resolve_redirect(db, slug)
    if redirect is not None:
        payload = RedirectData(
            to_slug_or_url=redirect.to_slug_or_url,
            status_code=redirect.status_code,
        )
        return {
            "type": "redirect",
            "status_code": payload.status_code,
            "target": payload.to_slug_or_url,
        }

    # 2. Page lookup (active + published)
    page = await page_svc.get_page_by_slug(db, slug)
    if page is None or page.published_content is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    public_data = _page_to_public(page)
    return {
        "type": "page",
        "data": public_data.model_dump(mode="json"),
    }


@public_router.get(
    "/api/v2/public/pages/preview/{token}",
    responses={
        200: {"description": "Preview data returned with X-Robots-Tag: noindex"},
        401: {"description": "Invalid or expired preview token"},
        404: {"description": "Page not found"},
    },
    summary="Fetch draft content for a signed preview token",
)
async def preview_public_page_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Return a page's draft content if the preview JWT is valid.

    Requirements: 4.1, 7.6, 13.4
    """
    payload = page_svc.verify_preview_token(token, secret=settings.jwt_secret)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired preview token.")

    page_key = payload.get("page_key")
    if not page_key:
        raise HTTPException(status_code=401, detail="Invalid preview token payload.")

    page = await page_svc.get_page(db, page_key)
    if page is None or page.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Page not found.")

    # Preview renders the draft — override published_content with draft_content
    preview_data = PublicPageData(
        page_key=page.page_key,
        page_slug=page.page_slug,
        title=page.title,
        published_content=page.draft_content,
        seo=page.seo,
        noindex=True,  # Previews are always noindex
        page_origin=PageOrigin(page.page_origin),
    )

    return JSONResponse(
        content=preview_data.model_dump(mode="json"),
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@public_router.get(
    "/sitemap.xml",
    responses={
        200: {
            "description": "XML sitemap of published, non-noindex pages",
            "content": {"application/xml": {}},
        },
    },
    summary="Dynamic XML sitemap",
)
async def sitemap_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Serve the dynamic sitemap. Requirements: 9.1, 9.2, 9.8."""
    host = _request_host(request)
    xml = await page_svc.generate_sitemap(db, host=host)
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@public_router.get(
    "/robots.txt",
    responses={
        200: {
            "description": "robots.txt with dynamic Allow/Disallow rules",
            "content": {"text/plain": {}},
        },
    },
    summary="Dynamic robots.txt",
)
async def robots_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Serve the dynamic robots.txt. Requirements: 9.1, 9.5."""
    host = _request_host(request)
    text = await page_svc.generate_robots(db, host=host)
    return PlainTextResponse(
        content=text,
        headers={"Cache-Control": "public, max-age=3600"},
    )
