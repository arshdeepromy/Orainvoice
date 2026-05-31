"""Unit tests for ``app.modules.leave.public_holidays`` — Phase 2 task B5.

Coverage (matches tasks.md B5 verify list + F3):

  1. ``is_otherwise_working_day``: staff with ``availability_schedule``
     containing the holiday's weekday → True; without → False.
  2. ``process_holiday_for_org``: staff with ``schedule_entry`` on a PH
     that's also an OWD → alt-day ledger row written + entries marked.
  3. ``s40a_extension``: annual leave with PH inside window on staff's
     OWD → extends by one day (schedule_entries row + ledger row).

Mocks the DB session with ``AsyncMock``/``MagicMock`` and patches the
Redis client per-test (``app.core.redis.redis_pool``) — same pattern as
``tests/test_auth_password_reset.py``.

**Validates: Requirement R8 — Staff Management Phase 2 task B5**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Pre-import the model modules whose string-based relationship targets
# would otherwise fail to resolve when SQLAlchemy initialises mappers.
# Mirrors the model-loading block in app/main.py + tests/fleet_portal/
# conftest.py.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.staff.models  # noqa: F401

from app.modules.admin.models import PublicHoliday
from app.modules.leave.models import (
    LeaveBalance,
    LeaveLedger,
    LeaveRequest,
    LeaveType,
)
from app.modules.leave.public_holidays import (
    is_otherwise_working_day,
    process_holiday_for_org,
    s40a_extension,
)
from app.modules.scheduling_v2.models import ScheduleEntry
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
    accrual_method: str = "event_based",
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
        is_statutory=True,
        requires_doctor_note=False,
        confidential_visibility=False,
        active=True,
        display_order=5,
    )


def _make_schedule_entry(
    *,
    staff: StaffMember,
    target_date: date,
    entry_type: str = "job",
    notes: str | None = None,
) -> ScheduleEntry:
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=staff.org_id,
        staff_id=staff.id,
        title="Test work",
        start_time=datetime(target_date.year, target_date.month, target_date.day, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(target_date.year, target_date.month, target_date.day, 17, 0, tzinfo=timezone.utc),
        entry_type=entry_type,
        status="scheduled",
        notes=notes,
    )


def _make_redis_mock(get_value=None) -> MagicMock:
    """Build a Redis mock that returns ``get_value`` from ``.get`` and
    silently swallows ``setex``."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=get_value)
    redis.setex = AsyncMock(return_value=True)
    return redis


# ===========================================================================
# 1. is_otherwise_working_day
# ===========================================================================


class TestIsOtherwiseWorkingDay:

    @pytest.mark.asyncio
    async def test_returns_true_when_weekday_matches_availability(self):
        staff = _make_staff(
            availability_schedule={
                "monday": {"start": "09:00", "end": "17:00"},
                "tuesday": {"start": "09:00", "end": "17:00"},
                "wednesday": {"start": "09:00", "end": "17:00"},
                "thursday": {"start": "09:00", "end": "17:00"},
                "friday": {"start": "09:00", "end": "17:00"},
            },
        )
        # 2026-12-25 is a Friday.
        holiday_date = date(2026, 12, 25)

        db = AsyncMock()
        db.get = AsyncMock(return_value=staff)

        with patch("app.core.redis.redis_pool", _make_redis_mock(get_value=None)):
            result = await is_otherwise_working_day(db, staff.id, holiday_date)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_weekday_not_in_schedule(self):
        # Staff doesn't work weekends.
        staff = _make_staff(
            availability_schedule={
                "monday": {"start": "09:00", "end": "17:00"},
                "tuesday": {"start": "09:00", "end": "17:00"},
                "wednesday": {"start": "09:00", "end": "17:00"},
                "thursday": {"start": "09:00", "end": "17:00"},
                "friday": {"start": "09:00", "end": "17:00"},
            },
        )
        # 2026-12-26 is a Saturday — not in schedule.
        holiday_date = date(2026, 12, 26)

        db = AsyncMock()
        db.get = AsyncMock(return_value=staff)

        with patch("app.core.redis.redis_pool", _make_redis_mock(get_value=None)):
            result = await is_otherwise_working_day(db, staff.id, holiday_date)

        assert result is False

    @pytest.mark.asyncio
    async def test_uses_redis_cache_when_available(self):
        """When Redis returns a cached '1', the DB lookup is skipped."""
        staff = _make_staff()
        holiday_date = date(2026, 12, 25)

        db = AsyncMock()
        db.get = AsyncMock(return_value=staff)

        redis = _make_redis_mock(get_value="1")
        with patch("app.core.redis.redis_pool", redis):
            result = await is_otherwise_working_day(db, staff.id, holiday_date)

        assert result is True
        # Cache hit → DB not consulted.
        db.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_back_to_cache_with_24h_ttl(self):
        staff = _make_staff(
            availability_schedule={"friday": {"start": "09:00"}},
        )
        holiday_date = date(2026, 12, 25)  # Friday

        db = AsyncMock()
        db.get = AsyncMock(return_value=staff)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            await is_otherwise_working_day(db, staff.id, holiday_date)

        redis.setex.assert_called_once()
        args = redis.setex.call_args[0]
        assert args[0] == f"staff:owd:{staff.id}:{holiday_date.isoformat()}"
        assert args[1] == 86400  # 24h TTL
        assert args[2] == "1"


# ===========================================================================
# 2. process_holiday_for_org — alt-day grant + entry marking
# ===========================================================================


class TestProcessHolidayForOrg:

    @pytest.mark.asyncio
    async def test_grants_alt_day_when_owd_staff_scheduled_to_work(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            availability_schedule={"friday": {"start": "09:00"}},
        )
        alt_lt = _make_leave_type(
            code="public_holiday_alt",
            org_id=org_id,
            accrual_method="event_based",
        )
        balance = LeaveBalance(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=alt_lt.id,
            accrued_hours=Decimal("0"),
            used_hours=Decimal("0"),
            pending_hours=Decimal("0"),
        )
        # 2026-12-25 is a Friday — also matches the staff's OWD.
        holiday_date = date(2026, 12, 25)
        entry = _make_schedule_entry(staff=staff, target_date=holiday_date)

        # Build the DB mock: this engine issues many execute() calls.
        # We sequence the responses based on call order.
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)

        async def _fake_get(model, key):
            if model is StaffMember:
                return staff if key == staff.id else None
            return None

        db.get = AsyncMock(side_effect=_fake_get)

        # Sequence:
        #   1. SELECT active staff in org → [staff]
        #   2. (cache miss) — handled by Redis mock; no DB hit
        #   3. _scheduled_work_entries_on_date → [entry]
        #   4. SELECT LeaveType WHERE code='public_holiday_alt' → alt_lt
        #   5. Idempotency check on leave_ledger → None
        #   6. SELECT LeaveBalance for the alt type → balance
        responses = [
            {"scalars_all": [staff]},          # active staff list
            {"scalars_all": [entry]},          # scheduled work entries
            {"scalar_one_or_none": alt_lt},    # alt leave type lookup
            {"scalar_one_or_none": None},      # idempotency: no row
            {"scalar_one_or_none": balance},   # balance row
        ]
        call_state = {"i": 0}

        async def _fake_execute(stmt):
            result = MagicMock()
            spec = responses[call_state["i"]]
            call_state["i"] += 1
            if "scalars_all" in spec:
                scalars = MagicMock()
                scalars.all.return_value = spec["scalars_all"]
                result.scalars.return_value = scalars
            if "scalar_one_or_none" in spec:
                result.scalar_one_or_none.return_value = spec["scalar_one_or_none"]
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            summary = await process_holiday_for_org(db, org_id, holiday_date)

        assert summary["alt_days_granted"] == 1
        assert summary["entries_marked"] == 1
        assert summary["staff_processed"] == 1

        ledger_rows = [o for o in db._added if isinstance(o, LeaveLedger)]
        assert len(ledger_rows) == 1
        ledger = ledger_rows[0]
        assert ledger.reason == "public_holiday_extension"
        assert ledger.delta_hours == Decimal("8.00")  # 40h/wk ÷ 5
        assert ledger.occurred_at == holiday_date
        assert ledger.leave_type_id == alt_lt.id

        # Schedule entry was flagged with the time-and-a-half marker.
        assert entry.notes is not None
        assert "[Public holiday — time and a half]" in entry.notes

        # Balance bumped.
        assert balance.accrued_hours == Decimal("8.00")

    @pytest.mark.asyncio
    async def test_skips_when_staff_not_scheduled(self):
        """OWD staff with no schedule_entry → no alt-day."""
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            availability_schedule={"friday": {"start": "09:00"}},
        )
        holiday_date = date(2026, 12, 25)

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)
        db.get = AsyncMock(return_value=staff)

        responses = [
            {"scalars_all": [staff]},   # active staff list
            {"scalars_all": []},        # no scheduled work entries
        ]
        call_state = {"i": 0}

        async def _fake_execute(stmt):
            result = MagicMock()
            spec = responses[call_state["i"]]
            call_state["i"] += 1
            scalars = MagicMock()
            scalars.all.return_value = spec.get("scalars_all", [])
            result.scalars.return_value = scalars
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            summary = await process_holiday_for_org(db, org_id, holiday_date)

        assert summary["alt_days_granted"] == 0
        assert summary["entries_marked"] == 0
        assert not any(isinstance(o, LeaveLedger) for o in db._added)

    @pytest.mark.asyncio
    async def test_skips_when_not_owd(self):
        """Staff not OWD on the holiday → no alt-day, no entry marking."""
        org_id = uuid.uuid4()
        # Schedule excludes the holiday's weekday.
        staff = _make_staff(
            org_id=org_id,
            availability_schedule={"monday": {"start": "09:00"}},
        )
        holiday_date = date(2026, 12, 25)  # Friday

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)
        db.get = AsyncMock(return_value=staff)

        responses = [
            {"scalars_all": [staff]},  # active staff list
        ]
        call_state = {"i": 0}

        async def _fake_execute(stmt):
            result = MagicMock()
            spec = responses[call_state["i"]]
            call_state["i"] += 1
            scalars = MagicMock()
            scalars.all.return_value = spec.get("scalars_all", [])
            result.scalars.return_value = scalars
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            summary = await process_holiday_for_org(db, org_id, holiday_date)

        assert summary["alt_days_granted"] == 0
        assert summary["entries_marked"] == 0


# ===========================================================================
# 3. s40a_extension — extend annual leave by one day per OWD PH
# ===========================================================================


class TestS40aExtension:

    @pytest.mark.asyncio
    async def test_extends_by_one_day_per_owd_public_holiday(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            availability_schedule={
                "monday": {"start": "09:00"},
                "tuesday": {"start": "09:00"},
                "wednesday": {"start": "09:00"},
                "thursday": {"start": "09:00"},
                "friday": {"start": "09:00"},
            },
        )
        annual_lt = _make_leave_type(
            code="annual",
            org_id=org_id,
            accrual_method="anniversary",
        )

        # Annual leave from Mon 2026-12-21 to Fri 2026-12-25 (5 working
        # days). Christmas Day (Friday 25) is a public holiday inside
        # the window AND an OWD for the staff → expect one extension.
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=annual_lt.id,
            start_date=date(2026, 12, 21),
            end_date=date(2026, 12, 25),
            hours_requested=Decimal("40"),
            status="approved",
            requested_by=staff.user_id,
            decided_by=uuid.uuid4(),
            decided_at=datetime.now(timezone.utc),
        )

        # Christmas Day is the only PH inside the window.
        christmas = PublicHoliday(
            id=uuid.uuid4(),
            country_code="NZ",
            holiday_date=date(2026, 12, 25),
            name="Christmas Day",
            year=2026,
        )

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)

        async def _fake_get(model, key):
            if model is LeaveType:
                return annual_lt if key == annual_lt.id else None
            if model is StaffMember:
                return staff if key == staff.id else None
            return None

        db.get = AsyncMock(side_effect=_fake_get)

        # ``load_public_holidays_in_range`` issues one execute (the
        # DB-side SELECT, when Redis miss).
        # ``is_otherwise_working_day`` issues one ``db.get(StaffMember,
        # ...)`` per holiday (when Redis miss). DB execute is NOT used
        # by the OWD path.
        responses = [
            {"scalars_all": [christmas]},  # public-holiday SELECT
        ]
        call_state = {"i": 0}

        async def _fake_execute(stmt):
            result = MagicMock()
            if call_state["i"] >= len(responses):
                # Defensive: any extra SELECT yields empty.
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
                result.scalar_one_or_none.return_value = None
                return result
            spec = responses[call_state["i"]]
            call_state["i"] += 1
            if "scalars_all" in spec:
                scalars = MagicMock()
                scalars.all.return_value = spec["scalars_all"]
                result.scalars.return_value = scalars
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            extensions = await s40a_extension(db, leave_request)

        assert extensions == 1

        ledger_rows = [
            o
            for o in db._added
            if isinstance(o, LeaveLedger)
            and o.reason == "public_holiday_extension"
        ]
        assert len(ledger_rows) == 1
        ext_ledger = ledger_rows[0]
        assert ext_ledger.delta_hours == Decimal("8.00")
        assert ext_ledger.request_id == leave_request.id
        # Extension lands on the next working day after Friday 25th —
        # that's Monday 28th (skipping Sat 26 + Sun 27).
        assert ext_ledger.occurred_at == date(2026, 12, 28)

        schedule_entries = [
            o for o in db._added if isinstance(o, ScheduleEntry)
        ]
        assert len(schedule_entries) == 1
        assert schedule_entries[0].entry_type == "leave"
        assert schedule_entries[0].start_time.date() == date(2026, 12, 28)

    @pytest.mark.asyncio
    async def test_no_extension_when_no_public_holiday_in_window(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            availability_schedule={
                "monday": {"start": "09:00"},
                "tuesday": {"start": "09:00"},
                "wednesday": {"start": "09:00"},
                "thursday": {"start": "09:00"},
                "friday": {"start": "09:00"},
            },
        )
        annual_lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary",
        )

        # Annual leave entirely in July — no NZ public holidays.
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=annual_lt.id,
            start_date=date(2026, 7, 13),
            end_date=date(2026, 7, 17),
            hours_requested=Decimal("40"),
            status="approved",
            requested_by=staff.user_id,
        )

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)

        async def _fake_get(model, key):
            if model is LeaveType:
                return annual_lt
            if model is StaffMember:
                return staff
            return None

        db.get = AsyncMock(side_effect=_fake_get)

        async def _fake_execute(stmt):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = []  # no holidays
            result.scalars.return_value = scalars
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            extensions = await s40a_extension(db, leave_request)

        assert extensions == 0
        assert not any(isinstance(o, LeaveLedger) for o in db._added)

    @pytest.mark.asyncio
    async def test_no_extension_when_holiday_not_owd_for_staff(self):
        """Staff doesn't normally work the holiday's weekday → no
        extension (s40A only applies to OWD)."""
        org_id = uuid.uuid4()
        # Staff works Mon–Thu, NOT Friday.
        staff = _make_staff(
            org_id=org_id,
            availability_schedule={
                "monday": {"start": "09:00"},
                "tuesday": {"start": "09:00"},
                "wednesday": {"start": "09:00"},
                "thursday": {"start": "09:00"},
            },
        )
        annual_lt = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary",
        )

        # Christmas Day (Friday) inside leave window, but not OWD.
        leave_request = LeaveRequest(
            id=uuid.uuid4(),
            org_id=org_id,
            staff_id=staff.id,
            leave_type_id=annual_lt.id,
            start_date=date(2026, 12, 21),
            end_date=date(2026, 12, 25),
            hours_requested=Decimal("32"),
            status="approved",
            requested_by=staff.user_id,
        )
        christmas = PublicHoliday(
            id=uuid.uuid4(),
            country_code="NZ",
            holiday_date=date(2026, 12, 25),
            name="Christmas Day",
            year=2026,
        )

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db._added: list = []
        db.add.side_effect = lambda obj: db._added.append(obj)

        async def _fake_get(model, key):
            if model is LeaveType:
                return annual_lt
            if model is StaffMember:
                return staff
            return None

        db.get = AsyncMock(side_effect=_fake_get)

        async def _fake_execute(stmt):
            result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = [christmas]
            result.scalars.return_value = scalars
            return result

        db.execute = AsyncMock(side_effect=_fake_execute)

        redis = _make_redis_mock(get_value=None)
        with patch("app.core.redis.redis_pool", redis):
            extensions = await s40a_extension(db, leave_request)

        assert extensions == 0
        assert not any(isinstance(o, LeaveLedger) for o in db._added)
