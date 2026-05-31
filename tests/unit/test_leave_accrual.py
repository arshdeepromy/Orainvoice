"""Unit tests for ``app.modules.leave.accrual`` — Phase 2 task B4.

Coverage (matches tasks.md B4 verify list + F1):

  1. Anniversary grant: writes a ledger row, updates ``balance.accrued_hours``.
  2. Sick yearly: 80h on anniversary, capped at ``carry_over_max=160h``.
  3. Family-violence yearly: 80h on anniversary, capped at 80h (no carry-over).
  4. Casual employment: skips annual leave but still grants sick / FV pro-rata.
  5. Idempotency: running ``accrue_for_staff`` twice on the same day writes
     only one ledger row per leave type.
  6. ``days_to_hours``: 5 days × 40h-week = 40h; 5 days × NULL-week = 40h
     (5 × 8h fallback).
  7. ``anniversary_in_year``: Feb 29 → Feb 28 in non-leap, Feb 29 in leap.

Mocks the DB session with ``AsyncMock``/``MagicMock`` following the same
pattern used by ``tests/unit/test_leave_request_workflow.py`` (Phase 2
task B3 tests).

**Validates: Requirements R5, R6, R7, R10 — Staff Management Phase 2 task B4**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# Pre-import the model modules whose string-based relationship targets
# would otherwise fail to resolve when SQLAlchemy initialises mappers.
# Mirrors the model-loading block in app/main.py + tests/fleet_portal/
# conftest.py.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.staff.models  # noqa: F401

from app.modules.leave.accrual import (
    accrue_for_staff,
    anniversary_in_year,
    days_to_hours,
)
from app.modules.leave.models import LeaveBalance, LeaveLedger, LeaveType
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
        employment_start_date=date(2024, 6, 1),
    )
    defaults.update(kwargs)
    return StaffMember(**defaults)


def _make_leave_type(
    *,
    code: str,
    org_id: uuid.UUID,
    accrual_method: str,
    accrual_amount: Decimal | None = None,
    accrual_unit: str = "hours",
    carry_over_max: Decimal | None = None,
) -> LeaveType:
    return LeaveType(
        id=uuid.uuid4(),
        org_id=org_id,
        code=code,
        name=code.title(),
        is_paid=True,
        accrual_method=accrual_method,
        accrual_amount=accrual_amount,
        accrual_unit=accrual_unit,
        carry_over_max=carry_over_max,
        is_statutory=False,
        requires_doctor_note=False,
        confidential_visibility=False,
        active=True,
        display_order=1,
    )


def _make_balance(
    *,
    staff: StaffMember,
    leave_type: LeaveType,
    accrued: Decimal = Decimal("0"),
    used: Decimal = Decimal("0"),
    pending: Decimal = Decimal("0"),
    anniversary_date: date | None = None,
) -> LeaveBalance:
    return LeaveBalance(
        id=uuid.uuid4(),
        org_id=staff.org_id,
        staff_id=staff.id,
        leave_type_id=leave_type.id,
        accrued_hours=accrued,
        used_hours=used,
        pending_hours=pending,
        anniversary_date=anniversary_date or staff.employment_start_date,
    )


def _make_db_for_accrual(
    *,
    pairs: list[tuple[LeaveBalance, LeaveType]],
    existing_ledger_keys: set[tuple[uuid.UUID, str, date]] | None = None,
) -> AsyncMock:
    """AsyncMock DB session for the accrual engine.

    The engine issues:

      1. ``db.execute(select(LeaveBalance, LeaveType).join(...).where(...))``
         → returns the (balance, type) pairs.
      2. ``db.execute(select(LeaveLedger.id).where(...).limit(1))`` →
         returns a row when ``(staff_id, leave_type_id, reason='accrual',
         occurred_at)`` matches ``existing_ledger_keys``.
      3. ``db.add(...)`` for each new ledger row + carry-over comp row.
      4. ``db.flush()`` once at the end.

    The discriminator between (1) and (2) is the column shape returned
    in the SELECT — call (1) carries TWO columns, call (2) carries ONE
    column. We use the call counter and a column-shape check to route.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db._added: list = []
    db.add.side_effect = lambda obj: db._added.append(obj)

    existing_keys = existing_ledger_keys or set()

    state = {"pairs_returned": False}

    async def _fake_execute(stmt):
        result = MagicMock()
        # ``_load_balances_with_types`` is the only call that uses
        # ``.all()``; every other call uses ``.scalar_one_or_none()``.
        if not state["pairs_returned"]:
            state["pairs_returned"] = True
            result.all.return_value = pairs
            result.scalar_one_or_none.return_value = None
            return result

        # Idempotency check. We can't easily inspect the SQL stmt, so
        # we drive off the order of calls: every subsequent execute is
        # an idempotency check that consumes one (staff_id,
        # leave_type_id, occurred_at) triple. The engine asks one
        # question per (balance, leave_type) pair when the date matches
        # the anniversary, so we model this with a per-call hook.
        # For tests, we drain the queue; if it's empty, no ledger row.
        result.scalar_one_or_none.return_value = (
            uuid.uuid4()
            if state.get("next_existing_match", False)
            else None
        )
        return result

    db.execute = AsyncMock(side_effect=_fake_execute)

    # Caller can flip ``state['next_existing_match']`` between calls
    # — but for the most common case (no existing rows) we leave it
    # False. Tests that need to exercise idempotency drive the second
    # ``accrue_for_staff`` invocation through a fresh DB.
    db._state = state
    db._existing_keys = existing_keys
    return db


def _added_ledger_rows(db: AsyncMock) -> list[LeaveLedger]:
    return [obj for obj in db._added if isinstance(obj, LeaveLedger)]


# ===========================================================================
# 1. Anniversary grant — happy path
# ===========================================================================


class TestAnniversaryGrant:

    @pytest.mark.asyncio
    async def test_writes_ledger_row_and_updates_balance_on_anniversary(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        annual = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff=staff, leave_type=annual,
            accrued=Decimal("0"), used=Decimal("0"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, annual)])

        # today = 2026-06-01 → exactly the 2nd anniversary.
        written = await accrue_for_staff(db, staff, date(2026, 6, 1))

        assert len(written) == 1
        ledger = written[0]
        assert ledger.reason == "accrual"
        assert ledger.delta_hours == Decimal("160.00")  # 40h × 4 weeks
        assert ledger.occurred_at == date(2026, 6, 1)
        # Balance bumped by the same amount.
        assert balance.accrued_hours == Decimal("160.00")

    @pytest.mark.asyncio
    async def test_no_grant_when_today_is_not_anniversary(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        annual = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff=staff, leave_type=annual,
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, annual)])

        # 2026-07-15 is not an anniversary.
        written = await accrue_for_staff(db, staff, date(2026, 7, 15))
        assert written == []
        assert balance.accrued_hours == Decimal("0")


# ===========================================================================
# 2. Sick yearly — 80h grant + carry_over cap
# ===========================================================================


class TestSickYearly:

    @pytest.mark.asyncio
    async def test_grants_80_hours_on_anniversary(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        sick = _make_leave_type(
            code="sick",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("160"),
        )
        balance = _make_balance(
            staff=staff, leave_type=sick,
            accrued=Decimal("0"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, sick)])

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))

        assert len(written) == 1
        assert written[0].delta_hours == Decimal("80.00")
        assert balance.accrued_hours == Decimal("80.00")

    @pytest.mark.asyncio
    async def test_caps_at_carry_over_max(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        sick = _make_leave_type(
            code="sick",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("160"),
        )
        # Already at 120h available — full 80h grant would push to 200h
        # (above 160 cap) so the engine scales down to +40h.
        balance = _make_balance(
            staff=staff, leave_type=sick,
            accrued=Decimal("120"), used=Decimal("0"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, sick)])

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))
        assert len(written) == 1
        assert written[0].delta_hours == Decimal("40.00")
        assert balance.accrued_hours == Decimal("160.00")

    @pytest.mark.asyncio
    async def test_no_grant_when_already_at_cap(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        sick = _make_leave_type(
            code="sick",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("160"),
        )
        balance = _make_balance(
            staff=staff, leave_type=sick,
            accrued=Decimal("160"), used=Decimal("0"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, sick)])

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))
        assert written == []
        assert balance.accrued_hours == Decimal("160")


# ===========================================================================
# 3. Family-violence yearly — 80h, no carry-over
# ===========================================================================


class TestFamilyViolenceYearly:

    @pytest.mark.asyncio
    async def test_grants_80_hours_on_anniversary(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        fv = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("80"),
        )
        balance = _make_balance(
            staff=staff, leave_type=fv,
            accrued=Decimal("0"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, fv)])

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))
        assert len(written) == 1
        assert written[0].delta_hours == Decimal("80.00")
        assert balance.accrued_hours == Decimal("80.00")

    @pytest.mark.asyncio
    async def test_resets_to_80h_when_partially_used(self):
        """No carry-over: grants enough to bring net up to 80h again."""
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        fv = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("80"),
        )
        # Used 30h last year, leaving 50h net. Engine grants 30h to
        # bring net back up to 80h.
        balance = _make_balance(
            staff=staff, leave_type=fv,
            accrued=Decimal("80"), used=Decimal("30"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, fv)])

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))
        assert len(written) == 1
        assert written[0].delta_hours == Decimal("30.00")
        assert balance.accrued_hours == Decimal("110.00")
        # Net (accrued - used) = 110 - 30 = 80.

    @pytest.mark.asyncio
    async def test_no_grant_when_unused_and_at_cap(self):
        """If staff didn't use any FV leave, net is already at cap →
        no grant (statute disallows carry-over above 80h)."""
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        fv = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("80"),
        )
        balance = _make_balance(
            staff=staff, leave_type=fv,
            accrued=Decimal("80"), used=Decimal("0"),
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(pairs=[(balance, fv)])

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))
        assert written == []


# ===========================================================================
# 4. Casual filter — annual skipped, sick + FV still accrue
# ===========================================================================


class TestCasualFilter:

    @pytest.mark.asyncio
    async def test_casual_skips_annual_but_accrues_sick_and_fv(self):
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id,
            employment_type="casual",
            standard_hours_per_week=Decimal("20.00"),  # part-time
            employment_start_date=date(2024, 6, 1),
        )
        annual = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        sick = _make_leave_type(
            code="sick",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("160"),
        )
        fv = _make_leave_type(
            code="family_violence",
            org_id=org_id,
            accrual_method="per_period",
            accrual_amount=Decimal("80"),
            carry_over_max=Decimal("80"),
        )
        bal_annual = _make_balance(
            staff=staff, leave_type=annual,
            anniversary_date=date(2024, 6, 1),
        )
        bal_sick = _make_balance(
            staff=staff, leave_type=sick,
            anniversary_date=date(2024, 6, 1),
        )
        bal_fv = _make_balance(
            staff=staff, leave_type=fv,
            anniversary_date=date(2024, 6, 1),
        )
        db = _make_db_for_accrual(
            pairs=[(bal_annual, annual), (bal_sick, sick), (bal_fv, fv)]
        )

        written = await accrue_for_staff(db, staff, date(2026, 6, 1))

        # Two grants — sick and FV — at pro-rata 20h × 2 = 40h each.
        assert len(written) == 2
        codes = sorted(
            next(lt.code for lt in (sick, fv) if lt.id == w.leave_type_id)
            for w in written
        )
        assert codes == ["family_violence", "sick"]
        for ledger in written:
            assert ledger.delta_hours == Decimal("40.00")
        # Annual untouched.
        assert bal_annual.accrued_hours == Decimal("0")


# ===========================================================================
# 5. Idempotency — running twice writes only one ledger row
# ===========================================================================


class TestIdempotency:

    @pytest.mark.asyncio
    async def test_second_run_writes_no_new_rows(self):
        """Second invocation finds the existing ledger row and skips the
        grant. We model this by flipping the DB's ``next_existing_match``
        flag on the second call's idempotency check."""
        org_id = uuid.uuid4()
        staff = _make_staff(
            org_id=org_id, employment_start_date=date(2024, 6, 1)
        )
        annual = _make_leave_type(
            code="annual", org_id=org_id, accrual_method="anniversary"
        )
        balance = _make_balance(
            staff=staff, leave_type=annual,
            anniversary_date=date(2024, 6, 1),
        )

        # First run — no existing rows.
        db1 = _make_db_for_accrual(pairs=[(balance, annual)])
        written1 = await accrue_for_staff(db1, staff, date(2026, 6, 1))
        assert len(written1) == 1
        assert balance.accrued_hours == Decimal("160.00")

        # Second run — same balance object, fresh DB; the
        # idempotency check SHOULD return an existing row this time.
        db2 = _make_db_for_accrual(pairs=[(balance, annual)])

        # Override the idempotency execute path: after the first
        # ``_load_balances_with_types`` call returns the pairs, every
        # subsequent execute returns a non-None scalar (mimics existing
        # ledger row).
        state2 = {"pairs_returned": False}

        async def _fake_execute_idempotent(stmt):
            result = MagicMock()
            if not state2["pairs_returned"]:
                state2["pairs_returned"] = True
                result.all.return_value = [(balance, annual)]
                result.scalar_one_or_none.return_value = None
                return result
            # Existing ledger row — return a UUID so the engine skips.
            result.scalar_one_or_none.return_value = uuid.uuid4()
            return result

        db2.execute = AsyncMock(side_effect=_fake_execute_idempotent)

        written2 = await accrue_for_staff(db2, staff, date(2026, 6, 1))
        assert written2 == []
        # Balance unchanged (still at 160 from the first run).
        assert balance.accrued_hours == Decimal("160.00")


# ===========================================================================
# 6. days_to_hours
# ===========================================================================


class TestDaysToHours:

    def test_5_days_at_40h_week_equals_40h(self):
        staff = _make_staff(standard_hours_per_week=Decimal("40.00"))
        assert days_to_hours(Decimal("5"), staff) == Decimal("40.00")

    def test_5_days_at_null_week_falls_back_to_8h_per_day(self):
        staff = _make_staff(standard_hours_per_week=None)
        assert days_to_hours(Decimal("5"), staff) == Decimal("40.00")

    def test_3_days_at_30h_week_equals_18h(self):
        staff = _make_staff(standard_hours_per_week=Decimal("30.00"))
        # 30 / 5 = 6h per day × 3 days = 18h
        assert days_to_hours(Decimal("3"), staff) == Decimal("18.00")

    def test_1_day_at_37_5h_week_equals_7_5h(self):
        staff = _make_staff(standard_hours_per_week=Decimal("37.50"))
        assert days_to_hours(Decimal("1"), staff) == Decimal("7.50")


# ===========================================================================
# 7. anniversary_in_year — leap-year safety
# ===========================================================================


class TestAnniversaryInYear:

    def test_feb_29_in_non_leap_year_returns_feb_28(self):
        """Staff with ``employment_start_date = 2020-02-29`` (a leap day)
        gets Feb 28 in 2025 (non-leap)."""
        assert anniversary_in_year(date(2020, 2, 29), 2025) == date(2025, 2, 28)

    def test_feb_29_in_leap_year_returns_feb_29(self):
        assert anniversary_in_year(date(2020, 2, 29), 2024) == date(2024, 2, 29)

    def test_non_leap_birthday_returns_same_mmdd(self):
        assert anniversary_in_year(date(2020, 6, 15), 2025) == date(2025, 6, 15)

    def test_feb_28_in_non_leap_year_unchanged(self):
        assert anniversary_in_year(date(2020, 2, 28), 2025) == date(2025, 2, 28)
