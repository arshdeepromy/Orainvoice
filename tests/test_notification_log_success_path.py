"""Bug 1 condition exploration test — ``notification_log`` empty (or
incomplete) on successful email for Group A migrated sites.

This file pins **Property 1: Bug Condition** for the
email-delivery-visibility-fixes spec. Each of the six Group A email
sites is exercised with ``send_email`` mocked to return a successful
:class:`~app.integrations.email_sender.SendResult`. The test then
asserts that
:func:`app.modules.notifications.service.log_email_sent` is called with
``status="sent"``, the site's ``template_type``, AND the winning
provider's ``provider_key`` / ``provider_message_id`` — the full
shape required for the Phase 8c bounce-correlation pipeline to match
inbound delivered/bounced webhooks to the row (Requirements 3.1, 3.2,
3.5).

**This test is EXPECTED TO FAIL on UNFIXED code for ALL SIX sites.**
The bug pattern manifests in two flavours:

- Flavour 1 (5 sites): no ``log_email_sent(status="sent")`` call at
  all — the success branch only writes ``audit_log``. Sites:
  ``email_invoice``, ``send_quote``, ``email_service_history_report``,
  ``_send_receipt_email``, ``_send_booking_confirmation_email``.
- Flavour 2 (1 site): ``log_email_sent(status="sent")`` IS called,
  but ``provider_key`` and ``provider_message_id`` are omitted, so the
  resulting row cannot be correlated with bounce webhooks. Site:
  ``notify_customer``.

The Hypothesis decorator drives the test with a small set of seeded
``(org_id, recipient_email)`` pairs to satisfy the spec's
"property-based test with seeded inputs" requirement while keeping the
example count small enough that the suite stays fast.

Group A sites under test:

1. ``app.modules.invoices.service.email_invoice``
   → expected ``template_type="invoice_send"``
2. ``app.modules.quotes.service.send_quote``
   → expected ``template_type="quote_send"``
3. ``app.modules.vehicles.report_service.email_service_history_report``
   → expected ``template_type="vehicle_report_send"``
4. ``app.modules.payments.service._send_receipt_email``
   → expected ``template_type="payment_receipt"``
5. ``app.modules.bookings.service._send_booking_confirmation_email``
   → expected ``template_type="booking_confirmation"``
6. ``app.modules.customers.service.notify_customer``
   → expected ``template_type="customer_notify"`` (with provider_key +
   provider_message_id required for bounce correlation)

Validates: Requirements 1.1, 1.3, 1.4, 1.5
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

# Import models so SQLAlchemy can resolve all relationships at import
# time. ``app.modules.admin.models`` brings in ``EmailProvider`` /
# ``Organisation``.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.customers.models import Customer
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401


# ---------------------------------------------------------------------------
# Hypothesis strategies — small seeded set per task spec
# ---------------------------------------------------------------------------


# Seeded set of org ids — small to keep the test fast.
_ORG_IDS = [
    uuid.UUID("11111111-1111-4111-8111-111111111111"),
    uuid.UUID("22222222-2222-4222-8222-222222222222"),
    uuid.UUID("33333333-3333-4333-8333-333333333333"),
]

# Seeded set of recipient emails — covers ASCII, longer local-parts.
_RECIPIENTS = [
    "casey@example.com",
    "alex+test@workshop.co.nz",
    "jordan_long_local_part@deliveries.example.org",
]


_seeded_pairs = st.tuples(
    st.sampled_from(_ORG_IDS),
    st.sampled_from(_RECIPIENTS),
)


# Hypothesis settings — small example count, no deadline (the real cost
# is the function-under-test's setup, not the strategy).
_PBT_SETTINGS = hyp_settings(
    max_examples=9,  # 3 orgs × 3 recipients = 9 pairs
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_send_result(
    *,
    provider_key: str = "brevo",
    provider_message_id: str = "msg-bug1-exploration-1",
) -> MagicMock:
    """Return a mock ``SendResult`` describing a successful send.

    The unified sender returns a real :class:`SendResult` dataclass;
    here we use a ``MagicMock`` so the call sites can read whichever
    attributes they need without us having to construct a full instance.
    """
    result = MagicMock()
    result.success = True
    result.provider_key = provider_key
    result.provider = provider_key  # backwards-compat alias used by some sites
    result.transport = "rest_api"
    result.message_id = provider_message_id
    result.provider_message_id = provider_message_id
    result.error = None
    result.attempts = []
    return result


def _scalar_one_or_none_result(value) -> MagicMock:
    """Build a SQLAlchemy result whose ``scalar_one_or_none`` returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_all_result(rows: list) -> MagicMock:
    """Build a SQLAlchemy result whose ``.scalars().all()`` returns ``rows``."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _make_org(org_id: uuid.UUID) -> MagicMock:
    """Mock an Organisation row used by every Group A site."""
    org = MagicMock()
    org.id = org_id
    org.name = "Test Workshop Ltd"
    org.settings = {
        "email": "info@test.co.nz",
        "phone": "09-555-1234",
        "email_signature_enabled": False,
        "email_signature": "",
    }
    org.base_currency = "NZD"
    return org


def _make_customer(
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    email: str,
) -> MagicMock:
    """Mock a Customer ORM row used by ``notify_customer`` / invoice sites."""
    customer = MagicMock(spec=Customer)
    customer.id = customer_id
    customer.org_id = org_id
    customer.first_name = "Casey"
    customer.last_name = "Tester"
    customer.email = email
    customer.phone = "+64 21 555 1234"
    customer.is_anonymised = False
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


# ---------------------------------------------------------------------------
# Site driver — A1 ``email_invoice``
# ---------------------------------------------------------------------------


def _build_invoice_dict(*, org_id: uuid.UUID, recipient_email: str) -> dict:
    """Invoice dict matching what ``get_invoice`` returns."""
    return {
        "id": uuid.uuid4(),
        "org_id": org_id,
        "invoice_number": "INV-9001",
        "customer_id": uuid.uuid4(),
        "customer": {
            "first_name": "Casey",
            "last_name": "Tester",
            "email": recipient_email,
        },
        "vehicle_rego": None,
        "branch_id": None,
        "status": "issued",
        "issue_date": date(2024, 6, 15),
        "due_date": date(2024, 7, 15),
        "currency": "NZD",
        "subtotal": Decimal("100.00"),
        "discount_amount": Decimal("0.00"),
        "gst_amount": Decimal("0.00"),
        "total": Decimal("100.00"),
        "amount_paid": Decimal("0.00"),
        "balance_due": Decimal("100.00"),
        "payment_gateway": None,
        "payment_page_url": None,
        "org_name": "Test Workshop Ltd",
        "org_email": "info@test.co.nz",
        "org_phone": "09-555-1234",
        "line_items": [],
        "created_at": datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
    }


async def _drive_email_invoice(org_id: uuid.UUID, recipient_email: str) -> AsyncMock:
    """Drive ``email_invoice`` with all dependencies mocked.

    Returns the ``log_email_sent`` mock so the caller can inspect calls.
    """
    inv_dict = _build_invoice_dict(org_id=org_id, recipient_email=recipient_email)
    invoice_id = inv_dict["id"]

    org = _make_org(org_id)

    # Inv ORM row — already issued, so the auto-issue branch is skipped.
    invoice_obj = MagicMock()
    invoice_obj.id = invoice_id
    invoice_obj.org_id = org_id
    invoice_obj.status = "issued"
    invoice_obj.invoice_number = "INV-9001"
    invoice_obj.issue_date = date(2024, 6, 15)
    invoice_obj.due_date = date(2024, 7, 15)
    invoice_obj.invoice_data_json = {}

    db = AsyncMock()
    # email_invoice executes (in order, when payment_gateway != "stripe"
    # and recipient_email is provided): org-for-signature, latest-payment,
    # invoice-orm-for-auto-issue, org-for-stripe-pi.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),  # org for signature
            _scalar_one_or_none_result(None),  # latest payment (none)
            _scalar_one_or_none_result(invoice_obj),  # invoice for auto-issue
            _scalar_one_or_none_result(org),  # org for stripe PI (skipped)
        ]
    )

    log_email_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_send_result())

    with patch(
        "app.modules.invoices.service.get_invoice",
        new_callable=AsyncMock,
        return_value=inv_dict,
    ), patch(
        "app.modules.invoices.service.generate_invoice_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-fake-bytes",
    ), patch(
        "app.modules.invoices.service.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.invoices.attachment_service.list_attachments",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ), patch(
        "app.modules.invoices.service._maybe_create_stripe_payment_intent",
        new=AsyncMock(),
    ):
        from app.modules.invoices.service import email_invoice

        await email_invoice(
            db,
            org_id=org_id,
            invoice_id=invoice_id,
            recipient_email=recipient_email,
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub


# ---------------------------------------------------------------------------
# Site driver — A3 ``send_quote``
# ---------------------------------------------------------------------------


def _build_quote_dict(*, org_id: uuid.UUID, recipient_email: str) -> dict:
    """Quote dict matching what ``get_quote`` returns."""
    quote_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    return {
        "id": quote_id,
        "org_id": org_id,
        "quote_number": "QUO-101",
        "customer_id": customer_id,
        "status": "draft",
        "valid_until": date(2024, 7, 15),
        "total": Decimal("250.00"),
        "subtotal": Decimal("250.00"),
        "gst_amount": Decimal("0.00"),
        "discount_amount": Decimal("0.00"),
        "currency": "NZD",
        "line_items": [],
        "acceptance_token": None,
        "customer": {
            "first_name": "Casey",
            "last_name": "Tester",
            "email": recipient_email,
        },
    }


async def _drive_send_quote(org_id: uuid.UUID, recipient_email: str) -> AsyncMock:
    """Drive ``send_quote`` with all dependencies mocked."""
    quote_dict = _build_quote_dict(org_id=org_id, recipient_email=recipient_email)
    quote_id = quote_dict["id"]
    customer_id = quote_dict["customer_id"]

    org = _make_org(org_id)
    customer = _make_customer(
        org_id=org_id, customer_id=customer_id, email=recipient_email
    )

    # Quote ORM row used for the draft → sent transition. ``MagicMock``
    # auto-creates attributes lazily, but ``if not quote_obj.acceptance_token``
    # would treat a fresh ``MagicMock()`` child as truthy — explicitly
    # set it to ``None`` so the function generates a fresh token instead
    # of skipping the assignment.
    quote_obj = MagicMock()
    quote_obj.id = quote_id
    quote_obj.org_id = org_id
    quote_obj.status = "draft"
    quote_obj.acceptance_token = None

    db = AsyncMock()
    # ``send_quote`` execute order when ``recipient_email`` is provided
    # (so the customer-by-id SELECT is skipped):
    # 1. Quote SELECT for the status flip.
    # 2. Organisation SELECT.
    # 3. Customer SELECT for template variable context.
    # Pad with two extra default rows in case the template-resolution
    # path adds another query in a future refactor.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(quote_obj),
            _scalar_one_or_none_result(org),
            _scalar_one_or_none_result(customer),
            _scalar_one_or_none_result(None),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_send_result())

    with patch(
        "app.modules.quotes.service.get_quote",
        new_callable=AsyncMock,
        return_value=quote_dict,
    ), patch(
        "app.modules.quotes.service.generate_quote_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-fake-bytes",
    ), patch(
        "app.modules.quotes.service.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ):
        from app.modules.quotes.service import send_quote

        await send_quote(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            quote_id=quote_id,
            recipient_email=recipient_email,
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub


# ---------------------------------------------------------------------------
# Site driver — A5 ``email_service_history_report``
# ---------------------------------------------------------------------------


async def _drive_email_vehicle_report(
    org_id: uuid.UUID, recipient_email: str
) -> AsyncMock:
    """Drive ``email_service_history_report``."""
    vehicle_id = uuid.uuid4()
    org = _make_org(org_id)

    vehicle = MagicMock()
    vehicle.id = vehicle_id
    vehicle.rego = "ABC123"
    vehicle.make = "Toyota"
    vehicle.model = "Corolla"
    vehicle.year = 2020

    db = AsyncMock()
    # email_service_history_report execute order: GlobalVehicle by id,
    # OrgVehicle by id (only if global lookup returned None), Org by id.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(vehicle),  # GlobalVehicle hit
            _scalar_one_or_none_result(org),  # Organisation
            # Padding for write_audit_log internals if it isn't fully patched.
            _scalar_one_or_none_result(None),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_send_result())

    with patch(
        "app.modules.vehicles.report_service.generate_service_history_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-fake-bytes",
    ), patch(
        # ``write_audit_log`` is imported function-locally inside
        # ``email_service_history_report`` from ``app.core.audit`` —
        # patch at the source module so the function-local import
        # picks up the stub.
        "app.core.audit.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ):
        from app.modules.vehicles.report_service import email_service_history_report

        await email_service_history_report(
            db,
            org_id=org_id,
            vehicle_id=vehicle_id,
            range_years=2,
            recipient_email=recipient_email,
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub


# ---------------------------------------------------------------------------
# Site driver — A4 ``_send_receipt_email``
# ---------------------------------------------------------------------------


async def _drive_send_receipt_email(
    org_id: uuid.UUID, recipient_email: str
) -> AsyncMock:
    """Drive ``_send_receipt_email`` (payment receipt site)."""
    invoice_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    invoice = MagicMock()
    invoice.id = invoice_id
    invoice.org_id = org_id
    invoice.customer_id = customer_id
    invoice.invoice_number = "INV-2042"
    invoice.currency = "NZD"
    invoice.balance_due = Decimal("0.00")
    invoice.due_date = date(2024, 7, 15)
    invoice.payment_page_url = None

    org = _make_org(org_id)
    customer = _make_customer(
        org_id=org_id, customer_id=customer_id, email=recipient_email
    )

    db = AsyncMock()
    # _send_receipt_email execute order: org by invoice.org_id, customer
    # by invoice.customer_id.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),
            _scalar_one_or_none_result(customer),
            # Padding so a future template call doesn't break the side_effect chain.
            _scalar_one_or_none_result(None),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_send_result())

    with patch(
        "app.modules.invoices.service.generate_invoice_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-fake-bytes",
    ), patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ), patch(
        "app.modules.payments.service.create_in_app_notification",
        new=AsyncMock(),
    ):
        from app.modules.payments.service import _send_receipt_email

        await _send_receipt_email(
            db,
            to_email=recipient_email,
            invoice=invoice,
            pay_amount=Decimal("100.00"),
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub


# ---------------------------------------------------------------------------
# Site driver — A6 ``_send_booking_confirmation_email``
# ---------------------------------------------------------------------------


async def _drive_send_booking_confirmation_email(
    org_id: uuid.UUID, recipient_email: str
) -> AsyncMock:
    """Drive ``_send_booking_confirmation_email`` (booking confirmation site)."""
    booking_id = uuid.uuid4()
    org = _make_org(org_id)

    db = AsyncMock()
    # Function executes a single Org SELECT.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),
            # Padding.
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_send_result())

    with patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ), patch(
        "app.modules.bookings.service.create_in_app_notification",
        new=AsyncMock(),
    ):
        from app.modules.bookings.service import _send_booking_confirmation_email

        await _send_booking_confirmation_email(
            db,
            org_id=org_id,
            booking_id=booking_id,
            customer_first_name="Casey",
            customer_email=recipient_email,
            service_type="WOF",
            start_time=datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc),
            duration_minutes=60,
            vehicle_rego="ABC123",
            notes=None,
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub


# ---------------------------------------------------------------------------
# Site driver — A12 ``notify_customer``
# ---------------------------------------------------------------------------


async def _drive_notify_customer(
    org_id: uuid.UUID, recipient_email: str
) -> AsyncMock:
    """Drive ``notify_customer`` (one-off customer email site)."""
    customer_id = uuid.uuid4()
    user_id = uuid.uuid4()
    customer = _make_customer(
        org_id=org_id, customer_id=customer_id, email=recipient_email
    )
    org = _make_org(org_id)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(customer),
            _scalar_one_or_none_result(org),
            # Padding.
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_send_result())

    with patch(
        "app.modules.customers.service.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ):
        from app.modules.customers.service import notify_customer

        await notify_customer(
            db,
            org_id=org_id,
            user_id=user_id,
            customer_id=customer_id,
            channel="email",
            subject="Hello",
            message="Your car is ready for collection.",
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub


# ---------------------------------------------------------------------------
# Property assertion helper
# ---------------------------------------------------------------------------


def _assert_success_log_written(
    log_email_stub: AsyncMock,
    *,
    site_name: str,
    expected_template_type: str,
    expected_recipient: str,
    expected_provider_key: str = "brevo",
    expected_provider_message_id: str = "msg-bug1-exploration-1",
) -> None:
    """Assert ``log_email_sent`` was called with the full success-row shape.

    Per ``bugfix.md`` Requirements 3.1 / 3.2 / 3.5, the success-path
    row must carry ``status="sent"``, the site's ``template_type``,
    AND the winning provider's ``provider_key`` + ``provider_message_id``
    so the Phase 8c bounce-correlation webhook can match inbound
    delivered/bounced events to the row by ``provider_message_id``.

    On UNFIXED code, the five Group A gap sites (``email_invoice``,
    ``send_quote``, ``email_service_history_report``,
    ``_send_receipt_email``, ``_send_booking_confirmation_email``)
    never call ``log_email_sent(status="sent", ...)`` at all — this
    assertion fires on the first sub-assert below.

    The sixth site, ``notify_customer``, DOES call
    ``log_email_sent(status="sent", ...)`` (Phase 3 task 3.12 / A12
    migrated it correctly) — but it omits ``provider_key`` and
    ``provider_message_id``. That makes the row unusable for
    bounce-correlation and means Bug 1 is still present at this site
    in the narrower sense. The third sub-assert below catches that
    case.
    """
    # Collect every ``log_email_sent`` call argument bag.
    calls = log_email_stub.await_args_list

    # Filter to status='sent' calls only.
    sent_calls = [c.kwargs for c in calls if c.kwargs.get("status") == "sent"]

    # Sub-assert 1: at least one ``status='sent'`` row was written.
    assert sent_calls, (
        f"BUG 1 counterexample (no success row): site={site_name!r} called "
        f"send_email and got a successful SendResult, but log_email_sent "
        f"was NEVER called with status='sent'. Total log_email_sent calls: "
        f"{len(calls)} (non-sent statuses: "
        f"{[c.kwargs.get('status') for c in calls]}). Expected one call "
        f"with template_type={expected_template_type!r}, status='sent', "
        f"recipient={expected_recipient!r}."
    )

    # Sub-assert 2: at least one matches the expected template_type +
    # recipient. Catches sites that write the wrong template_type.
    matching_template = [
        c for c in sent_calls
        if c.get("template_type") == expected_template_type
        and c.get("recipient") == expected_recipient
    ]
    assert matching_template, (
        f"BUG 1 counterexample (wrong template/recipient): site={site_name!r} "
        f"wrote log_email_sent with status='sent' but the template_type or "
        f"recipient was wrong. Got: {sent_calls}. "
        f"Expected: template_type={expected_template_type!r}, "
        f"recipient={expected_recipient!r}."
    )

    # Sub-assert 3: the winning provider's key + message id were
    # captured. Per Requirements 3.1, 3.2, 3.5 the bounce-correlation
    # webhook joins on ``provider_message_id``, so a success row
    # without these two fields is unusable for the Phase 8c pipeline.
    matching_full = [
        c for c in matching_template
        if c.get("provider_key") == expected_provider_key
        and c.get("provider_message_id") == expected_provider_message_id
    ]
    assert matching_full, (
        f"BUG 1 counterexample (missing provider correlation fields): "
        f"site={site_name!r} wrote log_email_sent(status='sent', "
        f"template_type={expected_template_type!r}) but the row lacks "
        f"provider_key={expected_provider_key!r} or "
        f"provider_message_id={expected_provider_message_id!r}. "
        f"Got kwargs={matching_template}. "
        f"Without these fields the Phase 8c bounce-correlation webhook "
        f"cannot match inbound delivered/bounced events to this row "
        f"(Requirement 3.5)."
    )


# ---------------------------------------------------------------------------
# Property tests — one per Group A site
# ---------------------------------------------------------------------------


class TestBug1NotificationLogSuccessPath:
    """Property 1 — successful email writes ``notification_log`` row.

    Each test case drives one Group A site and asserts the
    notification_log row is written. EXPECTED TO FAIL on UNFIXED code
    for sites 1-5 (the five gap sites). Site 6 (``notify_customer``)
    is expected to PASS because that migration was already done
    correctly.

    Validates: Requirements 1.1, 1.3, 1.4, 1.5
    """

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_email_invoice_writes_notification_log_on_success(
        self, pair
    ) -> None:
        """``email_invoice`` success path must write ``notification_log``.

        EXPECTED TO FAIL on UNFIXED code: the success branch of
        ``email_invoice`` only calls ``write_audit_log``; there is no
        ``log_email_sent(status='sent', ...)`` call.

        Validates: Requirements 1.1, 1.3, 1.4, 1.5
        """
        org_id, recipient_email = pair
        log_email_stub = await _drive_email_invoice(org_id, recipient_email)
        _assert_success_log_written(
            log_email_stub,
            site_name="email_invoice",
            expected_template_type="invoice_send",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_send_quote_writes_notification_log_on_success(
        self, pair
    ) -> None:
        """``send_quote`` success path must write ``notification_log``.

        EXPECTED TO FAIL on UNFIXED code.

        Validates: Requirements 1.3, 1.4
        """
        org_id, recipient_email = pair
        log_email_stub = await _drive_send_quote(org_id, recipient_email)
        _assert_success_log_written(
            log_email_stub,
            site_name="send_quote",
            expected_template_type="quote_send",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_email_vehicle_report_writes_notification_log_on_success(
        self, pair
    ) -> None:
        """``email_service_history_report`` success path must write ``notification_log``.

        EXPECTED TO FAIL on UNFIXED code.

        Validates: Requirements 1.3, 1.4
        """
        org_id, recipient_email = pair
        log_email_stub = await _drive_email_vehicle_report(org_id, recipient_email)
        _assert_success_log_written(
            log_email_stub,
            site_name="email_service_history_report",
            expected_template_type="vehicle_report_send",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_send_receipt_email_writes_notification_log_on_success(
        self, pair
    ) -> None:
        """``_send_receipt_email`` success path must write ``notification_log``.

        EXPECTED TO FAIL on UNFIXED code.

        Validates: Requirements 1.3, 1.4
        """
        org_id, recipient_email = pair
        log_email_stub = await _drive_send_receipt_email(org_id, recipient_email)
        _assert_success_log_written(
            log_email_stub,
            site_name="_send_receipt_email",
            expected_template_type="payment_receipt",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_send_booking_confirmation_email_writes_notification_log_on_success(
        self, pair
    ) -> None:
        """``_send_booking_confirmation_email`` success path must write ``notification_log``.

        EXPECTED TO FAIL on UNFIXED code.

        Validates: Requirements 1.3, 1.4
        """
        org_id, recipient_email = pair
        log_email_stub = await _drive_send_booking_confirmation_email(
            org_id, recipient_email
        )
        _assert_success_log_written(
            log_email_stub,
            site_name="_send_booking_confirmation_email",
            expected_template_type="booking_confirmation",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_notify_customer_writes_notification_log_on_success(
        self, pair
    ) -> None:
        """``notify_customer`` success path must write ``notification_log``
        WITH ``provider_key`` and ``provider_message_id`` populated.

        EXPECTED TO FAIL on UNFIXED code: ``notify_customer`` already
        calls ``log_email_sent(status='sent', template_type='customer_notify')``
        but omits ``provider_key`` / ``provider_message_id`` from the
        kwargs. Without those two fields the Phase 8c bounce-correlation
        webhook cannot match inbound delivered/bounced events to this
        row (Requirement 3.5).

        Validates: Requirements 1.3, 1.4, 1.5, 3.2, 3.5
        """
        org_id, recipient_email = pair
        log_email_stub = await _drive_notify_customer(org_id, recipient_email)
        _assert_success_log_written(
            log_email_stub,
            site_name="notify_customer",
            expected_template_type="customer_notify",
            expected_recipient=recipient_email,
        )
