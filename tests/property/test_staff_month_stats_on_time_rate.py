"""Property-based test for ``StaffService.get_staff_month_stats`` On_Time_Rate.

Covers task **2.5** from ``.kiro/specs/staff-redesign/tasks.md``.

**Property 4: On_Time_Rate counts only scheduled clock-ins within grace**

*For any* set of ``time_clock_entries`` for a staff member,
``get_staff_month_stats`` SHALL return ``on_time_rate`` equal to
``round(on_time / scheduled * 100)`` where the denominator is the count
of in-month clock-ins (by ``clock_in_at``) carrying a non-null
``scheduled_entry_id`` and the numerator counts those whose
``clock_in_at <= schedule_entries.start_time + 5 minutes``
(``ON_TIME_GRACE``). Unscheduled entries (null ``scheduled_entry_id``)
SHALL be excluded from the denominator, and ``on_time_rate.has_data``
SHALL be false (rendered "—") when there are no scheduled in-month
entries.

**Feature: staff-redesign, Property 4**

**Validates: Requirements 11.5, 11.6, 12.4**

Hypothesis generates a mix of clock entries that are in/out of the
current month, scheduled/unscheduled, and — for scheduled entries — with
a controlled gap between ``clock_in_at`` and the linked
``schedule_entries.start_time`` so that on-time vs late-beyond-grace is
deterministic. The entries are seeded into the real Postgres instance in
the dev compose stack (Hypothesis tests in this codebase run against the
real DB — see ``tests/property/test_staff_month_stats_hours_logged.py``).
A deterministic ``now`` is injected and the org timezone is pinned to UTC
so the month-boundary calculation is fully controlled; the org-timezone
behaviour is exercised separately by Property 5 (task 2.6).

The reference ratio uses the SAME rounding as the service
(``int(round(Decimal(on_time) / Decimal(scheduled) * 100))`` — Python
banker's rounding) so the two never disagree at a .5 boundary.

Run via: ``docker compose exec -T app python -m pytest \
tests/property/test_staff_month_stats_on_time_rate.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings as h_settings
from hypothesis import strategies as st
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
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.staff.service import ON_TIME_GRACE, StaffService
from app.modules.time_clock.models import TimeClockEntry


# ---------------------------------------------------------------------------
# Deterministic month window
# ---------------------------------------------------------------------------

# Injected "now" — fixed so the month is June 2026. The org timezone is
# pinned to UTC (see fixtures) so [month_start, month_end) is exactly
# [2026-06-01, 2026-07-01) in UTC.
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
MONTH_START = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
MONTH_END = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

# Grace window applied to scheduled clock-ins (5 minutes); imported from
# the service so the test tracks any future change to the constant.
_GRACE_MINUTES = int(ON_TIME_GRACE.total_seconds() // 60)

# Minutes in June (30 days) minus one minute — keeps generated in-month
# clock-ins strictly inside [MONTH_START, MONTH_END).
_IN_MONTH_MAX_OFFSET = 30 * 24 * 60 - 1


# ---------------------------------------------------------------------------
# Hypothesis configuration
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        # Each example provisions a fresh org / staff and runs a
        # sequence of async DB calls; the function-scoped-fixture
        # health check would otherwise block the run.
        HealthCheck.function_scoped_fixture,
    ],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def _entry_spec(draw) -> dict:
    """One generated clock entry.

    ``in_month`` — clock_in_at inside the current month vs outside (the
        in-month filter is on ``clock_in_at``, not the schedule start).
    ``scheduled`` — has a linked ``schedule_entry`` (counted in the
        denominator) vs unscheduled / null ``scheduled_entry_id``
        (excluded).
    ``gap_minutes`` — only relevant when ``scheduled``: the offset
        ``clock_in_at - schedule_entry.start_time`` in minutes. The entry
        is "on time" iff this gap is ``<= _GRACE_MINUTES``. Negative
        values mean the staff member clocked in early.
    """
    in_month = draw(st.booleans())
    scheduled = draw(st.booleans())
    # Span well below and above the grace boundary, including the exact
    # boundary (== grace, still on time) and just over it (late).
    gap_minutes = draw(st.integers(min_value=-120, max_value=120))

    if in_month:
        offset = draw(st.integers(min_value=0, max_value=_IN_MONTH_MAX_OFFSET))
        clock_in_at = MONTH_START + timedelta(minutes=offset)
    else:
        # Either before the month (May 2026) or after it (July 2026).
        after = draw(st.booleans())
        offset = draw(st.integers(min_value=1, max_value=30 * 24 * 60))
        if after:
            clock_in_at = MONTH_END + timedelta(minutes=offset)
        else:
            clock_in_at = MONTH_START - timedelta(minutes=offset)

    return {
        "in_month": in_month,
        "scheduled": scheduled,
        "gap_minutes": gap_minutes,
        "clock_in_at": clock_in_at,
    }


_entries_strategy = st.lists(_entry_spec(), min_size=0, max_size=12)


# ---------------------------------------------------------------------------
# Per-example engine + fixtures
# ---------------------------------------------------------------------------


async def _make_session() -> tuple[AsyncSession, "AsyncEngine"]:
    """Build a fresh engine + session per Hypothesis example."""
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


async def _create_fixtures(session: AsyncSession) -> dict:
    """Create plan + org (UTC timezone) + two staff members.

    A second staff member is created so seeded "noise" entries verify the
    metric is correctly scoped to a single ``staff_id``.
    """
    plan = SubscriptionPlan(
        name=f"On Time Rate Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"On Time Rate Org {uuid.uuid4().hex[:6]}",
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

    staff = StaffMember(
        org_id=org.id,
        name="Target Staff",
        first_name="Target",
        last_name="Staff",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
    )
    other_staff = StaffMember(
        org_id=org.id,
        name="Noise Staff",
        first_name="Noise",
        last_name="Staff",
        role_type="employee",
        is_active=True,
        availability_schedule={},
        skills=[],
    )
    session.add(staff)
    session.add(other_staff)
    await session.flush()
    await session.commit()

    return {
        "plan_id": plan.id,
        "org_id": org.id,
        "staff_id": staff.id,
        "other_staff_id": other_staff.id,
    }


async def _cleanup(session: AsyncSession, fixtures: dict) -> None:
    """Delete every row created for this example (child tables first)."""
    org_id = fixtures.get("org_id")
    plan_id = fixtures.get("plan_id")
    if not org_id:
        return
    try:
        await _set_rls_org_id(session, None)
        # time_clock_entries references schedule_entries via
        # scheduled_entry_id, so the clock entries must be deleted first.
        for table in (
            "time_clock_entries",
            "schedule_entries",
            "staff_members",
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


def _make_schedule_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    start_time: datetime,
) -> ScheduleEntry:
    """Build a ScheduleEntry with a known ``start_time``.

    Only the NOT NULL columns (org_id, staff_id, start_time, end_time)
    are populated; ``entry_type`` / ``status`` fall back to their model
    defaults.
    """
    return ScheduleEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        start_time=start_time,
        end_time=start_time + timedelta(hours=1),
    )


def _make_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    clock_in_at: datetime,
    scheduled_entry_id: uuid.UUID | None,
) -> TimeClockEntry:
    """Build a TimeClockEntry.

    ``source='admin_manual'`` avoids the kiosk-photo CHECK constraint.
    """
    return TimeClockEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=clock_in_at,
        clock_out_at=clock_in_at + timedelta(hours=1),
        source="admin_manual",
        scheduled_entry_id=scheduled_entry_id,
        break_minutes=0,
        flags={},
    )


# ===========================================================================
# Property 4 — On_Time_Rate
# ===========================================================================


class TestOnTimeRateProperty:
    """**Feature: staff-redesign, Property 4**

    On_Time_Rate equals ``round(on_time / scheduled * 100)`` over the
    in-month clock-ins with a non-null ``scheduled_entry_id`` (unscheduled
    entries excluded), where on-time means ``clock_in_at <= start_time +
    5min``; ``has_data`` is false when there are no scheduled in-month
    entries.

    **Validates: Requirements 11.5, 11.6, 12.4**
    """

    @PBT_SETTINGS
    @given(entries=_entries_strategy)
    @pytest.mark.asyncio
    async def test_on_time_rate_counts_only_scheduled_within_grace(
        self, entries: list[dict],
    ) -> None:
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            org_id = fixtures["org_id"]
            staff_id = fixtures["staff_id"]
            other_staff_id = fixtures["other_staff_id"]
            await _set_rls_org_id(session, str(org_id))

            # Seed the generated entries for the target staff member. For
            # scheduled specs, create a linked ScheduleEntry whose
            # start_time is offset from clock_in_at by ``gap_minutes`` so
            # on-time vs late is deterministic.
            for spec in entries:
                sched_id: uuid.UUID | None = None
                if spec["scheduled"]:
                    start_time = spec["clock_in_at"] - timedelta(
                        minutes=spec["gap_minutes"]
                    )
                    sched = _make_schedule_entry(
                        org_id=org_id,
                        staff_id=staff_id,
                        start_time=start_time,
                    )
                    session.add(sched)
                    sched_id = sched.id
                session.add(
                    _make_entry(
                        org_id=org_id,
                        staff_id=staff_id,
                        clock_in_at=spec["clock_in_at"],
                        scheduled_entry_id=sched_id,
                    )
                )

            # Scoping noise: an in-month, scheduled, on-time entry for
            # ANOTHER staff member that must NOT count toward the target.
            noise_sched = _make_schedule_entry(
                org_id=org_id,
                staff_id=other_staff_id,
                start_time=MONTH_START + timedelta(days=5),
            )
            session.add(noise_sched)
            session.add(
                _make_entry(
                    org_id=org_id,
                    staff_id=other_staff_id,
                    clock_in_at=MONTH_START + timedelta(days=5),
                    scheduled_entry_id=noise_sched.id,
                )
            )
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            # Reference computation over exactly the in-month, scheduled
            # entries for the target staff member.
            scheduled_specs = [
                spec
                for spec in entries
                if spec["in_month"] and spec["scheduled"]
            ]
            scheduled_count = len(scheduled_specs)
            on_time_count = sum(
                1
                for spec in scheduled_specs
                if spec["gap_minutes"] <= _GRACE_MINUTES
            )

            if scheduled_count > 0:
                expected_rate = int(
                    round(
                        Decimal(on_time_count)
                        / Decimal(scheduled_count)
                        * 100
                    )
                )
                expected_has_data = True
            else:
                expected_rate = 0
                expected_has_data = False

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(
                org_id, staff_id, now=NOW,
            )

            assert stats.on_time_rate == expected_rate, (
                f"on_time_rate {stats.on_time_rate} != expected "
                f"{expected_rate} (on_time={on_time_count}, "
                f"scheduled={scheduled_count})"
            )
            assert stats.on_time_rate_has_data is expected_has_data, (
                f"has_data {stats.on_time_rate_has_data} != expected "
                f"{expected_has_data} (scheduled={scheduled_count})"
            )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()
