"""Unit tests for sitemap and robots.txt generation.

Tests cover:
- generate_sitemap() includes only published, non-deleted, non-noindex pages
- generate_sitemap() sorts by slug
- generate_sitemap() includes both hand-coded and editor-created pages
- generate_sitemap() uses ISO 8601 lastmod from published_at
- generate_robots() includes static base with Allow: /
- generate_robots() adds Allow directives for published editor-created pages
- generate_robots() adds Disallow directives for noindex pages
- generate_robots() appends Sitemap URL
- In-memory cache returns cached content within TTL
- invalidate_sitemap_cache() clears the cache

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.page_editor.service import (
    _sitemap_robots_cache,
    _SITEMAP_CACHE_TTL,
    generate_robots,
    generate_sitemap,
    invalidate_sitemap_cache,
)


def _make_page_row(
    page_key: str,
    page_slug: str,
    page_origin: str = "editor-created",
    published_content: dict | None = None,
    published_at: datetime | None = None,
    noindex: bool = False,
    deleted_at: datetime | None = None,
):
    """Create a mock EditorPage object for sitemap tests."""
    page = MagicMock()
    page.page_key = page_key
    page.page_slug = page_slug
    page.page_origin = page_origin
    page.published_content = published_content
    page.published_at = published_at
    page.noindex = noindex
    page.deleted_at = deleted_at
    return page


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the sitemap cache before and after each test."""
    _sitemap_robots_cache.clear()
    yield
    _sitemap_robots_cache.clear()


# ---------------------------------------------------------------------------
# generate_sitemap() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_sitemap_includes_published_pages():
    """Sitemap should include published, non-deleted, non-noindex pages."""
    db = AsyncMock()
    published_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    pages = [
        _make_page_row(
            page_key="about",
            page_slug="/about",
            published_content={"content": []},
            published_at=published_at,
        ),
        _make_page_row(
            page_key="services",
            page_slug="/services",
            published_content={"content": []},
            published_at=published_at,
        ),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = pages
    db.execute.return_value = result_mock

    xml = await generate_sitemap(db, "example.com")

    assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
    assert "<urlset" in xml
    assert "<loc>https://example.com/about</loc>" in xml
    assert "<loc>https://example.com/services</loc>" in xml
    assert "<lastmod>2025-06-01T12:00:00+00:00</lastmod>" in xml


@pytest.mark.asyncio
async def test_generate_sitemap_sorted_by_slug():
    """Sitemap pages should be sorted by slug (query uses ORDER BY)."""
    db = AsyncMock()
    published_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Pages returned in slug order (as the query would return them)
    pages = [
        _make_page_row(
            page_key="about",
            page_slug="/about",
            published_content={"content": []},
            published_at=published_at,
        ),
        _make_page_row(
            page_key="contact",
            page_slug="/contact",
            published_content={"content": []},
            published_at=published_at,
        ),
        _make_page_row(
            page_key="services",
            page_slug="/services",
            published_content={"content": []},
            published_at=published_at,
        ),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = pages
    db.execute.return_value = result_mock

    xml = await generate_sitemap(db, "example.com")

    # Verify order in output
    about_pos = xml.index("/about")
    contact_pos = xml.index("/contact")
    services_pos = xml.index("/services")
    assert about_pos < contact_pos < services_pos


@pytest.mark.asyncio
async def test_generate_sitemap_includes_hand_coded_pages():
    """Sitemap should include hand-coded pages with published content."""
    db = AsyncMock()
    published_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    pages = [
        _make_page_row(
            page_key="landing",
            page_slug="/",
            page_origin="hand-coded",
            published_content={"content": []},
            published_at=published_at,
        ),
        _make_page_row(
            page_key="new-page",
            page_slug="/new-page",
            page_origin="editor-created",
            published_content={"content": []},
            published_at=published_at,
        ),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = pages
    db.execute.return_value = result_mock

    xml = await generate_sitemap(db, "example.com")

    assert "<loc>https://example.com/</loc>" in xml
    assert "<loc>https://example.com/new-page</loc>" in xml


@pytest.mark.asyncio
async def test_generate_sitemap_empty_when_no_pages():
    """Sitemap should be valid XML even with no pages."""
    db = AsyncMock()

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute.return_value = result_mock

    xml = await generate_sitemap(db, "example.com")

    assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
    assert "<urlset" in xml
    assert "</urlset>" in xml
    assert "<url>" not in xml


@pytest.mark.asyncio
async def test_generate_sitemap_handles_missing_published_at():
    """Sitemap should handle pages with no published_at (empty lastmod)."""
    db = AsyncMock()

    pages = [
        _make_page_row(
            page_key="about",
            page_slug="/about",
            published_content={"content": []},
            published_at=None,
        ),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = pages
    db.execute.return_value = result_mock

    xml = await generate_sitemap(db, "example.com")

    assert "<loc>https://example.com/about</loc>" in xml
    assert "<lastmod></lastmod>" in xml


# ---------------------------------------------------------------------------
# generate_robots() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_robots_static_base():
    """Robots.txt should start with User-agent and Allow: /."""
    db = AsyncMock()

    # Allow query returns no slugs
    allow_result = MagicMock()
    allow_result.all.return_value = []
    # Noindex query returns no slugs
    noindex_result = MagicMock()
    noindex_result.all.return_value = []

    db.execute.side_effect = [allow_result, noindex_result]

    robots = await generate_robots(db, "example.com")

    assert "User-agent: *" in robots
    assert "Allow: /" in robots
    assert "Sitemap: https://example.com/sitemap.xml" in robots


@pytest.mark.asyncio
async def test_generate_robots_allow_directives():
    """Robots.txt should include Allow directives for published editor-created pages."""
    db = AsyncMock()

    # Allow query returns slugs
    allow_result = MagicMock()
    allow_result.all.return_value = [("/about",), ("/services",)]
    # Noindex query returns no slugs
    noindex_result = MagicMock()
    noindex_result.all.return_value = []

    db.execute.side_effect = [allow_result, noindex_result]

    robots = await generate_robots(db, "example.com")

    assert "Allow: /about" in robots
    assert "Allow: /services" in robots
    assert "# Published editor pages" in robots


@pytest.mark.asyncio
async def test_generate_robots_disallow_noindex_pages():
    """Robots.txt should include Disallow directives for noindex pages."""
    db = AsyncMock()

    # Allow query returns no slugs
    allow_result = MagicMock()
    allow_result.all.return_value = []
    # Noindex query returns slugs
    noindex_result = MagicMock()
    noindex_result.all.return_value = [("/hidden-page",), ("/internal",)]

    db.execute.side_effect = [allow_result, noindex_result]

    robots = await generate_robots(db, "example.com")

    assert "Disallow: /hidden-page" in robots
    assert "Disallow: /internal" in robots
    assert "# Noindex pages" in robots


@pytest.mark.asyncio
async def test_generate_robots_sitemap_url():
    """Robots.txt should always include the Sitemap URL."""
    db = AsyncMock()

    allow_result = MagicMock()
    allow_result.all.return_value = []
    noindex_result = MagicMock()
    noindex_result.all.return_value = []

    db.execute.side_effect = [allow_result, noindex_result]

    robots = await generate_robots(db, "mysite.co.nz")

    assert "Sitemap: https://mysite.co.nz/sitemap.xml" in robots


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_sitemap_uses_cache():
    """Second call should return cached content without querying DB."""
    db = AsyncMock()
    published_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    pages = [
        _make_page_row(
            page_key="about",
            page_slug="/about",
            published_content={"content": []},
            published_at=published_at,
        ),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = pages
    db.execute.return_value = result_mock

    # First call populates cache
    xml1 = await generate_sitemap(db, "example.com")
    assert db.execute.call_count == 1

    # Second call should use cache (no additional DB call)
    xml2 = await generate_sitemap(db, "example.com")
    assert db.execute.call_count == 1
    assert xml1 == xml2


@pytest.mark.asyncio
async def test_generate_robots_uses_cache():
    """Second call should return cached content without querying DB."""
    db = AsyncMock()

    allow_result = MagicMock()
    allow_result.all.return_value = [("/about",)]
    noindex_result = MagicMock()
    noindex_result.all.return_value = []

    db.execute.side_effect = [allow_result, noindex_result]

    # First call populates cache
    robots1 = await generate_robots(db, "example.com")
    assert db.execute.call_count == 2  # allow + noindex queries

    # Second call should use cache
    robots2 = await generate_robots(db, "example.com")
    assert db.execute.call_count == 2  # no additional calls
    assert robots1 == robots2


def test_invalidate_sitemap_cache_clears_all():
    """invalidate_sitemap_cache() should clear all cached entries."""
    _sitemap_robots_cache["sitemap:example.com"] = ("<xml/>", time.time())
    _sitemap_robots_cache["robots:example.com"] = ("User-agent: *", time.time())

    assert len(_sitemap_robots_cache) == 2

    invalidate_sitemap_cache()

    assert len(_sitemap_robots_cache) == 0


@pytest.mark.asyncio
async def test_cache_expires_after_ttl():
    """Cache should expire after TTL and re-query the database."""
    db = AsyncMock()

    pages = [
        _make_page_row(
            page_key="about",
            page_slug="/about",
            published_content={"content": []},
            published_at=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        ),
    ]

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = pages
    db.execute.return_value = result_mock

    # Manually insert an expired cache entry
    _sitemap_robots_cache["sitemap:example.com"] = (
        "<old-xml/>",
        time.time() - _SITEMAP_CACHE_TTL - 1,
    )

    # Should bypass expired cache and re-query
    xml = await generate_sitemap(db, "example.com")

    assert "<old-xml/>" not in xml
    assert "<loc>https://example.com/about</loc>" in xml
    assert db.execute.call_count == 1
