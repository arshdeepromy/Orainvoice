"""Unified email sender — single source of truth for outbound email.

This module is the destination for the email-provider-unification work.
Phase 0 laid down the public dataclasses, the failure classification
enum, and module-level constants. Phase 1 (current state) fills in
``send_email`` itself: REST + SMTP transports, the failover loop with
per-attempt and total time budgets, error classification, the public
``dispatch_one_provider`` helper used by the per-provider admin Test
endpoint, and the bounce-blocklist pre-check call site. The
``bounced_addresses`` table that backs that pre-check is created in
Phase 8c (task 9.1) — until then ``_check_bounce_blocklist`` is a stub
that always returns "not blocked". The two no-providers /
all-auth-failed in-app alerts are also stubbed (task 1.9) and get their
real ``create_in_app_notification`` calls in Phase 4.

Public API (stable from Phase 0 onwards):

- ``EmailMessage`` / ``EmailAttachment`` — the message value objects.
- ``EmailAttempt`` / ``SendResult`` — the per-provider attempt record
  and the aggregate result returned by ``send_email``.
- ``FailureKind`` — classification of a failed attempt; controls whether
  the failover loop short-circuits or continues to the next provider.
- ``EMAIL_SIZE_LIMIT`` / ``EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS`` /
  ``EMAIL_TOTAL_BUDGET_SECONDS`` — module-level constants.

The full design lives at ``.kiro/specs/email-provider-unification/design.md``.

Requirements: 1.1, 1.2, 1.3, 1.5, 2.1-2.7, 5.7-5.9
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import smtplib
import time
import uuid
from dataclasses import dataclass, field
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from enum import Enum

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_decrypt_str
from app.modules.admin.models import EmailProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants (design Components §2)
# ---------------------------------------------------------------------------

#: Maximum total payload size (HTML + text + all attachments) accepted
#: by ``send_email``. Matches the existing invoice email path.
EMAIL_SIZE_LIMIT: int = 25 * 1024 * 1024  # 25 MB

#: Per-provider attempt timeout. Applies to both REST and SMTP transports.
EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS: int = 15

#: Total time budget for one ``send_email`` call across all provider
#: attempts. When exceeded, remaining providers are skipped and the last
#: attempt is marked ``FailureKind.BUDGET_EXCEEDED``.
EMAIL_TOTAL_BUDGET_SECONDS: int = 45

#: Redis dedup TTL for the "no active email providers configured" alert
#: (``_maybe_fire_no_providers_alert``). One hour: a noisy enough signal
#: that admins notice promptly, but quiet enough that a flood of sends
#: while the platform is fully misconfigured doesn't spam the inbox.
NO_PROVIDERS_DEDUP_SECONDS: int = 60 * 60  # 1 hour

#: Redis dedup TTL for the "every provider returned SOFT_AUTH" alert
#: (``_maybe_fire_all_auth_fail_alert``). One day: invalid credentials
#: are usually a single rotation event, so once-per-day is plenty.
ALL_AUTH_FAIL_DEDUP_SECONDS: int = 24 * 60 * 60  # 1 day


#: Default host / port / encryption tuples used when an ``EmailProvider``
#: row has no explicit ``smtp_host`` configured. Mirrors the fallback
#: table in ``app/modules/email_providers/service.py`` (the per-provider
#: admin Test endpoint). Keys are ``EmailProvider.provider_key`` values.
_DEFAULT_SMTP_HOSTS: dict[str, tuple[str, int, str]] = {
    "gmail": ("smtp.gmail.com", 587, "tls"),
    "outlook": ("smtp.office365.com", 587, "tls"),
    "brevo": ("smtp-relay.brevo.com", 587, "tls"),
    "sendgrid": ("smtp.sendgrid.net", 587, "tls"),
    "mailgun": ("smtp.mailgun.org", 587, "tls"),
    "ses": ("email-smtp.us-east-1.amazonaws.com", 587, "tls"),
}


# ---------------------------------------------------------------------------
# Dataclasses (design Components §1)
# ---------------------------------------------------------------------------


@dataclass
class EmailAttachment:
    """A single file attachment on an outbound email.

    Field shape mirrors ``app.integrations.brevo.EmailAttachment`` so
    Phase 0.2 can alias the legacy class to this one without breaking
    existing imports or kwargs.
    """

    filename: str
    content: bytes
    mime_type: str = "application/pdf"


@dataclass
class EmailMessage:
    """A single outbound email.

    Field shape mirrors ``app.integrations.brevo.EmailMessage`` plus the
    new ``org_id`` field added in Phase 0 for bounce-blocklist scoping
    (used by ``send_email`` in Phase 1; see design Components §7).
    ``org_id`` is ``None`` for public/external sends (e.g. landing-page
    demo requests) where there is no organisation context.
    """

    to_email: str
    to_name: str = ""
    subject: str = ""
    html_body: str = ""
    text_body: str = ""
    from_name: str | None = None  # override provider-level from_name
    reply_to: str | None = None  # override provider-level reply-to
    attachments: list[EmailAttachment] = field(default_factory=list)
    org_id: uuid.UUID | None = None


class FailureKind(str, Enum):
    """Classification of a failed provider attempt.

    The classification controls whether the failover loop short-circuits
    or continues to the next provider:

    - ``HARD_RECIPIENT`` / ``HARD_PAYLOAD`` — short-circuit; trying
      another provider would not help.
    - ``SOFT_AUTH`` / ``SOFT_PROVIDER`` — continue to the next provider.
    - ``BUDGET_EXCEEDED`` — total time budget hit; abort the chain.
    """

    HARD_RECIPIENT = "hard_recipient"
    HARD_PAYLOAD = "hard_payload"
    SOFT_AUTH = "soft_auth"
    SOFT_PROVIDER = "soft_provider"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class EmailAttempt:
    """Record of a single provider dispatch attempt.

    One ``EmailAttempt`` is appended to ``SendResult.attempts`` per
    provider tried, in priority order.
    """

    provider_key: str
    transport: str  # 'rest_api' | 'smtp' | 'precheck'
    success: bool
    error: str | None = None
    failure_kind: FailureKind | None = None
    duration_ms: int = 0
    message_id: str | None = None


@dataclass
class SendResult:
    """Aggregate result of a ``send_email`` call.

    ``success`` is ``True`` when any provider attempt succeeded; in that
    case ``provider_key``, ``transport``, and ``message_id`` reflect the
    winning attempt. When ``success`` is ``False``, ``error`` carries the
    last attempt's error message (or a synthetic message such as
    ``"No active email providers configured"``) and ``attempts`` holds
    the full per-provider history.
    """

    success: bool
    provider_key: str | None = None
    transport: str | None = None
    message_id: str | None = None
    error: str | None = None
    attempts: list[EmailAttempt] = field(default_factory=list)

    @property
    def provider(self) -> str:
        """Backwards-compatible alias for ``provider_key``.

        Several existing tests (e.g. ``tests/test_security_focused.py``)
        and the legacy ``send_org_email`` shim assert on ``result.provider``
        as a plain string. Returning ``""`` instead of ``None`` preserves
        the old contract where ``provider`` was a non-nullable ``str``.
        """
        return self.provider_key or ""


# ---------------------------------------------------------------------------
# Private dispatch functions (design Components §4)
# ---------------------------------------------------------------------------


def _resolve_sender_identity(
    provider: EmailProvider,
    *,
    org_sender_name: str | None,
    org_reply_to: str | None,
) -> tuple[str, str, str | None] | None:
    """Resolve the From identity for an outbound email (design Components §6).

    Returns ``(from_name, from_email, reply_to)`` when the provider has a
    usable ``from_email`` configured, or ``None`` to signal the caller
    should skip this provider with ``failure_kind=SOFT_PROVIDER`` and
    ``error="missing from_email"``.

    Precedence:

    - ``from_name``  = ``org_sender_name`` OR ``provider.config['from_name']`` OR ``""``
    - ``from_email`` = ``provider.config['from_email']``  (required; None ⇒ skip)
    - ``reply_to``   = ``org_reply_to`` OR ``provider.config['reply_to']`` OR ``None``

    The caller-provided ``org_sender_name`` and ``org_reply_to`` always win
    over the provider's static config so per-org friendly names (e.g.
    ``notify_customer`` passing ``org.name``) and per-org reply-to addresses
    are honoured regardless of which provider in the failover chain
    ultimately delivers the message.
    """
    config = provider.config or {}
    from_email = config.get("from_email")
    if not from_email:
        return None
    from_name = org_sender_name or config.get("from_name") or ""
    reply_to = org_reply_to or config.get("reply_to")
    return from_name, from_email, reply_to


# ---------------------------------------------------------------------------
# Error classification helpers (design Components §5)
# ---------------------------------------------------------------------------


def _classify_network_exc(exc: Exception) -> FailureKind:
    """Classify a transport-level exception (httpx or socket-level).

    Network-layer failures are always treated as ``SOFT_PROVIDER`` so the
    failover loop can try the next provider. There is no observable
    difference between a connect-timeout and a read-timeout for failover
    purposes — both mean "this provider isn't responding, try someone
    else". Includes ``httpx`` timeout/transport errors as well as the
    built-in ``TimeoutError`` / ``ConnectionError`` (note: ``socket.timeout``
    is an alias for ``TimeoutError`` on Python 3.10+).
    """
    if isinstance(exc, httpx.TimeoutException):
        return FailureKind.SOFT_PROVIDER
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            httpx.TransportError,
        ),
    ):
        return FailureKind.SOFT_PROVIDER
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return FailureKind.SOFT_PROVIDER
    return FailureKind.SOFT_PROVIDER


def _classify_brevo_rest_error(
    response: httpx.Response | None,
    exc: Exception | None,
) -> FailureKind:
    """Classify a failed Brevo REST attempt (per design Components §5).

    - ``exc is not None`` → delegate to ``_classify_network_exc``.
    - 401 / 403 → ``SOFT_AUTH`` (this provider's API key is bad — try next).
    - 413 → ``HARD_PAYLOAD`` (payload too large; no provider will accept it).
    - 400 with ``code=invalid_parameter`` and ``"email"`` in message →
      ``HARD_RECIPIENT`` (bad recipient address; short-circuit the chain).
    - 400 anything else → ``SOFT_PROVIDER`` (other providers may accept it).
    - 429, 5xx, anything else → ``SOFT_PROVIDER``.
    """
    if exc is not None:
        return _classify_network_exc(exc)
    if response is None:
        return FailureKind.SOFT_PROVIDER
    status = response.status_code
    if status in (401, 403):
        return FailureKind.SOFT_AUTH
    if status == 413:
        return FailureKind.HARD_PAYLOAD
    if status == 400:
        body: dict = {}
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json"):
            try:
                parsed = response.json()
            except (ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                body = parsed
        code = body.get("code")
        message = (body.get("message") or "").lower()
        if code == "invalid_parameter" and "email" in message:
            return FailureKind.HARD_RECIPIENT
        return FailureKind.SOFT_PROVIDER
    return FailureKind.SOFT_PROVIDER


def _classify_sendgrid_rest_error(
    response: httpx.Response | None,
    exc: Exception | None,
) -> FailureKind:
    """Classify a failed SendGrid REST attempt (per design Components §5).

    SendGrid 400 responses come back with a JSON body shaped
    ``{"errors": [{"message": "...", "field": "...", "help": "..."}]}``.
    If any error names a recipient/sender field (``to``/``from``, possibly
    inside a dotted path like ``personalizations.0.to.0.email``) or the
    message mentions a recipient/sender email address, classify as
    ``HARD_RECIPIENT``; everything else falls through to ``SOFT_PROVIDER``
    so the failover loop can try the next provider. JSON parse errors are
    handled defensively — a 400 with a non-JSON body is treated as
    ``SOFT_PROVIDER``.
    """
    if exc is not None:
        return _classify_network_exc(exc)
    if response is None:
        return FailureKind.SOFT_PROVIDER
    status = response.status_code
    if status in (401, 403):
        return FailureKind.SOFT_AUTH
    if status == 413:
        return FailureKind.HARD_PAYLOAD
    if status == 400:
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            body = None
        if isinstance(body, dict):
            errors = body.get("errors")
            if isinstance(errors, list):
                for err in errors:
                    if not isinstance(err, dict):
                        continue
                    field_value = (err.get("field") or "").lower()
                    msg = (err.get("message") or "").lower()
                    # SendGrid field paths look like
                    # 'personalizations.0.to.0.email' or 'from.email'.
                    if field_value and (
                        field_value.startswith("to")
                        or field_value.startswith("from")
                        or ".to" in field_value
                        or ".from" in field_value
                    ):
                        return FailureKind.HARD_RECIPIENT
                    if "email" in msg and (
                        "recipient" in msg
                        or "sender" in msg
                        or "address" in msg
                        or "to " in msg
                        or "from " in msg
                    ):
                        return FailureKind.HARD_RECIPIENT
        return FailureKind.SOFT_PROVIDER
    return FailureKind.SOFT_PROVIDER


def _classify_smtp_error(exc: Exception) -> FailureKind:
    """Classify a failed SMTP dispatch (per design Components §5).

    Maps every documented ``smtplib`` exception (and the network-layer
    exceptions raised by the underlying socket) to a ``FailureKind``.

    - ``SMTPRecipientsRefused`` → ``HARD_RECIPIENT``
    - ``SMTPDataError`` with code 552 → ``HARD_PAYLOAD``; other codes →
      ``SOFT_PROVIDER`` (transient data-channel issue, try next provider)
    - ``SMTPSenderRefused``: code 552 → ``HARD_PAYLOAD``; 530/535 →
      ``SOFT_AUTH``; other 5xx → ``HARD_RECIPIENT`` (sender address
      rejected — usually a misconfigured ``from_email``, no provider will
      accept it); 4xx → ``SOFT_PROVIDER``
    - ``SMTPAuthenticationError`` → ``SOFT_AUTH``
    - ``SMTPHeloError`` / ``SMTPConnectError`` / ``SMTPServerDisconnected``
      → ``SOFT_PROVIDER``
    - ``TimeoutError`` (incl. ``socket.timeout``) / ``ConnectionError`` →
      ``SOFT_PROVIDER``
    - Anything else → ``SOFT_PROVIDER`` (be conservative: an unknown SMTP
      error may succeed on another provider)
    """
    # Order matters: SMTPSenderRefused subclasses SMTPResponseException
    # but is checked before the generic SMTPDataError branch above. The
    # specific subclasses come first.
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return FailureKind.HARD_RECIPIENT
    if isinstance(exc, smtplib.SMTPSenderRefused):
        code = getattr(exc, "smtp_code", 0) or 0
        if code == 552:
            return FailureKind.HARD_PAYLOAD
        if code in (530, 535):
            return FailureKind.SOFT_AUTH
        if 500 <= code < 600:
            return FailureKind.HARD_RECIPIENT
        return FailureKind.SOFT_PROVIDER
    if isinstance(exc, smtplib.SMTPDataError):
        if getattr(exc, "smtp_code", 0) == 552:
            return FailureKind.HARD_PAYLOAD
        return FailureKind.SOFT_PROVIDER
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return FailureKind.SOFT_AUTH
    if isinstance(
        exc,
        (
            smtplib.SMTPHeloError,
            smtplib.SMTPConnectError,
            smtplib.SMTPServerDisconnected,
        ),
    ):
        return FailureKind.SOFT_PROVIDER
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return FailureKind.SOFT_PROVIDER
    return FailureKind.SOFT_PROVIDER


# ---------------------------------------------------------------------------
# In-app alert helpers (design Components §8)
# ---------------------------------------------------------------------------


async def _alert_dedup_should_fire(redis_key: str, ttl_seconds: int) -> bool:
    """Redis SETNX-with-TTL guard for in-app alert deduplication.

    Returns ``True`` when the caller should fire its alert (the dedup
    key was not set, so we just claimed it for ``ttl_seconds``), and
    ``False`` when an earlier call within the dedup window has already
    fired. On Redis unavailability the helper **fails open** by
    returning ``True``: per task 4.5/4.6 spec we'd rather duplicate an
    alert than silently swallow a real "outbound email is broken"
    signal.
    """
    try:
        from app.core.redis import redis_pool

        # ``set`` with ``nx=True, ex=ttl`` is the atomic SETNX-with-TTL
        # primitive. Returns truthy only when the key didn't already
        # exist; subsequent calls within the TTL window return None.
        was_new = await redis_pool.set(
            redis_key, "1", nx=True, ex=ttl_seconds
        )
        return bool(was_new)
    except Exception as exc:
        # Fail open: better duplication than silence.
        logger.warning(
            "email alert dedup: Redis unavailable for key=%s — firing anyway: %s",
            redis_key,
            exc,
        )
        return True


async def _maybe_fire_no_providers_alert(db: AsyncSession) -> None:
    """Fire an in-app alert when ``send_email`` is called with no
    active providers configured (Requirement 10.1, 10.3, 10.5).

    Deduped via Redis key ``email_no_providers_alert`` with TTL
    ``NO_PROVIDERS_DEDUP_SECONDS`` (1 hour). On Redis unavailability we
    fail open and fire anyway — better duplication than silence per
    the task spec.

    The alert targets ``audience_roles=["global_admin"]`` because the
    fix lives on the platform-wide Email Providers admin page. The
    in-app notifications system is org-scoped (``app_notifications.org_id``
    is NOT NULL) and explicitly rejects ``global_admin`` from the
    inbox, so the primary alerting channel here is the structured
    WARNING log line — the ``create_in_app_notification`` call is
    best-effort and will silently no-op if it can't persist.
    """
    if not await _alert_dedup_should_fire(
        "email_no_providers_alert", NO_PROVIDERS_DEDUP_SECONDS
    ):
        return

    # Structured log line is the primary alerting channel for ops /
    # log aggregation. The tag ``no_active_email_providers`` is grep-
    # friendly so a single CloudWatch / Loki query counts hits.
    logger.error(
        "no_active_email_providers: outbound email is currently disabled — "
        "configure at least one provider via Admin > Email Providers"
    )

    try:
        from app.modules.in_app_notifications.service import (
            create_in_app_notification,
        )

        await create_in_app_notification(
            db,
            org_id=None,  # type: ignore[arg-type]
            category="email_failure",
            severity="error",
            title="No email providers configured",
            body=(
                "Outbound email is currently disabled. Configure at "
                "least one provider in Admin > Email Providers."
            ),
            link_url="/admin/email-providers",
            audience_roles=["global_admin"],
        )
    except Exception:  # pragma: no cover — create_in_app_notification swallows
        # ``create_in_app_notification`` is exception-safe by contract,
        # but guard anyway: the structured log above is the source of
        # truth for ops alerting.
        logger.exception(
            "failed to fire in-app no-providers notification"
        )


async def _maybe_fire_all_auth_fail_alert(db: AsyncSession) -> None:
    """Fire an in-app alert when every provider attempt failed with
    ``SOFT_AUTH`` (Requirement 10.2, 10.4, 10.5).

    Deduped via Redis key ``email_all_auth_fail_alert`` with TTL
    ``ALL_AUTH_FAIL_DEDUP_SECONDS`` (1 day). Same fail-open behaviour
    on Redis unavailability as ``_maybe_fire_no_providers_alert``.
    """
    if not await _alert_dedup_should_fire(
        "email_all_auth_fail_alert", ALL_AUTH_FAIL_DEDUP_SECONDS
    ):
        return

    logger.error(
        "all_email_providers_auth_failed: every active provider returned "
        "SOFT_AUTH on the most recent send — credentials likely need rotation"
    )

    try:
        from app.modules.in_app_notifications.service import (
            create_in_app_notification,
        )

        await create_in_app_notification(
            db,
            org_id=None,  # type: ignore[arg-type]
            category="email_failure",
            severity="error",
            title="All email providers failed authentication",
            body=(
                "All providers' credentials appear to be invalid. "
                "Review Admin > Email Providers and re-test each provider."
            ),
            link_url="/admin/email-providers",
            audience_roles=["global_admin"],
        )
    except Exception:  # pragma: no cover — create_in_app_notification swallows
        logger.exception(
            "failed to fire in-app all-auth-fail notification"
        )


async def _dispatch_brevo_rest(
    provider: EmailProvider,
    message: EmailMessage,
    *,
    from_name: str,
    from_email: str,
    reply_to: str | None,
    timeout_seconds: int,
) -> EmailAttempt:
    """Dispatch ``message`` via the Brevo transactional REST API.

    POSTs to ``https://api.brevo.com/v3/smtp/email`` with the provider's
    decrypted ``api_key`` in the ``api-key`` header. On 2xx the response
    JSON's ``messageId`` is captured into the returned ``EmailAttempt``.

    Failure paths classify the outcome via ``_classify_brevo_rest_error``
    (non-2xx responses) or ``_classify_network_exc`` via that classifier
    (``httpx`` exceptions). Pre-flight credential failures are tagged
    ``SOFT_AUTH`` so the failover loop tries the next provider.

    Adapted from ``_send_test_via_rest_api`` in
    ``app/modules/email_providers/service.py`` (the test-endpoint helper),
    extended with multi-attachment support.
    """
    started = time.monotonic()
    transport = "rest_api"

    # Decrypt credentials.
    if not provider.credentials_set or not provider.credentials_encrypted:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error="credentials not configured",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        creds_json = envelope_decrypt_str(provider.credentials_encrypted)
        credentials = json.loads(creds_json)
    except Exception as exc:
        logger.error("brevo: failed to decrypt credentials: %s", exc)
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error=f"failed to decrypt credentials: {exc}",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    api_key = credentials.get("api_key") or ""
    if not api_key:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error="missing api_key",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Build payload (Brevo REST shape).
    sender: dict[str, str] = {"email": from_email}
    if from_name:
        sender["name"] = from_name

    recipient: dict[str, str] = {"email": message.to_email}
    if message.to_name:
        recipient["name"] = message.to_name

    payload: dict = {
        "sender": sender,
        "to": [recipient],
        "subject": message.subject,
    }
    if message.html_body:
        payload["htmlContent"] = message.html_body
    if message.text_body:
        payload["textContent"] = message.text_body
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    if message.attachments:
        payload["attachment"] = [
            {
                "name": att.filename,
                "content": base64.b64encode(att.content).decode("ascii"),
                "contentType": att.mime_type,
            }
            for att in message.attachments
        ]

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = "https://api.brevo.com/v3/smtp/email"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
    except Exception as exc:
        logger.warning("brevo REST request raised %s: %s", type(exc).__name__, exc)
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error=str(exc) or type(exc).__name__,
            failure_kind=_classify_brevo_rest_error(None, exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    duration_ms = int((time.monotonic() - started) * 1000)

    if response.status_code in (200, 201, 202):
        message_id: str | None = None
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            body = None
        if isinstance(body, dict):
            raw_id = body.get("messageId")
            if isinstance(raw_id, str) and raw_id:
                message_id = raw_id
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=True,
            error=None,
            failure_kind=None,
            duration_ms=duration_ms,
            message_id=message_id,
        )

    body_excerpt = (response.text or "")[:300]
    logger.warning(
        "brevo REST returned %s: %s", response.status_code, body_excerpt
    )
    return EmailAttempt(
        provider_key=provider.provider_key,
        transport=transport,
        success=False,
        error=f"brevo REST {response.status_code}: {body_excerpt}",
        failure_kind=_classify_brevo_rest_error(response, None),
        duration_ms=duration_ms,
    )


async def _dispatch_sendgrid_rest(
    provider: EmailProvider,
    message: EmailMessage,
    *,
    from_name: str,
    from_email: str,
    reply_to: str | None,
    timeout_seconds: int,
) -> EmailAttempt:
    """Dispatch ``message`` via the SendGrid v3 transactional REST API.

    POSTs to ``https://api.sendgrid.com/v3/mail/send`` with the provider's
    decrypted ``api_key`` in the ``Authorization: Bearer ...`` header.
    SendGrid returns ``202 Accepted`` with an empty body on success and
    surfaces the message id in the ``X-Message-Id`` response header,
    which is captured into the returned ``EmailAttempt``.

    Failure paths classify the outcome via
    ``_classify_sendgrid_rest_error`` (non-2xx responses and
    ``httpx`` exceptions). Pre-flight credential failures are tagged
    ``SOFT_AUTH`` so the failover loop tries the next provider.

    Mirrors the structure of ``_dispatch_brevo_rest`` so the failover
    loop can treat the two REST transports uniformly.
    """
    started = time.monotonic()
    transport = "rest_api"

    # Decrypt credentials.
    if not provider.credentials_set or not provider.credentials_encrypted:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error="credentials not configured",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        creds_json = envelope_decrypt_str(provider.credentials_encrypted)
        credentials = json.loads(creds_json)
    except Exception as exc:
        logger.error("sendgrid: failed to decrypt credentials: %s", exc)
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error=f"failed to decrypt credentials: {exc}",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    api_key = credentials.get("api_key") or ""
    if not api_key:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error="missing api_key",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Build payload (SendGrid v3 shape).
    personalization: dict = {}
    recipient: dict[str, str] = {"email": message.to_email}
    if message.to_name:
        recipient["name"] = message.to_name
    personalization["to"] = [recipient]
    if message.subject:
        personalization["subject"] = message.subject

    sender: dict[str, str] = {"email": from_email}
    if from_name:
        sender["name"] = from_name

    # Per SendGrid recommendation, plain-text part precedes HTML. Skip
    # parts whose body is empty so SendGrid doesn't reject the request.
    content: list[dict[str, str]] = []
    if message.text_body:
        content.append({"type": "text/plain", "value": message.text_body})
    if message.html_body:
        content.append({"type": "text/html", "value": message.html_body})

    payload: dict = {
        "personalizations": [personalization],
        "from": sender,
        "subject": message.subject,
        "content": content,
    }
    if reply_to:
        payload["reply_to"] = {"email": reply_to}
    if message.attachments:
        payload["attachments"] = [
            {
                "content": base64.b64encode(att.content).decode("ascii"),
                "filename": att.filename,
                "type": att.mime_type,
                "disposition": "attachment",
            }
            for att in message.attachments
        ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = "https://api.sendgrid.com/v3/mail/send"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, json=payload, headers=headers)
    except Exception as exc:
        logger.warning(
            "sendgrid REST request raised %s: %s", type(exc).__name__, exc
        )
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error=str(exc) or type(exc).__name__,
            failure_kind=_classify_sendgrid_rest_error(None, exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    duration_ms = int((time.monotonic() - started) * 1000)

    if response.status_code in (200, 201, 202):
        # SendGrid surfaces the message id via the X-Message-Id response
        # header (httpx headers lookup is case-insensitive).
        raw_id = response.headers.get("X-Message-Id")
        message_id = raw_id if isinstance(raw_id, str) and raw_id else None
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=True,
            error=None,
            failure_kind=None,
            duration_ms=duration_ms,
            message_id=message_id,
        )

    body_excerpt = (response.text or "")[:300]
    logger.warning(
        "sendgrid REST returned %s: %s", response.status_code, body_excerpt
    )
    return EmailAttempt(
        provider_key=provider.provider_key,
        transport=transport,
        success=False,
        error=f"sendgrid REST {response.status_code}: {body_excerpt}",
        failure_kind=_classify_sendgrid_rest_error(response, None),
        duration_ms=duration_ms,
    )


def _build_mime_message(
    message: EmailMessage,
    *,
    from_name: str,
    from_email: str,
    reply_to: str | None,
    message_id: str,
) -> MIMEMultipart:
    """Build the MIME envelope for an SMTP send.

    Returns ``multipart/mixed`` when ``message.attachments`` is non-empty
    (the body parts go inside an inner ``multipart/alternative`` part,
    attachments are appended to the outer mixed container) and a plain
    ``multipart/alternative`` otherwise. Per RFC 2046, the richer format
    (HTML) is added last so MUAs that honour the spec render it
    preferentially over the text alternative.

    Used by ``_dispatch_smtp``. The REST transports build their payloads
    natively because the provider APIs accept JSON dicts rather than raw
    MIME.
    """
    text_part: MIMEText | None = None
    html_part: MIMEText | None = None
    if message.text_body:
        text_part = MIMEText(message.text_body, "plain", "utf-8")
    if message.html_body:
        html_part = MIMEText(message.html_body, "html", "utf-8")

    body_alt = MIMEMultipart("alternative")
    if text_part is not None:
        body_alt.attach(text_part)
    if html_part is not None:
        body_alt.attach(html_part)

    if message.attachments:
        outer: MIMEMultipart = MIMEMultipart("mixed")
        outer.attach(body_alt)
        for att in message.attachments:
            maintype, _, subtype = (att.mime_type or "application/octet-stream").partition("/")
            part = MIMEApplication(att.content, _subtype=subtype or "octet-stream")
            # MIMEApplication forces application/<subtype>; rewrite when
            # the caller supplied something else (e.g. image/png).
            if maintype and maintype != "application":
                part.replace_header("Content-Type", att.mime_type or "application/octet-stream")
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=att.filename,
            )
            outer.attach(part)
    else:
        outer = body_alt

    # Headers on the outer container.
    if from_name:
        outer["From"] = f'"{from_name}" <{from_email}>'
    else:
        outer["From"] = f"<{from_email}>"
    if message.to_name:
        outer["To"] = f'"{message.to_name}" <{message.to_email}>'
    else:
        outer["To"] = message.to_email
    outer["Subject"] = message.subject
    if reply_to:
        outer["Reply-To"] = reply_to
    outer["Message-ID"] = message_id
    return outer


async def _dispatch_smtp(
    provider: EmailProvider,
    message: EmailMessage,
    *,
    from_name: str,
    from_email: str,
    reply_to: str | None,
    timeout_seconds: int,
) -> EmailAttempt:
    """Dispatch ``message`` via SMTP.

    Covers ``custom_smtp`` plus any of ``brevo`` (with smtp_login),
    ``mailgun``, ``ses``, ``gmail``, ``outlook`` whose credentials shape
    is ``{"username": ..., "password": ...}``. Brevo-with-smtp_login
    decodes credentials as ``{"api_key": ..., "smtp_login": ...}``: the
    SMTP login becomes the username and the API key becomes the password.

    Honours ``smtp_encryption`` ∈ ``none``, ``tls``, ``ssl``. When the
    provider has no ``smtp_host`` the default-host fallback table
    (``_DEFAULT_SMTP_HOSTS``) is consulted; if that lookup also misses,
    the attempt fails with ``error="missing smtp_host"``.

    Every blocking ``smtplib`` call runs inside ``asyncio.to_thread`` so
    the event loop stays free. The per-attempt socket timeout is applied
    by passing ``timeout=timeout_seconds`` to the
    ``smtplib.SMTP`` / ``smtplib.SMTP_SSL`` constructor — the smtplib
    implementation forwards this to ``socket.settimeout`` internally.

    Generates an RFC 5322 ``Message-ID`` at send time using
    ``email.utils.make_msgid`` (domain derived from ``from_email``) and
    persists it on the returned ``EmailAttempt.message_id`` so callers
    can correlate later bounce webhooks back to the originating row.

    Failure paths classify the outcome via ``_classify_smtp_error``
    (smtplib and socket-level exceptions). Pre-flight credential failures
    are tagged ``SOFT_AUTH``; missing ``smtp_host`` (no fallback in the
    default-host table) is ``SOFT_PROVIDER`` so the failover loop tries
    the next provider.
    """
    started = time.monotonic()
    transport = "smtp"

    # Decrypt credentials.
    if not provider.credentials_set or not provider.credentials_encrypted:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error="credentials not configured",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        creds_json = envelope_decrypt_str(provider.credentials_encrypted)
        credentials = json.loads(creds_json)
    except Exception as exc:
        logger.error("smtp: failed to decrypt credentials for %s: %s",
                     provider.provider_key, exc)
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error=f"failed to decrypt credentials: {exc}",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Resolve username / password by credentials shape.
    api_key = credentials.get("api_key") or ""
    smtp_login = credentials.get("smtp_login") or ""
    raw_username = credentials.get("username") or ""
    raw_password = credentials.get("password") or ""

    if smtp_login:
        # Brevo-with-smtp_login: smtp_login is the username, the api_key
        # is the SMTP password.
        username = smtp_login
        password = api_key or raw_password
    elif raw_username:
        username = raw_username
        password = raw_password
    elif api_key:
        # Generic-SMTP fallback (Phase 0.5 hotfix pattern): the admin
        # configured an api_key but no username — use the api_key for
        # both fields so providers like SendGrid SMTP keep working.
        username = api_key
        password = api_key
    else:
        username = ""
        password = ""

    # Resolve host / port / encryption.
    if provider.smtp_host:
        smtp_host = provider.smtp_host
        smtp_port = provider.smtp_port or 587
        smtp_encryption = (provider.smtp_encryption or "tls").lower()
    else:
        default = _DEFAULT_SMTP_HOSTS.get(provider.provider_key)
        if default is None:
            return EmailAttempt(
                provider_key=provider.provider_key,
                transport=transport,
                success=False,
                error="missing smtp_host",
                failure_kind=FailureKind.SOFT_PROVIDER,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
        smtp_host, smtp_port, default_encryption = default
        smtp_port = provider.smtp_port or smtp_port
        smtp_encryption = (provider.smtp_encryption or default_encryption).lower()

    # Generate RFC 5322 Message-ID (domain from from_email when present).
    domain = from_email.rsplit("@", 1)[-1] if "@" in from_email else "orainvoice.local"
    message_id = make_msgid(domain=domain)

    # Build MIME envelope.
    mime_msg = _build_mime_message(
        message,
        from_name=from_name,
        from_email=from_email,
        reply_to=reply_to,
        message_id=message_id,
    )
    raw_payload = mime_msg.as_string()

    def _send_sync() -> None:
        """Blocking smtplib dispatch — runs in a worker thread."""
        if smtp_encryption == "ssl":
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout_seconds)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds)
            if smtp_encryption == "tls":
                server.starttls()
        try:
            if username and password:
                server.login(username, password)
            server.sendmail(from_email, [message.to_email], raw_payload)
        finally:
            try:
                server.quit()
            except Exception:
                # quit() can raise if the connection already dropped;
                # the send already completed so swallow the close error.
                pass

    try:
        await asyncio.to_thread(_send_sync)
    except Exception as exc:
        logger.warning(
            "smtp dispatch raised %s for %s@%s:%s — %s",
            type(exc).__name__,
            provider.provider_key,
            smtp_host,
            smtp_port,
            exc,
        )
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport=transport,
            success=False,
            error=str(exc) or type(exc).__name__,
            failure_kind=_classify_smtp_error(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
            message_id=message_id,
        )

    return EmailAttempt(
        provider_key=provider.provider_key,
        transport=transport,
        success=True,
        error=None,
        failure_kind=None,
        duration_ms=int((time.monotonic() - started) * 1000),
        message_id=message_id,
    )


# ---------------------------------------------------------------------------
# Public per-provider helper (design Components §3)
# ---------------------------------------------------------------------------


async def dispatch_one_provider(
    db: AsyncSession,
    provider: EmailProvider,
    message: EmailMessage,
    *,
    org_sender_name: str | None = None,
    org_reply_to: str | None = None,
    timeout_seconds: int = EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS,
) -> EmailAttempt:
    """Dispatch ``message`` to a SINGLE provider — no failover, no blocklist check.

    Public helper used by the per-provider admin test endpoint
    (``app/modules/email_providers/service.py::test_email_provider``).
    Phase 3 refactors that endpoint to delegate here, replacing its
    inline SMTP/REST blocks with one call into the unified dispatch
    matrix.

    Compared with :func:`send_email`, this helper:

    - does **not** consult ``bounced_addresses`` (admin Test sends are
      diagnostic and must reach the provider regardless of blocklist
      state);
    - does **not** load other providers or attempt failover;
    - does **not** enforce the total time budget — only the per-attempt
      timeout passed through to the chosen dispatcher.

    Transport selection (the "dispatch matrix" pinned by the Phase 1
    tests):

    - ``provider.provider_key == "brevo"`` and credentials decrypt to a
      dict with a non-empty ``api_key`` and an empty/missing
      ``smtp_login`` → :func:`_dispatch_brevo_rest`.
    - ``provider.provider_key == "sendgrid"`` and credentials decrypt to
      a dict with a non-empty ``api_key`` → :func:`_dispatch_sendgrid_rest`.
    - Everything else (Brevo with ``smtp_login``, Mailgun, SES, Gmail,
      Outlook, ``custom_smtp``) → :func:`_dispatch_smtp`.

    The returned :class:`EmailAttempt` (including ``duration_ms``) comes
    straight from the chosen dispatcher; this helper only adds the
    pre-dispatch short-circuits for missing ``from_email`` and undecryptable
    credentials, both of which return ``duration_ms=0`` and ``transport=""``
    because no transport-level work was performed.

    The ``db`` argument is currently unused — kept in the signature for
    forward-compatibility with future bounce-blocklist plumbing in
    :func:`send_email`'s shared code path.
    """
    # `db` is intentionally unused here; see docstring.
    del db

    # 1. Resolve sender identity. Missing from_email is a per-provider
    #    config error, not a transport failure — surface it as
    #    SOFT_PROVIDER so a failover caller (send_email) would move on.
    identity = _resolve_sender_identity(
        provider,
        org_sender_name=org_sender_name,
        org_reply_to=org_reply_to,
    )
    if identity is None:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport="",
            success=False,
            error="missing from_email",
            failure_kind=FailureKind.SOFT_PROVIDER,
            duration_ms=0,
        )
    from_name, from_email, reply_to = identity

    # 2. Decrypt credentials up front so the dispatch matrix can inspect
    #    the shape (presence of api_key vs smtp_login). Each underlying
    #    dispatcher repeats this decryption — duplication is acceptable
    #    because (a) decryption is cheap relative to a network round-trip,
    #    and (b) it keeps each dispatcher self-contained for unit tests.
    if not provider.credentials_set or not provider.credentials_encrypted:
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport="",
            success=False,
            error="credentials not configured",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=0,
        )
    try:
        creds_json = envelope_decrypt_str(provider.credentials_encrypted)
        credentials = json.loads(creds_json)
        if not isinstance(credentials, dict):
            raise ValueError("credentials payload is not a JSON object")
    except Exception as exc:
        logger.error(
            "dispatch_one_provider: failed to decrypt credentials for %s: %s",
            provider.provider_key,
            exc,
        )
        return EmailAttempt(
            provider_key=provider.provider_key,
            transport="",
            success=False,
            error=f"failed to decrypt credentials: {exc}",
            failure_kind=FailureKind.SOFT_AUTH,
            duration_ms=0,
        )

    api_key = credentials.get("api_key") or ""
    smtp_login = credentials.get("smtp_login") or ""

    # 3. Route to the chosen transport.
    if (
        provider.provider_key == "brevo"
        and api_key
        and not smtp_login
    ):
        return await _dispatch_brevo_rest(
            provider,
            message,
            from_name=from_name,
            from_email=from_email,
            reply_to=reply_to,
            timeout_seconds=timeout_seconds,
        )
    if provider.provider_key == "sendgrid" and api_key:
        return await _dispatch_sendgrid_rest(
            provider,
            message,
            from_name=from_name,
            from_email=from_email,
            reply_to=reply_to,
            timeout_seconds=timeout_seconds,
        )
    return await _dispatch_smtp(
        provider,
        message,
        from_name=from_name,
        from_email=from_email,
        reply_to=reply_to,
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def _load_active_providers(db: AsyncSession) -> list[EmailProvider]:
    """Return active providers in failover order (priority ASC).

    Filters: ``is_active=True AND credentials_set=True``. Empty list
    means no provider is usable for outbound mail; the caller must
    decide whether to fire the no-providers alert.
    """
    stmt = (
        select(EmailProvider)
        .where(
            EmailProvider.is_active.is_(True),
            EmailProvider.credentials_set.is_(True),
        )
        .order_by(EmailProvider.priority.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _check_bounce_blocklist(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    email_address: str,
) -> tuple[bool, str | None]:
    """Look up whether ``email_address`` is on the bounced-addresses
    blocklist for the given org.

    Returns ``(is_blocked, reason)``. ``is_blocked=True`` means the
    address has an unexpired hard-bounce row and ``send_email`` must
    short-circuit with ``HARD_RECIPIENT``. ``is_blocked=False`` with a
    non-None ``reason`` means a soft-bounce is on file but the address
    is still allowed through; the caller logs a warning and proceeds.

    Phase 1 stub: returns ``(False, None)`` because the
    ``bounced_addresses`` table doesn't exist yet (it's created in
    Phase 8c, task 9.1). The call site in :func:`send_email` is wired up
    now so Phase 8c only has to swap the body for the real query.
    """
    # TODO(9.3): query bounced_addresses for (org_id OR NULL,
    #            lower(email_address)); return (is_blocked, reason).
    del db, org_id, email_address
    return False, None


async def send_email(
    db: AsyncSession,
    message: EmailMessage,
    *,
    org_sender_name: str | None = None,
    org_reply_to: str | None = None,
) -> SendResult:
    """Send an email through the active provider chain.

    Top-level orchestrator (design Components §8). The work happens in
    four phases:

    1. **Payload pre-check.** Sum the HTML body, text body, and every
       attachment payload. Anything over :data:`EMAIL_SIZE_LIMIT` is
       rejected up front with a single ``HARD_PAYLOAD`` attempt — no
       provider would accept it, so spending a network round-trip
       (per provider!) to learn that is wasteful.
    2. **Bounce-blocklist pre-check.** Consult
       :func:`_check_bounce_blocklist` for ``(org_id, to_email)``. A
       hard-bounce hit short-circuits to ``HARD_RECIPIENT``; a soft hit
       is logged as a warning and the send proceeds. (Phase 1 ships the
       call site only; the underlying table arrives in Phase 8c.)
    3. **Provider chain.** Load the active provider set ordered by
       priority (lowest first). Empty set fires the no-providers alert
       and returns failure with ``attempts=[]``. Otherwise loop, gating
       on the total time budget on each iteration. The per-attempt
       timeout passed to :func:`dispatch_one_provider` is shrunk to the
       remaining budget so a long-running attempt cannot blow past
       :data:`EMAIL_TOTAL_BUDGET_SECONDS`. ``HARD_RECIPIENT`` /
       ``HARD_PAYLOAD`` short-circuit; ``SOFT_AUTH`` / ``SOFT_PROVIDER``
       continue.
    4. **Chain exhaustion.** When every attempt was ``SOFT_AUTH`` we
       fire the all-auth-fail alert (a strong signal an admin needs to
       rotate keys). Other exhaustion modes just return failure with the
       last attempt's error.

    Caller responsibilities (per design Components §3): own the session,
    persist ``provider_key`` / ``provider_message_id`` after success,
    and decide whether to fire ``create_in_app_notification`` on
    failure. This function never commits.
    """
    started = time.monotonic()

    # 1. Payload pre-check.
    total_size = len(message.html_body or "") + len(message.text_body or "")
    total_size += sum(len(att.content) for att in message.attachments)
    if total_size > EMAIL_SIZE_LIMIT:
        return SendResult(
            success=False,
            error="attachment size exceeds limit",
            attempts=[
                EmailAttempt(
                    provider_key="",
                    transport="precheck",
                    success=False,
                    failure_kind=FailureKind.HARD_PAYLOAD,
                    error="attachment size exceeds limit",
                    duration_ms=0,
                )
            ],
        )

    # 2. Bounce-blocklist pre-check.
    blocked, reason = await _check_bounce_blocklist(
        db, org_id=message.org_id, email_address=message.to_email
    )
    if blocked:
        return SendResult(
            success=False,
            error="recipient is on the bounce list",
            attempts=[
                EmailAttempt(
                    provider_key="bouncelist",
                    transport="precheck",
                    success=False,
                    failure_kind=FailureKind.HARD_RECIPIENT,
                    error=reason or "blocked",
                    duration_ms=0,
                )
            ],
        )
    if reason:
        # Soft-bounce on file but not blocking — log and proceed.
        logger.warning(
            "send_email: %s has soft-bounce on file (%s) — proceeding",
            message.to_email,
            reason,
        )

    # 3. Load active providers (priority ASC).
    providers = await _load_active_providers(db)
    if not providers:
        await _maybe_fire_no_providers_alert(db)
        return SendResult(
            success=False,
            error="No active email providers configured",
            attempts=[],
        )

    # 4. Loop with per-attempt + total budget.
    attempts: list[EmailAttempt] = []
    for provider in providers:
        elapsed = time.monotonic() - started
        if elapsed > EMAIL_TOTAL_BUDGET_SECONDS:
            attempts.append(
                EmailAttempt(
                    provider_key=provider.provider_key,
                    transport="",
                    success=False,
                    failure_kind=FailureKind.BUDGET_EXCEEDED,
                    error="time budget exceeded",
                    duration_ms=0,
                )
            )
            break

        # Per-attempt timeout = min(default, remaining-total-budget) so a
        # single slow provider can't push us past EMAIL_TOTAL_BUDGET_SECONDS.
        # Floor at 1 second — sub-second timeouts cause flaky tests on slow
        # CI runners and offer no real protection.
        remaining_budget = max(1, int(EMAIL_TOTAL_BUDGET_SECONDS - elapsed))
        per_attempt_timeout = min(
            EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS, remaining_budget
        )

        attempt = await dispatch_one_provider(
            db,
            provider,
            message,
            org_sender_name=org_sender_name,
            org_reply_to=org_reply_to,
            timeout_seconds=per_attempt_timeout,
        )
        attempts.append(attempt)

        if attempt.success:
            return SendResult(
                success=True,
                provider_key=provider.provider_key,
                transport=attempt.transport,
                message_id=attempt.message_id,
                attempts=attempts,
            )
        if attempt.failure_kind in (
            FailureKind.HARD_RECIPIENT,
            FailureKind.HARD_PAYLOAD,
        ):
            return SendResult(
                success=False,
                error=attempt.error,
                attempts=attempts,
            )
        # else: SOFT_AUTH / SOFT_PROVIDER / BUDGET_EXCEEDED → try next.

    # 5. Chain exhausted. Fire all-auth-fail alert when every attempt
    #    came back SOFT_AUTH (strong signal: rotate creds).
    if attempts and all(
        a.failure_kind == FailureKind.SOFT_AUTH for a in attempts
    ):
        await _maybe_fire_all_auth_fail_alert(db)

    last = attempts[-1] if attempts else None
    return SendResult(
        success=False,
        error=(last.error if last else "unknown"),
        attempts=attempts,
    )
