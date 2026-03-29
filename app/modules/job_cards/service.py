"""Business logic for Job Card module — creation, status lifecycle, listing.

Requirements: 59.1, 59.2, 59.5
"""

from __future__ import annotations

import math
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

from datetime import datetime, timezone

from sqlalchemy import select, func as sa_func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.customers.models import Customer
from app.modules.job_cards.models import JobCard, JobCardItem
from app.modules.time_tracking_v2.models import TimeEntry


TWO_PLACES = Decimal("0.01")

# Valid status transitions: Open → In Progress → Completed → Invoiced
VALID_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress"},
    "in_progress": {"completed"},
    "completed": {"invoiced"},
    "invoiced": set(),
}


def _calculate_line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Calculate the total for a single job card line item."""
    return (quantity * unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _validate_status_transition(current: str, target: str) -> None:
    """Validate a job card status transition."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Cannot transition job card from '{current}' to '{target}'"
        )


def _job_card_to_dict(job_card: JobCard, line_items: list[JobCardItem]) -> dict:
    """Convert JobCard + JobCardItems to a serialisable dict."""
    customer_data = None
    if job_card.customer is not None:
        c = job_card.customer
        customer_data = {
            "first_name": c.first_name,
            "last_name": c.last_name,
            "email": c.email,
            "phone": c.phone,
            "address": c.address,
        }
    return {
        "id": job_card.id,
        "org_id": job_card.org_id,
        "customer_id": job_card.customer_id,
        "customer": customer_data,
        "vehicle_rego": job_card.vehicle_rego,
        "status": job_card.status,
        "description": job_card.description,
        "notes": job_card.notes,
        "assigned_to": job_card.assigned_to,
        "line_items": [_line_item_to_dict(li) for li in line_items],
        "created_by": job_card.created_by,
        "created_at": job_card.created_at,
        "updated_at": job_card.updated_at,
    }


def _line_item_to_dict(li: JobCardItem) -> dict:
    """Convert a JobCardItem to a serialisable dict."""
    line_total = _calculate_line_total(li.quantity, li.unit_price)
    return {
        "id": li.id,
        "catalogue_item_id": li.catalogue_item_id,
        "item_type": li.item_type,
        "description": li.description,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "is_completed": li.is_completed,
        "line_total": line_total,
        "sort_order": li.sort_order,
    }


async def create_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    vehicle_rego: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    assigned_to: uuid.UUID | None = None,
    line_items_data: list[dict] | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new job card in Open status.

    Requirements: 59.1
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

    # Resolve assigned_to: ensure it's a staff_members.id
    resolved_assigned_to = assigned_to
    if assigned_to is not None:
        from app.modules.staff.models import StaffMember
        direct = await db.execute(
            select(StaffMember.id).where(
                StaffMember.id == assigned_to,
                StaffMember.org_id == org_id,
            )
        )
        if direct.scalar_one_or_none() is None:
            # Try resolving as users.id → staff_members.id
            by_user = await db.execute(
                select(StaffMember.id).where(
                    StaffMember.user_id == assigned_to,
                    StaffMember.org_id == org_id,
                )
            )
            resolved = by_user.scalar_one_or_none()
            if resolved is not None:
                resolved_assigned_to = resolved
            else:
                resolved_assigned_to = None  # Invalid ID, skip assignment

    job_card = JobCard(
        org_id=org_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        status="open",
        description=description,
        notes=notes,
        assigned_to=resolved_assigned_to,
        created_by=user_id,
    )
    # Explicitly set the customer relationship so _job_card_to_dict can
    # access it without triggering a lazy load in async context.
    job_card.customer = customer
    db.add(job_card)
    await db.flush()

    # Create line items
    items = line_items_data or []
    created_items: list[JobCardItem] = []
    for i, item_data in enumerate(items):
        li = JobCardItem(
            job_card_id=job_card.id,
            org_id=org_id,
            item_type=item_data["item_type"],
            description=item_data["description"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            catalogue_item_id=item_data.get("catalogue_item_id"),
            sort_order=item_data.get("sort_order", i),
        )
        db.add(li)
        await db.flush()
        created_items.append(li)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="job_card.created",
        entity_type="job_card",
        entity_id=job_card.id,
        after_value={
            "status": "open",
            "customer_id": str(customer_id),
            "vehicle_rego": vehicle_rego,
            "line_item_count": len(items),
        },
        ip_address=ip_address,
    )

    # Refresh to load server-generated timestamps (created_at, updated_at)
    await db.refresh(job_card)

    return _job_card_to_dict(job_card, created_items)


async def get_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    job_card_id: uuid.UUID,
) -> dict:
    """Retrieve a single job card by ID within an organisation."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(JobCard)
        .options(selectinload(JobCard.customer))
        .where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card = result.scalar_one_or_none()
    if job_card is None:
        raise ValueError("Job card not found in this organisation")

    li_result = await db.execute(
        select(JobCardItem)
        .where(JobCardItem.job_card_id == job_card.id)
        .order_by(JobCardItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    base = _job_card_to_dict(job_card, line_items)

    # Resolve assigned_to_name
    if job_card.assigned_to is not None:
        from app.modules.staff.models import StaffMember
        staff_result = await db.execute(
            select(StaffMember.name).where(StaffMember.id == job_card.assigned_to)
        )
        base["assigned_to_name"] = staff_result.scalar_one_or_none()
    else:
        base["assigned_to_name"] = None

    # Include timer data
    timer_data = await get_timer_entries(db, org_id=org_id, job_card_id=job_card_id)
    base["time_entries"] = timer_data["entries"]
    base["is_timer_active"] = timer_data["is_active"]

    # Find active timer entry
    active_timer = None
    total_seconds = 0
    for entry in timer_data["entries"]:
        if entry.get("stopped_at") is None:
            active_timer = entry
        elif entry.get("duration_minutes") is not None:
            total_seconds += entry["duration_minutes"] * 60

    base["active_timer"] = active_timer
    base["total_time_seconds"] = total_seconds

    return base


async def list_job_cards(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    active_only: bool = False,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Search and filter job cards with pagination.

    When active_only=True, returns only Open and In Progress job cards
    (for the Salesperson dashboard work queue).

    Requirements: 59.5
    """
    base_filter = [JobCard.org_id == org_id]

    if status:
        # Support comma-separated status values (e.g. "open,in_progress")
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            base_filter.append(JobCard.status == statuses[0])
        elif statuses:
            base_filter.append(JobCard.status.in_(statuses))
    elif active_only:
        base_filter.append(JobCard.status.in_(["open", "in_progress"]))

    if search:
        search_term = f"%{search}%"
        base_filter.append(
            or_(
                JobCard.vehicle_rego.ilike(search_term),
                JobCard.description.ilike(search_term),
                Customer.first_name.ilike(search_term),
                Customer.last_name.ilike(search_term),
                (Customer.first_name + " " + Customer.last_name).ilike(search_term),
            )
        )

    # Count query
    count_q = (
        select(sa_func.count(JobCard.id))
        .join(Customer, JobCard.customer_id == Customer.id, isouter=True)
        .where(*base_filter)
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Data query — join StaffMember for assigned_to display name
    from app.modules.staff.models import StaffMember

    AssignedStaff = StaffMember

    data_q = (
        select(
            JobCard.id,
            Customer.first_name,
            Customer.last_name,
            JobCard.vehicle_rego,
            JobCard.status,
            JobCard.description,
            JobCard.assigned_to,
            JobCard.created_at,
            AssignedStaff.name.label("assigned_to_name"),
            AssignedStaff.user_id.label("assigned_to_user_id"),
        )
        .join(Customer, JobCard.customer_id == Customer.id, isouter=True)
        .join(
            AssignedStaff,
            AssignedStaff.id == JobCard.assigned_to,
            isouter=True,
        )
        .where(*base_filter)
        .order_by(JobCard.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(data_q)

    job_cards = []
    for row in rows:
        first = row.first_name or ""
        last = row.last_name or ""
        customer_name = f"{first} {last}".strip() or None
        job_cards.append(
            {
                "id": row.id,
                "customer_name": customer_name,
                "vehicle_rego": row.vehicle_rego,
                "status": row.status,
                "description": row.description,
                "assigned_to": str(row.assigned_to) if row.assigned_to else None,
                "assigned_to_name": row.assigned_to_name,
                "assigned_to_user_id": str(row.assigned_to_user_id) if row.assigned_to_user_id else None,
                "created_at": row.created_at,
            }
        )

    return {
        "job_cards": job_cards,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def update_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    updates: dict,
    ip_address: str | None = None,
) -> dict:
    """Update a job card with status validation.

    Open job cards allow full edits. Status transitions follow:
    Open → In Progress → Completed → Invoiced.

    Requirements: 59.2
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(JobCard)
        .options(selectinload(JobCard.customer))
        .where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card = result.scalar_one_or_none()
    if job_card is None:
        raise ValueError("Job card not found in this organisation")

    before_value = {
        "status": job_card.status,
        "customer_id": str(job_card.customer_id),
        "vehicle_rego": job_card.vehicle_rego,
        "description": job_card.description,
        "notes": job_card.notes,
    }

    # Handle status transition
    new_status = updates.get("status")
    if new_status and new_status != job_card.status:
        _validate_status_transition(job_card.status, new_status)
        job_card.status = new_status

    # Open and in_progress job cards allow structural edits
    if job_card.status in ("open", "in_progress"):
        for field in ("customer_id", "vehicle_rego", "description", "notes"):
            if field in updates and updates[field] is not None:
                setattr(job_card, field, updates[field])

        # Replace line items if provided
        if "line_items" in updates and updates["line_items"] is not None:
            existing = await db.execute(
                select(JobCardItem).where(
                    JobCardItem.job_card_id == job_card.id
                )
            )
            for li in existing.scalars().all():
                await db.delete(li)
            await db.flush()

            for i, item_data in enumerate(updates["line_items"]):
                li = JobCardItem(
                    job_card_id=job_card.id,
                    org_id=org_id,
                    item_type=item_data["item_type"],
                    description=item_data["description"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    catalogue_item_id=item_data.get("catalogue_item_id"),
                    sort_order=item_data.get("sort_order", i),
                )
                db.add(li)
            await db.flush()
    elif new_status is None:
        # Completed/invoiced job cards only allow notes updates
        if "notes" in updates:
            job_card.notes = updates["notes"]

    await db.flush()

    # Audit log
    after_value = {
        "status": job_card.status,
        "customer_id": str(job_card.customer_id),
        "vehicle_rego": job_card.vehicle_rego,
        "description": job_card.description,
        "notes": job_card.notes,
    }
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="job_card.updated",
        entity_type="job_card",
        entity_id=job_card.id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
    )

    # Refresh job_card to load server-generated updated_at (onupdate=func.now()
    # expires the attribute after flush, and accessing it lazily in async
    # context triggers greenlet_spawn errors).
    await db.refresh(job_card)

    # Reload line items
    li_result = await db.execute(
        select(JobCardItem)
        .where(JobCardItem.job_card_id == job_card.id)
        .order_by(JobCardItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    return _job_card_to_dict(job_card, line_items)


async def convert_job_card_to_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Convert a completed job card to a Draft invoice pre-filled with line items.

    The job card must be in 'completed' status. Creates a new Draft invoice
    and transitions the job card to 'invoiced'.

    Requirements: 59.3
    """
    from app.modules.invoices.service import create_invoice

    # Fetch job card with line items
    jc_dict = await get_job_card(db, org_id=org_id, job_card_id=job_card_id)

    if jc_dict["status"] != "completed":
        raise ValueError(
            f"Cannot convert a job card with status '{jc_dict['status']}'. "
            "Only completed job cards can be converted to invoices."
        )

    # Build invoice line items from job card items — strip location tags for customer-facing invoice
    invoice_line_items = []
    for li in jc_dict.get("line_items", []):
        desc = li["description"]
        # Remove [📍 ...] location tags from descriptions
        desc = re.sub(r'\s*\[📍[^\]]*\]', '', desc).strip()
        invoice_line_items.append({
            "item_type": li["item_type"],
            "description": desc,
            "quantity": li["quantity"],
            "unit_price": li["unit_price"],
            "catalogue_item_id": li.get("catalogue_item_id"),
            "is_gst_exempt": li.get("is_gst_exempt", False),
            "sort_order": li.get("sort_order", 0),
        })

    # Look up the original booking to get fluid usage data
    fluid_usage_for_invoice = None
    try:
        from app.modules.bookings.models import Booking
        bk_result = await db.execute(
            select(Booking).where(
                Booking.converted_job_id == job_card_id,
                Booking.org_id == org_id,
            )
        )
        source_booking = bk_result.scalar_one_or_none()
        if source_booking and source_booking.booking_data_json:
            booking_fluids = source_booking.booking_data_json.get("fluid_usage", [])
            if booking_fluids:
                fluid_usage_for_invoice = [
                    {
                        "stock_item_id": f.get("stock_item_id"),
                        "catalogue_item_id": f.get("catalogue_item_id"),
                        "item_name": f.get("item_name", ""),
                        "litres": f.get("litres", 0),
                    }
                    for f in booking_fluids if f.get("stock_item_id") and f.get("litres", 0) > 0
                ]
                # Release booking fluid reservations (invoice will re-reserve)
                from app.modules.inventory.stock_items_service import release_reservation
                for f in booking_fluids:
                    sid = f.get("stock_item_id")
                    litres = float(f.get("litres", 0))
                    if sid and litres > 0:
                        try:
                            await release_reservation(
                                db, org_id=org_id, user_id=user_id,
                                stock_item_id=uuid.UUID(str(sid)), quantity=litres,
                                reference_type="booking_fluid", reference_id=source_booking.id,
                            )
                        except Exception:
                            pass
            # Also release part reservations from booking (invoice will re-reserve)
            booking_parts = source_booking.booking_data_json.get("parts", [])
            for bp in booking_parts:
                sid = bp.get("stock_item_id")
                qty = float(bp.get("quantity", 0))
                if sid and qty > 0:
                    try:
                        await release_reservation(
                            db, org_id=org_id, user_id=user_id,
                            stock_item_id=uuid.UUID(str(sid)), quantity=qty,
                            reference_type="booking", reference_id=source_booking.id,
                        )
                    except Exception:
                        pass
    except Exception:
        pass  # Non-blocking — booking lookup is best-effort

    # Create draft invoice with parts (from line items) and fluid usage
    # Strip internal oil/fluid notes from customer-facing invoice notes
    raw_notes = jc_dict.get("notes") or ""
    # Remove the "── Oil / Fluid Required ──" section and everything after it
    clean_notes = re.split(r'\n*── Oil / Fluid Required ──', raw_notes)[0].strip() or None

    invoice_dict = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=jc_dict["customer_id"],
        vehicle_rego=jc_dict.get("vehicle_rego"),
        status="draft",
        line_items_data=invoice_line_items,
        fluid_usage_data=fluid_usage_for_invoice,
        notes_customer=clean_notes,
        ip_address=ip_address,
    )

    # Transition job card to invoiced
    result = await db.execute(
        select(JobCard).where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card_obj = result.scalar_one_or_none()
    if job_card_obj is not None:
        job_card_obj.status = "invoiced"
        await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="job_card.converted_to_invoice",
        entity_type="job_card",
        entity_id=job_card_id,
        after_value={
            "invoice_id": str(invoice_dict["id"]),
            "invoice_status": "draft",
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "job_card_id": job_card_id,
        "invoice_id": invoice_dict["id"],
        "invoice_status": "draft",
        "message": "Job card converted to draft invoice",
    }


async def combine_job_cards_to_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_ids: list[uuid.UUID],
    ip_address: str | None = None,
) -> dict:
    """Combine multiple completed job cards into a single Draft invoice.

    All job cards must be in 'completed' status and belong to the same customer.

    Requirements: 59.4
    """
    from app.modules.invoices.service import create_invoice

    if not job_card_ids:
        raise ValueError("At least one job card ID is required")

    # Fetch all job cards
    job_cards_data = []
    for jc_id in job_card_ids:
        jc_dict = await get_job_card(db, org_id=org_id, job_card_id=jc_id)
        job_cards_data.append(jc_dict)

    # Validate all are completed
    for jc in job_cards_data:
        if jc["status"] != "completed":
            raise ValueError(
                f"Job card {jc['id']} has status '{jc['status']}'. "
                "All job cards must be completed to combine into an invoice."
            )

    # Validate all belong to the same customer
    customer_ids = {jc["customer_id"] for jc in job_cards_data}
    if len(customer_ids) > 1:
        raise ValueError(
            "All job cards must belong to the same customer to combine into a single invoice"
        )

    customer_id = job_cards_data[0]["customer_id"]
    # Use vehicle rego from first job card that has one
    vehicle_rego = next(
        (jc.get("vehicle_rego") for jc in job_cards_data if jc.get("vehicle_rego")),
        None,
    )

    # Combine all line items
    invoice_line_items = []
    sort_offset = 0
    for jc in job_cards_data:
        for li in jc.get("line_items", []):
            desc = li["description"]
            desc = re.sub(r'\s*\[📍[^\]]*\]', '', desc).strip()
            invoice_line_items.append({
                "item_type": li["item_type"],
                "description": desc,
                "quantity": li["quantity"],
                "unit_price": li["unit_price"],
                "catalogue_item_id": li.get("catalogue_item_id"),
                "is_gst_exempt": li.get("is_gst_exempt", False),
                "sort_order": sort_offset + li.get("sort_order", 0),
            })
        sort_offset += len(jc.get("line_items", []))

    # Create draft invoice with combined fluid usage from source bookings
    combined_fluid_usage = []
    try:
        from app.modules.bookings.models import Booking
        from app.modules.inventory.stock_items_service import release_reservation
        for jc_id in job_card_ids:
            bk_result = await db.execute(
                select(Booking).where(Booking.converted_job_id == jc_id, Booking.org_id == org_id)
            )
            bk = bk_result.scalar_one_or_none()
            if bk and bk.booking_data_json:
                for f in bk.booking_data_json.get("fluid_usage", []):
                    if f.get("stock_item_id") and f.get("litres", 0) > 0:
                        combined_fluid_usage.append({
                            "stock_item_id": f["stock_item_id"],
                            "catalogue_item_id": f.get("catalogue_item_id", ""),
                            "item_name": f.get("item_name", ""),
                            "litres": f["litres"],
                        })
                        try:
                            await release_reservation(
                                db, org_id=org_id, user_id=user_id,
                                stock_item_id=uuid.UUID(str(f["stock_item_id"])),
                                quantity=float(f["litres"]),
                                reference_type="booking_fluid", reference_id=bk.id,
                            )
                        except Exception:
                            pass
                for bp in bk.booking_data_json.get("parts", []):
                    sid = bp.get("stock_item_id")
                    qty = float(bp.get("quantity", 0))
                    if sid and qty > 0:
                        try:
                            await release_reservation(
                                db, org_id=org_id, user_id=user_id,
                                stock_item_id=uuid.UUID(str(sid)), quantity=qty,
                                reference_type="booking", reference_id=bk.id,
                            )
                        except Exception:
                            pass
    except Exception:
        pass

    invoice_dict = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        status="draft",
        line_items_data=invoice_line_items,
        fluid_usage_data=combined_fluid_usage if combined_fluid_usage else None,
        ip_address=ip_address,
    )

    # Transition all job cards to invoiced
    for jc_id in job_card_ids:
        result = await db.execute(
            select(JobCard).where(
                JobCard.id == jc_id,
                JobCard.org_id == org_id,
            )
        )
        job_card_obj = result.scalar_one_or_none()
        if job_card_obj is not None:
            job_card_obj.status = "invoiced"
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="job_cards.combined_to_invoice",
        entity_type="job_card",
        entity_id=job_card_ids[0],
        after_value={
            "job_card_ids": [str(jc_id) for jc_id in job_card_ids],
            "invoice_id": str(invoice_dict["id"]),
            "invoice_status": "draft",
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "job_card_ids": job_card_ids,
        "invoice_id": invoice_dict["id"],
        "invoice_status": "draft",
        "message": f"{len(job_card_ids)} job cards combined into draft invoice",
    }


def _time_entry_to_dict(entry: TimeEntry) -> dict:
    """Convert a TimeEntry ORM instance to a plain dict."""
    return {
        "id": entry.id,
        "org_id": entry.org_id,
        "job_card_id": entry.job_id,
        "user_id": entry.user_id,
        "started_at": entry.start_time,
        "stopped_at": entry.end_time,
        "duration_minutes": entry.duration_minutes,
        "hourly_rate": entry.hourly_rate,
        "notes": entry.description,
        "created_at": entry.created_at,
    }


async def start_timer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    role: str,
) -> dict:
    """Create a TimeEntry with started_at=now(). Returns TimeEntry dict.

    Raises ValueError if timer already active (maps to 409).
    Raises PermissionError if non-admin user is not the assignee (maps to 403).

    Requirements: 4.6, 7.1, 4.2, 4.3, 8.3
    """
    # Fetch job card (org-scoped)
    result = await db.execute(
        select(JobCard).where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card = result.scalar_one_or_none()
    if job_card is None:
        raise ValueError("Job card not found in this organisation")

    # Permission check: non-admin must be the assignee
    if role != "org_admin":
        from app.modules.staff.models import StaffMember
        staff_result = await db.execute(
            select(StaffMember.id).where(
                StaffMember.user_id == user_id,
                StaffMember.org_id == org_id,
            )
        )
        caller_staff_id = staff_result.scalar_one_or_none()
        if job_card.assigned_to != caller_staff_id:
            raise PermissionError("You can only start jobs assigned to you.")

    # Check for already-active timer
    active_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.job_id == job_card_id,
            TimeEntry.org_id == org_id,
            TimeEntry.end_time.is_(None),
        )
    )
    active_entry = active_result.scalar_one_or_none()
    if active_entry is not None:
        raise ValueError("A timer is already running for this job card")

    # Create new time entry
    now = datetime.now(timezone.utc)
    entry = TimeEntry(
        org_id=org_id,
        user_id=user_id,
        job_id=job_card_id,
        start_time=now,
        end_time=None,
    )
    db.add(entry)

    # Update job card status to in_progress (if not already)
    if job_card.status == "open":
        job_card.status = "in_progress"

    await db.flush()

    return _time_entry_to_dict(entry)

async def stop_timer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    role: str,
) -> dict:
    """Set stopped_at=now() and calculate duration_minutes on active TimeEntry.

    Raises ValueError if no active timer (maps to 404).
    Raises PermissionError if non-admin user is not the assignee (maps to 403).

    Requirements: 4.9, 7.2, 8.9
    """
    # Fetch job card (org-scoped)
    result = await db.execute(
        select(JobCard).where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card = result.scalar_one_or_none()
    if job_card is None:
        raise ValueError("Job card not found in this organisation")

    # Permission check: non-admin must be the assignee
    if role != "org_admin":
        from app.modules.staff.models import StaffMember
        staff_result = await db.execute(
            select(StaffMember.id).where(
                StaffMember.user_id == user_id,
                StaffMember.org_id == org_id,
            )
        )
        caller_staff_id = staff_result.scalar_one_or_none()
        if job_card.assigned_to != caller_staff_id:
            raise PermissionError("You can only stop jobs assigned to you.")

    # Find active timer
    active_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.job_id == job_card_id,
            TimeEntry.org_id == org_id,
            TimeEntry.end_time.is_(None),
        )
    )
    active_entry = active_result.scalar_one_or_none()
    if active_entry is None:
        raise ValueError("No active timer found for this job card")

    # Stop the timer
    now = datetime.now(timezone.utc)
    active_entry.end_time = now
    active_entry.duration_minutes = math.ceil(
        (now - active_entry.start_time).total_seconds() / 60
    )

    await db.flush()

    return _time_entry_to_dict(active_entry)

async def get_timer_entries(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    job_card_id: uuid.UUID,
) -> dict:
    """Return all TimeEntry records for a job card plus active flag.

    Returns a dict with:
      - entries: list of TimeEntry dicts ordered by started_at ascending
      - is_active: True if any entry has stopped_at IS NULL

    Requirements: 7.5, 4.11
    """
    result = await db.execute(
        select(TimeEntry)
        .where(
            TimeEntry.job_id == job_card_id,
            TimeEntry.org_id == org_id,
        )
        .order_by(TimeEntry.start_time.asc())
    )
    entries = result.scalars().all()

    is_active = any(e.end_time is None for e in entries)

    return {
        "entries": [_time_entry_to_dict(e) for e in entries],
        "is_active": is_active,
    }

async def complete_job(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    role: str,
    ip_address: str | None = None,
) -> dict:
    """Stop active timer if any, set status='completed', convert to invoice,
    set status='invoiced'. Returns {job_card_id, invoice_id}.

    If invoice creation fails, the job card remains in 'completed' status
    and the error is re-raised.

    Requirements: 6.2, 6.3, 6.4, 6.5, 6.6
    """
    # Fetch job card (org-scoped)
    result = await db.execute(
        select(JobCard).where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card = result.scalar_one_or_none()
    if job_card is None:
        raise ValueError("Job card not found in this organisation")

    # Stop active timer if one is running (Req 6.2)
    active_result = await db.execute(
        select(TimeEntry).where(
            TimeEntry.job_id == job_card_id,
            TimeEntry.org_id == org_id,
            TimeEntry.end_time.is_(None),
        )
    )
    active_entry = active_result.scalar_one_or_none()
    if active_entry is not None:
        now = datetime.now(timezone.utc)
        active_entry.end_time = now
        active_entry.duration_minutes = math.ceil(
            (now - active_entry.start_time).total_seconds() / 60
        )
        await db.flush()

    # Transition to completed (Req 6.3)
    _validate_status_transition(job_card.status, "completed")
    job_card.status = "completed"
    await db.flush()

    # Create draft invoice via existing conversion (Req 6.4, 6.6)
    try:
        invoice_result = await convert_job_card_to_invoice(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card_id,
            ip_address=ip_address,
        )
    except Exception:
        # Invoice creation failed — keep status as 'completed' (Req 6.5)
        # The convert function may have changed status to 'invoiced' before
        # failing, so reset it.
        job_card.status = "completed"
        await db.flush()
        raise

    # Audit log for completion
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="job_card.completed",
        entity_type="job_card",
        entity_id=job_card_id,
        after_value={
            "status": job_card.status,
            "invoice_id": str(invoice_result["invoice_id"]),
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "job_card_id": job_card_id,
        "invoice_id": invoice_result["invoice_id"],
    }




async def assign_job(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    job_card_id: uuid.UUID,
    role: str,
    new_assignee_id: uuid.UUID,
    takeover_note: str | None = None,
) -> dict:
    """Assign or reassign a job card. Non-admin can only assign to self.
    If takeover_note provided, appends note with previous assignee and timestamp.

    Requirements: 8.5, 8.6, 8.7, 8.8
    """
    from sqlalchemy.orm import selectinload

    # Fetch job card (org-scoped)
    result = await db.execute(
        select(JobCard)
        .options(selectinload(JobCard.customer))
        .where(
            JobCard.id == job_card_id,
            JobCard.org_id == org_id,
        )
    )
    job_card = result.scalar_one_or_none()
    if job_card is None:
        raise ValueError("Job card not found in this organisation")

    # Resolve new_assignee_id: it may be a staff_members.id (from StaffPicker)
    # or a users.id (from "Assign to Me" which sends the logged-in user's ID).
    # We need to ensure it ends up as a valid staff_members.id.
    from app.modules.staff.models import StaffMember

    # First check if new_assignee_id is already a staff_members.id
    direct_result = await db.execute(
        select(StaffMember).where(
            StaffMember.id == new_assignee_id,
            StaffMember.org_id == org_id,
        )
    )
    direct_staff = direct_result.scalar_one_or_none()

    if direct_staff is None:
        # Maybe it's a users.id — try to resolve to staff member
        by_user_result = await db.execute(
            select(StaffMember).where(
                StaffMember.user_id == new_assignee_id,
                StaffMember.org_id == org_id,
            )
        )
        resolved_staff = by_user_result.scalar_one_or_none()
        if resolved_staff is not None:
            new_assignee_id = resolved_staff.id
            direct_staff = resolved_staff
        else:
            raise ValueError("Target assignee is not an active staff member in this organisation")

    # Permission check: non-admin can only assign to self (Req 8.5)
    if role != "org_admin":
        caller_result = await db.execute(
            select(StaffMember.id).where(
                StaffMember.user_id == user_id,
                StaffMember.org_id == org_id,
            )
        )
        caller_staff_id = caller_result.scalar_one_or_none()
        if new_assignee_id != caller_staff_id:
            raise PermissionError("Non-admin users can only assign jobs to themselves.")

    # Admin assigning: verify the target is active
    if role == "org_admin":
        if not direct_staff.is_active:
            raise ValueError("Target assignee is not an active staff member in this organisation")

    # If takeover_note provided, look up previous assignee name and append note (Req 8.8)
    if takeover_note and job_card.assigned_to is not None:
        previous_assignee_name = await _resolve_staff_display_name(db, job_card.assigned_to)
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M UTC")
        note_entry = (
            f"[Takeover {timestamp_str}] Previously assigned to {previous_assignee_name}. "
            f"Note: {takeover_note}"
        )
        if job_card.notes:
            job_card.notes = f"{job_card.notes}\n{note_entry}"
        else:
            job_card.notes = note_entry

    # Update assignment
    job_card.assigned_to = new_assignee_id
    await db.flush()

    # Refresh to load server-generated updated_at
    await db.refresh(job_card)

    # Return updated job card dict
    items_result = await db.execute(
        select(JobCardItem)
        .where(JobCardItem.job_card_id == job_card_id)
        .order_by(JobCardItem.sort_order)
    )
    line_items = list(items_result.scalars().all())

    return _job_card_to_dict(job_card, line_items)


async def _resolve_user_display_name(db: AsyncSession, user_id: uuid.UUID) -> str:
    """Look up a display name for a user — prefer StaffMember.name, fall back to User.email."""
    from app.modules.staff.models import StaffMember
    from app.modules.auth.models import User as AuthUser

    # Try staff member name first
    staff_result = await db.execute(
        select(StaffMember.name).where(StaffMember.user_id == user_id)
    )
    staff_name = staff_result.scalar_one_or_none()
    if staff_name:
        return staff_name

    # Fall back to user email
    user_result = await db.execute(
        select(AuthUser.email).where(AuthUser.id == user_id)
    )
    email = user_result.scalar_one_or_none()
    return email or "Unknown user"

async def _resolve_staff_display_name(db: AsyncSession, staff_id: uuid.UUID) -> str:
    """Look up a display name for a staff member by staff_members.id."""
    from app.modules.staff.models import StaffMember

    result = await db.execute(
        select(StaffMember.name).where(StaffMember.id == staff_id)
    )
    name = result.scalar_one_or_none()
    return name or "Unknown staff member"


