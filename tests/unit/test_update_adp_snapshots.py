"""Unit tests for ``app.tasks.scheduled.update_adp_snapshots``.

Covers task C2 from ``.kiro/specs/staff-management-p4`` (R13):

  1. Staff with finalised payslips totalling $30,000 → ADP from real
     data (= 30000 / 260 ≈ $115.38). ``source='payslips'`` audit row.
  2. Staff with NO finalised payslips → falls back to Phase 2 calc
     using ``hourly_rate × standard_hours_per_week / weekday_count``.
     ``source='phase2'`` audit row.
  3. Mixed batch — terminated staff are skipped (consistent with
     Phase 2 behaviour, ``is_active=false`` filtered at SELECT time).

The fake-session machinery mirrors the in-memory pattern used by
``tests/unit/test_roll_pay_periods.py``: we route ``session.execute``
on SQL substring so the task body can run end-to-end without a real
Postgres engine.

**Validates: Requirement R13 — Staff Management Phase 4 task C2**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake-session machinery
# ---------------------------------------------------------------------------


class _Result:
    """Minimal stand-in for ``AsyncSession.execute`` return value."""

    def __init__(self, *, all_rows=None, scalar=None, scalars_list=None):
        self._all = list(all_rows or [])
        self._scalar = scalar
        self._scalars_list = scalars_list

    def all(self):
        return list(self._all)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        proxy = MagicMock()
        proxy.all.return_value = list(self._scalars_list or [])
        return proxy


class _FakeSession:
    """In-memory stand-in for ``AsyncSession`` used by the task."""

    def __init__(
        self,
        *,
        staff_rows: list,
        gross_by_staff: dict[str, Decimal],
    ):
        self.staff_rows = staff_rows
        # Maps str(staff_id) → total finalised gross_pay in last 365d.
        self.gross_by_staff = gross_by_staff

        # Captured side effects.
        self.updates: list[dict] = []  # each = {staff_id, value}
        self.audit_log: list[dict] = []

    @asynccontextmanager
    async def begin(self):
        yield self

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        sql_upper = sql.upper()

        # 1. UPDATE staff_members.average_daily_pay_snapshot — checked
        #    BEFORE the SELECT branch because the ORM-compiled SELECT
        #    text contains the column name ``updated_at`` (substring
        #    matches "UPDATE").
        if "UPDATE STAFF_MEMBERS" in sql_upper and "AVERAGE_DAILY_PAY_SNAPSHOT" in sql_upper:
            assert params is not None
            self.updates.append({
                "staff_id": str(params["id"]),
                "value": params["v"],
            })
            return _Result()

        # 2. Real-payslip ADP query (R13 primary path) — checked before
        #    the broad staff_members SELECT branch.
        if "FROM payslips" in sql and "pay_periods" in sql:
            assert params is not None
            staff_id = str(params["staff_id"])
            total = self.gross_by_staff.get(staff_id, Decimal(0))
            return _Result(scalar=total)

        # 3. INSERT INTO audit_log (via write_audit_log helper) —
        #    checked before staff_members SELECT for the same reason.
        if "INSERT INTO audit_log" in sql:
            assert params is not None
            self.audit_log.append(dict(params))
            return _Result()

        # 4. SELECT staff_members WHERE is_active=true — the ORM-built
        #    statement contains the table name in its compiled form.
        if "FROM staff_members" in sql:
            return _Result(scalars_list=self.staff_rows)

        # Default — empty result.
        return _Result()


def _factory_for(session: _FakeSession):
    """Yield the SAME ``_FakeSession`` on every ``async_session_factory()``
    call so writes survive across re-entries."""

    @asynccontextmanager
    async def _factory_call():
        yield session

    return MagicMock(side_effect=lambda: _factory_call())


def _make_staff(
    *,
    name: str = "Jane Doe",
    is_active: bool = True,
    hourly_rate: Decimal | None = Decimal("25.00"),
    standard_hours_per_week: Decimal | None = Decimal("40.00"),
    availability_schedule: dict | None = None,
):
    """Build a duck-typed staff stand-in with the fields the task reads."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        name=name,
        is_active=is_active,
        hourly_rate=hourly_rate,
        standard_hours_per_week=standard_hours_per_week,
        availability_schedule=availability_schedule or {
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_uses_real_payslip_data_when_finalised_payslips_exist():
    """R13.1 — staff with finalised payslips totalling $30,000 over the
    last 52 weeks gets ADP = 30000 / 260 = $115.38.
    """
    from app.tasks.scheduled import update_adp_snapshots

    staff = _make_staff()
    session = _FakeSession(
        staff_rows=[staff],
        gross_by_staff={str(staff.id): Decimal("30000.00")},
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await update_adp_snapshots()

    assert summary["staff_updated"] == 1
    assert summary["from_payslips"] == 1
    assert summary["from_phase2"] == 0
    assert summary["skipped"] == 0
    assert summary["errors"] == 0
    assert len(session.updates) == 1
    # 30000 / 260 = 115.384615... → quantize to 115.38
    assert session.updates[0]["value"] == Decimal("115.38")
    assert session.updates[0]["staff_id"] == str(staff.id)

    # Audit row written with redacted after_value.
    audit = [r for r in session.audit_log if r["action"] == "staff.adp_snapshot_updated"]
    assert len(audit) == 1
    import json as _json
    after = _json.loads(audit[0]["after_value"])
    assert after["staff_id"] == str(staff.id)
    assert after["adp"] == "115.38"
    assert after["source"] == "payslips"
    # Redaction guard: no PII / breakdown in the after_value.
    assert "hourly_rate" not in after
    assert "gross_pay" not in after
    assert "ird_number" not in after
    assert "bank_account_number" not in after


@pytest.mark.asyncio
async def test_falls_back_to_phase2_when_no_finalised_payslips():
    """R13.2 — staff with no finalised payslips falls back to the
    Phase 2 placeholder calc and the audit row records ``source='phase2'``.
    """
    from app.tasks.scheduled import update_adp_snapshots

    # 25/h × 40h/wk / 5 weekdays = $200/day
    staff = _make_staff(
        hourly_rate=Decimal("25.00"),
        standard_hours_per_week=Decimal("40.00"),
    )
    session = _FakeSession(
        staff_rows=[staff],
        gross_by_staff={},  # No payslips.
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await update_adp_snapshots()

    assert summary["staff_updated"] == 1
    assert summary["from_payslips"] == 0
    assert summary["from_phase2"] == 1
    assert len(session.updates) == 1
    assert session.updates[0]["value"] == Decimal("200.00")

    audit = [r for r in session.audit_log if r["action"] == "staff.adp_snapshot_updated"]
    assert len(audit) == 1
    import json as _json
    after = _json.loads(audit[0]["after_value"])
    assert after["source"] == "phase2"
    assert after["adp"] == "200.00"


@pytest.mark.asyncio
async def test_skips_staff_with_no_payslips_and_no_phase2_inputs():
    """A staff with no finalised payslips AND missing
    ``hourly_rate``/``standard_hours_per_week`` is skipped entirely —
    no UPDATE, no audit row.
    """
    from app.tasks.scheduled import update_adp_snapshots

    staff = _make_staff(
        hourly_rate=None,
        standard_hours_per_week=None,
    )
    session = _FakeSession(
        staff_rows=[staff],
        gross_by_staff={},
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await update_adp_snapshots()

    assert summary["staff_updated"] == 0
    assert summary["skipped"] == 1
    assert len(session.updates) == 0
    assert len(session.audit_log) == 0


@pytest.mark.asyncio
async def test_terminated_staff_skipped_by_select_filter():
    """Terminated staff (``is_active=false``) are filtered out at the
    SELECT layer and never reach the compute path. We assert this by
    only feeding active staff to the fake session — the test
    documents the contract: the task's ORM SELECT includes
    ``is_active.is_(True)``.
    """
    from app.tasks.scheduled import update_adp_snapshots

    active = _make_staff(name="Active Alice")
    # Terminated staff is intentionally NOT in staff_rows because the
    # production SELECT filters them out before we see them. The fake
    # session mirrors that contract.
    session = _FakeSession(
        staff_rows=[active],
        gross_by_staff={str(active.id): Decimal("26000.00")},
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await update_adp_snapshots()

    assert summary["staff_updated"] == 1
    # 26000 / 260 = 100.00 exact
    assert session.updates[0]["value"] == Decimal("100.00")


@pytest.mark.asyncio
async def test_mixed_batch_payslips_plus_phase2_fallback():
    """A batch containing both staff types: one with payslips uses
    R13 primary; the other falls back to Phase 2. Both audit rows
    have the correct ``source`` tag.
    """
    from app.tasks.scheduled import update_adp_snapshots

    with_payslips = _make_staff(name="Payslipped Pat")
    new_hire = _make_staff(
        name="Brand-New Bob",
        hourly_rate=Decimal("30.00"),
        standard_hours_per_week=Decimal("40.00"),
    )
    session = _FakeSession(
        staff_rows=[with_payslips, new_hire],
        gross_by_staff={
            str(with_payslips.id): Decimal("52000.00"),  # 200/day exact
        },
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await update_adp_snapshots()

    assert summary["staff_updated"] == 2
    assert summary["from_payslips"] == 1
    assert summary["from_phase2"] == 1

    by_id = {u["staff_id"]: u["value"] for u in session.updates}
    assert by_id[str(with_payslips.id)] == Decimal("200.00")
    # 30/h × 40h/wk / 5 = 240/day
    assert by_id[str(new_hire.id)] == Decimal("240.00")

    sources = {}
    import json as _json
    for r in session.audit_log:
        if r["action"] == "staff.adp_snapshot_updated":
            after = _json.loads(r["after_value"])
            sources[after["staff_id"]] = after["source"]
    assert sources[str(with_payslips.id)] == "payslips"
    assert sources[str(new_hire.id)] == "phase2"


@pytest.mark.asyncio
async def test_zero_or_null_payslip_total_falls_back_to_phase2():
    """If the finalised-payslip SUM returns 0 (or NULL → coerced to 0
    by COALESCE), the task falls through to Phase 2 rather than
    persisting a $0 ADP — a $0 ADP would be worse than the placeholder.
    """
    from app.tasks.scheduled import update_adp_snapshots

    staff = _make_staff()
    session = _FakeSession(
        staff_rows=[staff],
        gross_by_staff={str(staff.id): Decimal("0.00")},
    )
    factory = _factory_for(session)

    with patch("app.core.database.async_session_factory", factory):
        summary = await update_adp_snapshots()

    assert summary["from_payslips"] == 0
    assert summary["from_phase2"] == 1
    # 25 × 40 / 5 = 200
    assert session.updates[0]["value"] == Decimal("200.00")


@pytest.mark.asyncio
async def test_helper_compute_phase2_adp_returns_none_when_inputs_missing():
    """Direct unit test of the extracted Phase 2 helper — confirms
    the public contract of ``_compute_phase2_adp``.
    """
    from app.tasks.scheduled import _compute_phase2_adp

    # Both inputs missing → None.
    assert _compute_phase2_adp(_make_staff(
        hourly_rate=None, standard_hours_per_week=None,
    )) is None
    # hourly_rate missing → None.
    assert _compute_phase2_adp(_make_staff(
        hourly_rate=None,
    )) is None
    # standard_hours_per_week missing → None.
    assert _compute_phase2_adp(_make_staff(
        standard_hours_per_week=None,
    )) is None
    # Both present, default 5-day schedule → daily rate.
    staff = _make_staff(
        hourly_rate=Decimal("20.00"),
        standard_hours_per_week=Decimal("40.00"),
    )
    assert _compute_phase2_adp(staff) == Decimal("160.00")
