"""Roster delivery orchestration for the Staff Management module.

Phase 1 ships both the email-roster path (task C3) and the SMS-roster
path (task C6) here. Keeping the delivery logic out of ``router.py``
and ``service.py`` lets both per-staff endpoints (R8, R9) and the
Friday-afternoon broadcast scheduled task (R10, task D1) share the
same code path.

**Validates: Requirements R8, R9** (Phase 1 tasks C3, C6).
"""

from __future__ import annotations

import logging
import pathlib
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timezone_utils import to_org_timezone
from app.integrations.email_sender import EmailMessage, send_email
from app.integrations.sms_sender import send_sms
from app.modules.admin.models import Organisation
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.staff.roster_tokens import get_or_create_viewer_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reasons returned by the delivery helpers when the precondition checks
# refuse a send. These mirror the strings the API surface returns to
# the caller (R8.2/R8.5 for email; R9.2 for SMS).
# ---------------------------------------------------------------------------

REASON_NO_EMAIL = "no_email"
REASON_NO_PHONE = "no_phone"
REASON_OPT_OUT = "opt_out"
REASON_NO_SHIFTS_IN_WEEK = "no_shifts_in_week"
REASON_SEND_FAILED = "send_failed"


@dataclass
class RosterDeliveryResult:
    """Return value of the ``send_roster_*`` helpers.

    ``ok`` is the success flag; on success ``message_id`` carries the
    provider's id and ``reason`` is None. On a precondition refusal
    (no email/phone, opt-out, no shifts) ``reason`` is one of the
    constants above and the caller should map it to HTTP 422 per R8.2 /
    R8.5 / R9.2. On a downstream send failure (provider chain
    exhausted) ``reason='send_failed'`` and ``ok=False``.

    ``audit_extras`` is populated by the SMS path with the encoding +
    segment count + masked phone number that the spec requires the
    audit row's ``after_value`` JSONB to capture (R9.3, P1-N12). The
    email path leaves it as an empty dict.
    """

    ok: bool
    message_id: str | None = None
    reason: str | None = None
    audit_extras: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Jinja environment — module-level so the template loader / autoescape
# config is built once per process. Mirrors the pattern in
# ``app/modules/job_cards/snapshot_renderer.py``.
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent
    / "templates"
    / "email"
)


def _build_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )


_JINJA_ENV: Environment | None = None


def _get_jinja_env() -> Environment:
    global _JINJA_ENV
    if _JINJA_ENV is None:
        _JINJA_ENV = _build_jinja_env()
    return _JINJA_ENV


# ---------------------------------------------------------------------------
# Schedule entry loading (R8.3)
# ---------------------------------------------------------------------------


async def _load_week_entries(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
) -> list[ScheduleEntry]:
    """Return ``schedule_entries`` for ``staff_id`` in the 7-day window
    starting on ``week_start``.

    The ``schedule_entries.start_time`` column is timezone-aware (UTC);
    we compare against UTC midnight on ``week_start`` and ``week_start
    + 7 days``. The display layer converts to the org's local timezone
    via ``to_org_timezone``.
    """
    week_end = week_start + timedelta(days=7)
    start_dt = datetime.combine(week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(week_end, time.min, tzinfo=timezone.utc)

    stmt = (
        select(ScheduleEntry)
        .where(
            ScheduleEntry.org_id == org_id,
            ScheduleEntry.staff_id == staff_id,
            ScheduleEntry.start_time >= start_dt,
            ScheduleEntry.start_time < end_dt,
        )
        .order_by(ScheduleEntry.start_time)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Template rendering helpers
# ---------------------------------------------------------------------------


def _format_entries_for_template(
    entries: list[ScheduleEntry], org_timezone: str,
) -> list[dict[str, Any]]:
    """Build the per-row template context.

    Each row converts the UTC ``start_time`` / ``end_time`` to the
    org's local timezone for display, falling back to UTC if the
    conversion fails (defence-in-depth — ``to_org_timezone`` already
    falls back to UTC on a bad zone name).
    """
    rendered: list[dict[str, Any]] = []
    for entry in entries:
        start_local = to_org_timezone(entry.start_time, org_timezone) or entry.start_time
        end_local = to_org_timezone(entry.end_time, org_timezone) or entry.end_time
        rendered.append({
            "day_label": start_local.strftime("%a %d %b"),
            "start_label": start_local.strftime("%H:%M"),
            "end_label": end_local.strftime("%H:%M"),
            "notes": entry.notes or entry.title or "",
        })
    return rendered


def _render_email_html(
    *,
    staff: StaffMember,
    entries: list[ScheduleEntry],
    week_start: date,
    org_name: str,
    org_timezone: str,
) -> str:
    """Render the ``staff_roster.html`` Jinja template."""
    env = _get_jinja_env()
    template = env.get_template("staff_roster.html")
    return template.render(
        first_name=staff.first_name or staff.name or "",
        week_start_label=week_start.strftime("%a %d %b %Y"),
        entries=_format_entries_for_template(entries, org_timezone),
        org_name=org_name,
        org_timezone=org_timezone,
    )


def _render_email_text(
    *,
    staff: StaffMember,
    entries: list[ScheduleEntry],
    week_start: date,
    org_timezone: str,
) -> str:
    """Plain-text alternative body — mirrors the HTML layout.

    Most modern clients prefer the HTML part, but some firewalls and
    legacy clients render only ``text/plain``; supplying both improves
    deliverability and keeps the message readable everywhere.
    """
    lines: list[str] = []
    lines.append(f"Kia ora {staff.first_name or staff.name or ''},")
    lines.append("")
    lines.append(
        f"Here is your roster for the week starting "
        f"{week_start.strftime('%a %d %b %Y')}."
    )
    lines.append("")
    if entries:
        for entry in entries:
            start_local = (
                to_org_timezone(entry.start_time, org_timezone) or entry.start_time
            )
            end_local = (
                to_org_timezone(entry.end_time, org_timezone) or entry.end_time
            )
            note_suffix = f" — {entry.notes or entry.title}" if (entry.notes or entry.title) else ""
            lines.append(
                f"- {start_local.strftime('%a %d %b')}  "
                f"{start_local.strftime('%H:%M')}–{end_local.strftime('%H:%M')}"
                f"{note_suffix}"
            )
        lines.append("")
        lines.append(f"Times shown in {org_timezone}.")
    else:
        lines.append("No shifts scheduled for this week.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Org lookup
# ---------------------------------------------------------------------------


async def _load_org(
    db: AsyncSession, org_id: uuid.UUID,
) -> tuple[str, str]:
    """Return ``(org_name, org_timezone)`` with sensible defaults."""
    res = await db.execute(
        select(Organisation.name, Organisation.timezone).where(
            Organisation.id == org_id,
        )
    )
    row = res.first()
    if row is None:
        return ("your workshop", "UTC")
    return (row[0] or "your workshop", row[1] or "UTC")


# ---------------------------------------------------------------------------
# Public entry point (R8)
# ---------------------------------------------------------------------------


async def send_roster_email(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff: StaffMember,
    week_start: date,
) -> RosterDeliveryResult:
    """Email this week's roster to a staff member.

    Implements R8 / task C3:

    1. Refuse with ``no_email`` when ``staff.email`` is null/blank.
    2. Refuse with ``opt_out`` when ``weekly_roster_email_enabled=False``.
    3. Refuse with ``no_shifts_in_week`` when zero schedule entries fall
       inside the ``[week_start, week_start+7d)`` window.
    4. Render the ``staff_roster.html`` Jinja template.
    5. Call the unified ``send_email`` with
       ``dlq_task_name='roster_email'`` so a chain-exhausted send lands
       in the dead-letter queue for replay.
    6. Return ``RosterDeliveryResult`` — the router maps this to the
       HTTP response (422 for refusal, 200 with ``ok=true`` on success,
       200 with ``ok=false, reason='send_failed'`` on chain exhaustion).

    The audit-log row is written by the **router** rather than this
    helper, so the calling user-id stays at the API boundary and the
    helper can be reused by the scheduled task (D1) which has no acting
    user. The router then is responsible for ``write_audit_log`` with
    ``action='roster.emailed'`` (R8.4).
    """
    # ------------------------------------------------------------------
    # Precondition checks (R8.2, R8.5).
    # ------------------------------------------------------------------
    if not staff.email or not staff.email.strip():
        return RosterDeliveryResult(ok=False, reason=REASON_NO_EMAIL)
    if not staff.weekly_roster_email_enabled:
        return RosterDeliveryResult(ok=False, reason=REASON_OPT_OUT)

    entries = await _load_week_entries(
        db, org_id=org_id, staff_id=staff.id, week_start=week_start,
    )
    if not entries:
        return RosterDeliveryResult(ok=False, reason=REASON_NO_SHIFTS_IN_WEEK)

    org_name, org_timezone = await _load_org(db, org_id)

    # ------------------------------------------------------------------
    # Render template + compose message (R8.3).
    # ------------------------------------------------------------------
    html_body = _render_email_html(
        staff=staff,
        entries=entries,
        week_start=week_start,
        org_name=org_name,
        org_timezone=org_timezone,
    )
    text_body = _render_email_text(
        staff=staff,
        entries=entries,
        week_start=week_start,
        org_timezone=org_timezone,
    )

    subject = (
        f"Your roster — week of {week_start.strftime('%a %d %b %Y')}"
    )
    to_name = (
        f"{staff.first_name or ''} {staff.last_name or ''}".strip()
        or (staff.name or "")
    )
    message = EmailMessage(
        to_email=staff.email.strip(),
        to_name=to_name,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        org_id=org_id,
    )

    # ------------------------------------------------------------------
    # Dispatch via the unified sender. ``dlq_task_name='roster_email'``
    # routes a chain-exhausted send to the DLQ for replay.
    # ------------------------------------------------------------------
    result = await send_email(
        db,
        message,
        org_sender_name=org_name,
        dlq_task_name="roster_email",
        dlq_task_args={
            "staff_id": str(staff.id),
            "week_start": week_start.isoformat(),
            "org_id": str(org_id),
        },
    )

    if result.success:
        return RosterDeliveryResult(
            ok=True, message_id=result.message_id, reason=None,
        )

    logger.warning(
        "roster_email send failed: org=%s staff=%s error=%s attempts=%d",
        org_id,
        staff.id,
        result.error,
        len(result.attempts),
    )
    return RosterDeliveryResult(
        ok=False, message_id=None, reason=REASON_SEND_FAILED,
    )


# ---------------------------------------------------------------------------
# SMS encoding detection + body composition (R9, G7)
# ---------------------------------------------------------------------------

# GSM-7 default alphabet per ETSI GSM 03.38. Each character occupies a
# single 7-bit slot. Any character outside this set + the extension set
# below downgrades the entire SMS to UCS-2 (16-bit) encoding.
_GSM7_CHARSET: frozenset[str] = frozenset(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789"
    ":;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyz"
    "äöñüà"
)

# GSM-7 extended characters — also 7-bit safe but each takes TWO
# 7-bit slots (one ESC byte + the symbol) when computing the encoded
# length.
_GSM7_EXTENDED: frozenset[str] = frozenset("|^€{}[]~\\")


def _detect_encoding_and_segments(body: str) -> tuple[str, int]:
    """Return ``(encoding, segments)`` for the SMS body.

    Encoding is one of ``"gsm7"`` or ``"ucs2"``. Segments is the number
    of concatenated SMS parts the message will occupy:

    - GSM-7 single-segment limit: 160 chars (or 140 7-bit slots when
      counting extended characters which take 2 slots each).
    - GSM-7 multi-segment limit: 153 chars per segment (the 7-byte
      User Data Header steals room from each part).
    - UCS-2 single-segment limit: 70 characters.
    - UCS-2 multi-segment limit: 67 characters per segment.

    The detection is conservative: any non-GSM-7 character in the body
    (e.g. a Māori macron ``ā``) downgrades the whole message to UCS-2.
    The spec forbids transliteration (R9.3 / G7) — Māori macrons must
    be sent as-is, even if it costs an extra segment.
    """
    is_gsm7 = all(c in _GSM7_CHARSET or c in _GSM7_EXTENDED for c in body)
    if is_gsm7:
        # Each extended character takes two 7-bit slots.
        slot_count = sum(2 if c in _GSM7_EXTENDED else 1 for c in body)
        if slot_count <= 160:
            return ("gsm7", 1)
        # ``ceil(slot_count / 153)`` — the standard concatenated-SMS
        # segment size for GSM-7 with the User Data Header in place.
        segments = (slot_count + 152) // 153
        return ("gsm7", segments)
    # UCS-2: ``len`` counts code-points. Surrogate pairs in BMP-only
    # ranges aren't an issue for the strings we'd ever build here
    # (roster names + URLs).
    char_count = len(body)
    if char_count <= 70:
        return ("ucs2", 1)
    segments = (char_count + 66) // 67
    return ("ucs2", segments)


def _mask_phone_number(phone: str | None) -> str:
    """Return a logged-friendly ``*****1234`` form of a phone number.

    Used for the audit log row (R9.3 — ``phone_number_masked`` on
    ``after_value``) so admins can correlate audit rows with
    notification_log entries without leaking the full destination.
    """
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit())
    if not digits:
        return ""
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def compose_roster_sms_body(
    staff: StaffMember,
    entries: list[ScheduleEntry],
    viewer_url: str,
) -> str:
    """Compose the SMS body for a staff roster send (R9.3).

    Template per the requirement:

        ``Kia ora {first_name}, your this week roster: {N} shifts,
        {first_shift_summary}. Full schedule: {tokenised_link}``

    Aim is to fit a single 160-char GSM-7 segment for ASCII names. A
    Māori macron in ``first_name`` (``ā ē ī ō ū``) downgrades the
    whole body to UCS-2 multi-part — that's accepted (R9.3), never
    transliterate.

    The first-shift summary is rendered as ``"<weekday> <HH:MM>"`` to
    fit the tight character budget. The display layer (public viewer
    URL) carries the full breakdown.
    """
    first_name = (staff.first_name or staff.name or "").strip() or "there"
    n_shifts = len(entries)
    shifts_word = "shift" if n_shifts == 1 else "shifts"

    if entries:
        first = entries[0]
        first_shift_summary = first.start_time.strftime("%a %H:%M")
    else:
        first_shift_summary = "no shifts"

    return (
        f"Kia ora {first_name}, your this week roster: "
        f"{n_shifts} {shifts_word}, {first_shift_summary}. "
        f"Full schedule: {viewer_url}"
    )


# ---------------------------------------------------------------------------
# Public entry point — SMS (R9, task C6)
# ---------------------------------------------------------------------------


async def send_roster_sms(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff: StaffMember,
    week_start: date,
    viewer_base_url: str,
) -> RosterDeliveryResult:
    """SMS this week's roster to a staff member.

    Implements R9 / task C6:

    1. Refuse with ``no_phone`` when ``staff.phone`` is null/blank
       (R9.2).
    2. Refuse with ``opt_out`` when ``weekly_roster_sms_enabled=False``
       (R9.2).
    3. Refuse with ``no_shifts_in_week`` when zero schedule entries
       fall inside the ``[week_start, week_start+7d)`` window (mirrors
       the email path's R8.5 — same precondition applies to SMS
       because there's nothing useful to send).
    4. Get-or-create the public viewer token (one-per-(staff, week))
       and assemble the public URL.
    5. Compose the 160-char body via :func:`compose_roster_sms_body`.
    6. Detect encoding + segment count via
       :func:`_detect_encoding_and_segments` for the audit row's
       ``after_value`` JSONB (R9.3 / P1-N12 — Māori macrons trigger
       UCS-2, possibly multi-part).
    7. Call :func:`app.integrations.sms_sender.send_sms` with
       ``dlq_task_name='roster_sms'`` so a chain-exhausted send lands
       in the dead-letter queue for replay.
    8. Return :class:`RosterDeliveryResult` with the encoding +
       segments + masked phone number on ``audit_extras`` so the
       router can fold them into the audit row.

    The audit-log row itself is written by the **router** rather than
    this helper, so the calling user-id stays at the API boundary and
    the helper can be reused by the scheduled task (D1) which has no
    acting user.
    """
    # ------------------------------------------------------------------
    # Precondition checks (R9.2).
    # ------------------------------------------------------------------
    phone = (staff.phone or "").strip()
    if not phone:
        return RosterDeliveryResult(ok=False, reason=REASON_NO_PHONE)
    if not staff.weekly_roster_sms_enabled:
        return RosterDeliveryResult(ok=False, reason=REASON_OPT_OUT)

    entries = await _load_week_entries(
        db, org_id=org_id, staff_id=staff.id, week_start=week_start,
    )
    if not entries:
        return RosterDeliveryResult(ok=False, reason=REASON_NO_SHIFTS_IN_WEEK)

    # ------------------------------------------------------------------
    # Public viewer link (R9.4) — get-or-create per (staff, week) so
    # re-sending the same week reuses the same URL.
    # ------------------------------------------------------------------
    token_obj = await get_or_create_viewer_token(
        db, org_id=org_id, staff_id=staff.id, week_start=week_start,
    )
    viewer_url = f"{viewer_base_url.rstrip('/')}/{token_obj.token}"

    # ------------------------------------------------------------------
    # Compose body + classify encoding/segments for the audit row
    # (R9.3 / G7 / P1-N12).
    # ------------------------------------------------------------------
    body = compose_roster_sms_body(staff, entries, viewer_url)
    encoding, segments = _detect_encoding_and_segments(body)
    audit_extras: dict[str, Any] = {
        "encoding": encoding,
        "segments": segments,
        "phone_number_masked": _mask_phone_number(phone),
    }

    # ------------------------------------------------------------------
    # Dispatch via the unified SMS wrapper (R9.5). DLQ for replay on
    # provider-chain exhaustion mirrors the email path.
    # ------------------------------------------------------------------
    result = await send_sms(
        db,
        to_phone=phone,
        body=body,
        dlq_task_name="roster_sms",
        dlq_task_args={
            "staff_id": str(staff.id),
            "week_start": week_start.isoformat(),
            "org_id": str(org_id),
        },
        org_id=org_id,
    )

    if result.ok:
        return RosterDeliveryResult(
            ok=True,
            message_id=result.message_id,
            reason=None,
            audit_extras=audit_extras,
        )

    logger.warning(
        "roster_sms send failed: org=%s staff=%s reason=%s provider=%s",
        org_id,
        staff.id,
        result.reason,
        result.provider_key,
    )
    return RosterDeliveryResult(
        ok=False,
        message_id=None,
        reason=REASON_SEND_FAILED,
        audit_extras=audit_extras,
    )
