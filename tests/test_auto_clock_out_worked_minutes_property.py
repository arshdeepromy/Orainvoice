"""Property-based test for Task 4.2 — worked_minutes consistency.

# Feature: auto-clock-out, Task 4.2 — single-entry closer invariant

**Validates: Requirements 2.1**

The closer under test is :func:`app.tasks.scheduled._auto_close_entry`. When it
finalises a stale open ``time_clock_entries`` row it sets both ``clock_out_at``
(resolved via the basis hierarchy and clamped to ``[clock_in_at, now]``) and
``worked_minutes``. The pinned-down design correctness property is:

* **Property 11 — worked_minutes consistency:** for an auto-closed entry the
  stored ``worked_minutes`` equals
  ``_compute_worked_minutes(clock_in_at, clock_out_at, break_minutes)`` and is
  floored at zero.

The closer performs DB reads (``session.get`` for the linked ``ScheduleEntry``
and the ``StaffMember``), a gating staff notification, a ``flags`` marker write
inside a ``begin_nested`` savepoint, an audit-log write, and a best-effort
manager notification. None of those are the subject of this property, so they
are mocked so the closer reaches the close path deterministically over every
generated input:

* ``_notify_staff_auto_clock_out`` → ``True`` (the staff notify gates the
  closure; forcing ``True`` drives the closer down the finalise path).
* ``_notify_manager_auto_clock_out`` / ``_resolve_manager`` → no-ops.
* ``write_audit_log`` → no-op (lazy-imported from ``app.core.audit``).
* ``session.get`` → returns the generated ``ScheduleEntry`` / ``StaffMember``
  doubles (or ``None``), ``session.flush`` is a no-op, and
  ``session.begin_nested`` is a no-op async context manager.

The generators exercise all three end-time bases (linked scheduled shift, fixed
working arrangement, and the safety-net cap) and deliberately include large
``break_minutes`` so the floor-at-zero branch of ``_compute_worked_minutes`` is
covered.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.time_clock.service import _compute_worked_minutes
from app.tasks.scheduled import _auto_close_entry

# ---------------------------------------------------------------------------
# Hypothesis settings — the closer is exercised in-memory with mocked I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

_UTC = st.just(timezone.utc)

# A tz-aware UTC datetime in a sane, overflow-safe window (well inside
# datetime.min/max so the largest generated timedeltas can't overflow).
aware_dt = st.datetimes(
    min_value=datetime(2020, 1, 1, 0, 0, 0),
    max_value=datetime(2030, 1, 1, 0, 0, 0),
    timezones=_UTC,
)

_WEEKDAY_KEYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


@st.composite
def close_scenario(draw):
    """Generate a full auto-close scenario exercising every end-time basis.

    ``break_minutes`` ranges well past a normal shift length so that some
    examples drive ``elapsed_minutes - break_minutes`` below zero, exercising
    the floor-at-zero clamp in ``_compute_worked_minutes``.
    """
    clock_in_at = draw(aware_dt)
    # Observed at/after clock-in, up to ~40 days open.
    open_minutes = draw(st.integers(min_value=0, max_value=40 * 24 * 60))
    now = clock_in_at + timedelta(minutes=open_minutes)

    after_hours = draw(st.integers(min_value=1, max_value=48))
    grace_minutes = draw(st.integers(min_value=0, max_value=240))
    # Up to ~83h of break — far larger than most resolved windows, so the
    # floor-at-zero path is hit for a meaningful fraction of examples.
    break_minutes = draw(st.integers(min_value=0, max_value=5000))

    basis = draw(st.sampled_from(["cap", "scheduled", "fixed"]))

    scheduled_entry_id = None
    sched_obj = None
    staff_obj = None

    if basis == "scheduled":
        scheduled_entry_id = uuid.uuid4()
        # scheduled_end placed anywhere from slightly before clock-in (clamp
        # up) to far in the future (clamp down to now).
        sched_offset = draw(st.integers(min_value=-600, max_value=40 * 24 * 60))
        scheduled_end = clock_in_at + timedelta(minutes=sched_offset)
        sched_obj = SimpleNamespace(end_time=scheduled_end)
        # A staff row may still exist; arrangement is irrelevant when scheduled.
        staff_obj = SimpleNamespace(
            id=uuid.uuid4(),
            working_arrangement="casual",
            availability_schedule=None,
        )
    elif basis == "fixed":
        # Fixed working arrangement with the same configured end on every
        # weekday, so the resolver finds an end regardless of clock-in weekday.
        end_h = draw(st.integers(min_value=0, max_value=23))
        end_m = draw(st.integers(min_value=0, max_value=59))
        hhmm = f"{end_h:02d}:{end_m:02d}"
        availability = {
            key: {"start": "08:00", "end": hhmm} for key in _WEEKDAY_KEYS
        }
        staff_obj = SimpleNamespace(
            id=uuid.uuid4(),
            working_arrangement="fixed",
            availability_schedule=availability,
        )
    else:  # "cap" — no scheduled link, no fixed end.
        staff_obj = SimpleNamespace(
            id=uuid.uuid4(),
            working_arrangement="casual",
            availability_schedule=None,
        )

    return {
        "clock_in_at": clock_in_at,
        "now": now,
        "after_hours": after_hours,
        "grace_minutes": grace_minutes,
        "break_minutes": break_minutes,
        "scheduled_entry_id": scheduled_entry_id,
        "sched_obj": sched_obj,
        "staff_obj": staff_obj,
    }


def _make_entry(scenario):
    """Build a TimeClockEntry double carrying every field the closer / its
    audit serialiser (``_entry_to_dict``) reads or writes."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        staff_id=scenario["staff_obj"].id if scenario["staff_obj"] else uuid.uuid4(),
        clock_in_at=scenario["clock_in_at"],
        clock_out_at=None,
        source="kiosk",
        clock_in_photo_url=None,
        clock_out_photo_url=None,
        clock_in_lat=None,
        clock_in_lng=None,
        clock_out_lat=None,
        clock_out_lng=None,
        scheduled_entry_id=scenario["scheduled_entry_id"],
        break_minutes=scenario["break_minutes"],
        notes=None,
        worked_minutes=None,
        flags=None,
    )


def _make_session(scenario):
    """A session double: ``get`` dispatches by model name, ``flush`` is a no-op,
    and ``begin_nested`` is a no-op async-context-manager savepoint."""
    session = SimpleNamespace()

    async def fake_get(model, ident):
        name = getattr(model, "__name__", "")
        if name == "ScheduleEntry":
            return scenario["sched_obj"]
        if name == "StaffMember":
            return scenario["staff_obj"]
        return None

    @asynccontextmanager
    async def fake_begin_nested():
        yield SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())

    session.get = fake_get
    session.flush = AsyncMock()
    session.begin_nested = fake_begin_nested
    return session


async def _run_example(scenario):
    entry = _make_entry(scenario)
    session = _make_session(scenario)
    policy = {
        "auto_clock_out_grace_minutes": scenario["grace_minutes"],
        "auto_clock_out_after_hours": scenario["after_hours"],
        "missed_clock_out_alert_channels": ["sms"],
    }

    with patch(
        "app.tasks.scheduled._notify_staff_auto_clock_out",
        new_callable=AsyncMock,
        return_value=True,  # staff notify gates the closure -> force the close path
    ), patch(
        "app.tasks.scheduled._notify_manager_auto_clock_out",
        new_callable=AsyncMock,
    ), patch(
        "app.tasks.scheduled._resolve_manager",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.core.audit.write_audit_log",
        new_callable=AsyncMock,
    ):
        closed = await _auto_close_entry(session, entry, policy, scenario["now"])

    # The staff notify returned True, so the entry must have been finalised.
    assert closed is True
    assert entry.clock_out_at is not None

    # Property 11: worked_minutes equals the pure computation over the stored
    # close columns, floored at zero.
    expected = _compute_worked_minutes(
        clock_in_at=entry.clock_in_at,
        clock_out_at=entry.clock_out_at,
        break_minutes=entry.break_minutes or 0,
    )
    assert entry.worked_minutes == expected
    assert entry.worked_minutes >= 0


@given(scenario=close_scenario())
@PBT_SETTINGS
def test_worked_minutes_consistency(scenario):
    """Property 11: an auto-closed entry's ``worked_minutes`` equals
    ``_compute_worked_minutes(clock_in_at, clock_out_at, break_minutes)`` and is
    never negative, across every end-time basis.

    **Validates: Requirements 2.1**
    """
    asyncio.run(_run_example(scenario))
