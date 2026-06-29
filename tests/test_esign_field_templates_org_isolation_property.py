"""Property-based test for Property 25: Field templates are strictly org-isolated.

# Feature: esignature-field-placement, Property: Field templates are strictly org-isolated

Exercises the saved-Field_Template CRUD service
(``app.modules.esignatures.templates_service`` — ``create_template`` /
``list_templates`` / ``get_template`` / ``delete_template``) against the real
dev Postgres database, over the
:class:`~app.modules.esignatures.models.EsignFieldTemplate` ORM model
(``esign_field_templates`` table, ``tenant_isolation`` RLS policy from migration
``0234``).

The property under test
-----------------------
For any two organisations each owning one or more Field_Templates, the service
is **strictly org-scoped** (RLS context + the service's explicit ``org_id``
predicate — the belt-and-braces ownership check in ``templates_service``):

* ``list_templates`` while scoped to org A returns exactly org A's templates and
  **never** any of org B's (and the mirror for org B);
* ``get_template`` returns a template under its owning org but raises a humanized
  **404** (``template_not_found``) when read under the wrong org — it never
  confirms the template exists for another organisation;
* ``delete_template`` scoped to org A **cannot** remove org B's template (raises
  404 and leaves org B's template intact), while a same-org delete succeeds and
  the row is then gone.

A Field_Template **stores roles, never people**: the persisted ``fields`` carry
only an abstract ``template_role`` slot (never a recipient name/email), which the
test asserts on every saved row (R17.1).

How each example is exercised
-----------------------------
Each Hypothesis example, inside a single transaction rolled back at the end:

1. picks two distinct org ids and a generated set of template payloads for each;
2. creates org A's templates under ``app.current_org_id`` = A and org B's under
   ``app.current_org_id`` = B (mirroring how the request session is RLS-scoped in
   production), via the real ``create_template`` service;
3. drives ``list_templates`` / ``get_template`` / ``delete_template`` under each
   org's context and asserts strict isolation.

A fresh async engine is created per example because asyncpg connections are bound
to the event loop ``asyncio.run`` creates — exactly like the reference DB-backed
property tests in this repo (e.g.
``tests/test_payroll_tax_resolution_precedence_property.py``). The transaction is
always rolled back, so nothing leaks between examples.

When Postgres is unreachable the test skips rather than fails red, matching the
other DB-backed tests in this repo. Backend tests run via
``docker compose exec app python -m pytest``.

**Validates: Requirements 17.3, 17.4**
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import the ORM model modules so SQLAlchemy can resolve string-based
# relationships at mapper-configuration time (mirrors the reference DB-backed
# property tests, e.g. tests/test_payroll_tax_resolution_precedence_property.py).
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
from app.modules.esignatures import models as _esign_models  # noqa: F401

from app.modules.esignatures.errors import CODE_TEMPLATE_NOT_FOUND
from app.modules.esignatures.models import EsignFieldTemplate
from app.modules.esignatures.schemas import FieldTemplateCreate
from app.modules.esignatures import templates_service


# ---------------------------------------------------------------------------
# Strategies — generate valid FieldTemplateCreate payloads. Geometry/types are
# kept simple and always in-bounds (this property is about org isolation, not
# validation); the role slots are abstract (no person ever stored, R17.1).
# ---------------------------------------------------------------------------

_FIELD_TYPES = ("signature", "initials", "name", "date", "email", "text")
_ROLE_SLOTS = ("signer 1", "signer 2", "viewer", "approver")
_AGREEMENT_TYPES = (None, "nda", "sales_agreement", "employment_agreement")


@st.composite
def _template_field(draw: st.DrawFn) -> dict:
    ftype = draw(st.sampled_from(_FIELD_TYPES))
    field: dict = {
        "type": ftype,
        "page": draw(st.integers(min_value=1, max_value=5)),
        "position_x": draw(st.floats(min_value=0, max_value=90)),
        "position_y": draw(st.floats(min_value=0, max_value=90)),
        "width": draw(st.floats(min_value=1, max_value=10)),
        "height": draw(st.floats(min_value=1, max_value=10)),
        "required": draw(st.booleans()),
        "template_role": draw(st.sampled_from(_ROLE_SLOTS)),
    }
    # Only text fields carry label/placeholder; keep them simple and benign.
    if ftype == "text":
        field["label"] = draw(st.sampled_from(("Notes", "Comment", "")))
        field["placeholder"] = draw(st.sampled_from(("...", "")))
    return field


@st.composite
def _template_payload(draw: st.DrawFn) -> FieldTemplateCreate:
    fields = draw(st.lists(_template_field(), min_size=1, max_size=4))
    roles = sorted({f["template_role"] for f in fields})
    # Printable, NUL-free name (Postgres text rejects 0x00); non-empty after strip.
    name = draw(
        st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            min_size=1,
            max_size=24,
        ).filter(lambda s: s.strip() != "")
    )
    return FieldTemplateCreate(
        name=name,
        agreement_type=draw(st.sampled_from(_AGREEMENT_TYPES)),
        fields=fields,
        roles=roles,
    )


# A scenario: the per-org template payload lists for two organisations.
_scenario = st.fixed_dictionaries(
    {
        "org_a_templates": st.lists(_template_payload(), min_size=1, max_size=3),
        "org_b_templates": st.lists(_template_payload(), min_size=1, max_size=3),
    }
)


# ---------------------------------------------------------------------------
# Engine / session helpers (mirror the reference DB-backed property tests).
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


async def _db_reachable() -> bool:
    engine = create_async_engine(app_settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 — any connect failure means skip
        return False
    finally:
        await engine.dispose()


_DB_REACHABLE: bool | None = None


def _skip_unless_db() -> None:
    """Skip (once-cached) when Postgres is unreachable, matching the repo pattern."""
    global _DB_REACHABLE
    if _DB_REACHABLE is None:
        _DB_REACHABLE = asyncio.run(_db_reachable())
    if not _DB_REACHABLE:
        pytest.skip("Postgres not reachable for esign field-template isolation test")


async def _set_org_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Scope the session's RLS context to ``org_id`` (as the request does)."""
    await session.execute(
        sa.text("SELECT set_config('app.current_org_id', :oid, true)"),
        {"oid": str(org_id)},
    )


def _assert_not_found(exc: HTTPException) -> None:
    """Assert the raised error is the humanized 404 (never confirms existence)."""
    assert exc.status_code == 404, f"expected 404, got {exc.status_code}"
    detail = exc.detail
    assert isinstance(detail, dict), f"detail must be the {{message, code}} shape: {detail!r}"
    assert detail.get("code") == CODE_TEMPLATE_NOT_FOUND
    # Humanized, leak-free message that does not confirm cross-org existence.
    assert detail.get("message"), "404 must carry a human-readable message"


def _assert_stores_roles_not_people(row: EsignFieldTemplate) -> None:
    """R17.1: a persisted template stores abstract roles, never a person."""
    for field in row.fields:
        assert "template_role" in field, "every stored field must carry a role slot"
        assert "name" not in field, "a template field must not store a recipient name"
        assert "email" not in field, "a template field must not store a recipient email"
    assert all(isinstance(r, str) for r in row.roles)


async def _create_all(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payloads: list[FieldTemplateCreate],
) -> list[uuid.UUID]:
    """Create every payload for ``org_id`` under its RLS context; return the ids."""
    await _set_org_context(session, org_id)
    ids: list[uuid.UUID] = []
    for payload in payloads:
        row = await templates_service.create_template(
            session, org_id=org_id, user_id=None, payload=payload
        )
        _assert_stores_roles_not_people(row)
        assert row.org_id == org_id
        ids.append(row.id)
    return ids


async def _run_example(scenario: dict) -> None:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    engine, factory = await _make_engine_and_factory()
    try:
        async with factory() as session:
            try:
                # --- Seed: org A's templates under A's context, B's under B's.
                a_ids = await _create_all(
                    session, org_id=org_a, payloads=scenario["org_a_templates"]
                )
                b_ids = await _create_all(
                    session, org_id=org_b, payloads=scenario["org_b_templates"]
                )
                await session.flush()

                a_set, b_set = set(a_ids), set(b_ids)
                # Generated org ids are fresh uuids — ids never collide.
                assert a_set.isdisjoint(b_set)

                # --- list_templates is strictly org-scoped (R17.3). ---
                await _set_org_context(session, org_a)
                listed_a = await templates_service.list_templates(session, org_id=org_a)
                listed_a_ids = {item.id for item in listed_a.items}
                assert listed_a_ids == a_set, (
                    "org A must list exactly its own templates; "
                    f"got {listed_a_ids}, expected {a_set}"
                )
                assert listed_a_ids.isdisjoint(b_set), (
                    "org A's listing leaked one of org B's templates"
                )
                assert listed_a.total == len(a_set)

                await _set_org_context(session, org_b)
                listed_b = await templates_service.list_templates(session, org_id=org_b)
                listed_b_ids = {item.id for item in listed_b.items}
                assert listed_b_ids == b_set, (
                    "org B must list exactly its own templates; "
                    f"got {listed_b_ids}, expected {b_set}"
                )
                assert listed_b_ids.isdisjoint(a_set), (
                    "org B's listing leaked one of org A's templates"
                )
                assert listed_b.total == len(b_set)

                # --- get_template: owning org succeeds; wrong org → 404. ---
                await _set_org_context(session, org_a)
                for tid in a_ids:
                    got = await templates_service.get_template(
                        session, org_id=org_a, template_id=tid
                    )
                    assert got.id == tid and got.org_id == org_a
                # Org A may not read any of org B's templates.
                for tid in b_ids:
                    with pytest.raises(HTTPException) as ei:
                        await templates_service.get_template(
                            session, org_id=org_a, template_id=tid
                        )
                    _assert_not_found(ei.value)

                await _set_org_context(session, org_b)
                for tid in a_ids:
                    with pytest.raises(HTTPException) as ei:
                        await templates_service.get_template(
                            session, org_id=org_b, template_id=tid
                        )
                    _assert_not_found(ei.value)

                # --- delete_template: cross-org delete is refused (404) and the
                #     target template survives; same-org delete removes it. ---
                target_b = b_ids[0]
                await _set_org_context(session, org_a)
                with pytest.raises(HTTPException) as ei:
                    await templates_service.delete_template(
                        session, org_id=org_a, template_id=target_b
                    )
                _assert_not_found(ei.value)

                # Org B's template is untouched by org A's failed delete.
                await _set_org_context(session, org_b)
                survived = await templates_service.get_template(
                    session, org_id=org_b, template_id=target_b
                )
                assert survived.id == target_b

                # A same-org delete genuinely removes the row.
                target_a = a_ids[0]
                await _set_org_context(session, org_a)
                await templates_service.delete_template(
                    session, org_id=org_a, template_id=target_a
                )
                await session.flush()
                with pytest.raises(HTTPException) as ei:
                    await templates_service.get_template(
                        session, org_id=org_a, template_id=target_a
                    )
                _assert_not_found(ei.value)
            finally:
                # Never persist — discard the whole generated example.
                await session.rollback()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 25: Field templates are strictly org-isolated.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(scenario=_scenario)
def test_field_templates_are_strictly_org_isolated(scenario: dict) -> None:
    """Property 25: Templates are isolated per organisation.

    # Feature: esignature-field-placement, Property: Field templates are strictly org-isolated

    For any two organisations each owning templates, listing/getting while scoped
    to one org returns only that org's templates and never the other's, and a
    delete scoped to one org cannot remove another org's template — get/delete
    under the wrong org raise a humanized 404 (``template_not_found``). Enforced
    by the ``tenant_isolation`` RLS policy on ``esign_field_templates`` plus the
    service's explicit ``org_id`` predicate. Templates store roles, never people.

    **Validates: Requirements 17.3, 17.4**
    """
    _skip_unless_db()
    asyncio.run(_run_example(scenario))