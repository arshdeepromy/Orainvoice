"""Module management API router.

Endpoints for listing, enabling, and disabling modules per organisation.
Mounted at ``/api/v2/modules``.

**Validates: Requirement 6**
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.modules import (
    CORE_MODULES,
    TRADE_FAMILY_REJECTION_MESSAGES,
    TRADE_FAMILY_REQUIRED_MODULES,
    ModuleService,
    fetch_org_trade_family,
    is_trade_family_satisfied,
)
from app.modules.auth.rbac import require_role
from app.modules.module_management.schemas import (
    DisableModuleResponse,
    EnableModuleResponse,
    ModuleListResponse,
    ModuleResponse,
)

router = APIRouter()

# Module categories that are only visible to global_admin users.
# These are platform-level features, not org-level features.
GLOBAL_ADMIN_CATEGORIES = {"admin"}


@router.get(
    "",
    response_model=ModuleListResponse,
    summary="List all modules with enabled state",
)
async def list_modules(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all available modules with their enabled/disabled state
    for the authenticated organisation.

    Modules in the 'admin' category (Branding, Analytics Dashboard,
    Migration Tool, Internationalisation) are only returned for
    global_admin users.
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return ModuleListResponse(modules=[], total=0)

    role = getattr(request.state, "role", None)
    svc = ModuleService(db)
    modules = await svc.get_all_modules_for_org(org_id)

    # Filter out global-admin-only modules for non-global_admin users
    if role != "global_admin":
        modules = [m for m in modules if m.get("category") not in GLOBAL_ADMIN_CATEGORIES]
        # Hide modules not included in the org's subscription plan
        modules = [m for m in modules if m.get("in_plan", True)]

    # Filter out trade-family-restricted modules whose required family does
    # not match the org's tradeFamily (Requirement 1.2 of b2b-fleet-portal).
    # Only resolve the trade family if at least one restricted module is in
    # the result set — saves a DB roundtrip for the common case.
    if any(m.get("slug") in TRADE_FAMILY_REQUIRED_MODULES for m in modules):
        org_trade_family = await fetch_org_trade_family(db, org_id)
        modules = [
            m
            for m in modules
            if is_trade_family_satisfied(m.get("slug", ""), org_trade_family)
        ]

    items = [ModuleResponse(**m) for m in modules]
    return ModuleListResponse(modules=items, total=len(items))


@router.put(
    "/{slug}/enable",
    response_model=EnableModuleResponse,
    summary="Enable a module for the organisation",
    dependencies=[require_role("org_admin")],
)
async def enable_module(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Enable a module, auto-enabling any required dependencies.

    Requirement 6.4: auto-enable dependency modules and notify.
    """
    org_id = getattr(request.state, "org_id", None)
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)

    if not org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation context required"},
        )

    # Block non-global_admin from enabling admin-category modules
    from app.modules.module_management.models import ModuleRegistry
    mod_result = await db.execute(
        select(ModuleRegistry.category).where(ModuleRegistry.slug == slug)
    )
    mod_category = mod_result.scalar_one_or_none()
    if mod_category in GLOBAL_ADMIN_CATEGORIES and role != "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": f"Module '{slug}' is a platform admin module and cannot be managed by org users."},
        )

    # Trade-family gating (Requirement 1.3 of b2b-fleet-portal): reject the
    # request with HTTP 403 when the module is restricted to a trade family
    # the org does not belong to.
    if slug in TRADE_FAMILY_REQUIRED_MODULES:
        org_trade_family = await fetch_org_trade_family(db, org_id)
        if not is_trade_family_satisfied(slug, org_trade_family):
            detail = TRADE_FAMILY_REJECTION_MESSAGES.get(
                slug,
                f"Module '{slug}' is not available for your trade family.",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": detail},
            )

    # Validate module is available in the org's plan
    from app.modules.admin.models import Organisation, SubscriptionPlan
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org and org.plan_id:
        plan_result = await db.execute(
            select(SubscriptionPlan.enabled_modules).where(SubscriptionPlan.id == org.plan_id)
        )
        plan_modules = plan_result.scalar_one_or_none()
        if plan_modules is not None:
            plan_set = set(plan_modules) if isinstance(plan_modules, list) else set()
            if "all" not in plan_set and slug not in plan_set and slug not in CORE_MODULES:
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Module '{slug}' is not available in your plan."},
                )

    svc = ModuleService(db)
    additionally_enabled = await svc.enable_module(org_id, slug, enabled_by=user_id)

    # Commit before cache invalidation so the refetch sees committed data
    await db.commit()
    await svc._invalidate_cache(org_id)

    msg = f"Module '{slug}' enabled."
    if additionally_enabled:
        msg += f" Dependencies also enabled: {', '.join(additionally_enabled)}."

    return EnableModuleResponse(
        slug=slug,
        enabled=True,
        additionally_enabled=additionally_enabled,
        message=msg,
    )


@router.put(
    "/{slug}/disable",
    response_model=DisableModuleResponse,
    summary="Disable a module for the organisation",
    dependencies=[require_role("org_admin")],
)
async def disable_module(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    force: bool = False,
):
    """Disable a module. If other enabled modules depend on it, returns a
    warning with the dependent list instead of disabling.

    Pass ``?force=true`` to disable even when dependents exist.

    Requirement 6.3: warn about dependents before disabling.
    Requirement 6.7: data is retained when module is disabled.
    """
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Organisation context required"},
        )

    if slug in CORE_MODULES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Core module '{slug}' cannot be disabled."},
        )

    # Block non-global_admin from disabling admin-category modules
    role = getattr(request.state, "role", None)
    from app.modules.module_management.models import ModuleRegistry
    mod_result = await db.execute(
        select(ModuleRegistry.category).where(ModuleRegistry.slug == slug)
    )
    mod_category = mod_result.scalar_one_or_none()
    if mod_category in GLOBAL_ADMIN_CATEGORIES and role != "global_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": f"Module '{slug}' is a platform admin module and cannot be managed by org users."},
        )

    svc = ModuleService(db)
    dependents = await svc.disable_module(org_id, slug)

    if dependents and not force:
        return DisableModuleResponse(
            slug=slug,
            disabled=False,
            dependents=dependents,
            warning=(
                f"Module '{slug}' cannot be disabled because the following "
                f"enabled modules depend on it: {', '.join(dependents)}. "
                f"Disable those modules first or use ?force=true."
            ),
            message="Module not disabled due to active dependents.",
        )

    await svc.force_disable_module(org_id, slug)

    # Commit before cache invalidation so the refetch sees committed data
    await db.commit()
    await svc._invalidate_cache(org_id)

    return DisableModuleResponse(
        slug=slug,
        disabled=True,
        dependents=[],
        message=f"Module '{slug}' disabled. Data has been retained.",
    )
