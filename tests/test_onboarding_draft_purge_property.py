"""Property-based test for onboarding draft purge (Task 4.7).

Feature: staff-onboarding-link
Property 21: Drafts are purged on submit, revoke, and expiry

Exercises the draft-purge guarantees of
``app.modules.staff.onboarding_tokens`` against the real dev Postgres
database (mirroring the DB-backed Hypothesis pattern in
``tests/test_onboarding_token_generation_property.py`` — fresh async engine
per example, full ORM import block, ``_ORG_MARKER`` cleanup,
``_seed_org_and_staff``, ``@settings`` with health-check suppression, and an
``asyncio.run`` driver).

For every example we seed one organisation + active staff member, mint a
pending onboarding token, save an encrypted draft onto it, then drive ONE of
the three purge paths and assert the draft is gone (both ``draft_data_encrypted``
and ``draft_updated_at`` are NULL), re-resolving from the DB to confirm the
NULLs are persisted (not just in-memory):

1. **SUBMIT (R12.8)** — ``consume(db, row)`` sets ``status="consumed"`` and NULLs
   both draft columns in the same write.
2. **REVOKE (R12.9)** — ``revoke_active(db, org_id=, staff_id=)`` bulk-updates the
   pending row to ``status="revoked"`` and NULLs both draft columns (the
   revoke / resend / deactivation path).
3. **EXPIRY (R12.9)** — after forcing ``expires_at`` into the past,
   ``purge_draft_if_expired(db, row)`` returns ``True`` and NULLs both draft
   columns (lazy expiry purge); ``status`` stays ``pending``.

Validates: Requirements 12.8, 12.9
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

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
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_4_7_draft_purge"

# The three purge paths under test.
_PATHS = ("submit", "revoke", "expiry")


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
# Draft payload strategy — arbitrary partial/empty form data, sometimes
# carrying the sensitive IRD/bank fields so the encrypted blob is exercised.
# ---------------------------------------------------------------------------

_optional_str = st.one_of(st.none(), st.text(min_size=0, max_size=24))

_draft_payload_strategy = st.fixed_dictionaries(
    {},
    optional={
        "last_name": _optional_str,
        "phone": _optional_str,
        "emergency_contact_name": _optional_str,
        "emergency_contact_phone": _optional_str,
        "bank_account_number": st.one_of(st.none(), st.just("12-3456-7890123-00")),
        "ird_number": st.one_of(st.none(), st.just("123-456-789")),
        "tax_code": st.one_of(st.none(), st.sampled_from(["M", "ME", "SB", "S"])),
        "residency_type": st.one_of(
            st.none(), st.sampled_from(["nz_citizen", "work_visa", "student_visa"])
        ),
        "documents_staged_count": st.one_of(st.none(), st.integers(min_value=0, max_value=3)),
    },
)


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(path: str, payload: dict) -> None:
    """Seed, mint, save a draft, drive ``path``, assert the draft is purged."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint a pending token and save an encrypted draft onto it. ---
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )
                row = await onboarding_tokens.resolve(session, raw)
                assert row is not None
                await onboarding_tokens.save_draft(session, row, payload)

                # Precondition: a draft really is present before we purge.
                assert row.draft_data_encrypted is not None, (
                    "save_draft must persist an encrypted draft blob"
                )
                assert row.draft_updated_at is not None, (
                    "save_draft must stamp draft_updated_at"
                )

        # --- Drive exactly one purge path. ---
        async with factory() as session:
            async with session.begin():
                row = await onboarding_tokens.resolve(session, raw)
                assert row is not None

                if path == "submit":
                    await onboarding_tokens.consume(session, row)
                    # In-memory effects of consume (R12.8).
                    assert row.status == "consumed"
                    assert row.draft_data_encrypted is None
                    assert row.draft_updated_at is None
                elif path == "revoke":
                    affected = await onboarding_tokens.revoke_active(
                        session, org_id=org_id, staff_id=staff_id
                    )
                    assert affected == 1, (
                        "revoke_active must revoke the single pending token"
                    )
                elif path == "expiry":
                    # Force the lazy-expiry condition: pending + past expiry.
                    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                    await session.flush()
                    purged = await onboarding_tokens.purge_draft_if_expired(
                        session, row
                    )
                    assert purged is True, (
                        "purge_draft_if_expired must purge a pending-but-expired draft"
                    )
                    # Expiry purge leaves the lifecycle status untouched (R12.9):
                    # expiry is a derived state, never a stored transition.
                    assert row.status == "pending"
                    assert row.draft_data_encrypted is None
                    assert row.draft_updated_at is None
                else:  # pragma: no cover - guarded by the strategy
                    raise AssertionError(f"unknown path {path!r}")

        # --- Re-resolve from the DB to confirm the NULLs are persisted. ---
        async with factory() as session:
            persisted = await onboarding_tokens.resolve(session, raw)
            assert persisted is not None, "token row must still exist after purge"
            assert persisted.draft_data_encrypted is None, (
                f"draft_data_encrypted must be NULL after {path} purge, "
                f"got non-null persisted bytes"
            )
            assert persisted.draft_updated_at is None, (
                f"draft_updated_at must be NULL after {path} purge"
            )

            expected_status = {
                "submit": "consumed",
                "revoke": "revoked",
                "expiry": "pending",
            }[path]
            assert persisted.status == expected_status, (
                f"after {path} purge, expected status={expected_status!r}, "
                f"got {persisted.status!r}"
            )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 21: Drafts are purged on submit, revoke, and expiry.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(path=st.sampled_from(_PATHS), payload=_draft_payload_strategy)
def test_drafts_are_purged_on_submit_revoke_and_expiry(path: str, payload: dict):
    """Property 21: Drafts are purged on submit, revoke, and expiry.

    For any pending token carrying a saved draft, driving the submit
    (``consume``), revoke (``revoke_active``), or expiry-classified
    (``purge_draft_if_expired``) path NULLs both ``draft_data_encrypted`` and
    ``draft_updated_at``, and the NULLs are persisted (confirmed by
    re-resolving from the DB).

    **Validates: Requirements 12.8, 12.9**
    """
    asyncio.run(_run_example(path, payload))


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
