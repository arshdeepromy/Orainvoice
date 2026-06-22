"""Property-based test for Employee_Portal enablement requiring a valid slug (Task 9.7).

Feature: organisation-employee-portal, Property 9: Enabling the portal requires a valid slug

Exercises ``app.modules.organisations.service.set_employee_portal_enabled``
against the real dev Postgres database (mirroring the DB-backed Hypothesis
pattern in ``tests/test_global_slug_uniqueness_property.py`` and
``tests/test_org_scoped_staff_uniqueness_property.py``). The invariant under
test is R4.4: the Employee_Portal may only be enabled for an organisation that
already holds a valid slug. Enabling an org with no slug must be rejected with
``EmployeePortalToggleError(code="slug_required")`` carrying a human-readable
"set a slug first" message, and must leave the ``employee_portal_enabled`` flag
disabled (no partial write). Disabling always succeeds regardless of slug.

For each example we seed several organisations — some with a valid slug set,
some without — then replay a generated sequence of enable/disable operations
against ``set_employee_portal_enabled``. Before each operation we predict, from
the rule the service encodes, whether it will succeed or be rejected
``slug_required``, and assert the service agrees. After every operation we
re-read the persisted ``employee_portal_enabled`` flag from the database and
assert it matches the expected state:

1. **Enable succeeds only with a valid slug set (R4.4)** — an enable on an org
   that holds a slug persists ``employee_portal_enabled = True``.
2. **Enable with no slug is rejected and stores nothing (R4.4)** — the call
   raises ``EmployeePortalToggleError(code="slug_required")`` with a non-empty,
   human-readable message mentioning the slug, and the flag remains disabled.
3. **Disable always succeeds** — regardless of whether a slug is set, disabling
   persists ``employee_portal_enabled = False`` (and deletes the org's sessions).

The whole generated sequence runs inside one transaction that is rolled back at
the end of every example, so the test leaves no rows behind. Seeded org names
carry a marker so a module-scoped safety-net fixture can sweep up any rows left
by an example that aborts mid-way. A fresh async engine is created per example
because asyncpg connections are bound to the event loop ``asyncio.run`` creates
— exactly like the reference DB-backed property tests in this repo.

Validates: Requirements 4.4

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
from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_global_slug_uniqueness_property.py).
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
from app.modules.employee_portal import models as _employee_portal_models  # noqa: F401
from app.modules.compliance_docs import models as _compliance_models  # noqa: F401

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.organisations.service import (
    EmployeePortalToggleError,
    set_employee_portal_enabled,
)

# Marker baked into seeded org names so a safety-net sweep can find orphans even
# when an example aborts mid-way (every example otherwise rolls back cleanly).
_ORG_MARKER = "TEST_9_7_portal_enable_slug"


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------


@st.composite
def _scenario(draw):
    """Generate a population of orgs (some with a slug) + an op sequence.

    Returns ``(slug_flags, ops)`` where ``slug_flags[i]`` says whether org ``i``
    is seeded with a valid slug, and each op is ``(org_index, desired_enabled)``.
    """
    # Between 2 and 4 orgs; at least one with and one without a slug is likely
    # but not forced, so all-with / all-without populations are also exercised.
    num_orgs = draw(st.integers(min_value=2, max_value=4))
    slug_flags = draw(
        st.lists(st.booleans(), min_size=num_orgs, max_size=num_orgs)
    )
    ops = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=num_orgs - 1),
                st.booleans(),
            ),
            min_size=1,
            max_size=12,
        )
    )
    return slug_flags, ops


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


def _fresh_slug() -> str:
    """A unique, valid, non-reserved slug (3-63 chars, ^[a-z0-9]+(-[a-z0-9]+)*$)."""
    return f"e97-{uuid.uuid4().hex[:12]}"


async def _seed_orgs(session, slug_flags: list[bool]) -> list[uuid.UUID]:
    """Create one subscription plan + the orgs (flush only; rolled back later).

    Org ``i`` is given a fresh valid slug iff ``slug_flags[i]`` is True; every
    org starts with empty settings, so ``employee_portal_enabled`` reads as the
    disabled default.
    """
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
    for has_slug in slug_flags:
        org = Organisation(
            name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:8]}",
            plan_id=plan.id,
            status="active",
            storage_quota_gb=1,
            locale="en",
            settings={},
            slug=_fresh_slug() if has_slug else None,
        )
        session.add(org)
        await session.flush()
        org_ids.append(org.id)
    return org_ids


async def _db_enabled(session, org_id: uuid.UUID) -> bool:
    """Re-read the persisted ``employee_portal_enabled`` flag from the DB."""
    settings_json = (
        await session.execute(
            select(Organisation.settings).where(Organisation.id == org_id)
        )
    ).scalar_one()
    settings_json = settings_json or {}
    return bool(settings_json.get("employee_portal_enabled", False))


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(slug_flags: list[bool], ops: list[tuple]) -> None:
    """Replay the enable/disable sequence; assert accept/reject + flag state."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_ids = await _seed_orgs(session, slug_flags)
                has_slug = {oid: flag for oid, flag in zip(org_ids, slug_flags)}
                user_id = uuid.uuid4()  # audit_log.user_id has no FK — any uuid is fine.

                # Model of each org's persisted enabled flag (seeded disabled).
                model: dict[uuid.UUID, bool] = {oid: False for oid in org_ids}

                for org_index, desired_enabled in ops:
                    org_id = org_ids[org_index]
                    previous = model[org_id]

                    # Predict: an ENABLE on a slug-less org is rejected
                    # ``slug_required`` (R4.4); everything else succeeds.
                    should_reject = desired_enabled and not has_slug[org_id]

                    if should_reject:
                        with pytest.raises(EmployeePortalToggleError) as excinfo:
                            await set_employee_portal_enabled(
                                session,
                                org_id=org_id,
                                user_id=user_id,
                                enabled=True,
                            )
                        err = excinfo.value
                        assert err.code == "slug_required", (
                            f"expected slug_required when enabling a slug-less org, "
                            f"got code={err.code!r}"
                        )
                        # Human-readable "set a slug first" message.
                        assert isinstance(err.message, str) and err.message.strip(), (
                            "slug_required error must carry a human-readable message"
                        )
                        assert "slug" in err.message.lower(), (
                            f"message should mention the slug, got {err.message!r}"
                        )
                        # Stores nothing: the flag is left at its previous value.
                        flag = await _db_enabled(session, org_id)
                        assert flag == previous, (
                            f"rejected enable must not change the flag: expected "
                            f"{previous!r}, got {flag!r}"
                        )
                    else:
                        returned = await set_employee_portal_enabled(
                            session,
                            org_id=org_id,
                            user_id=user_id,
                            enabled=desired_enabled,
                        )
                        assert returned == desired_enabled, (
                            f"set_employee_portal_enabled returned {returned!r}, "
                            f"expected {desired_enabled!r}"
                        )
                        model[org_id] = desired_enabled
                        # Confirm the persisted value matches the desired state.
                        flag = await _db_enabled(session, org_id)
                        assert flag == desired_enabled, (
                            f"DB flag {flag!r} != applied {desired_enabled!r}"
                        )

                    # --- Invariant after EVERY op: the portal is enabled ONLY
                    # for orgs that hold a slug (R4.4). Re-checked from the DB. -
                    for oid in org_ids:
                        persisted = await _db_enabled(session, oid)
                        assert persisted == model[oid], (
                            f"DB flag {persisted!r} diverged from model "
                            f"{model[oid]!r} for org {oid}"
                        )
                        if persisted:
                            assert has_slug[oid], (
                                f"org {oid} has the portal enabled with NO slug set"
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
                sa_text(
                    f"DELETE FROM employee_portal_sessions WHERE org_id IN ({org_subq})"
                ),
                params,
            )
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
# Property 9: Enabling the portal requires a valid slug.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(scenario=_scenario())
def test_portal_enable_requires_valid_slug(scenario):
    """Property 9: Enabling the portal requires a valid slug.

    # Feature: organisation-employee-portal, Property 9: Enabling the portal requires a valid slug

    For any population of organisations (some with a slug, some without) and any
    sequence of enable/disable operations applied through
    ``set_employee_portal_enabled`` against the real database:

    - enabling succeeds ONLY when the org holds a valid slug, persisting
      ``employee_portal_enabled = True`` (R4.4);
    - enabling an org with no slug raises
      ``EmployeePortalToggleError(code="slug_required")`` with a human-readable
      "set a slug first" message and leaves the flag disabled (no partial
      write); and
    - disabling always succeeds regardless of whether a slug is set.

    Each operation's accept/reject outcome is predicted from that rule and the
    service's actual behaviour must match; after every operation the persisted
    flag is re-read from the DB and the portal is asserted enabled only for orgs
    that hold a slug.

    **Validates: Requirements 4.4**
    """
    slug_flags, ops = scenario
    asyncio.run(_run_example(slug_flags, ops))


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
