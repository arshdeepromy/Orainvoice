"""Property-based test: application duplicate-check equals database determination.

# Feature: organisation-employee-portal, Property 3: Application duplicate-check equals database determination

**Validates: Requirements 1.9, 5.2**

Confirms that the application-level pre-check
``StaffService._check_duplicates`` (``app/modules/staff/service.py``, aligned in
task 4.1) reaches the *same* duplicate determination as the database partial
unique indexes created by migration ``0224``:

- ``uq_staff_active_email_per_org``      —
  ``(org_id, lower(btrim(email)))      WHERE is_active AND email IS NOT NULL AND btrim(email) <> ''``
- ``uq_staff_active_employee_id_per_org`` —
  ``(org_id, employee_id)              WHERE is_active AND employee_id IS NOT NULL AND btrim(employee_id) <> ''``

For every example we seed one organisation with a generated population of staff
members (a mix of active/inactive rows with overlapping emails / employee
identifiers, plus an optional same-email row in a *second* organisation to
exercise org-scoping). The seeded population is first reduced in Python to a
state that is itself valid under the two indexes — modelling the real,
already-constrained database — by flipping later active collisions to inactive.

Then, for a generated *candidate* (email + employee identifier) we:

1. **App determination** — call ``_check_duplicates`` for the main org and
   record whether it raises :class:`DuplicateStaffError` ("duplicate").
2. **DB determination** — attempt to ``INSERT`` an active staff row with the
   candidate email/employee_id inside a SAVEPOINT, catch any
   :class:`IntegrityError` (the partial unique index rejecting the insert),
   and roll the savepoint back so the seeded population is untouched.
3. **Parity assertion** — assert the app said "duplicate" *iff* the DB rejected
   the insert. Both sides use identical trim+lowercase normalisation for email
   (``str.strip().lower()`` vs ``lower(btrim(...))``) and identical active /
   non-empty scoping, so the two determinations must agree on every input.

The candidate generators deliberately exercise the normalisation surface that
matters for parity (case variants and surrounding whitespace on emails, blank
and ``None`` values, case variants on employee ids) while staying inside the
input space where the app check and the DB index are defined to agree — i.e.
employee identifiers carry no surrounding whitespace, since the email indexes
trim but the ``employee_id`` index keys on the raw value.

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` so the suite runs against the local dev Postgres
  (``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
- A fresh async engine is created per example (asyncpg connections are bound to
  the event loop ``asyncio.run`` creates), exactly like the reference DB-backed
  property tests in this repo.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_onboarding_persist_identity_property.py).
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
from app.modules.staff.service import DuplicateStaffError, StaffService

# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way. Distinct from the other DB property tests so
# parallel/interleaved runs never trample each other's fixtures.
_ORG_MARKER = "TEST_4_5_dup_parity"

# Shared pools so generated candidates and seeded rows collide frequently.
_EMAIL_LOCALS = ("alice", "bob", "carol")
_EMPLOYEE_IDS = ("E1", "E2", "EMP-100")


# ---------------------------------------------------------------------------
# Normalisation mirrors (Python copies of the app + DB rules, for seed pruning).
# ---------------------------------------------------------------------------


def _norm_email(value: str | None) -> str | None:
    """``lower(btrim(email))`` with the ``btrim(email) <> ''`` index guard.

    Returns the normalised key, or ``None`` when the value is absent/blank and
    therefore excluded from ``uq_staff_active_email_per_org``.
    """
    if value is None:
        return None
    trimmed = value.strip()
    if trimmed == "":
        return None
    return trimmed.lower()


def _norm_employee_id(value: str | None) -> str | None:
    """Index key for ``uq_staff_active_employee_id_per_org``.

    The index keys on the *raw* ``employee_id`` (no trim/lower) with only a
    ``btrim(employee_id) <> ''`` guard. Generated identifiers never carry
    surrounding whitespace, so ``strip()`` here only detects the blank case.
    """
    if value is None:
        return None
    if value.strip() == "":
        return None
    return value


# ---------------------------------------------------------------------------
# Generators.
# ---------------------------------------------------------------------------


def _email_strategy() -> st.SearchStrategy[str | None]:
    """Emails exercising the trim/lower parity surface, plus absent/blank."""
    base = st.sampled_from(_EMAIL_LOCALS).flatmap(
        lambda local: st.sampled_from(
            [
                f"{local}@example.com",
                f"{local.upper()}@EXAMPLE.COM",
                f"  {local}@example.com  ",
                f"{local.capitalize()}@Example.com",
            ]
        )
    )
    return st.one_of(
        base,
        st.none(),
        st.just(""),
        st.just("   "),
    )


def _employee_id_strategy() -> st.SearchStrategy[str | None]:
    """Employee identifiers (case variants, no surrounding whitespace) + blank."""
    base = st.sampled_from(_EMPLOYEE_IDS).flatmap(
        lambda eid: st.sampled_from([eid, eid.lower(), eid.upper()])
    )
    return st.one_of(
        base,
        st.none(),
        st.just(""),
        st.just("   "),
    )


@dataclass
class _SeedRow:
    email: str | None
    employee_id: str | None
    is_active: bool
    in_main_org: bool  # False => the second (other) org


_seed_row_strategy = st.builds(
    _SeedRow,
    email=_email_strategy(),
    employee_id=_employee_id_strategy(),
    is_active=st.booleans(),
    in_main_org=st.integers(min_value=0, max_value=4).map(lambda n: n != 0),
)


_example_strategy = st.fixed_dictionaries(
    {
        "population": st.lists(_seed_row_strategy, min_size=0, max_size=6),
        "candidate_email": _email_strategy(),
        "candidate_employee_id": _employee_id_strategy(),
    }
)


# ---------------------------------------------------------------------------
# Engine / session helpers (fresh engine per example — bound to the run loop).
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        poolclass=NullPool,
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
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


def _prune_to_valid_population(rows: list[_SeedRow]) -> list[_SeedRow]:
    """Reduce the generated rows to a state valid under both unique indexes.

    Models the real, already-constrained database: at most one active row per
    org per normalised email / employee identifier. A later active row that
    would collide with an earlier kept active row is flipped to inactive
    (inactive rows are unconstrained), so seeding never trips the indexes.
    """
    active_emails: set[tuple[bool, str]] = set()
    active_empids: set[tuple[bool, str]] = set()
    pruned: list[_SeedRow] = []
    for row in rows:
        is_active = row.is_active
        if is_active:
            ne = _norm_email(row.email)
            nx = _norm_employee_id(row.employee_id)
            org_key = row.in_main_org
            collides = (ne is not None and (org_key, ne) in active_emails) or (
                nx is not None and (org_key, nx) in active_empids
            )
            if collides:
                is_active = False
            else:
                if ne is not None:
                    active_emails.add((org_key, ne))
                if nx is not None:
                    active_empids.add((org_key, nx))
        pruned.append(
            _SeedRow(
                email=row.email,
                employee_id=row.employee_id,
                is_active=is_active,
                in_main_org=row.in_main_org,
            )
        )
    return pruned


async def _seed(factory, population: list[_SeedRow]) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed two orgs + the pruned staff population; return (main_org, other_org)."""
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

            main_org = Organisation(
                name=f"{_ORG_MARKER}_main_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            other_org = Organisation(
                name=f"{_ORG_MARKER}_other_{uuid.uuid4().hex[:8]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={},
            )
            session.add_all([main_org, other_org])
            await session.flush()

            for row in population:
                org_id = main_org.id if row.in_main_org else other_org.id
                session.add(
                    StaffMember(
                        org_id=org_id,
                        name="Seed Staff",
                        email=row.email,
                        employee_id=row.employee_id,
                        is_active=row.is_active,
                    )
                )
            await session.flush()

            return main_org.id, other_org.id


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(example: dict) -> None:
    population = _prune_to_valid_population(example["population"])
    candidate_email = example["candidate_email"]
    candidate_employee_id = example["candidate_employee_id"]

    engine, factory = await _make_engine_and_factory()
    try:
        main_org_id, _other_org_id = await _seed(factory, population)

        # --- 1. Application-level determination. ---
        async with factory() as session:
            svc = StaffService(session)
            app_says_duplicate = False
            try:
                await svc._check_duplicates(
                    main_org_id,
                    email=candidate_email,
                    phone=None,
                    employee_id=candidate_employee_id,
                )
            except DuplicateStaffError:
                app_says_duplicate = True

        # --- 2. Database determination (insert in a savepoint, then undo). ---
        async with factory() as session:
            async with session.begin():
                db_rejects = False
                try:
                    async with session.begin_nested():
                        session.add(
                            StaffMember(
                                org_id=main_org_id,
                                name="Candidate Staff",
                                email=candidate_email,
                                employee_id=candidate_employee_id,
                                is_active=True,
                            )
                        )
                        await session.flush()
                except IntegrityError:
                    # The partial unique index rejected the candidate; the
                    # savepoint has been rolled back so the population is intact.
                    db_rejects = True

        # --- 3. Parity. ---
        assert app_says_duplicate == db_rejects, (
            "app/DB duplicate determination disagreed for "
            f"candidate email={candidate_email!r} employee_id={candidate_employee_id!r}: "
            f"app_says_duplicate={app_says_duplicate}, db_rejects={db_rejects}"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3: Application duplicate-check equals database determination.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(example=_example_strategy)
def test_app_duplicate_check_matches_db_determination(example: dict):
    """Property 3: the app-level duplicate check returns "duplicate" iff the
    database partial unique index would reject inserting the candidate.

    **Validates: Requirements 1.9, 5.2**
    """
    asyncio.run(_run_example(example))


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
