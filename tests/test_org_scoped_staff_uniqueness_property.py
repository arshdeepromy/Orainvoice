"""Property-based test for org-scoped active staff identity uniqueness (Task 4.3).

Feature: organisation-employee-portal, Property 1: Org-scoped active staff identity uniqueness

Exercises the DB-level partial unique indexes introduced by migration 0224 —
``uq_staff_active_email_per_org`` and ``uq_staff_active_employee_id_per_org`` —
against the real dev Postgres database (mirroring the DB-backed Hypothesis
pattern in ``tests/test_onboarding_revocation_property.py``).

For each example we seed two organisations and then attempt to insert a
generated population of ``staff_members`` rows one at a time, each inside its
own SAVEPOINT. Before each insert we predict — from the rules the two indexes
encode — whether the DB will accept or reject the row, and assert the DB agrees:

1. **Per-org case-insensitive active email uniqueness (R1.2, R1.5)** — at most
   one ``is_active`` row per org for a given normalised email, where
   normalisation is ``lower(btrim(email))`` (trim + lowercase). A second active
   row in the SAME org whose email normalises identically is rejected; the
   existing row is left untouched.
2. **Per-org active non-empty employee-id uniqueness (R1.3)** — at most one
   ``is_active`` row per org for a given non-empty ``employee_id``.
3. **Same email allowed across different orgs (R1.6)** — an identical
   normalised email may be active in a *different* org; uniqueness is scoped
   to a single org, never global.
4. **Inactive duplicates are unconstrained** — rows with ``is_active = false``
   (and rows with an empty/whitespace email or empty employee_id) never trip
   either index, so arbitrarily many may coexist.

The whole population is inserted inside one transaction that is rolled back at
the end of every example, so the test leaves no rows behind (no marker-based
cleanup required). A fresh async engine is created per example because asyncpg
connections are bound to the event loop ``asyncio.run`` creates — exactly like
the reference DB-backed property tests in this repo.

Validates: Requirements 1.2, 1.3, 1.5, 1.6

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB tests in
# tests/test_onboarding_revocation_property.py).
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
from app.modules.staff.models import StaffMember


# ---------------------------------------------------------------------------
# Generation strategies
# ---------------------------------------------------------------------------

# A small pool of base emails so collisions arise naturally within ~100 examples.
_EMAIL_BASES = ["alice@example.com", "bob@example.com"]

# Whitespace/case decorations that all normalise (btrim + lower) to the base.
# NOTE: only ASCII spaces are used so Python ``str.strip()`` and SQL ``btrim``
# agree exactly on the normalised form.
_EMAIL_DECORATIONS = [
    lambda s: s,
    lambda s: s.upper(),
    lambda s: s.title(),
    lambda s: "  " + s,
    lambda s: s + "  ",
    lambda s: " " + s.upper() + " ",
]


@st.composite
def _staff_spec(draw):
    """Generate one staff row spec: (org_index, email, employee_id, is_active)."""
    org_index = draw(st.integers(min_value=0, max_value=1))

    email_kind = draw(st.sampled_from(["real", "real", "empty", "none"]))
    if email_kind == "none":
        email = None
    elif email_kind == "empty":
        email = draw(st.sampled_from(["", "   "]))
    else:
        base = draw(st.sampled_from(_EMAIL_BASES))
        decorate = draw(st.sampled_from(_EMAIL_DECORATIONS))
        email = decorate(base)

    # employee_id is an EXACT-match constraint (no normalisation in the index),
    # gated only by ``btrim(employee_id) <> ''`` — so empty/whitespace/None are
    # unconstrained. Generate exact values without case/space variation.
    employee_id = draw(st.sampled_from([None, "", "EMP-1", "EMP-2"]))

    is_active = draw(st.booleans())
    return {
        "org_index": org_index,
        "email": email,
        "employee_id": employee_id,
        "is_active": is_active,
    }


# ---------------------------------------------------------------------------
# Prediction — mirrors exactly what the two partial unique indexes enforce.
# ---------------------------------------------------------------------------


def _norm_email(email: str | None) -> str | None:
    """lower(btrim(email)); None when absent or whitespace-only (unconstrained)."""
    if email is None:
        return None
    trimmed = email.strip()
    return trimmed.lower() if trimmed else None


def _empid_key(employee_id: str | None) -> str | None:
    """Exact employee_id; None when absent or whitespace-only (unconstrained)."""
    if employee_id is None:
        return None
    return employee_id if employee_id.strip() else None


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


async def _seed_two_orgs(session) -> list[uuid.UUID]:
    """Create one subscription plan + two orgs (flush only; rolled back later)."""
    plan = SubscriptionPlan(
        name=f"uniqueness_prop_plan_{uuid.uuid4().hex[:8]}",
        monthly_price_nzd=0,
        user_seats=5,
        storage_quota_gb=1,
        carjam_lookups_included=0,
        enabled_modules=[],
    )
    session.add(plan)
    await session.flush()

    org_ids: list[uuid.UUID] = []
    for _ in range(2):
        org = Organisation(
            name=f"uniqueness_prop_org_{uuid.uuid4().hex[:8]}",
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


# ---------------------------------------------------------------------------
# Per-example driver.
# ---------------------------------------------------------------------------


async def _run_example(specs: list[dict]) -> None:
    """Insert the generated population; assert DB accept/reject matches prediction."""
    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                org_ids = await _seed_two_orgs(session)

                # Persisted ACTIVE keys, scoped per org.
                active_emails: set[tuple[uuid.UUID, str]] = set()
                active_empids: set[tuple[uuid.UUID, str]] = set()
                cross_org_email_accepted = False

                for spec in specs:
                    org_id = org_ids[spec["org_index"]]
                    norm_email = _norm_email(spec["email"])
                    empid_key = _empid_key(spec["employee_id"])

                    email_collision = (
                        spec["is_active"]
                        and norm_email is not None
                        and (org_id, norm_email) in active_emails
                    )
                    empid_collision = (
                        spec["is_active"]
                        and empid_key is not None
                        and (org_id, empid_key) in active_empids
                    )
                    should_fail = email_collision or empid_collision

                    staff = StaffMember(
                        org_id=org_id,
                        name="Prop Test Staff",
                        first_name="Prop",
                        last_name="Test",
                        email=spec["email"],
                        employee_id=spec["employee_id"],
                        is_active=spec["is_active"],
                    )

                    accepted = True
                    try:
                        async with session.begin_nested():
                            session.add(staff)
                            await session.flush()
                    except IntegrityError:
                        accepted = False

                    # Core invariant: the DB's accept/reject decision must match
                    # the rules the two partial unique indexes encode.
                    assert accepted == (not should_fail), (
                        f"DB accepted={accepted} but predicted should_fail={should_fail} "
                        f"for spec={spec!r} "
                        f"(norm_email={norm_email!r}, empid_key={empid_key!r})"
                    )

                    if accepted and spec["is_active"]:
                        # R1.6 coverage signal: an email already active in the
                        # OTHER org was just accepted in this org.
                        if norm_email is not None:
                            if any(
                                oid != org_id
                                for (oid, e) in active_emails
                                if e == norm_email
                            ):
                                cross_org_email_accepted = True
                            active_emails.add((org_id, norm_email))
                        if empid_key is not None:
                            active_empids.add((org_id, empid_key))

                # The test's correctness does not depend on cross_org_email being
                # exercised in every example, but when it is, it confirms R1.6.
                _ = cross_org_email_accepted
            finally:
                # Never persist — discard the whole generated population.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 1: Org-scoped active staff identity uniqueness.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(specs=st.lists(_staff_spec(), min_size=1, max_size=8))
def test_org_scoped_active_staff_identity_uniqueness(specs: list[dict]):
    """Property 1: Org-scoped active staff identity uniqueness.

    # Feature: organisation-employee-portal, Property 1: Org-scoped active staff identity uniqueness

    Over a generated population of staff rows inserted into the real database,
    the DB-level partial unique indexes guarantee that, after applying the
    uniqueness rules:

    - no two ACTIVE staff in the same org share a normalised (trim+lowercase)
      email (R1.2, R1.5),
    - no two ACTIVE staff in the same org share a non-empty ``employee_id``
      (R1.3),
    - the same normalised email MAY be active in different orgs (R1.6), and
    - inactive rows (and empty-email / empty-employee-id rows) are unconstrained.

    Each insert is predicted accept/reject from those rules and the DB's actual
    decision must match.

    **Validates: Requirements 1.2, 1.3, 1.5, 1.6**
    """
    asyncio.run(_run_example(specs))
