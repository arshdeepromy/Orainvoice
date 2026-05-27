"""Unified email sender — single source of truth for outbound email.

This module is the destination for the email-provider-unification work.
Phase 0 (this commit) lays down the public dataclasses, the failure
classification enum, and module-level constants so callers and tests can
already import the new types. Phase 1 fills in ``send_email`` itself
(REST + SMTP transports, failover, error classification, time budgets,
bounce-blocklist pre-check); Phase 1.7 adds ``dispatch_one_provider``
for the per-provider admin test endpoint.

Public API (stable from Phase 0 onwards):

- ``EmailMessage`` / ``EmailAttachment`` — the message value objects.
- ``EmailAttempt`` / ``SendResult`` — the per-provider attempt record
  and the aggregate result returned by ``send_email``.
- ``FailureKind`` — classification of a failed attempt; controls whether
  the failover loop short-circuits or continues to the next provider.
- ``EMAIL_SIZE_LIMIT`` / ``EMAIL_PER_ATTEMPT_TIMEOUT_SECONDS`` /
  ``EMAIL_TOTAL_BUDGET_SECONDS`` — module-level constants.

The full design lives at ``.kiro/specs/email-provider-unification/design.md``.

Requirements: 1.1, 1.2, 1.3, 1.5
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

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
# Public entry point (implementation lands in Phase 1)
# ---------------------------------------------------------------------------


async def send_email(
    db: AsyncSession,
    message: EmailMessage,
    *,
    org_sender_name: str | None = None,
    org_reply_to: str | None = None,
) -> SendResult:
    """Send an email through the active provider chain (Phase 1).

    Phase 0 only declares the signature so callers and tests can already
    import the symbol. The full implementation — payload pre-check,
    bounce-blocklist lookup, active-provider loop with per-attempt and
    total time budgets, and error classification — lands in Phase 1.

    See design Components §3 and §8 for the full contract.
    """
    raise NotImplementedError(
        "send_email is implemented in Phase 1 of email-provider-unification. "
        "See .kiro/specs/email-provider-unification/design.md."
    )
