"""Supplier API router.

Endpoints:
- GET    /api/v2/suppliers          — list
- POST   /api/v2/suppliers          — create
- GET    /api/v2/suppliers/{id}     — get
- PUT    /api/v2/suppliers/{id}     — update
- DELETE /api/v2/suppliers/{id}     — soft-delete

**Validates: Requirement 9.1**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.suppliers.schemas import (
    SupplierCreate,
    SupplierListResponse,
    SupplierResponse,
    SupplierUpdate,
)
from app.modules.suppliers.service import SupplierService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


@router.get("", response_model=SupplierListResponse, summary="List suppliers")
async def list_suppliers(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SupplierService(db)
    suppliers = await svc.list_suppliers(org_id)
    return SupplierListResponse(
        suppliers=[SupplierResponse.model_validate(s) for s in suppliers],
        total=len(suppliers),
    )


@router.post(
    "", response_model=SupplierResponse, status_code=201, summary="Create supplier",
)
async def create_supplier(
    payload: SupplierCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SupplierService(db)
    supplier = await svc.create_supplier(org_id, payload)
    return SupplierResponse.model_validate(supplier)


@router.get("/{supplier_id}", response_model=SupplierResponse, summary="Get supplier")
async def get_supplier(
    supplier_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SupplierService(db)
    supplier = await svc.get_supplier(org_id, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return SupplierResponse.model_validate(supplier)


@router.put(
    "/{supplier_id}", response_model=SupplierResponse, summary="Update supplier",
)
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SupplierService(db)
    supplier = await svc.update_supplier(org_id, supplier_id, payload)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return SupplierResponse.model_validate(supplier)


@router.delete(
    "/{supplier_id}", response_model=SupplierResponse, summary="Soft-delete supplier",
)
async def delete_supplier(
    supplier_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = SupplierService(db)
    supplier = await svc.delete_supplier(org_id, supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return SupplierResponse.model_validate(supplier)
