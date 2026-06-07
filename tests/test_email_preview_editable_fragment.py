"""Regression property test — the preview's editable fragment is clean.

Bugfix: email-preview-body-mismatch, Task 6.2 (fix-checking phase).

This file locks in the FIXED behaviour the bugfix delivers. It has two parts:

1. **Property 1 (Bug Condition — no chrome / subject leak)** — a Hypothesis
   property that, for ALL supported surfaces, the preview's NEW
   ``body_editable_html`` fragment (the field the rich-text editor now binds
   to) contains no document chrome (``<!DOCTYPE>`` / ``<head>`` / ``<title>``
   / ``<html>``) and, once stripped to text, does NOT contain the subject
   line. This is the invariant the original bug violated: the editor was
   seeded with the full transactional document whose ``<title>{subject}``
   leaked into the body as the first editable paragraph.
   **Validates: Requirements 2.1, 4.1, 4.2**

2. **Property 3 (Bug Condition — preview origin == send origin)** — a
   router-level test (in-process ASGI client) proving that a preview GET with
   NO ``Origin`` header but a ``Host`` header resolves the link origin from
   ``Host`` (not ``localhost``), and that an explicit ``Origin`` header is
   honoured. Browsers omit ``Origin`` on a same-origin GET, so the old code
   (``base_url = request.headers.get("origin")``) fell back to
   ``settings.frontend_base_url``/``localhost`` while the POST send paths saw
   the real public host. The router now uses ``extract_request_base_url`` (the
   ``Host`` fallback), so the preview resolves the SAME public origin the send
   path resolves.
   **Validates: Requirements 2.2, 4.3**

Both parts run DB-backed against the dev Postgres database, reusing the
seed/teardown approach of ``tests/test_email_compose_preview.py`` and the
DB-backed Hypothesis pattern of
``tests/test_email_compose_default_equivalence.py``.
"""

from __future__ import annotations

import asyncio
import html as _html
import re as _re
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings as app_settings

# Import ALL ORM models so SQLAlchemy can resolve string-based relationships
# at mapper-configuration time (mirrors tests/test_email_compose_preview.py).
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
from app.modules.email_compose.service import build_email_preview
from app.modules.invoices.models import Invoice
from app.modules.quotes.models import Quote
from app.modules.vehicles.models import CustomerVehicle


# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way.
_ORG_MARKER = "TEST_6_2_editable_frag"

# The supported surfaces and the entity_type each expects (mirrors
# email_compose.service.TEMPLATE_ENTITY_TYPES). The fragment-clean property
# must hold for EVERY one of them (Requirement 3.5 / 4.1).
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


# ---------------------------------------------------------------------------
# Text helpers.
# ---------------------------------------------------------------------------

_TAG_RE = _re.compile(r"<[^>]+>")


def _strip_to_text(fragment: str) -> str:
    """Reduce an HTML fragment to its rendered text (tags → spaces).

    This approximates ``editorVisibleText(...)`` from the bug methodology:
    everything a user would actually read once the markup is rendered.
    """
    return _html.unescape(_TAG_RE.sub(" ", fragment or ""))


# ---------------------------------------------------------------------------
# Hypothesis strategies — constrain to the real entity input space.
#
# Free text is kept to safe printable characters (no newlines/control chars)
# so the generated value survives the render + sanitise paths cleanly. The
# point is to vary the data that flows into the subject and body (org name,
# customer names, document numbers, totals, dates, origins) across many
# examples and assert the fragment is ALWAYS clean.
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        blacklist_characters="\n\r\t",
    ),
    min_size=0,
    max_size=40,
)

_name_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" -'"),
    min_size=0,
    max_size=30,
)

_money = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_doc_suffix = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=12,
)

_day_offset = st.integers(min_value=-365, max_value=365)

_origin = st.builds(
    lambda host, n: f"https://{host}.example.com/pay/{n}",
    host=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd")),
        min_size=1,
        max_size=12,
    ),
    n=st.integers(min_value=1, max_value=99999),
)


@st.composite
def _entity_data(draw):
    """Generate one self-consistent bundle of entity field values."""
    return {
        "org_name": draw(_safe_text),
        "org_email": draw(st.sampled_from(["", "shop@example.com", "hi@trade.co"])),
        "org_phone": draw(st.sampled_from(["", "09-555-0000", "021 123 456"])),
        "first_name": draw(_name_text),
        "last_name": draw(_name_text),
        "doc_suffix": draw(_doc_suffix),
        "subtotal": draw(_money),
        "gst": draw(_money),
        "total": draw(_money),
        "amount_paid": draw(_money),
        "balance_due": draw(_money),
        "due_offset": draw(_day_offset),
        "valid_offset": draw(_day_offset),
        "payment_origin": draw(_origin),
    }


# ---------------------------------------------------------------------------
# Engine / session helpers (bound to the dev DB, mirroring task 7.1 / 7.2).
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
    """Delete every row created by the seeders (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
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
                    sa_text(f"DELETE FROM {table} WHERE org_id IN ({org_subq})"),
                    params,
                )
            # Global vehicles are not org-scoped — delete by the test rego prefix.
            await session.execute(
                sa_text("DELETE FROM global_vehicles WHERE rego LIKE :rego"),
                {"rego": "T62%"},
            )
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                params,
            )
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


# ---------------------------------------------------------------------------
# Seeding — one org + customer + invoice + quote + vehicle link per example.
# ---------------------------------------------------------------------------


async def _seed(factory, data: dict, *, payment_page_url: str | None) -> dict:
    inv_number = f"INV-{data['doc_suffix']}"
    quote_number = f"QUO-{data['doc_suffix']}"
    today = date.today()
    due_date = today + timedelta(days=data["due_offset"])
    valid_until = today + timedelta(days=data["valid_offset"])

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
                name=f"{_ORG_MARKER}_{data['org_name']}_{uuid.uuid4().hex[:6]}",
                plan_id=plan.id,
                status="active",
                storage_quota_gb=1,
                locale="en",
                settings={
                    "email": data["org_email"],
                    "phone": data["org_phone"],
                    "gst_percentage": 15,
                },
            )
            session.add(org)
            await session.flush()

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

            customer = Customer(
                org_id=org.id,
                first_name=data["first_name"],
                last_name=data["last_name"],
                email="recipient@example.com",
                language="en",
                enable_portal=True,
                portal_token=uuid.uuid4().hex,
            )
            session.add(customer)
            await session.flush()

            invoice = Invoice(
                org_id=org.id,
                customer_id=customer.id,
                created_by=user.id,
                invoice_number=inv_number,
                status="issued",
                currency="NZD",
                issue_date=today,
                due_date=due_date,
                subtotal=data["subtotal"],
                gst_amount=data["gst"],
                total=data["total"],
                amount_paid=data["amount_paid"],
                balance_due=data["balance_due"],
                payment_page_url=payment_page_url,
            )
            session.add(invoice)
            await session.flush()

            quote = Quote(
                org_id=org.id,
                customer_id=customer.id,
                created_by=user.id,
                quote_number=quote_number,
                status="sent",
                subtotal=data["subtotal"],
                gst_amount=data["gst"],
                total=data["total"],
                valid_until=valid_until,
                acceptance_token=uuid.uuid4().hex,
            )
            session.add(quote)
            await session.flush()

            gv = GlobalVehicle(
                rego=f"T62{uuid.uuid4().hex[:5].upper()}",
                make="Toyota",
                model="Hilux",
                year=2020,
                wof_expiry=today + timedelta(days=20),
                cof_expiry=today + timedelta(days=25),
                registration_expiry=today + timedelta(days=30),
                service_due_date=today + timedelta(days=35),
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

            return {
                "org_id": org.id,
                "user_id": str(user.id),
                "customer_id": customer.id,
                "invoice_id": invoice.id,
                "quote_id": quote.id,
                "customer_vehicle_id": cv.id,
            }


# ---------------------------------------------------------------------------
# Property 1 — the editable fragment is clean for every surface.
# ---------------------------------------------------------------------------


def _assert_clean_fragment(template_type: str, preview: dict) -> None:
    """The editable fragment has no chrome and does not leak the subject."""
    subject = preview["subject"]
    editable = preview["body_editable_html"]

    assert subject, f"{template_type}: produced an empty subject (fixture problem)"

    lower = editable.lower()
    assert "<!doctype" not in lower, (
        f"{template_type}: body_editable_html must not contain a DOCTYPE"
    )
    assert "<head" not in lower, (
        f"{template_type}: body_editable_html must not contain a <head>"
    )
    assert "<title" not in lower, (
        f"{template_type}: body_editable_html must not contain a <title>"
    )
    assert "<html" not in lower, (
        f"{template_type}: body_editable_html must not contain an <html> tag"
    )

    # The subject must NOT survive in the editable content — neither in the
    # raw fragment nor in its rendered text (the leak the bug exposed).
    assert subject not in editable, (
        f"{template_type}: subject leaked into the raw editable fragment"
    )
    text = _strip_to_text(editable)
    assert subject not in text, (
        f"{template_type}: subject leaked into the rendered editable text"
    )


async def _preview(factory, ids, template_type: str, entity_type: str, entity_id):
    async with factory() as session:
        async with session.begin():
            return await build_email_preview(
                session,
                org_id=ids["org_id"],
                template_type=template_type,
                entity_type=entity_type,
                entity_id=entity_id,
            )


async def _run_fragment_example(data: dict) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed(factory, data, payment_page_url=data["payment_origin"])

        entity_id_for = {
            "invoice": ids["invoice_id"],
            "quote": ids["quote_id"],
            "customer": ids["customer_id"],
            "customer_vehicle": ids["customer_vehicle_id"],
        }

        for template_type, entity_type in ALL_TEMPLATE_TYPES:
            preview = await _preview(
                factory, ids, template_type, entity_type, entity_id_for[entity_type]
            )
            _assert_clean_fragment(template_type, preview)
    finally:
        await _cleanup(factory)
        await engine.dispose()


@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=_entity_data())
def test_editable_fragment_has_no_chrome_or_subject_leak(data):
    """Property 1: the editable fragment is clean across all surfaces.

    For ANY supported ``(template_type, entity)``, ``body_editable_html``
    contains no ``<!DOCTYPE>`` / ``<head>`` / ``<title>`` / ``<html>`` and,
    once stripped to text, does not contain the subject line.

    **Validates: Requirements 2.1, 4.1, 4.2**
    """
    asyncio.run(_run_fragment_example(data))


# ---------------------------------------------------------------------------
# Property 3 — preview origin == send origin (router-level Host fallback).
# ---------------------------------------------------------------------------


def _build_app(
    factory,
    *,
    user_id: str | None,
    org_id: str | None,
    role: str | None,
) -> FastAPI:
    """Build an app exposing the email-compose router at the production path.

    Mirrors ``tests/test_email_compose_preview.py``: a middleware populates
    ``request.state`` the way the real auth middleware does, and
    ``get_db_session`` yields a real session from the test factory.
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
    app.include_router(email_compose_router, prefix="/api/v2")
    return app


def _invoice_view_origin(payment_link: str) -> str:
    """Extract ``scheme://host`` from the invoice-view CTA URL."""
    from urllib.parse import urlsplit

    parts = urlsplit(payment_link)
    return f"{parts.scheme}://{parts.netloc}"


@pytest.mark.asyncio
async def test_preview_origin_resolves_from_host_and_honours_explicit_origin():
    """Property 3: preview origin == send origin.

    The preview is a GET; browsers omit ``Origin`` on same-origin GETs. The
    router now resolves ``base_url`` via ``extract_request_base_url`` (the
    ``Host`` fallback), so:

      * with NO ``Origin`` header but a ``Host`` header, the invoice-view link
        origin comes from ``Host`` (the real public host) — NOT
        ``localhost`` / ``settings.frontend_base_url``; and
      * an explicit ``Origin`` header is honoured.

    Because the POST send path resolves the same chain (request origin →
    payment-page origin → settings → localhost) and on a real browser POST the
    ``Origin`` equals the ``Host`` the GET sees, the preview origin equals the
    send origin for the same inputs.

    **Validates: Requirements 2.2, 4.3**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        # Seed an invoice with NO payment_page_url so the only origin source is
        # the request — this isolates the Host-vs-localhost behaviour.
        data = {
            "org_name": "Origin Co",
            "org_email": "shop@example.com",
            "org_phone": "09-555-0000",
            "first_name": "Jane",
            "last_name": "Doe",
            "doc_suffix": "6002",
            "subtotal": Decimal("100.00"),
            "gst": Decimal("15.00"),
            "total": Decimal("115.00"),
            "amount_paid": Decimal("0.00"),
            "balance_due": Decimal("115.00"),
            "due_offset": 14,
            "valid_offset": 30,
            "payment_origin": "",
        }
        ids = await _seed(factory, data, payment_page_url=None)

        app = _build_app(
            factory,
            user_id=ids["user_id"],
            org_id=str(ids["org_id"]),
            role="org_admin",
        )

        public_host = "devin.oraflows.co.nz"

        # --- Case 1: NO Origin header, Host header present (same-origin GET). ---
        # httpx sets the Host header from the client's base_url and does NOT
        # add an Origin header on a GET, exactly like a same-origin browser GET.
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=f"https://{public_host}",
        ) as client:
            resp = await client.get(
                "/api/v2/email-preview",
                params={
                    "template_type": "invoice_issued",
                    "entity_type": "invoice",
                    "entity_id": str(ids["invoice_id"]),
                },
            )
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        data_host = resp.json()
        payment_link = data_host["variable_context"]["payment_link"]
        assert payment_link, "invoice_issued must build an invoice-view link"
        # The link origin must be the public Host — NOT the localhost fallback.
        assert public_host in payment_link, (
            f"preview link must use the Host origin, got {payment_link!r}"
        )
        assert "localhost" not in payment_link, (
            f"preview link must NOT fall back to localhost, got {payment_link!r}"
        )
        assert _invoice_view_origin(payment_link) == f"https://{public_host}"

        # --- Case 2: explicit Origin header is honoured. ---
        explicit_origin = "https://explicit-origin.example.com"
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url=f"https://{public_host}",
        ) as client:
            resp2 = await client.get(
                "/api/v2/email-preview",
                params={
                    "template_type": "invoice_issued",
                    "entity_type": "invoice",
                    "entity_id": str(ids["invoice_id"]),
                },
                headers={"origin": explicit_origin},
            )
        assert resp2.status_code == 200, f"expected 200, got {resp2.status_code}: {resp2.text}"
        data_origin = resp2.json()
        payment_link2 = data_origin["variable_context"]["payment_link"]
        assert _invoice_view_origin(payment_link2) == explicit_origin, (
            f"explicit Origin must be honoured, got {payment_link2!r}"
        )
        assert "localhost" not in payment_link2
    finally:
        await _cleanup(factory)
        await engine.dispose()
