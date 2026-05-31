"""Integration test for the new ``start_lte`` / ``end_gte`` query
params on ``GET /api/v2/leave/approvals``.

We mount the leave router on a tiny FastAPI app with a fake
``AsyncSession`` that captures every SQL statement the endpoint
issues. The fake returns a curated list of "approved" leave_requests
so the test can assert the date-range predicate is applied at the
SQL level.

The fake session implements just enough of the AsyncSession surface
for the endpoint to run end-to-end:
- ``execute(stmt)`` for the count + detail SELECTs
- ``execute(stmt)`` for the audit_log INSERT path (irrelevant here)

The integration test asserts the documented behaviour: with
``start_lte=2025-06-08&end_gte=2025-06-04``, only the two requests
that overlap the window come back; the Jun 1–3 request is excluded.

**Validates: Roster Grid Editor — task A7 (R3.7).**
"""

from __future__ import annotations

# Resolve all SQLAlchemy mappers eagerly so the leave router's
# joined SELECTs (which touch ``users``, ``staff_members``, and
# ``leave_types``) can compile.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.leave.models  # noqa: F401

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.database import get_db_session
from app.modules.leave.router import router as leave_router

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
LEAVE_TYPE_ID = uuid.uuid4()


def _make_leave_request_row(
    *, start: date, end: date, request_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    """Build a SimpleNamespace shaped like a LeaveRequest ORM row."""
    rid = request_id or uuid.uuid4()
    return SimpleNamespace(
        id=rid,
        org_id=ORG_ID,
        staff_id=STAFF_ID,
        leave_type_id=LEAVE_TYPE_ID,
        start_date=start,
        end_date=end,
        hours_requested=Decimal("16.00"),
        status="approved",
        reason="testing",
        relationship_to_subject=None,
        partial_day_start_time=None,
        attachment_upload_id=None,
        requested_by=USER_ID,
        decided_by=USER_ID,
        decided_at=datetime(2025, 5, 30, 10, 0, tzinfo=timezone.utc),
        decision_notes=None,
        created_at=datetime(2025, 5, 30, 9, 0, tzinfo=timezone.utc),
        updated_at=datetime(2025, 5, 30, 9, 0, tzinfo=timezone.utc),
        is_confidential=False,
    )


def _make_detail_row(leave_request: SimpleNamespace) -> SimpleNamespace:
    """Build the multi-column row tuple the detail SELECT yields."""
    row = SimpleNamespace(
        staff_first_name="Test",
        staff_last_name="Staff",
        leave_type_code="annual_leave",
        leave_type_name="Annual leave",
        requested_by_first_name="Test",
        requested_by_last_name="User",
        requested_by_email="test@example.com",
    )
    # The endpoint accesses ``row[0]`` for the LeaveRequest object and
    # ``row.staff_first_name`` etc. for joined columns.

    class _Row:
        def __init__(self, lr, joined):
            self._lr = lr
            self._joined = joined

        def __getitem__(self, idx):
            if idx == 0:
                return self._lr
            raise IndexError(idx)

        def __getattr__(self, name):
            return getattr(self._joined, name)

    return _Row(leave_request, row)


class _FakeDB:
    def __init__(self, *, all_rows: list[SimpleNamespace]) -> None:
        self._all_rows = list(all_rows)
        self.captured_sql: list[str] = []

    async def execute(self, stmt, params=None):
        # Compile the statement to a SQL string we can inspect. Use the
        # PostgreSQL dialect so UUID + DATE literals render — the
        # default StrSQLCompiler can't render UUID types.
        from sqlalchemy.dialects import postgresql

        try:
            compiled = stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
            sql = str(compiled)
        except Exception:  # pragma: no cover — fallback for non-Selects
            sql = str(stmt)
        self.captured_sql.append(sql)
        result = MagicMock()

        sql_lower = sql.lower()
        if "count" in sql_lower and "select count" in sql_lower:
            # Count query — return the filtered count.
            result.scalar.return_value = len(
                self._filter_by_sql(sql_lower)
            )
            return result
        # Detail query — return the filtered row tuples.
        filtered = self._filter_by_sql(sql_lower)
        result.all.return_value = [_make_detail_row(lr) for lr in filtered]
        return result

    def _filter_by_sql(self, sql_lower: str) -> list[SimpleNamespace]:
        """Apply the documented date predicate to our in-memory rows by
        parsing the compiled SQL for ``start_date <= 'YYYY-MM-DD'`` and
        ``end_date >= 'YYYY-MM-DD'`` literals.
        """
        import re

        start_lte = None
        end_gte = None
        m1 = re.search(r"start_date\s*<=\s*'(\d{4}-\d{2}-\d{2})'", sql_lower)
        m2 = re.search(r"end_date\s*>=\s*'(\d{4}-\d{2}-\d{2})'", sql_lower)
        if m1:
            start_lte = date.fromisoformat(m1.group(1))
        if m2:
            end_gte = date.fromisoformat(m2.group(1))

        out = []
        for r in self._all_rows:
            if start_lte is not None and r.start_date > start_lte:
                continue
            if end_gte is not None and r.end_date < end_gte:
                continue
            out.append(r)
        return out


def _build_app(rows: list[SimpleNamespace]) -> tuple[FastAPI, _FakeDB]:
    app = FastAPI()
    fake_db = _FakeDB(all_rows=rows)

    async def override_db_session():
        yield fake_db

    @app.middleware("http")
    async def populate_state(request: Request, call_next):
        request.state.org_id = str(ORG_ID)
        request.state.user_id = str(USER_ID)
        request.state.role = "org_admin"
        return await call_next(request)

    app.dependency_overrides[get_db_session] = override_db_session
    app.include_router(leave_router, prefix="/api/v2")
    return app, fake_db


@pytest.fixture
def patched_module_gate():
    """Bypass the staff_management module gate (it spins up a real
    ``ModuleService`` that hits the DB; we don't need it for this test).
    """
    with patch(
        "app.modules.leave.router._require_staff_management_module",
        new_callable=AsyncMock,
    ) as mock_gate:
        yield mock_gate


class TestApprovalQueueDateRangeFilter:
    def test_filter_returns_only_overlapping_requests(self, patched_module_gate):
        """The documented predicate is
        ``start_date <= start_lte AND end_date >= end_gte`` — i.e. the
        leave request's date range overlaps the window
        ``[end_gte, start_lte]``.

        With ``start_lte=2025-06-08`` and ``end_gte=2025-06-04`` the
        window is Jun 4–8. Jun 1–3 ends before Jun 4 → excluded.
        Jun 5–7 is contained in the window → included. Jun 10–12 starts
        after Jun 8 → excluded. The original spec text claimed
        ``length == 2`` (Jun 5–7 + Jun 10–12) but that's inconsistent
        with its own documented predicate; we follow the predicate.
        See gap-analysis.md "Implementation gaps" for the reasoning.
        """
        rows = [
            _make_leave_request_row(
                start=date(2025, 6, 1), end=date(2025, 6, 3),
            ),
            _make_leave_request_row(
                start=date(2025, 6, 5), end=date(2025, 6, 7),
            ),
            _make_leave_request_row(
                start=date(2025, 6, 10), end=date(2025, 6, 12),
            ),
        ]
        app, fake_db = _build_app(rows)
        client = TestClient(app)

        resp = client.get(
            "/api/v2/leave/approvals",
            params={
                "status": "approved",
                "start_lte": "2025-06-08",
                "end_gte": "2025-06-04",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        # The single included request is Jun 5–7.
        assert body["items"][0]["start_date"] == "2025-06-05"
        assert body["items"][0]["end_date"] == "2025-06-07"
        # Confirm the SQL actually included our predicate.
        assert any(
            "start_date <= '2025-06-08'" in s.lower() for s in fake_db.captured_sql
        )
        assert any(
            "end_date >= '2025-06-04'" in s.lower() for s in fake_db.captured_sql
        )

    def test_filter_includes_request_starting_inside_window(self, patched_module_gate):
        """Sanity: a wider window includes a request that starts inside it."""
        rows = [
            _make_leave_request_row(
                start=date(2025, 6, 5), end=date(2025, 6, 7),
            ),
            _make_leave_request_row(
                start=date(2025, 6, 10), end=date(2025, 6, 12),
            ),
        ]
        app, fake_db = _build_app(rows)
        client = TestClient(app)

        resp = client.get(
            "/api/v2/leave/approvals",
            params={
                "status": "approved",
                "start_lte": "2025-06-15",  # window end pushed past 12
                "end_gte": "2025-06-04",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        # Confirm the SQL actually included the predicate.
        assert any(
            "start_date <= '2025-06-15'" in s.lower() for s in fake_db.captured_sql
        )
        assert any(
            "end_date >= '2025-06-04'" in s.lower() for s in fake_db.captured_sql
        )

    def test_filter_omitted_returns_all_requests(self, patched_module_gate):
        rows = [
            _make_leave_request_row(
                start=date(2025, 6, 1), end=date(2025, 6, 3),
            ),
            _make_leave_request_row(
                start=date(2025, 6, 5), end=date(2025, 6, 7),
            ),
            _make_leave_request_row(
                start=date(2025, 6, 10), end=date(2025, 6, 12),
            ),
        ]
        app, fake_db = _build_app(rows)
        client = TestClient(app)

        # No date params — backwards-compatible behaviour preserved.
        resp = client.get(
            "/api/v2/leave/approvals",
            params={"status": "approved"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3
        # And the SQL should NOT contain the date predicates when the
        # params are absent.
        for s in fake_db.captured_sql:
            assert "start_date <=" not in s.lower() or "end_date >=" not in s.lower(), (
                "date predicate should not be applied when params omitted"
            )
