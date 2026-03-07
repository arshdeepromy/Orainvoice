"""Business logic for Job Card module — creation, status lifecycle, listing.

Requirements: 59.1, 59.2, 59.5
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func as sa_func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.customers.models import Customer
from app.modules.job_cards.models import JobCard, JobCardItem


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
    return {
        "id": job_card.id,
        "org_id": job_card.org_id,
        "customer_id": job_card.customer_id,
        "vehicle_rego": job_card.vehicle_rego,
        "status": job_card.status,
        "description": job_card.description,
        "notes": job_card.notes,
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

    job_card = JobCard(
        org_id=org_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        status="open",
        description=description,
        notes=notes,
        created_by=user_id,
    )
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

    return _job_card_to_dict(job_card, created_items)


async def get_job_card(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    job_card_id: uuid.UUID,
) -> dict:
    """Retrieve a single job card by ID within an organisation."""
    result = await db.execute(
        select(JobCard).where(
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

    return _job_card_to_dict(job_card, line_items)


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
        base_filter.append(JobCard.status == status)
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

    # Data query
    data_q = (
        select(
            JobCard.id,
            Customer.first_name,
            Customer.last_name,
            JobCard.vehicle_rego,
            JobCard.status,
            JobCard.description,
            JobCard.created_at,
        )
        .join(Customer, JobCard.customer_id == Customer.id, isouter=True)
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
    result = await db.execute(
        select(JobCard).where(
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

    # Build invoice line items from job card items
    invoice_line_items = []
    for li in jc_dict.get("line_items", []):
        invoice_line_items.append({
            "item_type": li["item_type"],
            "description": li["description"],
            "quantity": li["quantity"],
            "unit_price": li["unit_price"],
            "is_gst_exempt": li.get("is_gst_exempt", False),
            "sort_order": li.get("sort_order", 0),
        })

    # Create draft invoice
    invoice_dict = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=jc_dict["customer_id"],
        vehicle_rego=jc_dict.get("vehicle_rego"),
        status="draft",
        line_items_data=invoice_line_items,
        notes_customer=jc_dict.get("notes"),
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
            invoice_line_items.append({
                "item_type": li["item_type"],
                "description": li["description"],
                "quantity": li["quantity"],
                "unit_price": li["unit_price"],
                "is_gst_exempt": li.get("is_gst_exempt", False),
                "sort_order": sort_offset + li.get("sort_order", 0),
            })
        sort_offset += len(jc.get("line_items", []))

    # Create draft invoice
    invoice_dict = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=customer_id,
        vehicle_rego=vehicle_rego,
        status="draft",
        line_items_data=invoice_line_items,
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
