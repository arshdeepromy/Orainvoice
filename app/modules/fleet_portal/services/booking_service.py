"""Service booking request lifecycle.

Implements: B2B Fleet Portal task 12.1 — Requirements 11.1–11.8.
Property 30: validation predicate for create.
Property 31: status state machine for transitions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.models import FleetServiceBookingRequest


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"accepted", "declined", "cancelled"},
    "accepted": {"completed"},
    "declined": set(),
    "completed": set(),
    "cancelled": set(),
}


def can_transition(current: str, target: str) -> bool:
    """Property 31 — return True iff the transition is allowed."""
    return target in _ALLOWED_TRANSITIONS.get(current, set())


def validate_create(
    *,
    preferred_date: date,
    preferred_slot: str,
    service_description: str,
    today: date | None = None,
) -> None:
    """Property 30 — service-side validation. Schemas catch most cases."""
    today = today or datetime.now(timezone.utc).date()
    if preferred_slot not in {"morning", "afternoon", "all_day"}:
        raise ValueError("preferred_slot must be morning, afternoon, or all_day")
    if preferred_date < today:
        raise ValueError("preferred_date cannot be in the past")
    if len((service_description or "").strip()) < 10:
        raise ValueError("service_description must be at least 10 characters")


async def create_booking_request(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    customer_vehicle_id: uuid.UUID,
    preferred_date: date,
    preferred_slot: str,
    service_description: str,
    notes: str | None,
) -> FleetServiceBookingRequest:
    if ctx.fleet_account_id is None:
        raise ValueError("No fleet account context")

    validate_create(
        preferred_date=preferred_date,
        preferred_slot=preferred_slot,
        service_description=service_description,
    )
    row = FleetServiceBookingRequest(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        customer_vehicle_id=customer_vehicle_id,
        requested_by_portal_account_id=ctx.portal_account_id,
        preferred_date=preferred_date,
        preferred_slot=preferred_slot,
        service_description=service_description,
        notes=notes,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    # Emit notification to workshop admins (Req 11.2)
    try:
        from app.modules.fleet_portal.services import audit_service
        await audit_service.log_event(
            db,
            org_id=ctx.org_id,
            action="fleet_booking_request",
            portal_account_id=ctx.portal_account_id,
            details={"booking_request_id": str(row.id), "vehicle_id": str(customer_vehicle_id)},
        )
    except Exception:
        pass  # Non-critical

    # In-app notification to workshop admins (Req 11.2)
    try:
        from app.modules.in_app_notifications.service import create_in_app_notification
        await create_in_app_notification(
            db,
            org_id=ctx.org_id,
            category="fleet_booking_request",
            severity="info",
            title="New fleet service booking request",
            body=f"A fleet customer has requested a service booking for {preferred_date.isoformat()} ({preferred_slot}).",
            link_url="/fleet-portal-admin/bookings",
            entity_type="fleet_service_booking_request",
            entity_id=row.id,
            audience_roles=["org_admin", "admin"],
        )
    except Exception:
        pass  # Non-critical

    return row


async def cancel_booking_request(
    db: AsyncSession,
    *,
    ctx: FleetSessionCtx,
    request_id: uuid.UUID,
) -> FleetServiceBookingRequest:
    res = await db.execute(
        select(FleetServiceBookingRequest).where(
            FleetServiceBookingRequest.id == request_id,
            FleetServiceBookingRequest.org_id == ctx.org_id,
            FleetServiceBookingRequest.requested_by_portal_account_id == ctx.portal_account_id,
        )
    )
    row = res.scalars().first()
    if row is None:
        raise ValueError("Booking request not found")
    if not can_transition(row.status, "cancelled"):
        raise ValueError(f"Cannot cancel request in status={row.status}")
    row.status = "cancelled"
    await db.flush()
    await db.refresh(row)
    return row


__all__ = [
    "can_transition",
    "validate_create",
    "create_booking_request",
    "cancel_booking_request",
]
