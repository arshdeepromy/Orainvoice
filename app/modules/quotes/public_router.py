"""Public (no-auth) endpoints for quote acceptance."""

from __future__ import annotations

import pathlib

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer
from app.modules.quotes.models import Quote, QuoteLineItem
from app.modules.quotes.service import accept_quote_by_token

router = APIRouter()


@router.get(
    "/view/{token}",
    response_class=HTMLResponse,
    summary="View a shared quote (public, no auth required)",
)
async def view_shared_quote(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Render a shared quote as HTML with an Accept button."""
    result = await db.execute(
        select(Quote).where(Quote.acceptance_token == token)
    )
    quote = result.scalar_one_or_none()
    if quote is None:
        return HTMLResponse(
            content="<html><body><h1>Quote not found</h1><p>This link may have expired or is invalid.</p></body></html>",
            status_code=404,
        )

    # Fetch line items
    li_result = await db.execute(
        select(QuoteLineItem)
        .where(QuoteLineItem.quote_id == quote.id)
        .order_by(QuoteLineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())

    # Fetch org
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == quote.org_id)
    )
    org = org_result.scalar_one_or_none()
    settings = org.settings or {} if org else {}

    org_context = {
        "name": org.name if org else "Company",
        "logo_url": settings.get("logo_url"),
        "primary_colour": settings.get("primary_colour", "#1a1a1a"),
        "address": settings.get("address"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
        "gst_number": settings.get("gst_number"),
    }

    # Fetch customer
    cust_result = await db.execute(
        select(Customer).where(Customer.id == quote.customer_id)
    )
    customer = cust_result.scalar_one_or_none()
    customer_context = {
        "first_name": customer.first_name if customer else "Unknown",
        "last_name": customer.last_name if customer else "",
        "email": customer.email if customer else None,
        "phone": customer.phone if customer else None,
    }

    gst_percentage = settings.get("gst_percentage", 15)

    # Build quote dict
    quote_dict = {
        "id": str(quote.id),
        "quote_number": quote.quote_number,
        "status": quote.status,
        "valid_until": str(quote.valid_until) if quote.valid_until else None,
        "subtotal": float(quote.subtotal),
        "gst_amount": float(quote.gst_amount or 0),
        "total": float(quote.total),
        "notes": quote.notes,
        "vehicle_rego": quote.vehicle_rego,
        "vehicle_make": quote.vehicle_make,
        "vehicle_model": quote.vehicle_model,
        "vehicle_year": quote.vehicle_year,
        "created_at": quote.created_at,
        "line_items": [
            {
                "description": li.description,
                "item_type": li.item_type,
                "quantity": float(li.quantity),
                "unit_price": float(li.unit_price),
                "hours": float(li.hours) if li.hours else None,
                "hourly_rate": float(li.hourly_rate) if li.hourly_rate else None,
                "is_gst_exempt": li.is_gst_exempt,
                "warranty_note": li.warranty_note,
                "line_total": float(li.line_total),
            }
            for li in line_items
        ],
    }

    # Render HTML
    template_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("quote_share.html")

    html_content = template.render(
        quote=quote_dict,
        org=org_context,
        customer=customer_context,
        gst_percentage=gst_percentage,
        token=token,
        can_accept=quote.status == "sent",
        already_accepted=quote.status == "accepted",
    )

    return HTMLResponse(content=html_content)


@router.post(
    "/accept/{token}",
    summary="Accept a quote (public, no auth required)",
)
async def accept_quote_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Public endpoint for customers to accept a quote via token."""
    try:
        result = await accept_quote_by_token(db, token=token)
        await db.commit()
        return result
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
