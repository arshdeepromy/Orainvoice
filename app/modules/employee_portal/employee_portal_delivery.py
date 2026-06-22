"""Employee Portal credential-issuance + password-reset email delivery (R15).

This module mirrors ``app/modules/staff/onboarding_delivery.py`` (and
``roster_delivery.py``): the fallible email work lives out of the API
routers so the credential-issuance / invite-resend / password-reset
endpoints all share one code path, and a provider failure is **returned
as a result object, never raised** — exactly like
``send_onboarding_email`` returns ``OnboardingDeliveryResult``.

Two public entry points, both built on the unified ``send_email`` (multi
provider failover + DLQ, R15.2) and ``render_transactional_html``:

- :func:`send_credential_setup_email` — the **credential-setup** email
  (R15.1). Composes a message that names the Organisation, carries a
  set-password CTA to the org's branded
  ``/e/{slug}/accept-invite/{token}`` login, and states the link's
  expiry (default ``"7 days"``). Never includes a raw password (R15.4).
- :func:`send_password_reset_email` — the **password-reset** email
  (R15.5). Names the Organisation, carries a reset CTA, and states the
  link's expiry (default ``"60 minutes"``). Never includes a raw
  password (R15.4).

Both return :class:`EmployeePortalDeliveryResult` and **never raise** on a
provider failure (R15.3): they are dispatched *after* the DB commit by the
API layer, which folds the result into the response (``invite_sent`` /
``invite_error``) and — for credential setup — surfaces a human-readable
"email could not be delivered" error without rolling back the created
Portal_User. A missing/blank destination address is rejected up front
with ``ERROR_NO_EMAIL`` (R15.6).

Composition (``compose_*``) is extracted as pure helpers so the message
shape can be property-tested without a network, and so the senders can be
tested with ``send_email`` mocked.

Validates: Requirements 15.1, 15.2, 15.4, 15.5.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.email_sender import (
    EmailMessage,
    render_transactional_html,
    send_email,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result object + error codes (mirror OnboardingDeliveryResult)
# ---------------------------------------------------------------------------

#: Machine error code returned when the destination address is missing or
#: blank (R15.6) — the API layer maps it to a "valid email required" message.
ERROR_NO_EMAIL = "portal_email_required"

#: Machine error code returned when every configured provider failed to
#: accept the message (R15.3) — the API layer maps it to an "email could
#: not be delivered" message without rolling back the Portal_User.
ERROR_SEND_FAILED = "send_failed"

#: CTA labels on the two emails' buttons.
_CREDENTIAL_CTA_LABEL = "Set your password"
_RESET_CTA_LABEL = "Reset your password"

#: Default expiry copy for each email — the API layer may override to match
#: the actual token TTL it minted.
_DEFAULT_CREDENTIAL_EXPIRY = "7 days"
_DEFAULT_RESET_EXPIRY = "60 minutes"


@dataclass
class EmployeePortalDeliveryResult:
    """Return value of the ``send_*`` helpers in this module.

    Mirrors ``OnboardingDeliveryResult``: ``ok`` is the success flag and
    ``message_id`` carries the provider's id on success. On failure
    ``error_code`` is one of the module constants above
    (``portal_email_required`` when the destination address is missing,
    ``send_failed`` when the provider chain is exhausted) so the API layer
    can fold it into the ``invite_sent`` / ``invite_error`` response fields
    (R15.3). These helpers **never raise** for a provider failure — they
    return ``ok=False`` instead.

    ``success`` is provided as an alias of ``ok`` so call-sites that read
    the result as ``result.success`` work too.
    """

    ok: bool
    message_id: str | None = None
    error_code: str | None = None

    @property
    def success(self) -> bool:
        """Alias of :attr:`ok`."""
        return self.ok


# ---------------------------------------------------------------------------
# Pure composition helpers (testable with the sender mocked)
# ---------------------------------------------------------------------------


def compose_credential_setup_email(
    *,
    staff_email: str,
    org_name: str,
    set_password_url: str,
    expiry_hint: str = _DEFAULT_CREDENTIAL_EXPIRY,
    org_id: uuid.UUID | None = None,
) -> EmailMessage:
    """Compose the **credential-setup** email (R15.1, R15.4).

    - Subject names the Organisation.
    - Body names the Organisation and states the link expires in
      ``expiry_hint`` (R15.1).
    - A prominent CTA button links to ``set_password_url`` (the branded
      ``/e/{slug}/accept-invite/{token}`` login), rendered via
      ``render_transactional_html`` (R15.1).
    - **Never** includes a raw password — credentials are delivered
      exclusively via the set-password link (R15.4).

    Pure: builds and returns an :class:`EmailMessage`, performs no I/O.
    """
    subject = f"Set up your {org_name} portal access"

    text_body = (
        f"Kia ora,\n\n"
        f"{org_name} has set up access for you to the {org_name} employee "
        f"portal. To finish setting up your account, choose your own "
        f"password using the secure link below:\n\n"
        f"{set_password_url}\n\n"
        f"This link expires in {expiry_hint}. If it expires before you set "
        f"your password, contact {org_name} and they can send you a new "
        f"one.\n\n"
        f"For your security, this email never contains a password — you "
        f"choose your own when you follow the link above.\n\n"
        f"Ngā mihi,\n{org_name}"
    )
    html_body = render_transactional_html(
        text_body,
        subject=subject,
        cta_url=set_password_url,
        cta_label=_CREDENTIAL_CTA_LABEL,
    )
    return EmailMessage(
        to_email=staff_email,
        to_name="",
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        org_id=org_id,
    )


def compose_password_reset_email(
    *,
    staff_email: str,
    org_name: str,
    reset_url: str,
    expiry_hint: str = _DEFAULT_RESET_EXPIRY,
    org_id: uuid.UUID | None = None,
) -> EmailMessage:
    """Compose the **password-reset** email (R15.5, R15.4).

    - Subject names the Organisation.
    - Body names the Organisation and states the link expires in
      ``expiry_hint`` (R15.5).
    - A prominent CTA button links to ``reset_url`` (the branded portal
      reset page), rendered via ``render_transactional_html``.
    - **Never** includes a raw password (R15.4).

    Pure: builds and returns an :class:`EmailMessage`, performs no I/O.
    """
    subject = f"Reset your {org_name} portal password"

    text_body = (
        f"Kia ora,\n\n"
        f"We received a request to reset the password for your {org_name} "
        f"employee portal account. Use the secure link below to choose a "
        f"new password:\n\n"
        f"{reset_url}\n\n"
        f"This link expires in {expiry_hint}. If you did not request a "
        f"password reset, you can safely ignore this email — your password "
        f"will not change.\n\n"
        f"For your security, this email never contains a password — you "
        f"choose a new one when you follow the link above.\n\n"
        f"Ngā mihi,\n{org_name}"
    )
    html_body = render_transactional_html(
        text_body,
        subject=subject,
        cta_url=reset_url,
        cta_label=_RESET_CTA_LABEL,
    )
    return EmailMessage(
        to_email=staff_email,
        to_name="",
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        org_id=org_id,
    )


# ---------------------------------------------------------------------------
# Public entry point — credential-setup email (R15.1)
# ---------------------------------------------------------------------------


async def send_credential_setup_email(
    db: AsyncSession,
    *,
    staff_email: str,
    org_name: str,
    set_password_url: str,
    expiry_hint: str = _DEFAULT_CREDENTIAL_EXPIRY,
    org_id: uuid.UUID | None = None,
) -> EmployeePortalDeliveryResult:
    """Email the credential-setup (set-password) link to a Staff_Member (R15).

    Mirrors :func:`onboarding_delivery.send_onboarding_email`:

    1. Refuse with ``portal_email_required`` when ``staff_email`` is
       null/blank (R15.6) — belt-and-braces; the API layer also gates this.
    2. Compose the message via :func:`compose_credential_setup_email`
       (org name, set-password CTA to ``/e/{slug}/accept-invite/{token}``,
       expiry copy, no raw password).
    3. Dispatch via the unified ``send_email`` with
       ``dlq_task_name='employee_portal_credential_email'`` so a
       chain-exhausted send lands in the dead-letter queue for replay
       (R15.2).
    4. Return :class:`EmployeePortalDeliveryResult` — **never raises** on a
       provider failure (R15.3); the API layer folds the result into the
       response and preserves the created Portal_User without rollback.

    The audit-log row and DB commit are owned by the caller (API layer),
    which dispatches this only *after* the commit.
    """
    if not staff_email or not staff_email.strip():
        return EmployeePortalDeliveryResult(ok=False, error_code=ERROR_NO_EMAIL)

    message = compose_credential_setup_email(
        staff_email=staff_email.strip(),
        org_name=org_name,
        set_password_url=set_password_url,
        expiry_hint=expiry_hint,
        org_id=org_id,
    )

    result = await send_email(
        db,
        message,
        org_sender_name=org_name,
        dlq_task_name="employee_portal_credential_email",
        dlq_task_args={
            "to_email": message.to_email,
            "org_id": str(org_id) if org_id else None,
        },
    )

    if result.success:
        return EmployeePortalDeliveryResult(ok=True, message_id=result.message_id)

    logger.warning(
        "employee_portal credential-setup email failed: org=%s error=%s attempts=%d",
        org_id,
        result.error,
        len(result.attempts),
    )
    return EmployeePortalDeliveryResult(ok=False, error_code=ERROR_SEND_FAILED)


# ---------------------------------------------------------------------------
# Public entry point — password-reset email (R15.5)
# ---------------------------------------------------------------------------


async def send_password_reset_email(
    db: AsyncSession,
    *,
    staff_email: str,
    org_name: str,
    reset_url: str,
    expiry_hint: str = _DEFAULT_RESET_EXPIRY,
    org_id: uuid.UUID | None = None,
) -> EmployeePortalDeliveryResult:
    """Email the password-reset link to a Staff_Member (R15.5).

    Same shape as :func:`send_credential_setup_email`:

    1. Refuse with ``portal_email_required`` when ``staff_email`` is
       null/blank (R15.6).
    2. Compose via :func:`compose_password_reset_email` (org name, reset
       CTA, expiry copy, no raw password).
    3. Dispatch via ``send_email`` with
       ``dlq_task_name='employee_portal_reset_email'`` (R15.2).
    4. Return :class:`EmployeePortalDeliveryResult` — **never raises** on a
       provider failure (R15.3).
    """
    if not staff_email or not staff_email.strip():
        return EmployeePortalDeliveryResult(ok=False, error_code=ERROR_NO_EMAIL)

    message = compose_password_reset_email(
        staff_email=staff_email.strip(),
        org_name=org_name,
        reset_url=reset_url,
        expiry_hint=expiry_hint,
        org_id=org_id,
    )

    result = await send_email(
        db,
        message,
        org_sender_name=org_name,
        dlq_task_name="employee_portal_reset_email",
        dlq_task_args={
            "to_email": message.to_email,
            "org_id": str(org_id) if org_id else None,
        },
    )

    if result.success:
        return EmployeePortalDeliveryResult(ok=True, message_id=result.message_id)

    logger.warning(
        "employee_portal password-reset email failed: org=%s error=%s attempts=%d",
        org_id,
        result.error,
        len(result.attempts),
    )
    return EmployeePortalDeliveryResult(ok=False, error_code=ERROR_SEND_FAILED)
