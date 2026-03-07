"""Retention service: calculate, release, and summarise retention.

Business rules:
- calculate_retention(): computes retention_withheld as a percentage of
  work_completed_this_period, called during progress claim creation.
- release_retention(): creates a RetentionRelease record; the sum of all
  releases must never exceed total retention withheld across all claims.
- get_retention_summary(): returns total withheld, total released, balance,
  and individual release records for a project.

**Validates: Requirement — Retention Module**
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_claims.models import ProgressClaim
from app.modules.retentions.models import RetentionRelease
from app.modules.retentions.schemas import RetentionReleaseCreate


class RetentionService:
    """Service layer for construction retention tracking."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Calculation (pure, no DB)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_retention(
        work_completed_this_period: Decimal,
        retention_percentage: Decimal,
    ) -> Decimal:
        """Calculate retention withheld for a single claim period.

        Returns the retention amount = work_this_period * (pct / 100),
        rounded to 2 decimal places.
        """
        if retention_percentage <= 0:
            return Decimal("0")
        return (
            work_completed_this_period * retention_percentage / Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def _total_retention_withheld(self, project_id: uuid.UUID) -> Decimal:
        """Sum of retention_withheld across all claims for a project."""
        stmt = select(
            func.coalesce(func.sum(ProgressClaim.retention_withheld), Decimal("0"))
        ).where(ProgressClaim.project_id == project_id)
        result = await self.db.execute(stmt)
        return result.scalar() or Decimal("0")

    async def _total_retention_released(self, project_id: uuid.UUID) -> Decimal:
        """Sum of all retention release amounts for a project."""
        stmt = select(
            func.coalesce(func.sum(RetentionRelease.amount), Decimal("0"))
        ).where(RetentionRelease.project_id == project_id)
        result = await self.db.execute(stmt)
        return result.scalar() or Decimal("0")

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    async def release_retention(
        self,
        project_id: uuid.UUID,
        payload: RetentionReleaseCreate,
    ) -> RetentionRelease:
        """Create a retention release, enforcing the invariant that
        total released never exceeds total withheld."""
        total_withheld = await self._total_retention_withheld(project_id)
        total_released = await self._total_retention_released(project_id)
        remaining = total_withheld - total_released

        if payload.amount > remaining:
            raise ValueError(
                f"Release amount ({payload.amount}) exceeds remaining "
                f"retention balance ({remaining})"
            )

        release = RetentionRelease(
            project_id=project_id,
            amount=payload.amount,
            release_date=payload.release_date,
            payment_id=payload.payment_id,
            notes=payload.notes,
        )
        self.db.add(release)
        await self.db.flush()
        return release

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    async def get_retention_summary(
        self, project_id: uuid.UUID,
    ) -> dict:
        """Return retention summary for a project."""
        total_withheld = await self._total_retention_withheld(project_id)
        total_released = await self._total_retention_released(project_id)

        stmt = (
            select(RetentionRelease)
            .where(RetentionRelease.project_id == project_id)
            .order_by(RetentionRelease.release_date.desc())
        )
        result = await self.db.execute(stmt)
        releases = list(result.scalars().all())

        return {
            "project_id": project_id,
            "total_retention_withheld": total_withheld,
            "total_retention_released": total_released,
            "retention_balance": total_withheld - total_released,
            "releases": releases,
        }
