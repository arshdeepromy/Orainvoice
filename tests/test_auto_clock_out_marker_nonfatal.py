"""Unit tests for Task 4.4 — the auto clock-out review-marker write is non-fatal.

Property 14 (REQ 3.4): when the ``flags`` review-marker write raises inside the
``begin_nested`` savepoint, ``_auto_close_entry`` must still finalise the
closure — ``clock_out_at`` and ``worked_minutes`` stay set, the function returns
``True`` (the entry is NOT left open just because the marker failed) — and the
failure is logged.

The closer (``app.tasks.scheduled._auto_close_entry``) wraps the marker write in
``async with session.begin_nested():`` and catches any exception, logging a
``auto_clock_out: marker write failed ...`` warning. We exercise two ways the
marker write can fail:

  * the savepoint itself fails to open (``begin_nested().__aenter__`` raises);
  * the flush inside the savepoint raises (after the close-column flush has
    already succeeded).

In both cases the earlier ``session.flush()`` for the close columns succeeds, so
the closure must remain intact.

The staff-notify gate, the manager best-effort notify, the manager resolution
and the audit-log write are patched out so the test isolates the marker path.

**Validates: Requirements 3.4**
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.scheduled import _auto_close_entry


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_entry(*, clock_in_at=None, break_minutes=0):
    """A TimeClockEntry-shaped object carrying every attribute read by
    ``_auto_close_entry`` / ``_entry_to_dict``. ``scheduled_entry_id`` is None so
    no ``ScheduleEntry`` lookup happens.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=uuid.uuid4(),
        clock_in_at=clock_in_at or _utc(2024, 1, 1, 8, 0),
        clock_out_at=None,
        worked_minutes=None,
        break_minutes=break_minutes,
        source="kiosk",
        clock_in_photo_url=None,
        clock_out_photo_url=None,
        clock_in_lat=None,
        clock_in_lng=None,
        clock_out_lat=None,
        clock_out_lng=None,
        scheduled_entry_id=None,
        notes=None,
        flags=None,
    )


def _make_staff():
    # working_arrangement != "fixed" so no fixed-end lookup -> safety-net cap basis.
    return SimpleNamespace(
        id=uuid.uuid4(),
        working_arrangement="casual",
        availability_schedule=None,
        first_name="Sam",
        name="Sam Smith",
        phone="+64211234567",
        email="sam@example.com",
    )


class _FakeNested:
    """Async context manager standing in for ``session.begin_nested()``."""

    def __init__(self, *, enter_error=None):
        self._enter_error = enter_error

    async def __aenter__(self):
        if self._enter_error is not None:
            raise self._enter_error
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False  # never suppress — let the marker error propagate to the except


class _FakeSession:
    """Minimal async session.

    ``get`` returns the staff member (the only lookup that happens here, since
    the entry has no ``scheduled_entry_id``). ``flush`` succeeds for the
    close-column flush; ``flush_error_on_call`` lets a later flush (the one
    inside the savepoint) raise. ``nested_enter_error`` makes opening the
    savepoint itself fail.
    """

    def __init__(self, *, staff, nested_enter_error=None, flush_error_on_call=None):
        self._staff = staff
        self._nested_enter_error = nested_enter_error
        self._flush_error_on_call = flush_error_on_call
        self.flush_calls = 0

    async def get(self, model, pk):
        return self._staff

    async def flush(self):
        self.flush_calls += 1
        if (
            self._flush_error_on_call is not None
            and self.flush_calls == self._flush_error_on_call
        ):
            raise RuntimeError("marker flush boom")

    def begin_nested(self):
        return _FakeNested(enter_error=self._nested_enter_error)


_POLICY = {
    "auto_clock_out_enabled": True,
    "auto_clock_out_after_hours": 14,
    "auto_clock_out_grace_minutes": 15,
    "missed_clock_out_alert_channels": ["sms"],
}

# Clock-in at 08:00, "now" well past the cap so the entry is closeable.
_CLOCK_IN = _utc(2024, 1, 1, 8, 0)
_NOW = _utc(2024, 1, 3, 0, 0)


def _patches():
    """Patch the collaborators so the test isolates the marker-write path:
    staff notify always succeeds (gate open), manager resolution returns None,
    manager notify and the audit write are no-ops.
    """
    return (
        patch(
            "app.tasks.scheduled._notify_staff_auto_clock_out",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.tasks.scheduled._notify_manager_auto_clock_out",
            new_callable=AsyncMock,
        ),
        patch(
            "app.tasks.scheduled._resolve_manager",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("app.core.audit.write_audit_log", new_callable=AsyncMock),
    )


class TestMarkerWriteNonFatal:
    """Property 14 — a failing marker write never leaves the entry open."""

    @pytest.mark.asyncio
    async def test_savepoint_open_failure_keeps_closure(self, caplog):
        """``begin_nested().__aenter__`` raises -> closure intact, returns True, logged."""
        entry = _make_entry(clock_in_at=_CLOCK_IN, break_minutes=30)
        staff = _make_staff()
        session = _FakeSession(
            staff=staff,
            nested_enter_error=RuntimeError("savepoint boom"),
        )

        p_staff, p_mgr, p_resolve, p_audit = _patches()
        with p_staff, p_mgr, p_resolve, p_audit as mock_audit:
            with caplog.at_level(logging.WARNING, logger="app.tasks.scheduled"):
                result = await _auto_close_entry(session, entry, _POLICY, _NOW)

        # Closure finalised despite the marker failure.
        assert result is True
        assert entry.clock_out_at is not None
        assert entry.worked_minutes is not None
        assert entry.worked_minutes >= 0
        # The close-column flush ran (savepoint open failed before any inner flush).
        assert session.flush_calls == 1
        # Audit still written — the closure is a real, recorded close.
        mock_audit.assert_awaited_once()
        # Failure was logged.
        assert any(
            "marker write failed" in rec.getMessage() for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_inner_flush_failure_keeps_closure(self, caplog):
        """The flush INSIDE the savepoint raises -> closure intact, returns True, logged."""
        entry = _make_entry(clock_in_at=_CLOCK_IN, break_minutes=0)
        staff = _make_staff()
        # 1st flush = close columns (succeeds); 2nd flush = inside savepoint (raises).
        session = _FakeSession(staff=staff, flush_error_on_call=2)

        p_staff, p_mgr, p_resolve, p_audit = _patches()
        with p_staff, p_mgr, p_resolve, p_audit as mock_audit:
            with caplog.at_level(logging.WARNING, logger="app.tasks.scheduled"):
                result = await _auto_close_entry(session, entry, _POLICY, _NOW)

        assert result is True
        assert entry.clock_out_at is not None
        assert entry.worked_minutes is not None
        # Both the close flush and the (failing) marker flush were attempted.
        assert session.flush_calls == 2
        mock_audit.assert_awaited_once()
        assert any(
            "marker write failed" in rec.getMessage() for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_worked_minutes_matches_expected_on_marker_failure(self):
        """The close columns are computed from the resolved end, not affected by
        the marker failure: worked_minutes == elapsed - break, floored at zero."""
        from app.modules.time_clock.service import _compute_worked_minutes

        entry = _make_entry(clock_in_at=_CLOCK_IN, break_minutes=45)
        staff = _make_staff()
        session = _FakeSession(
            staff=staff,
            nested_enter_error=RuntimeError("savepoint boom"),
        )

        p_staff, p_mgr, p_resolve, p_audit = _patches()
        with p_staff, p_mgr, p_resolve, p_audit:
            result = await _auto_close_entry(session, entry, _POLICY, _NOW)

        assert result is True
        expected = _compute_worked_minutes(
            clock_in_at=entry.clock_in_at,
            clock_out_at=entry.clock_out_at,
            break_minutes=45,
        )
        assert entry.worked_minutes == expected
