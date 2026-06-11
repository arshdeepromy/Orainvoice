"""Preservation tests — Bill-To address behaviour that must NOT regress.

Bugfix: invoice-billto-address-fix, Task 2 (observation-first phase).

These tests capture the CURRENT CORRECT behaviour on UNFIXED code. They are
EXPECTED TO PASS today and establish a baseline the fix must preserve. They
encode Properties 2–6 from the design:

  * Property 2 — Preservation: Plain Address Precedence
      A non-empty plain ``customers.address`` is rendered verbatim and wins over
      the structured ``billing_address`` JSONB.
      **Validates: Requirements 2.2, 3.1**

  * Property 3 — Preservation: No Address Resolves to Empty
      No address in either source (incl. all-empty-strings JSONB) → resolved
      address is ``None`` and the "Bill To" line is omitted.
      **Validates: Requirements 2.4, 3.4, 3.5**

  * Property 4 — Preservation: Already-Correct Invoice Paths Unchanged
      ``get_invoice`` and ``generate_invoice_pdf`` already carry the structured
      ``billing_address`` fallback, so a structured-only customer already renders
      the joined string today. This must remain true after the fix.
      **Validates: Requirements 3.2**

  * Property 5 — Preservation: Non-Address Bill-To Fields Unchanged
      Name / company / display name / email / phone render exactly as seeded.
      **Validates: Requirements 3.3**

  * Property 6 — Preservation: Compliance Check Unchanged (OUT OF SCOPE)
      The Req 80.2 high-value buyer-address compliance check reads the plain
      ``customer.address`` column only and is intentionally NOT touched by this
      fix. Its behaviour must be identical before and after.
      **Validates: Requirements 3.6**

Approach mirrors ``tests/test_billto_address_bug_condition.py``:
  * Seed real ORM rows (org, plan, user, customers, invoices) into the dev
    Postgres database and invoke the REAL production handlers.
  * Intercept ``jinja2.Template.render`` to capture the exact ``customer``
    context dict each handler constructs — that dict is the faithful unit of
    observation for the "Bill To" block.
  * The compliance check (Property 6) is a pure function, so it is exercised
    directly with in-memory ORM objects (no DB / no render needed).

  The app DB role bypasses RLS, so direct factory sessions are sufficient.
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
# at mapper-configuration time (mirrors the bug-condition test).
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
from app.modules.invoices.models import Invoice, LineItem

from app.modules.invoices.service import (
    get_invoice,
    generate_invoice_pdf,
    validate_tax_invoice_compliance,
    NZ_HIGH_VALUE_THRESHOLD,
)


# Marker baked into seeded org names so cleanup can find orphans even if a test
# aborts mid-way. Distinct from the bug-condition test's marker.
_ORG_MARKER = "TEST_billto_preserve"

# Structured-only address (plain ``address`` empty) — exercises the fallback.
_STRUCTURED_BILLING_ADDRESS = {
    "street": "842 Mahili Ave",
    "city": "Manukau",
    "state": "Auckland",
    "postal_code": "2104",
    "country": "NZ",
}
_EXPECTED_JOINED_ADDRESS = "842 Mahili Ave, Manukau, Auckland, 2104, NZ"

# Plain address present — must win over a (different) structured address.
_PLAIN_ADDRESS = "12 Queen Street, Auckland CBD"
_OTHER_BILLING_ADDRESS = {
    "street": "99 Other Road",
    "city": "Wellington",
    "state": "Wellington",
    "postal_code": "6011",
    "country": "NZ",
}

# All-empty-strings JSONB — must resolve to None (treated as no address).
_EMPTY_BILLING_ADDRESS = {
    "street": "",
    "city": "",
    "state": "",
    "postal_code": "",
    "country": "",
}


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


async def _add_customer_with_invoice(
    session: AsyncSession,
    *,
    org_id,
    user_id,
    address,
    billing_address,
    number_suffix: str,
) -> dict:
    """Create one customer (with the given address shape) and an invoice for it."""
    customer = Customer(
        org_id=org_id,
        customer_type="business",
        first_name="Nolin",
        last_name="Devi",
        company_name="MUMA Whanau Services Ltd",
        display_name="MUMA Whanau Services Ltd",
        email="billing@muma.example.com",
        phone="021-555-0123",
        address=address,
        billing_address=billing_address,
    )
    session.add(customer)
    await session.flush()

    invoice = Invoice(
        org_id=org_id,
        customer_id=customer.id,
        created_by=user_id,
        invoice_number=f"INV-PRES-{number_suffix}",
        status="issued",
        currency="NZD",
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=14),
        subtotal=Decimal("100.00"),
        gst_amount=Decimal("15.00"),
        total=Decimal("115.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("115.00"),
        payment_page_url=f"https://pay.example.com/inv-pres-{number_suffix}",
        invoice_data_json={},
    )
    session.add(invoice)
    await session.flush()

    return {"customer_id": customer.id, "invoice_id": invoice.id}


async def _seed(factory) -> dict:
    """Seed an org + user + one customer/invoice per address scenario."""
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

            plain = await _add_customer_with_invoice(
                session,
                org_id=org.id,
                user_id=user.id,
                address=_PLAIN_ADDRESS,
                billing_address=dict(_OTHER_BILLING_ADDRESS),
                number_suffix="PLAIN",
            )
            structured = await _add_customer_with_invoice(
                session,
                org_id=org.id,
                user_id=user.id,
                address=None,
                billing_address=dict(_STRUCTURED_BILLING_ADDRESS),
                number_suffix="STRUCT",
            )
            none_addr = await _add_customer_with_invoice(
                session,
                org_id=org.id,
                user_id=user.id,
                address=None,
                billing_address=None,
                number_suffix="NONE",
            )
            empty_jsonb = await _add_customer_with_invoice(
                session,
                org_id=org.id,
                user_id=user.id,
                address=None,
                billing_address=dict(_EMPTY_BILLING_ADDRESS),
                number_suffix="EMPTY",
            )

            return {
                "org_id": org.id,
                "plain": plain,
                "structured": structured,
                "none": none_addr,
                "empty_jsonb": empty_jsonb,
            }


class _RenderCapture:
    """Patch ``jinja2.Template.render`` to capture the ``customer`` context.

    Returns trivial valid HTML so any downstream WeasyPrint step stays fast and
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


# ---------------------------------------------------------------------------
# Property 2 — Plain address precedence (get_invoice + generate_invoice_pdf)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invoice_renders_plain_address_verbatim_and_wins():
    """A non-empty plain ``address`` is returned verbatim by ``get_invoice``
    and takes precedence over the structured ``billing_address`` JSONB.

    **Validates: Requirements 2.2, 3.1**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                result = await get_invoice(
                    session,
                    org_id=ids["org_id"],
                    invoice_id=ids["plain"]["invoice_id"],
                )

        assert result["customer"]["address"] == _PLAIN_ADDRESS, (
            "Plain customers.address must be rendered verbatim and win over the "
            f"structured billing_address. Expected {_PLAIN_ADDRESS!r}, "
            f"got {result['customer']['address']!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_generate_invoice_pdf_renders_plain_address_verbatim_and_wins():
    """``generate_invoice_pdf`` renders the plain ``address`` verbatim and it
    wins over the structured ``billing_address`` JSONB.

    **Validates: Requirements 2.2, 3.1**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await generate_invoice_pdf(
                        session,
                        org_id=ids["org_id"],
                        invoice_id=ids["plain"]["invoice_id"],
                    )

        assert cap.customer is not None, "PDF generator did not render a customer context"
        assert cap.customer.get("address") == _PLAIN_ADDRESS, (
            "Plain customers.address must be rendered verbatim and win over the "
            f"structured billing_address. Expected {_PLAIN_ADDRESS!r}, "
            f"got {cap.customer.get('address')!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 3 — No address resolves to None (get_invoice + generate_invoice_pdf)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invoice_no_address_resolves_to_none():
    """No address in either source → ``get_invoice`` resolves ``address`` to
    ``None`` (the "Bill To" line is omitted).

    **Validates: Requirements 2.4, 3.4**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                result = await get_invoice(
                    session,
                    org_id=ids["org_id"],
                    invoice_id=ids["none"]["invoice_id"],
                )

        assert result["customer"]["address"] is None, (
            "Customer with no address in either source must resolve to None, "
            f"got {result['customer']['address']!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_invoice_all_empty_strings_jsonb_resolves_to_none():
    """An all-empty-strings ``billing_address`` JSONB is treated as no address
    and ``get_invoice`` resolves ``address`` to ``None``.

    **Validates: Requirements 2.4, 3.5**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                result = await get_invoice(
                    session,
                    org_id=ids["org_id"],
                    invoice_id=ids["empty_jsonb"]["invoice_id"],
                )

        assert result["customer"]["address"] is None, (
            "All-empty-strings billing_address JSONB must resolve to None, "
            f"got {result['customer']['address']!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_generate_invoice_pdf_no_address_resolves_to_none():
    """``generate_invoice_pdf`` resolves ``address`` to ``None`` for a customer
    with no address in either source.

    **Validates: Requirements 2.4, 3.4**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await generate_invoice_pdf(
                        session,
                        org_id=ids["org_id"],
                        invoice_id=ids["none"]["invoice_id"],
                    )

        assert cap.customer is not None, "PDF generator did not render a customer context"
        assert cap.customer.get("address") is None, (
            "Customer with no address must resolve to None in the PDF context, "
            f"got {cap.customer.get('address')!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 4 — Already-correct invoice paths already show structured address
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invoice_structured_only_already_renders_joined_string():
    """``get_invoice`` already carries the structured fallback, so a
    structured-only customer already renders the joined string TODAY.

    **Validates: Requirements 3.2**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                result = await get_invoice(
                    session,
                    org_id=ids["org_id"],
                    invoice_id=ids["structured"]["invoice_id"],
                )

        assert result["customer"]["address"] == _EXPECTED_JOINED_ADDRESS, (
            "get_invoice already has the billing_address fallback and must "
            f"render the joined string. Expected {_EXPECTED_JOINED_ADDRESS!r}, "
            f"got {result['customer']['address']!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_generate_invoice_pdf_structured_only_already_renders_joined_string():
    """``generate_invoice_pdf`` already carries the structured fallback, so a
    structured-only customer already renders the joined string TODAY.

    **Validates: Requirements 3.2**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await generate_invoice_pdf(
                        session,
                        org_id=ids["org_id"],
                        invoice_id=ids["structured"]["invoice_id"],
                    )

        assert cap.customer is not None, "PDF generator did not render a customer context"
        assert cap.customer.get("address") == _EXPECTED_JOINED_ADDRESS, (
            "generate_invoice_pdf already has the billing_address fallback and "
            f"must render the joined string. Expected {_EXPECTED_JOINED_ADDRESS!r}, "
            f"got {cap.customer.get('address')!r}."
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 5 — Non-address Bill-To fields unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_invoice_non_address_fields_render_unchanged():
    """Name, company name, display name, email, and phone render exactly as
    seeded via ``get_invoice`` (only address resolution changes in the fix).

    **Validates: Requirements 3.3**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                result = await get_invoice(
                    session,
                    org_id=ids["org_id"],
                    invoice_id=ids["structured"]["invoice_id"],
                )

        cust = result["customer"]
        assert cust["first_name"] == "Nolin"
        assert cust["last_name"] == "Devi"
        assert cust["company_name"] == "MUMA Whanau Services Ltd"
        assert cust["display_name"] == "MUMA Whanau Services Ltd"
        assert cust["email"] == "billing@muma.example.com"
        assert cust["phone"] == "021-555-0123"
    finally:
        await _cleanup(factory)
        await engine.dispose()


@pytest.mark.asyncio
async def test_generate_invoice_pdf_non_address_fields_render_unchanged():
    """Name, company name, display name, email, and phone render exactly as
    seeded via ``generate_invoice_pdf``.

    **Validates: Requirements 3.3**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                with _RenderCapture() as cap:
                    await generate_invoice_pdf(
                        session,
                        org_id=ids["org_id"],
                        invoice_id=ids["structured"]["invoice_id"],
                    )

        assert cap.customer is not None, "PDF generator did not render a customer context"
        assert cap.customer.get("first_name") == "Nolin"
        assert cap.customer.get("last_name") == "Devi"
        assert cap.customer.get("company_name") == "MUMA Whanau Services Ltd"
        assert cap.customer.get("display_name") == "MUMA Whanau Services Ltd"
        assert cap.customer.get("email") == "billing@muma.example.com"
        assert cap.customer.get("phone") == "021-555-0123"
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 6 — Compliance check (Req 80.2) unchanged / OUT OF SCOPE
# ---------------------------------------------------------------------------
#
# The high-value buyer-address compliance check reads the plain
# ``customer.address`` column only. The fix does NOT touch it, so its behaviour
# must be identical: a structured-only customer (plain address empty) still
# triggers the "Buyer address is required" issue, and a customer with a plain
# address does not. These are pure-function checks (no DB / no render).


def _high_value_invoice() -> Invoice:
    """In-memory invoice over the high-value threshold with valid basics."""
    inv = Invoice(
        invoice_number="INV-COMP-001",
        status="issued",
        currency="NZD",
        issue_date=date.today(),
        subtotal=Decimal("1000.00"),
        gst_amount=Decimal("150.00"),
        total=NZ_HIGH_VALUE_THRESHOLD + Decimal("150.00"),
    )
    return inv


def _valid_line_item() -> LineItem:
    return LineItem(description="Service rendered", quantity=Decimal("1"))


def test_compliance_check_flags_missing_buyer_address_for_structured_only_customer():
    """A high-value GST invoice whose customer has the address ONLY in
    ``billing_address`` JSONB STILL triggers the Req 80.2 buyer-address issue
    (the check reads the plain ``address`` column only — unchanged behaviour).

    **Validates: Requirements 3.6**
    """
    invoice = _high_value_invoice()
    customer = Customer(
        customer_type="business",
        first_name="Nolin",
        last_name="Devi",
        address=None,
        billing_address=dict(_STRUCTURED_BILLING_ADDRESS),
    )
    invoice._compliance_customer = customer

    result = validate_tax_invoice_compliance(
        invoice=invoice,
        line_items=[_valid_line_item()],
        org_name="MUMA Whanau Services Ltd",
        gst_number="123-456-789",
    )

    address_issues = [
        i for i in result["issues"]
        if i.get("field") == "customer_address" and i.get("requirement") == "80.2"
    ]
    assert address_issues, (
        "Req 80.2 compliance check must STILL flag a missing buyer address when "
        "the address lives only in billing_address JSONB (this check reads the "
        "plain address column only and is out of scope for the fix). "
        f"Issues: {result['issues']!r}"
    )


def test_compliance_check_passes_buyer_address_for_plain_address_customer():
    """A high-value GST invoice whose customer has a plain ``address`` does NOT
    trigger the Req 80.2 buyer-address issue (unchanged behaviour).

    **Validates: Requirements 3.6**
    """
    invoice = _high_value_invoice()
    customer = Customer(
        customer_type="business",
        first_name="Nolin",
        last_name="Devi",
        address=_PLAIN_ADDRESS,
        billing_address=None,
    )
    invoice._compliance_customer = customer

    result = validate_tax_invoice_compliance(
        invoice=invoice,
        line_items=[_valid_line_item()],
        org_name="MUMA Whanau Services Ltd",
        gst_number="123-456-789",
    )

    address_issues = [
        i for i in result["issues"]
        if i.get("field") == "customer_address" and i.get("requirement") == "80.2"
    ]
    assert not address_issues, (
        "Req 80.2 compliance check must NOT flag a missing buyer address when "
        f"the customer has a plain address. Issues: {result['issues']!r}"
    )
