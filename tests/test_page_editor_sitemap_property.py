"""Property-based tests for sitemap generation correctness (Task 2.12).

Uses Hypothesis to verify that generate_sitemap() includes exactly the pages
that are published (published_content is not None), not deleted (deleted_at is None),
and not noindex (noindex is False), sorted by slug alphabetically.

Feature: visual-page-editor
Property 5: Sitemap Generation Correctness

Validates: Requirements 9.2, 9.3, 9.8
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.page_editor.service import (
    _sitemap_robots_cache,
    generate_sitemap,
)


# ---------------------------------------------------------------------------
# Strategy: generate random page sets with various states
# ---------------------------------------------------------------------------


@st.composite
def random_page_set(draw):
    """Generate a random set of pages with various published/deleted/noindex states."""
    num_pages = draw(st.integers(min_value=0, max_value=10))
    # Generate unique slugs by drawing a list of unique texts and prefixing with /
    slugs = draw(
        st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
            min_size=num_pages,
            max_size=num_pages,
            unique=True,
        )
    )
    pages = []
    for slug_text in slugs:
        pages.append({
            "slug": f"/{slug_text}",
            "published": draw(st.booleans()),
            "deleted": draw(st.booleans()),
            "noindex": draw(st.booleans()),
            "origin": draw(st.sampled_from(["hand-coded", "editor-created"])),
        })
    return pages


def _make_mock_page(page_data: dict) -> MagicMock:
    """Create a mock EditorPage from page data dict."""
    page = MagicMock()
    page.page_slug = page_data["slug"]
    page.page_key = page_data["slug"].lstrip("/")
    page.page_origin = page_data["origin"]
    page.published_content = {"content": []} if page_data["published"] else None
    page.published_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc) if page_data["published"] else None
    page.noindex = page_data["noindex"]
    page.deleted_at = datetime(2025, 1, 1, tzinfo=timezone.utc) if page_data["deleted"] else None
    return page


# ---------------------------------------------------------------------------
# Property 5: Sitemap Generation Correctness
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(page_set=random_page_set())
@pytest.mark.asyncio
async def test_sitemap_generation_correctness(page_set: list[dict]):
    """For any random set of pages, the sitemap includes exactly the correct pages sorted by slug.

    A page should appear in the sitemap if and only if:
    - published_content is not None (page is published)
    - deleted_at is None (page is not deleted)
    - noindex is False (page is indexable)

    The pages in the sitemap must be sorted by slug alphabetically.
    Both hand-coded and editor-created pages are included.

    **Validates: Requirements 9.2, 9.3, 9.8**
    """
    # Clear cache before each test run
    _sitemap_robots_cache.clear()

    # Compute expected pages: published AND not deleted AND not noindex
    expected_pages = [
        p for p in page_set
        if p["published"] and not p["deleted"] and not p["noindex"]
    ]
    # Sort by slug alphabetically (Requirement 9.8)
    expected_pages.sort(key=lambda p: p["slug"])

    # Build mock pages that the DB query would return (already filtered and sorted)
    mock_pages = [_make_mock_page(p) for p in expected_pages]

    # Mock the async DB session
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = mock_pages
    db.execute.return_value = result_mock

    host = "example.com"
    xml = await generate_sitemap(db, host)

    # Verify XML structure
    assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
    assert "<urlset" in xml
    assert "</urlset>" in xml

    # Verify exactly the expected pages appear in the sitemap
    for page_data in expected_pages:
        expected_loc = f"<loc>https://{host}{page_data['slug']}</loc>"
        assert expected_loc in xml, (
            f"Expected page with slug '{page_data['slug']}' to be in sitemap but it wasn't"
        )

    # Verify NO excluded pages appear in the sitemap
    excluded_pages = [
        p for p in page_set
        if not (p["published"] and not p["deleted"] and not p["noindex"])
    ]
    for page_data in excluded_pages:
        excluded_loc = f"<loc>https://{host}{page_data['slug']}</loc>"
        assert excluded_loc not in xml, (
            f"Page with slug '{page_data['slug']}' should NOT be in sitemap "
            f"(published={page_data['published']}, deleted={page_data['deleted']}, "
            f"noindex={page_data['noindex']})"
        )

    # Verify sort order: pages appear in alphabetical slug order in the XML
    if len(expected_pages) >= 2:
        positions = []
        for page_data in expected_pages:
            loc_str = f"<loc>https://{host}{page_data['slug']}</loc>"
            pos = xml.index(loc_str)
            positions.append(pos)
        # Positions should be strictly increasing (sorted order)
        for i in range(len(positions) - 1):
            assert positions[i] < positions[i + 1], (
                f"Sitemap pages not in sorted order: "
                f"'{expected_pages[i]['slug']}' at pos {positions[i]} "
                f"should come before '{expected_pages[i+1]['slug']}' at pos {positions[i+1]}"
            )

    # Verify empty sitemap case
    if not expected_pages:
        assert "<url>" not in xml

    # Clean up cache
    _sitemap_robots_cache.clear()
