"""Service history report generation for vehicles.

Generates a multi-page PDF report containing a cover page with org branding,
a table of contents, and individual invoice detail pages. Uses WeasyPrint
and Jinja2 templates following the same pattern as ``generate_invoice_pdf``.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 4.2, 4.4, 8.3, 8.5
"""

from __future__ import annotations

import pathlib
import uuid
from datetime import date

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GlobalVehicle, Organisation
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice, LineItem
from app.modules.vehicles.models import CustomerVehicle, OrgVehicle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_RANGE_LABELS: dict[int, str] = {
    0: "All Time",
    1: "Last 1 Year",
    2: "Last 2 Years",
    3: "Last 3 Years",
}


def compute_date_cutoff(range_years: int) -> date | None:
    """Return the cutoff date for filtering invoices.

    ``range_years=0`` means all time (returns ``None``).
    ``range_years=N`` means from ``(today - N years)`` to today.
    """
    if range_years == 0:
        return None
    return date.today() - relativedelta(years=range_years)


# ---------------------------------------------------------------------------
# Main report generation
# ---------------------------------------------------------------------------


async def generate_service_history_pdf(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    range_years: int,
) -> bytes:
    """Generate a multi-page PDF service history report.

    Returns the raw PDF bytes (never written to disk).

    Raises:
        HTTPException(404): Vehicle not found or not in the requesting
            user's organisation.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 4.2, 4.4, 8.3, 8.5
    """
    from jinja2 import Environment, FileSystemLoader
    from weasyprint import HTML

    # ------------------------------------------------------------------
    # 1. Fetch organisation settings
    # ------------------------------------------------------------------
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    settings = org.settings or {}
    org_context = {
        "name": org.name,
        "logo_url": settings.get("logo_url"),
        "address": ", ".join(
            filter(
                None,
                [
                    settings.get("address_unit"),
                    settings.get("address_street"),
                    settings.get("address_city"),
                    settings.get("address_state"),
                    settings.get("address_postcode"),
                    settings.get("address_country"),
                ],
            )
        )
        or settings.get("address"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
        "gst_number": settings.get("gst_number"),
    }

    # ------------------------------------------------------------------
    # 2. Fetch vehicle (global or org-scoped)
    # ------------------------------------------------------------------
    is_org_vehicle = False

    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()

    if vehicle is None:
        ov_result = await db.execute(
            select(OrgVehicle).where(
                OrgVehicle.id == vehicle_id,
                OrgVehicle.org_id == org_id,
            )
        )
        vehicle = ov_result.scalar_one_or_none()
        if vehicle is None:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        is_org_vehicle = True

    # For global vehicles, verify the org has a link to this vehicle
    if not is_org_vehicle:
        link_check = await db.execute(
            select(CustomerVehicle.id).where(
                CustomerVehicle.global_vehicle_id == vehicle_id,
                CustomerVehicle.org_id == org_id,
            )
        )
        if link_check.scalar_one_or_none() is None:
            # Also check if any invoices reference this rego in the org
            inv_check = await db.execute(
                select(Invoice.id).where(
                    Invoice.org_id == org_id,
                    Invoice.vehicle_rego == vehicle.rego,
                ).limit(1)
            )
            if inv_check.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Vehicle not found")

    vehicle_context = {
        "rego": vehicle.rego,
        "make": vehicle.make,
        "model": vehicle.model,
        "year": vehicle.year,
        "vin": vehicle.vin,
        "odometer": vehicle.odometer_last_recorded,
    }

    # ------------------------------------------------------------------
    # 3. Fetch linked customer
    # ------------------------------------------------------------------
    if is_org_vehicle:
        links_result = await db.execute(
            select(CustomerVehicle, Customer)
            .join(Customer, CustomerVehicle.customer_id == Customer.id)
            .where(
                CustomerVehicle.org_vehicle_id == vehicle_id,
                CustomerVehicle.org_id == org_id,
            )
        )
    else:
        links_result = await db.execute(
            select(CustomerVehicle, Customer)
            .join(Customer, CustomerVehicle.customer_id == Customer.id)
            .where(
                CustomerVehicle.global_vehicle_id == vehicle_id,
                CustomerVehicle.org_id == org_id,
            )
        )

    first_link = links_result.first()
    if first_link:
        _, cust = first_link
        customer_context = {
            "full_name": f"{cust.first_name} {cust.last_name}",
            "email": cust.email,
            "phone": cust.phone,
        }
    else:
        customer_context = {
            "full_name": "No linked customer",
            "email": None,
            "phone": None,
        }

    # ------------------------------------------------------------------
    # 4. Fetch invoices with line items, filtered by date range
    # ------------------------------------------------------------------
    cutoff = compute_date_cutoff(range_years)

    invoice_query = (
        select(Invoice, Customer)
        .join(Customer, Invoice.customer_id == Customer.id)
        .where(
            Invoice.org_id == org_id,
            Invoice.vehicle_rego == vehicle.rego,
        )
    )
    if cutoff is not None:
        invoice_query = invoice_query.where(Invoice.issue_date >= cutoff)

    invoice_query = invoice_query.order_by(Invoice.issue_date.desc())

    invoices_result = await db.execute(invoice_query)
    invoice_rows = invoices_result.all()

    invoices_context: list[dict] = []
    for inv, cust in invoice_rows:
        # Fetch line items for this invoice
        li_result = await db.execute(
            select(LineItem)
            .where(LineItem.invoice_id == inv.id)
            .order_by(LineItem.sort_order)
        )
        line_items = list(li_result.scalars().all())

        invoices_context.append(
            {
                "invoice_number": inv.invoice_number,
                "issue_date": inv.issue_date.strftime("%d %b %Y") if inv.issue_date else "",
                "status": inv.status,
                "odometer": inv.vehicle_odometer,
                "customer_name": f"{cust.first_name} {cust.last_name}",
                "line_items": [
                    {
                        "description": li.description,
                        "quantity": li.quantity,
                        "unit_price": li.unit_price,
                        "line_total": li.line_total,
                    }
                    for li in line_items
                ],
                "subtotal": inv.subtotal,
                "gst_amount": inv.gst_amount,
                "total": inv.total,
            }
        )

    # ------------------------------------------------------------------
    # 5. Build report context
    # ------------------------------------------------------------------
    date_range_label = _DATE_RANGE_LABELS.get(range_years, f"Last {range_years} Years")
    generated_date = date.today().strftime("%d %b %Y")

    report_context = {
        "org": org_context,
        "vehicle": vehicle_context,
        "customer": customer_context,
        "invoices": invoices_context,
        "date_range_label": date_range_label,
        "generated_date": generated_date,
        "has_invoices": len(invoices_context) > 0,
    }

    # ------------------------------------------------------------------
    # 6. Render HTML template and convert to PDF
    # ------------------------------------------------------------------
    template_dir = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "templates"
        / "pdf"
    )
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("service_history_report.html")

    html_content = template.render(**report_context)

    pdf_bytes: bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes

# ---------------------------------------------------------------------------
# Email service history report
# ---------------------------------------------------------------------------

import re

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


async def email_service_history_report(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    range_years: int,
    recipient_email: str,
) -> dict:
    """Generate the service history PDF and send it via email.

    Uses the highest-priority active email provider (SMTP failover chain),
    matching the pattern established by ``email_invoice()``.

    Returns a summary dict with vehicle_id, recipient_email, pdf_size_bytes,
    and status.

    Raises:
        HTTPException(422): Invalid recipient email format.
        HTTPException(404): Vehicle not found (propagated from generate fn).
        ValueError: No email providers configured or all providers failed.

    Requirements: 6.2, 7.1, 7.2, 7.3, 7.4, 8.2, 8.4
    """
    import json as _json
    import smtplib
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from jinja2 import Environment, FileSystemLoader

    from app.core.audit import write_audit_log
    from app.core.encryption import envelope_decrypt_str
    from app.modules.admin.models import EmailProvider

    # ------------------------------------------------------------------
    # 1. Validate recipient email
    # ------------------------------------------------------------------
    if not recipient_email or not _EMAIL_RE.match(recipient_email):
        raise HTTPException(
            status_code=422,
            detail="Invalid email format",
        )

    # ------------------------------------------------------------------
    # 2. Generate the PDF
    # ------------------------------------------------------------------
    pdf_bytes = await generate_service_history_pdf(
        db, org_id=org_id, vehicle_id=vehicle_id, range_years=range_years
    )

    # ------------------------------------------------------------------
    # 3. Fetch vehicle details for subject / filename / email body
    # ------------------------------------------------------------------
    from app.modules.admin.models import Organisation as _Org

    result = await db.execute(
        select(GlobalVehicle).where(GlobalVehicle.id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if vehicle is None:
        ov_result = await db.execute(
            select(OrgVehicle).where(
                OrgVehicle.id == vehicle_id,
                OrgVehicle.org_id == org_id,
            )
        )
        vehicle = ov_result.scalar_one_or_none()

    rego = vehicle.rego if vehicle else "UNKNOWN"
    make = vehicle.make if vehicle else ""
    model = vehicle.model if vehicle else ""
    year = vehicle.year if vehicle else None

    # Fetch org settings for email branding
    org_result = await db.execute(select(_Org).where(_Org.id == org_id))
    org = org_result.scalar_one_or_none()
    settings = (org.settings or {}) if org else {}
    org_name = org.name if org else "Workshop"

    org_context = {
        "name": org_name,
        "logo_url": settings.get("logo_url"),
        "address": ", ".join(
            filter(
                None,
                [
                    settings.get("address_unit"),
                    settings.get("address_street"),
                    settings.get("address_city"),
                    settings.get("address_state"),
                    settings.get("address_postcode"),
                    settings.get("address_country"),
                ],
            )
        )
        or settings.get("address"),
        "phone": settings.get("phone"),
        "email": settings.get("email"),
    }

    vehicle_context = {
        "rego": rego,
        "make": make,
        "model": model,
        "year": year,
    }

    date_range_label = _DATE_RANGE_LABELS.get(range_years, f"Last {range_years} Years")
    generated_date = date.today().strftime("%d %b %Y")

    # ------------------------------------------------------------------
    # 4. Build email subject, body, and attachment filename
    # ------------------------------------------------------------------
    subject = f"{rego} - Service History Report"

    # Render HTML email body from template
    template_dir = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "templates"
        / "pdf"
    )
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    email_template = env.get_template("service_history_email.html")
    html_body = email_template.render(
        org=org_context,
        vehicle=vehicle_context,
        date_range_label=date_range_label,
        generated_date=generated_date,
    )

    attachment_filename = f"{rego}_service_history_{date.today().strftime('%Y-%m-%d')}.pdf"

    # ------------------------------------------------------------------
    # 5. Send via SMTP failover chain
    # ------------------------------------------------------------------
    provider_result = await db.execute(
        select(EmailProvider)
        .where(
            EmailProvider.is_active == True,
            EmailProvider.credentials_set == True,
        )
        .order_by(EmailProvider.priority)
    )
    providers = list(provider_result.scalars().all())

    if not providers:
        raise ValueError(
            "No active email provider configured. "
            "Please set up an email provider in Admin > Email Providers."
        )

    def _build_message(from_name: str, from_email: str) -> MIMEMultipart:
        msg = MIMEMultipart("mixed")
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = recipient_email
        msg["Subject"] = subject

        msg.attach(MIMEText(html_body, "html"))

        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=attachment_filename,
        )
        msg.attach(pdf_attachment)
        return msg

    last_error = None
    used_provider = None

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

            server.sendmail(from_email, recipient_email, msg.as_string())
            server.quit()
            used_provider = provider
            break
        except Exception as e:
            last_error = e
            continue

    if used_provider is None:
        raise ValueError(
            f"All email providers failed. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # 6. Audit log
    # ------------------------------------------------------------------
    await write_audit_log(
        db,
        action="vehicle.report_emailed",
        entity_type="vehicle",
        entity_id=vehicle_id,
        org_id=org_id,
        after_value={
            "recipient": recipient_email,
            "vehicle_rego": rego,
            "pdf_size_bytes": len(pdf_bytes),
            "provider": used_provider.provider_key,
        },
    )
    await db.flush()

    # ------------------------------------------------------------------
    # 7. Return result
    # ------------------------------------------------------------------
    return {
        "vehicle_id": str(vehicle_id),
        "recipient_email": recipient_email,
        "pdf_size_bytes": len(pdf_bytes),
        "status": "sent",
    }
