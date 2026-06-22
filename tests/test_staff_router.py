"""Unit tests for the staff router module-gating helper.

Covers task C1 from `.kiro/specs/staff-management-p1`:

The ``_require_staff_management_module`` helper is the finer-grained
gate (404) layered on top of the existing path-prefix ``staff`` module
middleware (403). When ``staff_management`` is disabled for the
requesting org, it raises ``HTTPException(404)`` with the expected
``{"detail": "not_enabled", "module": "staff_management"}`` body. When
enabled, it returns ``None`` so the wrapped endpoint can proceed.

The tests below exercise the helper directly with a fake
``Request`` and ``ModuleService.is_enabled`` patched to return
``False`` / ``True``. Going through HTTP would require spinning up the
full FastAPI app + middleware stack + DB session, which adds noise
without exercising any new behaviour.

**Validates: Requirement R11.5** (Phase 1 task C1).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.staff.router import _require_staff_management_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(org_id: uuid.UUID | None) -> MagicMock:
    """Build a minimal ``Request``-like object with ``state.org_id`` set.

    The helper only reads ``request.state.org_id``; nothing else from the
    Request interface is exercised.
    """
    request = MagicMock()
    request.state = SimpleNamespace(org_id=org_id)
    return request


# ---------------------------------------------------------------------------
# Helper: module gating behaviour
# ---------------------------------------------------------------------------


class TestRequireStaffManagementModuleGate:
    """``_require_staff_management_module`` raises 404 when disabled,
    returns None when enabled.
    """

    @pytest.mark.asyncio
    async def test_module_gate_disabled_raises_404_not_enabled(self):
        """When ``ModuleService.is_enabled`` returns False the helper
        MUST raise ``HTTPException`` with status 404 and the
        spec-mandated detail body ``{"detail": "not_enabled",
        "module": "staff_management"}``.
        """
        org_id = uuid.uuid4()
        request = _make_request(org_id)
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_is_enabled:
            with pytest.raises(HTTPException) as excinfo:
                await _require_staff_management_module(request, db)

        # 404, not 403 — deliberate per design §2 (R11.5):
        # the path-prefix middleware already returns 403 for the broader
        # ``staff`` module; the new ``staff_management`` sub-gate uses
        # 404 to hide the new sub-endpoints without re-asserting denial.
        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }

        # The check was made against the right slug + the request's org_id.
        mock_is_enabled.assert_awaited_once()
        call_args = mock_is_enabled.await_args.args
        # ModuleService.is_enabled(org_id, slug) — slug is the second arg.
        assert call_args[1] == "staff_management"
        assert call_args[0] == str(org_id)

    @pytest.mark.asyncio
    async def test_module_gate_enabled_returns_none(self):
        """When ``ModuleService.is_enabled`` returns True the helper
        MUST return ``None`` (i.e., no exception) so the wrapped
        endpoint can proceed.
        """
        org_id = uuid.uuid4()
        request = _make_request(org_id)
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await _require_staff_management_module(request, db)

        assert result is None

    @pytest.mark.asyncio
    async def test_module_gate_no_org_context_raises_401(self):
        """Without ``request.state.org_id`` the helper MUST raise 401
        (matches the existing ``_get_org_id`` contract — the gate must
        not silently pass when no tenant context is set).
        """
        request = _make_request(None)
        db = AsyncMock()

        # We don't even need to patch is_enabled — the org-id check
        # short-circuits first.
        with pytest.raises(HTTPException) as excinfo:
            await _require_staff_management_module(request, db)

        assert excinfo.value.status_code == 401


# ---------------------------------------------------------------------------
# Importability — the helper is reused by C2-C11
# ---------------------------------------------------------------------------


class TestHelperImportable:
    """Subsequent C2–C11 tasks import the helper from the router module.

    Locking the public name in a test makes it explicit that this
    function is part of the staff router's module-internal API.
    """

    def test_helper_is_importable_from_router(self):
        from app.modules.staff import router as staff_router

        assert hasattr(staff_router, "_require_staff_management_module")
        assert callable(staff_router._require_staff_management_module)


# ---------------------------------------------------------------------------
# Pay rate history endpoint (C2)
# ---------------------------------------------------------------------------


class TestGetPayRateHistoryEndpoint:
    """Tests for ``GET /api/v2/staff/:id/pay-rates`` (Phase 1 task C2).

    Exercises the router glue directly: the helper that gates the
    endpoint, the staff-existence check, and the
    ``{ items, total }`` envelope. The underlying
    ``StaffService.get_pay_rate_history`` query is covered by
    ``tests/unit/test_staff_service_phase1.py`` (B5); these tests
    confirm the router wires it up correctly.

    **Validates: Requirement R3.5**.
    """

    @pytest.mark.asyncio
    async def test_returns_items_and_total(self):
        """Happy path: module enabled + staff exists → service items
        flow through into ``StaffPayRateListResponse(items=..., total=...)``.
        """
        from datetime import date
        from decimal import Decimal

        from app.modules.staff.router import get_pay_rate_history

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id)
        db = AsyncMock()

        rate_id = uuid.uuid4()
        items_dicts = [
            {
                "id": rate_id,
                "effective_from": date(2026, 5, 1),
                "hourly_rate": Decimal("28.50"),
                "overtime_rate": Decimal("42.75"),
                "change_reason": "rate_change",
                "changed_by_email": "owner@acme.co.nz",
            }
        ]

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            # ``get_staff`` returns a truthy stub so the endpoint
            # proceeds to the history fetch.
            mock_service.get_staff = AsyncMock(
                return_value=SimpleNamespace(id=staff_id, org_id=org_id)
            )
            mock_service.get_pay_rate_history = AsyncMock(
                return_value=(items_dicts, 3),
            )

            resp = await get_pay_rate_history(
                staff_id=staff_id,
                request=request,
                offset=0,
                limit=50,
                db=db,
            )

        # Wrapped in the project-overview ``{ items, total }`` envelope.
        assert resp.total == 3
        assert len(resp.items) == 1
        assert resp.items[0].id == rate_id
        assert resp.items[0].hourly_rate == Decimal("28.50")
        assert resp.items[0].changed_by_email == "owner@acme.co.nz"

        # Service was called with the right arguments — paging passes
        # straight through.
        mock_service.get_pay_rate_history.assert_awaited_once_with(
            org_id, staff_id, offset=0, limit=50,
        )

    @pytest.mark.asyncio
    async def test_pagination_params_passed_through(self):
        """``offset`` and ``limit`` from the query string MUST forward
        unmodified to the service (the existing list-endpoint
        convention).
        """
        from app.modules.staff.router import get_pay_rate_history

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id)
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(
                return_value=SimpleNamespace(id=staff_id, org_id=org_id)
            )
            mock_service.get_pay_rate_history = AsyncMock(return_value=([], 0))

            resp = await get_pay_rate_history(
                staff_id=staff_id,
                request=request,
                offset=10,
                limit=25,
                db=db,
            )

        assert resp.items == []
        assert resp.total == 0
        mock_service.get_pay_rate_history.assert_awaited_once_with(
            org_id, staff_id, offset=10, limit=25,
        )

    @pytest.mark.asyncio
    async def test_unknown_staff_returns_404(self):
        """When the staff member doesn't exist (or belongs to another
        org — same observable result thanks to RLS) the endpoint MUST
        return 404 ``"Staff member not found"`` instead of an empty
        history list. Without the existence guard the response would
        be a deceptive 200 ``{items: [], total: 0}`` for any UUID.
        """
        from app.modules.staff.router import get_pay_rate_history

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id)
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)
            mock_service.get_pay_rate_history = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_pay_rate_history(
                    staff_id=staff_id,
                    request=request,
                    offset=0,
                    limit=50,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Staff member not found"
        # The history fetch MUST NOT be attempted once the staff check
        # fails — that would be a wasted round-trip.
        mock_service.get_pay_rate_history.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_module_disabled_returns_404_not_enabled(self):
        """When ``staff_management`` is disabled the module gate fires
        first and returns the spec-mandated detail body — even before
        the staff existence check.
        """
        from app.modules.staff.router import get_pay_rate_history

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request(org_id)
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
            mock_service.get_pay_rate_history = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await get_pay_rate_history(
                    staff_id=staff_id,
                    request=request,
                    offset=0,
                    limit=50,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }
        # Neither staff lookup nor history query runs when the module
        # gate refuses the call.
        mock_service.get_staff.assert_not_awaited()
        mock_service.get_pay_rate_history.assert_not_awaited()


# ---------------------------------------------------------------------------
# Email roster endpoint (C3, R8)
# ---------------------------------------------------------------------------


def _make_request_with_user(
    org_id: uuid.UUID | None, user_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a ``Request``-like object with ``state.org_id`` AND
    ``state.user_id`` set so the email-roster endpoint can write an
    audit row with the acting user.
    """
    request = MagicMock()
    request.state = SimpleNamespace(
        org_id=org_id,
        user_id=user_id,
        client_ip=None,
    )
    return request


def _make_staff_stub(
    *,
    staff_id: uuid.UUID,
    org_id: uuid.UUID,
    email: str | None = "jane@example.co.nz",
    weekly_roster_email_enabled: bool = True,
    first_name: str = "Jane",
    last_name: str | None = "Doe",
):
    """Build a minimal ``StaffMember``-shaped stub for the helper.

    The roster_delivery helper accesses: ``id``, ``email``,
    ``weekly_roster_email_enabled``, ``first_name``, ``last_name``,
    and ``name``. A SimpleNamespace is enough — we never persist it.
    """
    return SimpleNamespace(
        id=staff_id,
        org_id=org_id,
        email=email,
        weekly_roster_email_enabled=weekly_roster_email_enabled,
        first_name=first_name,
        last_name=last_name,
        name=f"{first_name} {last_name or ''}".strip(),
    )


class TestEmailRosterEndpoint:
    """Tests for ``POST /api/v2/staff/:id/email-roster`` (Phase 1 task C3).

    Exercises the router glue directly: the module gate, the
    staff-existence check, the precondition refusals (no email /
    opt-out / no shifts), the happy path, and that the audit row is
    written with the right action + entity ids.

    **Validates: Requirement R8**.
    """

    @pytest.mark.asyncio
    async def test_module_disabled_returns_404_not_enabled(self):
        """When ``staff_management`` is disabled the module gate fires
        first — before the staff lookup or any send work — and returns
        the spec-mandated 404 detail body.
        """
        from datetime import date

        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await email_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }
        # No staff lookup, no send, no audit when module is off.
        mock_service.get_staff.assert_not_awaited()
        mock_send.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_staff_returns_404(self):
        """When the staff member doesn't exist (or belongs to another
        org) the endpoint MUST return 404 ``"Staff member not found"``
        rather than spending work on the precondition checks.
        """
        from datetime import date

        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as excinfo:
                await email_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Staff member not found"
        # The send work + audit row are skipped when the staff is missing.
        mock_send.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_email_refuses_with_422(self):
        """Staff with ``email=None`` MUST surface as HTTP 422 with
        ``reason='no_email'`` per R8.2, and MUST NOT write an audit
        row (the endpoint short-circuits before the audit step).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_EMAIL,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub(
            staff_id=staff_id, org_id=org_id, email=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, reason=REASON_NO_EMAIL,
            ),
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await email_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "ok": False,
            "reason": REASON_NO_EMAIL,
        }
        mock_send.assert_awaited_once()
        # Refusal cases short-circuit before the audit row is written.
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_opt_out_refuses_with_422(self):
        """When ``weekly_roster_email_enabled=False`` the helper returns
        ``opt_out`` and the router maps it to HTTP 422 (R8.2).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_OPT_OUT,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub(
            staff_id=staff_id, org_id=org_id,
            weekly_roster_email_enabled=False,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, reason=REASON_OPT_OUT,
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await email_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "ok": False,
            "reason": REASON_OPT_OUT,
        }
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_shifts_in_week_refuses_with_422(self):
        """Zero schedule entries in the week → HTTP 422 with
        ``reason='no_shifts_in_week'`` (R8.5).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_SHIFTS_IN_WEEK,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, reason=REASON_NO_SHIFTS_IN_WEEK,
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await email_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "ok": False,
            "reason": REASON_NO_SHIFTS_IN_WEEK,
        }
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_happy_path_returns_ok_and_writes_audit(self):
        """Module enabled + staff exists + email + opt-in + shifts →
        the helper returns ok=True with a message_id, the router
        surfaces ``{ok=true, message_id, reason=None}``, AND writes an
        ``audit_log`` row with ``action='roster.emailed'`` (R8.4).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import RosterDeliveryResult
        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=True, message_id="prov-msg-123", reason=None,
            ),
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await email_roster(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # Response shape is the spec-mandated RosterSendResponse.
        assert resp.ok is True
        assert resp.message_id == "prov-msg-123"
        assert resp.reason is None

        # send_roster_email was invoked with the resolved org/staff/week.
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.await_args.kwargs
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["staff"] is staff_stub
        assert call_kwargs["week_start"] == date(2026, 6, 8)

        # Audit row written with the right action + entity + after_value.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "roster.emailed"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        assert audit_kwargs["after_value"]["ok"] is True
        assert audit_kwargs["after_value"]["message_id"] == "prov-msg-123"
        assert audit_kwargs["after_value"]["week_start"] == "2026-06-08"

    @pytest.mark.asyncio
    async def test_send_failure_returns_200_with_reason_and_audits(self):
        """A downstream provider-chain exhaustion surfaces as HTTP 200
        with ``{ok=false, reason='send_failed'}`` (the DLQ already
        captured it for replay) AND writes an audit row so ops can
        trace the attempt.
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_SEND_FAILED,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import email_roster
        from app.modules.staff.schemas import RosterEmailRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = RosterEmailRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_email",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, message_id=None, reason=REASON_SEND_FAILED,
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await email_roster(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # Send-failure is NOT a refusal — it's a 200 with ok=false,
        # not a 422. The DLQ handles replay.
        assert resp.ok is False
        assert resp.message_id is None
        assert resp.reason == REASON_SEND_FAILED

        # Audit row IS written for send failures (so we can trace).
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "roster.emailed"
        assert audit_kwargs["after_value"]["ok"] is False
        assert audit_kwargs["after_value"]["reason"] == REASON_SEND_FAILED


# ---------------------------------------------------------------------------
# Roster delivery helper unit tests (C3, R8)
# ---------------------------------------------------------------------------


class TestSendRosterEmailHelper:
    """Tests for the ``send_roster_email`` orchestrator in
    ``app.modules.staff.roster_delivery``.

    These tests exercise the precondition-refusal logic and the
    successful-render-and-send path with the database + provider
    integration mocked at the boundaries.

    **Validates: Requirement R8**.
    """

    @pytest.mark.asyncio
    async def test_no_email_returns_no_email_reason(self):
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_EMAIL,
            send_roster_email,
        )

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=staff_id, org_id=org_id, email=None,
        )
        db = AsyncMock()

        result = await send_roster_email(
            db,
            org_id=org_id,
            staff=staff,
            week_start=date(2026, 6, 8),
        )

        assert result.ok is False
        assert result.reason == REASON_NO_EMAIL
        assert result.message_id is None
        # No DB query — the helper short-circuits on the missing email.
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blank_email_returns_no_email_reason(self):
        """Whitespace-only emails are treated the same as None."""
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_EMAIL,
            send_roster_email,
        )

        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(), org_id=org_id, email="   ",
        )
        db = AsyncMock()

        result = await send_roster_email(
            db,
            org_id=org_id,
            staff=staff,
            week_start=date(2026, 6, 8),
        )

        assert result.ok is False
        assert result.reason == REASON_NO_EMAIL

    @pytest.mark.asyncio
    async def test_opt_out_returns_opt_out_reason(self):
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_OPT_OUT,
            send_roster_email,
        )

        org_id = uuid.uuid4()
        staff = _make_staff_stub(
            staff_id=uuid.uuid4(),
            org_id=org_id,
            weekly_roster_email_enabled=False,
        )
        db = AsyncMock()

        result = await send_roster_email(
            db,
            org_id=org_id,
            staff=staff,
            week_start=date(2026, 6, 8),
        )

        assert result.ok is False
        assert result.reason == REASON_OPT_OUT
        # No DB query — the helper short-circuits on the opt-out flag.
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_entries_returns_no_shifts_in_week_reason(self):
        """When the schedule_entries query yields zero rows the helper
        returns ``no_shifts_in_week`` and skips the render + send.
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_SHIFTS_IN_WEEK,
            send_roster_email,
        )

        org_id = uuid.uuid4()
        staff = _make_staff_stub(staff_id=uuid.uuid4(), org_id=org_id)
        db = AsyncMock()

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.staff.roster_delivery.send_email",
            new_callable=AsyncMock,
        ) as mock_send_email:
            result = await send_roster_email(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
            )

        assert result.ok is False
        assert result.reason == REASON_NO_SHIFTS_IN_WEEK
        mock_send_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_happy_path_calls_send_email_with_dlq(self):
        """Happy path: entries present → render template → call
        ``send_email`` with ``dlq_task_name='roster_email'`` and the
        right ``dlq_task_args``. Returns the provider's message id.
        """
        from datetime import date, datetime, timezone

        from app.integrations.email_sender import SendResult
        from app.modules.staff.roster_delivery import send_roster_email

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        staff = _make_staff_stub(staff_id=staff_id, org_id=org_id)
        db = AsyncMock()

        # Stub schedule entries — minimal shape used by the renderer.
        entry = SimpleNamespace(
            start_time=datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            notes="Reception cover",
            title=None,
        )

        send_result = SendResult(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="prov-msg-456",
            attempts=[],
        )

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[entry],
        ), patch(
            "app.modules.staff.roster_delivery._load_org",
            new_callable=AsyncMock,
            return_value=("Acme Auto", "Pacific/Auckland"),
        ), patch(
            "app.modules.staff.roster_delivery.send_email",
            new_callable=AsyncMock,
            return_value=send_result,
        ) as mock_send_email:
            result = await send_roster_email(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
            )

        assert result.ok is True
        assert result.message_id == "prov-msg-456"
        assert result.reason is None

        mock_send_email.assert_awaited_once()
        # First positional arg is the session, second is the EmailMessage.
        call_args = mock_send_email.await_args.args
        assert call_args[0] is db
        message = call_args[1]
        assert message.to_email == "jane@example.co.nz"
        assert message.org_id == org_id
        assert "roster" in message.subject.lower()
        # Both HTML and text bodies populated for deliverability.
        assert message.html_body
        assert message.text_body
        assert "Jane" in message.html_body
        assert "Reception cover" in message.html_body

        # DLQ wiring per R8.3 + the email-provider-unification quick win.
        kwargs = mock_send_email.await_args.kwargs
        assert kwargs["dlq_task_name"] == "roster_email"
        assert kwargs["dlq_task_args"]["staff_id"] == str(staff_id)
        assert kwargs["dlq_task_args"]["week_start"] == "2026-06-08"
        assert kwargs["dlq_task_args"]["org_id"] == str(org_id)
        # Org name flows through as the From friendly name.
        assert kwargs["org_sender_name"] == "Acme Auto"

    @pytest.mark.asyncio
    async def test_send_failure_returns_send_failed_reason(self):
        """When ``send_email`` returns ``success=False`` (provider chain
        exhausted) the helper surfaces ``ok=false, reason='send_failed'``
        — the DLQ already captured the message for replay.
        """
        from datetime import date, datetime, timezone

        from app.integrations.email_sender import SendResult
        from app.modules.staff.roster_delivery import (
            REASON_SEND_FAILED,
            send_roster_email,
        )

        org_id = uuid.uuid4()
        staff = _make_staff_stub(staff_id=uuid.uuid4(), org_id=org_id)
        db = AsyncMock()

        entry = SimpleNamespace(
            start_time=datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            notes=None,
            title=None,
        )
        send_result = SendResult(
            success=False,
            provider_key=None,
            error="all providers failed",
            attempts=[],
        )

        with patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[entry],
        ), patch(
            "app.modules.staff.roster_delivery._load_org",
            new_callable=AsyncMock,
            return_value=("Acme Auto", "UTC"),
        ), patch(
            "app.modules.staff.roster_delivery.send_email",
            new_callable=AsyncMock,
            return_value=send_result,
        ):
            result = await send_roster_email(
                db,
                org_id=org_id,
                staff=staff,
                week_start=date(2026, 6, 8),
            )

        assert result.ok is False
        assert result.reason == REASON_SEND_FAILED
        assert result.message_id is None


# ---------------------------------------------------------------------------
# SMS roster endpoint (C6, R9)
# ---------------------------------------------------------------------------


def _make_staff_stub_for_sms(
    *,
    staff_id: uuid.UUID,
    org_id: uuid.UUID,
    phone: str | None = "+64 21 555 1234",
    weekly_roster_sms_enabled: bool = True,
    first_name: str = "Jane",
    last_name: str | None = "Doe",
):
    """Build a minimal ``StaffMember``-shaped stub with the SMS-path
    fields set (``phone``, ``weekly_roster_sms_enabled``).
    """
    return SimpleNamespace(
        id=staff_id,
        org_id=org_id,
        phone=phone,
        weekly_roster_sms_enabled=weekly_roster_sms_enabled,
        first_name=first_name,
        last_name=last_name,
        name=f"{first_name} {last_name or ''}".strip(),
    )


def _request_with_origin(
    org_id: uuid.UUID | None,
    user_id: uuid.UUID | None = None,
    origin: str = "https://app.example",
) -> MagicMock:
    """Build a Request-like object with ``state`` populated and an
    ``Origin`` header so the SMS endpoint can build a viewer URL.
    """
    request = MagicMock()
    request.state = SimpleNamespace(
        org_id=org_id, user_id=user_id, client_ip=None,
    )
    request.headers = {"origin": origin}
    return request


class TestSmsRosterEndpoint:
    """Tests for ``POST /api/v2/staff/:id/sms-roster`` (Phase 1 task C6).

    Exercises the router glue directly: the module gate, the
    staff-existence check, the precondition refusals (no phone /
    opt-out / no shifts), the happy path, the G7 Māori-macron path
    (audit row records ``encoding='ucs2'``), and that the audit row is
    written with ``action='roster.sms_sent'`` and the spec-mandated
    ``after_value`` extras (``encoding``, ``segments``,
    ``phone_number_masked``).

    **Validates: Requirement R9** (R9.1, R9.2, R9.3, R9.6).
    """

    @pytest.mark.asyncio
    async def test_module_disabled_returns_404_not_enabled(self):
        from datetime import date

        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _request_with_origin(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await sms_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }
        # No staff lookup, no send, no audit when module is off.
        mock_service.get_staff.assert_not_awaited()
        mock_send.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_staff_returns_404(self):
        from datetime import date

        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _request_with_origin(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as excinfo:
                await sms_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Staff member not found"
        mock_send.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_phone_refuses_with_422(self):
        """Staff with ``phone=None`` MUST surface as HTTP 422 with
        ``reason='no_phone'`` per R9.2, and MUST NOT write an audit
        row (the endpoint short-circuits before the audit step).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_PHONE,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _request_with_origin(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub_for_sms(
            staff_id=staff_id, org_id=org_id, phone=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, reason=REASON_NO_PHONE,
            ),
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await sms_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "ok": False,
            "reason": REASON_NO_PHONE,
        }
        mock_send.assert_awaited_once()
        # Refusal cases short-circuit before the audit row is written.
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_opt_out_refuses_with_422(self):
        """When ``weekly_roster_sms_enabled=False`` the helper returns
        ``opt_out`` and the router maps it to HTTP 422 (R9.2).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_OPT_OUT,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _request_with_origin(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub_for_sms(
            staff_id=staff_id, org_id=org_id,
            weekly_roster_sms_enabled=False,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, reason=REASON_OPT_OUT,
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await sms_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "ok": False,
            "reason": REASON_OPT_OUT,
        }
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_shifts_in_week_refuses_with_422(self):
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_NO_SHIFTS_IN_WEEK,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _request_with_origin(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub_for_sms(
            staff_id=staff_id, org_id=org_id,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False, reason=REASON_NO_SHIFTS_IN_WEEK,
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await sms_roster(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "ok": False,
            "reason": REASON_NO_SHIFTS_IN_WEEK,
        }
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_happy_path_writes_audit_with_encoding_segments(self):
        """Happy path: module enabled + staff exists + phone + opt-in +
        shifts → the helper returns ok=True with a message_id and
        ``audit_extras`` carrying encoding/segments/phone_mask, and
        the router writes an ``audit_log`` row with
        ``action='roster.sms_sent'`` and ``after_value`` containing all
        three extras (R9.3 / P1-N12).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import RosterDeliveryResult
        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _request_with_origin(org_id, user_id)
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub_for_sms(
            staff_id=staff_id, org_id=org_id,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=True,
                message_id="prov-sms-123",
                reason=None,
                audit_extras={
                    "encoding": "gsm7",
                    "segments": 1,
                    "phone_number_masked": "*********1234",
                },
            ),
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await sms_roster(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # Response shape per RosterSendResponse.
        assert resp.ok is True
        assert resp.message_id == "prov-sms-123"
        assert resp.reason is None

        # send_roster_sms invoked with org/staff/week + a viewer URL
        # built from the request Origin (not the static fallback).
        mock_send.assert_awaited_once()
        send_kwargs = mock_send.await_args.kwargs
        assert send_kwargs["org_id"] == org_id
        assert send_kwargs["staff"] is staff_stub
        assert send_kwargs["week_start"] == date(2026, 6, 8)
        assert send_kwargs["viewer_base_url"].endswith(
            "/public/staff-roster",
        )
        assert "https://app.example" in send_kwargs["viewer_base_url"]

        # Audit row written with the right action + entity + after_value.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "roster.sms_sent"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        after = audit_kwargs["after_value"]
        assert after["ok"] is True
        assert after["message_id"] == "prov-sms-123"
        assert after["week_start"] == "2026-06-08"
        # The R9.3 / P1-N12 extras land in after_value.
        assert after["encoding"] == "gsm7"
        assert after["segments"] == 1
        assert after["phone_number_masked"] == "*********1234"

    @pytest.mark.asyncio
    async def test_happy_path_g7_macron_audit_records_ucs2(self):
        """G7 path: a staff named ``Aroha Tāmaki`` triggers UCS-2
        encoding because of the ``ā`` macron. The audit row's
        ``after_value.encoding`` MUST be ``'ucs2'`` and segments >= 1.

        Drives the full router stack through to the helper to confirm
        the encoding flows from the body composer to the audit row.
        """
        from datetime import date

        from app.integrations.sms_sender import SmsSendResult
        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _request_with_origin(org_id, user_id)
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub_for_sms(
            staff_id=staff_id,
            org_id=org_id,
            first_name="Aroha Tāmaki",
        )

        from datetime import datetime, timezone

        entry = SimpleNamespace(
            start_time=datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 9, 17, 0, tzinfo=timezone.utc),
            notes=None,
            title=None,
        )
        token_obj = SimpleNamespace(
            token="tok-macron-1", week_start=date(2026, 6, 8),
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.roster_delivery._load_week_entries",
            new_callable=AsyncMock,
            return_value=[entry],
        ), patch(
            "app.modules.staff.roster_delivery.get_or_create_viewer_token",
            new_callable=AsyncMock,
            return_value=token_obj,
        ), patch(
            "app.modules.staff.roster_delivery.send_sms",
            new_callable=AsyncMock,
            return_value=SmsSendResult(
                ok=True, message_id="m-ucs2", provider_key="connexus",
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await sms_roster(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        assert resp.ok is True
        # Audit row records UCS-2 encoding.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        after = audit_kwargs["after_value"]
        assert audit_kwargs["action"] == "roster.sms_sent"
        assert after["encoding"] == "ucs2"
        assert after["segments"] >= 1

    @pytest.mark.asyncio
    async def test_send_failure_returns_200_with_reason_and_audits(self):
        """A downstream provider-chain exhaustion surfaces as HTTP 200
        with ``{ok=false, reason='send_failed'}`` AND writes an audit
        row with the encoding/segments captured for the attempted
        send (so ops can trace what went out).
        """
        from datetime import date

        from app.modules.staff.roster_delivery import (
            REASON_SEND_FAILED,
            RosterDeliveryResult,
        )
        from app.modules.staff.router import sms_roster
        from app.modules.staff.schemas import RosterSmsRequest

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _request_with_origin(org_id, user_id)
        db = AsyncMock()
        payload = RosterSmsRequest(week_start=date(2026, 6, 8))
        staff_stub = _make_staff_stub_for_sms(
            staff_id=staff_id, org_id=org_id,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.send_roster_sms",
            new_callable=AsyncMock,
            return_value=RosterDeliveryResult(
                ok=False,
                message_id=None,
                reason=REASON_SEND_FAILED,
                audit_extras={
                    "encoding": "gsm7",
                    "segments": 1,
                    "phone_number_masked": "*********1234",
                },
            ),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await sms_roster(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # Send-failure is a 200 with ok=false (DLQ handles replay).
        assert resp.ok is False
        assert resp.message_id is None
        assert resp.reason == REASON_SEND_FAILED

        # Audit row IS written for send failures so ops can trace.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "roster.sms_sent"
        after = audit_kwargs["after_value"]
        assert after["ok"] is False
        assert after["reason"] == REASON_SEND_FAILED
        # Encoding/segments still captured on the failed send.
        assert after["encoding"] == "gsm7"
        assert after["segments"] == 1


# ---------------------------------------------------------------------------
# Employment agreement attach (C8, R5)
# ---------------------------------------------------------------------------


class TestAttachEmploymentAgreementEndpoint:
    """Tests for ``POST /api/v2/staff/:id/employment-agreement`` (Phase 1
    task C8).

    Exercises the router glue directly: the module gate, the
    staff-existence check, the upload-existence check (filesystem
    glob under the requesting org's ``attachments/`` namespace), the
    happy path that sets ``employment_agreement_upload_id``, and the
    audit row written with ``action='staff.employment_agreement_uploaded'``.

    Verifies cross-org isolation: a file uploaded by org A cannot be
    attached to a staff member in org B (the file path itself is
    org-scoped — the glob scopes the search to the caller's org).

    **Validates: Requirement R5**.
    """

    @staticmethod
    def _make_upload_file(
        upload_dir, org_id: uuid.UUID, upload_id: uuid.UUID, ext: str = ".pdf",
    ) -> str:
        """Materialise a fake uploaded file under
        ``{upload_dir}/attachments/{org_id}/{upload_id.hex}{ext}`` and
        return the file_key.
        """
        from pathlib import Path as _Path

        org_dir = _Path(upload_dir) / "attachments" / str(org_id)
        org_dir.mkdir(parents=True, exist_ok=True)
        target = org_dir / f"{upload_id.hex}{ext}"
        target.write_bytes(b"\x01encrypted-pdf-bytes")
        return f"attachments/{org_id}/{upload_id.hex}{ext}"

    @pytest.mark.asyncio
    async def test_employment_agreement_module_disabled_returns_404_not_enabled(self, tmp_path, monkeypatch):
        """When ``staff_management`` is disabled the module gate fires
        first — before any staff lookup or file check — and returns
        the spec-mandated 404 detail body.
        """
        from app.modules.staff.router import attach_employment_agreement
        from app.modules.staff.schemas import EmploymentAgreementRequest

        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = EmploymentAgreementRequest(upload_id=upload_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock()

            with pytest.raises(HTTPException) as excinfo:
                await attach_employment_agreement(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == {
            "detail": "not_enabled",
            "module": "staff_management",
        }
        # No staff lookup, no audit when module is off.
        mock_service.get_staff.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_employment_agreement_unknown_staff_returns_404(self, tmp_path, monkeypatch):
        """When the staff member doesn't exist (or belongs to another
        org) the endpoint MUST return 404 ``"Staff member not found"``
        — even if the upload file exists on disk. The staff check
        runs before the upload check.
        """
        from app.modules.staff.router import attach_employment_agreement
        from app.modules.staff.schemas import EmploymentAgreementRequest

        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        # Materialise the upload so we know the 404 came from the
        # staff check, not the upload check.
        self._make_upload_file(tmp_path, org_id, upload_id)
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = EmploymentAgreementRequest(upload_id=upload_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as excinfo:
                await attach_employment_agreement(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Staff member not found"
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_employment_agreement_missing_upload_returns_404(self, tmp_path, monkeypatch):
        """When the staff exists but the referenced ``upload_id`` has
        no file on disk under the org's ``attachments/`` folder, the
        endpoint MUST return 404 ``"Upload not found"``.
        """
        from app.modules.staff.router import attach_employment_agreement
        from app.modules.staff.schemas import EmploymentAgreementRequest

        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        # Note: do NOT materialise the upload — it should be missing.
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()
        payload = EmploymentAgreementRequest(upload_id=upload_id)
        staff_stub = SimpleNamespace(
            id=staff_id, org_id=org_id, employment_agreement_upload_id=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await attach_employment_agreement(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Upload not found"
        # Staff record is NOT mutated when the upload is missing.
        assert staff_stub.employment_agreement_upload_id is None
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_employment_agreement_upload_from_other_org_returns_404(
        self, tmp_path, monkeypatch,
    ):
        """When a caller from org A tries to attach an upload that
        was actually uploaded by org B (file lives at
        ``attachments/<orgB>/<upload_hex>.pdf``), the endpoint MUST
        return 404 ``"Upload not found"`` because the glob scopes the
        search to ``attachments/<orgA>/...``. This proves cross-org
        isolation without requiring an ``uploads`` ORM table.
        """
        from app.modules.staff.router import attach_employment_agreement
        from app.modules.staff.schemas import EmploymentAgreementRequest

        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        caller_org = uuid.uuid4()
        other_org = uuid.uuid4()
        staff_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        # Materialise the upload under the OTHER org's folder — the
        # caller (caller_org) should not be able to find it.
        self._make_upload_file(tmp_path, other_org, upload_id)

        request = _make_request_with_user(caller_org, uuid.uuid4())
        db = AsyncMock()
        payload = EmploymentAgreementRequest(upload_id=upload_id)
        staff_stub = SimpleNamespace(
            id=staff_id, org_id=caller_org,
            employment_agreement_upload_id=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await attach_employment_agreement(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Upload not found"
        assert staff_stub.employment_agreement_upload_id is None
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_employment_agreement_happy_path_sets_upload_id_and_writes_audit(
        self, tmp_path, monkeypatch,
    ):
        """Happy path: staff exists, upload file exists under the
        caller's org folder → ``staff.employment_agreement_upload_id``
        is set, ``db.flush`` + ``db.refresh`` are called, an
        ``audit_log`` row is written with
        ``action='staff.employment_agreement_uploaded'`` and the
        new upload_id in ``after_value``, and the response is the
        masked ``StaffMemberResponse``.
        """
        from datetime import datetime, timezone
        from decimal import Decimal

        from app.modules.staff.router import attach_employment_agreement
        from app.modules.staff.schemas import (
            EmploymentAgreementRequest,
            StaffMemberResponse,
        )

        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        self._make_upload_file(tmp_path, org_id, upload_id, ext=".pdf")

        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        # The router calls _enrich_reporting_to which runs a SQL query —
        # patch it so we don't need a real DB session.
        payload = EmploymentAgreementRequest(upload_id=upload_id)

        # Build a staff stub shaped enough that
        # ``StaffMemberResponse.model_validate`` succeeds (the router
        # serialises the staff via ``_enrich_reporting_to``).
        now = datetime.now(timezone.utc)
        staff_stub = SimpleNamespace(
            id=staff_id,
            org_id=org_id,
            user_id=None,
            name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            email=None,
            phone=None,
            employee_id=None,
            position=None,
            reporting_to=None,
            shift_start=None,
            shift_end=None,
            role_type="employee",
            hourly_rate=Decimal("28.00"),
            overtime_rate=None,
            is_active=True,
            availability_schedule={},
            skills=[],
            created_at=now,
            updated_at=now,
            location_assignments=[],
            employment_start_date=None,
            employment_end_date=None,
            employment_type="permanent",
            standard_hours_per_week=None,
            tax_code=None,
            ird_number=None,
            student_loan=False,
            kiwisaver_enrolled=False,
            kiwisaver_employee_rate=None,
            kiwisaver_employer_rate=Decimal("3.00"),
            bank_account_number=None,
            probation_end_date=None,
            residency_type="citizen",
            visa_expiry_date=None,
            self_service_clock_enabled=False,
            on_file_photo_url=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
            weekly_roster_email_enabled=True,
            weekly_roster_sms_enabled=False,
            last_pay_review_date=None,
            employment_agreement_upload_id=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)
            # _enrich_reporting_to is what the existing endpoints use
            # to build the response dict; patch it to return the
            # mutated stub's dict so the response shape is correct
            # without needing a real DB query.
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await attach_employment_agreement(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # The staff record now points at the uploaded agreement.
        assert staff_stub.employment_agreement_upload_id == upload_id

        # db.flush + db.refresh both called (project-overview rule:
        # always refresh after flush before Pydantic serialization).
        db.flush.assert_awaited()
        db.refresh.assert_awaited_once_with(staff_stub)

        # Audit row written with the spec-mandated action + entity ids.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "staff.employment_agreement_uploaded"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        # First-time attach → no before_value (previous was None).
        assert audit_kwargs["before_value"] is None
        assert audit_kwargs["after_value"] == {"upload_id": str(upload_id)}

        # Response is the masked StaffMemberResponse with the new id.
        assert isinstance(resp, StaffMemberResponse)
        assert resp.employment_agreement_upload_id == upload_id

    @pytest.mark.asyncio
    async def test_employment_agreement_replace_existing_records_before_value(
        self, tmp_path, monkeypatch,
    ):
        """When the staff already has an employment agreement attached,
        replacing it MUST record the prior ``upload_id`` in
        ``before_value`` so the audit trail captures the swap.
        """
        from datetime import datetime, timezone
        from decimal import Decimal

        from app.modules.staff.router import attach_employment_agreement
        from app.modules.staff.schemas import (
            EmploymentAgreementRequest,
            StaffMemberResponse,
        )

        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        previous_upload_id = uuid.uuid4()
        new_upload_id = uuid.uuid4()
        self._make_upload_file(tmp_path, org_id, new_upload_id, ext=".pdf")

        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = EmploymentAgreementRequest(upload_id=new_upload_id)

        now = datetime.now(timezone.utc)
        staff_stub = SimpleNamespace(
            id=staff_id,
            org_id=org_id,
            user_id=None,
            name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            email=None,
            phone=None,
            employee_id=None,
            position=None,
            reporting_to=None,
            shift_start=None,
            shift_end=None,
            role_type="employee",
            hourly_rate=Decimal("28.00"),
            overtime_rate=None,
            is_active=True,
            availability_schedule={},
            skills=[],
            created_at=now,
            updated_at=now,
            location_assignments=[],
            employment_start_date=None,
            employment_end_date=None,
            employment_type="permanent",
            standard_hours_per_week=None,
            tax_code=None,
            ird_number=None,
            student_loan=False,
            kiwisaver_enrolled=False,
            kiwisaver_employee_rate=None,
            kiwisaver_employer_rate=Decimal("3.00"),
            bank_account_number=None,
            probation_end_date=None,
            residency_type="citizen",
            visa_expiry_date=None,
            self_service_clock_enabled=False,
            on_file_photo_url=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
            weekly_roster_email_enabled=True,
            weekly_roster_sms_enabled=False,
            last_pay_review_date=None,
            employment_agreement_upload_id=previous_upload_id,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            await attach_employment_agreement(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # New upload id now stored.
        assert staff_stub.employment_agreement_upload_id == new_upload_id

        # Audit row captures the swap: before = previous, after = new.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "staff.employment_agreement_uploaded"
        assert audit_kwargs["before_value"] == {
            "upload_id": str(previous_upload_id),
        }
        assert audit_kwargs["after_value"] == {
            "upload_id": str(new_upload_id),
        }


# ---------------------------------------------------------------------------
# Minimum-wage gate (C10, R4)
# ---------------------------------------------------------------------------


def _make_min_wage_staff_stub(
    *,
    staff_id: uuid.UUID,
    org_id: uuid.UUID,
    hourly_rate,
    employment_agreement_upload_id: uuid.UUID | None = None,
):
    """Build a ``StaffMember``-shaped stub that ``StaffMemberResponse``
    can serialise without complaining about missing attributes.

    Centralises the mutable defaults so the C10 tests below stay
    focused on the minimum-wage branching, not on field plumbing.
    """
    from datetime import datetime, timezone
    from decimal import Decimal

    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=staff_id,
        org_id=org_id,
        user_id=None,
        name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        email=None,
        phone=None,
        employee_id=None,
        position=None,
        reporting_to=None,
        shift_start=None,
        shift_end=None,
        role_type="employee",
        hourly_rate=hourly_rate,
        overtime_rate=None,
        is_active=True,
        availability_schedule={},
        skills=[],
        created_at=now,
        updated_at=now,
        location_assignments=[],
        employment_start_date=None,
        employment_end_date=None,
        employment_type="permanent",
        standard_hours_per_week=None,
        tax_code=None,
        ird_number=None,
        student_loan=False,
        kiwisaver_enrolled=False,
        kiwisaver_employee_rate=None,
        kiwisaver_employer_rate=Decimal("3.00"),
        bank_account_number=None,
        probation_end_date=None,
        residency_type="citizen",
        visa_expiry_date=None,
        self_service_clock_enabled=False,
        on_file_photo_url=None,
        emergency_contact_name=None,
        emergency_contact_phone=None,
        weekly_roster_email_enabled=True,
        weekly_roster_sms_enabled=False,
        last_pay_review_date=None,
        employment_agreement_upload_id=employment_agreement_upload_id,
    )


class TestCreateStaffMinimumWageGate:
    """Tests for ``POST /api/v2/staff`` minimum-wage gate (Phase 1 task C10).

    Two paths in scope per R4:

    1. Below threshold + no override → HTTP 422 with detail body
       ``{"detail": "minimum_wage_below_threshold", "threshold": 23.15}``.
    2. Below threshold + ``minimum_wage_override=True`` → 201 created,
       AND an ``audit_log`` row is written with
       ``action='staff.minimum_wage_override'`` carrying the acting
       user_id (the one waving it through).

    Plus the negative case: a rate at or above threshold MUST NOT
    write an override audit row.

    **Validates: Requirement R4** (Phase 1 task C10).
    """

    @pytest.mark.asyncio
    async def test_below_threshold_no_override_returns_422(self):
        """When the service raises ``MinimumWageBelowThresholdError``
        the router translates it into HTTP 422 with the documented
        detail body — and never writes an override audit row (the
        request was refused).
        """
        from decimal import Decimal

        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import StaffMemberCreate
        from app.modules.staff.service import (
            MinimumWageBelowThresholdError,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=False,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.create_staff = AsyncMock(
                side_effect=MinimumWageBelowThresholdError(
                    threshold=Decimal("23.15"),
                ),
            )

            with pytest.raises(HTTPException) as excinfo:
                await create_staff(
                    payload=payload, request=request, db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "detail": "minimum_wage_below_threshold",
            "threshold": 23.15,
        }
        # Refusal path → no override audit row.
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_below_threshold_with_override_writes_audit(self):
        """Override path: the service accepts the create AND the
        router writes an ``audit_log`` row with
        ``action='staff.minimum_wage_override'`` and the acting user_id
        attached. The audit row's ``after_value`` carries the rate that
        was waved through and the threshold it was compared against
        so the audit trail is self-contained.
        """
        from decimal import Decimal

        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import (
            StaffMemberCreate,
            StaffMemberResponse,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=True,
        )
        staff_stub = _make_min_wage_staff_stub(
            staff_id=staff_id, org_id=org_id, hourly_rate=Decimal("20.00"),
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            # The service accepts the create when override=True.
            mock_service.create_staff = AsyncMock(return_value=staff_stub)
            # Router resolves the threshold to gate the audit-row write
            # to the actual below-threshold case.
            mock_service._resolve_minimum_wage_threshold = AsyncMock(
                return_value=Decimal("23.15"),
            )
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await create_staff(
                payload=payload, request=request, db=db,
            )

        # Request succeeded — response is the masked StaffMemberResponse.
        assert isinstance(resp, StaffMemberResponse)
        assert resp.id == staff_id

        # Audit row written for the override.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "staff.minimum_wage_override"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        assert audit_kwargs["after_value"] == {
            "hourly_rate": "20.00",
            "threshold": "23.15",
        }

    @pytest.mark.asyncio
    async def test_at_or_above_threshold_no_override_no_audit(self):
        """A rate at or above the threshold MUST NOT write an override
        audit row even if the client (incorrectly) sets
        ``minimum_wage_override=True`` — the audit row only fires when
        the rate actually fell below the threshold. Stops the override
        log filling up with non-overrides.
        """
        from decimal import Decimal

        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import (
            StaffMemberCreate,
            StaffMemberResponse,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        # Above threshold, but the client sent override=True anyway.
        payload = StaffMemberCreate(
            first_name="Jane",
            hourly_rate=Decimal("30.00"),
            minimum_wage_override=True,
        )
        staff_stub = _make_min_wage_staff_stub(
            staff_id=staff_id, org_id=org_id, hourly_rate=Decimal("30.00"),
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.create_staff = AsyncMock(return_value=staff_stub)
            mock_service._resolve_minimum_wage_threshold = AsyncMock(
                return_value=Decimal("23.15"),
            )
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await create_staff(
                payload=payload, request=request, db=db,
            )

        assert isinstance(resp, StaffMemberResponse)
        # Audit row NOT written — rate was above threshold.
        mock_audit.assert_not_awaited()


class TestUpdateStaffMinimumWageGate:
    """Tests for ``PUT /api/v2/staff/:id`` minimum-wage gate (C10, R4).

    Mirrors :class:`TestCreateStaffMinimumWageGate` for the update
    path: the same 422 envelope on refusal and the same
    ``staff.minimum_wage_override`` audit row when the override flag
    is set and the rate is below threshold.
    """

    @pytest.mark.asyncio
    async def test_below_threshold_no_override_returns_422(self):
        """Update with a below-threshold rate and no override surfaces
        the canonical 422 detail body. No audit row written.
        """
        from decimal import Decimal

        from app.modules.staff.router import update_staff
        from app.modules.staff.schemas import StaffMemberUpdate
        from app.modules.staff.service import (
            MinimumWageBelowThresholdError,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberUpdate(
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=False,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.update_staff = AsyncMock(
                side_effect=MinimumWageBelowThresholdError(
                    threshold=Decimal("23.15"),
                ),
            )

            with pytest.raises(HTTPException) as excinfo:
                await update_staff(
                    staff_id=staff_id,
                    payload=payload,
                    request=request,
                    db=db,
                )

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {
            "detail": "minimum_wage_below_threshold",
            "threshold": 23.15,
        }
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_below_threshold_with_override_writes_audit(self):
        """Update with override=True succeeds AND writes the
        ``staff.minimum_wage_override`` audit row carrying the acting
        user_id.
        """
        from decimal import Decimal

        from app.modules.staff.router import update_staff
        from app.modules.staff.schemas import (
            StaffMemberResponse,
            StaffMemberUpdate,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberUpdate(
            hourly_rate=Decimal("20.00"),
            minimum_wage_override=True,
        )
        staff_stub = _make_min_wage_staff_stub(
            staff_id=staff_id, org_id=org_id, hourly_rate=Decimal("20.00"),
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.update_staff = AsyncMock(return_value=staff_stub)
            mock_service._resolve_minimum_wage_threshold = AsyncMock(
                return_value=Decimal("23.15"),
            )
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await update_staff(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        assert isinstance(resp, StaffMemberResponse)
        assert resp.id == staff_id

        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "staff.minimum_wage_override"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        assert audit_kwargs["after_value"] == {
            "hourly_rate": "20.00",
            "threshold": "23.15",
        }

    @pytest.mark.asyncio
    async def test_update_without_hourly_rate_no_audit(self):
        """An update that doesn't touch ``hourly_rate`` MUST NOT trigger
        the override audit row even if ``minimum_wage_override=True``
        is in the payload — the override only matters when the rate
        is being changed.
        """
        from app.modules.staff.router import update_staff
        from app.modules.staff.schemas import (
            StaffMemberResponse,
            StaffMemberUpdate,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        # No hourly_rate in the payload — only updating the contact.
        payload = StaffMemberUpdate(
            emergency_contact_name="John Doe",
            minimum_wage_override=True,
        )
        staff_stub = _make_min_wage_staff_stub(
            staff_id=staff_id, org_id=org_id, hourly_rate=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.update_staff = AsyncMock(return_value=staff_stub)
            mock_service._resolve_minimum_wage_threshold = AsyncMock()
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await update_staff(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        assert isinstance(resp, StaffMemberResponse)
        # No audit row when the update doesn't touch the rate.
        mock_audit.assert_not_awaited()

# ---------------------------------------------------------------------------
# Roster-token revocation on deactivation + termination (C11, G4, R9.7)
# ---------------------------------------------------------------------------


class TestDeactivateStaffRevokesTokens:
    """Tests for ``DELETE /api/v2/staff/:id`` revoking active roster
    viewer tokens (Phase 1 task C11 / gap-closure tag G4).

    Exercises the router glue: the SQL UPDATE is dispatched against
    ``StaffRosterViewToken`` for the (org, staff) pair, the audit row
    is written when at least one token was revoked, and no audit row
    is written for staff who never had a roster sent.

    Drives the helper ``_revoke_active_roster_tokens`` directly via
    the public endpoint so a regression in the deactivation flow is
    caught at the API boundary, not just at the helper.

    **Validates: Requirement R9.7** (Phase 1 task C11).
    """

    @pytest.mark.asyncio
    async def test_deactivate_with_active_tokens_revokes_and_writes_audit(self):
        """Deactivating a staff with N active roster tokens MUST run
        the bulk UPDATE that flips ``expires_at = now()`` and write a
        single audit_log row with ``action='roster.tokens_revoked'``
        carrying the revoked count in ``after_value``.
        """
        from app.modules.staff.router import deactivate_staff

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)

        # Stub the DB session: the UPDATE...RETURNING dispatched by
        # ``_revoke_active_roster_tokens`` lands in db.execute, so we
        # have to make ``result.fetchall()`` return a non-empty list.
        revoked_ids = [(uuid.uuid4(),), (uuid.uuid4(),)]
        update_result = MagicMock()
        update_result.fetchall = MagicMock(return_value=revoked_ids)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=update_result)
        # The deactivation flag flip mutates the in-memory staff stub;
        # the test only cares that the staff existed and was found.
        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, is_active=True)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.onboarding_tokens.revoke_active",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.staff.router.account_service.revoke_portal_access_for_staff",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await deactivate_staff(
                staff_id=staff_id, request=request, db=db,
            )

        assert resp == {"message": "Staff member deactivated", "id": str(staff_id)}
        # The ``is_active`` flag was flipped before the revocation runs.
        assert staff_stub.is_active is False

        # Audit row written with the revoked count.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "roster.tokens_revoked"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        assert audit_kwargs["after_value"] == {
            "tokens_revoked_count": len(revoked_ids),
        }

    @pytest.mark.asyncio
    async def test_deactivate_with_no_active_tokens_writes_no_audit(self):
        """A staff who never had a roster sent has zero rows in
        ``staff_roster_view_tokens``. Deactivation MUST still
        succeed but MUST NOT write the ``roster.tokens_revoked``
        audit row — the audit log shouldn't fill up with no-op entries.
        """
        from app.modules.staff.router import deactivate_staff

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)

        # Empty fetchall → zero tokens revoked → no audit row.
        update_result = MagicMock()
        update_result.fetchall = MagicMock(return_value=[])
        db = AsyncMock()
        db.execute = AsyncMock(return_value=update_result)
        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, is_active=True)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.onboarding_tokens.revoke_active",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.staff.router.account_service.revoke_portal_access_for_staff",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await deactivate_staff(
                staff_id=staff_id, request=request, db=db,
            )

        assert resp["message"] == "Staff member deactivated"
        assert staff_stub.is_active is False
        # Zero tokens revoked → no audit row.
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deactivate_unknown_staff_returns_404_no_revocation(self):
        """A 404 short-circuits before any revocation work — proves the
        existence guard precedes the token UPDATE so we don't silently
        revoke tokens for a staff that doesn't belong to the caller's
        org.
        """
        from app.modules.staff.router import deactivate_staff

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, uuid.uuid4())
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as excinfo:
                await deactivate_staff(
                    staff_id=staff_id, request=request, db=db,
                )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Staff member not found"
        # No revocation work + no audit row when the staff is missing.
        db.execute.assert_not_awaited()
        mock_audit.assert_not_awaited()


class TestUpdateStaffTerminationRevokesTokens:
    """Tests for ``PUT /api/v2/staff/:id`` revoking active roster
    viewer tokens when ``employment_end_date`` is being set for the
    first time (the "termination" flow).

    Three branches cover the spec contract:

    1. Setting ``employment_end_date`` from None → date triggers
       revocation (and an audit row when tokens existed).
    2. An update that doesn't touch ``employment_end_date`` MUST NOT
       trigger revocation, even if there are active tokens.
    3. Re-saving the same ``employment_end_date`` (already set) MUST
       NOT trigger another revocation — the spec scopes revocation to
       the None → set transition, not every PUT that includes the
       field.

    **Validates: Requirement R9.7** (Phase 1 task C11).
    """

    def _build_min_wage_stub(self, *, staff_id, org_id, employment_end_date=None):
        """Build a ``StaffMember``-shaped stub that the response
        serialiser is happy with — reuses the same field set as the
        C10 helpers above.
        """
        from datetime import datetime, timezone
        from decimal import Decimal

        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=staff_id,
            org_id=org_id,
            user_id=None,
            name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            email=None,
            phone=None,
            employee_id=None,
            position=None,
            reporting_to=None,
            shift_start=None,
            shift_end=None,
            role_type="employee",
            hourly_rate=Decimal("28.00"),
            overtime_rate=None,
            is_active=True,
            availability_schedule={},
            skills=[],
            created_at=now,
            updated_at=now,
            location_assignments=[],
            employment_start_date=None,
            employment_end_date=employment_end_date,
            employment_type="permanent",
            standard_hours_per_week=None,
            tax_code=None,
            ird_number=None,
            student_loan=False,
            kiwisaver_enrolled=False,
            kiwisaver_employee_rate=None,
            kiwisaver_employer_rate=Decimal("3.00"),
            bank_account_number=None,
            probation_end_date=None,
            residency_type="citizen",
            visa_expiry_date=None,
            self_service_clock_enabled=False,
            on_file_photo_url=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
            weekly_roster_email_enabled=True,
            weekly_roster_sms_enabled=False,
            last_pay_review_date=None,
            employment_agreement_upload_id=None,
        )

    @pytest.mark.asyncio
    async def test_setting_end_date_first_time_revokes_tokens_and_audits(self):
        """``employment_end_date`` going from None to a real date is
        the termination signal. The router MUST revoke any active
        roster tokens in the same transaction and write a
        ``roster.tokens_revoked`` audit row when revocations happen.
        """
        from datetime import date

        from app.modules.staff.router import update_staff
        from app.modules.staff.schemas import (
            StaffMemberResponse,
            StaffMemberUpdate,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        payload = StaffMemberUpdate(
            employment_end_date=date(2026, 6, 30),
        )

        # Two stubs: the prior one (employment_end_date=None) is what
        # the pre-update svc.get_staff returns; the post-update one
        # (employment_end_date set) is what svc.update_staff returns.
        prior_stub = self._build_min_wage_stub(
            staff_id=staff_id, org_id=org_id, employment_end_date=None,
        )
        updated_stub = self._build_min_wage_stub(
            staff_id=staff_id,
            org_id=org_id,
            employment_end_date=date(2026, 6, 30),
        )

        # The revocation UPDATE returns 1 token revoked.
        revoked_ids = [(uuid.uuid4(),)]
        update_result = MagicMock()
        update_result.fetchall = MagicMock(return_value=revoked_ids)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=update_result)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.account_service.revoke_portal_access_for_staff",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=prior_stub)
            mock_service.update_staff = AsyncMock(return_value=updated_stub)
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await update_staff(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        # Update succeeded.
        assert isinstance(resp, StaffMemberResponse)
        assert resp.employment_end_date == date(2026, 6, 30)

        # Audit row written for the revocation.
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "roster.tokens_revoked"
        assert audit_kwargs["entity_type"] == "staff_member"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        assert audit_kwargs["after_value"] == {
            "tokens_revoked_count": 1,
        }

    @pytest.mark.asyncio
    async def test_update_without_end_date_change_no_revocation(self):
        """An update that doesn't include ``employment_end_date`` in
        the payload MUST NOT trigger any revocation work, even if the
        staff happens to have active tokens. Only the
        None → set transition is the trigger.
        """
        from app.modules.staff.router import update_staff
        from app.modules.staff.schemas import (
            StaffMemberResponse,
            StaffMemberUpdate,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        # Only updating an emergency contact — no end-date in the body.
        payload = StaffMemberUpdate(
            emergency_contact_name="John Doe",
        )
        updated_stub = self._build_min_wage_stub(
            staff_id=staff_id, org_id=org_id, employment_end_date=None,
        )

        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            # ``get_staff`` should NOT be called for the prior-state
            # check when the payload doesn't touch end_date.
            mock_service.get_staff = AsyncMock()
            mock_service.update_staff = AsyncMock(return_value=updated_stub)
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await update_staff(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        assert isinstance(resp, StaffMemberResponse)
        # No prior-state lookup, no audit row when end_date isn't touched.
        mock_service.get_staff.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_with_end_date_already_set_no_revocation(self):
        """When the staff already has an ``employment_end_date`` set,
        re-saving the same date (or even a different date) MUST NOT
        trigger a fresh revocation — the spec scopes revocation to
        the None → set transition. Otherwise admins fixing a typo on
        the termination date would re-revoke tokens unnecessarily.
        """
        from datetime import date

        from app.modules.staff.router import update_staff
        from app.modules.staff.schemas import (
            StaffMemberResponse,
            StaffMemberUpdate,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        payload = StaffMemberUpdate(
            employment_end_date=date(2026, 7, 15),
        )

        # Prior state already has an end date set — this PUT is a
        # correction, not a termination event.
        prior_stub = self._build_min_wage_stub(
            staff_id=staff_id,
            org_id=org_id,
            employment_end_date=date(2026, 6, 30),
        )
        updated_stub = self._build_min_wage_stub(
            staff_id=staff_id,
            org_id=org_id,
            employment_end_date=date(2026, 7, 15),
        )

        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=prior_stub)
            mock_service.update_staff = AsyncMock(return_value=updated_stub)
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await update_staff(
                staff_id=staff_id,
                payload=payload,
                request=request,
                db=db,
            )

        assert isinstance(resp, StaffMemberResponse)
        # No revocation when the prior end_date was already set.
        mock_audit.assert_not_awaited()


class TestActivateDoesNotRestoreTokens:
    """Tests for ``POST /api/v2/staff/:id/activate`` (gap-closure tag G4).

    Reactivation is a deliberate no-op for tokens — the spec says
    staff must receive a fresh roster send to get a new viewer link,
    so the activate handler MUST NOT touch ``staff_roster_view_tokens``
    at all. This test locks that contract: zero UPDATEs to the token
    table when activating, even when the deactivated tokens are still
    sitting in the table with ``expires_at = now()``.

    **Validates: Requirement R9.7** (Phase 1 task C11).
    """

    @pytest.mark.asyncio
    async def test_activate_does_not_touch_token_table(self):
        from app.modules.staff.router import activate_staff
        from app.modules.staff.schemas import StaffMemberResponse

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)

        # Track every db.execute call so the test can assert no UPDATE
        # against staff_roster_view_tokens went out.
        executed_statements: list = []

        async def _record_execute(stmt, *args, **kwargs):
            executed_statements.append(stmt)
            # Reactivation only does an in-memory flag flip + flush,
            # so no execute results are needed; return a benign mock.
            return MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_record_execute)

        # The deactivated staff is what activate_staff() will flip.
        from datetime import datetime, timezone
        from decimal import Decimal

        now = datetime.now(timezone.utc)
        staff_stub = SimpleNamespace(
            id=staff_id,
            org_id=org_id,
            user_id=None,
            name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            email=None,
            phone=None,
            employee_id=None,
            position=None,
            reporting_to=None,
            shift_start=None,
            shift_end=None,
            role_type="employee",
            hourly_rate=Decimal("28.00"),
            overtime_rate=None,
            is_active=False,
            availability_schedule={},
            skills=[],
            created_at=now,
            updated_at=now,
            location_assignments=[],
            employment_start_date=None,
            employment_end_date=None,
            employment_type="permanent",
            standard_hours_per_week=None,
            tax_code=None,
            ird_number=None,
            student_loan=False,
            kiwisaver_enrolled=False,
            kiwisaver_employee_rate=None,
            kiwisaver_employer_rate=Decimal("3.00"),
            bank_account_number=None,
            probation_end_date=None,
            residency_type="citizen",
            visa_expiry_date=None,
            self_service_clock_enabled=False,
            on_file_photo_url=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
            weekly_roster_email_enabled=True,
            weekly_roster_sms_enabled=False,
            last_pay_review_date=None,
            employment_agreement_upload_id=None,
        )

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
        ) as mock_enrich, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)
            mock_enrich.side_effect = lambda _db, s: {
                **{
                    k: getattr(s, k, None)
                    for k in StaffMemberResponse.model_fields
                },
            }

            resp = await activate_staff(
                staff_id=staff_id, request=request, db=db,
            )

        assert isinstance(resp, StaffMemberResponse)
        # The flag was flipped back to True.
        assert staff_stub.is_active is True
        # No audit row written by the activate handler — and crucially
        # no ``roster.tokens_revoked`` row (the C11 contract is that
        # reactivation does NOT un-revoke tokens).
        mock_audit.assert_not_awaited()
        # No SQL execute touched StaffRosterViewToken at all.
        for stmt in executed_statements:
            stmt_text = str(stmt).lower()
            assert "staff_roster_view_tokens" not in stmt_text, (
                "activate_staff should not touch the token table — "
                f"saw statement: {stmt_text}"
            )


# ---------------------------------------------------------------------------
# Task 6.1 — POST /api/v2/staff onboarding-link branch (R1.2/1.3/1.4/1.5,
# R3.6/3.7)
# ---------------------------------------------------------------------------


def _valid_response_dict(*, staff_id: uuid.UUID, org_id: uuid.UUID) -> dict:
    """A complete, schema-valid ``StaffMemberResponse`` payload dict.

    Mirrors what ``_enrich_reporting_to`` returns for a freshly-created
    staff member — only the required fields need real values; the rest
    fall back to their schema defaults.
    """
    from datetime import datetime

    now = datetime(2026, 1, 1, 12, 0, 0)
    return {
        "id": staff_id,
        "org_id": org_id,
        "name": "Jane Doe",
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@example.co.nz",
        "role_type": "employee",
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


class TestCreateStaffOnboardingLink:
    """The ``send_onboarding_link`` branch of ``create_staff`` (task 6.1)."""

    @pytest.mark.asyncio
    async def test_flag_set_with_email_mints_token_and_sends_email(self):
        """R1.3 — flag set + email present → mint a token, send the
        invite email, and fold a successful send into the response
        advisory fields. An ``onboarding.link_sent`` audit row is
        written.
        """
        from app.modules.staff.onboarding_delivery import OnboardingDeliveryResult
        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import StaffMemberCreate, StaffMemberResponse

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberCreate(
            first_name="Jane", email="jane@example.co.nz", send_onboarding_link=True,
        )
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
            return_value=_valid_response_dict(staff_id=staff_id, org_id=org_id),
        ), patch(
            "app.modules.staff.router.onboarding_tokens.mint",
            new_callable=AsyncMock,
            return_value="raw-token-xyz",
        ) as mock_mint, patch(
            "app.modules.staff.router.send_onboarding_email",
            new_callable=AsyncMock,
            return_value=OnboardingDeliveryResult(ok=True, message_id="msg-1"),
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.create_staff = AsyncMock(return_value=staff_stub)

            resp = await create_staff(payload=payload, request=request, db=db)

        assert isinstance(resp, StaffMemberResponse)
        assert resp.onboarding_email_sent is True
        assert resp.onboarding_email_error is None

        mock_mint.assert_awaited_once()
        assert mock_mint.await_args.kwargs["org_id"] == org_id
        assert mock_mint.await_args.kwargs["staff_id"] == staff_id

        mock_send.assert_awaited_once()
        assert mock_send.await_args.kwargs["token"] == "raw-token-xyz"

        mock_audit.assert_awaited_once()
        assert mock_audit.await_args.kwargs["action"] == "onboarding.link_sent"
        assert mock_audit.await_args.kwargs["after_value"] == {
            "onboarding_email_sent": True,
            "onboarding_email_error": None,
        }

    @pytest.mark.asyncio
    async def test_send_failure_preserves_record_and_does_not_raise(self):
        """R3.6 — a provider failure must NOT raise; the created staff
        record is preserved and the failure folds into
        ``onboarding_email_error``.
        """
        from app.modules.staff.onboarding_delivery import OnboardingDeliveryResult
        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import StaffMemberCreate, StaffMemberResponse

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberCreate(
            first_name="Jane", email="jane@example.co.nz", send_onboarding_link=True,
        )
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
            return_value=_valid_response_dict(staff_id=staff_id, org_id=org_id),
        ), patch(
            "app.modules.staff.router.onboarding_tokens.mint",
            new_callable=AsyncMock,
            return_value="raw-token-xyz",
        ), patch(
            "app.modules.staff.router.send_onboarding_email",
            new_callable=AsyncMock,
            return_value=OnboardingDeliveryResult(ok=False, error_code="send_failed"),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ):
            mock_service = mock_service_cls.return_value
            mock_service.create_staff = AsyncMock(return_value=staff_stub)

            resp = await create_staff(payload=payload, request=request, db=db)

        assert isinstance(resp, StaffMemberResponse)
        assert resp.id == staff_id  # record preserved
        assert resp.onboarding_email_sent is False
        assert resp.onboarding_email_error == "send_failed"

    @pytest.mark.asyncio
    async def test_flag_set_without_email_returns_422_and_no_mint(self):
        """R1.2 belt-and-braces — flag set but no email → 422
        ``onboarding_email_required`` and NO token minted.
        """
        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import StaffMemberCreate

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberCreate(
            first_name="Jane", email=None, send_onboarding_link=True,
        )
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id, email=None)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
            return_value=_valid_response_dict(staff_id=staff_id, org_id=org_id),
        ), patch(
            "app.modules.staff.router.onboarding_tokens.mint",
            new_callable=AsyncMock,
        ) as mock_mint, patch(
            "app.modules.staff.router.send_onboarding_email",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_service = mock_service_cls.return_value
            mock_service.create_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await create_staff(payload=payload, request=request, db=db)

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == {"detail": "onboarding_email_required"}
        mock_mint.assert_not_awaited()
        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flag_unset_does_not_mint_or_send(self):
        """R1.4 — flag unset → no token, no email, advisory fields stay None."""
        from app.modules.staff.router import create_staff
        from app.modules.staff.schemas import StaffMemberCreate, StaffMemberResponse

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)
        db = AsyncMock()
        payload = StaffMemberCreate(first_name="Jane", email="jane@example.co.nz")
        staff_stub = _make_staff_stub(staff_id=staff_id, org_id=org_id)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router._enrich_reporting_to",
            new_callable=AsyncMock,
            return_value=_valid_response_dict(staff_id=staff_id, org_id=org_id),
        ), patch(
            "app.modules.staff.router.onboarding_tokens.mint",
            new_callable=AsyncMock,
        ) as mock_mint, patch(
            "app.modules.staff.router.send_onboarding_email",
            new_callable=AsyncMock,
        ) as mock_send:
            mock_service = mock_service_cls.return_value
            mock_service.create_staff = AsyncMock(return_value=staff_stub)

            resp = await create_staff(payload=payload, request=request, db=db)

        assert isinstance(resp, StaffMemberResponse)
        assert resp.onboarding_email_sent is None
        assert resp.onboarding_email_error is None
        mock_mint.assert_not_awaited()
        mock_send.assert_not_awaited()


def _make_portal_request(org_id, user_id, *, origin=None):
    """A ``Request``-like stub with ``state`` set and a real ``headers`` dict.

    The portal-access issue handler reads ``request.headers.get("origin")``;
    a bare ``MagicMock`` would return a truthy mock there, so we give it a
    plain dict (empty → falls back to the configured base url).
    """
    request = MagicMock()
    request.state = SimpleNamespace(org_id=org_id, user_id=user_id, client_ip=None)
    request.headers = {"origin": origin} if origin else {}
    return request


class TestIssuePortalAccess:
    """``POST /api/v2/staff/{staff_id}/portal-access`` (task 9.5, R5.3/R15)."""

    @pytest.mark.asyncio
    async def test_issue_success_sends_email_and_audits(self):
        """Happy path: issue access, build the branded set-password URL,
        dispatch the credential-setup email, fold ``invite_sent=True`` into
        the response, and write a ``staff.portal_access_issued`` audit row.
        """
        from app.modules.employee_portal.employee_portal_delivery import (
            EmployeePortalDeliveryResult,
        )
        from app.modules.staff.router import issue_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        portal_user_id = uuid.uuid4()
        request = _make_portal_request(org_id, user_id, origin="https://acme.example")

        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, email="worker@acme.example")
        portal_user_stub = SimpleNamespace(id=portal_user_id, email="worker@acme.example")

        org_result = MagicMock()
        org_result.first = MagicMock(return_value=("acme", "Acme Ltd"))
        db = AsyncMock()
        db.execute = AsyncMock(return_value=org_result)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.issue_access",
            new_callable=AsyncMock,
            return_value=(portal_user_stub, "raw-token-abc"),
        ), patch(
            "app.modules.staff.router.employee_portal_delivery.send_credential_setup_email",
            new_callable=AsyncMock,
            return_value=EmployeePortalDeliveryResult(ok=True, message_id="m1"),
        ) as mock_send, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await issue_portal_access(staff_id=staff_id, request=request, db=db)

        assert resp.portal_user_id == portal_user_id
        assert resp.email == "worker@acme.example"
        assert resp.invite_sent is True
        assert resp.invite_error is None

        # The branded set-password URL was built from origin + slug + token.
        send_kwargs = mock_send.await_args.kwargs
        assert send_kwargs["set_password_url"] == (
            "https://acme.example/e/acme/accept-invite/raw-token-abc"
        )
        assert send_kwargs["org_name"] == "Acme Ltd"

        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "staff.portal_access_issued"
        assert audit_kwargs["entity_id"] == staff_id
        assert audit_kwargs["after_value"]["invite_sent"] is True

    @pytest.mark.asyncio
    async def test_issue_email_failure_still_returns_201_user_preserved(self):
        """All providers failing folds ``invite_sent=False`` + ``invite_error``
        into the response but the Portal_User is preserved (no rollback, R15.3).
        """
        from app.modules.employee_portal.employee_portal_delivery import (
            EmployeePortalDeliveryResult,
        )
        from app.modules.staff.router import issue_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        portal_user_id = uuid.uuid4()
        request = _make_portal_request(org_id, user_id)

        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, email="w@acme.example")
        portal_user_stub = SimpleNamespace(id=portal_user_id, email="w@acme.example")

        org_result = MagicMock()
        org_result.first = MagicMock(return_value=("acme", "Acme Ltd"))
        db = AsyncMock()
        db.execute = AsyncMock(return_value=org_result)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.issue_access",
            new_callable=AsyncMock,
            return_value=(portal_user_stub, "raw-token-abc"),
        ), patch(
            "app.modules.staff.router.employee_portal_delivery.send_credential_setup_email",
            new_callable=AsyncMock,
            return_value=EmployeePortalDeliveryResult(ok=False, error_code="send_failed"),
        ), patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ):
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await issue_portal_access(staff_id=staff_id, request=request, db=db)

        assert resp.portal_user_id == portal_user_id  # user preserved
        assert resp.invite_sent is False
        assert resp.invite_error == "send_failed"

    @pytest.mark.asyncio
    async def test_issue_without_email_returns_422(self):
        """A staff member with no email is rejected 422 ``email_required``
        before issuing — no Portal_User is created (R15.6).
        """
        from app.modules.staff.router import issue_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_portal_request(org_id, uuid.uuid4())
        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, email="   ")
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.issue_access",
            new_callable=AsyncMock,
        ) as mock_issue:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await issue_portal_access(staff_id=staff_id, request=request, db=db)

        assert excinfo.value.status_code == 422
        assert excinfo.value.detail["code"] == "email_required"
        mock_issue.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_issue_duplicate_returns_409(self):
        """An active Portal_User already holding the email → 409 ``duplicate``."""
        from app.modules.staff.router import account_service, issue_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_portal_request(org_id, uuid.uuid4())
        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, email="dup@acme.example")
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.issue_access",
            new_callable=AsyncMock,
            side_effect=account_service.DuplicatePortalUser("dup"),
        ):
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            with pytest.raises(HTTPException) as excinfo:
                await issue_portal_access(staff_id=staff_id, request=request, db=db)

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["code"] == "duplicate"

    @pytest.mark.asyncio
    async def test_issue_unknown_staff_returns_404(self):
        """A staff record outside the caller's org / missing → 404, no issue."""
        from app.modules.staff.router import issue_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_portal_request(org_id, uuid.uuid4())
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.issue_access",
            new_callable=AsyncMock,
        ) as mock_issue:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as excinfo:
                await issue_portal_access(staff_id=staff_id, request=request, db=db)

        assert excinfo.value.status_code == 404
        mock_issue.assert_not_awaited()


class TestRevokePortalAccess:
    """``DELETE /api/v2/staff/{staff_id}/portal-access`` (task 9.5, R5.10)."""

    @pytest.mark.asyncio
    async def test_revoke_success_invalidates_sessions_and_audits(self):
        from app.modules.staff.router import revoke_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_portal_request(org_id, user_id)
        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, email="w@acme.example")
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.revoke_access",
            new_callable=AsyncMock,
            return_value=3,
        ) as mock_revoke, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            resp = await revoke_portal_access(staff_id=staff_id, request=request, db=db)

        assert resp.revoked is True
        assert resp.sessions_invalidated == 3
        mock_revoke.assert_awaited_once()
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "staff.portal_access_revoked"
        assert audit_kwargs["after_value"] == {"sessions_invalidated": 3}

    @pytest.mark.asyncio
    async def test_revoke_unknown_staff_returns_404(self):
        from app.modules.staff.router import revoke_portal_access

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        request = _make_portal_request(org_id, uuid.uuid4())
        db = AsyncMock()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.account_service.revoke_access",
            new_callable=AsyncMock,
        ) as mock_revoke:
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as excinfo:
                await revoke_portal_access(staff_id=staff_id, request=request, db=db)

        assert excinfo.value.status_code == 404
        mock_revoke.assert_not_awaited()


class TestDeactivateAutoRevokesPortalAccess:
    """R5.11 — staff deactivation / termination auto-revokes portal access."""

    @pytest.mark.asyncio
    async def test_deactivate_calls_revoke_portal_access_for_staff(self):
        from app.modules.staff.router import deactivate_staff

        org_id = uuid.uuid4()
        staff_id = uuid.uuid4()
        user_id = uuid.uuid4()
        request = _make_request_with_user(org_id, user_id)

        update_result = MagicMock()
        update_result.fetchall = MagicMock(return_value=[])
        db = AsyncMock()
        db.execute = AsyncMock(return_value=update_result)
        staff_stub = SimpleNamespace(id=staff_id, org_id=org_id, is_active=True)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.staff.router.StaffService"
        ) as mock_service_cls, patch(
            "app.modules.staff.router.onboarding_tokens.revoke_active",
            new_callable=AsyncMock,
            return_value=0,
        ), patch(
            "app.modules.staff.router.account_service.revoke_portal_access_for_staff",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_revoke, patch(
            "app.modules.staff.router.write_audit_log",
            new_callable=AsyncMock,
        ):
            mock_service = mock_service_cls.return_value
            mock_service.get_staff = AsyncMock(return_value=staff_stub)

            await deactivate_staff(staff_id=staff_id, request=request, db=db)

        # Portal access auto-revoked in the same transaction as the flag flip.
        assert staff_stub.is_active is False
        mock_revoke.assert_awaited_once()
        revoke_args = mock_revoke.await_args
        assert revoke_args.args[1] == org_id
        assert revoke_args.args[2] == staff_id
