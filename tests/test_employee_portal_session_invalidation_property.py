"""Property-based test: Employee Portal session invalidation.

# Feature: organisation-employee-portal, Property 17: Session invalidation

**Validates: Requirements 4.5, 4.6, 5.10, 5.11, 6.9, 14.8**

Property 17 (design.md): *For any* prior Employee_Portal session, after the org
disables the portal, an Org_Admin revokes a staff member's access, a Staff_Member
is deactivated, the Portal_User logs out, or a password reset completes, **no
prior session for the affected scope remains valid** — the corresponding rows in
``employee_portal_sessions`` are gone, so they can never re-authenticate.

The five invalidation paths under test (and the affected scope of each):

- **disable** — ``organisations.service.set_employee_portal_enabled(enabled=False)``
  → ``session_service.delete_sessions_for_org`` (R4.6). Scope = the **whole org**:
  every session for the org is invalidated.
- **revoke** — ``account_service.revoke_access(org_id, staff_id)`` →
  ``delete_sessions_for_user`` (R5.10). Scope = the **revoked staff's** portal
  user only.
- **deactivate** — ``account_service.revoke_portal_access_for_staff(org_id,
  staff_id)`` → ``delete_sessions_for_user`` (R5.11). Scope = the **deactivated
  staff's** portal user only.
- **logout** — ``session_service.destroy_session(raw_token)`` (R6.9). Scope = the
  **single** session being logged out.
- **reset** — ``account_service.complete_reset(raw_token, new_password)`` →
  ``delete_sessions_for_user`` (R14.8). Scope = the **resetting** portal user.

For each generated ``(action, a_count, b_count)`` we seed one org with the portal
enabled, two active staff members each with a linked active Portal_User, and a
handful of valid sessions per user (``created_at = last_seen_at = now``,
``expires_at = now + 12h``). We then apply one invalidation action and assert:

- every session in the **affected scope** is gone from ``employee_portal_sessions``
  (a deleted row cannot be valid — the strongest form of "no longer valid"); and
- every session **outside** the affected scope survives and is still valid by
  ``is_session_valid`` — proving the invalidation is correctly scoped and never
  over-broad (e.g. revoking staff A never touches staff B's sessions).

This is a DB-backed Hypothesis test against the transactional dev Postgres,
mirroring the established pattern in
``tests/test_employee_portal_single_use_token_property.py`` and
``tests/test_global_slug_uniqueness_property.py``: a fresh async engine per
example (asyncpg connections are bound to the loop ``asyncio.run`` creates), the
full ORM import block, an org-name marker for orphan cleanup, and an
``asyncio.run`` driver. Each invalidation action commits, and assertions re-read
session rows from the database (not in-memory ORM objects) so they pin the
committed state.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import secrets
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
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_employee_portal_single_use_token_property.py).
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
from app.modules.employee_portal.models import (
    EmployeePortalSession,
    EmployeePortalUser,
)
from app.modules.employee_portal.services import account_service, session_service
from app.modules.employee_portal.services.session_service import (
    hash_token,
    is_session_valid,
)
from app.modules.organisations.service import set_employee_portal_enabled
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other portal DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_P17_session_invalidation"

# The five invalidation paths exercised by the property.
_ACTIONS = ["disable", "revoke", "deactivate", "logout", "reset"]


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
                "audit_log",
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
                sa_text("DELETE FROM subscription_plans WHERE name LIKE :marker"),
                {"marker": f"{_ORG_MARKER}_plan%"},
            )


async def _seed(factory, *, action: str, a_count: int, b_count: int) -> dict:
    """Seed an org + two staff + two portal users + their sessions.

    Returns the ids needed to apply an action and to assert on its scope:
    ``org_id``, ``staff_a_id``, the per-user session id lists, the raw token of
    user A's first session (for logout), and (for reset) user A's raw reset
    token.
    """
    now = datetime.now(timezone.utc)
    async with factory() as session:
        async with session.begin():
            plan = SubscriptionPlan(
                name=f"{_ORG_MARKER}_plan_{uuid.uuid4().hex[:8]}",
                monthly_price_nzd=0,
                user_seats=5,
                storage_quota_gb=1,
                carjam_lookups_included=0,
                enabled_modules=[],
            )
            session.add(plan)
            await session.flush()

            # Portal enabled so the disable path has a real flag to flip.
            org = Organisation(
                name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={"employee_portal_enabled": True},
            )
            session.add(org)
            await session.flush()
            org_id = org.id

            staff_a = StaffMember(
                org_id=org_id,
                name="Portal Staff A",
                first_name="Portal",
                last_name="StaffA",
                email=f"p17a-{uuid.uuid4().hex[:8]}@example.com",
                is_active=True,
            )
            staff_b = StaffMember(
                org_id=org_id,
                name="Portal Staff B",
                first_name="Portal",
                last_name="StaffB",
                email=f"p17b-{uuid.uuid4().hex[:8]}@example.com",
                is_active=True,
            )
            session.add_all([staff_a, staff_b])
            await session.flush()

            raw_reset = secrets.token_urlsafe(32)
            user_a = EmployeePortalUser(
                org_id=org_id,
                staff_id=staff_a.id,
                email=f"p17a-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=None,
                is_active=True,
                # Seed a live single-use reset token so complete_reset resolves.
                reset_token_hash=hash_token(raw_reset),
                reset_token_expires_at=now + timedelta(seconds=3600),
            )
            user_b = EmployeePortalUser(
                org_id=org_id,
                staff_id=staff_b.id,
                email=f"p17b-{uuid.uuid4().hex[:8]}@example.com",
                password_hash=None,
                is_active=True,
            )
            session.add_all([user_a, user_b])
            await session.flush()

            def _mint_session(portal_user_id: uuid.UUID) -> tuple[uuid.UUID, str]:
                raw = secrets.token_urlsafe(32)
                sess = EmployeePortalSession(
                    org_id=org_id,
                    portal_user_id=portal_user_id,
                    session_token_hash=hash_token(raw),
                    csrf_token=secrets.token_urlsafe(32),
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + timedelta(hours=12),
                )
                session.add(sess)
                return sess, raw

            a_sessions = [_mint_session(user_a.id) for _ in range(a_count)]
            b_sessions = [_mint_session(user_b.id) for _ in range(b_count)]
            await session.flush()

            return {
                "org_id": org_id,
                "staff_a_id": staff_a.id,
                "a_session_ids": [s.id for s, _ in a_sessions],
                "b_session_ids": [s.id for s, _ in b_sessions],
                "a_first_raw": a_sessions[0][1],
                "raw_reset": raw_reset,
            }


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(action: str, a_count: int, b_count: int) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        seed = await _seed(factory, action=action, a_count=a_count, b_count=b_count)
        org_id = seed["org_id"]
        a_ids = set(seed["a_session_ids"])
        b_ids = set(seed["b_session_ids"])
        all_ids = a_ids | b_ids

        # --- Apply the invalidation action (commits via session.begin()). ---
        async with factory() as session:
            async with session.begin():
                if action == "disable":
                    await set_employee_portal_enabled(
                        session,
                        org_id=org_id,
                        user_id=uuid.uuid4(),  # audit_log.user_id has no FK
                        enabled=False,
                    )
                elif action == "revoke":
                    await account_service.revoke_access(
                        session, org_id, seed["staff_a_id"]
                    )
                elif action == "deactivate":
                    await account_service.revoke_portal_access_for_staff(
                        session, org_id, seed["staff_a_id"]
                    )
                elif action == "logout":
                    destroyed = await session_service.destroy_session(
                        session, seed["a_first_raw"]
                    )
                    assert destroyed is True, "logout did not delete the session row"
                elif action == "reset":
                    await account_service.complete_reset(
                        session, seed["raw_reset"], "p" * 12
                    )
                else:  # pragma: no cover - guarded by the strategy
                    raise AssertionError(f"unknown action {action!r}")

        # --- Determine the affected scope for this action. ---
        if action == "disable":
            affected, unaffected = all_ids, set()
        elif action in ("revoke", "deactivate", "reset"):
            # Scope = the targeted user (staff A); staff B is untouched.
            affected, unaffected = a_ids, b_ids
        else:  # logout — only the single session being logged out.
            logged_out = seed["a_session_ids"][0]
            affected, unaffected = {logged_out}, all_ids - {logged_out}

        # --- Assert the invariant from committed state. ---
        async with factory() as session:
            rows = (
                await session.execute(
                    select(EmployeePortalSession).where(
                        EmployeePortalSession.org_id == org_id
                    )
                )
            ).scalars().all()
            remaining_ids = {r.id for r in rows}

            # No prior session in the affected scope survives — a deleted row
            # can never be valid (the strongest form of "no longer valid").
            assert affected.isdisjoint(remaining_ids), (
                f"action={action}: affected-scope sessions still present: "
                f"{sorted(affected & remaining_ids)}"
            )

            # Every out-of-scope session survives and is still valid — the
            # invalidation is correctly scoped, never over-broad.
            assert unaffected <= remaining_ids, (
                f"action={action}: over-broad invalidation removed out-of-scope "
                f"sessions: {sorted(unaffected - remaining_ids)}"
            )
            now = datetime.now(timezone.utc)
            for r in rows:
                assert r.id in unaffected, (
                    f"action={action}: unexpected surviving session {r.id}"
                )
                assert is_session_valid(r.created_at, r.last_seen_at, now), (
                    f"action={action}: surviving out-of-scope session {r.id} "
                    f"is not valid"
                )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 17: Session invalidation on disable / revoke / deactivate / logout /
# reset.
# ---------------------------------------------------------------------------


@settings(
    max_examples=110,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(
    action=st.sampled_from(_ACTIONS),
    a_count=st.integers(min_value=1, max_value=3),
    b_count=st.integers(min_value=1, max_value=3),
)
def test_session_invalidation(action: str, a_count: int, b_count: int) -> None:
    """Property 17: Session invalidation on disable / revoke / deactivate /
    logout / reset.

    # Feature: organisation-employee-portal, Property 17: Session invalidation

    After portal disable, access revoke, staff deactivation, logout, or password
    reset, no prior session for the affected scope remains valid (the rows are
    deleted from ``employee_portal_sessions``), while every out-of-scope session
    survives and stays valid.

    **Validates: Requirements 4.5, 4.6, 5.10, 5.11, 6.9, 14.8**
    """
    asyncio.run(_run_example(action, a_count, b_count))


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
