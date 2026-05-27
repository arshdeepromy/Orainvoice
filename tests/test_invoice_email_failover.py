"""Failover integration tests for invoice email sites (Group A).

This file is the home for end-to-end failover tests covering all the
invoice-related Group A migrations in Phase 3:

- **A1** ``email_invoice`` — task 3.1 (this commit)
- **A2** ``send_payment_reminder`` — task 3.2 (lands in a later commit)
- **A14** ``send_invoice_payment_link_email`` — task 3.14 (lands in a
  later commit)

Each migration replaces a hand-rolled ``smtplib`` provider loop with a
single :func:`app.integrations.email_sender.send_email` call. The tests
in this file pin the failover contract end-to-end: with two active
``EmailProvider`` rows where the first returns a Brevo REST 401 (which
the unified sender classifies as ``SOFT_AUTH``) and the second returns
a SendGrid REST 202, the call site must succeed and the audit-log entry
must record the **winning** provider's ``provider_key``.

Patches (kept identical across every test in this file so future A2 /
A14 tests reuse them):

- ``app.integrations.email_sender._load_active_providers`` — returns the
  two mock provider rows in priority order. Bypasses the real DB query
  that the unified sender does internally.
- ``app.integrations.email_sender._check_bounce_blocklist`` — returns
  ``(False, None)`` (Phase 1 stub anyway, but patched explicitly for
  forward-compat with Phase 8c).
- ``app.integrations.email_sender.envelope_decrypt_str`` — returns the
  raw JSON credentials so the dispatchers find ``api_key``.
- ``app.integrations.email_sender.httpx.AsyncClient`` — a fake client
  that returns 401 for the Brevo URL and 202 (with ``X-Message-Id``) for
  the SendGrid URL. This is the same fake used in
  ``tests/test_send_email_task_integration.py`` so the two test files
  share an end-to-end shape.

Validates: Requirements 6.1, 6.3, 6.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401


# ---------------------------------------------------------------------------
# Shared identifiers / fixtures
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_invoice_dict() -> dict:
    """Build an invoice dict shaped like ``get_invoice`` returns.

    Uses ``payment_gateway=None`` to short-circuit the Stripe payment-link
    regeneration path inside ``email_invoice`` so the test does not have
    to mock ``_maybe_create_stripe_payment_intent``. Status is set to
    ``issued`` (not ``draft``) so the auto-issue branch in
    ``email_invoice`` is also bypassed.
    """
    return {
        "id": INVOICE_ID,
        "org_id": ORG_ID,
        "invoice_number": "INV-9001",
        "customer_id": CUSTOMER_ID,
        "customer": {
            "first_name": "Casey",
            "last_name": "Tester",
            "email": "casey@example.com",
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


def _make_org_with_settings() -> MagicMock:
    """Mock an Organisation row with no email signature configured."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    org.settings = {
        "email_signature_enabled": False,
        "email_signature": "",
    }
    return org


def _make_invoice_orm() -> MagicMock:
    """Mock an Invoice ORM row used by the post-send auto-issue check.

    Always created with ``status='issued'`` so the
    ``if invoice_obj.status == 'draft'`` branch in ``email_invoice``
    is skipped — those scenarios are tested elsewhere.
    """
    inv_obj = MagicMock()
    inv_obj.id = INVOICE_ID
    inv_obj.org_id = ORG_ID
    inv_obj.status = "issued"
    inv_obj.invoice_number = "INV-9001"
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
    org_for_signature: MagicMock,
    latest_payment,
    invoice_obj: MagicMock,
) -> list:
    """Return the ordered ``db.execute`` results for ``email_invoice``.

    Order follows ``email_invoice``'s code path **after** the Phase 3
    migration when ``recipient_email`` is supplied (so the
    customer-lookup query is skipped) and ``payment_gateway`` is not
    ``"stripe"`` (so the regen branch is skipped):

    1. ``Organisation`` row for email-signature settings.
    2. Latest non-refund ``Payment`` row for partial-receipt detection.
    3. ``Invoice`` row for the auto-issue check after send.

    The previous ``select(EmailProvider)`` query is now done **inside**
    ``send_email`` — and ``_load_active_providers`` is patched out at
    that level — so the caller's ``db.execute`` no longer sees that
    statement.
    """
    return [
        _scalar_one_or_none_result(org_for_signature),
        _scalar_one_or_none_result(latest_payment),
        _scalar_one_or_none_result(invoice_obj),
    ]


# ---------------------------------------------------------------------------
# Fake httpx client (shared with test_send_email_task_integration.py)
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response``.

    Implements just the surface area the dispatchers read:
    ``status_code``, ``text``, ``headers`` (dict-like with ``.get``), and
    ``json()``.
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
    (success — captured into ``EmailAttempt.message_id`` and surfaced as
    ``SendResult.message_id``).
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []

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
                headers={"X-Message-Id": "msg-invoice-9001"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


# ---------------------------------------------------------------------------
# A1 — email_invoice
# ---------------------------------------------------------------------------


class TestA1EmailInvoiceFailover:
    """End-to-end failover for ``email_invoice`` (task 3.1).

    With Brevo configured at priority 1 and SendGrid at priority 2,
    ``email_invoice`` must walk past the Brevo 401 (``SOFT_AUTH``),
    succeed on SendGrid (202), and record SendGrid as the winning
    provider in the audit-log payload.

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → audit log records ``sendgrid``.

        Pins the contract that the migrated ``email_invoice``:

        1. Calls ``send_email`` exactly once (no manual ``smtplib`` loop
           leaks back in).
        2. Surfaces both REST URLs as POSTed in priority order — Brevo
           first, then SendGrid. Failure on the first must not abort the
           chain.
        3. Returns ``status='sent'`` and the recipient on the API
           contract (``recipient_email`` echoes back).
        4. Writes an audit-log entry whose ``after_value['provider']``
           is ``"sendgrid"`` (the winning provider, NOT the first one
           tried).

        Validates: Requirements 6.1, 6.3, 6.4
        """
        inv_dict = _make_invoice_dict()
        org_for_sig = _make_org_with_settings()
        invoice_obj = _make_invoice_orm()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                org_for_signature=org_for_sig,
                latest_payment=None,  # first-time send, no prior payment
                invoice_obj=invoice_obj,
            )
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        audit_log_stub = AsyncMock()

        # Reset the fake client's recorded URLs so this test is order-
        # independent within the suite.
        _FakeClient.posted_urls = []

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
            new=audit_log_stub,
        ), patch(
            "app.modules.invoices.attachment_service.list_attachments",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
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
            from app.modules.invoices.service import email_invoice

            result = await email_invoice(
                db,
                org_id=ORG_ID,
                invoice_id=INVOICE_ID,
                recipient_email="casey@example.com",
            )

        # 1. The function returns the Phase 3 contract: sent + recipient.
        assert result["status"] == "sent"
        assert result["recipient_email"] == "casey@example.com"
        assert result["invoice_number"] == "INV-9001"
        assert result["pdf_size_bytes"] == len(b"%PDF-fake-bytes")

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

        # 4. Audit log records the winning provider.
        audit_log_stub.assert_awaited_once()
        _audit_args, audit_kwargs = audit_log_stub.await_args
        assert audit_kwargs["action"] == "invoice.email_sent"
        assert audit_kwargs["entity_id"] == INVOICE_ID
        assert audit_kwargs["after_value"]["provider"] == "sendgrid"
        assert audit_kwargs["after_value"]["recipient"] == "casey@example.com"

    @pytest.mark.asyncio
    async def test_all_providers_fail_logs_and_creates_in_app_notification(
        self,
    ) -> None:
        """When every provider returns ``SOFT_AUTH`` ``email_invoice``
        raises ``ValueError`` and the failure path runs both
        ``log_email_sent(status='failed')`` and
        ``create_in_app_notification(category='email_failure')`` —
        preserving the contract the original raw-smtplib version had.

        Validates: Requirements 6.3, 6.4
        """
        inv_dict = _make_invoice_dict()
        org_for_sig = _make_org_with_settings()
        invoice_obj = _make_invoice_orm()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        # On the all-fail path the auto-issue / audit-log queries are
        # never reached because the function raises ValueError after the
        # in-app notification fires. Only the org-signature read happens
        # before send_email — the latest_payment and invoice_obj results
        # are appended for safety in case the failure path code shifts.
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                org_for_signature=org_for_sig,
                latest_payment=None,
                invoice_obj=invoice_obj,
            )
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        log_email_stub = AsyncMock()
        in_app_stub = AsyncMock()

        # Both providers fail with 401 (SOFT_AUTH). The fake client
        # routes by URL, so we need a variant that returns 401 for both.
        class _AllFail401Client(_FakeClient):
            async def post(self, url, json=None, headers=None):  # noqa: A002
                type(self).posted_urls.append(url)
                return _FakeResponse(
                    401,
                    text='{"code":"unauthorized","message":"invalid api key"}',
                    headers={"content-type": "application/json"},
                    json_body={
                        "code": "unauthorized",
                        "message": "invalid api key",
                    },
                )

        _AllFail401Client.posted_urls = []

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
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.modules.in_app_notifications.service.create_in_app_notification",
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
            from app.modules.invoices.service import email_invoice

            with pytest.raises(ValueError, match="All email providers failed"):
                await email_invoice(
                    db,
                    org_id=ORG_ID,
                    invoice_id=INVOICE_ID,
                    recipient_email="casey@example.com",
                )

        # Both providers were attempted (chain not short-circuited by a
        # HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

        # log_email_sent was called once with status='failed' (preserved
        # from the original raw-smtplib failure handler).
        log_email_stub.assert_awaited_once()
        _log_args, log_kwargs = log_email_stub.await_args
        assert log_kwargs["status"] == "failed"
        assert log_kwargs["template_type"] == "invoice_send"
        assert log_kwargs["recipient"] == "casey@example.com"

        # create_in_app_notification was called once with the
        # 'email_failure' category (preserved from the original
        # raw-smtplib failure handler).
        in_app_stub.assert_awaited_once()
        _ian_args, ian_kwargs = in_app_stub.await_args
        assert ian_kwargs["category"] == "email_failure"
        assert ian_kwargs["entity_type"] == "invoice"
        assert ian_kwargs["entity_id"] == INVOICE_ID
        assert "casey@example.com" in ian_kwargs["title"]
