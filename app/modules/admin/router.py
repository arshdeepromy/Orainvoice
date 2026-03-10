"""Global Admin router — organisation provisioning and management."""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db_session
from app.modules.admin.schemas import (
    AdminCarjamUsageResponse,
    AdminSmsUsageResponse,
    CarjamConfigRequest,
    CarjamConfigResponse,
    CarjamCostReportResponse,
    CarjamTestResponse,
    ChurnOrgRow,
    ChurnReportResponse,
    ErrorLogStatusUpdateRequest,
    IntegrationConfigGetResponse,
    MrrPlanBreakdown,
    MrrMonthTrend,
    MrrReportResponse,
    OrgCarjamUsageRow,
    OrgSmsUsageRow,
    OrgDeleteRequest,
    OrgDeleteRequestResponse,
    OrgDeleteResponse,
    OrgHardDeleteRequest,
    OrgHardDeleteResponse,
    OrgListItem,
    OrgListResponse,
    OrgOverviewResponse,
    OrgOverviewRow,
    OrgUpdateRequest,
    OrgUpdateResponse,
    PlanCreateRequest,
    PlanListResponse,
    PlanResponse,
    PlanUpdateRequest,
    PlatformSettingsUpdateRequest,
    ProvisionOrganisationRequest,
    ProvisionOrganisationResponse,
    SmtpConfigRequest,
    SmtpConfigResponse,
    SmtpTestEmailResponse,
    StripeConfigRequest,
    StripeConfigResponse,
    StripeTestResponse,
    TwilioConfigRequest,
    TwilioConfigResponse,
    TwilioTestSmsRequest,
    TwilioTestSmsResponse,
    VehicleDbStatsResponse,
)
from app.modules.admin.service import (
    archive_plan,
    create_plan,
    delete_organisation,
    hard_delete_organisation,
    get_all_orgs_carjam_usage,
    get_all_orgs_sms_usage,
    get_carjam_cost_report,
    get_churn_report,
    get_integration_config,
    get_mrr_report,
    get_org_overview_report,
    get_plan,
    get_vehicle_db_stats,
    list_organisations,
    list_plans,
    provision_organisation,
    save_carjam_config,
    save_smtp_config,
    save_stripe_config,
    save_twilio_config,
    send_test_email,
    send_test_sms,
    test_carjam_connection,
    test_stripe_connection,
    update_organisation,
    update_plan,
)
from app.modules.auth.rbac import require_role

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/organisations",
    response_model=ProvisionOrganisationResponse,
    responses={
        400: {"description": "Validation error (bad plan, duplicate email, etc.)"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Provision a new organisation",
    dependencies=[require_role("global_admin")],
)
async def create_organisation(
    payload: ProvisionOrganisationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Provision a new organisation, assign a subscription plan, and
    generate an Org_Admin invitation email.

    Only Global_Admin users can access this endpoint.
    Requirement 8.1.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        plan_uuid = uuid.UUID(payload.plan_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid plan_id format"},
        )

    try:
        result = await provision_organisation(
            db,
            name=payload.name,
            plan_id=plan_uuid,
            admin_email=payload.admin_email,
            status=payload.status,
            provisioned_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return ProvisionOrganisationResponse(
        message="Organisation provisioned successfully",
        **result,
    )


@router.get(
    "/organisations",
    response_model=OrgListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List all organisations (sortable, searchable)",
    dependencies=[require_role("global_admin")],
)
async def list_orgs(
    search: str | None = None,
    status: str | None = None,
    plan_id: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 25,
    db: AsyncSession = Depends(get_db_session),
):
    """List all organisations in a sortable and searchable table.

    Supports filtering by name (search), status, and plan_id.
    Supports sorting by created_at, updated_at, name, status.

    Only Global_Admin users can access this endpoint.
    Requirement 47.1.
    """
    plan_uuid = None
    if plan_id:
        try:
            plan_uuid = uuid.UUID(plan_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid plan_id format"})

    data = await list_organisations(
        db,
        search=search,
        status=status,
        plan_id=plan_uuid,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )

    return OrgListResponse(
        organisations=[OrgListItem(**o) for o in data["organisations"]],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
    )


@router.put(
    "/organisations/{org_id}",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    summary="Update organisation (suspend, reinstate, delete request, move plan)",
    dependencies=[require_role("global_admin")],
)
async def update_org(
    org_id: str,
    payload: OrgUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an organisation: suspend, reinstate, activate, deactivate, initiate deletion, or move between plans.

    Actions:
    - suspend: Temporarily suspend organisation (requires reason)
    - reinstate: Reactivate from suspended state
    - activate: Activate organisation from any non-deleted state
    - deactivate: Deactivate organisation (requires reason)
    - delete_request: Initiate soft deletion (step 1 of 2, returns confirmation token)
    - hard_delete_request: Initiate permanent deletion (step 1 of 2, returns confirmation token)
    - move_plan: Move organisation to a different subscription plan

    For suspend/delete_request/deactivate, a reason is required (stored in audit log).
    Optionally sends email to Org_Admin.

    Only Global_Admin users can access this endpoint.
    Requirements 47.2, 47.3.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    new_plan_uuid = None
    if payload.new_plan_id:
        try:
            new_plan_uuid = uuid.UUID(payload.new_plan_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid new_plan_id format"})

    try:
        result = await update_organisation(
            db,
            org_id=org_uuid,
            action=payload.action,
            reason=payload.reason,
            new_plan_id=new_plan_uuid,
            notify_org_admin=payload.notify_org_admin,
            updated_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    # delete_request or hard_delete_request returns a confirmation token
    if payload.action in ("delete_request", "hard_delete_request"):
        from app.modules.admin.schemas import OrgDeleteRequestResponse
        return OrgDeleteRequestResponse(
            message=result["message"],
            organisation_id=result["organisation_id"],
            organisation_name=result["organisation_name"],
            confirmation_token=result["confirmation_token"],
            expires_in_seconds=result["expires_in_seconds"],
        )

    return OrgUpdateResponse(**result)


@router.delete(
    "/organisations/{org_id}",
    response_model=OrgDeleteResponse,
    responses={
        400: {"description": "Validation error or invalid token"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    summary="Delete organisation (multi-step confirmation)",
    dependencies=[require_role("global_admin")],
)
async def delete_org(
    org_id: str,
    payload: OrgDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete an organisation (soft-delete to 'deleted' status).

    Requires a confirmation_token obtained from the delete_request action
    on PUT /organisations/{id}. This implements multi-step confirmation.

    A reason is required and stored in the audit log.
    Optionally sends email to Org_Admin.

    Only Global_Admin users can access this endpoint.
    Requirements 47.2, 47.3.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    try:
        result = await delete_organisation(
            db,
            org_id=org_uuid,
            reason=payload.reason,
            confirmation_token=payload.confirmation_token,
            notify_org_admin=payload.notify_org_admin,
            deleted_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return OrgDeleteResponse(**result)


@router.delete(
    "/organisations/{org_id}/hard",
    response_model=OrgHardDeleteResponse,
    responses={
        400: {"description": "Validation error, invalid token, or incorrect confirmation text"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    summary="PERMANENTLY delete organisation and ALL data (multi-step confirmation)",
    dependencies=[require_role("global_admin")],
)
async def hard_delete_org(
    org_id: str,
    payload: OrgHardDeleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """PERMANENTLY delete an organisation and ALL related data from the database.

    This is IRREVERSIBLE and removes:
    - Organisation record
    - All users in the organisation
    - All vehicles, customers, invoices, quotes, etc.
    - Audit logs are kept for compliance
    
    Requires:
    1. A confirmation_token obtained from the hard_delete_request action on PUT /organisations/{id}
    2. User must type "PERMANENTLY DELETE" exactly in the confirm_text field
    
    This implements multi-step confirmation for safety.
    A reason is required and stored in the audit log before deletion.

    Only Global_Admin users can access this endpoint.
    Requirements 47.2, 47.3.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    try:
        result = await hard_delete_organisation(
            db,
            org_id=org_uuid,
            reason=payload.reason,
            confirmation_token=payload.confirmation_token,
            confirm_text=payload.confirm_text,
            deleted_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error during hard delete")
        return JSONResponse(status_code=500, content={"detail": "An error occurred during deletion"})

    return OrgHardDeleteResponse(**result)


@router.get(
    "/carjam-usage",
    response_model=AdminCarjamUsageResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Carjam usage table for all organisations",
    dependencies=[require_role("global_admin")],
)
async def get_carjam_usage(
    db: AsyncSession = Depends(get_db_session),
):
    """Return real-time Carjam API usage per organisation.

    Shows total lookups this month, included in plan, overage count,
    and overage charge accrued for every non-deleted organisation.

    Only Global_Admin users can access this endpoint.
    Requirement 16.1.
    """
    usage_list, per_lookup_cost = await get_all_orgs_carjam_usage(db)

    return AdminCarjamUsageResponse(
        per_lookup_cost_nzd=per_lookup_cost,
        organisations=[OrgCarjamUsageRow(**row) for row in usage_list],
    )


# ---------------------------------------------------------------------------
# SMS usage reporting (Req 7.4)
# ---------------------------------------------------------------------------


@router.get(
    "/sms-usage",
    response_model=AdminSmsUsageResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="SMS usage table for all organisations",
    dependencies=[require_role("global_admin")],
)
async def get_sms_usage(
    db: AsyncSession = Depends(get_db_session),
):
    """Return real-time SMS usage per organisation.

    Shows total SMS sent this month, included in plan, package credits,
    effective quota, overage count, and overage charge accrued for every
    non-deleted organisation.

    Only Global_Admin users can access this endpoint.
    Requirement 7.4.
    """
    usage_list, _cost = await get_all_orgs_sms_usage(db)

    return AdminSmsUsageResponse(
        organisations=[OrgSmsUsageRow(**row) for row in usage_list],
    )


# ---------------------------------------------------------------------------
# SMTP / Email integration configuration (Req 33.1, 33.2, 33.3)
# ---------------------------------------------------------------------------


@router.put(
    "/integrations/smtp",
    response_model=SmtpConfigResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Configure platform-wide email relay",
    dependencies=[require_role("global_admin")],
)
async def configure_smtp(
    payload: SmtpConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure the platform-wide SMTP or email relay.

    Supports Brevo, SendGrid, or custom SMTP with API key, domain,
    from name, and reply-to address.

    Only Global_Admin users can access this endpoint.
    Requirement 33.1.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await save_smtp_config(
            db,
            provider=payload.provider,
            api_key=payload.api_key,
            host=payload.host,
            port=payload.port,
            username=payload.username,
            password=payload.password,
            domain=payload.domain,
            from_email=payload.from_email,
            from_name=payload.from_name,
            reply_to=payload.reply_to,
            updated_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return SmtpConfigResponse(message="SMTP configuration saved", **result)


@router.post(
    "/integrations/smtp/test",
    response_model=SmtpTestEmailResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Send test email to Global Admin",
    dependencies=[require_role("global_admin")],
)
async def test_smtp_email(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a real test email to the Global_Admin's address to confirm
    the SMTP configuration is working.

    Only Global_Admin users can access this endpoint.
    Requirement 33.2.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    # Look up the admin's email
    admin_email = getattr(request.state, "email", None)
    if not admin_email and user_id:
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_id))
        )
        user = result.scalar_one_or_none()
        if user:
            admin_email = user.email

    if not admin_email:
        return SmtpTestEmailResponse(
            success=False,
            message="Could not determine admin email address",
        )

    test_result = await send_test_email(
        db,
        admin_email=admin_email,
        admin_user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
        ip_address=ip_address,
    )

    return SmtpTestEmailResponse(**test_result)



# ---------------------------------------------------------------------------
# Twilio / SMS integration configuration (Req 36.1)
# ---------------------------------------------------------------------------


@router.put(
    "/integrations/twilio",
    response_model=TwilioConfigResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Configure platform-wide Twilio SMS",
    dependencies=[require_role("global_admin")],
)
async def configure_twilio(
    payload: TwilioConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure the platform-wide Twilio SMS credentials.

    Stores account SID, auth token, and default sender number.
    Only Global_Admin users can access this endpoint.
    Requirement 36.1.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await save_twilio_config(
            db,
            account_sid=payload.account_sid,
            auth_token=payload.auth_token,
            sender_number=payload.sender_number,
            updated_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return TwilioConfigResponse(message="Twilio configuration saved", **result)


@router.post(
    "/integrations/twilio/test",
    response_model=TwilioTestSmsResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Send test SMS via Twilio",
    dependencies=[require_role("global_admin")],
)
async def test_twilio_sms(
    payload: TwilioTestSmsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a real test SMS to verify the Twilio configuration.

    Only Global_Admin users can access this endpoint.
    Requirement 36.1.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    test_result = await send_test_sms(
        db,
        to_number=payload.to_number,
        admin_user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
        ip_address=ip_address,
    )

    return TwilioTestSmsResponse(**test_result)



# ---------------------------------------------------------------------------
# Module Registry (admin view — no org context required)
# ---------------------------------------------------------------------------


@router.get(
    "/modules/registry",
    summary="List all modules from the global registry",
    dependencies=[require_role("global_admin")],
)
async def list_module_registry(
    db: AsyncSession = Depends(get_db_session),
):
    """Return every module in the global registry.

    Unlike the org-scoped ``/modules`` endpoint this does NOT require
    organisation context and returns the full catalogue so the admin
    can assign modules to subscription plans.
    """
    from app.modules.module_management.models import ModuleRegistry
    from sqlalchemy import select as sa_select

    result = await db.execute(sa_select(ModuleRegistry).order_by(ModuleRegistry.category, ModuleRegistry.display_name))
    rows = result.scalars().all()
    modules = []
    for r in rows:
        deps = r.dependencies or []
        if isinstance(deps, str):
            import json as _json
            try:
                deps = _json.loads(deps)
            except (ValueError, TypeError):
                deps = []
        modules.append({
            "slug": r.slug,
            "display_name": r.display_name,
            "description": r.description,
            "category": r.category,
            "is_core": r.is_core,
            "dependencies": deps if isinstance(deps, list) else [],
        })
    return {"modules": modules, "total": len(modules)}


# ---------------------------------------------------------------------------
# Subscription Plan Management (Req 40.1, 40.2, 40.3, 40.4)
# ---------------------------------------------------------------------------


@router.get(
    "/plans",
    response_model=PlanListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List subscription plans",
    dependencies=[require_role("global_admin")],
)
async def get_plans(
    include_archived: bool = False,
    db: AsyncSession = Depends(get_db_session),
):
    """List all subscription plans.

    By default, archived plans are excluded. Pass `include_archived=true`
    to include them.

    Only Global_Admin users can access this endpoint.
    Requirement 40.1.
    """
    plans = await list_plans(db, include_archived=include_archived)
    return PlanListResponse(plans=[PlanResponse(**p) for p in plans], total=len(plans))


@router.post(
    "/plans",
    response_model=PlanResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error (duplicate name, etc.)"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Create a subscription plan",
    dependencies=[require_role("global_admin")],
)
async def create_subscription_plan(
    payload: PlanCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new subscription plan.

    Only Global_Admin users can access this endpoint.
    Requirements 40.1, 40.2, 40.4.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await create_plan(
            db,
            name=payload.name,
            monthly_price_nzd=payload.monthly_price_nzd,
            user_seats=payload.user_seats,
            storage_quota_gb=payload.storage_quota_gb,
            carjam_lookups_included=payload.carjam_lookups_included,
            enabled_modules=payload.enabled_modules,
            is_public=payload.is_public,
            storage_tier_pricing=[t.model_dump() for t in payload.storage_tier_pricing],
            trial_duration=payload.trial_duration,
            trial_duration_unit=payload.trial_duration_unit,
            sms_included=payload.sms_included,
            per_sms_cost_nzd=payload.per_sms_cost_nzd,
            sms_included_quota=payload.sms_included_quota,
            sms_package_pricing=[t.model_dump() for t in payload.sms_package_pricing] if payload.sms_package_pricing else [],
            created_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return PlanResponse(**result)


@router.put(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Plan not found"},
    },
    summary="Update a subscription plan",
    dependencies=[require_role("global_admin")],
)
async def update_subscription_plan(
    plan_id: str,
    payload: PlanUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a subscription plan without affecting existing subscribers.

    Only Global_Admin users can access this endpoint.
    Requirements 40.3, 40.4.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        plan_uuid = uuid.UUID(plan_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid plan_id format"})

    updates = payload.model_dump(exclude_none=True)
    if "storage_tier_pricing" in updates:
        updates["storage_tier_pricing"] = [
            t.model_dump() if hasattr(t, "model_dump") else t
            for t in updates["storage_tier_pricing"]
        ]
    if "sms_package_pricing" in updates:
        updates["sms_package_pricing"] = [
            t.model_dump() if hasattr(t, "model_dump") else t
            for t in updates["sms_package_pricing"]
        ]

    try:
        result = await update_plan(
            db,
            plan_uuid,
            updates=updates,
            updated_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error updating subscription plan")
        return JSONResponse(status_code=500, content={"detail": "An error occurred while updating the plan"})

    return PlanResponse(**result)


@router.put(
    "/plans/{plan_id}/archive",
    response_model=PlanResponse,
    responses={
        400: {"description": "Plan already archived"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Plan not found"},
    },
    summary="Archive a subscription plan",
    dependencies=[require_role("global_admin")],
)
async def archive_subscription_plan(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Archive a subscription plan without affecting existing subscribers.

    Only Global_Admin users can access this endpoint.
    Requirement 40.3.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        plan_uuid = uuid.UUID(plan_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid plan_id format"})

    try:
        result = await archive_plan(
            db,
            plan_uuid,
            archived_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return PlanResponse(**result)


# ---------------------------------------------------------------------------
# Global Admin Reports (Req 46.1–46.5)
# ---------------------------------------------------------------------------


@router.get(
    "/reports/mrr",
    response_model=MrrReportResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Platform MRR report",
    dependencies=[require_role("global_admin")],
)
async def get_mrr(
    db: AsyncSession = Depends(get_db_session),
):
    """Platform MRR with plan breakdown and month-over-month trend.

    Only Global_Admin users can access this endpoint.
    Requirement 46.2.
    """
    data = await get_mrr_report(db)
    return MrrReportResponse(
        total_mrr_nzd=data["total_mrr_nzd"],
        plan_breakdown=[MrrPlanBreakdown(**p) for p in data["plan_breakdown"]],
        month_over_month=[MrrMonthTrend(**m) for m in data["month_over_month"]],
    )


@router.get(
    "/reports/organisations",
    response_model=OrgOverviewResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Organisation overview report",
    dependencies=[require_role("global_admin")],
)
async def get_org_overview(
    db: AsyncSession = Depends(get_db_session),
):
    """Table of all organisations with plan, signup date, trial status,
    billing status, storage, Carjam usage, and last login.

    Only Global_Admin users can access this endpoint.
    Requirement 46.3.
    """
    data = await get_org_overview_report(db)
    return OrgOverviewResponse(
        organisations=[OrgOverviewRow(**o) for o in data["organisations"]],
        total=data["total"],
    )


@router.get(
    "/reports/carjam-cost",
    response_model=CarjamCostReportResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Carjam cost vs revenue report",
    dependencies=[require_role("global_admin")],
)
async def get_carjam_cost(
    db: AsyncSession = Depends(get_db_session),
):
    """Carjam cost vs revenue analysis.

    Only Global_Admin users can access this endpoint.
    Requirement 46.1.
    """
    data = await get_carjam_cost_report(db)
    return CarjamCostReportResponse(**data)


@router.get(
    "/reports/churn",
    response_model=ChurnReportResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Churn report",
    dependencies=[require_role("global_admin")],
)
async def get_churn(
    db: AsyncSession = Depends(get_db_session),
):
    """Churn report showing cancelled/suspended organisations with plan type
    and subscription duration.

    Only Global_Admin users can access this endpoint.
    Requirement 46.5.
    """
    data = await get_churn_report(db)
    return ChurnReportResponse(
        churned_organisations=[ChurnOrgRow(**c) for c in data["churned_organisations"]],
        total=data["total"],
    )


@router.get(
    "/reports/billing-issues",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Billing issues report",
    dependencies=[require_role("global_admin")],
)
async def get_billing_issues(
    db: AsyncSession = Depends(get_db_session),
):
    """Return organisations with billing issues (overdue, failed payments, etc.).

    Used by the Global Admin dashboard.
    """
    from sqlalchemy import text as sa_text

    try:
        result = await db.execute(
            sa_text(
                """
                SELECT o.id, o.name, o.status, o.updated_at
                FROM organisations o
                WHERE o.status IN ('grace_period', 'suspended')
                ORDER BY o.updated_at DESC
                LIMIT 50
                """
            )
        )
        rows = result.all()
        issues = []
        for row in rows:
            issues.append({
                "id": str(row[0]),
                "org_name": row[1],
                "issue_type": "grace_period" if row[2] == "grace_period" else "suspended",
                "amount": 0,
                "created_at": row[3].isoformat() if row[3] else None,
            })
        return issues
    except Exception:
        return []


@router.get(
    "/vehicle-db/stats",
    response_model=VehicleDbStatsResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Global Vehicle Database statistics",
    dependencies=[require_role("global_admin")],
)
async def get_vehicle_db_statistics(
    db: AsyncSession = Depends(get_db_session),
):
    """Global Vehicle Database stats: total records, cache hit rate,
    and total lookups.

    Only Global_Admin users can access this endpoint.
    Requirement 46.4.
    """
    data = await get_vehicle_db_stats(db)
    return VehicleDbStatsResponse(**data)


# ---------------------------------------------------------------------------
# Generic integration config GET endpoint (Req 48.1)
# ---------------------------------------------------------------------------


@router.get(
    "/integrations",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List all integration statuses",
    dependencies=[require_role("global_admin")],
)
async def list_integrations(
    db: AsyncSession = Depends(get_db_session),
):
    """Return health status for all known integrations.

    Used by the Global Admin dashboard to show integration health at a glance.
    """
    integration_names = ("carjam", "stripe", "smtp", "twilio")
    results = []
    for name in integration_names:
        config = await get_integration_config(db, name=name)
        results.append({
            "name": name,
            "status": "healthy" if config and config.get("is_verified") else "down",
            "last_checked": config.get("updated_at") if config else None,
        })
    return results


@router.get(
    "/integrations/{name}",
    response_model=IntegrationConfigGetResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Unknown integration name"},
    },
    summary="Get integration configuration (non-secret fields)",
    dependencies=[require_role("global_admin")],
)
async def get_integration(
    name: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return non-secret configuration fields for an integration.

    Secrets are never returned — only masked (last 4 chars) versions.
    Only Global_Admin users can access this endpoint.
    Requirement 48.1, 48.5.
    """
    result = await get_integration_config(db, name=name)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Unknown integration: {name}"},
        )
    return IntegrationConfigGetResponse(**result)


# ---------------------------------------------------------------------------
# Carjam integration config endpoints (Req 48.3)
# ---------------------------------------------------------------------------


@router.put(
    "/integrations/carjam",
    response_model=CarjamConfigResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Configure Carjam integration",
    dependencies=[require_role("global_admin")],
)
async def configure_carjam(
    payload: CarjamConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure the platform-wide Carjam API credentials.

    Stores API key, endpoint URL, per-lookup cost, and global rate limit.
    Only updates fields that are provided in the request.
    Only Global_Admin users can access this endpoint.
    Requirement 48.3.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await save_carjam_config(
            db,
            api_key=payload.api_key,
            endpoint_url=payload.endpoint_url,
            per_lookup_cost_nzd=payload.per_lookup_cost_nzd,
            global_rate_limit_per_minute=payload.global_rate_limit_per_minute,
            updated_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return CarjamConfigResponse(message="Carjam configuration saved", **result)


@router.post(
    "/integrations/carjam/test",
    response_model=CarjamTestResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Test Carjam connection",
    dependencies=[require_role("global_admin")],
)
async def test_carjam(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Test the Carjam API connection using the saved configuration.

    Only Global_Admin users can access this endpoint.
    Requirement 48.2.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    test_result = await test_carjam_connection(
        db,
        admin_user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
        ip_address=ip_address,
    )

    return CarjamTestResponse(**test_result)


@router.post(
    "/integrations/carjam/lookup-test",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Vehicle not found"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"},
        504: {"description": "Request timeout"},
    },
    summary="Test vehicle lookup (admin only)",
    dependencies=[require_role("global_admin")],
)
async def test_vehicle_lookup(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Test vehicle lookup by registration for admin testing purposes.
    
    Uses the existing vehicle lookup service with cache-first strategy.
    Does NOT increment any org's usage counter (uses a test context).
    
    Only Global_Admin users can access this endpoint.
    """
    import asyncio
    from app.modules.vehicles.service import lookup_vehicle as lookup_vehicle_service
    from app.integrations.carjam import CarjamNotFoundError, CarjamRateLimitError, CarjamError
    from app.core.redis import redis_pool
    
    logger.info("=== VEHICLE LOOKUP TEST START ===")
    logger.info(f"Payload received: {payload}")
    
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None
    rego = payload.get("rego", "").upper().strip()
    
    logger.info(f"User ID: {user_id}, IP: {ip_address}, Rego: {rego}")
    
    if not rego:
        logger.warning("No rego provided in payload")
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Registration number is required"},
        )
    
    # Get first org for testing context (or create a dummy UUID)
    try:
        org_result = await db.execute(
            text("SELECT id FROM organisations LIMIT 1")
        )
        org_row = org_result.first()
        test_org_id = uuid.UUID(org_row[0]) if org_row else uuid.uuid4()
        logger.info(f"Using test org_id: {test_org_id}")
    except Exception as e:
        logger.error(f"Failed to get org_id: {e}")
        test_org_id = uuid.uuid4()
    
    # Use redis_pool directly instead of get_redis()
    logger.info(f"Using redis_pool: {redis_pool}")
    
    try:
        logger.info(f"Calling lookup_vehicle_service for rego: {rego}")
        
        # Add timeout to prevent hanging
        result = await asyncio.wait_for(
            lookup_vehicle_service(
                db,
                redis_pool,
                rego=rego,
                org_id=test_org_id,
                user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
                ip_address=ip_address,
            ),
            timeout=30.0  # 30 second timeout
        )
        
        logger.info(f"Lookup successful! Result: {result}")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Vehicle found: {result.get('make', '')} {result.get('model', '')}",
                "data": result,
                "source": result.get("source", "unknown"),
            },
        )
    except asyncio.TimeoutError:
        logger.error(f"Vehicle lookup timed out after 30 seconds")
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "message": "Request timed out. Please try again.",
            },
        )
    except CarjamNotFoundError as exc:
        logger.warning(f"Vehicle not found: {exc}")
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "message": f"No vehicle found for registration '{rego}'",
                "rego": rego,
            },
        )
    except CarjamRateLimitError as exc:
        logger.warning(f"Rate limit exceeded: {exc}")
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "message": "Rate limit exceeded. Please try again shortly.",
                "retry_after": exc.retry_after,
            },
            headers={"Retry-After": str(exc.retry_after)},
        )
    except CarjamError as exc:
        logger.error(f"Carjam service error: {exc}")
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "message": f"Carjam service error: {str(exc)}",
            },
        )
    except Exception as exc:
        logger.error(f"Unexpected error in test vehicle lookup: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Unexpected error: {str(exc)}",
            },
        )


@router.post(
    "/integrations/carjam/lookup-test-abcd",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Vehicle not found"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Internal server error"},
        504: {"description": "Request timeout"},
    },
    summary="Test ABCD vehicle lookup (admin only)",
    dependencies=[require_role("global_admin")],
)
async def test_vehicle_lookup_abcd(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Test ABCD (Absolute Basic Car Details) vehicle lookup for admin testing.
    
    ABCD is a lower-cost API option that provides basic vehicle information.
    Stores results in global_vehicles database but does NOT increment org usage counters.
    
    Only Global_Admin users can access this endpoint.
    """
    import asyncio
    from app.integrations.carjam import CarjamClient, CarjamNotFoundError, CarjamRateLimitError, CarjamError
    from app.core.redis import redis_pool
    from app.modules.admin.service import get_integration_config
    from app.core.encryption import envelope_decrypt_str
    from app.modules.vehicles.service import _carjam_data_to_global_vehicle, _global_vehicle_to_dict
    from app.modules.admin.models import GlobalVehicle
    from sqlalchemy import select
    import json
    
    logger.info("=== ABCD VEHICLE LOOKUP TEST START ===")
    logger.info(f"Payload received: {payload}")
    
    rego = payload.get("rego", "").upper().strip()
    use_mvr = payload.get("use_mvr", True)  # Default to True
    
    logger.info(f"Rego: {rego}, Use MVR: {use_mvr}")
    
    if not rego:
        logger.warning("No rego provided in payload")
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Registration number is required"},
        )
    
    # Load Carjam config
    try:
        from app.modules.admin.models import IntegrationConfig
        from sqlalchemy import select
        
        config_result = await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
        )
        config_row = config_result.scalar_one_or_none()
        
        if not config_row:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Carjam integration not configured"},
            )
        
        config_data = json.loads(envelope_decrypt_str(config_row.config_encrypted))
        api_key = config_data.get("api_key", "")
        base_url = config_data.get("endpoint_url", "https://www.carjam.co.nz")
        rate_limit = config_data.get("global_rate_limit_per_minute", 60)
        
        logger.info(f"Loaded Carjam config: base_url={base_url}, has_api_key={bool(api_key)}")
    except Exception as e:
        logger.error(f"Failed to load Carjam config: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Failed to load Carjam configuration"},
        )
    
    try:
        logger.info(f"Calling CarjamClient.lookup_vehicle_abcd for rego: {rego}")
        
        client = CarjamClient(
            redis=redis_pool,
            api_key=api_key,
            base_url=base_url,
            rate_limit=rate_limit,
        )
        
        # ABCD API may return null initially while fetching data
        # Implement retry logic with up to 3 attempts
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                # Add timeout to prevent hanging
                result = await asyncio.wait_for(
                    client.lookup_vehicle_abcd(rego, use_mvr=use_mvr),
                    timeout=30.0  # 30 second timeout
                )
                
                logger.info(f"ABCD Lookup successful on attempt {attempt + 1}! Result: {result}")
                
                # Check if vehicle already exists in database
                existing_result = await db.execute(
                    select(GlobalVehicle).where(GlobalVehicle.rego == rego)
                )
                existing_vehicle = existing_result.scalar_one_or_none()
                
                if existing_vehicle:
                    # Update existing record
                    logger.info(f"Updating existing vehicle record for {rego}")
                    from datetime import datetime, timezone
                    from app.modules.vehicles.service import _parse_date
                    
                    now = datetime.now(timezone.utc)
                    existing_vehicle.make = result.make
                    existing_vehicle.model = result.model
                    existing_vehicle.year = result.year
                    existing_vehicle.colour = result.colour
                    existing_vehicle.body_type = result.body_type
                    existing_vehicle.fuel_type = result.fuel_type
                    existing_vehicle.engine_size = result.engine_size
                    existing_vehicle.num_seats = result.seats
                    existing_vehicle.wof_expiry = _parse_date(result.wof_expiry)
                    existing_vehicle.registration_expiry = _parse_date(result.rego_expiry)
                    existing_vehicle.odometer_last_recorded = result.odometer
                    existing_vehicle.last_pulled_at = now
                    existing_vehicle.lookup_type = result.lookup_type
                    # Extended fields
                    existing_vehicle.vin = result.vin
                    existing_vehicle.chassis = result.chassis
                    existing_vehicle.engine_no = result.engine_no
                    existing_vehicle.transmission = result.transmission
                    existing_vehicle.country_of_origin = result.country_of_origin
                    existing_vehicle.number_of_owners = result.number_of_owners
                    existing_vehicle.vehicle_type = result.vehicle_type
                    existing_vehicle.reported_stolen = result.reported_stolen
                    existing_vehicle.power_kw = result.power_kw
                    existing_vehicle.tare_weight = result.tare_weight
                    existing_vehicle.gross_vehicle_mass = result.gross_vehicle_mass
                    existing_vehicle.date_first_registered_nz = _parse_date(result.date_first_registered_nz)
                    existing_vehicle.plate_type = result.plate_type
                    existing_vehicle.submodel = result.submodel
                    existing_vehicle.second_colour = result.second_colour
                    await db.flush()
                    await db.commit()
                    
                    stored_data = _global_vehicle_to_dict(existing_vehicle, source="carjam_abcd")
                else:
                    # Create new record
                    logger.info(f"Creating new vehicle record for {rego}")
                    new_vehicle = _carjam_data_to_global_vehicle(result)
                    db.add(new_vehicle)
                    await db.flush()
                    await db.commit()
                    
                    stored_data = _global_vehicle_to_dict(new_vehicle, source="carjam_abcd")
                
                # Convert dataclass to dict for response
                result_dict = {
                    "rego": result.rego,
                    "make": result.make,
                    "model": result.model,
                    "submodel": result.submodel,
                    "year": result.year,
                    "colour": result.colour,
                    "second_colour": result.second_colour,
                    "body_type": result.body_type,
                    "fuel_type": result.fuel_type,
                    "engine_size": result.engine_size,
                    "seats": result.seats,
                    "wof_expiry": result.wof_expiry,
                    "rego_expiry": result.rego_expiry,
                    "odometer": result.odometer,
                    "vin": result.vin,
                    "chassis": result.chassis,
                    "engine_no": result.engine_no,
                    "transmission": result.transmission,
                    "country_of_origin": result.country_of_origin,
                    "number_of_owners": result.number_of_owners,
                    "vehicle_type": result.vehicle_type,
                    "reported_stolen": result.reported_stolen,
                    "power_kw": result.power_kw,
                    "tare_weight": result.tare_weight,
                    "gross_vehicle_mass": result.gross_vehicle_mass,
                    "date_first_registered_nz": result.date_first_registered_nz,
                    "plate_type": result.plate_type,
                    "lookup_type": result.lookup_type,
                }
                
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": f"Vehicle found and stored: {result.make} {result.model}",
                        "data": result_dict,
                        "source": "carjam_abcd",
                        "mvr_used": use_mvr,
                        "attempts": attempt + 1,
                        "stored": True,
                    },
                )
            except CarjamError as exc:
                # Check if it's the "data being fetched" case
                if str(exc) == "ABCD_FETCHING":
                    if attempt < max_retries - 1:
                        logger.info(f"ABCD data not ready, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        logger.warning(f"ABCD data still not ready after {max_retries} attempts")
                        return JSONResponse(
                            status_code=202,  # Accepted but not ready
                            content={
                                "success": False,
                                "message": f"Carjam is still fetching data for '{rego}'. Please try again in a few seconds.",
                                "rego": rego,
                                "retry_suggested": True,
                            },
                        )
                else:
                    # Other CarjamError, re-raise
                    raise
    except asyncio.TimeoutError:
        logger.error(f"ABCD lookup timed out after 30 seconds")
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "message": "Request timed out. Please try again.",
            },
        )
    except CarjamNotFoundError as exc:
        logger.warning(f"Vehicle not found: {exc}")
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "message": f"No vehicle found for registration '{rego}'",
                "rego": rego,
            },
        )
    except CarjamRateLimitError as exc:
        logger.warning(f"Rate limit exceeded: {exc}")
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "message": "Rate limit exceeded. Please try again shortly.",
                "retry_after": exc.retry_after,
            },
            headers={"Retry-After": str(exc.retry_after)},
        )
    except CarjamError as exc:
        logger.error(f"Carjam ABCD service error: {exc}")
        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "message": f"Carjam ABCD service error: {str(exc)}",
            },
        )
    except Exception as exc:
        logger.error(f"Unexpected error in ABCD test lookup: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Unexpected error: {str(exc)}",
            },
        )


# ---------------------------------------------------------------------------
# Global Stripe integration config endpoints (Req 48.4)
# ---------------------------------------------------------------------------


@router.put(
    "/integrations/stripe",
    response_model=StripeConfigResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Configure Global Stripe integration",
    dependencies=[require_role("global_admin")],
)
async def configure_stripe(
    payload: StripeConfigRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure the platform-wide Global Stripe credentials.

    Stores platform account, webhook endpoint, and signing secret.
    Only Global_Admin users can access this endpoint.
    Requirement 48.4.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await save_stripe_config(
            db,
            platform_account_id=payload.platform_account_id,
            webhook_endpoint=payload.webhook_endpoint,
            signing_secret=payload.signing_secret,
            updated_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return StripeConfigResponse(message="Stripe configuration saved", **result)


@router.post(
    "/integrations/stripe/test",
    response_model=StripeTestResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Test Stripe connection",
    dependencies=[require_role("global_admin")],
)
async def test_stripe(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Test the Stripe connection using the saved configuration.

    Only Global_Admin users can access this endpoint.
    Requirement 48.2.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    test_result = await test_stripe_connection(
        db,
        admin_user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
        ip_address=ip_address,
    )

    return StripeTestResponse(**test_result)



# ---------------------------------------------------------------------------
# Comprehensive Error Logging (Req 49.1–49.7)
# ---------------------------------------------------------------------------


@router.get(
    "/errors/dashboard",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Error log dashboard with real-time counts",
    dependencies=[require_role("global_admin")],
)
async def error_dashboard(
    db: AsyncSession = Depends(get_db_session),
):
    """Real-time error counts for the last 1h, 24h, and 7d
    broken down by severity and category.

    Only Global_Admin users can access this endpoint.
    Requirement 49.4.
    """
    from app.modules.admin.schemas import ErrorLogDashboardResponse, ErrorLogSummaryCount
    from app.modules.admin.service import get_error_dashboard

    data = await get_error_dashboard(db)
    return ErrorLogDashboardResponse(
        by_severity=[ErrorLogSummaryCount(**s) for s in data["by_severity"]],
        by_category=[ErrorLogSummaryCount(**c) for c in data["by_category"]],
        total_1h=data["total_1h"],
        total_24h=data["total_24h"],
        total_7d=data["total_7d"],
    )


@router.get(
    "/errors/export",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Export error logs as CSV or JSON",
    dependencies=[require_role("global_admin")],
)
async def export_errors(
    format: str = "json",
    date_from: str | None = None,
    date_to: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Export error logs for a date range in CSV or JSON format.

    Only Global_Admin users can access this endpoint.
    Requirement 49.7.
    """
    from datetime import datetime as dt
    from app.modules.admin.service import export_error_logs

    parsed_from = None
    parsed_to = None
    if date_from:
        try:
            parsed_from = dt.fromisoformat(date_from)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid date_from format"})
    if date_to:
        try:
            parsed_to = dt.fromisoformat(date_to)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid date_to format"})

    data = await export_error_logs(
        db,
        fmt=format,
        date_from=parsed_from,
        date_to=parsed_to,
        severity=severity,
        category=category,
    )

    if format == "csv":
        import csv
        import io

        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        csv_content = output.getvalue()
        return JSONResponse(
            content={"format": "csv", "data": csv_content, "count": len(data)},
        )

    return JSONResponse(content={"format": "json", "data": data, "count": len(data)})


@router.get(
    "/errors/{error_id}",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Error not found"},
    },
    summary="Get error detail",
    dependencies=[require_role("global_admin")],
)
async def get_error(
    error_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Full error detail: stack trace, context, request/response, status, notes.

    Only Global_Admin users can access this endpoint.
    Requirement 49.6.
    """
    from app.modules.admin.schemas import ErrorLogDetailResponse
    from app.modules.admin.service import get_error_detail

    try:
        eid = uuid.UUID(error_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid error_id format"})

    detail = await get_error_detail(db, eid)
    if detail is None:
        return JSONResponse(status_code=404, content={"detail": "Error not found"})

    return ErrorLogDetailResponse(**detail)


@router.get(
    "/errors",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List error logs with search and filter",
    dependencies=[require_role("global_admin")],
)
async def list_errors(
    severity: str | None = None,
    category: str | None = None,
    status: str | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 25,
    db: AsyncSession = Depends(get_db_session),
):
    """Paginated error log list with filtering by severity, category,
    status, org, keyword, and date range.

    Only Global_Admin users can access this endpoint.
    Requirement 49.4.
    """
    from datetime import datetime as dt
    from app.modules.admin.schemas import ErrorLogListItem, ErrorLogListResponse
    from app.modules.admin.service import list_error_logs

    parsed_from = None
    parsed_to = None
    if date_from:
        try:
            parsed_from = dt.fromisoformat(date_from)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid date_from format"})
    if date_to:
        try:
            parsed_to = dt.fromisoformat(date_to)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid date_to format"})

    data = await list_error_logs(
        db,
        severity=severity,
        category=category,
        status=status,
        org_id=org_id,
        keyword=keyword,
        date_from=parsed_from,
        date_to=parsed_to,
        page=page,
        page_size=page_size,
    )

    return ErrorLogListResponse(
        errors=[ErrorLogListItem(**e) for e in data["errors"]],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
    )


@router.put(
    "/errors/{error_id}/status",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Error not found"},
    },
    summary="Update error status",
    dependencies=[require_role("global_admin")],
)
async def update_error(
    error_id: str,
    payload: ErrorLogStatusUpdateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Update error status (open/investigating/resolved) and add resolution notes.

    Only Global_Admin users can access this endpoint.
    Requirement 49.6.
    """
    from app.modules.admin.schemas import ErrorLogStatusUpdateResponse
    from app.modules.admin.service import update_error_status

    try:
        eid = uuid.UUID(error_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid error_id format"})

    try:
        result = await update_error_status(
            db,
            eid,
            status=payload.status,
            resolution_notes=payload.resolution_notes,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return ErrorLogStatusUpdateResponse(**result)


# ---------------------------------------------------------------------------
# Platform Settings (Task 23.4)
# ---------------------------------------------------------------------------


@router.get(
    "/settings",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Get platform settings",
    dependencies=[require_role("global_admin")],
)
async def get_settings(
    db: AsyncSession = Depends(get_db_session),
):
    """Return platform settings: T&C with version history, announcement banner.

    Only Global_Admin users can access this endpoint.
    Requirement 50.1.
    """
    from app.modules.admin.schemas import PlatformSettingsResponse
    from app.modules.admin.service import get_platform_settings

    data = await get_platform_settings(db)
    return PlatformSettingsResponse(**data)


@router.put(
    "/settings",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Update platform settings",
    dependencies=[require_role("global_admin")],
)
async def update_settings(
    payload: PlatformSettingsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update platform settings: T&C (triggers re-accept), announcement banner.

    Only Global_Admin users can access this endpoint.
    Requirements 50.1, 50.2, 50.3.
    """
    from app.modules.admin.schemas import PlatformSettingsUpdateResponse
    from app.modules.admin.service import update_platform_settings

    actor_user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    result = await update_platform_settings(
        db,
        terms_and_conditions=payload.terms_and_conditions,
        announcement_banner=payload.announcement_banner,
        announcement_active=payload.announcement_active,
        storage_pricing=payload.storage_pricing.model_dump() if payload.storage_pricing else None,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )
    return PlatformSettingsUpdateResponse(**result)


@router.get(
    "/vehicle-db/search/{rego}",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Search Global Vehicle DB by rego",
    dependencies=[require_role("global_admin")],
)
async def search_vehicle_db(
    rego: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Search the Global Vehicle DB by registration number (partial match).

    Only Global_Admin users can access this endpoint.
    Requirement 50.1.
    """
    from app.modules.admin.schemas import GlobalVehicleSearchResponse
    from app.modules.admin.service import search_global_vehicles

    data = await search_global_vehicles(db, rego)
    return GlobalVehicleSearchResponse(**data)


@router.post(
    "/vehicle-db/{rego}/refresh",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Vehicle not found"},
    },
    summary="Force-refresh vehicle from Carjam",
    dependencies=[require_role("global_admin")],
)
async def refresh_vehicle(
    rego: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Force-refresh a vehicle record from Carjam API.

    Only Global_Admin users can access this endpoint.
    Requirement 50.1.
    """
    from app.modules.admin.schemas import GlobalVehicleRefreshResponse
    from app.modules.admin.service import refresh_global_vehicle

    actor_user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    result = await refresh_global_vehicle(
        db,
        rego,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )

    if result["vehicle"] is None and "not found" in result["message"].lower():
        return JSONResponse(status_code=404, content=result)

    return GlobalVehicleRefreshResponse(**result)


@router.delete(
    "/vehicle-db/stale",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Delete stale vehicle records",
    dependencies=[require_role("global_admin")],
)
async def delete_stale_vehicles_endpoint(
    stale_days: int = 365,
    request: Request = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete vehicle records not refreshed within *stale_days* days.

    Only Global_Admin users can access this endpoint.
    Requirement 50.1.
    """
    from app.modules.admin.schemas import GlobalVehicleDeleteResponse
    from app.modules.admin.service import delete_stale_vehicles

    actor_user_id = getattr(request.state, "user_id", None) if request else None
    ip_address = request.client.host if request and request.client else None

    result = await delete_stale_vehicles(
        db,
        stale_days,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )
    return GlobalVehicleDeleteResponse(**result)


# ---------------------------------------------------------------------------
# User Management — Global Admin (ISSUE-011)
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List all users across organisations",
    dependencies=[require_role("global_admin")],
)
async def list_users(
    search: str | None = None,
    role: str | None = None,
    org_id: str | None = None,
    is_active: bool | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 25,
    db: AsyncSession = Depends(get_db_session),
):
    """List all users across all organisations with filtering and pagination.

    Only Global_Admin users can access this endpoint.
    """
    from app.modules.admin.service import list_all_users

    org_uuid = None
    if org_id:
        try:
            org_uuid = uuid.UUID(org_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    data = await list_all_users(
        db,
        search=search,
        role=role,
        org_id=org_uuid,
        is_active=is_active,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return data


@router.put(
    "/users/{user_id}/status",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "User not found"},
    },
    summary="Activate or deactivate a user",
    dependencies=[require_role("global_admin")],
)
async def update_user_status(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Toggle a user's is_active status. Only Global_Admin."""
    from app.modules.admin.service import toggle_user_active

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid user_id format"})

    actor_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await toggle_user_active(
            db, uid,
            toggled_by=uuid.UUID(actor_id) if actor_id else None,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return result


# ---------------------------------------------------------------------------
# Audit log viewing — Global Admin (Req 51.1, 51.2, 51.4)
# ---------------------------------------------------------------------------


@router.get(
    "/audit-log",
    response_model=None,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Platform-wide audit log",
    dependencies=[require_role("global_admin")],
)
async def get_global_audit_log(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Return paginated, filterable platform-wide audit log.

    Only Global_Admin users can access this endpoint.
    Requirements: 51.1, 51.2, 51.4.
    """
    from app.modules.admin.schemas import AuditLogEntry, AuditLogListResponse
    from app.modules.admin.service import list_audit_logs

    result = await list_audit_logs(
        db,
        org_id=None,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )

    return AuditLogListResponse(
        entries=[AuditLogEntry(**e) for e in result["entries"]],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )

# ---------------------------------------------------------------------------
# User Management — Global Admin (ISSUE-011)
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="List all users across organisations",
    dependencies=[require_role("global_admin")],
)
async def list_users(
    search: str | None = None,
    role: str | None = None,
    org_id: str | None = None,
    is_active: bool | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 25,
    db: AsyncSession = Depends(get_db_session),
):
    """List all users across all organisations with filtering and pagination.

    Only Global_Admin users can access this endpoint.
    """
    from app.modules.admin.service import list_all_users

    org_uuid = None
    if org_id:
        try:
            org_uuid = uuid.UUID(org_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    data = await list_all_users(
        db,
        search=search,
        role=role,
        org_id=org_uuid,
        is_active=is_active,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return data


@router.put(
    "/users/{user_id}/status",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "User not found"},
    },
    summary="Activate or deactivate a user",
    dependencies=[require_role("global_admin")],
)
async def update_user_status(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Toggle a user's is_active status. Only Global_Admin."""
    from app.modules.admin.service import toggle_user_active

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid user_id format"})

    actor_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await toggle_user_active(
            db, uid,
            toggled_by=uuid.UUID(actor_id) if actor_id else None,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return result

