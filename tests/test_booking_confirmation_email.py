"""Failover integration tests for ``_send_booking_confirmation_email`` (A6).

This file pins the Phase 3 task 3.6 contract:
``_send_booking_confirmation_email``
(``app/modules/bookings/service.py``) was migrated from a hand-rolled
``smtplib`` provider loop to a single
:func:`app.integrations.email_sender.send_email` call. The unified
sender owns failover, error classification, and per-attempt + total
time budgets — so the migration must:

1. POST both REST URLs when two providers are configured and the
   first one fails with a soft error (Brevo 401 → SendGrid 202).
2. Build an :class:`~app.integrations.email_sender.EmailMessage` with
   ``html_body=None`` and ``text_body=<plain text>`` — the legacy MIME
   builder only attached a ``text/plain`` part, no HTML alternative.
   Per the per-site variation table in
   ``.kiro/specs/email-provider-unification/design.md`` row A6, this
   site is "Plain text only, no attachment".
3. Pass ``EmailMessage.org_id = org_id`` so the bounce-blocklist
   pre-check can scope correctly.
4. Pass NO ``org_sender_name`` / ``org_reply_to`` overrides — A6 never
   set a per-org sender name (the legacy implementation read
   ``provider.config['from_name']`` with an ``org_name`` fallback that
   the unified sender does not preserve; this is intentional per the
   per-site variation table).
5. Return ``True`` on success and ``False`` on total failure (no
   ``raise`` — this is a best-effort fire-and-forget call from
   ``create_booking``).
6. On total failure, call
   ``create_in_app_notification(category="email_failure", ...)`` so
   admins see the bounce in the in-app notification list (preserved
   from the legacy raw-smtplib version).

Patches (kept self-contained — no imports from other test files):

- ``app.modules.notifications.service.resolve_template`` — returns
  ``None`` so the function falls back to the hardcoded subject / body.
  Patched at the source module because the migrated function imports
  it function-locally. The template-rendered branch is exercised in
  ``tests/test_notification_template_integration.py`` and is not in
  Phase 3 scope.
- ``app.integrations.email_sender._load_active_providers`` — returns
  the mocked provider rows in priority order.
- ``app.integrations.email_sender._check_bounce_blocklist`` — returns
  ``(False, None)``.
- ``app.integrations.email_sender.envelope_decrypt_str`` — returns
  canned credentials.
- ``app.integrations.email_sender.httpx.AsyncClient`` — fake client
  that routes by URL.

Validates: Requirements 6.1, 6.3, 6.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import
# time. Importing ``app.modules.bookings.service`` later in the test
# pulls in ``Booking`` + ``Customer`` mappers — the admin / inventory
# / org modules carry the relationships those rely on.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401


# ---------------------------------------------------------------------------
# Shared identifiers / builders
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
BOOKING_ID = uuid.uuid4()
START_TIME = datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc)


def _make_org() -> MagicMock:
    """Mock the organisation row used for the email-template context.

    The migrated function reads ``org.name`` for the body fallback and
    ``org.settings`` for the ``org_phone`` template variable. Nothing
    else.
    """
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    org.settings = {
        "phone": "09-555-1234",
    }
    return org


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
    (success).
    """

    BREVO_URL = "https://api.brevo.com/v3/smtp/email"
    SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

    posted_urls: list[str] = []
    posted_payloads: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
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
                headers={"X-Message-Id": "msg-booking-1"},
            )
        raise AssertionError(f"unexpected URL hit by the test: {url!r}")


class _AllFail401Client(_FakeClient):
    """Variant of ``_FakeClient`` where every URL returns 401."""

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


def _build_db_execute_side_effect(*, org: MagicMock) -> list:
    """Return the ordered ``db.execute`` results for the success path.

    The migrated function only does ONE ``db.execute`` before
    ``send_email`` — the ``Organisation`` lookup. The previous
    ``select(EmailProvider)`` is now done **inside** ``send_email`` —
    and ``_load_active_providers`` is patched out at that level — so
    the caller's ``db.execute`` no longer sees that statement.
    """
    return [_scalar_one_or_none_result(org)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA6SendBookingConfirmationEmailFailover:
    """End-to-end failover for ``_send_booking_confirmation_email``
    (task 3.6).

    With Brevo at priority 1 and SendGrid at priority 2, the function
    must walk past the Brevo 401 (``SOFT_AUTH``), succeed on SendGrid
    (202), and return ``True``.

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_returns_true(self) -> None:
        """Brevo 401 → SendGrid 202 → function returns ``True``.

        Pins the contract that the migrated
        ``_send_booking_confirmation_email``:

        1. Calls ``send_email`` exactly once (no manual ``smtplib``
           loop leaks back in).
        2. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). Failure on the first must NOT abort
           the chain.
        3. Returns ``True`` (the success path returns
           ``result.success`` which is ``True`` after SendGrid's 202).

        Validates: Requirements 6.1, 6.3, 6.4
        """
        org = _make_org()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(org=org)
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FakeClient.posted_urls = []
        _FakeClient.posted_payloads = []

        with patch(
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
            from app.modules.bookings.service import (
                _send_booking_confirmation_email,
            )

            result = await _send_booking_confirmation_email(
                db,
                org_id=ORG_ID,
                booking_id=BOOKING_ID,
                customer_first_name="Casey",
                customer_email="casey@example.com",
                service_type="WOF",
                start_time=START_TIME,
                duration_minutes=60,
                vehicle_rego="ABC123",
                notes="Please check tyre pressure",
            )

        # 1. The function returns True (the contract from ``create_booking``
        #    that `confirmation_sent` is truthy when the email got out).
        assert result is True

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

        # 4. The recipient on each payload matches the caller's
        #    ``customer_email`` argument — sanity check that the
        #    migration didn't drop the To address on the floor.
        brevo_payload = _FakeClient.posted_payloads[0]
        sendgrid_payload = _FakeClient.posted_payloads[1]
        assert brevo_payload["to"][0]["email"] == "casey@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "casey@example.com"
        )

        # 5. Plain-text body went out (no HTML alternative) — A6 is
        #    "plain text only, no attachment" per the per-site
        #    variation table.
        assert "Casey" in brevo_payload.get("textContent", "")
        assert "WOF" in brevo_payload.get("textContent", "")
        assert "ABC123" in brevo_payload.get("textContent", "")
        # No htmlContent key (or empty) on the Brevo payload because
        # the migration sets ``html_body=None``.
        assert not brevo_payload.get("htmlContent")

        # 6. No attachments on either payload — A6 sends no PDF.
        assert brevo_payload.get("attachment", []) == []
        assert sendgrid_payload.get("attachments", []) == []

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_false_and_creates_in_app_notification(
        self,
    ) -> None:
        """When every provider returns ``SOFT_AUTH`` the function returns
        ``False`` and writes an in-app notification with category
        ``email_failure`` — preserving the contract the original
        raw-smtplib version had. Unlike A1/A2/A4/A5 it does NOT raise:
        ``_send_booking_confirmation_email`` is called best-effort
        from ``create_booking`` and the booking itself must commit
        regardless of email delivery.

        Validates: Requirements 6.3, 6.4
        """
        org = _make_org()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(org=org)
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        in_app_stub = AsyncMock()

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.modules.bookings.service.create_in_app_notification",
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
            from app.modules.bookings.service import (
                _send_booking_confirmation_email,
            )

            result = await _send_booking_confirmation_email(
                db,
                org_id=ORG_ID,
                booking_id=BOOKING_ID,
                customer_first_name="Casey",
                customer_email="casey@example.com",
                service_type="WOF",
                start_time=START_TIME,
                duration_minutes=60,
                vehicle_rego="ABC123",
                notes=None,
            )

        # 1. Best-effort contract: returns False, does NOT raise.
        assert result is False

        # 2. Both providers were attempted (chain not short-circuited
        #    by a HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

        # 3. create_in_app_notification was called once with the
        #    'email_failure' category (preserved from the original
        #    raw-smtplib failure handler).
        in_app_stub.assert_awaited_once()
        _ian_args, ian_kwargs = in_app_stub.await_args
        assert ian_kwargs["category"] == "email_failure"
        assert ian_kwargs["entity_type"] == "booking"
        assert ian_kwargs["entity_id"] == BOOKING_ID
        assert ian_kwargs["audience_roles"] == ["org_admin"]
        assert "casey@example.com" in ian_kwargs["title"]
        assert (
            ian_kwargs["metadata"]["template_type"] == "booking_confirmation"
        )
        assert ian_kwargs["metadata"]["recipient_email"] == "casey@example.com"


class TestA6SendBookingConfirmationEmailMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A6 in
    ``design.md``: ``EmailMessage.org_id`` MUST be the caller's
    ``org_id``; the body is plain text only (``html_body=None``); no
    attachments; no ``org_sender_name`` override.

    Validates: Requirement 6.3 (org_id plumbing) and 6.4 (no manual
    smtplib loop)
    """

    @pytest.mark.asyncio
    async def test_email_message_carries_org_id_and_plain_text_only_body(
        self,
    ) -> None:
        """``send_email`` is called with the right ``EmailMessage`` shape.

        Pins:

        - ``message.org_id == org_id`` (per the per-site variation
          table — A6's ``org_id`` source is ``booking.org_id``, which
          matches the caller's ``org_id`` argument).
        - ``message.text_body`` is the plain-text body (contains the
          customer name and service type).
        - ``message.html_body`` is ``None`` — the legacy MIME builder
          only attached a ``text/plain`` part, so the migration
          intentionally does not synthesise an HTML alternative.
        - ``message.attachments`` is empty — A6 sends no PDF.

        Validates: Requirements 6.1, 6.3
        """
        org = _make_org()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(org=org)
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
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            # Patch where the migrated function imports it (function-
            # local import inside ``_send_booking_confirmation_email``).
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.bookings.service import (
                _send_booking_confirmation_email,
            )

            await _send_booking_confirmation_email(
                db,
                org_id=ORG_ID,
                booking_id=BOOKING_ID,
                customer_first_name="Casey",
                customer_email="casey@example.com",
                service_type="WOF",
                start_time=START_TIME,
                duration_minutes=60,
                vehicle_rego="ABC123",
                notes="Please check tyre pressure",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        # Positional: db, message
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design Per-Site Migration Patterns > Group A row A6:
        # org_id = booking.org_id (== caller's org_id).
        assert message.org_id == ORG_ID
        assert message.to_email == "casey@example.com"
        # Subject contains the service type and a date phrase.
        assert "WOF" in message.subject

        # Plain-text-only body — A6 is explicitly "plain text only, no
        # attachment" per the per-site variation table. The legacy
        # MIME builder only attached ``MIMEText(body, "plain")``.
        assert message.html_body is None
        assert message.text_body is not None
        assert "Casey" in message.text_body
        assert "WOF" in message.text_body
        assert "ABC123" in message.text_body
        assert "Please check tyre pressure" in message.text_body

        # No attachments.
        assert message.attachments == []

    @pytest.mark.asyncio
    async def test_no_org_sender_name_passed(self) -> None:
        """A6 does NOT pass ``org_sender_name`` to ``send_email``.

        Per the per-site variation table the ``org_sender_name``
        column for A6 is ``None`` — the provider's configured
        ``from_name`` (or its fallback) is used. This pins that
        contract: a future refactor that starts plumbing
        ``org.name`` into ``org_sender_name`` would change the From
        header on outbound booking confirmations and would need
        explicit review.

        Validates: Requirement 6.5 (org_sender_name only when
        originally set — A6 never set one)
        """
        org = _make_org()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(org=org)
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
            "app.modules.notifications.service.resolve_template",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.bookings.service import (
                _send_booking_confirmation_email,
            )

            await _send_booking_confirmation_email(
                db,
                org_id=ORG_ID,
                booking_id=BOOKING_ID,
                customer_first_name="Casey",
                customer_email="casey@example.com",
                service_type=None,
                start_time=START_TIME,
                duration_minutes=30,
                vehicle_rego=None,
                notes=None,
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args

        # No org_sender_name keyword — the provider's from_name (or
        # its default) is what shows up in the From header.
        assert "org_sender_name" not in kwargs or kwargs["org_sender_name"] is None
        assert "org_reply_to" not in kwargs or kwargs["org_reply_to"] is None
