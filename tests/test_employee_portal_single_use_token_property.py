"""Property-based test: Employee Portal single-use credential token consumption.

# Feature: organisation-employee-portal, Property 20: Single-use credential token consumption

**Validates: Requirements 5.9, 14.5, 14.6**

Property 20 (design.md): *For any* invite or password-reset token, successful
consumption updates the credential and immediately invalidates the token so a
second use is rejected; an expired, already-used, or unknown token is rejected
and leaves the stored password hash unchanged.

The two consumption paths under test live in
``app.modules.employee_portal.services.account_service``:

- ``accept_invite(db, raw_token, new_password)`` — single-use invite token,
  valid for 7 days (``INVITE_VALIDITY``); on success sets ``password_hash``,
  stamps ``invite_accepted_at`` and clears ``invite_token_hash`` (R5.9).
- ``complete_reset(db, raw_token, new_password)`` — single-use reset token,
  valid for 3600s (``RESET_VALIDITY``); on success updates ``password_hash``,
  clears ``reset_token_hash`` / ``reset_token_expires_at`` and deletes the
  user's sessions (R14.5, R14.6).

This is a DB-backed Hypothesis test against the transactional dev Postgres,
mirroring the established pattern in
``tests/test_employee_portal_password_length_property.py`` and
``tests/test_org_scoped_staff_uniqueness_property.py``: a fresh async engine per
example (asyncpg connections are bound to the loop ``asyncio.run`` creates), the
full ORM import block, an org-name marker for orphan cleanup, and an
``asyncio.run`` driver.

For each generated ``(flow, scenario)`` we seed an org + active staff + a portal
user holding the relevant token, then:

- **valid** — submit a well-formed password; assert the credential is updated
  (``password_hash`` set to a bcrypt hash that verifies, never the plaintext),
  the token is consumed (the relevant ``*_token_hash`` is cleared), any prior
  session is gone (reset), and a **second use of the same raw token is
  rejected** leaving the now-cleared stored hash unchanged.
- **expired** — seed a token past its validity window; assert the call is
  rejected and the stored password hash + token hash are left unchanged.
- **used** — seed an already-consumed token (invite already accepted); assert
  rejection with no change to stored state.
- **unknown** — submit a raw token that was never issued; assert rejection and
  that the seeded credential is untouched.

All persistence assertions re-read the row from the database (not the in-memory
ORM object) so they pin the committed state.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

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
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_password_length_property.py).
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
from app.modules.employee_portal import models as _emp_portal_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal.auth import verify_password_sync
from app.modules.employee_portal.models import (
    EmployeePortalSession,
    EmployeePortalUser,
)
from app.modules.employee_portal.services import account_service, session_service
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_P20_single_use_token"

# A password the existing reset users already hold, so we can prove a rejected
# reset leaves the prior hash unchanged.
_EXISTING_PASSWORD = "existing-password-123"


# ---------------------------------------------------------------------------
# Engine / session / cleanup helpers (fresh engine per example).
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
            for tbl in (
                "employee_portal_audit_log",
                "employee_portal_sessions",
                "employee_portal_users",
                "staff_members",
            ):
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
                name="Single Use Token Test Staff",
                first_name="Single",
                last_name="Token",
                email=f"sut-{uuid.uuid4().hex[:8]}@example.com",
                is_active=True,
            )
            session.add(staff)
            await session.flush()

            return {"org_id": org.id, "staff_id": staff.id}


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(flow: str, scenario: str, password: str) -> None:
    """Seed a portal user holding a token in ``scenario`` state, then consume.

    ``flow`` ∈ {"invite", "reset"}; ``scenario`` ∈ {"valid", "expired",
    "used", "unknown"}.
    """
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed_org_and_staff(factory)
        org_id = ids["org_id"]
        staff_id = ids["staff_id"]
        now = datetime.now(timezone.utc)

        # The raw token that will actually be submitted to the consumer.
        issued_raw = uuid.uuid4().hex + uuid.uuid4().hex
        issued_hash = account_service._hash_token(issued_raw)

        # For the "unknown" scenario we store a *different* token's hash and
        # submit a brand-new raw token that was never issued.
        stored_hash = (
            account_service._hash_token(uuid.uuid4().hex + uuid.uuid4().hex)
            if scenario == "unknown"
            else issued_hash
        )
        submitted_raw = issued_raw

        # --- Provision the portal user in the requested token state. ---
        async with factory() as session:
            async with session.begin():
                user = EmployeePortalUser(
                    org_id=org_id,
                    staff_id=staff_id,
                    email=f"sut-{uuid.uuid4().hex[:8]}@example.com",
                    password_hash=None,
                    is_active=True,
                )
                if flow == "invite":
                    user.invite_token_hash = stored_hash
                    if scenario == "expired":
                        # Issued 8 days ago — beyond the 7-day window.
                        user.invite_sent_at = now - timedelta(days=8)
                    elif scenario == "used":
                        # Already accepted — a second acceptance is rejected.
                        user.invite_sent_at = now - timedelta(hours=1)
                        user.invite_accepted_at = now - timedelta(minutes=30)
                        user.password_hash = ep_auth.hash_password_sync(
                            _EXISTING_PASSWORD
                        )
                    else:  # valid / unknown
                        user.invite_sent_at = now
                else:  # reset — a reset presupposes an already-set password.
                    user.password_hash = ep_auth.hash_password_sync(_EXISTING_PASSWORD)
                    user.reset_token_hash = stored_hash
                    if scenario == "expired":
                        user.reset_token_expires_at = now - timedelta(seconds=1)
                    elif scenario == "used":
                        # An already-consumed reset has its hash cleared; submit
                        # the raw token that no longer resolves.
                        user.reset_token_hash = None
                        user.reset_token_expires_at = None
                    else:  # valid / unknown
                        user.reset_token_expires_at = now + timedelta(seconds=3600)
                session.add(user)
                await session.flush()
                user_id = user.id
                seeded_password_hash = user.password_hash
                seeded_token_hash = (
                    user.invite_token_hash
                    if flow == "invite"
                    else user.reset_token_hash
                )

                # Seed one session so we can prove a successful reset tears it
                # down (R14.8). (Invite acceptance does not touch sessions.)
                if flow == "reset" and scenario == "valid":
                    sess = EmployeePortalSession(
                        org_id=org_id,
                        portal_user_id=user_id,
                        session_token_hash=account_service._hash_token(
                            uuid.uuid4().hex
                        ),
                        csrf_token=uuid.uuid4().hex,
                        created_at=now,
                        last_seen_at=now,
                        expires_at=now + timedelta(hours=12),
                    )
                    session.add(sess)
                    await session.flush()

        call = (
            account_service.accept_invite
            if flow == "invite"
            else account_service.complete_reset
        )
        token_col = (
            EmployeePortalUser.invite_token_hash
            if flow == "invite"
            else EmployeePortalUser.reset_token_hash
        )

        if scenario == "valid":
            # --- Successful consumption updates the credential. ---
            async with factory() as session:
                async with session.begin():
                    updated = await call(session, submitted_raw, password)
                    assert updated.id == user_id

            async with factory() as session:
                persisted = await session.get(EmployeePortalUser, user_id)
                assert persisted is not None
                # Credential updated: stored as a bcrypt hash, never plaintext.
                assert persisted.password_hash is not None
                assert persisted.password_hash != password
                assert verify_password_sync(password, persisted.password_hash)
                # Token invalidated (single-use).
                if flow == "invite":
                    assert persisted.invite_token_hash is None
                    assert persisted.invite_accepted_at is not None
                else:
                    assert persisted.reset_token_hash is None
                    assert persisted.reset_token_expires_at is None
                    # Sessions torn down (R14.8).
                    remaining = await session.execute(
                        select(func.count())
                        .select_from(EmployeePortalSession)
                        .where(EmployeePortalSession.portal_user_id == user_id)
                    )
                    assert remaining.scalar_one() == 0

            # --- Second use of the SAME raw token is rejected. ---
            with pytest.raises(account_service.AccountServiceError):
                async with factory() as session:
                    async with session.begin():
                        await call(session, submitted_raw, password)

            # The cleared token hash is left unchanged by the rejected reuse.
            async with factory() as session:
                after = await session.get(EmployeePortalUser, user_id)
                assert after is not None
                hash_after = (
                    after.invite_token_hash
                    if flow == "invite"
                    else after.reset_token_hash
                )
                assert hash_after is None
        else:
            # --- expired / used / unknown → rejected, stored state unchanged. ---
            with pytest.raises(account_service.AccountServiceError):
                async with factory() as session:
                    async with session.begin():
                        await call(session, submitted_raw, password)

            async with factory() as session:
                persisted = await session.get(EmployeePortalUser, user_id)
                assert persisted is not None
                # Stored password hash is unchanged.
                assert persisted.password_hash == seeded_password_hash
                # Stored token hash is unchanged.
                current_token_hash = (
                    persisted.invite_token_hash
                    if flow == "invite"
                    else persisted.reset_token_hash
                )
                assert current_token_hash == seeded_token_hash
                if flow == "invite" and scenario != "used":
                    assert persisted.invite_accepted_at is None
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 20: Single-use credential token consumption.
# ---------------------------------------------------------------------------

# Keep accepted-password lengths small so the per-example bcrypt cost stays
# affordable; the length gate itself is covered by Property 11.
_password_strategy = st.integers(min_value=8, max_value=20).map(lambda n: "p" * n)


@settings(
    max_examples=110,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    flow=st.sampled_from(["invite", "reset"]),
    scenario=st.sampled_from(["valid", "expired", "used", "unknown"]),
    password=_password_strategy,
)
def test_single_use_credential_token_consumption(
    flow: str, scenario: str, password: str
) -> None:
    """Property 20: Single-use credential token consumption.

    # Feature: organisation-employee-portal, Property 20: Single-use credential token consumption

    Successful consumption updates the credential and invalidates the token so a
    second use is rejected; an expired / already-used / unknown token is
    rejected and leaves the stored password hash unchanged.

    **Validates: Requirements 5.9, 14.5, 14.6**
    """
    asyncio.run(_run_example(flow, scenario, password))


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
