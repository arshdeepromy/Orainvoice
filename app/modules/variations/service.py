"""Variation order service: CRUD, approve, register.

Business rules:
- revised_contract_value = original contract_value + SUM(approved variation cost_impacts)
- Approved variations cannot be deleted — must create an offsetting variation
- cost_impact can be positive (addition) or negative (deduction)
- Variation register shows all variations for a project with running total

**Validates: Requirement 29 — Variation Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.variations.models import VariationOrder
from app.modules.variations.schemas import (
    VariationOrderCreate,
    VariationOrderUpdate,
)


class VariationService:
    """Service layer for construction variation orders."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _next_variation_number(self, org_id: uuid.UUID, project_id: uuid.UUID) -> int:
        stmt = (
            select(func.coalesce(func.max(VariationOrder.variation_number), 0))
            .where(
                and_(
                    VariationOrder.org_id == org_id,
                    VariationOrder.project_id == project_id,
                )
            )
        )
        result = (await self.db.execute(stmt)).scalar() or 0
        return result + 1

    async def _sum_approved_cost_impacts(self, org_id: uuid.UUID, project_id: uuid.UUID) -> Decimal:
        """Sum cost_impact of all approved variations for a project."""
        stmt = (
            select(func.coalesce(func.sum(VariationOrder.cost_impact), Decimal("0")))
            .where(
                and_(
                    VariationOrder.org_id == org_id,
                    VariationOrder.project_id == project_id,
                    VariationOrder.status == "approved",
                )
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar() or Decimal("0")

    async def _update_project_revised_value(self, org_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """Recalculate and update the project's revised_contract_value."""
        stmt = select(Project).where(
            and_(Project.org_id == org_id, Project.id == project_id),
        )
        result = await self.db.execute(stmt)
        project = result.scalar_one_or_none()
        if project is None:
            return
        approved_sum = await self._sum_approved_cost_impacts(org_id, project_id)
        original = project.contract_value or Decimal("0")
        project.revised_contract_value = original + approved_sum

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_variations(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[VariationOrder], int]:
        stmt = select(VariationOrder).where(VariationOrder.org_id == org_id)
        if project_id is not None:
            stmt = stmt.where(VariationOrder.project_id == project_id)
        if status is not None:
            stmt = stmt.where(VariationOrder.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(VariationOrder.variation_number.asc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def create_variation(
        self,
        org_id: uuid.UUID,
        payload: VariationOrderCreate,
    ) -> VariationOrder:
        variation_number = await self._next_variation_number(org_id, payload.project_id)
        variation = VariationOrder(
            org_id=org_id,
            project_id=payload.project_id,
            variation_number=variation_number,
            description=payload.description,
            cost_impact=payload.cost_impact,
        )
        self.db.add(variation)
        await self.db.flush()
        return variation

    async def get_variation(
        self, org_id: uuid.UUID, variation_id: uuid.UUID,
    ) -> VariationOrder | None:
        stmt = select(VariationOrder).where(
            and_(VariationOrder.org_id == org_id, VariationOrder.id == variation_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_variation(
        self,
        org_id: uuid.UUID,
        variation_id: uuid.UUID,
        payload: VariationOrderUpdate,
    ) -> VariationOrder | None:
        variation = await self.get_variation(org_id, variation_id)
        if variation is None:
            return None
        if variation.status != "draft":
            raise ValueError("Only draft variations can be updated")
        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(variation, field, value)
        await self.db.flush()
        return variation

    async def delete_variation(
        self, org_id: uuid.UUID, variation_id: uuid.UUID,
    ) -> None:
        """Delete a variation. Approved variations cannot be deleted."""
        variation = await self.get_variation(org_id, variation_id)
        if variation is None:
            raise ValueError("Variation not found")
        if variation.status == "approved":
            raise ValueError(
                "Approved variations cannot be deleted. "
                "Create an offsetting variation to reverse the change."
            )
        await self.db.delete(variation)
        await self.db.flush()

    async def approve_variation(
        self, org_id: uuid.UUID, variation_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Approve a variation and update the project's revised_contract_value."""
        variation = await self.get_variation(org_id, variation_id)
        if variation is None:
            raise ValueError("Variation not found")
        if variation.status not in ("draft", "submitted"):
            raise ValueError(f"Cannot approve a variation with status '{variation.status}'")

        now = datetime.now(timezone.utc)
        variation.status = "approved"
        variation.approved_at = now
        await self.db.flush()

        # Update the project's revised_contract_value
        await self._update_project_revised_value(org_id, variation.project_id)

        return {
            "variation_id": variation.id,
            "cost_impact": variation.cost_impact,
            "status": variation.status,
        }

    # ------------------------------------------------------------------
    # Variation Register
    # ------------------------------------------------------------------

    async def get_variation_register(
        self, org_id: uuid.UUID, project_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Return all variations for a project with running total."""
        stmt = (
            select(VariationOrder)
            .where(
                and_(
                    VariationOrder.org_id == org_id,
                    VariationOrder.project_id == project_id,
                )
            )
            .order_by(VariationOrder.variation_number.asc())
        )
        result = await self.db.execute(stmt)
        variations = list(result.scalars().all())

        running_total = Decimal("0")
        register: list[dict[str, Any]] = []
        for v in variations:
            if v.status == "approved":
                running_total += v.cost_impact
            register.append({
                "variation_number": v.variation_number,
                "description": v.description,
                "cost_impact": v.cost_impact,
                "status": v.status,
                "running_total": running_total,
                "submitted_at": v.submitted_at,
                "approved_at": v.approved_at,
            })

        return {
            "project_id": project_id,
            "variations": register,
            "total_approved_impact": running_total,
            "count": len(variations),
        }
