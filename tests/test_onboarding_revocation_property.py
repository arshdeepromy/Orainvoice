"""Property-based test for onboarding-link revocation (Task 6.5).

Feature: staff-onboarding-link
Property 4: Revocation invalidates all active links for a staff member

Exercises ``app.modules.staff.onboarding_tokens.revoke_active`` / ``mint`` /
``resolve`` against the real dev Postgres database (mirroring the DB-backed
Hypothesis pattern in ``tests/test_onboarding_token_generation_property.py``,
task 4.3). For each example we seed one organisation + staff member and then
assert the three revocation guarantees the design promises across the
revoke / resend / deactivate paths:

1. **REVOKE invalidates ALL active links (R10.3)** — directly insert ``N``
   (1..5) ``pending`` token rows for one staff member (distinct
   ``token_hash`` values, future expiry), bypassing ``mint``'s revoke-first
   so several live links coexist. ``revoke_active`` then returns ``N`` and
   EVERY row for that staff is ``revoked`` — none remain ``pending``.
2. **RESEND yields exactly one new pending token (R10.2)** — the resend flow
   (``revoke_active`` then ``mint``) leaves exactly one ``pending`` row, it is
   the newest (its ``token_hash`` matches the freshly minted raw token), and
   every earlier row is ``revoked``.
3. **DEACTIVATE auto-revokes (R10.4)** — ``revoke_active`` is the building
   block the deactivation path delegates to; after ``mint`` + ``revoke_active``
   the pending count is 0 and the row is ``revoked``.

All assertions re-query the database so they reflect *persisted* status, not
in-session state.

Validates: Requirements 10.2, 10.3, 10.4

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres.
- A fresh async engine is created per example (asyncpg connections are bound
  to the event loop ``asyncio.run`` creates), exactly like the reference
  DB-backed property tests in this repo.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select, text as sa_text
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
# example aborts mid-way.
_ORG_MARKER = "TEST_6_5_revocation"

# 7-day TTL the service promises (used when directly inserting pending rows).
_TOKEN_TTL_DAYS = 7


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
# Re-query helpers (assert against PERSISTED status, not in-session state).
# ---------------------------------------------------------------------------


async def _status_counts(factory, org_id, staff_id) -> dict[str, int]:
    """Return a {status: count} map for the staff member's tokens, from the DB."""
    async with factory() as session:
        rows = (
            await session.execute(
                select(StaffOnboardingToken.status, func.count())
                .where(
                    StaffOnboardingToken.org_id == org_id,
                    StaffOnboardingToken.staff_id == staff_id,
                )
                .group_by(StaffOnboardingToken.status)
            )
        ).all()
    return {status: count for status, count in rows}


async def _pending_hashes(factory, org_id, staff_id) -> list[str]:
    """Return the token_hash of every currently-pending row for the staff."""
    async with factory() as session:
        rows = (
            await session.execute(
                select(StaffOnboardingToken.token_hash).where(
                    StaffOnboardingToken.org_id == org_id,
                    StaffOnboardingToken.staff_id == staff_id,
                    StaffOnboardingToken.status == "pending",
                )
            )
        ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(num_active: int) -> None:
    """Seed, exercise revoke / resend / deactivate, assert persisted status."""
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]

        # --- Scenario 1: REVOKE invalidates ALL active links (R10.3). --------
        # Directly insert N pending rows (bypassing mint's revoke-first) so
        # several active links coexist for one staff member.
        async with factory() as session:
            async with session.begin():
                for _ in range(num_active):
                    session.add(
                        StaffOnboardingToken(
                            org_id=org_id,
                            staff_id=staff_id,
                            token_hash=onboarding_tokens._hash_token(
                                uuid.uuid4().hex + uuid.uuid4().hex
                            ),
                            status="pending",
                            expires_at=onboarding_tokens._now_utc()
                            + timedelta(days=_TOKEN_TTL_DAYS),
                        )
                    )

        # Sanity: the direct inserts produced N live links.
        pre = await _status_counts(factory, org_id, staff_id)
        assert pre.get("pending", 0) == num_active, (
            f"expected {num_active} pending rows before revoke, got {pre}"
        )

        async with factory() as session:
            async with session.begin():
                revoked_count = await onboarding_tokens.revoke_active(
                    session, org_id=org_id, staff_id=staff_id
                )

        assert revoked_count == num_active, (
            f"revoke_active returned {revoked_count}, expected {num_active}"
        )

        post = await _status_counts(factory, org_id, staff_id)
        assert post.get("pending", 0) == 0, (
            f"no token should remain pending after revoke, got {post}"
        )
        assert post.get("revoked", 0) == num_active, (
            f"all {num_active} tokens should be revoked, got {post}"
        )

        # --- Scenario 2: RESEND yields exactly one new pending token (R10.2). -
        # Resend = revoke_active then mint. (mint also revokes-first, so this is
        # idempotent w.r.t. leftover pending rows.)
        async with factory() as session:
            async with session.begin():
                await onboarding_tokens.revoke_active(
                    session, org_id=org_id, staff_id=staff_id
                )
                resent_raw = await onboarding_tokens.mint(
                    session, org_id=org_id, staff_id=staff_id
                )

        pending_hashes = await _pending_hashes(factory, org_id, staff_id)
        assert len(pending_hashes) == 1, (
            f"resend must leave exactly one pending token, got {len(pending_hashes)}"
        )
        assert pending_hashes[0] == onboarding_tokens._hash_token(resent_raw), (
            "the single pending row must be the freshly minted (newest) token"
        )

        # resolve() must find the new token and report it pending.
        async with factory() as session:
            resolved = await onboarding_tokens.resolve(session, resent_raw)
        assert resolved is not None, "resolve must find the freshly minted token"
        assert resolved.status == "pending", (
            f"resolved token should be pending, got {resolved.status!r}"
        )

        # All earlier rows revoked: total = num_active (revoked) + 1 (pending).
        after_resend = await _status_counts(factory, org_id, staff_id)
        assert after_resend.get("pending", 0) == 1
        assert after_resend.get("revoked", 0) == num_active, (
            f"all prior tokens should be revoked after resend, got {after_resend}"
        )
        assert after_resend.get("consumed", 0) == 0, (
            "resend/revoke must never mark a token consumed"
        )

        # --- Scenario 3: DEACTIVATE auto-revokes (R10.4). --------------------
        # revoke_active is the deactivation building block: after it runs the
        # single pending token from the resend must become revoked, leaving
        # zero pending.
        async with factory() as session:
            async with session.begin():
                deact_count = await onboarding_tokens.revoke_active(
                    session, org_id=org_id, staff_id=staff_id
                )

        assert deact_count == 1, (
            f"deactivation revoke should have revoked the 1 pending token, "
            f"got {deact_count}"
        )
        final = await _status_counts(factory, org_id, staff_id)
        assert final.get("pending", 0) == 0, (
            f"no pending token may survive deactivation, got {final}"
        )
        assert final.get("consumed", 0) == 0, (
            "deactivation revokes, it never consumes (R10.4 / R2.x)"
        )

        # The previously-resolved token is now revoked when re-queried.
        async with factory() as session:
            resolved_after = await onboarding_tokens.resolve(session, resent_raw)
        assert resolved_after is not None
        assert resolved_after.status == "revoked", (
            f"the token must be revoked after deactivation, got {resolved_after.status!r}"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 4: Revocation invalidates all active links for a staff member.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(num_active=st.integers(min_value=1, max_value=5))
def test_revocation_invalidates_all_active_links(num_active: int):
    """Property 4: Revocation invalidates all active links for a staff member.

    For any number (1..5) of concurrently-pending onboarding tokens belonging
    to one staff member, ``revoke_active`` transitions EVERY pending row to
    ``revoked`` and returns the count (R10.3). The resend flow
    (``revoke_active`` + ``mint``) then leaves exactly one pending token — the
    newest — with all earlier rows revoked (R10.2). Finally the deactivation
    building block (``revoke_active`` again) drives the pending count back to
    zero without ever consuming a token (R10.4). Every assertion re-queries the
    database so it reflects persisted status.

    **Validates: Requirements 10.2, 10.3, 10.4**
    """
    asyncio.run(_run_example(num_active))


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
