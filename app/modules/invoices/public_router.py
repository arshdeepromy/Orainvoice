"""Public (no-auth) endpoints for shared invoice viewing."""

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
from app.modules.invoices.models import Invoice, LineItem
from app.modules.invoices.service import (
    _invoice_to_dict,
    get_currency_symbol,
)

router = APIRouter()


@router.get(
    "/{share_token}",
    response_class=HTMLResponse,
    summary="View a shared invoice (public, no auth required)",
)
async def view_shared_invoice(
    share_token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Render a shared invoice as a full HTML page that can be printed or saved as PDF."""
    from sqlalchemy import func

    # Find invoice by share token in invoice_data_json
    result = await db.execute(
        select(Invoice).where(
            Invoice.invoice_data_json["share_token"].astext == share_token
        )
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        return HTMLResponse(
            content="<html><body><h1>Invoice not found</h1><p>This link may have expired or is invalid.</p></body></html>",
            status_code=404,
        )

    # Fetch line items
    li_result = await db.execute(
        select(LineItem)
        .where(LineItem.invoice_id == invoice.id)
        .order_by(LineItem.sort_order)
    )
    line_items = list(li_result.scalars().all())
    invoice_dict = _invoice_to_dict(invoice, line_items)

    # Fetch org
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == invoice.org_id)
    )
    org = org_result.scalar_one_or_none()
    settings = org.settings or {} if org else {}

    org_context = {
        "name": org.name if org else "Company",
        "logo_url": settings.get("logo_url"),
        "primary_colour": settings.get("primary_colour", "#1a1a1a"),
        "address": ", ".join(filter(None, [
            settings.get("address_unit"),
            settings.get("address_street"),
            settings.get("address_city"),
            settings.get("address_state"),
            settings.get("address_postcode"),
            settings.get("address_country"),
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
        "invoice_footer": settings.get("invoice_footer_text"),
    }

    # Fetch customer
    cust_result = await db.execute(
        select(Customer).where(Customer.id == invoice.customer_id)
    )
    customer = cust_result.scalar_one_or_none()
    customer_context = {
        "first_name": customer.first_name if customer else "Unknown",
        "last_name": customer.last_name if customer else "",
        "email": customer.email if customer else None,
        "phone": customer.phone if customer else None,
        "address": customer.address if customer else None,
    }

    # Vehicle info
    if invoice.vehicle_rego:
        from app.modules.admin.models import GlobalVehicle
        gv_result = await db.execute(
            select(GlobalVehicle).where(
                func.upper(GlobalVehicle.rego) == invoice.vehicle_rego.upper()
            )
        )
        gv = gv_result.scalar_one_or_none()
        if gv:
            invoice_dict["vehicle"] = {
                "rego": gv.rego,
                "make": gv.make,
                "model": gv.model,
                "year": gv.year,
                "wof_expiry": gv.wof_expiry.isoformat() if getattr(gv, "wof_expiry", None) else None,
                "odometer": getattr(gv, "odometer_last_recorded", None),
            }

    gst_percentage = settings.get("gst_percentage", 15)
    payment_terms = settings.get("payment_terms_text", "")
    terms_and_conditions = settings.get("terms_and_conditions", "")
    currency_symbol = get_currency_symbol(invoice_dict.get("currency", "NZD"))

    # Render the shared invoice HTML template
    template_dir = pathlib.Path(__file__).resolve().parent.parent.parent / "templates" / "pdf"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("invoice_share.html")

    html_content = template.render(
        invoice=invoice_dict,
        org=org_context,
        customer=customer_context,
        currency_symbol=currency_symbol,
        gst_percentage=gst_percentage,
        payment_terms=payment_terms,
        terms_and_conditions=terms_and_conditions,
    )

    return HTMLResponse(
        content=html_content,
        headers={
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self'; "
                "frame-ancestors 'none'"
            ),
        },
    )
