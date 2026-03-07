"""Supplier service: CRUD operations.

**Validates: Requirement 9.1**
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.suppliers.models import Supplier
from app.modules.suppliers.schemas import SupplierCreate, SupplierUpdate


class SupplierService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_suppliers(
        self, org_id: uuid.UUID, *, is_active: bool | None = True,
    ) -> list[Supplier]:
        stmt = select(Supplier).where(Supplier.org_id == org_id)
        if is_active is not None:
            stmt = stmt.where(Supplier.is_active == is_active)
        stmt = stmt.order_by(Supplier.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_supplier(
        self, org_id: uuid.UUID, supplier_id: uuid.UUID,
    ) -> Supplier | None:
        stmt = select(Supplier).where(
            and_(Supplier.id == supplier_id, Supplier.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_supplier(
        self, org_id: uuid.UUID, data: SupplierCreate,
    ) -> Supplier:
        supplier = Supplier(
            org_id=org_id,
            name=data.name,
            contact_name=data.contact_name,
            email=data.email,
            phone=data.phone,
            address=data.address,
            notes=data.notes,
        )
        self.db.add(supplier)
        await self.db.flush()
        return supplier

    async def update_supplier(
        self, org_id: uuid.UUID, supplier_id: uuid.UUID, data: SupplierUpdate,
    ) -> Supplier | None:
        supplier = await self.get_supplier(org_id, supplier_id)
        if supplier is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(supplier, field, value)
        await self.db.flush()
        return supplier

    async def delete_supplier(
        self, org_id: uuid.UUID, supplier_id: uuid.UUID,
    ) -> Supplier | None:
        """Soft-delete by setting is_active=False."""
        supplier = await self.get_supplier(org_id, supplier_id)
        if supplier is None:
            return None
        supplier.is_active = False
        await self.db.flush()
        return supplier
