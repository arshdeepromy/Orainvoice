"""Property-based test for ``StaffService.get_staff_month_stats`` Hours_Logged.

Covers task **2.2** from ``.kiro/specs/staff-redesign/tasks.md``.

**Property 1: Hours_Logged sums completed in-month worked minutes**

*For any* set of ``time_clock_entries`` for a staff member,
``get_staff_month_stats`` SHALL return ``hours_logged`` equal to
``SUM(worked_minutes) / 60`` over exactly the entries whose
``clock_out_at`` is non-null and whose ``clock_in_at`` falls within
This_Month, and SHALL set ``hours_logged.has_data`` to false (value
rendered as "—") when no such entries exist.

**Feature: staff-redesign, Property 1**

**Validates: Requirements 11.2, 12.2**

Hypothesis generates a mix of clock entries that are in/out of the
current month, completed/open, and with varying (or NULL) worked
minutes. The entries are seeded into the real Postgres instance in the
dev compose stack (Hypothesis tests in this codebase run against the
real DB — see ``tests/property/test_leave_balance_invariants.py`` and
``tests/test_invoice_vehicle_fk_preservation.py``). A deterministic
``now`` is injected and the org timezone is pinned to UTC so the
month-boundary calculation is fully controlled; the org-timezone
behaviour is exercised separately by Property 5 (task 2.6).

Run via: ``docker compose exec app python -m pytest \
tests/property/test_staff_month_stats_hours_logged.py``.
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

# Pre-import the model modules whose string-based relationship targets
# would otherwise fail to resolve when SQLAlchemy initialises mappers.
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
from app.modules.staff.models import StaffMember
from app.modules.staff.service import StaffService
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

# worked_minutes is NULL while a shift is open and is set by the service
# at clock-out. We still allow NULL on completed entries to exercise the
# COALESCE(..., 0) path in the aggregate query.
_worked_minutes_strategy = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=600),
)


@st.composite
def _entry_spec(draw) -> dict:
    """One generated clock entry.

    ``in_month`` — clock_in_at inside the current month vs outside.
    ``completed`` — clock_out_at non-null (counted) vs null (excluded).
    ``worked_minutes`` — set value or NULL.
    """
    in_month = draw(st.booleans())
    completed = draw(st.booleans())
    worked_minutes = draw(_worked_minutes_strategy)

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

    clock_out_at = clock_in_at + timedelta(hours=1) if completed else None

    return {
        "in_month": in_month,
        "completed": completed,
        "worked_minutes": worked_minutes,
        "clock_in_at": clock_in_at,
        "clock_out_at": clock_out_at,
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
        name=f"Hours Logged Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"Hours Logged Org {uuid.uuid4().hex[:6]}",
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
        for table in (
            "time_clock_entries",
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


def _make_entry(
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    spec: dict,
) -> TimeClockEntry:
    """Build a TimeClockEntry from a generated spec.

    ``source='admin_manual'`` avoids the kiosk-photo CHECK constraint.
    """
    return TimeClockEntry(
        id=uuid.uuid4(),
        org_id=org_id,
        staff_id=staff_id,
        clock_in_at=spec["clock_in_at"],
        clock_out_at=spec["clock_out_at"],
        source="admin_manual",
        worked_minutes=spec["worked_minutes"],
        break_minutes=0,
        flags={},
    )


# ===========================================================================
# Property 1 — Hours_Logged
# ===========================================================================


class TestHoursLoggedProperty:
    """**Feature: staff-redesign, Property 1**

    Hours_Logged equals ``SUM(worked_minutes) / 60`` over the completed
    in-month entries, and ``has_data`` is false when there are none.

    **Validates: Requirements 11.2, 12.2**
    """

    @PBT_SETTINGS
    @given(entries=_entries_strategy)
    @pytest.mark.asyncio
    async def test_hours_logged_sums_completed_in_month_minutes(
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

            # Seed the generated entries for the target staff member.
            for spec in entries:
                session.add(
                    _make_entry(org_id=org_id, staff_id=staff_id, spec=spec)
                )

            # Scoping noise: a completed in-month entry for ANOTHER staff
            # member that must NOT be counted toward the target's hours.
            session.add(
                _make_entry(
                    org_id=org_id,
                    staff_id=other_staff_id,
                    spec={
                        "clock_in_at": MONTH_START + timedelta(days=5),
                        "clock_out_at": MONTH_START + timedelta(days=5, hours=1),
                        "worked_minutes": 480,
                    },
                )
            )
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            # Reference computation over exactly the completed in-month
            # entries for the target staff member.
            counted = [
                spec
                for spec in entries
                if spec["completed"] and spec["in_month"]
            ]
            total_minutes = sum(
                (spec["worked_minutes"] or 0) for spec in counted
            )
            expected_hours = Decimal(total_minutes) / Decimal(60)
            expected_has_data = len(counted) > 0

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(
                org_id, staff_id, now=NOW,
            )

            assert stats.hours_logged == expected_hours, (
                f"hours_logged {stats.hours_logged} != expected "
                f"{expected_hours} (counted={len(counted)} entries, "
                f"total_minutes={total_minutes})"
            )
            assert stats.hours_logged_has_data is expected_has_data, (
                f"has_data {stats.hours_logged_has_data} != expected "
                f"{expected_has_data} (counted={len(counted)} entries)"
            )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()
