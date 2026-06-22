"""Property-based test for global Org_Slug uniqueness (Task 9.6).

Feature: organisation-employee-portal, Property 6: Global slug uniqueness

Exercises ``app.modules.organisations.service.update_org_slug`` against the real
dev Postgres database (mirroring the DB-backed Hypothesis pattern in
``tests/test_org_scoped_staff_uniqueness_property.py``). The invariant under
test is guarded at the database level by the unique functional index
``uq_organisations_slug_lower ON organisations (lower(slug)) WHERE slug IS NOT
NULL`` (migration 0224) and enforced at the application level by the save-time
uniqueness re-check in ``update_org_slug`` (which raises
``SlugUpdateError(code="slug_taken")`` when the normalised candidate is held by
another organisation).

For each example we seed three organisations, then replay a generated sequence
of slug-assignment operations — each operation assigns a slug (drawn from a
small pool, with case/whitespace variants so collisions and re-normalisation
arise naturally) to one of the orgs. Before each assignment we predict — from
the rules ``update_org_slug`` encodes — whether it will be accepted or rejected
``slug_taken``, and assert the service agrees. After every operation we assert
the global invariants:

1. **No two orgs ever hold the same normalised slug (R2.5)** — checked from the
   persisted ``organisations.slug`` values queried back from the DB.
2. **Assigning a slug held by another org is rejected and stores nothing
   (R2.6)** — the call raises ``SlugUpdateError`` with code ``slug_taken`` and
   the requesting org's stored slug is left unchanged.
3. **Re-assigning an org's own current slug is accepted** — the save-time
   re-check excludes the requesting org, so re-submitting the org's own slug
   succeeds (hard cut-over, D2).

The whole generated sequence runs inside one transaction that is rolled back at
the end of every example, so the test leaves no rows behind. Seeded org names
carry a marker so a module-scoped safety-net fixture can sweep up any rows left
by an example that aborts mid-way. A fresh async engine is created per example
because asyncpg connections are bound to the event loop ``asyncio.run`` creates
— exactly like the reference DB-backed property tests in this repo.

Validates: Requirements 2.5, 2.6

Notes:
- The DB connection honours the ``DATABASE_URL`` env override exposed by
  ``app.config.settings`` (default
  ``postgresql+asyncpg://postgres:postgres@localhost:5434/workshoppro``).
"""

from __future__ import annotations

import asyncio
import uuid

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
# tests/test_org_scoped_staff_uniqueness_property.py).
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
from app.modules.organisations.service import SlugUpdateError, update_org_slug
from app.modules.organisations.slug_service import normalise_slug

# Marker baked into seeded org names so a safety-net sweep can find orphans even
# when an example aborts mid-way (every example otherwise rolls back cleanly).
_ORG_MARKER = "TEST_9_6_global_slug"

# Number of orgs competing for slugs in every example.
_NUM_ORGS = 3


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------

# A small pool of valid, NON-reserved base slugs so collisions arise naturally
# within a sequence (each passes ``validate_slug_format`` and is not in
# ``RESERVED_SLUGS``).
_SLUG_BASES = ["alpha-one", "beta-two", "gamma-three", "delta-four"]

# Decorations that all normalise (trim + lowercase) back to the base, so the
# uniqueness check is exercised in a case-insensitive way (R2.8). Only ASCII
# spaces are used so Python ``str.strip()`` and the service's normalisation
# agree exactly.
_SLUG_DECORATIONS = [
    lambda s: s,
    lambda s: s.upper(),
    lambda s: s.replace("-", "-").title(),  # Title-case, hyphen preserved
    lambda s: "  " + s,
    lambda s: s + "  ",
    lambda s: " " + s.upper() + " ",
]


@st.composite
def _assignment(draw):
    """Generate one slug-assignment op: (org_index, raw_slug)."""
    org_index = draw(st.integers(min_value=0, max_value=_NUM_ORGS - 1))
    base = draw(st.sampled_from(_SLUG_BASES))
    decorate = draw(st.sampled_from(_SLUG_DECORATIONS))
    return {"org_index": org_index, "raw_slug": decorate(base)}


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


async def _seed_orgs(session) -> list[uuid.UUID]:
    """Create one subscription plan + N orgs (flush only; rolled back later)."""
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

    org_ids: list[uuid.UUID] = []
    for _ in range(_NUM_ORGS):
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
        org_ids.append(org.id)
    return org_ids


async def _db_slugs(session, org_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Return the persisted (flushed) slug for each org, queried from the DB."""
    rows = (
        await session.execute(
            select(Organisation.id, Organisation.slug).where(
                Organisation.id.in_(org_ids)
            )
        )
    ).all()
    return {oid: slug for oid, slug in rows}


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(ops: list[dict]) -> None:
    """Replay the slug-assignment sequence; assert accept/reject + invariants."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_ids = await _seed_orgs(session)
                user_id = uuid.uuid4()  # audit_log.user_id has no FK — any uuid is fine.

                # Model of which normalised slug each org currently holds.
                model: dict[uuid.UUID, str | None] = {oid: None for oid in org_ids}

                for op in ops:
                    org_id = org_ids[op["org_index"]]
                    raw = op["raw_slug"]
                    normalised = normalise_slug(raw)

                    # Predict: rejected iff a DIFFERENT org currently holds the
                    # normalised slug (R2.6). Re-assigning the org's own slug is
                    # accepted (save-time re-check excludes the requesting org).
                    holder = next(
                        (
                            oid
                            for oid, s in model.items()
                            if s == normalised and oid != org_id
                        ),
                        None,
                    )
                    should_reject = holder is not None
                    previous_own = model[org_id]

                    if should_reject:
                        with pytest.raises(SlugUpdateError) as excinfo:
                            await update_org_slug(
                                session,
                                org_id=org_id,
                                user_id=user_id,
                                candidate=raw,
                            )
                        assert excinfo.value.code == "slug_taken", (
                            f"expected slug_taken for {raw!r} (held by another org), "
                            f"got code={excinfo.value.code!r}"
                        )
                        # Stores nothing: the requesting org's slug is unchanged.
                        db_slugs = await _db_slugs(session, org_ids)
                        assert db_slugs[org_id] == previous_own, (
                            f"rejected assignment must not change the org's slug: "
                            f"expected {previous_own!r}, got {db_slugs[org_id]!r}"
                        )
                    else:
                        stored = await update_org_slug(
                            session,
                            org_id=org_id,
                            user_id=user_id,
                            candidate=raw,
                        )
                        # Stored normalised (R2.7) and equals the prediction.
                        assert stored == normalised, (
                            f"stored slug {stored!r} != normalised {normalised!r}"
                        )
                        model[org_id] = normalised
                        # Confirm the persisted value matches.
                        db_slugs = await _db_slugs(session, org_ids)
                        assert db_slugs[org_id] == normalised, (
                            f"DB slug {db_slugs[org_id]!r} != accepted {normalised!r}"
                        )

                    # --- Global invariant after EVERY op (R2.5): no two orgs
                    # hold the same normalised slug, checked from the DB. ------
                    db_slugs = await _db_slugs(session, org_ids)
                    held = [s for s in db_slugs.values() if s is not None]
                    assert len(held) == len(set(held)), (
                        f"two orgs hold the same normalised slug: {db_slugs!r}"
                    )
                    # The DB and the model must agree.
                    assert db_slugs == model, (
                        f"DB state {db_slugs!r} diverged from model {model!r}"
                    )
            finally:
                # Never persist — discard the whole generated sequence.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Safety-net cleanup (examples roll back, but sweep any orphan from an abort).
# ---------------------------------------------------------------------------


async def _cleanup(factory) -> None:
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            await session.execute(
                sa_text(f"DELETE FROM audit_log WHERE org_id IN ({org_subq})"),
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


# ---------------------------------------------------------------------------
# Property 6: Global slug uniqueness.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(ops=st.lists(_assignment(), min_size=1, max_size=10))
def test_global_slug_uniqueness(ops: list[dict]):
    """Property 6: Global slug uniqueness.

    # Feature: organisation-employee-portal, Property 6: Global slug uniqueness

    For any sequence of slug-assignment operations across organisations, applied
    through ``update_org_slug`` against the real database:

    - no two distinct organisations ever simultaneously hold the same normalised
      slug (R2.5, DB-enforced by ``uq_organisations_slug_lower``);
    - an attempt to assign a slug already held by ANOTHER organisation is
      rejected with ``SlugUpdateError(code="slug_taken")`` and stores nothing —
      the requesting org's slug is left unchanged (R2.6); and
    - re-assigning an org's own current slug is accepted (the save-time
      uniqueness re-check excludes the requesting org).

    Each operation's accept/reject outcome is predicted from those rules and the
    service's actual behaviour must match; the no-duplicate invariant is
    re-checked from persisted state after every operation.

    **Validates: Requirements 2.5, 2.6**
    """
    asyncio.run(_run_example(ops))


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
