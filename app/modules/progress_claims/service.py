"""Progress claim service: create, approve, validate cumulative invariant.

Business rules:
- revised_contract_value = contract_value + variations_to_date
- work_completed_this_period = work_completed_to_date - work_completed_previous
- completion_percentage = (work_completed_to_date / revised_contract_value) * 100
- amount_due = work_completed_this_period + materials_on_site - retention_withheld
- Cumulative claimed (work_completed_to_date) must never exceed revised_contract_value

**Validates: Requirement — ProgressClaim Module**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress_claims.models import ProgressClaim
from app.modules.progress_claims.schemas import (
    ProgressClaimCreate,
    ProgressClaimUpdate,
)
from app.modules.projects.models import Project
from app.modules.retentions.service import RetentionService


class ProgressClaimService:
    """Service layer for construction progress claims."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Calculations
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_fields(
        contract_value: Decimal,
        variations_to_date: Decimal,
        work_completed_to_date: Decimal,
        work_completed_previous: Decimal,
        materials_on_site: Decimal,
        retention_withheld: Decimal,
    ) -> dict[str, Decimal]:
        """Compute derived fields from input values."""
        revised = contract_value + variations_to_date
        this_period = work_completed_to_date - work_completed_previous
        amount_due = this_period + materials_on_site - retention_withheld
        if revised > 0:
            pct = (work_completed_to_date / revised * 100).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
        else:
            pct = Decimal("0")
        return {
            "revised_contract_value": revised,
            "work_completed_this_period": this_period,
            "amount_due": amount_due,
            "completion_percentage": pct,
        }

    @staticmethod
    def validate_cumulative_not_exceeding_contract(
        work_completed_to_date: Decimal,
        revised_contract_value: Decimal,
    ) -> None:
        """Raise if cumulative claimed exceeds revised contract value."""
        if work_completed_to_date > revised_contract_value:
            raise ValueError(
                f"Cumulative work completed ({work_completed_to_date}) "
                f"exceeds revised contract value ({revised_contract_value})"
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_claims(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[ProgressClaim], int]:
        """List progress claims with pagination and filtering."""
        stmt = select(ProgressClaim).where(ProgressClaim.org_id == org_id)
        if project_id is not None:
            stmt = stmt.where(ProgressClaim.project_id == project_id)
        if status is not None:
            stmt = stmt.where(ProgressClaim.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(ProgressClaim.claim_number.desc()).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().all()), total

    async def _next_claim_number(self, org_id: uuid.UUID, project_id: uuid.UUID) -> int:
        """Get the next claim number for a project."""
        stmt = (
            select(func.coalesce(func.max(ProgressClaim.claim_number), 0))
            .where(
                and_(
                    ProgressClaim.org_id == org_id,
                    ProgressClaim.project_id == project_id,
                )
            )
        )
        result = (await self.db.execute(stmt)).scalar() or 0
        return result + 1

    async def create_claim(
        self,
        org_id: uuid.UUID,
        payload: ProgressClaimCreate,
    ) -> ProgressClaim:
        """Create a new progress claim with auto-calculated fields.

        If retention_withheld is not explicitly provided (defaults to 0),
        auto-calculate it from the project's retention_percentage.
        """
        # Auto-calculate retention from project config when not explicitly set
        retention_withheld = payload.retention_withheld
        if retention_withheld == Decimal("0"):
            stmt = select(Project.retention_percentage).where(
                and_(Project.id == payload.project_id, Project.org_id == org_id),
            )
            result = await self.db.execute(stmt)
            retention_pct = result.scalar()
            if retention_pct and retention_pct > 0:
                # Calculate this_period first to derive retention
                this_period = payload.work_completed_to_date - payload.work_completed_previous
                retention_withheld = RetentionService.calculate_retention(
                    this_period, retention_pct,
                )

        calc = self.calculate_fields(
            contract_value=payload.contract_value,
            variations_to_date=payload.variations_to_date,
            work_completed_to_date=payload.work_completed_to_date,
            work_completed_previous=payload.work_completed_previous,
            materials_on_site=payload.materials_on_site,
            retention_withheld=retention_withheld,
        )
        self.validate_cumulative_not_exceeding_contract(
            payload.work_completed_to_date, calc["revised_contract_value"],
        )
        claim_number = await self._next_claim_number(org_id, payload.project_id)
        claim = ProgressClaim(
            org_id=org_id,
            project_id=payload.project_id,
            claim_number=claim_number,
            contract_value=payload.contract_value,
            variations_to_date=payload.variations_to_date,
            revised_contract_value=calc["revised_contract_value"],
            work_completed_to_date=payload.work_completed_to_date,
            work_completed_previous=payload.work_completed_previous,
            work_completed_this_period=calc["work_completed_this_period"],
            materials_on_site=payload.materials_on_site,
            retention_withheld=retention_withheld,
            amount_due=calc["amount_due"],
            completion_percentage=calc["completion_percentage"],
        )
        self.db.add(claim)
        await self.db.flush()
        return claim

    async def get_claim(
        self, org_id: uuid.UUID, claim_id: uuid.UUID,
    ) -> ProgressClaim | None:
        """Get a single progress claim by ID."""
        stmt = select(ProgressClaim).where(
            and_(ProgressClaim.org_id == org_id, ProgressClaim.id == claim_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_claim(
        self,
        org_id: uuid.UUID,
        claim_id: uuid.UUID,
        payload: ProgressClaimUpdate,
    ) -> ProgressClaim | None:
        """Update a draft progress claim and recalculate derived fields."""
        claim = await self.get_claim(org_id, claim_id)
        if claim is None:
            return None
        if claim.status != "draft":
            raise ValueError("Only draft claims can be updated")

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(claim, field, value)

        # Recalculate derived fields
        calc = self.calculate_fields(
            contract_value=claim.contract_value,
            variations_to_date=claim.variations_to_date,
            work_completed_to_date=claim.work_completed_to_date,
            work_completed_previous=claim.work_completed_previous,
            materials_on_site=claim.materials_on_site,
            retention_withheld=claim.retention_withheld,
        )
        self.validate_cumulative_not_exceeding_contract(
            claim.work_completed_to_date, calc["revised_contract_value"],
        )
        claim.revised_contract_value = calc["revised_contract_value"]
        claim.work_completed_this_period = calc["work_completed_this_period"]
        claim.amount_due = calc["amount_due"]
        claim.completion_percentage = calc["completion_percentage"]
        await self.db.flush()
        return claim

    async def approve_claim(
        self, org_id: uuid.UUID, claim_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Approve a submitted claim and generate an invoice reference."""
        claim = await self.get_claim(org_id, claim_id)
        if claim is None:
            raise ValueError("Claim not found")
        if claim.status not in ("draft", "submitted"):
            raise ValueError(f"Cannot approve a claim with status '{claim.status}'")

        now = datetime.now(timezone.utc)
        claim.status = "approved"
        claim.approved_at = now

        # Generate an invoice ID reference (actual invoice creation
        # would be handled by the invoice module in production)
        invoice_id = uuid.uuid4()
        claim.invoice_id = invoice_id

        await self.db.flush()
        return {
            "claim_id": claim.id,
            "invoice_id": invoice_id,
            "amount_due": claim.amount_due,
            "status": claim.status,
        }
