"""Integration tests for GET /org/plan-sms-pricing (reports-remediation C3).

These exercise the HTTP endpoint end-to-end (router + ``require_role`` guard +
``PlanSmsPricingResponse`` serialisation) with a mocked DB session, asserting
the contract introduced by the reports-remediation spec:

  - Tiers are returned when the org plan has ``sms_package_pricing`` (R8.1).
  - An empty list is returned when the plan has no tiers, whether the DB row
    is ``None`` or already ``[]`` (R8.2).
  - The endpoint is guarded by ``require_role("org_admin")`` — a non-org_admin
    role receives 403 (R8.1 WHERE-clause).

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

# Ensure ORM models are registered for relationship resolution.
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.core.database import get_db_session
from app.modules.organisations.router import router


# A representative set of plan tiers as stored in the JSONB column.
SAMPLE_TIERS = [
    {"tier_name": "500 SMS", "sms_quantity": 500, "price_nzd": 49.99},
    {"tier_name": "1000 SMS", "sms_quantity": 1000, "price_nzd": 89.0},
]


def _build_db(*, scalar_value) -> AsyncMock:
    """Build a mock async DB whose execute().scalar_one_or_none() returns the
    given value (the plan's ``sms_package_pricing`` JSONB, ``[]``, or ``None``).
    """
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _build_app(*, org_id: str | None, role: str, db: AsyncMock) -> FastAPI:
    """Minimal FastAPI app mounting the organisations router with mocked auth
    context (via middleware injecting request.state) and a mocked DB."""
    app = FastAPI()

    @app.middleware("http")
    async def _inject_context(request: Request, call_next):  # noqa: ANN001
        request.state.user_id = str(uuid.uuid4())
        if org_id is not None:
            request.state.org_id = org_id
        request.state.role = role
        return await call_next(request)

    async def _override_db():
        yield db

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(router, prefix="/api/v1/org")
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPlanSmsPricingEndpoint:
    """GET /org/plan-sms-pricing — tiers, empty list, and org_admin guard."""

    @pytest.mark.asyncio
    async def test_returns_tiers_when_plan_has_them(self):
        """An org_admin gets the plan's configured SMS package tiers (R8.1)."""
        org_id = str(uuid.uuid4())
        db = _build_db(scalar_value=SAMPLE_TIERS)
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/org/plan-sms-pricing")

        assert resp.status_code == 200
        data = resp.json()
        tiers = data["sms_package_pricing"]
        assert [t["tier_name"] for t in tiers] == ["500 SMS", "1000 SMS"]
        assert tiers[0]["sms_quantity"] == 500
        assert tiers[0]["price_nzd"] == 49.99
        assert tiers[1]["sms_quantity"] == 1000

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_plan_has_no_tiers_none_row(self):
        """When the plan row resolves to None, the response is `[]` (R8.2)."""
        org_id = str(uuid.uuid4())
        db = _build_db(scalar_value=None)
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/org/plan-sms-pricing")

        assert resp.status_code == 200
        assert resp.json()["sms_package_pricing"] == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_plan_has_no_tiers_empty_row(self):
        """When the plan's pricing is already an empty list, so is the response (R8.2)."""
        org_id = str(uuid.uuid4())
        db = _build_db(scalar_value=[])
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/org/plan-sms-pricing")

        assert resp.status_code == 200
        assert resp.json()["sms_package_pricing"] == []

    @pytest.mark.asyncio
    async def test_org_admin_guard_blocks_non_admin_role(self):
        """A non-org_admin role is denied with 403 by require_role (R8.1)."""
        org_id = str(uuid.uuid4())
        db = _build_db(scalar_value=SAMPLE_TIERS)
        app = _build_app(org_id=org_id, role="salesperson", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/org/plan-sms-pricing")

        assert resp.status_code == 403
        # The guard never reaches the handler, so the DB is not queried.
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_org_admin_guard_allows_org_admin_role(self):
        """The org_admin role passes the guard and reaches the handler (R8.1)."""
        org_id = str(uuid.uuid4())
        db = _build_db(scalar_value=SAMPLE_TIERS)
        app = _build_app(org_id=org_id, role="org_admin", db=db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/org/plan-sms-pricing")

        assert resp.status_code == 200
        db.execute.assert_awaited_once()
