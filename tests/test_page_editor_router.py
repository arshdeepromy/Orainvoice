"""Integration tests for the page_editor admin + public routers.

Covers:
  - Access control (403 for non-global_admin)
  - Public resolve endpoint (page found, redirect, 404)
  - Sitemap and robots.txt output
  - Preview token generation + consumption

These tests stand up a minimal FastAPI app with the editor's two routers
mounted, the DB dependency mocked, and the auth state injected via a
middleware so we can flip roles per-test.

Requirements: 4.1, 7.2, 9.1, 13.2, 13.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Ensure SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.modules.page_editor.router import router as admin_router, public_router


USER_ID = uuid.uuid4()
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _fake_db():
    return AsyncMock()


def _fake_redis():
    """Return an AsyncMock Redis with no-op lock methods."""
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    redis.delete.return_value = 1
    return redis


def _make_app(role: str = "global_admin", user_id: uuid.UUID = USER_ID) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_db_session] = _fake_db
    app.dependency_overrides[get_redis] = _fake_redis

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = str(user_id) if user_id else None
        request.state.role = role
        request.state.email = "tester@example.com"
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    # Admin router is mounted at /api/v2/admin/page-editor in production
    app.include_router(admin_router, prefix="/api/v2/admin/page-editor")
    # Public router includes its own absolute paths in @route decorators
    app.include_router(public_router)
    return app


# ---------------------------------------------------------------------------
# Access control (Requirement 13.2, 13.3)
# ---------------------------------------------------------------------------


@patch("app.modules.page_editor.router._audit_out_of_band", new=AsyncMock())
def test_admin_endpoint_denies_non_global_admin():
    """A non-global_admin role must be rejected with 403 by the dependency guard."""
    app = _make_app(role="org_admin")
    client = TestClient(app)
    res = client.get("/api/v2/admin/page-editor/pages")
    assert res.status_code == 403


@patch("app.modules.page_editor.router._audit_out_of_band", new=AsyncMock())
def test_admin_endpoint_denies_anonymous_401():
    """Missing user state must yield 401 from the guard."""
    app = _make_app(role="global_admin", user_id=None)
    # The guard reads user_id from state; if missing → 401
    # Override middleware to clear state.user_id
    @app.middleware("http")
    async def clear_user(request: Request, call_next):
        request.state.user_id = None
        request.state.role = None
        return await call_next(request)

    client = TestClient(app)
    res = client.get("/api/v2/admin/page-editor/pages")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Public resolve endpoint (Requirement 7.2)
# ---------------------------------------------------------------------------


def _make_page_mock(
    *,
    page_key: str = "demo",
    page_slug: str = "/demo",
    page_origin: str = "editor-created",
    title: str = "Demo Page",
    published_content: dict | None = None,
    seo: dict | None = None,
    noindex: bool = False,
):
    page = MagicMock()
    page.page_key = page_key
    page.page_slug = page_slug
    page.page_origin = page_origin
    page.title = title
    page.published_content = published_content or {
        "content": [],
        "root": {"props": {}},
    }
    page.seo = seo or {}
    page.noindex = noindex
    page.deleted_at = None
    return page


def test_public_resolve_returns_page():
    app = _make_app()
    page = _make_page_mock()

    with patch(
        "app.modules.page_editor.router.page_svc.resolve_redirect",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.modules.page_editor.router.page_svc.get_page_by_slug",
        new=AsyncMock(return_value=page),
    ):
        client = TestClient(app)
        res = client.get("/api/v2/public/pages/resolve", params={"slug": "/demo"})

    assert res.status_code == 200
    body = res.json()
    assert body.get("type") == "page"
    assert body.get("data", {}).get("page_key") == "demo"


def test_public_resolve_returns_redirect():
    app = _make_app()
    redirect = MagicMock()
    redirect.to_slug_or_url = "/new-slug"
    redirect.status_code = 301

    with patch(
        "app.modules.page_editor.router.page_svc.resolve_redirect",
        new=AsyncMock(return_value=redirect),
    ):
        client = TestClient(app)
        res = client.get("/api/v2/public/pages/resolve", params={"slug": "/old"})

    assert res.status_code == 200
    body = res.json()
    assert body.get("type") == "redirect"
    assert body.get("status_code") == 301
    assert body.get("target") == "/new-slug"


def test_public_resolve_returns_404_when_no_match():
    app = _make_app()
    with patch(
        "app.modules.page_editor.router.page_svc.resolve_redirect",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.modules.page_editor.router.page_svc.get_page_by_slug",
        new=AsyncMock(return_value=None),
    ):
        client = TestClient(app)
        res = client.get("/api/v2/public/pages/resolve", params={"slug": "/nope"})
    assert res.status_code == 404


def test_public_resolve_returns_404_when_page_unpublished():
    """A page that exists but has no published_content should still 404 publicly."""
    app = _make_app()
    page = _make_page_mock()
    page.published_content = None
    with patch(
        "app.modules.page_editor.router.page_svc.resolve_redirect",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.modules.page_editor.router.page_svc.get_page_by_slug",
        new=AsyncMock(return_value=page),
    ):
        client = TestClient(app)
        res = client.get("/api/v2/public/pages/resolve", params={"slug": "/demo"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Sitemap + robots (Requirement 9.1)
# ---------------------------------------------------------------------------


def test_sitemap_endpoint_returns_xml():
    app = _make_app()
    body_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    )
    with patch(
        "app.modules.page_editor.router.page_svc.generate_sitemap",
        new=AsyncMock(return_value=body_xml),
    ):
        client = TestClient(app)
        res = client.get("/sitemap.xml")
    assert res.status_code == 200
    assert "application/xml" in res.headers.get("content-type", "")
    assert res.text == body_xml


def test_robots_endpoint_returns_text_plain():
    app = _make_app()
    body_txt = "User-agent: *\nAllow: /\nSitemap: https://example/sitemap.xml\n"
    with patch(
        "app.modules.page_editor.router.page_svc.generate_robots",
        new=AsyncMock(return_value=body_txt),
    ):
        client = TestClient(app)
        res = client.get("/robots.txt")
    assert res.status_code == 200
    assert "text/plain" in res.headers.get("content-type", "")
    assert res.text == body_txt


# ---------------------------------------------------------------------------
# Preview token generation + consumption (Requirement 4.1, 7.6)
# ---------------------------------------------------------------------------


def test_preview_invalid_token_returns_401():
    app = _make_app()
    with patch(
        "app.modules.page_editor.router.page_svc.verify_preview_token",
        return_value=None,
    ):
        client = TestClient(app)
        res = client.get("/api/v2/public/pages/preview/garbage")
    assert res.status_code == 401


def test_preview_valid_token_returns_draft_with_noindex_header():
    app = _make_app()
    page = _make_page_mock()
    page.draft_content = {"content": [{"type": "Heading", "props": {"text": "Draft"}}], "root": {"props": {}}}

    with patch(
        "app.modules.page_editor.router.page_svc.verify_preview_token",
        return_value={"page_key": "demo", "user_id": str(USER_ID)},
    ), patch(
        "app.modules.page_editor.router.page_svc.get_page",
        new=AsyncMock(return_value=page),
    ):
        client = TestClient(app)
        res = client.get("/api/v2/public/pages/preview/valid-token")

    assert res.status_code == 200
    assert "noindex" in res.headers.get("x-robots-tag", "").lower()
    body = res.json()
    # Preview always serves draft content and is always noindex
    assert body.get("noindex") is True
    assert body.get("page_key") == "demo"
