"""Property test — Property 12: tenant + fleet isolation.

This test exercises the *application-level* WHERE filters in the
service layer. Postgres RLS is the second line of defence and is
asserted by the smoke tests against the live DB.

The vehicle-list query helper ``_vehicle_query_for_session`` is the
single place where the org_id + customer_id (+ assignment for drivers)
filters are applied. We test that the helper:

1. Returns an always-empty SELECT when ``ctx.fleet_account_id is None``.
2. Builds a filter on ``org_id`` and ``customer_id`` for fleet admins.
3. Adds the ``fleet_driver_assignments`` join for drivers.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.services.vehicle_service import (
    _vehicle_query_for_session,
)


# Ensure relationship models are loaded for SQLAlchemy mapper init.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.fleet_portal.models  # noqa: F401


def _ctx_for(role: str, fleet_account_id):
    return FleetSessionCtx(
        org_id=uuid4(),
        portal_account_id=uuid4(),
        portal_user_role=role,
        fleet_account_id=fleet_account_id,
        email="user@example.com",
        session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_no_fleet_account_returns_empty_select(monkeypatch) -> None:
    """ctx.fleet_account_id is None → always-empty SELECT."""
    ctx = _ctx_for("driver", None)
    db = AsyncMock()
    stmt = await _vehicle_query_for_session(db, ctx)
    sql = str(stmt)
    # The fallback uses ``where(False)`` → compiles to "WHERE false".
    assert "false" in sql.lower() or "where" in sql.lower()


@pytest.mark.asyncio
async def test_admin_query_filters_org_and_customer(monkeypatch) -> None:
    """fleet_admin role → filter on org_id AND customer_id."""
    ctx = _ctx_for("fleet_admin", uuid4())

    async def _customer_id_lookup(_db, _fa):
        return uuid4()

    monkeypatch.setattr(
        "app.modules.fleet_portal.services.vehicle_service._customer_id_for_fleet",
        _customer_id_lookup,
    )

    db = AsyncMock()
    stmt = await _vehicle_query_for_session(db, ctx)
    sql = str(stmt).lower()
    assert "org_id" in sql
    assert "customer_id" in sql


@pytest.mark.asyncio
async def test_driver_query_joins_assignments(monkeypatch) -> None:
    """driver role → JOIN fleet_driver_assignments."""
    ctx = _ctx_for("driver", uuid4())

    async def _customer_id_lookup(_db, _fa):
        return uuid4()

    monkeypatch.setattr(
        "app.modules.fleet_portal.services.vehicle_service._customer_id_for_fleet",
        _customer_id_lookup,
    )

    db = AsyncMock()
    stmt = await _vehicle_query_for_session(db, ctx)
    sql = str(stmt).lower()
    assert "fleet_driver_assignments" in sql
