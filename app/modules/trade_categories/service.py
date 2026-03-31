"""Trade category registry service.

Implements CRUD for trade families and categories, filtering,
retirement logic, and seed data export/import.

**Validates: Requirement 3.1–3.8**
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.trade_categories.models import TradeCategory, TradeFamily
from app.modules.trade_categories.schemas import (
    DefaultProductItem,
    DefaultServiceItem,
    SeedDataExport,
    TradeCategoryCreate,
    TradeCategoryResponse,
    TradeCategoryUpdate,
    TradeFamilyCreate,
    TradeFamilyResponse,
    TradeFamilyUpdate,
)


class TradeCategoryService:
    """Service layer for the Trade Category Registry."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Trade Families
    # ------------------------------------------------------------------

    async def list_families(
        self,
        *,
        include_inactive: bool = False,
        country_code: str | None = None,
    ) -> list[TradeFamily]:
        """Return trade families ordered by display_order.
        
        Args:
            include_inactive: If True, include inactive families
            country_code: If provided, filter to families available in this country
        """
        stmt = select(TradeFamily).order_by(TradeFamily.display_order)
        
        if not include_inactive:
            stmt = stmt.where(TradeFamily.is_active.is_(True))

        result = await self.db.execute(stmt)
        families = list(result.scalars().all())
        
        # Filter by country if specified
        if country_code:
            filtered = []
            for f in families:
                codes = f.country_codes or []
                # Empty list means available to all countries
                if not codes or country_code in codes:
                    filtered.append(f)
            return filtered
        
        return families

    async def list_all_families(self) -> list[TradeFamily]:
        """Return ALL trade families (including inactive) for admin view."""
        stmt = select(TradeFamily).order_by(TradeFamily.display_order)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_family(self, data: TradeFamilyCreate) -> TradeFamily:
        """Create a new trade family."""
        family = TradeFamily(
            slug=data.slug,
            display_name=data.display_name,
            icon=data.icon,
            display_order=data.display_order,
            country_codes=data.country_codes,
            gated_features=data.gated_features,
        )
        self.db.add(family)
        await self.db.flush()
        return family

    async def update_family(
        self, slug: str, data: TradeFamilyUpdate,
    ) -> TradeFamily | None:
        """Update a trade family."""
        family = await self._get_family_by_slug(slug)
        if family is None:
            return None

        update_fields = data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            setattr(family, field, value)

        await self.db.flush()
        return family

    async def get_family(self, slug: str) -> TradeFamily | None:
        """Get a single trade family by slug."""
        return await self._get_family_by_slug(slug)

    # ------------------------------------------------------------------
    # Trade Categories
    # ------------------------------------------------------------------

    async def list_categories(
        self,
        *,
        family_slug: str | None = None,
        include_retired: bool = False,
    ) -> list[TradeCategory]:
        """Return trade categories, optionally filtered by family slug."""
        stmt = select(TradeCategory).where(TradeCategory.is_active.is_(True))

        if not include_retired:
            stmt = stmt.where(TradeCategory.is_retired.is_(False))

        if family_slug:
            stmt = stmt.join(TradeFamily).where(TradeFamily.slug == family_slug)

        stmt = stmt.order_by(TradeCategory.display_name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_category(self, slug: str) -> TradeCategory | None:
        """Get a single trade category by slug, including seed data."""
        stmt = select(TradeCategory).where(TradeCategory.slug == slug)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_category(self, data: TradeCategoryCreate) -> TradeCategory:
        """Create a new trade category.

        Validates:
        - Slug is unique
        - Family exists
        - At least one default service is defined (Req 3.2)
        """
        # Validate unique slug
        existing = await self.get_category(data.slug)
        if existing is not None:
            raise ValueError(f"Trade category slug '{data.slug}' already exists")

        # Validate family exists
        family = await self._get_family_by_id(data.family_id)
        if family is None:
            raise ValueError(f"Trade family '{data.family_id}' does not exist")

        # Validate at least one default service
        if not data.default_services:
            raise ValueError("At least one default service is required")

        category = TradeCategory(
            slug=data.slug,
            display_name=data.display_name,
            family_id=data.family_id,
            icon=data.icon,
            description=data.description,
            invoice_template_layout=data.invoice_template_layout,
            recommended_modules=data.recommended_modules,
            terminology_overrides=data.terminology_overrides,
            default_services=[s.model_dump() for s in data.default_services],
            default_products=[p.model_dump() for p in data.default_products],
            default_expense_categories=data.default_expense_categories,
            default_job_templates=data.default_job_templates,
            compliance_notes=data.compliance_notes,
        )
        self.db.add(category)
        await self.db.flush()
        return category

    async def update_category(
        self, slug: str, data: TradeCategoryUpdate,
    ) -> TradeCategory | None:
        """Update a trade category.

        Changes to defaults only affect new orgs (Req 3.5).
        The service simply persists the new defaults; existing orgs
        are not retroactively modified because they snapshot seed data
        during the setup wizard.
        """
        category = await self.get_category(slug)
        if category is None:
            return None

        update_fields = data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            if field == "default_services" and value is not None:
                value = [
                    s.model_dump() if isinstance(s, DefaultServiceItem) else s
                    for s in value
                ]
            elif field == "default_products" and value is not None:
                value = [
                    p.model_dump() if isinstance(p, DefaultProductItem) else p
                    for p in value
                ]
            setattr(category, field, value)

        await self.db.flush()
        return category

    async def retire_category(self, slug: str) -> TradeCategory | None:
        """Retire a trade category.

        Sets is_retired=True. Existing orgs using this category
        continue unchanged (Req 3.3).
        """
        category = await self.get_category(slug)
        if category is None:
            return None
        category.is_retired = True
        await self.db.flush()
        return category

    # ------------------------------------------------------------------
    # Seed data export / import (Req 3.6)
    # ------------------------------------------------------------------

    async def export_seed_data(self) -> dict:
        """Export all families and categories as JSON-serialisable dict."""
        families = await self.list_families()
        categories_stmt = select(TradeCategory).order_by(TradeCategory.display_name)
        result = await self.db.execute(categories_stmt)
        categories = list(result.scalars().all())

        return SeedDataExport(
            families=[TradeFamilyResponse.model_validate(f) for f in families],
            categories=[TradeCategoryResponse.model_validate(c) for c in categories],
        ).model_dump(mode="json")

    async def import_seed_data(self, data: dict) -> dict[str, int]:
        """Import seed data from a JSON dict.

        Returns counts of created/updated families and categories.
        """
        export = SeedDataExport.model_validate(data)
        counts: dict[str, int] = {"families_created": 0, "categories_created": 0}

        for fam_data in export.families:
            existing = await self._get_family_by_slug(fam_data.slug)
            if existing is None:
                family = TradeFamily(
                    slug=fam_data.slug,
                    display_name=fam_data.display_name,
                    icon=fam_data.icon,
                    display_order=fam_data.display_order,
                )
                self.db.add(family)
                counts["families_created"] += 1

        await self.db.flush()

        for cat_data in export.categories:
            existing = await self.get_category(cat_data.slug)
            if existing is None:
                family = await self._get_family_by_id(cat_data.family_id)
                if family is None:
                    continue
                category = TradeCategory(
                    slug=cat_data.slug,
                    display_name=cat_data.display_name,
                    family_id=cat_data.family_id,
                    icon=cat_data.icon,
                    description=cat_data.description,
                    invoice_template_layout=cat_data.invoice_template_layout,
                    recommended_modules=cat_data.recommended_modules,
                    terminology_overrides=cat_data.terminology_overrides,
                    default_services=[s.model_dump() for s in cat_data.default_services],
                    default_products=[p.model_dump() for p in cat_data.default_products],
                    default_expense_categories=cat_data.default_expense_categories,
                    default_job_templates=cat_data.default_job_templates,
                    compliance_notes=cat_data.compliance_notes,
                    seed_data_version=cat_data.seed_data_version,
                )
                self.db.add(category)
                counts["categories_created"] += 1

        await self.db.flush()
        return counts

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_family_by_id(self, family_id: uuid.UUID) -> TradeFamily | None:
        stmt = select(TradeFamily).where(TradeFamily.id == family_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_family_by_slug(self, slug: str) -> TradeFamily | None:
        stmt = select(TradeFamily).where(TradeFamily.slug == slug)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
