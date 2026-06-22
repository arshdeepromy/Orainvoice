"""Integration test for Task 5.5 — deferral on staff-notify failure, close later.

Drives the hourly :func:`app.tasks.scheduled.check_missed_clock_outs_task`
across two runs to verify the deferral / retry contract pinned down by the
spec (REQ 4.2, 9.6):

  * **Run 1 — staff notification cannot be dispatched.** The auto-close branch
    calls :func:`_auto_close_entry`, which returns ``False`` (DEFER). The task
    must therefore leave the entry OPEN (no ``clock_out_at`` written), must NOT
    set the ``auto_clockout:{entry_id}`` Redis dedupe key, and must count the
    entry under the ``deferred`` summary bucket (never ``auto_closed``).
  * **Run 2 — notification now succeeds.** Because run 1 set no dedupe key, the
    entry is re-tried (NOT skipped): ``_auto_close_entry`` is called a second
    time, returns ``True`` (finalised closure), the task counts it under
    ``auto_closed`` and only NOW sets the dedupe key.

This test exercises ONLY the task's wiring (the dedupe-key lifecycle and the
deferred-vs-closed branching), so the single-entry closer
``_auto_close_entry`` is patched as an :class:`AsyncMock` whose side-effect
returns ``False`` on the first call and ``True`` on the second (mutating the
entry to simulate the real close on success). The org-policy loader is patched
to return an enabled policy with a cap the entry already exceeds, and the DB
session / ``redis_pool`` are replaced with light fakes. The fake redis is a
stateful dict so the dedupe-key lifecycle survives across the two runs.

**Validates: Requirements 4.2, 9.6**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Stateful dict-backed stand-in for ``app.core.redis.redis_pool``.

    Only the handful of operations the task uses are implemented. The
    backing ``store`` is shared across both runs so the dedupe-key lifecycle
    (set only after a finalised closure) can be asserted end-to-end.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return True

    async def expire(self, key, ttl):
        return True


class _Result:
    """Mimic the slice of ``AsyncSession.execute()`` the task touches."""

    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        proxy = MagicMock()
        proxy.all.return_value = self._rows
        return proxy


class _FakeSession:
    """In-memory ``AsyncSession`` stand-in.

    The task only issues the single open-entry SELECT before delegating to the
    (patched) ``_auto_close_entry``; everything else in the auto-close branch
    is short-circuited by the patches, so ``execute`` always returns the open
    entry list as instructed.
    """

    def __init__(self, entries):
        self._entries = entries

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, stmt, params=None):
        return _Result(self._entries)

    async def get(self, model, pk):  # pragma: no cover - not reached (closer patched)
        return None


def _factory_for(session: _FakeSession):
    """Return an ``async_session_factory`` substitute yielding ``session``."""

    @asynccontextmanager
    async def _factory_call():
        yield session

    return MagicMock(side_effect=lambda: _factory_call())


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_ENABLED_POLICY = {
    "auto_clock_out_enabled": True,
    "auto_clock_out_after_hours": 14,
    "auto_clock_out_grace_minutes": 15,
    "missed_clock_out_alert_enabled": True,
    "missed_clock_out_alert_channels": ["sms"],
    "missed_clock_out_reminder_hours": 12,
}


def _make_open_entry():
    """An open ``time_clock_entries`` row opened 20h ago — past the 14h cap."""
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        clock_in_at=now - timedelta(hours=20),
        clock_out_at=None,
        worked_minutes=None,
        break_minutes=0,
        scheduled_entry_id=None,
        flags={},
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deferral_then_close_on_later_run():
    """REQ 4.2 / 9.6 — a non-dispatchable staff notify defers the entry (left
    open, no dedupe); a later run, once the notify succeeds, closes it and only
    then sets the dedupe key.
    """
    from app.tasks import scheduled

    entry = _make_open_entry()
    dedupe_key = f"auto_clockout:{entry.id}"
    fake_redis = _FakeRedis()
    factory = _factory_for(_FakeSession([entry]))

    # _auto_close_entry: DEFER (False) on run 1, finalise (True) on run 2.
    # On success it mutates the entry the way the real closer would, so we can
    # assert the entry is genuinely closed only after run 2.
    async def _close_side_effect(session, the_entry, policy, now):
        if _close_side_effect.calls == 0:
            _close_side_effect.calls += 1
            return False  # deferred — staff notify not dispatched
        _close_side_effect.calls += 1
        the_entry.clock_out_at = now
        the_entry.worked_minutes = 600
        return True

    _close_side_effect.calls = 0
    mock_close = AsyncMock(side_effect=_close_side_effect)

    with patch("app.core.database.async_session_factory", factory), \
            patch("app.core.redis.redis_pool", fake_redis), \
            patch(
                "app.tasks.scheduled._load_org_clock_in_policy",
                new=AsyncMock(return_value=_ENABLED_POLICY),
            ), \
            patch("app.tasks.scheduled._auto_close_entry", new=mock_close):

        # ---- Run 1: staff notify undispatchable → DEFER ----
        summary1 = await scheduled.check_missed_clock_outs_task()

        # The closer was attempted exactly once and reported a deferral.
        assert mock_close.await_count == 1
        # Counted as deferred, NOT auto-closed.
        assert summary1["deferred"] == 1
        assert summary1["auto_closed"] == 0
        # The entry was left OPEN (no clock-out written).
        assert entry.clock_out_at is None
        # No dedupe key — so the entry will be retried on the next run.
        assert dedupe_key not in fake_redis.store

        # ---- Run 2: staff notify now succeeds → CLOSE ----
        summary2 = await scheduled.check_missed_clock_outs_task()

        # The entry was retried (NOT skipped by a dedupe key) — second call.
        assert mock_close.await_count == 2
        # This run finalised the closure.
        assert summary2["auto_closed"] == 1
        assert summary2["deferred"] == 0
        # The entry is now closed.
        assert entry.clock_out_at is not None
        # And only NOW is the dedupe key set (24h TTL), preventing re-close.
        assert dedupe_key in fake_redis.store


@pytest.mark.asyncio
async def test_deferred_entry_is_not_skipped_by_stale_dedupe():
    """Guard: the deferral path must not leave a dedupe key behind that would
    cause the retry run to short-circuit (``skipped``) instead of re-attempting
    the closure. After a deferral the entry is re-attempted, not skipped.
    """
    from app.tasks import scheduled

    entry = _make_open_entry()
    fake_redis = _FakeRedis()
    factory = _factory_for(_FakeSession([entry]))

    mock_close = AsyncMock(return_value=False)  # always defers

    with patch("app.core.database.async_session_factory", factory), \
            patch("app.core.redis.redis_pool", fake_redis), \
            patch(
                "app.tasks.scheduled._load_org_clock_in_policy",
                new=AsyncMock(return_value=_ENABLED_POLICY),
            ), \
            patch("app.tasks.scheduled._auto_close_entry", new=mock_close):

        summary1 = await scheduled.check_missed_clock_outs_task()
        summary2 = await scheduled.check_missed_clock_outs_task()

    # Both runs re-attempted the closer (never skipped via a dedupe key).
    assert mock_close.await_count == 2
    assert summary1["deferred"] == 1
    assert summary2["deferred"] == 1
    assert summary1["skipped"] == 0
    assert summary2["skipped"] == 0
