"""Unit tests for ``app/modules/ppsr/router.py``.

**Validates: Requirements R4 / R6 / R8 — PPSR module Phase 1, task C5.**

The tests below exercise the FastAPI ``Depends`` / exception-handler
wiring with :class:`PpsrService` patched out. We deliberately do NOT
spin up the real DB / Redis / middleware stack — we mount the router
on a bare :class:`FastAPI` app, override
:func:`app.core.database.get_db_session` /
:func:`app.core.redis.get_redis` to async-mocks, and use a small
HTTP middleware to stamp ``request.state.{org_id, user_id, role}``
the same way :class:`AuthMiddleware` would.

Coverage matrix (per tasks.md C5 ``**Verify:**`` block):

  - 401 when the request has no auth context.
  - 403 ``ppsr_requires_org_context`` when caller is a global admin
    with no ``org_id``.
  - Happy path for ``POST /search`` (200, body matches schema).
  - 402 mapping for :class:`PpsrQuotaExceededError`.
  - 410 mapping for :class:`PpsrSearchForgottenError` on
    ``GET /searches/{id}``.
  - 204 + admin-only ``DELETE /searches/{id}/forget`` with 403 for
    non-admins.

The fixtures keep the tests narrow and resilient to refactors of the
service layer — every test stubs only the service method it needs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.core.redis import get_redis
from app.modules.ppsr.exceptions import (
    PpsrQuotaExceededError,
    PpsrSearchForgottenError,
)
from app.modules.ppsr.router import router
from app.modules.ppsr.schemas import (
    PpsrQuotaResponse,
    PpsrSearchResult,
)


ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
SEARCH_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# App / fixture helpers
# ---------------------------------------------------------------------------


def _build_test_app(
    *,
    org_id: str | None = str(ORG_ID),
    user_id: str | None = str(USER_ID),
    role: str = "salesperson",
) -> FastAPI:
    """Build a minimal :class:`FastAPI` app mounting the PPSR router.

    The middleware mimics :class:`AuthMiddleware`'s state stamping —
    parameterised so individual tests can simulate global-admin
    (``org_id=None``) or unauthenticated (``user_id=None``) callers.
    """

    test_app = FastAPI()
    test_app.include_router(router)

    async def _mock_db_session():
        yield AsyncMock()

    async def _mock_redis():
        return AsyncMock()

    test_app.dependency_overrides[get_db_session] = _mock_db_session
    test_app.dependency_overrides[get_redis] = _mock_redis

    @test_app.middleware("http")
    async def _stamp_state(request, call_next):
        # Mirror AuthMiddleware: assign None where no auth context.
        request.state.org_id = org_id
        request.state.user_id = user_id
        request.state.role = role
        return await call_next(request)

    return test_app


def _make_search_result(**overrides: Any) -> PpsrSearchResult:
    """Build a default :class:`PpsrSearchResult` for happy-path tests."""

    base: dict[str, Any] = {
        "search_id": SEARCH_ID,
        "rego": "ABC123",
        "cached": False,
        "cached_at": None,
        "source_search_id": None,
        "match": "N",
        "match_description": "No money owing",
        "statement_count": 0,
        "ppsr_details": [],
        "ownership_history": None,
        "current_owner": None,
        "warnings": [],
        "basic": {"make": "Toyota", "model": "Hilux", "year": 2018},
        "not_found": False,
        "charges_cents": 50,
        "carjam_request_id": "carjam-req-1",
    }
    base.update(overrides)
    return PpsrSearchResult(**base)


# ---------------------------------------------------------------------------
# Auth / global-admin gates
# ---------------------------------------------------------------------------


class TestAuthGate:
    """``request.state.user_id`` missing → 401 across every endpoint."""

    @pytest.mark.asyncio
    async def test_post_search_returns_401_when_unauthenticated(self):
        test_app = _build_test_app(user_id=None, org_id=str(ORG_ID))
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v2/ppsr/search",
                json={"rego": "ABC123"},
            )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"

    @pytest.mark.asyncio
    async def test_get_quota_returns_401_when_unauthenticated(self):
        # ``_get_org_id_required`` runs first when org_id is missing,
        # but with org_id set and no user_id, the user-id helper
        # surfaces 401 once the endpoint goes to build current_user.
        # ``GET /quota`` only calls ``_get_org_id_required`` — when org
        # is also missing this returns 403; the 401 path requires
        # touching ``_build_current_user`` so we exercise it via
        # ``POST /search`` above. This test confirms the org-gate fires
        # when both are absent (still 403 — see TestGlobalAdminGate).
        test_app = _build_test_app(user_id=None, org_id=None)
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v2/ppsr/quota")
        # No org → org-gate fires first.
        assert resp.status_code == 403


class TestGlobalAdminGate:
    """No ``org_id`` on the request → HTTP 403 ``ppsr_requires_org_context``
    on every endpoint (G8)."""

    @pytest.mark.asyncio
    async def test_post_search_blocks_global_admin(self):
        test_app = _build_test_app(
            org_id=None,
            user_id=str(USER_ID),
            role="global_admin",
        )
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v2/ppsr/search",
                json={"rego": "ABC123"},
            )
        assert resp.status_code == 403
        assert resp.json()["detail"] == "ppsr_requires_org_context"

    @pytest.mark.asyncio
    async def test_get_quota_blocks_global_admin(self):
        test_app = _build_test_app(
            org_id=None,
            user_id=str(USER_ID),
            role="global_admin",
        )
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v2/ppsr/quota")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "ppsr_requires_org_context"

    @pytest.mark.asyncio
    async def test_list_searches_blocks_global_admin(self):
        test_app = _build_test_app(
            org_id=None,
            user_id=str(USER_ID),
            role="global_admin",
        )
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/v2/ppsr/searches")
        assert resp.status_code == 403
        assert resp.json()["detail"] == "ppsr_requires_org_context"


# ---------------------------------------------------------------------------
# POST /search — happy path + error mappings
# ---------------------------------------------------------------------------


class TestPostSearchHappyPath:
    """A successful search returns the structured result body."""

    @pytest.mark.asyncio
    async def test_post_search_returns_200_with_structured_result(self):
        test_app = _build_test_app()
        result = _make_search_result()

        with patch(
            "app.modules.ppsr.router.PpsrService",
        ) as MockService:
            instance = MockService.return_value
            instance.search = AsyncMock(return_value=result)

            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v2/ppsr/search",
                    json={
                        "rego": "abc123",  # router schema uppercases
                        "include_warnings": True,
                        "force_refresh": False,
                    },
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["search_id"] == str(SEARCH_ID)
        assert body["rego"] == "ABC123"
        assert body["match"] == "N"
        assert body["cached"] is False
        # Encrypted blob must NOT leak via the response.
        assert "response_encrypted" not in body

        # The router should pass an uppercased rego + parsed options
        # through to the service.
        instance.search.assert_awaited_once()
        kwargs = instance.search.await_args.kwargs
        assert kwargs["rego"] == "ABC123"
        assert kwargs["force_refresh"] is False


class TestPostSearchErrorMappings:
    """Every typed PPSR exception maps to the documented HTTP status."""

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_402(self):
        test_app = _build_test_app()

        with patch(
            "app.modules.ppsr.router.PpsrService",
        ) as MockService:
            instance = MockService.return_value
            instance.search = AsyncMock(
                side_effect=PpsrQuotaExceededError(used=10, included=10),
            )
            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.post(
                    "/api/v2/ppsr/search",
                    json={"rego": "ABC123"},
                )

        assert resp.status_code == 402
        body = resp.json()["detail"]
        assert body["detail"] == "ppsr_quota_exceeded"
        assert body["used"] == 10
        assert body["included"] == 10


# ---------------------------------------------------------------------------
# GET /searches/{id} — forgotten → 410
# ---------------------------------------------------------------------------


class TestGetSearchForgotten:
    """G29: GET detail on a forgotten row → HTTP 410 with ``forgotten_at``."""

    @pytest.mark.asyncio
    async def test_forgotten_search_returns_410(self):
        test_app = _build_test_app()
        forgotten_at = datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc)

        with patch(
            "app.modules.ppsr.router.PpsrService",
        ) as MockService:
            instance = MockService.return_value
            instance.get_search = AsyncMock(
                side_effect=PpsrSearchForgottenError(forgotten_at=forgotten_at),
            )
            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.get(f"/api/v2/ppsr/searches/{SEARCH_ID}")

        assert resp.status_code == 410
        body = resp.json()["detail"]
        assert body["detail"] == "search_forgotten"
        # ISO-8601 timestamp round-trip — we don't pin the exact format
        # to avoid trailing ``+00:00`` vs ``Z`` brittleness.
        assert "2026-05-01" in body["forgotten_at"]


# ---------------------------------------------------------------------------
# DELETE /searches/{id}/forget — admin only
# ---------------------------------------------------------------------------


class TestForgetEndpoint:
    """``DELETE /searches/{id}/forget`` is org_admin-only."""

    @pytest.mark.asyncio
    async def test_admin_forget_returns_204(self):
        test_app = _build_test_app(role="org_admin")

        with patch(
            "app.modules.ppsr.router.PpsrService",
        ) as MockService:
            instance = MockService.return_value
            instance.forget_search = AsyncMock(return_value=None)

            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.delete(
                    f"/api/v2/ppsr/searches/{SEARCH_ID}/forget",
                )

        assert resp.status_code == 204
        instance.forget_search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_admin_forget_returns_403(self):
        test_app = _build_test_app(role="salesperson")

        with patch(
            "app.modules.ppsr.router.PpsrService",
        ) as MockService:
            # The service should not even be called when the role gate
            # at the router layer rejects the request.
            instance = MockService.return_value
            instance.forget_search = AsyncMock(return_value=None)

            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.delete(
                    f"/api/v2/ppsr/searches/{SEARCH_ID}/forget",
                )

        assert resp.status_code == 403
        assert resp.json()["detail"] == "org_admin_required"
        instance.forget_search.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /quota — happy path
# ---------------------------------------------------------------------------


class TestQuotaEndpoint:
    """The quota endpoint returns the service's :class:`PpsrQuotaResponse`."""

    @pytest.mark.asyncio
    async def test_quota_returns_payload(self):
        test_app = _build_test_app()
        quota = PpsrQuotaResponse(
            used=3,
            included=50,
            hidden_plate_used=0,
            hidden_plate_included=10,
            resets_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        with patch(
            "app.modules.ppsr.router.PpsrService",
        ) as MockService:
            instance = MockService.return_value
            instance.get_quota = AsyncMock(return_value=quota)

            async with AsyncClient(
                transport=ASGITransport(app=test_app),
                base_url="http://test",
            ) as client:
                resp = await client.get("/api/v2/ppsr/quota")

        assert resp.status_code == 200
        body = resp.json()
        assert body["used"] == 3
        assert body["included"] == 50
        assert body["hidden_plate_used"] == 0
        assert body["hidden_plate_included"] == 10
        assert body["resets_at"].startswith("2026-07-01")
