"""Property-based test for Task 5.3 — auto-close threshold gate.

# Feature: auto-clock-out, Task 5.3 — hourly task threshold gate

**Validates: Requirements 2.1**

The task under test is :func:`app.tasks.scheduled.check_missed_clock_outs_task`.
For each open ``time_clock_entries`` row, once the org policy has
``auto_clock_out_enabled`` true, it computes::

    open_hours = (now - entry.clock_in_at).total_seconds() / 3600.0

and only calls :func:`_auto_close_entry` (the single-entry closer) when
``open_hours >= int(policy["auto_clock_out_after_hours"])``. The pinned-down
design correctness property is:

* **Property 2 — Threshold gate:** an open entry is auto-closed *only* when its
  open duration ``(now - clock_in_at)`` is at least
  ``auto_clock_out_after_hours``.

This test exercises ONLY the gate in the hourly task, so the closer itself and
all I/O collaborators are mocked at their reference sites:

* ``app.core.database.async_session_factory`` → a session double whose
  ``begin()`` is a no-op async-context-manager savepoint and whose
  ``execute(...)`` returns the single generated open entry.
* ``app.core.redis.redis_pool`` → ``get`` returns ``None`` (never deduped) so
  the gate is always reached; ``set`` is a no-op.
* ``app.tasks.scheduled._load_org_clock_in_policy`` → a policy with
  ``auto_clock_out_enabled`` true, the generated ``auto_clock_out_after_hours``,
  and a very large ``missed_clock_out_reminder_hours`` so a below-threshold
  entry short-circuits the reminder branch (keeping the test focused on the
  gate).
* ``app.tasks.scheduled._auto_close_entry`` → an ``AsyncMock`` returning
  ``True`` (a finalised closure); we assert only on *whether* it was called.

The hourly task calls ``datetime.now(timezone.utc)`` itself, so each generated
entry's ``clock_in_at`` is placed a guaranteed margin (>= 15 minutes) above or
below the threshold relative to a reference ``now`` captured just before the
run. The sub-second gap between that reference and the task's own ``now`` can
never cross a 15-minute margin, so the IFF assertion is robust.

This file owns its own doubles and does not depend on the fixtures of the other
Task 5 test files (5.2/5.4/5.5/5.6), which target the same task in parallel.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.tasks.scheduled import check_missed_clock_outs_task

# Patch targets (all imported INSIDE the task body, so patch at source module).
ASYNC_SESSION_FACTORY = "app.core.database.async_session_factory"
REDIS_POOL = "app.core.redis.redis_pool"
LOAD_POLICY = "app.tasks.scheduled._load_org_clock_in_policy"
AUTO_CLOSE = "app.tasks.scheduled._auto_close_entry"

# A 15-minute floor on the distance from the threshold. The task recomputes
# ``now`` microseconds after our reference, which can never cross this margin.
MARGIN_MINUTES = 15

PBT_SETTINGS = settings(max_examples=200, deadline=None)


class _AsyncCM:
    """Minimal no-op async context manager (stands in for ``session.begin()``)."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _SessionFactoryCM:
    """Async context manager returned by ``async_session_factory()``."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


def _make_entry(clock_in_at):
    """An open TimeClockEntry double carrying the fields the gate reads."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        clock_in_at=clock_in_at,
        clock_out_at=None,
    )


def _make_session(entries):
    """Session double: ``execute(...)`` yields the generated entry list via
    ``.scalars().all()``, ``begin()`` is a no-op savepoint."""
    scalars = SimpleNamespace(all=lambda: list(entries))
    result = SimpleNamespace(scalars=lambda: scalars)

    session = SimpleNamespace()
    session.execute = AsyncMock(return_value=result)
    session.begin = lambda: _AsyncCM()
    session.get = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    return session


def _make_redis():
    redis = SimpleNamespace()
    redis.get = AsyncMock(return_value=None)   # never deduped -> gate reached
    redis.set = AsyncMock()
    return redis


async def _run_gate(*, clock_in_at, after_hours):
    """Run the hourly task over a single open entry and report whether the
    closer was invoked."""
    entry = _make_entry(clock_in_at)
    session = _make_session([entry])
    redis = _make_redis()
    policy = {
        "auto_clock_out_enabled": True,
        "auto_clock_out_after_hours": after_hours,
        # Huge reminder threshold so a below-cap entry short-circuits the
        # reminder branch without touching staff/redis lookups.
        "missed_clock_out_reminder_hours": 10 ** 9,
        "missed_clock_out_alert_enabled": False,
        "missed_clock_out_alert_channels": ["sms"],
    }

    with patch(ASYNC_SESSION_FACTORY,
               MagicMock(return_value=_SessionFactoryCM(session))), \
         patch(REDIS_POOL, redis), \
         patch(LOAD_POLICY, new_callable=AsyncMock, return_value=policy), \
         patch(AUTO_CLOSE, new_callable=AsyncMock, return_value=True) as m_close:
        await check_missed_clock_outs_task()

    return m_close.await_count > 0


@st.composite
def gate_scenario(draw):
    """Generate an ``after_hours`` cap and an open duration placed a guaranteed
    >= 15-minute margin clearly above or clearly below that cap."""
    after_hours = draw(st.integers(min_value=1, max_value=48))
    cap_minutes = after_hours * 60
    above = draw(st.booleans())
    gap = draw(st.integers(min_value=MARGIN_MINUTES, max_value=600))
    if above:
        open_minutes = cap_minutes + gap
    else:
        open_minutes = max(0, cap_minutes - gap)
    return {
        "after_hours": after_hours,
        "open_minutes": open_minutes,
        "expected_close": above,
    }


@given(scenario=gate_scenario())
@PBT_SETTINGS
def test_threshold_gate(scenario):
    """Property 2: the hourly task calls the closer IFF the entry's open
    duration ``(now - clock_in_at)`` is at least ``auto_clock_out_after_hours``.

    **Validates: Requirements 2.1**
    """
    # Reference now captured just before the run; the task's own ``now`` is at
    # or after this, by less than the 15-minute margin.
    ref_now = datetime.now(timezone.utc)
    clock_in_at = ref_now - timedelta(minutes=scenario["open_minutes"])

    closed = asyncio.run(
        _run_gate(clock_in_at=clock_in_at, after_hours=scenario["after_hours"])
    )

    assert closed is scenario["expected_close"]


# ---------------------------------------------------------------------------
# Example-based companions (clear-cut above / below / just-over-threshold).
# ---------------------------------------------------------------------------

class TestThresholdGateExamples:
    @pytest.mark.asyncio
    async def test_well_above_threshold_closes(self):
        """An entry open far past the cap is auto-closed."""
        after_hours = 14
        clock_in_at = datetime.now(timezone.utc) - timedelta(hours=after_hours + 10)
        assert await _run_gate(clock_in_at=clock_in_at, after_hours=after_hours) is True

    @pytest.mark.asyncio
    async def test_well_below_threshold_does_not_close(self):
        """An entry open well under the cap is NOT auto-closed."""
        after_hours = 14
        clock_in_at = datetime.now(timezone.utc) - timedelta(hours=after_hours - 5)
        assert await _run_gate(clock_in_at=clock_in_at, after_hours=after_hours) is False

    @pytest.mark.asyncio
    async def test_just_over_threshold_closes(self):
        """An entry open just past the cap (>= 15 min margin) is auto-closed."""
        after_hours = 8
        clock_in_at = datetime.now(timezone.utc) - timedelta(
            hours=after_hours, minutes=30
        )
        assert await _run_gate(clock_in_at=clock_in_at, after_hours=after_hours) is True
