"""Organisation router — onboarding wizard and org-level endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.modules import ModuleService
from app.modules.auth.rbac import require_role
from app.modules.admin.schemas import SmsPackagePurchaseRequest
from app.modules.organisations.schemas import (
    AssignUserBranchesRequest,
    AssignUserBranchesResponse,
    BranchCreateRequest,
    BranchCreateResponse,
    BranchDeactivateResponse,
    BranchDetailResponse,
    BranchListResponse,
    BranchReactivateResponse,
    BranchResponse,
    BranchSettingsResponse,
    BranchSettingsUpdateRequest,
    BranchSettingsUpdateResponse,
    BranchUpdateRequest,
    BranchUpdateResponse,
    BusinessTypeUpdateRequest,
    BusinessTypeResponse,
    MFAPolicyUpdateRequest,
    MFAPolicyUpdateResponse,
    OrgCarjamUsageResponse,
    OrgUserResponse,
    OnboardingStepRequest,
    OnboardingStepResponse,
    OrgSettingsResponse,
    OrgSettingsUpdateRequest,
    OrgSettingsUpdateResponse,
    SalespersonItem,
    SalespersonListResponse,
    SeatLimitResponse,
    UserDeactivateResponse,
    UserInviteRequest,
    UserInviteResponse,
    UserListResponse,
    UserUpdateRequest,
    UserUpdateResponse,
)
from app.modules.organisations.service import (
    SeatLimitExceeded,
    assign_user_branches,
    create_branch,
    deactivate_branch,
    deactivate_org_user,
    get_branch_settings,
    get_org_settings,
    invite_org_user,
    list_branches,
    list_org_users,
    list_salespeople,
    reactivate_branch,
    revoke_user_sessions,
    save_onboarding_step,
    set_business_type,
    update_branch,
    update_branch_settings,
    update_mfa_policy,
    update_org_settings,
    update_org_user,
)

router = APIRouter()


async def require_branch_module(
    request: Request, db: AsyncSession = Depends(get_db_session)
):
    """FastAPI dependency that gates endpoints behind branch_management module.

    Extracts org_id from request.state, checks ModuleService.is_enabled,
    and raises HTTP 403 when the module is disabled.

    Requirements: 9.1, 9.2, 9.3, 11.1, 12.1
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return  # No org context — let other middleware handle
    svc = ModuleService(db)
    if not await svc.is_enabled(org_id, "branch_management"):
        raise HTTPException(
            status_code=403,
            detail="Branch management module is not enabled for this organisation",
        )


@router.post(
    "/onboarding",
    response_model=OnboardingStepResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Save onboarding wizard step",
    dependencies=[require_role("org_admin")],
)
async def save_onboarding(
    payload: OnboardingStepRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Save one or more onboarding wizard fields for the current organisation.

    Any field can be omitted (skipped). The workspace is usable immediately
    regardless of completion state.

    Requirements: 8.2, 8.3, 8.4, 8.5
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id or user_id format"},
        )

    try:
        result = await save_onboarding_step(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            org_name=payload.org_name,
            logo_url=payload.logo_url,
            primary_colour=payload.primary_colour,
            secondary_colour=payload.secondary_colour,
            gst_number=payload.gst_number,
            gst_percentage=payload.gst_percentage,
            invoice_prefix=payload.invoice_prefix,
            invoice_start_number=payload.invoice_start_number,
            default_due_days=payload.default_due_days,
            payment_terms_text=payload.payment_terms_text,
            first_service_name=payload.first_service_name,
            first_service_price=payload.first_service_price,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    msg = "Step skipped" if result["skipped"] else "Onboarding step saved"
    return OnboardingStepResponse(
        message=msg,
        updated_fields=result["updated_fields"],
        onboarding_complete=result["onboarding_complete"],
        skipped=result["skipped"],
    )


# ---------------------------------------------------------------------------
# Organisation Settings CRUD (Task 6.3)
# Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
# ---------------------------------------------------------------------------


@router.get(
    "/settings",
    response_model=OrgSettingsResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="Get organisation settings and branding",
    dependencies=[require_role("org_admin", "salesperson", "location_manager", "kiosk")],
)
async def get_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current organisation's settings and branding configuration.

    Accessible to both Org_Admin and Salesperson roles.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    try:
        settings_data = await get_org_settings(db, org_id=org_uuid)
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return OrgSettingsResponse(**settings_data)


@router.put(
    "/settings",
    response_model=OrgSettingsUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        422: {"description": "Invalid template ID or colour value"},
    },
    summary="Update organisation settings",
    dependencies=[require_role("org_admin")],
)
async def update_settings(
    payload: OrgSettingsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update the current organisation's settings and branding.

    Only Org_Admin role can update settings. Only provided (non-null)
    fields are updated; omitted fields remain unchanged.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id or user_id format"},
        )

    # Build kwargs from non-None payload fields
    update_kwargs = {
        k: v
        for k, v in payload.model_dump().items()
        if v is not None
    }

    try:
        result = await update_org_settings(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        error_msg = str(exc)
        # Template and colour validation errors → 422 Unprocessable Entity
        if "invoice template" in error_msg.lower() or "hex colour" in error_msg.lower():
            return JSONResponse(
                status_code=422,
                content={"detail": error_msg},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": error_msg},
        )

    if not result["updated_fields"]:
        return OrgSettingsUpdateResponse(
            message="No fields to update",
            updated_fields=[],
        )

    return OrgSettingsUpdateResponse(
        message="Organisation settings updated",
        updated_fields=result["updated_fields"],
    )


# ---------------------------------------------------------------------------
# Branch Management (Task 6.4)
# Requirements: 9.7, 9.8
# ---------------------------------------------------------------------------


@router.get(
    "/branches",
    response_model=BranchListResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org role required"},
    },
    summary="List organisation branches",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_branches(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all active branches for the current organisation.

    Accessible to both Org_Admin and Salesperson roles.

    Requirements: 9.7
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    branches = await list_branches(db, org_id=org_uuid)
    return BranchListResponse(
        branches=[BranchResponse(**b) for b in branches]
    )


@router.post(
    "/branches",
    response_model=BranchCreateResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Create a new branch",
    dependencies=[require_role("org_admin")],
)
async def create_new_branch(
    payload: BranchCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _branch_gate=Depends(require_branch_module),
):
    """Create a new branch location for the current organisation.

    Only Org_Admin role can create branches.

    Requirements: 9.7
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id or user_id format"},
        )

    try:
        branch_data = await create_branch(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            name=payload.name,
            address=payload.address,
            phone=payload.phone,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return BranchCreateResponse(
        message="Branch created",
        branch=BranchResponse(**branch_data),
    )


@router.post(
    "/branches/assign-user",
    response_model=AssignUserBranchesResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Assign a user to branches",
    dependencies=[require_role("org_admin")],
)
async def assign_user_to_branches(
    payload: AssignUserBranchesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Assign a user to one or more branches within the organisation.

    Only Org_Admin role can assign users to branches.

    Requirements: 9.8
    """
    acting_user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        acting_uuid = uuid.UUID(acting_user_id) if acting_user_id else uuid.uuid4()
        target_uuid = uuid.UUID(payload.user_id)
        branch_uuids = [uuid.UUID(bid) for bid in payload.branch_ids]
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid UUID format"},
        )

    try:
        result = await assign_user_branches(
            db,
            org_id=org_uuid,
            acting_user_id=acting_uuid,
            target_user_id=target_uuid,
            branch_ids=branch_uuids,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return AssignUserBranchesResponse(
        message="User assigned to branches",
        user_id=result["user_id"],
        branch_ids=result["branch_ids"],
    )


# ---------------------------------------------------------------------------
# Branch CRUD — Update, Deactivate, Reactivate, Settings (Task 9.1)
# Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.5, 2.6, 3.1, 3.5
# ---------------------------------------------------------------------------


@router.put(
    "/branches/{branch_id}",
    response_model=BranchUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Branch not found"},
    },
    summary="Update a branch",
    dependencies=[require_role("org_admin")],
)
async def update_branch_endpoint(
    branch_id: str,
    payload: BranchUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _branch_gate=Depends(require_branch_module),
):
    """Update branch fields for the current organisation.

    Only Org_Admin role can update branches. Only provided (non-null)
    fields are updated; omitted fields remain unchanged.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
        branch_uuid = uuid.UUID(branch_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid UUID format"},
        )

    update_kwargs = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }

    try:
        result = await update_branch(
            db,
            org_id=org_uuid,
            branch_id=branch_uuid,
            user_id=user_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Branch not found"},
        )

    return BranchUpdateResponse(
        message="Branch updated",
        branch=BranchDetailResponse(**result),
    )


@router.delete(
    "/branches/{branch_id}",
    response_model=BranchDeactivateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Branch not found"},
    },
    summary="Deactivate (soft-delete) a branch",
    dependencies=[require_role("org_admin")],
)
async def deactivate_branch_endpoint(
    branch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _branch_gate=Depends(require_branch_module),
):
    """Soft-delete a branch by setting is_active = False.

    Rejects if the branch is the only active branch or is HQ while
    other active branches exist.

    Requirements: 2.1, 2.5
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
        branch_uuid = uuid.UUID(branch_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid UUID format"},
        )

    try:
        result = await deactivate_branch(
            db,
            org_id=org_uuid,
            branch_id=branch_uuid,
            user_id=user_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Branch not found"},
        )

    return BranchDeactivateResponse(
        message="Branch deactivated",
        branch=BranchDetailResponse(**result),
    )


@router.post(
    "/branches/{branch_id}/reactivate",
    response_model=BranchReactivateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Branch not found"},
    },
    summary="Reactivate a deactivated branch",
    dependencies=[require_role("org_admin")],
)
async def reactivate_branch_endpoint(
    branch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _branch_gate=Depends(require_branch_module),
):
    """Reactivate a previously deactivated branch.

    Requirements: 2.6
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
        branch_uuid = uuid.UUID(branch_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid UUID format"},
        )

    try:
        result = await reactivate_branch(
            db,
            org_id=org_uuid,
            branch_id=branch_uuid,
            user_id=user_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Branch not found"},
        )

    return BranchReactivateResponse(
        message="Branch reactivated",
        branch=BranchDetailResponse(**result),
    )


@router.get(
    "/branches/{branch_id}/settings",
    response_model=BranchSettingsResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Branch not found"},
    },
    summary="Get branch settings",
    dependencies=[require_role("org_admin")],
)
async def get_branch_settings_endpoint(
    branch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return settings for a specific branch.

    Requirements: 3.1
    """
    org_id = getattr(request.state, "org_id", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        branch_uuid = uuid.UUID(branch_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid UUID format"},
        )

    result = await get_branch_settings(
        db,
        org_id=org_uuid,
        branch_id=branch_uuid,
    )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Branch not found"},
        )

    return BranchSettingsResponse(**result)


@router.put(
    "/branches/{branch_id}/settings",
    response_model=BranchSettingsUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Branch not found"},
    },
    summary="Update branch settings",
    dependencies=[require_role("org_admin")],
)
async def update_branch_settings_endpoint(
    branch_id: str,
    payload: BranchSettingsUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update settings for a specific branch.

    Only provided (non-null) fields are updated. Validates IANA timezone
    strings; rejects invalid values with 400.

    Requirements: 3.1, 3.5, 22.4
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
        branch_uuid = uuid.UUID(branch_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid UUID format"},
        )

    update_kwargs = {
        k: v for k, v in payload.model_dump().items() if v is not None
    }

    try:
        result = await update_branch_settings(
            db,
            org_id=org_uuid,
            branch_id=branch_uuid,
            user_id=user_uuid,
            ip_address=ip_address,
            **update_kwargs,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    if result is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Branch not found"},
        )

    return BranchSettingsUpdateResponse(
        message="Branch settings updated",
        settings=BranchSettingsResponse(**result),
    )


# ---------------------------------------------------------------------------
# User Management (Task 6.5)
# Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
# ---------------------------------------------------------------------------


@router.get(
    "/users",
    response_model=UserListResponse,
    responses={401: {"description": "Authentication required"}, 403: {"description": "Org_Admin role required"}},
    summary="List organisation users",
    dependencies=[require_role("org_admin")],
)
async def get_users(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all users for the current organisation with seat limit info.

    Requirements: 10.1, 10.4
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    result = await list_org_users(db, org_id=org_uuid)
    return UserListResponse(
        users=[OrgUserResponse(**u) for u in result["users"]],
        total=result["total"],
        seat_limit=result["seat_limit"],
    )


@router.get(
    "/salespeople",
    response_model=SalespersonListResponse,
    responses={401: {"description": "Authentication required"}, 403: {"description": "Organisation context required"}},
    summary="List salespeople for dropdown",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def get_salespeople(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return a simple list of active users for the salesperson dropdown.

    This endpoint is accessible by both org_admin and salesperson roles.
    Returns only id and name (email) for active users.
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    result = await list_salespeople(db, org_id=org_uuid)
    return SalespersonListResponse(
        salespeople=[SalespersonItem(**u) for u in result]
    )


@router.post(
    "/users/invite",
    response_model=UserInviteResponse,
    status_code=201,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        409: {"description": "Seat limit reached"},
    },
    summary="Invite a new user to the organisation",
    dependencies=[require_role("org_admin")],
)
async def invite_user(
    payload: UserInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Invite a new user with a 48-hour signup link and assign a role.

    Enforces user seat limits per the subscription plan.
    When the seat limit is reached, returns 409 with upgrade message.

    Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid UUID format"})

    # Gate branch_admin role behind branch_management module (Req 10.1, 10.2)
    if payload.role == "branch_admin":
        svc = ModuleService(db)
        if not await svc.is_enabled(str(org_uuid), "branch_management"):
            return JSONResponse(
                status_code=400,
                content={"detail": "branch_admin role requires the Branch Management module to be enabled"},
            )

    try:
        user_data = await invite_org_user(
            db,
            org_id=org_uuid,
            inviter_user_id=user_uuid,
            email=payload.email,
            role=payload.role,
            password=payload.password,
            ip_address=ip_address,
        )
    except SeatLimitExceeded as exc:
        return JSONResponse(
            status_code=409,
            content=SeatLimitResponse(
                detail=str(exc),
                current_users=exc.current_users,
                seat_limit=exc.seat_limit,
            ).model_dump(),
        )
    except ValueError as exc:
        import logging
        logging.getLogger(__name__).warning("Invite failed: %s", exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return UserInviteResponse(
        message="User invited successfully",
        user=OrgUserResponse(**user_data),
    )


@router.put(
    "/users/{target_user_id}",
    response_model=UserUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Update user role or status",
    dependencies=[require_role("org_admin")],
)
async def update_user(
    target_user_id: str,
    payload: UserUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a user's role or active status. Deactivating invalidates sessions.

    Requirements: 10.1, 10.2, 10.3
    """
    acting_user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
        acting_uuid = uuid.UUID(acting_user_id) if acting_user_id else uuid.uuid4()
        target_uuid = uuid.UUID(target_user_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid UUID format"})

    # Gate branch_admin role behind branch_management module (Req 10.2, 10.3)
    if payload.role == "branch_admin":
        svc = ModuleService(db)
        if not await svc.is_enabled(str(org_uuid), "branch_management"):
            return JSONResponse(
                status_code=400,
                content={"detail": "branch_admin role requires the Branch Management module to be enabled"},
            )

    try:
        result = await update_org_user(
            db,
            org_id=org_uuid,
            acting_user_id=acting_uuid,
            target_user_id=target_uuid,
            role=payload.role,
            is_active=payload.is_active,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return UserUpdateResponse(
        message="User updated successfully",
        user=OrgUserResponse(
            id=result["id"],
            email=result["email"],
            role=result["role"],
            is_active=result["is_active"],
            is_email_verified=result["is_email_verified"],
            last_login_at=result["last_login_at"],
            created_at=result["created_at"],
        ),
    )


@router.delete(
    "/users/{target_user_id}",
    response_model=UserDeactivateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Deactivate a user",
    dependencies=[require_role("org_admin")],
)
async def delete_user(
    target_user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Deactivate a user and immediately invalidate all their sessions.

    Requirements: 10.2
    """
    acting_user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
        acting_uuid = uuid.UUID(acting_user_id) if acting_user_id else uuid.uuid4()
        target_uuid = uuid.UUID(target_user_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid UUID format"})

    try:
        result = await deactivate_org_user(
            db,
            org_id=org_uuid,
            acting_user_id=acting_uuid,
            target_user_id=target_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return UserDeactivateResponse(
        message="User deactivated",
        user_id=result["user_id"],
        sessions_invalidated=result["sessions_invalidated"],
    )


@router.post(
    "/users/{target_user_id}/revoke-sessions",
    response_model=UserDeactivateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Revoke all active sessions for a user",
    dependencies=[require_role("org_admin")],
)
async def revoke_sessions(
    target_user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Revoke all active sessions for a user without deactivating the account.

    Requirements: 7.3
    """
    acting_user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
        acting_uuid = uuid.UUID(acting_user_id) if acting_user_id else uuid.uuid4()
        target_uuid = uuid.UUID(target_user_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid UUID format"})

    try:
        result = await revoke_user_sessions(
            db,
            org_id=org_uuid,
            acting_user_id=acting_uuid,
            target_user_id=target_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return UserDeactivateResponse(
        message="Sessions revoked",
        user_id=result["user_id"],
        sessions_invalidated=result["sessions_invalidated"],
    )


@router.delete(
    "/users/{target_user_id}/permanent",
    responses={
        200: {"description": "User permanently deleted"},
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Permanently delete a user",
    dependencies=[require_role("org_admin")],
)
async def delete_user_permanent(
    target_user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Permanently delete a user from the organisation.

    Reassigns any invoices/credit notes created by this user to the acting
    admin before deletion to avoid FK constraint violations.
    """
    from sqlalchemy import update as sql_update, select, delete
    from app.core.audit import write_audit_log
    from app.modules.auth.models import User, Session, UserMfaMethod, UserPasskeyCredential, UserBackupCode
    from app.modules.invoices.models import Invoice, CreditNote

    acting_user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
        acting_uuid = uuid.UUID(acting_user_id) if acting_user_id else None
        target_uuid = uuid.UUID(target_user_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid UUID format"})

    if acting_uuid and acting_uuid == target_uuid:
        return JSONResponse(status_code=400, content={"detail": "Cannot delete your own account"})

    # Verify user belongs to this org
    result = await db.execute(
        select(User).where(User.id == target_uuid, User.org_id == org_uuid)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return JSONResponse(status_code=400, content={"detail": "User not found in this organisation"})

    email = user.email

    # Reassign invoices and credit notes to the acting admin
    if acting_uuid:
        await db.execute(
            sql_update(Invoice)
            .where(Invoice.created_by == target_uuid)
            .values(created_by=acting_uuid)
        )
        await db.execute(
            sql_update(CreditNote)
            .where(CreditNote.created_by == target_uuid)
            .values(created_by=acting_uuid)
        )

    # Delete related auth records
    await db.execute(delete(UserMfaMethod).where(UserMfaMethod.user_id == target_uuid))
    await db.execute(delete(UserPasskeyCredential).where(UserPasskeyCredential.user_id == target_uuid))
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == target_uuid))
    await db.execute(delete(Session).where(Session.user_id == target_uuid))

    # Delete the user
    await db.delete(user)

    await write_audit_log(
        session=db,
        org_id=org_uuid,
        user_id=acting_uuid,
        action="org.user_deleted_permanently",
        entity_type="user",
        entity_id=target_uuid,
        after_value={"email": email, "deleted_permanently": True},
        ip_address=ip_address,
    )

    await db.commit()

    return {"message": f"User {email} permanently deleted", "user_id": str(target_uuid)}


@router.put(
    "/users/mfa-policy",
    response_model=MFAPolicyUpdateResponse,
    responses={
        400: {"description": "Validation error"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Configure MFA policy for the organisation",
    dependencies=[require_role("org_admin")],
)
async def set_mfa_policy(
    payload: MFAPolicyUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure whether MFA is optional or mandatory for all org users.

    Requirements: 10.3
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
        user_uuid = uuid.UUID(user_id) if user_id else uuid.uuid4()
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid UUID format"})

    try:
        result = await update_mfa_policy(
            db,
            org_id=org_uuid,
            user_id=user_uuid,
            mfa_policy=payload.mfa_policy,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return MFAPolicyUpdateResponse(
        message="MFA policy updated",
        mfa_policy=result["mfa_policy"],
    )


@router.get(
    "/carjam-usage",
    response_model=OrgCarjamUsageResponse,
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    summary="Organisation Carjam usage for billing dashboard",
    dependencies=[require_role("org_admin")],
)
async def get_org_carjam_usage(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the organisation's own Carjam usage for the current month.

    Shows total lookups, included in plan, overage count, and charge.
    Displayed on the billing dashboard so Org_Admins are aware of
    accrued charges.

    Requirement 16.4.
    """
    from app.modules.admin.service import get_org_carjam_usage as _get_usage

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    try:
        usage = await _get_usage(db, org_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return OrgCarjamUsageResponse(**usage)

# ---------------------------------------------------------------------------
# SMS usage — Org Admin (Requirements 6.5, 6.6, 7.1)
# ---------------------------------------------------------------------------


@router.get(
    "/sms-usage",
    summary="Organisation SMS usage for billing dashboard",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Organisation not found"},
    },
    dependencies=[require_role("org_admin")],
)
async def get_org_sms_usage(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the organisation's own SMS usage for the current month.

    Shows total SMS sent, included in plan, package credits, effective
    quota, overage count, and overage charge.

    Requirements: 7.1.
    """
    from app.modules.admin.schemas import OrgSmsUsageResponse
    from app.modules.admin.service import get_org_sms_usage as _get_usage

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    try:
        usage = await _get_usage(db, org_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    return OrgSmsUsageResponse(**usage)


@router.get(
    "/sms-packages",
    summary="Organisation active SMS package purchases",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    dependencies=[require_role("org_admin")],
)
async def get_org_sms_packages(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the organisation's active SMS package purchases.

    Lists all purchased SMS packages with remaining credits, ordered
    by purchase date ascending (oldest first).

    Requirements: 6.5.
    """
    from app.modules.admin.schemas import SmsPackagePurchaseResponse
    from app.modules.admin.service import get_org_sms_packages as _get_packages

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    packages = await _get_packages(db, org_uuid)
    return [SmsPackagePurchaseResponse(**pkg) for pkg in packages]


@router.post(
    "/sms-packages/purchase",
    summary="Purchase an SMS package",
    responses={
        401: {"description": "Authentication required"},
        402: {"description": "Payment failed"},
        403: {"description": "Org_Admin role required"},
        404: {"description": "Tier not found on plan"},
        502: {"description": "Payment service unavailable"},
    },
    dependencies=[require_role("org_admin")],
)
async def purchase_org_sms_package(
    request: Request,
    body: SmsPackagePurchaseRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Purchase a bulk SMS package for the organisation.

    Validates the requested tier exists on the org's plan, creates a
    Stripe one-time charge, and records the purchase with full credits.

    Requirements: 6.6.
    """
    from app.modules.admin.schemas import SmsPackagePurchaseResponse
    from app.modules.admin.service import purchase_sms_package as _purchase

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    try:
        result = await _purchase(db, org_uuid, body.tier_name)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    except RuntimeError as exc:
        error_msg = str(exc)
        if "Payment failed" in error_msg:
            return JSONResponse(status_code=402, content={"detail": error_msg})
        return JSONResponse(status_code=502, content={"detail": "Payment service unavailable"})

    return SmsPackagePurchaseResponse(**result)



# ---------------------------------------------------------------------------
# Audit log viewing — Org Admin (Req 51.1, 51.2, 51.4)
# ---------------------------------------------------------------------------


@router.get(
    "/audit-log",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Organisation audit log",
    dependencies=[require_role("org_admin")],
)
async def get_org_audit_log(
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
    """Return paginated, filterable audit log scoped to the caller's org.

    Only Org_Admin users can access this endpoint.
    Requirements: 51.1, 51.2, 51.4.
    """
    from app.modules.admin.schemas import AuditLogEntry, AuditLogListResponse
    from app.modules.admin.service import list_audit_logs

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(status_code=403, content={"detail": "Organisation context required"})

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(status_code=400, content={"detail": "Invalid org_id format"})

    result = await list_audit_logs(
        db,
        org_id=org_uuid,
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
# Plan features — subscription plan feature flags (Req 4.2, 4.3)
# ---------------------------------------------------------------------------


@router.get(
    "/plan-features",
    responses={
        401: {"description": "Authentication required"},
        403: {"description": "Organisation context required"},
    },
    summary="Get organisation plan feature flags",
)
async def get_plan_features(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return feature flags derived from the organisation's subscription plan.

    Currently returns ``sms_included`` so the frontend can gate SMS-related
    UI elements based on the plan.

    Requirements: 4.2, 4.3.
    """
    from sqlalchemy import select

    from app.modules.admin.models import Organisation, SubscriptionPlan

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    result = await db.execute(
        select(SubscriptionPlan.sms_included)
        .join(Organisation, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_uuid)
    )
    row = result.scalar_one_or_none()
    return {"sms_included": bool(row) if row is not None else False}


# ---------------------------------------------------------------------------
# Public Holidays (org-level, filtered by org country)
# ---------------------------------------------------------------------------


@router.get(
    "/holidays",
    summary="Get public holidays for the org's country",
)
async def get_org_holidays(
    request: Request,
    year: int | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Return public holidays based on the organisation's address_country setting.

    Falls back to NZ if no country is configured. Only returns holidays
    for the org's country code.
    """
    from sqlalchemy import select
    from app.modules.admin.models import Organisation, PublicHoliday

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    # Get org's country code from settings
    result = await db.execute(
        select(Organisation.settings).where(Organisation.id == org_uuid)
    )
    settings = result.scalar_one_or_none() or {}
    country_raw = settings.get("address_country", "NZ") or "NZ"

    # Resolve legacy full names to codes
    legacy_map = {
        "new zealand": "NZ",
        "australia": "AU",
    }
    country_code = country_raw.upper() if len(country_raw) == 2 else legacy_map.get(country_raw.lower(), country_raw.upper()[:2])

    # Query holidays
    stmt = select(PublicHoliday).where(PublicHoliday.country_code == country_code)
    if year:
        stmt = stmt.where(PublicHoliday.year == year)
    stmt = stmt.order_by(PublicHoliday.holiday_date)

    rows = await db.execute(stmt)
    holidays = rows.scalars().all()

    return {
        "country_code": country_code,
        "holidays": [
            {
                "id": str(h.id),
                "date": h.holiday_date.isoformat(),
                "name": h.name,
                "local_name": h.local_name,
                "year": h.year,
            }
            for h in holidays
        ],
    }


# ---------------------------------------------------------------------------
# Branch Dashboard — metrics and comparison (Req 15, 16)
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard/branch-metrics",
    summary="Branch-scoped dashboard metrics",
    dependencies=[require_role("org_admin", "salesperson")],
)
async def branch_metrics(
    request: Request,
    branch_id: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Return dashboard metrics scoped to a branch or aggregated org-wide.

    When branch_id is provided, returns metrics for that branch only.
    When omitted, returns org-wide aggregated metrics.

    Requirements: 15.1, 15.2, 15.3, 15.4
    """
    from app.modules.organisations.dashboard_service import get_branch_metrics

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    branch_uuid = None
    if branch_id:
        try:
            branch_uuid = uuid.UUID(branch_id)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid branch_id format"},
            )
    else:
        # Fallback: use branch_id from BranchContextMiddleware (X-Branch-Id header)
        middleware_branch = getattr(request.state, "branch_id", None)
        if middleware_branch is not None:
            branch_uuid = middleware_branch if isinstance(middleware_branch, uuid.UUID) else uuid.UUID(str(middleware_branch))

    data = await get_branch_metrics(db, org_uuid, branch_id=branch_uuid)

    # Serialize Decimal values to strings for JSON
    return {
        "branch_id": data["branch_id"],
        "revenue": str(data["revenue"]),
        "invoice_count": data["invoice_count"],
        "invoice_value": str(data["invoice_value"]),
        "customer_count": data["customer_count"],
        "staff_count": data["staff_count"],
        "total_expenses": str(data["total_expenses"]),
    }


@router.get(
    "/dashboard/branch-comparison",
    summary="Compare multiple branches side by side",
    dependencies=[require_role("org_admin")],
)
async def branch_comparison(
    request: Request,
    branch_ids: str = "",
    db: AsyncSession = Depends(get_db_session),
):
    """Return side-by-side metrics for selected branches.

    Pass branch_ids as a comma-separated list of UUIDs.

    Requirements: 16.1, 16.2, 16.3, 16.4
    """
    from app.modules.organisations.dashboard_service import get_branch_comparison

    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    # Parse comma-separated branch IDs
    parsed_ids = []
    if branch_ids.strip():
        for bid_str in branch_ids.split(","):
            bid_str = bid_str.strip()
            if bid_str:
                try:
                    parsed_ids.append(uuid.UUID(bid_str))
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": f"Invalid branch_id: {bid_str}"},
                    )

    data = await get_branch_comparison(db, org_uuid, parsed_ids)

    # Serialize Decimal values
    serialized_branches = []
    for bm in data["branches"]:
        serialized_branches.append({
            "branch_id": bm["branch_id"],
            "branch_name": bm["branch_name"],
            "revenue": str(bm["revenue"]),
            "invoice_count": bm["invoice_count"],
            "invoice_value": str(bm["invoice_value"]),
            "customer_count": bm["customer_count"],
            "staff_count": bm["staff_count"],
            "total_expenses": str(bm["total_expenses"]),
        })

    highlights = {}
    for key, val in data.get("highlights", {}).items():
        highlights[key] = {
            "highest": {"branch": val["highest"]["branch"], "value": str(val["highest"]["value"])},
            "lowest": {"branch": val["lowest"]["branch"], "value": str(val["lowest"]["value"])},
        }

    return {
        "branches": serialized_branches,
        "highlights": highlights,
    }


# ---------------------------------------------------------------------------
# Sprint 7 — Business Entity Type (Req 29.1, 30.1)
# ---------------------------------------------------------------------------


@router.put(
    "/organisations/{org_id}/business-type",
    response_model=BusinessTypeResponse,
    summary="Set business entity type and NZBN",
    dependencies=[require_role("org_admin")],
)
async def update_business_type(
    org_id: uuid.UUID,
    payload: BusinessTypeUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Set business type, NZBN, and related entity fields.

    Requirements: 29.1, 30.1
    """
    request_org_id = getattr(request.state, "org_id", None)
    if not request_org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    # Ensure user can only update their own org
    try:
        request_org_uuid = uuid.UUID(request_org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    if request_org_uuid != org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Cannot update another organisation's business type"},
        )

    user_id = getattr(request.state, "user_id", None)
    ip_address = getattr(request.state, "client_ip", None)

    result = await set_business_type(
        db,
        org_id=org_id,
        user_id=uuid.UUID(user_id) if user_id else None,
        business_type=payload.business_type,
        nzbn=payload.nzbn,
        nz_company_number=payload.nz_company_number,
        gst_registered=payload.gst_registered,
        gst_registration_date=payload.gst_registration_date,
        income_tax_year_end=payload.income_tax_year_end,
        provisional_tax_method=payload.provisional_tax_method,
        ip_address=ip_address,
    )

    return BusinessTypeResponse(**result, message="Business type updated")


# ---------------------------------------------------------------------------
# Portal Analytics (Req 47.1, 47.2, 47.3)
# ---------------------------------------------------------------------------


@router.get(
    "/portal-analytics",
    summary="Get portal usage analytics for the last 30 days",
    dependencies=[require_role("org_admin")],
)
async def get_portal_analytics_endpoint(
    request: Request,
):
    """Return portal usage statistics (views, quote acceptances, bookings,
    payments) aggregated per day for the last 30 days.

    Requirements: 47.1, 47.2, 47.3
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )

    try:
        org_uuid = uuid.UUID(org_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid org_id format"},
        )

    from app.modules.portal.service import get_portal_analytics

    result = await get_portal_analytics(org_uuid)
    return result
