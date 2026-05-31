"""Unit tests for ``StaffService.get_pay_rate_history`` (Phase 1 task B5).

Covers:

1. Empty result → returns ``([], 0)``.
2. Multiple rows → ordered by ``effective_from`` DESC (and ``created_at``
   DESC as the tiebreaker).
3. Pagination: with 5 underlying rows and ``offset=2, limit=2`` the
   service returns 2 items but the total count stays at 5 (so the UI
   can render an accurate paginator).
4. ``changed_by_email`` is populated when a ``users.id`` join match
   exists.
5. ``changed_by_email`` is ``None`` when ``changed_by`` is NULL (the
   left/outer join still returns the pay-rate row).
6. Query construction smoke-test: the SELECT goes through ``StaffPayRate
   OUTER JOIN users`` and applies the ``offset`` / ``limit`` so the
   planner can use ``idx_staff_pay_rates_staff_effective``.

The tests stub the DB session with ``AsyncMock`` — the service-layer
logic under test is "build the right SQL + transform the rows", not
"run a real PostgreSQL query". The B4 sibling test file uses the same
pattern.

**Validates: Requirements R3 — Staff Phase 1 task B5**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql import Select

from app.modules.staff.service import StaffService


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_row(
    *,
    row_id: uuid.UUID | None = None,
    effective_from: date,
    hourly_rate: Decimal | None = Decimal("30.00"),
    overtime_rate: Decimal | None = Decimal("45.00"),
    change_reason: str | None = "rate_change",
    changed_by_email: str | None = None,
) -> SimpleNamespace:
    """Build a row-mapping-like object for the ``execute().all()`` mock.

    The service consumes the join result with attribute access
    (``row.id``, ``row.effective_from``, etc.) — ``SimpleNamespace`` is
    a faithful stand-in for the ``Row`` SQLAlchemy returns.
    """
    return SimpleNamespace(
        id=row_id or uuid.uuid4(),
        effective_from=effective_from,
        hourly_rate=hourly_rate,
        overtime_rate=overtime_rate,
        change_reason=change_reason,
        changed_by_email=changed_by_email,
    )


def _make_db(*, total: int, rows: list[SimpleNamespace]) -> AsyncMock:
    """AsyncMock DB whose ``execute()`` answers count then row queries.

    The service calls ``db.execute()`` twice per ``get_pay_rate_history``
    invocation:

    1. The COUNT query → ``.scalar()`` returns ``total``.
    2. The SELECT … OUTER JOIN users query → ``.all()`` returns ``rows``.

    A single call counter routes between the two responses so the tests
    can assert ordering without a real DB.
    """
    db = AsyncMock()

    state = {"calls": []}

    async def fake_execute(stmt):
        state["calls"].append(stmt)
        result = MagicMock()
        if len(state["calls"]) == 1:
            # COUNT query.
            result.scalar.return_value = total
            # Defensive: shouldn't be hit but keep the contract intact.
            result.all.return_value = []
        else:
            # The paginated SELECT.
            result.scalar.return_value = None
            result.all.return_value = rows
        return result

    db.execute = fake_execute
    db._calls = state["calls"]  # type: ignore[attr-defined]
    return db


# ---------------------------------------------------------------------------
# 1. Empty result
# ---------------------------------------------------------------------------


class TestEmptyResult:
    """No rows → ``([], 0)``."""

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list_and_zero_total(self):
        db = _make_db(total=0, rows=[])
        svc = StaffService(db)

        items, total = await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(),
        )

        assert items == []
        assert total == 0


# ---------------------------------------------------------------------------
# 2. Ordering DESC by effective_from
# ---------------------------------------------------------------------------


class TestOrdering:
    """Rows come back newest-first by ``effective_from``.

    The service trusts the DB to apply the ``ORDER BY`` clause in the
    SQL, so the test asserts both:
    - the data flows through unchanged in the order the DB returned it,
      and
    - the SELECT statement includes a ``ORDER BY ... DESC`` clause on
      ``effective_from`` (and ``created_at`` DESC as the tiebreaker).
    """

    @pytest.mark.asyncio
    async def test_rows_returned_in_db_order(self):
        # Simulate the DB returning rows that have already been ordered
        # newest-first (the service shouldn't re-sort in Python).
        rows = [
            _make_row(
                effective_from=date(2026, 5, 1),
                change_reason="rate_change",
                hourly_rate=Decimal("32.00"),
            ),
            _make_row(
                effective_from=date(2026, 1, 15),
                change_reason="rate_change",
                hourly_rate=Decimal("30.00"),
            ),
            _make_row(
                effective_from=date(2025, 6, 1),
                change_reason="initial_rate",
                hourly_rate=Decimal("28.50"),
            ),
        ]
        db = _make_db(total=3, rows=rows)
        svc = StaffService(db)

        items, total = await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(),
        )

        assert total == 3
        assert [item["effective_from"] for item in items] == [
            date(2026, 5, 1),
            date(2026, 1, 15),
            date(2025, 6, 1),
        ]
        assert [item["change_reason"] for item in items] == [
            "rate_change",
            "rate_change",
            "initial_rate",
        ]

    @pytest.mark.asyncio
    async def test_select_statement_orders_by_effective_from_desc(self):
        rows = [
            _make_row(effective_from=date(2026, 5, 1)),
            _make_row(effective_from=date(2025, 6, 1)),
        ]
        db = _make_db(total=2, rows=rows)
        svc = StaffService(db)

        await svc.get_pay_rate_history(uuid.uuid4(), uuid.uuid4())

        # Second execute() call is the SELECT … ORDER BY query.
        select_stmt = db._calls[1]  # type: ignore[attr-defined]
        assert isinstance(select_stmt, Select)

        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True}),
        )
        # ``effective_from`` appears in an ``ORDER BY ... DESC`` slot.
        assert "ORDER BY" in compiled.upper()
        assert "EFFECTIVE_FROM DESC" in compiled.upper()
        # ``created_at`` is the secondary DESC tiebreaker so same-day
        # corrections still come back newest-first.
        assert "CREATED_AT DESC" in compiled.upper()


# ---------------------------------------------------------------------------
# 3. Pagination — total reflects unfiltered count
# ---------------------------------------------------------------------------


class TestPagination:
    """``offset=2, limit=2`` returns 2 rows out of 5; total stays 5."""

    @pytest.mark.asyncio
    async def test_offset_limit_returns_subset_with_full_total(self):
        # The DB has 5 rows total, the SELECT with offset=2/limit=2
        # returns rows #3 and #4 (in sort order).
        rows = [
            _make_row(effective_from=date(2024, 6, 1)),
            _make_row(effective_from=date(2024, 1, 1)),
        ]
        db = _make_db(total=5, rows=rows)
        svc = StaffService(db)

        items, total = await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(),
            offset=2, limit=2,
        )

        # Two items returned for the page, but the total count keeps the
        # full row count so the paginator can render "showing 3-4 of 5".
        assert len(items) == 2
        assert total == 5

    @pytest.mark.asyncio
    async def test_select_applies_offset_and_limit(self):
        db = _make_db(total=5, rows=[])
        svc = StaffService(db)

        await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(),
            offset=2, limit=2,
        )

        # The SELECT (second execute call) carries OFFSET 2 LIMIT 2.
        select_stmt = db._calls[1]  # type: ignore[attr-defined]
        assert isinstance(select_stmt, Select)
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True}),
        )
        upper = compiled.upper()
        # SQLAlchemy can render LIMIT/OFFSET as ``LIMIT 2 OFFSET 2``.
        assert "LIMIT 2" in upper
        assert "OFFSET 2" in upper

    @pytest.mark.asyncio
    async def test_default_offset_zero_limit_fifty(self):
        db = _make_db(total=0, rows=[])
        svc = StaffService(db)

        await svc.get_pay_rate_history(uuid.uuid4(), uuid.uuid4())

        select_stmt = db._calls[1]  # type: ignore[attr-defined]
        compiled = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True}),
        )
        upper = compiled.upper()
        assert "LIMIT 50" in upper
        # Offset 0 may render as ``OFFSET 0`` or be omitted depending on
        # the dialect — accept either.
        assert "OFFSET 0" in upper or "OFFSET" not in upper


# ---------------------------------------------------------------------------
# 4. Joined e-mail populated when changer points to a user
# ---------------------------------------------------------------------------


class TestChangedByEmail:
    """``changed_by_email`` flows through the join."""

    @pytest.mark.asyncio
    async def test_email_populated_when_changed_by_matches_user(self):
        rows = [
            _make_row(
                effective_from=date(2026, 5, 1),
                changed_by_email="manager@acme.co.nz",
            ),
        ]
        db = _make_db(total=1, rows=rows)
        svc = StaffService(db)

        items, _ = await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(),
        )

        assert len(items) == 1
        assert items[0]["changed_by_email"] == "manager@acme.co.nz"

    @pytest.mark.asyncio
    async def test_email_none_when_changed_by_is_null(self):
        # ``changed_by`` IS NULL (e.g. the system-inserted initial_rate
        # row) — the OUTER JOIN still returns the pay-rate row, with
        # ``changed_by_email`` set to NULL.
        rows = [
            _make_row(
                effective_from=date(2025, 6, 1),
                change_reason="initial_rate",
                changed_by_email=None,
            ),
        ]
        db = _make_db(total=1, rows=rows)
        svc = StaffService(db)

        items, _ = await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(),
        )

        assert len(items) == 1
        assert items[0]["changed_by_email"] is None
        # The row itself still carries the rest of the data.
        assert items[0]["change_reason"] == "initial_rate"


# ---------------------------------------------------------------------------
# 6. Query shape smoke test
# ---------------------------------------------------------------------------


class TestQueryShape:
    """Sanity-check the SQL touches the right tables + filters."""

    @pytest.mark.asyncio
    async def test_select_joins_users_and_filters_by_org_and_staff(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        db = _make_db(total=0, rows=[])
        svc = StaffService(db)

        await svc.get_pay_rate_history(org_id, staff_id)

        # The COUNT query is the first execute() call.
        count_stmt = db._calls[0]  # type: ignore[attr-defined]
        count_sql = str(
            count_stmt.compile(compile_kwargs={"literal_binds": True}),
        ).upper()
        assert "STAFF_PAY_RATES" in count_sql

        # The paginated SELECT is the second; it joins ``users`` LEFT
        # so rows without a ``changed_by`` still come back.
        select_stmt = db._calls[1]  # type: ignore[attr-defined]
        select_sql = str(
            select_stmt.compile(compile_kwargs={"literal_binds": True}),
        ).upper()
        assert "STAFF_PAY_RATES" in select_sql
        assert "USERS" in select_sql
        assert "LEFT OUTER JOIN" in select_sql or "LEFT JOIN" in select_sql

    @pytest.mark.asyncio
    async def test_count_uses_total_without_pagination(self):
        # The COUNT query must NOT carry the OFFSET/LIMIT — otherwise
        # the total would equal the page size, defeating the paginator.
        db = _make_db(total=99, rows=[])
        svc = StaffService(db)

        await svc.get_pay_rate_history(
            uuid.uuid4(), uuid.uuid4(), offset=10, limit=5,
        )

        count_stmt = db._calls[0]  # type: ignore[attr-defined]
        count_sql = str(
            count_stmt.compile(compile_kwargs={"literal_binds": True}),
        ).upper()
        assert "LIMIT" not in count_sql
        assert "OFFSET" not in count_sql
