"""API router for email template customisation and delivery tracking.

Endpoints:
  GET  /api/v1/notifications/templates                     — list all templates
  GET  /api/v1/notifications/templates/{template_type}     — get single template
  PUT  /api/v1/notifications/templates/{template_type}     — update template
  GET  /api/v1/notifications/templates/{template_type}/preview — preview with sample data
  GET  /api/v1/notifications/log                           — email delivery log (Org_Admin)

Requirements: 34.1, 34.2, 34.3, 35.1, 35.2, 35.3
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.notifications.schemas import (
    EMAIL_TEMPLATE_TYPES,
    SMS_TEMPLATE_TYPES,
    TEMPLATE_VARIABLES,
    NotificationLogEntry,
    NotificationLogResponse,
    OrgSmsSettingsRequest,
    OrgSmsSettingsResponse,
    SmsTemplateListResponse,
    SmsTemplateResponse,
    SmsTemplateUpdateRequest,
    SmsTemplateUpdateResponse,
    TemplateListResponse,
    TemplatePreviewResponse,
    TemplateResponse,
    TemplateUpdateRequest,
    TemplateUpdateResponse,
)
from app.modules.notifications.service import (
    get_sms_template,
    get_template,
    list_notification_log,
    list_sms_templates,
    list_templates,
    render_template_preview,
    update_sms_template,
    update_template,
)

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, uuid.UUID | None, str | None]:
    """Extract org_id, user_id, and ip_address from request."""
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = request.client.host if request.client else None
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
        user_uuid = uuid.UUID(user_id) if user_id else None
    except (ValueError, TypeError):
        return None, None, ip_address
    return org_uuid, user_uuid, ip_address


@router.get("/templates", response_model=TemplateListResponse)
async def list_templates_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all 16 customisable email templates for the organisation.

    Seeds default templates on first access.
    Requirements: 34.1, 34.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_templates(db, org_id=org_uuid)

    return TemplateListResponse(
        templates=[TemplateResponse(**t) for t in result["templates"]],
        total=result["total"],
        available_variables=result["available_variables"],
    )


@router.get("/templates/{template_type}", response_model=TemplateResponse)
async def get_template_endpoint(
    template_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get a single email template by type.

    Requirements: 34.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    if template_type not in EMAIL_TEMPLATE_TYPES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid template type: {template_type}"},
        )

    result = await get_template(db, org_id=org_uuid, template_type=template_type)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Template not found"},
        )

    return TemplateResponse(**result)


@router.put("/templates/{template_type}", response_model=TemplateUpdateResponse)
async def update_template_endpoint(
    template_type: str,
    body: TemplateUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an email template (subject, body blocks, enabled state).

    Requirements: 34.1, 34.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    if template_type not in EMAIL_TEMPLATE_TYPES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid template type: {template_type}"},
        )

    body_blocks_dicts = None
    if body.body_blocks is not None:
        body_blocks_dicts = [b.model_dump() for b in body.body_blocks]

    result = await update_template(
        db,
        org_id=org_uuid,
        template_type=template_type,
        subject=body.subject,
        body_blocks=body_blocks_dicts,
        is_enabled=body.is_enabled,
    )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Template not found"},
        )

    return TemplateUpdateResponse(
        message="Template updated",
        template=TemplateResponse(**result),
    )


@router.get(
    "/templates/{template_type}/preview",
    response_model=TemplatePreviewResponse,
)
async def preview_template_endpoint(
    template_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Preview an email template with sample variable values.

    Requirements: 34.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    if template_type not in EMAIL_TEMPLATE_TYPES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid template type: {template_type}"},
        )

    tpl = await get_template(db, org_id=org_uuid, template_type=template_type)
    if tpl is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Template not found"},
        )

    preview = render_template_preview(
        subject=tpl["subject"],
        body_blocks=tpl["body_blocks"],
    )

    return TemplatePreviewResponse(
        subject=preview["subject"],
        html_body=preview["html_body"],
    )



@router.get("/log", response_model=NotificationLogResponse)
async def get_notification_log(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Entries per page"),
    status: Optional[str] = Query(None, description="Filter by delivery status"),
    channel: Optional[str] = Query(None, description="Filter by channel (email/sms)"),
    db: AsyncSession = Depends(get_db_session),
):
    """View email/SMS delivery log for the organisation.

    Org_Admin only. Returns paginated log entries with delivery status.
    Requirements: 35.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can view the notification log"},
        )

    result = await list_notification_log(
        db,
        org_id=org_uuid,
        page=page,
        page_size=page_size,
        status_filter=status,
        channel_filter=channel,
    )

    return NotificationLogResponse(
        entries=[NotificationLogEntry(**e) for e in result["entries"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )



# ---------------------------------------------------------------------------
# SMS template endpoints (Req 36.2, 36.3, 36.4, 36.5)
# ---------------------------------------------------------------------------


@router.get("/sms-settings", response_model=OrgSmsSettingsResponse)
async def get_sms_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get SMS settings for the organisation.

    Requirements: 36.2
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    from app.modules.admin.models import Organisation
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    settings = org.settings or {}
    return OrgSmsSettingsResponse(
        sms_enabled=settings.get("sms_enabled", False),
        sender_name=settings.get("sms_sender_name", ""),
    )


@router.put("/sms-settings", response_model=OrgSmsSettingsResponse)
async def update_sms_settings(
    body: OrgSmsSettingsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update SMS settings for the organisation.

    Requirements: 36.2, 36.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can update SMS settings"},
        )

    from app.modules.admin.models import Organisation
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if org is None:
        return JSONResponse(status_code=404, content={"detail": "Organisation not found"})

    settings = dict(org.settings or {})
    if body.sms_enabled is not None:
        settings["sms_enabled"] = body.sms_enabled
    if body.sender_name is not None:
        settings["sms_sender_name"] = body.sender_name
    org.settings = settings

    await db.flush()

    return OrgSmsSettingsResponse(
        sms_enabled=settings.get("sms_enabled", False),
        sender_name=settings.get("sms_sender_name", ""),
    )


@router.get("/sms-templates", response_model=SmsTemplateListResponse)
async def list_sms_templates_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all 4 SMS templates for the organisation.

    Seeds default SMS templates on first access.
    Requirements: 36.3, 36.4
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_sms_templates(db, org_id=org_uuid)

    return SmsTemplateListResponse(
        templates=[SmsTemplateResponse(**t) for t in result["templates"]],
        total=result["total"],
        available_variables=result["available_variables"],
    )


@router.get("/sms-templates/{template_type}", response_model=SmsTemplateResponse)
async def get_sms_template_endpoint(
    template_type: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get a single SMS template by type.

    Requirements: 36.3
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    if template_type not in SMS_TEMPLATE_TYPES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid SMS template type: {template_type}"},
        )

    result = await get_sms_template(db, org_id=org_uuid, template_type=template_type)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "SMS template not found"},
        )

    return SmsTemplateResponse(**result)


@router.put(
    "/sms-templates/{template_type}",
    response_model=SmsTemplateUpdateResponse,
)
async def update_sms_template_endpoint(
    template_type: str,
    body: SmsTemplateUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an SMS template (body text, enabled state).

    Warns if body exceeds 160 characters.
    Requirements: 36.3, 36.5
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    if template_type not in SMS_TEMPLATE_TYPES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Invalid SMS template type: {template_type}"},
        )

    result = await update_sms_template(
        db,
        org_id=org_uuid,
        template_type=template_type,
        body=body.body,
        is_enabled=body.is_enabled,
    )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "SMS template not found"},
        )

    msg = "SMS template updated"
    if result.get("exceeds_limit"):
        msg = "SMS template updated (warning: body exceeds 160 characters)"

    return SmsTemplateUpdateResponse(
        message=msg,
        template=SmsTemplateResponse(**result),
    )


# ---------------------------------------------------------------------------
# Overdue reminder rule endpoints (Req 38.1, 38.2, 38.3, 38.4)
# ---------------------------------------------------------------------------

from app.modules.notifications.schemas import (
    OverdueReminderRuleCreate,
    OverdueReminderRuleListResponse,
    OverdueReminderRuleResponse,
    OverdueReminderRuleUpdate,
)
from app.modules.notifications.service import (
    create_reminder_rule,
    delete_reminder_rule,
    list_reminder_rules,
    update_reminder_rule,
    _set_reminders_enabled,
)


@router.get("/overdue-rules", response_model=OverdueReminderRuleListResponse)
async def list_overdue_rules(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all overdue reminder rules for the organisation.

    Requirements: 38.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    result = await list_reminder_rules(db, org_id=org_uuid)

    return OverdueReminderRuleListResponse(
        rules=[OverdueReminderRuleResponse(**r) for r in result["rules"]],
        total=result["total"],
        reminders_enabled=result["reminders_enabled"],
    )


@router.post("/overdue-rules", response_model=OverdueReminderRuleResponse, status_code=201)
async def create_overdue_rule(
    body: OverdueReminderRuleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new overdue reminder rule (max 3 per org).

    Requirements: 38.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage overdue reminder rules"},
        )

    result = await create_reminder_rule(
        db,
        org_id=org_uuid,
        days_after_due=body.days_after_due,
        send_email=body.send_email,
        send_sms=body.send_sms,
        is_enabled=body.is_enabled,
    )

    if isinstance(result, str):
        return JSONResponse(status_code=400, content={"detail": result})

    return OverdueReminderRuleResponse(**result)


@router.put("/overdue-rules/{rule_id}", response_model=OverdueReminderRuleResponse)
async def update_overdue_rule(
    rule_id: str,
    body: OverdueReminderRuleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an overdue reminder rule.

    Requirements: 38.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage overdue reminder rules"},
        )

    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid rule ID"})

    result = await update_reminder_rule(
        db,
        org_id=org_uuid,
        rule_id=rule_uuid,
        days_after_due=body.days_after_due,
        send_email=body.send_email,
        send_sms=body.send_sms,
        is_enabled=body.is_enabled,
    )

    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Rule not found"})
    if isinstance(result, str):
        return JSONResponse(status_code=400, content={"detail": result})

    return OverdueReminderRuleResponse(**result)


@router.delete("/overdue-rules/{rule_id}")
async def delete_overdue_rule(
    rule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete an overdue reminder rule.

    Requirements: 38.1
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage overdue reminder rules"},
        )

    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid rule ID"})

    deleted = await delete_reminder_rule(db, org_id=org_uuid, rule_id=rule_uuid)

    if not deleted:
        return JSONResponse(status_code=404, content={"detail": "Rule not found"})

    return JSONResponse(content={"message": "Rule deleted"})


@router.put("/overdue-rules-toggle")
async def toggle_overdue_reminders(
    request: Request,
    enabled: bool = Query(..., description="Enable or disable overdue reminders"),
    db: AsyncSession = Depends(get_db_session),
):
    """Enable or disable the entire overdue reminder feature for the org.

    Disabled by default; automatic once enabled until disabled (Req 38.4).
    """
    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can toggle overdue reminders"},
        )

    await _set_reminders_enabled(db, org_id=org_uuid, enabled=enabled)

    return JSONResponse(content={
        "message": f"Overdue reminders {'enabled' if enabled else 'disabled'}",
        "reminders_enabled": enabled,
    })


# ---------------------------------------------------------------------------
# WOF / Registration expiry reminder settings (Req 39.1, 39.2, 39.3, 39.4)
# ---------------------------------------------------------------------------


@router.get("/wof-rego-settings")
async def get_wof_rego_settings_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get WOF and registration expiry reminder settings for the org.

    Requirements: 39.1, 39.2, 39.4
    """
    from app.modules.notifications.service import get_wof_rego_settings
    from app.modules.notifications.schemas import WofRegoReminderSettingsResponse

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    settings = await get_wof_rego_settings(db, org_id=org_uuid)
    return WofRegoReminderSettingsResponse(**settings)


@router.put("/wof-rego-settings")
async def update_wof_rego_settings_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update WOF and registration expiry reminder settings for the org.

    Only Org_Admin can modify these settings. Disabled by default (Req 39.1).

    Requirements: 39.1, 39.2, 39.4
    """
    from app.modules.notifications.service import update_wof_rego_settings
    from app.modules.notifications.schemas import (
        WofRegoReminderSettingsRequest,
        WofRegoReminderSettingsResponse,
    )

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage WOF/rego reminder settings"},
        )

    body = await request.json()
    payload = WofRegoReminderSettingsRequest(**body)

    updated = await update_wof_rego_settings(
        db,
        org_id=org_uuid,
        enabled=payload.enabled,
        days_in_advance=payload.days_in_advance,
        channel=payload.channel,
    )

    return WofRegoReminderSettingsResponse(**updated)


# ---------------------------------------------------------------------------
# Notification preference endpoints (Req 83.1, 83.2, 83.3, 83.4)
# ---------------------------------------------------------------------------


@router.get("/settings")
async def get_notification_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Get all notification preferences grouped by category.

    Returns every known notification type with its current enabled/channel
    state. Types without a stored preference default to disabled + email.

    Requirements: 83.1, 83.3
    """
    from app.modules.notifications.service import list_notification_preferences
    from app.modules.notifications.schemas import NotificationPreferencesResponse

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    data = await list_notification_preferences(db, org_id=org_uuid)
    return NotificationPreferencesResponse(**data)


@router.put("/settings")
async def update_notification_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a single notification type preference.

    Only Org_Admin can modify notification preferences. Each notification
    type is individually toggleable and supports independent channel config.

    Requirements: 83.1, 83.2, 83.4
    """
    from app.modules.notifications.service import update_notification_preference
    from app.modules.notifications.schemas import (
        NotificationPreferenceUpdateRequest,
        NotificationPreferenceItem,
    )

    org_uuid, _, _ = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    role = getattr(request.state, "role", None)
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage notification preferences"},
        )

    body = await request.json()
    payload = NotificationPreferenceUpdateRequest(**body)

    try:
        updated = await update_notification_preference(
            db,
            org_id=org_uuid,
            notification_type=payload.notification_type,
            is_enabled=payload.is_enabled,
            channel=payload.channel,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return NotificationPreferenceItem(**updated)
