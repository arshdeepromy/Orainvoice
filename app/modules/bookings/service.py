"""Business logic for Booking module — CRUD, calendar view data, and conversion.

Requirements: 64.1, 64.2, 64.3, 64.4, 64.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func as sa_func, and_
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.core.audit import write_audit_log
from app.modules.bookings.models import Booking
from app.modules.customers.models import Customer

logger = logging.getLogger(__name__)


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
        "service_catalogue_id": booking.service_catalogue_id,
        "service_price": booking.service_price,
        "scheduled_at": booking.scheduled_at,
        "duration_minutes": booking.duration_minutes,
        "notes": booking.notes,
        "status": booking.status,
        "reminder_sent": booking.reminder_sent,
        "send_email_confirmation": booking.send_email_confirmation,
        "send_sms_confirmation": booking.send_sms_confirmation,
        "reminder_offset_hours": booking.reminder_offset_hours,
        "reminder_scheduled_at": booking.reminder_scheduled_at,
        "reminder_cancelled": booking.reminder_cancelled,
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
    service_catalogue_id: uuid.UUID | None = None,
    scheduled_at: datetime,
    duration_minutes: int = 60,
    notes: str | None = None,
    assigned_to: uuid.UUID | None = None,
    send_confirmation: bool = False,
    send_email_confirmation: bool | None = None,
    send_sms_confirmation: bool = False,
    reminder_offset_hours: float | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new booking in 'scheduled' status.

    Requirements: 64.2, 64.3, 4.4, 4.5, 4.6, 5.5, 5.8, 5.9
    """
    # Backward compat: if send_confirmation is true and
    # send_email_confirmation was not explicitly provided, treat as
    # send_email_confirmation = True (Req 4.4)
    if send_email_confirmation is None:
        send_email_confirmation = send_confirmation

    # Gate vehicle rego behind vehicles module (Req 2.5, 2.6)
    if vehicle_rego is not None:
        from app.core.modules import ModuleService
        module_svc = ModuleService(db)
        if not await module_svc.is_enabled(str(org_id), "vehicles"):
            vehicle_rego = None

    # Service catalogue linkage (Req 3.2, 3.8, 3.9)
    service_price = None
    if service_catalogue_id is not None:
        from app.modules.catalogue.models import ServiceCatalogue

        cat_result = await db.execute(
            select(ServiceCatalogue).where(
                ServiceCatalogue.id == service_catalogue_id,
            )
        )
        catalogue = cat_result.scalar_one_or_none()
        if catalogue is None:
            raise ValueError("Service not found in this organisation")
        if catalogue.org_id != org_id:
            raise ValueError("Service not found in this organisation")
        if not catalogue.is_active:
            raise ValueError("Selected service is no longer active")
        service_type = catalogue.name
        service_price = catalogue.default_price

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

    # Gate SMS behind org subscription plan (Req 4.5)
    effective_send_sms = send_sms_confirmation
    if send_sms_confirmation:
        from app.modules.admin.models import Organisation, SubscriptionPlan
        org_result = await db.execute(
            select(Organisation).where(Organisation.id == org_id)
        )
        org_row = org_result.scalar_one_or_none()
        sms_allowed = False
        if org_row and org_row.plan_id:
            plan_result = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.id == org_row.plan_id)
            )
            plan_row = plan_result.scalar_one_or_none()
            sms_allowed = plan_row.sms_included if plan_row else False
        if not sms_allowed:
            logger.warning(
                "SMS confirmation requested for org %s but plan does not include SMS — skipping",
                org_id,
            )
            effective_send_sms = False

    # Reminder scheduling (Req 5.5, 5.8, 5.9)
    reminder_scheduled_at = None
    if reminder_offset_hours is not None:
        reminder_scheduled_at = scheduled_at - timedelta(hours=reminder_offset_hours)
        if reminder_scheduled_at <= datetime.now(timezone.utc):
            logger.warning(
                "Reminder time %s is in the past for booking scheduled at %s — skipping reminder",
                reminder_scheduled_at,
                scheduled_at,
            )
            reminder_scheduled_at = None

    booking = Booking(
        org_id=org_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        branch_id=branch_id,
        service_type=service_type,
        service_catalogue_id=service_catalogue_id,
        service_price=service_price,
        scheduled_at=scheduled_at,
        duration_minutes=duration_minutes,
        notes=notes,
        status="scheduled",
        assigned_to=assigned_to,
        created_by=user_id,
        send_email_confirmation=send_email_confirmation,
        send_sms_confirmation=effective_send_sms,
        reminder_offset_hours=reminder_offset_hours,
        reminder_scheduled_at=reminder_scheduled_at,
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
            "send_email_confirmation": send_email_confirmation,
            "send_sms_confirmation": effective_send_sms,
            "reminder_offset_hours": reminder_offset_hours,
            "reminder_scheduled_at": str(reminder_scheduled_at) if reminder_scheduled_at else None,
        },
        ip_address=ip_address,
    )

    # --- Notification dispatch (Req 4.4, 4.5, 4.6) ---
    # Failures must NOT roll back the booking — log and continue.
    if send_email_confirmation and customer.email:
        try:
            from app.modules.notifications.service import log_email_sent
            from app.tasks.notifications import send_email_task

            log_entry = await log_email_sent(
                db,
                org_id=org_id,
                recipient=customer.email,
                template_type="booking_confirmation",
                subject=f"Booking confirmation — {service_type or 'your appointment'}",
                status="queued",
                channel="email",
            )
            send_email_task.delay(
                str(org_id),
                log_entry["id"],
                customer.email,
                customer_name,
                f"Booking confirmation — {service_type or 'your appointment'}",
                "",  # html_body — rendered by template system
                "",  # text_body
                None,
                None,
                "booking_confirmation",
            )
        except Exception:
            logger.exception(
                "Failed to dispatch email confirmation for booking %s",
                booking.id,
            )

    if effective_send_sms and customer.phone:
        try:
            from app.modules.notifications.service import log_sms_sent
            from app.tasks.notifications import send_sms_task
            from app.modules.admin.service import increment_sms_usage

            sms_log = await log_sms_sent(
                db,
                org_id=org_id,
                recipient=customer.phone,
                template_type="booking_confirmation",
                body=f"Booking confirmed for {service_type or 'your appointment'} on {scheduled_at.strftime('%d/%m/%Y %H:%M')}.",
                status="queued",
            )
            send_sms_task.delay(
                str(org_id),
                sms_log["id"],
                customer.phone,
                f"Booking confirmed for {service_type or 'your appointment'} on {scheduled_at.strftime('%d/%m/%Y %H:%M')}.",
                None,
                "booking_confirmation",
            )
            # Best-effort SMS usage tracking
            try:
                await increment_sms_usage(db, org_id)
            except Exception:
                logger.warning(
                    "Failed to increment SMS usage for org %s", org_id
                )
        except Exception:
            logger.exception(
                "Failed to dispatch SMS confirmation for booking %s",
                booking.id,
            )

    result = _booking_to_dict(booking, customer_name)
    result["confirmation_sent"] = send_email_confirmation or effective_send_sms
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

        # Cancel pending reminder when booking is cancelled
        if new_status == "cancelled":
            if booking.reminder_scheduled_at is not None and not booking.reminder_cancelled:
                booking.reminder_cancelled = True

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

    # Cancel pending reminder if one is scheduled
    if booking.reminder_scheduled_at is not None and not booking.reminder_cancelled:
        booking.reminder_cancelled = True

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
