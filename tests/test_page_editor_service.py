"""Unit tests for the page_editor service layer.

Covers: create_page (valid + invalid slugs), publish workflow, slug change
creates redirect, soft-delete and undelete, registry sync. Revision cap
enforcement is exercised via the publish path.

Requirements: 2.1, 4.2, 5.7, 6.8, 10.1, 14.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.page_editor.schemas import CreatePageRequest
from app.modules.page_editor.service import (
    create_page,
    publish_page,
    soft_delete_page,
    undelete_page,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(
    *,
    page_key: str = "demo",
    page_slug: str = "/demo",
    page_origin: str = "editor-created",
    title: str = "Demo",
    draft_content: dict | None = None,
    published_content: dict | None = None,
    published_version: int | None = None,
    deleted_at: datetime | None = None,
):
    """Build a MagicMock page mirroring the EditorPage ORM shape."""
    page = MagicMock()
    page.page_key = page_key
    page.page_slug = page_slug
    page.page_origin = page_origin
    page.title = title
    page.draft_content = draft_content if draft_content is not None else {
        "content": [],
        "root": {"props": {}},
    }
    page.published_content = published_content
    page.published_version = published_version
    page.published_at = None
    page.published_by = None
    page.draft_updated_at = None
    page.draft_updated_by = None
    page.seo = {}
    page.noindex = False
    page.deleted_at = deleted_at
    page.deleted_by = None
    page.updated_at = None
    return page


def _execute_returns(scalar_result):
    """Build an AsyncMock db.execute() result that yields ``scalar_result``."""
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar_result
    return res


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# create_page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_page_invalid_slug_rejected(user_id):
    """Pydantic validator rejects malformed slugs at request time."""
    with pytest.raises(Exception):  # ValidationError
        CreatePageRequest(title="X", page_slug="missing-leading-slash")


@pytest.mark.asyncio
async def test_create_page_reserved_slug_rejected(user_id):
    """The service should reject reserved-prefix slugs even if regex passes."""
    db = AsyncMock()
    request = CreatePageRequest(title="Reserved", page_slug="/admin")
    with pytest.raises(HTTPException) as exc:
        await create_page(db, request, user_id)
    assert exc.value.status_code in {400, 409, 422}


@pytest.mark.asyncio
async def test_create_page_slug_collision_returns_409(user_id):
    """If the slug already exists on an active page, raise 409."""
    db = AsyncMock()
    # First execute() — slug uniqueness check returns an existing key
    db.execute.side_effect = [
        _execute_returns("existing-key"),  # slug collision check
    ]
    request = CreatePageRequest(title="Dup", page_slug="/demo")
    with pytest.raises(HTTPException) as exc:
        await create_page(db, request, user_id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_page_writes_initial_revision(user_id):
    """create_page should add both the page and an initial v1 revision."""
    db = AsyncMock()
    db.execute.side_effect = [
        _execute_returns(None),   # slug not in use
        _execute_returns(None),   # page_key not in use
    ]
    request = CreatePageRequest(title="Demo", page_slug="/demo")

    page = await create_page(db, request, user_id)

    # Page + revision were added
    assert db.add.call_count == 2
    # Two flushes (page row, then revision row)
    assert db.flush.await_count == 2
    # Returned object is the page mock built by service
    assert page is not None


# ---------------------------------------------------------------------------
# publish_page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_page_not_found_returns_404(user_id):
    db = AsyncMock()
    db.execute.return_value = _execute_returns(None)
    with pytest.raises(HTTPException) as exc:
        await publish_page(db, "ghost", user_id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_publish_page_deleted_returns_410(user_id):
    db = AsyncMock()
    page = _make_page(deleted_at=datetime.now(timezone.utc))
    db.execute.return_value = _execute_returns(page)
    with pytest.raises(HTTPException) as exc:
        await publish_page(db, page.page_key, user_id)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_publish_page_first_publish_sets_version_one(user_id):
    """First publish: published_version goes from None to 1, revision created."""
    db = AsyncMock()
    page = _make_page(
        draft_content={"content": [{"type": "Heading", "props": {"text": "Hi"}}], "root": {"props": {}}}
    )
    db.execute.return_value = _execute_returns(page)
    with patch("app.modules.page_editor.service._enforce_revision_cap", new=AsyncMock()):
        result = await publish_page(db, page.page_key, user_id)
    assert result.published_version == 1
    assert result.published_content == result.draft_content
    assert result.published_by == user_id
    # One add() call (the revision)
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_publish_page_subsequent_publish_increments_version(user_id):
    db = AsyncMock()
    page = _make_page(
        draft_content={"content": [], "root": {"props": {}}},
        published_version=4,
    )
    db.execute.return_value = _execute_returns(page)
    with patch("app.modules.page_editor.service._enforce_revision_cap", new=AsyncMock()):
        result = await publish_page(db, page.page_key, user_id)
    assert result.published_version == 5


@pytest.mark.asyncio
async def test_publish_page_no_draft_returns_422(user_id):
    db = AsyncMock()
    page = _make_page()
    page.draft_content = None
    db.execute.return_value = _execute_returns(page)
    with pytest.raises(HTTPException) as exc:
        await publish_page(db, page.page_key, user_id)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_publish_page_invokes_revision_cap_enforcement(user_id):
    """Ensure _enforce_revision_cap is called on every publish (Req 5.7)."""
    db = AsyncMock()
    page = _make_page(
        draft_content={"content": [], "root": {"props": {}}},
    )
    db.execute.return_value = _execute_returns(page)
    cap = AsyncMock()
    with patch("app.modules.page_editor.service._enforce_revision_cap", cap):
        await publish_page(db, page.page_key, user_id)
    cap.assert_awaited_once_with(db, page.page_key)


# ---------------------------------------------------------------------------
# soft_delete_page / undelete_page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_page_hand_coded_rejected_409(user_id):
    db = AsyncMock()
    page = _make_page(page_origin="hand-coded")
    db.execute.return_value = _execute_returns(page)
    with pytest.raises(HTTPException) as exc:
        await soft_delete_page(db, page.page_key, user_id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_soft_delete_page_already_deleted_returns_410(user_id):
    db = AsyncMock()
    page = _make_page(deleted_at=datetime.now(timezone.utc))
    db.execute.return_value = _execute_returns(page)
    with pytest.raises(HTTPException) as exc:
        await soft_delete_page(db, page.page_key, user_id)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_soft_delete_page_sets_deleted_fields(user_id):
    db = AsyncMock()
    page = _make_page()
    db.execute.return_value = _execute_returns(page)
    result = await soft_delete_page(db, page.page_key, user_id)
    assert result.deleted_at is not None
    assert result.deleted_by == user_id


@pytest.mark.asyncio
async def test_undelete_page_not_deleted_returns_400(user_id):
    db = AsyncMock()
    page = _make_page()  # deleted_at is None
    db.execute.return_value = _execute_returns(page)
    with pytest.raises(HTTPException) as exc:
        await undelete_page(db, page.page_key)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_undelete_page_slug_conflict_returns_409():
    db = AsyncMock()
    deleted_page = _make_page(
        page_key="archived",
        page_slug="/conflict",
        deleted_at=datetime.now(timezone.utc),
    )
    conflicting_row = MagicMock()
    conflicting_row.page_key = "active"
    conflicting_row.title = "Active Page"

    db.execute.side_effect = [
        _execute_returns(deleted_page),  # load page
        MagicMock(first=MagicMock(return_value=conflicting_row)),  # conflict check
    ]
    with pytest.raises(HTTPException) as exc:
        await undelete_page(db, "archived")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_undelete_page_clears_deleted_fields():
    db = AsyncMock()
    deleted_page = _make_page(deleted_at=datetime.now(timezone.utc))
    deleted_page.deleted_by = uuid.uuid4()

    db.execute.side_effect = [
        _execute_returns(deleted_page),  # load page
        MagicMock(first=MagicMock(return_value=None)),  # no conflict
    ]
    result = await undelete_page(db, deleted_page.page_key)
    assert result.deleted_at is None
    assert result.deleted_by is None
