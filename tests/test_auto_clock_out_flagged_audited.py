"""Property/integration test for Task 4.3 — flagged + audited close path.

Drives :func:`app.tasks.scheduled._auto_close_entry` to the *finalised close*
path and verifies the two durable side effects required by REQ 3.1/3.2/3.3:

  * **Property 7 — Flagged + audited:** once an entry is auto-closed it carries
    a ``flags`` review marker (``auto_clocked_out is True`` plus a non-empty
    ``auto_clock_out_reason``) AND a ``time_clock.auto_clock_out`` audit row is
    written, system-attributable (``user_id=None``) with both a ``before`` and
    an ``after`` snapshot.

To reach the close path without a database the test:
  * patches ``_notify_staff_auto_clock_out`` → ``True`` (the staff notify GATES
    the closure; ``True`` means "dispatched", so the entry is finalised),
  * patches ``_resolve_manager`` / ``_notify_manager_auto_clock_out`` (best-effort
    manager notify, irrelevant to this property),
  * spies on ``write_audit_log`` at its source module (it is lazily imported
    inside the function),
  * mocks ``session.get`` (StaffMember lookup), ``session.flush``, and
    ``session.begin_nested`` (the marker savepoint, an async context manager).

The pure resolver (``_resolve_auto_clock_out_end``), ``_compute_worked_minutes``
and ``_entry_to_dict`` run for real so the snapshots match the production close.

**Validates: Requirements 3.1, 3.2, 3.3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.tasks import scheduled
from app.tasks.scheduled import _auto_close_entry

AUDIT_TARGET = "app.core.audit.write_audit_log"
STAFF_NOTIFY = "app.tasks.scheduled._notify_staff_auto_clock_out"
MANAGER_NOTIFY = "app.tasks.scheduled._notify_manager_auto_clock_out"
RESOLVE_MANAGER = "app.tasks.scheduled._resolve_manager"


PBT_SETTINGS = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class _AsyncCM:
    """Minimal async context manager standing in for ``session.begin_nested``."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_entry(*, clock_in_at, break_minutes=0, flags=None):
    """A TimeClockEntry-shaped object with every attr ``_entry_to_dict`` reads.

    ``scheduled_entry_id`` is ``None`` so the closer takes the safety-net-cap
    basis without loading a ScheduleEntry.
    """
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
        scheduled_entry_id=None,
        break_minutes=break_minutes,
        notes=None,
        worked_minutes=None,
        flags=flags,
    )


def _make_session(staff):
    """An AsyncSession-shaped mock for the no-DB close path."""
    session = MagicMock()
    # Only StaffMember is fetched (scheduled_entry_id is None).
    session.get = AsyncMock(return_value=staff)
    session.flush = AsyncMock()
    session.begin_nested = MagicMock(side_effect=lambda: _AsyncCM())
    return session


def _make_staff():
    # working_arrangement != "fixed" -> no fixed-end basis, safety-net cap used.
    return SimpleNamespace(
        id=uuid.uuid4(),
        working_arrangement="casual",
        reporting_to=None,
        phone="+64210000000",
        email="staff@example.com",
        first_name="Sam",
        name="Sam Smith",
    )


async def _drive_close(entry, *, after_hours, grace, now):
    """Run ``_auto_close_entry`` through the finalised-close path and return the
    spied ``write_audit_log`` mock for assertions."""
    staff = _make_staff()
    session = _make_session(staff)
    policy = {
        "auto_clock_out_after_hours": after_hours,
        "auto_clock_out_grace_minutes": grace,
        "missed_clock_out_alert_channels": ["sms"],
    }

    with patch(STAFF_NOTIFY, new_callable=AsyncMock, return_value=True), \
         patch(RESOLVE_MANAGER, new_callable=AsyncMock, return_value=None), \
         patch(MANAGER_NOTIFY, new_callable=AsyncMock) as mock_mgr, \
         patch(AUDIT_TARGET, new_callable=AsyncMock,
               return_value=uuid.uuid4()) as mock_audit:
        result = await _auto_close_entry(session, entry, policy, now)

    return result, mock_audit, mock_mgr


# ---------------------------------------------------------------------------
# Property 7 — Flagged + audited (Hypothesis)
# ---------------------------------------------------------------------------

class TestFlaggedAndAudited:
    """Property 7: a finalised close is both flagged for review and audited."""

    @given(
        open_hours=st.integers(min_value=1, max_value=72),
        after_hours=st.integers(min_value=1, max_value=48),
        grace=st.integers(min_value=0, max_value=240),
        break_minutes=st.integers(min_value=0, max_value=120),
        existing_flags=st.one_of(
            st.none(),
            st.just({"some_prior": "value"}),
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_closed_entry_is_flagged_and_audited(
        self, open_hours, after_hours, grace, break_minutes, existing_flags,
    ):
        """For any closeable open entry, once ``_auto_close_entry`` finalises:

        - it returns ``True`` (closed, not deferred),
        - ``entry.flags['auto_clocked_out'] is True`` with a non-empty reason,
        - a single ``time_clock.auto_clock_out`` audit row is written with
          ``user_id=None`` and both before/after snapshots present.

        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        clock_in = _utc(2024, 1, 1, 8, 0)
        now = clock_in + timedelta(hours=open_hours)
        entry = _make_entry(
            clock_in_at=clock_in,
            break_minutes=break_minutes,
            flags=dict(existing_flags) if existing_flags else None,
        )

        result, mock_audit, _ = await _drive_close(
            entry, after_hours=after_hours, grace=grace, now=now,
        )

        # Closed, not deferred.
        assert result is True
        assert entry.clock_out_at is not None

        # --- Flagged for review (REQ 3.1, 3.2) ---
        assert entry.flags is not None
        assert entry.flags["auto_clocked_out"] is True
        assert entry.flags.get("auto_clock_out_reason")  # non-empty reason
        assert entry.flags.get("needs_review") is True
        # Any pre-existing flag keys are preserved (marker is merged in).
        if existing_flags:
            assert entry.flags["some_prior"] == "value"

        # --- Audited, system-attributable, with snapshots (REQ 3.3) ---
        mock_audit.assert_awaited_once()
        kwargs = mock_audit.await_args.kwargs
        assert kwargs["action"] == "time_clock.auto_clock_out"
        assert kwargs["user_id"] is None
        assert kwargs["entity_type"] == "time_clock_entry"
        assert kwargs["entity_id"] == entry.id
        assert kwargs["org_id"] == entry.org_id
        assert kwargs["before_value"] is not None
        assert kwargs["after_value"] is not None
        # before captures the still-open entry; after captures the close + basis.
        assert kwargs["before_value"]["clock_out_at"] is None
        assert kwargs["after_value"]["clock_out_at"] is not None
        assert kwargs["after_value"]["basis"] == entry.flags["auto_clock_out_reason"]


# ---------------------------------------------------------------------------
# Property 7 — focused example (deterministic safety-net-cap basis)
# ---------------------------------------------------------------------------

class TestFlaggedAndAuditedExample:
    """A single concrete close confirming the marker reason and audit basis
    line up on the safety-net-cap path."""

    @pytest.mark.asyncio
    async def test_safety_net_cap_close(self):
        """**Validates: Requirements 3.1, 3.2, 3.3**"""
        clock_in = _utc(2024, 1, 1, 8, 0)
        now = _utc(2024, 1, 2, 12, 0)  # ~28h open
        entry = _make_entry(clock_in_at=clock_in, break_minutes=30)

        result, mock_audit, mock_mgr = await _drive_close(
            entry, after_hours=14, grace=15, now=now,
        )

        assert result is True
        # No scheduled/fixed basis available -> safety-net cap.
        assert entry.flags["auto_clocked_out"] is True
        assert entry.flags["auto_clock_out_reason"] == "safety_net_cap"
        assert entry.flags["needs_review"] is True
        # clock_out is clamped to clock_in + 14h cap (well before `now`).
        assert entry.clock_out_at == clock_in + timedelta(hours=14)

        mock_audit.assert_awaited_once()
        kwargs = mock_audit.await_args.kwargs
        assert kwargs["action"] == "time_clock.auto_clock_out"
        assert kwargs["user_id"] is None
        assert kwargs["after_value"]["basis"] == "safety_net_cap"
        # Manager resolved to None in this run -> best-effort notify skipped.
        mock_mgr.assert_not_awaited()
