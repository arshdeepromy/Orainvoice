"""Unit tests for sync_registry service function.

Tests cover:
- Creates all hand-coded pages when DB is empty
- Skips pages that already exist in DB
- Returns correct count of created pages
- Does not call flush when no pages are created
- Calls flush when pages are created

Requirements: 14.2, 14.3, 14.8
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.page_editor.service import HAND_CODED_PAGES, sync_registry


@pytest.fixture
def db_mock():
    """Create a mock AsyncSession."""
    return AsyncMock()


def _make_execute_side_effect(existing_keys: set[str]):
    """Create a side effect for db.execute that returns None for missing keys."""
    async def side_effect(stmt):
        result_mock = MagicMock()
        # Check if any of the existing keys match the query
        # The query checks page_key, so we inspect the statement
        # We'll use a simple approach: track call count and match to HAND_CODED_PAGES order
        return result_mock
    return side_effect


@pytest.mark.asyncio
async def test_sync_registry_creates_all_pages_when_empty(db_mock):
    """Should create all 4 hand-coded pages when none exist in DB."""
    # All queries return None (no existing pages)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db_mock.execute.return_value = result_mock

    count = await sync_registry(db_mock)

    assert count == 4
    assert db_mock.add.call_count == 4
    db_mock.flush.assert_called_once()


@pytest.mark.asyncio
async def test_sync_registry_skips_existing_pages(db_mock):
    """Should skip pages that already exist and only create missing ones."""
    existing_keys = {"landing", "privacy"}

    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        result_mock = MagicMock()
        page_key = HAND_CODED_PAGES[call_count]["page_key"]
        if page_key in existing_keys:
            result_mock.scalar_one_or_none.return_value = page_key
        else:
            result_mock.scalar_one_or_none.return_value = None
        call_count += 1
        return result_mock

    db_mock.execute.side_effect = execute_side_effect

    count = await sync_registry(db_mock)

    assert count == 2
    assert db_mock.add.call_count == 2
    db_mock.flush.assert_called_once()


@pytest.mark.asyncio
async def test_sync_registry_no_flush_when_all_exist(db_mock):
    """Should not call flush when all pages already exist."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = "existing"
    db_mock.execute.return_value = result_mock

    count = await sync_registry(db_mock)

    assert count == 0
    assert db_mock.add.call_count == 0
    db_mock.flush.assert_not_called()


@pytest.mark.asyncio
async def test_sync_registry_page_attributes():
    """Should create pages with correct attributes (page_origin, noindex, etc.)."""
    db_mock = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db_mock.execute.return_value = result_mock

    await sync_registry(db_mock)

    # Verify the pages added have correct attributes
    added_pages = [call.args[0] for call in db_mock.add.call_args_list]
    assert len(added_pages) == 4

    for page, expected in zip(added_pages, HAND_CODED_PAGES):
        assert page.page_key == expected["page_key"]
        assert page.page_origin == "hand-coded"
        assert page.page_slug == expected["page_slug"]
        assert page.title == expected["title"]
        assert page.draft_content is None
        assert page.published_content is None
        assert page.noindex is False


@pytest.mark.asyncio
async def test_hand_coded_pages_list_has_expected_entries():
    """HAND_CODED_PAGES should contain the 4 expected pages."""
    assert len(HAND_CODED_PAGES) == 4

    keys = [p["page_key"] for p in HAND_CODED_PAGES]
    assert "landing" in keys
    assert "workshop" in keys
    assert "trades" in keys
    assert "privacy" in keys

    # Verify landing page has root slug
    landing = next(p for p in HAND_CODED_PAGES if p["page_key"] == "landing")
    assert landing["page_slug"] == "/"
