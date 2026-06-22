"""Router scope-enforcement integration tests for the admin force clock-out.

Covers task **6.2** from ``.kiro/specs/auto-clock-out/tasks.md``:

    **Property 15: Force-close scope enforced** — a branch-scoped user
    (``branch_admin`` / ``location_manager``) targeting a staff member in
    another branch is rejected (403 ``forbidden_scope``) and the Open_Entry is
    left unchanged; an org-level admin may close any entry in the org.

    **Validates: Requirements 6.4, 6.5, 9.7**

These tests exercise the ``admin_clock_out`` handler behind
``POST /api/v2/time-clock/admin-clock-out/{entry_id}`` (the scope gate
``_require_force_close_scope`` wired in by task 6.1).

Following the established convention in ``tests/test_staff_stats_router.py``,
the handler is called **directly** with a fake ``Request`` (a
``SimpleNamespace`` on ``request.state``) and an ``AsyncMock`` DB, rather than
spinning up the full FastAPI + middleware + Postgres stack. The module gate
(``ModuleService.is_enabled``) and the service mutation
(``clock_service.admin_force_clock_out``) are patched so the tests isolate the
authorisation-scope logic. Only the ``db.get`` (entry/org-ownership check) and
the ``StaffLocationAssignment`` lookup (branch scope) are configured on the
``AsyncMock`` DB.

The central "entry left unchanged" assertion is that the service mutation
``admin_force_clock_out`` is **never awaited** on a rejected request — the
scope gate runs BEFORE the service touches the row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.time_clock.router import admin_clock_out
from app.modules.time_clock.schemas import (
    AdminClockOutRequest,
    TimeClockEntryResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    org_id: uuid.UUID,
    role: str,
    user_id: uuid.UUID | None = None,
    branch_ids: list | None = None,
) -> MagicMock:
    """Build a minimal ``Request``-like object with the ``state`` fields the
    handler reads: ``org_id``, ``role``, ``user_id``, ``branch_ids``,
    ``client_ip``.
    """
    request = MagicMock()
    request.state = SimpleNamespace(
        org_id=org_id,
        role=role,
        user_id=user_id or uuid.uuid4(),
        branch_ids=branch_ids,
        client_ip="203.0.113.7",
    )
    return request


def _make_open_entry(*, entry_id: uuid.UUID, org_id: uuid.UUID, staff_id: uuid.UUID):
    """Minimal ``TimeClockEntry``-shaped stub for the ``db.get`` org-ownership
    check. The handler reads ``.org_id`` (404 gate) and ``.staff_id`` (scope
    gate); the row is **Open** (``clock_out_at is None``).
    """
    return SimpleNamespace(
        id=entry_id,
        org_id=org_id,
        staff_id=staff_id,
        clock_out_at=None,
    )


def _make_closed_entry(
    *, entry_id: uuid.UUID, org_id: uuid.UUID, staff_id: uuid.UUID,
):
    """A fully-populated closed entry the patched ``admin_force_clock_out``
    returns on the success path so the handler's response serialisation maps
    cleanly onto a ``TimeClockEntryResponse``.
    """
    now = datetime(2026, 5, 26, 17, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=entry_id,
        org_id=org_id,
        staff_id=staff_id,
        staff_name=None,
        clock_in_at=datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc),
        clock_out_at=now,
        source="admin_clock_out",
        clock_in_photo_url=None,
        clock_out_photo_url=None,
        clock_in_lat=None,
        clock_in_lng=None,
        clock_out_lat=None,
        clock_out_lng=None,
        scheduled_entry_id=None,
        break_minutes=0,
        notes=None,
        created_by=None,
        worked_minutes=480,
        flags={},
        created_at=datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc),
    )


def _scope_db(*, entry, in_scope: bool | None) -> AsyncMock:
    """An ``AsyncMock`` DB:

    - ``db.get(...)`` resolves the entry/org-ownership check to ``entry``.
    - ``db.execute(...).scalar_one_or_none()`` returns a truthy id when
      ``in_scope`` is ``True`` (the ``StaffLocationAssignment`` branch-scope
      lookup matched) else ``None``. Pass ``in_scope=None`` when the lookup is
      not expected to run (org_admin short-circuits).
    """
    db = AsyncMock()
    db.get = AsyncMock(return_value=entry)
    result = MagicMock()
    result.scalar_one_or_none.return_value = (
        uuid.uuid4() if in_scope else None
    )
    db.execute = AsyncMock(return_value=result)
    return db


def _payload() -> AdminClockOutRequest:
    return AdminClockOutRequest(reason_note="forgot to tap out at end of shift")


# ---------------------------------------------------------------------------
# Org-level admin — may force-close ANY entry in the org (R6.4)
# ---------------------------------------------------------------------------


class TestAdminClockOutOrgAdminScope:
    """**Validates: Requirements 6.4, 9.7** — an ``org_admin`` may force-close
    any Open_Entry in the organisation regardless of branch.
    """

    @pytest.mark.asyncio
    async def test_org_admin_closes_any_entry_returns_200(self):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entry_id = uuid.uuid4()
        request = _make_request(org_id=org_id, role="org_admin")
        open_entry = _make_open_entry(
            entry_id=entry_id, org_id=org_id, staff_id=staff_id,
        )
        # in_scope=None: the branch-scope lookup must not gate an org admin.
        db = _scope_db(entry=open_entry, in_scope=None)
        closed = _make_closed_entry(
            entry_id=entry_id, org_id=org_id, staff_id=staff_id,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.time_clock.router.clock_service.admin_force_clock_out",
            new_callable=AsyncMock,
            return_value=closed,
        ) as mock_force:
            resp = await admin_clock_out(
                entry_id=entry_id,
                payload=_payload(),
                request=request,
                db=db,
            )

        assert isinstance(resp, TimeClockEntryResponse)
        assert resp.id == entry_id
        assert resp.clock_out_at is not None
        # The org admin's close is handed to the service exactly once.
        mock_force.assert_awaited_once()


# ---------------------------------------------------------------------------
# Branch-scoped user — only entries for staff in their assigned branches
# ---------------------------------------------------------------------------


class TestAdminClockOutBranchScope:
    """**Validates: Requirements 6.4, 6.5, 9.7** — a branch-scoped user may
    force-close only entries for staff in their assigned branches; an
    out-of-scope target is rejected and the entry is left unchanged.
    """

    @pytest.mark.parametrize("role", ["branch_admin", "location_manager"])
    @pytest.mark.asyncio
    async def test_out_of_scope_target_rejected_and_entry_unchanged(self, role):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entry_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role=role, branch_ids=[str(branch_id)],
        )
        open_entry = _make_open_entry(
            entry_id=entry_id, org_id=org_id, staff_id=staff_id,
        )
        # scalar_one_or_none() -> None: the target's location assignments do
        # NOT intersect the requester's branch scope (staff in another branch).
        db = _scope_db(entry=open_entry, in_scope=False)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.time_clock.router.clock_service.admin_force_clock_out",
            new_callable=AsyncMock,
        ) as mock_force:
            with pytest.raises(HTTPException) as excinfo:
                await admin_clock_out(
                    entry_id=entry_id,
                    payload=_payload(),
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == {"detail": "forbidden_scope"}
        # Entry left UNCHANGED — the scope gate runs before the service
        # mutates the row, so the close is never attempted.
        mock_force.assert_not_awaited()

    @pytest.mark.parametrize("role", ["branch_admin", "location_manager"])
    @pytest.mark.asyncio
    async def test_in_scope_target_closes_returns_200(self, role):
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entry_id = uuid.uuid4()
        branch_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id, role=role, branch_ids=[str(branch_id)],
        )
        open_entry = _make_open_entry(
            entry_id=entry_id, org_id=org_id, staff_id=staff_id,
        )
        # scalar_one_or_none() -> match: the target is in the requester's scope.
        db = _scope_db(entry=open_entry, in_scope=True)
        closed = _make_closed_entry(
            entry_id=entry_id, org_id=org_id, staff_id=staff_id,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.time_clock.router.clock_service.admin_force_clock_out",
            new_callable=AsyncMock,
            return_value=closed,
        ) as mock_force:
            resp = await admin_clock_out(
                entry_id=entry_id,
                payload=_payload(),
                request=request,
                db=db,
            )

        assert isinstance(resp, TimeClockEntryResponse)
        assert resp.id == entry_id
        assert resp.clock_out_at is not None
        mock_force.assert_awaited_once()

    @pytest.mark.parametrize("role", ["branch_admin", "location_manager"])
    @pytest.mark.asyncio
    async def test_no_branch_ids_rejected_and_entry_unchanged(self, role):
        """A branch-scoped user with an empty branch scope cannot intersect any
        location and is rejected without modifying the entry.
        """
        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        entry_id = uuid.uuid4()
        request = _make_request(org_id=org_id, role=role, branch_ids=[])
        open_entry = _make_open_entry(
            entry_id=entry_id, org_id=org_id, staff_id=staff_id,
        )
        db = _scope_db(entry=open_entry, in_scope=False)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.time_clock.router.clock_service.admin_force_clock_out",
            new_callable=AsyncMock,
        ) as mock_force:
            with pytest.raises(HTTPException) as excinfo:
                await admin_clock_out(
                    entry_id=entry_id,
                    payload=_payload(),
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == {"detail": "forbidden_scope"}
        mock_force.assert_not_awaited()
