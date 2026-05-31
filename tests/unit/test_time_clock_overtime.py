"""Unit tests for ``app.modules.time_clock.overtime`` (task B6).

Covers task B6 from `.kiro/specs/staff-management-p3` (R10):

1. ``submit_overtime_request`` happy path — inserts row in
   ``status='pending'``; ``requested_by`` carried; audit row
   ``overtime_request.submitted`` written.
2. ``submit_overtime_request`` validates ``proposed_extra_minutes``:
   - ``0`` raises :class:`OvertimeRequestValidationError`.
   - ``> 1440`` raises the same error.
3. ``submit_overtime_request`` 404s on missing staff or
   schedule_entry.
4. ``approve_overtime_request`` flips ``'pending' -> 'approved'``;
   ``decided_by`` + ``decided_at`` set; audit
   ``overtime_request.approved``.
5. ``reject_overtime_request`` flips ``'pending' -> 'rejected'``;
   audit ``overtime_request.rejected``.
6. ``approve`` / ``reject`` raise :class:`OvertimeRequestInvalidStateError`
   on a non-pending row.
7. ``cancel_overtime_request`` happy path — only the original
   requester can cancel; status goes to ``'rejected'`` with
   ``decision_notes='cancelled_by_requester'`` and audit action
   ``overtime_request.cancelled``.
8. ``cancel_overtime_request`` raises
   :class:`OvertimeRequestNotAuthorisedError` for a different user.

The DB session is mocked with ``AsyncMock`` following the same pattern
used by ``tests/unit/test_time_clock_service.py`` /
``tests/unit/test_time_clock_breaks.py``.

**Validates: Requirements R10 — Staff Management Phase 3 task B6**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import ORM modules so SQLAlchemy resolves string-name relationships
# before instantiating ORM objects in tests.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import OvertimeRequest
from app.modules.time_clock.overtime import (
    OvertimeRequestInvalidStateError,
    OvertimeRequestNotAuthorisedError,
    OvertimeRequestNotFoundError,
    OvertimeRequestValidationError,
    approve_overtime_request,
    cancel_overtime_request,
    reject_overtime_request,
    submit_overtime_request,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_staff(
    *,
    org_id: uuid.UUID,
    **kwargs,
) -> StaffMember:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        name="Jane Doe",
        first_name="Jane",
        last_name="Doe",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        employee_id="EMP-001",
        self_service_clock_enabled=False,
        on_file_photo_url=None,
        employment_type="permanent",
    )
    defaults.update(kwargs)
    return StaffMember(**defaults)


def _make_schedule_entry(*, org_id: uuid.UUID, staff_id: uuid.UUID) -> ScheduleEntry:
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 1, 17, 0, tzinfo=timezone.utc),
        entry_type="job",
        status="scheduled",
    )


def _make_request(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    requested_by: uuid.UUID,
    status: str = "pending",
    schedule_entry_id: uuid.UUID | None = None,
    proposed_extra_minutes: int = 60,
) -> OvertimeRequest:
    return OvertimeRequest(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        schedule_entry_id=schedule_entry_id,
        proposed_extra_minutes=proposed_extra_minutes,
        reason=None,
        requested_by=requested_by,
        status=status,
    )


def _make_db(
    *,
    staff_by_id: dict[uuid.UUID, StaffMember] | None = None,
    schedule_by_id: dict[uuid.UUID, ScheduleEntry] | None = None,
    request_by_id: dict[uuid.UUID, OvertimeRequest] | None = None,
) -> tuple[AsyncMock, list]:
    """Build an :class:`AsyncMock` DB session for the overtime tests.

    Returns a 2-tuple ``(db, added)`` where ``added`` is the list that
    accumulates objects passed to ``db.add(...)`` so the tests can
    assert on the inserted ORM row.
    """
    staff_by_id = staff_by_id or {}
    schedule_by_id = schedule_by_id or {}
    request_by_id = request_by_id or {}
    added: list = []

    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock(side_effect=lambda obj: added.append(obj))

    async def _fake_get(model, key):
        if model is StaffMember:
            return staff_by_id.get(key)
        if model is ScheduleEntry:
            return schedule_by_id.get(key)
        if model is OvertimeRequest:
            return request_by_id.get(key)
        return None

    db.get = AsyncMock(side_effect=_fake_get)
    db.execute = AsyncMock()
    return db, added


@pytest.fixture
def captured_audit():
    """Capture ``write_audit_log`` calls in the overtime module."""
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.overtime.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


# ---------------------------------------------------------------------------
# submit_overtime_request
# ---------------------------------------------------------------------------


class TestSubmitOvertimeRequest:

    @pytest.mark.asyncio
    async def test_happy_path_inserts_pending_row(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        entry = _make_schedule_entry(org_id=org_id, staff_id=staff.id)
        requested_by = uuid.uuid4()
        db, added = _make_db(
            staff_by_id={staff.id: staff},
            schedule_by_id={entry.id: entry},
        )

        result = await submit_overtime_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            proposed_extra_minutes=120,
            requested_by=requested_by,
            schedule_entry_id=entry.id,
            reason="Long booking",
        )

        assert result.status == "pending"
        assert result.proposed_extra_minutes == 120
        assert result.requested_by == requested_by
        assert result.staff_id == staff.id
        assert result.schedule_entry_id == entry.id
        # Persisted via db.add.
        assert result in added
        # Audit row.
        actions = [a["action"] for a in captured_audit]
        assert "overtime_request.submitted" in actions

    @pytest.mark.asyncio
    async def test_works_without_schedule_entry(self, captured_audit):
        """Free-form OT request — ``schedule_entry_id=None``."""
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db, added = _make_db(staff_by_id={staff.id: staff})

        result = await submit_overtime_request(
            db,
            org_id=org_id,
            staff_id=staff.id,
            proposed_extra_minutes=60,
            requested_by=uuid.uuid4(),
        )

        assert result.schedule_entry_id is None
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_zero_minutes_raises_validation_error(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db, _ = _make_db(staff_by_id={staff.id: staff})

        with pytest.raises(OvertimeRequestValidationError):
            await submit_overtime_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                proposed_extra_minutes=0,
                requested_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_minutes_above_cap_raises_validation_error(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db, _ = _make_db(staff_by_id={staff.id: staff})

        with pytest.raises(OvertimeRequestValidationError):
            await submit_overtime_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                proposed_extra_minutes=1441,
                requested_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_missing_staff_raises_404(self, captured_audit):
        org_id = uuid.uuid4()
        db, _ = _make_db()

        with pytest.raises(OvertimeRequestNotFoundError):
            await submit_overtime_request(
                db,
                org_id=org_id,
                staff_id=uuid.uuid4(),
                proposed_extra_minutes=60,
                requested_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_missing_schedule_entry_raises_404(self, captured_audit):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        db, _ = _make_db(staff_by_id={staff.id: staff})

        with pytest.raises(OvertimeRequestNotFoundError):
            await submit_overtime_request(
                db,
                org_id=org_id,
                staff_id=staff.id,
                proposed_extra_minutes=60,
                requested_by=uuid.uuid4(),
                schedule_entry_id=uuid.uuid4(),  # not in db
            )


# ---------------------------------------------------------------------------
# approve_overtime_request
# ---------------------------------------------------------------------------


class TestApproveOvertimeRequest:

    @pytest.mark.asyncio
    async def test_pending_to_approved(self, captured_audit):
        org_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=uuid.uuid4(),
        )
        decided_by = uuid.uuid4()
        db, _ = _make_db(request_by_id={request.id: request})

        result = await approve_overtime_request(
            db,
            org_id=org_id,
            request_id=request.id,
            decided_by=decided_by,
            decision_notes="OK",
        )

        assert result.status == "approved"
        assert result.decided_by == decided_by
        assert result.decided_at is not None
        assert result.decision_notes == "OK"
        actions = [a["action"] for a in captured_audit]
        assert "overtime_request.approved" in actions

    @pytest.mark.asyncio
    async def test_approve_on_already_approved_refused(self, captured_audit):
        org_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=uuid.uuid4(),
            status="approved",
        )
        db, _ = _make_db(request_by_id={request.id: request})

        with pytest.raises(OvertimeRequestInvalidStateError):
            await approve_overtime_request(
                db,
                org_id=org_id,
                request_id=request.id,
                decided_by=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_missing_request_raises_404(self, captured_audit):
        org_id = uuid.uuid4()
        db, _ = _make_db()

        with pytest.raises(OvertimeRequestNotFoundError):
            await approve_overtime_request(
                db,
                org_id=org_id,
                request_id=uuid.uuid4(),
                decided_by=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# reject_overtime_request
# ---------------------------------------------------------------------------


class TestRejectOvertimeRequest:

    @pytest.mark.asyncio
    async def test_pending_to_rejected(self, captured_audit):
        org_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=uuid.uuid4(),
        )
        decided_by = uuid.uuid4()
        db, _ = _make_db(request_by_id={request.id: request})

        result = await reject_overtime_request(
            db,
            org_id=org_id,
            request_id=request.id,
            decided_by=decided_by,
            decision_notes="No",
        )

        assert result.status == "rejected"
        assert result.decided_by == decided_by
        assert result.decision_notes == "No"
        actions = [a["action"] for a in captured_audit]
        assert "overtime_request.rejected" in actions

    @pytest.mark.asyncio
    async def test_reject_on_already_rejected_refused(self, captured_audit):
        org_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=uuid.uuid4(),
            status="rejected",
        )
        db, _ = _make_db(request_by_id={request.id: request})

        with pytest.raises(OvertimeRequestInvalidStateError):
            await reject_overtime_request(
                db,
                org_id=org_id,
                request_id=request.id,
                decided_by=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# cancel_overtime_request
# ---------------------------------------------------------------------------


class TestCancelOvertimeRequest:

    @pytest.mark.asyncio
    async def test_requester_cancel_happy_path(self, captured_audit):
        org_id = uuid.uuid4()
        requested_by = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=requested_by,
        )
        db, _ = _make_db(request_by_id={request.id: request})

        result = await cancel_overtime_request(
            db,
            org_id=org_id,
            request_id=request.id,
            acting_user_id=requested_by,
        )

        # Cancel maps to the rejected state with a marker note so the
        # row survives audit but doesn't count toward covered overtime.
        assert result.status == "rejected"
        assert result.decision_notes == "cancelled_by_requester"
        actions = [a["action"] for a in captured_audit]
        assert "overtime_request.cancelled" in actions

    @pytest.mark.asyncio
    async def test_non_requester_cannot_cancel(self, captured_audit):
        org_id = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=uuid.uuid4(),
        )
        db, _ = _make_db(request_by_id={request.id: request})

        with pytest.raises(OvertimeRequestNotAuthorisedError):
            await cancel_overtime_request(
                db,
                org_id=org_id,
                request_id=request.id,
                acting_user_id=uuid.uuid4(),  # different user
            )

    @pytest.mark.asyncio
    async def test_cancel_on_terminal_state_refused(self, captured_audit):
        org_id = uuid.uuid4()
        requested_by = uuid.uuid4()
        request = _make_request(
            org_id=org_id,
            staff_id=uuid.uuid4(),
            requested_by=requested_by,
            status="approved",
        )
        db, _ = _make_db(request_by_id={request.id: request})

        with pytest.raises(OvertimeRequestInvalidStateError):
            await cancel_overtime_request(
                db,
                org_id=org_id,
                request_id=request.id,
                acting_user_id=requested_by,
            )
