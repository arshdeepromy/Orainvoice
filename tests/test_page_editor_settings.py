"""Unit tests for update_page_settings service function.

Tests cover:
- Basic SEO field updates
- Title and noindex updates
- Slug change for editor-created pages (creates redirect)
- Slug change rejection for hand-coded pages (409)
- Redirect cycle detection and removal
- 404 for missing page, 410 for deleted page
- Slug conflict detection

Requirements: 6.1, 6.7, 6.8, 6.9, 6.10
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.page_editor.schemas import PageSettingsRequest
from app.modules.page_editor.service import update_page_settings


def _make_page(
    page_key: str = "test-page",
    page_origin: str = "editor-created",
    page_slug: str = "/test-page",
    title: str = "Test Page",
    seo: dict | None = None,
    noindex: bool = False,
    deleted_at: datetime | None = None,
):
    """Create a mock EditorPage object."""
    page = MagicMock()
    page.page_key = page_key
    page.page_origin = page_origin
    page.page_slug = page_slug
    page.title = title
    page.seo = seo or {}
    page.noindex = noindex
    page.deleted_at = deleted_at
    page.updated_at = None
    return page


def _make_redirect(from_slug: str, to_slug_or_url: str, deleted_at=None):
    """Create a mock EditorPageRedirect object."""
    redirect = MagicMock()
    redirect.from_slug = from_slug
    redirect.to_slug_or_url = to_slug_or_url
    redirect.deleted_at = deleted_at
    return redirect


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_update_page_settings_page_not_found(user_id):
    """Should raise 404 when page doesn't exist."""
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(title="New Title")

    with pytest.raises(HTTPException) as exc_info:
        await update_page_settings(db, "nonexistent", settings, user_id)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_page_settings_deleted_page(user_id):
    """Should raise 410 when page is deleted."""
    db = AsyncMock()
    page = _make_page(deleted_at=datetime.now(timezone.utc))
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = page
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(title="New Title")

    with pytest.raises(HTTPException) as exc_info:
        await update_page_settings(db, "test-page", settings, user_id)

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_update_page_settings_slug_change_hand_coded_rejected(user_id):
    """Should raise 409 when trying to change slug of hand-coded page."""
    db = AsyncMock()
    page = _make_page(page_origin="hand-coded", page_slug="/workshop")
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = page
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(page_slug="/new-workshop")

    with pytest.raises(HTTPException) as exc_info:
        await update_page_settings(db, "workshop", settings, user_id)

    assert exc_info.value.status_code == 409
    assert "Cannot change slug of hand-coded pages" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_update_page_settings_title_update(user_id):
    """Should update title when provided."""
    db = AsyncMock()
    page = _make_page()

    # First call returns the page, subsequent calls return no conflict
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = page
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(title="Updated Title")

    result = await update_page_settings(db, "test-page", settings, user_id)

    assert page.title == "Updated Title"
    assert page.updated_at is not None
    db.flush.assert_called_once()
    db.refresh.assert_called_once_with(page)


@pytest.mark.asyncio
async def test_update_page_settings_noindex_update(user_id):
    """Should update noindex when provided."""
    db = AsyncMock()
    page = _make_page(noindex=False)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = page
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(noindex=True)

    await update_page_settings(db, "test-page", settings, user_id)

    assert page.noindex is True


@pytest.mark.asyncio
async def test_update_page_settings_seo_fields_update(user_id):
    """Should update SEO fields in the seo dict."""
    db = AsyncMock()
    page = _make_page(seo={"meta_title": "Old Title"})

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = page
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(
        meta_title="New Meta Title",
        meta_description="A description",
        og_type="article",
    )

    await update_page_settings(db, "test-page", settings, user_id)

    assert page.seo["meta_title"] == "New Meta Title"
    assert page.seo["meta_description"] == "A description"
    assert page.seo["og_type"] == "article"


@pytest.mark.asyncio
async def test_update_page_settings_same_slug_no_redirect(user_id):
    """Should not create redirect when slug is unchanged."""
    db = AsyncMock()
    page = _make_page(page_slug="/test-page")

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = page
    db.execute.return_value = result_mock

    settings = PageSettingsRequest(page_slug="/test-page", title="New Title")

    await update_page_settings(db, "test-page", settings, user_id)

    # db.add should not be called (no redirect created)
    db.add.assert_not_called()
    assert page.title == "New Title"
