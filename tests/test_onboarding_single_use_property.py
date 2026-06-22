"""Property-based test for single-use token consumption (Task 8.4).

Feature: staff-onboarding-link
Property 2: Tokens are single-use and consumed only by successful submission

Exercises the token lifecycle of ``app.modules.staff.onboarding_tokens``
(``mint`` / ``resolve`` / ``consume`` / ``revoke_active`` /
``purge_draft_if_expired``) together with the pure classifier
``app.modules.staff.onboarding_validation.classify_token_state`` against the
real dev Postgres database (mirroring the DB-backed Hypothesis pattern in
``tests/test_onboarding_token_generation_property.py`` — fresh async engine per
example, full ORM import block, ``_ORG_MARKER`` cleanup, ``_seed_org_and_staff``,
``@settings`` with health-check suppression, and an ``asyncio.run`` driver).

For every example we seed one organisation + active staff member, mint a
pending onboarding token, optionally save an encrypted draft, then drive ONE of
four lifecycle paths and assert the single-use guarantee, re-resolving from the
DB each time to confirm the persisted ``status`` / ``consumed_at`` (not just the
in-memory ORM state):

1. **SUBMIT (R2.5, R9.6)** — ``consume(db, row)`` marks ``status="consumed"`` and
   stamps ``consumed_at``. A SECOND ``resolve`` + ``classify_token_state`` of the
   same token returns ``"consumed"`` (single-use; subsequent use rejected), and a
   redundant second ``consume`` keeps it ``consumed`` with the SAME
   ``consumed_at`` (consumed exactly once — no re-stamp).
2. **EXPIRY** — after forcing ``expires_at`` into the past,
   ``classify_token_state`` returns ``"expired"`` and the token is NEVER marked
   ``consumed`` (``status`` stays ``pending``, ``consumed_at`` stays NULL); the
   lazy ``purge_draft_if_expired`` likewise never consumes.
3. **REVOKE** — ``revoke_active`` sets ``status="revoked"`` and NEVER
   ``consumed`` (``consumed_at`` stays NULL); ``classify_token_state`` →
   ``"revoked"``.
4. **DEACTIVATE** — a deactivation-style ``revoke_active`` (with the staff member
   flipped inactive) likewise sets ``status="revoked"`` and NEVER ``consumed``;
   ``classify_token_state`` → ``"revoked"`` (the revoked status takes precedence
   over the inactive staff member).

Validates: Requirements 2.5, 9.6

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
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
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
from app.modules.staff.models import StaffMember
from app.modules.staff.onboarding_validation import classify_token_state

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other onboarding DB property tests
# so parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_8_4_single_use"

# The four lifecycle paths under test.
_PATHS = ("submit", "expiry", "revoke", "deactivate")


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
        "documents_staged_count": st.one_of(
            st.none(), st.integers(min_value=0, max_value=3)
        ),
    },
)


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(path: str, save_draft_first: bool, payload: dict) -> None:
    """Seed, mint (optionally save a draft), drive ``path``, assert single-use."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Mint a pending token (and optionally stash an encrypted draft). ---
        async with factory() as session:
            async with session.begin():
                raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )
                if save_draft_first:
                    row = await onboarding_tokens.resolve(session, raw)
                    assert row is not None
                    await onboarding_tokens.save_draft(session, row, payload)

        now = datetime.now(timezone.utc)

        if path == "submit":
            # --- SUBMIT: consume marks consumed + stamps consumed_at (R2.5/R9.6). ---
            async with factory() as session:
                async with session.begin():
                    row = await onboarding_tokens.resolve(session, raw)
                    assert row is not None
                    await onboarding_tokens.consume(session, row)
                    assert row.status == "consumed"
                    assert row.consumed_at is not None

            # Re-resolve to capture the persisted consumed_at for the
            # "exactly once" check below.
            async with factory() as session:
                row = await onboarding_tokens.resolve(session, raw)
                assert row is not None
                assert row.status == "consumed"
                assert row.consumed_at is not None
                first_consumed_at = row.consumed_at
                # Subsequent use is rejected: classify reports 'consumed'.
                assert (
                    classify_token_state(row, now, staff_is_active=True) == "consumed"
                )

            # --- SECOND use of the same token (the public submit/prefill path
            # re-resolves and classifies BEFORE doing any work, so a consumed
            # token is rejected up front and never re-consumed). The persisted
            # status / consumed_at are unchanged — consumed exactly once. ---
            async with factory() as session:
                persisted = await onboarding_tokens.resolve(session, raw)
                assert persisted is not None
                assert persisted.status == "consumed", (
                    "a second use must leave the token consumed (single-use)"
                )
                assert persisted.consumed_at == first_consumed_at, (
                    "re-resolving a consumed token must not re-stamp consumed_at "
                    "(consumed exactly once)"
                )
                assert (
                    classify_token_state(persisted, now, staff_is_active=True)
                    == "consumed"
                ), "a consumed token must classify as 'consumed' on re-use"

        elif path == "expiry":
            # --- EXPIRY: classifies 'expired', NEVER consumed. ---
            async with factory() as session:
                async with session.begin():
                    row = await onboarding_tokens.resolve(session, raw)
                    assert row is not None
                    row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                    await session.flush()
                    # The lazy expiry purge must NOT consume the token.
                    await onboarding_tokens.purge_draft_if_expired(session, row)
                    assert row.status == "pending"
                    assert row.consumed_at is None

            async with factory() as session:
                persisted = await onboarding_tokens.resolve(session, raw)
                assert persisted is not None
                # Expiry is a derived state — status stays pending, never consumed.
                assert persisted.status == "pending", (
                    "expiry must never set status='consumed'"
                )
                assert persisted.consumed_at is None, (
                    "expiry-rejection must never stamp consumed_at (R2.5)"
                )
                assert (
                    classify_token_state(persisted, now, staff_is_active=True)
                    == "expired"
                )

        elif path == "revoke":
            # --- REVOKE: status -> 'revoked', NEVER consumed. ---
            async with factory() as session:
                async with session.begin():
                    affected = await onboarding_tokens.revoke_active(
                        session, org_id=org_id, staff_id=staff_id
                    )
                    assert affected == 1

            async with factory() as session:
                persisted = await onboarding_tokens.resolve(session, raw)
                assert persisted is not None
                assert persisted.status == "revoked", (
                    "revoke must set status='revoked'"
                )
                assert persisted.consumed_at is None, (
                    "revoke must never stamp consumed_at (R2.5)"
                )
                assert (
                    classify_token_state(persisted, now, staff_is_active=True)
                    == "revoked"
                )

        elif path == "deactivate":
            # --- DEACTIVATE: deactivation-style revoke, NEVER consumed. ---
            async with factory() as session:
                async with session.begin():
                    # Flip the staff member inactive (the deactivation event)
                    # and revoke their active onboarding token in the same txn.
                    staff = await session.get(StaffMember, staff_id)
                    assert staff is not None
                    staff.is_active = False
                    affected = await onboarding_tokens.revoke_active(
                        session, org_id=org_id, staff_id=staff_id
                    )
                    assert affected == 1

            async with factory() as session:
                persisted = await onboarding_tokens.resolve(session, raw)
                assert persisted is not None
                assert persisted.status == "revoked", (
                    "deactivation revokes a token, it does not consume it"
                )
                assert persisted.consumed_at is None, (
                    "deactivation must never stamp consumed_at (R2.5)"
                )
                # Revoked status takes precedence over the inactive staff member.
                assert (
                    classify_token_state(persisted, now, staff_is_active=False)
                    == "revoked"
                )

        else:  # pragma: no cover - guarded by the strategy
            raise AssertionError(f"unknown path {path!r}")
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 2: Tokens are single-use and consumed only by successful submission.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    path=st.sampled_from(_PATHS),
    save_draft_first=st.booleans(),
    payload=_draft_payload_strategy,
)
def test_tokens_are_single_use_and_consumed_only_on_submit(
    path: str, save_draft_first: bool, payload: dict
):
    """Property 2: Tokens are single-use and consumed only by successful submission.

    A successful submit (``consume``) marks the token ``consumed`` exactly once
    (``consumed_at`` stamped and not re-stamped on a redundant second consume),
    and any subsequent ``resolve`` + ``classify_token_state`` reports
    ``"consumed"`` (subsequent use rejected). None of the non-submit lifecycle
    paths — expiry, revoke, or deactivation-revoke — ever set
    ``status="consumed"`` or stamp ``consumed_at``; they classify as
    ``"expired"`` / ``"revoked"`` respectively. Every assertion re-resolves the
    row from the DB to confirm the persisted state.

    **Validates: Requirements 2.5, 9.6**
    """
    asyncio.run(_run_example(path, save_draft_first, payload))


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
