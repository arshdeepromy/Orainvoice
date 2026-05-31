"""Unit tests for ``app.modules.time_clock.roster_change_sms`` (task B7a, G2).

Covers task B7a from `.kiro/specs/staff-management-p3` (G2 / R14a):

1. **In-window update sends SMS** — call ``_emit_roster_change_sms``
   for an entry whose ``start_time`` is < 48h away with a
   ``time_changed`` signal and a staff member with
   ``weekly_roster_sms_enabled=True`` and a phone → SMS dispatched +
   ``roster.change_sms_sent`` audit row written.
2. **Redis dedupe** — second call within 60 minutes for the same
   ``schedule_entry_id`` is suppressed (no SMS, no audit row).
3. **Opt-out skip** — ``weekly_roster_sms_enabled=False`` →
   ``roster.change_sms_skipped`` reason=``opt_out``, no SMS.
4. **No-phone skip** — ``staff.phone is None`` →
   ``roster.change_sms_skipped`` reason=``no_phone``, no SMS.
5. **Out-of-window skip** — ``entry_after.start_time`` more than 48h
   in the future → no audit, no SMS.
6. **Cancelled-entry skip (P3-N10)** — ``entry_after.status ==
   'cancelled'`` → ``roster.change_sms_skipped`` reason=
   ``cancelled_entry``, no SMS, no Redis dedupe write.
7. **Staff reassignment** — both the outgoing and incoming staff
   receive their respective templates.
8. **Composer templates** — ``compose_change_sms_body`` returns the
   spec-mandated bodies for each change_type.

The DB session is mocked with ``AsyncMock`` and ``redis_pool`` is
patched with an in-memory double, mirroring the patterns used in
``tests/unit/test_time_clock_swap_cover.py`` and
``tests/unit/test_time_clock_service.py``.

**Validates: Requirement R14a — Staff Management Phase 3 task B7a**
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
from app.modules.time_clock.roster_change_sms import (
    _emit_roster_change_sms,
    compose_change_sms_body,
    snapshot_schedule_entry,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_staff(
    *,
    org_id: uuid.UUID,
    first_name: str = "Jane",
    phone: str | None = "+64211234567",
    weekly_roster_sms_enabled: bool = True,
    **kwargs,
) -> StaffMember:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        name=first_name + " Doe",
        first_name=first_name,
        last_name="Doe",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
        employee_id="EMP-001",
        phone=phone,
        weekly_roster_sms_enabled=weekly_roster_sms_enabled,
        self_service_clock_enabled=False,
        on_file_photo_url=None,
        employment_type="permanent",
    )
    defaults.update(kwargs)
    return StaffMember(**defaults)


def _make_schedule_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID | None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    status: str = "scheduled",
) -> ScheduleEntry:
    start = start_time or (
        datetime.now(timezone.utc) + timedelta(hours=24)
    )
    end = end_time or (start + timedelta(hours=6))
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=start,
        end_time=end,
        entry_type="job",
        status=status,
    )


class _FakeRedis:
    """In-memory Redis double covering ``set(nx=True, ex=...)``.

    The ``set`` semantics mirror the real Redis NX flag — first call
    with a key returns ``True``, every subsequent call within TTL
    returns ``False``.
    """

    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.keys:
            return None  # NX failed — key already exists.
        self.keys.add(key)
        return True


def _make_db(staff_by_id: dict[uuid.UUID, StaffMember]) -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    async def _fake_get(model, key):
        if model is StaffMember:
            return staff_by_id.get(key)
        return None

    db.get = AsyncMock(side_effect=_fake_get)
    return db


@pytest.fixture
def fake_redis():
    redis = _FakeRedis()
    with patch(
        "app.modules.time_clock.roster_change_sms.redis_pool",
        redis,
    ):
        yield redis


@pytest.fixture
def captured_audit():
    captured: list[dict] = []

    async def _fake_audit(session, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    with patch(
        "app.modules.time_clock.roster_change_sms.write_audit_log",
        side_effect=_fake_audit,
    ):
        yield captured


@pytest.fixture
def captured_sms():
    sent: list[dict] = []

    async def _fake_send(db, *, to_phone, body, **kwargs):
        sent.append({"to_phone": to_phone, "body": body, **kwargs})
        return SimpleNamespace(ok=True, message_id="m1", provider_key="conn")

    with patch(
        "app.modules.time_clock.roster_change_sms.send_sms",
        side_effect=_fake_send,
    ):
        yield sent


# ---------------------------------------------------------------------------
# Pure helper — compose_change_sms_body
# ---------------------------------------------------------------------------


class TestComposeChangeSmsBody:
    """Per-template fixture checks against design §4.6 specifications."""

    def test_time_changed_template(self):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        # 9 Jun 2026 was a Tuesday.
        before_start = datetime(2026, 6, 9, 9, 0, tzinfo=timezone.utc)
        after_start = datetime(2026, 6, 9, 10, 30, tzinfo=timezone.utc)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=before_start,
            end_time=before_start + timedelta(hours=8),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=after_start,
            end_time=after_start + timedelta(hours=6, minutes=30),
            status="scheduled",
        )

        body = compose_change_sms_body(
            entry_before, entry_after, "time_changed", staff,
        )
        assert "Tue 9 Jun" in body
        assert "now 10:30-17:00" in body
        assert "(was 09:00-17:00)" in body

    def test_staff_reassigned_outgoing_template(self):
        org_id = uuid.uuid4()
        outgoing = _make_staff(org_id=org_id, first_name="Alice")
        incoming = _make_staff(org_id=org_id, first_name="Bob")
        start = datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=outgoing.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=incoming.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )

        body = compose_change_sms_body(
            entry_before, entry_after, "staff_reassigned", outgoing,
        )
        assert "has been reassigned" in body
        assert "Sat 13 Jun" in body
        assert "10:00-16:00" in body

    def test_staff_reassigned_incoming_template(self):
        org_id = uuid.uuid4()
        outgoing = _make_staff(org_id=org_id, first_name="Alice")
        incoming = _make_staff(org_id=org_id, first_name="Bob")
        start = datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=outgoing.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=incoming.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )

        body = compose_change_sms_body(
            entry_before, entry_after, "staff_reassigned", incoming,
        )
        assert "You're now on" in body
        assert "Sat 13 Jun" in body
        assert "10:00-16:00" in body

    def test_unknown_change_type_returns_empty(self):
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        start = datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc)
        entry = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        assert compose_change_sms_body(entry, entry, "garbage", staff) == ""


# ---------------------------------------------------------------------------
# Snapshot helper
# ---------------------------------------------------------------------------


class TestSnapshotScheduleEntry:

    def test_captures_pre_mutation_state(self):
        org_id = uuid.uuid4()
        original_staff = uuid.uuid4()
        new_staff = uuid.uuid4()
        entry = _make_schedule_entry(
            org_id=org_id, staff_id=original_staff,
        )

        snapshot = snapshot_schedule_entry(entry)
        # Mutate AFTER snapshot — snapshot must not change.
        entry.staff_id = new_staff
        entry.start_time = datetime.now(timezone.utc) + timedelta(days=2)

        assert snapshot.staff_id == original_staff
        assert snapshot.staff_id != entry.staff_id


# ---------------------------------------------------------------------------
# Hook — happy paths + dedupe
# ---------------------------------------------------------------------------


class TestEmitRosterChangeSms:

    @pytest.mark.asyncio
    async def test_in_window_time_change_sends_sms(
        self, fake_redis, captured_audit, captured_sms,
    ):
        """Verify case 1: update an entry within 48h → SMS sent."""
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            weekly_roster_sms_enabled=True,
        )
        # Shift starts 24h from now — well inside the 48h window.
        before_start = datetime.now(timezone.utc) + timedelta(hours=24)
        after_start = before_start + timedelta(hours=1)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=before_start,
            end_time=before_start + timedelta(hours=8),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=after_start,
            end_time=after_start + timedelta(hours=8),
            status="scheduled",
        )
        db = _make_db(staff_by_id={staff.id: staff})

        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type="time_changed",
        )

        # SMS sent.
        assert len(captured_sms) == 1
        assert captured_sms[0]["to_phone"] == staff.phone
        assert captured_sms[0]["dlq_task_name"] == "roster_change_sms"
        # Audit row written.
        actions = [a["action"] for a in captured_audit]
        assert "roster.change_sms_sent" in actions
        # Dedupe key claimed.
        assert f"roster_change:{entry_after.id}" in fake_redis.keys

    @pytest.mark.asyncio
    async def test_redis_dedupe_suppresses_second_send(
        self, fake_redis, captured_audit, captured_sms,
    ):
        """Verify case 2: update again within 1h → second SMS dedup'd."""
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            weekly_roster_sms_enabled=True,
        )
        start = datetime.now(timezone.utc) + timedelta(hours=24)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after_first = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=7),
            status="scheduled",
        )
        entry_after_second = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=start + timedelta(hours=2),
            end_time=start + timedelta(hours=8),
            status="scheduled",
        )
        db = _make_db(staff_by_id={staff.id: staff})

        # First call — sends SMS.
        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after_first,
            change_type="time_changed",
        )
        first_sms_count = len(captured_sms)
        first_audit_count = len(captured_audit)

        # Second call — dedupe key already claimed.
        await _emit_roster_change_sms(
            db,
            entry_before=entry_after_first,
            entry_after=entry_after_second,
            change_type="time_changed",
        )

        # No new SMS sent.
        assert len(captured_sms) == first_sms_count == 1
        # No new audit rows from the second call.
        assert len(captured_audit) == first_audit_count

    @pytest.mark.asyncio
    async def test_opt_out_writes_skipped_audit(
        self, fake_redis, captured_audit, captured_sms,
    ):
        """Verify case 3: staff has weekly_roster_sms_enabled=False →
        ``roster.change_sms_skipped`` reason=``opt_out``, no SMS.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            weekly_roster_sms_enabled=False,
        )
        start = datetime.now(timezone.utc) + timedelta(hours=24)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=7),
            status="scheduled",
        )
        db = _make_db(staff_by_id={staff.id: staff})

        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type="time_changed",
        )

        # No SMS dispatched.
        assert captured_sms == []
        # Audit row with opt_out reason.
        skipped = [
            a for a in captured_audit
            if a["action"] == "roster.change_sms_skipped"
        ]
        assert len(skipped) == 1
        assert skipped[0]["after_value"]["reason"] == "opt_out"

    @pytest.mark.asyncio
    async def test_no_phone_writes_skipped_audit(
        self, fake_redis, captured_audit, captured_sms,
    ):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            weekly_roster_sms_enabled=True,
            phone=None,
        )
        start = datetime.now(timezone.utc) + timedelta(hours=24)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=7),
            status="scheduled",
        )
        db = _make_db(staff_by_id={staff.id: staff})

        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type="time_changed",
        )

        assert captured_sms == []
        skipped = [
            a for a in captured_audit
            if a["action"] == "roster.change_sms_skipped"
        ]
        assert len(skipped) == 1
        assert skipped[0]["after_value"]["reason"] == "no_phone"

    @pytest.mark.asyncio
    async def test_out_of_window_skips_silently(
        self, fake_redis, captured_audit, captured_sms,
    ):
        """Shifts more than 48h out are picked up by the Friday
        auto-roster broadcast — the hook silently no-ops.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        # 96h out — well past the 48h window.
        start = datetime.now(timezone.utc) + timedelta(hours=96)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=7),
            status="scheduled",
        )
        db = _make_db(staff_by_id={staff.id: staff})

        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type="time_changed",
        )

        # No SMS, no audit, no dedupe write.
        assert captured_sms == []
        assert captured_audit == []
        assert fake_redis.keys == set()

    @pytest.mark.asyncio
    async def test_cancelled_entry_writes_skipped_audit(
        self, fake_redis, captured_audit, captured_sms,
    ):
        """P3-N10: editing a cancelled entry → no SMS, audit
        ``roster.change_sms_skipped`` reason=``cancelled_entry``.
        """
        org_id = uuid.uuid4()
        staff = _make_staff(org_id=org_id)
        start = datetime.now(timezone.utc) + timedelta(hours=24)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="cancelled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=staff.id,
            start_time=start + timedelta(hours=1),
            end_time=start + timedelta(hours=7),
            status="cancelled",
        )
        db = _make_db(staff_by_id={staff.id: staff})

        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type="time_changed",
        )

        # No SMS dispatched.
        assert captured_sms == []
        # Audit row with cancelled_entry reason.
        skipped = [
            a for a in captured_audit
            if a["action"] == "roster.change_sms_skipped"
        ]
        assert len(skipped) == 1
        assert skipped[0]["after_value"]["reason"] == "cancelled_entry"
        # Dedupe key NOT claimed — cancelled entries don't burn the slot.
        assert f"roster_change:{entry_after.id}" not in fake_redis.keys

    @pytest.mark.asyncio
    async def test_staff_reassigned_notifies_both_parties(
        self, fake_redis, captured_audit, captured_sms,
    ):
        """staff_reassigned change_type → both outgoing AND incoming
        staff get an SMS with their respective templates.
        """
        org_id = uuid.uuid4()
        outgoing = _make_staff(org_id=org_id, first_name="Alice")
        incoming = _make_staff(org_id=org_id, first_name="Bob")
        start = datetime.now(timezone.utc) + timedelta(hours=24)
        entry_before = SimpleNamespace(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=outgoing.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        entry_after = SimpleNamespace(
            id=entry_before.id,
            org_id=org_id,
            staff_id=incoming.id,
            start_time=start,
            end_time=start + timedelta(hours=6),
            status="scheduled",
        )
        db = _make_db(staff_by_id={
            outgoing.id: outgoing,
            incoming.id: incoming,
        })

        await _emit_roster_change_sms(
            db,
            entry_before=entry_before,
            entry_after=entry_after,
            change_type="staff_reassigned",
        )

        # Two SMS dispatched.
        recipients = {sms["to_phone"] for sms in captured_sms}
        assert recipients == {outgoing.phone, incoming.phone}
        # Both templates appear in the bodies.
        bodies = [sms["body"] for sms in captured_sms]
        assert any("has been reassigned" in b for b in bodies)
        assert any("You're now on" in b for b in bodies)
