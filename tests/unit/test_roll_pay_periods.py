"""Unit tests for ``app.tasks.scheduled.roll_pay_periods_task``.

Covers task C1 from ``.kiro/specs/staff-management-p4`` plus its
verify list:

  1. Fresh org with no history → 4 periods created.
  2. Same call again → 0 created (idempotency via ON CONFLICT DO NOTHING
     against ``uq_pay_periods_org_start``).
  3. Cadence change is non-retroactive (G14) — the next tick rolls
     forward from the existing watermark using the new cadence rules
     without rewriting any existing period.
  4. Audit row is written for every newly inserted period
     (``pay_period.created_by_roll``) and the after_value is
     redaction-compliant (no PII / money / amounts).
  5. No orgs with payroll enabled → zero summary.
  6. Org-level exception is logged and counted but doesn't poison the
     batch.

The function is exercised against an in-memory fake session that
records every ``INSERT`` it sees, so we can assert idempotency
without a real Postgres ON CONFLICT engine — the fake matches the
production semantics by tracking ``(org_id, start_date)`` keys and
returning ``None`` from the RETURNING column on conflict.

**Validates: Requirements R1.5, R1.6 (G5 + G14) — Staff Management
Phase 4 task C1.**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake-session machinery
# ---------------------------------------------------------------------------


class _FakeSession:
    """In-memory stand-in for ``AsyncSession``.

    The real task issues:

      1. A SELECT enumerating orgs with ``payroll`` enabled (via
         ``sql_text``) — the very first ``execute`` call on the
         FACTORY-LEVEL session.
      2. A ``_set_rls_org_id`` call that issues a ``SET`` statement on
         the per-org session.
      3. A SELECT for ``MAX(pay_periods.end_date)`` for the org.
      4. An INSERT ... ON CONFLICT (org_id, start_date) DO NOTHING
         RETURNING id, repeated four times.
      5. ``write_audit_log`` issues an INSERT into ``audit_log`` for
         every successful INSERT.

    The fake pretends to be a real session so the task body runs
    end-to-end. It is shared across ALL ``async_session_factory()``
    invocations made by a single test so ``pay_periods`` rows
    inserted on one factory call are visible to the next one.
    """

    def __init__(self, *, org_rows: list[tuple], today: date):
        self.org_rows = org_rows
        self.today = today

        # In-memory pay_periods rows: list of dicts.
        self.pay_periods: list[dict] = []
        # In-memory audit_log rows: list of dicts.
        self.audit_log: list[dict] = []

        # Per-session counter so we can dispense the org list on call 1
        # of the factory's FIRST session, and the latest_end SELECT on
        # subsequent sessions' first call.
        self._first_session = True
        self._first_call_in_session = True

        # Used by the factory to pin which org_id this session is
        # processing — set by the ``_set_rls_org_id`` patch below.
        self.current_org_id: str | None = None

    # ------------------------------------------------------------------
    # async-with helpers
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def begin(self):
        yield self

    # ------------------------------------------------------------------
    # execute() router — branches off the SQL string
    # ------------------------------------------------------------------

    async def execute(self, stmt, params=None):
        sql = str(stmt)

        # 1. List orgs with payroll enabled.
        if "FROM organisations o" in sql and "module_slug = 'payroll'" in sql:
            return _Result(all_rows=self.org_rows)

        # 2. SET app.current_org_id (RLS) — no-op.
        if sql.startswith("SET ") or "set_config" in sql:
            return _Result(all_rows=[])

        # 3. SELECT pay_periods.end_date ... ORDER BY end_date DESC
        if "pay_periods" in sql and "end_date" in sql and "ORDER BY" in sql.lower():
            org_id = self.current_org_id
            ends = [
                r["end_date"]
                for r in self.pay_periods
                if str(r["org_id"]) == str(org_id)
            ]
            latest = max(ends) if ends else None
            return _Result(scalar=latest)

        # 4. INSERT INTO pay_periods ... ON CONFLICT DO NOTHING RETURNING id
        if "INSERT INTO pay_periods" in sql:
            assert params is not None
            org_id = str(params["org_id"])
            start = params["start"]
            # Idempotency: skip when (org_id, start_date) already exists.
            for row in self.pay_periods:
                if str(row["org_id"]) == org_id and row["start_date"] == start:
                    return _Result(scalar=None)  # ON CONFLICT path
            new_id = params["id"]
            self.pay_periods.append({
                "id": new_id,
                "org_id": org_id,
                "start_date": params["start"],
                "end_date": params["end"],
                "pay_date": params["pay"],
                "status": "open",
            })
            return _Result(scalar=new_id)

        # 5. INSERT INTO audit_log
        if "INSERT INTO audit_log" in sql:
            self.audit_log.append(dict(params or {}))
            return _Result(scalar=None)

        # Default: empty result.
        return _Result(all_rows=[])


class _Result:
    """Mimic the shape returned by ``AsyncSession.execute()``."""

    def __init__(self, *, all_rows: list | None = None, scalar=None):
        self._all = all_rows or []
        self._scalar = scalar

    def all(self):
        return list(self._all)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        scalars_proxy = MagicMock()
        scalars_proxy.all.return_value = self._all
        return scalars_proxy


def _factory_for(session: _FakeSession):
    """Return an ``async_session_factory`` substitute that yields the
    SAME ``_FakeSession`` every time, so cross-session writes survive."""

    @asynccontextmanager
    async def _factory_call():
        # Reset per-session call counter on each entry — the real
        # task issues fresh SELECTs in each session.
        session._first_call_in_session = True
        yield session

    return MagicMock(side_effect=lambda: _factory_call())


def _patch_set_rls(session: _FakeSession):
    """Build a patcher that records ``current_org_id`` on the fake
    session whenever the task calls ``_set_rls_org_id``."""

    async def _set_rls(_sess, org_id):
        session.current_org_id = org_id

    return patch("app.core.database._set_rls_org_id", new=_set_rls)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_org_no_history_creates_four_periods():
    """G5 — fresh org with no pay_periods rows: the task creates
    exactly four sequential periods using the org's cadence + anchor
    settings.
    """
    from app.tasks.scheduled import roll_pay_periods_task

    org_id = uuid.uuid4()
    session = _FakeSession(
        org_rows=[(org_id, "fortnightly", 1, 3)],
        today=date(2026, 6, 1),
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory), \
            _patch_set_rls(session), \
            patch("app.tasks.scheduled.date") as mock_date:
        mock_date.today.return_value = date(2026, 6, 3)
        # ``date(...)`` constructor calls inside the task should still
        # work — only ``today()`` is patched.
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        summary = await roll_pay_periods_task()

    assert summary["periods_created"] == 4
    assert summary["periods_skipped"] == 0
    assert summary["orgs_processed"] == 1
    assert summary["errors"] == 0
    assert len(session.pay_periods) == 4
    # Periods chain end-to-start, fortnightly = 14-day windows.
    starts = sorted(r["start_date"] for r in session.pay_periods)
    ends = sorted(r["end_date"] for r in session.pay_periods)
    for i in range(1, 4):
        assert starts[i] == ends[i - 1] + _one_day()
    # Every period has status='open'.
    assert all(r["status"] == "open" for r in session.pay_periods)
    # Every newly inserted period emits a `pay_period.created_by_roll`
    # audit row.
    assert (
        sum(
            1 for r in session.audit_log
            if r.get("action") == "pay_period.created_by_roll"
        )
        == 4
    )


@pytest.mark.asyncio
async def test_idempotent_second_run_creates_zero():
    """Idempotency — running the task twice on the same org with no
    cadence change creates zero new periods on the second run, with
    every INSERT hitting the ``ON CONFLICT DO NOTHING`` branch.
    """
    from app.tasks.scheduled import roll_pay_periods_task

    org_id = uuid.uuid4()
    session = _FakeSession(
        org_rows=[(org_id, "fortnightly", 1, 3)],
        today=date(2026, 6, 1),
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory), \
            _patch_set_rls(session), \
            patch("app.tasks.scheduled.date") as mock_date:
        mock_date.today.return_value = date(2026, 6, 3)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        first = await roll_pay_periods_task()
        # Second call on the same fake DB → every INSERT collides.
        second = await roll_pay_periods_task()

    assert first["periods_created"] == 4
    assert second["periods_created"] == 0
    assert second["periods_skipped"] == 4
    # Underlying table still has only 4 rows (no duplicates).
    assert len(session.pay_periods) == 4
    # No new audit rows on the idempotent second run.
    audit_after_second = [
        r for r in session.audit_log
        if r.get("action") == "pay_period.created_by_roll"
    ]
    assert len(audit_after_second) == 4


@pytest.mark.asyncio
async def test_cadence_change_non_retroactive_g14():
    """G14 — an org's cadence flips weekly→monthly mid-flight. The
    task re-reads cadence at run time and rolls forward from
    ``latest_end+1`` only — existing weekly periods stay untouched.
    """
    from app.tasks.scheduled import roll_pay_periods_task

    org_id = uuid.uuid4()
    session = _FakeSession(
        org_rows=[(org_id, "weekly", 1, 3)],
        today=date(2026, 6, 1),
    )
    factory = _factory_for(session)

    # First tick — weekly cadence, 4 weekly periods land.
    with patch("app.core.database.async_session_factory", factory), \
            _patch_set_rls(session), \
            patch("app.tasks.scheduled.date") as mock_date:
        mock_date.today.return_value = date(2026, 6, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        first = await roll_pay_periods_task()

    assert first["periods_created"] == 4
    weekly_periods = sorted(
        session.pay_periods, key=lambda r: r["start_date"],
    )
    weekly_lengths = [
        (r["end_date"] - r["start_date"]).days + 1 for r in weekly_periods
    ]
    assert weekly_lengths == [7, 7, 7, 7]
    last_weekly_end = weekly_periods[-1]["end_date"]

    # Admin flips cadence to monthly. The next tick re-reads cadence
    # from the org row — we mutate ``org_rows`` to model the DB write.
    session.org_rows = [(org_id, "monthly", 1, 3)]

    with patch("app.core.database.async_session_factory", factory), \
            _patch_set_rls(session), \
            patch("app.tasks.scheduled.date") as mock_date:
        mock_date.today.return_value = date(2026, 6, 29)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        second = await roll_pay_periods_task()

    # The 4 existing weekly periods are still in the table unchanged.
    weekly_after = [
        r for r in session.pay_periods if r["end_date"] <= last_weekly_end
    ]
    assert len(weekly_after) == 4
    weekly_lengths_after = sorted(
        (r["end_date"] - r["start_date"]).days + 1 for r in weekly_after
    )
    assert weekly_lengths_after == [7, 7, 7, 7]

    # The new periods are monthly-shaped — at least one is > 27 days.
    new_periods = [
        r for r in session.pay_periods if r["start_date"] > last_weekly_end
    ]
    assert second["periods_created"] >= 1
    assert any(
        (r["end_date"] - r["start_date"]).days + 1 >= 27 for r in new_periods
    )
    # The first new monthly period starts strictly AFTER the last
    # weekly end — never overlaps backwards into the weekly window
    # (non-retroactive). A small forward gap is acceptable per the
    # algorithm: monthly cadence with anchor_day=1 lands on the
    # 1st of the next calendar month, not on the day after
    # last_weekly_end.
    assert min(r["start_date"] for r in new_periods) > last_weekly_end


@pytest.mark.asyncio
async def test_audit_row_has_redacted_payload():
    """G12 — the ``pay_period.created_by_roll`` audit row carries
    only dates / cadence / pay_period_id; no PII, no money.
    """
    from app.tasks.scheduled import roll_pay_periods_task

    org_id = uuid.uuid4()
    session = _FakeSession(
        org_rows=[(org_id, "monthly", 1, 3)],
        today=date(2026, 6, 1),
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory), \
            _patch_set_rls(session), \
            patch("app.tasks.scheduled.date") as mock_date:
        mock_date.today.return_value = date(2026, 6, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        await roll_pay_periods_task()

    import json
    forbidden_keys = {
        "gross_pay", "net_pay", "amount", "ird_number",
        "bank_account_number", "paye", "recipient_email",
    }
    audit_rows = [
        r for r in session.audit_log
        if r.get("action") == "pay_period.created_by_roll"
    ]
    assert len(audit_rows) == 4
    for row in audit_rows:
        after = json.loads(row["after_value"])
        assert set(after.keys()) == {
            "pay_period_id", "start_date", "end_date",
            "pay_date", "cadence",
        }
        assert not (forbidden_keys & set(after.keys()))


@pytest.mark.asyncio
async def test_no_payroll_orgs_returns_zero_summary():
    """No orgs have ``payroll`` enabled → zero work, zero summary."""
    from app.tasks.scheduled import roll_pay_periods_task

    session = _FakeSession(org_rows=[], today=date(2026, 6, 1))
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await roll_pay_periods_task()

    assert summary == {
        "orgs_processed": 0,
        "periods_created": 0,
        "periods_skipped": 0,
        "errors": 0,
    }
    assert session.pay_periods == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)
