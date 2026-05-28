"""Bug 1 preservation property test — failure-path behaviour unchanged.

This file pins **Property 2: Preservation** for the
email-delivery-visibility-fixes spec. Each of the six Group A email
sites is exercised with ``send_email`` mocked to return a *failed*
:class:`~app.integrations.email_sender.SendResult`. The test then
asserts the failure-path observability calls fire **exactly as today**:

- ``log_email_sent`` was called with ``status="failed"`` AND a
  non-empty ``error_message``.
- ``create_in_app_notification`` was called with
  ``category="email_failure"``.

The Bug 1 success-path fix (tasks 7-12) MUST NOT touch this branch.
This test runs on UNFIXED code today and is expected to PASS — that
result locks in current correct behaviour. After the success-path fix
ships, re-running this file MUST still pass.

Group A sites under test, with the failure-path call pattern observed
today (see ``bugfix.md`` Affected Files + the failure branches in each
service module):

1. ``app.modules.invoices.service.email_invoice`` →
   ``log_email_sent(status="failed", template_type="invoice_send")`` +
   ``create_in_app_notification(category="email_failure")`` +
   ``raise ValueError``.
2. ``app.modules.quotes.service.send_quote`` →
   ``log_email_sent(status="failed", template_type="quote_send")`` +
   ``create_in_app_notification(category="email_failure")`` +
   ``raise ValueError``.
3. ``app.modules.vehicles.report_service.email_service_history_report`` →
   ``log_email_sent(status="failed", template_type="vehicle_report_send")`` +
   ``create_in_app_notification(category="email_failure")`` +
   ``raise ValueError``.
4. ``app.modules.payments.service._send_receipt_email`` →
   ``create_in_app_notification(category="email_failure")`` only, no
   ``log_email_sent`` call (best-effort site, returns ``None``).
5. ``app.modules.bookings.service._send_booking_confirmation_email`` →
   ``create_in_app_notification(category="email_failure")`` only, no
   ``log_email_sent`` call (best-effort site, returns ``False``).
6. ``app.modules.customers.service.notify_customer`` →
   ``log_email_sent(status="failed", template_type="customer_notify")`` +
   ``create_in_app_notification(category="email_failure")`` +
   ``raise ValueError``.

The third assertion (``log_email_sent`` failure row) is omitted for
sites 4 and 5 because those sites have NEVER written a
``log_email_sent`` row for failure — they were classified in the
email-provider-unification spec as best-effort sites where the
in-app notification is the only failure surface. Adding a
``log_email_sent`` failure row to those sites is out of scope for
this spec (Bug 1 only fixes the *success* path; failure-path
behaviour must remain exactly as observed today per Requirement 4.1).

Validates: Requirements 4.1, 4.2
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


# Sentinel error string used by ``_make_failure_send_result``. Asserted
# verbatim on the ``error_message`` kwarg so we know the failure-path
# code propagated the provider error through to ``log_email_sent``
# rather than swallowing it.
_FAILURE_ERROR = "boom"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_failure_send_result() -> MagicMock:
    """Return a mock ``SendResult`` describing a failed send.

    Mirrors the success-path helper in
    ``tests/test_notification_log_success_path.py`` but flips
    ``success`` to ``False`` and sets ``error`` to ``_FAILURE_ERROR``.
    The handlers under test read ``result.error`` to compose
    ``error_message=...`` for ``log_email_sent``.
    """
    result = MagicMock()
    result.success = False
    result.provider_key = None
    result.provider = None
    result.transport = None
    result.message_id = None
    result.provider_message_id = None
    result.error = _FAILURE_ERROR
    result.attempts = []
    return result


def _scalar_one_or_none_result(value) -> MagicMock:
    """Build a SQLAlchemy result whose ``scalar_one_or_none`` returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
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


async def _drive_email_invoice(
    org_id: uuid.UUID, recipient_email: str
) -> tuple[AsyncMock, AsyncMock]:
    """Drive ``email_invoice`` with all dependencies mocked.

    Returns ``(log_email_stub, in_app_notification_stub)`` so the
    caller can inspect the failure-path calls.

    The function is expected to ``raise ValueError`` on failure — we
    catch and re-raise nothing because the failure-path observability
    calls fire BEFORE the raise.
    """
    inv_dict = _build_invoice_dict(org_id=org_id, recipient_email=recipient_email)
    invoice_id = inv_dict["id"]

    org = _make_org(org_id)

    # Inv ORM row — already issued, so the auto-issue branch is skipped
    # (irrelevant on failure path because we raise before it).
    invoice_obj = MagicMock()
    invoice_obj.id = invoice_id
    invoice_obj.org_id = org_id
    invoice_obj.status = "issued"
    invoice_obj.invoice_number = "INV-9001"

    db = AsyncMock()
    # email_invoice executes (in order) on the failure path: org for
    # signature, latest payment lookup. Pad with a couple extra ``None``
    # rows in case of unexpected SELECTs in the unfixed code.
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),  # org for signature
            _scalar_one_or_none_result(None),  # latest payment (none)
            _scalar_one_or_none_result(None),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    in_app_notification_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_failure_send_result())

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
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=in_app_notification_stub,
    ):
        from app.modules.invoices.service import email_invoice

        with pytest.raises(ValueError, match="All email providers failed"):
            await email_invoice(
                db,
                org_id=org_id,
                invoice_id=invoice_id,
                recipient_email=recipient_email,
            )

    send_email_stub.assert_awaited_once()
    return log_email_stub, in_app_notification_stub


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


async def _drive_send_quote(
    org_id: uuid.UUID, recipient_email: str
) -> tuple[AsyncMock, AsyncMock]:
    """Drive ``send_quote`` failure path."""
    quote_dict = _build_quote_dict(org_id=org_id, recipient_email=recipient_email)
    quote_id = quote_dict["id"]
    customer_id = quote_dict["customer_id"]

    org = _make_org(org_id)
    customer = _make_customer(
        org_id=org_id, customer_id=customer_id, email=recipient_email
    )

    # Quote ORM row used for the draft → sent transition.
    quote_obj = MagicMock()
    quote_obj.id = quote_id
    quote_obj.org_id = org_id
    quote_obj.status = "draft"
    quote_obj.acceptance_token = None

    db = AsyncMock()
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
    in_app_notification_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_failure_send_result())

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
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=in_app_notification_stub,
    ):
        from app.modules.quotes.service import send_quote

        with pytest.raises(ValueError, match="All email providers failed"):
            await send_quote(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                quote_id=quote_id,
                recipient_email=recipient_email,
            )

    send_email_stub.assert_awaited_once()
    return log_email_stub, in_app_notification_stub


# ---------------------------------------------------------------------------
# Site driver — A5 ``email_service_history_report``
# ---------------------------------------------------------------------------


async def _drive_email_vehicle_report(
    org_id: uuid.UUID, recipient_email: str
) -> tuple[AsyncMock, AsyncMock]:
    """Drive ``email_service_history_report`` failure path."""
    vehicle_id = uuid.uuid4()
    org = _make_org(org_id)

    vehicle = MagicMock()
    vehicle.id = vehicle_id
    vehicle.rego = "ABC123"
    vehicle.make = "Toyota"
    vehicle.model = "Corolla"
    vehicle.year = 2020

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(vehicle),  # GlobalVehicle hit
            _scalar_one_or_none_result(org),  # Organisation
            _scalar_one_or_none_result(None),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    in_app_notification_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_failure_send_result())

    with patch(
        "app.modules.vehicles.report_service.generate_service_history_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-fake-bytes",
    ), patch(
        "app.core.audit.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=in_app_notification_stub,
    ):
        from app.modules.vehicles.report_service import email_service_history_report

        with pytest.raises(ValueError, match="All email providers failed"):
            await email_service_history_report(
                db,
                org_id=org_id,
                vehicle_id=vehicle_id,
                range_years=2,
                recipient_email=recipient_email,
            )

    send_email_stub.assert_awaited_once()
    return log_email_stub, in_app_notification_stub


# ---------------------------------------------------------------------------
# Site driver — A4 ``_send_receipt_email``
# ---------------------------------------------------------------------------


async def _drive_send_receipt_email(
    org_id: uuid.UUID, recipient_email: str
) -> tuple[AsyncMock, AsyncMock]:
    """Drive ``_send_receipt_email`` failure path.

    This site is best-effort: it does NOT raise, does NOT call
    ``log_email_sent``, and returns ``None``. The only failure
    observability surface today is
    ``create_in_app_notification(category="email_failure")``.
    """
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
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),
            _scalar_one_or_none_result(customer),
            _scalar_one_or_none_result(None),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    in_app_notification_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_failure_send_result())

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
        new=in_app_notification_stub,
    ):
        from app.modules.payments.service import _send_receipt_email

        # Best-effort: does not raise on failure.
        await _send_receipt_email(
            db,
            to_email=recipient_email,
            invoice=invoice,
            pay_amount=Decimal("100.00"),
        )

    send_email_stub.assert_awaited_once()
    return log_email_stub, in_app_notification_stub


# ---------------------------------------------------------------------------
# Site driver — A6 ``_send_booking_confirmation_email``
# ---------------------------------------------------------------------------


async def _drive_send_booking_confirmation_email(
    org_id: uuid.UUID, recipient_email: str
) -> tuple[AsyncMock, AsyncMock]:
    """Drive ``_send_booking_confirmation_email`` failure path.

    This site is best-effort: returns ``False`` on failure, does NOT
    call ``log_email_sent``. The only failure observability surface
    today is ``create_in_app_notification(category="email_failure")``.
    """
    booking_id = uuid.uuid4()
    org = _make_org(org_id)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_one_or_none_result(org),
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    in_app_notification_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_failure_send_result())

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
        new=in_app_notification_stub,
    ):
        from app.modules.bookings.service import _send_booking_confirmation_email

        result = await _send_booking_confirmation_email(
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

    # Site contract: returns False on failure.
    assert result is False, (
        "Preservation regression: _send_booking_confirmation_email "
        "returned %r on failure, expected False" % result
    )
    send_email_stub.assert_awaited_once()
    return log_email_stub, in_app_notification_stub


# ---------------------------------------------------------------------------
# Site driver — A12 ``notify_customer``
# ---------------------------------------------------------------------------


async def _drive_notify_customer(
    org_id: uuid.UUID, recipient_email: str
) -> tuple[AsyncMock, AsyncMock]:
    """Drive ``notify_customer`` failure path."""
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
            _scalar_one_or_none_result(None),
        ]
    )

    log_email_stub = AsyncMock()
    in_app_notification_stub = AsyncMock()
    send_email_stub = AsyncMock(return_value=_make_failure_send_result())

    with patch(
        "app.modules.customers.service.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "app.modules.notifications.service.log_email_sent",
        new=log_email_stub,
    ), patch(
        "app.integrations.email_sender.send_email",
        new=send_email_stub,
    ), patch(
        "app.modules.in_app_notifications.service.create_in_app_notification",
        new=in_app_notification_stub,
    ):
        from app.modules.customers.service import notify_customer

        with pytest.raises(ValueError, match="All email providers failed"):
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
    return log_email_stub, in_app_notification_stub


# ---------------------------------------------------------------------------
# Property assertion helpers
# ---------------------------------------------------------------------------


def _assert_failure_log_written(
    log_email_stub: AsyncMock,
    *,
    site_name: str,
    expected_template_type: str,
    expected_recipient: str,
) -> None:
    """Assert ``log_email_sent`` was called with ``status="failed"``.

    Validates Requirement 4.1 — the failure-path observability call
    fires today and must continue to fire after the success-path fix
    lands.
    """
    calls = log_email_stub.await_args_list

    failed_calls = [c.kwargs for c in calls if c.kwargs.get("status") == "failed"]

    assert failed_calls, (
        f"PRESERVATION regression: site={site_name!r} returned a failed "
        f"SendResult, but log_email_sent was NEVER called with "
        f"status='failed'. Total log_email_sent calls: {len(calls)} "
        f"(statuses seen: {[c.kwargs.get('status') for c in calls]}). "
        f"Expected one call with template_type={expected_template_type!r}, "
        f"status='failed', recipient={expected_recipient!r} (Requirement 4.1)."
    )

    matching = [
        c for c in failed_calls
        if c.get("template_type") == expected_template_type
        and c.get("recipient") == expected_recipient
    ]
    assert matching, (
        f"PRESERVATION regression: site={site_name!r} called log_email_sent "
        f"with status='failed' but the template_type or recipient was "
        f"wrong. Got: {failed_calls}. Expected: "
        f"template_type={expected_template_type!r}, "
        f"recipient={expected_recipient!r}."
    )

    # Each matching call must carry a non-empty ``error_message`` —
    # the failure-path code reads ``result.error`` and propagates it.
    for kwargs in matching:
        error_message = kwargs.get("error_message") or kwargs.get("error") or ""
        assert error_message, (
            f"PRESERVATION regression: site={site_name!r} wrote "
            f"log_email_sent(status='failed') without a non-empty "
            f"error_message kwarg. Got kwargs={kwargs}. Expected the "
            f"failure-path code to propagate result.error "
            f"({_FAILURE_ERROR!r}) into error_message."
        )


def _assert_email_failure_in_app_notification(
    in_app_notification_stub: AsyncMock,
    *,
    site_name: str,
    expected_recipient: str,
) -> None:
    """Assert ``create_in_app_notification(category="email_failure")`` fired.

    Validates Requirement 4.1 — the in-app email-failure notification
    is the user-facing surface for total send failures and must
    continue to fire today.
    """
    calls = in_app_notification_stub.await_args_list

    failure_calls = [
        c.kwargs for c in calls
        if c.kwargs.get("category") == "email_failure"
    ]

    assert failure_calls, (
        f"PRESERVATION regression: site={site_name!r} returned a failed "
        f"SendResult, but create_in_app_notification was NEVER called "
        f"with category='email_failure'. Total calls: {len(calls)} "
        f"(categories seen: {[c.kwargs.get('category') for c in calls]}). "
        f"Expected the user-facing email-failure notification to fire "
        f"(Requirement 4.1)."
    )

    # Every email_failure call must reference the recipient — either
    # in the title (substring) or in the metadata dict — so the admin
    # can identify which customer the bounce affected.
    for kwargs in failure_calls:
        title = kwargs.get("title") or ""
        metadata = kwargs.get("metadata") or {}
        recipient_in_metadata = (
            metadata.get("recipient_email") == expected_recipient
        )
        recipient_in_title = expected_recipient in title
        assert recipient_in_metadata or recipient_in_title, (
            f"PRESERVATION regression: site={site_name!r} fired "
            f"create_in_app_notification(category='email_failure') but "
            f"the recipient {expected_recipient!r} was not surfaced in "
            f"either the title or metadata. Got title={title!r}, "
            f"metadata={metadata!r}."
        )



# ---------------------------------------------------------------------------
# Property tests — one per Group A site
# ---------------------------------------------------------------------------


class TestBug1NotificationLogFailurePreservation:
    """Property 2 — failure-path observability calls fire today.

    Each test case drives one Group A site with ``send_email`` mocked
    to return failure and asserts the existing failure-path
    observability calls fire exactly as observed today. Expected to
    PASS on UNFIXED code (these tests lock in the current behaviour
    that the Bug 1 success-path fix MUST NOT regress).

    Validates: Requirements 4.1, 4.2
    """

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_email_invoice_logs_failure_and_in_app_notification(
        self, pair
    ) -> None:
        """``email_invoice`` failure path: log_email_sent + in-app notification.

        EXPECTED TO PASS on UNFIXED code (preservation test).

        Validates: Requirement 4.1
        """
        org_id, recipient_email = pair
        log_email_stub, in_app_stub = await _drive_email_invoice(
            org_id, recipient_email
        )
        _assert_failure_log_written(
            log_email_stub,
            site_name="email_invoice",
            expected_template_type="invoice_send",
            expected_recipient=recipient_email,
        )
        _assert_email_failure_in_app_notification(
            in_app_stub,
            site_name="email_invoice",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_send_quote_logs_failure_and_in_app_notification(
        self, pair
    ) -> None:
        """``send_quote`` failure path: log_email_sent + in-app notification.

        EXPECTED TO PASS on UNFIXED code (preservation test).

        Validates: Requirement 4.1
        """
        org_id, recipient_email = pair
        log_email_stub, in_app_stub = await _drive_send_quote(
            org_id, recipient_email
        )
        _assert_failure_log_written(
            log_email_stub,
            site_name="send_quote",
            expected_template_type="quote_send",
            expected_recipient=recipient_email,
        )
        _assert_email_failure_in_app_notification(
            in_app_stub,
            site_name="send_quote",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_email_vehicle_report_logs_failure_and_in_app_notification(
        self, pair
    ) -> None:
        """``email_service_history_report`` failure path observability.

        EXPECTED TO PASS on UNFIXED code (preservation test).

        Validates: Requirement 4.1
        """
        org_id, recipient_email = pair
        log_email_stub, in_app_stub = await _drive_email_vehicle_report(
            org_id, recipient_email
        )
        _assert_failure_log_written(
            log_email_stub,
            site_name="email_service_history_report",
            expected_template_type="vehicle_report_send",
            expected_recipient=recipient_email,
        )
        _assert_email_failure_in_app_notification(
            in_app_stub,
            site_name="email_service_history_report",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_send_receipt_email_logs_in_app_notification(
        self, pair
    ) -> None:
        """``_send_receipt_email`` failure path: in-app notification only.

        Best-effort site — never called ``log_email_sent`` on failure
        even before this spec. Only the in-app notification surface is
        observable today, and that is what the success-path fix MUST
        leave unchanged.

        EXPECTED TO PASS on UNFIXED code (preservation test).

        Validates: Requirement 4.1
        """
        org_id, recipient_email = pair
        _, in_app_stub = await _drive_send_receipt_email(
            org_id, recipient_email
        )
        _assert_email_failure_in_app_notification(
            in_app_stub,
            site_name="_send_receipt_email",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_send_booking_confirmation_email_logs_in_app_notification(
        self, pair
    ) -> None:
        """``_send_booking_confirmation_email`` failure: in-app notification only.

        Best-effort site — same as ``_send_receipt_email``. The site
        returns ``False`` on failure (asserted inside the driver) and
        fires the email_failure in-app notification but no
        ``log_email_sent`` row.

        EXPECTED TO PASS on UNFIXED code (preservation test).

        Validates: Requirement 4.1
        """
        org_id, recipient_email = pair
        _, in_app_stub = await _drive_send_booking_confirmation_email(
            org_id, recipient_email
        )
        _assert_email_failure_in_app_notification(
            in_app_stub,
            site_name="_send_booking_confirmation_email",
            expected_recipient=recipient_email,
        )

    @_PBT_SETTINGS
    @given(pair=_seeded_pairs)
    @pytest.mark.asyncio
    async def test_notify_customer_logs_failure_and_in_app_notification(
        self, pair
    ) -> None:
        """``notify_customer`` failure path: log_email_sent + in-app notification.

        EXPECTED TO PASS on UNFIXED code (preservation test).

        Validates: Requirement 4.1
        """
        org_id, recipient_email = pair
        log_email_stub, in_app_stub = await _drive_notify_customer(
            org_id, recipient_email
        )
        _assert_failure_log_written(
            log_email_stub,
            site_name="notify_customer",
            expected_template_type="customer_notify",
            expected_recipient=recipient_email,
        )
        _assert_email_failure_in_app_notification(
            in_app_stub,
            site_name="notify_customer",
            expected_recipient=recipient_email,
        )
