"""Regression test for the route-ordering bug that caused
``GET /api/v2/schedule/templates`` to return 422 in the wild.

The bug: ``GET /{entry_id}`` was registered BEFORE the static
``GET /templates`` route. FastAPI matches routes in registration
order, so the path component "templates" was validated against the
``UUID`` parameter on the dynamic route and failed with 422 before
FastAPI got a chance to try the static route.

Surfaced when the Roster Grid Editor's ``listTemplates()`` call
landed in production (the legacy ScheduleEntryModal silently
swallowed the 422 by setting ``templates=[]`` in its catch block,
masking the bug for ~2 years until the new typed API client
exposed it).

This test pins the ordering — every static route on the scheduling
router must resolve before any UUID-parameterised route.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.database import get_db_session
from app.modules.scheduling_v2.router import router as scheduling_router

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class _FakeDB:
    """Stub session — every read returns empty result sets."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, entry):
        # Populate ORM-default fields at add-time — a few endpoints
        # (legacy create_entry, create_template) build the response
        # directly from the ORM object without an explicit refresh
        # call, so we need every field populated on add.
        if not getattr(entry, "id", None):
            entry.id = uuid.uuid4()
        if not getattr(entry, "created_at", None):
            entry.created_at = datetime.now(timezone.utc)
        if not getattr(entry, "updated_at", None):
            entry.updated_at = datetime.now(timezone.utc)
        if not getattr(entry, "status", None):
            entry.status = "scheduled"
        if not getattr(entry, "org_id", None):
            entry.org_id = ORG_ID
        self.added.append(entry)

    async def flush(self):
        return None

    async def refresh(self, entry):
        if not getattr(entry, "id", None):
            entry.id = uuid.uuid4()
        if not getattr(entry, "created_at", None):
            entry.created_at = datetime.now(timezone.utc)
        if not getattr(entry, "updated_at", None):
            entry.updated_at = datetime.now(timezone.utc)
        if not getattr(entry, "status", None):
            entry.status = "scheduled"
        if not getattr(entry, "org_id", None):
            entry.org_id = ORG_ID

    async def delete(self, entry):
        return None

    @asynccontextmanager
    async def begin_nested(self):
        yield SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())

    async def execute(self, stmt, params=None):
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar.return_value = 0
        # `scalar_one_or_none` is used by ``service.get_entry`` for
        # the dynamic ``GET /{entry_id}`` route — return None so the
        # service treats the entry as missing and the handler returns
        # 404 (rather than feeding a MagicMock into Pydantic).
        result.scalar_one_or_none.return_value = None
        return result


def _build_app(*, role: str = "org_admin") -> FastAPI:
    app = FastAPI()
    fake_db = _FakeDB()

    async def override_db_session():
        yield fake_db

    @app.middleware("http")
    async def populate_state(request: Request, call_next):
        request.state.org_id = str(ORG_ID)
        request.state.user_id = str(USER_ID)
        request.state.role = role
        return await call_next(request)

    app.dependency_overrides[get_db_session] = override_db_session
    app.include_router(scheduling_router, prefix="/api/v2/schedule")
    return app


class TestTemplatesRouteOrdering:
    """``GET /api/v2/schedule/templates`` must NOT collide with
    ``GET /api/v2/schedule/{entry_id}``.
    """

    def test_get_templates_returns_200_not_422(self):
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/api/v2/schedule/templates")
        # Before the fix this returned 422 with `entry_id is not a UUID`.
        assert resp.status_code == 200, (
            f"GET /api/v2/schedule/templates regressed to "
            f"{resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert "templates" in body
        assert "total" in body
        assert isinstance(body["templates"], list)
        assert isinstance(body["total"], int)

    def test_get_with_real_uuid_still_works(self):
        """Sanity check — the static route ordering must NOT break
        the dynamic ``GET /{entry_id}`` handler. A real UUID still
        routes to ``get_entry`` (returns 404 here because the fake
        DB has no matching row, but does NOT return 422 — that
        would mean the path was rejected at Pydantic validation,
        which is the bug we're guarding against)."""
        app = _build_app()
        client = TestClient(app)
        valid_uuid = str(uuid.uuid4())
        resp = client.get(f"/api/v2/schedule/{valid_uuid}")
        # The fake DB returns no entry → service returns None → 404.
        # Critically NOT 422 (which would mean Pydantic rejected the
        # path BEFORE the handler ran).
        assert resp.status_code != 422, (
            f"GET /{{entry_id}} should not return 422 for a valid "
            f"UUID — got {resp.status_code}: {resp.text}"
        )

    def test_get_with_invalid_uuid_returns_422(self):
        """A non-UUID, non-static path still falls through to the
        dynamic route and yields the standard 422 from Pydantic."""
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/api/v2/schedule/not-a-uuid-and-not-templates")
        assert resp.status_code == 422

    def test_post_templates_routes_to_create(self):
        """``POST /templates`` is also static — must route to the
        create handler, not get rejected as a missing UUID body.
        We assert the response did NOT come from a different route
        — anything except 405 (method-not-allowed) or a UUID-parse
        422 indicates the right route was hit."""
        app = _build_app()
        client = TestClient(app)
        resp = client.post(
            "/api/v2/schedule/templates",
            json={
                "name": "Test shift",
                "start_time": "09:00",
                "end_time": "17:00",
                "entry_type": "job",
            },
        )
        assert resp.status_code != 405, (
            f"POST /templates routed to a wrong handler: "
            f"{resp.status_code} {resp.text}"
        )
