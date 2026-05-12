"""Service layer for the visual page editor module.

Core CRUD operations for editor pages: create, get, list, save draft,
soft-delete, undelete, publish workflow, preview tokens, and sitemap/robots generation.
Uses db.flush() (not commit) since the session.begin() context manager auto-commits.

Requirements: 2.1, 2.3, 3.1, 3.6, 3.12, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.7, 8.1, 8.2, 8.3, 8.4, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8, 10.1, 10.5, 10.6
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Set

import jwt
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.page_editor.models import EditorPage, EditorPageRedirect, EditorPageRevision
from app.modules.page_editor.schemas import CreatePageRequest, PageSettingsRequest

logger = logging.getLogger(__name__)

# Maximum allowed size for serialized Puck_Data JSON (1 MB)
MAX_JSON_SIZE_BYTES = 1_048_576

# Maximum number of revisions to keep per page (Requirements: 5.1, 5.7)
REVISION_CAP = 50

# ---------------------------------------------------------------------------
# Sitemap/Robots cache (Requirements: 9.1, 9.6)
# ---------------------------------------------------------------------------

# Cache TTL: 5 minutes
_SITEMAP_CACHE_TTL = 300

# Module-level cache: {"sitemap": (content, timestamp), "robots": (content, timestamp)}
_sitemap_robots_cache: dict[str, tuple[str, float]] = {}

# ---------------------------------------------------------------------------
# Slug validation constants (Requirements: 8.2, 8.3, 8.7)
# ---------------------------------------------------------------------------

SLUG_PATTERN = re.compile(r"^/(?:[a-z0-9-]+)(?:/[a-z0-9-]+){0,2}$")

# Reserved prefixes from nginx config, auth routes, API routes, product routes,
# public routes, static/system paths, and alias redirects.
RESERVED_PREFIXES: Set[str] = {
    # Auth routes
    "/login",
    "/register",
    "/forgot-password",
    "/reset-password",
    "/verify-email",
    "/mfa",
    "/auth",
    # API routes
    "/api",
    # Admin routes
    "/admin",
    # Product routes
    "/dashboard",
    "/invoices",
    "/quotes",
    "/customers",
    "/inventory",
    "/jobs",
    "/reports",
    "/settings",
    "/billing",
    "/staff",
    "/schedule",
    "/expenses",
    "/purchase-orders",
    "/compliance",
    "/franchise",
    "/accounting",
    "/banking",
    "/tax",
    "/pos",
    "/kiosk",
    # Public routes already in use
    "/workshop",
    "/trades",
    "/privacy",
    # Static/system
    "/assets",
    "/static",
    "/uploads",
    "/health",
    "/ws",
    "/_",
    # Alias redirects
    "/mechanics",
    "/garage",
}


# ---------------------------------------------------------------------------
# Slug validation and derivation (Requirements: 8.2, 8.3, 8.7)
# ---------------------------------------------------------------------------


def validate_slug(slug: str) -> str:
    """Validate slug format and reserved prefix check.

    Raises HTTPException(422) if the slug format is invalid.
    Raises HTTPException(409) if the slug collides with a reserved prefix.

    Returns the slug unchanged if valid.
    """
    # Length check
    if len(slug) > 80:
        raise HTTPException(
            status_code=422,
            detail="Slug must be at most 80 characters.",
        )

    # Regex format check
    if not SLUG_PATTERN.match(slug):
        raise HTTPException(
            status_code=422,
            detail=(
                "Slug must match /segment or /seg/seg or /seg/seg/seg "
                "(lowercase letters, digits, and hyphens only)."
            ),
        )

    # Reserved prefix check
    for prefix in RESERVED_PREFIXES:
        if slug == prefix or slug.startswith(prefix + "/"):
            raise HTTPException(
                status_code=409,
                detail=f"Slug conflicts with reserved path: {prefix}",
            )

    return slug


def title_to_slug(title: str) -> str:
    """Derive a slug from a page title.

    Steps:
    1. Unicode normalize (NFKD)
    2. ASCII fold (encode to ASCII, ignore errors)
    3. Lowercase
    4. Replace spaces and underscores with hyphens
    5. Remove any character that isn't alphanumeric or hyphen
    6. Collapse multiple hyphens into one
    7. Strip leading/trailing hyphens
    8. Prefix with /
    9. If result is just / (empty title), return /untitled

    Requirements: 8.7
    """
    # Unicode normalize (NFKD)
    normalized = unicodedata.normalize("NFKD", title)
    # ASCII fold
    ascii_str = normalized.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    ascii_str = ascii_str.lower()
    # Replace spaces and underscores with hyphens
    ascii_str = ascii_str.replace(" ", "-").replace("_", "-")
    # Remove any character that isn't alphanumeric or hyphen
    ascii_str = re.sub(r"[^a-z0-9-]", "", ascii_str)
    # Collapse multiple hyphens into one
    ascii_str = re.sub(r"-{2,}", "-", ascii_str)
    # Strip leading/trailing hyphens
    slug = ascii_str.strip("-")
    # Prefix with /
    if slug:
        return f"/{slug}"
    # Empty title → /untitled
    return "/untitled"


def sanitise_html_in_content(content: dict) -> dict:
    """Sanitise HTML string fields within Puck_Data.

    Delegates to sanitiser.sanitise_puck_content() which recursively walks
    the Puck_Data JSON and sanitises all HTML string values.

    Requirements: 2.4, 2.5
    """
    from app.modules.page_editor.sanitiser import sanitise_puck_content

    return sanitise_puck_content(content)


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


async def create_page(
    db: AsyncSession,
    request: CreatePageRequest,
    user_id: uuid.UUID,
    templates: dict[str, dict] | None = None,
) -> EditorPage:
    """Create a new editor page with an initial revision.

    Validates slug, checks reserved prefixes, creates EditorPage row
    with page_origin='editor-created', and writes an initial revision
    (version=1).

    Requirements: 8.1, 8.2, 8.3, 8.4
    """
    # Validate slug format and reserved prefix check
    validate_slug(request.page_slug)

    # Check slug uniqueness among active pages
    existing = await db.execute(
        select(EditorPage.page_key).where(
            and_(
                EditorPage.page_slug == request.page_slug,
                EditorPage.deleted_at.is_(None),
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Slug '{request.page_slug}' is already in use by another page.",
        )

    # Determine initial draft content from template or request
    template_name = request.template or "blank"
    if request.content is not None:
        # Duplicate flow — use provided content
        draft_content = request.content
        template_name = "duplicate"
    elif templates and template_name in templates:
        draft_content = templates[template_name]
    else:
        # Blank template — empty Puck_Data structure
        draft_content = {"content": [], "root": {"props": {}}}

    # Generate page_key from slug (strip leading slash, replace / with -)
    page_key = request.page_slug.lstrip("/").replace("/", "-")

    # Ensure page_key uniqueness
    key_exists = await db.execute(
        select(EditorPage.page_key).where(EditorPage.page_key == page_key)
    )
    if key_exists.scalar_one_or_none() is not None:
        # Append a short suffix to make it unique
        page_key = f"{page_key}-{uuid.uuid4().hex[:6]}"

    now = datetime.now(timezone.utc)

    # Build SEO metadata
    seo: dict = {}
    if request.meta_title:
        seo["meta_title"] = request.meta_title
    if request.meta_description:
        seo["meta_description"] = request.meta_description

    # Create the page record
    page = EditorPage(
        page_key=page_key,
        page_origin="editor-created",
        page_slug=request.page_slug,
        title=request.title,
        draft_content=draft_content,
        published_content=None,
        published_version=None,
        draft_updated_at=now,
        draft_updated_by=user_id,
        published_at=None,
        published_by=None,
        seo=seo,
        noindex=False,
        deleted_at=None,
        deleted_by=None,
    )
    db.add(page)
    await db.flush()

    # Create initial revision (version 1)
    revision = EditorPageRevision(
        page_key=page_key,
        version=1,
        content=draft_content,
        published_at=None,
        published_by=None,
        note=f"initial creation from template: {template_name}",
    )
    db.add(revision)
    await db.flush()

    await db.refresh(page)
    invalidate_sitemap_cache()
    return page


async def get_page(db: AsyncSession, page_key: str) -> EditorPage | None:
    """Load a page by key.

    Returns the EditorPage or None if not found. The editing lock check
    is handled at the router level (Redis-based advisory lock).

    Requirements: 2.1, 3.1
    """
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    return result.scalar_one_or_none()


async def get_page_by_slug(db: AsyncSession, slug: str) -> EditorPage | None:
    """Load an active (non-deleted) page by its slug.

    Used by the public resolve endpoint. Returns None if no page exists
    at that slug or if the page has been soft-deleted.

    Requirements: 7.2, 7.3
    """
    result = await db.execute(
        select(EditorPage).where(
            and_(
                EditorPage.page_slug == slug,
                EditorPage.deleted_at.is_(None),
            )
        )
    )
    return result.scalar_one_or_none()


async def list_pages(
    db: AsyncSession,
    search: str | None = None,
    origin: str | None = None,
    state: str | None = None,
    include_deleted: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[EditorPage], int]:
    """Paginated page list with search and filters.

    Supports filtering by origin (hand-coded/editor-created), publish state
    (never-published/published/draft-ahead), text search on title/slug,
    and optional inclusion of soft-deleted pages.

    Requirements: 3.1, 3.6, 10.1
    """
    # Base conditions
    conditions = []

    if not include_deleted:
        conditions.append(EditorPage.deleted_at.is_(None))

    if search:
        search_term = f"%{search}%"
        conditions.append(
            or_(
                EditorPage.title.ilike(search_term),
                EditorPage.page_slug.ilike(search_term),
            )
        )

    if origin:
        conditions.append(EditorPage.page_origin == origin)

    # Build base query
    base_where = and_(*conditions) if conditions else True

    # Count total
    count_stmt = select(func.count()).select_from(EditorPage).where(base_where)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    # Fetch pages
    query = (
        select(EditorPage)
        .where(base_where)
        .order_by(EditorPage.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    pages = list(result.scalars().all())

    # Post-filter by publish state if requested
    if state:
        filtered_pages = []
        for page in pages:
            page_state = _compute_publish_state(page)
            if page_state == state:
                filtered_pages.append(page)
        pages = filtered_pages

    return pages, total


def _compute_publish_state(page: EditorPage) -> str:
    """Compute the publish state from page data.

    - never-published: published_content is None
    - published: draft matches published (or no draft changes since publish)
    - draft-ahead: draft differs from published
    """
    if page.published_content is None:
        return "never-published"

    # If draft_updated_at is after published_at, draft is ahead
    if page.draft_updated_at and page.published_at:
        if page.draft_updated_at > page.published_at:
            return "draft-ahead"

    # Compare content directly
    if page.draft_content != page.published_content:
        return "draft-ahead"

    return "published"


async def save_draft(
    db: AsyncSession,
    page_key: str,
    content: dict,
    user_id: uuid.UUID,
) -> EditorPage:
    """Save draft content for a page.

    Validates JSON size (≤ 1MB), sanitises HTML fields, and updates
    draft_content on the page record.

    Requirements: 2.3, 2.4, 2.5
    """
    # Validate JSON size
    serialized = json.dumps(content, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_JSON_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Draft content exceeds maximum size of 1 MB.",
        )

    # Sanitise HTML fields (placeholder — full implementation in task 2.5)
    content = sanitise_html_in_content(content)

    # Load the page
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    if page.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Page has been deleted.")

    # Update draft
    now = datetime.now(timezone.utc)
    page.draft_content = content
    page.draft_updated_at = now
    page.draft_updated_by = user_id
    page.updated_at = now

    await db.flush()
    await db.refresh(page)
    return page


async def soft_delete_page(
    db: AsyncSession,
    page_key: str,
    user_id: uuid.UUID,
) -> EditorPage:
    """Soft-delete a page by setting deleted_at and deleted_by.

    Rejects hand-coded pages with HTTP 409 — those cannot be deleted,
    only reverted to fallback.

    Requirements: 10.1, 10.5
    """
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    if page.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Page is already deleted.")

    # Reject hand-coded pages
    if page.page_origin == "hand-coded":
        raise HTTPException(
            status_code=409,
            detail=(
                "Hand-coded pages cannot be deleted. "
                "Use 'Revert to Fallback' to clear published content instead."
            ),
        )

    now = datetime.now(timezone.utc)
    page.deleted_at = now
    page.deleted_by = user_id
    page.updated_at = now

    await db.flush()
    await db.refresh(page)
    invalidate_sitemap_cache()
    return page


async def undelete_page(
    db: AsyncSession,
    page_key: str,
) -> EditorPage:
    """Restore a soft-deleted page by clearing deleted_at/deleted_by.

    Checks that the page's slug does not conflict with another active page
    before restoring.

    Requirements: 10.6
    """
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    if page.deleted_at is None:
        raise HTTPException(status_code=400, detail="Page is not deleted.")

    # Check slug conflict with active pages
    conflict = await db.execute(
        select(EditorPage.page_key, EditorPage.title).where(
            and_(
                EditorPage.page_slug == page.page_slug,
                EditorPage.deleted_at.is_(None),
                EditorPage.page_key != page_key,
            )
        )
    )
    conflicting = conflict.first()
    if conflicting is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot restore: slug '{page.page_slug}' is already in use "
                f"by '{conflicting.title}'."
            ),
        )

    now = datetime.now(timezone.utc)
    page.deleted_at = None
    page.deleted_by = None
    page.updated_at = now

    await db.flush()
    await db.refresh(page)
    invalidate_sitemap_cache()
    return page


# ---------------------------------------------------------------------------
# Revision control (Requirements: 5.1, 5.2, 5.3, 5.4, 5.6)
# ---------------------------------------------------------------------------


async def list_revisions(
    db: AsyncSession,
    page_key: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[EditorPageRevision], int]:
    """List revisions for a page, newest-first, paginated.

    Requirements: 5.1, 5.4
    """
    # Count total revisions for the page
    count_stmt = (
        select(func.count())
        .select_from(EditorPageRevision)
        .where(EditorPageRevision.page_key == page_key)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Query revisions ordered by version DESC (newest first)
    query = (
        select(EditorPageRevision)
        .where(EditorPageRevision.page_key == page_key)
        .order_by(EditorPageRevision.version.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    revisions = list(result.scalars().all())

    return revisions, total


async def revert_to_revision(
    db: AsyncSession,
    page_key: str,
    version: int,
    user_id: uuid.UUID,
) -> EditorPage:
    """Copy a revision's content to draft_content, mark dirty, do NOT publish.

    Requirements: 5.6
    """
    # 1. Load the page by key
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    # 2. Load the specific revision by page_key + version
    rev_result = await db.execute(
        select(EditorPageRevision).where(
            and_(
                EditorPageRevision.page_key == page_key,
                EditorPageRevision.version == version,
            )
        )
    )
    revision = rev_result.scalar_one_or_none()
    if revision is None:
        raise HTTPException(
            status_code=404,
            detail=f"Revision version {version} not found for page '{page_key}'.",
        )

    now = datetime.now(timezone.utc)

    # 3. Copy revision.content to page.draft_content
    page.draft_content = revision.content

    # 4. Set page.draft_updated_at = now
    page.draft_updated_at = now

    # 5. Set page.draft_updated_by = user_id
    page.draft_updated_by = user_id

    # 6. Set page.updated_at = now
    page.updated_at = now

    # Do NOT change published_content or published_version

    # 7. flush + refresh
    await db.flush()
    await db.refresh(page)

    return page


# ---------------------------------------------------------------------------
# Publish workflow (Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.7)
# ---------------------------------------------------------------------------


async def publish_page(
    db: AsyncSession,
    page_key: str,
    user_id: uuid.UUID,
    note: str | None = None,
) -> EditorPage:
    """Publish a page: validate draft, copy to published_content, increment version, create revision.

    Steps:
    1. Load the page by key, raise 404 if not found
    2. Check page is not deleted (raise 410)
    3. Validate draft_content is not None (raise 422)
    4. Copy draft_content to published_content
    5. Increment published_version (or set to 1 if first publish)
    6. Set published_at = now, published_by = user_id
    7. Create a new EditorPageRevision
    8. Enforce revision cap: if count > 50, delete oldest and log
    9. flush + refresh

    Requirements: 4.2, 4.3, 5.1, 5.2, 5.7
    """
    # 1. Load the page
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    # 2. Check page is not deleted
    if page.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Page has been deleted.")

    # 3. Validate draft_content is not None
    if page.draft_content is None:
        raise HTTPException(
            status_code=422, detail="No draft content to publish."
        )

    now = datetime.now(timezone.utc)

    # 4. Copy draft_content to published_content
    page.published_content = page.draft_content

    # 5. Increment published_version (or set to 1 if first publish)
    if page.published_version is None:
        page.published_version = 1
    else:
        page.published_version += 1

    # 6. Set published_at and published_by
    page.published_at = now
    page.published_by = user_id
    page.updated_at = now

    # 7. Create a new EditorPageRevision
    revision = EditorPageRevision(
        page_key=page_key,
        version=page.published_version,
        content=page.draft_content,
        published_at=now,
        published_by=user_id,
        note=note,
    )
    db.add(revision)

    # 8. Enforce revision cap
    await _enforce_revision_cap(db, page_key)

    # 9. flush + refresh
    await db.flush()
    await db.refresh(page)
    invalidate_sitemap_cache()
    return page


async def _enforce_revision_cap(db: AsyncSession, page_key: str) -> None:
    """Prune oldest revisions when count exceeds REVISION_CAP per page.

    Deletes the oldest revision(s) and logs the pruning to audit.

    Requirements: 5.7
    """
    # Count revisions for this page
    count_result = await db.execute(
        select(func.count())
        .select_from(EditorPageRevision)
        .where(EditorPageRevision.page_key == page_key)
    )
    count = count_result.scalar() or 0

    if count <= REVISION_CAP:
        return

    # Find the oldest revisions that exceed the cap
    excess = count - REVISION_CAP
    oldest_query = (
        select(EditorPageRevision.id)
        .where(EditorPageRevision.page_key == page_key)
        .order_by(EditorPageRevision.created_at.asc())
        .limit(excess)
    )
    oldest_result = await db.execute(oldest_query)
    oldest_ids = [row[0] for row in oldest_result.all()]

    if oldest_ids:
        await db.execute(
            delete(EditorPageRevision).where(
                EditorPageRevision.id.in_(oldest_ids)
            )
        )
        logger.info(
            "Pruned %d oldest revision(s) for page '%s' (cap: %d)",
            len(oldest_ids),
            page_key,
            REVISION_CAP,
        )


# ---------------------------------------------------------------------------
# Preview token (Requirements: 4.1, 13.4)
# ---------------------------------------------------------------------------

# Preview token expiry duration
_PREVIEW_TOKEN_EXPIRY = timedelta(minutes=60)


def generate_preview_token(page_key: str, user_id: uuid.UUID, secret: str) -> str:
    """Generate a stateless JWT preview token with 60-minute expiry.

    Payload: page_key, user_id, exp (now + 60 minutes).
    Signed with HS256 using the provided secret.

    Requirements: 4.1, 13.4
    """
    now = datetime.now(timezone.utc)
    payload = {
        "page_key": page_key,
        "user_id": str(user_id),
        "exp": now + _PREVIEW_TOKEN_EXPIRY,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_preview_token(token: str, secret: str) -> dict | None:
    """Decode and validate a preview JWT. Returns payload dict or None if invalid/expired.

    Requirements: 4.1, 13.4
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Exception):
        return None


# ---------------------------------------------------------------------------
# Page settings update (Requirements: 6.1, 6.7, 6.8, 6.9, 6.10)
# ---------------------------------------------------------------------------


async def update_page_settings(
    db: AsyncSession,
    page_key: str,
    settings: PageSettingsRequest,
    user_id: uuid.UUID,
) -> EditorPage:
    """Update page settings (SEO, title, slug) with redirect creation on slug change.

    Steps:
    1. Load the page by key (raise 404 if not found)
    2. Check page is not deleted (raise 410)
    3. If settings.page_slug is provided and differs from current:
       a. If page_origin == 'hand-coded' → raise HTTPException(409)
       b. Validate the new slug (call validate_slug())
       c. Check new slug doesn't conflict with active pages
       d. Store old_slug = page.page_slug
       e. Update page.page_slug = settings.page_slug
       f. Create an EditorPageRedirect(from_slug=old_slug, to_slug_or_url=new_slug, ...)
       g. Detect and remove redirect cycles
    4. If settings.title is provided → update page.title
    5. If settings.noindex is provided → update page.noindex
    6. Update SEO fields in page.seo dict
    7. Set page.updated_at = now
    8. flush + refresh
    9. Return the updated page

    Requirements: 6.1, 6.7, 6.8, 6.9, 6.10
    """
    # 1. Load the page by key
    result = await db.execute(
        select(EditorPage).where(EditorPage.page_key == page_key)
    )
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found.")

    # 2. Check page is not deleted
    if page.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Page has been deleted.")

    now = datetime.now(timezone.utc)

    # Track whether sitemap-relevant fields change
    _invalidate_cache = False

    # 3. Handle slug change
    if settings.page_slug is not None and settings.page_slug != page.page_slug:
        _invalidate_cache = True
        new_slug = settings.page_slug

        # 3a. Reject slug change for hand-coded pages
        if page.page_origin == "hand-coded":
            raise HTTPException(
                status_code=409,
                detail="Cannot change slug of hand-coded pages",
            )

        # 3b. Validate the new slug
        validate_slug(new_slug)

        # 3c. Check new slug doesn't conflict with active pages
        conflict = await db.execute(
            select(EditorPage.page_key).where(
                and_(
                    EditorPage.page_slug == new_slug,
                    EditorPage.deleted_at.is_(None),
                    EditorPage.page_key != page_key,
                )
            )
        )
        if conflict.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Slug '{new_slug}' is already in use by another page.",
            )

        # 3d. Store old slug
        old_slug = page.page_slug

        # 3e. Update page slug
        page.page_slug = new_slug

        # 3f. Create 301 redirect from old to new
        redirect = EditorPageRedirect(
            from_slug=old_slug,
            to_slug_or_url=new_slug,
            status_code=301,
            created_by=user_id,
        )
        db.add(redirect)

        # 3g. Detect and remove redirect cycles
        # Check if any active redirect points from new_slug back to old_slug
        # or self-redirects (from_slug == to_slug_or_url)
        cycle_result = await db.execute(
            select(EditorPageRedirect).where(
                and_(
                    EditorPageRedirect.deleted_at.is_(None),
                    or_(
                        # Redirect from new_slug pointing back to old_slug (cycle)
                        and_(
                            EditorPageRedirect.from_slug == new_slug,
                            EditorPageRedirect.to_slug_or_url == old_slug,
                        ),
                        # Self-redirect: from_slug == to_slug_or_url
                        and_(
                            EditorPageRedirect.from_slug == EditorPageRedirect.to_slug_or_url,
                        ),
                    ),
                )
            )
        )
        cycle_redirects = list(cycle_result.scalars().all())
        for cycle_redirect in cycle_redirects:
            cycle_redirect.deleted_at = now

    # 4. Update title if provided
    if settings.title is not None:
        page.title = settings.title

    # 5. Update noindex if provided
    if settings.noindex is not None:
        if settings.noindex != page.noindex:
            _invalidate_cache = True
        page.noindex = settings.noindex

    # 6. Update SEO fields in page.seo dict
    seo = dict(page.seo) if page.seo else {}
    seo_fields = {
        "meta_title": settings.meta_title,
        "meta_description": settings.meta_description,
        "canonical": settings.canonical,
        "og_image": settings.og_image,
        "og_type": settings.og_type,
        "twitter_card": settings.twitter_card,
        "json_ld": settings.json_ld,
    }
    for field_name, field_value in seo_fields.items():
        if field_value is not None:
            seo[field_name] = field_value
    page.seo = seo

    # 7. Set updated_at
    page.updated_at = now

    # 8. flush + refresh
    await db.flush()
    await db.refresh(page)

    # Invalidate sitemap/robots cache if slug or noindex changed
    if _invalidate_cache:
        invalidate_sitemap_cache()

    # 9. Return the updated page
    return page


# ---------------------------------------------------------------------------
# Sitemap and Robots.txt generation (Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8)
# ---------------------------------------------------------------------------


def invalidate_sitemap_cache() -> None:
    """Invalidate the in-memory sitemap and robots.txt cache.

    Called on publish, create, delete, undelete, slug change, and noindex change.

    Requirements: 9.6
    """
    _sitemap_robots_cache.clear()


async def generate_sitemap(db: AsyncSession, host: str) -> str:
    """Generate XML sitemap with published, non-deleted, non-noindex pages sorted by slug.

    Includes both hand-coded and editor-created pages that have published content.
    Uses an in-memory cache with 5-minute TTL.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.8
    """
    # Check cache
    cache_key = f"sitemap:{host}"
    cached = _sitemap_robots_cache.get(cache_key)
    if cached is not None:
        content, timestamp = cached
        if time.time() - timestamp < _SITEMAP_CACHE_TTL:
            return content

    # Query published, non-deleted, non-noindex pages sorted by slug
    stmt = (
        select(EditorPage)
        .where(
            and_(
                EditorPage.published_content.isnot(None),
                EditorPage.deleted_at.is_(None),
                EditorPage.noindex == False,  # noqa: E712
            )
        )
        .order_by(EditorPage.page_slug.asc())
    )

    result = await db.execute(stmt)
    pages = result.scalars().all()

    # Build XML sitemap
    urls = []
    for page in pages:
        lastmod = ""
        if page.published_at:
            lastmod = page.published_at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        urls.append(
            f"  <url>\n"
            f"    <loc>https://{host}{page.page_slug}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"  </url>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n"
        "</urlset>"
    )

    # Cache the result
    _sitemap_robots_cache[cache_key] = (xml, time.time())

    return xml


async def generate_robots(db: AsyncSession, host: str) -> str:
    """Generate robots.txt with static base + dynamic Allow/Disallow directives.

    Static base includes User-agent and general Disallow rules.
    Dynamic section adds Allow directives for published, non-noindex editor-created pages,
    and Disallow directives for noindex pages.
    Appends Sitemap URL.

    Requirements: 9.1, 9.5, 9.6
    """
    # Check cache
    cache_key = f"robots:{host}"
    cached = _sitemap_robots_cache.get(cache_key)
    if cached is not None:
        content, timestamp = cached
        if time.time() - timestamp < _SITEMAP_CACHE_TTL:
            return content

    # Static base
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
    ]

    # Query published, non-noindex, editor-created pages for Allow directives
    allow_stmt = (
        select(EditorPage.page_slug)
        .where(
            and_(
                EditorPage.published_content.isnot(None),
                EditorPage.deleted_at.is_(None),
                EditorPage.noindex == False,  # noqa: E712
                EditorPage.page_origin == "editor-created",
            )
        )
        .order_by(EditorPage.page_slug.asc())
    )
    allow_result = await db.execute(allow_stmt)
    allow_slugs = [row[0] for row in allow_result.all()]

    if allow_slugs:
        lines.append("# Published editor pages")
        for slug in allow_slugs:
            lines.append(f"Allow: {slug}")
        lines.append("")

    # Query noindex pages (non-deleted) for Disallow directives
    noindex_stmt = (
        select(EditorPage.page_slug)
        .where(
            and_(
                EditorPage.deleted_at.is_(None),
                EditorPage.noindex == True,  # noqa: E712
            )
        )
        .order_by(EditorPage.page_slug.asc())
    )
    noindex_result = await db.execute(noindex_stmt)
    noindex_slugs = [row[0] for row in noindex_result.all()]

    if noindex_slugs:
        lines.append("# Noindex pages")
        for slug in noindex_slugs:
            lines.append(f"Disallow: {slug}")
        lines.append("")

    # Append sitemap URL
    lines.append(f"Sitemap: https://{host}/sitemap.xml")

    robots_txt = "\n".join(lines)

    # Cache the result
    _sitemap_robots_cache[cache_key] = (robots_txt, time.time())

    return robots_txt


# ---------------------------------------------------------------------------
# Redirect service functions (Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7)
# ---------------------------------------------------------------------------


async def list_redirects(
    db: AsyncSession,
    include_deleted: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[EditorPageRedirect], int]:
    """List redirects, paginated, optionally including soft-deleted.

    Requirements: 11.1, 11.3
    """
    conditions = []
    if not include_deleted:
        conditions.append(EditorPageRedirect.deleted_at.is_(None))

    base_where = and_(*conditions) if conditions else True

    # Count total
    count_stmt = (
        select(func.count())
        .select_from(EditorPageRedirect)
        .where(base_where)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # Fetch redirects ordered by created_at DESC
    query = (
        select(EditorPageRedirect)
        .where(base_where)
        .order_by(EditorPageRedirect.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    redirects = list(result.scalars().all())

    return redirects, total


async def create_redirect(
    db: AsyncSession,
    from_slug: str,
    to_slug_or_url: str,
    status_code: int,
    user_id: uuid.UUID,
) -> EditorPageRedirect:
    """Create a redirect. Validates from_slug doesn't match active page, checks for cycles.

    Steps:
    1. Validate from_slug format (call validate_slug)
    2. Check from_slug doesn't match an active page → raise 409 if match
    3. Check from_slug doesn't already have an active redirect → raise 409 if exists
    4. Check for cycles: if to_slug_or_url matches from_slug → raise 422 "Self-redirect not allowed"
    5. Create EditorPageRedirect row
    6. flush + refresh
    7. Return the redirect

    Requirements: 11.1, 11.2, 11.5, 11.6
    """
    # 1. Validate from_slug format
    validate_slug(from_slug)

    # 2. Check from_slug doesn't match an active page
    page_conflict = await db.execute(
        select(EditorPage.page_key).where(
            and_(
                EditorPage.page_slug == from_slug,
                EditorPage.deleted_at.is_(None),
            )
        )
    )
    if page_conflict.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot create redirect: slug '{from_slug}' is used by an active page.",
        )

    # 3. Check from_slug doesn't already have an active redirect
    existing_redirect = await db.execute(
        select(EditorPageRedirect.id).where(
            and_(
                EditorPageRedirect.from_slug == from_slug,
                EditorPageRedirect.deleted_at.is_(None),
            )
        )
    )
    if existing_redirect.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An active redirect from '{from_slug}' already exists.",
        )

    # 4. Check for self-redirect cycle
    if to_slug_or_url == from_slug:
        raise HTTPException(
            status_code=422,
            detail="Self-redirect not allowed.",
        )

    # 5. Create EditorPageRedirect row
    redirect = EditorPageRedirect(
        from_slug=from_slug,
        to_slug_or_url=to_slug_or_url,
        status_code=status_code,
        created_by=user_id,
    )
    db.add(redirect)

    # 6. flush + refresh
    await db.flush()
    await db.refresh(redirect)

    # 7. Return the redirect
    return redirect


async def soft_delete_redirect(
    db: AsyncSession,
    redirect_id: uuid.UUID,
) -> EditorPageRedirect:
    """Soft-delete a redirect by setting deleted_at.

    Requirements: 11.3, 11.7
    """
    result = await db.execute(
        select(EditorPageRedirect).where(EditorPageRedirect.id == redirect_id)
    )
    redirect = result.scalar_one_or_none()
    if redirect is None:
        raise HTTPException(status_code=404, detail="Redirect not found.")

    if redirect.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Redirect is already deleted.")

    now = datetime.now(timezone.utc)
    redirect.deleted_at = now

    await db.flush()
    await db.refresh(redirect)
    return redirect


async def resolve_redirect(
    db: AsyncSession,
    slug: str,
) -> EditorPageRedirect | None:
    """Lookup active redirect by from_slug (one hop max). Returns None if not found.

    Only one hop — do NOT follow chains. Soft-deleted redirects are excluded.

    Requirements: 11.4, 11.5, 11.7
    """
    result = await db.execute(
        select(EditorPageRedirect).where(
            and_(
                EditorPageRedirect.from_slug == slug,
                EditorPageRedirect.deleted_at.is_(None),
            )
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Page registry sync (Requirements: 14.2, 14.3, 14.8)
# ---------------------------------------------------------------------------

HAND_CODED_PAGES = [
    {"page_key": "landing", "page_slug": "/", "title": "OraInvoice - Trade Business Management"},
    {"page_key": "workshop", "page_slug": "/workshop", "title": "Workshop Management"},
    {"page_key": "trades", "page_slug": "/trades", "title": "Trades & Services"},
    {"page_key": "privacy", "page_slug": "/privacy", "title": "Privacy Policy"},
]


async def sync_registry(db: AsyncSession) -> int:
    """Sync hand-coded page registry to the database.

    Auto-creates empty EditorPage rows for hand-coded pages not yet in DB.
    Returns the number of pages created.

    Requirements: 14.2, 14.3, 14.8
    """
    created = 0

    for entry in HAND_CODED_PAGES:
        # Check if page_key already exists in editor_pages
        existing = await db.execute(
            select(EditorPage.page_key).where(
                EditorPage.page_key == entry["page_key"]
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        # Create a new EditorPage for this hand-coded page
        page = EditorPage(
            page_key=entry["page_key"],
            page_origin="hand-coded",
            page_slug=entry["page_slug"],
            title=entry["title"],
            draft_content=None,
            published_content=None,
            noindex=False,
        )
        db.add(page)
        created += 1

    if created > 0:
        await db.flush()

    logger.info("sync_registry: created %d hand-coded page(s)", created)
    return created


# ---------------------------------------------------------------------------
# Concurrent editing advisory lock (Redis) (Requirements: 3.12)
# ---------------------------------------------------------------------------

# Lock TTL: 5 minutes (300 seconds)
_EDITOR_LOCK_TTL = 300


async def acquire_editor_lock(
    redis: Redis,
    page_key: str,
    user_id: uuid.UUID,
    user_email: str,
) -> dict | None:
    """Acquire advisory editing lock. Returns existing lock holder info if different user, None if acquired.

    Logic:
    1. Build the Redis key: page_editor:lock:{page_key}
    2. Try to GET the existing value
    3. If exists and user_id differs → return the existing lock holder info
    4. If exists and same user_id → refresh TTL, return None (lock acquired/refreshed)
    5. If not exists → SET with NX and EX=300, return None (lock acquired)

    Requirements: 3.12
    """
    key = f"page_editor:lock:{page_key}"

    # Check for existing lock
    existing = await redis.get(key)

    if existing is not None:
        lock_data = json.loads(existing)
        existing_user_id = lock_data.get("user_id", "")

        if existing_user_id != str(user_id):
            # Different user holds the lock — return their info
            return {
                "user_email": lock_data.get("user_email", ""),
                "opened_at": lock_data.get("opened_at", ""),
            }

        # Same user — refresh TTL
        await redis.expire(key, _EDITOR_LOCK_TTL)
        return None

    # No existing lock — set with NX and TTL
    lock_value = json.dumps({
        "user_id": str(user_id),
        "user_email": user_email,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    })
    await redis.set(key, lock_value, nx=True, ex=_EDITOR_LOCK_TTL)
    return None


async def refresh_editor_lock(
    redis: Redis,
    page_key: str,
    user_id: uuid.UUID,
) -> None:
    """Refresh the TTL on an existing editor lock (called on auto-save).

    Only refreshes if the lock is owned by the given user_id.

    Requirements: 3.12
    """
    key = f"page_editor:lock:{page_key}"

    existing = await redis.get(key)
    if existing is None:
        return

    lock_data = json.loads(existing)
    if lock_data.get("user_id") == str(user_id):
        await redis.expire(key, _EDITOR_LOCK_TTL)


async def release_editor_lock(
    redis: Redis,
    page_key: str,
    user_id: uuid.UUID,
) -> None:
    """Release the editor lock if owned by the current user.

    Only deletes the key if the lock belongs to the given user_id.
    Does nothing if the lock doesn't exist or belongs to another user.

    Requirements: 3.12
    """
    key = f"page_editor:lock:{page_key}"

    existing = await redis.get(key)
    if existing is None:
        return

    lock_data = json.loads(existing)
    if lock_data.get("user_id") == str(user_id):
        await redis.delete(key)
