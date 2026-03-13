"""Loyalty and memberships service layer.

Provides:
- configure()            — create / update loyalty config for an org
- award_points()         — called on invoice payment
- redeem_points()        — deduct points from a customer balance
- get_customer_balance() — current points, tier, next-tier info
- auto_apply_tier_discount() — returns discount line item for eligible customer
- check_tier_upgrade()   — determine if customer qualifies for a higher tier

**Validates: Requirement 38 — Loyalty Module**
"""

from __future__ import annotations

import math
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.loyalty.models import (
    LoyaltyConfig,
    LoyaltyTier,
    LoyaltyTransaction,
)


class LoyaltyService:
    """Encapsulates all loyalty programme business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    async def get_config(self, org_id: uuid.UUID) -> LoyaltyConfig | None:
        result = await self.db.execute(
            select(LoyaltyConfig).where(LoyaltyConfig.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def configure(
        self,
        org_id: uuid.UUID,
        *,
        earn_rate: Decimal = Decimal("1.0"),
        redemption_rate: Decimal = Decimal("0.01"),
        is_active: bool = True,
    ) -> LoyaltyConfig:
        """Create or update the loyalty configuration for an organisation."""
        config = await self.get_config(org_id)
        if config is None:
            config = LoyaltyConfig(
                org_id=org_id,
                earn_rate=earn_rate,
                redemption_rate=redemption_rate,
                is_active=is_active,
            )
            self.db.add(config)
        else:
            config.earn_rate = earn_rate
            config.redemption_rate = redemption_rate
            config.is_active = is_active
        await self.db.flush()
        return config

    # ------------------------------------------------------------------
    # Tiers
    # ------------------------------------------------------------------

    async def list_tiers(self, org_id: uuid.UUID) -> list[LoyaltyTier]:
        result = await self.db.execute(
            select(LoyaltyTier)
            .where(LoyaltyTier.org_id == org_id)
            .order_by(LoyaltyTier.display_order, LoyaltyTier.threshold_points)
        )
        return list(result.scalars().all())

    async def create_tier(
        self,
        org_id: uuid.UUID,
        *,
        name: str,
        threshold_points: int,
        discount_percent: Decimal = Decimal("0"),
        benefits: dict | None = None,
        display_order: int = 0,
    ) -> LoyaltyTier:
        tier = LoyaltyTier(
            org_id=org_id,
            name=name,
            threshold_points=threshold_points,
            discount_percent=discount_percent,
            benefits=benefits or {},
            display_order=display_order,
        )
        self.db.add(tier)
        await self.db.flush()
        return tier

    # ------------------------------------------------------------------
    # Balance & transactions
    # ------------------------------------------------------------------

    async def get_customer_balance(
        self, org_id: uuid.UUID, customer_id: uuid.UUID,
    ) -> int:
        """Return the current loyalty points balance for a customer.

        The balance is the sum of all transaction points (positive for earn,
        negative for redeem).
        """
        result = await self.db.execute(
            select(func.coalesce(func.sum(LoyaltyTransaction.points), 0)).where(
                LoyaltyTransaction.org_id == org_id,
                LoyaltyTransaction.customer_id == customer_id,
            )
        )
        return int(result.scalar_one())

    async def get_customer_transactions(
        self, org_id: uuid.UUID, customer_id: uuid.UUID,
    ) -> list[LoyaltyTransaction]:
        result = await self.db.execute(
            select(LoyaltyTransaction)
            .where(
                LoyaltyTransaction.org_id == org_id,
                LoyaltyTransaction.customer_id == customer_id,
            )
            .order_by(LoyaltyTransaction.created_at.desc())
        )
        return list(result.scalars().all())

    async def _record_transaction(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        transaction_type: str,
        points: int,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
    ) -> LoyaltyTransaction:
        """Internal helper to record a loyalty transaction."""
        current_balance = await self.get_customer_balance(org_id, customer_id)
        new_balance = current_balance + points
        txn = LoyaltyTransaction(
            org_id=org_id,
            customer_id=customer_id,
            transaction_type=transaction_type,
            points=points,
            balance_after=new_balance,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        self.db.add(txn)
        await self.db.flush()
        return txn

    # ------------------------------------------------------------------
    # Award points (called on invoice payment)
    # ------------------------------------------------------------------

    async def award_points(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_total: Decimal,
        invoice_id: uuid.UUID | None = None,
        *,
        txn: Any | None = None,
    ) -> LoyaltyTransaction | None:
        """Award loyalty points based on the invoice total and earn rate.

        Points = floor(invoice_total * earn_rate).
        Returns None if the programme is inactive or points would be zero.
        """
        config = await self.get_config(org_id)
        if config is None or not config.is_active:
            return None

        points = int(
            (invoice_total * config.earn_rate).to_integral_value(rounding=ROUND_DOWN)
        )
        if points <= 0:
            return None

        return await self._record_transaction(
            org_id=org_id,
            customer_id=customer_id,
            transaction_type="earn",
            points=points,
            reference_type="invoice" if invoice_id else None,
            reference_id=invoice_id,
        )

    # ------------------------------------------------------------------
    # Redeem points
    # ------------------------------------------------------------------

    async def redeem_points(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        points: int,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
    ) -> LoyaltyTransaction:
        """Redeem loyalty points. Raises ValueError if insufficient balance."""
        if points <= 0:
            raise ValueError("Points to redeem must be positive")

        balance = await self.get_customer_balance(org_id, customer_id)
        if balance < points:
            raise ValueError(
                f"Insufficient loyalty points: balance={balance}, requested={points}"
            )

        return await self._record_transaction(
            org_id=org_id,
            customer_id=customer_id,
            transaction_type="redeem",
            points=-points,
            reference_type=reference_type,
            reference_id=reference_id,
        )

    # ------------------------------------------------------------------
    # Tier logic
    # ------------------------------------------------------------------

    async def check_tier_upgrade(
        self, org_id: uuid.UUID, customer_id: uuid.UUID,
    ) -> LoyaltyTier | None:
        """Return the highest tier the customer qualifies for, or None."""
        balance = await self.get_customer_balance(org_id, customer_id)
        tiers = await self.list_tiers(org_id)
        if not tiers:
            return None

        # Sort descending by threshold so we find the highest qualifying tier
        sorted_tiers = sorted(tiers, key=lambda t: t.threshold_points, reverse=True)
        for tier in sorted_tiers:
            if balance >= tier.threshold_points:
                return tier
        return None

    async def get_next_tier(
        self, org_id: uuid.UUID, current_balance: int,
    ) -> LoyaltyTier | None:
        """Return the next tier above the customer's current balance."""
        tiers = await self.list_tiers(org_id)
        sorted_tiers = sorted(tiers, key=lambda t: t.threshold_points)
        for tier in sorted_tiers:
            if tier.threshold_points > current_balance:
                return tier
        return None

    async def auto_apply_tier_discount(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_subtotal: Decimal,
    ) -> dict | None:
        """If the customer qualifies for a tier with a discount, return a
        discount line item dict suitable for adding to an invoice.

        Returns None if no tier discount applies.
        """
        tier = await self.check_tier_upgrade(org_id, customer_id)
        if tier is None or tier.discount_percent <= 0:
            return None

        discount_amount = (
            invoice_subtotal * tier.discount_percent / Decimal("100")
        ).quantize(Decimal("0.01"))

        if discount_amount <= 0:
            return None

        return {
            "description": f"{tier.name} Loyalty Discount",
            "quantity": 1,
            "unit_price": -discount_amount,
            "total": -discount_amount,
            "tier_id": str(tier.id),
            "tier_name": tier.name,
        }

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    async def get_analytics(self, org_id: uuid.UUID) -> dict:
        """Return loyalty programme analytics for the organisation."""
        from app.modules.loyalty.schemas import LoyaltyAnalyticsResponse

        # Total distinct customers with transactions
        active_result = await self.db.execute(
            select(func.count(func.distinct(LoyaltyTransaction.customer_id))).where(
                LoyaltyTransaction.org_id == org_id,
            )
        )
        total_active = int(active_result.scalar_one())

        # Total points issued (earn transactions)
        issued_result = await self.db.execute(
            select(func.coalesce(func.sum(LoyaltyTransaction.points), 0)).where(
                LoyaltyTransaction.org_id == org_id,
                LoyaltyTransaction.transaction_type == "earn",
            )
        )
        total_issued = int(issued_result.scalar_one())

        # Total points redeemed (redeem transactions — stored as negative)
        redeemed_result = await self.db.execute(
            select(func.coalesce(-func.sum(LoyaltyTransaction.points), 0)).where(
                LoyaltyTransaction.org_id == org_id,
                LoyaltyTransaction.transaction_type == "redeem",
            )
        )
        total_redeemed = int(redeemed_result.scalar_one())

        redemption_pct = (total_redeemed / total_issued * 100) if total_issued > 0 else 0.0

        return LoyaltyAnalyticsResponse(
            total_active_members=total_active,
            members_per_tier=[],
            total_points_issued=total_issued,
            total_points_redeemed=total_redeemed,
            redemption_rate_pct=round(redemption_pct, 1),
            top_customers=[],
        )

