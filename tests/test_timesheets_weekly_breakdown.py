"""DB-backed example tests for the timesheets weekly-breakdown review aid.

Feature: weekly-lens review aid for the OraInvoice Staff Timesheets.

Exercises ``compute_weekly_breakdown`` (Components → service.py) against the real
dev Postgres database, mirroring the DB-backed pattern in
``tests/test_payrun_independent_per_cycle_property.py`` and
``tests/test_materialisation_cycle_scoped_property.py`` (fresh async engine per
test, full ORM imports, a Branch for clock entries, everything rolled back).

These are example-style tests (not Hypothesis) asserting:

- A fortnightly period (2 ISO weeks) yields exactly 2 week buckets with the
  correct clamped date ranges and ``multi_week=True``.
- A staff member with clock entries in week 1 only shows minutes in week 1 and
  zero in week 2; the week totals sum correctly.
- A ``fixed`` working-arrangement staff member with no clock entries shows their
  schedule-derived rostered minutes per week.
- A weekly (single-week) period returns 1 bucket with ``multi_week=False``.

This feature is READ-ONLY — it never touches pay-run / materialisation /
payslip logic — so the tests seed ``timesheets`` + ``time_clock_entries`` rows
directly and only call ``compute_weekly_breakdown``.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests).
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.module_management import models as _module_mgmt_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.leave import models as _leave_models  # noqa: F401
from app.modules.time_clock import models as _time_clock_models  # noqa: F401
from app.modules.payslips import models as _payslip_models  # noqa: F401
from app.modules.timesheets import models as _timesheet_models  # noqa: F401
from app.modules.timesheets import pay_cycles as _pay_cycle_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.organisations.models import Branch
from app.modules.payslips.models import PayPeriod
from app.modules.staff.models import StaffMember
from app.modules.time_clock.models import TimeClockEntry
from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.service import compute_weekly_breakdown


# Fortnight: two whole ISO weeks. Mon 1 Jun 2026 .. Sun 14 Jun 2026.
_FORTNIGHT_START = date(2026, 6, 1)   # Monday
_FORTNIGHT_END = date(2026, 6, 14)    # Sunday
_WEEK1_START = date(2026, 6, 1)
_WEEK1_END = date(2026, 6, 7)
_WEEK2_START = date(2026, 6, 8)
_WEEK2_END = date(2026, 6, 14)
_PAY_DATE = date(2026, 6, 17)

# Single week: Mon 8 Jun .. Sun 14 Jun 2026.
_WEEKLY_START = date(2026, 6, 8)
_WEEKLY_END = date(2026, 6, 14)

# Mon–Fri 09:00–17:00 == 8h/day == 480 min/day == 2400 min/week.
_FIXED_SCHEDULE = {
    "monday": {"start": "09:00", "end": "17:00"},
    "tuesday": {"start": "09:00", "end": "17:00"},
    "wednesday": {"start": "09:00", "end": "17:00"},
    "thursday": {"start": "09:00", "end": "17:00"},
    "friday": {"start": "09:00", "end": "17:00"},
}


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_org_and_branch(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    plan = SubscriptionPlan(
        name=f"weekly_lens_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"weekly_lens_org_{uuid.uuid4().hex[:8]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={},
    )
    session.add(org)
    await session.flush()

    # New time_clock_entries rows require a branch_id (DB check constraint
    # ck_tce_branch_id_new_rows).
    branch = Branch(org_id=org.id, name="Test Branch", is_default=True)
    session.add(branch)
    await session.flush()
    return org.id, branch.id


async def _new_period(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    start: date,
    end: date,
) -> PayPeriod:
    period = PayPeriod(
        org_id=org_id,
        start_date=start,
        end_date=end,
        pay_date=_PAY_DATE,
        status="open",
    )
    session.add(period)
    await session.flush()
    return period


async def _new_staff(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    working_arrangement: str = "rostered",
    availability_schedule: dict | None = None,
) -> StaffMember:
    staff = StaffMember(
        org_id=org_id,
        name=name,
        first_name=name.split()[0],
        employment_type="permanent",
        working_arrangement=working_arrangement,
        availability_schedule=availability_schedule or {},
        is_active=True,
    )
    session.add(staff)
    await session.flush()
    return staff


async def _new_timesheet(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    period_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
) -> Timesheet:
    ts = Timesheet(
        org_id=org_id,
        staff_id=staff_id,
        pay_period_id=period_id,
        branch_id=branch_id,
        status="open",
    )
    session.add(ts)
    await session.flush()
    return ts


async def _new_clock_entry(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    branch_id: uuid.UUID,
    day: date,
    worked_minutes: int | None,
) -> None:
    session.add(
        TimeClockEntry(
            org_id=org_id,
            staff_id=staff_id,
            clock_in_at=datetime.combine(day, time(9, 0), tzinfo=timezone.utc),
            clock_out_at=datetime.combine(day, time(17, 0), tzinfo=timezone.utc),
            source="admin_manual",
            worked_minutes=worked_minutes,
            branch_id=branch_id,
        )
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Test 1: fortnight → 2 buckets, correct clamped ranges, multi_week True, and
#         a clock-source staff member shows in week 1 only.
# ---------------------------------------------------------------------------


async def _run_fortnight_clock_in_week1_only() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                period = await _new_period(
                    session, org_id=org_id,
                    start=_FORTNIGHT_START, end=_FORTNIGHT_END,
                )
                staff = await _new_staff(session, org_id=org_id, name="Clocker One")
                await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id,
                )
                # Two clock entries in week 1 (Mon + Tue), none in week 2.
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=date(2026, 6, 2), worked_minutes=480,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=date(2026, 6, 3), worked_minutes=300,
                )

                result = await compute_weekly_breakdown(
                    session, org_id=org_id, pay_period_id=period.id,
                )

                # Exactly two ISO-week buckets, multi_week True.
                assert result.multi_week is True
                assert len(result.weeks) == 2

                w1, w2 = result.weeks
                # Clamped ranges + 1-based week_index.
                assert w1.week_index == 1
                assert w1.start_date == _WEEK1_START
                assert w1.end_date == _WEEK1_END
                assert w2.week_index == 2
                assert w2.start_date == _WEEK2_START
                assert w2.end_date == _WEEK2_END
                # ISO week numbers are consecutive.
                assert w2.iso_week == w1.iso_week + 1

                # Week 1 carries the clock sum (480 + 300); week 2 is zero.
                assert w1.total_minutes == 780
                assert len(w1.staff) == 1
                assert w1.staff[0].staff_id == staff.id
                assert w1.staff[0].staff_name == "Clocker One"
                assert w1.staff[0].minutes == 780

                # Week 2 has no activity — bucket kept, but empty + zero total.
                assert w2.total_minutes == 0
                assert w2.staff == []

                # Totals sum across the period.
                assert sum(w.total_minutes for w in result.weeks) == 780
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_fortnight_two_buckets_clock_in_week1_only():
    """Fortnight → 2 clamped ISO-week buckets; clock-source staff in week 1 only.

    **Validates: weekly-lens — multi-week split + clock-source bucketing.**
    """
    asyncio.run(_run_fortnight_clock_in_week1_only())


# ---------------------------------------------------------------------------
# Test 2: fixed-arrangement staff with NO clock entries → schedule-derived
#         rostered minutes appear in EACH week.
# ---------------------------------------------------------------------------


async def _run_fixed_staff_schedule_per_week() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                period = await _new_period(
                    session, org_id=org_id,
                    start=_FORTNIGHT_START, end=_FORTNIGHT_END,
                )
                staff = await _new_staff(
                    session, org_id=org_id, name="Fixed Fred",
                    working_arrangement="fixed",
                    availability_schedule=_FIXED_SCHEDULE,
                )
                await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id,
                )
                # No clock entries at all → schedule is the source of truth.

                result = await compute_weekly_breakdown(
                    session, org_id=org_id, pay_period_id=period.id,
                )

                assert result.multi_week is True
                assert len(result.weeks) == 2

                # Mon–Fri 8h == 2400 min for each full ISO week.
                for week in result.weeks:
                    assert week.total_minutes == 2400
                    assert len(week.staff) == 1
                    assert week.staff[0].staff_id == staff.id
                    assert week.staff[0].minutes == 2400
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_fixed_staff_shows_schedule_minutes_per_week():
    """Fixed staff with no clock entries → schedule-derived minutes per week.

    **Validates: weekly-lens — fixed-arrangement fallback mirrors materialise.**
    """
    asyncio.run(_run_fixed_staff_schedule_per_week())


# ---------------------------------------------------------------------------
# Test 3: weekly (single-week) period → 1 bucket, multi_week False.
# ---------------------------------------------------------------------------


async def _run_single_week_period() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                period = await _new_period(
                    session, org_id=org_id,
                    start=_WEEKLY_START, end=_WEEKLY_END,
                )
                staff = await _new_staff(session, org_id=org_id, name="Weekly Wendy")
                await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=date(2026, 6, 9), worked_minutes=240,
                )

                result = await compute_weekly_breakdown(
                    session, org_id=org_id, pay_period_id=period.id,
                )

                assert result.multi_week is False
                assert len(result.weeks) == 1
                only = result.weeks[0]
                assert only.week_index == 1
                assert only.start_date == _WEEKLY_START
                assert only.end_date == _WEEKLY_END
                assert only.total_minutes == 240
                assert len(only.staff) == 1
                assert only.staff[0].minutes == 240
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_single_week_period_one_bucket_not_multi_week():
    """Weekly (single-week) period → 1 bucket, multi_week False.

    **Validates: weekly-lens — single-week periods are not multi-week.**
    """
    asyncio.run(_run_single_week_period())


# ---------------------------------------------------------------------------
# Test 4: NULL worked_minutes treated as 0, but the entry still counts as a
#         clock entry (so a fixed staff member's clock presence suppresses the
#         schedule fallback). Also a missing period returns an empty result.
# ---------------------------------------------------------------------------


async def _run_null_worked_and_missing_period() -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_id, branch_id = await _seed_org_and_branch(session)
                period = await _new_period(
                    session, org_id=org_id,
                    start=_FORTNIGHT_START, end=_FORTNIGHT_END,
                )
                # Fixed staff WITH a clock entry in week 1 (worked_minutes NULL).
                staff = await _new_staff(
                    session, org_id=org_id, name="Fixed Nullah",
                    working_arrangement="fixed",
                    availability_schedule=_FIXED_SCHEDULE,
                )
                await _new_timesheet(
                    session, org_id=org_id, staff_id=staff.id,
                    period_id=period.id, branch_id=branch_id,
                )
                await _new_clock_entry(
                    session, org_id=org_id, staff_id=staff.id, branch_id=branch_id,
                    day=date(2026, 6, 2), worked_minutes=None,
                )

                result = await compute_weekly_breakdown(
                    session, org_id=org_id, pay_period_id=period.id,
                )
                w1, w2 = result.weeks
                # Week 1: clock present (NULL -> 0) suppresses the schedule
                # fallback, so total is 0 and the zero-minute staff is omitted.
                assert w1.total_minutes == 0
                assert w1.staff == []
                # Week 2: no clock entries -> schedule fallback applies (2400).
                assert w2.total_minutes == 2400
                assert len(w2.staff) == 1
                assert w2.staff[0].minutes == 2400

                # A missing pay period returns an empty (non-multi-week) result.
                missing = await compute_weekly_breakdown(
                    session, org_id=org_id, pay_period_id=uuid.uuid4(),
                )
                assert missing.multi_week is False
                assert missing.weeks == []
            finally:
                await session.rollback()
    finally:
        await engine.dispose()


def test_null_worked_minutes_and_missing_period():
    """NULL worked_minutes counts as a clock entry (0 min); missing period empty.

    **Validates: weekly-lens — clock-presence rule + missing-period guard.**
    """
    asyncio.run(_run_null_worked_and_missing_period())
