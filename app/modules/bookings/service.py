"""Business logic for Booking module — CRUD, calendar view data, and conversion.

Matches the actual DB schema from migration 0038 + 0081 + 0082.
DB columns: customer_name, customer_email, customer_phone, staff_id,
start_time, end_time, confirmation_token, converted_job_id, converted_invoice_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.core.audit import write_audit_log
from app.modules.bookings.models import Booking
from app.modules.customers.models import Customer

logger = logging.getLogger(__name__)

_CONVERTIBLE_STATUSES = {"scheduled", "confirmed", "pending"}

# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"scheduled", "confirmed", "cancelled"},
    "scheduled": {"confirmed", "cancelled", "no_show"},
    "confirmed": {"completed", "cancelled", "no_show"},
    "completed": set(),
    "cancelled": set(),
    "no_show": set(),
}


def _validate_status_transition(current: str, target: str) -> None:
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Cannot transition booking from '{current}' to '{target}'"
        )


def _booking_to_dict(booking: Booking) -> dict:
    """Convert a Booking to a serialisable dict."""
    duration = int((booking.end_time - booking.start_time).total_seconds() / 60) if booking.end_time and booking.start_time else 60
    return {
        "id": booking.id,
        "org_id": booking.org_id,
        "customer_name": booking.customer_name,
        "customer_email": booking.customer_email,
        "customer_phone": booking.customer_phone,
        "vehicle_rego": booking.vehicle_rego,
        "staff_id": booking.staff_id,
        "service_type": booking.service_type,
        "service_catalogue_id": booking.service_catalogue_id,
        "service_price": booking.service_price,
        "scheduled_at": booking.start_time,
        "start_time": booking.start_time,
        "end_time": booking.end_time,
        "duration_minutes": duration,
        "notes": booking.notes,
        "status": booking.status,
        "confirmation_token": booking.confirmation_token,
        "converted_job_id": booking.converted_job_id,
        "converted_invoice_id": booking.converted_invoice_id,
        "send_email_confirmation": booking.send_email_confirmation,
        "send_sms_confirmation": booking.send_sms_confirmation,
        "reminder_offset_hours": booking.reminder_offset_hours,
        "reminder_scheduled_at": booking.reminder_scheduled_at,
        "reminder_cancelled": booking.reminder_cancelled,
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
    }


DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


async def _check_staff_availability(
    db: AsyncSession,
    org_id: uuid.UUID,
    start_time: datetime,
    end_time: datetime,
) -> None:
    """If the staff module is enabled, verify at least one active staff member
    is available during the booking window.  Raises ValueError if nobody is
    available.  Does nothing when the staff module is disabled.

    Availability is determined by:
    1. ``availability_schedule`` (JSONB weekday map with start/end times), or
    2. ``shift_start`` / ``shift_end`` (simple daily window), or
    3. If a staff member has neither configured they are treated as always
       available (no restriction).

    Times are converted to the organisation's local timezone before comparison,
    since staff schedules are defined in local time.
    """
    from app.core.modules import ModuleService

    svc = ModuleService(db)
    staff_enabled = await svc.is_enabled(str(org_id), "staff")
    if not staff_enabled:
        return  # no restriction when staff module is off

    from app.modules.staff.models import StaffMember

    result = await db.execute(
        select(StaffMember).where(
            StaffMember.org_id == org_id,
            StaffMember.is_active.is_(True),
        )
    )
    staff_list = list(result.scalars().all())

    if not staff_list:
        # No staff configured at all — allow booking (org hasn't set up staff yet)
        return

    # Convert UTC times to org local timezone for comparison with staff schedules
    from zoneinfo import ZoneInfo
    from sqlalchemy import text as sa_text

    org_tz_result = await db.execute(
        sa_text("SELECT timezone FROM organisations WHERE id = :oid"),
        {"oid": str(org_id)},
    )
    org_tz_name = org_tz_result.scalar_one_or_none()
    if org_tz_name:
        try:
            local_tz = ZoneInfo(org_tz_name)
            local_start = start_time.astimezone(local_tz)
            local_end = end_time.astimezone(local_tz)
        except (KeyError, Exception):
            # Unknown timezone — fall back to UTC
            local_start = start_time
            local_end = end_time
    else:
        local_start = start_time
        local_end = end_time

    booking_day = DAY_NAMES[local_start.weekday()]
    booking_start_mins = local_start.hour * 60 + local_start.minute
    booking_end_mins = local_end.hour * 60 + local_end.minute
    # Handle overnight bookings (end next day)
    if booking_end_mins <= booking_start_mins:
        booking_end_mins = 24 * 60

    for member in staff_list:
        schedule = member.availability_schedule or {}

        if schedule:
            # Weekday-specific schedule is configured — it's authoritative
            day_schedule = schedule.get(booking_day)
            if not day_schedule or not isinstance(day_schedule, dict):
                continue  # this member doesn't work on this day
            try:
                sh, sm = map(int, day_schedule.get("start", "09:00").split(":"))
                eh, em = map(int, day_schedule.get("end", "17:00").split(":"))
                avail_start = sh * 60 + sm
                avail_end = eh * 60 + em
                if booking_start_mins >= avail_start and booking_end_mins <= avail_end:
                    return  # at least one staff member covers this window
            except (ValueError, AttributeError):
                pass
            continue

        # No availability_schedule — fall back to shift_start / shift_end
        if member.shift_start and member.shift_end:
            try:
                sh, sm = map(int, member.shift_start.split(":"))
                eh, em = map(int, member.shift_end.split(":"))
                avail_start = sh * 60 + sm
                avail_end = eh * 60 + em
                if booking_start_mins >= avail_start and booking_end_mins <= avail_end:
                    return  # covered (shift doesn't specify days, so any day is OK)
            except (ValueError, AttributeError):
                pass
            continue

        # No schedule and no shift configured — treat as always available
        return

    # Nobody covers the window
    raise ValueError(
        "No staff available during the selected time. "
        "Please choose a time within working hours."
    )


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
    """Create a new booking."""
    # Prevent backdated bookings
    now = datetime.now(scheduled_at.tzinfo) if scheduled_at.tzinfo else datetime.utcnow()
    if scheduled_at < now:
        raise ValueError("Cannot create a booking in the past")

    if send_email_confirmation is None:
        send_email_confirmation = send_confirmation

    # Calculate times early so we can validate availability
    start_time = scheduled_at
    end_time = scheduled_at + timedelta(minutes=duration_minutes)

    # Staff availability check (only when staff module is enabled)
    await _check_staff_availability(db, org_id, start_time, end_time)

    # Vehicle rego module gating: clear vehicle_rego when vehicles module is disabled
    if vehicle_rego is not None:
        from app.core.modules import ModuleService
        module_svc = ModuleService(db)
        vehicles_enabled = await module_svc.is_enabled(str(org_id), "vehicles")
        if not vehicles_enabled:
            vehicle_rego = None

    # Service catalogue linkage
    service_price = None
    if service_catalogue_id is not None:
        from app.modules.catalogue.models import ItemsCatalogue
        cat_result = await db.execute(
            select(ItemsCatalogue).where(ItemsCatalogue.id == service_catalogue_id)
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

    # Validate customer
    cust_result = await db.execute(
        select(Customer).where(Customer.id == customer_id, Customer.org_id == org_id)
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found in this organisation")

    customer_name = f"{customer.first_name} {customer.last_name}".strip()

    # Reminder scheduling
    reminder_scheduled_at = None
    if reminder_offset_hours is not None:
        reminder_scheduled_at = scheduled_at - timedelta(hours=reminder_offset_hours)
        if reminder_scheduled_at <= datetime.now(timezone.utc):
            logger.warning("Reminder time %s is in the past — skipping", reminder_scheduled_at)
            reminder_scheduled_at = None

    now = datetime.now(timezone.utc)
    booking = Booking(
        org_id=org_id,
        customer_name=customer_name,
        customer_email=customer.email,
        customer_phone=customer.phone,
        vehicle_rego=vehicle_rego,
        staff_id=assigned_to,
        service_type=service_type,
        service_catalogue_id=service_catalogue_id,
        service_price=service_price,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
        status="scheduled",
        send_email_confirmation=send_email_confirmation,
        send_sms_confirmation=send_sms_confirmation,
        reminder_offset_hours=reminder_offset_hours,
        reminder_scheduled_at=reminder_scheduled_at,
        created_at=now,
        updated_at=now,
    )
    db.add(booking)
    await db.flush()

    # --- Auto-link customer ↔ vehicle (mirrors invoice creation logic) ---
    if vehicle_rego:
        try:
            from app.modules.admin.models import GlobalVehicle
            from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

            # Try global_vehicles first
            gv_result = await db.execute(
                select(GlobalVehicle).where(
                    sa_func.upper(GlobalVehicle.rego) == vehicle_rego.upper()
                )
            )
            gv = gv_result.scalar_one_or_none()

            if gv:
                existing = await db.execute(
                    select(CustomerVehicle).where(
                        CustomerVehicle.org_id == org_id,
                        CustomerVehicle.customer_id == customer_id,
                        CustomerVehicle.global_vehicle_id == gv.id,
                    )
                )
                if existing.scalar_one_or_none() is None:
                    cv = CustomerVehicle(
                        org_id=org_id,
                        customer_id=customer_id,
                        global_vehicle_id=gv.id,
                    )
                    db.add(cv)
                    await db.flush()
            else:
                # Fallback: try org_vehicles
                ov_result = await db.execute(
                    select(OrgVehicle).where(
                        OrgVehicle.org_id == org_id,
                        sa_func.upper(OrgVehicle.rego) == vehicle_rego.upper(),
                    )
                )
                ov = ov_result.scalar_one_or_none()
                if ov:
                    existing = await db.execute(
                        select(CustomerVehicle).where(
                            CustomerVehicle.org_id == org_id,
                            CustomerVehicle.customer_id == customer_id,
                            CustomerVehicle.org_vehicle_id == ov.id,
                        )
                    )
                    if existing.scalar_one_or_none() is None:
                        cv = CustomerVehicle(
                            org_id=org_id,
                            customer_id=customer_id,
                            org_vehicle_id=ov.id,
                        )
                        db.add(cv)
                        await db.flush()
        except Exception:
            logger.warning(
                "Failed to auto-link customer %s to vehicle %s on booking %s",
                customer_id, vehicle_rego, booking.id, exc_info=True,
            )

    # Audit log
    await write_audit_log(
        session=db, org_id=org_id, user_id=user_id,
        action="booking.created", entity_type="booking", entity_id=booking.id,
        after_value={"status": "scheduled", "customer_name": customer_name, "service_type": service_type},
        ip_address=ip_address,
    )

    # Refresh customer to avoid MissingGreenlet after multiple flushes
    if send_email_confirmation or send_sms_confirmation:
        await db.refresh(customer)

    # --- Send confirmation email ---
    confirmation_sent = False
    if send_email_confirmation and customer.email:
        try:
            confirmation_sent = await _send_booking_confirmation_email(
                db,
                org_id=org_id,
                customer_first_name=customer.first_name,
                customer_email=customer.email,
                service_type=service_type,
                start_time=start_time,
                duration_minutes=duration_minutes,
                vehicle_rego=vehicle_rego,
                notes=notes,
            )
            if confirmation_sent:
                logger.info(
                    "Booking confirmation email sent: org=%s, booking=%s, to=%s",
                    org_id, booking.id, customer.email,
                )
        except Exception:
            logger.error(
                "Failed to send booking confirmation email: org=%s, booking=%s",
                org_id, booking.id, exc_info=True,
            )

    # --- Send confirmation SMS ---
    sms_sent = False
    if send_sms_confirmation and customer.phone:
        try:
            from app.modules.notifications.service import log_sms_sent
            from app.tasks.notifications import send_sms_task

            formatted_date = start_time.strftime("%d/%m/%Y %I:%M %p")
            sms_body = (
                f"Hi {customer.first_name}, your booking for "
                f"{service_type or 'an appointment'} on {formatted_date} "
                f"has been confirmed."
            )

            sms_log = await log_sms_sent(
                db,
                org_id=org_id,
                recipient=customer.phone,
                template_type="booking_confirmation",
                body=sms_body,
                status="queued",
            )

            await send_sms_task(
                str(org_id),
                sms_log["id"],
                customer.phone,
                sms_body,
                None,
                "booking_confirmation",
            )
            sms_sent = True
            logger.info(
                "Booking confirmation SMS queued: org=%s, booking=%s, to=%s",
                org_id, booking.id, customer.phone,
            )
        except Exception:
            logger.error(
                "Failed to queue booking confirmation SMS: org=%s, booking=%s",
                org_id, booking.id, exc_info=True,
            )

    result = _booking_to_dict(booking)
    result["confirmation_sent"] = confirmation_sent or sms_sent
    return result


async def get_booking(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    booking_id: uuid.UUID,
) -> dict:
    """Retrieve a single booking by ID."""
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.org_id == org_id)
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")
    return _booking_to_dict(booking)


def _get_calendar_range(view: str, date_param: datetime | None) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes for a calendar view."""
    now = date_param or datetime.now(timezone.utc)
    if view == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif view == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    else:  # week
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
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
    """List bookings for a calendar view."""
    start, end = _get_calendar_range(view, date_param)

    filters = [
        Booking.org_id == org_id,
        Booking.start_time >= start,
        Booking.start_time < end,
    ]
    if status:
        filters.append(Booking.status == status)

    count_q = select(sa_func.count(Booking.id)).where(*filters)
    total = (await db.execute(count_q)).scalar() or 0

    data_q = select(Booking).where(*filters).order_by(Booking.start_time.asc())
    rows = await db.execute(data_q)

    bookings = []
    for (booking,) in rows:
        d = _booking_to_dict(booking)
        bookings.append(d)

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
    """Update a booking with status validation."""
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.org_id == org_id)
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")

    before_value = {"status": booking.status, "notes": booking.notes}

    # Handle status transition
    new_status = updates.get("status")
    if new_status and new_status != booking.status:
        _validate_status_transition(booking.status, new_status)
        booking.status = new_status
        if new_status == "cancelled" and booking.reminder_scheduled_at and not booking.reminder_cancelled:
            booking.reminder_cancelled = True

    # Editable fields for active bookings
    if booking.status in ("scheduled", "confirmed", "pending"):
        field_map = {
            "service_type": "service_type",
            "vehicle_rego": "vehicle_rego",
            "notes": "notes",
            "staff_id": "staff_id",
            "assigned_to": "staff_id",
        }
        for key, col in field_map.items():
            if key in updates and updates[key] is not None:
                setattr(booking, col, updates[key])
        # Handle scheduled_at + duration_minutes → start_time/end_time
        if "scheduled_at" in updates:
            new_start = updates["scheduled_at"]
            dur = updates.get("duration_minutes", 60)
            new_end = new_start + timedelta(minutes=dur)
            await _check_staff_availability(db, org_id, new_start, new_end)
            booking.start_time = new_start
            booking.end_time = new_end
        elif "duration_minutes" in updates:
            new_end = booking.start_time + timedelta(minutes=updates["duration_minutes"])
            await _check_staff_availability(db, org_id, booking.start_time, new_end)
            booking.end_time = new_end
    elif new_status is None:
        if "notes" in updates:
            booking.notes = updates["notes"]

    await db.flush()

    after_value = {"status": booking.status, "notes": booking.notes}
    await write_audit_log(
        session=db, org_id=org_id, user_id=user_id,
        action="booking.updated", entity_type="booking", entity_id=booking.id,
        before_value=before_value, after_value=after_value, ip_address=ip_address,
    )

    return _booking_to_dict(booking)


async def delete_booking(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Soft-delete (cancel) a booking."""
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.org_id == org_id)
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")

    booking.status = "cancelled"
    if booking.reminder_scheduled_at and not booking.reminder_cancelled:
        booking.reminder_cancelled = True
    await db.flush()

    await write_audit_log(
        session=db, org_id=org_id, user_id=user_id,
        action="booking.deleted", entity_type="booking", entity_id=booking.id,
        after_value={"status": "cancelled"}, ip_address=ip_address,
    )

    return {"id": booking.id, "status": "cancelled", "message": "Booking cancelled"}


async def convert_booking_to_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    assigned_to: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Convert a booking to a Job Card."""
    from app.modules.job_cards.service import create_job_card

    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.org_id == org_id)
    )
    booking = result.scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found in this organisation")
    if booking.status not in _CONVERTIBLE_STATUSES:
        raise ValueError(f"Cannot convert booking with status '{booking.status}'")

    # If no explicit assignee, try to resolve the caller's staff member ID
    if assigned_to is None:
        from app.modules.staff.models import StaffMember
        staff_result = await db.execute(
            select(StaffMember.id).where(
                StaffMember.user_id == user_id,
                StaffMember.org_id == org_id,
                StaffMember.is_active.is_(True),
            )
        )
        caller_staff_id = staff_result.scalar_one_or_none()
        if caller_staff_id is not None:
            assigned_to = caller_staff_id

    # Look up customer by name/email to get customer_id
    customer_id = await _resolve_customer_id(db, org_id, booking)
    if customer_id is None:
        raise ValueError("Cannot find matching customer for this booking")

    # Build line_items_data from booking's catalogue reference
    line_items_data: list[dict] = []
    if booking.service_catalogue_id is not None:
        from app.modules.catalogue.models import ItemsCatalogue
        cat_result = await db.execute(
            select(ItemsCatalogue).where(
                ItemsCatalogue.id == booking.service_catalogue_id
            )
        )
        cat_item = cat_result.scalar_one_or_none()
        if cat_item is not None and cat_item.is_active:
            line_items_data.append({
                "item_type": "service",
                "catalogue_item_id": cat_item.id,
                "description": cat_item.name,
                "quantity": Decimal("1"),
                "unit_price": cat_item.default_price,
            })
        else:
            # Catalogue item missing or inactive — fall back to booking snapshot
            if booking.service_price is not None:
                line_items_data.append({
                    "item_type": "service",
                    "catalogue_item_id": None,
                    "description": booking.service_type or "Service",
                    "quantity": Decimal("1"),
                    "unit_price": booking.service_price,
                })

    job_card = await create_job_card(
        db, org_id=org_id, user_id=user_id,
        customer_id=customer_id,
        vehicle_rego=booking.vehicle_rego,
        description=booking.service_type,
        notes=booking.notes,
        assigned_to=assigned_to,
        line_items_data=line_items_data,
        ip_address=ip_address,
    )

    old_status = booking.status
    booking.status = "confirmed"
    booking.converted_job_id = job_card["id"]
    await db.flush()

    await write_audit_log(
        session=db, org_id=org_id, user_id=user_id,
        action="booking.converted_to_job_card", entity_type="booking", entity_id=booking.id,
        before_value={"status": old_status},
        after_value={"status": "confirmed", "job_card_id": str(job_card["id"])},
        ip_address=ip_address,
    )

    return {"booking_id": booking.id, "target": "job_card", "created_id": job_card["id"], "message": "Booking converted to job card"}


async def convert_booking_to_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Convert a booking to a Draft invoice.

    Mirrors the convert_job_card_to_invoice pattern:
    1. Fetch booking as a serialised dict (no lazy-loading issues).
    2. Resolve customer_id from email / name.
    3. Build line items from booking service info.
    4. Create draft invoice via create_invoice.
    5. Mark booking as completed.
    """
    from app.modules.invoices.service import create_invoice

    # Fetch as dict to avoid lazy-loading / MissingGreenlet issues
    bk = await get_booking(db, org_id=org_id, booking_id=booking_id)

    if bk["status"] not in _CONVERTIBLE_STATUSES:
        raise ValueError(f"Cannot convert booking with status '{bk['status']}'")

    # Resolve customer — try email first, then name
    customer_id = await _resolve_customer_id_from_dict(db, org_id, bk)
    if customer_id is None:
        raise ValueError(
            "Cannot find matching customer for this booking. "
            "Please ensure the customer exists before converting."
        )

    # Build line items from booking service info
    invoice_line_items: list[dict] = []
    if bk.get("service_type"):
        price = Decimal(str(bk["service_price"])) if bk.get("service_price") else Decimal("0")
        invoice_line_items.append({
            "item_type": "service",
            "description": bk["service_type"],
            "quantity": 1,
            "unit_price": price,
            "is_gst_exempt": False,
            "sort_order": 0,
        })

    # Create draft invoice (same pattern as convert_job_card_to_invoice)
    invoice_dict = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=customer_id,
        vehicle_rego=bk.get("vehicle_rego"),
        status="draft",
        line_items_data=invoice_line_items if invoice_line_items else None,
        notes_internal=bk.get("notes"),
        ip_address=ip_address,
    )

    # Mark booking as completed and link to invoice
    result = await db.execute(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.org_id == org_id,
        )
    )
    booking_obj = result.scalar_one_or_none()
    old_status = bk["status"]
    if booking_obj is not None:
        booking_obj.status = "completed"
        booking_obj.converted_invoice_id = invoice_dict["id"]
        await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="booking.converted_to_invoice",
        entity_type="booking",
        entity_id=booking_id,
        before_value={"status": old_status},
        after_value={
            "status": "completed",
            "invoice_id": str(invoice_dict["id"]),
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "booking_id": booking_id,
        "target": "invoice",
        "created_id": invoice_dict["id"],
        "message": "Booking converted to draft invoice",
    }



async def _resolve_customer_id_from_dict(
    db: AsyncSession, org_id: uuid.UUID, bk: dict
) -> uuid.UUID | None:
    """Resolve customer_id from a booking dict.

    Tries in order: email (case-insensitive) → phone → display_name →
    first/last name.
    """
    # 1. Match by email (most reliable, case-insensitive)
    email = bk.get("customer_email")
    if email:
        result = await db.execute(
            select(Customer.id).where(
                Customer.org_id == org_id,
                sa_func.lower(Customer.email) == email.lower(),
            ).limit(1)
        )
        cid = result.scalar_one_or_none()
        if cid:
            return cid

    # 2. Match by phone
    phone = bk.get("customer_phone")
    if phone:
        result = await db.execute(
            select(Customer.id).where(
                Customer.org_id == org_id,
                Customer.phone == phone,
            ).limit(1)
        )
        cid = result.scalar_one_or_none()
        if cid:
            return cid

    name = bk.get("customer_name")
    if not name:
        logger.warning(
            "Cannot resolve customer for booking — no email, phone, or name. "
            "booking data: email=%s, phone=%s, name=%s",
            email, phone, name,
        )
        return None

    # 3. Match by display_name (case-insensitive)
    result = await db.execute(
        select(Customer.id).where(
            Customer.org_id == org_id,
            sa_func.lower(Customer.display_name) == name.lower(),
        ).limit(1)
    )
    cid = result.scalar_one_or_none()
    if cid:
        return cid

    # 4. Fallback: match by first_name + last_name (case-insensitive)
    parts = name.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ""
    result = await db.execute(
        select(Customer.id).where(
            Customer.org_id == org_id,
            sa_func.lower(Customer.first_name) == first.lower(),
            sa_func.lower(Customer.last_name) == last.lower(),
        ).limit(1)
    )
    cid = result.scalar_one_or_none()
    if cid:
        return cid

    logger.warning(
        "Cannot resolve customer for booking — no match found. "
        "email=%s, phone=%s, name=%s, org_id=%s",
        email, phone, name, org_id,
    )
    return None


async def _resolve_customer_id(db: AsyncSession, org_id: uuid.UUID, booking: Booking) -> uuid.UUID | None:
    """Try to find the customer_id from booking's customer_name/email (ORM version)."""
    bk = {
        "customer_email": booking.customer_email,
        "customer_name": booking.customer_name,
    }
    return await _resolve_customer_id_from_dict(db, org_id, bk)


async def _send_booking_confirmation_email(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_first_name: str,
    customer_email: str,
    service_type: str | None,
    start_time: datetime,
    duration_minutes: int,
    vehicle_rego: str | None,
    notes: str | None,
) -> bool:
    """Send booking confirmation email via the configured EmailProvider (SMTP).

    Uses the same EmailProvider priority-failover pattern as invoice and quote
    emails. Returns True if the email was sent successfully, False otherwise.
    """
    import json as _json
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import EmailProvider, Organisation

    # Resolve org name for the From header
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Workshop"

    # Find active email providers ordered by priority
    provider_result = await db.execute(
        select(EmailProvider)
        .where(EmailProvider.is_active == True, EmailProvider.credentials_set == True)
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())

    if not providers:
        logger.warning("No active email provider configured — skipping booking confirmation email")
        return False

    formatted_date = start_time.strftime("%A %d %B %Y at %I:%M %p")
    subject = f"Booking Confirmation — {service_type or 'Appointment'} on {formatted_date}"

    body = (
        f"Hi {customer_first_name},\n\n"
        f"Your booking has been confirmed:\n\n"
        f"Service: {service_type or 'Appointment'}\n"
        f"Date & Time: {formatted_date}\n"
        f"Duration: {duration_minutes} minutes\n"
    )
    if vehicle_rego:
        body += f"Vehicle: {vehicle_rego}\n"
    if notes:
        body += f"Notes: {notes}\n"
    body += (
        f"\nIf you need to reschedule or cancel, please contact us.\n\n"
        f"Kind regards,\n{org_name}\n"
    )

    recipient = customer_email

    def _build_message(from_name: str, from_email: str) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        return msg

    last_error = None
    for provider in providers:
        try:
            creds_json = envelope_decrypt_str(provider.credentials_encrypted)
            credentials = _json.loads(creds_json)

            smtp_host = provider.smtp_host
            smtp_port = provider.smtp_port or 587
            smtp_encryption = getattr(provider, "smtp_encryption", "tls") or "tls"
            username = credentials.get("username") or credentials.get("api_key", "")
            password = credentials.get("password") or credentials.get("api_key", "")

            config = provider.config or {}
            from_email = config.get("from_email") or username
            from_name = config.get("from_name") or org_name

            msg = _build_message(from_name, from_email)

            if smtp_encryption == "ssl":
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                if smtp_encryption == "tls":
                    server.starttls()

            if username and password:
                server.login(username, password)

            server.sendmail(from_email, recipient, msg.as_string())
            server.quit()
            return True
        except Exception as e:
            last_error = e
            logger.warning(
                "Email provider %s failed for booking confirmation: %s",
                provider.provider_key, e,
            )
            continue

    logger.error("All email providers failed for booking confirmation. Last error: %s", last_error)
    return False
