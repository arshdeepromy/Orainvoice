"""Unit tests for concurrent editing advisory lock (Redis).

Tests cover:
- acquire_editor_lock: acquires lock when no existing lock
- acquire_editor_lock: returns lock holder info when different user holds lock
- acquire_editor_lock: refreshes TTL when same user holds lock
- refresh_editor_lock: refreshes TTL when owned by user
- refresh_editor_lock: does nothing when lock doesn't exist
- refresh_editor_lock: does nothing when owned by different user
- release_editor_lock: deletes key when owned by user
- release_editor_lock: does nothing when lock doesn't exist
- release_editor_lock: does nothing when owned by different user

Requirements: 3.12
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from app.modules.page_editor.service import (
    _EDITOR_LOCK_TTL,
    acquire_editor_lock,
    refresh_editor_lock,
    release_editor_lock,
)


@pytest.fixture
def redis_mock():
    """Create a mock Redis client."""
    return AsyncMock()


@pytest.fixture
def user_a_id():
    return uuid.uuid4()


@pytest.fixture
def user_b_id():
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# acquire_editor_lock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_lock_no_existing(redis_mock, user_a_id):
    """Should acquire lock and return None when no existing lock."""
    redis_mock.get.return_value = None

    result = await acquire_editor_lock(
        redis_mock, "my-page", user_a_id, "alice@example.com"
    )

    assert result is None
    redis_mock.get.assert_called_once_with("page_editor:lock:my-page")
    redis_mock.set.assert_called_once()
    # Verify set was called with nx=True and ex=300
    call_kwargs = redis_mock.set.call_args.kwargs
    assert call_kwargs["nx"] is True
    assert call_kwargs["ex"] == _EDITOR_LOCK_TTL


@pytest.mark.asyncio
async def test_acquire_lock_different_user(redis_mock, user_a_id, user_b_id):
    """Should return lock holder info when different user holds the lock."""
    existing_lock = json.dumps({
        "user_id": str(user_b_id),
        "user_email": "bob@example.com",
        "opened_at": "2025-01-01T12:00:00+00:00",
    })
    redis_mock.get.return_value = existing_lock

    result = await acquire_editor_lock(
        redis_mock, "my-page", user_a_id, "alice@example.com"
    )

    assert result is not None
    assert result["user_email"] == "bob@example.com"
    assert result["opened_at"] == "2025-01-01T12:00:00+00:00"
    # Should NOT call set (lock not acquired)
    redis_mock.set.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_lock_same_user_refreshes_ttl(redis_mock, user_a_id):
    """Should refresh TTL and return None when same user holds the lock."""
    existing_lock = json.dumps({
        "user_id": str(user_a_id),
        "user_email": "alice@example.com",
        "opened_at": "2025-01-01T12:00:00+00:00",
    })
    redis_mock.get.return_value = existing_lock

    result = await acquire_editor_lock(
        redis_mock, "my-page", user_a_id, "alice@example.com"
    )

    assert result is None
    redis_mock.expire.assert_called_once_with(
        "page_editor:lock:my-page", _EDITOR_LOCK_TTL
    )
    redis_mock.set.assert_not_called()


@pytest.mark.asyncio
async def test_acquire_lock_stores_correct_json(redis_mock, user_a_id):
    """Should store correct JSON structure in Redis."""
    redis_mock.get.return_value = None

    await acquire_editor_lock(
        redis_mock, "test-page", user_a_id, "alice@example.com"
    )

    # Verify the value stored
    set_call_args = redis_mock.set.call_args.args
    stored_value = json.loads(set_call_args[1])
    assert stored_value["user_id"] == str(user_a_id)
    assert stored_value["user_email"] == "alice@example.com"
    assert "opened_at" in stored_value


# ---------------------------------------------------------------------------
# refresh_editor_lock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_lock_owned_by_user(redis_mock, user_a_id):
    """Should refresh TTL when lock is owned by the user."""
    existing_lock = json.dumps({
        "user_id": str(user_a_id),
        "user_email": "alice@example.com",
        "opened_at": "2025-01-01T12:00:00+00:00",
    })
    redis_mock.get.return_value = existing_lock

    await refresh_editor_lock(redis_mock, "my-page", user_a_id)

    redis_mock.expire.assert_called_once_with(
        "page_editor:lock:my-page", _EDITOR_LOCK_TTL
    )


@pytest.mark.asyncio
async def test_refresh_lock_no_existing(redis_mock, user_a_id):
    """Should do nothing when no lock exists."""
    redis_mock.get.return_value = None

    await refresh_editor_lock(redis_mock, "my-page", user_a_id)

    redis_mock.expire.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_lock_different_user(redis_mock, user_a_id, user_b_id):
    """Should not refresh TTL when lock is owned by a different user."""
    existing_lock = json.dumps({
        "user_id": str(user_b_id),
        "user_email": "bob@example.com",
        "opened_at": "2025-01-01T12:00:00+00:00",
    })
    redis_mock.get.return_value = existing_lock

    await refresh_editor_lock(redis_mock, "my-page", user_a_id)

    redis_mock.expire.assert_not_called()


# ---------------------------------------------------------------------------
# release_editor_lock tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_lock_owned_by_user(redis_mock, user_a_id):
    """Should delete key when lock is owned by the user."""
    existing_lock = json.dumps({
        "user_id": str(user_a_id),
        "user_email": "alice@example.com",
        "opened_at": "2025-01-01T12:00:00+00:00",
    })
    redis_mock.get.return_value = existing_lock

    await release_editor_lock(redis_mock, "my-page", user_a_id)

    redis_mock.delete.assert_called_once_with("page_editor:lock:my-page")


@pytest.mark.asyncio
async def test_release_lock_no_existing(redis_mock, user_a_id):
    """Should do nothing when no lock exists."""
    redis_mock.get.return_value = None

    await release_editor_lock(redis_mock, "my-page", user_a_id)

    redis_mock.delete.assert_not_called()


@pytest.mark.asyncio
async def test_release_lock_different_user(redis_mock, user_a_id, user_b_id):
    """Should not delete key when lock is owned by a different user."""
    existing_lock = json.dumps({
        "user_id": str(user_b_id),
        "user_email": "bob@example.com",
        "opened_at": "2025-01-01T12:00:00+00:00",
    })
    redis_mock.get.return_value = existing_lock

    await release_editor_lock(redis_mock, "my-page", user_a_id)

    redis_mock.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Redis key format tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_key_format(redis_mock, user_a_id):
    """Should use correct Redis key format: page_editor:lock:{page_key}."""
    redis_mock.get.return_value = None

    await acquire_editor_lock(
        redis_mock, "about-us", user_a_id, "alice@example.com"
    )

    redis_mock.get.assert_called_once_with("page_editor:lock:about-us")
    set_call_args = redis_mock.set.call_args.args
    assert set_call_args[0] == "page_editor:lock:about-us"
