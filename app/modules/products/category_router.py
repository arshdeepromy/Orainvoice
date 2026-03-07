"""Product category API router with tree structure support.

Endpoints:
- GET    /api/v2/product-categories          — list (tree)
- POST   /api/v2/product-categories          — create
- GET    /api/v2/product-categories/{id}     — get
- PUT    /api/v2/product-categories/{id}     — update
- DELETE /api/v2/product-categories/{id}     — delete

**Validates: Requirement 9.2**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.products.schemas import (
    ProductCategoryCreate,
    ProductCategoryResponse,
    ProductCategoryTreeResponse,
    ProductCategoryUpdate,
)
from app.modules.products.service import ProductService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get(
    "", response_model=ProductCategoryTreeResponse,
    summary="List categories as tree",
)
async def list_categories(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    tree = await svc.get_category_tree(org_id)
    all_cats = await svc.list_categories(org_id)
    return ProductCategoryTreeResponse(tree=tree, total=len(all_cats))


@router.post(
    "",
    response_model=ProductCategoryResponse,
    status_code=201,
    summary="Create category",
)
async def create_category(
    payload: ProductCategoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    category = await svc.create_category(org_id, payload)
    return ProductCategoryResponse.model_validate(category)


@router.get(
    "/{category_id}",
    response_model=ProductCategoryResponse,
    summary="Get category",
)
async def get_category(
    category_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    category = await svc.get_category(org_id, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return ProductCategoryResponse.model_validate(category)


@router.put(
    "/{category_id}",
    response_model=ProductCategoryResponse,
    summary="Update category",
)
async def update_category(
    category_id: UUID,
    payload: ProductCategoryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    category = await svc.update_category(org_id, category_id, payload)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return ProductCategoryResponse.model_validate(category)


@router.delete("/{category_id}", summary="Delete category")
async def delete_category(
    category_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    deleted = await svc.delete_category(org_id, category_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"detail": "Category deleted"}
