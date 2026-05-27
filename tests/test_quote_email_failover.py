"""Failover integration tests for quote email send (Group A site A3).

This file pins the Phase 3 migration of
``app.modules.quotes.service.send_quote`` (task 3.3 / Group A site A3).
The migration replaced a hand-rolled ``smtplib`` provider loop with a
single :func:`app.integrations.email_sender.send_email` call. The tests
in this file exercise the same Brevo-401 → SendGrid-202 chain used by
``tests/test_invoice_email_failover.py`` so the failover contract for
quote sends matches the contract for invoice sends.

The fixtures and the ``_FakeClient`` / ``_FakeResponse`` helpers are
re-implemented locally rather than imported from
``test_invoice_email_failover.py`` (per task 3.3's instruction to keep
the two test files independent so future refactors of one do not break
the other).

Patches (held constant across both tests):

- ``app.integrations.email_sender._load_active_providers`` — returns
  the two mock provider rows in priority order, bypassing the real DB
  query the unified sender does internally.
- ``app.integrations.email_sender._check_bounce_blocklist`` — returns
  ``(False, None)`` so the recipient pre-check passes (Phase 1 stub
  anyway, patched explicitly for forward-compat with Phase 8c).
- ``app.integrations.email_sender.envelope_decrypt_str`` — returns
  canned JSON credentials so the dispatchers find ``api_key``.
- ``app.integrations.email_sender.httpx.AsyncClient`` — a fake client
  that returns 401 for the Brevo URL and 202 (with ``X-Message-Id``)
  for the SendGrid URL.

Validates: Requirements 6.1, 6.3, 6.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
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
USER_ID = uuid.uuid4()
QUOTE_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_quote_dict() -> dict:
    """Build a quote dict shaped like ``get_quote`` returns.

    Status is ``"draft"`` so the draft-transition branch in
    ``send_quote`` runs — the test exercises the same code path as a
    real first-time quote send, which is the path most likely to
    regress on a future refactor.
    """
    return {
        "id": QUOTE_ID,
        "org_id": ORG_ID,
        "customer_id": CUSTOMER_ID,
        "quote_number": "QT-9001",
        "vehicle_rego": "ABC123",
        "vehicle_make": "Toyota",
        "vehicle_model": "Corolla",
        "vehicle_year": 2020,
        "status": "draft",
        "valid_until": date(2024, 7, 15),
        "subtotal": Decimal("100.00"),
        "gst_amount": Decimal("15.00"),
        "total": Decimal("115.00"),
        "notes": "Test quote notes",
        "acceptance_token": None,
        "line_items": [
            {
                "id": uuid.uuid4(),
                "item_type": "service",
                "description": "Oil Change",
                "quantity": Decimal("1"),
                "unit_price": Decimal("100.00"),
                "hours": None,
                "hourly_rate": None,
                "is_gst_exempt": False,
                "warranty_note": None,
                "line_total": Decimal("100.00"),
                "sort_order": 0,
            },
        ],
        "created_by": USER_ID,
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


def _make_org() -> MagicMock:
    """Mock an Organisation row with no email signature configured."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    org.base_currency = "NZD"
    org.settings = {
        "email_signature_enabled": False,
        "email_signature": "",
    }
    return org


def _make_customer() -> MagicMock:
    """Mock a ``Customer`` ORM row used by the template-variable lookup."""
    cust = MagicMock()
    cust.id = CUSTOMER_ID
    cust.org_id = ORG_ID
    cust.first_name = "Casey"
    cust.last_name = "Tester"
    cust.email = "casey@example.com"
    return cust


def _make_quote_orm() -> MagicMock:
    """Mock a Quote ORM row used by the draft-transition branch.

    Set ``status='draft'`` so ``send_quote`` flips it to ``'sent'`` and
    generates an ``acceptance_token``. ``acceptance_token`` starts as
    ``None`` so the secrets-token generation path runs (mirrors the
    real first-send code path).
    """
    quote_obj = MagicMock()
    quote_obj.id = QUOTE_ID
    quote_obj.org_id = ORG_ID
    quote_obj.status = "draft"
    quote_obj.acceptance_token = None
    return quote_obj


def _scalar_one_or_none_result(value) -> MagicMock:
    """Build a result that returns ``value`` from ``scalar_one_or_none``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _build_db_execute_side_effect(
    *,
    quote_obj: MagicMock,
    org: MagicMock,
    customer: MagicMock,
) -> list:
    """Return the ordered ``db.execute`` results for ``send_quote``.

    Order follows ``send_quote``'s code path **after** the Phase 3
    migration when ``recipient_email`` is supplied (so the
    customer-lookup at the top of the function is skipped) and the
    quote starts in ``status='draft'`` (so the draft-transition branch
    runs):

    1. ``Quote`` row (draft-transition branch flips status to sent).
    2. ``Organisation`` row (used for ``org_settings`` + ``org_name``).
    3. ``Customer`` row (used for template variables).

    The previous ``select(EmailProvider)`` query is now done **inside**
    ``send_email`` — and ``_load_active_providers`` is patched out at
    that level — so the caller's ``db.execute`` no longer sees that
    statement.
    """
    return [
        _scalar_one_or_none_result(quote_obj),
        _scalar_one_or_none_result(org),
        _scalar_one_or_none_result(customer),
    ]


# ---------------------------------------------------------------------------
# Fake httpx client
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
                headers={"X-Message-Id": "msg-quote-9001"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


# ---------------------------------------------------------------------------
# A3 — send_quote
# ---------------------------------------------------------------------------


class TestA3SendQuoteFailover:
    """End-to-end failover for ``send_quote`` (task 3.3, A3).

    With Brevo configured at priority 1 and SendGrid at priority 2,
    ``send_quote`` must walk past the Brevo 401 (``SOFT_AUTH``),
    succeed on SendGrid (202), and record SendGrid as the winning
    provider in the audit-log payload. PDF attachment behaviour
    matches A1 (``email_invoice``).

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → audit log records ``sendgrid``.

        Pins the contract that the migrated ``send_quote``:

        1. Calls ``send_email`` exactly once (no manual ``smtplib``
           loop leaks back in).
        2. Surfaces both REST URLs as POSTed in priority order — Brevo
           first, then SendGrid. Failure on the first must not abort
           the chain.
        3. Returns ``status='sent'`` and the recipient on the API
           contract (``recipient_email`` echoes back).
        4. Writes an audit-log entry whose
           ``after_value['provider']`` is ``"sendgrid"`` (the winning
           provider, NOT the first one tried).

        Validates: Requirements 6.1, 6.3, 6.4
        """
        quote_dict = _make_quote_dict()
        org = _make_org()
        customer = _make_customer()
        quote_obj = _make_quote_orm()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                quote_obj=quote_obj,
                org=org,
                customer=customer,
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
            "app.modules.quotes.service.get_quote",
            new_callable=AsyncMock,
            return_value=quote_dict,
        ), patch(
            "app.modules.quotes.service.generate_quote_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake-bytes",
        ), patch(
            "app.modules.quotes.service.write_audit_log",
            new=audit_log_stub,
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
            from app.modules.quotes.service import send_quote

            result = await send_quote(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                quote_id=QUOTE_ID,
                recipient_email="casey@example.com",
            )

        # 1. The function returns the Phase 3 contract: sent + recipient.
        assert result["status"] == "sent"
        assert result["recipient_email"] == "casey@example.com"
        assert result["quote_number"] == "QT-9001"
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
        assert audit_kwargs["action"] == "quote.sent"
        assert audit_kwargs["entity_type"] == "quote"
        assert audit_kwargs["entity_id"] == QUOTE_ID
        assert audit_kwargs["after_value"]["provider"] == "sendgrid"
        assert audit_kwargs["after_value"]["recipient"] == "casey@example.com"
        assert audit_kwargs["after_value"]["quote_number"] == "QT-9001"
        assert audit_kwargs["after_value"]["email_sent"] is True

    @pytest.mark.asyncio
    async def test_all_providers_fail_logs_and_creates_in_app_notification(
        self,
    ) -> None:
        """When every provider returns ``SOFT_AUTH`` ``send_quote``
        raises ``ValueError`` and the failure path runs both
        ``log_email_sent(status='failed')`` and
        ``create_in_app_notification(category='email_failure')`` —
        preserving the contract the original raw-smtplib version had.

        Validates: Requirements 6.3, 6.4
        """
        quote_dict = _make_quote_dict()
        org = _make_org()
        customer = _make_customer()
        quote_obj = _make_quote_orm()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(
                quote_obj=quote_obj,
                org=org,
                customer=customer,
            )
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        log_email_stub = AsyncMock()
        in_app_stub = AsyncMock()

        # Both providers fail with 401 (SOFT_AUTH).
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
            "app.modules.quotes.service.get_quote",
            new_callable=AsyncMock,
            return_value=quote_dict,
        ), patch(
            "app.modules.quotes.service.generate_quote_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake-bytes",
        ), patch(
            "app.modules.quotes.service.write_audit_log",
            new_callable=AsyncMock,
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
            from app.modules.quotes.service import send_quote

            with pytest.raises(ValueError, match="All email providers failed"):
                await send_quote(
                    db,
                    org_id=ORG_ID,
                    user_id=USER_ID,
                    quote_id=QUOTE_ID,
                    recipient_email="casey@example.com",
                )

        # Both providers were attempted (chain not short-circuited by
        # a HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

        # log_email_sent was called once with status='failed' (preserved
        # from the original raw-smtplib failure handler).
        log_email_stub.assert_awaited_once()
        _log_args, log_kwargs = log_email_stub.await_args
        assert log_kwargs["status"] == "failed"
        assert log_kwargs["template_type"] == "quote_send"
        assert log_kwargs["recipient"] == "casey@example.com"

        # create_in_app_notification was called once with the
        # 'email_failure' category (preserved from the original
        # raw-smtplib failure handler).
        in_app_stub.assert_awaited_once()
        _ian_args, ian_kwargs = in_app_stub.await_args
        assert ian_kwargs["category"] == "email_failure"
        assert ian_kwargs["entity_type"] == "quote"
        assert ian_kwargs["entity_id"] == QUOTE_ID
        assert "casey@example.com" in ian_kwargs["title"]
        assert "QT-9001" in ian_kwargs["title"]
