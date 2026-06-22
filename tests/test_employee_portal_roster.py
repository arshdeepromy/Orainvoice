"""Unit / smoke tests for the Employee Portal roster endpoint wiring.

Covers task 11.4 at the level that does not require a live database:

- the router mounts ``GET /e/api/roster`` under ``/e/api`` (session-gated);
- the ``GET /e/api/roster`` route declares the ``require_portal_session``
  dependency and does NOT pull in the state-changing CSRF gate (own-roster-only
  is enforced by the session staff_id + org_id + RLS — R7.1, R7.4);
- the ``_current_week_start`` helper returns the Monday of the week containing a
  given date (the default week window when ``week_start`` is omitted);
- ``RosterResponse`` / ``RosterEntry`` serialise their UUID / date / datetime
  fields to JSON-safe primitives and only expose the display fields.

The DB-backed tenant/owner isolation property (a foreign/other-org staff id
never resolves any entries) is covered by the dedicated property test in task
11.6.

Implements: Organisation Employee Portal task 11.4 — Requirements 7.1, 7.2, 7.4.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone


def test_app_factory_mounts_roster() -> None:
    """``GET /e/api/roster`` is registered under /e/api."""
    from app.main import create_app

    app = create_app()
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    assert "/e/api/roster" in paths


def test_roster_route_requires_portal_session() -> None:
    """The roster route is gated by ``require_portal_session`` (R7.1, R7.4)."""
    from app.modules.employee_portal import router as R

    roster_routes = [
        r
        for r in R.router.routes
        if getattr(r, "path", None) == "/roster" and "GET" in getattr(r, "methods", set())
    ]
    assert roster_routes, "GET /roster route should be registered on the router"

    route = roster_routes[0]
    dep_calls = [d.call for d in route.dependant.dependencies]
    assert R.require_portal_session in dep_calls
    # A safe GET must NOT pull in the state-changing CSRF gate.
    assert R.validate_emp_portal_csrf not in dep_calls


def test_current_week_start_returns_monday() -> None:
    """``_current_week_start`` lands on the Monday of the containing week."""
    from app.modules.employee_portal.router import _current_week_start

    # 2026-06-03 is a Wednesday → Monday is 2026-06-01.
    assert _current_week_start(date(2026, 6, 3)) == date(2026, 6, 1)
    # A Monday maps to itself (idempotent at the week boundary).
    assert _current_week_start(date(2026, 6, 1)) == date(2026, 6, 1)
    # A Sunday maps back to the preceding Monday.
    assert _current_week_start(date(2026, 6, 7)) == date(2026, 6, 1)


def test_roster_response_serialises_json_safe() -> None:
    """RosterResponse → JSON-safe dict (UUID/date/datetime → strings)."""
    from app.modules.employee_portal.schemas import RosterEntry, RosterResponse

    staff_id = uuid.uuid4()
    start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc)
    resp = RosterResponse(
        staff_id=staff_id,
        week_start=date(2026, 6, 1),
        week_end=date(2026, 6, 8),
        entries=[
            RosterEntry(
                start_time=start,
                end_time=end,
                title="Morning shift",
                notes="Front desk",
                entry_type="job",
            )
        ],
    )

    dumped = resp.model_dump(mode="json")
    assert dumped["staff_id"] == str(staff_id)
    assert dumped["week_start"] == "2026-06-01"
    assert dumped["week_end"] == "2026-06-08"
    assert len(dumped["entries"]) == 1
    entry = dumped["entries"][0]
    assert entry["title"] == "Morning shift"
    assert entry["entry_type"] == "job"
    assert entry["notes"] == "Front desk"
    # Only the display fields are exposed — no staff_id / org_id / linkage ids.
    assert set(entry.keys()) == {
        "start_time",
        "end_time",
        "title",
        "notes",
        "entry_type",
    }


def test_roster_response_defaults_to_empty_entries() -> None:
    """A week with no schedule entries serialises to an empty list (not null)."""
    from app.modules.employee_portal.schemas import RosterResponse

    resp = RosterResponse(
        staff_id=uuid.uuid4(),
        week_start=date(2026, 6, 1),
        week_end=date(2026, 6, 8),
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["entries"] == []
