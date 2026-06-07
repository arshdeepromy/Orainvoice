"""Exploratory bug-condition test — preview ``body_html`` is a full document.

Bugfix: email-preview-body-mismatch, Task 6.1 (exploratory phase).

Root cause being documented/locked here:
``email_compose.service.build_email_preview()`` returns ``body_html`` as a
**complete transactional HTML document** (``<!DOCTYPE>…<head><title>{subject}
</title></head><body>…</body></html>``). The Send-Email-Modal historically fed
that whole document into a TipTap editor, which surfaced the ``<title>`` text
as the first editable body paragraph — the "subject leaked into the body"
defect (bugfix Requirement 2.1, bug condition 1.1).

This test asserts the bug-producing property of the *raw artifact*: the
full-document ``body_html`` field STILL contains ``<title>`` and the subject
string. That field is UNCHANGED by the fix (by design — it backs Property 1
byte-equivalence and the faithful "this is the whole email" representation).
The fix moved the editor to bind to the NEW ``body_editable_html`` fragment
instead, so this exploration test is expected to PASS: it demonstrates *why*
the contract change was necessary by showing the old seeding source was a full
document.

It runs DB-backed against the dev Postgres database, reusing the seed/teardown
approach of ``tests/test_email_compose_preview.py``.

**Validates: Requirements 2.1**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

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

from app.integrations.email_sender import render_transactional_html
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.customers.models import Customer
from app.modules.email_compose.service import build_email_preview
from app.modules.invoices.models import Invoice


# Marker baked into seeded org names so cleanup can find orphans even if a
# test aborts mid-way.
_ORG_MARKER = "TEST_6_1_body_leak"


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
                "line_items",
                "invoices",
                "notification_log",
                "notification_templates",
                "bounced_addresses",
                "customers",
                "invoice_sequences",
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

            invoice = Invoice(
                org_id=org.id,
                customer_id=customer.id,
                created_by=user.id,
                invoice_number="INV-6001",
                status="issued",
                currency="NZD",
                issue_date=date.today(),
                due_date=date.today() + timedelta(days=14),
                subtotal=Decimal("100.00"),
                gst_amount=Decimal("15.00"),
                total=Decimal("115.00"),
                amount_paid=Decimal("0.00"),
                balance_due=Decimal("115.00"),
                payment_page_url="https://pay.example.com/inv-6001",
            )
            session.add(invoice)
            await session.flush()

            return {
                "org_id": org.id,
                "invoice_id": invoice.id,
            }


@pytest.mark.asyncio
async def test_preview_body_html_is_full_document_and_leaks_subject():
    """The full-document ``body_html`` field leaks the subject into the body.

    This demonstrates the ROOT CAUSE on the two artifacts that exhibit it:

    1. The *unsanitised* full document produced by ``render_transactional_html``
       (what the preview wraps before sanitising) is a complete HTML document
       carrying ``<!DOCTYPE>`` + ``<head><title>{subject}</title>`` — the
       document chrome whose ``<title>`` text the TipTap editor surfaced as the
       first editable body paragraph.

    2. The *sanitised* ``body_html`` field the preview returns (the OLD editor
       seeding source). ``sanitise_email_html`` strips disallowed tags
       (``<!DOCTYPE>``, ``<head>``, ``<title>``) but PRESERVES their text
       (``strip=True``), so the subject survives as a bare leading text node
       BEFORE the body ``<div>`` — which is precisely what leaked into the
       editor as the first visible line.

    The fix moved the editor onto the NEW ``body_editable_html`` fragment
    (asserted clean here as the contrast), leaving this full-document field
    unchanged so Property 1 byte-equivalence still holds.

    **Validates: Requirements 2.1**
    """
    engine, factory = await _make_engine_and_factory()
    try:
        await _cleanup(factory)
        ids = await _seed(factory)

        async with factory() as session:
            async with session.begin():
                preview = await build_email_preview(
                    session,
                    org_id=ids["org_id"],
                    template_type="invoice_issued",
                    entity_type="invoice",
                    entity_id=ids["invoice_id"],
                )

        subject = preview["subject"]
        body_html = preview["body_html"]
        assert subject, "preview produced an empty subject (fixture problem)"

        # --- (1) The pre-sanitise full document carries the chrome + <title>. ---
        # Reconstruct the exact wrapper the preview feeds into sanitise_email_html
        # for this surface to show the literal <!DOCTYPE>/<title>{subject} markup.
        raw_document = render_transactional_html(
            "Body text here.",
            subject=subject,
        )
        raw_lower = raw_document.lower()
        assert "<!doctype" in raw_lower, (
            "render_transactional_html should emit a full HTML document (DOCTYPE)"
        )
        assert f"<title>{subject}".lower() in raw_lower or "<title>" in raw_lower, (
            "the document head should carry a <title> element — the leak source"
        )
        assert subject in raw_document, (
            "the subject is embedded in the document <title> — feeding the whole "
            "document to TipTap surfaced it as editable body text"
        )

        # --- (2) The sanitised body_html field STILL leaks the subject text. ---
        # sanitise_email_html strips the <title>/<head>/<!DOCTYPE> tags but keeps
        # their TEXT, so the subject survives as a leading text node ahead of the
        # body <div>. This is the OLD editor seeding source and the observed leak.
        assert subject in body_html, (
            "the subject string still appears in the full-document body_html "
            "(as preserved <title> text) — this is the leak the bugfix addresses"
        )
        assert body_html.strip().startswith(subject), (
            "the subject leaks as the FIRST text in body_html, ahead of the body "
            "<div> — exactly the leading line the editor displayed"
        )

        # --- Contrast: the NEW editable fragment the editor now binds to is
        # clean — no chrome, no subject leak. (Shows why the fix works.) ---
        editable = preview["body_editable_html"]
        lower = editable.lower()
        assert "<!doctype" not in lower
        assert "<head" not in lower
        assert "<title" not in lower
        assert subject not in editable, (
            "body_editable_html must not contain the subject (no leak)"
        )
    finally:
        await _cleanup(factory)
        await engine.dispose()
