"""Unit tests for ``send_email`` attachment plumbing — REST + SMTP.

Covers task 1.12 of the email-provider-unification spec: a single
:class:`~app.integrations.email_sender.EmailMessage` carrying two
attachments with mixed MIME types (a PDF and a PNG image) must round-
trip through both transport paths intact:

- **Brevo REST** — ``_dispatch_brevo_rest`` serialises each attachment
  into the ``attachment`` array on the outbound JSON payload, with the
  bytes base64-encoded under ``content`` and the original filename and
  content-type preserved.
- **SMTP** — ``_dispatch_smtp`` builds a ``multipart/mixed`` MIME tree
  with the body inside an inner ``multipart/alternative`` part and one
  attachment part per file. The PDF stays ``application/pdf`` (the
  default :class:`email.mime.application.MIMEApplication` subtype rewrite),
  and the PNG part has its ``Content-Type`` rewritten by
  ``_build_mime_message`` to the original ``image/png``.

We patch ``httpx.AsyncClient`` (REST test) and ``smtplib.SMTP`` (SMTP
test) so neither transport touches the network — the tests assert on
what the dispatcher *would* have sent.

Validates: Requirements 3.7, 21.1
"""

from __future__ import annotations

import base64
import uuid
from email import message_from_string
from unittest.mock import MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    EmailAttachment,
    EmailMessage,
    _dispatch_brevo_rest,
    _dispatch_smtp,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


PDF_BYTES = b"PDF-PAYLOAD-BYTES"
PNG_BYTES = b"\x89PNG\r\n\x1a\n-png-payload-bytes-"


def _make_message() -> EmailMessage:
    """Build an EmailMessage carrying one PDF + one PNG attachment."""
    return EmailMessage(
        to_email="to@example.com",
        to_name="Recipient",
        subject="Subject with attachments",
        html_body="<p>See attached.</p>",
        text_body="See attached.",
        org_id=uuid.uuid4(),
        attachments=[
            EmailAttachment(
                filename="invoice.pdf",
                content=PDF_BYTES,
                mime_type="application/pdf",
            ),
            EmailAttachment(
                filename="logo.png",
                content=PNG_BYTES,
                mime_type="image/png",
            ),
        ],
    )


def _make_brevo_provider() -> MagicMock:
    """Mock an active Brevo REST provider row."""
    provider = MagicMock()
    provider.provider_key = "brevo"
    provider.credentials_set = True
    provider.credentials_encrypted = b"x"
    provider.config = {"from_email": "from@example.com"}
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


def _make_smtp_provider() -> MagicMock:
    """Mock an active custom-SMTP provider row."""
    provider = MagicMock()
    provider.provider_key = "custom_smtp"
    provider.credentials_set = True
    provider.credentials_encrypted = b"x"
    provider.config = {"from_email": "from@example.com"}
    provider.smtp_host = "smtp.example.com"
    provider.smtp_port = 587
    provider.smtp_encryption = "tls"
    return provider


# ---------------------------------------------------------------------------
# Fake transports
# ---------------------------------------------------------------------------


class _FakeSMTP:
    """In-process replacement for ``smtplib.SMTP``.

    Mirrors the pattern from ``tests/test_password_reset_email.py`` —
    captures the most recent ``sendmail`` arguments on class-level
    attributes so the test can parse the raw MIME payload that *would*
    have been transmitted.
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


# ---------------------------------------------------------------------------
# Test 1 — Brevo REST attachments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brevo_rest_serialises_both_attachments_to_payload() -> None:
    """``_dispatch_brevo_rest`` puts both attachments on the outbound JSON.

    For a message carrying a PDF and a PNG, the captured payload's
    ``attachment`` array must contain exactly two entries — one per
    attachment, in the order they were declared on the message — each
    with ``name``, base64-encoded ``content``, and ``contentType`` matching
    the original bytes and metadata.

    Validates: Requirements 3.7, 21.1
    """
    provider = _make_brevo_provider()
    message = _make_message()

    captured: dict = {}

    class FakeResp:
        status_code = 201

        def json(self) -> dict:
            return {"messageId": "test-id"}

        @property
        def text(self) -> str:
            return ""

        @property
        def headers(self) -> dict:
            return {"content-type": "application/json"}

    class FakeClient:
        """Replacement for ``httpx.AsyncClient`` — captures POST kwargs."""

        def __init__(self, *args, **kwargs) -> None:
            # ``timeout=...`` and any other kwargs are accepted but
            # ignored; the test isolates payload shape from transport.
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
            return FakeResp()

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"api_key": "x"}',
    ), patch(
        "app.integrations.email_sender.httpx.AsyncClient",
        FakeClient,
    ):
        attempt = await _dispatch_brevo_rest(
            provider,
            message,
            from_name="Test",
            from_email="from@example.com",
            reply_to=None,
            timeout_seconds=15,
        )

    # Sanity: the dispatcher reported success and reached the FakeClient.
    assert attempt.success is True
    assert attempt.message_id == "test-id"
    assert captured["url"] == "https://api.brevo.com/v3/smtp/email"

    # The Brevo payload spells the attachment array as ``attachment``
    # (singular) — see ``_dispatch_brevo_rest``.
    payload = captured["json"]
    assert "attachment" in payload, (
        "Expected Brevo payload to include an 'attachment' array; "
        f"got keys={list(payload)}"
    )
    attachments = payload["attachment"]
    assert isinstance(attachments, list)
    assert len(attachments) == 2

    # First entry — PDF.
    pdf_entry = attachments[0]
    assert pdf_entry["name"] == "invoice.pdf"
    assert pdf_entry["contentType"] == "application/pdf"
    assert base64.b64decode(pdf_entry["content"]) == PDF_BYTES

    # Second entry — PNG.
    png_entry = attachments[1]
    assert png_entry["name"] == "logo.png"
    assert png_entry["contentType"] == "image/png"
    assert base64.b64decode(png_entry["content"]) == PNG_BYTES


# ---------------------------------------------------------------------------
# Test 2 — SMTP attachments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_dispatch_emits_multipart_mixed_with_both_attachments() -> None:
    """``_dispatch_smtp`` builds a multipart/mixed envelope with both files.

    Asserts the structural contract pinned by ``_build_mime_message``:

    - The outer container is ``multipart/mixed``.
    - Inside, exactly one ``multipart/alternative`` part holds the
      text + HTML bodies.
    - Two attachment parts sit alongside the body part; both carry
      ``Content-Disposition: attachment`` with the original filenames,
      and decode to the original bytes.
    - The PDF part keeps ``Content-Type: application/pdf`` (the
      :class:`MIMEApplication` default for ``application/<subtype>``);
      the PNG part's Content-Type is rewritten to ``image/png`` by the
      MIME builder's non-application branch.

    Validates: Requirements 3.7, 21.1
    """
    provider = _make_smtp_provider()
    message = _make_message()

    _FakeSMTP.reset()

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value='{"username": "u", "password": "p"}',
    ), patch("smtplib.SMTP", _FakeSMTP):
        attempt = await _dispatch_smtp(
            provider,
            message,
            from_name="Test",
            from_email="from@example.com",
            reply_to=None,
            timeout_seconds=15,
        )

    # Sanity: the dispatcher reported success and reached the FakeSMTP.
    assert attempt.success is True
    assert _FakeSMTP.sendmail_call_count == 1
    raw_mime = _FakeSMTP.last_message
    assert isinstance(raw_mime, str) and raw_mime, "SMTP payload was not captured"

    msg = message_from_string(raw_mime)

    # Outer container is multipart/mixed because attachments are present.
    assert msg.get_content_type() == "multipart/mixed", (
        f"Expected multipart/mixed outer, got {msg.get_content_type()}"
    )

    # Walk the parts: one multipart/alternative (the body) plus two
    # attachment parts.
    direct_children = list(msg.iter_parts()) if hasattr(msg, "iter_parts") else [
        p for p in msg.get_payload() if hasattr(p, "get_content_type")
    ]
    body_parts = [
        p for p in direct_children if p.get_content_type() == "multipart/alternative"
    ]
    attachment_parts = [
        p
        for p in direct_children
        if (p.get("Content-Disposition") or "").lower().startswith("attachment")
    ]
    assert len(body_parts) == 1, (
        f"Expected exactly one multipart/alternative body part, got {len(body_parts)}"
    )
    assert len(attachment_parts) == 2, (
        "Expected exactly two attachment parts; got "
        f"{len(attachment_parts)} (children content-types: "
        f"{[p.get_content_type() for p in direct_children]})"
    )

    # Index attachments by filename so order doesn't matter.
    by_name = {p.get_filename(): p for p in attachment_parts}
    assert set(by_name) == {"invoice.pdf", "logo.png"}, (
        f"Filenames mismatch: {set(by_name)}"
    )

    # PDF part — default MIMEApplication subtype rewrite keeps it as
    # application/pdf.
    pdf_part = by_name["invoice.pdf"]
    assert pdf_part.get_content_type() == "application/pdf", (
        f"Expected application/pdf, got {pdf_part.get_content_type()}"
    )
    pdf_payload = pdf_part.get_payload(decode=True)
    assert pdf_payload == PDF_BYTES

    # PNG part — _build_mime_message rewrites Content-Type to the
    # caller-supplied image/png because the maintype is not 'application'.
    png_part = by_name["logo.png"]
    assert png_part.get_content_type() == "image/png", (
        f"Expected image/png, got {png_part.get_content_type()}"
    )
    png_payload = png_part.get_payload(decode=True)
    assert png_payload == PNG_BYTES
