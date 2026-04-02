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

from sqlalchemy import select, func, update, text
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


def render_sms_body(template_body: str, variables: dict[str, str]) -> str:
    """Render an SMS template body by substituting ``{{variable}}`` placeholders.

    Uses the same ``{{variable}}`` syntax as the email template system.
    Variables present in *variables* are replaced; unmatched placeholders
    are left as-is so the caller can detect missing values.

    Requirements: 15.1, 15.2
    """

    def _replacer(match: re.Match) -> str:
        var_name = match.group(1).strip()
        return variables.get(var_name, match.group(0))

    return re.sub(r"\{\{(\w+)\}\}", _replacer, template_body)


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

def render_sms_body(template_body: str, variables: dict[str, str]) -> str:
    """Render an SMS template body by substituting ``{{variable}}`` placeholders.

    Uses the same ``{{variable}}`` syntax as the email template system.
    Variables present in *variables* are replaced; unmatched placeholders
    are left as-is so the caller can detect missing values.

    Requirements: 15.1, 15.2
    """

    def _replacer(match: re.Match) -> str:
        var_name = match.group(1).strip()
        return variables.get(var_name, match.group(0))

    return re.sub(r"\{\{(\w+)\}\}", _replacer, template_body)




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
from app.integrations.sms_types import SMS_CHAR_LIMIT


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
                    # Enqueue email task
                    from app.tasks.notifications import send_email_task
                    await send_email_task(
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
                    await send_sms_task(
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

                    await send_email_task(
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

                    await send_sms_task(
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


# ---------------------------------------------------------------------------
# Reminder rules CRUD (Zoho-style configurable reminders)
# ---------------------------------------------------------------------------

from app.modules.notifications.models import ReminderRule

MAX_REMINDER_RULES_PER_ORG = 10


def _reminder_rule_to_dict(rule: ReminderRule) -> dict[str, Any]:
    """Convert a ReminderRule ORM instance to a plain dict."""
    return {
        "id": str(rule.id),
        "org_id": str(rule.org_id),
        "name": rule.name,
        "reminder_type": rule.reminder_type,
        "target": rule.target,
        "days_offset": rule.days_offset,
        "timing": rule.timing,
        "reference_date": rule.reference_date,
        "send_email": rule.send_email,
        "send_sms": rule.send_sms,
        "is_enabled": rule.is_enabled,
        "sort_order": rule.sort_order,
    }


async def list_reminder_rules(
    db: AsyncSession, *, org_id: uuid.UUID
) -> dict[str, Any]:
    """Return all reminder rules for an org, grouped for the UI."""
    from app.modules.notifications.schemas import MANUAL_REMINDERS

    stmt = (
        select(ReminderRule)
        .where(ReminderRule.org_id == org_id)
        .order_by(ReminderRule.reference_date, ReminderRule.sort_order)
    )
    result = await db.execute(stmt)
    rules = [_reminder_rule_to_dict(r) for r in result.scalars().all()]

    return {
        "manual_reminders": MANUAL_REMINDERS,
        "automated_reminders": rules,
        "total": len(rules),
    }


async def create_reminder_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    name: str,
    reminder_type: str,
    target: str = "customer",
    days_offset: int = 0,
    timing: str = "after",
    reference_date: str = "due_date",
    send_email: bool = True,
    send_sms: bool = False,
    is_enabled: bool = True,
) -> dict[str, Any] | str:
    """Create a new reminder rule. Returns dict on success, error string on failure."""
    from app.modules.notifications.schemas import (
        VALID_REMINDER_TYPES,
        VALID_TARGETS,
        VALID_TIMINGS,
        VALID_REFERENCE_DATES,
    )

    if reminder_type not in VALID_REMINDER_TYPES:
        return f"Invalid reminder_type: {reminder_type}"
    if target not in VALID_TARGETS:
        return f"Invalid target: {target}"
    if timing not in VALID_TIMINGS:
        return f"Invalid timing: {timing}"
    if reference_date not in VALID_REFERENCE_DATES:
        return f"Invalid reference_date: {reference_date}"

    count_stmt = select(func.count(ReminderRule.id)).where(
        ReminderRule.org_id == org_id,
    )
    existing_count = (await db.execute(count_stmt)).scalar() or 0
    if existing_count >= MAX_REMINDER_RULES_PER_ORG:
        return f"Maximum of {MAX_REMINDER_RULES_PER_ORG} reminder rules per organisation"

    # Determine sort_order
    max_sort_stmt = select(func.max(ReminderRule.sort_order)).where(
        ReminderRule.org_id == org_id,
    )
    max_sort = (await db.execute(max_sort_stmt)).scalar() or 0

    rule = ReminderRule(
        org_id=org_id,
        name=name,
        reminder_type=reminder_type,
        target=target,
        days_offset=days_offset,
        timing=timing,
        reference_date=reference_date,
        send_email=send_email,
        send_sms=send_sms,
        is_enabled=is_enabled,
        sort_order=max_sort + 1,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return _reminder_rule_to_dict(rule)


async def update_reminder_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    rule_id: uuid.UUID,
    name: str | None = None,
    target: str | None = None,
    days_offset: int | None = None,
    timing: str | None = None,
    reference_date: str | None = None,
    send_email: bool | None = None,
    send_sms: bool | None = None,
    is_enabled: bool | None = None,
) -> dict[str, Any] | str | None:
    """Update a reminder rule. Returns dict, error string, or None if not found."""
    from app.modules.notifications.schemas import (
        VALID_TARGETS,
        VALID_TIMINGS,
        VALID_REFERENCE_DATES,
    )

    stmt = select(ReminderRule).where(
        ReminderRule.id == rule_id,
        ReminderRule.org_id == org_id,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if rule is None:
        return None

    if target is not None:
        if target not in VALID_TARGETS:
            return f"Invalid target: {target}"
        rule.target = target
    if name is not None:
        rule.name = name
    if days_offset is not None:
        rule.days_offset = days_offset
    if timing is not None:
        if timing not in VALID_TIMINGS:
            return f"Invalid timing: {timing}"
        rule.timing = timing
    if reference_date is not None:
        if reference_date not in VALID_REFERENCE_DATES:
            return f"Invalid reference_date: {reference_date}"
        rule.reference_date = reference_date
    if send_email is not None:
        rule.send_email = send_email
    if send_sms is not None:
        rule.send_sms = send_sms
    if is_enabled is not None:
        rule.is_enabled = is_enabled

    await db.flush()
    await db.refresh(rule)
    return _reminder_rule_to_dict(rule)


async def delete_reminder_rule(
    db: AsyncSession, *, org_id: uuid.UUID, rule_id: uuid.UUID
) -> bool:
    """Delete a reminder rule. Returns True if deleted, False if not found."""
    stmt = select(ReminderRule).where(
        ReminderRule.id == rule_id,
        ReminderRule.org_id == org_id,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if rule is None:
        return False
    await db.delete(rule)
    await db.flush()
    return True


async def toggle_reminder_rule(
    db: AsyncSession, *, org_id: uuid.UUID, rule_id: uuid.UUID, is_enabled: bool
) -> dict[str, Any] | None:
    """Toggle a single reminder rule on/off. Returns updated dict or None."""
    stmt = select(ReminderRule).where(
        ReminderRule.id == rule_id,
        ReminderRule.org_id == org_id,
    )
    result = await db.execute(stmt)
    rule = result.scalar_one_or_none()
    if rule is None:
        return None
    rule.is_enabled = is_enabled
    await db.flush()
    await db.refresh(rule)
    return _reminder_rule_to_dict(rule)


# ---------------------------------------------------------------------------
# Per-customer reminder processing (Service Due / WOF Expiry)
# ---------------------------------------------------------------------------

# Country code → phone prefix mapping
COUNTRY_PHONE_PREFIX: dict[str, str] = {
    "NZ": "+64",
    "AU": "+61",
    "GB": "+44",
    "US": "+1",
    "CA": "+1",
}

DEFAULT_COUNTRY_CODE = "NZ"


def normalize_phone_number(
    phone: str | None,
    *,
    customer_address: str | None = None,
    org_country_code: str | None = None,
) -> str | None:
    """Normalize a phone number to include a country code prefix.

    Resolution order for country code:
    1. Phone already starts with '+' → use as-is
    2. Customer address contains a known country → use that country's prefix
    3. Organisation country_code → use that prefix
    4. Default to NZ (+64)

    Strips leading '0' when prepending country prefix (e.g. 021... → +6421...).
    """
    if not phone:
        return None

    # Strip whitespace, dashes, parens
    cleaned = re.sub(r"[\s\-\(\)]+", "", phone.strip())

    if not cleaned:
        return None

    # Already has country code
    if cleaned.startswith("+"):
        return cleaned

    # Try to resolve country from customer address
    resolved_country = None
    if customer_address:
        addr_upper = customer_address.upper()
        for code, _prefix in COUNTRY_PHONE_PREFIX.items():
            # Simple heuristic: check if country name or code appears in address
            country_names = {
                "NZ": ["NEW ZEALAND", "NZ"],
                "AU": ["AUSTRALIA", "AU"],
                "GB": ["UNITED KINGDOM", "UK", "ENGLAND", "GB"],
                "US": ["UNITED STATES", "USA", "US"],
                "CA": ["CANADA", "CA"],
            }
            for name in country_names.get(code, []):
                if name in addr_upper:
                    resolved_country = code
                    break
            if resolved_country:
                break

    country = resolved_country or org_country_code or DEFAULT_COUNTRY_CODE
    prefix = COUNTRY_PHONE_PREFIX.get(country, COUNTRY_PHONE_PREFIX[DEFAULT_COUNTRY_CODE])

    # Strip leading 0 (local format) before prepending prefix
    if cleaned.startswith("0"):
        cleaned = cleaned[1:]

    return f"{prefix}{cleaned}"


async def process_customer_reminders(db: AsyncSession) -> dict[str, Any]:
    """Process per-customer configured reminders (Service Due / WOF Expiry).

    Called daily by a scheduled task. For each customer with reminder_config
    in their custom_fields, checks linked vehicles for upcoming expiry dates
    and sends notifications via the configured channel.

    Logs detailed errors for org admins when delivery fails.
    """
    from app.modules.customers.models import Customer
    from app.modules.vehicles.models import CustomerVehicle
    from app.modules.admin.models import GlobalVehicle, Organisation
    from app.modules.admin.models import SubscriptionPlan
    from app.modules.admin.models import SmsVerificationProvider
    from app.modules.notifications.models import NotificationLog
    from app.core.errors import log_error, Severity, Category

    import datetime as dt_mod

    now = datetime.now(timezone.utc)
    today = now.date()

    stats: dict[str, Any] = {
        "customers_checked": 0,
        "reminders_sent": 0,
        "errors": 0,
        "skipped": 0,
        "error_details": [],
    }

    # Find all customers that have reminder_config in custom_fields
    from sqlalchemy import cast, String
    cust_stmt = select(Customer).where(
        Customer.is_anonymised == False,  # noqa: E712
        Customer.custom_fields.has_key("reminder_config"),  # noqa: W601
    )
    cust_result = await db.execute(cust_stmt)
    customers = cust_result.scalars().all()

    # Cache org data to avoid repeated queries
    org_cache: dict[uuid.UUID, dict] = {}

    async def _get_org_data(org_id: uuid.UUID) -> dict | None:
        if org_id in org_cache:
            return org_cache[org_id]

        org_result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org = org_result.scalar_one_or_none()
        if org is None:
            org_cache[org_id] = None  # type: ignore
            return None

        org_settings = org.settings or {}

        # Check SMS plan allowance
        sms_allowed = False
        if org.plan_id:
            sp_result = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
            )
            sp = sp_result.scalar_one_or_none()
            sms_allowed = sp.sms_included if sp else False

        # Check if SMS provider is configured
        sms_provider_result = await db.execute(
            select(SmsVerificationProvider).where(
                SmsVerificationProvider.is_active == True,  # noqa: E712
            ).order_by(SmsVerificationProvider.is_default.desc(), SmsVerificationProvider.priority)
        )
        sms_provider = sms_provider_result.scalars().first()
        sms_configured = sms_provider is not None and sms_provider.credentials_encrypted is not None

        # Check if email provider is configured
        from app.modules.admin.models import EmailProvider
        email_provider_result = await db.execute(
            select(EmailProvider).where(
                EmailProvider.is_active == True,  # noqa: E712
                EmailProvider.credentials_set == True,  # noqa: E712
            ).order_by(EmailProvider.priority)
        )
        email_configured = email_provider_result.scalars().first() is not None

        # Get org country_code from the organisations table
        country_row = await db.execute(
            text("SELECT country_code FROM organisations WHERE id = :oid"),
            {"oid": str(org_id)},
        )
        country_code_val = country_row.scalar_one_or_none()
        org_country_code = country_code_val if country_code_val else "NZ"

        data = {
            "org": org,
            "org_name": org.name,
            "org_phone": org_settings.get("phone", ""),
            "org_email": org_settings.get("email", ""),
            "org_country_code": org_country_code,
            "sms_allowed": sms_allowed,
            "sms_configured": sms_configured,
            "email_configured": email_configured,
        }
        org_cache[org_id] = data
        return data

    for customer in customers:
        custom_fields = customer.custom_fields or {}
        reminder_config = custom_fields.get("reminder_config", {})

        if not reminder_config:
            continue

        stats["customers_checked"] += 1
        org_id = customer.org_id

        org_data = await _get_org_data(org_id)
        if org_data is None:
            stats["skipped"] += 1
            continue

        # Get customer's linked vehicles (global vehicles only — they have expiry dates)
        cv_stmt = (
            select(CustomerVehicle, GlobalVehicle)
            .join(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
            .where(
                CustomerVehicle.customer_id == customer.id,
                CustomerVehicle.org_id == org_id,
            )
        )
        cv_result = await db.execute(cv_stmt)
        vehicle_rows = cv_result.all()

        if not vehicle_rows:
            continue

        customer_name = f"{customer.first_name} {customer.last_name}".strip()

        for reminder_type, config_entry in reminder_config.items():
            if not isinstance(config_entry, dict):
                continue
            if not config_entry.get("enabled", False):
                continue

            days_before = config_entry.get("days_before", 30)
            channel = config_entry.get("channel", "email")
            target_date = today + dt_mod.timedelta(days=days_before)

            # Map reminder type to vehicle field
            if reminder_type == "service_due":
                expiry_field = "service_due_date"
                reminder_label = "Service Due"
                template_type = "customer_service_due_reminder"
            elif reminder_type == "wof_expiry":
                expiry_field = "wof_expiry"
                reminder_label = "WOF Expiry"
                template_type = "customer_wof_expiry_reminder"
            else:
                continue

            for cv, gv in vehicle_rows:
                expiry_date = getattr(gv, expiry_field, None)
                if expiry_date is None:
                    continue

                # Only send if expiry matches the target date
                if expiry_date != target_date:
                    continue

                rego = gv.rego or "Unknown"
                expiry_date_str = str(expiry_date)
                vehicle_desc = " ".join(filter(None, [str(gv.year) if gv.year else None, gv.make, gv.model]))

                # Dedup check
                dedup_subject = f"{template_type}_{org_id}_{gv.id}_{customer.id}_{expiry_date_str}"
                dedup_stmt = select(func.count(NotificationLog.id)).where(
                    NotificationLog.org_id == org_id,
                    NotificationLog.template_type == template_type,
                    NotificationLog.subject == dedup_subject,
                )
                dedup_count = (await db.execute(dedup_stmt)).scalar() or 0
                if dedup_count > 0:
                    continue

                send_email = channel in ("email", "both")
                send_sms = channel in ("sms", "both")

                # --- Email ---
                if send_email:
                    if not org_data["email_configured"]:
                        error_msg = (
                            f"Customer reminder ({reminder_label}) failed for "
                            f"{customer_name} — Email service not configured. "
                            f"Set up an email provider in Admin > Email Providers."
                        )
                        await log_error(
                            db,
                            severity=Severity.WARNING,
                            category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="process_customer_reminders",
                            message=error_msg,
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        stats["error_details"].append(error_msg)
                    elif not customer.email:
                        error_msg = (
                            f"Customer reminder ({reminder_label}) failed for "
                            f"{customer_name} — No email address on file for customer."
                        )
                        await log_error(
                            db,
                            severity=Severity.WARNING,
                            category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="process_customer_reminders",
                            message=error_msg,
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        stats["error_details"].append(error_msg)
                    else:
                        email_subject = f"{reminder_label} reminder for {rego}"
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

                        email_body = (
                            f"<p>Hi {customer.first_name},</p>"
                            f"<p>{reminder_label} for your vehicle <strong>{rego}</strong>"
                            f"{(' (' + vehicle_desc + ')') if vehicle_desc else ''}"
                            f" is coming up on <strong>{expiry_date_str}</strong>.</p>"
                            f"<p>Please contact {org_data['org_name']}"
                            f"{(' on ' + org_data['org_phone']) if org_data['org_phone'] else ''}"
                            f" to book your appointment.</p>"
                        )
                        text_body = (
                            f"Hi {customer.first_name}, "
                            f"{reminder_label} for {rego} is coming up on {expiry_date_str}. "
                            f"Contact {org_data['org_name']}"
                            f"{(' on ' + org_data['org_phone']) if org_data['org_phone'] else ''}."
                        )

                        await send_email_task(
                            str(org_id),
                            log_entry["id"],
                            customer.email,
                            customer_name,
                            email_subject,
                            email_body,
                            text_body,
                            None,
                            org_data["org_email"] or None,
                            template_type,
                        )
                        stats["reminders_sent"] += 1

                # --- SMS ---
                if send_sms:
                    if not org_data["sms_configured"]:
                        error_msg = (
                            f"Customer reminder ({reminder_label}) failed for "
                            f"{customer_name} — SMS service not configured or not enabled. "
                            f"Set up an SMS provider in Admin > SMS Providers."
                        )
                        await log_error(
                            db,
                            severity=Severity.WARNING,
                            category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="process_customer_reminders",
                            message=error_msg,
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        stats["error_details"].append(error_msg)
                    elif not org_data["sms_allowed"]:
                        error_msg = (
                            f"Customer reminder ({reminder_label}) failed for "
                            f"{customer_name} — SMS not included in organisation's subscription plan. "
                            f"Upgrade your plan or purchase an SMS package."
                        )
                        await log_error(
                            db,
                            severity=Severity.WARNING,
                            category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="process_customer_reminders",
                            message=error_msg,
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        stats["error_details"].append(error_msg)
                    elif not customer.phone:
                        error_msg = (
                            f"Customer reminder ({reminder_label}) failed for "
                            f"{customer_name} — No phone number on file for customer."
                        )
                        await log_error(
                            db,
                            severity=Severity.WARNING,
                            category=Category.INTEGRATION,
                            module="notifications.customer_reminders",
                            function_name="process_customer_reminders",
                            message=error_msg,
                            org_id=str(org_id),
                        )
                        stats["errors"] += 1
                        stats["error_details"].append(error_msg)
                    else:
                        # Normalize phone number with country code
                        normalized_phone = normalize_phone_number(
                            customer.phone,
                            customer_address=customer.address,
                            org_country_code=org_data["org_country_code"],
                        )
                        if not normalized_phone:
                            error_msg = (
                                f"Customer reminder ({reminder_label}) failed for "
                                f"{customer_name} — Could not determine country code for phone number. "
                                f"Please add a country code to the customer's phone number, "
                                f"or set the customer's address or organisation country."
                            )
                            await log_error(
                                db,
                                severity=Severity.WARNING,
                                category=Category.INTEGRATION,
                                module="notifications.customer_reminders",
                                function_name="process_customer_reminders",
                                message=error_msg,
                                org_id=str(org_id),
                            )
                            stats["errors"] += 1
                            stats["error_details"].append(error_msg)
                        else:
                            sms_body = (
                                f"Hi {customer.first_name}, "
                                f"{reminder_label} for {rego} is due on {expiry_date_str}. "
                                f"Contact {org_data['org_name']}"
                                f"{(' on ' + org_data['org_phone']) if org_data['org_phone'] else ''}."
                            )
                            sms_log = await log_sms_sent(
                                db,
                                org_id=org_id,
                                recipient=normalized_phone,
                                template_type=template_type,
                                body=sms_body,
                                status="queued",
                            )
                            from app.tasks.notifications import send_sms_task

                            await send_sms_task(
                                str(org_id),
                                sms_log["id"],
                                normalized_phone,
                                sms_body,
                                None,
                                template_type,
                            )
                            stats["reminders_sent"] += 1

                            # Track SMS usage
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
# Branch notification triggers (Req 22.1, 22.2, 22.3, 22.4, 22.5)
# ---------------------------------------------------------------------------


async def _get_org_admin_users(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[dict]:
    """Return all active Org_Admin users for an organisation."""
    from app.modules.auth.models import User

    result = await db.execute(
        select(User.id, User.email, User.first_name, User.last_name)
        .where(
            User.org_id == org_id,
            User.role == "org_admin",
            User.is_active == True,  # noqa: E712
        )
    )
    return [
        {
            "id": row.id,
            "email": row.email,
            "name": f"{row.first_name or ''} {row.last_name or ''}".strip(),
        }
        for row in result.all()
    ]


async def _get_branch_users(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_id: uuid.UUID,
) -> list[dict]:
    """Return all active users assigned to a specific branch."""
    from app.modules.auth.models import User
    from sqlalchemy.dialects.postgresql import JSONB

    result = await db.execute(
        select(User.id, User.email, User.first_name, User.last_name)
        .where(
            User.org_id == org_id,
            User.is_active == True,  # noqa: E712
        )
    )
    users = []
    for row in result.all():
        users.append({
            "id": row.id,
            "email": row.email,
            "name": f"{row.first_name or ''} {row.last_name or ''}".strip(),
        })
    return users


def _should_send_notification(
    notification_preferences: dict,
    notification_type: str,
) -> bool:
    """Check if a notification type is enabled in branch preferences.

    If notification_preferences is empty or the type is not configured,
    defaults to True (send the notification).

    Requirements: 22.4
    """
    if not notification_preferences:
        return True
    # Check if the specific type is explicitly disabled
    return notification_preferences.get(notification_type, True)


async def notify_branch_created(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_name: str,
    branch_id: uuid.UUID,
) -> int:
    """Send "New branch added" notification to all Org_Admin users.

    Requirements: 22.1
    """
    admins = await _get_org_admin_users(db, org_id)
    sent_count = 0

    for admin in admins:
        try:
            await log_email_sent(
                db,
                org_id=org_id,
                recipient=admin["email"],
                template_type="branch_created",
                subject=f"New branch added: {branch_name}",
                status="queued",
                channel="in_app",
            )
            sent_count += 1
        except Exception:
            logger.error(
                "Failed to send branch_created notification to %s",
                admin["email"],
                exc_info=True,
            )

    return sent_count


async def notify_branch_deactivated(
    db: AsyncSession,
    org_id: uuid.UUID,
    branch_name: str,
    branch_id: uuid.UUID,
    notification_preferences: dict | None = None,
) -> int:
    """Send "Branch deactivated" notification to all Org_Admin users.

    Respects per-branch notification_preferences.

    Requirements: 22.2, 22.4
    """
    if not _should_send_notification(
        notification_preferences or {}, "branch_deactivated"
    ):
        return 0

    admins = await _get_org_admin_users(db, org_id)
    sent_count = 0

    for admin in admins:
        try:
            await log_email_sent(
                db,
                org_id=org_id,
                recipient=admin["email"],
                template_type="branch_deactivated",
                subject=f"Branch deactivated: {branch_name}",
                status="queued",
                channel="in_app",
            )
            sent_count += 1
        except Exception:
            logger.error(
                "Failed to send branch_deactivated notification to %s",
                admin["email"],
                exc_info=True,
            )

    return sent_count


async def notify_billing_updated(
    db: AsyncSession,
    org_id: uuid.UUID,
    new_monthly_total: str,
    reason: str = "Branch activation/deactivation",
    notification_preferences: dict | None = None,
) -> int:
    """Send "Billing updated" notification with new monthly total.

    Requirements: 22.3, 22.4
    """
    if not _should_send_notification(
        notification_preferences or {}, "billing_updated"
    ):
        return 0

    admins = await _get_org_admin_users(db, org_id)
    sent_count = 0

    for admin in admins:
        try:
            await log_email_sent(
                db,
                org_id=org_id,
                recipient=admin["email"],
                template_type="billing_updated",
                subject=f"Billing updated: new monthly total ${new_monthly_total}",
                status="queued",
                channel="in_app",
            )
            sent_count += 1
        except Exception:
            logger.error(
                "Failed to send billing_updated notification to %s",
                admin["email"],
                exc_info=True,
            )

    return sent_count


async def notify_stock_transfer_request(
    db: AsyncSession,
    org_id: uuid.UUID,
    to_branch_id: uuid.UUID,
    to_branch_name: str,
    from_branch_name: str,
    product_name: str,
    quantity: str,
    notification_preferences: dict | None = None,
) -> int:
    """Send "Stock transfer request" notification to destination branch users.

    Requirements: 22.5, 22.4
    """
    if not _should_send_notification(
        notification_preferences or {}, "stock_transfer_request"
    ):
        return 0

    branch_users = await _get_branch_users(db, org_id, to_branch_id)
    sent_count = 0

    for user in branch_users:
        try:
            await log_email_sent(
                db,
                org_id=org_id,
                recipient=user["email"],
                template_type="stock_transfer_request",
                subject=f"Stock transfer request: {quantity} x {product_name} from {from_branch_name}",
                status="queued",
                channel="in_app",
            )
            sent_count += 1
        except Exception:
            logger.error(
                "Failed to send stock_transfer_request notification to %s",
                user["email"],
                exc_info=True,
            )

    return sent_count
