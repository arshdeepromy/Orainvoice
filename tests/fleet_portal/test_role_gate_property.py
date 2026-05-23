"""Property test for role gate (Property 11, Req 5.1, 12.1, 13.7, 14.1, 17.5).

Tests the dependency-level role check by invoking
``require_fleet_admin`` and ``require_driver_or_admin`` directly with
synthetic FleetSessionCtx values and asserting the spec'd HTTP 403
behaviour for drivers on admin-only paths.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from hypothesis import given, settings as hyp_settings
from hypothesis import strategies as st

from app.modules.fleet_portal.dependencies import (
    FleetSessionCtx,
    require_driver_or_admin,
    require_fleet_admin,
)


def _ctx(role: str) -> FleetSessionCtx:
    return FleetSessionCtx(
        org_id=uuid4(),
        portal_account_id=uuid4(),
        portal_user_role=role,
        fleet_account_id=uuid4(),
        email="user@example.com",
        session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_admin_dependency_passes_admin() -> None:
    ctx = _ctx("fleet_admin")
    out = await require_fleet_admin(ctx)
    assert out is ctx


@pytest.mark.asyncio
async def test_admin_dependency_rejects_driver() -> None:
    ctx = _ctx("driver")
    with pytest.raises(HTTPException) as exc:
        await require_fleet_admin(ctx)
    assert exc.value.status_code == 403
    assert "Fleet Account Admin" in exc.value.detail


@pytest.mark.asyncio
async def test_driver_or_admin_passes_both() -> None:
    for role in ("fleet_admin", "driver"):
        ctx = _ctx(role)
        out = await require_driver_or_admin(ctx)
        assert out.portal_user_role == role


@given(role=st.sampled_from(["fleet_admin", "driver"]))
@hyp_settings(max_examples=50)
@pytest.mark.asyncio
async def test_admin_only_iff_fleet_admin(role: str) -> None:
    """Property 11 — admin gate succeeds iff role == 'fleet_admin'."""
    ctx = _ctx(role)
    if role == "fleet_admin":
        out = await require_fleet_admin(ctx)
        assert out.portal_user_role == "fleet_admin"
    else:
        with pytest.raises(HTTPException):
            await require_fleet_admin(ctx)
