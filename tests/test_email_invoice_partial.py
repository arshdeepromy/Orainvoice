"""Unit tests for partial-payment-aware ``email_invoice`` subject and body.

Covers the changes made in tasks 13.5.1 / 13.5.2 / 13.5.3 of the
``qr-partial-payment`` spec:

  - The hardcoded fallback subject for a partial-payment receipt becomes
    "Partial payment received for invoice {number} — ${amount}".
  - The hardcoded fallback body gains a two-line summary
    ("Payment received: $X.XX" / "Remaining balance: $Y.YY") above the
    existing copy.
  - Full payments (and regular first-time invoice sends) keep the
    existing "Invoice {number} from {org}" subject — no regression.
  - Custom ``invoice_send`` / ``invoice_issued`` templates configured on
    the org bypass the partial-vs-full logic entirely (Requirement 11.5).

Validates: Requirements 11.1, 11.2, 11.4, 11.5
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from email import message_from_string
from email.header import decode_header, make_header
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
import app.modules.inventory.models  # noqa: F401


# ---------------------------------------------------------------------------
# Shared identifiers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_invoice_dict(
    *,
    status: str = "partially_paid",
    balance_due: Decimal = Decimal("200.00"),
    amount_paid: Decimal = Decimal("100.00"),
    invoice_number: str = "INV-0042",
    org_name: str = "Test Workshop Ltd",
    currency: str = "NZD",
    payment_gateway: str | None = None,
    payment_page_url: str | None = None,
) -> dict:
    """Build an invoice dict shaped like ``get_invoice`` returns.

    ``payment_gateway`` defaults to None to short-circuit the Stripe
    payment-link regeneration path inside ``email_invoice`` so the test
    does not have to mock ``_maybe_create_stripe_payment_intent`` and the
    extra DB round-trips that path triggers.
    """
    return {
        "id": INVOICE_ID,
        "org_id": ORG_ID,
        "invoice_number": invoice_number,
        "customer_id": CUSTOMER_ID,
        "customer": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane@example.com",
        },
        "vehicle_rego": None,
        "branch_id": None,
        "status": status,
        "issue_date": date(2024, 6, 15),
        "due_date": date(2024, 7, 15),
        "currency": currency,
        "subtotal": Decimal("300.00"),
        "discount_amount": Decimal("0.00"),
        "gst_amount": Decimal("0.00"),
        "total": Decimal("300.00"),
        "amount_paid": amount_paid,
        "balance_due": balance_due,
        "payment_gateway": payment_gateway,
        "payment_page_url": payment_page_url,
        "org_name": org_name,
        "org_email": "info@test.co.nz",
        "org_phone": "09-555-1234",
        "line_items": [],
        "created_at": datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
    }


def _make_email_provider() -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row."""
    provider = MagicMock()
    provider.provider_key = "smtp-test"
    provider.smtp_host = "smtp.example.com"
    provider.smtp_port = 587
    provider.smtp_encryption = "tls"
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {
        "from_email": "noreply@example.com",
        "from_name": "OraInvoice",
    }
    provider.priority = 1
    return provider


def _make_org_with_settings() -> MagicMock:
    """Mock an Organisation row with no signature configured."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    org.settings = {
        "email_signature_enabled": False,
        "email_signature": "",
    }
    return org


def _make_payment(amount: Decimal, *, is_refund: bool = False) -> MagicMock:
    """Mock a ``Payment`` ORM row."""
    payment = MagicMock()
    payment.id = uuid.uuid4()
    payment.invoice_id = INVOICE_ID
    payment.org_id = ORG_ID
    payment.amount = amount
    payment.is_refund = is_refund
    payment.created_at = datetime(2024, 6, 16, 10, 0, tzinfo=timezone.utc)
    return payment


def _make_invoice_orm(*, status: str) -> MagicMock:
    """Mock an Invoice ORM row used by the post-send auto-issue check.

    The test scenarios all use non-draft invoices (partially_paid, paid,
    overdue), so the ``email_invoice`` function reads this row but the
    ``if invoice_obj.status == 'draft'`` branch is never taken.
    """
    inv_obj = MagicMock()
    inv_obj.id = INVOICE_ID
    inv_obj.org_id = ORG_ID
    inv_obj.status = status
    inv_obj.invoice_number = "INV-0042"
    inv_obj.issue_date = date(2024, 6, 15)
    inv_obj.due_date = date(2024, 7, 15)
    inv_obj.invoice_data_json = {}
    return inv_obj


def _scalars_result(rows: list) -> MagicMock:
    """Build a result that returns ``rows`` from ``.scalars().all()``."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _scalar_one_or_none_result(value) -> MagicMock:
    """Build a result that returns ``value`` from ``scalar_one_or_none``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _build_db_execute_side_effect(
    *,
    providers: list,
    org_for_signature: MagicMock,
    latest_payment,
    invoice_obj: MagicMock,
) -> list:
    """Construct the ordered ``db.execute`` return values.

    Order follows ``email_invoice``'s code path when ``recipient_email``
    is provided and ``payment_gateway`` is not ``"stripe"`` (so the
    regen branch is skipped):

      1. ``EmailProvider`` listing (for failover loop).
      2. ``Organisation`` row (for email-signature settings).
      3. Latest non-refund ``Payment`` row (partial-receipt detection).
      4. ``Invoice`` row (auto-issue check after send).
    """
    return [
        _scalars_result(providers),
        _scalar_one_or_none_result(org_for_signature),
        _scalar_one_or_none_result(latest_payment),
        _scalar_one_or_none_result(invoice_obj),
    ]


class _FakeSMTP:
    """In-process replacement for ``smtplib.SMTP``.

    Captures the most recent ``sendmail`` arguments on a class attribute so
    individual tests can inspect the resulting MIME message without any
    network activity. The instance methods are no-ops aside from
    ``sendmail``.
    """

    last_from: str | None = None
    last_to: str | None = None
    last_message: str | None = None

    def __init__(self, host, port, timeout=None):  # noqa: D401
        self.host = host
        self.port = port

    def starttls(self):
        return None

    def login(self, username, password):
        return None

    def sendmail(self, from_email, to_email, message_str):
        type(self).last_from = from_email
        type(self).last_to = to_email
        type(self).last_message = message_str

    def quit(self):
        return None


def _extract_subject_and_html_body(raw_message: str) -> tuple[str, str]:
    """Pull the ``Subject`` header and decoded HTML body from a sent MIME."""
    msg = message_from_string(raw_message)
    raw_subject = msg["Subject"] or ""
    # The subject may be RFC 2047-encoded if it contains non-ASCII chars
    # (e.g. an em-dash). Decode it back to a plain Unicode string before
    # returning so test assertions can match readable text.
    subject = str(make_header(decode_header(raw_subject)))
    html_body = ""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            html_body = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )
            break
    return subject, html_body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmailInvoicePartialReceipt:
    """Subject and body changes for partial vs full payment receipts."""

    @pytest.mark.asyncio
    async def test_partial_receipt_subject_distinguishes_partial(self):
        """A partial payment yields the new "Partial payment received" subject.

        Validates: Requirement 11.1
        """
        inv_dict = _make_invoice_dict(
            status="partially_paid",
            balance_due=Decimal("200.00"),
            amount_paid=Decimal("100.00"),
        )
        provider = _make_email_provider()
        org_for_sig = _make_org_with_settings()
        latest_payment = _make_payment(Decimal("100.00"))
        invoice_obj = _make_invoice_orm(status="partially_paid")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                providers=[provider],
                org_for_signature=org_for_sig,
                latest_payment=latest_payment,
                invoice_obj=invoice_obj,
            )
        )

        _FakeSMTP.last_message = None

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake",
        ), patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.invoices.attachment_service.list_attachments",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.core.encryption.envelope_decrypt_str",
            return_value='{"username": "user", "password": "pass"}',
        ), patch("smtplib.SMTP", _FakeSMTP):
            from app.modules.invoices.service import email_invoice

            result = await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
                recipient_email="jane@example.com",
            )

        assert result["status"] == "sent"
        assert _FakeSMTP.last_message is not None
        subject, _ = _extract_subject_and_html_body(_FakeSMTP.last_message)
        assert subject.startswith("Partial payment received for invoice INV-0042")
        assert "100.00" in subject

    @pytest.mark.asyncio
    async def test_partial_receipt_body_includes_received_and_remaining(self):
        """Body shows the two-line "Payment received / Remaining balance" summary.

        Validates: Requirement 11.2
        """
        inv_dict = _make_invoice_dict(
            status="partially_paid",
            balance_due=Decimal("200.00"),
            amount_paid=Decimal("100.00"),
        )
        provider = _make_email_provider()
        org_for_sig = _make_org_with_settings()
        latest_payment = _make_payment(Decimal("100.00"))
        invoice_obj = _make_invoice_orm(status="partially_paid")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                providers=[provider],
                org_for_signature=org_for_sig,
                latest_payment=latest_payment,
                invoice_obj=invoice_obj,
            )
        )

        _FakeSMTP.last_message = None

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake",
        ), patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.invoices.attachment_service.list_attachments",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.core.encryption.envelope_decrypt_str",
            return_value='{"username": "user", "password": "pass"}',
        ), patch("smtplib.SMTP", _FakeSMTP):
            from app.modules.invoices.service import email_invoice

            await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
                recipient_email="jane@example.com",
            )

        assert _FakeSMTP.last_message is not None
        _, html_body = _extract_subject_and_html_body(_FakeSMTP.last_message)
        # The plain-text body is converted to HTML via newline -> <br>
        # substitution before being attached, so the summary lines appear
        # verbatim in the rendered HTML.
        assert "Payment received: $100.00" in html_body
        assert "Remaining balance: $200.00" in html_body

    @pytest.mark.asyncio
    async def test_full_payment_uses_existing_subject(self):
        """A final payment that settles the invoice keeps the regular subject.

        Regression check for Requirement 11.1 — the partial-receipt
        phrasing must NOT leak into emails for invoices that are now
        fully paid (``status == 'paid'``, ``balance_due == 0``).
        """
        inv_dict = _make_invoice_dict(
            status="paid",
            balance_due=Decimal("0.00"),
            amount_paid=Decimal("300.00"),
        )
        provider = _make_email_provider()
        org_for_sig = _make_org_with_settings()
        latest_payment = _make_payment(Decimal("100.00"))  # closing payment
        invoice_obj = _make_invoice_orm(status="paid")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                providers=[provider],
                org_for_signature=org_for_sig,
                latest_payment=latest_payment,
                invoice_obj=invoice_obj,
            )
        )

        _FakeSMTP.last_message = None

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake",
        ), patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.invoices.attachment_service.list_attachments",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.core.encryption.envelope_decrypt_str",
            return_value='{"username": "user", "password": "pass"}',
        ), patch("smtplib.SMTP", _FakeSMTP):
            from app.modules.invoices.service import email_invoice

            await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
                recipient_email="jane@example.com",
            )

        assert _FakeSMTP.last_message is not None
        subject, html_body = _extract_subject_and_html_body(
            _FakeSMTP.last_message
        )
        assert subject == "Invoice INV-0042 from Test Workshop Ltd"
        assert "Partial payment received" not in subject
        assert "Payment received:" not in html_body
        assert "Remaining balance:" not in html_body

    @pytest.mark.asyncio
    async def test_custom_template_overrides_partial_logic(self):
        """A configured custom template wins over the partial fallback.

        Validates: Requirement 11.5 — orgs that have customised their
        ``invoice_issued`` template must keep their wording even when the
        invoice is in a partial-paid state.
        """
        from app.modules.notifications.service import RenderedTemplate

        inv_dict = _make_invoice_dict(
            status="partially_paid",
            balance_due=Decimal("200.00"),
            amount_paid=Decimal("100.00"),
        )
        provider = _make_email_provider()
        org_for_sig = _make_org_with_settings()
        latest_payment = _make_payment(Decimal("100.00"))
        invoice_obj = _make_invoice_orm(status="partially_paid")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                providers=[provider],
                org_for_signature=org_for_sig,
                latest_payment=latest_payment,
                invoice_obj=invoice_obj,
            )
        )

        custom_subject = "Your custom invoice notice"
        custom_body = "Hi from a custom template — outstanding $200.00."
        rendered = RenderedTemplate(subject=custom_subject, body=custom_body)

        _FakeSMTP.last_message = None

        with patch(
            "app.modules.invoices.service.get_invoice",
            new_callable=AsyncMock,
            return_value=inv_dict,
        ), patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake",
        ), patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.modules.invoices.attachment_service.list_attachments",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=rendered,
        ), patch(
            "app.core.encryption.envelope_decrypt_str",
            return_value='{"username": "user", "password": "pass"}',
        ), patch("smtplib.SMTP", _FakeSMTP):
            from app.modules.invoices.service import email_invoice

            await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
                recipient_email="jane@example.com",
            )

        assert _FakeSMTP.last_message is not None
        subject, html_body = _extract_subject_and_html_body(
            _FakeSMTP.last_message
        )
        # Custom template wins — partial phrasing must not appear.
        assert subject == custom_subject
        assert "Partial payment received" not in subject
        assert "Hi from a custom template" in html_body
        assert "Payment received: $" not in html_body
        assert "Remaining balance: $" not in html_body
