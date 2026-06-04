"""Property-based tests for the SMS Usage report daily breakdown.

Feature: reports-remediation (C4 — SMS `daily_breakdown`).

Property 6 — SMS daily breakdown sums to the total sent:

  * Σ daily_breakdown[i].sms_count == total_sent

This is a real-DB property test: the property is a statement about the two
SQL aggregations inside ``get_sms_usage``. Both the period total (``total_sent``)
and the per-day series (``daily_breakdown``) are computed from the SAME two
sources under the SAME filters:

  * outbound ``sms_messages``                       (direction = 'outbound')
  * non-failed ``notification_log`` SMS rows        (channel = 'sms', status != 'failed')

filtered by ``created_at`` within the reporting period. The per-day series is
just the period total partitioned by calendar day (and zero-count days are
dropped, which does not change the sum). Therefore the day-buckets must
reconcile to the ungrouped period total.

For each Hypothesis example we seed an arbitrary message dataset (mixing
counted and uncounted rows, with ``created_at`` dates spanning before / inside /
after the period to exercise the date filter), run the service, and assert the
property. All inserts happen inside a transaction that is rolled back after
every example, so no test data persists.

The DB session time zone is pinned to UTC for each example so the daily
``created_at::date`` cast shares the same frame as the UTC period bounds used by
the total query — this makes the reconciliation exact at day boundaries.

**Validates: Requirements 9.2**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

import pytest
import pytest_asyncio
from hypothesis import given, settings as hyp_settings, strategies as st, HealthCheck
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Import ALL ORM models so SQLAlchemy can resolve string-based relationships.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.notifications import models as _notification_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401

from app.core.database import _set_rls_org_id
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.notifications.models import NotificationLog
from app.modules.sms_chat.models import SmsConversation, SmsMessage
from app.modules.reports.service import get_sms_usage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORG_NAME = "SMS Daily Breakdown PBT Org"
_PLAN_NAME = "SMS Daily Breakdown PBT Plan"

# Fixed reporting period for the property. created_at dates are generated across
# a wider window so some messages fall OUTSIDE the period (exercising the
# date-range filter shared by the total query and the daily query).
PERIOD_START = date(2024, 1, 1)
PERIOD_END = date(2024, 12, 31)

# Messages are timestamped at noon so they sit well clear of midnight; combined
# with the UTC session time zone the day-bucket cast is unambiguous.
_NOON = time(12, 0, 0)


# ---------------------------------------------------------------------------
# Hypothesis settings + strategies
# ---------------------------------------------------------------------------

PBT_SETTINGS = hyp_settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)

# Both message sources are generated. For each spec we vary the discriminating
# fields so the dataset mixes counted and uncounted rows:
#   * sms_messages   — counted only when direction == 'outbound'
#   * notification_log — counted only when channel == 'sms' AND status != 'failed'
# All ``notification_log`` statuses allowed by its CHECK constraint are sampled
# (including 'failed', which must be excluded).
message_spec_strategy = st.fixed_dictionaries({
    "source": st.sampled_from(["sms", "notif"]),
    "direction": st.sampled_from(["outbound", "inbound"]),
    "channel": st.sampled_from(["sms", "email"]),
    "status": st.sampled_from(
        ["queued", "sent", "delivered", "bounced", "opened", "failed"]
    ),
    # Spans ~4 months before to ~3 months after the period.
    "day": st.dates(min_value=date(2023, 9, 1), max_value=date(2025, 3, 31)),
})

dataset_strategy = st.lists(message_spec_strategy, min_size=0, max_size=15)


def _is_counted(spec: dict) -> bool:
    """Mirror the service's two-source, non-failed, in-period filter."""
    if not (PERIOD_START <= spec["day"] <= PERIOD_END):
        return False
    if spec["source"] == "sms":
        return spec["direction"] == "outbound"
    # notification_log
    return spec["channel"] == "sms" and spec["status"] != "failed"


# ---------------------------------------------------------------------------
# DB session helper
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, "object"]:
    """Create a fresh engine + session for the test run."""
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


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------

class TestP6SmsDailyBreakdown:
    """Property 6: Σ daily_breakdown[i].sms_count == total_sent, over arbitrary
    outbound-message datasets in range.

    **Validates: Requirements 9.2**
    """

    @pytest_asyncio.fixture(autouse=True)
    async def _org_fixtures(self):
        """Create a committed plan/org/conversation reused across examples, and
        tear them down (including any leaked messages) afterwards."""
        session, engine = await _make_session()
        try:
            async with session.begin():
                await _set_rls_org_id(session, None)

                plan = SubscriptionPlan(
                    name=_PLAN_NAME,
                    monthly_price_nzd=0,
                    user_seats=5,
                    storage_quota_gb=1,
                    carjam_lookups_included=0,
                    enabled_modules=[],
                )
                session.add(plan)
                await session.flush()

                org = Organisation(
                    name=_ORG_NAME,
                    plan_id=plan.id,
                    status="active",
                    storage_quota_gb=1,
                    settings={"gst_percentage": 15, "invoice_prefix": "SPBT-"},
                )
                session.add(org)
                await session.flush()

                conversation = SmsConversation(
                    org_id=org.id,
                    phone_number="+6421000000",
                    contact_name="SMS PBT",
                    last_message_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    last_message_preview="seed",
                )
                session.add(conversation)
                await session.flush()

                self.org_id = org.id
                self.conversation_id = conversation.id
        finally:
            await session.close()
            await engine.dispose()

        yield

        # Teardown — remove all data created under this org.
        session, engine = await _make_session()
        try:
            async with session.begin():
                await session.execute(sa_text(
                    "DELETE FROM notification_log WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM sms_messages WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM sms_conversations WHERE org_id IN "
                    "(SELECT id FROM organisations WHERE name = :n)"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM organisations WHERE name = :n"
                ), {"n": _ORG_NAME})
                await session.execute(sa_text(
                    "DELETE FROM subscription_plans WHERE name = :n"
                ), {"n": _PLAN_NAME})
        finally:
            await session.close()
            await engine.dispose()

    @pytest.mark.asyncio
    @PBT_SETTINGS
    @given(dataset=dataset_strategy)
    async def test_daily_breakdown_sums_to_total_sent(
        self, dataset: list[dict],
    ) -> None:
        """P6: the daily series reconciles to the period total."""
        session, engine = await _make_session()
        try:
            # Each example runs in its own transaction that is ALWAYS rolled
            # back (in the finally), so generated messages never persist.
            await session.begin()
            await _set_rls_org_id(session, str(self.org_id))
            # Pin the cast frame so created_at::date (daily query) shares the
            # UTC frame of the explicit UTC bounds used by the total query.
            await session.execute(sa_text("SET TIME ZONE 'UTC'"))

            for spec in dataset:
                created_at = datetime.combine(
                    spec["day"], _NOON, tzinfo=timezone.utc
                )
                if spec["source"] == "sms":
                    session.add(SmsMessage(
                        conversation_id=self.conversation_id,
                        org_id=self.org_id,
                        direction=spec["direction"],
                        body="pbt",
                        from_number="+6421000000",
                        to_number="+6421999999",
                        status="delivered",
                        created_at=created_at,
                    ))
                else:
                    session.add(NotificationLog(
                        org_id=self.org_id,
                        channel=spec["channel"],
                        recipient="+6421999999",
                        template_type="pbt",
                        status=spec["status"],
                        created_at=created_at,
                    ))
            await session.flush()

            data = await get_sms_usage(
                session, self.org_id, PERIOD_START, PERIOD_END,
            )

            total_sent = data["total_sent"]
            breakdown = data["daily_breakdown"]

            # ---- Independently recompute the expectation from the dataset ----
            expected_total = sum(1 for s in dataset if _is_counted(s))

            expected_by_day: dict[date, int] = {}
            for s in dataset:
                if _is_counted(s):
                    expected_by_day[s["day"]] = expected_by_day.get(s["day"], 0) + 1

            # ---- Sanity: the service total matches the independent count ----
            assert total_sent == expected_total, (
                f"total_sent {total_sent} != expected {expected_total}"
            )

            # ---- Daily series shape: in-period, ascending, no zero buckets ----
            days = [pt["date"] for pt in breakdown]
            assert days == sorted(days), (
                f"daily_breakdown not sorted ascending: {days}"
            )
            assert len(days) == len(set(days)), (
                f"daily_breakdown has duplicate days: {days}"
            )
            for pt in breakdown:
                assert PERIOD_START <= pt["date"] <= PERIOD_END, (
                    f"daily_breakdown day {pt['date']} outside period"
                )
                assert pt["sms_count"] > 0, (
                    f"zero-count day leaked into daily_breakdown: {pt}"
                )

            # ---- Per-day reconciliation against the independent computation ----
            actual_by_day = {pt["date"]: pt["sms_count"] for pt in breakdown}
            assert actual_by_day == expected_by_day, (
                f"per-day count mismatch: actual={actual_by_day} "
                f"expected={expected_by_day}"
            )

            # ---- Property 6: Σ daily_breakdown.sms_count == total_sent ----
            sum_breakdown = sum(pt["sms_count"] for pt in breakdown)
            assert sum_breakdown == total_sent, (
                f"Σ daily_breakdown.sms_count ({sum_breakdown}) != "
                f"total_sent ({total_sent})"
            )
        finally:
            await session.rollback()
            await session.close()
            await engine.dispose()
