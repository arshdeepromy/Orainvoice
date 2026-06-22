"""Unit tests for Task 4.5 — staff notification gates closure, manager best-effort.

Example-based (pytest) coverage of the gating contract enforced by
``app.tasks.scheduled._auto_close_entry(session, entry, policy, now)``:

  **Property 8: Staff notification gates closure; manager best-effort** — the
  entry is closed only after the staff notify is dispatched; a failed staff
  notify DEFERS (returns ``False``, writes nothing — no ``clock_out_at``, no
  audit); a failed manager notify never reverts the closure (still returns
  ``True`` with the closure intact + audited).

The closer orchestrates several collaborators that are tested in isolation
elsewhere (the end-time resolver, the two notification helpers, the manager
resolver, the audit writer, the worked-minutes/entry-dict helpers). Here we
patch those collaborators at their reference sites so the test exercises ONLY
the gating + best-effort control flow of ``_auto_close_entry`` itself:

  - ``app.tasks.scheduled._resolve_auto_clock_out_end`` (pure, fixed end)
  - ``app.tasks.scheduled._notify_staff_auto_clock_out`` (the gate)
  - ``app.tasks.scheduled._notify_manager_auto_clock_out`` (best-effort)
  - ``app.tasks.scheduled._resolve_manager`` (returns a manager so the
    manager-notify path runs)
  - ``app.core.audit.write_audit_log`` (lazy-imported inside the closer)
  - ``app.modules.time_clock.service._compute_worked_minutes`` / ``_entry_to_dict``
    (lazy-imported inside the closer)

``session.get`` (StaffMember lookup), ``session.flush`` and the
``session.begin_nested()`` savepoint async-context-manager are mocked.

**Validates: Requirements 4.1, 4.2, 4.3, 4.5**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tasks.scheduled import _auto_close_entry

# Patch targets — referenced from inside ``_auto_close_entry``.
RESOLVE_END = "app.tasks.scheduled._resolve_auto_clock_out_end"
NOTIFY_STAFF = "app.tasks.scheduled._notify_staff_auto_clock_out"
NOTIFY_MANAGER = "app.tasks.scheduled._notify_manager_auto_clock_out"
RESOLVE_MANAGER = "app.tasks.scheduled._resolve_manager"
WRITE_AUDIT = "app.core.audit.write_audit_log"
COMPUTE_WORKED = "app.modules.time_clock.service._compute_worked_minutes"
ENTRY_TO_DICT = "app.modules.time_clock.service._entry_to_dict"


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


CLOCK_IN = _utc(2024, 1, 1, 8, 0)
END = _utc(2024, 1, 1, 17, 0)
NOW = _utc(2024, 1, 2, 12, 0)
POLICY = {
    "auto_clock_out_after_hours": 14,
    "auto_clock_out_grace_minutes": 15,
    "missed_clock_out_alert_channels": ["sms"],
}


class _AsyncCM:
    """Minimal async context manager standing in for ``begin_nested()``."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


def _make_entry():
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        scheduled_entry_id=None,   # no scheduled shift -> skip ScheduleEntry.get
        clock_in_at=CLOCK_IN,
        clock_out_at=None,
        worked_minutes=None,
        break_minutes=0,
        flags=None,
    )


def _make_staff():
    # working_arrangement != "fixed" -> _fixed_end_minutes_for_date is skipped.
    return SimpleNamespace(
        id=uuid.uuid4(),
        working_arrangement="casual",
        phone="+64211234567",
        email="sam@example.com",
        first_name="Sam",
        name="Sam Smith",
    )


def _make_session(staff):
    session = AsyncMock()
    # Only StaffMember.get is reached (scheduled_entry_id is None).
    session.get = AsyncMock(return_value=staff)
    session.flush = AsyncMock()
    # begin_nested() must return an async context manager, not a coroutine.
    session.begin_nested = MagicMock(return_value=_AsyncCM())
    return session


# ---------------------------------------------------------------------------
# REQ 4.1 / 4.2 — staff notify GATES the closure
# ---------------------------------------------------------------------------

class TestStaffNotifyGatesClosure:
    @pytest.mark.asyncio
    async def test_failed_staff_notify_defers_writes_nothing(self):
        """Staff notify False -> return False, entry stays open, no audit (REQ 4.2)."""
        entry = _make_entry()
        staff = _make_staff()
        session = _make_session(staff)

        with patch(RESOLVE_END, return_value=END), \
             patch(NOTIFY_STAFF, new_callable=AsyncMock, return_value=False) as m_staff, \
             patch(NOTIFY_MANAGER, new_callable=AsyncMock) as m_mgr, \
             patch(RESOLVE_MANAGER, new_callable=AsyncMock) as m_resolve_mgr, \
             patch(WRITE_AUDIT, new_callable=AsyncMock) as m_audit, \
             patch(COMPUTE_WORKED, return_value=540) as m_worked, \
             patch(ENTRY_TO_DICT, return_value={}):
            result = await _auto_close_entry(session, entry, POLICY, NOW)

        assert result is False
        # The gate was attempted ...
        m_staff.assert_awaited_once()
        # ... and the closure was NOT performed.
        assert entry.clock_out_at is None
        assert entry.worked_minutes is None
        m_worked.assert_not_called()
        m_audit.assert_not_awaited()
        # No manager notification on a deferral.
        m_resolve_mgr.assert_not_awaited()
        m_mgr.assert_not_awaited()
        # Nothing flushed for a deferred entry.
        session.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_closure_happens_only_after_staff_notify_dispatched(self):
        """Happy path: staff notify True -> entry closed + audited, returns True."""
        entry = _make_entry()
        staff = _make_staff()
        manager = SimpleNamespace(id=uuid.uuid4(), phone="+64217654321", email=None)
        session = _make_session(staff)

        with patch(RESOLVE_END, return_value=END), \
             patch(NOTIFY_STAFF, new_callable=AsyncMock, return_value=True) as m_staff, \
             patch(NOTIFY_MANAGER, new_callable=AsyncMock) as m_mgr, \
             patch(RESOLVE_MANAGER, new_callable=AsyncMock, return_value=manager), \
             patch(WRITE_AUDIT, new_callable=AsyncMock) as m_audit, \
             patch(COMPUTE_WORKED, return_value=540), \
             patch(ENTRY_TO_DICT, return_value={}):
            result = await _auto_close_entry(session, entry, POLICY, NOW)

        assert result is True
        m_staff.assert_awaited_once()
        # Closure performed.
        assert entry.clock_out_at == END
        assert entry.worked_minutes == 540
        # Review marker written.
        assert entry.flags["auto_clocked_out"] is True
        assert entry.flags["needs_review"] is True
        # Audit row written for the closure.
        m_audit.assert_awaited_once()
        # Manager notified (best-effort) after closure.
        m_mgr.assert_awaited_once()


# ---------------------------------------------------------------------------
# REQ 4.3 / 4.5 — manager notify is best-effort and never reverts the closure
# ---------------------------------------------------------------------------

class TestManagerNotifyBestEffort:
    @pytest.mark.asyncio
    async def test_manager_notify_raising_does_not_revert_closure(self):
        """Manager notify raising -> closure intact, still returns True (REQ 4.5)."""
        entry = _make_entry()
        staff = _make_staff()
        manager = SimpleNamespace(id=uuid.uuid4(), phone="+64217654321", email=None)
        session = _make_session(staff)

        with patch(RESOLVE_END, return_value=END), \
             patch(NOTIFY_STAFF, new_callable=AsyncMock, return_value=True), \
             patch(NOTIFY_MANAGER, new_callable=AsyncMock,
                   side_effect=RuntimeError("manager sms down")) as m_mgr, \
             patch(RESOLVE_MANAGER, new_callable=AsyncMock, return_value=manager), \
             patch(WRITE_AUDIT, new_callable=AsyncMock) as m_audit, \
             patch(COMPUTE_WORKED, return_value=540), \
             patch(ENTRY_TO_DICT, return_value={}):
            result = await _auto_close_entry(session, entry, POLICY, NOW)

        # The manager-notify failure must NOT propagate ...
        assert result is True
        # ... and the closure remains intact + audited.
        assert entry.clock_out_at == END
        assert entry.worked_minutes == 540
        m_audit.assert_awaited_once()
        m_mgr.assert_awaited_once()
