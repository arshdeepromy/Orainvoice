"""Onboarding email delivery + completion side-effects for the Staff module.

This module mirrors ``app/modules/staff/roster_delivery.py`` (the
``send_roster_email`` / ``RosterDeliveryResult`` pattern): the fallible
email work lives out of ``router.py`` / ``public_router.py`` so the admin
create/resend endpoints and the public submit endpoint all share one code
path, and a provider failure is **returned as a result object, never
raised** — exactly like ``send_roster_email`` returns ``RosterDeliveryResult``.

Three public entry points:

- :func:`send_onboarding_email` — the **invite** email (R3). Composes the
  ``Complete your onboarding — {org_name}`` message with a first-name
  greeting, a CTA button to ``/onboard/{token}``, and 7-day-expiry copy;
  dispatches via the unified ``send_email`` (multi-provider failover + DLQ);
  returns :class:`OnboardingDeliveryResult` and never raises on a provider
  failure (R3.6).
- :func:`send_onboarding_confirmation_email` — the best-effort staff
  thank-you after a successful submit (R15). Wrapped so any failure is
  logged and swallowed — never raises.
- :func:`notify_org_onboarding_complete` — the best-effort org notification
  on completion (R16): creates the in-app notification and emails each
  active ``org_admin`` / ``branch_admin`` user (deduped by email) that the
  staff member finished onboarding. Every send is wrapped so a failure is
  logged and swallowed — never raises.

Composition (``compose_*``) and recipient resolution
(``resolve_org_notification_recipients``) are extracted as small helpers so
the senders can be tested with ``send_email`` mocked, and so the message
shape can be property-tested without a network (tasks 5.2, 5.3).

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 15.1, 15.2, 15.4, 16.1,
16.2, 16.3, 16.4, 16.6.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.integrations.email_sender import (
    EmailMessage,
    render_transactional_html,
    send_email,
)
from app.modules.admin.models import Organisation
from app.modules.auth.models import User
from app.modules.in_app_notifications.service import create_in_app_notification
from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result object + error codes (mirror RosterDeliveryResult)
# ---------------------------------------------------------------------------

#: Machine error codes folded into the admin response by the router
#: (``onboarding_email_error``) and mapped to a human sentence via
#: ``humanize_onboarding_error``. They are a subset of
#: ``onboarding_validation.ONBOARDING_ERROR_CODES``.
ERROR_NO_EMAIL = "onboarding_email_required"
ERROR_SEND_FAILED = "send_failed"

#: CTA label on the invite email button.
_INVITE_CTA_LABEL = "Complete your onboarding"

#: Number of days the invite link stays valid — copy must match the token
#: TTL in ``onboarding_tokens._TOKEN_TTL_DAYS`` (R3.5).
_LINK_TTL_DAYS = 7


@dataclass
class OnboardingDeliveryResult:
    """Return value of the ``send_onboarding_*`` helpers.

    Mirrors ``RosterDeliveryResult``: ``ok`` is the success flag and
    ``message_id`` carries the provider's id on success. On failure
    ``error_code`` is one of the module constants above
    (``onboarding_email_required`` when the destination address is missing,
    ``send_failed`` when the provider chain is exhausted) so the router can
    fold it into the ``onboarding_email_sent`` / ``onboarding_email_error``
    response fields (R3.6). These helpers **never raise** for a provider
    failure — they return ``ok=False`` instead.

    ``success`` is provided as an alias of ``ok`` so call-sites that read
    the result as ``result.success`` (per the task's stated shape) work too.
    """

    ok: bool
    message_id: str | None = None
    error_code: str | None = None

    @property
    def success(self) -> bool:
        """Alias of :attr:`ok` (the task describes the shape as ``success``)."""
        return self.ok


# ---------------------------------------------------------------------------
# URL + org helpers
# ---------------------------------------------------------------------------


def build_onboard_url(token: str, base_url: str | None = None) -> str:
    """Return the public onboarding URL ``{base}/onboard/{token}`` (R11.1).

    ``base_url`` (typically the request ``Origin``) wins so the link uses the
    public domain the admin is on; it falls back to the configured
    ``frontend_base_url`` and finally ``http://localhost`` — the same
    precedence the invoice / quote / portal email links use.
    """
    base = (base_url or app_settings.frontend_base_url or "http://localhost").rstrip("/")
    return f"{base}/onboard/{token}"


def build_staff_detail_url(staff_id: uuid.UUID, base_url: str | None = None) -> str:
    """Return the admin staff-detail URL ``{base}/staff/{staff_id}`` (R16.2/R16.3)."""
    base = (base_url or app_settings.frontend_base_url or "http://localhost").rstrip("/")
    return f"{base}/staff/{staff_id}"


def _staff_to_name(staff: StaffMember) -> str:
    """Best display name for an email ``to_name`` / notification body."""
    full = f"{staff.first_name or ''} {staff.last_name or ''}".strip()
    return full or (staff.name or "")


async def _load_org_name(db: AsyncSession, org_id: uuid.UUID) -> str:
    """Return the organisation name, defaulting to a friendly fallback."""
    res = await db.execute(
        select(Organisation.name).where(Organisation.id == org_id)
    )
    row = res.first()
    if row is None or not row[0]:
        return "your employer"
    return row[0]


# ---------------------------------------------------------------------------
# Pure composition helpers (testable with the sender mocked — tasks 5.2/5.3)
# ---------------------------------------------------------------------------


def compose_onboarding_email(
    *,
    to_email: str,
    to_name: str,
    staff_first_name: str,
    org_name: str,
    onboard_url: str,
    org_id: uuid.UUID | None = None,
) -> EmailMessage:
    """Compose the onboarding **invite** email (R3.2, R3.3, R3.4, R3.5).

    - Subject is exactly ``Complete your onboarding — {org_name}`` (R3.2).
    - Body opens with a first-name greeting (R3.3).
    - A prominent CTA button links to ``onboard_url`` (``/onboard/{token}``),
      rendered via ``render_transactional_html`` (R3.4).
    - Copy states the link expires in 7 days (R3.5).

    Pure: builds and returns an :class:`EmailMessage`, performs no I/O.
    """
    greeting_name = (staff_first_name or "").strip() or "there"
    subject = f"Complete your onboarding — {org_name}"

    text_body = (
        f"Kia ora {greeting_name},\n\n"
        f"{org_name} has invited you to complete your staff onboarding. "
        f"Use the secure link below to enter your personal, bank, tax, and "
        f"working-rights details — no login required.\n\n"
        f"{onboard_url}\n\n"
        f"This link expires in {_LINK_TTL_DAYS} days. If it expires before "
        f"you finish, contact your employer and they can send you a new one.\n\n"
        f"Ngā mihi,\n{org_name}"
    )
    html_body = render_transactional_html(
        text_body,
        subject=subject,
        cta_url=onboard_url,
        cta_label=_INVITE_CTA_LABEL,
    )
    return EmailMessage(
        to_email=to_email,
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        org_id=org_id,
    )


def compose_confirmation_email(
    *,
    staff_email: str,
    staff_first_name: str,
    org_name: str,
    org_id: uuid.UUID | None = None,
) -> EmailMessage:
    """Compose the staff **completion confirmation** email (R15.2).

    Addressed to the staff member by first name, thanks them for completing
    onboarding, and names the organisation. Pure: returns an
    :class:`EmailMessage` and performs no I/O.
    """
    greeting_name = (staff_first_name or "").strip() or "there"
    subject = f"Thanks for completing your onboarding — {org_name}"

    text_body = (
        f"Kia ora {greeting_name},\n\n"
        f"Thank you for completing your onboarding with {org_name}. "
        f"Your details have been submitted successfully and there is nothing "
        f"more you need to do.\n\n"
        f"If anything changes or you need to update your details, please "
        f"contact your employer.\n\n"
        f"Ngā mihi,\n{org_name}"
    )
    html_body = render_transactional_html(text_body, subject=subject)
    return EmailMessage(
        to_email=staff_email,
        to_name=greeting_name,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        org_id=org_id,
    )


def compose_org_completion_email(
    *,
    to_email: str,
    staff_name: str,
    org_name: str,
    staff_detail_url: str,
    org_id: uuid.UUID | None = None,
) -> EmailMessage:
    """Compose the **org-notification** email sent to each admin (R16.3).

    Tells the recipient that ``staff_name`` finished onboarding and links to
    the staff detail page. Pure: returns an :class:`EmailMessage`.
    """
    display_name = staff_name.strip() or "A staff member"
    subject = f"{display_name} completed onboarding — {org_name}"

    text_body = (
        f"Kia ora,\n\n"
        f"{display_name} has completed their staff onboarding for {org_name}. "
        f"You can review their submitted details on their staff page:\n\n"
        f"{staff_detail_url}\n\n"
        f"Ngā mihi,\nOraInvoice"
    )
    html_body = render_transactional_html(
        text_body,
        subject=subject,
        cta_url=staff_detail_url,
        cta_label="View staff details",
    )
    return EmailMessage(
        to_email=to_email,
        to_name="",
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        org_id=org_id,
    )


# ---------------------------------------------------------------------------
# Recipient resolution (R16.1, R16.3)
# ---------------------------------------------------------------------------


async def resolve_org_notification_recipients(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[str]:
    """Resolve the onboarding-link senders' email addresses for ``org_id``.

    Queries the ``users`` table (``app.modules.auth.models.User``) for active
    ``org_admin`` / ``branch_admin`` users in the org, selecting ``email`` and
    **deduping by email** (case-insensitive, preserving first-seen order).
    Returns an empty list when there are none.

    ``branch_admin`` is a real built-in role gated behind the
    ``branch_management`` module — orgs without that module simply have no
    ``branch_admin`` users, so only ``org_admin`` users are returned, which
    is correct (R16.3). Org-scoped via ``org_id`` alone (R16.4).
    """
    stmt = select(User.email).where(
        User.org_id == org_id,
        User.role.in_(("org_admin", "branch_admin")),
        User.is_active.is_(True),
    )
    rows = (await db.execute(stmt)).scalars().all()

    seen: set[str] = set()
    recipients: list[str] = []
    for email in rows:
        if not email or not email.strip():
            continue
        key = email.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email.strip())
    return recipients


# ---------------------------------------------------------------------------
# Public entry point — invite email (R3)
# ---------------------------------------------------------------------------


async def send_onboarding_email(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff: StaffMember,
    token: str,
    base_url: str | None = None,
) -> OnboardingDeliveryResult:
    """Email the onboarding invite link to a newly-created staff member (R3).

    Mirrors :func:`roster_delivery.send_roster_email`:

    1. Refuse with ``onboarding_email_required`` when ``staff.email`` is
       null/blank (belt-and-braces — the router also gates this, R1.2).
    2. Compose the message via :func:`compose_onboarding_email` (subject,
       first-name greeting, CTA to ``/onboard/{token}``, 7-day-expiry copy).
    3. Dispatch via the unified ``send_email`` with
       ``dlq_task_name='onboarding_email'`` so a chain-exhausted send lands in
       the dead-letter queue for replay (R3.1).
    4. Return :class:`OnboardingDeliveryResult` — **never raises** on a
       provider failure (R3.6); the router folds the result into the response.

    The audit-log row is written by the caller (router), keeping the acting
    user-id at the API boundary, matching the roster-delivery convention.
    """
    if not staff.email or not staff.email.strip():
        return OnboardingDeliveryResult(ok=False, error_code=ERROR_NO_EMAIL)

    org_name = await _load_org_name(db, org_id)
    onboard_url = build_onboard_url(token, base_url)

    message = compose_onboarding_email(
        to_email=staff.email.strip(),
        to_name=_staff_to_name(staff),
        staff_first_name=staff.first_name or staff.name or "",
        org_name=org_name,
        onboard_url=onboard_url,
        org_id=org_id,
    )

    result = await send_email(
        db,
        message,
        org_sender_name=org_name,
        dlq_task_name="onboarding_email",
        dlq_task_args={
            "staff_id": str(staff.id),
            "org_id": str(org_id),
            "token": token,
        },
    )

    if result.success:
        return OnboardingDeliveryResult(ok=True, message_id=result.message_id)

    logger.warning(
        "onboarding_email send failed: org=%s staff=%s error=%s attempts=%d",
        org_id,
        staff.id,
        result.error,
        len(result.attempts),
    )
    return OnboardingDeliveryResult(ok=False, error_code=ERROR_SEND_FAILED)


# ---------------------------------------------------------------------------
# Public entry point — staff confirmation email (R15, best-effort)
# ---------------------------------------------------------------------------


async def send_onboarding_confirmation_email(
    db: AsyncSession,
    *,
    staff_email: str,
    staff_first_name: str,
    org_name: str,
    org_id: uuid.UUID | None = None,
) -> OnboardingDeliveryResult:
    """Best-effort thank-you email to the staff member after submit (R15).

    Composes the confirmation via :func:`compose_confirmation_email` (org name
    + a friendly thank-you addressed to the staff member, R15.2) and dispatches
    it. The whole body is wrapped in ``try/except`` so **any** failure — a
    missing address, a provider exhaustion, or an unexpected error — is logged
    and swallowed; this never raises and never affects the already-successful
    submission (R15.4). Dispatched only on final submit, never on draft save
    (the draft handler does not call this — R15.5).
    """
    try:
        if not staff_email or not staff_email.strip():
            logger.info(
                "onboarding confirmation skipped: no staff email (org=%s)", org_id
            )
            return OnboardingDeliveryResult(ok=False, error_code=ERROR_NO_EMAIL)

        message = compose_confirmation_email(
            staff_email=staff_email.strip(),
            staff_first_name=staff_first_name,
            org_name=org_name,
            org_id=org_id,
        )
        result = await send_email(
            db,
            message,
            org_sender_name=org_name,
            dlq_task_name="onboarding_confirmation_email",
        )
        if result.success:
            return OnboardingDeliveryResult(ok=True, message_id=result.message_id)

        logger.warning(
            "onboarding confirmation email failed: org=%s error=%s",
            org_id,
            result.error,
        )
        return OnboardingDeliveryResult(ok=False, error_code=ERROR_SEND_FAILED)
    except Exception as exc:  # noqa: BLE001 — best-effort, must never raise (R15.4)
        logger.warning(
            "onboarding confirmation email swallowed exception: org=%s err=%s",
            org_id,
            exc,
        )
        return OnboardingDeliveryResult(ok=False, error_code=ERROR_SEND_FAILED)


# ---------------------------------------------------------------------------
# Public entry point — org completion notification (R16, best-effort)
# ---------------------------------------------------------------------------


async def notify_org_onboarding_complete(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff: StaffMember,
    base_url: str | None = None,
) -> None:
    """Notify the org's onboarding-link senders that ``staff`` finished (R16).

    Two parts, both **best-effort** (never raises, R16.6):

    (a) Create the in-app notification via ``create_in_app_notification`` for
        the ``org_admin`` / ``branch_admin`` audience, org-scoped to ``org_id``,
        linking to the staff detail page (R16.1, R16.2, R16.4). The helper
        never raises (it catches and logs internally).

    (b) Resolve active ``org_admin`` / ``branch_admin`` users for the org
        (deduped by email) and email each one that the staff member completed
        onboarding, with a link to the staff detail page (R16.3). Every send is
        wrapped in ``try/except`` so a failure is logged and swallowed.

    The notification is organisation-scoped only — ``StaffMember`` has no
    scalar ``branch_id`` (staff↔branch linkage lives in
    ``staff_location_assignments``) and ``create_in_app_notification`` has no
    branch parameter, so org-scoping to ``org_id`` satisfies R16.4 and
    branch-level targeting is out of scope.

    Dispatched only on final submit, never on draft save (R16.5) — the draft
    handler does not call this.
    """
    first_name = (staff.first_name or staff.name or "").strip() or "A staff member"
    staff_name = _staff_to_name(staff) or first_name
    staff_detail_url = build_staff_detail_url(staff.id, base_url)

    # (a) In-app notification — never raises (helper catches internally).
    try:
        await create_in_app_notification(
            db,
            org_id=org_id,
            category="staff_onboarding",
            severity="success",
            title=f"{first_name} completed onboarding",
            body=f"{first_name} completed their onboarding",
            audience_roles=["org_admin", "branch_admin"],
            link_url=f"/staff/{staff.id}",
            entity_type="staff_member",
            entity_id=staff.id,
        )
    except Exception as exc:  # noqa: BLE001 — defensive; helper already never raises
        logger.warning(
            "onboarding completion in-app notification swallowed exception: "
            "org=%s staff=%s err=%s",
            org_id,
            staff.id,
            exc,
        )

    # (b) Email each org_admin / branch_admin recipient — best-effort.
    try:
        org_name = await _load_org_name(db, org_id)
        recipients = await resolve_org_notification_recipients(db, org_id=org_id)
    except Exception as exc:  # noqa: BLE001 — recipient lookup must not break submit
        logger.warning(
            "onboarding completion recipient resolution failed: org=%s err=%s",
            org_id,
            exc,
        )
        return

    for recipient_email in recipients:
        try:
            message = compose_org_completion_email(
                to_email=recipient_email,
                staff_name=staff_name,
                org_name=org_name,
                staff_detail_url=staff_detail_url,
                org_id=org_id,
            )
            await send_email(
                db,
                message,
                org_sender_name=org_name,
                dlq_task_name="onboarding_org_complete_email",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort per recipient (R16.6)
            logger.warning(
                "onboarding completion email to org admin swallowed exception: "
                "org=%s recipient=%s err=%s",
                org_id,
                recipient_email,
                exc,
            )
