"""Failover integration tests for ``notify_customer`` (A12).

This file pins the Phase 3 task 3.12 contract: ``notify_customer``
(``app/modules/customers/service.py``) was migrated from a hand-rolled
``smtplib`` provider loop to a single
:func:`app.integrations.email_sender.send_email` call. The unified
sender owns failover, error classification, and per-attempt + total
time budgets — so the migration must:

1. Walk the active provider chain in priority order, skipping
   ``SOFT_AUTH`` failures and succeeding on the next provider.
2. Pass ``org_sender_name=org_name`` so the From header reads as the
   organisation, not the platform default (Requirement 6.5).
3. Build the :class:`~app.integrations.email_sender.EmailMessage` with
   ``org_id=customer.org_id`` so the bounce-blocklist pre-check scopes
   correctly.
4. Preserve ``log_email_sent`` on both success and failure (Requirement
   6.3).
5. Preserve ``create_in_app_notification(category='email_failure', ...)``
   on total failure (Requirement 6.4).
6. On total failure, surface the error by raising ``ValueError`` so the
   caller (the customer-notify router) reports HTTP 500 to the client.

Patches (kept self-contained — no imports from other test files):

- ``app.integrations.email_sender._load_active_providers`` returns the
  mocked provider rows in priority order.
- ``app.integrations.email_sender._check_bounce_blocklist`` returns
  ``(False, None)`` so the message reaches the dispatch loop.
- ``app.integrations.email_sender.envelope_decrypt_str`` returns canned
  credentials.
- ``httpx.AsyncClient`` is replaced with an in-process fake whose
  responses depend on the URL hit.
- ``app.modules.customers.service.write_audit_log`` is stubbed so the
  audit log call doesn't try to touch a real DB.
- ``app.modules.notifications.service.log_email_sent`` is stubbed so we
  can assert it is called on both success and failure.
- ``app.modules.in_app_notifications.service.create_in_app_notification``
  is stubbed so we can assert it fires only on total failure.

Validates: Requirements 6.1, 6.3, 6.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.service import notify_customer


# ---------------------------------------------------------------------------
# Shared identifiers / builders
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_customer(
    *,
    org_id: uuid.UUID = ORG_ID,
    customer_id: uuid.UUID = CUSTOMER_ID,
    email: str | None = "casey@example.com",
    is_anonymised: bool = False,
) -> MagicMock:
    """Mock a Customer ORM row with the fields ``notify_customer`` reads."""
    customer = MagicMock(spec=Customer)
    customer.id = customer_id
    customer.org_id = org_id
    customer.first_name = "Casey"
    customer.last_name = "Tester"
    customer.email = email
    customer.phone = "+64 21 555 1234"
    customer.is_anonymised = is_anonymised
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


def _make_org(*, name: str = "Acme Workshop") -> MagicMock:
    """Mock the Organisation row used for the per-org sender name."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = name
    return org


def _make_provider(provider_key: str, priority: int) -> MagicMock:
    """Mock an active EmailProvider row.

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
        "from_name": "ProviderDefault",
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
# Fake httpx client
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Drop-in replacement for ``httpx.Response``.

    Implements just the surface area the dispatchers read.
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


class _FailoverFakeClient:
    """In-process replacement for ``httpx.AsyncClient`` (failover scenario).

    Brevo (priority 1) returns 401 — drives ``SOFT_AUTH`` and the loop
    continues. SendGrid (priority 2) returns 202 with an
    ``X-Message-Id`` header — success. Captured in
    ``SendResult.message_id``.

    Class-level state is reset by each test so ordering assertions stay
    independent.
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []
    posted_headers: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        self._args = args
        self._kwargs = kwargs

    async def __aenter__(self) -> "_FailoverFakeClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        type(self).posted_headers.append(headers or {})
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
                headers={"X-Message-Id": "msg-customer-notify-1"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


class _AllFail401Client(_FailoverFakeClient):
    """Variant where every URL returns 401 — drives total auth failure."""

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).posted_urls.append(url)
        type(self).posted_payloads.append(json or {})
        type(self).posted_headers.append(headers or {})
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


class TestA12NotifyCustomerFailover:
    """End-to-end failover for ``notify_customer`` (task 3.12).

    With Brevo at priority 1 and SendGrid at priority 2,
    ``notify_customer`` must walk past the Brevo 401 (``SOFT_AUTH``),
    succeed on SendGrid (202), and return cleanly without raising.

    Validates: Requirements 6.1, 6.3, 6.5
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → both URLs hit, no failure raised.

        Pins the contract that the migrated ``notify_customer``:

        1. Calls ``send_email`` exactly once (no manual ``smtplib`` loop
           leaks back in).
        2. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). Failure on the first must NOT abort the
           chain.
        3. Builds an ``EmailMessage`` with ``org_id`` set to
           ``customer.org_id``.
        4. Returns cleanly on success and calls ``log_email_sent`` with
           ``status='sent'``.

        Validates: Requirements 6.1, 6.3, 6.5
        """
        customer = _make_customer()

        db = AsyncMock()
        # notify_customer's first two execute calls are: customer
        # SELECT, then organisation SELECT. The provider SELECT now
        # lives inside send_email and is bypassed via the
        # _load_active_providers patch below.
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(customer),
                _scalar_one_or_none_result(_make_org(name="Acme Workshop")),
            ]
        )

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)
        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        log_email_stub = AsyncMock()
        in_app_stub = AsyncMock()
        audit_stub = AsyncMock()

        _FailoverFakeClient.posted_urls = []
        _FailoverFakeClient.posted_payloads = []
        _FailoverFakeClient.posted_headers = []

        with patch(
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
            _FailoverFakeClient,
        ), patch(
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.modules.in_app_notifications.service.create_in_app_notification",
            new=in_app_stub,
        ), patch(
            "app.modules.customers.service.write_audit_log",
            new=audit_stub,
        ):
            result = await notify_customer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                channel="email",
                subject="Hello",
                message="Your car is ready for collection.",
            )

        # 1. Notify returned cleanly with the email channel.
        assert result["channel"] == "email"
        assert result["recipient"] == "casey@example.com"

        # 2. Both REST endpoints were hit in priority order — Brevo
        #    first (401, SOFT_AUTH), then SendGrid (202, success).
        assert _FailoverFakeClient.posted_urls == [
            _FailoverFakeClient.BREVO_URL,
            _FailoverFakeClient.SENDGRID_URL,
        ]

        # 3. Provider chain was loaded once and the bounce-blocklist
        #    pre-check fired exactly once.
        load_providers_stub.assert_awaited_once()
        blocklist_stub.assert_awaited_once()

        # 4. log_email_sent was called once with status='sent' on the
        #    success path.
        log_email_stub.assert_awaited_once()
        _, log_kwargs = log_email_stub.await_args
        assert log_kwargs["status"] == "sent"
        assert log_kwargs["recipient"] == "casey@example.com"
        assert log_kwargs["template_type"] == "customer_notify"
        assert log_kwargs["subject"] == "Hello"

        # 5. The success path does NOT fire the in-app failure
        #    notification.
        in_app_stub.assert_not_awaited()

        # 6. Audit log was written.
        audit_stub.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_org_sender_name_drives_from_header(self) -> None:
        """``org_sender_name=org_name`` must reach the dispatched payload.

        Requirement 6.5: when the original site used a per-org sender
        name (e.g. ``notify_customer`` using ``org_name``), the migrated
        site SHALL pass it via ``org_sender_name=...``. The unified
        sender then prefers it over the provider's ``from_name``.

        Pin this by intercepting ``send_email`` directly and asserting
        the kwarg is plumbed through.

        Validates: Requirement 6.5
        """
        customer = _make_customer()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(customer),
                _scalar_one_or_none_result(_make_org(name="Acme Workshop")),
            ]
        )

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.log_email_sent",
            new=AsyncMock(),
        ), patch(
            "app.modules.customers.service.write_audit_log",
            new=AsyncMock(),
        ):
            await notify_customer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                channel="email",
                subject="Hello",
                message="Body",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args

        # send_email signature: (db, message, *, org_sender_name=...)
        assert kwargs.get("org_sender_name") == "Acme Workshop"

        # Positional: db, message
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design Per-Site Migration Patterns > Group A row A12:
        # org_id = customer.org_id (org-scoped send).
        assert message.org_id == ORG_ID
        assert message.to_email == "casey@example.com"
        assert message.attachments == []
        assert message.subject == "Hello"

    @pytest.mark.asyncio
    async def test_all_providers_fail_raises_and_fires_failure_notif(
        self,
    ) -> None:
        """When every provider returns ``SOFT_AUTH`` ``notify_customer``
        SHALL:

        - Raise ``ValueError`` so the router surfaces HTTP 500.
        - Call ``log_email_sent`` with ``status='failed'``.
        - Fire ``create_in_app_notification(category='email_failure')``.

        Validates: Requirements 6.3, 6.4
        """
        customer = _make_customer()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(customer),
                _scalar_one_or_none_result(_make_org()),
            ]
        )

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)
        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        log_email_stub = AsyncMock()
        in_app_stub = AsyncMock()
        audit_stub = AsyncMock()

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []
        _AllFail401Client.posted_headers = []

        with patch(
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
        ), patch(
            "app.modules.notifications.service.log_email_sent",
            new=log_email_stub,
        ), patch(
            "app.modules.in_app_notifications.service.create_in_app_notification",
            new=in_app_stub,
        ), patch(
            "app.modules.customers.service.write_audit_log",
            new=audit_stub,
        ):
            with pytest.raises(ValueError, match="All email providers failed"):
                await notify_customer(
                    db,
                    org_id=ORG_ID,
                    user_id=USER_ID,
                    customer_id=CUSTOMER_ID,
                    channel="email",
                    subject="Hello",
                    message="Body",
                )

        # Both providers were attempted (chain not short-circuited by a
        # HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

        # log_email_sent called once with status='failed'.
        log_email_stub.assert_awaited_once()
        _, log_kwargs = log_email_stub.await_args
        assert log_kwargs["status"] == "failed"
        assert log_kwargs["recipient"] == "casey@example.com"
        assert log_kwargs["template_type"] == "customer_notify"

        # In-app failure notification fired with email_failure category.
        in_app_stub.assert_awaited_once()
        _ian_args, ian_kwargs = in_app_stub.await_args
        assert ian_kwargs["category"] == "email_failure"
        assert ian_kwargs["entity_type"] == "customer"
        assert ian_kwargs["entity_id"] == CUSTOMER_ID
        assert "casey@example.com" in ian_kwargs["title"]
        assert "org_admin" in ian_kwargs["audience_roles"]

        # Audit log is NOT written on the failure path — the function
        # raises before reaching write_audit_log.
        audit_stub.assert_not_awaited()


class TestA12NotifyCustomerEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A12 in
    ``design.md``: ``EmailMessage.org_id`` MUST be ``customer.org_id``;
    no attachments; subject defaults to ``f"Message from {org_name}"``
    when caller passes none.

    Validates: Requirements 6.1, 6.3, 6.5
    """

    @pytest.mark.asyncio
    async def test_default_subject_uses_org_name(self) -> None:
        """When caller passes no subject, default to ``Message from {org_name}``.

        Validates: Requirements 6.1, 6.5
        """
        customer = _make_customer()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(customer),
                _scalar_one_or_none_result(_make_org(name="Sample Garage")),
            ]
        )

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.log_email_sent",
            new=AsyncMock(),
        ), patch(
            "app.modules.customers.service.write_audit_log",
            new=AsyncMock(),
        ):
            await notify_customer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                channel="email",
                subject=None,
                message="Body",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None
        assert message.subject == "Message from Sample Garage"
        # org_sender_name reflects the org name even with default subject.
        assert kwargs.get("org_sender_name") == "Sample Garage"

    @pytest.mark.asyncio
    async def test_html_body_built_from_message_lines(self) -> None:
        """Newline-separated message becomes ``<p>``-wrapped HTML.

        Validates: Requirement 6.1 (one send_email call, no smtplib loop)
        """
        customer = _make_customer()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(customer),
                _scalar_one_or_none_result(_make_org()),
            ]
        )

        send_email_stub = AsyncMock()
        send_email_stub.return_value = MagicMock(
            success=True,
            provider_key="brevo",
            transport="rest_api",
            message_id="msg-1",
            error=None,
            attempts=[],
        )

        with patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ), patch(
            "app.modules.notifications.service.log_email_sent",
            new=AsyncMock(),
        ), patch(
            "app.modules.customers.service.write_audit_log",
            new=AsyncMock(),
        ):
            await notify_customer(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                channel="email",
                subject="Hi",
                message="Line one\nLine two",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None
        # Plain-text body preserves the original message verbatim.
        assert message.text_body == "Line one\nLine two"
        # HTML body wraps each non-blank line in <p>.
        assert "<p>Line one</p>" in message.html_body
        assert "<p>Line two</p>" in message.html_body
