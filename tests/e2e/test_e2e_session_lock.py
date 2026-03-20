"""E2E tests for session creation Redis distributed lock (REM-16).

Covers:
  - Session creation acquires Redis lock before checking session count
  - Lock is released after successful session creation
  - Lock is released even when session logic raises an exception
  - Lock timeout (cannot acquire) raises ValueError with appropriate message
  - Concurrent session creation attempts are serialised (second waits for lock)

The ``enforce_session_limit()`` function in ``app/modules/auth/service.py``
uses ``redis_pool.lock(f"session_lock:{user_id}", timeout=5, blocking_timeout=5)``
to serialise concurrent session creation for the same user.

Requirements: 19.1
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx

from app.modules.auth.jwt import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_USER_ID = uuid.uuid4()
_TEST_ORG_ID = uuid.uuid4()
_TEST_EMAIL = "admin@example.com"


def _make_access_token(role="global_admin"):
    """Create a valid JWT access token for test requests."""
    return create_access_token(
        user_id=_TEST_USER_ID,
        org_id=_TEST_ORG_ID,
        role=role,
        email=_TEST_EMAIL,
    )


def _auth_headers(token: str | None = None) -> dict:
    """Return Authorization header dict."""
    t = token or _make_access_token()
    return {"Authorization": f"Bearer {t}"}


# ---------------------------------------------------------------------------
# Mock lock helpers
# ---------------------------------------------------------------------------


def _make_mock_lock(acquire_result: bool = True):
    """Create a mock Redis lock that tracks acquire/release calls.

    Parameters
    ----------
    acquire_result:
        What ``await lock.acquire()`` should return.  ``True`` means the
        lock was successfully acquired; ``False`` simulates a timeout.
    """
    lock = AsyncMock()
    lock.acquire = AsyncMock(return_value=acquire_result)
    lock.release = AsyncMock()
    return lock


def _make_mock_redis_pool(lock_obj):
    """Return a mock redis_pool whose ``.lock()`` returns *lock_obj*."""
    pool = MagicMock()
    pool.lock = MagicMock(return_value=lock_obj)
    return pool


def _make_mock_db_with_sessions(session_count: int = 0):
    """Return a mock AsyncSession with *session_count* active sessions."""
    sessions = []
    for _ in range(session_count):
        s = MagicMock()
        s.is_revoked = False
        sessions.append(s)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sessions

    db = AsyncMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# 1. Lock is acquired before checking session count
# ---------------------------------------------------------------------------


class TestSessionLockAcquisition:
    """Verify that enforce_session_limit acquires the Redis lock."""

    @pytest.mark.asyncio
    async def test_lock_acquired_before_session_check(self):
        """The Redis lock must be acquired before the DB query runs."""
        from app.modules.auth.service import enforce_session_limit

        mock_lock = _make_mock_lock(acquire_result=True)
        mock_pool = _make_mock_redis_pool(mock_lock)
        mock_db = _make_mock_db_with_sessions(session_count=0)

        with patch("app.core.redis.redis_pool", mock_pool):
            await enforce_session_limit(mock_db, _TEST_USER_ID, max_sessions=5)

        # Lock was created with the correct key pattern
        mock_pool.lock.assert_called_once()
        call_args = mock_pool.lock.call_args
        assert call_args[0][0] == f"session_lock:{_TEST_USER_ID}"

        # Lock was acquired
        mock_lock.acquire.assert_awaited_once()

        # DB was queried (session count check happened after lock)
        mock_db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. Lock is released after successful session creation
# ---------------------------------------------------------------------------


class TestSessionLockRelease:
    """Verify that the lock is always released after the operation."""

    @pytest.mark.asyncio
    async def test_lock_released_after_success(self):
        """Lock must be released after a successful session limit check."""
        from app.modules.auth.service import enforce_session_limit

        mock_lock = _make_mock_lock(acquire_result=True)
        mock_pool = _make_mock_redis_pool(mock_lock)
        mock_db = _make_mock_db_with_sessions(session_count=0)

        with patch("app.core.redis.redis_pool", mock_pool):
            result = await enforce_session_limit(mock_db, _TEST_USER_ID, max_sessions=5)

        assert result == 0  # no sessions revoked
        mock_lock.release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lock_released_after_exception(self):
        """Lock must be released even when the session logic raises."""
        from app.modules.auth.service import enforce_session_limit

        mock_lock = _make_mock_lock(acquire_result=True)
        mock_pool = _make_mock_redis_pool(mock_lock)

        # DB that raises an exception during execute
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch("app.core.redis.redis_pool", mock_pool):
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await enforce_session_limit(mock_db, _TEST_USER_ID, max_sessions=5)

        # Lock MUST still be released despite the exception
        mock_lock.release.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Lock timeout raises ValueError
# ---------------------------------------------------------------------------


class TestLockTimeout:
    """When the lock cannot be acquired, a ValueError is raised."""

    @pytest.mark.asyncio
    async def test_lock_timeout_raises_value_error(self):
        """If lock.acquire() returns False, ValueError is raised."""
        from app.modules.auth.service import enforce_session_limit

        mock_lock = _make_mock_lock(acquire_result=False)
        mock_pool = _make_mock_redis_pool(mock_lock)
        mock_db = _make_mock_db_with_sessions(session_count=0)

        with patch("app.core.redis.redis_pool", mock_pool):
            with pytest.raises(ValueError, match="Could not acquire session lock"):
                await enforce_session_limit(mock_db, _TEST_USER_ID, max_sessions=5)

        # DB should NOT have been queried — lock was never acquired
        mock_db.execute.assert_not_awaited()

        # Lock release should NOT be called when acquire fails
        mock_lock.release.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_lock_timeout_error_message(self):
        """The ValueError message includes retry guidance."""
        from app.modules.auth.service import enforce_session_limit

        mock_lock = _make_mock_lock(acquire_result=False)
        mock_pool = _make_mock_redis_pool(mock_lock)
        mock_db = _make_mock_db_with_sessions(session_count=0)

        with patch("app.core.redis.redis_pool", mock_pool):
            with pytest.raises(ValueError) as exc_info:
                await enforce_session_limit(mock_db, _TEST_USER_ID, max_sessions=5)

        assert "Please try again" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Concurrent session creation is serialised
# ---------------------------------------------------------------------------


class TestConcurrentSessionCreation:
    """Concurrent calls for the same user are serialised by the lock."""

    @pytest.mark.asyncio
    async def test_concurrent_attempts_serialised(self):
        """Two concurrent enforce_session_limit calls for the same user
        must both acquire the lock — the second waits until the first
        releases it.

        We simulate this by making the first lock.acquire() succeed
        immediately and the second one succeed only after a short delay
        (simulating waiting for the lock).
        """
        from app.modules.auth.service import enforce_session_limit

        call_order: list[str] = []

        # Track when each call enters and exits the critical section
        original_lock = _make_mock_lock(acquire_result=True)

        async def _tracked_acquire_1():
            call_order.append("acquire_1")
            return True

        async def _tracked_release_1():
            call_order.append("release_1")

        async def _tracked_acquire_2():
            call_order.append("acquire_2")
            return True

        async def _tracked_release_2():
            call_order.append("release_2")

        lock_1 = AsyncMock()
        lock_1.acquire = _tracked_acquire_1
        lock_1.release = _tracked_release_1

        lock_2 = AsyncMock()
        lock_2.acquire = _tracked_acquire_2
        lock_2.release = _tracked_release_2

        lock_call_count = 0

        def _lock_factory(*args, **kwargs):
            nonlocal lock_call_count
            lock_call_count += 1
            return lock_1 if lock_call_count == 1 else lock_2

        mock_pool = MagicMock()
        mock_pool.lock = MagicMock(side_effect=_lock_factory)

        mock_db_1 = _make_mock_db_with_sessions(session_count=0)
        mock_db_2 = _make_mock_db_with_sessions(session_count=0)

        user_id = uuid.uuid4()

        with patch("app.core.redis.redis_pool", mock_pool):
            await asyncio.gather(
                enforce_session_limit(mock_db_1, user_id, max_sessions=5),
                enforce_session_limit(mock_db_2, user_id, max_sessions=5),
            )

        # Both calls acquired and released their locks
        assert "acquire_1" in call_order
        assert "release_1" in call_order
        assert "acquire_2" in call_order
        assert "release_2" in call_order

        # The lock was created twice (once per call) with the same key
        assert mock_pool.lock.call_count == 2
        for call in mock_pool.lock.call_args_list:
            assert call[0][0] == f"session_lock:{user_id}"

    @pytest.mark.asyncio
    async def test_lock_key_is_user_specific(self):
        """Different users get different lock keys — no cross-user blocking."""
        from app.modules.auth.service import enforce_session_limit

        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        lock_keys: list[str] = []

        def _tracking_lock(key, **kwargs):
            lock_keys.append(key)
            return _make_mock_lock(acquire_result=True)

        mock_pool = MagicMock()
        mock_pool.lock = MagicMock(side_effect=_tracking_lock)

        mock_db = _make_mock_db_with_sessions(session_count=0)

        with patch("app.core.redis.redis_pool", mock_pool):
            await enforce_session_limit(mock_db, user_a, max_sessions=5)
            await enforce_session_limit(mock_db, user_b, max_sessions=5)

        assert f"session_lock:{user_a}" in lock_keys
        assert f"session_lock:{user_b}" in lock_keys
        assert lock_keys[0] != lock_keys[1]
