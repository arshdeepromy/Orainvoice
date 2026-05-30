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
    payment_terms_enabled = settings.get("payment_terms_enabled", True)
    payment_terms_text = settings.get("payment_terms_text", "") if payment_terms_enabled else ""

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
        "vehicle_odometer": quote.vehicle_odometer,
        "vehicle_wof_expiry": quote.vehicle_wof_expiry,
        "vehicle_cof_expiry": quote.vehicle_cof_expiry,
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

    def _parse_iso_date(value: str | None):
        """Parse ISO date string (YYYY-MM-DD) to a date object for Jinja2 templates."""
        from datetime import date as date_type
        if not value:
            return None
        try:
            return date_type.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    env.filters["parse_date"] = _parse_iso_date

    template = env.get_template("quote_share.html")

    # Resolve salesperson name if set
    salesperson_name = None
    if quote.salesperson_id:
        from app.modules.auth.models import User
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

    html_content = template.render(
        quote=quote_dict,
        org=org_context,
        customer=customer_context,
        gst_percentage=gst_percentage,
        payment_terms_text=payment_terms_text,
        token=token,
        can_accept=quote.status == "sent",
        already_accepted=quote.status == "accepted",
        order_number=quote.order_number,
        salesperson_name=salesperson_name,
        additional_vehicles=quote.additional_vehicles or [],
    )

    return HTMLResponse(content=html_content)


@router.get(
    "/view/{token}/pdf",
    summary="Download quote as PDF (public, no auth required)",
)
async def public_quote_pdf(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate and return the quote PDF for public download."""
    from app.modules.quotes.service import generate_quote_pdf

    # Look up quote by acceptance token
    result = await db.execute(
        select(Quote).where(Quote.acceptance_token == token)
    )
    quote = result.scalar_one_or_none()
    if quote is None:
        return JSONResponse(status_code=404, content={"detail": "Quote not found"})

    pdf_bytes = await generate_quote_pdf(db, org_id=quote.org_id, quote_id=quote.id)

    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Quote-{quote.quote_number}.pdf"',
        },
    )


@router.post(
    "/accept/{token}",
    summary="Accept a quote (public, no auth required)",
)
async def accept_quote_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Public endpoint for customers to accept a quote via token.
    
    Returns an HTML page confirming acceptance (not raw JSON) so the
    customer sees a friendly confirmation on their phone/browser.
    """
    try:
        result = await accept_quote_by_token(db, token=token)
        await db.commit()

        # Return a friendly HTML confirmation page instead of raw JSON
        quote_number = result.get("quote_number", "")
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Quote {quote_number} Accepted</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.5; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
  .card {{ max-width: 480px; width: 100%; background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); padding: 48px 32px; text-align: center; }}
  .icon {{ width: 64px; height: 64px; background: #dcfce7; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; }}
  .icon svg {{ width: 32px; height: 32px; color: #16a34a; }}
  h1 {{ font-size: 22px; font-weight: 700; color: #1a1a1a; margin-bottom: 8px; }}
  p {{ font-size: 15px; color: #555; margin-bottom: 16px; }}
  .badge {{ display: inline-block; padding: 8px 20px; background: #dcfce7; color: #166534; font-size: 14px; font-weight: 600; border-radius: 6px; margin-top: 8px; }}
  .back-link {{ display: inline-block; margin-top: 24px; color: #2563eb; font-size: 14px; text-decoration: none; }}
  .back-link:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon"><svg fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg></div>
  <h1>Quote Accepted!</h1>
  <p>Thank you for accepting quote <strong>{quote_number}</strong>.</p>
  <p>An invoice has been created and you will receive it shortly.</p>
  <div class="badge">✓ Accepted</div>
  <br>
  <a href="/api/v1/public/quotes/view/{token}" class="back-link">← View Quote Details</a>
</div>
</body>
</html>"""
        return HTMLResponse(content=html)

    except ValueError as exc:
        error_msg = str(exc)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Error</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.5; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
  .card {{ max-width: 480px; width: 100%; background: #fff; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.08); padding: 48px 32px; text-align: center; }}
  h1 {{ font-size: 20px; font-weight: 700; color: #991b1b; margin-bottom: 12px; }}
  p {{ font-size: 15px; color: #555; }}
  .back-link {{ display: inline-block; margin-top: 24px; color: #2563eb; font-size: 14px; text-decoration: none; }}
</style>
</head>
<body>
<div class="card">
  <h1>Unable to Accept</h1>
  <p>{error_msg}</p>
  <a href="/api/v1/public/quotes/view/{token}" class="back-link">← Back to Quote</a>
</div>
</body>
</html>"""
        return HTMLResponse(content=html, status_code=400)
