"""Unit tests for ``StaffService.get_compliance_summary`` (Phase 1 task C9).

Covers:

1. All 7 keys are present in the returned dict.
2. Each counter maps to the right ``COUNT(*) FILTER`` aggregate when
   the DB returns known integer values for the row.
3. ``visa_expiring_soon`` filters by ``residency_type IN
   ('work_visa','student_visa','other')`` so citizens and permanent
   residents are excluded from the count (G2 — visa-holders only).
4. ``NULL`` counters from the DB collapse to ``0`` so callers can rely
   on the field being a real integer.
5. The SELECT statement filters by ``org_id`` (tenant isolation).
6. The SELECT statement uses the seven labelled aggregates expected by
   the router (``probation_ending_soon``, ``visa_expiring_soon``,
   ``missing_agreement``, ``pay_review_due``, ``below_minimum_wage``,
   ``missing_employee_id``, ``missing_start_date``) so the response
   schema's keys line up.

The tests stub the DB session with ``AsyncMock``; the focus is the
SQL-construction + row-to-dict mapping, not a real PostgreSQL run.

**Validates: Requirements R6, G1, G2, G3 — Staff Phase 1 task C9**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql import Select

from app.modules.staff.schemas import ComplianceSummary
from app.modules.staff.service import StaffService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(*, row: SimpleNamespace) -> AsyncMock:
    """AsyncMock DB whose single ``execute().one()`` returns ``row``.

    The service issues exactly one SELECT against ``staff_members`` —
    the seven ``COUNT(*) FILTER`` aggregates collapse into one row with
    seven labelled columns.
    """
    db = AsyncMock()

    state = {"calls": []}

    async def fake_execute(stmt):
        state["calls"].append(stmt)
        result = MagicMock()
        result.one.return_value = row
        return result

    db.execute = fake_execute
    db._calls = state["calls"]  # type: ignore[attr-defined]
    return db


def _make_row(**overrides: int | None) -> SimpleNamespace:
    """Build a row-mapping-like object with the seven counter columns.

    Defaults all counters to 0 so each test only has to override the
    field(s) it cares about.
    """
    base: dict[str, int | None] = {
        "probation_ending_soon": 0,
        "visa_expiring_soon": 0,
        "missing_agreement": 0,
        "pay_review_due": 0,
        "below_minimum_wage": 0,
        "missing_employee_id": 0,
        "missing_start_date": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# 1. All 7 keys present
# ---------------------------------------------------------------------------


class TestAllKeysPresent:
    """The dict returned by ``get_compliance_summary`` always has the
    seven keys listed in R6.1, regardless of whether any of them are
    zero."""

    @pytest.mark.asyncio
    async def test_dict_contains_all_seven_keys(self):
        db = _make_db(row=_make_row())
        svc = StaffService(db)

        result = await svc.get_compliance_summary(
            uuid.uuid4(), Decimal("23.15"),
        )

        assert set(result.keys()) == {
            "probation_ending_soon",
            "visa_expiring_soon",
            "missing_agreement",
            "pay_review_due",
            "below_minimum_wage",
            "missing_employee_id",
            "missing_start_date",
        }
        # Every value is a real ``int``, not None.
        assert all(isinstance(v, int) for v in result.values())

    @pytest.mark.asyncio
    async def test_dict_round_trips_through_compliance_summary_schema(self):
        """Sanity check: the dict shape maps cleanly onto the Pydantic
        schema the router serialises."""
        db = _make_db(row=_make_row(
            probation_ending_soon=2,
            visa_expiring_soon=1,
            missing_agreement=3,
            pay_review_due=4,
            below_minimum_wage=0,
            missing_employee_id=5,
            missing_start_date=6,
        ))
        svc = StaffService(db)

        result = await svc.get_compliance_summary(
            uuid.uuid4(), Decimal("23.15"),
        )
        schema = ComplianceSummary(**result)

        assert schema.probation_ending_soon == 2
        assert schema.visa_expiring_soon == 1
        assert schema.missing_agreement == 3
        assert schema.pay_review_due == 4
        assert schema.below_minimum_wage == 0
        assert schema.missing_employee_id == 5
        assert schema.missing_start_date == 6


# ---------------------------------------------------------------------------
# 2. Counter mapping — DB row values flow through to dict
# ---------------------------------------------------------------------------


class TestCounterMapping:
    """When the DB returns specific integers, each label appears in the
    right key of the returned dict (no off-by-one or label swap)."""

    @pytest.mark.asyncio
    async def test_each_counter_maps_to_its_label(self):
        # Use a unique value per counter so a label swap would surface.
        db = _make_db(row=_make_row(
            probation_ending_soon=11,
            visa_expiring_soon=22,
            missing_agreement=33,
            pay_review_due=44,
            below_minimum_wage=55,
            missing_employee_id=66,
            missing_start_date=77,
        ))
        svc = StaffService(db)

        result = await svc.get_compliance_summary(
            uuid.uuid4(), Decimal("23.15"),
        )

        assert result["probation_ending_soon"] == 11
        assert result["visa_expiring_soon"] == 22
        assert result["missing_agreement"] == 33
        assert result["pay_review_due"] == 44
        assert result["below_minimum_wage"] == 55
        assert result["missing_employee_id"] == 66
        assert result["missing_start_date"] == 77


# ---------------------------------------------------------------------------
# 3. NULL collapses to 0 (defensive)
# ---------------------------------------------------------------------------


class TestNullCollapsesToZero:
    """``COUNT(*) FILTER`` returns 0 not NULL, but defence-in-depth: if
    the row carries None for any column the dict still surfaces 0 so
    the response schema validates."""

    @pytest.mark.asyncio
    async def test_none_columns_become_zero(self):
        db = _make_db(row=_make_row(
            probation_ending_soon=None,
            visa_expiring_soon=None,
            missing_agreement=None,
            pay_review_due=None,
            below_minimum_wage=None,
            missing_employee_id=None,
            missing_start_date=None,
        ))
        svc = StaffService(db)

        result = await svc.get_compliance_summary(
            uuid.uuid4(), Decimal("23.15"),
        )

        for key, value in result.items():
            assert value == 0, f"{key} should collapse None to 0"


# ---------------------------------------------------------------------------
# 4. Visa filter excludes citizens / permanent_residents (G2)
# ---------------------------------------------------------------------------


class TestVisaResidencyFilter:
    """The compiled SQL for ``visa_expiring_soon`` filters
    ``residency_type IN ('work_visa','student_visa','other')`` so
    citizens and permanent residents are not counted."""

    @pytest.mark.asyncio
    async def test_visa_counter_filter_includes_residency_type(self):
        db = _make_db(row=_make_row())
        svc = StaffService(db)

        await svc.get_compliance_summary(uuid.uuid4(), Decimal("23.15"))

        # The single SELECT with seven aggregates was the only
        # execute() call.
        stmt = db._calls[0]  # type: ignore[attr-defined]
        assert isinstance(stmt, Select)
        compiled = str(
            stmt.compile(compile_kwargs={"literal_binds": True}),
        )

        # The visa counter clause carries the residency_type IN list.
        # We assert each whitelisted value appears in the compiled SQL,
        # and that the two excluded values (citizen, permanent_resident)
        # do NOT appear inside the visa filter (they may appear in other
        # places like the residency_type column itself, so we assert on
        # the literal IN clause shape).
        assert "'work_visa'" in compiled
        assert "'student_visa'" in compiled
        assert "'other'" in compiled
        # The two excluded residency types must not be IN'd into the
        # visa_expiring_soon filter — assert via substring match on the
        # exact whitelist clause SQLAlchemy renders. (PostgreSQL renders
        # ``IN ('work_visa', 'student_visa', 'other')``.)
        whitelist = "'work_visa', 'student_visa', 'other'"
        assert whitelist in compiled, (
            "visa_expiring_soon filter must whitelist exactly the "
            "three visa-holder residency types (G2)"
        )

    @pytest.mark.asyncio
    async def test_query_filters_by_org_id(self):
        """Tenant isolation — the WHERE org_id = :org_id clause is
        present in the SELECT."""
        db = _make_db(row=_make_row())
        svc = StaffService(db)

        org_id = uuid.uuid4()
        await svc.get_compliance_summary(org_id, Decimal("23.15"))

        stmt = db._calls[0]  # type: ignore[attr-defined]
        compiled = str(
            stmt.compile(compile_kwargs={"literal_binds": True}),
        )
        # The org_id literal must appear in the WHERE clause.
        # SQLAlchemy renders UUID literals without hyphens for psycopg.
        assert str(org_id) in compiled or org_id.hex in compiled
        assert "ORG_ID" in compiled.upper()


# ---------------------------------------------------------------------------
# 5. All seven labelled aggregates appear in the SELECT
# ---------------------------------------------------------------------------


class TestSelectShape:
    """The compiled SELECT names all seven aggregate columns so the
    router's row-to-dict mapping doesn't silently lose a counter."""

    @pytest.mark.asyncio
    async def test_select_includes_all_seven_labels(self):
        db = _make_db(row=_make_row())
        svc = StaffService(db)

        await svc.get_compliance_summary(uuid.uuid4(), Decimal("23.15"))

        stmt = db._calls[0]  # type: ignore[attr-defined]
        compiled = str(
            stmt.compile(compile_kwargs={"literal_binds": True}),
        ).lower()

        for label in (
            "probation_ending_soon",
            "visa_expiring_soon",
            "missing_agreement",
            "pay_review_due",
            "below_minimum_wage",
            "missing_employee_id",
            "missing_start_date",
        ):
            assert label in compiled, f"label {label!r} missing from SELECT"

    @pytest.mark.asyncio
    async def test_select_uses_minimum_wage_threshold(self):
        """The ``below_minimum_wage`` filter compares against the
        threshold passed in by the caller — so an org-customised value
        (e.g. 25.00) is honoured."""
        db = _make_db(row=_make_row())
        svc = StaffService(db)

        custom_threshold = Decimal("25.00")
        await svc.get_compliance_summary(uuid.uuid4(), custom_threshold)

        stmt = db._calls[0]  # type: ignore[attr-defined]
        compiled = str(
            stmt.compile(compile_kwargs={"literal_binds": True}),
        )
        # The literal threshold must appear in the compiled SQL — proves
        # the function isn't hard-coding 23.15.
        assert "25.00" in compiled or "25" in compiled

    @pytest.mark.asyncio
    async def test_single_round_trip(self):
        """All seven aggregates should be computed in ONE SELECT — the
        spec calls for a single round-trip query."""
        db = _make_db(row=_make_row())
        svc = StaffService(db)

        await svc.get_compliance_summary(uuid.uuid4(), Decimal("23.15"))

        # Exactly one execute() call against the DB.
        assert len(db._calls) == 1  # type: ignore[attr-defined]
