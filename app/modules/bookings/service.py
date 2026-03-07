"""Business logic for Booking module — CRUD, calendar view data, and conversion.

Requirements: 64.1, 64.2, 64.3, 64.4, 64.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func as sa_func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.bookings.models import Booking
from app.modules.customers.models import Customer


# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"confirmed", "cancelled", "no_show"},
    "confirmed": {"completed", "cancelled", "no_show"},
    "completed": set(),
    "cancelled": set(),
    "no_show": set(),
}


def _validate_status_transition(current: str, target: str) -> None:
    """Validate a booking status transition."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Cannot transition booking from '{current}' to '{target}'"
        )


def _booking_to_dict(booking: Booking, customer_name: str | None = None) -> dict:
    """Convert a Booking to a serialisable dict."""
    return {
        "id": booking.id,
        "org_id": booking.org_id,
        "customer_id": booking.customer_id,
        "customer_name": customer_name,
        "vehicle_rego": booking.vehicle_rego,
        "branch_id": booking.branch_id,
        "service_type": booking.service_type,
        "scheduled_at": booking.scheduled_at,
        "duration_minutes": booking.duration_minutes,
        "notes": booking.notes,
        "status": booking.status,
        "reminder_sent": booking.reminder_sent,
        "assigned_to": booking.assigned_to,
        "created_by": booking.created_by,
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
    }


async def create_booking(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    vehicle_rego: str | None = None,
    branch_id: uuid.UUID | None = None,
    service_type: str | None = None,
    scheduled_at: datetime,
    duration_minutes: int = 60,
    notes: str | None = None,
    assigned_to: uuid.UUID | None = None,
    send_confirmation: bool = False,
    ip_address: str | None = None,
) -> dict:
    """Create a new booking in 'scheduled' status.

    Requirements: 64.2, 64.3
    """
    # Validate customer exists and belongs to org
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found in this organisation")

    customer_name = f"{customer.first_name} {customer.last_name}".strip()

    booking = Booking(
        org_id=org_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        branch_id=branch_id,
        service_type=service_type,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        notes=notes,
        status="scheduled",
        assigned_to=assigned_to,
        created_by=user_id,
    )
    db.add(booking)
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="booking.created",
        entity_type="booking",
        entity_id=booking.id,
        after_value={
            "status": "scheduled",
            "customer_id": str(customer_id),
            "vehicle_rego": vehicle_rego,
            "service_type": service_type,
            "scheduled_at": str(scheduled_at),
            "duration_minutes": duration_minutes,
            "send_confirmation": send_confirmation,
        },
        ip_address=ip_address,
    )

    result = _booking_to_dict(booking, customer_name)
    result["confirmation_sent"] = send_confirmation
    return result


async def get_booking(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    booking_id: uuid.UUID,
) -> dict:
    """Retrieve a single booking by ID within an organisation."""
    result = await db.execute(
        select(Booking, Customer.first_name, Customer.last_name)
        .join(Customer, Booking.customer_id == Customer.id, isouter=True)
        .where(Booking.id == booking_id, Booking.org_id == org_id)
    )
    row = result.first()
    if row is None:
        raise ValueError("Booking not found in this organisation")

    booking = row[0]
    first = row[1] or ""
    last = row[2] or ""
    customer_name = f"{first} {last}".strip() or None

    return _booking_to_dict(booking, customer_name)


def _get_calendar_range(
    view: str,
    date_param: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Calculate start/end datetime for a calendar view.

    Requirements: 64.1
    """
    now = date_param or datetime.now(timezone.utc)
    if view == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif view == "week":
        # Start on Monday
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start - timedelta(days=start.weekday())
        end = start + timedelta(days=7)
    else:  # month
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # End of month: go to next month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    return start, end


async def list_bookings(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    view: str = "week",
    date_param: datetime | None = None,
    status: str | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """List bookings for a calendar view (day/week/month).

    Requirements: 64.1
    """
    start, end = _get_calendar_range(view, date_param)

    filters = [
        Booking.org_id == org_id,
        Booking.scheduled_at >= start,
        Booking.scheduled_at < end,
    ]

    if status:
        filters.append(Booking.status == status)
    if branch_id:
        filters.append(Booking.branch_id == branch_id)

    # Count
    count_q = (
        select(sa_func.count(Booking.id))
        .join(Customer, Booking.customer_id == Customer.id, isouter=True)
        .where(*filters)
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Data
    data_q = (
        select(
            Booking.id,
            Customer.first_name,
            Customer.last_name,
            Booking.vehicle_rego,
            Booking.service_type,
            Booking.scheduled_at,
            Booking.duration_minutes,
            Booking.status,
        )
        .join(Customer, Booking.customer_id == Customer.id, isouter=True)
        .where(*filters)
        .order_by(Booking.scheduled_at.asc())
    )
    rows = await db.execute(data_q)

    bookings = []
    for row in rows:
        first = row.first_name or ""
        last = row.last_name or ""
        customer_name = f"{first} {last}".strip() or None
        bookings.append({
            "id": row.id,
            "customer_name": customer_name,
            "vehicle_rego": row.vehicle_rego,
            "service_type": row.service_type,
            "scheduled_at": row.scheduled_at,
            "duration_minutes": row.duration_minutes,
            "status": row.status,
        })

    return {
        "bookings": bookings,
        "total": total,
        "view": view,
        "start_date": start,
        "end_date": end,
    }


async def update_booking(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    updates: dict,
    ip_address: str | None = None,
) -> dict:
    """Update a booking with status validation.

    Scheduled/confirmed bookings allow full edits.
    Completed/cancelled/no_show bookings only allow notes updates.

    Requirements: 64.2
    """
    result = await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.org_id == org_id,
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")

    before_value = {
        "status": booking.status,
        "customer_id": str(booking.customer_id) if booking.customer_id else None,
        "vehicle_rego": booking.vehicle_rego,
        "scheduled_at": str(booking.scheduled_at),
        "notes": booking.notes,
    }

    # Handle status transition
    new_status = updates.get("status")
    if new_status and new_status != booking.status:
        _validate_status_transition(booking.status, new_status)
        booking.status = new_status

    # Scheduled/confirmed bookings allow structural edits
    if booking.status in ("scheduled", "confirmed"):
        for field in ("customer_id", "vehicle_rego", "branch_id",
                       "service_type", "scheduled_at", "duration_minutes",
                       "notes", "assigned_to"):
            if field in updates and updates[field] is not None:
                setattr(booking, field, updates[field])
    elif new_status is None:
        # Terminal statuses only allow notes updates
        if "notes" in updates:
            booking.notes = updates["notes"]

    await db.flush()

    # Get customer name for response
    cust_result = await db.execute(
        select(Customer).where(Customer.id == booking.customer_id)
    )
    customer = cust_result.scalar_one_or_none()
    customer_name = None
    if customer:
        customer_name = f"{customer.first_name} {customer.last_name}".strip()

    after_value = {
        "status": booking.status,
        "customer_id": str(booking.customer_id) if booking.customer_id else None,
        "vehicle_rego": booking.vehicle_rego,
        "scheduled_at": str(booking.scheduled_at),
        "notes": booking.notes,
    }
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="booking.updated",
        entity_type="booking",
        entity_id=booking.id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
    )

    return _booking_to_dict(booking, customer_name)


async def delete_booking(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Cancel a booking (soft delete via status change to 'cancelled').

    Requirements: 64.2
    """
    result = await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.org_id == org_id,
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")

    if booking.status in ("completed", "cancelled", "no_show"):
        raise ValueError(
            f"Cannot cancel a booking with status '{booking.status}'"
        )

    old_status = booking.status
    booking.status = "cancelled"
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="booking.cancelled",
        entity_type="booking",
        entity_id=booking.id,
        before_value={"status": old_status},
        after_value={"status": "cancelled"},
        ip_address=ip_address,
    )

    return {"id": booking.id, "status": "cancelled", "message": "Booking cancelled"}


# ---------------------------------------------------------------------------
# Booking conversion — Requirement 64.5
# ---------------------------------------------------------------------------

# Statuses that allow conversion
_CONVERTIBLE_STATUSES = {"scheduled", "confirmed"}


async def convert_booking_to_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Convert a booking to a Job Card pre-filled with appointment details.

    Only scheduled or confirmed bookings may be converted.
    The booking status transitions to 'completed' after conversion.

    Requirements: 64.5
    """
    from app.modules.job_cards.service import create_job_card

    result = await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.org_id == org_id,
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")

    if booking.status not in _CONVERTIBLE_STATUSES:
        raise ValueError(
            f"Only scheduled or confirmed bookings can be converted, "
            f"current status is '{booking.status}'"
        )

    if booking.customer_id is None:
        raise ValueError("Booking must have a customer to convert")

    job_card = await create_job_card(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=booking.customer_id,
        vehicle_rego=booking.vehicle_rego,
        description=booking.service_type,
        notes=booking.notes,
        ip_address=ip_address,
    )

    # Transition booking to completed
    old_status = booking.status
    booking.status = "completed"
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="booking.converted_to_job_card",
        entity_type="booking",
        entity_id=booking.id,
        before_value={"status": old_status},
        after_value={
            "status": "completed",
            "job_card_id": str(job_card["id"]),
        },
        ip_address=ip_address,
    )

    return {
        "booking_id": booking.id,
        "target": "job_card",
        "created_id": job_card["id"],
        "message": "Booking converted to job card",
    }


async def convert_booking_to_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Convert a booking to a Draft invoice pre-filled with appointment details.

    Only scheduled or confirmed bookings may be converted.
    The booking status transitions to 'completed' after conversion.

    Requirements: 64.5
    """
    from app.modules.invoices.service import create_invoice

    result = await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.org_id == org_id,
        )
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")

    if booking.status not in _CONVERTIBLE_STATUSES:
        raise ValueError(
            f"Only scheduled or confirmed bookings can be converted, "
            f"current status is '{booking.status}'"
        )

    if booking.customer_id is None:
        raise ValueError("Booking must have a customer to convert")

    invoice = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=booking.customer_id,
        vehicle_rego=booking.vehicle_rego,
        status="draft",
        notes_internal=booking.notes,
        ip_address=ip_address,
    )

    # Transition booking to completed
    old_status = booking.status
    booking.status = "completed"
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="booking.converted_to_invoice",
        entity_type="booking",
        entity_id=booking.id,
        before_value={"status": old_status},
        after_value={
            "status": "completed",
            "invoice_id": str(invoice["id"]),
        },
        ip_address=ip_address,
    )

    return {
        "booking_id": booking.id,
        "target": "invoice",
        "created_id": invoice["id"],
        "message": "Booking converted to draft invoice",
    }
