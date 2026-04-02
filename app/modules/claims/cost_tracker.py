"""Cost Tracker for Customer Claims & Returns.

Calculates and updates cost_to_business for claims including:
- labour_cost: from warranty job time entries (hours × hourly_rate)
- parts_cost: from warranty job parts (quantity × cost_price/unit_price)
- write_off_cost: from flagged stock returns

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.claims.models import ClaimAction, CustomerClaim
from app.modules.job_cards.models import JobCard, JobCardItem
from app.modules.time_tracking_v2.models import TimeEntry


@dataclass
class CostBreakdown:
    """Cost breakdown for a claim.

    Requirements: 5.1
    """

    labour_cost: Decimal = Decimal("0")
    parts_cost: Decimal = Decimal("0")
    write_off_cost: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        return self.labour_cost + self.parts_cost + self.write_off_cost


class CostTracker:
    """Calculates and updates cost_to_business for claims."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def calculate_claim_cost(
        self,
        *,
        claim_id: uuid.UUID,
    ) -> CostBreakdown:
        """Calculate total cost breakdown for a claim.

        - labour_cost: sum of (duration_minutes/60 × hourly_rate) from warranty job time entries
        - parts_cost: sum of (quantity × unit_price) for parts used in warranty job
        - write_off_cost: from the claim's existing cost_breakdown (set during resolution)

        Requirements: 5.1, 5.2, 5.3, 5.4
        """
        result = await self.db.execute(
            select(CustomerClaim).where(CustomerClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()
        if claim is None:
            raise ValueError("Claim not found")

        labour_cost = Decimal("0")
        parts_cost = Decimal("0")

        # Calculate labour and parts costs from warranty job
        if claim.warranty_job_id is not None:
            labour_cost = await self._calculate_job_labour_cost(claim.warranty_job_id)
            parts_cost = await self._calculate_job_parts_cost(claim.warranty_job_id)

        # Write-off cost comes from the existing breakdown (set during resolution)
        raw_breakdown = claim.cost_breakdown or {}
        write_off_cost = Decimal(str(raw_breakdown.get("write_off_cost", 0)))

        return CostBreakdown(
            labour_cost=labour_cost,
            parts_cost=parts_cost,
            write_off_cost=write_off_cost,
        )

    async def update_claim_cost(
        self,
        *,
        claim_id: uuid.UUID,
        labour_cost: Decimal | None = None,
        parts_cost: Decimal | None = None,
        write_off_cost: Decimal | None = None,
        user_id: uuid.UUID | None = None,
    ) -> None:
        """Update claim cost_breakdown and cost_to_business.

        Requirements: 5.5, 5.6
        """
        result = await self.db.execute(
            select(CustomerClaim).where(CustomerClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()
        if claim is None:
            raise ValueError("Claim not found")

        # Build updated breakdown
        breakdown = dict(claim.cost_breakdown) if claim.cost_breakdown else {
            "labour_cost": 0, "parts_cost": 0, "write_off_cost": 0,
        }

        if labour_cost is not None:
            breakdown["labour_cost"] = float(labour_cost)
        if parts_cost is not None:
            breakdown["parts_cost"] = float(parts_cost)
        if write_off_cost is not None:
            breakdown["write_off_cost"] = float(write_off_cost)

        # Update claim fields
        claim.cost_breakdown = breakdown
        claim.cost_to_business = (
            Decimal(str(breakdown["labour_cost"]))
            + Decimal(str(breakdown["parts_cost"]))
            + Decimal(str(breakdown["write_off_cost"]))
        )
        claim.updated_at = datetime.now(timezone.utc)

        # Create ClaimAction record for cost update
        if user_id is not None:
            action = ClaimAction(
                org_id=claim.org_id,
                claim_id=claim.id,
                action_type="cost_updated",
                from_status=claim.status,
                to_status=claim.status,
                action_data={
                    "labour_cost": float(breakdown["labour_cost"]),
                    "parts_cost": float(breakdown["parts_cost"]),
                    "write_off_cost": float(breakdown["write_off_cost"]),
                    "cost_to_business": float(claim.cost_to_business),
                },
                notes="Cost breakdown updated",
                performed_by=user_id,
                performed_at=datetime.now(timezone.utc),
            )
            self.db.add(action)

        await self.db.flush()

    async def _calculate_job_labour_cost(self, job_card_id: uuid.UUID) -> Decimal:
        """Sum of (duration_minutes/60 × hourly_rate) from time entries linked to the job.

        Requirements: 5.2
        """
        result = await self.db.execute(
            select(TimeEntry).where(TimeEntry.job_id == job_card_id)
        )
        entries = result.scalars().all()

        total = Decimal("0")
        for entry in entries:
            if entry.duration_minutes and entry.hourly_rate:
                hours = Decimal(str(entry.duration_minutes)) / Decimal("60")
                total += hours * entry.hourly_rate
        return total

    async def _calculate_job_parts_cost(self, job_card_id: uuid.UUID) -> Decimal:
        """Sum of (quantity × unit_price) for parts used in the warranty job.

        Requirements: 5.3
        """
        result = await self.db.execute(
            select(JobCardItem).where(
                JobCardItem.job_card_id == job_card_id,
                JobCardItem.item_type == "part",
            )
        )
        items = result.scalars().all()

        total = Decimal("0")
        for item in items:
            total += item.quantity * item.unit_price
        return total


# ---------------------------------------------------------------------------
# Hook: update_claim_cost_on_job_completion (Task 6.3)
# Requirements: 5.2, 5.3, 5.6
# ---------------------------------------------------------------------------


async def update_claim_cost_on_job_completion(
    db: AsyncSession,
    job_card_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> None:
    """Called when a warranty job card is completed.

    Finds the claim linked to this warranty job, calculates labour and parts
    costs, and updates the claim's cost breakdown.

    Requirements: 5.2, 5.3, 5.6
    """
    # Find claim linked to this warranty job
    result = await db.execute(
        select(CustomerClaim).where(
            CustomerClaim.warranty_job_id == job_card_id
        )
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        return  # No claim linked to this job — nothing to do

    tracker = CostTracker(db)

    # Calculate labour and parts costs from the job
    labour_cost = await tracker._calculate_job_labour_cost(job_card_id)
    parts_cost = await tracker._calculate_job_parts_cost(job_card_id)

    # Update claim cost breakdown
    await tracker.update_claim_cost(
        claim_id=claim.id,
        labour_cost=labour_cost,
        parts_cost=parts_cost,
        user_id=user_id or claim.created_by,
    )
