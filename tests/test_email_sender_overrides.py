"""Unit tests for sender-identity override precedence — REST + SMTP.

Covers task 1.13 of the email-provider-unification spec: when a caller
supplies ``org_sender_name`` and/or ``org_reply_to`` to
:func:`~app.integrations.email_sender.dispatch_one_provider`, those
caller-provided values must win over the provider's static
``config['from_name']`` / ``config['reply_to']``.

The precedence is fixed by ``_resolve_sender_identity`` (design
Components §6):

- ``from_name``  = ``org_sender_name`` OR ``provider.config['from_name']`` OR ``""``
- ``from_email`` = ``provider.config['from_email']``  (always provider; required)
- ``reply_to``   = ``org_reply_to`` OR ``provider.config['reply_to']`` OR ``None``

We pin all three legs of that precedence:

- **Test 1 — Brevo REST.** Caller passes overrides; assert the captured
  JSON payload's ``sender.name`` and ``replyTo.email`` come from the
  caller, while ``sender.email`` still comes from the provider's
  ``from_email`` (which has no override path).
- **Test 2 — SMTP.** Same provider config but routed via SMTP; parse
  the raw MIME string and assert the ``From`` header carries the
  caller-supplied display name with the provider's ``from_email``, and
  the ``Reply-To`` header equals the caller's value.
- **Test 3 — provider config wins when overrides are absent.** Same
  provider config but the caller passes neither override; assert the
  outbound payload reflects the provider's static ``from_name`` and
  ``reply_to``.

We patch ``httpx.AsyncClient`` (REST tests) and ``smtplib.SMTP`` (SMTP
test) so neither transport touches the network — the tests assert on
what the dispatcher *would* have sent.

Validates: Requirements 4.1, 4.3, 21.4
"""

from __future__ import annotations

import uuid
from email import message_from_string
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    EmailMessage,
    dispatch_one_provider,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


#: Provider config used by every test in this module. Crucially, both
#: ``from_name`` and ``reply_to`` are set to values the override tests
#: explicitly do NOT want to see in the dispatched payload, so a missing
#: override path would surface as a real assertion failure.
PROVIDER_CONFIG = {
    "from_email": "noreply@platform.com",
    "from_name": "Platform Default",
    "reply_to": "default@platform.com",
}

#: Caller overrides that must win over the provider config.
OVERRIDE_SENDER_NAME = "Acme Workshop"
OVERRIDE_REPLY_TO = "reply@acme.co.nz"


def _make_message() -> EmailMessage:
    """Build a minimal EmailMessage with no attachments."""
    return EmailMessage(
        to_email="to@example.com",
        to_name="Recipient",
        subject="Override-precedence test",
        html_body="<p>Body</p>",
        text_body="Body",
        org_id=uuid.uuid4(),
    )


def _make_brevo_provider() -> MagicMock:
    """Mock an active Brevo REST provider row with our pinned config."""
    provider = MagicMock()
    provider.provider_key = "brevo"
    provider.credentials_set = True
    provider.credentials_encrypted = b"x"
    provider.config = dict(PROVIDER_CONFIG)
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


def _make_smtp_provider() -> MagicMock:
    """Mock an active custom-SMTP provider row with our pinned config."""
    provider = MagicMock()
    provider.provider_key = "custom_smtp"
    provider.credentials_set = True
    provider.credentials_encrypted = b"x"
    provider.config = dict(PROVIDER_CONFIG)
    provider.smtp_host = "smtp.example.com"
    provider.smtp_port = 587
    provider.smtp_encryption = "tls"
    return provider


# ---------------------------------------------------------------------------
# Fake transports
# ---------------------------------------------------------------------------


class _FakeSMTP:
    """In-process replacement for ``smtplib.SMTP``.

    Captures the most recent ``sendmail`` arguments on class-level
    attributes so the test can parse the raw MIME payload that *would*
    have been transmitted. Mirrors the helper in
    ``tests/test_email_sender_attachments.py``.
    """

    last_from: str | None = None
    last_to: list[str] | str | None = None
    last_message: str | None = None
    sendmail_call_count: int = 0

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
        type(self).sendmail_call_count += 1

    def quit(self):
        return None

    @classmethod
    def reset(cls) -> None:
        cls.last_from = None
        cls.last_to = None
        cls.last_message = None
        cls.sendmail_call_count = 0


class _FakeBrevoResp:
    """Minimal stand-in for the Brevo REST 201 response."""

    status_code = 201

    def json(self) -> dict:
        return {"messageId": "test-id"}

    @property
    def text(self) -> str:
        return ""

    @property
    def headers(self) -> dict:
        return {"content-type": "application/json"}


def _make_fake_client(captured: dict):
    """Build a fake ``httpx.AsyncClient`` class that records the POST kwargs.

    The test is shape-only (we don't care about the actual HTTP wire
    format) so any kwargs handed to the constructor are accepted and
    ignored.
    """

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self._args = args
            self._kwargs = kwargs

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *a) -> None:
            return None

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeBrevoResp()

    return FakeClient


# ---------------------------------------------------------------------------
# Test 1 — Brevo REST: caller overrides win
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brevo_rest_caller_overrides_win_over_provider_config() -> None:
    """When ``org_sender_name`` and ``org_reply_to`` are supplied, the
    Brevo REST payload reflects the caller's values, not the provider's
    static ``from_name`` / ``reply_to``.

    ``sender.email`` always tracks the provider's ``from_email`` because
    the precedence rule has no caller-side override for that leg.

    Validates: Requirements 4.1, 4.3, 21.4
    """
    provider = _make_brevo_provider()
    message = _make_message()
    db = AsyncMock()

    captured: dict = {}

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "x"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _make_fake_client(captured),
    ):
        attempt = await dispatch_one_provider(
            db,
            provider,
            message,
            org_sender_name=OVERRIDE_SENDER_NAME,
            org_reply_to=OVERRIDE_REPLY_TO,
        )

    # Sanity: dispatcher reached the FakeClient.
    assert attempt.success is True
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"

    payload = captured["json"]

    # `sender.name` comes from the caller override (NOT "Platform Default").
    assert payload["sender"]["name"] == OVERRIDE_SENDER_NAME, (
        f"Expected sender.name={OVERRIDE_SENDER_NAME!r} (caller override); "
        f"got {payload['sender'].get('name')!r}"
    )

    # `sender.email` always comes from the provider's `from_email` —
    # there is no caller-side override for the address itself.
    assert payload["sender"]["email"] == PROVIDER_CONFIG["from_email"]

    # `replyTo.email` comes from the caller override (NOT
    # "default@platform.com").
    assert payload["replyTo"]["email"] == OVERRIDE_REPLY_TO, (
        f"Expected replyTo.email={OVERRIDE_REPLY_TO!r} (caller override); "
        f"got {payload['replyTo'].get('email')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — SMTP: caller overrides win
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_caller_overrides_win_over_provider_config() -> None:
    """When ``org_sender_name`` and ``org_reply_to`` are supplied, the
    SMTP transport's MIME headers reflect the caller's values.

    The ``From`` header pairs the caller's display name with the
    provider's ``from_email``; the ``Reply-To`` header equals the
    caller's reply-to address.

    Validates: Requirements 4.1, 4.3, 21.4
    """
    provider = _make_smtp_provider()
    message = _make_message()
    db = AsyncMock()

    _FakeSMTP.reset()

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"username": "u", "password": "p"}',
    ), patch("smtplib.SMTP", _FakeSMTP):
        attempt = await dispatch_one_provider(
            db,
            provider,
            message,
            org_sender_name=OVERRIDE_SENDER_NAME,
            org_reply_to=OVERRIDE_REPLY_TO,
        )

    # Sanity: SMTP path was actually exercised.
    assert attempt.success is True
    assert _FakeSMTP.sendmail_call_count == 1
    raw_mime = _FakeSMTP.last_message
    assert isinstance(raw_mime, str) and raw_mime, "SMTP payload was not captured"

    msg = message_from_string(raw_mime)

    # The From header must carry the caller-supplied display name and
    # the provider's `from_email` address. We assert on substring
    # presence rather than the exact serialised form so we don't pin
    # the quoting style emitted by `_build_mime_message`.
    from_header = msg.get("From") or ""
    assert OVERRIDE_SENDER_NAME in from_header, (
        f"Expected From to contain {OVERRIDE_SENDER_NAME!r} (caller override); "
        f"got {from_header!r}"
    )
    assert "Platform Default" not in from_header, (
        f"From header still references provider's from_name; got {from_header!r}"
    )
    assert PROVIDER_CONFIG["from_email"] in from_header, (
        f"From header missing provider from_email "
        f"{PROVIDER_CONFIG['from_email']!r}; got {from_header!r}"
    )

    # Reply-To must be exactly the caller override (not the provider
    # config's reply_to).
    reply_to_header = msg.get("Reply-To") or ""
    assert reply_to_header == OVERRIDE_REPLY_TO, (
        f"Expected Reply-To={OVERRIDE_REPLY_TO!r} (caller override); "
        f"got {reply_to_header!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — provider config wins when caller supplies no overrides
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_config_wins_when_no_caller_overrides() -> None:
    """When the caller passes neither ``org_sender_name`` nor
    ``org_reply_to``, the dispatched payload reflects the provider's
    static ``from_name`` and ``reply_to``.

    This is the "no override" leg of the precedence rule: the override
    path is opt-in; absent overrides, provider config is honoured.

    Validates: Requirements 4.1, 4.3, 21.4
    """
    provider = _make_brevo_provider()
    message = _make_message()
    db = AsyncMock()

    captured: dict = {}

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "x"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        _make_fake_client(captured),
    ):
        attempt = await dispatch_one_provider(db, provider, message)

    assert attempt.success is True

    payload = captured["json"]

    # No override → provider config wins.
    assert payload["sender"]["name"] == PROVIDER_CONFIG["from_name"]
    assert payload["sender"]["email"] == PROVIDER_CONFIG["from_email"]
    assert payload["replyTo"]["email"] == PROVIDER_CONFIG["reply_to"]
