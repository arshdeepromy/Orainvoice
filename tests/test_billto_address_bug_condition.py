"""Bug condition exploration test — structured-only Bill-To address omitted.

Bugfix: invoice-billto-address-fix, Task 1 (exploratory phase).

This test encodes the EXPECTED behaviour for the customer "Bill To" address on
the three rendering surfaces that lack the ``billing_address`` JSONB fallback.
On UNFIXED code these assertions FAIL — proving the bug exists. After the fix
they PASS — confirming the bug is resolved.

**Validates: Requirements 1.2, 1.3, 1.4, 2.1, 2.3**

Root cause being documented/locked here:
  The Edit Customer modal writes the address into the structured
  ``customers.billing_address`` JSONB column and leaves the legacy plain-text
  ``customers.address`` column empty. Three rendering surfaces build a
  ``customer_context`` whose ``address`` comes from ``customer.address`` only
  (no JSONB fallback):

    1. Public / shared invoice view (``invoices/public_router.py``)
       — ``address`` sourced from ``customer.address`` only.
    2. Authenticated quote PDF (``quotes/service.py:generate_quote_pdf``)
       — ``address`` sourced from ``customer.address`` only.
    3. Public quote view (``quotes/public_router.py``)
       — NO ``address`` key in ``customer_context`` at all.

  So a customer whose address lives only in ``billing_address`` JSONB gets no
  address on any of these three surfaces.

Approach:
  We seed real ORM rows (org, plan, user, customer, invoice, quote) into the
  dev Postgres database, then invoke the REAL production handlers. We intercept
  the Jinja ``Template.render`` call to capture the exact ``customer`` context
  dict each handler constructs — the bug lives in context construction, so
  capturing that dict is the faithful unit of observation. The captured
  ``address`` value is then asserted against the joined structured string.

  The app DB role bypasses RLS (matches prod read paths gated by explicit
  ``org_id`` predicates), so direct factory sessions are sufficient.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import jinja2
import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Import ALL ORM models so SQLAlchemy can resolve string-based relationships
# at mapper-configuration time (mirrors other DB-backed tests).
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

from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.quotes.models import Quote

from app.modules.invoices.public_router import view_shared_invoice
from app.modules.quotes.public_router import view_shared_quote
from app.modules.quotes.service import generate_quote_pdf


# Marker baked into seeded org names so cleanup can find orphans even if a
# test aborts mid-way.
_ORG_MARKER = "TEST_billto_bug"

# The customer's address lives ONLY in the structured JSONB column.
_STRUCTURED_BILLING_ADDRESS = {
    "street": "842 Mahili Ave",
    "city": "Manukau",
    "state": "Auckland",
    "postal_code": "2104",
    "country": "NZ",
}
# Expected joined string, parts in order street, city, state, postal_code, country.
_EXPECTED_JOINED_ADDRESS = "842 Mahili Ave, Manukau, Auckland, 2104, NZ"


async def _make_engine_and_factory():
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
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for table in (
                "quote_line_items",
                "quotes",
                "quote_sequences",
                "line_items",
                "invoices",
                "invoice_sequences",
                "customers",
                "org_modules",
                "users",
                "branches",
            ):
                await session.execute(
                    sa_text(f"DELETE FROM {table} WHERE org_id IN ({org_subq})"),
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


async def _seed(factory) -> dict:
    """Seed an org + user + structured-only-address customer + invoice + quote."""
    share_token = uuid.uuid4().hex
    acceptance_token = uuid.uuid4().hex

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
                name=f"{_ORG_MARKER}_{uuid.uuid4().hex[:6]}",
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

            # Customer whose address exists ONLY in billing_address JSONB.
            customer = Customer(
                org_id=org.id,
                customer_type="business",
                first_name="Nolin",
                last_name="Devi",
                company_name="MUMA Whanau Services Ltd",
                display_name="MUMA Whanau Services Ltd",
                email="billing@muma.example.com",
                phone="021-555-0123",
                address=None,
                billing_address=dict(_STRUCTURED_BILLING_ADDRESS),
            )
            session.add(customer)
            await session.flush()

            invoice = Invoice(
                org_id=org.id,
                customer_id=customer.id,
                created_by=user.id,
                invoice_number="INV-BTO-001",
                status="issued",
                currency="NZD",
                issue_date=date.today(),
                due_date=date.today() + timedelta(days=14),
                subtotal=Decimal("100.00"),
                gst_amount=Decimal("15.00"),
                total=Decimal("115.00"),
                amount_paid=Decimal("0.00"),
                balance_due=Decimal("115.00"),
                payment_page_url="https://pay.example.com/inv-bto-001",
                invoice_data_json={"share_token": share_token},
            )
            session.add(invoice)
            await session.flush()

            quote = Quote(
                org_id=org.id,
                customer_id=customer.id,
                created_by=user.id,
                quote_number="QUO-BTO-001",
                status="sent",
                subtotal=Decimal("100.00"),
                gst_amount=Decimal("15.00"),
                total=Decimal("115.00"),
                valid_until=date.today() + timedelta(days=30),
                acceptance_token=acceptance_token,
            )
            session.add(quote)
            await session.flush()

            return {
                "org_id": org.id,
                "customer_id": customer.id,
                "invoice_id": invoice.id,
                "quote_id": quote.id,
                "share_token": share_token,
                "acceptance_token": acceptance_token,
            }


class _RenderCapture:
    """Patch ``jinja2.Template.render`` to capture the ``customer`` context.

    The bug lives in how each surface builds its ``customer_context`` dict, not
    in template syntax. We capture that dict at the render boundary and return a
    trivial valid HTML document so any downstream WeasyPrint step stays fast and
    cannot mask the captured context.
    """

    def __init__(self):
        self.customer = None
        self._orig = jinja2.Template.render

    def __enter__(self):
        capture = self

        def _patched(self_tmpl, *args, **kwargs):
            ctx = {}
            if args and isinstance(args[0], dict):
                ctx.update(args[0])
            ctx.update(kwargs)
            if "customer" in ctx:
                capture.customer = ctx["customer"]
            return "<html><body></body></html>"

        jinja2.Template.render = _patched
        return self

    def __exit__(self, *exc):
        jinja2.Template.render = self._orig
        return False


@pytest.mark.asyncio
async def test_public_invoice_address_includes_structured_billing_address():
    """Public/shared invoice context ``address`` SHALL equal the joined
    structured address when the plain ``address`` column is empty.

    EXPECTED ON UNFIXED CODE: FAIL — the context ``address`` is ``None`` because
    the public invoice path reads ``customer.address`` only.

    **Validates: Requirements 1.2, 2.1, 2.3**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await view_shared_invoice(ids["share_token"], db=session)

        assert cap.customer is not None, (
            "public invoice handler did not render a customer context (fixture problem)"
        )
        assert cap.customer.get("address") == _EXPECTED_JOINED_ADDRESS, (
            "Public/shared invoice 'Bill To' omits the structured address. "
            f"Expected {_EXPECTED_JOINED_ADDRESS!r}, "
            f"got {cap.customer.get('address')!r}. "
            "Customer address lives only in billing_address JSONB "
            f"({_STRUCTURED_BILLING_ADDRESS!r}) and this surface reads "
            "customer.address only."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_authenticated_quote_pdf_address_includes_structured_billing_address():
    """Authenticated quote-PDF context ``address`` SHALL equal the joined
    structured address when the plain ``address`` column is empty.

    EXPECTED ON UNFIXED CODE: FAIL — ``generate_quote_pdf`` builds ``address``
    from ``customer.address`` only.

    **Validates: Requirements 1.3, 2.1, 2.3**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await generate_quote_pdf(
                        session,
                        org_id=ids["org_id"],
                        quote_id=ids["quote_id"],
                    )

        assert cap.customer is not None, (
            "quote PDF generator did not render a customer context (fixture problem)"
        )
        assert cap.customer.get("address") == _EXPECTED_JOINED_ADDRESS, (
            "Authenticated quote PDF 'Bill To' omits the structured address. "
            f"Expected {_EXPECTED_JOINED_ADDRESS!r}, "
            f"got {cap.customer.get('address')!r}. "
            "Customer address lives only in billing_address JSONB "
            f"({_STRUCTURED_BILLING_ADDRESS!r}) and this surface reads "
            "customer.address only."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_public_quote_context_contains_resolved_address_key():
    """Public quote context SHALL contain an ``address`` key equal to the
    joined structured address.

    EXPECTED ON UNFIXED CODE: FAIL — the public quote ``customer_context`` has
    NO ``address`` key at all, so the value resolves to ``None``.

    **Validates: Requirements 1.4, 2.1, 2.3**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await view_shared_quote(ids["acceptance_token"], db=session)

        assert cap.customer is not None, (
            "public quote handler did not render a customer context (fixture problem)"
        )
        assert "address" in cap.customer, (
            "Public quote customer_context has NO 'address' key at all — the "
            "structured address can never display. "
            f"Context keys: {sorted(cap.customer.keys())!r}"
        )
        assert cap.customer.get("address") == _EXPECTED_JOINED_ADDRESS, (
            "Public quote 'Prepared For' omits the structured address. "
            f"Expected {_EXPECTED_JOINED_ADDRESS!r}, "
            f"got {cap.customer.get('address')!r}. "
            "Customer address lives only in billing_address JSONB "
            f"({_STRUCTURED_BILLING_ADDRESS!r})."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()
