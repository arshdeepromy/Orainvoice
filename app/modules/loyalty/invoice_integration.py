"""Loyalty integration with invoice payment and creation.

Provides helper functions to:
- Auto-award loyalty points when an invoice is paid
- Auto-apply tier discount as a line item on invoice creation

**Validates: Requirement 38 — Loyalty Module, Tasks 41.5, 41.6**
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.loyalty.service import LoyaltyService


async def award_points_on_payment(
    db: AsyncSession,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    invoice_total: Decimal,
    invoice_id: uuid.UUID,
) -> dict | None:
    """Award loyalty points when an invoice is paid.

    Called from the invoice payment flow. Returns a dict with the
    transaction details, or None if loyalty is inactive / zero points.
    """
    svc = LoyaltyService(db)
    txn = await svc.award_points(
        org_id=org_id,
        customer_id=customer_id,
        invoice_total=invoice_total,
        invoice_id=invoice_id,
    )
    if txn is None:
        return None
    return {
        "transaction_id": str(txn.id),
        "points_awarded": txn.points,
        "balance_after": txn.balance_after,
    }


async def apply_tier_discount_line(
    db: AsyncSession,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    invoice_subtotal: Decimal,
) -> dict | None:
    """Return a discount line item dict if the customer qualifies for a
    tier-based discount. Returns None otherwise.
    """
    svc = LoyaltyService(db)
    return await svc.auto_apply_tier_discount(
        org_id=org_id,
        customer_id=customer_id,
        invoice_subtotal=invoice_subtotal,
    )
