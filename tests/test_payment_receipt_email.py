"""Failover integration tests for ``_send_receipt_email`` (A4).

This file pins the Phase 3 task 3.4 contract: ``_send_receipt_email``
(``app/modules/payments/service.py``) was migrated from a hand-rolled
``smtplib`` provider loop to a single
:func:`app.integrations.email_sender.send_email` call. The unified
sender owns failover, error classification, and per-attempt + total
time budgets — so the migration must:

1. Surface both REST URLs (POSTs) when two providers are configured
   and the first one fails with a soft error.
2. Return cleanly on success (no exception, no in-app notification
   fired).
3. Preserve the original best-effort failure handling: when every
   provider fails, log a warning and call
   :func:`app.modules.in_app_notifications.service.create_in_app_notification`
   with ``category='email_failure'``. The function does NOT raise.
4. Pass the payment's ``org_id`` (= ``invoice.org_id``) on the
   :class:`~app.integrations.email_sender.EmailMessage` so the
   bounce-blocklist pre-check can scope correctly.
5. Build a single PDF :class:`~app.integrations.email_sender.EmailAttachment`
   from the bytes returned by ``generate_invoice_pdf``.

Notes on the original site:

- The legacy implementation called ``log_email_sent`` on neither
  success nor failure (best-effort send), so this file does NOT assert
  on it either.
- The legacy implementation did not pass a per-org ``from_name``
  override (the provider's ``from_name`` was always used, falling back
  to ``org_name``). The migrated version preserves this — no
  ``org_sender_name`` argument is passed.
- ``EmailMessage.org_id`` MUST be the payment's ``org_id``, which the
  function reads from ``invoice.org_id`` (per the per-site variation
  table in design.md).

Patches (kept self-contained — no imports from other test files):

- ``app.modules.invoices.service.generate_invoice_pdf`` returns a
  fixed bytes blob so the PDF attachment is deterministic.
- ``app.modules.notifications.service.resolve_template`` returns
  ``None`` so the function falls through to the hardcoded
  ``payment_received`` body.
- ``app.modules.in_app_notifications.service.create_in_app_notification``
  is stubbed so the failure path can be asserted on without touching
  the DB.
- ``app.integrations.email_sender._load_active_providers`` returns the
  mocked provider rows in priority order; ``_check_bounce_blocklist``
  returns ``(False, None)``; ``envelope_decrypt_str`` returns canned
  credentials; ``httpx.AsyncClient`` is replaced with an in-process
  fake whose responses depend on the URL hit.

Validates: Requirements 6.1, 6.3, 6.4
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import
# time. ``app.modules.admin.models`` brings in ``EmailProvider`` /
# ``Organisation``; importing ``app.modules.payments.service`` early in
# the test would otherwise miss these.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401


# ---------------------------------------------------------------------------
# Shared identifiers / builders
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_invoice() -> MagicMock:
    """Mock an :class:`~app.modules.invoices.models.Invoice` ORM row.

    The function only reads ``id``, ``org_id``, ``customer_id``,
    ``invoice_number``, ``currency``, ``balance_due``, ``due_date``, and
    ``payment_page_url`` — everything else can stay default. ``org_id``
    is the field the migration plumbs onto ``EmailMessage.org_id``.
    """
    invoice = MagicMock()
    invoice.id = INVOICE_ID
    invoice.org_id = ORG_ID
    invoice.customer_id = CUSTOMER_ID
    invoice.invoice_number = "INV-2042"
    invoice.currency = "NZD"
    invoice.balance_due = Decimal("0.00")
    invoice.due_date = date(2024, 7, 15)
    invoice.payment_page_url = None
    return invoice


def _make_org() -> MagicMock:
    """Mock the organisation row used for the from_name fallback."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    org.settings = {
        "email": "info@test.co.nz",
        "phone": "09-555-1234",
    }
    return org


def _make_customer() -> MagicMock:
    """Mock the customer row used for template variable context."""
    cust = MagicMock()
    cust.id = CUSTOMER_ID
    cust.org_id = ORG_ID
    cust.email = "casey@example.com"
    cust.first_name = "Casey"
    cust.last_name = "Tester"
    return cust


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row.

    The two REST dispatchers
    (``_dispatch_brevo_rest`` / ``_dispatch_sendgrid_rest``) only read
    ``credentials_set``, ``credentials_encrypted``, ``provider_key``,
    and ``config['from_email']``. The blob bytes are opaque because we
    patch ``envelope_decrypt_str`` to return canned credentials.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.priority = priority
    provider.is_active = True
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {
        "from_email": "noreply@example.com",
        "from_name": "OraInvoice",
    }
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


def _scalar_one_or_none_result(value) -> MagicMock:
    """Build a result that returns ``value`` from ``scalar_one_or_none``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


# ---------------------------------------------------------------------------
# Fake httpx client (self-contained — copy of the dispatcher's expected
# surface, kept private to this file so a test layout shuffle elsewhere
# can't break us)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response``.

    Implements just the surface area the dispatchers read:
    ``status_code``, ``text``, ``headers`` (dict-like with ``.get``),
    and ``json()``.
    """

    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        headers: dict | None = None,
        json_body: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._json_body = json_body

    def json(self) -> dict:
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FakeClient:
    """In-process replacement for ``httpx.AsyncClient`` (failover scenario).

    Routes by URL: Brevo gets a 401 (drives ``SOFT_AUTH``, loop
    continues), SendGrid gets a 202 with ``X-Message-Id`` populated
    (success — captured into ``EmailAttempt.message_id`` and surfaced
    as ``SendResult.message_id``).

    The class-level ``posted_urls`` list is reset by each test so the
    ordering assertion is order-independent.
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        # ``timeout=...`` and any other kwargs are accepted but ignored.
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        if url == self.BREVO_URL:
            return _FakeResponse(
                401,
                text='{"code":"unauthorized","message":"invalid api key"}',
                headers={"content-type": "application/json"},
                json_body={"code": "unauthorized", "message": "invalid api key"},
            )
        if url == self.SENDGRID_URL:
            return _FakeResponse(
                202,
                text="",
                headers={"X-Message-Id": "msg-receipt-2042"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


class _AllFail401Client(_FakeClient):
    """Variant of ``_FakeClient`` where every URL returns 401.

    Drives a chain where every provider yields ``SOFT_AUTH`` and the
    failover loop exhausts itself. Used by the all-fail test below.
    """

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        return _FakeResponse(
            401,
            text='{"code":"unauthorized","message":"invalid api key"}',
            headers={"content-type": "application/json"},
            json_body={
                "code": "unauthorized",
                "message": "invalid api key",
            },
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA4SendReceiptEmailFailover:
    """End-to-end failover for ``_send_receipt_email`` (task 3.4).

    With Brevo at priority 1 and SendGrid at priority 2,
    ``_send_receipt_email`` must walk past the Brevo 401
    (``SOFT_AUTH``), succeed on SendGrid (202), and return cleanly
    without firing the in-app failure notification.

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → both URLs hit, no failure notif.

        Pins the contract that the migrated ``_send_receipt_email``:

        1. Calls ``send_email`` exactly once (no manual ``smtplib`` loop
           leaks back in).
        2. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). Failure on the first must NOT abort the
           chain.
        3. Builds an ``EmailMessage`` with ``org_id`` set to
           ``invoice.org_id`` and includes the PDF as a single
           ``application/pdf`` attachment in the dispatched payload.
        4. Returns ``None`` cleanly on success and does NOT call
           ``create_in_app_notification``.

        Validates: Requirements 6.1, 6.3, 6.4
        """
        invoice = _make_invoice()
        org = _make_org()
        customer = _make_customer()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        # The function does two SELECTs before send_email: organisation
        # then customer. The active-provider SELECT now lives inside
        # send_email, which is patched at _load_active_providers below.
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(org),
                _scalar_one_or_none_result(customer),
            ]
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        in_app_stub = AsyncMock()

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FakeClient.posted_urls = []
        _FakeClient.posted_payloads = []

        with patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake-receipt-bytes",
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.modules.payments.service.create_in_app_notification",
            new=in_app_stub,
        ), patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _FakeClient,
        ):
            from app.modules.payments.service import _send_receipt_email

            result = await _send_receipt_email(
                db,
                to_email="casey@example.com",
                invoice=invoice,
                pay_amount=Decimal("100.00"),
            )

        # 1. Best-effort signature: returns None on success.
        assert result is None

        # 2. Both REST endpoints were hit in priority order — Brevo
        #    first (401, SOFT_AUTH), then SendGrid (202, success).
        assert _FakeClient.posted_urls == [
            _FakeClient.BREVO_URL,
            _FakeClient.SENDGRID_URL,
        ]

        # 3. Provider chain was loaded once and the bounce-blocklist
        #    pre-check fired exactly once.
        load_providers_stub.assert_awaited_once()
        blocklist_stub.assert_awaited_once()

        # 4. The success path does NOT fire the in-app failure
        #    notification.
        in_app_stub.assert_not_awaited()

        # 5. Both dispatched payloads carry the PDF attachment in their
        #    Brevo / SendGrid REST shapes. Brevo uses an ``attachment``
        #    array with ``name``; SendGrid uses ``attachments`` with
        #    ``filename``. The PDF is the only attachment.
        brevo_payload = _FakeClient.posted_payloads[0]
        sendgrid_payload = _FakeClient.posted_payloads[1]

        assert "attachment" in brevo_payload
        assert len(brevo_payload["attachment"]) == 1
        assert brevo_payload["attachment"][0]["name"] == "INV-2042.pdf"

        assert "attachments" in sendgrid_payload
        assert len(sendgrid_payload["attachments"]) == 1
        assert sendgrid_payload["attachments"][0]["filename"] == "INV-2042.pdf"

        # 6. The recipient on each payload matches the caller's
        #    ``to_email`` argument — sanity check that the migration
        #    didn't drop the To address on the floor.
        assert brevo_payload["to"][0]["email"] == "casey@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "casey@example.com"
        )

    @pytest.mark.asyncio
    async def test_all_providers_fail_creates_in_app_notification(self) -> None:
        """When every provider returns ``SOFT_AUTH`` ``_send_receipt_email``
        returns cleanly (does NOT raise) and fires
        ``create_in_app_notification(category='email_failure')`` —
        preserving the best-effort contract the original raw-smtplib
        version had.

        Validates: Requirements 6.3, 6.4
        """
        invoice = _make_invoice()
        org = _make_org()
        customer = _make_customer()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(org),
                _scalar_one_or_none_result(customer),
            ]
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        in_app_stub = AsyncMock()

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake-receipt-bytes",
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.modules.payments.service.create_in_app_notification",
            new=in_app_stub,
        ), patch(
            "app.integrations.email_sender._load_active_providers",
            new=load_providers_stub,
        ), patch(
            "app.integrations.email_sender._check_bounce_blocklist",
            new=blocklist_stub,
        ), patch(
            "app.integrations.email_sender.envelope_decrypt_str",
            return_value='{"api_key": "test-api-key"}',
        ), patch(
            "app.integrations.email_sender.httpx.AsyncClient",
            _AllFail401Client,
        ):
            from app.modules.payments.service import _send_receipt_email

            # The function does NOT raise — best-effort send.
            result = await _send_receipt_email(
                db,
                to_email="casey@example.com",
                invoice=invoice,
                pay_amount=Decimal("100.00"),
            )

        assert result is None

        # Both providers were attempted (chain not short-circuited by a
        # HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

        # The in-app failure notification fired once with the
        # ``email_failure`` category — preserved from the original
        # raw-smtplib failure handler.
        in_app_stub.assert_awaited_once()
        _ian_args, ian_kwargs = in_app_stub.await_args
        assert ian_kwargs["category"] == "email_failure"
        assert ian_kwargs["entity_type"] == "invoice"
        assert ian_kwargs["entity_id"] == INVOICE_ID
        assert "casey@example.com" in ian_kwargs["title"]
        assert "INV-2042" in ian_kwargs["title"]
        assert ian_kwargs["audience_roles"] == ["org_admin"]


class TestA4SendReceiptEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A4 in
    ``design.md``: ``EmailMessage.org_id`` MUST be ``invoice.org_id``;
    the PDF is built into a single ``EmailAttachment`` with the invoice
    number filename.

    Validates: Requirement 6.3 (org_id plumbing) and 6.4 (no manual
    smtplib loop)
    """

    @pytest.mark.asyncio
    async def test_email_message_carries_invoice_org_id(self) -> None:
        """``send_email`` is called with ``message.org_id == invoice.org_id``.

        Validates: Requirements 6.1, 6.3
        """
        invoice = _make_invoice()
        org = _make_org()
        customer = _make_customer()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(org),
                _scalar_one_or_none_result(customer),
            ]
        )

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-bytes",
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            # Patch where _send_receipt_email imports it (function-local
            # import inside the migrated function body).
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.payments.service import _send_receipt_email

            await _send_receipt_email(
                db,
                to_email="casey@example.com",
                invoice=invoice,
                pay_amount=Decimal("100.00"),
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        # Positional: db, message
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design Per-Site Migration Patterns > Group A row A4:
        # org_id = payment.org_id (which equals invoice.org_id).
        assert message.org_id == ORG_ID
        assert message.to_email == "casey@example.com"

        # Single PDF attachment built from generate_invoice_pdf bytes.
        assert len(message.attachments) == 1
        attachment = message.attachments[0]
        assert attachment.filename == "INV-2042.pdf"
        assert attachment.mime_type == "application/pdf"
        assert attachment.content == b"%PDF-bytes"

    @pytest.mark.asyncio
    async def test_pdf_generation_failure_omits_attachment(self) -> None:
        """A PDF render error must not block the email — no attachment.

        The function wraps ``generate_invoice_pdf`` in try/except and
        logs a warning on failure. The migrated path must continue to
        send the email body even when ``pdf_bytes`` ends up ``None`` —
        this preserves the legacy "best-effort" contract.

        Validates: Requirement 6.1 (one send_email call, no smtplib
        loop)
        """
        invoice = _make_invoice()
        org = _make_org()
        customer = _make_customer()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(org),
                _scalar_one_or_none_result(customer),
            ]
        )

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-id-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.modules.invoices.service.generate_invoice_pdf",
            new_callable=AsyncMock,
            side_effect=RuntimeError("PDF render failed"),
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.payments.service import _send_receipt_email

            # Must NOT raise — PDF failure is best-effort.
            result = await _send_receipt_email(
                db,
                to_email="casey@example.com",
                invoice=invoice,
                pay_amount=Decimal("100.00"),
            )

        assert result is None

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None

        # No attachment when PDF generation fails — body still sends.
        assert message.attachments == []
