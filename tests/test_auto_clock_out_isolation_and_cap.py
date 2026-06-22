"""Integration test for Task 5.6 — per-org isolation + casual no-schedule cap.

**Property 9: Casual clock-in preserved** — a no-schedule staff member can clock
in and is closed via the safety-net cap; a failure for one org does not block
others; an enabled org closes + notifies once.

Two angles, each in its own test class with its own mocks (this file is
self-contained so it can run alongside the sibling 5.2-5.5 tests which exercise
the same ``check_missed_clock_outs_task``):

  1. **Per-org isolation** (``TestPerOrgIsolation``) — the hourly task processes
     two open entries across two orgs. ``_auto_close_entry`` raises for the first
     org's entry and succeeds for the second. The exception is isolated: the
     second entry is still closed, and the run summary reports ``errors == 1``
     and ``auto_closed == 1`` (REQ 2.7). The Redis dedupe key is set exactly once
     — only for the finalised closure (REQ 2.6 / "notifies once").

  2. **Casual no-schedule cap** (``TestCasualNoScheduleCap``) — drives the REAL
     ``_auto_close_entry`` for a casual entry (``scheduled_entry_id`` is None and
     the staff member's ``working_arrangement`` is not ``"fixed"``). With the
     staff notification dispatched, the entry is closed via the safety-net cap:
     ``clock_out_at == clock_in_at + after_hours`` (clamped to ``now``), the
     staff member is notified exactly once, and the closer returns ``True``
     (REQ 5.1 / 5.2 / 9.4).

**Validates: Requirements 2.7, 5.1, 5.2, 9.4**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.scheduled import _auto_close_entry, check_missed_clock_outs_task

# Patch targets referenced from inside the hourly task / closer.
LOAD_POLICY = "app.tasks.scheduled._load_org_clock_in_policy"
AUTO_CLOSE = "app.tasks.scheduled._auto_close_entry"
SESSION_FACTORY = "app.core.database.async_session_factory"
REDIS_POOL = "app.core.redis.redis_pool"
STAFF_NOTIFY = "app.tasks.scheduled._notify_staff_auto_clock_out"
MANAGER_NOTIFY = "app.tasks.scheduled._notify_manager_auto_clock_out"
RESOLVE_MANAGER = "app.tasks.scheduled._resolve_manager"
WRITE_AUDIT = "app.core.audit.write_audit_log"


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# An enabled auto-clock-out policy: cap 14h, grace 15m, SMS channel.
ENABLED_POLICY = {
    "auto_clock_out_enabled": True,
    "auto_clock_out_after_hours": 14,
    "auto_clock_out_grace_minutes": 15,
    "missed_clock_out_alert_channels": ["sms"],
    "missed_clock_out_alert_enabled": True,
}


# ---------------------------------------------------------------------------
# Stateful Redis double — backs the ``auto_clockout:{entry_id}`` dedupe keys.
# ---------------------------------------------------------------------------

class _FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.set_calls: list = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        self.set_calls.append(key)
        self.store[key] = value
        return True


# ---------------------------------------------------------------------------
# Fake async session factory — yields a session whose single ``execute`` call
# returns the pre-baked open entries via ``.scalars().all()``.
# ---------------------------------------------------------------------------

def _make_session_factory(open_entries: list):
    @asynccontextmanager
    async def _begin(_session):
        yield _session

    def _build_session():
        session = AsyncMock()

        # ``async with session.begin():`` — a no-op async context manager.
        session.begin = MagicMock(side_effect=lambda: _begin(session))

        async def _execute(_stmt, *_args, **_kwargs):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = open_entries
            result.scalars.return_value = scalars
            return result

        session.execute = _execute
        return session

    @asynccontextmanager
    async def _factory_call():
        yield _build_session()

    return MagicMock(side_effect=lambda: _factory_call())


def _make_open_entry(*, org_id, clock_in_at):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=uuid.uuid4(),
        clock_in_at=clock_in_at,
        clock_out_at=None,
        worked_minutes=None,
        scheduled_entry_id=None,
        break_minutes=0,
        flags=None,
    )


# ---------------------------------------------------------------------------
# Angle 1 — per-org failure isolation (REQ 2.7)
# ---------------------------------------------------------------------------

class TestPerOrgIsolation:
    """One org's auto-close failure never blocks another org's closure."""

    @pytest.mark.asyncio
    async def test_one_org_failure_does_not_block_the_other(self):
        """**Validates: Requirements 2.7**

        Two open entries in two different orgs. ``_auto_close_entry`` raises for
        org 1's entry (simulating a per-org failure) and succeeds for org 2's.
        The batch must isolate the exception: org 2's entry is still closed,
        ``errors == 1``, ``auto_closed == 1``, and the dedupe key is set ONCE
        (only for the finalised closure).
        """
        org1 = uuid.uuid4()
        org2 = uuid.uuid4()
        # Both opened ~20h ago, well past the 14h cap.
        clock_in = datetime.now(timezone.utc) - timedelta(hours=20)
        entry1 = _make_open_entry(org_id=org1, clock_in_at=clock_in)
        entry2 = _make_open_entry(org_id=org2, clock_in_at=clock_in)

        factory = _make_session_factory([entry1, entry2])
        fake_redis = _FakeRedis()

        async def _policy_loader(_session, org_id, _cache):
            # Per-org policy via the memoised loader mock — both enabled.
            return dict(ENABLED_POLICY)

        def _close_side_effect(_session, entry, _policy, now):
            if entry.org_id == org1:
                raise RuntimeError("org1 auto-close blew up")
            # org2 — finalise the closure.
            entry.clock_out_at = now
            entry.worked_minutes = 480
            return True

        with patch(SESSION_FACTORY, factory), \
             patch(REDIS_POOL, fake_redis), \
             patch(LOAD_POLICY, new_callable=AsyncMock, side_effect=_policy_loader), \
             patch(AUTO_CLOSE, new_callable=AsyncMock,
                   side_effect=_close_side_effect) as m_close:
            summary = await check_missed_clock_outs_task()

        # Both entries were attempted (exception did not abort the loop).
        assert m_close.await_count == 2
        # org1 failed, org2 closed — failure isolated (REQ 2.7).
        assert summary["errors"] == 1
        assert summary["auto_closed"] == 1
        # org2's entry was actually closed; org1's left open for retry.
        assert entry2.clock_out_at is not None
        assert entry1.clock_out_at is None
        # Dedupe key set ONCE — only after the finalised closure (org2), so the
        # closure notifies/closes at most once and the failed org retries next
        # run with no dedupe.
        assert fake_redis.set_calls == [f"auto_clockout:{entry2.id}"]


# ---------------------------------------------------------------------------
# Angle 2 — casual / no-schedule staff closed via the safety-net cap (REQ 5.2)
# ---------------------------------------------------------------------------

class _AsyncCM:
    """Minimal async context manager standing in for ``session.begin_nested``."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_closer_entry(*, clock_in_at):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        clock_in_at=clock_in_at,
        clock_out_at=None,
        source="kiosk",
        clock_in_photo_url=None,
        clock_out_photo_url=None,
        clock_in_lat=None,
        clock_in_lng=None,
        clock_out_lat=None,
        clock_out_lng=None,
        scheduled_entry_id=None,   # no linked shift -> no scheduled basis
        break_minutes=0,
        notes=None,
        worked_minutes=None,
        flags=None,
    )


def _make_casual_staff():
    # working_arrangement != "fixed" -> no fixed-end basis -> safety-net cap.
    return SimpleNamespace(
        id=uuid.uuid4(),
        working_arrangement="casual",
        reporting_to=None,
        phone="+64210000000",
        email="casual@example.com",
        first_name="Cas",
        name="Cas Ual",
    )


class TestCasualNoScheduleCap:
    """A no-schedule (casual) entry is closed via the elapsed-cap fallback."""

    @pytest.mark.asyncio
    async def test_casual_entry_closed_via_safety_net_cap(self):
        """**Validates: Requirements 5.1, 5.2, 9.4**

        Drives the REAL ``_auto_close_entry`` for a casual entry with no
        scheduled shift and ``working_arrangement != "fixed"``. With the staff
        notification dispatched, the entry closes at ``clock_in_at +
        after_hours`` (the safety-net cap), clamped to ``now``; the staff member
        is notified exactly once and the closer returns ``True``.
        """
        clock_in = _utc(2024, 1, 1, 8, 0)
        now = _utc(2024, 1, 3, 12, 0)   # ~52h open — far past the 14h cap
        entry = _make_closer_entry(clock_in_at=clock_in)
        staff = _make_casual_staff()

        session = MagicMock()
        # Only StaffMember.get is reached (scheduled_entry_id is None).
        session.get = AsyncMock(return_value=staff)
        session.flush = AsyncMock()
        session.begin_nested = MagicMock(side_effect=lambda: _AsyncCM())

        policy = {
            "auto_clock_out_enabled": True,
            "auto_clock_out_after_hours": 14,
            "auto_clock_out_grace_minutes": 15,
            "missed_clock_out_alert_channels": ["sms"],
        }

        with patch(STAFF_NOTIFY, new_callable=AsyncMock,
                   return_value=True) as m_staff, \
             patch(RESOLVE_MANAGER, new_callable=AsyncMock, return_value=None), \
             patch(MANAGER_NOTIFY, new_callable=AsyncMock), \
             patch(WRITE_AUDIT, new_callable=AsyncMock, return_value=uuid.uuid4()):
            result = await _auto_close_entry(session, entry, policy, now)

        # Finalised closure (not deferred).
        assert result is True
        # Closed via the safety-net cap (no scheduled/fixed basis), well before
        # `now`, so the cap (not the clamp-to-now) determines the timestamp.
        assert entry.clock_out_at == clock_in + timedelta(hours=14)
        assert entry.clock_out_at >= entry.clock_in_at   # never before clock-in
        assert entry.clock_out_at <= now                 # never in the future
        # Flagged with the cap basis for review.
        assert entry.flags["auto_clocked_out"] is True
        assert entry.flags["auto_clock_out_reason"] == "safety_net_cap"
        # Staff notified exactly once (gates + notifies once).
        m_staff.assert_awaited_once()
