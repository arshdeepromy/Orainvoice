"""Property-based test for ``StaffService.get_staff_month_stats`` Jobs_Completed.

Covers task **2.3** from ``.kiro/specs/staff-redesign/tasks.md``.

**Property 2: Jobs_Completed counts assigned completed/invoiced cards in-month**

*For any* set of ``job_cards``, ``get_staff_month_stats`` SHALL return
``jobs_completed`` equal to the count of cards where ``assigned_to`` is the
staff member, ``status`` is in (``completed``, ``invoiced``), and
``updated_at`` falls within This_Month.

**Feature: staff-redesign, Property 2**

**Validates: Requirements 11.3**

Hypothesis generates a mix of job cards that are assigned to the target
staff member vs another staff member, with a status in/out of the
completed/invoiced set, and an ``updated_at`` in/out of the current
month. The cards are seeded into the real Postgres instance in the dev
compose stack (Hypothesis tests in this codebase run against the real
DB — see ``tests/property/test_staff_month_stats_hours_logged.py``). A
deterministic ``now`` is injected and the org timezone is pinned to UTC
so the month-boundary calculation is fully controlled; the org-timezone
behaviour is exercised separately by Property 5 (task 2.6).

Run via: ``docker compose exec -T app python -m pytest \
tests/property/test_staff_month_stats_jobs_completed.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.job_cards.models import JobCard
from app.modules.staff.models import StaffMember
from app.modules.staff.service import StaffService


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
# updated_at timestamps strictly inside [MONTH_START, MONTH_END).
_IN_MONTH_MAX_OFFSET = 30 * 24 * 60 - 1

# The five valid job-card statuses (per the ck_job_cards_status CHECK
# constraint). Only completed/invoiced count toward Jobs_Completed.
_STATUSES = ("open", "in_progress", "awaiting_parts", "completed", "invoiced")
_COMPLETED_STATUSES = ("completed", "invoiced")


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
def _card_spec(draw) -> dict:
    """One generated job card.

    ``assigned_target`` — assigned to the target staff vs another staff.
    ``status`` — any of the five valid statuses (only completed/invoiced
    count).
    ``in_month`` — updated_at inside the current month vs outside.
    """
    assigned_target = draw(st.booleans())
    status = draw(st.sampled_from(_STATUSES))
    in_month = draw(st.booleans())

    if in_month:
        offset = draw(st.integers(min_value=0, max_value=_IN_MONTH_MAX_OFFSET))
        updated_at = MONTH_START + timedelta(minutes=offset)
    else:
        # Either before the month (May 2026) or after it (July 2026).
        after = draw(st.booleans())
        offset = draw(st.integers(min_value=1, max_value=30 * 24 * 60))
        if after:
            updated_at = MONTH_END + timedelta(minutes=offset)
        else:
            updated_at = MONTH_START - timedelta(minutes=offset)

    return {
        "assigned_target": assigned_target,
        "status": status,
        "in_month": in_month,
        "updated_at": updated_at,
    }


_cards_strategy = st.lists(_card_spec(), min_size=0, max_size=12)


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
    """Create plan + org (UTC timezone) + a user + a customer + two staff.

    A ``customer`` and ``user`` are required to satisfy the JobCard
    ``customer_id`` (NOT NULL) and ``created_by`` (NOT NULL) FKs. A second
    staff member is created so seeded "noise" cards verify the metric is
    correctly scoped to a single ``staff_id``.
    """
    plan = SubscriptionPlan(
        name=f"Jobs Completed Plan {uuid.uuid4().hex[:6]}",
        monthly_price_nzd=0,
        user_seats=10,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org = Organisation(
        name=f"Jobs Completed Org {uuid.uuid4().hex[:6]}",
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

    # JobCard.created_by → users.id (NOT NULL).
    user = User(
        org_id=org.id,
        email=f"jobs-completed-{uuid.uuid4().hex[:8]}@example.test",
        first_name="Creator",
        last_name="User",
        role="org_admin",
        is_active=True,
    )
    session.add(user)

    # JobCard.customer_id → customers.id (NOT NULL).
    customer = Customer(
        org_id=org.id,
        customer_type="individual",
        first_name="Job",
        last_name="Customer",
    )
    session.add(customer)

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
        "user_id": user.id,
        "customer_id": customer.id,
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


def _make_card(
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    created_by: uuid.UUID,
    assigned_to: uuid.UUID,
    status: str,
    updated_at: datetime,
) -> JobCard:
    """Build a JobCard with an explicit ``updated_at``.

    ``updated_at`` is set explicitly so it overrides the column's
    ``server_default`` on INSERT, letting the strategy place the card
    in/out of the current month deterministically. We never UPDATE the
    row, so the column's ``onupdate=func.now()`` never fires.
    """
    return JobCard(
        id=uuid.uuid4(),
        org_id=org_id,
        customer_id=customer_id,
        created_by=created_by,
        assigned_to=assigned_to,
        status=status,
        updated_at=updated_at,
    )


# ===========================================================================
# Property 2 — Jobs_Completed
# ===========================================================================


class TestJobsCompletedProperty:
    """**Feature: staff-redesign, Property 2**

    Jobs_Completed equals the count of job cards assigned to the target
    staff member with a completed/invoiced status whose ``updated_at`` is
    in-month.

    **Validates: Requirements 11.3**
    """

    @PBT_SETTINGS
    @given(cards=_cards_strategy)
    @pytest.mark.asyncio
    async def test_jobs_completed_counts_assigned_completed_in_month(
        self, cards: list[dict],
    ) -> None:
        session, engine = await _make_session()
        fixtures: dict = {}
        try:
            fixtures = await _create_fixtures(session)
            org_id = fixtures["org_id"]
            customer_id = fixtures["customer_id"]
            created_by = fixtures["user_id"]
            staff_id = fixtures["staff_id"]
            other_staff_id = fixtures["other_staff_id"]
            await _set_rls_org_id(session, str(org_id))

            # Seed the generated cards, assigning each to the target or the
            # other staff member per its spec.
            for spec in cards:
                session.add(
                    _make_card(
                        org_id=org_id,
                        customer_id=customer_id,
                        created_by=created_by,
                        assigned_to=(
                            staff_id if spec["assigned_target"] else other_staff_id
                        ),
                        status=spec["status"],
                        updated_at=spec["updated_at"],
                    )
                )

            # Scoping noise: a completed in-month card assigned to ANOTHER
            # staff member that must NOT be counted for the target.
            session.add(
                _make_card(
                    org_id=org_id,
                    customer_id=customer_id,
                    created_by=created_by,
                    assigned_to=other_staff_id,
                    status="completed",
                    updated_at=MONTH_START + timedelta(days=5),
                )
            )
            await session.commit()
            await _set_rls_org_id(session, str(org_id))

            # Reference computation over exactly the cards assigned to the
            # target with a completed/invoiced status whose updated_at is
            # in-month.
            expected = sum(
                1
                for spec in cards
                if spec["assigned_target"]
                and spec["status"] in _COMPLETED_STATUSES
                and spec["in_month"]
            )

            svc = StaffService(session)
            stats = await svc.get_staff_month_stats(
                org_id, staff_id, now=NOW,
            )

            assert stats.jobs_completed == expected, (
                f"jobs_completed {stats.jobs_completed} != expected "
                f"{expected} (cards={len(cards)})"
            )
        finally:
            await _cleanup(session, fixtures)
            await session.close()
            await engine.dispose()
