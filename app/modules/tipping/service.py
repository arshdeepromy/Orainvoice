"""Tipping service: record tips, allocate to staff, generate summaries.

**Validates: Requirement 24 — Tipping Module**
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tipping.models import Tip, TipAllocation
from app.modules.tipping.schemas import (
    TipAllocateRequest,
    TipCreate,
    TipEvenSplitRequest,
)


class TippingService:
    """Service layer for tip management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_tip(self, org_id: uuid.UUID, payload: TipCreate) -> Tip:
        """Record a new tip against a POS transaction or invoice."""
        tip = Tip(
            org_id=org_id,
            invoice_id=payload.invoice_id,
            pos_transaction_id=payload.pos_transaction_id,
            amount=payload.amount,
            payment_method=payload.payment_method,
        )
        self.db.add(tip)
        await self.db.flush()
        return tip

    async def allocate_to_staff(
        self,
        org_id: uuid.UUID,
        tip_id: uuid.UUID,
        payload: TipAllocateRequest,
    ) -> Tip | None:
        """Allocate a tip to staff members with custom amounts.

        The sum of allocation amounts must equal the tip amount.
        """
        tip = await self._get_tip(org_id, tip_id)
        if tip is None:
            return None

        total_allocated = sum(a.amount for a in payload.allocations)
        if total_allocated != tip.amount:
            raise ValueError(
                f"Allocation total ({total_allocated}) must equal tip amount ({tip.amount})"
            )

        # Remove existing allocations
        for existing in list(tip.allocations):
            await self.db.delete(existing)

        for alloc in payload.allocations:
            tip_alloc = TipAllocation(
                tip_id=tip.id,
                staff_member_id=alloc.staff_member_id,
                amount=alloc.amount,
            )
            self.db.add(tip_alloc)

        await self.db.flush()
        await self.db.refresh(tip)
        return tip

    async def allocate_even_split(
        self,
        org_id: uuid.UUID,
        tip_id: uuid.UUID,
        payload: TipEvenSplitRequest,
    ) -> Tip | None:
        """Split a tip evenly across the given staff members."""
        tip = await self._get_tip(org_id, tip_id)
        if tip is None:
            return None

        count = len(payload.staff_member_ids)
        per_person = (tip.amount / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        # Adjust last person to absorb rounding difference
        remainder = tip.amount - (per_person * (count - 1))

        # Remove existing allocations
        for existing in list(tip.allocations):
            await self.db.delete(existing)

        for i, staff_id in enumerate(payload.staff_member_ids):
            amount = remainder if i == count - 1 else per_person
            tip_alloc = TipAllocation(
                tip_id=tip.id,
                staff_member_id=staff_id,
                amount=amount,
            )
            self.db.add(tip_alloc)

        await self.db.flush()
        await self.db.refresh(tip)
        return tip

    async def get_tip_summary(
        self,
        org_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        staff_id: uuid.UUID | None = None,
    ) -> dict:
        """Generate a tip summary report filterable by date range and staff.

        Returns dict with: total_tips, total_count, staff_summaries.
        """
        # Base filter
        filters = [Tip.org_id == org_id]
        if start_date:
            filters.append(Tip.created_at >= datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc))
        if end_date:
            end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
            filters.append(Tip.created_at <= end_dt)

        # Total tips
        total_stmt = select(
            func.coalesce(func.sum(Tip.amount), Decimal("0")),
            func.count(Tip.id),
        ).where(and_(*filters))
        result = await self.db.execute(total_stmt)
        row = result.one()
        total_tips = row[0]
        total_count = row[1]

        # Staff summaries via tip_allocations
        alloc_filters = [Tip.org_id == org_id]
        if start_date:
            alloc_filters.append(Tip.created_at >= datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc))
        if end_date:
            end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
            alloc_filters.append(Tip.created_at <= end_dt)
        if staff_id:
            alloc_filters.append(TipAllocation.staff_member_id == staff_id)

        staff_stmt = (
            select(
                TipAllocation.staff_member_id,
                func.coalesce(func.sum(TipAllocation.amount), Decimal("0")).label("total_tips"),
                func.count(TipAllocation.id).label("tip_count"),
            )
            .join(Tip, TipAllocation.tip_id == Tip.id)
            .where(and_(*alloc_filters))
            .group_by(TipAllocation.staff_member_id)
        )
        staff_result = await self.db.execute(staff_stmt)
        staff_summaries = []
        for srow in staff_result.all():
            avg = (srow.total_tips / srow.tip_count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if srow.tip_count > 0 else Decimal("0")
            staff_summaries.append({
                "staff_member_id": srow.staff_member_id,
                "total_tips": srow.total_tips,
                "tip_count": srow.tip_count,
                "average_tip": avg,
            })

        return {
            "total_tips": total_tips,
            "total_count": total_count,
            "staff_summaries": staff_summaries,
            "start_date": start_date,
            "end_date": end_date,
        }

    async def get_tip(self, org_id: uuid.UUID, tip_id: uuid.UUID) -> Tip | None:
        """Get a single tip by ID."""
        return await self._get_tip(org_id, tip_id)

    async def _get_tip(self, org_id: uuid.UUID, tip_id: uuid.UUID) -> Tip | None:
        stmt = select(Tip).where(and_(Tip.org_id == org_id, Tip.id == tip_id))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
