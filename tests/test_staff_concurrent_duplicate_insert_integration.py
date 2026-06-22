"""Integration test: concurrent duplicate active staff insert (Task 17.2).

Feature: organisation-employee-portal — Requirement 1.4

R1.4: *When two concurrent requests attempt to create active Staff_Members with
the same normalised email in the same Organisation, the Staff_Module SHALL
persist exactly one Staff_Member, SHALL reject the other request with an error
indicating a duplicate Staff_Member, and SHALL leave no partial record from the
rejected request.*

This is a **DB-backed integration test** that exercises the real race the
partial unique index ``uq_staff_active_email_per_org`` (migration 0224) is there
to win. The application-level ``_check_duplicates`` is racy and bypassable by
design (two requests can both pass the check before either commits); only the
database constraint can guarantee that exactly one of two genuinely concurrent
inserts survives. So we drive two **independent transactions on two separate
connections** that both insert an active staff row whose email normalises to the
SAME ``lower(btrim(email))`` value in the SAME org, hold both transactions open
simultaneously (via an ``asyncio.Barrier``), then let both attempt to commit.

We assert, against the committed database state (re-read, not in-memory ORM):

1. **Exactly one persists** — precisely one of the two workers commits its row.
2. **The other is rejected with a duplicate error** — the losing worker raises
   ``IntegrityError`` naming ``uq_staff_active_email_per_org`` (the duplicate
   determination).
3. **No partial record** — exactly one active staff row exists for that org +
   normalised email, and the losing worker's pre-generated row id is absent
   from the table (its whole transaction rolled back — no orphan/partial row).

The same race is exercised across several email-decoration pairs (identical
string, case-only difference, surrounding-whitespace difference) to confirm the
constraint keys on the normalised ``lower(btrim(email))`` form, not the raw
string (R1.4 + the normalisation defined in R1.2).

A fresh async engine is created per scenario because asyncpg connections are
bound to the event loop ``asyncio.run`` creates — exactly like the reference
DB-backed tests (``tests/test_org_scoped_staff_uniqueness_property.py``,
``tests/test_employee_portal_session_invalidation_property.py``). The seeded org
+ plan are COMMITTED (both concurrent transactions must see the org to satisfy
the FK), so cleanup is keyed on an org-name marker to remove any orphans.

Run with::

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro \
        python3 -m pytest tests/test_staff_concurrent_duplicate_insert_integration.py

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# tests, e.g. tests/test_org_scoped_staff_uniqueness_property.py).
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
from app.modules.staff.models import StaffMember

# Marker baked into seeded org names so cleanup can find orphans even when a
# scenario aborts mid-way. Distinct from the other staff/portal DB tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_T172_concurrent_dup_insert"

# The index keys on lower(btrim(email)); each pair must normalise identically so
# the second concurrent insert is a true duplicate at the DB level.
_BASE = "alice@example.com"
_DECORATION_PAIRS = [
    (_BASE, _BASE),                       # identical strings
    (_BASE, _BASE.upper()),               # case-only difference
    (_BASE, "   " + _BASE + "   "),       # surrounding-whitespace difference
    ("  " + _BASE.upper() + " ", _BASE),  # case + whitespace difference
]


# ---------------------------------------------------------------------------
# Engine / session / cleanup helpers (fresh engine per scenario).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        # Two live connections are required for two genuinely concurrent txns.
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
            await session.execute(
                sa_text(f"DELETE FROM staff_members WHERE org_id IN ({org_subq})"),
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


async def _seed_org(factory) -> uuid.UUID:
    """Create + COMMIT one subscription plan and one org; return the org id.

    The org must be committed so both concurrent transactions can see it and
    satisfy the ``staff_members.org_id`` FK.
    """
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
            return org.id


# ---------------------------------------------------------------------------
# Concurrent insert worker.
# ---------------------------------------------------------------------------


async def _insert_worker(
    factory,
    *,
    org_id: uuid.UUID,
    email: str,
    staff_id: uuid.UUID,
    barrier: asyncio.Barrier,
) -> dict:
    """One concurrent request: insert an active staff row, then commit.

    Both workers rendezvous at ``barrier`` *after* opening their transaction and
    staging the row but *before* issuing the INSERT, so both transactions are
    live simultaneously — the genuine R1.4 race. Exactly one INSERT wins the
    ``uq_staff_active_email_per_org`` lock and commits; the other raises
    ``IntegrityError`` once the winner commits.

    Returns ``{"outcome": "persisted"|"rejected", "staff_id", "error"}``.
    """
    async with factory() as session:
        staff = StaffMember(
            id=staff_id,
            org_id=org_id,
            name="Concurrent Dup Staff",
            first_name="Concurrent",
            last_name="Dup",
            email=email,
            is_active=True,
        )
        session.add(staff)
        try:
            # Both transactions are now open; release them together so the two
            # INSERTs contend for the same normalised-email index key.
            await barrier.wait()
            await session.flush()   # issues INSERT; the loser blocks here...
            await session.commit()  # ...then resolves to a unique violation.
            return {"outcome": "persisted", "staff_id": staff_id, "error": None}
        except IntegrityError as exc:
            await session.rollback()
            return {"outcome": "rejected", "staff_id": staff_id, "error": str(exc)}


async def _run_scenario(email_a: str, email_b: str) -> None:
    """Drive two concurrent duplicate inserts and assert R1.4 holds."""
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        org_id = await _seed_org(factory)

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        barrier = asyncio.Barrier(2)

        results = await asyncio.gather(
            _insert_worker(
                factory, org_id=org_id, email=email_a, staff_id=id_a, barrier=barrier
            ),
            _insert_worker(
                factory, org_id=org_id, email=email_b, staff_id=id_b, barrier=barrier
            ),
        )

        persisted = [r for r in results if r["outcome"] == "persisted"]
        rejected = [r for r in results if r["outcome"] == "rejected"]

        # (1) Exactly one persists, exactly one is rejected (R1.4).
        assert len(persisted) == 1, (
            f"expected exactly one persisted insert, got {len(persisted)} "
            f"for emails {email_a!r} / {email_b!r}: {results!r}"
        )
        assert len(rejected) == 1, (
            f"expected exactly one rejected insert, got {len(rejected)} "
            f"for emails {email_a!r} / {email_b!r}: {results!r}"
        )

        # (2) The rejection is the duplicate determination from the staff index.
        assert "uq_staff_active_email_per_org" in (rejected[0]["error"] or ""), (
            "rejected insert must fail on the active-email uniqueness index; "
            f"got error: {rejected[0]['error']!r}"
        )

        # (3) No partial record: exactly one active staff row exists for this
        # org + normalised email, it is the winner's, and the loser's row id is
        # absent (its whole transaction rolled back). Re-read committed state.
        norm = _BASE.strip().lower()
        async with factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(StaffMember)
                .where(
                    StaffMember.org_id == org_id,
                    StaffMember.is_active.is_(True),
                    func.lower(func.btrim(StaffMember.email)) == norm,
                )
            )
            assert count == 1, (
                f"expected exactly one active staff row for the normalised email, "
                f"found {count}"
            )

            winner_id = persisted[0]["staff_id"]
            loser_id = rejected[0]["staff_id"]

            winner_present = await session.scalar(
                select(func.count())
                .select_from(StaffMember)
                .where(StaffMember.id == winner_id)
            )
            loser_present = await session.scalar(
                select(func.count())
                .select_from(StaffMember)
                .where(StaffMember.id == loser_id)
            )
            assert winner_present == 1, "the persisted worker's row must exist"
            assert loser_present == 0, (
                "the rejected worker must leave NO partial record "
                f"(found {loser_present} rows for loser id {loser_id})"
            )
    finally:
        try:
            await _cleanup(factory)
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("email_a,email_b", _DECORATION_PAIRS)
def test_concurrent_duplicate_active_staff_insert(email_a: str, email_b: str) -> None:
    """Two concurrent active inserts with the same normalised email in one org →
    exactly one persists, the other is rejected with a duplicate error, and the
    rejected request leaves no partial record (R1.4).

    Feature: organisation-employee-portal — Requirement 1.4
    """
    asyncio.run(_run_scenario(email_a, email_b))
