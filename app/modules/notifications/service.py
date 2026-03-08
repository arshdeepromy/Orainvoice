"""Service layer for email template customisation and delivery tracking.

Provides CRUD operations for notification templates per organisation,
email delivery logging, log querying, bounce flagging on customers,
and locale-aware template rendering.

Requirements: 34.1, 34.2, 34.3, 35.1, 35.2, 35.3
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationLog, NotificationTemplate
from app.modules.notifications.schemas import (
    EMAIL_TEMPLATE_TYPES,
    DEFAULT_SUBJECTS,
    TEMPLATE_VARIABLES,
    get_default_body_blocks,
)
from app.modules.admin.service import increment_sms_usage

logger = logging.getLogger(__name__)


def _template_to_dict(tpl: NotificationTemplate) -> dict[str, Any]:
    """Convert a NotificationTemplate ORM instance to a plain dict."""
    return {
        "id": str(tpl.id),
        "template_type": tpl.template_type,
        "channel": tpl.channel,
        "subject": tpl.subject,
        "body_blocks": tpl.body_blocks if tpl.body_blocks else [],
        "is_enabled": tpl.is_enabled,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else "",
    }


async def _get_org_locale(db: AsyncSession, *, org_id: uuid.UUID) -> str:
    """Return the organisation's configured locale, defaulting to ``'en'``.

    The locale column stores values like ``'en'``, ``'fr'``, ``'en-NZ'``, etc.
    We extract the language code (the part before any hyphen) for template
    variant lookup.
    """
    from app.modules.admin.models import Organisation

    stmt = select(Organisation.locale).where(Organisation.id == org_id)
    result = await db.execute(stmt)
    locale_value = result.scalar_one_or_none()

    if not locale_value:
        return "en"

    # Extract language code: "en-NZ" -> "en", "fr" -> "fr"
    lang = locale_value.split("-")[0].lower()
    return lang if lang else "en"


async def get_template_for_locale(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_type: str,
    channel: str = "email",
) -> dict[str, Any] | None:
    """Get a template with locale-aware selection and English fallback.

    Checks the organisation's configured locale and looks for a
    locale-specific template variant (e.g., ``invoice_issued_fr``).
    Falls back to the default English template if no translation exists.

    Requirements: 2.21
    """
    locale = await _get_org_locale(db, org_id=org_id)

    # For English or unset locale, use the default template directly
    if locale == "en":
        if channel == "sms":
            return await get_sms_template(db, org_id=org_id, template_type=template_type)
        return await get_template(db, org_id=org_id, template_type=template_type)

    # Look for a locale-specific variant (e.g., "invoice_issued_fr")
    locale_template_type = f"{template_type}_{locale}"

    if channel == "sms":
        await _seed_sms_templates(db, org_id=org_id)
    else:
        await _seed_email_templates(db, org_id=org_id)

    stmt = select(NotificationTemplate).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.template_type == locale_template_type,
        NotificationTemplate.channel == channel,
    )
    result = await db.execute(stmt)
    tpl = result.scalar_one_or_none()

    if tpl is not None:
        logger.info(
            "Using locale-specific template %s for org %s (locale=%s)",
            locale_template_type,
            org_id,
            locale,
        )
        if channel == "sms":
            return _sms_template_to_dict(tpl)
        return _template_to_dict(tpl)

    # Fall back to the default English template
    logger.debug(
        "No locale-specific template %s found for org %s, falling back to %s",
        locale_template_type,
        org_id,
        template_type,
    )
    if channel == "sms":
        return await get_sms_template(db, org_id=org_id, template_type=template_type)
    return await get_template(db, org_id=org_id, template_type=template_type)


async def _seed_email_templates(
    db: AsyncSession, *, org_id: uuid.UUID
) -> None:
    """Create default email templates for an org if none exist.

    This ensures all 16 template types are available on first access.
    Requirements: 34.3
    """
    count_stmt = select(func.count(NotificationTemplate.id)).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.channel == "email",
    )
    existing_count = (await db.execute(count_stmt)).scalar() or 0

    if existing_count >= len(EMAIL_TEMPLATE_TYPES):
        return  # Already seeded

    # Find which types already exist
    existing_stmt = select(NotificationTemplate.template_type).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.channel == "email",
    )
    existing_types = set(
        (await db.execute(existing_stmt)).scalars().all()
    )

    for ttype in EMAIL_TEMPLATE_TYPES:
        if ttype in existing_types:
            continue
        tpl = NotificationTemplate(
            org_id=org_id,
            template_type=ttype,
            channel="email",
            subject=DEFAULT_SUBJECTS.get(ttype, ""),
            body_blocks=get_default_body_blocks(ttype),
            is_enabled=False,
        )
        db.add(tpl)

    await db.flush()


async def list_templates(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """List all email templates for an organisation.

    Seeds default templates on first access.
    Requirements: 34.1, 34.3
    """
    await _seed_email_templates(db, org_id=org_id)

    stmt = (
        select(NotificationTemplate)
        .where(
            NotificationTemplate.org_id == org_id,
            NotificationTemplate.channel == "email",
        )
        .order_by(NotificationTemplate.template_type)
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()

    return {
        "templates": [_template_to_dict(t) for t in templates],
        "total": len(templates),
        "available_variables": TEMPLATE_VARIABLES,
    }


async def get_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_type: str,
) -> dict[str, Any] | None:
    """Get a single email template by type.

    Seeds defaults if needed.
    Requirements: 34.1
    """
    await _seed_email_templates(db, org_id=org_id)

    stmt = select(NotificationTemplate).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.template_type == template_type,
        NotificationTemplate.channel == "email",
    )
    result = await db.execute(stmt)
    tpl = result.scalar_one_or_none()

    if tpl is None:
        return None

    return _template_to_dict(tpl)


async def update_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_type: str,
    subject: str | None = None,
    body_blocks: list[dict[str, Any]] | None = None,
    is_enabled: bool | None = None,
) -> dict[str, Any] | None:
    """Update an email template for an organisation.

    Requirements: 34.1, 34.2
    """
    await _seed_email_templates(db, org_id=org_id)

    stmt = select(NotificationTemplate).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.template_type == template_type,
        NotificationTemplate.channel == "email",
    )
    result = await db.execute(stmt)
    tpl = result.scalar_one_or_none()

    if tpl is None:
        return None

    if subject is not None:
        tpl.subject = subject
    if body_blocks is not None:
        tpl.body_blocks = body_blocks
    if is_enabled is not None:
        tpl.is_enabled = is_enabled

    await db.flush()
    await db.refresh(tpl)

    return _template_to_dict(tpl)


def render_template_preview(
    *,
    subject: str | None,
    body_blocks: list[dict[str, Any]],
) -> dict[str, str]:
    """Render a template preview with sample variable values.

    Requirements: 34.2
    """
    sample_values = {
        "customer_first_name": "Jane",
        "customer_last_name": "Smith",
        "customer_email": "jane@example.com",
        "invoice_number": "INV-0042",
        "total_due": "$150.00",
        "due_date": "15/01/2025",
        "payment_link": "https://pay.example.com/inv-0042",
        "org_name": "Workshop Pro Demo",
        "org_phone": "09 555 1234",
        "org_email": "info@workshoppro.co.nz",
        "vehicle_rego": "ABC123",
        "vehicle_make": "Toyota",
        "vehicle_model": "Corolla",
        "expiry_date": "28/02/2025",
        "user_name": "John Doe",
        "reset_link": "https://app.example.com/reset/abc123",
        "signup_link": "https://app.example.com/signup/abc123",
    }

    def _replace_vars(text: str) -> str:
        """Replace {{variable}} placeholders with sample values."""
        def _replacer(match: re.Match) -> str:
            var_name = match.group(1).strip()
            return sample_values.get(var_name, match.group(0))
        return re.sub(r"\{\{(\w+)\}\}", _replacer, text)

    rendered_subject = _replace_vars(subject or "")

    html_parts: list[str] = []
    for block in body_blocks:
        btype = block.get("type", "text")
        content = _replace_vars(block.get("content", ""))
        url = _replace_vars(block.get("url", ""))

        if btype == "header":
            html_parts.append(f"<h2>{content}</h2>")
        elif btype == "text":
            html_parts.append(f"<p>{content}</p>")
        elif btype == "button":
            html_parts.append(
                f'<a href="{url}" style="display:inline-block;padding:10px 20px;'
                f'background:#007bff;color:#fff;text-decoration:none;border-radius:4px">'
                f"{content}</a>"
            )
        elif btype == "image":
            html_parts.append(f'<img src="{url}" alt="{content}" style="max-width:100%" />')
        elif btype == "divider":
            html_parts.append("<hr />")
        elif btype == "footer":
            html_parts.append(f'<footer style="font-size:12px;color:#666">{content}</footer>')

    return {
        "subject": rendered_subject,
        "html_body": "\n".join(html_parts),
    }


# ---------------------------------------------------------------------------
# Email delivery tracking (Req 35.1, 35.2, 35.3)
# ---------------------------------------------------------------------------


def _log_entry_to_dict(entry: NotificationLog) -> dict[str, Any]:
    """Convert a NotificationLog ORM instance to a plain dict."""
    return {
        "id": str(entry.id),
        "channel": entry.channel,
        "recipient": entry.recipient,
        "template_type": entry.template_type,
        "subject": entry.subject,
        "status": entry.status,
        "error_message": entry.error_message,
        "sent_at": entry.sent_at.isoformat() if entry.sent_at else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
    }


async def log_email_sent(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    recipient: str,
    template_type: str,
    subject: str,
    status: str = "queued",
    channel: str = "email",
    error_message: str | None = None,
    sent_at: datetime | None = None,
) -> dict[str, Any]:
    """Log a sent email to the notification_log table.

    Requirements: 35.1
    """
    entry = NotificationLog(
        org_id=org_id,
        channel=channel,
        recipient=recipient,
        template_type=template_type,
        subject=subject,
        status=status,
        error_message=error_message,
        sent_at=sent_at,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return _log_entry_to_dict(entry)


async def update_log_status(
    db: AsyncSession,
    *,
    log_id: uuid.UUID,
    status: str,
    error_message: str | None = None,
    sent_at: datetime | None = None,
) -> dict[str, Any] | None:
    """Update the delivery status of a notification log entry.

    Requirements: 35.1
    """
    stmt = select(NotificationLog).where(NotificationLog.id == log_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        return None

    entry.status = status
    if error_message is not None:
        entry.error_message = error_message
    if sent_at is not None:
        entry.sent_at = sent_at

    await db.flush()
    await db.refresh(entry)
    return _log_entry_to_dict(entry)


async def list_notification_log(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    page: int = 1,
    page_size: int = 50,
    status_filter: str | None = None,
    channel_filter: str | None = None,
) -> dict[str, Any]:
    """List notification log entries for an organisation.

    Requirements: 35.2
    """
    base = select(NotificationLog).where(NotificationLog.org_id == org_id)
    count_base = select(func.count(NotificationLog.id)).where(
        NotificationLog.org_id == org_id
    )

    if status_filter:
        base = base.where(NotificationLog.status == status_filter)
        count_base = count_base.where(NotificationLog.status == status_filter)
    if channel_filter:
        base = base.where(NotificationLog.channel == channel_filter)
        count_base = count_base.where(NotificationLog.channel == channel_filter)

    total = (await db.execute(count_base)).scalar() or 0

    offset = (page - 1) * page_size
    stmt = base.order_by(NotificationLog.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    entries = result.scalars().all()

    return {
        "entries": [_log_entry_to_dict(e) for e in entries],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def flag_bounced_email_on_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    email_address: str,
) -> int:
    """Flag email_bounced=True on customer records matching the bounced address.

    Returns the number of customer records updated.
    Requirements: 35.3
    """
    from app.modules.customers.models import Customer

    stmt = (
        update(Customer)
        .where(
            Customer.org_id == org_id,
            Customer.email == email_address,
            Customer.email_bounced == False,  # noqa: E712
        )
        .values(email_bounced=True)
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount


# ---------------------------------------------------------------------------
# SMS template management (Req 36.3, 36.4, 36.5, 36.6)
# ---------------------------------------------------------------------------

from app.modules.notifications.schemas import (
    SMS_TEMPLATE_TYPES,
    DEFAULT_SMS_BODIES,
)
from app.integrations.twilio_sms import SMS_CHAR_LIMIT


def _sms_template_to_dict(tpl: NotificationTemplate) -> dict[str, Any]:
    """Convert an SMS NotificationTemplate ORM instance to a plain dict."""
    body_blocks = tpl.body_blocks if tpl.body_blocks else []
    # SMS templates store body as a single text block in body_blocks
    body = ""
    if body_blocks and isinstance(body_blocks, list) and len(body_blocks) > 0:
        body = body_blocks[0].get("content", "") if isinstance(body_blocks[0], dict) else ""
    char_count = len(body)
    return {
        "id": str(tpl.id),
        "template_type": tpl.template_type,
        "channel": "sms",
        "body": body,
        "char_count": char_count,
        "exceeds_limit": char_count > SMS_CHAR_LIMIT,
        "is_enabled": tpl.is_enabled,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else "",
    }


async def _seed_sms_templates(
    db: AsyncSession, *, org_id: uuid.UUID
) -> None:
    """Create default SMS templates for an org if none exist.

    Provides the 4 SMS template types defined in Req 36.4.
    """
    count_stmt = select(func.count(NotificationTemplate.id)).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.channel == "sms",
    )
    existing_count = (await db.execute(count_stmt)).scalar() or 0

    if existing_count >= len(SMS_TEMPLATE_TYPES):
        return

    existing_stmt = select(NotificationTemplate.template_type).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.channel == "sms",
    )
    existing_types = set(
        (await db.execute(existing_stmt)).scalars().all()
    )

    for ttype in SMS_TEMPLATE_TYPES:
        if ttype in existing_types:
            continue
        default_body = DEFAULT_SMS_BODIES.get(ttype, "")
        tpl = NotificationTemplate(
            org_id=org_id,
            template_type=ttype,
            channel="sms",
            subject=None,  # SMS has no subject
            body_blocks=[{"type": "text", "content": default_body}],
            is_enabled=False,
        )
        db.add(tpl)

    await db.flush()


async def list_sms_templates(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """List all SMS templates for an organisation.

    Seeds default SMS templates on first access.
    Requirements: 36.3, 36.4
    """
    await _seed_sms_templates(db, org_id=org_id)

    stmt = (
        select(NotificationTemplate)
        .where(
            NotificationTemplate.org_id == org_id,
            NotificationTemplate.channel == "sms",
        )
        .order_by(NotificationTemplate.template_type)
    )
    result = await db.execute(stmt)
    templates = result.scalars().all()

    return {
        "templates": [_sms_template_to_dict(t) for t in templates],
        "total": len(templates),
        "available_variables": TEMPLATE_VARIABLES,
    }


async def get_sms_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_type: str,
) -> dict[str, Any] | None:
    """Get a single SMS template by type.

    Requirements: 36.3
    """
    await _seed_sms_templates(db, org_id=org_id)

    stmt = select(NotificationTemplate).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.template_type == template_type,
        NotificationTemplate.channel == "sms",
    )
    result = await db.execute(stmt)
    tpl = result.scalar_one_or_none()

    if tpl is None:
        return None

    return _sms_template_to_dict(tpl)


async def update_sms_template(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_type: str,
    body: str | None = None,
    is_enabled: bool | None = None,
) -> dict[str, Any] | None:
    """Update an SMS template for an organisation.

    Requirements: 36.3, 36.5
    """
    await _seed_sms_templates(db, org_id=org_id)

    stmt = select(NotificationTemplate).where(
        NotificationTemplate.org_id == org_id,
        NotificationTemplate.template_type == template_type,
        NotificationTemplate.channel == "sms",
    )
    result = await db.execute(stmt)
    tpl = result.scalar_one_or_none()

    if tpl is None:
        return None

    if body is not None:
        tpl.body_blocks = [{"type": "text", "content": body}]
    if is_enabled is not None:
        tpl.is_enabled = is_enabled

    await db.flush()
    await db.refresh(tpl)

    return _sms_template_to_dict(tpl)


async def log_sms_sent(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    recipient: str,
    template_type: str,
    body: str,
    status: str = "queued",
    error_message: str | None = None,
    sent_at: datetime | None = None,
) -> dict[str, Any]:
    """Log a sent SMS to the notification_log table.

    Logs SMS with the same detail as email (Req 36.6).
    """
    entry = NotificationLog(
        org_id=org_id,
        channel="sms",
        recipient=recipient,
        template_type=template_type,
        subject=None,  # SMS has no subject
        status=status,
        error_message=error_message,
        sent_at=sent_at,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return _log_entry_to_dict(entry)


# ---------------------------------------------------------------------------
# Overdue reminder rules CRUD (Req 38.1, 38.2, 38.3, 38.4)
# ---------------------------------------------------------------------------

from app.modules.notifications.models import OverdueReminderRule

MAX_OVERDUE_RULES_PER_ORG = 3


def _rule_to_dict(rule: OverdueReminderRule) -> dict[str, Any]:
    """Convert an OverdueReminderRule ORM instance to a plain dict."""
    return {
        "id": str(rule.id),
        "org_id": str(rule.org_id),
        "days_after_due": rule.days_after_due,
        "send_email": rule.send_email,
        "send_sms": rule.send_sms,
        "sort_order": rule.sort_order,
        "is_enabled": rule.is_enabled,
    }


async def _get_reminders_enabled(db: AsyncSession, *, org_id: uuid.UUID) -> bool:
    """Check if overdue reminders are enabled for an org via notification_preferences."""
    from app.modules.notifications.models import NotificationPreference

    stmt = select(NotificationPreference).where(
        NotificationPreference.org_id == org_id,
        NotificationPreference.notification_type == "overdue_reminders",
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()
    return pref.is_enabled if pref else False


async def _set_reminders_enabled(
    db: AsyncSession, *, org_id: uuid.UUID, enabled: bool
) -> None:
    """Set overdue reminders enabled/disabled for an org."""
    from app.modules.notifications.models import NotificationPreference

    stmt = select(NotificationPreference).where(
        NotificationPreference.org_id == org_id,
        NotificationPreference.notification_type == "overdue_reminders",
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = NotificationPreference(
            org_id=org_id,
            notification_type="overdue_reminders",
            is_enabled=enabled,
            channel="both",
            config={},
        )
        db.add(pref)
    else:
        pref.is_enabled = enabled

    await db.flush()


async def create_reminder_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    days_after_due: int,
    send_email: bool = True,
    send_sms: bool = False,
    is_enabled: bool = True,
) -> dict[str, Any] | str:
    """Create a new overdue reminder rule for an organisation.

    Returns the rule dict on success, or an error string on failure.
    Enforces max 3 rules per org (Req 38.1).
    """
    # Check existing count
    count_stmt = select(func.count(OverdueReminderRule.id)).where(
        OverdueReminderRule.org_id == org_id,
    )
    existing_count = (await db.execute(count_stmt)).scalar() or 0

    if existing_count >= MAX_OVERDUE_RULES_PER_ORG:
        return f"Maximum of {MAX_OVERDUE_RULES_PER_ORG} overdue reminder rules per organisation"

    # Check for duplicate days_after_due
    dup_stmt = select(OverdueReminderRule).where(
        OverdueReminderRule.org_id == org_id,
        OverdueReminderRule.days_after_due == days_after_due,
    )
    dup = (await db.execute(dup_stmt)).scalar_one_or_none()
    if dup is not None:
        return f"A rule for {days_after_due} days after due already exists"

    rule = OverdueReminderRule(
        org_id=org_id,
        days_after_due=days_after_due,
        send_email=send_email,
        send_sms=send_sms,
        sort_order=existing_count,
        is_enabled=is_enabled,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return _rule_to_dict(rule)


async def list_reminder_rules(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """List all overdue reminder rules for an organisation.

    Requirements: 38.1
    """
    stmt = (
        select(OverdueReminderRule)
        .where(OverdueReminderRule.org_id == org_id)
        .order_by(OverdueReminderRule.sort_order)
    )
    result = await db.execute(stmt)
    rules = result.scalars().all()

    reminders_enabled = await _get_reminders_enabled(db, org_id=org_id)

    return {
        "rules": [_rule_to_dict(r) for r in rules],
        "total": len(rules),
        "reminders_enabled": reminders_enabled,
    }


async def update_reminder_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    days_after_due: int | None = None,
    send_email: bool | None = None,
    send_sms: bool | None = None,
    is_enabled: bool | None = None,
) -> dict[str, Any] | None | str:
    """Update an overdue reminder rule.

    Returns the updated rule dict, None if not found, or error string.
    Requirements: 38.1
    """
    stmt = select(OverdueReminderRule).where(
        OverdueReminderRule.id == rule_id,
        OverdueReminderRule.org_id == org_id,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    if rule is None:
        return None

    if days_after_due is not None and days_after_due != rule.days_after_due:
        # Check for duplicate
        dup_stmt = select(OverdueReminderRule).where(
            OverdueReminderRule.org_id == org_id,
            OverdueReminderRule.days_after_due == days_after_due,
            OverdueReminderRule.id != rule_id,
        )
        dup = (await db.execute(dup_stmt)).scalar_one_or_none()
        if dup is not None:
            return f"A rule for {days_after_due} days after due already exists"
        rule.days_after_due = days_after_due

    if send_email is not None:
        rule.send_email = send_email
    if send_sms is not None:
        rule.send_sms = send_sms
    if is_enabled is not None:
        rule.is_enabled = is_enabled

    await db.flush()
    await db.refresh(rule)
    return _rule_to_dict(rule)


async def delete_reminder_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
) -> bool:
    """Delete an overdue reminder rule. Returns True if deleted, False if not found.

    Requirements: 38.1
    """
    stmt = select(OverdueReminderRule).where(
        OverdueReminderRule.id == rule_id,
        OverdueReminderRule.org_id == org_id,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()

    if rule is None:
        return False

    await db.delete(rule)
    await db.flush()
    return True


async def process_overdue_reminders(db: AsyncSession) -> dict[str, Any]:
    """Process overdue reminders for all organisations with enabled rules.

    Called by Celery Beat every 5 minutes. For each org with enabled overdue
    reminder rules, finds invoices that are overdue by the configured number
    of days and sends notifications via the configured channels.

    Skips voided and paid invoices (Req 38.3).
    Only processes orgs where overdue reminders are enabled (Req 38.4).

    Requirements: 38.2, 38.3, 38.4
    """
    from app.modules.invoices.models import Invoice
    from app.modules.customers.models import Customer
    from app.modules.notifications.models import NotificationPreference

    now = datetime.now(timezone.utc)
    today = now.date()

    # Find all orgs with overdue reminders enabled
    pref_stmt = select(NotificationPreference).where(
        NotificationPreference.notification_type == "overdue_reminders",
        NotificationPreference.is_enabled == True,  # noqa: E712
    )
    pref_result = await db.execute(pref_stmt)
    enabled_prefs = pref_result.scalars().all()

    stats = {"orgs_processed": 0, "reminders_sent": 0, "errors": 0}

    for pref in enabled_prefs:
        org_id = pref.org_id

        # Get enabled rules for this org
        rules_stmt = (
            select(OverdueReminderRule)
            .where(
                OverdueReminderRule.org_id == org_id,
                OverdueReminderRule.is_enabled == True,  # noqa: E712
            )
            .order_by(OverdueReminderRule.days_after_due)
        )
        rules_result = await db.execute(rules_stmt)
        rules = rules_result.scalars().all()

        if not rules:
            continue

        stats["orgs_processed"] += 1

        for rule in rules:
            # Find invoices that are overdue by exactly this many days
            # (to avoid sending duplicate reminders)
            target_due_date = today - __import__("datetime").timedelta(
                days=rule.days_after_due
            )

            invoice_stmt = (
                select(Invoice)
                .where(
                    Invoice.org_id == org_id,
                    Invoice.due_date == target_due_date,
                    Invoice.status.in_(["issued", "partially_paid", "overdue"]),
                )
            )
            invoice_result = await db.execute(invoice_stmt)
            invoices = invoice_result.scalars().all()

            for invoice in invoices:
                # Check if we already sent a reminder for this invoice + rule
                existing_log_stmt = select(func.count(NotificationLog.id)).where(
                    NotificationLog.org_id == org_id,
                    NotificationLog.template_type == "payment_overdue_reminder",
                    NotificationLog.recipient.like(f"%{str(invoice.id)}%"),
                )
                # Use a simpler dedup: check notification_log for this invoice
                # by embedding invoice_id in the subject
                dedup_subject = f"overdue_rule_{rule.id}_{invoice.id}"
                dedup_stmt = select(func.count(NotificationLog.id)).where(
                    NotificationLog.org_id == org_id,
                    NotificationLog.template_type == "payment_overdue_reminder",
                    NotificationLog.subject == dedup_subject,
                )
                dedup_count = (await db.execute(dedup_stmt)).scalar() or 0
                if dedup_count > 0:
                    continue  # Already sent for this rule + invoice combo

                # Get customer details
                cust_stmt = select(Customer).where(
                    Customer.id == invoice.customer_id
                )
                cust_result = await db.execute(cust_stmt)
                customer = cust_result.scalar_one_or_none()

                if customer is None or customer.is_anonymised:
                    continue

                # Send email if configured
                if rule.send_email and customer.email:
                    log_entry = await log_email_sent(
                        db,
                        org_id=org_id,
                        recipient=customer.email,
                        template_type="payment_overdue_reminder",
                        subject=dedup_subject,
                        status="queued",
                        channel="email",
                    )
                    # Enqueue Celery task
                    from app.tasks.notifications import send_email_task
                    send_email_task.delay(
                        str(org_id),
                        log_entry["id"],
                        customer.email,
                        f"{customer.first_name} {customer.last_name}",
                        f"Payment overdue — invoice {invoice.invoice_number or ''}",
                        "",  # html_body rendered by template system
                        "",  # text_body
                        None,
                        None,
                        "payment_overdue_reminder",
                    )
                    stats["reminders_sent"] += 1

                # Send SMS if configured (and plan includes SMS)
                if rule.send_sms and customer.phone:
                    # Check if org's plan includes SMS notifications
                    from app.modules.admin.models import Organisation as _Org, SubscriptionPlan as _Plan
                    _org_result = await db.execute(
                        select(_Org).where(_Org.id == org_id)
                    )
                    _org_row = _org_result.scalar_one_or_none()
                    _sms_allowed = False
                    if _org_row and _org_row.plan_id:
                        _plan_result = await db.execute(
                            select(_Plan).where(_Plan.id == _org_row.plan_id)
                        )
                        _plan_row = _plan_result.scalar_one_or_none()
                        _sms_allowed = _plan_row.sms_included if _plan_row else False

                    if not _sms_allowed:
                        continue

                    sms_log = await log_sms_sent(
                        db,
                        org_id=org_id,
                        recipient=customer.phone,
                        template_type="payment_overdue_reminder",
                        body=f"Invoice {invoice.invoice_number or ''} is overdue.",
                        status="queued",
                    )
                    from app.tasks.notifications import send_sms_task
                    send_sms_task.delay(
                        str(org_id),
                        sms_log["id"],
                        customer.phone,
                        f"Invoice {invoice.invoice_number or ''} is overdue. Please pay promptly.",
                        None,
                        "payment_overdue_reminder",
                    )
                    stats["reminders_sent"] += 1

                    # Best-effort SMS usage tracking (Req 2.3, 8.4)
                    try:
                        await increment_sms_usage(db, org_id)
                    except Exception:
                        logger.error(
                            "Failed to increment SMS usage for org %s",
                            org_id,
                            exc_info=True,
                        )

    return stats


# ---------------------------------------------------------------------------
# WOF / Registration expiry reminder settings & processing (Req 39)
# ---------------------------------------------------------------------------

WOF_REGO_NOTIFICATION_TYPE = "wof_rego_reminders"
DEFAULT_WOF_REGO_DAYS_IN_ADVANCE = 30


async def get_wof_rego_settings(
    db: AsyncSession, *, org_id: uuid.UUID
) -> dict[str, Any]:
    """Return WOF/rego reminder settings for an organisation.

    Requirements: 39.1, 39.2, 39.4
    """
    from app.modules.notifications.models import NotificationPreference

    stmt = select(NotificationPreference).where(
        NotificationPreference.org_id == org_id,
        NotificationPreference.notification_type == WOF_REGO_NOTIFICATION_TYPE,
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()

    if pref is None:
        return {
            "enabled": False,
            "days_in_advance": DEFAULT_WOF_REGO_DAYS_IN_ADVANCE,
            "channel": "email",
        }

    config = pref.config or {}
    return {
        "enabled": pref.is_enabled,
        "days_in_advance": config.get(
            "days_in_advance", DEFAULT_WOF_REGO_DAYS_IN_ADVANCE
        ),
        "channel": pref.channel,
    }


async def update_wof_rego_settings(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    enabled: bool | None = None,
    days_in_advance: int | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Update WOF/rego reminder settings for an organisation.

    Requirements: 39.1, 39.2, 39.4
    """
    from app.modules.notifications.models import NotificationPreference

    stmt = select(NotificationPreference).where(
        NotificationPreference.org_id == org_id,
        NotificationPreference.notification_type == WOF_REGO_NOTIFICATION_TYPE,
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = NotificationPreference(
            org_id=org_id,
            notification_type=WOF_REGO_NOTIFICATION_TYPE,
            is_enabled=enabled if enabled is not None else False,
            channel=channel or "email",
            config={
                "days_in_advance": days_in_advance
                if days_in_advance is not None
                else DEFAULT_WOF_REGO_DAYS_IN_ADVANCE
            },
        )
        db.add(pref)
    else:
        if enabled is not None:
            pref.is_enabled = enabled
        if channel is not None:
            pref.channel = channel
        if days_in_advance is not None:
            config = dict(pref.config or {})
            config["days_in_advance"] = days_in_advance
            pref.config = config

    await db.flush()
    await db.refresh(pref)

    config = pref.config or {}
    return {
        "enabled": pref.is_enabled,
        "days_in_advance": config.get(
            "days_in_advance", DEFAULT_WOF_REGO_DAYS_IN_ADVANCE
        ),
        "channel": pref.channel,
    }


async def process_wof_rego_reminders(db: AsyncSession) -> dict[str, Any]:
    """Process WOF and registration expiry reminders for all enabled orgs.

    Called daily by Celery Beat at 2am NZST. For each org with WOF/rego
    reminders enabled, finds vehicles with expiry dates within the configured
    window and sends notifications to linked customers.

    Requirements: 39.1, 39.2, 39.3, 39.4
    """
    from app.modules.notifications.models import NotificationPreference
    from app.modules.vehicles.models import CustomerVehicle
    from app.modules.customers.models import Customer

    # Import GlobalVehicle from admin models where it's defined
    from app.modules.admin.models import GlobalVehicle

    now = datetime.now(timezone.utc)
    today = now.date()

    # Find all orgs with WOF/rego reminders enabled
    pref_stmt = select(NotificationPreference).where(
        NotificationPreference.notification_type == WOF_REGO_NOTIFICATION_TYPE,
        NotificationPreference.is_enabled == True,  # noqa: E712
    )
    pref_result = await db.execute(pref_stmt)
    enabled_prefs = pref_result.scalars().all()

    stats: dict[str, Any] = {
        "orgs_processed": 0,
        "reminders_sent": 0,
        "errors": 0,
    }

    for pref in enabled_prefs:
        org_id = pref.org_id
        config = pref.config or {}
        days_in_advance = config.get(
            "days_in_advance", DEFAULT_WOF_REGO_DAYS_IN_ADVANCE
        )
        channel = pref.channel  # "email", "sms", or "both"

        # Target expiry date = today + days_in_advance
        import datetime as dt_mod

        target_date = today + dt_mod.timedelta(days=days_in_advance)

        stats["orgs_processed"] += 1

        # Get org settings for workshop contact details
        from app.modules.admin.models import Organisation

        org_result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is None:
            continue

        org_settings = org.settings or {}
        org_name = org.name
        org_phone = org_settings.get("phone", "")
        org_email = org_settings.get("email", "")

        # Check if org's plan includes SMS notifications
        _org_sms_allowed = False
        if org.plan_id:
            from app.modules.admin.models import SubscriptionPlan as _SPlan
            _sp_result = await db.execute(
                select(_SPlan).where(_SPlan.id == org.plan_id)
            )
            _sp_row = _sp_result.scalar_one_or_none()
            _org_sms_allowed = _sp_row.sms_included if _sp_row else False

        # Downgrade channel if plan doesn't include SMS
        effective_channel = channel
        if not _org_sms_allowed and channel in ("sms", "both"):
            effective_channel = "email" if channel == "both" else None
        if effective_channel is None:
            continue

        # Process WOF expiry reminders from global_vehicles
        for expiry_type, expiry_field, template_type in [
            ("WOF", "wof_expiry", "wof_expiry_reminder"),
            ("Registration", "registration_expiry", "registration_expiry_reminder"),
        ]:
            # Find customer_vehicles linked to global vehicles expiring on target_date
            cv_gv_stmt = (
                select(CustomerVehicle, GlobalVehicle, Customer)
                .join(
                    GlobalVehicle,
                    CustomerVehicle.global_vehicle_id == GlobalVehicle.id,
                )
                .join(Customer, CustomerVehicle.customer_id == Customer.id)
                .where(
                    CustomerVehicle.org_id == org_id,
                    getattr(GlobalVehicle, expiry_field) == target_date,
                    Customer.is_anonymised == False,  # noqa: E712
                )
            )
            cv_gv_result = await db.execute(cv_gv_stmt)
            rows = cv_gv_result.all()

            for cv, gv, customer in rows:
                rego = gv.rego
                expiry_date_str = str(getattr(gv, expiry_field))
                vehicle_make = gv.make or ""
                vehicle_model = gv.model or ""

                # Dedup: check if we already sent this reminder
                dedup_subject = (
                    f"{template_type}_{org_id}_{gv.id}_{expiry_date_str}"
                )
                dedup_stmt = select(func.count(NotificationLog.id)).where(
                    NotificationLog.org_id == org_id,
                    NotificationLog.template_type == template_type,
                    NotificationLog.subject == dedup_subject,
                )
                dedup_count = (await db.execute(dedup_stmt)).scalar() or 0
                if dedup_count > 0:
                    continue

                # Send email if channel is email or both
                if effective_channel in ("email", "both") and customer.email:
                    log_entry = await log_email_sent(
                        db,
                        org_id=org_id,
                        recipient=customer.email,
                        template_type=template_type,
                        subject=dedup_subject,
                        status="queued",
                        channel="email",
                    )
                    from app.tasks.notifications import send_email_task

                    send_email_task.delay(
                        str(org_id),
                        log_entry["id"],
                        customer.email,
                        f"{customer.first_name} {customer.last_name}",
                        f"{expiry_type} expiry reminder for {rego}",
                        "",  # html_body rendered by template system
                        "",  # text_body
                        None,
                        None,
                        template_type,
                    )
                    stats["reminders_sent"] += 1

                # Send SMS if channel is sms or both (plan SMS check already done above)
                if effective_channel in ("sms", "both") and customer.phone:
                    sms_body = (
                        f"Hi {customer.first_name}, {expiry_type} for "
                        f"{rego} expires {expiry_date_str}. "
                        f"Contact {org_name}"
                        f"{' on ' + org_phone if org_phone else ''}."
                    )
                    sms_log = await log_sms_sent(
                        db,
                        org_id=org_id,
                        recipient=customer.phone,
                        template_type=template_type,
                        body=sms_body,
                        status="queued",
                    )
                    from app.tasks.notifications import send_sms_task

                    send_sms_task.delay(
                        str(org_id),
                        sms_log["id"],
                        customer.phone,
                        sms_body,
                        None,
                        template_type,
                    )
                    stats["reminders_sent"] += 1

                    # Best-effort SMS usage tracking (Req 2.3, 8.4)
                    try:
                        await increment_sms_usage(db, org_id)
                    except Exception:
                        logger.error(
                            "Failed to increment SMS usage for org %s",
                            org_id,
                            exc_info=True,
                        )

    return stats


# ---------------------------------------------------------------------------
# Notification preference settings (Req 83.1, 83.2, 83.3, 83.4)
# ---------------------------------------------------------------------------


async def list_notification_preferences(
    db: AsyncSession, *, org_id: uuid.UUID
) -> dict[str, Any]:
    """Return all notification preferences grouped by category.

    For any notification type without a stored preference row, returns the
    default (disabled, channel=email). This ensures the response always
    contains every known notification type.

    Requirements: 83.1, 83.3
    """
    from app.modules.notifications.models import NotificationPreference
    from app.modules.notifications.schemas import (
        ALL_NOTIFICATION_TYPES,
        NOTIFICATION_CATEGORIES,
    )

    stmt = select(NotificationPreference).where(
        NotificationPreference.org_id == org_id,
        NotificationPreference.notification_type.in_(ALL_NOTIFICATION_TYPES),
    )
    result = await db.execute(stmt)
    stored = {p.notification_type: p for p in result.scalars().all()}

    categories: list[dict[str, Any]] = []
    for category_name, types in NOTIFICATION_CATEGORIES.items():
        prefs: list[dict[str, Any]] = []
        for nt in types:
            pref = stored.get(nt)
            prefs.append(
                {
                    "notification_type": nt,
                    "is_enabled": pref.is_enabled if pref else False,
                    "channel": pref.channel if pref else "email",
                }
            )
        categories.append({"category": category_name, "preferences": prefs})

    return {"categories": categories}


async def update_notification_preference(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    notification_type: str,
    is_enabled: bool | None = None,
    channel: str | None = None,
) -> dict[str, Any]:
    """Create or update a single notification preference.

    Requirements: 83.1, 83.2, 83.4
    """
    from app.modules.notifications.models import NotificationPreference
    from app.modules.notifications.schemas import ALL_NOTIFICATION_TYPES

    if notification_type not in ALL_NOTIFICATION_TYPES:
        raise ValueError(
            f"Unknown notification type: {notification_type}"
        )

    stmt = select(NotificationPreference).where(
        NotificationPreference.org_id == org_id,
        NotificationPreference.notification_type == notification_type,
    )
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = NotificationPreference(
            org_id=org_id,
            notification_type=notification_type,
            is_enabled=is_enabled if is_enabled is not None else False,
            channel=channel or "email",
            config={},
        )
        db.add(pref)
    else:
        if is_enabled is not None:
            pref.is_enabled = is_enabled
        if channel is not None:
            pref.channel = channel

    await db.flush()
    await db.refresh(pref)

    return {
        "notification_type": pref.notification_type,
        "is_enabled": pref.is_enabled,
        "channel": pref.channel,
    }
