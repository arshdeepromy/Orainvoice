"""Unit tests for ``app.modules.leave.service`` workflow paths.

Covers task B3 from `.kiro/specs/staff-management-p2`:

1. ``submit_request`` happy path — pending row inserted, pending_hours
   incremented for accruing types, audit row written.
2. Bereavement: missing ``relationship_to_subject`` →
   :class:`BereavementValidationError`.
3. Bereavement: ``relationship='close_family'`` and hours over the 3-day
   cap → :class:`BereavementCapExceededError` with ``cap_hours``.
4. Bereavement: ``relationship='other'`` and hours over the 1-day cap
   → :class:`BereavementCapExceededError`.
5. Bereavement happy path: ``relationship='close_family'``, hours=24
   (= 3 × 8h) → submitted; pending_hours NOT incremented (event_based);
   audit redaction does not apply (bereavement is not confidential).
6. TOIL Phase 2 guard: requesting more than ``available`` →
   :class:`InsufficientToilBalanceError`.
7. TOIL: hours equal to available → succeeds.
8. ``approve_request``: confidential leave, approver lacks
   ``leave.fv_view`` → :class:`LeavePermissionDenied`, status stays
   ``pending``.
9. ``approve_request``: confidential leave, approver has
   ``leave.fv_view`` → status flips to ``approved``, ledger row written.
10. ``approve_request``: writes ledger row with
    ``reason='request_approved'`` for a non-confidential type.
11. ``reject_request``: same permission gate as approve.
12. ``adjust_balance``: writes a ledger row reason='manual_adjustment'
    and updates ``balance.accrued_hours``.
13. Partial-day capture: single date, hours < std_daily →
    ``partial_day_start_time`` persisted on the row.

Mocks the DB session with ``AsyncMock``/``MagicMock`` following the
same pattern used by ``tests/unit/test_staff_service_phase1.py`` (Phase
1 task B4 tests).

**Validates: Requirements R1, R2, R3, R4, R12 — Staff Phase 2 task B3**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the User mapper is registered before any StaffMember /
# Organisation mapper configuration runs. The Organisation mapper has a
# string-name relationship to ``User`` that fails to resolve if no
# module has imported the User class into the registry yet — this
# triggers ``KeyError: 'User'`` deep inside SQLAlchemy when the test
# tries to instantiate a StaffMember. Importing here side-steps it.
import app.modules.auth.models  # noqa: F401

from app.modules.leave.models import (
    LeaveBalance,
    LeaveLedger,
    LeaveRequest,
    LeaveType,
)
from app.modules.leave.service import (
    BereavementCapExceededError,
    BereavementValidationError,
    InsufficientLeaveError,
    InsufficientToilBalanceError,
    LeavePermissionDenied,
    LeaveServiceError,
    adjust_balance,
    approve_request,
    cancel_request,
    reject_request,
    submit_request,
)
from app.modules.staff.models import StaffMember


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_staff(**kwargs) -> StaffMember:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        standard_hours_per_week=Decimal("40.00"),
        shift_start="09:00",
        shift_end="17:00",
        employment_type="permanent",
    )
    defaults.update(kwargs)
    return StaffMember(**defaults)


def _make_leave_type(
    *,
    code: str,
    org_id: uuid.UUID,
    accrual_method: str = "anniversary",
    confidential: bool = False,
    requires_doctor_note: bool = False,
) -> LeaveType:
    return LeaveType(
        id=uuid.uuid4(),
        org_id=org_id,
        code=code,
        name=code.title(),
        is_paid=True,
        accrual_method=accrual_method,
        accrual_amount=None,
        accrual_unit="hours",
        carry_over_max=None,
        is_statutory=False,
        requires_doctor_note=requires_doctor_note,
        confidential_visibility=confidential,
        active=True,
        display_order=1,
    )


def _make_balance(
    *,
    staff_id: uuid.UUID,
    leave_type_id: uuid.UUID,
    org_id: uuid.UUID,
    accrued: Decimal = Decimal("0"),
    used: Decimal = Decimal("0"),
    pending: Decimal = Decimal("0"),
) -> LeaveBalance:
    return LeaveBalance(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        leave_type_id=leave_type_id,
        accrued_hours=accrued,
        used_hours=used,
        pending_hours=pending,
        anniversary_date=date(2024, 1, 1),
    )


def _make_payload(
    *,
    leave_type_id: uuid.UUID,
    start_date: date,
    end_date: date,
    hours_requested: Decimal,
    reason: str | None = None,
    relationship_to_subject: str | None = None,
    partial_day_start_time: time | None = None,
    attachment_upload_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    """Lightweight payload stand-in. The service only attribute-accesses
    fields, so a SimpleNamespace stands in for ``LeaveRequestCreate``
    without re-validating dates / relationships through pydantic (the
    bereavement validation we want to test happens in the SERVICE
    layer, not the schema layer).
    """
    return SimpleNamespace(
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        hours_requested=hours_requested,
        reason=reason,
        relationship_to_subject=relationship_to_subject,
        partial_day_start_time=partial_day_start_time,
        attachment_upload_id=attachment_upload_id,
    )


def _make_db_for_submit(
    *,
    staff: StaffMember,
    leave_type: LeaveType,
    balance: LeaveBalance,
) -> AsyncMock:
    """AsyncMock DB session for the submit_request path.

    submit_request issues:
      1. ``db.get(StaffMember, staff_id)`` → returns ``staff``
      2. ``db.get(LeaveType, leave_type_id)`` → returns ``leave_type``
      3. ``db.execute(select(LeaveBalance)...)`` → returns ``balance``
      4. ``db.flush()`` / ``db.refresh(leave_request)``
      5. write_audit_log → executes a raw INSERT (mocked away)
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db._added: list = []

    def _fake_add(obj):
        db._added.append(obj)
        # Mimic SQLAlchemy server defaults so the audit redactor can
        # serialise the row — only matters for LeaveRequest.
        if isinstance(obj, LeaveRequest):
            if obj.id is None:
                obj.id = uuid.uuid4()
            if obj.status is None:
                obj.status = "pending"

    db.add.side_effect = _fake_add

    async def _fake_get(model, key):
        if model is StaffMember:
            return staff if key == staff.id else None
        if model is LeaveType:
            return leave_type if key == leave_type.id else None
        return None

    db.get = AsyncMock(side_effect=_fake_get)

    async def _fake_execute(stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = balance
        result.scalar.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db


def _make_db_for_decision(
    *,
    leave_request: LeaveRequest,
    leave_type: LeaveType,
    staff: StaffMember,
    balance: LeaveBalance,
) -> AsyncMock:
    """AsyncMock DB for approve_request / reject_request / cancel_request.

    The decision helpers call ``_load_request_for_decision`` which:
      1. ``db.execute(select(LeaveRequest)...with_for_update())`` → returns leave_request
      2. ``db.get(LeaveType, leave_type_id)`` → returns leave_type
      3. ``db.get(StaffMember, staff_id)`` → returns staff
      4. ``db.execute(select(LeaveBalance)...)`` → returns balance
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db._added: list = []
    db.add.side_effect = lambda obj: db._added.append(obj)

    async def _fake_get(model, key):
        if model is LeaveType:
            return leave_type if key == leave_type.id else None
        if model is StaffMember:
            return staff if key == staff.id else None
        return None

    db.get = AsyncMock(side_effect=_fake_get)

    state = {"call": 0}

    async def _fake_execute(stmt):
        state["call"] += 1
        result = MagicMock()
        if state["call"] == 1:
            result.scalar_one_or_none.return_value = leave_request
        else:
            result.scalar_one_or_none.return_value = balance
        result.scalar.return_value = None
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)
    return db


def _make_request(
    *,
    role: str = "org_admin",
    has_fv_view: bool = False,
    org_id: uuid.UUID | None = None,
):
    """Build a FastAPI-style ``Request`` stand-in carrying ``state.role``,
    ``state.permission_overrides``, and ``state.org_id``.
    """
    overrides: list[dict] = []
    if has_fv_view:
        overrides.append({
            "permission_key": "leave.fv_view",
            "is_granted": True,
        })
    state = SimpleNamespace(
        role=role,
        permission_overrides=overrides,
        org_id=org_id or uuid.uuid4(),
    )
    return SimpleNamespace(state=state)


# Patch ``write_audit_log`` so the service's INSERT into ``audit_log``
# doesn't try to actually run against a mocked DB. We capture the call
# args on a per-test basis for assertions.
@pytest.fixture
def captured_audit():
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.leave.service.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


# Patch the decision-notification senders so approve_request /
# reject_request can run without hitting real provider configuration in
# the DB. The hooks are best-effort (failures are swallowed in the
# service), but mocking them keeps tests deterministic and lets us
# assert on call arguments when needed. The service imports
# ``send_email`` / ``send_sms`` locally inside
# ``_send_decision_notifications`` (to side-step the SQLAlchemy mapper
# ordering issue noted in the service's docstring), so the patches
# target the source modules themselves.
@pytest.fixture(autouse=True)
def mock_decision_notifications():
    with patch(
        "app.integrations.email_sender.send_email",
        new=AsyncMock(return_value=MagicMock(success=True)),
    ) as mock_email, patch(
        "app.integrations.sms_sender.send_sms",
        new=AsyncMock(return_value=MagicMock(ok=True)),
    ) as mock_sms:
        yield {"email": mock_email, "sms": mock_sms}


# ===========================================================================
# 1. Submit happy path
# ===========================================================================


class TestSubmitHappyPath:

    @pytest.mark.asyncio
    async def test_submit_writes_pending_row_and_increments_pending_hours(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(code="annual", org_id=org_id)
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("0"),
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            hours_requested=Decimal("40"),
            reason="Family trip",
        )

        result = await submit_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            payload=payload,
            requested_by_user_id=staff.user_id,
        )

        assert result.status == "pending"
        assert result.hours_requested == Decimal("40")
        assert balance.pending_hours == Decimal("40")
        assert any(isinstance(o, LeaveRequest) for o in db._added)
        assert len(captured_audit) == 1
        assert captured_audit[0]["action"] == "leave_request.submitted"
        # Non-confidential annual leave → reason field present in audit.
        assert captured_audit[0]["after_value"]["reason"] == "Family trip"


# ===========================================================================
# 2-5. Bereavement gate
# ===========================================================================


class TestBereavementGate:

    @pytest.mark.asyncio
    async def test_missing_relationship_raises_validation_error(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="bereavement", org_id=org_id, accrual_method="event_based"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
            relationship_to_subject=None,  # missing
        )

        with pytest.raises(BereavementValidationError) as exc:
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )
        assert exc.value.field == "relationship_to_subject"

    @pytest.mark.asyncio
    async def test_close_family_over_3_days_raises_cap_exceeded(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)  # 40h/wk → 8h/day
        lt = _make_leave_type(
            code="bereavement", org_id=org_id, accrual_method="event_based"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 4),
            hours_requested=Decimal("32"),  # > 24h cap
            relationship_to_subject="close_family",
        )

        with pytest.raises(BereavementCapExceededError) as exc:
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )
        assert exc.value.cap_hours == Decimal("24.00")

    @pytest.mark.asyncio
    async def test_other_over_1_day_raises_cap_exceeded(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="bereavement", org_id=org_id, accrual_method="event_based"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            hours_requested=Decimal("16"),  # > 8h cap
            relationship_to_subject="other",
        )

        with pytest.raises(BereavementCapExceededError) as exc:
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )
        assert exc.value.cap_hours == Decimal("8.00")

    @pytest.mark.asyncio
    async def test_close_family_24_hours_succeeds(self, captured_audit):
        """3 working days × 8 h/day = 24 h — exactly at the cap."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="bereavement", org_id=org_id, accrual_method="event_based"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 3),
            hours_requested=Decimal("24"),
            relationship_to_subject="close_family",
        )

        result = await submit_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            payload=payload,
            requested_by_user_id=staff.user_id,
        )

        assert result.status == "pending"
        # Bereavement is event_based — pending_hours stays at 0.
        assert balance.pending_hours == Decimal("0")
        assert result.relationship_to_subject == "close_family"


# ===========================================================================
# 6-7. TOIL Phase 2 guard
# ===========================================================================


class TestToilGuard:

    @pytest.mark.asyncio
    async def test_toil_over_available_raises(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="toil", org_id=org_id, accrual_method="event_based"
        )
        # 4h available, request 8h → fails.
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("4"), used=Decimal("0"), pending=Decimal("0"),
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
        )

        with pytest.raises(InsufficientToilBalanceError) as exc:
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )
        assert exc.value.available == Decimal("4")

    @pytest.mark.asyncio
    async def test_toil_equal_to_available_succeeds(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="toil", org_id=org_id, accrual_method="event_based"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("8"), used=Decimal("0"), pending=Decimal("0"),
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
        )

        result = await submit_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            payload=payload,
            requested_by_user_id=staff.user_id,
        )
        assert result.status == "pending"


# ===========================================================================
# 8-9. Confidential leave permission gate on approve
# ===========================================================================


class TestApproveConfidentialPermission:

    @pytest.mark.asyncio
    async def test_approver_without_fv_view_denied(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        approver_user_id = uuid.uuid4()  # NOT the staff's user_id
        lt = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            confidential=True,
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("8"),
        )
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
            status="pending",
            reason="confidential reason",
            requested_by=staff.user_id,
        )
        db = _make_db_for_decision(
            leave_request=leave_request,
            leave_type=lt,
            staff=staff,
            balance=balance,
        )
        request = _make_request(
            role="branch_admin",
            has_fv_view=False,
            org_id=org_id,
        )

        with pytest.raises(LeavePermissionDenied) as exc:
            await approve_request(
                db,
                org_id=org_id,
                request_id=leave_request.id,
                decided_by_user_id=approver_user_id,
                request=request,
            )
        assert exc.value.reason == "fv_leave_no_approval_permission"
        # State unchanged.
        assert leave_request.status == "pending"
        # No audit row written for the failed action.
        assert captured_audit == []

    @pytest.mark.asyncio
    async def test_approver_with_fv_view_succeeds(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        approver_user_id = uuid.uuid4()
        lt = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            confidential=True,
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("8"),
        )
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
            status="pending",
            reason="confidential reason",
            requested_by=staff.user_id,
        )
        db = _make_db_for_decision(
            leave_request=leave_request,
            leave_type=lt,
            staff=staff,
            balance=balance,
        )
        request = _make_request(
            role="branch_admin",
            has_fv_view=True,
            org_id=org_id,
        )

        result = await approve_request(
            db,
            org_id=org_id,
            request_id=leave_request.id,
            decided_by_user_id=approver_user_id,
            request=request,
        )
        assert result.status == "approved"
        assert result.decided_by == approver_user_id
        assert balance.used_hours == Decimal("8")
        assert balance.pending_hours == Decimal("0")
        # Audit row written, redacted (no reason / decision_notes /
        # relationship_to_subject / attachment_upload_id).
        assert len(captured_audit) == 1
        after = captured_audit[0]["after_value"]
        assert "reason" not in after
        assert "decision_notes" not in after
        assert "relationship_to_subject" not in after
        assert "attachment_upload_id" not in after


# ===========================================================================
# 10. Approve writes ledger row reason='request_approved'
# ===========================================================================


class TestApproveLedgerRow:

    @pytest.mark.asyncio
    async def test_approve_writes_ledger_request_approved(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        approver_user_id = uuid.uuid4()
        lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("40"),
        )
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            hours_requested=Decimal("40"),
            status="pending",
            requested_by=staff.user_id,
        )
        db = _make_db_for_decision(
            leave_request=leave_request,
            leave_type=lt,
            staff=staff,
            balance=balance,
        )
        request = _make_request(role="org_admin", org_id=org_id)

        await approve_request(
            db,
            org_id=org_id,
            request_id=leave_request.id,
            decided_by_user_id=approver_user_id,
            request=request,
        )

        ledger_rows = [o for o in db._added if isinstance(o, LeaveLedger)]
        assert len(ledger_rows) == 1
        ledger = ledger_rows[0]
        assert ledger.reason == "request_approved"
        assert ledger.delta_hours == Decimal("-40")
        assert ledger.request_id == leave_request.id


# ===========================================================================
# 11. Reject permission check
# ===========================================================================


class TestRejectPermission:

    @pytest.mark.asyncio
    async def test_reject_confidential_without_permission_denied(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        approver_user_id = uuid.uuid4()
        lt = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            confidential=True,
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("8"),
        )
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
            status="pending",
            requested_by=staff.user_id,
        )
        db = _make_db_for_decision(
            leave_request=leave_request,
            leave_type=lt,
            staff=staff,
            balance=balance,
        )
        request = _make_request(
            role="branch_admin", has_fv_view=False, org_id=org_id
        )

        with pytest.raises(LeavePermissionDenied):
            await reject_request(
                db,
                org_id=org_id,
                request_id=leave_request.id,
                decided_by_user_id=approver_user_id,
                request=request,
            )
        assert leave_request.status == "pending"

    @pytest.mark.asyncio
    async def test_reject_confidential_with_permission_succeeds(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        approver_user_id = uuid.uuid4()
        lt = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            confidential=True,
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("8"),
        )
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            hours_requested=Decimal("8"),
            status="pending",
            reason="x",
            requested_by=staff.user_id,
        )
        db = _make_db_for_decision(
            leave_request=leave_request,
            leave_type=lt,
            staff=staff,
            balance=balance,
        )
        request = _make_request(
            role="branch_admin", has_fv_view=True, org_id=org_id
        )

        result = await reject_request(
            db,
            org_id=org_id,
            request_id=leave_request.id,
            decided_by_user_id=approver_user_id,
            request=request,
            decision_notes="not approved",
        )
        assert result.status == "rejected"
        # Pending hours decremented.
        assert balance.pending_hours == Decimal("0")
        # No ledger row on reject.
        assert not any(isinstance(o, LeaveLedger) for o in db._added)


# ===========================================================================
# 12. adjust_balance writes ledger + updates accrued_hours
# ===========================================================================


class TestAdjustBalance:

    @pytest.mark.asyncio
    async def test_adjust_balance_writes_ledger_updates_accrued(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        admin_user_id = uuid.uuid4()
        lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("0"),
        )

        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)

        async def _fake_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = balance
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        ledger = await adjust_balance(
            db,
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=lt.id,
            delta_hours=Decimal("16"),
            reason="Pre-funded for July trip",
            notes="Granted per CEO approval 2026-05-20",
            created_by_user_id=admin_user_id,
        )

        assert ledger.reason == "manual_adjustment"
        assert ledger.delta_hours == Decimal("16")
        assert balance.accrued_hours == Decimal("96")
        # Audit row tagged with the human reason + notes.
        assert len(captured_audit) == 1
        assert captured_audit[0]["action"] == "leave_balance.adjusted"
        assert captured_audit[0]["after_value"]["reason"] == "Pre-funded for July trip"


# ===========================================================================
# 13. Partial-day capture
# ===========================================================================


class TestPartialDayCapture:

    @pytest.mark.asyncio
    async def test_single_date_under_std_daily_persists_partial_start_time(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)  # 8h/day
        lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("0"),
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 10),
            hours_requested=Decimal("4"),  # < 8h std day
            partial_day_start_time=time(13, 0),
        )

        result = await submit_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            payload=payload,
            requested_by_user_id=staff.user_id,
        )

        assert result.partial_day_start_time == time(13, 0)
        assert result.start_date == result.end_date

    @pytest.mark.asyncio
    async def test_multi_day_request_does_not_persist_partial_start_time(
        self, captured_audit
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("80"), used=Decimal("0"), pending=Decimal("0"),
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        # Multi-day → partial_day_start_time is ignored even if supplied.
        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            hours_requested=Decimal("16"),
            partial_day_start_time=time(13, 0),
        )

        result = await submit_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            payload=payload,
            requested_by_user_id=staff.user_id,
        )
        assert result.partial_day_start_time is None


# ===========================================================================
# Bonus regression: non-bereavement, accruing type with insufficient balance
# ===========================================================================


class TestInsufficientBalance:

    @pytest.mark.asyncio
    async def test_insufficient_annual_leave_raises(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff_id=staff.id, leave_type_id=lt.id, org_id=org_id,
            accrued=Decimal("16"), used=Decimal("0"), pending=Decimal("0"),
        )
        db = _make_db_for_submit(staff=staff, leave_type=lt, balance=balance)

        payload = _make_payload(
            leave_type_id=lt.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            hours_requested=Decimal("40"),
        )

        with pytest.raises(InsufficientLeaveError) as exc:
            await submit_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                payload=payload,
                requested_by_user_id=staff.user_id,
            )
        assert exc.value.available == Decimal("16")
