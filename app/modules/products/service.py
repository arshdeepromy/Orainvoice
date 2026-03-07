"""Product service: CRUD, barcode lookup, category tree, stock management.

**Validates: Requirement 9.1, 9.2, 9.10**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.products.models import Product, ProductCategory
from app.modules.products.schemas import (
    ProductCategoryCreate,
    ProductCategoryTreeNode,
    ProductCategoryUpdate,
    ProductCreate,
    ProductUpdate,
)


class ProductService:
    """Service layer for product catalogue and categories."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Products — CRUD
    # ------------------------------------------------------------------

    async def list_products(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = True,
    ) -> tuple[list[Product], int]:
        """List products with pagination and filtering."""
        stmt = select(Product).where(Product.org_id == org_id)

        if is_active is not None:
            stmt = stmt.where(Product.is_active == is_active)
        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                Product.name.ilike(pattern)
                | Product.sku.ilike(pattern)
                | Product.barcode.ilike(pattern)
            )

        # Total count
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        stmt = stmt.order_by(Product.name).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_product(
        self, org_id: uuid.UUID, data: ProductCreate,
    ) -> Product:
        """Create a new product."""
        product = Product(
            org_id=org_id,
            name=data.name,
            sku=data.sku,
            barcode=data.barcode,
            category_id=data.category_id,
            description=data.description,
            unit_of_measure=data.unit_of_measure,
            sale_price=data.sale_price,
            cost_price=data.cost_price,
            tax_applicable=data.tax_applicable,
            tax_rate_override=data.tax_rate_override,
            stock_quantity=data.stock_quantity,
            low_stock_threshold=data.low_stock_threshold,
            reorder_quantity=data.reorder_quantity,
            allow_backorder=data.allow_backorder,
            supplier_id=data.supplier_id,
            supplier_sku=data.supplier_sku,
            images=data.images,
            location_id=data.location_id,
        )
        self.db.add(product)
        await self.db.flush()
        return product

    async def get_product(
        self, org_id: uuid.UUID, product_id: uuid.UUID,
    ) -> Product | None:
        """Get a single product by ID."""
        stmt = select(Product).where(
            and_(Product.id == product_id, Product.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_product(
        self, org_id: uuid.UUID, product_id: uuid.UUID, data: ProductUpdate,
    ) -> Product | None:
        """Update a product."""
        product = await self.get_product(org_id, product_id)
        if product is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(product, field, value)
        await self.db.flush()
        return product

    async def soft_delete_product(
        self, org_id: uuid.UUID, product_id: uuid.UUID,
    ) -> Product | None:
        """Soft-delete a product by setting is_active=False."""
        product = await self.get_product(org_id, product_id)
        if product is None:
            return None
        product.is_active = False
        await self.db.flush()
        return product

    async def lookup_by_barcode(
        self, org_id: uuid.UUID, barcode: str,
    ) -> Product | None:
        """Look up a product by barcode."""
        stmt = select(Product).where(
            and_(
                Product.org_id == org_id,
                Product.barcode == barcode,
                Product.is_active.is_(True),
            ),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Stock quantity helpers (used by StockService)
    # ------------------------------------------------------------------

    async def adjust_stock_quantity(
        self, product: Product, quantity_change: Decimal,
    ) -> Decimal:
        """Adjust product stock_quantity and return the new value.

        Does NOT create a stock_movement — that is StockService's job.
        """
        product.stock_quantity = product.stock_quantity + quantity_change
        await self.db.flush()
        return product.stock_quantity

    def check_low_stock(self, product: Product) -> bool:
        """Return True if product is at or below low_stock_threshold."""
        threshold = product.low_stock_threshold or Decimal("0")
        return product.stock_quantity <= threshold

    def can_add_to_invoice(self, product: Product, quantity: Decimal) -> bool:
        """Check if product can be added to an invoice line item.

        Returns False if stock is zero/insufficient and backorder is disabled.
        """
        if product.allow_backorder:
            return True
        return product.stock_quantity >= quantity

    # ------------------------------------------------------------------
    # Categories — CRUD & tree
    # ------------------------------------------------------------------

    async def list_categories(
        self, org_id: uuid.UUID,
    ) -> list[ProductCategory]:
        """List all categories for an org."""
        stmt = (
            select(ProductCategory)
            .where(ProductCategory.org_id == org_id)
            .order_by(ProductCategory.display_order, ProductCategory.name)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_category(
        self, org_id: uuid.UUID, category_id: uuid.UUID,
    ) -> ProductCategory | None:
        stmt = select(ProductCategory).where(
            and_(ProductCategory.id == category_id, ProductCategory.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_category(
        self, org_id: uuid.UUID, data: ProductCategoryCreate,
    ) -> ProductCategory:
        category = ProductCategory(
            org_id=org_id,
            name=data.name,
            parent_id=data.parent_id,
            display_order=data.display_order,
        )
        self.db.add(category)
        await self.db.flush()
        return category

    async def update_category(
        self, org_id: uuid.UUID, category_id: uuid.UUID, data: ProductCategoryUpdate,
    ) -> ProductCategory | None:
        category = await self.get_category(org_id, category_id)
        if category is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(category, field, value)
        await self.db.flush()
        return category

    async def delete_category(
        self, org_id: uuid.UUID, category_id: uuid.UUID,
    ) -> bool:
        """Delete a category. Returns False if not found."""
        category = await self.get_category(org_id, category_id)
        if category is None:
            return False
        await self.db.delete(category)
        await self.db.flush()
        return True

    async def get_category_tree(
        self, org_id: uuid.UUID,
    ) -> list[ProductCategoryTreeNode]:
        """Build a nested tree of categories."""
        categories = await self.list_categories(org_id)
        return self._build_tree(categories)

    @staticmethod
    def _build_tree(
        categories: list[ProductCategory],
    ) -> list[ProductCategoryTreeNode]:
        """Build nested tree from flat list."""
        nodes: dict[uuid.UUID, ProductCategoryTreeNode] = {}
        for cat in categories:
            nodes[cat.id] = ProductCategoryTreeNode(
                id=cat.id,
                name=cat.name,
                parent_id=cat.parent_id,
                display_order=cat.display_order,
            )

        roots: list[ProductCategoryTreeNode] = []
        for node in nodes.values():
            if node.parent_id and node.parent_id in nodes:
                nodes[node.parent_id].children.append(node)
            else:
                roots.append(node)

        return sorted(roots, key=lambda n: n.display_order)
