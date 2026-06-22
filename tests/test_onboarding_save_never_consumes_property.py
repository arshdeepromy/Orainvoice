"""Property-based test for save-draft never consuming the token (Task 4.6).

Feature: staff-onboarding-link
Property 20: Saving a draft never consumes the token

Exercises ``app.modules.staff.onboarding_tokens.{mint,resolve,save_draft}``
against the real dev Postgres database (mirroring the DB-backed Hypothesis
pattern in ``tests/test_onboarding_token_generation_property.py`` / task 4.3).
For each example we seed one organisation + staff member, mint a pending token,
resolve it, and then call ``save_draft`` one or more times with arbitrary
partial payloads. After EVERY save we assert the lifecycle guarantee R12.7:

- ``status`` remains ``"pending"`` (the token is left in its pending state and
  stays usable until successful submission or expiry).
- ``consumed_at`` remains ``None`` (saving a draft never consumes the token).
- ``draft_data_encrypted`` is now non-NULL and ``draft_updated_at`` is set
  (the only two columns ``save_draft`` is permitted to mutate).
- The minted lifecycle columns ``created_at`` and ``expires_at`` are unchanged
  from the freshly-minted row (``save_draft`` touches nothing else).

Validates: Requirements 12.7

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property test in this repo.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_onboarding_token_generation_property.py).
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

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.staff import onboarding_tokens
from app.modules.staff.models import StaffMember, StaffOnboardingToken

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way (distinct from other DB-backed onboarding tests).
_ORG_MARKER = "TEST_4_6_save_no_consume"


# ---------------------------------------------------------------------------
# Partial-payload strategy — arbitrary, possibly-empty onboarding form drafts,
# mixing plain fields with the sensitive IRD/bank fields and non-primitive
# types (date / Decimal) that ``save_draft``'s JSON default knows how to coerce.
# ---------------------------------------------------------------------------

_text = st.text(max_size=40)
_dates = st.dates().map(lambda d: d.isoformat()) | st.dates()
_rates = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_partial_payload = st.fixed_dictionaries(
    {},
    optional={
        "first_name": _text,
        "last_name": _text,
        "phone": _text,
        "address": _text,
        "ird_number": st.text(alphabet="0123456789-", max_size=11),
        "bank_account_number": st.text(alphabet="0123456789-", max_size=18),
        "kiwisaver_employee_rate": _rates,
        "visa_expiry_date": _dates,
        "emergency_contact_name": _text,
        "notes": _text,
    },
)


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
# ---------------------------------------------------------------------------


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


async def _cleanup(factory) -> None:
    """Delete every row created by the seeder (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for tbl in ("staff_onboarding_tokens", "staff_members"):
                await session.execute(
                    sa_text(f"DELETE FROM {tbl} WHERE org_id IN ({org_subq})"),
                    params,
                )
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                params,
            )
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


async def _seed_org_and_staff(factory) -> dict:
    """Seed one org + one active staff member; return their ids."""
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan",
                monthly_price_nzd=0,
                user_seats=5,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            org = Organisation(
                name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            session.add(org)
            await session.flush()

            staff = StaffMember(
                org_id=org.id,
                name="Onboarding Test Staff",
                first_name="Onboarding",
                last_name="Tester",
                email="onboard-test@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(payloads: list[dict]) -> None:
    """Seed, mint+resolve a token, save each payload, assert R12.7 each time."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        # Capture the minted lifecycle columns so we can prove save_draft
        # never disturbs them.
        async with factory() as session:
            row = await onboarding_tokens.resolve(session, raw)
            assert row is not None, "freshly minted token must resolve"
            minted_created_at = row.created_at
            minted_expires_at = row.expires_at
            assert row.status == "pending"
            assert row.consumed_at is None
            assert row.draft_data_encrypted is None
            assert row.draft_updated_at is None

        # Save each arbitrary partial payload (in its own transaction) and
        # re-resolve to verify the lifecycle invariant holds after every save.
        for payload in payloads:
            async with factory() as session:
                async with session.begin():
                    row = await onboarding_tokens.resolve(session, raw)
                    assert row is not None
                    await onboarding_tokens.save_draft(session, row, payload)

            async with factory() as session:
                row = await onboarding_tokens.resolve(session, raw)
                assert row is not None

                # --- R12.7: never consumes ---
                assert row.status == "pending", (
                    f"save_draft mutated status to {row.status!r}; "
                    "R12.7 requires it to stay 'pending'"
                )
                assert row.consumed_at is None, (
                    "save_draft set consumed_at; R12.7 requires it to stay NULL"
                )

                # --- Only the two draft columns may change ---
                assert row.draft_data_encrypted is not None, (
                    "save_draft must populate draft_data_encrypted"
                )
                assert row.draft_updated_at is not None, (
                    "save_draft must populate draft_updated_at"
                )

                # --- Minted lifecycle columns untouched ---
                assert row.created_at == minted_created_at, (
                    "save_draft must not change created_at"
                )
                assert row.expires_at == minted_expires_at, (
                    "save_draft must not change expires_at"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 20: Saving a draft never consumes the token.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(payloads=st.lists(_partial_payload, min_size=1, max_size=4))
def test_save_draft_never_consumes_token(payloads: list[dict]):
    """Property 20: Saving a draft never consumes the token.

    For any pending token and any sequence of arbitrary partial payloads,
    ``save_draft`` leaves ``status="pending"`` and ``consumed_at`` NULL, only
    mutating ``draft_data_encrypted`` / ``draft_updated_at`` and leaving the
    minted ``created_at`` / ``expires_at`` untouched.

    **Validates: Requirements 12.7**
    """
    asyncio.run(_run_example(payloads))


@pytest.fixture(scope="module", autouse=True)
def _final_cleanup():
    """Best-effort teardown of any rows left behind by an aborted example."""
    yield

    async def _do():
        engine, factory = await _make_engine_and_factory()
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()

    asyncio.run(_do())
