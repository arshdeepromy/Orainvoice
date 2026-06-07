"""Router tests for ``GET /api/v2/staff/kpis``.

Covers task **6.2** from ``.kiro/specs/staff-redesign/tasks.md``.

These tests exercise the ``get_list_kpis`` router handler implemented in task
6.1, focusing on:

* the ``staff_management`` module gate (disabled → 404 ``not_enabled``);
* the structured response carrying all four KPI fields (``total_staff``,
  ``employee_count``, ``with_login_count``, ``avg_hourly_rate``);
* the ``avg_hourly_rate`` null pass-through when no active staff have a rate.

Following the established convention in ``tests/test_staff_router.py`` and
``tests/test_staff_stats_router.py``, the handler is called **directly** with a
fake ``Request`` (a ``SimpleNamespace`` on ``request.state``) and an
``AsyncMock`` DB, rather than spinning up the full FastAPI + middleware +
Postgres stack. ``ModuleService.is_enabled`` is patched for the module gate
and ``StaffService`` is patched so ``get_list_kpis`` returns a
``StaffListKpis`` dataclass instance.

Note: the router handler ``get_list_kpis`` shares its name with the
``StaffService.get_list_kpis`` method, but they are different objects. The
import below pulls the **router coroutine**.

**Validates: Requirement 1.6.**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.staff.router import get_list_kpis
from app.modules.staff.schemas import StaffListKpisResponse
from app.modules.staff.service import StaffListKpis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(*, org_id: uuid.UUID | None) -> MagicMock:
    """Build a minimal ``Request``-like object exposing ``state.org_id`` —
    the only field the kpis handler reads (via ``_get_org_id``).
    """
    request = MagicMock()
    request.state = SimpleNamespace(org_id=org_id)
    return request


def _make_kpis(
    *,
    total_staff: int = 10,
    employee_count: int = 7,
    with_login_count: int = 4,
    avg_hourly_rate: Decimal | None = Decimal("32.50"),
) -> StaffListKpis:
    """A ``StaffListKpis`` service dataclass with sensible defaults."""
    return StaffListKpis(
        total_staff=total_staff,
        employee_count=employee_count,
        with_login_count=with_login_count,
        avg_hourly_rate=avg_hourly_rate,
    )


# ---------------------------------------------------------------------------
# R1.6 — module gate
# ---------------------------------------------------------------------------


class TestKpisModuleGate:
    """**Validates: Requirement 1.6** — the kpis endpoint is module-gated."""

    @pytest.mark.asyncio
    async def test_module_disabled_returns_404_not_enabled(self):
        """When ``staff_management`` is disabled the module gate fires first
        and raises 404 with the spec-mandated detail body — before any KPI
        aggregation runs.
        """
        org_id = uuid.uuid4()
        request = _make_request(org_id=org_id)
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            from fastapi import HTTPException

            mock_service = mock_service_cls.return_value
            mock_service.get_list_kpis = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_list_kpis(request=request, db=db)

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }
        # Module gate short-circuits before the KPI query.
        mock_service.get_list_kpis.assert_not_awaited()


# ---------------------------------------------------------------------------
# R1.6 — structured response with all four fields
# ---------------------------------------------------------------------------


class TestKpisResponseShape:
    """**Validates: Requirement 1.6** — the response is a structured object
    carrying all four KPI fields, mapped from the service dataclass.
    """

    @pytest.mark.asyncio
    async def test_happy_path_returns_all_four_fields(self):
        org_id = uuid.uuid4()
        request = _make_request(org_id=org_id)
        db = AsyncMock()
        kpis = _make_kpis(
            total_staff=12,
            employee_count=8,
            with_login_count=5,
            avg_hourly_rate=Decimal("28.75"),
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_list_kpis = AsyncMock(return_value=kpis)

            resp = await get_list_kpis(request=request, db=db)

        assert isinstance(resp, StaffListKpisResponse)
        assert resp.total_staff == 12
        assert resp.employee_count == 8
        assert resp.with_login_count == 5
        assert resp.avg_hourly_rate == Decimal("28.75")
        # The KPI computation is org-scoped via the request's org_id.
        mock_service.get_list_kpis.assert_awaited_once_with(org_id)


# ---------------------------------------------------------------------------
# R1.6 / R1.7 — avg_hourly_rate null pass-through
# ---------------------------------------------------------------------------


class TestKpisNullAvgRate:
    """**Validates: Requirement 1.6** — when no active staff have a rate the
    service returns ``avg_hourly_rate=None`` and the response preserves the
    ``None`` (so the frontend renders "—" rather than a misleading 0, R1.7).
    """

    @pytest.mark.asyncio
    async def test_avg_hourly_rate_none_is_preserved(self):
        org_id = uuid.uuid4()
        request = _make_request(org_id=org_id)
        db = AsyncMock()
        kpis = _make_kpis(avg_hourly_rate=None)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_list_kpis = AsyncMock(return_value=kpis)

            resp = await get_list_kpis(request=request, db=db)

        assert isinstance(resp, StaffListKpisResponse)
        assert resp.avg_hourly_rate is None
        # The other three counts still flow through intact.
        assert resp.total_staff == kpis.total_staff
        assert resp.employee_count == kpis.employee_count
        assert resp.with_login_count == kpis.with_login_count
