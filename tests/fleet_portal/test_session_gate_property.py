"""Property tests for module-disabled gate and staff-JWT rejection.

Implements:
- **Property 3** — Module-disabled gate is uniform and existence-preserving
  (Req 1.5, 1.6, 1.7, 17.6)
- **Property 5** — Staff JWTs cannot access fleet portal endpoints
  (Req 2.5, 2.6)

These are documented as "the dependency MUST behave this way" — the
unit tests below exercise the dependency directly with stubbed inputs.
The integration smoke tests (task 20.x) round-trip the same flows
against a live app.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.fleet_portal import dependencies as fp_deps


# ---------------------------------------------------------------------------
# Property 3 — module disabled returns 403; missing org returns 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_module_enabled_returns_404_when_no_org(monkeypatch) -> None:
    """No org → 404 (existence-preserving)."""

    async def _resolver_returns_none(_req, _db):
        return None

    monkeypatch.setattr(
        fp_deps, "resolve_workshop_org_from_request", _resolver_returns_none
    )
    request = MagicMock()
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await fp_deps.require_module_enabled(request, db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_require_module_enabled_returns_403_when_disabled(monkeypatch) -> None:
    """Module disabled → 403 with the spec-mandated message."""
    org = MagicMock()
    org.id = uuid4()

    async def _resolver_returns_org(_req, _db):
        return org

    async def _is_enabled_false(_db, _org_id, slug=""):
        return False

    monkeypatch.setattr(
        fp_deps, "resolve_workshop_org_from_request", _resolver_returns_org
    )
    monkeypatch.setattr(fp_deps, "_is_module_enabled", _is_enabled_false)

    request = MagicMock()
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await fp_deps.require_module_enabled(request, db)
    assert exc.value.status_code == 403
    assert "B2B Fleet Management" in exc.value.detail


# ---------------------------------------------------------------------------
# Property 5 — staff cookies cannot grant fleet portal access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_session_rejects_missing_cookie() -> None:
    """No fleet_portal_session cookie → 401, regardless of any other auth."""
    org = MagicMock()
    org.id = uuid4()

    request = MagicMock()
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await fp_deps.require_fleet_portal_session(
            request=request, org=org, fleet_session=None, db=db
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_session_rejects_token_link_session(monkeypatch) -> None:
    """A row whose ``portal_account_id IS NULL`` is a token-link
    customer-portal session, not a fleet portal session — must reject."""
    org = MagicMock()
    org.id = uuid4()

    async def _load_returns_none(_db, _token):
        return None

    monkeypatch.setattr(fp_deps, "_load_session", _load_returns_none)

    request = MagicMock()
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await fp_deps.require_fleet_portal_session(
            request=request,
            org=org,
            fleet_session="some-token",
            db=db,
        )
    assert exc.value.status_code == 401
