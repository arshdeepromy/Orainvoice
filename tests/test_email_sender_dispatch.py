"""Unit tests for ``dispatch_one_provider`` — credential dispatch matrix.

Covers task 1.10 of the email-provider-unification spec: for every
``provider_key`` × credentials shape, assert which underlying transport
``dispatch_one_provider`` chooses.

The matrix is the contract pinned by the design (Components §3,
"dispatch matrix"):

==================  ===========================================  ===================
provider_key        credentials                                  expected dispatcher
==================  ===========================================  ===================
brevo               {"api_key": "..."}                            REST   (Brevo)
brevo               {"api_key": "...", "smtp_login": "..."}       SMTP
sendgrid            {"api_key": "..."}                            REST   (SendGrid)
mailgun             {"username": "...", "password": "..."}        SMTP
ses                 {"username": "...", "password": "..."}        SMTP
gmail               {"username": "...", "password": "..."}        SMTP
outlook             {"username": "...", "password": "..."}        SMTP
custom_smtp         {"username": "...", "password": "..."}        SMTP
==================  ===========================================  ===================

The three private dispatchers (`_dispatch_brevo_rest`,
`_dispatch_sendgrid_rest`, `_dispatch_smtp`) are patched to
``AsyncMock``s that return a stub successful ``EmailAttempt`` so no
actual network or smtplib activity occurs. ``envelope_decrypt_str`` is
also patched to return the raw JSON credentials directly, avoiding the
need for the real envelope-encryption keys to be configured.

Validates: Requirements 3.1, 3.2, 3.3, 21.1
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at import time.
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.integrations.email_sender import (
    EmailAttempt,
    EmailMessage,
    dispatch_one_provider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(provider_key: str) -> MagicMock:
    """Mock an active ``EmailProvider`` row.

    The bytes blob in ``credentials_encrypted`` is opaque — we patch
    ``envelope_decrypt_str`` to return whatever JSON the test wants.
    """
    provider = MagicMock()
    provider.provider_key = provider_key
    provider.credentials_set = True
    provider.credentials_encrypted = b"x"
    provider.config = {"from_email": "from@example.com"}
    # SMTP-only fields used by the SMTP dispatcher; patched dispatchers
    # never touch them but real EmailProvider rows have these set.
    provider.smtp_host = None
    provider.smtp_port = None
    provider.smtp_encryption = "tls"
    return provider


def _make_message() -> EmailMessage:
    return EmailMessage(
        to_email="to@example.com",
        to_name="Recipient",
        subject="Subject line",
        html_body="<p>Hello</p>",
        text_body="Hello",
        org_id=uuid.uuid4(),
    )


def _stub_attempt(provider_key: str, transport: str) -> EmailAttempt:
    """Return a successful ``EmailAttempt`` for a stubbed dispatcher."""
    return EmailAttempt(
        provider_key=provider_key,
        transport=transport,
        success=True,
        error=None,
        failure_kind=None,
        duration_ms=1,
        message_id="<stub@example.com>",
    )


# ---------------------------------------------------------------------------
# Dispatch matrix
# ---------------------------------------------------------------------------

#: One entry per row of the design's dispatch matrix. ``expected``
#: identifies the dispatcher we expect ``dispatch_one_provider`` to call:
#: ``"brevo_rest"``, ``"sendgrid_rest"``, or ``"smtp"``.
DISPATCH_MATRIX: list[tuple[str, dict, str]] = [
    ("brevo", {"api_key": "xkeysib-abc"}, "brevo_rest"),
    (
        "brevo",
        {"api_key": "xkeysib-abc", "smtp_login": "user@smtp-relay.brevo.com"},
        "smtp",
    ),
    ("sendgrid", {"api_key": "SG.test"}, "sendgrid_rest"),
    ("mailgun", {"username": "postmaster@mg", "password": "pw"}, "smtp"),
    ("ses", {"username": "AKIA...", "password": "pw"}, "smtp"),
    ("gmail", {"username": "user@gmail.com", "password": "pw"}, "smtp"),
    ("outlook", {"username": "user@outlook.com", "password": "pw"}, "smtp"),
    ("custom_smtp", {"username": "user", "password": "pw"}, "smtp"),
]


@pytest.mark.parametrize(
    "provider_key,credentials,expected",
    DISPATCH_MATRIX,
    ids=[
        "brevo-api_key-only=>rest",
        "brevo-api_key+smtp_login=>smtp",
        "sendgrid-api_key=>rest",
        "mailgun-user+pass=>smtp",
        "ses-user+pass=>smtp",
        "gmail-user+pass=>smtp",
        "outlook-user+pass=>smtp",
        "custom_smtp-user+pass=>smtp",
    ],
)
@pytest.mark.asyncio
async def test_dispatch_matrix(
    provider_key: str,
    credentials: dict,
    expected: str,
) -> None:
    """``dispatch_one_provider`` selects the transport per the matrix.

    For each row, exactly one of the three private dispatchers must be
    awaited and the other two must remain untouched. The provider and
    message arguments forwarded to the chosen dispatcher must be the
    same objects we passed in.

    Validates: Requirements 3.1, 3.2, 3.3, 21.1
    """
    provider = _make_provider(provider_key)
    message = _make_message()
    db = AsyncMock()

    brevo_rest_stub = AsyncMock(
        return_value=_stub_attempt(provider_key, "rest_api")
    )
    sendgrid_rest_stub = AsyncMock(
        return_value=_stub_attempt(provider_key, "rest_api")
    )
    smtp_stub = AsyncMock(
        return_value=_stub_attempt(provider_key, "smtp")
    )

    with patch(
        "app.integrations.email_sender.envelope_decrypt_str",
        return_value=json.dumps(credentials),
    ), patch(
        "app.integrations.email_sender._dispatch_brevo_rest",
        new=brevo_rest_stub,
    ), patch(
        "app.integrations.email_sender._dispatch_sendgrid_rest",
        new=sendgrid_rest_stub,
    ), patch(
        "app.integrations.email_sender._dispatch_smtp",
        new=smtp_stub,
    ):
        attempt = await dispatch_one_provider(db, provider, message)

    # The chosen dispatcher's stub return value must be passed straight
    # through (no rewrapping) so callers see the real EmailAttempt.
    assert attempt.success is True
    assert attempt.provider_key == provider_key

    if expected == "brevo_rest":
        brevo_rest_stub.assert_awaited_once()
        sendgrid_rest_stub.assert_not_awaited()
        smtp_stub.assert_not_awaited()
        chosen = brevo_rest_stub
    elif expected == "sendgrid_rest":
        sendgrid_rest_stub.assert_awaited_once()
        brevo_rest_stub.assert_not_awaited()
        smtp_stub.assert_not_awaited()
        chosen = sendgrid_rest_stub
    else:  # smtp
        smtp_stub.assert_awaited_once()
        brevo_rest_stub.assert_not_awaited()
        sendgrid_rest_stub.assert_not_awaited()
        chosen = smtp_stub

    # Confirm the call shape: positional args are (provider, message),
    # then keyword args carry the resolved sender identity.
    call_args, call_kwargs = chosen.await_args
    assert call_args[0] is provider
    assert call_args[1] is message
    assert call_kwargs["from_email"] == "from@example.com"
    # ``timeout_seconds`` is forwarded from the public helper.
    assert "timeout_seconds" in call_kwargs
