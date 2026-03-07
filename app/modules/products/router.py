"""Product API router.

Endpoints:
- GET    /api/v2/products                 — list (paginated/filterable)
- POST   /api/v2/products                 — create
- GET    /api/v2/products/{id}            — get
- PUT    /api/v2/products/{id}            — update
- DELETE /api/v2/products/{id}            — soft-delete
- GET    /api/v2/products/barcode/{code}  — barcode lookup

**Validates: Requirement 9**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.products.schemas import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.modules.products.service import ProductService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    """Extract org_id from request state (set by auth middleware)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("", response_model=ProductListResponse, summary="List products")
async def list_products(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str | None = Query(None),
    category_id: UUID | None = Query(None),
    is_active: bool | None = Query(True),
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    products, total = await svc.list_products(
        org_id, page=page, page_size=page_size,
        search=search, category_id=category_id, is_active=is_active,
    )
    return ProductListResponse(
        products=[ProductResponse.model_validate(p) for p in products],
        total=total, page=page, page_size=page_size,
    )


@router.get(
    "/barcode/{barcode}",
    response_model=ProductResponse,
    summary="Lookup product by barcode",
)
async def lookup_barcode(
    barcode: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    product = await svc.lookup_by_barcode(org_id, barcode)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found for barcode")
    return ProductResponse.model_validate(product)


@router.post(
    "", response_model=ProductResponse, status_code=201, summary="Create product",
)
async def create_product(
    payload: ProductCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    product = await svc.create_product(org_id, payload)
    return ProductResponse.model_validate(product)


@router.get("/{product_id}", response_model=ProductResponse, summary="Get product")
async def get_product(
    product_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    product = await svc.get_product(org_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product)


@router.put("/{product_id}", response_model=ProductResponse, summary="Update product")
async def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    product = await svc.update_product(org_id, product_id, payload)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product)


@router.delete(
    "/{product_id}", response_model=ProductResponse, summary="Soft-delete product",
)
async def delete_product(
    product_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = ProductService(db)
    product = await svc.soft_delete_product(org_id, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product)


# ---------------------------------------------------------------------------
# CSV Import endpoints
# ---------------------------------------------------------------------------

from app.modules.products.csv_import import CSVImportService
from app.modules.products.schemas import CSVImportRequest, CSVImportPreview, CSVImportResult


@router.post(
    "/import",
    summary="CSV bulk import (preview or commit)",
)
async def import_products_csv(
    payload: CSVImportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = CSVImportService(db)

    # Apply field mapping
    mapped = svc.apply_field_mapping(payload.data, payload.field_mapping or None)

    if payload.preview_only:
        preview = svc.validate_rows(mapped)
        return preview
    else:
        # Validate first
        preview = svc.validate_rows(mapped)
        if preview.error_rows > 0:
            return preview
        result = await svc.import_products(org_id, mapped)
        return result


@router.get("/import/template", summary="Download sample CSV template")
async def get_import_template(
    trade: str | None = Query(None, description="Trade category slug"),
):
    from fastapi.responses import PlainTextResponse
    svc = CSVImportService(None)  # type: ignore[arg-type]
    csv_content = svc.get_sample_template(trade)
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=product_import_template.csv"},
    )
