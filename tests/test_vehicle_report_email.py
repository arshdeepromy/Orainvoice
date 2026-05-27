"""Failover integration tests for ``email_service_history_report`` (A5).

This file pins the Phase 3 task 3.5 contract:
``email_service_history_report``
(``app/modules/vehicles/report_service.py``) was migrated from a
hand-rolled ``smtplib`` provider loop to a single
:func:`app.integrations.email_sender.send_email` call. The unified
sender owns failover, error classification, and per-attempt + total
time budgets — so the migration must:

1. Surface both REST URLs (POSTs) when two providers are configured
   and the first one fails with a soft error (Brevo 401 → SendGrid
   202).
2. Build a single PDF :class:`~app.integrations.email_sender.EmailAttachment`
   from the bytes returned by ``generate_service_history_pdf``.
3. Render the HTML body from the
   ``app/templates/pdf/service_history_email.html`` Jinja template
   and pass it as ``EmailMessage.html_body`` (no plain-text body —
   the legacy MIME builder only attached a ``text/html`` part).
4. Pass ``EmailMessage.org_id = org_id`` so the bounce-blocklist
   pre-check can scope correctly.
5. Preserve the original failure handling: when every provider fails
   call ``log_email_sent(status='failed')`` and
   ``create_in_app_notification(category='email_failure')``, then
   raise ``ValueError`` with the chain's last error.
6. Preserve the audit-log call on success, recording
   ``after_value['provider']`` as the winning provider's key (NOT the
   first one tried).

Notes on the original site:

- The legacy implementation built its own MIME envelope with only a
  ``text/html`` body part — no plain-text alternative — so the
  migrated ``EmailMessage`` carries ``html_body`` only and leaves
  ``text_body=None``.
- The function reads from :class:`~app.modules.admin.models.GlobalVehicle`
  first, and falls back to :class:`~app.modules.vehicles.models.OrgVehicle`
  if not found.

Patches (kept self-contained — no imports from other test files):

- ``app.modules.vehicles.report_service.generate_service_history_pdf``
  returns fixed bytes so the PDF attachment is deterministic.
- ``app.integrations.email_sender._load_active_providers`` returns the
  mocked provider rows in priority order; ``_check_bounce_blocklist``
  returns ``(False, None)``; ``envelope_decrypt_str`` returns canned
  credentials; ``httpx.AsyncClient`` is replaced with an in-process
  fake whose responses depend on the URL hit.

Validates: Requirements 6.1, 6.3, 6.4
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import
# time. ``app.modules.admin.models`` brings in ``EmailProvider`` /
# ``Organisation`` / ``GlobalVehicle``; importing
# ``app.modules.vehicles.report_service`` early in the test would
# otherwise miss these.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401


# ---------------------------------------------------------------------------
# Shared identifiers / builders
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
VEHICLE_ID = uuid.uuid4()


def _make_vehicle() -> MagicMock:
    """Mock a :class:`~app.modules.admin.models.GlobalVehicle` ORM row.

    The function only reads ``rego``, ``make``, ``model``, and
    ``year`` for the subject / filename / template context.
    """
    vehicle = MagicMock()
    vehicle.id = VEHICLE_ID
    vehicle.rego = "ABC123"
    vehicle.make = "Toyota"
    vehicle.model = "Corolla"
    vehicle.year = 2020
    return vehicle


def _make_org() -> MagicMock:
    """Mock the organisation row used for the email-template context."""
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop Ltd"
    org.settings = {
        "email": "info@test.co.nz",
        "phone": "09-555-1234",
        "address": "123 Test St, Auckland",
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
    (success — captured into ``EmailAttempt.message_id`` and surfaced
    as ``SendResult.message_id``).

    The class-level ``posted_urls`` / ``posted_payloads`` lists are
    reset by each test so the ordering assertion is order-independent.
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
                headers={"X-Message-Id": "msg-vehicle-report-1"},
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


def _build_db_execute_side_effect(
    *,
    vehicle: MagicMock,
    org: MagicMock,
) -> list:
    """Return the ordered ``db.execute`` results for the success path.

    Order follows ``email_service_history_report``'s code path:

    1. ``GlobalVehicle`` row lookup.
    2. ``Organisation`` row lookup (used for branding context).

    The previous ``select(EmailProvider)`` query is now done **inside**
    ``send_email`` — and ``_load_active_providers`` is patched out at
    that level — so the caller's ``db.execute`` no longer sees that
    statement. The audit-log call that follows the send writes via
    :func:`app.core.audit.write_audit_log` which we patch out, so the
    side-effect list does not need to cover any further executes.
    """
    return [
        _scalar_one_or_none_result(vehicle),
        _scalar_one_or_none_result(org),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestA5EmailServiceHistoryReportFailover:
    """End-to-end failover for ``email_service_history_report``
    (task 3.5).

    With Brevo at priority 1 and SendGrid at priority 2, the function
    must walk past the Brevo 401 (``SOFT_AUTH``), succeed on SendGrid
    (202), and record SendGrid as the winning provider in the
    audit-log payload.

    Validates: Requirements 6.1, 6.3, 6.4
    """

    @pytest.mark.asyncio
    async def test_failover_to_second_provider_succeeds(self) -> None:
        """Brevo 401 → SendGrid 202 → audit log records ``sendgrid``.

        Pins the contract that the migrated
        ``email_service_history_report``:

        1. Calls ``send_email`` exactly once (no manual ``smtplib``
           loop leaks back in).
        2. POSTs the Brevo URL first (priority 1) and the SendGrid URL
           second (priority 2). Failure on the first must NOT abort
           the chain.
        3. Builds an ``EmailMessage`` with ``org_id`` set to the
           caller's ``org_id`` and includes the PDF as a single
           ``application/pdf`` attachment.
        4. Returns ``status='sent'`` plus the recipient and PDF size.
        5. Writes an audit-log entry whose
           ``after_value['provider']`` is ``"sendgrid"`` (the winning
           provider, not the first one tried).

        Validates: Requirements 6.1, 6.3, 6.4
        """
        vehicle = _make_vehicle()
        org = _make_org()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(vehicle=vehicle, org=org)
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        audit_log_stub = AsyncMock()

        # Reset class-level state on the fake client so this test is
        # order-independent within the suite.
        _FakeClient.posted_urls = []
        _FakeClient.posted_payloads = []

        with patch(
            "app.modules.vehicles.report_service.generate_service_history_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake-vehicle-bytes",
        ), patch(
            "app.core.audit.write_audit_log",
            new=audit_log_stub,
        ), patch(
            "app.core.pdf_utils.resolve_logo_for_pdf",
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
            from app.modules.vehicles.report_service import (
                email_service_history_report,
            )

            result = await email_service_history_report(
                db,
                org_id=ORG_ID,
                vehicle_id=VEHICLE_ID,
                range_years=1,
                recipient_email="owner@example.com",
            )

        # 1. The function returns the Phase 3 contract: sent +
        #    recipient + PDF size.
        assert result["status"] == "sent"
        assert result["recipient_email"] == "owner@example.com"
        assert result["vehicle_id"] == str(VEHICLE_ID)
        assert result["pdf_size_bytes"] == len(b"%PDF-fake-vehicle-bytes")

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

        # 4. Both dispatched payloads carry the PDF attachment with
        #    the rego-prefixed filename. Brevo uses an ``attachment``
        #    array with ``name``; SendGrid uses ``attachments`` with
        #    ``filename``. The PDF is the only attachment.
        brevo_payload = _FakeClient.posted_payloads[0]
        sendgrid_payload = _FakeClient.posted_payloads[1]

        assert "attachment" in brevo_payload
        assert len(brevo_payload["attachment"]) == 1
        assert brevo_payload["attachment"][0]["name"].startswith("ABC123_service_history_")
        assert brevo_payload["attachment"][0]["name"].endswith(".pdf")

        assert "attachments" in sendgrid_payload
        assert len(sendgrid_payload["attachments"]) == 1
        assert sendgrid_payload["attachments"][0]["filename"].startswith(
            "ABC123_service_history_"
        )
        assert sendgrid_payload["attachments"][0]["filename"].endswith(".pdf")

        # 5. The recipient on each payload matches the caller's
        #    ``recipient_email`` argument — sanity check that the
        #    migration didn't drop the To address on the floor.
        assert brevo_payload["to"][0]["email"] == "owner@example.com"
        assert (
            sendgrid_payload["personalizations"][0]["to"][0]["email"]
            == "owner@example.com"
        )

        # 6. The HTML body rendered from the Jinja template went out
        #    on both providers (not a plain-text fallback).
        assert "ABC123" in brevo_payload.get("htmlContent", "")
        assert "Service History Report" in brevo_payload.get("htmlContent", "")

        # 7. Audit log records the winning provider — sendgrid, not
        #    the brevo one that 401'd first.
        audit_log_stub.assert_awaited_once()
        _audit_args, audit_kwargs = audit_log_stub.await_args
        assert audit_kwargs["action"] == "vehicle.report_emailed"
        assert audit_kwargs["entity_type"] == "vehicle"
        assert audit_kwargs["entity_id"] == VEHICLE_ID
        assert audit_kwargs["after_value"]["provider"] == "sendgrid"
        assert audit_kwargs["after_value"]["recipient"] == "owner@example.com"
        assert audit_kwargs["after_value"]["vehicle_rego"] == "ABC123"
        assert audit_kwargs["after_value"]["pdf_size_bytes"] == len(
            b"%PDF-fake-vehicle-bytes"
        )

    @pytest.mark.asyncio
    async def test_all_providers_fail_logs_and_creates_in_app_notification(
        self,
    ) -> None:
        """When every provider returns ``SOFT_AUTH``
        ``email_service_history_report`` raises ``ValueError`` and the
        failure path runs both ``log_email_sent(status='failed')`` and
        ``create_in_app_notification(category='email_failure')`` —
        preserving the contract the original raw-smtplib version had.

        Validates: Requirements 6.3, 6.4
        """
        vehicle = _make_vehicle()
        org = _make_org()

        brevo_provider = _make_provider("brevo", priority=1)
        sendgrid_provider = _make_provider("sendgrid", priority=2)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(vehicle=vehicle, org=org)
        )

        load_providers_stub = AsyncMock(
            return_value=[brevo_provider, sendgrid_provider]
        )
        blocklist_stub = AsyncMock(return_value=(False, None))
        log_email_stub = AsyncMock()
        in_app_stub = AsyncMock()

        _AllFail401Client.posted_urls = []
        _AllFail401Client.posted_payloads = []

        with patch(
            "app.modules.vehicles.report_service.generate_service_history_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-fake-vehicle-bytes",
        ), patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.core.pdf_utils.resolve_logo_for_pdf",
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
            from app.modules.vehicles.report_service import (
                email_service_history_report,
            )

            with pytest.raises(ValueError, match="All email providers failed"):
                await email_service_history_report(
                    db,
                    org_id=ORG_ID,
                    vehicle_id=VEHICLE_ID,
                    range_years=1,
                    recipient_email="owner@example.com",
                )

        # Both providers were attempted (chain not short-circuited by
        # a HARD_* failure).
        assert len(_AllFail401Client.posted_urls) == 2

        # log_email_sent was called once with status='failed' (preserved
        # from the original raw-smtplib failure handler).
        log_email_stub.assert_awaited_once()
        _log_args, log_kwargs = log_email_stub.await_args
        assert log_kwargs["status"] == "failed"
        assert log_kwargs["template_type"] == "vehicle_report_send"
        assert log_kwargs["recipient"] == "owner@example.com"
        assert log_kwargs["org_id"] == ORG_ID

        # create_in_app_notification was called once with the
        # 'email_failure' category (preserved from the original
        # raw-smtplib failure handler).
        in_app_stub.assert_awaited_once()
        _ian_args, ian_kwargs = in_app_stub.await_args
        assert ian_kwargs["category"] == "email_failure"
        assert ian_kwargs["entity_type"] == "vehicle"
        assert ian_kwargs["entity_id"] == VEHICLE_ID
        assert "owner@example.com" in ian_kwargs["title"]
        assert "ABC123" in ian_kwargs["title"]
        assert ian_kwargs["audience_roles"] == ["org_admin", "salesperson"]


class TestA5EmailServiceHistoryReportMessage:
    """Pin the ``EmailMessage`` shape the migration constructs.

    Validates the per-site variation table entry for A5 in
    ``design.md``: ``EmailMessage.org_id`` MUST be the caller's
    ``org_id``; the body is the rendered Jinja template as
    ``html_body`` (no plain-text alternative); the PDF is built into a
    single ``EmailAttachment`` with the
    ``{rego}_service_history_{YYYY-MM-DD}.pdf`` filename pattern.

    Validates: Requirement 6.3 (org_id plumbing) and 6.4 (no manual
    smtplib loop)
    """

    @pytest.mark.asyncio
    async def test_email_message_carries_org_id_and_html_only_body(
        self,
    ) -> None:
        """``send_email`` is called with ``message.org_id == org_id``.

        Also pins:

        - ``html_body`` is the rendered Jinja template (contains the
          rego and report heading text).
        - ``text_body`` is ``None`` — the legacy MIME builder only
          attached a ``text/html`` part, so the migration intentionally
          does not synthesise a plain-text alternative.
        - The single PDF ``EmailAttachment`` has the
          ``{rego}_service_history_{YYYY-MM-DD}.pdf`` filename and
          ``application/pdf`` mime type.

        Validates: Requirements 6.1, 6.3
        """
        vehicle = _make_vehicle()
        org = _make_org()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(vehicle=vehicle, org=org)
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
            "app.modules.vehicles.report_service.generate_service_history_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-bytes",
        ), patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.core.pdf_utils.resolve_logo_for_pdf",
            return_value=None,
        ), patch(
            # Patch where the migrated function imports it (function-
            # local import inside ``email_service_history_report``).
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.vehicles.report_service import (
                email_service_history_report,
            )

            await email_service_history_report(
                db,
                org_id=ORG_ID,
                vehicle_id=VEHICLE_ID,
                range_years=2,
                recipient_email="owner@example.com",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args
        # Positional: db, message
        message = _args[1] if len(_args) > 1 else kwargs.get("message")
        assert message is not None

        # Per design Per-Site Migration Patterns > Group A row A5:
        # org_id = vehicle.org_id (== caller's org_id).
        assert message.org_id == ORG_ID
        assert message.to_email == "owner@example.com"
        assert message.subject == "ABC123 - Service History Report"

        # HTML-only body — the legacy site's MIMEText was 'html', no
        # text/plain alternative. Body comes from the Jinja template.
        assert message.text_body is None
        assert message.html_body is not None
        assert "ABC123" in message.html_body
        assert "Service History Report" in message.html_body

        # Single PDF attachment from generate_service_history_pdf bytes.
        assert len(message.attachments) == 1
        attachment = message.attachments[0]
        # Filename pattern: {rego}_service_history_{YYYY-MM-DD}.pdf
        assert attachment.filename.startswith("ABC123_service_history_")
        assert attachment.filename.endswith(".pdf")
        assert attachment.mime_type == "application/pdf"
        assert attachment.content == b"%PDF-bytes"

    @pytest.mark.asyncio
    async def test_no_org_sender_name_passed(self) -> None:
        """A5 does NOT pass ``org_sender_name`` to ``send_email``.

        Per the per-site variation table, the ``org_sender_name``
        column for A5 is ``None`` — the provider's configured
        ``from_name`` (or its fallback) is used. This pins that
        contract: a future refactor that starts plumbing
        ``org.name`` into ``org_sender_name`` would change the From
        header on outbound vehicle reports and would need explicit
        review.

        Validates: Requirement 6.5 (org_sender_name only when
        originally set — A5 never set one)
        """
        vehicle = _make_vehicle()
        org = _make_org()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=_build_db_execute_side_effect(vehicle=vehicle, org=org)
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
            "app.modules.vehicles.report_service.generate_service_history_pdf",
            new_callable=AsyncMock,
            return_value=b"%PDF-bytes",
        ), patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ), patch(
            "app.core.pdf_utils.resolve_logo_for_pdf",
            return_value=None,
        ), patch(
            "app.integrations.email_sender.send_email",
            new=send_email_stub,
        ):
            from app.modules.vehicles.report_service import (
                email_service_history_report,
            )

            await email_service_history_report(
                db,
                org_id=ORG_ID,
                vehicle_id=VEHICLE_ID,
                range_years=0,
                recipient_email="owner@example.com",
            )

        send_email_stub.assert_awaited_once()
        _args, kwargs = send_email_stub.await_args

        # No org_sender_name keyword — the provider's from_name (or
        # its default) is what shows up in the From header.
        assert "org_sender_name" not in kwargs or kwargs["org_sender_name"] is None
        assert "org_reply_to" not in kwargs or kwargs["org_reply_to"] is None
