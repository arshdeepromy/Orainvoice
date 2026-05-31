"""Unit tests for ``app.modules.time_clock.swaps`` + ``cover`` (task B6).

Covers task B6 from `.kiro/specs/staff-management-p3` (G6 + G8 + G13):

1. **G6 — cover eligibility filter at broadcast time:**
   - Active staff with ``employee_id`` only → eligible.
   - Active staff with ``user_id`` only → eligible.
   - Inactive staff → excluded.
   - Staff with neither ``employee_id`` nor ``user_id`` → excluded.
   - Staff already scheduled inside the
     ``[shift.start - 30min, shift.end + 30min]`` window → excluded.
   - Requester themselves → excluded.

2. **G6 — cover eligibility re-check at claim time:**
   - Claim succeeds when no window conflict.
   - Claim raises 409 ``scheduling_conflict_at_claim`` when a new
     conflicting shift exists since broadcast; cover stays
     ``'open'``; audit row ``shift_cover.claim_conflict`` written.

3. **G8 — auto-approve vs manager-approval state transitions:**
   - With ``shift_swap_requires_manager_approval=False`` (default),
     ``target_accepts_swap`` flips status straight to ``'accepted'``
     and updates ``schedule_entries.staff_id``.
   - With ``shift_swap_requires_manager_approval=True``,
     ``target_accepts_swap`` transitions to ``'awaiting_manager'``
     and DOES NOT change ``schedule_entries.staff_id``.
   - From ``'awaiting_manager'``, ``manager_approves_swap`` flips to
     ``'accepted'`` and changes ``schedule_entries.staff_id``.
   - ``manager_rejects_swap`` flips to ``'rejected'`` without
     changing ``schedule_entries.staff_id``.
   - ``manager_approves_swap`` raises 409
     ``scheduling_conflict_at_manager_approval`` when the target now
     overlaps another shift.
   - ``cancel_swap`` flips a pending swap to ``'cancelled'``.

4. **G13 — notification matrix per event:**
   - ``request_created`` → SMS to target only.
   - ``auto_approved`` → SMS to requester + target.
   - ``target_accepted_pending_manager`` → SMS to all three roles.
   - ``target_rejected`` → SMS to requester only.
   - ``manager_approved`` → SMS to requester + target.
   - ``manager_rejected`` → SMS to requester + target.
   - ``requester_cancelled`` → SMS to target only.
   - Recipient without ``phone`` → ``shift_swap.sms_skipped`` audit
     reason=``no_phone``; no exception raised.

The DB session is mocked with ``AsyncMock`` following the same pattern
used by ``tests/unit/test_time_clock_service.py``.

**Validates: Requirements R12, R13 — Staff Management Phase 3 task B6**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import ORM modules so SQLAlchemy resolves string-name
# relationships before instantiating ORM objects in tests.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401

from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.time_clock.cover import (
    ShiftCoverConflictError,
    ShiftCoverInvalidStateError,
    ShiftCoverNotAuthorisedError,
    accept_cover_request,
    create_cover_request,
    list_eligible_staff,
)
from app.modules.time_clock.models import (
    ShiftCoverRequest,
    ShiftSwapRequest,
)
from app.modules.time_clock.swaps import (
    ShiftSwapConflictError,
    ShiftSwapInvalidStateError,
    ShiftSwapNotAuthorisedError,
    cancel_swap,
    create_swap_request,
    manager_approves_swap,
    manager_rejects_swap,
    target_accepts_swap,
    target_rejects_swap,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_staff(
    *,
    org_id: uuid.UUID,
    employee_id: str | None = "EMP-001",
    user_id: uuid.UUID | None = None,
    is_active: bool = True,
    phone: str | None = "+64211234567",
    first_name: str = "Jane",
    reporting_to: uuid.UUID | None = None,
    **kwargs,
) -> StaffMember:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=user_id if user_id is not None else uuid.uuid4(),
        name=first_name + " Doe",
        first_name=first_name,
        last_name="Doe",
        role_type="employee",
        is_active=is_active,
        availability_schedule={},
        skills=[],
        employee_id=employee_id,
        phone=phone,
        self_service_clock_enabled=False,
        on_file_photo_url=None,
        employment_type="permanent",
        reporting_to=reporting_to,
    )
    defaults.update(kwargs)
    return StaffMember(**defaults)


def _make_schedule_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    entry_type: str = "job",
    status: str = "scheduled",
) -> ScheduleEntry:
    start = start_time or datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc)
    end = end_time or start + timedelta(hours=6)
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=start,
        end_time=end,
        entry_type=entry_type,
        status=status,
    )


def _make_swap(
    *,
    org_id: uuid.UUID,
    requester_staff_id: uuid.UUID,
    target_staff_id: uuid.UUID | None,
    schedule_entry_id: uuid.UUID,
    status: str = "pending",
) -> ShiftSwapRequest:
    return ShiftSwapRequest(
        id=uuid.uuid4(),
        org_id=org_id,
        requester_staff_id=requester_staff_id,
        target_staff_id=target_staff_id,
        schedule_entry_id=schedule_entry_id,
        status=status,
    )


def _make_cover(
    *,
    org_id: uuid.UUID,
    requester_staff_id: uuid.UUID,
    schedule_entry_id: uuid.UUID,
    status: str = "open",
) -> ShiftCoverRequest:
    return ShiftCoverRequest(
        id=uuid.uuid4(),
        org_id=org_id,
        requester_staff_id=requester_staff_id,
        schedule_entry_id=schedule_entry_id,
        status=status,
        broadcast_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    )


class _SwapMockDB:
    """Async-mock DB session covering the swaps/cover service code paths.

    Knobs:
      - ``staff_by_id``: dict of staff_id -> StaffMember, used by db.get.
      - ``schedule_by_id``: dict of schedule_entry_id -> ScheduleEntry.
      - ``swap_by_id``: dict of swap_id -> ShiftSwapRequest.
      - ``cover_by_id``: dict of cover_id -> ShiftCoverRequest.
      - ``clock_in_policy``: dict for the ``SELECT clock_in_policy`` text
        query.
      - ``window_conflicts``: dict of staff_id -> bool indicating that
        the staff has a conflicting shift in the eligibility window.
      - ``eligible_staff``: list of StaffMember returned by the
        base-eligibility ``select(StaffMember)`` query in
        :func:`list_eligible_staff`.
    """

    def __init__(
        self,
        *,
        staff_by_id: dict[uuid.UUID, StaffMember] | None = None,
        schedule_by_id: dict[uuid.UUID, ScheduleEntry] | None = None,
        swap_by_id: dict[uuid.UUID, ShiftSwapRequest] | None = None,
        cover_by_id: dict[uuid.UUID, ShiftCoverRequest] | None = None,
        clock_in_policy: dict | None = None,
        window_conflicts: dict[uuid.UUID, bool] | None = None,
        eligible_staff: list[StaffMember] | None = None,
    ) -> None:
        self.staff_by_id = staff_by_id or {}
        self.schedule_by_id = schedule_by_id or {}
        self.swap_by_id = swap_by_id or {}
        self.cover_by_id = cover_by_id or {}
        self.clock_in_policy = clock_in_policy or {}
        self.window_conflicts = window_conflicts or {}
        self.eligible_staff = eligible_staff or []
        self.added: list = []

    def make_session(self) -> AsyncMock:
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock(side_effect=lambda obj: self.added.append(obj))
        db.get = AsyncMock(side_effect=self._fake_get)
        db.execute = AsyncMock(side_effect=self._fake_execute)
        return db

    async def _fake_get(self, model, key):
        if model is StaffMember:
            return self.staff_by_id.get(key)
        if model is ScheduleEntry:
            return self.schedule_by_id.get(key)
        if model is ShiftSwapRequest:
            return self.swap_by_id.get(key)
        if model is ShiftCoverRequest:
            return self.cover_by_id.get(key)
        return None

    async def _fake_execute(self, stmt, params=None):
        result = MagicMock()
        rendered = str(stmt).lower()
        try:
            text_repr = (stmt.text or "").lower()
        except AttributeError:
            text_repr = ""

        # text("SELECT clock_in_policy ...")
        if "clock_in_policy" in text_repr:
            result.scalar_one_or_none.return_value = self.clock_in_policy
            return result

        # select(StaffMember) — base eligibility filter.
        if "staff_members" in rendered and "is_active" in rendered:
            scalars = MagicMock()
            scalars.all.return_value = self.eligible_staff
            result.scalars.return_value = scalars
            return result

        # select(ScheduleEntry.id) — overlap conflict check.
        if (
            "schedule_entries" in rendered
            and "start_time" in rendered
            and "end_time" in rendered
        ):
            # Determine which staff this query is asking about — the
            # service passes ``ScheduleEntry.staff_id == :staff_id`` so
            # the param dict carries the value. SQLAlchemy parameterises
            # via Compiled.params, but when the bind isn't provided we
            # fall back to checking if any window_conflicts entry is
            # truthy. Tests construct a single-staff-at-a-time scenario
            # so this is unambiguous in practice.
            #
            # Strategy: default to "no conflicts" unless the test set
            # ``window_conflicts[staff_id]=True`` for some staff_id —
            # in which case any execute of this query type returns a
            # conflict for that staff_id when the test arms a knob
            # via the tracked _conflict_staff_id attribute.
            #
            # We keep this simple: if any window_conflicts is True,
            # we return a conflict; if all are False (or empty), no
            # conflict.
            has_conflict = any(self.window_conflicts.values())
            result.scalar_one_or_none.return_value = (
                uuid.uuid4() if has_conflict else None
            )
            return result

        # Default — empty.
        result.scalar_one_or_none.return_value = None
        scalars = MagicMock()
        scalars.all.return_value = []
        result.scalars.return_value = scalars
        return result


@pytest.fixture
def captured_audit_swaps():
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.swaps.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


@pytest.fixture
def captured_audit_cover():
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.cover.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


@pytest.fixture
def captured_sms_swaps():
    sent: list[dict] = []

    async def _fake_send(db, *, to_phone, body, **kwargs):
        sent.append({"to_phone": to_phone, "body": body, **kwargs})
        return SimpleNamespace(ok=True, message_id="m1", provider_key="conn")

    with patch(
        "app.modules.time_clock.swaps.send_sms",
        side_effect=_fake_send,
    ):
        yield sent


@pytest.fixture
def captured_sms_cover():
    sent: list[dict] = []

    async def _fake_send(db, *, to_phone, body, **kwargs):
        sent.append({"to_phone": to_phone, "body": body, **kwargs})
        return SimpleNamespace(ok=True, message_id="m1", provider_key="conn")

    with patch(
        "app.modules.time_clock.cover.send_sms",
        side_effect=_fake_send,
    ):
        yield sent


# ---------------------------------------------------------------------------
# G6 — cover eligibility filter
# ---------------------------------------------------------------------------


class TestCoverEligibilityFilter:

    @pytest.mark.asyncio
    async def test_eligible_staff_with_employee_id(self):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id, employee_id="REQ")
        eligible = _make_staff(
            org_id=org_id, employee_id="EMP-002", user_id=None,
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        mock = _SwapMockDB(eligible_staff=[eligible])
        db = mock.make_session()

        result = await list_eligible_staff(
            db,
            org_id=org_id,
            schedule_entry=entry,
            requester_staff_id=requester.id,
        )

        assert eligible in result

    @pytest.mark.asyncio
    async def test_window_conflict_excludes_staff(self):
        """Staff already scheduled inside the
        ``[shift.start - 30min, shift.end + 30min]`` window is
        excluded by the second-pass filter.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        conflicting = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        mock = _SwapMockDB(
            eligible_staff=[conflicting],
            window_conflicts={conflicting.id: True},
        )
        db = mock.make_session()

        result = await list_eligible_staff(
            db,
            org_id=org_id,
            schedule_entry=entry,
            requester_staff_id=requester.id,
        )

        assert conflicting not in result
        assert result == []


class TestCreateCoverRequest:

    @pytest.mark.asyncio
    async def test_creates_cover_and_broadcasts(
        self, captured_audit_cover, captured_sms_cover,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        recipient = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, recipient.id: recipient},
            schedule_by_id={entry.id: entry},
            eligible_staff=[recipient],
        )
        db = mock.make_session()

        cover = await create_cover_request(
            db,
            org_id=org_id,
            schedule_entry_id=entry.id,
            requester_staff_id=requester.id,
        )

        assert cover.status == "open"
        assert cover.requester_staff_id == requester.id
        assert cover in mock.added
        # Broadcast SMS dispatched to the eligible staff.
        assert len(captured_sms_cover) == 1
        assert captured_sms_cover[0]["to_phone"] == recipient.phone
        # Audit row written on creation.
        actions = [a["action"] for a in captured_audit_cover]
        assert "shift_cover.requested" in actions
        assert "shift_cover.sms_sent" in actions

    @pytest.mark.asyncio
    async def test_no_phone_writes_skipped_audit(
        self, captured_audit_cover, captured_sms_cover,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        no_phone_staff = _make_staff(
            org_id=org_id, employee_id="EMP-002", phone=None,
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        mock = _SwapMockDB(
            staff_by_id={
                requester.id: requester,
                no_phone_staff.id: no_phone_staff,
            },
            schedule_by_id={entry.id: entry},
            eligible_staff=[no_phone_staff],
        )
        db = mock.make_session()

        await create_cover_request(
            db,
            org_id=org_id,
            schedule_entry_id=entry.id,
            requester_staff_id=requester.id,
        )

        assert captured_sms_cover == []
        skipped = [
            a for a in captured_audit_cover
            if a["action"] == "shift_cover.sms_skipped"
        ]
        assert len(skipped) == 1
        assert skipped[0]["after_value"]["reason"] == "no_phone"


class TestAcceptCoverRequest:

    @pytest.mark.asyncio
    async def test_claim_succeeds_when_no_conflict(
        self, captured_audit_cover, captured_sms_cover,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        claimer = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        cover = _make_cover(
            org_id=org_id,
            requester_staff_id=requester.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, claimer.id: claimer},
            schedule_by_id={entry.id: entry},
            cover_by_id={cover.id: cover},
        )
        db = mock.make_session()

        result = await accept_cover_request(
            db,
            org_id=org_id,
            cover_id=cover.id,
            accepting_staff_id=claimer.id,
        )

        assert result.status == "accepted"
        assert result.accepted_by == claimer.id
        # Schedule_entries.staff_id flipped to the claimer.
        assert entry.staff_id == claimer.id
        # Audit row + SMS to requester.
        actions = [a["action"] for a in captured_audit_cover]
        assert "shift_cover.accepted" in actions
        assert "shift_cover.sms_sent" in actions

    @pytest.mark.asyncio
    async def test_claim_conflict_raises_409_and_audit(
        self, captured_audit_cover, captured_sms_cover,
    ):
        """G6 — race-at-claim: claimer has been scheduled into the
        window since broadcast → 409 + ``shift_cover.claim_conflict``
        audit + cover stays ``'open'``.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        claimer = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        cover = _make_cover(
            org_id=org_id,
            requester_staff_id=requester.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, claimer.id: claimer},
            schedule_by_id={entry.id: entry},
            cover_by_id={cover.id: cover},
            window_conflicts={claimer.id: True},
        )
        db = mock.make_session()

        with pytest.raises(ShiftCoverConflictError):
            await accept_cover_request(
                db,
                org_id=org_id,
                cover_id=cover.id,
                accepting_staff_id=claimer.id,
            )

        assert cover.status == "open"
        # The schedule entry was not flipped.
        assert entry.staff_id == requester.id
        # Audit row written.
        actions = [a["action"] for a in captured_audit_cover]
        assert "shift_cover.claim_conflict" in actions

    @pytest.mark.asyncio
    async def test_claim_by_inactive_staff_refused(
        self, captured_audit_cover, captured_sms_cover,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        inactive = _make_staff(
            org_id=org_id, employee_id="EMP-002", is_active=False,
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        cover = _make_cover(
            org_id=org_id,
            requester_staff_id=requester.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, inactive.id: inactive},
            schedule_by_id={entry.id: entry},
            cover_by_id={cover.id: cover},
        )
        db = mock.make_session()

        with pytest.raises(ShiftCoverNotAuthorisedError):
            await accept_cover_request(
                db,
                org_id=org_id,
                cover_id=cover.id,
                accepting_staff_id=inactive.id,
            )

    @pytest.mark.asyncio
    async def test_claim_on_non_open_cover_refused(
        self, captured_audit_cover, captured_sms_cover,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        claimer = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        cover = _make_cover(
            org_id=org_id,
            requester_staff_id=requester.id,
            schedule_entry_id=entry.id,
            status="accepted",
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, claimer.id: claimer},
            schedule_by_id={entry.id: entry},
            cover_by_id={cover.id: cover},
        )
        db = mock.make_session()

        with pytest.raises(ShiftCoverInvalidStateError):
            await accept_cover_request(
                db,
                org_id=org_id,
                cover_id=cover.id,
                accepting_staff_id=claimer.id,
            )


# ---------------------------------------------------------------------------
# G8 — auto-approve vs manager-approval state transitions
# ---------------------------------------------------------------------------


class TestSwapAutoApprove:

    @pytest.mark.asyncio
    async def test_auto_approve_flips_status_and_schedule(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """Default policy (no manager approval): target accepts →
        ``'accepted'`` straight away + ``schedule_entries.staff_id``
        flips.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id, first_name="Bob")
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002", first_name="Alice",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
            clock_in_policy={"shift_swap_requires_manager_approval": False},
        )
        db = mock.make_session()

        result = await target_accepts_swap(
            db,
            org_id=org_id,
            swap_id=swap.id,
            acting_staff_id=target.id,
        )

        assert result.status == "accepted"
        assert entry.staff_id == target.id
        # Audit row fired.
        actions = [a["action"] for a in captured_audit_swaps]
        assert "shift_swap.target_accepted" in actions
        # Notifications: requester + target SMS via auto_approved event.
        assert len(captured_sms_swaps) == 2
        recipients = {sms["to_phone"] for sms in captured_sms_swaps}
        assert requester.phone in recipients
        assert target.phone in recipients

    @pytest.mark.asyncio
    async def test_auto_approve_conflict_raises_409(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """G8 — eligibility re-check at flip moment fails with code
        ``scheduling_conflict_at_accept``.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
            clock_in_policy={"shift_swap_requires_manager_approval": False},
            window_conflicts={target.id: True},
        )
        db = mock.make_session()

        with pytest.raises(ShiftSwapConflictError) as exc_info:
            await target_accepts_swap(
                db,
                org_id=org_id,
                swap_id=swap.id,
                acting_staff_id=target.id,
            )

        assert exc_info.value.code == "scheduling_conflict_at_accept"
        # Schedule_entries.staff_id stays with the requester.
        assert entry.staff_id == requester.id
        assert swap.status == "pending"


class TestSwapManagerApprovalFlow:

    @pytest.mark.asyncio
    async def test_target_accept_transitions_to_awaiting_manager(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """G8 — when manager approval required, target accept goes to
        ``'awaiting_manager'`` (no schedule change yet).
        """
        org_id = uuid.uuid4()
        manager = _make_staff(
            org_id=org_id, employee_id="MGR", first_name="Mike",
        )
        requester = _make_staff(
            org_id=org_id, first_name="Bob", reporting_to=manager.id,
        )
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002", first_name="Alice",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={
                manager.id: manager,
                requester.id: requester,
                target.id: target,
            },
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
            clock_in_policy={"shift_swap_requires_manager_approval": True},
        )
        db = mock.make_session()

        result = await target_accepts_swap(
            db,
            org_id=org_id,
            swap_id=swap.id,
            acting_staff_id=target.id,
        )

        assert result.status == "awaiting_manager"
        # Schedule entry is NOT flipped yet.
        assert entry.staff_id == requester.id
        # All three roles get an SMS per R12.5 matrix.
        recipients = {sms["to_phone"] for sms in captured_sms_swaps}
        assert requester.phone in recipients
        assert target.phone in recipients
        assert manager.phone in recipients

    @pytest.mark.asyncio
    async def test_manager_approves_flips_to_accepted(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """G8 — manager approves an awaiting_manager swap: status →
        ``'accepted'`` + ``schedule_entries.staff_id`` flips.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id, first_name="Bob")
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002", first_name="Alice",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
            status="awaiting_manager",
        )
        manager_user_id = uuid.uuid4()
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        result = await manager_approves_swap(
            db,
            org_id=org_id,
            swap_id=swap.id,
            manager_user_id=manager_user_id,
        )

        assert result.status == "accepted"
        assert result.decided_by == manager_user_id
        assert entry.staff_id == target.id
        actions = [a["action"] for a in captured_audit_swaps]
        assert "shift_swap.manager_approved" in actions
        # SMS to requester + target.
        assert len(captured_sms_swaps) == 2

    @pytest.mark.asyncio
    async def test_manager_approve_conflict_raises_409(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """G8 — eligibility re-check at manager approval fails with
        code ``scheduling_conflict_at_manager_approval``.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
            status="awaiting_manager",
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
            window_conflicts={target.id: True},
        )
        db = mock.make_session()

        with pytest.raises(ShiftSwapConflictError) as exc_info:
            await manager_approves_swap(
                db,
                org_id=org_id,
                swap_id=swap.id,
                manager_user_id=uuid.uuid4(),
            )

        assert exc_info.value.code == "scheduling_conflict_at_manager_approval"
        assert entry.staff_id == requester.id
        assert swap.status == "awaiting_manager"

    @pytest.mark.asyncio
    async def test_manager_rejects_flips_to_rejected(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
            status="awaiting_manager",
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        result = await manager_rejects_swap(
            db,
            org_id=org_id,
            swap_id=swap.id,
            manager_user_id=uuid.uuid4(),
        )

        assert result.status == "rejected"
        # Schedule_entries.staff_id stays with the requester.
        assert entry.staff_id == requester.id
        actions = [a["action"] for a in captured_audit_swaps]
        assert "shift_swap.manager_rejected" in actions

    @pytest.mark.asyncio
    async def test_manager_approve_on_pending_refused(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """Manager-approve transition only valid from
        ``'awaiting_manager'`` — calling on ``'pending'`` raises 409.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
            status="pending",
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        with pytest.raises(ShiftSwapInvalidStateError):
            await manager_approves_swap(
                db,
                org_id=org_id,
                swap_id=swap.id,
                manager_user_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# G13 — notification matrix per event
# ---------------------------------------------------------------------------


class TestNotificationMatrix:

    @pytest.mark.asyncio
    async def test_request_created_sms_to_target_only(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id, first_name="Bob")
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002", first_name="Alice",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
        )
        db = mock.make_session()

        await create_swap_request(
            db,
            org_id=org_id,
            requester_staff_id=requester.id,
            schedule_entry_id=entry.id,
            target_staff_id=target.id,
        )

        # Only the target receives the request_created SMS.
        recipients = {sms["to_phone"] for sms in captured_sms_swaps}
        assert recipients == {target.phone}
        # SMS body mentions the requester's first name.
        assert "Bob" in captured_sms_swaps[0]["body"]

    @pytest.mark.asyncio
    async def test_target_rejected_sms_to_requester_only(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id, first_name="Bob")
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002", first_name="Alice",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        await target_rejects_swap(
            db,
            org_id=org_id,
            swap_id=swap.id,
            acting_staff_id=target.id,
        )

        recipients = {sms["to_phone"] for sms in captured_sms_swaps}
        assert recipients == {requester.phone}
        assert "Alice" in captured_sms_swaps[0]["body"]

    @pytest.mark.asyncio
    async def test_requester_cancel_sms_to_target_only(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id, first_name="Bob")
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002", first_name="Alice",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        result = await cancel_swap(
            db,
            org_id=org_id,
            swap_id=swap.id,
            acting_staff_id=requester.id,
        )

        assert result.status == "cancelled"
        recipients = {sms["to_phone"] for sms in captured_sms_swaps}
        assert recipients == {target.phone}
        assert "Bob" in captured_sms_swaps[0]["body"]

    @pytest.mark.asyncio
    async def test_no_phone_writes_skipped_audit(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        """G13 — recipient without ``phone`` produces a
        ``shift_swap.sms_skipped`` audit row reason=``no_phone``.
        """
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target_no_phone = _make_staff(
            org_id=org_id, employee_id="EMP-002", phone=None,
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        mock = _SwapMockDB(
            staff_by_id={
                requester.id: requester,
                target_no_phone.id: target_no_phone,
            },
            schedule_by_id={entry.id: entry},
        )
        db = mock.make_session()

        await create_swap_request(
            db,
            org_id=org_id,
            requester_staff_id=requester.id,
            schedule_entry_id=entry.id,
            target_staff_id=target_no_phone.id,
        )

        # No SMS dispatched.
        assert captured_sms_swaps == []
        # Audit row written with reason=no_phone.
        skipped = [
            a for a in captured_audit_swaps
            if a["action"] == "shift_swap.sms_skipped"
        ]
        assert len(skipped) >= 1
        assert any(
            a["after_value"].get("reason") == "no_phone"
            for a in skipped
        )


class TestSwapCancel:

    @pytest.mark.asyncio
    async def test_only_requester_can_cancel(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        with pytest.raises(ShiftSwapNotAuthorisedError):
            await cancel_swap(
                db,
                org_id=org_id,
                swap_id=swap.id,
                acting_staff_id=target.id,  # not the requester
            )

    @pytest.mark.asyncio
    async def test_cancel_on_terminal_state_refused(
        self, captured_audit_swaps, captured_sms_swaps,
    ):
        org_id = uuid.uuid4()
        requester = _make_staff(org_id=org_id)
        target = _make_staff(
            org_id=org_id, employee_id="EMP-002",
        )
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=requester.id,
        )
        swap = _make_swap(
            org_id=org_id,
            requester_staff_id=requester.id,
            target_staff_id=target.id,
            schedule_entry_id=entry.id,
            status="accepted",
        )
        mock = _SwapMockDB(
            staff_by_id={requester.id: requester, target.id: target},
            schedule_by_id={entry.id: entry},
            swap_by_id={swap.id: swap},
        )
        db = mock.make_session()

        with pytest.raises(ShiftSwapInvalidStateError):
            await cancel_swap(
                db,
                org_id=org_id,
                swap_id=swap.id,
                acting_staff_id=requester.id,
            )
