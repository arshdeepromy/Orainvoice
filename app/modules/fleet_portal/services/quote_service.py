"""Quotation request lifecycle.

Implements: B2B Fleet Portal task 12.2 — Requirements 12.1–12.7.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import FleetQuotationRequest


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"quoted", "declined", "cancelled"},
    "quoted": {"accepted", "declined", "expired"},
    "accepted": set(),
    "declined": set(),
    "expired": set(),
    "cancelled": set(),
}


def can_transition(current: str, target: str) -> bool:
    """Property 31 — quote state machine."""
    return target in _ALLOWED_TRANSITIONS.get(current, set())


async def create_quote_request(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
    service_description: str,
    notes: str | None,
) -> FleetQuotationRequest:
    if ctx.fleet_account_id is None:
        raise ValueError("No fleet account context")
    if len((service_description or "").strip()) < 10:
        raise ValueError("service_description must be at least 10 characters")

    row = FleetQuotationRequest(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        customer_vehicle_id=customer_vehicle_id,
        requested_by_portal_account_id=ctx.portal_account_id,
        service_description=service_description,
        notes=notes,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    # In-app notification to workshop admins (Req 12.2)
    try:
        from app.modules.in_app_notifications.service import create_in_app_notification
        await create_in_app_notification(
            db,
            org_id=ctx.org_id,
            category="fleet_quote_request",
            severity="info",
            title="New fleet quotation request",
            body=f"A fleet customer has requested a quote: {service_description[:80]}",
            link_url="/fleet-portal-admin/quotes",
            entity_type="fleet_quotation_request",
            entity_id=row.id,
            audience_roles=["org_admin", "admin"],
        )
    except Exception:
        pass  # Non-critical

    return row


__all__ = ["can_transition", "create_quote_request"]
