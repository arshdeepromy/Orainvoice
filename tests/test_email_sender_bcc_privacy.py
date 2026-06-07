"""BCC-privacy unit tests for the unified email sender (send-email-modal task 2.2).

These tests pin the privacy contract for the ``cc`` / ``bcc`` fields added to
``EmailMessage`` in task 2.1 across every transport:

- **MIME builder** (``_build_mime_message``, used by the SMTP transport):
  ``Cc`` recipients appear in the visible ``Cc:`` header; ``Bcc`` recipients
  NEVER appear in any header (no ``Bcc:`` header is emitted, and the bcc
  address must not leak into the serialised message at all).
- **SMTP envelope** (``_dispatch_smtp`` → ``smtplib.sendmail``): the envelope
  ``RCPT TO`` list is ``[to, *cc, *bcc]`` so bcc recipients still receive the
  mail, while staying invisible in the rendered headers.
- **REST payload builders** (``_dispatch_brevo_rest`` / ``_dispatch_sendgrid_rest``
  / ``_dispatch_resend_rest``): bcc addresses go in the provider's dedicated
  ``bcc`` field, never in the ``to`` / ``cc`` arrays.

Design ref: Testing Strategy → "BCC-privacy unit test on ``_build_mime_message``".

Validates: Requirements 4.9
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time —
# ``email_sender`` imports ``EmailProvider`` from ``admin.models`` which pulls
# in a network of cross-module relationships (mirrors the other sender tests).
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.integrations.email_sender import (
    EmailMessage,
    _build_mime_message,
    _dispatch_brevo_rest,
    _dispatch_resend_rest,
    _dispatch_sendgrid_rest,
    _dispatch_smtp,
)

# ---------------------------------------------------------------------------
# Test fixtures / constants
# ---------------------------------------------------------------------------

TO_EMAIL = "customer@example.com"
CC_EMAIL = "accountant@example.com"
BCC_EMAIL_1 = "secret-audit@example.com"
BCC_EMAIL_2 = "compliance@example.com"

FROM_NAME = "OraInvoice"
FROM_EMAIL = "noreply@orainvoice.test"


def _make_message() -> EmailMessage:
    """An ``EmailMessage`` with one To, one Cc, and two Bcc recipients."""
    return EmailMessage(
        to_email=TO_EMAIL,
        to_name="Customer",
        subject="Your invoice",
        html_body="<p>Please find your invoice attached.</p>",
        text_body="Please find your invoice attached.",
        cc=[CC_EMAIL],
        bcc=[BCC_EMAIL_1, BCC_EMAIL_2],
    )


def _make_provider(provider_key: str, *, smtp: bool = False) -> MagicMock:
    """Mock an active ``EmailProvider`` ORM row.

    The dispatchers read ``credentials_set``, ``credentials_encrypted``,
    ``provider_key`` and ``config['from_email']`` (REST) plus the smtp_*
    host fields (SMTP). The blob bytes are opaque because ``envelope_decrypt_str``
    is patched to return canned credentials.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.credentials_set = True
    provider.credentials_encrypted = b"encrypted-blob"
    provider.config = {"from_email": FROM_EMAIL, "from_name": FROM_NAME}
    if smtp:
        provider.smtp_host = "smtp.example.test"
        provider.smtp_port = 587
        provider.smtp_encryption = "tls"
    else:
        provider.smtp_host = None
        provider.smtp_port = None
        provider.smtp_encryption = "tls"
    return provider


class _FakeResponse:
    """Minimal ``httpx.Response`` stand-in for the REST dispatchers.

    Returns a success status (200 — accepted by all three dispatchers) with
    both a ``messageId``/``id`` JSON body and an ``X-Message-Id`` header so the
    same instance satisfies Brevo, SendGrid, and Resend success parsing.
    """

    status_code = 200
    text = '{"messageId": "m-1", "id": "m-1"}'
    headers = {"X-Message-Id": "m-1", "content-type": "application/json"}

    def json(self) -> dict:
        return {"messageId": "m-1", "id": "m-1"}


class _CapturingClient:
    """In-process ``httpx.AsyncClient`` replacement that captures the payload."""

    last_payload: dict | None = None
    last_url: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_CapturingClient":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).last_payload = json or {}
        type(self).last_url = url
        return _FakeResponse()


# ---------------------------------------------------------------------------
# MIME builder (SMTP header privacy)
# ---------------------------------------------------------------------------


def test_build_mime_message_cc_visible_bcc_absent_from_headers() -> None:
    """``_build_mime_message`` exposes Cc but never emits a Bcc header.

    Validates: Requirements 4.9
    """
    mime = _build_mime_message(
        _make_message(),
        from_name=FROM_NAME,
        from_email=FROM_EMAIL,
        reply_to=None,
        message_id="<msg-id@orainvoice.test>",
    )

    # No Bcc header exists at all (blind by construction).
    assert mime.get("Bcc") is None
    assert "Bcc" not in mime

    # The To header carries only the primary recipient.
    to_header = mime.get("To")
    assert TO_EMAIL in to_header
    assert CC_EMAIL not in to_header
    assert BCC_EMAIL_1 not in to_header
    assert BCC_EMAIL_2 not in to_header

    # The Cc header carries the cc recipient and no bcc addresses.
    cc_header = mime.get("Cc")
    assert CC_EMAIL in cc_header
    assert BCC_EMAIL_1 not in cc_header
    assert BCC_EMAIL_2 not in cc_header

    # The fully-serialised message must not leak either bcc address
    # anywhere (headers or body).
    raw = mime.as_string()
    assert CC_EMAIL in raw
    assert BCC_EMAIL_1 not in raw
    assert BCC_EMAIL_2 not in raw


# ---------------------------------------------------------------------------
# SMTP envelope (RCPT TO list carries bcc; headers do not)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_smtp_envelope_includes_bcc_but_headers_hide_it() -> None:
    """``_dispatch_smtp`` passes ``[to, *cc, *bcc]`` as envelope recipients,
    while the rendered MIME headers expose only To + Cc.

    Validates: Requirements 4.9
    """
    captured: dict = {}

    class _FakeSMTP:
        """Records the ``sendmail`` envelope without touching the network."""

        def __init__(self, host, port, timeout=None) -> None:
            captured["host"] = host
            captured["port"] = port

        def starttls(self) -> None:
            captured["starttls"] = True

        def login(self, username, password) -> None:
            captured["login"] = (username, password)

        def sendmail(self, from_addr, to_addrs, raw_payload) -> None:
            captured["from_addr"] = from_addr
            captured["to_addrs"] = list(to_addrs)
            captured["raw_payload"] = raw_payload

        def quit(self) -> None:
            captured["quit"] = True

    provider = _make_provider("custom_smtp", smtp=True)

    with patch(
        "app.integrations.email_sender.smtplib.SMTP",
        _FakeSMTP,
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"username": "smtp-user", "password": "smtp-pass"}',
    ):
        attempt = await _dispatch_smtp(
            provider,
            _make_message(),
            from_name=FROM_NAME,
            from_email=FROM_EMAIL,
            reply_to=None,
            timeout_seconds=5,
        )

    assert attempt.success is True

    # Envelope RCPT TO list = To + Cc + Bcc, in that order. Bcc recipients
    # still receive the message via the envelope.
    assert captured["to_addrs"] == [TO_EMAIL, CC_EMAIL, BCC_EMAIL_1, BCC_EMAIL_2]

    # The wire payload (rendered MIME) hides every bcc address but keeps cc.
    raw_payload = captured["raw_payload"]
    assert CC_EMAIL in raw_payload
    assert BCC_EMAIL_1 not in raw_payload
    assert BCC_EMAIL_2 not in raw_payload


# ---------------------------------------------------------------------------
# REST payload builders (provider bcc field; never in to/cc)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brevo_rest_payload_bcc_isolated_from_to_and_cc() -> None:
    """Brevo REST payload: bcc lives in the top-level ``bcc`` array only.

    Validates: Requirements 4.9
    """
    _CapturingClient.last_payload = None
    provider = _make_provider("brevo")

    with patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _CapturingClient,
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "test-key"}',
    ):
        attempt = await _dispatch_brevo_rest(
            provider,
            _make_message(),
            from_name=FROM_NAME,
            from_email=FROM_EMAIL,
            reply_to=None,
            timeout_seconds=5,
        )

    assert attempt.success is True
    payload = _CapturingClient.last_payload or {}

    to_emails = [r.get("email") for r in payload.get("to", [])]
    cc_emails = [r.get("email") for r in payload.get("cc", [])]
    bcc_emails = [r.get("email") for r in payload.get("bcc", [])]

    assert to_emails == [TO_EMAIL]
    assert cc_emails == [CC_EMAIL]
    assert bcc_emails == [BCC_EMAIL_1, BCC_EMAIL_2]

    # bcc addresses must not bleed into the visible to/cc arrays.
    assert BCC_EMAIL_1 not in to_emails and BCC_EMAIL_1 not in cc_emails
    assert BCC_EMAIL_2 not in to_emails and BCC_EMAIL_2 not in cc_emails


@pytest.mark.asyncio
async def test_sendgrid_rest_payload_bcc_isolated_from_to_and_cc() -> None:
    """SendGrid v3 payload: bcc lives in the personalization ``bcc`` array only.

    Validates: Requirements 4.9
    """
    _CapturingClient.last_payload = None
    provider = _make_provider("sendgrid")

    with patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _CapturingClient,
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "test-key"}',
    ):
        attempt = await _dispatch_sendgrid_rest(
            provider,
            _make_message(),
            from_name=FROM_NAME,
            from_email=FROM_EMAIL,
            reply_to=None,
            timeout_seconds=5,
        )

    assert attempt.success is True
    payload = _CapturingClient.last_payload or {}
    personalization = (payload.get("personalizations") or [{}])[0]

    to_emails = [r.get("email") for r in personalization.get("to", [])]
    cc_emails = [r.get("email") for r in personalization.get("cc", [])]
    bcc_emails = [r.get("email") for r in personalization.get("bcc", [])]

    assert to_emails == [TO_EMAIL]
    assert cc_emails == [CC_EMAIL]
    assert bcc_emails == [BCC_EMAIL_1, BCC_EMAIL_2]

    assert BCC_EMAIL_1 not in to_emails and BCC_EMAIL_1 not in cc_emails
    assert BCC_EMAIL_2 not in to_emails and BCC_EMAIL_2 not in cc_emails


@pytest.mark.asyncio
async def test_resend_rest_payload_bcc_isolated_from_to_and_cc() -> None:
    """Resend payload: bcc lives in the top-level ``bcc`` string array only.

    Validates: Requirements 4.9
    """
    _CapturingClient.last_payload = None
    provider = _make_provider("resend")

    with patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _CapturingClient,
    ), patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "test-key"}',
    ):
        attempt = await _dispatch_resend_rest(
            provider,
            _make_message(),
            from_name=FROM_NAME,
            from_email=FROM_EMAIL,
            reply_to=None,
            timeout_seconds=5,
        )

    assert attempt.success is True
    payload = _CapturingClient.last_payload or {}

    to_emails = payload.get("to", [])
    cc_emails = payload.get("cc", [])
    bcc_emails = payload.get("bcc", [])

    assert to_emails == [TO_EMAIL]
    assert cc_emails == [CC_EMAIL]
    assert bcc_emails == [BCC_EMAIL_1, BCC_EMAIL_2]

    assert BCC_EMAIL_1 not in to_emails and BCC_EMAIL_1 not in cc_emails
    assert BCC_EMAIL_2 not in to_emails and BCC_EMAIL_2 not in cc_emails
