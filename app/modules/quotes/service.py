"""Business logic for Quote module — creation, numbering, status lifecycle.

Requirements: 58.1, 58.2, 58.4, 58.6
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select, text, func as sa_func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.admin.models import Organisation
from app.modules.auth.models import User
from app.modules.customers.address_utils import resolve_customer_display_address
from app.modules.customers.models import Customer
from app.modules.quotes.attachment_models import QuoteAttachment
from app.modules.quotes.attachment_service import get_attachment_count
from app.modules.quotes.models import Quote, QuoteLineItem


TWO_PLACES = Decimal("0.01")
GST_RATE_DECIMAL = Decimal("0.15")
GST_DIVISOR = Decimal("1.15")

# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"issued", "sent", "accepted", "declined"},
    "issued": {"draft", "sent", "accepted", "declined", "expired", "cancelled"},
    "sent": {"draft", "accepted", "declined", "expired", "cancelled"},
    "accepted": set(),
    "declined": set(),
    "expired": set(),
    "cancelled": set(),  # terminal state
}


def _resolve_document_settings(
    org_settings: Mapping[str, Any] | None,
    *,
    per_quote_terms: str | None,
) -> dict[str, object]:
    """Resolve render-time Payment Terms and Terms & Conditions for a quote.

    Mirrors the invoice service's behaviour at:
      - app/modules/invoices/service.py:1764-1775 (detail response)
      - app/modules/invoices/service.py:4153-4161 (PDF render)

    Both the API response builder (``get_quote``) and the PDF generator
    (``generate_quote_pdf``) MUST call this helper so the on-screen quote
    and the PDF cannot drift.

    Parameters
    ----------
    org_settings:
        The organisation's ``settings`` mapping (typically ``Organisation.settings``).
        ``None`` is treated as an empty mapping so organisations without a
        settings row resolve to safe defaults.
    per_quote_terms:
        The per-quote Terms & Conditions override stored on ``quotes.terms``.
        Whitespace-only strings are treated as empty.

    Returns
    -------
    dict[str, object]
        ``{"payment_terms_text": str | None,
           "terms_and_conditions": str | None,
           "terms_and_conditions_enabled": bool}``

    Resolution rules
    ----------------
    payment_terms_text:
        non-empty ``settings["payment_terms_text"]`` when
        ``settings.get("payment_terms_enabled", True)`` is true,
        else ``None``.

    terms_and_conditions_enabled:
        ``bool(settings.get("terms_and_conditions_enabled", True))``.

    terms_and_conditions:
        ``per_quote_terms`` if non-empty (regardless of toggle);
        else ``settings["terms_and_conditions"]`` if the toggle is true and
        the value is non-empty;
        else ``None``.

    The helper is total over its declared input domain and does not raise.
    """
    settings: Mapping[str, Any] = org_settings if org_settings is not None else {}

    def _clean(value: object) -> str | None:
        """Return ``value`` as a stripped non-empty string, else ``None``."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
        return None

    # Payment terms — gated by payment_terms_enabled (default True).
    payment_terms_enabled = bool(settings.get("payment_terms_enabled", True))
    if payment_terms_enabled:
        payment_terms_text = _clean(settings.get("payment_terms_text"))
    else:
        payment_terms_text = None

    # Terms & Conditions toggle — surfaced on the response so the frontend
    # can gate its rendering even when no resolved string is present.
    terms_and_conditions_enabled = bool(
        settings.get("terms_and_conditions_enabled", True)
    )

    # Terms & Conditions resolution: per-quote override wins, then org-level
    # value when enabled, else None.
    per_quote_clean = _clean(per_quote_terms)
    if per_quote_clean is not None:
        terms_and_conditions: str | None = per_quote_clean
    elif terms_and_conditions_enabled:
        terms_and_conditions = _clean(settings.get("terms_and_conditions"))
    else:
        terms_and_conditions = None

    return {
        "payment_terms_text": payment_terms_text,
        "terms_and_conditions": terms_and_conditions,
        "terms_and_conditions_enabled": terms_and_conditions_enabled,
    }


def _calculate_line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """Calculate the total for a single quote line item (ex-GST)."""
    return (quantity * unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _calculate_quote_totals(
    line_items_data: list[dict],
    gst_rate: Decimal,
) -> dict:
    """Calculate subtotal, GST, total for a quote.

    Supports GST-inclusive lines: when a line has gst_inclusive=True and
    inclusive_price is set, unit_price is back-calculated as
    inclusive_price / 1.15 (rounded half-up to 2 d.p.), and GST on that
    line = line_total * 0.15 (rounded half-up to 2 d.p.).
    """
    line_totals: list[Decimal] = []
    line_unit_prices: list[Decimal] = []
    subtotal = Decimal("0")
    gst_amount = Decimal("0")

    for item in line_items_data:
        quantity = Decimal(str(item["quantity"]))
        gst_inclusive = item.get("gst_inclusive", False)
        inclusive_price = item.get("inclusive_price")

        if gst_inclusive and inclusive_price is not None:
            # GST-inclusive back-calculation
            inc_price = Decimal(str(inclusive_price))
            unit_price = (inc_price / GST_DIVISOR).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            lt = (quantity * unit_price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            line_gst = (lt * GST_RATE_DECIMAL).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            gst_amount += line_gst
        else:
            unit_price = Decimal(str(item["unit_price"]))
            lt = _calculate_line_total(quantity, unit_price)
            # GST on non-exempt items (per-line)
            if not item.get("is_gst_exempt", False):
                line_gst = (lt * GST_RATE_DECIMAL).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                gst_amount += line_gst

        line_totals.append(lt)
        line_unit_prices.append(unit_price)
        subtotal += lt

    total = (subtotal + gst_amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return {
        "subtotal": subtotal.quantize(TWO_PLACES),
        "gst_amount": gst_amount.quantize(TWO_PLACES),
        "total": total,
        "line_totals": line_totals,
        "line_unit_prices": line_unit_prices,
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
        "vehicle_odometer": quote.vehicle_odometer,
        "vehicle_wof_expiry": quote.vehicle_wof_expiry,
        "vehicle_cof_expiry": quote.vehicle_cof_expiry,
        "project_id": quote.project_id,
        "status": quote.status,
        "valid_until": quote.valid_until,
        "subtotal": quote.subtotal,
        "gst_amount": quote.gst_amount,
        "total": quote.total,
        "discount_type": quote.discount_type,
        "discount_value": quote.discount_value,
        "discount_amount": quote.discount_amount,
        "shipping_charges": quote.shipping_charges,
        "adjustment": quote.adjustment,
        "notes": quote.notes,
        "terms": quote.terms,
        "subject": quote.subject,
        "acceptance_token": quote.acceptance_token,
        "converted_invoice_id": quote.converted_invoice_id,
        "order_number": quote.order_number,
        "salesperson_id": quote.salesperson_id,
        "additional_vehicles": quote.additional_vehicles or [],
        "fluid_usage": quote.fluid_usage or [],
        "cancel_reason": quote.cancel_reason,
        "cancelled_at": quote.cancelled_at,
        "cancelled_by": quote.cancelled_by,
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
        "catalogue_item_id": li.catalogue_item_id,
        "stock_item_id": li.stock_item_id,
        "gst_inclusive": li.gst_inclusive,
        "inclusive_price": li.inclusive_price,
        "tax_rate": li.tax_rate,
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
    vehicle_odometer: int | None = None,
    vehicle_wof_expiry: date | None = None,
    vehicle_cof_expiry: date | None = None,
    validity_days: int = 30,
    line_items_data: list[dict] | None = None,
    notes: str | None = None,
    terms: str | None = None,
    subject: str | None = None,
    project_id: uuid.UUID | None = None,
    discount_type: str | None = "percentage",
    discount_value: Decimal | None = None,
    shipping_charges: Decimal | None = None,
    adjustment: Decimal | None = None,
    ip_address: str | None = None,
    branch_id: uuid.UUID | None = None,
    order_number: str | None = None,
    salesperson_id: uuid.UUID | None = None,
    additional_vehicles_data: list[dict] | None = None,
    fluid_usage_data: list[dict] | None = None,
    save_terms_as_default: bool = False,
) -> dict:
    """Create a new quote in Draft status.

    Assigns a sequential quote number with the org's quote prefix.

    Requirements: 58.1, 58.4, 58.6
    """
    # Validate branch is active if provided (Req 2.2)
    if branch_id is not None:
        from app.core.branch_validation import validate_branch_active
        await validate_branch_active(db, branch_id)

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

    # Apply discount, shipping, adjustment
    _discount_value = Decimal(str(discount_value or 0))
    _discount_type = discount_type or "percentage"
    if _discount_type == "percentage":
        _discount_amount = (totals["subtotal"] * _discount_value / Decimal("100")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        _discount_amount = _discount_value.quantize(TWO_PLACES)
    _shipping = Decimal(str(shipping_charges or 0)).quantize(TWO_PLACES)
    _adjustment = Decimal(str(adjustment or 0)).quantize(TWO_PLACES)

    final_total = (totals["subtotal"] - _discount_amount + totals["gst_amount"] + _shipping + _adjustment).quantize(TWO_PLACES)

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
        vehicle_odometer=vehicle_odometer,
        vehicle_wof_expiry=vehicle_wof_expiry,
        vehicle_cof_expiry=vehicle_cof_expiry,
        project_id=project_id,
        branch_id=branch_id,
        status="draft",
        valid_until=valid_until,
        subtotal=totals["subtotal"],
        gst_amount=totals["gst_amount"],
        total=final_total,
        discount_type=_discount_type,
        discount_value=_discount_value,
        discount_amount=_discount_amount,
        shipping_charges=_shipping,
        adjustment=_adjustment,
        notes=notes,
        terms=terms,
        subject=subject,
        created_by=user_id,
        order_number=order_number,
        salesperson_id=salesperson_id,
        additional_vehicles=additional_vehicles_data,
        fluid_usage=fluid_usage_data,
    )
    db.add(quote)
    await db.flush()
    await db.refresh(quote)

    # Create line items
    created_line_items: list[QuoteLineItem] = []
    for i, item_data in enumerate(items):
        li = QuoteLineItem(
            quote_id=quote.id,
            org_id=org_id,
            item_type=item_data["item_type"],
            description=item_data["description"],
            quantity=item_data["quantity"],
            unit_price=totals["line_unit_prices"][i],
            hours=item_data.get("hours"),
            hourly_rate=item_data.get("hourly_rate"),
            is_gst_exempt=item_data.get("is_gst_exempt", False),
            warranty_note=item_data.get("warranty_note"),
            line_total=totals["line_totals"][i],
            sort_order=item_data.get("sort_order", i),
            catalogue_item_id=item_data.get("catalogue_item_id"),
            stock_item_id=item_data.get("stock_item_id"),
            gst_inclusive=item_data.get("gst_inclusive", False),
            inclusive_price=item_data.get("inclusive_price"),
            tax_rate=Decimal(str(item_data.get("tax_rate", 15))),
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

    # Save terms as org default if requested (task 5.4)
    if save_terms_as_default and terms:
        org_settings = dict(org.settings or {})
        org_settings["terms_and_conditions"] = terms
        org.settings = org_settings
        await db.flush()

        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="org.settings_updated",
            entity_type="organisation",
            entity_id=org_id,
            after_value={"terms_and_conditions": terms},
            ip_address=ip_address,
        )

    result = _quote_to_dict(quote, created_line_items)
    # Resolve per-document settings so the create response shape matches
    # get_quote / update_quote / cancel_quote (Requirement 5.6).
    result.update(
        _resolve_document_settings(org.settings, per_quote_terms=quote.terms)
    )
    return result


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

    result = _quote_to_dict(quote, line_items)

    # Enrich with salesperson name (task 5.5)
    salesperson_name: str | None = None
    if quote.salesperson_id:
        sp_result = await db.execute(
            select(User.first_name, User.last_name, User.email)
            .where(User.id == quote.salesperson_id)
        )
        sp_row = sp_result.first()
        if sp_row:
            first = sp_row.first_name or ""
            last = sp_row.last_name or ""
            name = f"{first} {last}".strip()
            salesperson_name = name if name else sp_row.email
    result["salesperson_name"] = salesperson_name

    # Enrich with attachment count (task 5.5)
    result["attachment_count"] = await get_attachment_count(
        db, org_id=org_id, quote_id=quote_id
    )

    # Include customer portal token info for mobile share link
    if quote.customer_id:
        cust_result = await db.execute(
            select(Customer).where(Customer.id == quote.customer_id)
        )
        customer = cust_result.scalar_one_or_none()
        if customer:
            result["customer_portal_token"] = str(customer.portal_token) if customer.portal_token else None
            result["customer_enable_portal"] = bool(customer.enable_portal)
            result["customer_name"] = (
                customer.display_name
                or f"{customer.first_name or ''} {customer.last_name or ''}".strip()
                or None
            )
            result["customer_email"] = customer.email

    # Enrich with org info for template preview (mirrors invoice detail)
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org:
        settings = org.settings or {}
        result["org_name"] = org.name
        result["org_address"] = ", ".join(filter(None, [
            settings.get("address_unit"),
            settings.get("address_street"),
            settings.get("address_city"),
            settings.get("address_state"),
            settings.get("address_postcode"),
            settings.get("address_country"),
        ])) or settings.get("address") or settings.get("business_address")
        result["org_address_unit"] = settings.get("address_unit")
        result["org_address_street"] = settings.get("address_street")
        result["org_address_city"] = settings.get("address_city")
        result["org_address_state"] = settings.get("address_state")
        result["org_address_country"] = settings.get("address_country")
        result["org_address_postcode"] = settings.get("address_postcode")
        result["org_phone"] = settings.get("phone") or settings.get("business_phone")
        result["org_email"] = settings.get("email") or settings.get("business_email")
        result["org_logo_url"] = settings.get("logo_url")
        result["org_gst_number"] = settings.get("gst_number") or settings.get("tax_number")
        result["org_website"] = settings.get("website")
        result["invoice_template_id"] = settings.get("invoice_template_id")
        result["invoice_template_colours"] = settings.get("invoice_template_colours")

        # Payment terms + per-quote Terms & Conditions resolution.
        # Single source of truth shared with generate_quote_pdf so the
        # on-screen quote and the PDF cannot drift (Requirements 3.4, 4.6, 5.6).
        resolved = _resolve_document_settings(org.settings, per_quote_terms=quote.terms)
        result.update(resolved)

    return result


async def list_quotes(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    search: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Search and filter quotes with pagination."""
    base_filter = [Quote.org_id == org_id]

    # Branch filter — include NULL branch_id records (legacy/org-wide)
    if branch_id is not None:
        base_filter.append(or_(Quote.branch_id == branch_id, Quote.branch_id.is_(None)))

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
    attachment_count_subq = (
        select(sa_func.count(QuoteAttachment.id))
        .where(QuoteAttachment.quote_id == Quote.id)
        .correlate(Quote)
        .scalar_subquery()
        .label("attachment_count")
    )

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
            Quote.created_at,
            attachment_count_subq,
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
        # Summary view only — list rows intentionally omit ``payment_terms_text``,
        # ``terms_and_conditions``, and ``terms_and_conditions_enabled`` because
        # ``QuoteSearchResult`` exposes only the columns needed by the list UI
        # (id, status, totals, customer name, vehicle rego). The full document
        # settings live on ``GET /quotes/{id}`` via ``get_quote`` and on the PDF
        # via ``generate_quote_pdf``; both paths share ``_resolve_document_settings``.
        # See requirements.md §5.6 and design.md "Testing Strategy".
        quotes.append(
            {
                "id": row.id,
                "quote_number": row.quote_number,
                "customer_name": customer_name,
                "vehicle_rego": row.vehicle_rego,
                "total": row.total,
                "status": row.status,
                "valid_until": row.valid_until,
                "created_at": row.created_at,
                "attachment_count": row.attachment_count or 0,
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
                       "vehicle_model", "vehicle_year", "vehicle_odometer",
                       "vehicle_wof_expiry", "vehicle_cof_expiry",
                       "notes", "terms", "subject", "project_id",
                       "discount_type", "discount_value", "shipping_charges", "adjustment",
                       "order_number", "salesperson_id"):
            if field in updates and updates[field] is not None:
                setattr(quote, field, updates[field])

        # Handle JSONB fields that can be set to empty list or None
        if "additional_vehicles" in updates:
            quote.additional_vehicles = updates["additional_vehicles"]
        if "fluid_usage" in updates:
            quote.fluid_usage = updates["fluid_usage"]

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

            # Recalculate discount amount and final total
            _dv = Decimal(str(quote.discount_value or 0))
            _dt = quote.discount_type or "percentage"
            if _dt == "percentage":
                _da = (totals["subtotal"] * _dv / Decimal("100")).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            else:
                _da = _dv.quantize(TWO_PLACES)
            quote.discount_amount = _da
            _ship = Decimal(str(quote.shipping_charges or 0))
            _adj = Decimal(str(quote.adjustment or 0))
            quote.total = (totals["subtotal"] - _da + totals["gst_amount"] + _ship + _adj).quantize(TWO_PLACES)

            for i, item_data in enumerate(items):
                li = QuoteLineItem(
                    quote_id=quote.id,
                    org_id=org_id,
                    item_type=item_data["item_type"],
                    description=item_data["description"],
                    quantity=item_data["quantity"],
                    unit_price=totals["line_unit_prices"][i],
                    hours=item_data.get("hours"),
                    hourly_rate=item_data.get("hourly_rate"),
                    is_gst_exempt=item_data.get("is_gst_exempt", False),
                    warranty_note=item_data.get("warranty_note"),
                    line_total=totals["line_totals"][i],
                    sort_order=item_data.get("sort_order", i),
                    catalogue_item_id=item_data.get("catalogue_item_id"),
                    stock_item_id=item_data.get("stock_item_id"),
                    gst_inclusive=item_data.get("gst_inclusive", False),
                    inclusive_price=item_data.get("inclusive_price"),
                    tax_rate=Decimal(str(item_data.get("tax_rate", 15))),
                )
                db.add(li)
            await db.flush()

        # Handle save_terms_as_default on update
        if updates.get("save_terms_as_default") and quote.terms:
            org_result2 = await db.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org_for_terms = org_result2.scalar_one_or_none()
            if org_for_terms:
                org_s = dict(org_for_terms.settings or {})
                org_s["terms_and_conditions"] = quote.terms
                org_for_terms.settings = org_s
                await db.flush()
    elif new_status is None:
        # Non-draft quotes only allow notes/terms updates
        if "notes" in updates:
            quote.notes = updates["notes"]
        if "terms" in updates:
            quote.terms = updates["terms"]

    await db.flush()

    # Refresh to get updated server-side timestamps
    await db.refresh(quote)

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

    result = _quote_to_dict(quote, line_items)
    # Resolve per-document settings so the update response matches
    # get_quote / create_quote / cancel_quote (Requirement 5.6). ``org`` may
    # not be in scope here (it is only loaded conditionally above), so we
    # fetch the settings row by primary key — a single cheap lookup.
    org_for_settings = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org_row = org_for_settings.scalar_one_or_none()
    result.update(
        _resolve_document_settings(
            org_row.settings if org_row else None,
            per_quote_terms=quote.terms,
        )
    )
    return result


async def delete_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    quote_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Hard-delete a quote and its line items.

    Only draft, declined, and expired quotes can be deleted.
    Sent/accepted/converted quotes cannot be deleted.
    """
    q_result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = q_result.scalar_one_or_none()
    if quote is None:
        raise ValueError("Quote not found in this organisation")

    non_deletable = {"sent", "accepted", "converted"}
    if quote.status in non_deletable:
        raise ValueError(
            f"Cannot delete a quote with status '{quote.status}'. "
            "Only draft, declined, expired, or cancelled quotes can be deleted."
        )

    quote_number = quote.quote_number

    # Delete line items first
    li_result = await db.execute(
        select(QuoteLineItem).where(QuoteLineItem.quote_id == quote.id)
    )
    for li in li_result.scalars().all():
        await db.delete(li)

    await db.delete(quote)
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="quote.deleted",
        entity_type="quote",
        entity_id=quote_id,
        after_value={"quote_number": quote_number},
        ip_address=ip_address,
    )

    return {"quote_id": quote_id, "quote_number": quote_number, "deleted": True}


async def cancel_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    quote_id: uuid.UUID,
    reason: str,
    ip_address: str | None = None,
) -> dict:
    """Cancel a quote that has been issued or sent.

    Records the cancellation reason, timestamp, and actor. Writes an
    audit log entry with before/after values.
    """
    q_result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = q_result.scalar_one_or_none()
    if quote is None:
        raise ValueError("Quote not found in this organisation")

    before_status = quote.status
    _validate_status_transition(before_status, "cancelled")

    # Record cancellation metadata
    quote.status = "cancelled"
    quote.cancel_reason = reason
    quote.cancelled_at = datetime.now(timezone.utc)
    quote.cancelled_by = user_id

    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="quote.cancelled",
        entity_type="quote",
        entity_id=quote.id,
        before_value={"status": before_status},
        after_value={
            "status": "cancelled",
            "cancel_reason": reason,
            "cancelled_by": str(user_id),
        },
        ip_address=ip_address,
    )

    await db.refresh(quote)

    # Reload line items
    li_result = await db.execute(
        select(QuoteLineItem)
        .where(QuoteLineItem.quote_id == quote.id)
        .order_by(QuoteLineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    result = _quote_to_dict(quote, line_items)
    # Resolve per-document settings so the cancel response matches
    # get_quote / create_quote / update_quote (Requirement 5.6).
    org_for_settings = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org_row = org_for_settings.scalar_one_or_none()
    result.update(
        _resolve_document_settings(
            org_row.settings if org_row else None,
            per_quote_terms=quote.terms,
        )
    )
    return result


async def expire_quotes(db: AsyncSession) -> int:
    """Auto-expire quotes past their valid_until date.

    Called by a scheduled task. Only transitions 'sent' quotes to 'expired'.

    Requirements: 58.4
    """
    today = date.today()
    result = await db.execute(
        select(Quote).where(
            Quote.status.in_(["issued", "sent"]),
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
        "logo_url": None,
        "primary_colour": settings.get("primary_colour", "#3b5bdb"),
        "secondary_colour": settings.get("secondary_colour"),
        "address": ", ".join(filter(None, [
            settings.get("address_unit"),
            settings.get("address_street"),
            settings.get("address_city"),
            settings.get("address_state"),
            settings.get("address_postcode"),
        ])) or settings.get("address"),
        "address_unit": settings.get("address_unit"),
        "address_street": settings.get("address_street"),
        "address_city": settings.get("address_city"),
        "address_state": settings.get("address_state"),
        "address_country": settings.get("address_country"),
        "address_postcode": settings.get("address_postcode"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
        "website": settings.get("website"),
        "gst_number": settings.get("gst_number"),
        "invoice_footer": settings.get("invoice_footer_text") or settings.get("invoice_footer"),
    }

    # Resolve logo for PDF rendering (base64 data URI for WeasyPrint)
    from app.core.pdf_utils import resolve_logo_for_pdf
    org_context["logo_url"] = resolve_logo_for_pdf(org)

    gst_percentage = settings.get("gst_percentage", 15)
    # Single source of truth shared with the API response builder so the
    # on-screen quote and the PDF cannot drift (Requirements 4.3, 8.1, 8.4).
    resolved = _resolve_document_settings(settings, per_quote_terms=quote_dict.get("terms"))
    payment_terms_text = resolved["payment_terms_text"] or ""   # template expects "" for skip
    terms_and_conditions = resolved["terms_and_conditions"] or ""
    # terms_and_conditions_enabled is not needed by the template;
    # the PDF gates on the resolved string itself.

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
        "address": resolve_customer_display_address(customer) if customer else None,
    }

    # Render HTML
    template_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)

    def _parse_iso_date(value: str | None) -> "date | None":
        """Parse ISO date string (YYYY-MM-DD) to a date object for Jinja2 templates."""
        if not value:
            return None
        try:
            from datetime import date as date_cls
            return date_cls.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    env.filters["parse_date"] = _parse_iso_date

    template = env.get_template("quote.html")

    html_content = template.render(
        quote=quote_dict,
        org=org_context,
        customer=customer_context,
        gst_percentage=gst_percentage,
        terms_and_conditions=terms_and_conditions,
        payment_terms_text=payment_terms_text,
        order_number=quote_dict.get("order_number"),
        salesperson_name=quote_dict.get("salesperson_name"),
        additional_vehicles=quote_dict.get("additional_vehicles") or [],
        fluid_usage=quote_dict.get("fluid_usage") or [],
    )

    # Generate PDF (in-memory only) — off the event loop because WeasyPrint
    # is CPU-heavy (200-1500 ms per page). PERFORMANCE_AUDIT.md §B-H1.
    import asyncio
    pdf_bytes: bytes = await asyncio.to_thread(
        lambda: HTML(string=html_content).write_pdf()
    )
    return pdf_bytes


async def send_quote(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    quote_id: uuid.UUID,
    recipient_email: str | None = None,
    ip_address: str | None = None,
    base_url: str | None = None,
    recipients: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str | None = None,
    body_html: str | None = None,
    attachments: list[str] | None = None,
    subject_was_edited: bool = False,
    body_was_edited: bool = False,
    override_blocklist: bool = False,
) -> dict:
    """Generate a branded PDF quote and email it to the customer.

    Transitions the quote status from Draft to Sent.
    If *recipient_email* is not provided, the customer's email on file is used.

    Send Email Modal overrides (send-email-modal task 8.4): the optional
    ``recipients`` / ``cc`` / ``bcc`` / ``subject`` / ``body_html`` /
    ``attachments`` / ``subject_was_edited`` / ``body_was_edited`` /
    ``override_blocklist`` params let the modal override the default-render
    content. When NONE of them are supplied the function behaves byte-for-byte
    identically to the pre-modal auto-send path (Property P1, quote_sent):

    - ``recipients`` non-empty → ``recipient_email = recipients[0]`` and
      ``recipients[1:]`` are merged into the Cc list; ``cc`` / ``bcc`` thread
      into ``EmailMessage.cc`` / ``.bcc``.
    - ``subject`` (with ``subject_was_edited``) overrides the rendered subject.
    - ``body_html`` (with ``body_was_edited``) is server-sanitised and used as
      the HTML body; when omitted the unchanged default render runs.
    - ``attachments`` (when not ``None``) are validated as HMAC tokens via
      :func:`validate_attachment_token`; any miss raises
      :class:`InvalidAttachmentSelection`. The quote surface offers
      ``quote_pdf`` (required); matching files are re-resolved server-side and
      attached (the default no-override path attaches no PDF to avoid Gmail
      content filtering).
    - On send failure the override path raises :class:`EmailSendFailure`
      carrying the ``failure_kind`` so the router maps it to the right HTTP
      status; the legacy (no-override) path keeps raising ``ValueError``.
    - ``override_blocklist`` is threaded to ``send_email(allow_blocklisted=…)``.
    - Any client-supplied ``from_email`` / ``from_name`` / ``reply_to`` is
      ignored; the sender identity is resolved server-side (R9.3).

    Requirements: 58.3, 2.4, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9,
                  8.10, 9.3, 11.2, 11.3, 11.5
    """
    # Did the caller pass any Send-Email-Modal override field? When False the
    # function runs the original code path byte-for-byte (Property P1) and
    # keeps its legacy ValueError-on-failure contract. ``recipient_email`` is
    # the pre-existing legacy param and is NOT part of the override set.
    _is_override_call = (
        recipients is not None
        or cc is not None
        or bcc is not None
        or subject is not None
        or body_html is not None
        or attachments is not None
        or subject_was_edited
        or body_was_edited
        or override_blocklist
    )

    # Resolve the override recipient list (R8.1). recipients[0] becomes the
    # primary To; recipients[1:] merge into the Cc list. cc/bcc thread into
    # the EmailMessage below.
    _cc_list: list[str] = list(cc) if cc else []
    _bcc_list: list[str] = list(bcc) if bcc else []
    if recipients:
        recipient_email = recipients[0]
        _cc_list = [*recipients[1:], *_cc_list]

    # Fetch quote
    quote_dict = await get_quote(db, org_id=org_id, quote_id=quote_id)

    # Only draft or sent quotes can be (re-)sent
    if quote_dict["status"] not in ("draft", "issued", "sent"):
        raise ValueError(
            f"Cannot send a quote with status '{quote_dict['status']}'. "
            "Only draft, issued, or sent quotes can be sent."
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

    # Transition status to "sent" if currently draft or issued, and generate acceptance token
    if quote_dict["status"] in ("draft", "issued"):
        result = await db.execute(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.org_id == org_id,
            )
        )
        quote_obj = result.scalar_one_or_none()
        if quote_obj is not None:
            import secrets
            quote_obj.status = "sent"
            if not quote_obj.acceptance_token:
                quote_obj.acceptance_token = secrets.token_urlsafe(32)
            await db.flush()

    # Send the email with PDF attachment via the unified sender
    # (:mod:`app.integrations.email_sender`). Failover, error
    # classification, per-attempt + total time budgets are all handled
    # inside ``send_email``. This was migrated from a hand-rolled
    # ``smtplib`` provider loop in Phase 3 task 3.3 (A3).
    from app.integrations.email_sender import (
        EmailAttachment,
        EmailMessage,
        send_email,
    )

    org_result2 = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result2.scalar_one_or_none()
    org_settings = org.settings or {} if org else {}
    org_name = org.name if org else "Company"

    # Build a public view link if acceptance token exists
    acceptance_token = quote_dict.get("acceptance_token")
    if not acceptance_token and quote_obj is not None:
        acceptance_token = quote_obj.acceptance_token
    view_link_text = ""
    if acceptance_token:
        from app.config import settings as app_settings
        frontend_base = (base_url or app_settings.frontend_base_url or "http://localhost").rstrip("/")
        view_link_text = (
            f"\nYou can also view and accept this quote online at:\n"
            f"{frontend_base}/api/v1/public/quotes/view/{acceptance_token}\n"
        )

    # --- Template resolution for quote_sent ---
    from app.modules.notifications.service import resolve_template
    from app.modules.invoices.service import get_currency_symbol

    # Fetch customer details for template variable context
    _cust_for_tpl_result = await db.execute(
        select(Customer).where(
            Customer.id == quote_dict["customer_id"],
            Customer.org_id == org_id,
        )
    )
    _cust_for_tpl = _cust_for_tpl_result.scalar_one_or_none()
    _customer_first_name = _cust_for_tpl.first_name if _cust_for_tpl else ""
    _customer_last_name = _cust_for_tpl.last_name if _cust_for_tpl else ""

    # Format monetary value using quote currency (org's base_currency or NZD default)
    _quote_currency = getattr(org, "base_currency", None) or "NZD"
    _currency_symbol = get_currency_symbol(_quote_currency)
    _quote_total_raw = quote_dict.get("total", 0)
    _quote_total_formatted = f"{_currency_symbol}{_quote_total_raw:.2f}" if isinstance(_quote_total_raw, (int, float, Decimal)) else f"{_currency_symbol}{_quote_total_raw}"

    _valid_until_raw = quote_dict.get("valid_until")
    _valid_until_str = str(_valid_until_raw) if _valid_until_raw else ""

    _org_email = org_settings.get("email") or org_settings.get("business_email") or ""
    _org_phone = org_settings.get("phone") or org_settings.get("business_phone") or ""

    _template_variables = {
        "customer_first_name": _customer_first_name or "",
        "customer_last_name": _customer_last_name or "",
        "quote_number": quote_dict.get("quote_number", ""),
        "quote_total": _quote_total_formatted,
        "quote_valid_until": _valid_until_str,
        "org_name": org_name,
        "org_email": _org_email,
        "org_phone": _org_phone,
    }

    _rendered_quote_template = await resolve_template(
        db,
        org_id=org_id,
        template_type="quote_sent",
        channel="email",
        variables=_template_variables,
    )

    if _rendered_quote_template:
        _email_subject = _rendered_quote_template.subject
        _email_body = _rendered_quote_template.body
    else:
        # Existing hardcoded content (unchanged fallback)
        _email_subject = f"Quote {quote_dict['quote_number']} from {org_name}"
        _email_body = (
            f"Hi,\n\n"
            f"Please find attached quote {quote_dict['quote_number']} from {org_name}.\n\n"
            f"Total: ${quote_dict['total']:.2f} (incl. GST)\n"
            f"This quote is valid until {quote_dict.get('valid_until', 'N/A')}.\n"
            f"{view_link_text}\n"
            f"If you have any questions, please don't hesitate to contact us.\n\n"
            f"Kind regards,\n{org_name}\n"
        )

    # --- Send Email Modal subject override (R8.1) ---
    # Replace the rendered/fallback subject when the modal supplied one.
    if subject is not None:
        _email_subject = subject

    # Build HTML body with conditional email signature, using the
    # unified transactional-HTML renderer so the message is a
    # well-formed document (proper <!DOCTYPE>, paragraph structure,
    # <a href> for any embedded URLs) — matches the parity fix on
    # A1 (email_invoice). The signature, when enabled, is rendered
    # inside the document after a thin <hr>.
    _email_signature_enabled = org_settings.get("email_signature_enabled", False)
    _email_signature = org_settings.get("email_signature", "") or ""
    _signature_html_block = (
        _email_signature
        if _email_signature_enabled and _email_signature.strip()
        else None
    )
    from app.integrations.email_sender import render_transactional_html
    _html_body = render_transactional_html(
        _email_body,
        subject=_email_subject,
        signature_html=_signature_html_block,
    )

    # --- Send Email Modal body override (R8.1, R10.1) ---
    # When the modal supplied an edited body_html, server-sanitise it and use
    # it as the HTML body. When omitted (the common "send default" case) the
    # default-rendered _html_body above is used unchanged (byte-equivalence,
    # Property P1 / R3.6).
    if body_html is not None:
        from app.integrations.html_sanitise import sanitise_email_html

        _html_body = sanitise_email_html(body_html)

    # Compute the audit hashes over the FINAL (post-sanitisation) strings so
    # notification_log records what was actually sent (R11.2, R11.3 / P4).
    from app.modules.email_compose.service import compute_audit_hashes as _cah

    _audit_hashes = _cah(_email_subject, _html_body)
    _edited_subject_hash = (
        _audit_hashes["subject_hash"] if subject_was_edited else None
    )
    _edited_body_hash = _audit_hashes["body_hash"] if body_was_edited else None

    # The legacy code set ``Reply-To`` to ``org_settings['email']`` when
    # configured. The unified sender's ``org_reply_to`` override drives
    # the same header regardless of which provider in the failover chain
    # ultimately delivers the message (see Requirement 4.3).
    _org_reply_to = org_settings.get("email") or None

    # Build attachments list. The default no-override path attaches no PDF
    # (avoids Gmail content filter). When the modal supplies ``attachments``,
    # validate EVERY token against this org+quote and re-resolve the file
    # server-side (R7.6, R8.1). When ``attachments`` is None the default
    # no-attachment behaviour is preserved for byte-equivalence (Property P1).
    _email_attachments: list[EmailAttachment] = []
    if attachments is not None:
        from app.modules.email_compose.service import (
            InvalidAttachmentSelection,
            validate_attachment_token,
        )

        _resolved_kinds: list[str] = []
        for _token in attachments:
            _kind = validate_attachment_token(_token, org_id, quote_id)
            if _kind is None:
                raise InvalidAttachmentSelection("Invalid attachment selection.")
            _resolved_kinds.append(_kind)

        for _kind in _resolved_kinds:
            if _kind == "quote_pdf":
                _email_attachments.append(
                    EmailAttachment(
                        filename=f"Quote-{quote_dict['quote_number']}.pdf",
                        content=pdf_bytes,
                        mime_type="application/pdf",
                    )
                )

    _message = EmailMessage(
        to_email=recipient_email,
        to_name="",
        subject=_email_subject,
        html_body=_html_body,
        text_body=_email_body,
        attachments=_email_attachments,
        cc=_cc_list,
        bcc=_bcc_list,
        org_id=org_id,
    )
    result = await send_email(
        db,
        _message,
        org_reply_to=_org_reply_to,
        allow_blocklisted=override_blocklist,
    )

    if not result.success:
        last_error = result.error or "send failed"
        error_msg = f"All email providers failed. Last error: {last_error}"

        # Log the failed email attempt for parity with customers pattern
        from app.modules.notifications.service import log_email_sent
        try:
            await log_email_sent(
                db, org_id=org_id, recipient=recipient_email,
                template_type="quote_send", subject=f"Quote {quote_dict['quote_number']} from {org_name}",
                status="failed", error_message=str(last_error),
            )
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning("Failed to log email failure for quote %s", quote_id)

        # Create in-app notification for email failure (Req 4.3.1)
        from app.modules.in_app_notifications.service import create_in_app_notification
        await create_in_app_notification(
            db, org_id=org_id,
            category="email_failure",
            severity="error",
            title=f"Failed to email quote {quote_dict['quote_number']} to {recipient_email}",
            body=str(last_error)[:1500],
            link_url=f"/quotes/{quote_id}",
            entity_type="quote",
            entity_id=quote_id,
            audience_roles=["org_admin", "salesperson"],
            metadata={
                "recipient_email": recipient_email,
                "template_type": "quote_send",
                "error_message": str(last_error),
            },
        )

        # For Send Email Modal override calls, surface the failure_kind so the
        # router can map it to the right HTTP status (R8.5–R8.8). The legacy
        # (no-override) path keeps raising ValueError for backward compat.
        if _is_override_call:
            from app.modules.email_compose.service import EmailSendFailure

            _last_attempt = result.attempts[-1] if result.attempts else None
            _failure_kind = (
                _last_attempt.failure_kind if _last_attempt else None
            )
            raise EmailSendFailure(
                _failure_kind,
                attempts=len(result.attempts),
                error=str(last_error),
            )

        raise ValueError(error_msg)

    # Success-path notification_log row (Bug 1 / Requirement 3.1).
    # Written BEFORE the audit log so the bounce-correlation pipeline
    # (Phase 8c) can match inbound delivered/bounced webhook events to
    # this row by ``provider_message_id``.
    from app.modules.notifications.service import log_email_sent as _log_email_sent
    try:
        await _log_email_sent(
            db, org_id=org_id, recipient=recipient_email,
            template_type="quote_send", subject=_email_subject,
            status="sent", channel="email",
            provider_key=result.provider_key,
            provider_message_id=result.provider_message_id,
            subject_was_edited=subject_was_edited,
            body_was_edited=body_was_edited,
            edited_subject_hash=_edited_subject_hash,
            edited_body_hash=_edited_body_hash,
            cc_recipients=_cc_list,
            bcc_recipients=_bcc_list,
        )
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Failed to log success for quote %s", quote_id
        )

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
            "email_sent": True,
            "provider": result.provider_key,
        },
        ip_address=ip_address,
    )
    await db.flush()

    return {
        "quote_id": quote_id,
        "quote_number": quote_dict["quote_number"],
        "recipient_email": recipient_email,
        "pdf_size_bytes": len(pdf_bytes),
        "status": "sent",
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
    if quote_dict["status"] not in ("issued", "sent", "accepted"):
        raise ValueError(
            f"Cannot convert a quote with status '{quote_dict['status']}'. "
            "Only issued, sent, or accepted quotes can be converted to invoices."
        )

    # Prevent duplicate conversion
    if quote_dict.get("converted_invoice_id"):
        raise ValueError(
            "This quote has already been converted to an invoice. "
            "Delete the existing invoice first to convert again."
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
            "catalogue_item_id": li.get("catalogue_item_id"),
            "stock_item_id": li.get("stock_item_id"),
        })

    # Build additional vehicles list if present — preserve every field the
    # invoice side knows how to store (rego/make/model/year/odometer/id +
    # wof_expiry/cof_expiry/inspection_type used by the detail page).
    additional_vehicles = quote_dict.get("additional_vehicles") or []
    vehicles_data = None
    if additional_vehicles:
        vehicles_data = [
            {
                "id": v.get("id"),
                "rego": v.get("rego"),
                "make": v.get("make"),
                "model": v.get("model"),
                "year": v.get("year"),
                "odometer": v.get("odometer"),
                "wof_expiry": v.get("wof_expiry"),
                "cof_expiry": v.get("cof_expiry"),
                "inspection_type": v.get("inspection_type"),
            }
            for v in additional_vehicles
        ]

    # Build fluid usage data if present
    fluid_usage = quote_dict.get("fluid_usage") or []
    fluid_usage_data = fluid_usage if fluid_usage else None

    # Per-quote vehicle metadata that ``create_invoice`` knows how to persist:
    #   - ``vehicle_odometer`` → invoices.vehicle_odometer column
    #   - ``vehicle_wof_expiry_date`` / ``vehicle_cof_expiry_date`` →
    #     invoice_data_json.vehicle_display (drives the InvoiceDetail "WOF
    #     Expiry" / "COF Expiry" tile and the PDF appendix).
    # Quote stores these as ``date`` objects (per ``_quote_to_dict``); pass
    # them through unchanged.
    quote_wof = quote_dict.get("vehicle_wof_expiry")
    quote_cof = quote_dict.get("vehicle_cof_expiry")

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
        vehicle_odometer=quote_dict.get("vehicle_odometer"),
        vehicle_wof_expiry_date=quote_wof,
        vehicle_cof_expiry_date=quote_cof,
        vehicles=vehicles_data,
        status="draft",
        line_items_data=invoice_line_items,
        fluid_usage_data=fluid_usage_data,
        notes_customer=quote_dict.get("notes"),
        terms_and_conditions=quote_dict.get("terms"),
        discount_type=quote_dict.get("discount_type"),
        discount_value=Decimal(str(quote_dict.get("discount_value") or 0)) if quote_dict.get("discount_value") else None,
        ip_address=ip_address,
    )

    # Update quote status to accepted if it was issued or sent, and store converted invoice ID
    result = await db.execute(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.org_id == org_id,
        )
    )
    quote_obj = result.scalar_one_or_none()
    if quote_obj is not None:
        if quote_obj.status in ("issued", "sent"):
            quote_obj.status = "accepted"
        quote_obj.converted_invoice_id = invoice_dict["id"]
        await db.flush()

    # Check stock availability — alert if items are out of stock
    stock_alerts = []
    for li in quote_dict.get("line_items", []):
        sid = li.get("stock_item_id")
        if sid:
            from app.modules.inventory.models import StockItem
            si_result = await db.execute(
                select(StockItem).where(StockItem.id == uuid.UUID(str(sid)) if not isinstance(sid, uuid.UUID) else sid)
            )
            si = si_result.scalar_one_or_none()
            if si:
                available = float(si.current_quantity) - float(si.reserved_quantity)
                needed = float(li.get("quantity", 0)) if li.get("item_type") != 'labour' else float(li.get("hours") or 0)
                if available < needed:
                    stock_alerts.append({
                        "stock_item_id": str(sid),
                        "description": li.get("description", "Unknown item"),
                        "needed": needed,
                        "available": available,
                    })

    if stock_alerts:
        from app.modules.in_app_notifications.service import create_in_app_notification
        for alert in stock_alerts:
            await create_in_app_notification(
                db,
                org_id=org_id,
                category="stock_alert",
                severity="warning",
                title=f"Restock needed: {alert['description']} (Quote {quote_dict['quote_number']} converted)",
                audience_roles=["org_admin"],
                entity_type="quote",
                entity_id=quote_id,
                link_url=f"/inventory?search={alert.get('stock_item_id', '')}",
                metadata={
                    "stock_item_id": alert["stock_item_id"],
                    "description": alert["description"],
                    "needed": alert["needed"],
                    "available": alert["available"],
                    "quote_number": quote_dict["quote_number"],
                },
            )

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


async def accept_quote_by_token(
    db: AsyncSession,
    *,
    token: str,
) -> dict:
    """Accept a quote via its public acceptance token.

    Transitions the quote from 'sent' to 'accepted', then auto-converts
    to a draft invoice with 'issued' status.
    """
    import secrets
    from datetime import datetime, timezone

    result = await db.execute(
        select(Quote).where(Quote.acceptance_token == token)
    )
    quote = result.scalar_one_or_none()
    if quote is None:
        raise ValueError("Invalid or expired acceptance link")

    if quote.status == "accepted":
        raise ValueError("This quote has already been accepted")

    if quote.status not in ("issued", "sent"):
        raise ValueError(f"Quote cannot be accepted in '{quote.status}' status")

    # Check expiry
    if quote.valid_until and quote.valid_until < date.today():
        quote.status = "expired"
        await db.flush()
        raise ValueError("This quote has expired")

    # Transition to accepted
    quote.status = "accepted"
    quote.accepted_at = datetime.now(timezone.utc)
    await db.flush()

    # Auto-convert to invoice
    from app.modules.invoices.service import create_invoice

    li_result = await db.execute(
        select(QuoteLineItem)
        .where(QuoteLineItem.quote_id == quote.id)
        .order_by(QuoteLineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    invoice_line_items = []
    for li in line_items:
        invoice_line_items.append({
            "item_type": li.item_type,
            "description": li.description,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "hours": li.hours,
            "hourly_rate": li.hourly_rate,
            "is_gst_exempt": li.is_gst_exempt,
            "warranty_note": li.warranty_note,
            "sort_order": li.sort_order,
        })

    invoice_dict = await create_invoice(
        db,
        org_id=quote.org_id,
        user_id=quote.created_by,
        customer_id=quote.customer_id,
        vehicle_rego=quote.vehicle_rego,
        vehicle_make=quote.vehicle_make,
        vehicle_model=quote.vehicle_model,
        vehicle_year=quote.vehicle_year,
        status="issued",
        line_items_data=invoice_line_items,
        notes_customer=quote.notes,
    )

    quote.converted_invoice_id = invoice_dict["id"]
    await db.flush()

    # Check stock availability for items on the quote — alert if out of stock
    stock_alerts = []
    for li in line_items:
        if li.stock_item_id:
            from app.modules.inventory.models import StockItem
            si_result = await db.execute(
                select(StockItem).where(StockItem.id == li.stock_item_id)
            )
            si = si_result.scalar_one_or_none()
            if si:
                available = float(si.current_quantity) - float(si.reserved_quantity)
                needed = float(li.quantity) if li.item_type != 'labour' else float(li.hours or 0)
                if available < needed:
                    stock_alerts.append({
                        "stock_item_id": str(li.stock_item_id),
                        "description": li.description,
                        "needed": needed,
                        "available": available,
                    })

    # Create in-app notifications for out-of-stock items
    if stock_alerts:
        from app.modules.in_app_notifications.service import create_in_app_notification
        for alert in stock_alerts:
            await create_in_app_notification(
                db,
                org_id=quote.org_id,
                category="stock_alert",
                severity="warning",
                title=f"Restock needed: {alert['description']} (Quote {quote.quote_number} accepted)",
                audience_roles=["org_admin"],
                entity_type="quote",
                entity_id=quote.id,
                link_url=f"/inventory?search={alert.get('stock_item_id', '')}",
                metadata={
                    "stock_item_id": alert["stock_item_id"],
                    "description": alert["description"],
                    "needed": alert["needed"],
                    "available": alert["available"],
                    "quote_number": quote.quote_number,
                },
            )

        # Also log to audit trail for visibility
        await write_audit_log(
            session=db,
            org_id=quote.org_id,
            user_id=None,
            action="inventory.restock_alert",
            entity_type="quote",
            entity_id=quote.id,
            after_value={
                "quote_number": quote.quote_number,
                "out_of_stock_items": stock_alerts,
                "message": f"{len(stock_alerts)} item(s) need restocking for accepted quote {quote.quote_number}",
            },
        )

    # Audit log
    await write_audit_log(
        session=db,
        org_id=quote.org_id,
        user_id=None,
        action="quote.accepted_by_customer",
        entity_type="quote",
        entity_id=quote.id,
        after_value={
            "quote_number": quote.quote_number,
            "invoice_id": str(invoice_dict["id"]),
            "accepted_via": "public_link",
        },
    )

    return {
        "quote_id": quote.id,
        "quote_number": quote.quote_number,
        "status": "accepted",
        "invoice_id": invoice_dict["id"],
        "message": "Quote accepted and invoice created",
    }


async def generate_acceptance_token(
    db: AsyncSession,
    *,
    quote_id: uuid.UUID,
    org_id: uuid.UUID,
) -> str:
    """Generate and store an acceptance token for a quote."""
    import secrets

    result = await db.execute(
        select(Quote).where(Quote.id == quote_id, Quote.org_id == org_id)
    )
    quote = result.scalar_one_or_none()
    if quote is None:
        raise ValueError("Quote not found")

    if not quote.acceptance_token:
        quote.acceptance_token = secrets.token_urlsafe(32)
        await db.flush()

    return quote.acceptance_token
