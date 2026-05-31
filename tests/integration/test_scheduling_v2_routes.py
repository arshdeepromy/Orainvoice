"""Integration tests for the new bulk + copy-week routes on
``/api/v2/schedule``.

These tests use a TestClient against a small FastAPI app that mounts
the scheduling router with the project's standard dependency-override
pattern. We override:

- ``get_db_session`` to yield a fake AsyncSession that captures the
  service's writes without hitting Postgres.
- ``request.state.org_id`` / ``user_id`` / ``role`` via a tiny
  middleware so the route's ``_get_org_id`` helper + the
  ``require_role`` dependency see the right values.

**Validates: Roster Grid Editor — task A5 / A6.**
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.database import get_db_session
from app.modules.scheduling_v2.router import router as scheduling_router

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
BASE_TIME = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)


def _entry_payload(*, offset_hours: int = 0) -> dict:
    return {
        "staff_id": str(STAFF_ID),
        "title": f"Shift +{offset_hours}h",
        "start_time": (BASE_TIME + timedelta(hours=offset_hours)).isoformat(),
        "end_time": (BASE_TIME + timedelta(hours=offset_hours + 2)).isoformat(),
        "entry_type": "job",
    }


class _FakeDB:
    """Captures audit writes; stubs flush/refresh; stubs execute returns
    empty result sets so the service's SELECT for sources is empty.
    """

    def __init__(self) -> None:
        self.added: list = []
        self.deleted: list = []
        self.audit_writes: list[dict] = []

    def add(self, entry):
        # Populate ORM-default-ish fields the test relies on. Real
        # SQLAlchemy fills these from server defaults / Python defaults
        # at flush time; the legacy create_entry route does not call
        # ``db.refresh()`` so we must populate at add-time.
        if not getattr(entry, "id", None):
            entry.id = uuid.uuid4()
        if not getattr(entry, "status", None):
            entry.status = "scheduled"
        if not getattr(entry, "created_at", None):
            entry.created_at = datetime.now(timezone.utc)
        if not getattr(entry, "updated_at", None):
            entry.updated_at = datetime.now(timezone.utc)
        if not getattr(entry, "org_id", None):
            entry.org_id = ORG_ID
        self.added.append(entry)

    async def flush(self):
        return None

    async def refresh(self, entry):
        if not getattr(entry, "id", None):
            entry.id = uuid.uuid4()
        if not getattr(entry, "status", None):
            entry.status = "scheduled"
        if not getattr(entry, "created_at", None):
            entry.created_at = datetime.now(timezone.utc)
        if not getattr(entry, "updated_at", None):
            entry.updated_at = datetime.now(timezone.utc)
        if not getattr(entry, "org_id", None):
            entry.org_id = ORG_ID

    async def delete(self, entry):
        self.deleted.append(entry)

    @asynccontextmanager
    async def begin_nested(self):
        yield SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO audit_log" in sql:
            if params is not None:
                self.audit_writes.append(params)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        return result


def _build_app(*, role: str = "org_admin", authenticated: bool = True) -> tuple[FastAPI, _FakeDB]:
    app = FastAPI()

    fake_db = _FakeDB()

    async def override_db_session():
        yield fake_db

    @app.middleware("http")
    async def populate_state(request: Request, call_next):
        if authenticated:
            request.state.org_id = str(ORG_ID)
            request.state.user_id = str(USER_ID)
            request.state.role = role
        # When unauthenticated, we deliberately leave state.org_id /
        # user_id / role unset so the route's ``_get_org_id`` returns
        # 401 and ``require_role`` returns 401.
        return await call_next(request)

    app.dependency_overrides[get_db_session] = override_db_session
    app.include_router(scheduling_router, prefix="/api/v2/schedule")
    return app, fake_db


class TestBulkRouteRBAC:
    def test_unauth_request_returns_401(self):
        app, _ = _build_app(authenticated=False)
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/bulk",
            json={"entries": [_entry_payload()]},
        )
        assert resp.status_code == 401

    def test_staff_member_role_returns_403(self):
        app, _ = _build_app(role="staff_member")
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/bulk",
            json={"entries": [_entry_payload()]},
        )
        assert resp.status_code == 403

    def test_org_admin_role_returns_200(self):
        app, _ = _build_app(role="org_admin")
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/bulk",
            json={"entries": [_entry_payload()]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "created" in body
        assert "conflicts" in body
        assert isinstance(body["created"], list)
        assert isinstance(body["conflicts"], list)

    def test_salesperson_role_returns_200(self):
        app, _ = _build_app(role="salesperson")
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/bulk",
            json={"entries": [_entry_payload()]},
        )
        assert resp.status_code == 200


class TestBulkRouteValidation:
    def test_zero_entries_returns_422(self):
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post("/api/v2/schedule/bulk", json={"entries": []})
        assert resp.status_code == 422

    def test_201_entries_returns_422(self):
        app, _ = _build_app()
        client = TestClient(app)
        entries = [_entry_payload(offset_hours=i) for i in range(201)]
        resp = client.post("/api/v2/schedule/bulk", json={"entries": entries})
        assert resp.status_code == 422


class TestCopyWeekRouteRBAC:
    def test_unauth_returns_401(self):
        app, _ = _build_app(authenticated=False)
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/copy-week",
            json={
                "source_week_start": "2026-06-01",
                "target_week_start": "2026-06-08",
                "overwrite_existing": False,
            },
        )
        assert resp.status_code == 401

    def test_staff_member_returns_403(self):
        app, _ = _build_app(role="staff_member")
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/copy-week",
            json={
                "source_week_start": "2026-06-01",
                "target_week_start": "2026-06-08",
                "overwrite_existing": False,
            },
        )
        assert resp.status_code == 403

    def test_org_admin_returns_200(self):
        app, _ = _build_app(role="org_admin")
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/copy-week",
            json={
                "source_week_start": "2026-06-01",
                "target_week_start": "2026-06-08",
                "overwrite_existing": False,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"created": [], "conflicts": []}


class TestCopyWeekRouteValidation:
    def test_zero_delta_returns_422(self):
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/copy-week",
            json={
                "source_week_start": "2026-06-01",
                "target_week_start": "2026-06-01",
                "overwrite_existing": False,
            },
        )
        assert resp.status_code == 422

    def test_non_seven_day_delta_returns_422(self):
        app, _ = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/copy-week",
            json={
                "source_week_start": "2026-06-01",
                "target_week_start": "2026-06-04",
                "overwrite_existing": False,
            },
        )
        assert resp.status_code == 422


class TestExistingEndpointStillAcceptsStaffMember:
    """Regression: the existing single-entry POST /api/v2/schedule must
    still accept staff_member callers (CODE-GAP-8 — we deliberately
    do NOT add a role guard to the legacy endpoint).
    """

    def test_existing_post_accepts_staff_member(self):
        app, _ = _build_app(role="staff_member")
        client = TestClient(app)
        resp = client.post("/api/v2/schedule", json=_entry_payload())
        # No RBAC guard on the legacy endpoint → should be 201 (or
        # 200), NOT 403.
        assert resp.status_code in (200, 201), resp.text
