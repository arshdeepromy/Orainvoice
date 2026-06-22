"""Integration test for Task 5.4 — idempotent run.

# Feature: auto-clock-out, Task 5.4 — task-level idempotency

**Validates: Requirements 2.6, 4.6, 9.3**

The task under test is :func:`app.tasks.scheduled.check_missed_clock_outs_task`.
Its auto-close branch protects against re-closing / re-notifying the same entry
across runs (or after a worker restart) using a Redis dedupe key
``auto_clockout:{entry.id}`` that is set with a 24h TTL **only after** a
finalised closure. On a later run the branch finds that key and skips the entry.

Pinned-down design correctness property:

* **Property 10 — Idempotent run:** running the task twice closes a given entry
  at most once and notifies at most once (the Redis dedupe set is written only
  after closure).

This is an integration-style test of the *task wiring*, not of the closer
itself, so :func:`_auto_close_entry` is mocked as an ``AsyncMock`` returning
``True`` (a finalised closure). The fakes are stateful where it matters:

* ``redis_pool`` is a dict-backed double, so the dedupe key written on run 1
  persists into run 2 (this is the whole point of the property).
* ``async_session_factory`` yields a fresh session per run, but every session's
  ``execute`` returns the *same* still-open entry (the closer is mocked, so it
  never sets ``clock_out_at``; the entry stays open across both runs exactly as
  it would before the dedupe key is honoured).
* ``_load_org_clock_in_policy`` returns an enabled policy whose cap is well
  below the entry's open duration, so the entry is always eligible.

The assertions are that across the two runs ``_auto_close_entry`` was awaited
exactly once (run 2 short-circuits on the dedupe key) and the dedupe key was
written exactly once.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tasks.scheduled import check_missed_clock_outs_task


# ---------------------------------------------------------------------------
# Stateful fakes
# ---------------------------------------------------------------------------

class _FakeRedis:
    """A dict-backed ``redis_pool`` double.

    Only the handful of operations the auto-close branch uses are
    implemented. ``set_calls`` records every key written so the test can
    assert the dedupe key was set exactly once across both runs.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[str] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return None
        self.store[key] = value
        self.set_calls.append(key)
        return True

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return True


class _AsyncNullCtx:
    """A no-op async context manager (stands in for ``session.begin()``)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    """A session double that always returns the same single open entry.

    Doubles as its own async context manager so ``async with
    async_session_factory() as session`` works.
    """

    def __init__(self, entry):
        self._entry = entry

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def begin(self):
        return _AsyncNullCtx()

    async def execute(self, stmt):
        # Every run sees the same still-open entry — the closer is mocked
        # so it never sets clock_out_at, so the entry never leaves the scan.
        return _Result([self._entry])

    async def get(self, model, ident):
        return None


def _make_open_entry():
    """An open ``time_clock_entries`` double opened ~20h ago (well past the
    8h cap configured by the fake policy)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        clock_in_at=datetime.now(timezone.utc) - timedelta(hours=20),
        clock_out_at=None,
        break_minutes=0,
        flags=None,
        worked_minutes=None,
    )


def _enabled_policy():
    return {
        "auto_clock_out_enabled": True,
        "auto_clock_out_after_hours": 8,
        "auto_clock_out_grace_minutes": 15,
        "missed_clock_out_alert_enabled": True,
        "missed_clock_out_alert_channels": ["sms"],
        "missed_clock_out_reminder_hours": 12,
    }


async def _run_twice():
    entry = _make_open_entry()
    fake_redis = _FakeRedis()

    def factory():
        # Fresh session per run; same underlying open entry both times.
        return _FakeSession(entry)

    close_mock = AsyncMock(return_value=True)
    policy_mock = AsyncMock(return_value=_enabled_policy())

    with patch(
        "app.core.database.async_session_factory", factory,
    ), patch(
        "app.core.redis.redis_pool", fake_redis,
    ), patch(
        "app.tasks.scheduled._load_org_clock_in_policy", policy_mock,
    ), patch(
        "app.tasks.scheduled._auto_close_entry", close_mock,
    ):
        first = await check_missed_clock_outs_task()
        second = await check_missed_clock_outs_task()

    return entry, fake_redis, close_mock, first, second


def test_idempotent_run_closes_and_notifies_at_most_once():
    """Property 10: running the task twice closes a given entry at most once
    and notifies at most once — the Redis dedupe key is set only after a
    finalised closure, and the second run short-circuits on it.

    **Validates: Requirements 2.6, 4.6, 9.3**
    """
    entry, fake_redis, close_mock, first, second = asyncio.run(_run_twice())

    dedupe_key = f"auto_clockout:{entry.id}"

    # The closer ran exactly once across BOTH runs (run 2 skipped via dedupe).
    assert close_mock.await_count == 1

    # The dedupe key was written exactly once, and only after the closure.
    assert fake_redis.set_calls.count(dedupe_key) == 1
    assert fake_redis.store.get(dedupe_key) == "1"

    # Run 1 finalised the closure; run 2 saw the dedupe key and skipped.
    assert first["auto_closed"] == 1
    assert second["auto_closed"] == 0
    assert second["skipped"] >= 1
