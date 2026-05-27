"""Unit tests for the four error-classification helpers in
``app/integrations/email_sender.py``.

Covers task 1.14 of the email-provider-unification spec: drive every
``FailureKind`` across both REST transports (Brevo + SendGrid) and the
SMTP transport, exercising the classifier helpers directly rather than
through the dispatchers. Going straight at the helpers is faster and
keeps the scope narrow — task 1.10 (`tests/test_email_sender_dispatch.py`)
and 1.11 (`tests/test_email_sender_failover.py`) already pin the
integration-level behaviour.

The four classifiers under test:

- ``_classify_brevo_rest_error(response, exc)``
- ``_classify_sendgrid_rest_error(response, exc)``
- ``_classify_smtp_error(exc)``
- ``_classify_network_exc(exc)`` (also exercised via the REST classifiers'
  ``exc=...`` path, which delegates to it)

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 21.2
"""

from __future__ import annotations

import json
import smtplib
from unittest.mock import MagicMock

import httpx
import pytest

# Import models so SQLAlchemy can resolve all relationships at import
# time. The classifiers themselves don't touch the ORM, but importing
# ``email_sender`` pulls in ``app.modules.admin.models.EmailProvider``,
# which transitively expects the rest of the model graph to be loadable.
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.integrations.email_sender import (
    FailureKind,
    _classify_brevo_rest_error,
    _classify_network_exc,
    _classify_sendgrid_rest_error,
    _classify_smtp_error,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_resp(
    status: int,
    *,
    body: dict | list | None = None,
    content_type: str | None = "application/json",
) -> MagicMock:
    """Build a mock ``httpx.Response`` shaped for the classifier code paths.

    The classifiers only read ``status_code``, ``headers`` (for
    content-type sniffing on the Brevo path), ``.json()``, and ``.text``.
    Building a real ``httpx.Response`` is possible but uses more
    machinery than the classifiers actually exercise; a ``MagicMock``
    keeps the test fixture small and explicit.

    Pass ``body=None`` together with ``content_type=None`` (or any
    non-JSON content-type) to simulate a non-JSON response body — the
    Brevo classifier short-circuits before ``.json()`` in that case, and
    the SendGrid classifier will see ``response.json()`` raise.
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.headers = {"content-type": content_type} if content_type else {}
    if body is not None:
        resp.json.return_value = body
        resp.text = json.dumps(body)
    else:
        resp.json.side_effect = ValueError("not JSON")
        resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# Brevo REST classifier
# ---------------------------------------------------------------------------


BREVO_RESPONSE_CASES: list[tuple[int, dict | None, str | None, FailureKind]] = [
    # 400 invalid_parameter recipient → HARD_RECIPIENT (the headline
    # Brevo failure mode for malformed recipient addresses).
    (
        400,
        {"code": "invalid_parameter", "message": "Email address is invalid"},
        "application/json",
        FailureKind.HARD_RECIPIENT,
    ),
    # 400 with invalid_parameter but no "email" in message — could be
    # any other parameter validation failure, treat as soft so the next
    # provider gets a shot.
    (
        400,
        {"code": "invalid_parameter", "message": "subject is required"},
        "application/json",
        FailureKind.SOFT_PROVIDER,
    ),
    # 400 with no body / non-JSON content-type → SOFT_PROVIDER. The
    # classifier never reaches .json() when content-type isn't JSON.
    (400, None, "text/html", FailureKind.SOFT_PROVIDER),
    # Auth failures: stale or revoked API key → try the next provider.
    (401, None, "application/json", FailureKind.SOFT_AUTH),
    (403, None, "application/json", FailureKind.SOFT_AUTH),
    # Payload too large: no provider will accept it; short-circuit.
    (413, None, "application/json", FailureKind.HARD_PAYLOAD),
    # Rate limiting and server-side errors are soft so the chain
    # continues to a hopefully-healthier provider.
    (429, None, "application/json", FailureKind.SOFT_PROVIDER),
    (500, None, "application/json", FailureKind.SOFT_PROVIDER),
    (502, None, "application/json", FailureKind.SOFT_PROVIDER),
]


@pytest.mark.parametrize(
    "status,body,content_type,expected",
    BREVO_RESPONSE_CASES,
    ids=[
        "400-invalid_parameter-email=>HARD_RECIPIENT",
        "400-invalid_parameter-non-email=>SOFT_PROVIDER",
        "400-non-json-body=>SOFT_PROVIDER",
        "401=>SOFT_AUTH",
        "403=>SOFT_AUTH",
        "413=>HARD_PAYLOAD",
        "429=>SOFT_PROVIDER",
        "500=>SOFT_PROVIDER",
        "502=>SOFT_PROVIDER",
    ],
)
def test_classify_brevo_rest_response(
    status: int,
    body: dict | None,
    content_type: str | None,
    expected: FailureKind,
) -> None:
    """``_classify_brevo_rest_error`` maps each Brevo HTTP status correctly.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.6, 21.2
    """
    resp = _make_resp(status, body=body, content_type=content_type)
    assert _classify_brevo_rest_error(resp, None) is expected


BREVO_EXCEPTION_CASES: list[tuple[Exception, FailureKind]] = [
    # Timeouts and connection errors are always soft on the network
    # classifier — we want the loop to fail over rather than give up.
    (httpx.TimeoutException("read timed out"), FailureKind.SOFT_PROVIDER),
    (httpx.ConnectError("connection refused"), FailureKind.SOFT_PROVIDER),
    (httpx.ReadTimeout("read timeout"), FailureKind.SOFT_PROVIDER),
    (httpx.RemoteProtocolError("server closed connection"), FailureKind.SOFT_PROVIDER),
]


@pytest.mark.parametrize(
    "exc,expected",
    BREVO_EXCEPTION_CASES,
    ids=[
        "TimeoutException=>SOFT_PROVIDER",
        "ConnectError=>SOFT_PROVIDER",
        "ReadTimeout=>SOFT_PROVIDER",
        "RemoteProtocolError=>SOFT_PROVIDER",
    ],
)
def test_classify_brevo_rest_exception(
    exc: Exception, expected: FailureKind
) -> None:
    """Network-layer exceptions on the Brevo path delegate to
    ``_classify_network_exc`` and always come back ``SOFT_PROVIDER``.

    Validates: Requirements 5.6, 21.2
    """
    assert _classify_brevo_rest_error(None, exc) is expected


def test_classify_brevo_rest_response_none_returns_soft_provider() -> None:
    """Defensive default: no response and no exception → ``SOFT_PROVIDER``.

    Validates: Requirements 5.6, 21.2
    """
    assert (
        _classify_brevo_rest_error(None, None) is FailureKind.SOFT_PROVIDER
    )


# ---------------------------------------------------------------------------
# SendGrid REST classifier
# ---------------------------------------------------------------------------


SENDGRID_RESPONSE_CASES: list[tuple[int, dict | None, FailureKind]] = [
    # 400 with a recipient field path → HARD_RECIPIENT. SendGrid uses
    # dotted paths like 'personalizations.0.to.0.email' for nested
    # recipient validation errors.
    (
        400,
        {
            "errors": [
                {
                    "message": "Invalid email",
                    "field": "personalizations.0.to.0.email",
                }
            ]
        },
        FailureKind.HARD_RECIPIENT,
    ),
    # 400 with a sender field path → HARD_RECIPIENT (the classifier
    # treats malformed senders the same way as malformed recipients —
    # no provider will accept the message until the config is fixed).
    (
        400,
        {"errors": [{"message": "Invalid sender", "field": "from.email"}]},
        FailureKind.HARD_RECIPIENT,
    ),
    # 400 with a non-recipient/sender field — e.g. subject validation —
    # is soft so the next provider gets a chance.
    (
        400,
        {"errors": [{"message": "subject is required", "field": "subject"}]},
        FailureKind.SOFT_PROVIDER,
    ),
    # 400 whose body parses as a dict but has no actionable signal at
    # all: still soft so the chain continues.
    (400, {"errors": []}, FailureKind.SOFT_PROVIDER),
    # Auth: revoked or stale API key → try next provider.
    (401, None, FailureKind.SOFT_AUTH),
    (403, None, FailureKind.SOFT_AUTH),
    # Payload too large: short-circuit, no provider will accept it.
    (413, None, FailureKind.HARD_PAYLOAD),
    # 5xx: SendGrid having a bad day → fail over.
    (500, None, FailureKind.SOFT_PROVIDER),
    (503, None, FailureKind.SOFT_PROVIDER),
]


@pytest.mark.parametrize(
    "status,body,expected",
    SENDGRID_RESPONSE_CASES,
    ids=[
        "400-recipient-field=>HARD_RECIPIENT",
        "400-sender-field=>HARD_RECIPIENT",
        "400-other-field=>SOFT_PROVIDER",
        "400-empty-errors=>SOFT_PROVIDER",
        "401=>SOFT_AUTH",
        "403=>SOFT_AUTH",
        "413=>HARD_PAYLOAD",
        "500=>SOFT_PROVIDER",
        "503=>SOFT_PROVIDER",
    ],
)
def test_classify_sendgrid_rest_response(
    status: int,
    body: dict | None,
    expected: FailureKind,
) -> None:
    """``_classify_sendgrid_rest_error`` maps each SendGrid status correctly.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.6, 21.2
    """
    resp = _make_resp(status, body=body)
    assert _classify_sendgrid_rest_error(resp, None) is expected


SENDGRID_EXCEPTION_CASES: list[tuple[Exception, FailureKind]] = [
    (httpx.TimeoutException("read timed out"), FailureKind.SOFT_PROVIDER),
    (httpx.ConnectError("dns failure"), FailureKind.SOFT_PROVIDER),
]


@pytest.mark.parametrize(
    "exc,expected",
    SENDGRID_EXCEPTION_CASES,
    ids=[
        "TimeoutException=>SOFT_PROVIDER",
        "ConnectError=>SOFT_PROVIDER",
    ],
)
def test_classify_sendgrid_rest_exception(
    exc: Exception, expected: FailureKind
) -> None:
    """Network-layer exceptions on the SendGrid path → ``SOFT_PROVIDER``.

    Validates: Requirements 5.6, 21.2
    """
    assert _classify_sendgrid_rest_error(None, exc) is expected


# ---------------------------------------------------------------------------
# SMTP classifier
# ---------------------------------------------------------------------------


def _make_smtp_recipients_refused() -> smtplib.SMTPRecipientsRefused:
    """Construct an ``SMTPRecipientsRefused`` with a non-empty recipients map.

    smtplib raises this when *every* RCPT TO command was rejected, with
    a ``recipients`` dict mapping each rejected address to its error.
    The classifier doesn't introspect the dict — any instance triggers
    HARD_RECIPIENT — but a realistic value documents the failure mode.
    """
    return smtplib.SMTPRecipientsRefused(
        {"recipient@example.com": (550, b"5.1.1 No such user")}
    )


SMTP_EXCEPTION_CASES: list[tuple[Exception, FailureKind]] = [
    # SMTPRecipientsRefused: the entire RCPT TO list was rejected — a
    # provider switch won't help, short-circuit.
    (_make_smtp_recipients_refused(), FailureKind.HARD_RECIPIENT),
    # SMTPDataError 552: payload too large (RFC 5321 enhanced status).
    (smtplib.SMTPDataError(552, b"message size exceeds limit"),
     FailureKind.HARD_PAYLOAD),
    # SMTPDataError 4xx is transient — try next provider.
    (smtplib.SMTPDataError(450, b"mailbox temporarily unavailable"),
     FailureKind.SOFT_PROVIDER),
    # SMTPAuthenticationError: this provider's credentials are bad,
    # next provider may have valid ones.
    (smtplib.SMTPAuthenticationError(535, b"authentication failed"),
     FailureKind.SOFT_AUTH),
    # SMTPSenderRefused 530 ("auth required") → SOFT_AUTH.
    (smtplib.SMTPSenderRefused(530, b"authentication required", "from@x"),
     FailureKind.SOFT_AUTH),
    # SMTPSenderRefused 5xx (non-552) → HARD_RECIPIENT (the From
    # address itself was rejected — a provider switch won't fix it).
    (smtplib.SMTPSenderRefused(550, b"sender address rejected", "from@x"),
     FailureKind.HARD_RECIPIENT),
    # SMTPSenderRefused 552 → HARD_PAYLOAD.
    (smtplib.SMTPSenderRefused(552, b"message too large", "from@x"),
     FailureKind.HARD_PAYLOAD),
    # Connection-level smtplib errors → SOFT_PROVIDER.
    (smtplib.SMTPConnectError(421, b"service unavailable"),
     FailureKind.SOFT_PROVIDER),
    (smtplib.SMTPServerDisconnected("connection closed"),
     FailureKind.SOFT_PROVIDER),
    # Socket-level exceptions (socket.timeout aliases TimeoutError on
    # 3.10+) → SOFT_PROVIDER.
    (TimeoutError("timed out"), FailureKind.SOFT_PROVIDER),
    (ConnectionError("connection refused"), FailureKind.SOFT_PROVIDER),
    # Default fallback: an unrecognised exception is conservatively
    # soft — the next provider may still succeed.
    (Exception("something else"), FailureKind.SOFT_PROVIDER),
]


@pytest.mark.parametrize(
    "exc,expected",
    SMTP_EXCEPTION_CASES,
    ids=[
        "SMTPRecipientsRefused=>HARD_RECIPIENT",
        "SMTPDataError-552=>HARD_PAYLOAD",
        "SMTPDataError-450=>SOFT_PROVIDER",
        "SMTPAuthenticationError=>SOFT_AUTH",
        "SMTPSenderRefused-530=>SOFT_AUTH",
        "SMTPSenderRefused-550=>HARD_RECIPIENT",
        "SMTPSenderRefused-552=>HARD_PAYLOAD",
        "SMTPConnectError=>SOFT_PROVIDER",
        "SMTPServerDisconnected=>SOFT_PROVIDER",
        "TimeoutError=>SOFT_PROVIDER",
        "ConnectionError=>SOFT_PROVIDER",
        "bare-Exception=>SOFT_PROVIDER",
    ],
)
def test_classify_smtp_error(exc: Exception, expected: FailureKind) -> None:
    """``_classify_smtp_error`` maps every documented smtplib failure
    (and the network-level exceptions raised by the underlying socket)
    to the right ``FailureKind``.

    Validates: Requirements 5.1, 5.2, 5.3, 5.5, 5.6, 21.2
    """
    assert _classify_smtp_error(exc) is expected


# ---------------------------------------------------------------------------
# Network exception classifier (also reachable via REST classifiers above)
# ---------------------------------------------------------------------------


NETWORK_EXCEPTION_CASES: list[tuple[Exception, FailureKind]] = [
    (httpx.TimeoutException("timed out"), FailureKind.SOFT_PROVIDER),
    (httpx.ReadTimeout("read"), FailureKind.SOFT_PROVIDER),
    (httpx.ConnectError("refused"), FailureKind.SOFT_PROVIDER),
    (httpx.NetworkError("network down"), FailureKind.SOFT_PROVIDER),
    (httpx.RemoteProtocolError("eof"), FailureKind.SOFT_PROVIDER),
    (TimeoutError("socket timeout"), FailureKind.SOFT_PROVIDER),
    (ConnectionError("conn refused"), FailureKind.SOFT_PROVIDER),
    # The fallback case: some other transport-level error we haven't
    # explicitly named. Still soft so the chain continues.
    (RuntimeError("unexpected transport error"), FailureKind.SOFT_PROVIDER),
]


@pytest.mark.parametrize(
    "exc,expected",
    NETWORK_EXCEPTION_CASES,
    ids=[
        "httpx-TimeoutException",
        "httpx-ReadTimeout",
        "httpx-ConnectError",
        "httpx-NetworkError",
        "httpx-RemoteProtocolError",
        "TimeoutError",
        "ConnectionError",
        "fallback-RuntimeError",
    ],
)
def test_classify_network_exc(exc: Exception, expected: FailureKind) -> None:
    """Every transport-level exception classifies to ``SOFT_PROVIDER``.

    The failover loop relies on this universal soft classification:
    if the network is the problem, the next provider's network path
    might still be healthy.

    Validates: Requirements 5.6, 21.2
    """
    assert _classify_network_exc(exc) is expected
