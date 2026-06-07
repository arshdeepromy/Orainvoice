"""Example/integration tests for ``GET /api/v2/email-preview`` (task 7.1).

These are DB-backed tests that exercise the real preview endpoint end-to-end
through an in-process ASGI client against the dev Postgres database. They seed
real ``organisations`` / ``customers`` / ``invoices`` / ``quotes`` /
``customer_vehicles`` rows, hit the router (with a fake auth middleware that
populates ``request.state`` exactly the way the production auth middleware
does), and assert on the :class:`EmailPreviewResponse` body.

Coverage (per the spec):
  * Preview returns a complete ``EmailPreviewResponse`` for **all 10 template
    types** (R20.1): invoice_issued, invoice_payment_link, payment_received,
    quote_sent, customer_statement, portal_link, and the four vehicle reminder
    types (wof/cof/registration/service).
  * Cross-org IDOR: org A requesting org B's entity → 403/404 (never 200,
    never leaking data) (R25.1, R25.2).
  * Unauthenticated request → 401 (R25.1).
  * Wrong role (global_admin) → 403 (R25.2).

The app DB role bypasses RLS (``rolbypassrls=True``), so tenant isolation on
this read path is enforced by the service's explicit ``org_id`` predicates
(a cross-org/missing entity raises ``EntityNotFound`` → HTTP 404). These tests
therefore assert the *service-level* isolation contract through the endpoint.

Requirements: 20.1, 21.6, 25.1, 25.2
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Import ALL ORM models so SQLAlchemy can resolve string-based relationships
# at mapper-configuration time (otherwise the first ORM query inside the
# endpoint blows up with an unresolved-relationship error).
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

from app.core.database import get_db_session
from app.modules.admin.models import GlobalVehicle, Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.email_compose.router import router as email_compose_router
from app.modules.invoices.models import Invoice
from app.modules.quotes.models import Quote
from app.modules.vehicles.models import CustomerVehicle


# Marker baked into seeded org names so cleanup can find orphans even if a
# test aborts mid-way.
_ORG_MARKER = "TEST_7_1_email_preview"

# The 10 template types and the entity_type each expects (mirrors
# email_compose.service.TEMPLATE_ENTITY_TYPES).
ALL_TEMPLATE_TYPES: list[tuple[str, str]] = [
    ("invoice_issued", "invoice"),
    ("invoice_payment_link", "invoice"),
    ("payment_received", "invoice"),
    ("quote_sent", "quote"),
    ("customer_statement", "customer"),
    ("portal_link", "customer"),
    ("wof_expiry_reminder", "customer_vehicle"),
    ("cof_expiry_reminder", "customer_vehicle"),
    ("registration_expiry_reminder", "customer_vehicle"),
    ("service_due_reminder", "customer_vehicle"),
]

# Every field EmailPreviewResponse declares, with its expected Python type as
# decoded from JSON.
_RESPONSE_FIELD_TYPES: dict[str, type | tuple[type, ...]] = {
    "subject": str,
    "body_html": str,
    "recipients": list,
    "cc": list,
    "bcc": list,
    "variable_context": dict,
    "attachments": list,
    "default_was_template": bool,
    "sender_preview": dict,
    "blocklisted": list,
    "locale": str,
    "email_size_limit_bytes": int,
    "total_budget_seconds": int,
}


# ---------------------------------------------------------------------------
# Engine / session helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Create a fresh async engine + session factory bound to the dev DB."""
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _cleanup(factory) -> None:
    """Delete every row created by the seeders (keyed on the org-name marker).

    Deletes child rows before parents to respect foreign keys. Safe to call
    multiple times.
    """
    async with factory() as session:
        async with session.begin():
            org_subq = (
                "SELECT id FROM organisations WHERE name LIKE :marker"
            )
            params = {"marker": f"{_ORG_MARKER}%"}
            for table in (
                "customer_vehicles",
                "line_items",
                "invoices",
                "quote_line_items",
                "quotes",
                "notification_log",
                "notification_templates",
                "bounced_addresses",
                "customers",
                "invoice_sequences",
                "quote_sequences",
                "org_modules",
                "users",
                "branches",
            ):
                await session.execute(
                    sa_text(
                        f"DELETE FROM {table} WHERE org_id IN ({org_subq})"
                    ),
                    params,
                )
            # Global vehicles are not org-scoped — delete by the test rego prefix.
            await session.execute(
                sa_text("DELETE FROM global_vehicles WHERE rego LIKE :rego"),
                {"rego": "T71%"},
            )
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                params,
            )
            await session.execute(
                sa_text(
                    "DELETE FROM subscription_plans WHERE name = :name"
                ),
                {"name": f"{_ORG_MARKER}_plan"},
            )


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


async def _seed_org(session: AsyncSession, plan, *, suffix: str) -> Organisation:
    org = Organisation(
        name=f"{_ORG_MARKER}_{suffix}",
        plan_id=plan.id,
        status="active",
        storage_quota_gb=1,
        locale="en",
        settings={
            "email": "shop@example.com",
            "phone": "09-555-0000",
            "gst_percentage": 15,
        },
    )
    session.add(org)
    await session.flush()
    return org


async def _seed_user(session: AsyncSession, org) -> User:
    user = User(
        org_id=org.id,
        email=f"u-{uuid.uuid4().hex[:10]}@example.com",
        first_name="Test",
        last_name="Admin",
        role="org_admin",
        password_hash="x",
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_customer(session: AsyncSession, org) -> Customer:
    customer = Customer(
        org_id=org.id,
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.com",
        language="en",
        enable_portal=True,
        portal_token=uuid.uuid4().hex,
    )
    session.add(customer)
    await session.flush()
    return customer


async def _seed_invoice(session: AsyncSession, org, customer, user) -> Invoice:
    invoice = Invoice(
        org_id=org.id,
        customer_id=customer.id,
        created_by=user.id,
        invoice_number="INV-7001",
        status="issued",
        currency="NZD",
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=14),
        subtotal=Decimal("100.00"),
        gst_amount=Decimal("15.00"),
        total=Decimal("115.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("115.00"),
        payment_page_url="https://pay.example.com/inv-7001",
    )
    session.add(invoice)
    await session.flush()
    return invoice


async def _seed_quote(session: AsyncSession, org, customer, user) -> Quote:
    quote = Quote(
        org_id=org.id,
        customer_id=customer.id,
        created_by=user.id,
        quote_number="QUO-7001",
        status="sent",
        subtotal=Decimal("200.00"),
        gst_amount=Decimal("30.00"),
        total=Decimal("230.00"),
        valid_until=date.today() + timedelta(days=30),
        acceptance_token=uuid.uuid4().hex,
    )
    session.add(quote)
    await session.flush()
    return quote


async def _seed_vehicle_link(session: AsyncSession, org, customer) -> CustomerVehicle:
    gv = GlobalVehicle(
        rego=f"T71{uuid.uuid4().hex[:5].upper()}",
        make="Toyota",
        model="Hilux",
        year=2020,
        wof_expiry=date.today() + timedelta(days=20),
        cof_expiry=date.today() + timedelta(days=25),
        registration_expiry=date.today() + timedelta(days=30),
        service_due_date=date.today() + timedelta(days=35),
    )
    session.add(gv)
    await session.flush()

    cv = CustomerVehicle(
        org_id=org.id,
        customer_id=customer.id,
        global_vehicle_id=gv.id,
    )
    session.add(cv)
    await session.flush()
    return cv


async def _seed_full(factory) -> dict:
    """Seed org A (full set of entities) and org B (a single invoice).

    Returns a dict of the ids the tests need.
    """
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

            # Org A — full fixture set.
            org_a = await _seed_org(session, plan, suffix="orgA")
            user_a = await _seed_user(session, org_a)
            cust_a = await _seed_customer(session, org_a)
            invoice_a = await _seed_invoice(session, org_a, cust_a, user_a)
            quote_a = await _seed_quote(session, org_a, cust_a, user_a)
            cv_a = await _seed_vehicle_link(session, org_a, cust_a)

            # Org B — a single invoice used for the IDOR test.
            org_b = await _seed_org(session, plan, suffix="orgB")
            user_b = await _seed_user(session, org_b)
            cust_b = await _seed_customer(session, org_b)
            invoice_b = await _seed_invoice(session, org_b, cust_b, user_b)

            return {
                "org_a_id": str(org_a.id),
                "user_a_id": str(user_a.id),
                "customer_a_id": str(cust_a.id),
                "invoice_a_id": str(invoice_a.id),
                "quote_a_id": str(quote_a.id),
                "customer_vehicle_a_id": str(cv_a.id),
                "org_b_id": str(org_b.id),
                "invoice_b_id": str(invoice_b.id),
            }


# ---------------------------------------------------------------------------
# App / client builder
# ---------------------------------------------------------------------------


def _build_app(
    factory,
    *,
    user_id: str | None,
    org_id: str | None,
    role: str | None,
) -> FastAPI:
    """Build an app exposing the email-compose router at the production path.

    A middleware populates ``request.state`` exactly as the real auth
    middleware does, and ``get_db_session`` is overridden to yield a real
    session from the test factory (RLS-bypassing app role — matches prod).
    """
    app = FastAPI()

    @app.middleware("http")
    async def _inject_state(request: Request, call_next):
        request.state.user_id = user_id
        request.state.org_id = org_id
        request.state.role = role
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    async def _override_db():
        async with factory() as session:
            async with session.begin():
                yield session

    app.dependency_overrides[get_db_session] = _override_db
    # Mirror app/main.py: include_router(..., prefix="/api/v2").
    app.include_router(email_compose_router, prefix="/api/v2")
    return app


def _assert_complete_preview(data: dict) -> None:
    """Assert the JSON body is a complete, correctly-typed EmailPreviewResponse."""
    for field, expected_type in _RESPONSE_FIELD_TYPES.items():
        assert field in data, f"missing field {field!r} in preview response"
        # JSON booleans decode to bool which is a subclass of int — guard the
        # int fields against accidentally accepting a bool.
        if expected_type is int:
            assert isinstance(data[field], int) and not isinstance(
                data[field], bool
            ), f"field {field!r} should be int, got {type(data[field])}"
        else:
            assert isinstance(
                data[field], expected_type
            ), f"field {field!r} should be {expected_type}, got {type(data[field])}"

    # sender_preview always carries the three identity keys.
    sp = data["sender_preview"]
    for key in ("from_email", "from_name", "reply_to"):
        assert key in sp, f"sender_preview missing {key!r}"

    # Each attachment spec carries the full AttachmentSpec shape.
    for att in data["attachments"]:
        assert isinstance(att, dict)
        for key in ("key", "label", "size_bytes", "default_attached", "required"):
            assert key in att, f"attachment missing {key!r}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_complete_response_for_all_ten_template_types():
    """All 10 template types return a complete EmailPreviewResponse (R20.1)."""
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        seeded = await _seed_full(factory)

        app = _build_app(
            factory,
            user_id=seeded["user_a_id"],
            org_id=seeded["org_a_id"],
            role="org_admin",
        )

        entity_id_for = {
            "invoice": seeded["invoice_a_id"],
            "quote": seeded["quote_a_id"],
            "customer": seeded["customer_a_id"],
            "customer_vehicle": seeded["customer_vehicle_a_id"],
        }

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for template_type, entity_type in ALL_TEMPLATE_TYPES:
                resp = await client.get(
                    "/api/v2/email-preview",
                    params={
                        "template_type": template_type,
                        "entity_type": entity_type,
                        "entity_id": entity_id_for[entity_type],
                    },
                )
                assert resp.status_code == 200, (
                    f"{template_type}: expected 200, got {resp.status_code} "
                    f"— {resp.text}"
                )
                data = resp.json()
                _assert_complete_preview(data)
                # The seeded customer has an email, so every surface that maps
                # to that customer resolves a recipient.
                assert data["recipients"] == ["jane.doe@example.com"], (
                    f"{template_type}: unexpected recipients {data['recipients']!r}"
                )
                # No template rows seeded → the hardcoded fallback is used.
                assert data["default_was_template"] is False
                assert data["subject"], f"{template_type}: empty subject"
                assert data["body_html"], f"{template_type}: empty body_html"
                assert data["email_size_limit_bytes"] > 0
                assert data["total_budget_seconds"] > 0
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_preview_cross_org_idor_does_not_leak_data():
    """Org A requesting org B's invoice must NOT return 200 (R25.1, R25.2)."""
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        seeded = await _seed_full(factory)

        # Authenticated as org A...
        app = _build_app(
            factory,
            user_id=seeded["user_a_id"],
            org_id=seeded["org_a_id"],
            role="org_admin",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # ...requesting org B's invoice id.
            resp = await client.get(
                "/api/v2/email-preview",
                params={
                    "template_type": "invoice_issued",
                    "entity_type": "invoice",
                    "entity_id": seeded["invoice_b_id"],
                },
            )

        assert resp.status_code in (403, 404), (
            f"cross-org request must be denied, got {resp.status_code}: {resp.text}"
        )
        # Never leak the cross-org entity's content.
        body = resp.text
        assert "INV-7001" not in body or resp.status_code != 200
        assert "jane.doe@example.com" not in body
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_preview_unauthenticated_returns_401():
    """A request with no authenticated user is rejected with 401 (R25.1)."""
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        seeded = await _seed_full(factory)

        # No user_id / role on request.state → require_role raises 401.
        app = _build_app(factory, user_id=None, org_id=None, role=None)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v2/email-preview",
                params={
                    "template_type": "invoice_issued",
                    "entity_type": "invoice",
                    "entity_id": seeded["invoice_a_id"],
                },
            )

        assert resp.status_code == 401, (
            f"unauthenticated request must be 401, got {resp.status_code}: {resp.text}"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_preview_wrong_role_returns_403():
    """A global_admin (not org_admin/salesperson) is denied with 403 (R25.2)."""
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        seeded = await _seed_full(factory)

        app = _build_app(
            factory,
            user_id=str(uuid.uuid4()),
            org_id=seeded["org_a_id"],
            role="global_admin",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v2/email-preview",
                params={
                    "template_type": "invoice_issued",
                    "entity_type": "invoice",
                    "entity_id": seeded["invoice_a_id"],
                },
            )

        assert resp.status_code == 403, (
            f"wrong-role request must be 403, got {resp.status_code}: {resp.text}"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()
