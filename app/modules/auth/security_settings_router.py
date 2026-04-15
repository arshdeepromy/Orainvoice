"""API router for org-level security settings.

Provides endpoints for reading/updating security settings, managing custom
roles, listing permissions, and viewing the security audit log.

All endpoints are gated with ``require_role("org_admin")``.

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.auth.security_settings_schemas import (
    AuditLogFilters,
    AuditLogPage,
    CustomRoleCreate,
    CustomRoleUpdate,
    OrgSecuritySettings,
    PermissionGroup,
    RoleResponse,
    SecuritySettingsUpdate,
)
from app.modules.auth.security_settings_service import (
    get_security_settings,
    update_security_settings,
)
from app.modules.auth.security_audit_service import get_security_audit_log
from app.modules.auth.custom_roles_service import (
    create_custom_role,
    delete_custom_role,
    list_roles,
    update_custom_role,
)
from app.modules.auth.permission_registry import get_available_permissions

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_context(request: Request) -> tuple[uuid.UUID, uuid.UUID, str | None, str | None]:
    """Extract org_id, user_id, ip_address, and device_info from request state."""
    org_id = uuid.UUID(request.state.org_id)
    user_id = uuid.UUID(request.state.user_id)
    ip_address = request.client.host if request.client else None
    device_info = request.headers.get("user-agent")
    return org_id, user_id, ip_address, device_info


# ---------------------------------------------------------------------------
# Security Settings
# ---------------------------------------------------------------------------


@router.get(
    "/security-settings",
    response_model=OrgSecuritySettings,
    summary="Get org security settings",
    dependencies=[require_role("org_admin")],
)
async def get_settings_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgSecuritySettings:
    """Return the complete security settings for the current org."""
    org_id = uuid.UUID(request.state.org_id)
    return await get_security_settings(db, org_id)


@router.put(
    "/security-settings",
    response_model=OrgSecuritySettings,
    summary="Update org security settings",
    dependencies=[require_role("org_admin")],
)
async def update_settings_endpoint(
    payload: SecuritySettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgSecuritySettings:
    """Partially update security settings. Only provided sections are overwritten."""
    org_id, user_id, ip_address, device_info = _extract_context(request)
    return await update_security_settings(
        db, org_id, user_id, payload,
        ip_address=ip_address,
        device_info=device_info,
    )


# ---------------------------------------------------------------------------
# Security Audit Log
# ---------------------------------------------------------------------------


@router.get(
    "/security-audit-log",
    response_model=AuditLogPage,
    summary="Get security audit log",
    dependencies=[require_role("org_admin")],
)
async def get_audit_log_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    action: str | None = Query(default=None),
    user_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25),
) -> AuditLogPage:
    """Return paginated security audit log entries for the current org."""
    org_id = uuid.UUID(request.state.org_id)
    filters = AuditLogFilters(
        start_date=start_date,
        end_date=end_date,
        action=action,
        user_id=user_id,
        page=page,
        page_size=page_size,
    )
    return await get_security_audit_log(db, org_id, filters)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    summary="List all roles",
    dependencies=[require_role("org_admin")],
)
async def list_roles_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> list[RoleResponse]:
    """List built-in and custom roles for the current org."""
    org_id = uuid.UUID(request.state.org_id)
    roles = await list_roles(db, org_id)
    return [RoleResponse(**r) for r in roles]


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=201,
    summary="Create a custom role",
    dependencies=[require_role("org_admin")],
)
async def create_role_endpoint(
    payload: CustomRoleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RoleResponse:
    """Create a new custom role for the current org."""
    org_id, user_id, ip_address, device_info = _extract_context(request)
    role = await create_custom_role(
        db, org_id,
        name=payload.name,
        permissions=payload.permissions,
        description=payload.description,
        created_by=user_id,
        ip_address=ip_address,
        device_info=device_info,
    )
    return RoleResponse(**role)


@router.put(
    "/roles/{role_id}",
    response_model=RoleResponse,
    summary="Update a custom role",
    dependencies=[require_role("org_admin")],
)
async def update_role_endpoint(
    role_id: uuid.UUID,
    payload: CustomRoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RoleResponse:
    """Update an existing custom role."""
    _, user_id, ip_address, device_info = _extract_context(request)
    try:
        role = await update_custom_role(
            db, role_id,
            name=payload.name,
            permissions=payload.permissions,
            description=payload.description,
            updated_by=user_id,
            ip_address=ip_address,
            device_info=device_info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RoleResponse(**role)


@router.delete(
    "/roles/{role_id}",
    summary="Delete a custom role",
    dependencies=[require_role("org_admin")],
)
async def delete_role_endpoint(
    role_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Delete a custom role. Fails if role is built-in or has assigned users."""
    _, user_id, ip_address, device_info = _extract_context(request)
    try:
        await delete_custom_role(
            db, role_id,
            deleted_by=user_id,
            ip_address=ip_address,
            device_info=device_info,
        )
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "assigned to" in detail else 400
        raise HTTPException(status_code=status, detail=detail)
    return {"message": "Role deleted"}


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


@router.get(
    "/permissions",
    response_model=list[PermissionGroup],
    summary="List available permissions",
    dependencies=[require_role("org_admin")],
)
async def list_permissions_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> list[PermissionGroup]:
    """Return available permissions grouped by module for the current org."""
    org_id = uuid.UUID(request.state.org_id)
    return await get_available_permissions(db, org_id)
