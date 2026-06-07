"""Property test: Send-default byte-equivalence.

Feature: send-email-modal, Property 1: Send-default byte-equivalence.

*For any* supported ``(template_type, entity)``, the subject and the
sanitised ``body_html`` bytes produced by
``email_compose.service.build_email_preview()`` SHALL exactly equal the
bytes the underlying send function produces on its **no-override**
default-render path. Editing nothing and clicking Send is therefore
byte-identical to the pre-modal auto-send (Requirements 3.6, 20.5).

How the property is exercised
-----------------------------
This is a TRUE property, not a fixed example: Hypothesis varies the
**entity data** (invoice/quote numbers, monetary totals, customer names,
due/valid dates, payment-page URLs, org name/contact details, …) across
>=100 examples. For each example we:

  1. Seed a real ``organisation`` + ``customer`` + entity row into the dev
     Postgres database (reusing task 7.1's DB-backed seed/teardown approach
     — a real async engine, marker-based cleanup in ``try/finally``).
  2. Call ``build_email_preview()`` → ``(subject, body_html)``. The body is
     already run through ``Body_Sanitiser`` inside the preview.
  3. Call the **real** send function for that surface with **no overrides**,
     but with the actual network dispatch (``email_sender.send_email``) and
     PDF generation patched out so nothing leaves the process. We capture the
     ``EmailMessage`` the send path *would* have dispatched.
  4. Assert ``preview.subject == sent.subject`` AND
     ``preview.body_html == sanitise_email_html(sent.html_body)`` — i.e. the
     exact bytes the modal's "send default" path yields equal the exact bytes
     the auto-send path yields.

Comparing the rendering (rather than truly dispatching) is what keeps this a
fast, deterministic property that still guards the byte-equivalence contract:
the preview and the send path are two independently-maintained code paths, and
this test fails the moment they diverge.

Surfaces covered (the ones with a callable default-render send path):
  * ``invoice_issued``        → ``invoices.service.email_invoice``
  * ``payment_received``      → ``payments.service._send_receipt_email``
  * ``invoice_payment_link``  → ``payments.service._send_receipt_email``
                                 (``template_type="invoice_issued"`` mode)
  * ``quote_sent``            → ``quotes.service.send_quote``
  * ``portal_link``           → ``customers.service.send_portal_link``

Design ref: ``.kiro/specs/send-email-modal/design.md`` →
"Correctness Properties → Property 1: Send-default byte-equivalence".

**Validates: Requirements 3.6, 20.5**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select, text as sa_text
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

from app.integrations.html_sanitise import sanitise_email_html
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.email_compose.service import build_email_preview
from app.modules.invoices.models import Invoice
from app.modules.quotes.models import Quote


# Marker baked into seeded org names so cleanup can find orphans even when an
# example aborts mid-way.
_ORG_MARKER = "TEST_7_2_byte_equiv"


# ---------------------------------------------------------------------------
# Hypothesis strategies — constrain to the real entity input space.
#
# Free text (names, org name) is kept to safe printable characters so the
# generated value survives both code paths identically. The point of the
# property is the *equivalence* of the two render paths over varying data,
# not fuzzing the HTML sanitiser (that is Property 2's job). Both the preview
# and the send path feed identical text through the same renderer + sanitiser,
# so any value works; we simply avoid pathological control characters that the
# DB driver or text renderer might normalise differently and that would add
# noise rather than coverage.
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        # Exclude characters that the transactional-HTML renderer treats
        # specially (newlines split paragraphs) or that collapse on a DB
        # round-trip; both paths would still agree, but we keep the data clean.
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

# Money as a 2dp Decimal in a realistic range.
_money = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A short alphanumeric document number suffix (e.g. INV-<suffix>).
_doc_suffix = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=12,
)

_day_offset = st.integers(min_value=-365, max_value=365)

# An https origin used as the customer-facing base URL / payment-page origin.
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
# Engine / session helpers (bound to the dev DB, mirroring task 7.1).
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
    """Delete every row created by the seeder (keyed on the org-name marker)."""
    async with factory() as session:
        async with session.begin():
            org_subq = "SELECT id FROM organisations WHERE name LIKE :marker"
            params = {"marker": f"{_ORG_MARKER}%"}
            for table in (
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
            await session.execute(
                sa_text("DELETE FROM organisations WHERE name LIKE :marker"),
                params,
            )
            await session.execute(
                sa_text("DELETE FROM subscription_plans WHERE name = :name"),
                {"name": f"{_ORG_MARKER}_plan"},
            )


# ---------------------------------------------------------------------------
# Seeding — one org + customer + invoice + quote per example.
# ---------------------------------------------------------------------------


async def _seed(factory, data: dict) -> dict:
    inv_number = f"INV-{data['doc_suffix']}"
    quote_number = f"QUO-{data['doc_suffix']}"
    today = date.today()
    due_date = today + timedelta(days=data["due_offset"])
    valid_until = today + timedelta(days=data["valid_offset"])
    portal_token = uuid.uuid4().hex
    # Use a deterministic, pre-persisted share token so the invoice-view CTA
    # URL is stable across the preview and send paths.
    share_token = uuid.uuid4().hex

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
                portal_token=portal_token,
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
                payment_page_url=data["payment_origin"],
                invoice_data_json={"share_token": share_token},
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

            return {
                "org_id": org.id,
                "user_id": user.id,
                "customer_id": customer.id,
                "invoice_id": invoice.id,
                "quote_id": quote.id,
            }


# ---------------------------------------------------------------------------
# Capture helper — patch the network dispatch so we observe the EmailMessage
# the send path WOULD have sent, without anything leaving the process.
# ---------------------------------------------------------------------------


class _Captured:
    def __init__(self):
        self.message = None


def _fake_send_email(capture: _Captured):
    async def _send(db, message, **kwargs):  # noqa: ANN001
        capture.message = message

        class _Result:
            success = True
            provider_key = "test-provider"
            provider_message_id = "test-message-id"
            error = None
            failure_kind = None

        return _Result()

    return _send


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


def _assert_equivalent(template_type, preview, sent_subject, sent_html):
    """The preview's (subject, body_html) must equal the send path's bytes."""
    assert preview["subject"] == sent_subject, (
        f"{template_type}: subject diverged\n"
        f"  preview: {preview['subject']!r}\n"
        f"  send   : {sent_subject!r}"
    )
    expected_body = sanitise_email_html(sent_html)
    assert preview["body_html"] == expected_body, (
        f"{template_type}: body_html diverged from the send default-render path"
    )


# ---------------------------------------------------------------------------
# The per-example coroutine: seed, run both paths for every surface, compare.
# ---------------------------------------------------------------------------


async def _run_example(data: dict) -> None:
    engine, factory = await _make_engine_and_factory()
    try:
        ids = await _seed(factory, data)

        # ---- invoice_issued → invoices.service.email_invoice ----
        preview = await _preview(factory, ids, "invoice_issued", "invoice", ids["invoice_id"])
        cap = _Captured()
        async with factory() as session:
            async with session.begin():
                with patch(
                    "app.integrations.email_sender.send_email",
                    new=_fake_send_email(cap),
                ), patch(
                    "app.modules.invoices.service.generate_invoice_pdf",
                    new=AsyncMock(return_value=b"PDF"),
                ):
                    from app.modules.invoices.service import email_invoice

                    await email_invoice(
                        session, org_id=ids["org_id"], invoice_id=ids["invoice_id"]
                    )
        assert cap.message is not None, "invoice_issued: send path did not dispatch"
        _assert_equivalent("invoice_issued", preview, cap.message.subject, cap.message.html_body)

        # ---- payment_received → payments.service._send_receipt_email ----
        preview = await _preview(factory, ids, "payment_received", "invoice", ids["invoice_id"])
        cap = _Captured()
        async with factory() as session:
            async with session.begin():
                invoice = (
                    await session.execute(
                        select(Invoice).where(Invoice.id == ids["invoice_id"])
                    )
                ).scalar_one()
                with patch(
                    "app.integrations.email_sender.send_email",
                    new=_fake_send_email(cap),
                ), patch(
                    "app.modules.invoices.service.generate_invoice_pdf",
                    new=AsyncMock(return_value=b"PDF"),
                ):
                    from app.modules.payments.service import _send_receipt_email

                    await _send_receipt_email(
                        session,
                        to_email="recipient@example.com",
                        invoice=invoice,
                        pay_amount=invoice.amount_paid,
                        template_type="payment_received",
                    )
        assert cap.message is not None, "payment_received: send path did not dispatch"
        _assert_equivalent("payment_received", preview, cap.message.subject, cap.message.html_body)

        # ---- invoice_payment_link → _send_receipt_email (invoice_issued mode) ----
        preview = await _preview(
            factory, ids, "invoice_payment_link", "invoice", ids["invoice_id"]
        )
        cap = _Captured()
        async with factory() as session:
            async with session.begin():
                invoice = (
                    await session.execute(
                        select(Invoice).where(Invoice.id == ids["invoice_id"])
                    )
                ).scalar_one()
                with patch(
                    "app.integrations.email_sender.send_email",
                    new=_fake_send_email(cap),
                ), patch(
                    "app.modules.invoices.service.generate_invoice_pdf",
                    new=AsyncMock(return_value=b"PDF"),
                ):
                    from app.modules.payments.service import _send_receipt_email

                    await _send_receipt_email(
                        session,
                        to_email="recipient@example.com",
                        invoice=invoice,
                        pay_amount=invoice.balance_due,
                        template_type="invoice_issued",
                        payment_url=invoice.payment_page_url,
                    )
        assert cap.message is not None, "invoice_payment_link: send path did not dispatch"
        _assert_equivalent(
            "invoice_payment_link", preview, cap.message.subject, cap.message.html_body
        )

        # ---- quote_sent → quotes.service.send_quote ----
        preview = await _preview(factory, ids, "quote_sent", "quote", ids["quote_id"])
        cap = _Captured()
        async with factory() as session:
            async with session.begin():
                with patch(
                    "app.integrations.email_sender.send_email",
                    new=_fake_send_email(cap),
                ), patch(
                    "app.modules.quotes.service.generate_quote_pdf",
                    new=AsyncMock(return_value=b"PDF"),
                ):
                    from app.modules.quotes.service import send_quote

                    await send_quote(
                        session,
                        org_id=ids["org_id"],
                        user_id=ids["user_id"],
                        quote_id=ids["quote_id"],
                    )
        assert cap.message is not None, "quote_sent: send path did not dispatch"
        _assert_equivalent("quote_sent", preview, cap.message.subject, cap.message.html_body)

        # ---- portal_link → customers.service.send_portal_link ----
        # send_portal_link dispatches via the queued send_email_task; capture
        # the html_body/subject it enqueues and compare against the preview.
        preview = await _preview(factory, ids, "portal_link", "customer", ids["customer_id"])
        task_capture: dict = {}

        async def _fake_task(**kwargs):
            task_capture.update(kwargs)

        async with factory() as session:
            async with session.begin():
                with patch("app.tasks.notifications.send_email_task", new=_fake_task):
                    from app.modules.customers.service import send_portal_link

                    await send_portal_link(
                        session,
                        org_id=ids["org_id"],
                        user_id=ids["user_id"],
                        customer_id=ids["customer_id"],
                    )
        assert task_capture, "portal_link: send path did not enqueue an email"
        _assert_equivalent(
            "portal_link", preview, task_capture["subject"], task_capture["html_body"]
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()


# ---------------------------------------------------------------------------
# Property 1 — Send-default byte-equivalence.
# ---------------------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=_entity_data())
def test_send_default_byte_equivalence(data):
    """Feature: send-email-modal, Property 1: Send-default byte-equivalence.

    For any supported ``(template_type, entity)``, the subject + sanitised
    ``body_html`` bytes from ``build_email_preview()`` exactly equal the bytes
    the underlying send function produces on its no-override default-render
    path.

    **Validates: Requirements 3.6, 20.5**
    """
    asyncio.run(_run_example(data))
