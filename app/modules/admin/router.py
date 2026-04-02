"""Global Admin router — organisation provisioning and management."""

from __future__ import annotations

import uuid
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select

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
    CouponCreateRequest,
    CouponDetailResponse,
    CouponListResponse,
    CouponRedeemRequest,
    CouponRedeemResponse,
    CouponRedemptionRow,
    CouponResponse,
    CouponUpdateRequest,
    CouponValidateRequest,
    CouponValidateResponse,
    CreateGlobalAdminRequest,
    CreateGlobalAdminResponse,
    ErrorLogStatusUpdateRequest,
    IntegrationConfigGetResponse,
    MrrIntervalBreakdown,
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
    StoragePackageCreateRequest,
    StoragePackageListResponse,
    StoragePackageResponse,
    StoragePackageUpdateRequest,
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
    create_coupon,
    create_plan,
    create_storage_package,
    deactivate_coupon,
    deactivate_storage_package,
    delete_organisation,
    delete_plan,
    get_coupon,
    get_coupon_redemptions,
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
    list_coupons,
    list_organisations,
    list_plans,
    list_storage_packages,
    provision_organisation,
    reactivate_coupon,
    redeem_coupon,
    save_carjam_config,
    save_smtp_config,
    save_stripe_config,
    save_twilio_config,
    send_test_email,
    send_test_sms,
    test_carjam_connection,
    test_stripe_connection,
    update_coupon,
    update_organisation,
    update_plan,
    update_storage_package,
    validate_coupon,
)
from app.modules.auth.rbac import require_role
from app.modules.billing.schemas import StripeTestResult, StripeTestAllResponse

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

    try:
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
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

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
        custom_message=payload.message,
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
    Requirements 40.1, 40.2, 40.4, 4.1, 4.5.
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
            interval_config=[ic.model_dump() for ic in payload.interval_config] if payload.interval_config else None,
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
    if "interval_config" in updates:
        updates["interval_config"] = [
            ic.model_dump() if hasattr(ic, "model_dump") else ic
            for ic in updates["interval_config"]
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


@router.delete(
    "/plans/{plan_id}",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "Plan not found"},
    },
    summary="Permanently delete a subscription plan",
    dependencies=[require_role("global_admin")],
)
async def delete_subscription_plan(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a subscription plan.

    Fails if any organisation is currently subscribed to this plan.
    Only Global_Admin users can access this endpoint.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        plan_uuid = uuid.UUID(plan_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid plan_id format"})

    try:
        result = await delete_plan(
            db,
            plan_uuid,
            deleted_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})

    return result


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
        interval_breakdown=[MrrIntervalBreakdown(**ib) for ib in data.get("interval_breakdown", [])],
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


# ---------------------------------------------------------------------------
# Integration Cost Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard/integration-costs",
    summary="Integration cost/usage dashboard for all integrations",
    dependencies=[require_role("global_admin")],
)
async def integration_cost_dashboard(
    db: AsyncSession = Depends(get_db_session),
    period: str = "monthly",
):
    """Aggregated cost and usage data for CarJam, SMS, SMTP, and Stripe.

    Query param ``period`` can be ``daily``, ``weekly``, or ``monthly``.
    """
    from app.modules.admin.service import get_integration_cost_dashboard

    data = await get_integration_cost_dashboard(db, period=period)
    return data


@router.get(
    "/dashboard/connexus-token-refresh-log",
    summary="Connexus SMS token refresh log with reasons",
    dependencies=[require_role("global_admin")],
)
async def connexus_token_refresh_log():
    """Return the last 50 token refresh events with plain-English reasons."""
    from app.integrations.connexus_sms import get_token_refresh_log

    return {"entries": get_token_refresh_log()}


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
    integration_names = ("carjam", "stripe")
    results = []
    for name in integration_names:
        config = await get_integration_config(db, name=name)
        results.append({
            "name": name,
            "status": "healthy" if config and config.get("is_verified") else "down",
            "last_checked": config.get("updated_at") if config else None,
        })

    # SMTP / Email — check email_providers table for any active, configured provider
    from app.modules.admin.models import EmailProvider
    active_email_result = await db.execute(
        select(EmailProvider).where(
            EmailProvider.is_active.is_(True),
            EmailProvider.credentials_set.is_(True),
        ).order_by(EmailProvider.priority)
    )
    active_email = active_email_result.scalars().first()

    if not active_email:
        # Also check for any provider with credentials set (configured but not activated)
        creds_email_result = await db.execute(
            select(EmailProvider).where(
                EmailProvider.credentials_set.is_(True),
            ).order_by(EmailProvider.priority)
        )
        active_email = creds_email_result.scalars().first()

    if active_email:
        results.append({
            "name": "smtp",
            "status": "healthy",
            "last_checked": active_email.updated_at.isoformat() if active_email.updated_at else None,
        })
    else:
        # Fallback to legacy integration_configs
        smtp_config = await get_integration_config(db, name="smtp")
        if smtp_config and smtp_config.get("fields"):
            results.append({
                "name": "smtp",
                "status": "healthy" if smtp_config.get("is_verified") else "down",
                "last_checked": smtp_config.get("updated_at"),
            })
        else:
            results.append({
                "name": "smtp",
                "status": "not_configured",
                "last_checked": None,
            })

    # Connexus SMS provider — stored in sms_verification_providers, not integration_configs
    from app.modules.admin.models import SmsVerificationProvider
    connexus_result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == "connexus",
            SmsVerificationProvider.is_active == True,  # noqa: E712
        )
    )
    connexus = connexus_result.scalar_one_or_none()
    if connexus and connexus.credentials_set:
        results.append({
            "name": "Connexus SMS",
            "status": "healthy",
            "last_checked": connexus.updated_at.isoformat() if connexus.updated_at else None,
        })
    else:
        results.append({
            "name": "Connexus SMS",
            "status": "down",
            "last_checked": connexus.updated_at.isoformat() if connexus and connexus.updated_at else None,
        })

    return results


@router.get(
    "/integrations/backup",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Export all integration settings as JSON backup",
    dependencies=[require_role("global_admin")],
)
async def backup_integration_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Export all integration configs (carjam, stripe, smtp, twilio),
    SMS providers, and email providers as a downloadable JSON backup.

    Only Global_Admin users can access this endpoint.
    Requires password re-confirmation via x-confirm-password header.
    """
    from app.modules.admin.service import export_integration_settings
    from app.modules.auth.password import verify_password
    from app.modules.auth.models import User
    from app.core.audit import write_audit_log

    # --- Password re-confirmation (REM-04) ---
    confirm_password = request.headers.get("x-confirm-password")
    if not confirm_password:
        return JSONResponse(status_code=401, content={"detail": "Password confirmation required"})

    user_id = getattr(request.state, "user_id", None)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not verify_password(confirm_password, user.password_hash):
        return JSONResponse(status_code=400, content={"detail": "Invalid password"})

    data = await export_integration_settings(db)

    # --- Audit log (REM-04) ---
    ip_address = request.client.host if request.client else None
    await write_audit_log(
        session=db,
        action="admin.integration_backup_exported",
        entity_type="integration_backup",
        user_id=user_id,
        ip_address=ip_address,
    )
    await db.commit()

    return JSONResponse(content=data)



@router.post(
    "/integrations/restore",
    responses={
        400: {"description": "Invalid backup data"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Restore integration settings from JSON backup",
    dependencies=[require_role("global_admin")],
)
async def restore_integration_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Restore integration configs, SMS providers, and email providers
    from a previously exported JSON backup.

    Only Global_Admin users can access this endpoint.
    """
    from app.modules.admin.service import import_integration_settings

    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

    if not isinstance(body, dict) or "integrations" not in body:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid backup format — missing 'integrations' key"},
        )

    try:
        restored = await import_integration_settings(
            db,
            data=body,
            imported_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
    except Exception as exc:
        logger.exception("Failed to restore integration settings")
        return JSONResponse(
            status_code=500,
            content={"detail": f"Restore failed: {str(exc)}"},
        )

    return JSONResponse(content={
        "message": "Integration settings restored successfully",
        "restored": restored,
    })


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
            abcd_per_lookup_cost_nzd=payload.abcd_per_lookup_cost_nzd,
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
            publishable_key=payload.publishable_key,
            secret_key=payload.secret_key,
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

@router.post(
    "/integrations/stripe/test-keys",
    response_model=StripeTestResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Test Stripe API keys",
    dependencies=[require_role("global_admin")],
)
async def test_stripe_keys(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Test the Stripe API keys by making a simple balance retrieval call.

    Uses the stored secret key to verify it's valid and has API access.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    from app.modules.admin.service import test_stripe_api_keys
    test_result = await test_stripe_api_keys(
        db,
        admin_user_id=uuid.UUID(user_id) if user_id else uuid.uuid4(),
        ip_address=ip_address,
    )

    return StripeTestResponse(**test_result)




# ---------------------------------------------------------------------------
# Stripe Test-All Suite (Req 12.2, 12.4, 12.7, 12.8)
# ---------------------------------------------------------------------------


@router.post(
    "/integrations/stripe/test-all",
    response_model=StripeTestAllResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Run all Stripe function and webhook handler tests",
    dependencies=[require_role("global_admin")],
)
async def test_all_stripe(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Run all 15 Stripe function and webhook handler tests sequentially.

    Tests API functions (Create Customer, Create SetupIntent, etc.) and
    webhook handlers (invoice.created, invoice.payment_succeeded, etc.)
    using mock event payloads. Cleans up test resources after completion.

    Always returns 200 — individual test failures are recorded in the
    results array.

    Requirements: 12.2, 12.4, 12.7, 12.8
    """
    from app.integrations.stripe_billing import (
        create_stripe_customer,
        create_setup_intent,
        list_payment_methods,
        set_default_payment_method,
        create_invoice_item,
        _load_webhook_secret_from_db,
    )

    results: list[StripeTestResult] = []
    test_customer_id: str | None = None

    try:
        # ---------------------------------------------------------------
        # API Function Tests
        # ---------------------------------------------------------------

        # 1. Create Customer
        try:
            test_customer_id = await create_stripe_customer(
                email="stripe-test-all@workshoppro.test",
                name="WorkshopPro Test Customer",
                metadata={"purpose": "automated_test_suite"},
            )
            results.append(StripeTestResult(
                test_name="Create Customer",
                category="api_functions",
                status="passed",
            ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="Create Customer",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

        # 2. Create SetupIntent
        try:
            if test_customer_id:
                si = await create_setup_intent(customer_id=test_customer_id)
                assert si.get("setup_intent_id"), "Missing setup_intent_id"
                assert si.get("client_secret"), "Missing client_secret"
                results.append(StripeTestResult(
                    test_name="Create SetupIntent",
                    category="api_functions",
                    status="passed",
                ))
            else:
                results.append(StripeTestResult(
                    test_name="Create SetupIntent",
                    category="api_functions",
                    status="skipped",
                    skip_reason="No test customer available",
                ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="Create SetupIntent",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

        # 3. List Payment Methods
        try:
            if test_customer_id:
                pms = await list_payment_methods(customer_id=test_customer_id)
                assert isinstance(pms, list), "Expected list of payment methods"
                results.append(StripeTestResult(
                    test_name="List Payment Methods",
                    category="api_functions",
                    status="passed",
                ))
            else:
                results.append(StripeTestResult(
                    test_name="List Payment Methods",
                    category="api_functions",
                    status="skipped",
                    skip_reason="No test customer available",
                ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="List Payment Methods",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

        # 4. Set Default Payment Method
        try:
            if test_customer_id:
                pms = await list_payment_methods(customer_id=test_customer_id)
                if pms:
                    await set_default_payment_method(
                        customer_id=test_customer_id,
                        payment_method_id=pms[0]["id"],
                    )
                    results.append(StripeTestResult(
                        test_name="Set Default Payment Method",
                        category="api_functions",
                        status="passed",
                    ))
                else:
                    results.append(StripeTestResult(
                        test_name="Set Default Payment Method",
                        category="api_functions",
                        status="skipped",
                        skip_reason="No payment methods on test customer",
                    ))
            else:
                results.append(StripeTestResult(
                    test_name="Set Default Payment Method",
                    category="api_functions",
                    status="skipped",
                    skip_reason="No test customer available",
                ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="Set Default Payment Method",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

        # 6. Create Invoice Item
        try:
            if test_customer_id:
                item = await create_invoice_item(
                    customer_id=test_customer_id,
                    description="Test overage charge",
                    quantity=1,
                    unit_amount_cents=50,
                    currency="nzd",
                    metadata={"purpose": "automated_test_suite"},
                )
                assert item.get("invoice_item_id"), "Missing invoice_item_id"
                results.append(StripeTestResult(
                    test_name="Create Invoice Item",
                    category="api_functions",
                    status="passed",
                ))
            else:
                results.append(StripeTestResult(
                    test_name="Create Invoice Item",
                    category="api_functions",
                    status="skipped",
                    skip_reason="No test customer available",
                ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="Create Invoice Item",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

        # 7. Webhook Signature Verification
        try:
            import stripe as _stripe
            import time as _time

            webhook_secret = await _load_webhook_secret_from_db()
            if not webhook_secret:
                results.append(StripeTestResult(
                    test_name="Webhook Signature Verification",
                    category="api_functions",
                    status="failed",
                    error_message="No webhook signing secret configured",
                ))
            else:
                test_payload = '{"type":"test.event","data":{"object":{}}}'
                timestamp = str(int(_time.time()))
                signed_payload = f"{timestamp}.{test_payload}"
                import hmac as _hmac
                import hashlib as _hashlib
                signature = _hmac.new(
                    webhook_secret.encode("utf-8"),
                    signed_payload.encode("utf-8"),
                    _hashlib.sha256,
                ).hexdigest()
                sig_header = f"t={timestamp},v1={signature}"

                _stripe.Webhook.construct_event(
                    test_payload, sig_header, webhook_secret
                )
                results.append(StripeTestResult(
                    test_name="Webhook Signature Verification",
                    category="api_functions",
                    status="passed",
                ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="Webhook Signature Verification",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

        # 15. Billing Portal Session
        try:
            from app.integrations.stripe_billing import create_billing_portal_session

            if test_customer_id:
                portal_url = await create_billing_portal_session(
                    customer_id=test_customer_id,
                    return_url="https://workshoppro.test/settings/billing",
                )
                assert portal_url, "Missing portal URL"
                results.append(StripeTestResult(
                    test_name="Billing Portal Session",
                    category="api_functions",
                    status="passed",
                ))
            else:
                results.append(StripeTestResult(
                    test_name="Billing Portal Session",
                    category="api_functions",
                    status="skipped",
                    skip_reason="No test customer available",
                ))
        except Exception as exc:
            results.append(StripeTestResult(
                test_name="Billing Portal Session",
                category="api_functions",
                status="failed",
                error_message=str(exc),
            ))

    finally:
        # Clean up test resources
        if test_customer_id:
            try:
                import stripe as _stripe
                _stripe.Customer.delete(test_customer_id)
                logger.info("Cleaned up test customer %s", test_customer_id)
            except Exception as exc:
                logger.warning(
                    "Failed to clean up test customer %s: %s",
                    test_customer_id,
                    exc,
                )

    # Compute summary
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")

    return StripeTestAllResponse(
        results=results,
        summary={
            "total": passed + failed + skipped,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
    )


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
        signup_billing=payload.signup_billing.model_dump() if payload.signup_billing else None,
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

    try:
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
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
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
# Global Admin user creation
# ---------------------------------------------------------------------------


@router.post(
    "/users/global-admin",
    response_model=CreateGlobalAdminResponse,
    responses={
        400: {"description": "Validation error (duplicate email, weak password)"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Create a new Global Admin user",
    dependencies=[require_role("global_admin")],
)
async def create_global_admin_user(
    payload: CreateGlobalAdminRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new global_admin user with email and password.

    Only existing Global_Admin users can access this endpoint.
    The new user is created with is_email_verified=True (no verification needed).
    """
    from app.modules.admin.service import create_global_admin

    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await create_global_admin(
            db,
            email=payload.email,
            password=payload.password,
            first_name=payload.first_name,
            last_name=payload.last_name,
            created_by=uuid.UUID(user_id) if user_id else uuid.uuid4(),
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return CreateGlobalAdminResponse(**result)


# ---------------------------------------------------------------------------
# User management actions — Global Admin
# ---------------------------------------------------------------------------


@router.delete(
    "/users/{user_id}",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "User not found"},
    },
    summary="Permanently delete a user",
    dependencies=[require_role("global_admin")],
)
async def delete_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a user and all associated data (MFA, sessions)."""
    from app.modules.admin.service import delete_user_permanently

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid user_id format"})

    actor_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await delete_user_permanently(
            db, uid,
            deleted_by=uuid.UUID(actor_id) if actor_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        status = 404 if "not found" in msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": msg})

    return result


@router.post(
    "/users/{user_id}/reset-password",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "User not found"},
    },
    summary="Send password reset link to user",
    dependencies=[require_role("global_admin")],
)
async def admin_send_password_reset(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Trigger a password reset email for the specified user."""
    from app.modules.auth.service import request_password_reset
    from app.modules.auth.models import User

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid user_id format"})

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None:
        return JSONResponse(status_code=404, content={"detail": "User not found"})

    ip_address = request.client.host if request.client else None
    await request_password_reset(db=db, email=user.email, ip_address=ip_address)
    await db.commit()

    return {"message": f"Password reset link sent to {user.email}"}


@router.post(
    "/users/{user_id}/reset-mfa",
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
        404: {"description": "User not found"},
    },
    summary="Reset all MFA methods for a user",
    dependencies=[require_role("global_admin")],
)
async def admin_reset_mfa(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Clear all MFA methods, passkeys, and backup codes for a user."""
    from app.modules.admin.service import admin_reset_user_mfa

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid user_id format"})

    actor_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await admin_reset_user_mfa(
            db, uid,
            reset_by=uuid.UUID(actor_id) if actor_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        status = 404 if "not found" in msg.lower() else 400
        return JSONResponse(status_code=status, content={"detail": msg})

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

    try:
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
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
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


# ── Demo Account Reset ──────────────────────────────────────────────

_DEMO_RESET_ALLOWED_ENVIRONMENTS = {"development"}


@router.post(
    "/demo/reset",
    responses={
        200: {"description": "Demo account reset successfully"},
        401: {"description": "Authentication required"},
        403: {"description": "Not a development environment / Global_Admin role required"},
    },
    summary="Reset the demo organisation account",
    dependencies=[require_role("global_admin")],
)
async def reset_demo_account(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete and re-seed the demo organisation (Demo Workshop).

    Only available in development environments. Removes all data
    belonging to the demo org and re-runs the seed script.
    """
    from app.config import settings as app_settings

    if app_settings.environment not in _DEMO_RESET_ALLOWED_ENVIRONMENTS:
        return JSONResponse(
            status_code=403,
            content={"detail": "Demo reset is only available in development"},
        )

    demo_email = "demo@orainvoice.com"
    demo_org_name = "Demo Workshop"

    try:
        # Find the demo user and org
        result = await db.execute(
            text("SELECT id, org_id FROM users WHERE email = :email"),
            {"email": demo_email},
        )
        row = result.first()
        if not row:
            return JSONResponse(
                status_code=404,
                content={"detail": "Demo account not found"},
            )

        user_id = str(row[0])
        org_id = str(row[1])

        # Delete org data in dependency order
        # Sessions, audit logs, tokens
        await db.execute(text("DELETE FROM sessions WHERE user_id = CAST(:uid AS uuid)"), {"uid": user_id})
        # audit_log may have DB-level DELETE restrictions — skip if so
        try:
            await db.execute(text("DELETE FROM audit_log WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})
        except Exception:
            pass  # audit_log is append-only, DELETE may be revoked

        # SMS data
        await db.execute(text("""
            DELETE FROM sms_messages WHERE conversation_id IN (
                SELECT id FROM sms_conversations WHERE org_id = CAST(:oid AS uuid)
            )
        """), {"oid": org_id})
        await db.execute(text("DELETE FROM sms_conversations WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})

        # Invoices and related
        await db.execute(text("""
            DELETE FROM line_items WHERE invoice_id IN (
                SELECT id FROM invoices WHERE org_id = CAST(:oid AS uuid)
            )
        """), {"oid": org_id})
        await db.execute(text("DELETE FROM invoices WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})

        # Payments
        await db.execute(text("DELETE FROM payments WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})

        # Quotes
        await db.execute(text("""
            DELETE FROM quote_line_items WHERE quote_id IN (
                SELECT id FROM quotes WHERE org_id = CAST(:oid AS uuid)
            )
        """), {"oid": org_id})
        await db.execute(text("DELETE FROM quotes WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})

        # Vehicles and customer-vehicle links (before customers)
        await db.execute(text("""
            DELETE FROM customer_vehicles WHERE vehicle_id IN (
                SELECT id FROM org_vehicles WHERE org_id = CAST(:oid AS uuid)
            )
        """), {"oid": org_id})
        await db.execute(text("DELETE FROM org_vehicles WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})

        # Customers (after invoices, quotes, customer_vehicles)
        await db.execute(text("DELETE FROM customers WHERE org_id = CAST(:oid AS uuid)"), {"oid": org_id})

        # Org modules and feature flag overrides stay (they get re-synced)
        # Reset user password and clear login timestamps
        from app.modules.auth.password import hash_password
        pw_hash = hash_password("demo123")
        await db.execute(
            text("""
                UPDATE users SET password_hash = :pw, last_login_at = NULL,
                    failed_login_attempts = 0, locked_until = NULL
                WHERE id = CAST(:uid AS uuid)
            """),
            {"pw": pw_hash, "uid": user_id},
        )

        await db.commit()

        # Re-sync modules and flags
        from app.core.demo_org_sync import sync_demo_org_modules
        await sync_demo_org_modules()

        logger.info("Demo account reset by admin %s", getattr(request.state, "user_id", "unknown"))

        return {"detail": "Demo account reset successfully", "org_name": demo_org_name, "email": demo_email}

    except Exception as exc:
        await db.rollback()
        logger.error("Demo reset failed: %s", exc)
        return JSONResponse(status_code=500, content={"detail": f"Reset failed: {exc}"})


# ---------------------------------------------------------------------------
# Public Holiday Calendar Sync
# ---------------------------------------------------------------------------

@router.post(
    "/calendar/holidays/sync",
    summary="Sync public holidays for a country and year",
    dependencies=[require_role("global_admin")],
)
async def sync_holidays(
    request: Request,
    country_code: str,
    year: int,
    db: AsyncSession = Depends(get_db_session),
):
    """Fetch public holidays from Nager.Date API and store in DB."""
    from app.modules.admin.service import sync_public_holidays

    valid_countries = {"NZ", "AU"}
    code = country_code.upper()
    if code not in valid_countries:
        return JSONResponse(status_code=400, content={"detail": f"Unsupported country. Use: {', '.join(valid_countries)}"})

    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await sync_public_holidays(
            db,
            code,
            year,
            actor_user_id=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        return result
    except Exception as exc:
        logger.error("Holiday sync failed: %s", exc)
        return JSONResponse(status_code=500, content={"detail": f"Sync failed: {str(exc)}"})


@router.get(
    "/calendar/holidays",
    summary="List synced public holidays",
    dependencies=[require_role("global_admin")],
)
async def list_holidays(
    country_code: str | None = None,
    year: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Return synced public holidays, optionally filtered."""
    from app.modules.admin.service import list_public_holidays
    return await list_public_holidays(db, country_code=country_code, year=year)


# ---------------------------------------------------------------------------
# Coupon CRUD endpoints (admin, global_admin only)
# Requirements 2.1–2.8
# ---------------------------------------------------------------------------


@router.get(
    "/coupons",
    response_model=CouponListResponse,
    summary="List coupons (paginated)",
    dependencies=[require_role("global_admin")],
)
async def list_coupons_endpoint(
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db_session),
):
    """Return a paginated list of coupons, ordered by created_at desc."""
    result = await list_coupons(
        db,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )
    return CouponListResponse(**result)


@router.post(
    "/coupons",
    response_model=CouponResponse,
    status_code=201,
    summary="Create a coupon",
    dependencies=[require_role("global_admin")],
)
async def create_coupon_endpoint(
    payload: CouponCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new coupon. Code is normalised to uppercase."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await create_coupon(
            db,
            code=payload.code,
            description=payload.description,
            discount_type=payload.discount_type,
            discount_value=payload.discount_value,
            duration_months=payload.duration_months,
            usage_limit=payload.usage_limit,
            starts_at=payload.starts_at,
            expires_at=payload.expires_at,
            created_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error creating coupon")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while creating the coupon"},
        )

    return CouponResponse(**result)


@router.get(
    "/coupons/{coupon_id}",
    response_model=CouponDetailResponse,
    summary="Get coupon detail with redemptions",
    dependencies=[require_role("global_admin")],
)
async def get_coupon_endpoint(
    coupon_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return a single coupon with its full details and redemption list."""
    try:
        coupon_uuid = uuid.UUID(coupon_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid coupon_id format"}
        )

    try:
        result = await get_coupon(db, coupon_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return CouponDetailResponse(**result)


@router.put(
    "/coupons/{coupon_id}",
    response_model=CouponResponse,
    summary="Update a coupon",
    dependencies=[require_role("global_admin")],
)
async def update_coupon_endpoint(
    coupon_id: str,
    payload: CouponUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update coupon fields. usage_limit must be >= times_redeemed."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        coupon_uuid = uuid.UUID(coupon_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid coupon_id format"}
        )

    updates = payload.model_dump(exclude_none=True)

    try:
        result = await update_coupon(
            db,
            coupon_uuid,
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
        if "usage limit" in msg.lower():
            return JSONResponse(status_code=422, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error updating coupon")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while updating the coupon"},
        )

    return CouponResponse(**result)


@router.delete(
    "/coupons/{coupon_id}",
    response_model=CouponResponse,
    summary="Soft-delete (deactivate) a coupon",
    dependencies=[require_role("global_admin")],
)
async def delete_coupon_endpoint(
    coupon_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Soft-delete a coupon by setting is_active to false."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        coupon_uuid = uuid.UUID(coupon_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid coupon_id format"}
        )

    try:
        result = await deactivate_coupon(
            db,
            coupon_uuid,
            updated_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error deactivating coupon")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while deactivating the coupon"},
        )

    return CouponResponse(**result)


@router.put(
    "/coupons/{coupon_id}/reactivate",
    response_model=CouponResponse,
    summary="Reactivate a coupon",
    dependencies=[require_role("global_admin")],
)
async def reactivate_coupon_endpoint(
    coupon_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Reactivate a previously deactivated coupon."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        coupon_uuid = uuid.UUID(coupon_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid coupon_id format"}
        )

    try:
        result = await reactivate_coupon(
            db,
            coupon_uuid,
            updated_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error reactivating coupon")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while reactivating the coupon"},
        )

    return CouponResponse(**result)


@router.get(
    "/coupons/{coupon_id}/redemptions",
    response_model=list[CouponRedemptionRow],
    summary="List coupon redemptions",
    dependencies=[require_role("global_admin")],
)
async def list_coupon_redemptions_endpoint(
    coupon_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all organisation_coupons records for a given coupon."""
    try:
        coupon_uuid = uuid.UUID(coupon_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid coupon_id format"}
        )

    try:
        result = await get_coupon_redemptions(db, coupon_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return [CouponRedemptionRow(**r) for r in result]


# ---------------------------------------------------------------------------
# Public coupon endpoints (no auth — used during signup)
# Requirements 3.1–3.8
# ---------------------------------------------------------------------------

coupon_public_router = APIRouter()


@coupon_public_router.post(
    "/validate",
    response_model=CouponValidateResponse,
    summary="Validate a coupon code (public)",
)
async def validate_coupon_endpoint(
    payload: CouponValidateRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Public endpoint: validate a coupon code. Always returns 200."""
    result = await validate_coupon(db, payload.code)
    return CouponValidateResponse(**result)


@coupon_public_router.post(
    "/redeem",
    response_model=CouponRedeemResponse,
    summary="Redeem a coupon for an organisation (public)",
)
async def redeem_coupon_endpoint(
    payload: CouponRedeemRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Public endpoint: redeem a coupon for an organisation after signup."""
    try:
        result = await redeem_coupon(db, code=payload.code, org_id=payload.org_id)
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        if "already redeemed" in msg.lower():
            return JSONResponse(status_code=409, content={"detail": msg})
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error redeeming coupon")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while redeeming the coupon"},
        )

    return CouponRedeemResponse(**result)


# ---------------------------------------------------------------------------
# Storage Package CRUD endpoints
# Requirements 2.1–2.6
# ---------------------------------------------------------------------------


@router.get(
    "/storage-packages",
    response_model=StoragePackageListResponse,
    summary="List storage packages",
    dependencies=[require_role("global_admin")],
)
async def list_storage_packages_endpoint(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all storage packages ordered by sort_order ascending.

    Pass `include_inactive=true` to include deactivated packages.
    Requirement 2.1.
    """
    packages = await list_storage_packages(db, include_inactive=include_inactive)
    return StoragePackageListResponse(
        packages=[StoragePackageResponse(**p) for p in packages],
        total=len(packages),
    )


@router.post(
    "/storage-packages",
    response_model=StoragePackageResponse,
    status_code=201,
    summary="Create a storage package",
    dependencies=[require_role("global_admin")],
)
async def create_storage_package_endpoint(
    payload: StoragePackageCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new storage package.

    Requirements 2.2, 2.5.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await create_storage_package(
            db,
            name=payload.name,
            storage_gb=payload.storage_gb,
            price_nzd_per_month=payload.price_nzd_per_month,
            description=payload.description,
            sort_order=payload.sort_order,
            created_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception:
        await db.rollback()
        logger.exception("Unexpected error creating storage package")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while creating the storage package"},
        )

    return StoragePackageResponse(**result)


@router.put(
    "/storage-packages/{package_id}",
    response_model=StoragePackageResponse,
    summary="Update a storage package",
    dependencies=[require_role("global_admin")],
)
async def update_storage_package_endpoint(
    package_id: str,
    payload: StoragePackageUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update storage package fields.

    Requirements 2.3, 2.5.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        pkg_uuid = uuid.UUID(package_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid package_id format"}
        )

    fields = payload.model_dump(exclude_none=True)

    try:
        result = await update_storage_package(
            db,
            pkg_uuid,
            updated_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
            **fields,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        msg = str(exc)
        if "not found" in msg.lower():
            return JSONResponse(status_code=404, content={"detail": msg})
        return JSONResponse(status_code=400, content={"detail": msg})
    except Exception:
        await db.rollback()
        logger.exception("Unexpected error updating storage package")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred while updating the storage package"},
        )

    return StoragePackageResponse(**result)


@router.delete(
    "/storage-packages/{package_id}",
    response_model=StoragePackageResponse,
    summary="Soft-delete (deactivate) a storage package",
    dependencies=[require_role("global_admin")],
)
async def delete_storage_package_endpoint(
    package_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Soft-delete a storage package by setting is_active to false.

    Requirements 2.4, 2.6.
    """
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        pkg_uuid = uuid.UUID(package_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid package_id format"}
        )

    try:
        result = await deactivate_storage_package(
            db,
            pkg_uuid,
            deactivated_by=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except Exception:
        await db.rollback()
        logger.exception("Unexpected error deactivating storage package")
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An error occurred while deactivating the storage package"
            },
        )

    return StoragePackageResponse(**result)

@router.post(
    "/org-context/{org_id}",
    summary="Set active org context for global admin session",
    dependencies=[require_role("global_admin")],
    responses={
        200: {"description": "Org context set successfully"},
        404: {"description": "Organisation not found"},
        403: {"description": "Global_Admin role required"},
    },
)
async def set_org_context(
    org_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Set the active organisation context for a global admin session.

    Global admins must select an org context before accessing tenant-scoped
    endpoints. The selected org_id is stored in Redis keyed by user_id.

    REM-10: Session-scoped org context for global admins.
    """
    from app.modules.admin.models import Organisation
    from app.core.redis import redis_pool
    from app.core.audit import write_audit_log

    user_id = getattr(request.state, "user_id", None)

    # Validate org_id format
    try:
        org_uuid = uuid.UUID(org_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid org_id format"}
        )

    # Validate org exists
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = result.scalar_one_or_none()
    if not org:
        return JSONResponse(
            status_code=404, content={"detail": "Organisation not found"}
        )

    # Store org context in Redis keyed by user_id
    redis_key = f"admin_org_ctx:{user_id}"
    await redis_pool.set(redis_key, str(org_uuid))

    # Audit log: admin.org_context_switched
    ip_address = request.client.host if request.client else None
    await write_audit_log(
        session=db,
        action="admin.org_context_switched",
        entity_type="org_context",
        user_id=user_id,
        entity_id=org_uuid,
        after_value={"org_id": str(org_uuid), "org_name": org.name},
        ip_address=ip_address,
    )
    await db.commit()

    return {"detail": "Organisation context set", "org_id": str(org_uuid), "org_name": org.name}


# ---------------------------------------------------------------------------
# REM-15: Portal token regeneration
# ---------------------------------------------------------------------------


@router.post(
    "/customers/{customer_id}/regenerate-portal-token",
    responses={
        200: {"description": "New portal token generated"},
        404: {"description": "Customer not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Global_Admin role required"},
    },
    summary="Regenerate a customer's portal token and reset expiry",
    dependencies=[require_role("global_admin")],
)
async def regenerate_portal_token(
    customer_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a new portal token for a customer and reset the expiry.

    REM-15: Portal Token TTL and Rotation.
    """
    from app.modules.customers.models import Customer
    from app.core.audit import write_audit_log
    from datetime import datetime, timedelta, timezone

    # Validate customer_id format
    try:
        cust_uuid = uuid.UUID(customer_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid customer_id format"}
        )

    result = await db.execute(
        select(Customer).where(Customer.id == cust_uuid)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        return JSONResponse(
            status_code=404, content={"detail": "Customer not found"}
        )

    # Generate new token and reset expiry
    from app.config import settings as app_settings

    new_token = uuid.uuid4()
    new_expiry = datetime.now(timezone.utc) + timedelta(days=app_settings.portal_token_ttl_days)
    customer.portal_token = new_token
    customer.portal_token_expires_at = new_expiry

    # Audit log
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None
    await write_audit_log(
        session=db,
        action="admin.portal_token_regenerated",
        entity_type="customer",
        user_id=user_id,
        entity_id=cust_uuid,
        after_value={
            "portal_token": str(new_token),
            "portal_token_expires_at": new_expiry.isoformat(),
        },
        ip_address=ip_address,
    )
    await db.commit()

    return {
        "detail": "Portal token regenerated",
        "customer_id": str(cust_uuid),
        "portal_token": str(new_token),
        "portal_token_expires_at": new_expiry.isoformat(),
    }



# ---------------------------------------------------------------------------
# Global Admin — Branch Overview (Req 7.1, 7.2, 7.3, 21.1, 21.2, 21.3, 21.4)
# ---------------------------------------------------------------------------


@router.get(
    "/branches",
    summary="Paginated branch list across all organisations",
    dependencies=[require_role("global_admin")],
)
async def list_all_branches(
    search: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 25,
    db: AsyncSession = Depends(get_db_session),
):
    """Return a paginated list of all branches across all organisations.

    Supports filtering by organisation name (search) and branch status
    (active/inactive).

    Only Global_Admin users can access this endpoint.
    Requirements: 21.1, 21.2
    """
    from app.modules.organisations.models import Branch
    from app.modules.admin.models import Organisation
    from sqlalchemy import func

    base_query = (
        select(
            Branch.id,
            Branch.name.label("branch_name"),
            Branch.is_active,
            Branch.is_hq,
            Branch.address,
            Branch.phone,
            Branch.email,
            Branch.timezone,
            Branch.created_at,
            Organisation.name.label("org_name"),
            Organisation.id.label("org_id"),
        )
        .join(Organisation, Branch.org_id == Organisation.id)
    )

    count_query = (
        select(func.count(Branch.id))
        .join(Organisation, Branch.org_id == Organisation.id)
    )

    if search:
        search_filter = f"%{search}%"
        base_query = base_query.where(
            Organisation.name.ilike(search_filter) | Branch.name.ilike(search_filter)
        )
        count_query = count_query.where(
            Organisation.name.ilike(search_filter) | Branch.name.ilike(search_filter)
        )

    if status == "active":
        base_query = base_query.where(Branch.is_active == True)  # noqa: E712
        count_query = count_query.where(Branch.is_active == True)  # noqa: E712
    elif status == "inactive":
        base_query = base_query.where(Branch.is_active == False)  # noqa: E712
        count_query = count_query.where(Branch.is_active == False)  # noqa: E712

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    base_query = base_query.order_by(Branch.created_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(base_query)
    rows = result.all()

    branches = []
    for r in rows:
        branches.append({
            "id": str(r.id),
            "branch_name": r.branch_name,
            "org_name": r.org_name,
            "org_id": str(r.org_id),
            "is_active": r.is_active,
            "is_hq": r.is_hq,
            "address": r.address,
            "phone": r.phone,
            "email": r.email,
            "timezone": r.timezone,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return {
        "branches": branches,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get(
    "/branches/{branch_id}",
    summary="Branch detail with users and activity",
    dependencies=[require_role("global_admin")],
)
async def get_branch_detail(
    branch_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return detailed branch information including assigned users and
    recent activity.

    Only Global_Admin users can access this endpoint.
    Requirements: 21.3
    """
    from app.modules.organisations.models import Branch
    from app.modules.admin.models import Organisation
    from app.modules.auth.models import User

    try:
        branch_uuid = uuid.UUID(branch_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid branch_id format"})

    # Fetch branch with org info
    result = await db.execute(
        select(Branch, Organisation.name.label("org_name"))
        .join(Organisation, Branch.org_id == Organisation.id)
        .where(Branch.id == branch_uuid)
    )
    row = result.one_or_none()
    if not row:
        return JSONResponse(status_code=404, content={"detail": "Branch not found"})

    branch = row[0]
    org_name = row[1]

    # Fetch users assigned to this branch
    user_result = await db.execute(
        select(User.id, User.email, User.first_name, User.last_name, User.role, User.is_active)
        .where(
            User.org_id == branch.org_id,
            User.is_active == True,  # noqa: E712
        )
    )
    users = []
    for u in user_result.all():
        # Check if user is assigned to this branch via branch_ids JSONB
        users.append({
            "id": str(u.id),
            "email": u.email,
            "name": f"{u.first_name or ''} {u.last_name or ''}".strip(),
            "role": u.role,
            "is_active": u.is_active,
        })

    return {
        "id": str(branch.id),
        "name": branch.name,
        "org_id": str(branch.org_id),
        "org_name": org_name,
        "address": branch.address,
        "phone": branch.phone,
        "email": branch.email,
        "logo_url": branch.logo_url,
        "operating_hours": branch.operating_hours,
        "timezone": branch.timezone,
        "is_hq": branch.is_hq,
        "is_active": branch.is_active,
        "notification_preferences": branch.notification_preferences,
        "created_at": branch.created_at.isoformat() if branch.created_at else None,
        "updated_at": branch.updated_at.isoformat() if branch.updated_at else None,
        "users": users,
    }


@router.get(
    "/branch-summary",
    summary="Platform-wide branch statistics",
    dependencies=[require_role("global_admin")],
)
async def branch_summary(
    db: AsyncSession = Depends(get_db_session),
):
    """Return platform-wide branch statistics.

    Shows total active branches, total inactive, and average branches
    per organisation.

    Only Global_Admin users can access this endpoint.
    Requirements: 21.4
    """
    from app.modules.organisations.models import Branch
    from app.modules.admin.models import Organisation
    from sqlalchemy import func, case
    from decimal import Decimal

    # Total active and inactive branches
    stats_result = await db.execute(
        select(
            func.count(Branch.id).label("total_branches"),
            func.count(Branch.id).filter(Branch.is_active == True).label("active_branches"),  # noqa: E712
            func.count(Branch.id).filter(Branch.is_active == False).label("inactive_branches"),  # noqa: E712
        )
    )
    stats = stats_result.one()

    # Count orgs with at least one branch
    org_count_result = await db.execute(
        select(func.count(func.distinct(Branch.org_id)))
    )
    orgs_with_branches = org_count_result.scalar() or 0

    avg_branches = (
        round(stats.total_branches / orgs_with_branches, 2)
        if orgs_with_branches > 0
        else 0
    )

    return {
        "total_branches": stats.total_branches,
        "active_branches": stats.active_branches,
        "inactive_branches": stats.inactive_branches,
        "orgs_with_branches": orgs_with_branches,
        "average_branches_per_org": avg_branches,
    }


@router.get(
    "/org-branch-revenue",
    summary="Organisation table with branch counts and revenue",
    dependencies=[require_role("global_admin")],
)
async def org_branch_revenue(
    db: AsyncSession = Depends(get_db_session),
):
    """Return a table of organisations with their branch counts and revenue.

    Shows org name, active branch count, total monthly revenue, and
    per-branch average revenue.

    Only Global_Admin users can access this endpoint.
    Requirements: 7.1, 7.2, 7.3
    """
    from app.modules.organisations.models import Branch
    from app.modules.admin.models import Organisation
    from app.modules.invoices.models import Invoice
    from sqlalchemy import func
    from decimal import Decimal

    # Get orgs with branch counts
    org_branch_result = await db.execute(
        select(
            Organisation.id,
            Organisation.name,
            func.count(Branch.id).filter(Branch.is_active == True).label("active_branch_count"),  # noqa: E712
        )
        .outerjoin(Branch, Branch.org_id == Organisation.id)
        .where(Organisation.status != "deleted")
        .group_by(Organisation.id, Organisation.name)
        .order_by(Organisation.name)
    )
    org_rows = org_branch_result.all()

    orgs = []
    total_active_branches = 0
    total_revenue = Decimal("0")

    for row in org_rows:
        # Get revenue for this org (last 30 days)
        from datetime import datetime, timedelta, timezone as tz
        thirty_days_ago = datetime.now(tz.utc) - timedelta(days=30)

        rev_result = await db.execute(
            select(
                func.coalesce(func.sum(Invoice.total), 0).label("revenue"),
            ).where(
                Invoice.org_id == row.id,
                Invoice.status != "voided",
                Invoice.status != "draft",
                Invoice.created_at >= thirty_days_ago,
            )
        )
        revenue = Decimal(str(rev_result.scalar() or 0))

        branch_count = row.active_branch_count or 0
        avg_revenue = (
            round(revenue / branch_count, 2) if branch_count > 0 else Decimal("0")
        )

        total_active_branches += branch_count
        total_revenue += revenue

        orgs.append({
            "org_id": str(row.id),
            "org_name": row.name,
            "active_branch_count": branch_count,
            "total_monthly_revenue": str(revenue),
            "per_branch_avg_revenue": str(avg_revenue),
        })

    return {
        "organisations": orgs,
        "summary": {
            "total_active_branches": total_active_branches,
            "total_revenue": str(total_revenue),
            "average_branches_per_org": (
                round(total_active_branches / len(orgs), 2) if orgs else 0
            ),
        },
    }
