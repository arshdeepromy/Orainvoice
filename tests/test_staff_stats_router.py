"""Router auth/scope integration tests for ``GET /api/v2/staff/{id}/stats``.

Covers task **5.4** from ``.kiro/specs/staff-redesign/tasks.md``.

These tests exercise the ``get_staff_stats`` handler implemented in tasks
5.1/5.2, focusing on the module gate and the RBAC / self-scope
access-control matrix (R13.1–R13.6).

Following the established convention in ``tests/test_staff_router.py``, the
handler is called **directly** with a fake ``Request`` (a ``SimpleNamespace``
on ``request.state``) and an ``AsyncMock`` DB, rather than spinning up the
full FastAPI + middleware + Postgres stack. ``StaffService.get_staff`` and
``StaffService.get_staff_month_stats`` are patched at the class level so the
tests isolate the access-control logic from the DB; only the
``StaffLocationAssignment`` lookup (branch_admin scope) is configured on the
``AsyncMock`` ``db.execute``.

The one exception is the **bad ``period`` → 422** case: a 422 from the
``Query(pattern="^this_month$")`` constraint is enforced by FastAPI's
request-validation layer, which is NOT exercised when calling the coroutine
directly. That case therefore mounts the real router on a tiny FastAPI app
and drives it through a ``TestClient`` so the validation layer runs (mirroring
``tests/integration/test_scheduling_v2_routes.py``).

**Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6.**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.staff.router import get_staff_stats
from app.modules.staff.schemas import StaffMonthStatsResponse
from app.modules.staff.service import StaffMonthStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    org_id: uuid.UUID | None,
    role: str | None = None,
    user_id: uuid.UUID | None = None,
    branch_ids: list | None = None,
) -> MagicMock:
    """Build a minimal ``Request``-like object with the ``state`` fields the
    stats handler reads: ``org_id``, ``role``, ``user_id``, ``branch_ids``.
    """
    request = MagicMock()
    request.state = SimpleNamespace(
        org_id=org_id,
        role=role,
        user_id=user_id,
        branch_ids=branch_ids,
    )
    return request


def _make_staff(*, staff_id: uuid.UUID, org_id: uuid.UUID, user_id=None):
    """Minimal ``StaffMember``-shaped stub. The handler reads ``.user_id``
    (self-scope check); ``.id`` / ``.org_id`` are carried for realism.
    """
    return SimpleNamespace(id=staff_id, org_id=org_id, user_id=user_id)


def _make_month_stats() -> StaffMonthStats:
    """A fully-populated ``StaffMonthStats`` so the success path maps cleanly
    onto a ``StaffMonthStatsResponse``.
    """
    return StaffMonthStats(
        hours_logged=Decimal("12.5"),
        hours_logged_has_data=True,
        jobs_completed=3,
        jobs_completed_has_data=True,
        billable_ratio=80,
        billable_ratio_has_data=True,
        on_time_rate=90,
        on_time_rate_has_data=True,
        last_sign_in=datetime(2026, 5, 20, 8, 30, tzinfo=timezone.utc),
        user_role="staff_member",
    )


def _branch_scope_db(*, in_scope: bool) -> AsyncMock:
    """An ``AsyncMock`` DB whose ``execute(...).scalar_one_or_none()`` returns
    a truthy id when ``in_scope`` else ``None`` — the exact shape the
    branch_admin ``StaffLocationAssignment`` lookup consumes.
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid.uuid4() if in_scope else None
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# R13.1 — Module gate
# ---------------------------------------------------------------------------


class TestStatsModuleGate:
    """**Validates: Requirement 13.1** — the stats endpoint is module-gated."""

    @pytest.mark.asyncio
    async def test_module_disabled_returns_404_not_enabled(self):
        """When ``staff_management`` is disabled the module gate fires first
        and raises 404 with the spec-mandated detail body — before any staff
        lookup or stats computation.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id=org_id, role="org_admin")
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock()
            mock_service.get_staff_month_stats = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_staff_stats(
                    staff_id=staff_id,
                    request=request,
                    period="this_month",
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }
        # Module gate short-circuits before the staff lookup / stats query.
        mock_service.get_staff.assert_not_awaited()
        mock_service.get_staff_month_stats.assert_not_awaited()


# ---------------------------------------------------------------------------
# R13.2 — org_admin / salesperson: any in-org staff
# ---------------------------------------------------------------------------


class TestStatsOrgWideRoles:
    """**Validates: Requirement 13.2** — ``org_admin`` / ``salesperson`` may
    read any staff member in their org.
    """

    @pytest.mark.parametrize("role", ["org_admin", "salesperson"])
    @pytest.mark.asyncio
    async def test_org_wide_role_returns_200_for_any_in_org_staff(self, role):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id=org_id, role=role)
        db = AsyncMock()
        staff = _make_staff(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock(
                return_value=_make_month_stats()
            )

            resp = await get_staff_stats(
                staff_id=staff_id,
                request=request,
                period="this_month",
                db=db,
            )

        assert isinstance(resp, StaffMonthStatsResponse)
        assert resp.staff_id == staff_id
        assert resp.period == "this_month"
        assert resp.hours_logged.value == Decimal("12.5")
        assert resp.hours_logged.has_data is True
        assert resp.jobs_completed.value == Decimal(3)
        # No branch-scope DB lookup is performed for org-wide roles.
        mock_service.get_staff_month_stats.assert_awaited_once()


# ---------------------------------------------------------------------------
# R13.3 — branch_admin: in-scope 200, out-of-scope 403
# ---------------------------------------------------------------------------


class TestStatsBranchAdminScope:
    """**Validates: Requirement 13.3** — ``branch_admin`` may read only staff
    whose location assignments intersect their branch scope.
    """

    @pytest.mark.asyncio
    async def test_in_scope_staff_returns_200(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role="branch_admin", branch_ids=[str(branch_id)],
        )
        # scalar_one_or_none() returns a match → in scope.
        db = _branch_scope_db(in_scope=True)
        staff = _make_staff(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock(
                return_value=_make_month_stats()
            )

            resp = await get_staff_stats(
                staff_id=staff_id,
                request=request,
                period="this_month",
                db=db,
            )

        assert isinstance(resp, StaffMonthStatsResponse)
        assert resp.staff_id == staff_id
        mock_service.get_staff_month_stats.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_out_of_scope_staff_returns_403(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role="branch_admin", branch_ids=[str(branch_id)],
        )
        # scalar_one_or_none() returns None → out of scope.
        db = _branch_scope_db(in_scope=False)
        staff = _make_staff(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock(
                return_value=_make_month_stats()
            )

            with pytest.raises(HTTPException) as excinfo:
                await get_staff_stats(
                    staff_id=staff_id,
                    request=request,
                    period="this_month",
                    db=db,
                )

        assert excinfo.value.status_code == 403
        # Denied before any stats are computed.
        mock_service.get_staff_month_stats.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_branch_admin_with_no_branch_ids_returns_403(self):
        """A ``branch_admin`` with an empty branch scope cannot intersect any
        location and is denied without even running the location lookup.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role="branch_admin", branch_ids=[],
        )
        db = AsyncMock()
        staff = _make_staff(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_staff_stats(
                    staff_id=staff_id,
                    request=request,
                    period="this_month",
                    db=db,
                )

        assert excinfo.value.status_code == 403
        mock_service.get_staff_month_stats.assert_not_awaited()


# ---------------------------------------------------------------------------
# R13.4 / R13.5 — staff_member: own record 200, other 403
# ---------------------------------------------------------------------------


class TestStatsStaffMemberSelfScope:
    """**Validates: Requirements 13.4, 13.5** — a ``staff_member`` may read
    only their own staff record.
    """

    @pytest.mark.asyncio
    async def test_own_record_returns_200(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role="staff_member", user_id=user_id,
        )
        db = AsyncMock()
        # The staff record is linked to the requesting user → self scope.
        staff = _make_staff(staff_id=staff_id, org_id=org_id, user_id=user_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock(
                return_value=_make_month_stats()
            )

            resp = await get_staff_stats(
                staff_id=staff_id,
                request=request,
                period="this_month",
                db=db,
            )

        assert isinstance(resp, StaffMonthStatsResponse)
        assert resp.staff_id == staff_id
        mock_service.get_staff_month_stats.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_other_staff_record_returns_403(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role="staff_member", user_id=uuid.uuid4(),
        )
        db = AsyncMock()
        # The staff record belongs to a DIFFERENT user → denied.
        staff = _make_staff(
            staff_id=staff_id, org_id=org_id, user_id=uuid.uuid4(),
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_staff_stats(
                    staff_id=staff_id,
                    request=request,
                    period="this_month",
                    db=db,
                )

        assert excinfo.value.status_code == 403
        mock_service.get_staff_month_stats.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_staff_member_record_with_no_linked_user_returns_403(self):
        """An unlinked staff record (``user_id is None``) can never match the
        requesting ``staff_member`` and is denied.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role="staff_member", user_id=uuid.uuid4(),
        )
        db = AsyncMock()
        staff = _make_staff(staff_id=staff_id, org_id=org_id, user_id=None)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_staff_stats(
                    staff_id=staff_id,
                    request=request,
                    period="this_month",
                    db=db,
                )

        assert excinfo.value.status_code == 403
        mock_service.get_staff_month_stats.assert_not_awaited()


# ---------------------------------------------------------------------------
# R13.6 — cross-org target: 404
# ---------------------------------------------------------------------------


class TestStatsCrossOrgTarget:
    """**Validates: Requirement 13.6** — a target outside the requester's org
    surfaces as 404 (``get_staff`` filters by ``org_id`` and returns None).
    """

    @pytest.mark.asyncio
    async def test_cross_org_or_missing_target_returns_404(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id=org_id, role="org_admin")
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            # get_staff filters by org_id; a cross-org id resolves to None.
            mock_service.get_staff = AsyncMock(return_value=None)
            mock_service.get_staff_month_stats = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_staff_stats(
                    staff_id=staff_id,
                    request=request,
                    period="this_month",
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Staff member not found"
        mock_service.get_staff_month_stats.assert_not_awaited()


# ---------------------------------------------------------------------------
# Bad ``period`` → 422 (request-validation layer)
# ---------------------------------------------------------------------------


class TestStatsBadPeriodValidation:
    """A bad ``period`` value MUST be rejected with HTTP 422.

    The 422 originates from the ``Query(pattern="^this_month$")`` constraint,
    which is enforced by FastAPI's request-validation layer BEFORE the handler
    body runs. Calling the coroutine directly (as the other tests do) bypasses
    that layer, so this case mounts the real router on a small FastAPI app and
    drives it through a ``TestClient`` — the same approach as
    ``tests/integration/test_scheduling_v2_routes.py``.

    Because validation fails before the handler body executes, neither the
    module gate nor ``get_db_session`` is reached; we still override the DB
    dependency so the app builds cleanly.
    """

    def _build_client(self):
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient

        from app.core.database import get_db_session
        from app.modules.staff.router import router as staff_router

        app = FastAPI()

        async def override_db_session():
            yield AsyncMock()

        @app.middleware("http")
        async def populate_state(request: Request, call_next):
            request.state.org_id = str(uuid.uuid4())
            request.state.user_id = str(uuid.uuid4())
            request.state.role = "org_admin"
            request.state.branch_ids = []
            return await call_next(request)

        app.dependency_overrides[get_db_session] = override_db_session
        app.include_router(staff_router, prefix="/api/v2/staff")
        return TestClient(app)

    def test_bad_period_value_returns_422(self):
        client = self._build_client()
        staff_id = uuid.uuid4()
        resp = client.get(
            f"/api/v2/staff/{staff_id}/stats", params={"period": "last_month"}
        )
        assert resp.status_code == 422

    def test_default_period_is_accepted_by_validation(self):
        """Sanity check: the valid ``this_month`` value (the default) passes
        the validation layer (the request proceeds past it into the handler).
        With the module gate patched on, the happy path returns 200.
        """
        client = self._build_client()
        staff_id = uuid.uuid4()

        staff = _make_staff(staff_id=staff_id, org_id=uuid.uuid4())
        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff)
            mock_service.get_staff_month_stats = AsyncMock(
                return_value=_make_month_stats()
            )
            resp = client.get(
                f"/api/v2/staff/{staff_id}/stats",
                params={"period": "this_month"},
            )

        # Valid period clears validation; not a 422.
        assert resp.status_code != 422
