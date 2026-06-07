"""Unit / example tests for ``StaffService.get_staff_month_stats``.

Covers task **2.7** from ``.kiro/specs/staff-redesign/tasks.md``.

These are plain example-based async tests (NOT Hypothesis property tests).
They pin down the concrete behaviours that the Property tests (2.2–2.6)
describe in the abstract:

1. **Last_Sign_In + User_Role (R11.8, R9.4)** — three linked-user cases:
   - a linked user with a non-null ``last_login_at`` returns that
     timestamp and the user's role;
   - a linked user with a null ``last_login_at`` returns ``None`` for the
     timestamp but still returns the role;
   - no linked user (``staff.user_id is None``) returns ``None`` for both.

2. **Fully-populated fixture (R11.2–R11.6, R12.2–R12.4)** — one staff
   member seeded with completed in-month clock entries (known worked
   minutes), completed/invoiced in-month job cards, in-month time entries
   (a billable/non-billable mix), and scheduled in-month clock-ins
   (on-time and late) so all four metrics compute exact, known values
   with every ``has_data`` flag True, plus last sign-in and user role.

3. **All-empty fixture (R12.2–R12.4)** — a staff member with no clock
   entries, no job cards, no time entries, and no schedules: Hours_Logged,
   Billable_Ratio, and On_Time_Rate all carry ``has_data=False`` while
   Jobs_Completed is a true zero (``has_data=True``, value ``0``).

The fixtures are seeded into the real Postgres instance in the dev compose
stack (the staff-month-stats tests in this codebase run against the real
DB — see ``tests/property/test_staff_month_stats_hours_logged.py``). A
deterministic ``now`` is injected and the org timezone is pinned to UTC so
the month-boundary calculation is fully controlled; the org-timezone
behaviour is exercised separately by Property 5 (task 2.6).

Run via: ``docker compose exec -T app python -m pytest \
tests/property/test_staff_month_stats_examples.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Pre-import the full set of model modules so SQLAlchemy can resolve all
# string-based relationship references when ``configure_mappers()`` runs.
# Mirrors the import block in ``app/main.py`` that runs at app startup.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.invoices import attachment_models as _invoice_attachment_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.time_clock import models as _time_clock_models  # noqa: F401
from app.modules.scheduling_v2 import models as _scheduling_v2_models  # noqa: F401
from app.modules.time_tracking_v2 import models as _time_tracking_v2_models  # noqa: F401
from app.modules.payslips import models as _payslips_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401

from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.config import settings
from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.job_cards.models import JobCard
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.staff.service import ON_TIME_GRACE, StaffService
from app.modules.time_clock.models import TimeClockEntry
from app.modules.time_tracking_v2.models import TimeEntry


# ---------------------------------------------------------------------------
# Deterministic month window
# ---------------------------------------------------------------------------

# Injected "now" — fixed so the month is June 2026. The org timezone is
# pinned to UTC (see fixtures) so [month_start, month_end) is exactly
# [2026-06-01, 2026-07-01) in UTC.
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
MONTH_START = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)

# A known last-sign-in timestamp used by the linked-user example.
LAST_LOGIN_AT = datetime(2026, 6, 10, 9, 30, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Per-example engine + fixtures
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, "AsyncEngine"]:
    """Build a fresh engine + session for one test."""
    test_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    return factory(), test_engine


async def _create_org(session: AsyncSession, label: str) -> dict:
    """Create a plan + org (UTC timezone) and return their ids."""
    plan = SubscriptionPlan(
        name=f"{label} Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"{label} Org {uuid.uuid4().hex[:6]}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        settings={},
        # Pin to UTC so the month window is deterministic; the org-tz
        # behaviour is covered by Property 5 (task 2.6).
        timezone="UTC",
    )
    session.add(org)
    await session.flush()
    await _set_rls_org_id(session, str(org.id))

    return {"plan_id": plan.id, "org_id": org.id}


def _make_staff(org_id: uuid.UUID, *, name: str, user_id: uuid.UUID | None = None) -> StaffMember:
    return StaffMember(
        org_id=org_id,
        user_id=user_id,
        name=name,
        first_name=name.split()[0],
        last_name=name.split()[-1] if len(name.split()) > 1 else None,
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
    )


def _make_user(
    org_id: uuid.UUID,
    *,
    role: str = "org_admin",
    last_login_at: datetime | None,
) -> User:
    return User(
        org_id=org_id,
        email=f"staff-stats-{uuid.uuid4().hex[:8]}@example.test",
        first_name="Linked",
        last_name="User",
        role=role,
        is_active=True,
        last_login_at=last_login_at,
    )


def _make_clock_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    clock_in_at: datetime,
    worked_minutes: int | None,
    scheduled_entry_id: uuid.UUID | None = None,
) -> TimeClockEntry:
    """Build a completed TimeClockEntry.

    ``source='admin_manual'`` avoids the kiosk-photo CHECK constraint.
    """
    return TimeClockEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=clock_in_at,
        clock_out_at=clock_in_at + timedelta(hours=1),
        source="admin_manual",
        worked_minutes=worked_minutes,
        scheduled_entry_id=scheduled_entry_id,
        break_minutes=0,
        flags={},
    )


def _make_schedule_entry(
    *, org_id: uuid.UUID, staff_id: uuid.UUID, start_time: datetime,
) -> ScheduleEntry:
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=start_time,
        end_time=start_time + timedelta(hours=1),
    )


def _make_time_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    start_time: datetime,
    duration_minutes: int,
    is_billable: bool,
) -> TimeEntry:
    return TimeEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        user_id=uuid.uuid4(),
        staff_id=staff_id,
        start_time=start_time,
        duration_minutes=duration_minutes,
        is_billable=is_billable,
    )


def _make_job_card(
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    created_by: uuid.UUID,
    assigned_to: uuid.UUID,
    status: str,
    updated_at: datetime,
) -> JobCard:
    return JobCard(
        id=uuid.uuid4(),
        org_id=org_id,
        customer_id=customer_id,
        created_by=created_by,
        assigned_to=assigned_to,
        status=status,
        updated_at=updated_at,
    )


async def _cleanup(session: AsyncSession, org_id: uuid.UUID | None, plan_id: uuid.UUID | None) -> None:
    """Delete every row created for this test (child tables first)."""
    if not org_id:
        return
    try:
        await _set_rls_org_id(session, None)
        for table in (
            "time_clock_entries",
            "schedule_entries",
            "time_entries",
            "job_cards",
            "customers",
            "staff_members",
            "users",
            "organisations",
        ):
            await session.execute(
                sa_text(f"DELETE FROM {table} WHERE org_id = :oid"),
                {"oid": str(org_id)},
            )
        if plan_id:
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE id = :pid"),
                {"pid": str(plan_id)},
            )
        await session.commit()
    except Exception:
        await session.rollback()


# ===========================================================================
# Last_Sign_In + User_Role example cases (R11.8, R9.4)
# ===========================================================================


class TestLastSignInExamples:
    """Last_Sign_In and User_Role behaviour for the three linked-user cases.

    **Validates: Requirements 11.8, 9.4**
    """

    @pytest.mark.asyncio
    async def test_linked_user_with_timestamp_returns_it_and_role(self) -> None:
        """A linked user with a non-null ``last_login_at`` → that timestamp
        is returned and ``user_role`` equals the user's role."""
        session, engine = await _make_session()
        org_id = plan_id = None
        try:
            ids = await _create_org(session, "LastSignIn Has")
            org_id, plan_id = ids["org_id"], ids["plan_id"]

            user = _make_user(org_id, role="salesperson", last_login_at=LAST_LOGIN_AT)
            session.add(user)
            await session.flush()

            staff = _make_staff(org_id, name="Linked Staff", user_id=user.id)
            session.add(staff)
            await session.flush()
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(org_id, staff.id, now=NOW)

            assert stats.last_sign_in == LAST_LOGIN_AT
            assert stats.user_role == "salesperson"
        finally:
            await _cleanup(session, org_id, plan_id)
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_linked_user_with_null_login_returns_none_but_role(self) -> None:
        """A linked user with a null ``last_login_at`` → ``last_sign_in`` is
        None, but the role is still returned."""
        session, engine = await _make_session()
        org_id = plan_id = None
        try:
            ids = await _create_org(session, "LastSignIn Null")
            org_id, plan_id = ids["org_id"], ids["plan_id"]

            user = _make_user(org_id, role="staff_member", last_login_at=None)
            session.add(user)
            await session.flush()

            staff = _make_staff(org_id, name="Never Loggedin", user_id=user.id)
            session.add(staff)
            await session.flush()
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(org_id, staff.id, now=NOW)

            assert stats.last_sign_in is None
            assert stats.user_role == "staff_member"
        finally:
            await _cleanup(session, org_id, plan_id)
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_no_linked_user_returns_none_for_both(self) -> None:
        """No linked user (``staff.user_id is None``) → both ``last_sign_in``
        and ``user_role`` are None."""
        session, engine = await _make_session()
        org_id = plan_id = None
        try:
            ids = await _create_org(session, "LastSignIn None")
            org_id, plan_id = ids["org_id"], ids["plan_id"]

            staff = _make_staff(org_id, name="No Account", user_id=None)
            session.add(staff)
            await session.flush()
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(org_id, staff.id, now=NOW)

            assert stats.last_sign_in is None
            assert stats.user_role is None
        finally:
            await _cleanup(session, org_id, plan_id)
            await session.close()
            await engine.dispose()


# ===========================================================================
# Fully-populated fixture — exact values across all four metrics (R11, R12)
# ===========================================================================


class TestFullyPopulatedFixture:
    """A staff member seeded so all four metrics compute exact, known values
    with every ``has_data`` flag True, plus last sign-in and user role.

    Seeded data (all in June 2026, the deterministic ``NOW`` month):

    - **Clock entries (5 completed, in-month):** four scheduled — three
      on-time, one late — plus one unscheduled, each with
      ``worked_minutes=60``. → Hours_Logged = 300/60 = ``5.0``;
      On_Time_Rate = 3 on-time / 4 scheduled = ``75``%.
    - **Job cards (in-month):** two ``completed`` + one ``invoiced`` assigned
      to the staff member, plus one ``open`` (excluded). → Jobs_Completed = ``3``.
    - **Time entries (in-month):** billable 180 min + non-billable 60 min. →
      Billable_Ratio = 180/240 = ``75``%.
    - **Linked user:** ``last_login_at = LAST_LOGIN_AT``, ``role='org_admin'``.

    **Validates: Requirements 11.2, 11.3, 11.4, 11.5, 11.6, 11.8, 9.4,
    12.2, 12.3, 12.4**
    """

    @pytest.mark.asyncio
    async def test_fully_populated_exact_values(self) -> None:
        session, engine = await _make_session()
        org_id = plan_id = None
        try:
            ids = await _create_org(session, "Full")
            org_id, plan_id = ids["org_id"], ids["plan_id"]

            # Linked user for last-sign-in + role.
            user = _make_user(org_id, role="org_admin", last_login_at=LAST_LOGIN_AT)
            session.add(user)
            await session.flush()

            # Customer + creator user are needed for the job-card FKs.
            customer = Customer(
                org_id=org_id,
                customer_type="individual",
                first_name="Full",
                last_name="Customer",
            )
            session.add(customer)

            staff = _make_staff(org_id, name="Full Staff", user_id=user.id)
            session.add(staff)
            await session.flush()

            # --- Clock entries (Hours_Logged + On_Time_Rate) -------------
            # Three scheduled on-time entries: start_time == clock_in (gap 0).
            for day in (2, 3, 4):
                clock_in = MONTH_START + timedelta(days=day, hours=9)
                sched = _make_schedule_entry(
                    org_id=org_id, staff_id=staff.id, start_time=clock_in,
                )
                session.add(sched)
                session.add(
                    _make_clock_entry(
                        org_id=org_id,
                        staff_id=staff.id,
                        clock_in_at=clock_in,
                        worked_minutes=60,
                        scheduled_entry_id=sched.id,
                    )
                )
            # One scheduled LATE entry: clock-in is 10 min after start +
            # grace, so it is beyond the 5-min ON_TIME_GRACE window.
            late_clock_in = MONTH_START + timedelta(days=5, hours=9)
            late_start = late_clock_in - ON_TIME_GRACE - timedelta(minutes=10)
            late_sched = _make_schedule_entry(
                org_id=org_id, staff_id=staff.id, start_time=late_start,
            )
            session.add(late_sched)
            session.add(
                _make_clock_entry(
                    org_id=org_id,
                    staff_id=staff.id,
                    clock_in_at=late_clock_in,
                    worked_minutes=60,
                    scheduled_entry_id=late_sched.id,
                )
            )
            # One unscheduled completed entry: counts toward Hours_Logged but
            # is excluded from the On_Time_Rate denominator (R11.6).
            session.add(
                _make_clock_entry(
                    org_id=org_id,
                    staff_id=staff.id,
                    clock_in_at=MONTH_START + timedelta(days=6, hours=9),
                    worked_minutes=60,
                    scheduled_entry_id=None,
                )
            )

            # --- Job cards (Jobs_Completed) ------------------------------
            for status in ("completed", "invoiced", "completed"):
                session.add(
                    _make_job_card(
                        org_id=org_id,
                        customer_id=customer.id,
                        created_by=user.id,
                        assigned_to=staff.id,
                        status=status,
                        updated_at=MONTH_START + timedelta(days=7, hours=12),
                    )
                )
            # An open card (excluded from the completed/invoiced count).
            session.add(
                _make_job_card(
                    org_id=org_id,
                    customer_id=customer.id,
                    created_by=user.id,
                    assigned_to=staff.id,
                    status="open",
                    updated_at=MONTH_START + timedelta(days=7, hours=12),
                )
            )

            # --- Time entries (Billable_Ratio) ---------------------------
            session.add(
                _make_time_entry(
                    org_id=org_id,
                    staff_id=staff.id,
                    start_time=MONTH_START + timedelta(days=8, hours=10),
                    duration_minutes=180,
                    is_billable=True,
                )
            )
            session.add(
                _make_time_entry(
                    org_id=org_id,
                    staff_id=staff.id,
                    start_time=MONTH_START + timedelta(days=8, hours=14),
                    duration_minutes=60,
                    is_billable=False,
                )
            )

            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(org_id, staff.id, now=NOW)

            # Hours_Logged: 5 completed in-month entries × 60 min = 300 → 5.0h
            assert stats.hours_logged == Decimal(300) / Decimal(60)
            assert stats.hours_logged_has_data is True

            # Jobs_Completed: 2 completed + 1 invoiced = 3 (open excluded)
            assert stats.jobs_completed == 3
            assert stats.jobs_completed_has_data is True

            # Billable_Ratio: 180 / (180 + 60) * 100 = 75
            assert stats.billable_ratio == 75
            assert stats.billable_ratio_has_data is True

            # On_Time_Rate: 3 on-time / 4 scheduled * 100 = 75 (unscheduled
            # entry excluded from the denominator)
            assert stats.on_time_rate == 75
            assert stats.on_time_rate_has_data is True

            # Last sign-in + role from the linked user.
            assert stats.last_sign_in == LAST_LOGIN_AT
            assert stats.user_role == "org_admin"
        finally:
            await _cleanup(session, org_id, plan_id)
            await session.close()
            await engine.dispose()


# ===========================================================================
# All-empty fixture — has_data=false on hours/billable/on-time (R12)
# ===========================================================================


class TestAllEmptyFixture:
    """A staff member with no clock entries, no job cards, no time entries,
    and no schedules.

    Hours_Logged, Billable_Ratio, and On_Time_Rate carry ``has_data=False``;
    Jobs_Completed is a true zero (``has_data=True``, value ``0``) by design.

    **Validates: Requirements 12.2, 12.3, 12.4**
    """

    @pytest.mark.asyncio
    async def test_all_empty_has_data_false_on_three_metrics(self) -> None:
        session, engine = await _make_session()
        org_id = plan_id = None
        try:
            ids = await _create_org(session, "Empty")
            org_id, plan_id = ids["org_id"], ids["plan_id"]

            staff = _make_staff(org_id, name="Empty Staff", user_id=None)
            session.add(staff)
            await session.flush()
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(org_id, staff.id, now=NOW)

            # Hours_Logged: no completed clock entries → has_data False (R12.2)
            assert stats.hours_logged == Decimal(0)
            assert stats.hours_logged_has_data is False

            # Billable_Ratio: no logged time entries → has_data False (R12.3)
            assert stats.billable_ratio == 0
            assert stats.billable_ratio_has_data is False

            # On_Time_Rate: no scheduled clock-ins → has_data False (R12.4)
            assert stats.on_time_rate == 0
            assert stats.on_time_rate_has_data is False

            # Jobs_Completed: a true zero — has_data True by design.
            assert stats.jobs_completed == 0
            assert stats.jobs_completed_has_data is True

            # No linked user → both None.
            assert stats.last_sign_in is None
            assert stats.user_role is None
        finally:
            await _cleanup(session, org_id, plan_id)
            await session.close()
            await engine.dispose()
