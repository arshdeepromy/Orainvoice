"""Trade category registry API routers.

Public endpoints (any authenticated user):
- GET  /api/v2/trade-families
- GET  /api/v2/trade-categories
- GET  /api/v2/trade-categories/{slug}

Admin endpoints (Global Admin only):
- POST /api/v2/admin/trade-families
- POST /api/v2/admin/trade-categories
- PUT  /api/v2/admin/trade-categories/{slug}
- GET  /api/v2/admin/trade-categories/export
- POST /api/v2/admin/trade-categories/import

**Validates: Requirement 3**
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.trade_categories.schemas import (
    SeedDataExport,
    TradeCategoryCreate,
    TradeCategoryListResponse,
    TradeCategoryResponse,
    TradeCategoryUpdate,
    TradeFamilyCreate,
    TradeFamilyListResponse,
    TradeFamilyResponse,
)
from app.modules.trade_categories.service import TradeCategoryService

# ---------------------------------------------------------------------------
# Public router — mounted at /api/v2/trade-families and /api/v2/trade-categories
# ---------------------------------------------------------------------------

families_router = APIRouter()
categories_router = APIRouter()


@families_router.get(
    "",
    response_model=TradeFamilyListResponse,
    summary="List all active trade families",
)
async def list_trade_families(
    db: AsyncSession = Depends(get_db_session),
):
    """Return all active trade families ordered by display_order."""
    svc = TradeCategoryService(db)
    families = await svc.list_families()
    return TradeFamilyListResponse(
        families=[TradeFamilyResponse.model_validate(f) for f in families],
        total=len(families),
    )


@categories_router.get(
    "",
    response_model=TradeCategoryListResponse,
    summary="List trade categories",
)
async def list_trade_categories(
    family: str | None = Query(None, description="Filter by family slug"),
    include_retired: bool = Query(False, description="Include retired categories"),
    db: AsyncSession = Depends(get_db_session),
):
    """Return trade categories, optionally filtered by family slug."""
    svc = TradeCategoryService(db)
    categories = await svc.list_categories(
        family_slug=family, include_retired=include_retired,
    )
    return TradeCategoryListResponse(
        categories=[TradeCategoryResponse.model_validate(c) for c in categories],
        total=len(categories),
    )


@categories_router.get(
    "/{slug}",
    response_model=TradeCategoryResponse,
    summary="Get trade category by slug",
)
async def get_trade_category(
    slug: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return a single trade category with full seed data."""
    svc = TradeCategoryService(db)
    category = await svc.get_category(slug)
    if category is None:
        raise HTTPException(status_code=404, detail="Trade category not found")
    return TradeCategoryResponse.model_validate(category)


# ---------------------------------------------------------------------------
# Admin router — mounted at /api/v2/admin/trade-families and
#                             /api/v2/admin/trade-categories
# ---------------------------------------------------------------------------

admin_families_router = APIRouter()
admin_categories_router = APIRouter()


@admin_families_router.post(
    "",
    response_model=TradeFamilyResponse,
    status_code=201,
    summary="Create a trade family",
    dependencies=[require_role("global_admin")],
)
async def create_trade_family(
    payload: TradeFamilyCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new trade family (Global Admin only)."""
    svc = TradeCategoryService(db)
    family = await svc.create_family(payload)
    return TradeFamilyResponse.model_validate(family)


@admin_categories_router.post(
    "",
    response_model=TradeCategoryResponse,
    status_code=201,
    summary="Create a trade category",
    dependencies=[require_role("global_admin")],
)
async def create_trade_category(
    payload: TradeCategoryCreate,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new trade category (Global Admin only).

    Validates unique slug, valid family, and at least one default service.
    """
    svc = TradeCategoryService(db)
    try:
        category = await svc.create_category(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return TradeCategoryResponse.model_validate(category)


@admin_categories_router.put(
    "/{slug}",
    response_model=TradeCategoryResponse,
    summary="Update a trade category",
    dependencies=[require_role("global_admin")],
)
async def update_trade_category(
    slug: str,
    payload: TradeCategoryUpdate,
    db: AsyncSession = Depends(get_db_session),
):
    """Update a trade category (Global Admin only).

    Changes to defaults only affect new orgs going through setup wizard.
    """
    svc = TradeCategoryService(db)
    category = await svc.update_category(slug, payload)
    if category is None:
        raise HTTPException(status_code=404, detail="Trade category not found")
    return TradeCategoryResponse.model_validate(category)


@admin_categories_router.get(
    "/export",
    summary="Export seed data as JSON",
    dependencies=[require_role("global_admin")],
)
async def export_seed_data(
    db: AsyncSession = Depends(get_db_session),
):
    """Export all trade families and categories as JSON for version control."""
    svc = TradeCategoryService(db)
    return await svc.export_seed_data()


@admin_categories_router.post(
    "/import",
    summary="Import seed data from JSON",
    dependencies=[require_role("global_admin")],
)
async def import_seed_data(
    payload: SeedDataExport,
    db: AsyncSession = Depends(get_db_session),
):
    """Import trade families and categories from JSON export."""
    svc = TradeCategoryService(db)
    counts = await svc.import_seed_data(payload.model_dump(mode="json"))
    return counts
