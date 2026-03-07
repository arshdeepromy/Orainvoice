"""Business logic for Quote module — creation, numbering, status lifecycle.

Requirements: 58.1, 58.2, 58.4, 58.6
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, text, func as sa_func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer
from app.modules.quotes.models import Quote, QuoteLineItem


TWO_PLACES = Decimal("0.01")

# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"sent", "accepted", "declined"},
    "sent": {"accepted", "declined", "expired"},
    "accepted": set(),
    "declined": set(),
    "expired": set(),
}


def _calculate_line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Calculate the total for a single quote line item (ex-GST)."""
    return (quantity * unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _calculate_quote_totals(
    line_items_data: list[dict],
    gst_rate: Decimal,
) -> dict:
    """Calculate subtotal, GST, total for a quote."""
    line_totals: list[Decimal] = []
    subtotal = Decimal("0")
    gst_amount = Decimal("0")

    for item in line_items_data:
        lt = _calculate_line_total(item["quantity"], item["unit_price"])
        line_totals.append(lt)
        subtotal += lt

    # GST on non-exempt items
    taxable_subtotal = Decimal("0")
    for i, item in enumerate(line_items_data):
        if not item.get("is_gst_exempt", False):
            taxable_subtotal += line_totals[i]

    if taxable_subtotal > 0:
        gst_amount = (taxable_subtotal * gst_rate / Decimal("100")).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

    total = (subtotal + gst_amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return {
        "subtotal": subtotal.quantize(TWO_PLACES),
        "gst_amount": gst_amount,
        "total": total,
        "line_totals": line_totals,
    }


def _validate_status_transition(current: str, target: str) -> None:
    """Validate a quote status transition."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Cannot transition quote from '{current}' to '{target}'"
        )


async def _get_next_quote_number(
    db: AsyncSession,
    org_id: uuid.UUID,
    prefix: str,
) -> str:
    """Assign the next gap-free quote number using SELECT ... FOR UPDATE.

    Requirements: 58.6
    """
    result = await db.execute(
        text(
            "SELECT id, last_number FROM quote_sequences "
            "WHERE org_id = :org_id FOR UPDATE"
        ),
        {"org_id": str(org_id)},
    )
    row = result.first()

    if row is None:
        seq_id = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO quote_sequences (id, org_id, last_number) "
                "VALUES (:id, :org_id, 1)"
            ),
            {"id": str(seq_id), "org_id": str(org_id)},
        )
        next_number = 1
    else:
        next_number = row.last_number + 1
        await db.execute(
            text(
                "UPDATE quote_sequences SET last_number = :num "
                "WHERE id = :id"
            ),
            {"num": next_number, "id": str(row.id)},
        )

    return f"{prefix}{next_number:04d}"


def _quote_to_dict(quote: Quote, line_items: list[QuoteLineItem]) -> dict:
    """Convert Quote + QuoteLineItems to a serialisable dict."""
    return {
        "id": quote.id,
        "org_id": quote.org_id,
        "customer_id": quote.customer_id,
        "quote_number": quote.quote_number,
        "vehicle_rego": quote.vehicle_rego,
        "vehicle_make": quote.vehicle_make,
        "vehicle_model": quote.vehicle_model,
        "vehicle_year": quote.vehicle_year,
        "status": quote.status,
        "valid_until": quote.valid_until,
        "subtotal": quote.subtotal,
        "gst_amount": quote.gst_amount,
        "total": quote.total,
        "notes": quote.notes,
        "line_items": [_line_item_to_dict(li) for li in line_items],
        "created_by": quote.created_by,
        "created_at": quote.created_at,
        "updated_at": quote.updated_at,
    }


def _line_item_to_dict(li: QuoteLineItem) -> dict:
    """Convert a QuoteLineItem to a serialisable dict."""
    return {
        "id": li.id,
        "item_type": li.item_type,
        "description": li.description,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "hours": li.hours,
        "hourly_rate": li.hourly_rate,
        "is_gst_exempt": li.is_gst_exempt,
        "warranty_note": li.warranty_note,
        "line_total": li.line_total,
        "sort_order": li.sort_order,
    }


async def create_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    vehicle_rego: str | None = None,
    vehicle_make: str | None = None,
    vehicle_model: str | None = None,
    vehicle_year: int | None = None,
    validity_days: int = 30,
    line_items_data: list[dict] | None = None,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new quote in Draft status.

    Assigns a sequential quote number with the org's quote prefix.

    Requirements: 58.1, 58.4, 58.6
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

    # Get org settings for GST rate and quote prefix
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    org_settings = org.settings or {}
    gst_rate = Decimal(str(org_settings.get("gst_percentage", 15)))
    quote_prefix = org_settings.get("quote_prefix", "QT-")

    # Calculate totals
    items = line_items_data or []
    totals = _calculate_quote_totals(items, gst_rate)

    # Assign quote number
    quote_number = await _get_next_quote_number(db, org_id, quote_prefix)

    # Calculate valid_until date
    valid_until = date.today() + timedelta(days=validity_days)

    # Create quote record
    quote = Quote(
        org_id=org_id,
        customer_id=customer_id,
        quote_number=quote_number,
        vehicle_rego=vehicle_rego,
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_year=vehicle_year,
        status="draft",
        valid_until=valid_until,
        subtotal=totals["subtotal"],
        gst_amount=totals["gst_amount"],
        total=totals["total"],
        notes=notes,
        created_by=user_id,
    )
    db.add(quote)
    await db.flush()

    # Create line items
    created_line_items: list[QuoteLineItem] = []
    for i, item_data in enumerate(items):
        li = QuoteLineItem(
            quote_id=quote.id,
            org_id=org_id,
            item_type=item_data["item_type"],
            description=item_data["description"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
            hours=item_data.get("hours"),
            hourly_rate=item_data.get("hourly_rate"),
            is_gst_exempt=item_data.get("is_gst_exempt", False),
            warranty_note=item_data.get("warranty_note"),
            line_total=totals["line_totals"][i],
            sort_order=item_data.get("sort_order", i),
        )
        db.add(li)
        await db.flush()
        created_line_items.append(li)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="quote.created",
        entity_type="quote",
        entity_id=quote.id,
        after_value={
            "status": "draft",
            "quote_number": quote_number,
            "customer_id": str(customer_id),
            "total": str(totals["total"]),
            "validity_days": validity_days,
            "valid_until": str(valid_until),
            "line_item_count": len(items),
        },
        ip_address=ip_address,
    )

    return _quote_to_dict(quote, created_line_items)


async def get_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    quote_id: uuid.UUID,
) -> dict:
    """Retrieve a single quote by ID within an organisation."""
    q_result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = q_result.scalar_one_or_none()
    if quote is None:
        raise ValueError("Quote not found in this organisation")

    li_result = await db.execute(
        select(QuoteLineItem)
        .where(QuoteLineItem.quote_id == quote.id)
        .order_by(QuoteLineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    return _quote_to_dict(quote, line_items)


async def list_quotes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Search and filter quotes with pagination."""
    base_filter = [Quote.org_id == org_id]

    if status:
        base_filter.append(Quote.status == status)

    if search:
        search_term = f"%{search}%"
        base_filter.append(
            or_(
                Quote.quote_number.ilike(search_term),
                Quote.vehicle_rego.ilike(search_term),
                Customer.first_name.ilike(search_term),
                Customer.last_name.ilike(search_term),
                (Customer.first_name + " " + Customer.last_name).ilike(search_term),
            )
        )

    # Count query
    count_q = (
        select(sa_func.count(Quote.id))
        .join(Customer, Quote.customer_id == Customer.id, isouter=True)
        .where(*base_filter)
    )
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Data query
    data_q = (
        select(
            Quote.id,
            Quote.quote_number,
            Customer.first_name,
            Customer.last_name,
            Quote.vehicle_rego,
            Quote.total,
            Quote.status,
            Quote.valid_until,
        )
        .join(Customer, Quote.customer_id == Customer.id, isouter=True)
        .where(*base_filter)
        .order_by(Quote.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await db.execute(data_q)

    quotes = []
    for row in rows:
        first = row.first_name or ""
        last = row.last_name or ""
        customer_name = f"{first} {last}".strip() or None
        quotes.append(
            {
                "id": row.id,
                "quote_number": row.quote_number,
                "customer_name": customer_name,
                "vehicle_rego": row.vehicle_rego,
                "total": row.total,
                "status": row.status,
                "valid_until": row.valid_until,
            }
        )

    return {
        "quotes": quotes,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def update_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    quote_id: uuid.UUID,
    updates: dict,
    ip_address: str | None = None,
) -> dict:
    """Update a quote with status validation.

    Draft quotes allow full edits. Status transitions are validated
    against the allowed transition map.

    Requirements: 58.2
    """
    q_result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = q_result.scalar_one_or_none()
    if quote is None:
        raise ValueError("Quote not found in this organisation")

    before_value = {
        "status": quote.status,
        "customer_id": str(quote.customer_id),
        "vehicle_rego": quote.vehicle_rego,
        "notes": quote.notes,
        "valid_until": str(quote.valid_until) if quote.valid_until else None,
    }

    # Handle status transition
    new_status = updates.get("status")
    if new_status and new_status != quote.status:
        _validate_status_transition(quote.status, new_status)
        quote.status = new_status

    # Only draft quotes allow structural edits
    if quote.status == "draft":
        for field in ("customer_id", "vehicle_rego", "vehicle_make",
                       "vehicle_model", "vehicle_year", "notes"):
            if field in updates and updates[field] is not None:
                setattr(quote, field, updates[field])

        # Update validity period
        if "validity_days" in updates and updates["validity_days"] is not None:
            quote.valid_until = date.today() + timedelta(days=updates["validity_days"])

        # Replace line items if provided
        if "line_items" in updates and updates["line_items"] is not None:
            # Get org settings for GST rate
            org_result = await db.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org = org_result.scalar_one_or_none()
            org_settings = org.settings or {} if org else {}
            gst_rate = Decimal(str(org_settings.get("gst_percentage", 15)))

            # Delete existing line items
            existing = await db.execute(
                select(QuoteLineItem).where(QuoteLineItem.quote_id == quote.id)
            )
            for li in existing.scalars().all():
                await db.delete(li)
            await db.flush()

            # Create new line items and recalculate totals
            items = updates["line_items"]
            totals = _calculate_quote_totals(items, gst_rate)
            quote.subtotal = totals["subtotal"]
            quote.gst_amount = totals["gst_amount"]
            quote.total = totals["total"]

            for i, item_data in enumerate(items):
                li = QuoteLineItem(
                    quote_id=quote.id,
                    org_id=org_id,
                    item_type=item_data["item_type"],
                    description=item_data["description"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    hours=item_data.get("hours"),
                    hourly_rate=item_data.get("hourly_rate"),
                    is_gst_exempt=item_data.get("is_gst_exempt", False),
                    warranty_note=item_data.get("warranty_note"),
                    line_total=totals["line_totals"][i],
                    sort_order=item_data.get("sort_order", i),
                )
                db.add(li)
            await db.flush()
    elif new_status is None:
        # Non-draft quotes only allow notes updates
        if "notes" in updates:
            quote.notes = updates["notes"]

    await db.flush()

    # Audit log
    after_value = {
        "status": quote.status,
        "customer_id": str(quote.customer_id),
        "vehicle_rego": quote.vehicle_rego,
        "notes": quote.notes,
        "valid_until": str(quote.valid_until) if quote.valid_until else None,
    }
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="quote.updated",
        entity_type="quote",
        entity_id=quote.id,
        before_value=before_value,
        after_value=after_value,
        ip_address=ip_address,
    )

    # Reload line items
    li_result = await db.execute(
        select(QuoteLineItem)
        .where(QuoteLineItem.quote_id == quote.id)
        .order_by(QuoteLineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    return _quote_to_dict(quote, line_items)


async def expire_quotes(db: AsyncSession) -> int:
    """Auto-expire quotes past their valid_until date.

    Called by a scheduled task. Only transitions 'sent' quotes to 'expired'.

    Requirements: 58.4
    """
    today = date.today()
    result = await db.execute(
        select(Quote).where(
            Quote.status == "sent",
            Quote.valid_until < today,
        )
    )
    quotes = list(result.scalars().all())
    count = 0
    for quote in quotes:
        quote.status = "expired"
        count += 1
    if count:
        await db.flush()
    return count


async def generate_quote_pdf(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    quote_id: uuid.UUID,
) -> bytes:
    """Generate a branded PDF for a quote on-the-fly using WeasyPrint.

    The PDF is rendered from the stored quote data combined with current
    organisation branding. The result is returned as raw bytes and is
    never written to permanent storage.

    Requirements: 58.3
    """
    import pathlib

    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    # Fetch quote
    quote_dict = await get_quote(db, org_id=org_id, quote_id=quote_id)

    # Fetch organisation branding
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    settings = org.settings or {}
    org_context = {
        "name": org.name,
        "logo_url": settings.get("logo_url"),
        "primary_colour": settings.get("primary_colour", "#1a1a1a"),
        "secondary_colour": settings.get("secondary_colour"),
        "address": settings.get("address"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
        "gst_number": settings.get("gst_number"),
        "invoice_footer": settings.get("invoice_footer"),
    }

    gst_percentage = settings.get("gst_percentage", 15)
    terms_and_conditions = settings.get("terms_and_conditions", "")

    # Fetch customer
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == quote_dict["customer_id"],
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    customer_context = {
        "first_name": customer.first_name if customer else "Unknown",
        "last_name": customer.last_name if customer else "",
        "email": customer.email if customer else None,
        "phone": customer.phone if customer else None,
        "address": customer.address if customer else None,
    }

    # Render HTML
    template_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("quote.html")

    html_content = template.render(
        quote=quote_dict,
        org=org_context,
        customer=customer_context,
        gst_percentage=gst_percentage,
        terms_and_conditions=terms_and_conditions,
    )

    # Generate PDF (in-memory only)
    pdf_bytes: bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes


async def send_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    quote_id: uuid.UUID,
    recipient_email: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Generate a branded PDF quote and email it to the customer.

    Transitions the quote status from Draft to Sent.
    If *recipient_email* is not provided, the customer's email on file is used.

    Requirements: 58.3
    """
    # Fetch quote
    quote_dict = await get_quote(db, org_id=org_id, quote_id=quote_id)

    # Only draft or sent quotes can be (re-)sent
    if quote_dict["status"] not in ("draft", "sent"):
        raise ValueError(
            f"Cannot send a quote with status '{quote_dict['status']}'. "
            "Only draft or sent quotes can be sent."
        )

    # Resolve recipient email
    if recipient_email is None:
        cust_result = await db.execute(
            select(Customer).where(
                Customer.id == quote_dict["customer_id"],
                Customer.org_id == org_id,
            )
        )
        customer = cust_result.scalar_one_or_none()
        if customer is None or not customer.email:
            raise ValueError(
                "Customer has no email address on file. Provide a recipient_email."
            )
        recipient_email = customer.email

    # Generate PDF
    pdf_bytes = await generate_quote_pdf(db, org_id=org_id, quote_id=quote_id)

    # Transition status to "sent" if currently draft
    if quote_dict["status"] == "draft":
        result = await db.execute(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.org_id == org_id,
            )
        )
        quote_obj = result.scalar_one_or_none()
        if quote_obj is not None:
            quote_obj.status = "sent"
            await db.flush()

    # Audit log
    await write_audit_log(
        db,
        action="quote.sent",
        entity_type="quote",
        entity_id=quote_id,
        org_id=org_id,
        user_id=user_id,
        after_value={
            "recipient": recipient_email,
            "quote_number": quote_dict["quote_number"],
            "pdf_size_bytes": len(pdf_bytes),
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "quote_id": quote_id,
        "quote_number": quote_dict["quote_number"],
        "recipient_email": recipient_email,
        "pdf_size_bytes": len(pdf_bytes),
        "status": "queued",
    }


async def convert_quote_to_invoice(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    quote_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Convert an accepted/sent quote to a Draft invoice pre-filled with all quote details.

    The quote must be in 'sent' or 'accepted' status. Creates a new Draft
    invoice with the same customer, vehicle, and line items.

    Requirements: 58.5
    """
    from app.modules.invoices.service import create_invoice

    # Fetch quote with line items
    quote_dict = await get_quote(db, org_id=org_id, quote_id=quote_id)

    # Only sent or accepted quotes can be converted
    if quote_dict["status"] not in ("sent", "accepted"):
        raise ValueError(
            f"Cannot convert a quote with status '{quote_dict['status']}'. "
            "Only sent or accepted quotes can be converted to invoices."
        )

    # Build line items data for invoice creation
    invoice_line_items = []
    for li in quote_dict.get("line_items", []):
        invoice_line_items.append({
            "item_type": li["item_type"],
            "description": li["description"],
            "quantity": li["quantity"],
            "unit_price": li["unit_price"],
            "hours": li.get("hours"),
            "hourly_rate": li.get("hourly_rate"),
            "is_gst_exempt": li.get("is_gst_exempt", False),
            "warranty_note": li.get("warranty_note"),
            "sort_order": li.get("sort_order", 0),
        })

    # Create draft invoice with quote details
    invoice_dict = await create_invoice(
        db,
        org_id=org_id,
        user_id=user_id,
        customer_id=quote_dict["customer_id"],
        vehicle_rego=quote_dict.get("vehicle_rego"),
        vehicle_make=quote_dict.get("vehicle_make"),
        vehicle_model=quote_dict.get("vehicle_model"),
        vehicle_year=quote_dict.get("vehicle_year"),
        status="draft",
        line_items_data=invoice_line_items,
        notes_customer=quote_dict.get("notes"),
        ip_address=ip_address,
    )

    # Update quote status to accepted if it was sent
    if quote_dict["status"] == "sent":
        result = await db.execute(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.org_id == org_id,
            )
        )
        quote_obj = result.scalar_one_or_none()
        if quote_obj is not None:
            quote_obj.status = "accepted"
            await db.flush()

    # Audit log
    await write_audit_log(
        db,
        action="quote.converted_to_invoice",
        entity_type="quote",
        entity_id=quote_id,
        org_id=org_id,
        user_id=user_id,
        after_value={
            "quote_number": quote_dict["quote_number"],
            "invoice_id": str(invoice_dict["id"]),
            "invoice_status": "draft",
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "quote_id": quote_id,
        "quote_number": quote_dict["quote_number"],
        "invoice_id": invoice_dict["id"],
        "invoice_status": "draft",
        "message": f"Quote {quote_dict['quote_number']} converted to draft invoice",
    }
