"""Property-based test for Task 5.2 — disabled means never closed.

# Feature: auto-clock-out, Task 5.2 — task-level invariant

**Validates: Requirements 1.4, 9.2**

The function under test is the hourly scheduled task
:func:`app.tasks.scheduled.check_missed_clock_outs_task`. Its auto-close branch
is opt-in: it only runs when the org's ``clock_in_policy`` has
``auto_clock_out_enabled`` set to ``True``.

  **Property 1: Disabled means never closed** — for any set of open entries, if
  every org's ``auto_clock_out_enabled`` is ``False`` (the default), the task
  never closes any entry: ``_auto_close_entry`` is never invoked, no entry's
  ``clock_out_at`` (or ``worked_minutes`` / auto-close ``flags``) is set, and the
  run reports zero auto-closures and zero deferrals. The alert/reminder path is
  unchanged.

The task lazily imports its collaborators inside the function body
(``from app.core.database import async_session_factory``,
``from app.core.redis import redis_pool``, the SMS/email senders, the ORM
models), so those are patched at their SOURCE modules. The pure per-entry policy
loader and the single-entry closer are module-level in ``app.tasks.scheduled``
and are patched there:

  - ``app.core.database.async_session_factory`` — yields a mocked session whose
    ``begin()`` is an async context manager and whose ``execute`` returns the
    generated open entries.
  - ``app.core.redis.redis_pool`` — get/set stubbed.
  - ``app.tasks.scheduled._load_org_clock_in_policy`` — forced to return a policy
    with ``auto_clock_out_enabled=False`` for every org.
  - ``app.tasks.scheduled._auto_close_entry`` — a spy asserted to NEVER be called.
  - ``app.integrations.sms_sender.send_sms`` / ``app.integrations.email_sender.send_email``
    — stubbed so the (unchanged) reminder path never actually sends.

This test lives in its own module and builds its own mocks (no shared fixtures)
so it never clobbers the parallel task-level tests for the same function.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Patch targets (lazy-imported inside the task / module-level helpers).
SESSION_FACTORY = "app.core.database.async_session_factory"
REDIS_POOL = "app.core.redis.redis_pool"
LOAD_POLICY = "app.tasks.scheduled._load_org_clock_in_policy"
AUTO_CLOSE = "app.tasks.scheduled._auto_close_entry"
SEND_SMS = "app.integrations.sms_sender.send_sms"
SEND_EMAIL = "app.integrations.email_sender.send_email"


# ---------------------------------------------------------------------------
# Hypothesis settings — the task body is exercised over many generated batches.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies — varied open entries + varied (always-disabled) org policies.
# ---------------------------------------------------------------------------

channels_st = st.lists(
    st.sampled_from(["sms", "email"]), min_size=0, max_size=2, unique=True
)


@st.composite
def disabled_scenario(draw):
    """A batch of open entries, each in an org whose policy disables auto-close.

    ``open_hours`` is generated across a wide band (0..96h) so entries fall both
    below and above the reminder threshold, exercising both the early-skip and
    the (unchanged) reminder path — neither of which may ever close an entry.
    """
    now = datetime.now(timezone.utc)
    n = draw(st.integers(min_value=1, max_value=8))
    entries = []
    policies: dict = {}
    for _ in range(n):
        org_id = uuid.uuid4()
        open_hours = draw(st.floats(min_value=0.0, max_value=96.0))
        clock_in_at = now - timedelta(hours=open_hours)
        entry = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=uuid.uuid4(),
            clock_in_at=clock_in_at,
            clock_out_at=None,
            worked_minutes=None,
            break_minutes=draw(st.integers(min_value=0, max_value=120)),
            flags=None,
        )
        entries.append(entry)
        # Policy: auto-close DISABLED, but other knobs vary freely so the
        # invariant is not accidentally tied to a single policy shape.
        policies[org_id] = {
            "auto_clock_out_enabled": False,
            "auto_clock_out_after_hours": draw(st.integers(min_value=1, max_value=48)),
            "auto_clock_out_grace_minutes": draw(st.integers(min_value=0, max_value=240)),
            "missed_clock_out_alert_enabled": draw(st.booleans()),
            "missed_clock_out_alert_channels": draw(channels_st),
            "missed_clock_out_reminder_hours": draw(st.integers(min_value=1, max_value=24)),
        }
    return entries, policies


# ---------------------------------------------------------------------------
# Mock builders.
# ---------------------------------------------------------------------------

def _make_async_cm(return_value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=return_value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_session(entries):
    """A mocked AsyncSession: begin() is an async CM, execute() yields entries."""
    session = MagicMock()
    session.begin = MagicMock(return_value=_make_async_cm(None))

    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = entries
    result.scalars.return_value = scalars
    session.execute = AsyncMock(return_value=result)

    # Reminder branch fetches the StaffMember; give a fully-contactable person
    # so the (unchanged) reminder path can proceed without touching the entry.
    staff = SimpleNamespace(
        id=uuid.uuid4(),
        phone="+64211234567",
        email="sam@example.com",
        first_name="Sam",
        name="Sam Smith",
    )
    session.get = AsyncMock(return_value=staff)
    return session


def _make_session_factory(session):
    return MagicMock(return_value=_make_async_cm(session))


# ---------------------------------------------------------------------------
# Property 1: Disabled means never closed.
# ---------------------------------------------------------------------------

@given(scenario=disabled_scenario())
@PBT_SETTINGS
def test_disabled_policy_never_closes_any_entry(scenario):
    """Property 1: with ``auto_clock_out_enabled`` false, no entry is closed.

    **Validates: Requirements 1.4, 9.2**
    """
    entries, policies = scenario

    async def _run():
        from app.tasks.scheduled import check_missed_clock_outs_task

        session = _make_session(entries)
        factory = _make_session_factory(session)

        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        async def _policy(_session, org_id, _cache):
            return policies[org_id]

        auto_close_spy = AsyncMock(return_value=True)

        with patch(SESSION_FACTORY, factory), \
             patch(REDIS_POOL, redis), \
             patch(LOAD_POLICY, new=AsyncMock(side_effect=_policy)), \
             patch(AUTO_CLOSE, new=auto_close_spy), \
             patch(SEND_SMS, new_callable=AsyncMock), \
             patch(SEND_EMAIL, new_callable=AsyncMock):
            summary = await check_missed_clock_outs_task()

        return summary, auto_close_spy

    summary, auto_close_spy = asyncio.run(_run())

    # The run must not have errored out.
    assert "error" not in summary, summary

    # The auto-close branch was never entered for a disabled org.
    auto_close_spy.assert_not_called()

    # No entry was closed or even partially mutated by an auto-close.
    for entry in entries:
        assert entry.clock_out_at is None
        assert entry.worked_minutes is None
        assert entry.flags is None

    # And the summary reflects zero auto-close activity.
    assert summary["auto_closed"] == 0
    assert summary["deferred"] == 0
    assert summary["entries_checked"] == len(entries)
