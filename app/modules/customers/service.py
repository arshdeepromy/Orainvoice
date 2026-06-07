"""Business logic for Customer module — CRUD, search, profile, notify, vehicle tagging, privacy.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 13.4
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import or_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.customers.models import Customer

logger = logging.getLogger(__name__)


def _customer_to_dict(customer: Customer) -> dict:
    """Convert a Customer ORM instance to a serialisable dict."""
    return {
        "id": str(customer.id),
        # Identity
        "customer_type": customer.customer_type or "individual",
        "salutation": customer.salutation,
        "first_name": customer.first_name,
        "last_name": customer.last_name,
        "company_name": customer.company_name,
        "display_name": customer.display_name,
        # Contact
        "email": customer.email,
        "phone": customer.phone,
        "work_phone": customer.work_phone,
        "mobile_phone": customer.mobile_phone,
        # Preferences
        "currency": customer.currency or "NZD",
        "language": customer.language or "en",
        # Business/Tax
        "tax_rate_id": str(customer.tax_rate_id) if customer.tax_rate_id else None,
        "company_id": customer.company_id,
        "payment_terms": customer.payment_terms or "due_on_receipt",
        # Options
        "enable_bank_payment": customer.enable_bank_payment or False,
        "enable_portal": customer.enable_portal or False,
        # Portal
        "portal_token": str(customer.portal_token) if customer.portal_token else None,
        "portal_token_expires_at": customer.portal_token_expires_at.isoformat() if customer.portal_token_expires_at else None,
        "last_portal_access_at": customer.last_portal_access_at.isoformat() if customer.last_portal_access_at else None,
        # Addresses
        "address": customer.address,
        "billing_address": customer.billing_address or {},
        "shipping_address": customer.shipping_address or {},
        # Additional data
        "contact_persons": customer.contact_persons or [],
        "custom_fields": customer.custom_fields or {},
        # Notes
        "notes": customer.notes,
        "remarks": customer.remarks,
        # Status
        "is_anonymised": customer.is_anonymised,
        # Timestamps
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
        "updated_at": customer.updated_at.isoformat() if customer.updated_at else None,
    }


def _customer_to_search_dict(customer: Customer) -> dict:
    """Convert a Customer ORM instance to a search-result dict."""
    custom = customer.custom_fields or {}
    rc = custom.get("reminder_config", {})
    reminders_on = False
    if isinstance(rc, dict):
        reminders_on = any(
            isinstance(v, dict) and v.get("enabled", False)
            for v in rc.values()
        )
    return {
        "id": str(customer.id),
        "customer_type": customer.customer_type or "individual",
        "first_name": customer.first_name,
        "last_name": customer.last_name,
        "company_name": customer.company_name,
        "display_name": customer.display_name,
        "email": customer.email,
        "phone": customer.phone,
        "mobile_phone": customer.mobile_phone,
        "work_phone": customer.work_phone,
        "reminders_enabled": reminders_on,
        "last_portal_access_at": (
            customer.last_portal_access_at.isoformat()
            if customer.last_portal_access_at
            else None
        ),
    }


async def search_customers(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_vehicles: bool = False,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Search customers by name, phone, or email.

    Uses PostgreSQL full-text search (GIN index) when a query is provided.
    Falls back to listing all customers when no query is given.

    Returns a dict with ``customers`` list, ``total`` count, and
    ``has_exact_match`` flag.
    
    If include_vehicles is True, also returns linked vehicles for each customer.

    Requirements: 11.1, 11.2, 11.3, 11.6
    """
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    # Gate linked_vehicles behind vehicles module (Req 6.1, 6.2)
    from app.core.modules import ModuleService
    module_svc = ModuleService(db)
    if not await module_svc.is_enabled(str(org_id), "vehicles"):
        include_vehicles = False
    
    base_filter = [
        Customer.org_id == org_id,
        Customer.is_anonymised.is_(False),
    ]

    # Branch filter — for customers, include shared customers (branch_id IS NULL)
    if branch_id is not None:
        base_filter.append(
            or_(Customer.branch_id == branch_id, Customer.branch_id.is_(None))
        )

    if query and query.strip():
        search_term = query.strip()
        # Use ILIKE for flexible matching on name, display_name, company, email, phone
        like_pattern = f"%{search_term}%"
        search_condition = or_(
            func.concat(Customer.first_name, " ", Customer.last_name).ilike(like_pattern),
            Customer.display_name.ilike(like_pattern),
            Customer.company_name.ilike(like_pattern),
            Customer.email.ilike(like_pattern),
            Customer.phone.ilike(like_pattern),
        )

        # Count total matches
        count_stmt = (
            select(func.count(Customer.id))
            .where(*base_filter, search_condition)
        )
        total = (await db.execute(count_stmt)).scalar() or 0

        # Fetch results
        stmt = (
            select(Customer)
            .where(*base_filter, search_condition)
            .order_by(Customer.first_name, Customer.last_name)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        customers = result.scalars().all()

        # Check for exact match (name matches exactly)
        has_exact_match = any(
            f"{c.first_name} {c.last_name}".lower() == search_term.lower()
            or (c.display_name and c.display_name.lower() == search_term.lower())
            or (c.email and c.email.lower() == search_term.lower())
            or (c.phone and c.phone == search_term)
            for c in customers
        )
    else:
        # No query — return all customers for the org
        count_stmt = select(func.count(Customer.id)).where(*base_filter)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Customer)
            .where(*base_filter)
            .order_by(Customer.first_name, Customer.last_name)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        customers = result.scalars().all()
        has_exact_match = False

    # Build customer dicts with optional vehicles and financial summaries
    from app.modules.invoices.models import Invoice, CreditNote

    # Batch-fetch receivables (sum of balance_due for non-voided invoices) per customer
    customer_ids = [c.id for c in customers]
    receivables_map: dict[uuid.UUID, float] = {}
    credits_map: dict[uuid.UUID, float] = {}

    if customer_ids:
        recv_stmt = (
            select(
                Invoice.customer_id,
                func.coalesce(func.sum(Invoice.balance_due), 0).label("receivable"),
            )
            .where(
                Invoice.customer_id.in_(customer_ids),
                Invoice.org_id == org_id,
                Invoice.status.notin_(["voided", "draft"]),
            )
            .group_by(Invoice.customer_id)
        )
        recv_result = await db.execute(recv_stmt)
        for row in recv_result.all():
            receivables_map[row.customer_id] = float(row.receivable)

        # Batch-fetch unused credits (sum of credit note amounts) per customer
        cred_stmt = (
            select(
                Invoice.customer_id,
                func.coalesce(func.sum(CreditNote.amount), 0).label("credits"),
            )
            .join(Invoice, CreditNote.invoice_id == Invoice.id)
            .where(
                Invoice.customer_id.in_(customer_ids),
                Invoice.org_id == org_id,
            )
            .group_by(Invoice.customer_id)
        )
        cred_result = await db.execute(cred_stmt)
        for row in cred_result.all():
            credits_map[row.customer_id] = float(row.credits)

    customer_dicts = []
    for c in customers:
        cust_dict = _customer_to_search_dict(c)
        cust_dict["receivables"] = receivables_map.get(c.id, 0.0)
        cust_dict["unused_credits"] = credits_map.get(c.id, 0.0)
        
        if include_vehicles:
            # Fetch linked vehicles for this customer.
            #
            # Use a double outerjoin so we capture both link types:
            #  - Pre-promotion / unmigrated links (``global_vehicle_id`` set,
            #    ``org_vehicle_id`` NULL) — read from ``GlobalVehicle``.
            #  - Post-promotion / migrated links (``org_vehicle_id`` set,
            #    ``global_vehicle_id`` NULL) — read from ``OrgVehicle``.
            # The ``vehicle_link_check`` CHECK constraint guarantees exactly
            # one of the two columns is non-NULL, so ``v = gv if gv else ov``
            # always picks the correct source. Migrations 0105 and 0181
            # established schema parity, so every consumed attribute (rego,
            # make, model, year, colour, odometer_last_recorded,
            # service_due_date, wof_expiry, cof_expiry, inspection_type)
            # exists identically on both records.
            cv_stmt = (
                select(CustomerVehicle, GlobalVehicle, OrgVehicle)
                .outerjoin(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
                .outerjoin(OrgVehicle, CustomerVehicle.org_vehicle_id == OrgVehicle.id)
                .where(
                    CustomerVehicle.customer_id == c.id,
                    CustomerVehicle.org_id == org_id,
                )
                .order_by(CustomerVehicle.linked_at.desc())
            )
            cv_result = await db.execute(cv_stmt)
            linked_vehicles = []
            for cv, gv, ov in cv_result.all():
                v = gv if gv is not None else ov
                if v is not None:
                    linked_vehicles.append({
                        "id": str(v.id),
                        "rego": v.rego,
                        "make": v.make,
                        "model": v.model,
                        "year": v.year,
                        "colour": v.colour,
                        "odometer": v.odometer_last_recorded,
                        "service_due_date": v.service_due_date.isoformat() if v.service_due_date else None,
                        "wof_expiry": v.wof_expiry.isoformat() if v.wof_expiry else None,
                        "cof_expiry": v.cof_expiry.isoformat() if v.cof_expiry else None,
                        "inspection_type": v.inspection_type,
                        # Optional source tag — frontend ignores unknown keys
                        # per safe-api-consumption.md. Useful for downstream
                        # consumers (e.g. tests, future features) that need
                        # to know which record-type the row came from.
                        "source": "org" if gv is None else "global",
                    })
            cust_dict["linked_vehicles"] = linked_vehicles
        
        customer_dicts.append(cust_dict)

    return {
        "customers": customer_dicts,
        "total": total,
        "has_exact_match": has_exact_match,
    }


async def create_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    first_name: str,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    mobile_phone: str | None = None,
    work_phone: str | None = None,
    address: str | None = None,
    notes: str | None = None,
    ip_address: str | None = None,
    branch_id: uuid.UUID | None = None,
    # New fields
    customer_type: str = "individual",
    salutation: str | None = None,
    company_name: str | None = None,
    display_name: str | None = None,
    currency: str = "NZD",
    language: str = "en",
    tax_rate_id: uuid.UUID | None = None,
    company_id: str | None = None,
    payment_terms: str = "due_on_receipt",
    enable_bank_payment: bool = False,
    enable_portal: bool = False,
    billing_address: dict | None = None,
    shipping_address: dict | None = None,
    contact_persons: list | None = None,
    custom_fields: dict | None = None,
    remarks: str | None = None,
) -> dict:
    """Create a new customer record scoped to the organisation.

    Requirements: 11.4, 11.5, 11.6
    """
    # Validate branch is active if provided (Req 2.2)
    if branch_id is not None:
        from app.core.branch_validation import validate_branch_active
        await validate_branch_active(db, branch_id)

    # Auto-generate display_name if not provided
    if not display_name:
        if customer_type == "business" and company_name:
            display_name = company_name
        else:
            display_name = f"{first_name} {last_name}".strip() if last_name else first_name
    
    customer = Customer(
        org_id=org_id,
        customer_type=customer_type,
        salutation=salutation,
        first_name=first_name,
        last_name=last_name,
        company_name=company_name,
        display_name=display_name,
        email=email,
        phone=phone or mobile_phone,  # Backward compatibility
        work_phone=work_phone,
        mobile_phone=mobile_phone,
        currency=currency,
        language=language,
        tax_rate_id=tax_rate_id,
        company_id=company_id,
        payment_terms=payment_terms,
        enable_bank_payment=enable_bank_payment,
        enable_portal=enable_portal,
        address=address,
        billing_address=billing_address or {},
        shipping_address=shipping_address or {},
        contact_persons=contact_persons or [],
        custom_fields=custom_fields or {},
        notes=notes,
        remarks=remarks,
        branch_id=branch_id,
    )
    db.add(customer)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.created",
        entity_type="customer",
        entity_id=customer.id,
        before_value=None,
        after_value={
            "customer_type": customer_type,
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company_name,
            "email": email,
            "mobile_phone": mobile_phone,
        },
        ip_address=ip_address,
    )

    return _customer_to_dict(customer)


async def get_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict:
    """Retrieve a single customer by ID within the organisation.

    Raises ValueError if not found.
    """
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    return _customer_to_dict(customer)


async def update_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    ip_address: str | None = None,
    **kwargs,
) -> dict:
    """Update a customer record. Only non-None kwargs are applied.

    Requirements: 11.5, 11.6
    """
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    if customer.is_anonymised:
        raise ValueError("Cannot update an anonymised customer record")

    allowed_fields = {
        "first_name", "last_name", "email", "phone", "address", "notes",
        "customer_type", "salutation", "company_name", "display_name",
        "work_phone", "mobile_phone", "currency", "language",
        "tax_rate_id", "company_id", "payment_terms",
        "enable_bank_payment", "enable_portal",
        "billing_address", "shipping_address",
        "contact_persons", "custom_fields", "remarks",
    }
    before_value = {}
    updated_fields = []

    for field in allowed_fields:
        value = kwargs.get(field)
        if value is not None:
            before_value[field] = getattr(customer, field, None)
            setattr(customer, field, value)
            updated_fields.append(field)

    if not updated_fields:
        return _customer_to_dict(customer)

    # --- Portal token lifecycle (Req 12.1, 12.2, 12.3) ---
    # When enable_portal transitions to True and portal_token is NULL,
    # auto-generate a token with org-configured TTL.
    # When enable_portal transitions to False, revoke the token.
    if "enable_portal" in updated_fields:
        if customer.enable_portal and customer.portal_token is None:
            from app.modules.admin.models import Organisation

            org_result = await db.execute(
                select(Organisation).where(Organisation.id == org_id)
            )
            org = org_result.scalar_one_or_none()
            ttl_days = 90
            if org and org.settings:
                ttl_days = org.settings.get("portal_token_ttl_days", 90)

            customer.portal_token = secrets.token_urlsafe(32)
            customer.portal_token_expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)

            before_value["portal_token"] = None
            before_value["portal_token_expires_at"] = None

            # Auto-send portal link email if customer has an email address
            if customer.email:
                try:
                    await send_portal_link(
                        db,
                        org_id=org_id,
                        user_id=user_id,
                        customer_id=customer.id,
                        ip_address=ip_address,
                    )
                except Exception:
                    # Best-effort — token is generated even if email fails
                    import logging
                    logging.getLogger(__name__).warning(
                        "Auto-send portal link failed for customer %s — token generated but email not sent",
                        customer.id,
                    )
        elif not customer.enable_portal:
            before_value["portal_token"] = str(customer.portal_token) if customer.portal_token else None
            before_value["portal_token_expires_at"] = (
                customer.portal_token_expires_at.isoformat() if customer.portal_token_expires_at else None
            )
            customer.portal_token = None
            customer.portal_token_expires_at = None

    await db.flush()
    await db.refresh(customer)

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.updated",
        entity_type="customer",
        entity_id=customer.id,
        before_value=before_value,
        after_value={f: kwargs[f] for f in updated_fields},
        ip_address=ip_address,
    )

    return _customer_to_dict(customer)


# ---------------------------------------------------------------------------
# Task 7.2 — Customer profile, notify, vehicle tagging
# Requirements: 12.1, 12.2, 12.3
# ---------------------------------------------------------------------------


async def get_customer_profile(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict:
    """Retrieve a full customer profile with linked vehicles, invoice history,
    total spend, and outstanding balance.

    Requirements: 12.1
    """
    from app.modules.invoices.models import Invoice
    from app.modules.payments.models import Payment
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    # 1. Fetch customer
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    # 2. Fetch linked vehicles
    cv_stmt = (
        select(CustomerVehicle)
        .where(
            CustomerVehicle.customer_id == customer_id,
            CustomerVehicle.org_id == org_id,
        )
        .order_by(CustomerVehicle.linked_at.desc())
    )
    cv_result = await db.execute(cv_stmt)
    customer_vehicles = cv_result.scalars().all()

    vehicles = []
    for cv in customer_vehicles:
        if cv.global_vehicle_id:
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == cv.global_vehicle_id)
            )
            gv = gv_result.scalar_one_or_none()
            vehicles.append({
                "id": str(cv.id),
                "rego": gv.rego if gv else None,
                "make": gv.make if gv else None,
                "model": gv.model if gv else None,
                "year": gv.year if gv else None,
                "colour": gv.colour if gv else None,
                "odometer": gv.odometer_last_recorded if gv else None,
                "wof_expiry": gv.wof_expiry.isoformat() if gv and gv.wof_expiry else None,
                "cof_expiry": gv.cof_expiry.isoformat() if gv and gv.cof_expiry else None,
                "inspection_type": gv.inspection_type if gv else None,
                "service_due_date": gv.service_due_date.isoformat() if gv and gv.service_due_date else None,
                "source": "global",
                # GlobalVehicle records are created exclusively from CarJam
                # lookups (manual entries land directly in OrgVehicle).
                "origin": "carjam",
                "linked_at": cv.linked_at.isoformat() if cv.linked_at else None,
            })
        elif cv.org_vehicle_id:
            ov_result = await db.execute(
                select(OrgVehicle).where(
                    OrgVehicle.id == cv.org_vehicle_id,
                    OrgVehicle.org_id == org_id,
                )
            )
            ov = ov_result.scalar_one_or_none()
            vehicles.append({
                "id": str(cv.id),
                "rego": ov.rego if ov else None,
                "make": ov.make if ov else None,
                "model": ov.model if ov else None,
                "year": ov.year if ov else None,
                "colour": ov.colour if ov else None,
                "odometer": ov.odometer_last_recorded if ov else None,
                "wof_expiry": ov.wof_expiry.isoformat() if ov and ov.wof_expiry else None,
                "cof_expiry": ov.cof_expiry.isoformat() if ov and ov.cof_expiry else None,
                "inspection_type": ov.inspection_type if ov else None,
                "service_due_date": ov.service_due_date.isoformat() if ov and ov.service_due_date else None,
                "source": "org",
                # OrgVehicle.is_manual_entry is set to False when the row was
                # promoted from a CarJam lookup, True when the user typed
                # the details by hand.
                "origin": "manual" if (ov and ov.is_manual_entry) else "carjam",
                "linked_at": cv.linked_at.isoformat() if cv.linked_at else None,
            })

    # 3. Fetch invoice history
    inv_stmt = (
        select(Invoice)
        .where(
            Invoice.customer_id == customer_id,
            Invoice.org_id == org_id,
        )
        .order_by(Invoice.created_at.desc())
    )
    inv_result = await db.execute(inv_stmt)
    invoices = inv_result.scalars().all()

    invoice_list = []
    for inv in invoices:
        invoice_list.append({
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "vehicle_rego": inv.vehicle_rego,
            "status": inv.status,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "total": str(inv.total),
            "balance_due": str(inv.balance_due),
        })

    # 4. Calculate total spend (sum of amount_paid across all non-voided invoices)
    spend_stmt = select(func.coalesce(func.sum(Invoice.amount_paid), Decimal("0"))).where(
        Invoice.customer_id == customer_id,
        Invoice.org_id == org_id,
        Invoice.status != "voided",
    )
    total_spend = (await db.execute(spend_stmt)).scalar() or Decimal("0")

    # 5. Calculate outstanding balance (sum of balance_due across non-voided invoices)
    balance_stmt = select(func.coalesce(func.sum(Invoice.balance_due), Decimal("0"))).where(
        Invoice.customer_id == customer_id,
        Invoice.org_id == org_id,
        Invoice.status != "voided",
    )
    outstanding_balance = (await db.execute(balance_stmt)).scalar() or Decimal("0")

    return {
        **_customer_to_dict(customer),
        "vehicles": vehicles,
        "invoices": invoice_list,
        "total_spend": str(total_spend),
        "outstanding_balance": str(outstanding_balance),
    }


async def notify_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    channel: str,
    subject: str | None = None,
    message: str,
    ip_address: str | None = None,
) -> dict:
    """Send a one-off email or SMS to a customer from their profile.

    Requirements: 12.2
    """
    from app.modules.admin.models import Organisation

    # Fetch customer to get contact details
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    if customer.is_anonymised:
        raise ValueError("Cannot notify an anonymised customer")

    # Fetch org for sender settings
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Workshop"

    recipient = None

    if channel == "email":
        if not customer.email:
            raise ValueError("Customer has no email address on file")
        recipient = customer.email

        # Migrated from a hand-rolled smtplib provider loop in Phase 3
        # task 3.12 (A12) of the email-provider-unification spec. Dispatch
        # goes through :func:`app.integrations.email_sender.send_email`,
        # which owns failover, error classification, and per-attempt +
        # total time budgets.
        #
        # Per the per-site variation table in design.md row A12:
        # - ``EmailMessage.org_id`` = ``customer.org_id`` (org-scoped send).
        # - ``org_sender_name=org_name`` so the From header reads as the
        #   org, not the platform default.
        # - ``log_email_sent`` is called on both success and failure
        #   (preserved from the legacy implementation).
        # - ``create_in_app_notification(category='email_failure', ...)``
        #   fires on total failure (preserved).
        # - On total failure, raise ``ValueError`` so the caller (router)
        #   surfaces the error to the client.
        from app.integrations.email_sender import EmailMessage, send_email
        from app.modules.notifications.service import log_email_sent

        customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip()
        email_subject = subject or f"Message from {org_name}"

        # Build plain-text + HTML email
        html_body = "".join(
            f"<p>{line}</p>" if line.strip() else "<br/>"
            for line in message.split("\n")
        )

        email_message = EmailMessage(
            to_email=customer.email,
            to_name=customer_name,
            subject=email_subject,
            html_body=html_body,
            text_body=message,
            attachments=[],
            org_id=customer.org_id,
        )

        result = await send_email(
            db,
            email_message,
            org_sender_name=org_name,
        )

        if result.success:
            logger.info(
                "Email sent to customer %s via %s",
                customer_id, result.provider_key,
            )

            # Log the successful email send
            try:
                await log_email_sent(
                    db, org_id=org_id, recipient=customer.email,
                    template_type="customer_notify", subject=email_subject,
                    status="sent", sent_at=datetime.now(timezone.utc),
                    provider_key=result.provider_key,
                    provider_message_id=result.provider_message_id,
                )
            except Exception:
                logger.warning("Failed to log email send for customer %s", customer_id)
        else:
            last_error = result.error or "send failed"

            # Log the failed email attempt
            try:
                await log_email_sent(
                    db, org_id=org_id, recipient=customer.email,
                    template_type="customer_notify", subject=email_subject,
                    status="failed", error_message=str(last_error),
                )
            except Exception:
                logger.warning("Failed to log email failure for customer %s", customer_id)

            # Create in-app notification for email failure (Req 4.3.1)
            from app.modules.in_app_notifications.service import create_in_app_notification

            await create_in_app_notification(
                db,
                org_id=org_id,
                category="email_failure",
                severity="error",
                title=f"Failed to email customer notification to {customer.email}",
                body=str(last_error)[:1500],
                link_url=f"/customers/{customer_id}",
                entity_type="customer",
                entity_id=customer_id,
                audience_roles=["org_admin", "salesperson"],
                metadata={
                    "recipient_email": customer.email,
                    "template_type": "customer_notify",
                    "error_message": str(last_error),
                },
            )

            raise ValueError(f"All email providers failed. Last error: {last_error}")

    elif channel == "sms":
        if not customer.phone:
            raise ValueError("Customer has no phone number on file")
        recipient = customer.phone

        from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
        from app.integrations.sms_types import SmsMessage as SmsMsg
        from app.modules.admin.models import SmsVerificationProvider
        from app.core.encryption import envelope_decrypt_str
        from app.modules.admin.service import increment_sms_usage
        from app.modules.notifications.service import log_sms_sent

        # Load active SMS provider
        sms_result = await db.execute(
            select(SmsVerificationProvider).where(
                SmsVerificationProvider.provider_key == "connexus",
                SmsVerificationProvider.is_active.is_(True),
            )
        )
        sms_provider = sms_result.scalar_one_or_none()

        if sms_provider and sms_provider.credentials_encrypted:
            import json
            creds_json = envelope_decrypt_str(sms_provider.credentials_encrypted)
            creds = json.loads(creds_json)
            if sms_provider.config and sms_provider.config.get("token_refresh_interval_seconds"):
                creds["token_refresh_interval_seconds"] = sms_provider.config["token_refresh_interval_seconds"]
            config = ConnexusConfig.from_dict(creds)
            client = ConnexusSmsClient(config)
            try:
                sms_msg = SmsMsg(to_number=customer.phone, body=message)
                sms_send = await client.send(sms_msg)
            finally:
                await client.close()

            if not sms_send.success:
                error_msg = sms_send.error or "SMS send failed"
                # Log the failed attempt
                try:
                    await log_sms_sent(
                        db, org_id=org_id, recipient=customer.phone,
                        template_type="customer_notify", body=message,
                        status="failed", error_message=error_msg,
                    )
                except Exception:
                    logger.warning("Failed to log SMS send failure for customer %s", customer_id)
                # Surface a clearer message for auth failures
                if "401" in error_msg:
                    raise ValueError(
                        "SMS authentication failed (401). Your Connexus credentials may have "
                        "expired or been rotated. Please re-enter them in Admin → SMS Providers "
                        "and test the connection."
                    )
                raise ValueError(error_msg)

            # Track SMS usage
            try:
                await increment_sms_usage(db, org_id)
            except Exception:
                logger.error("Failed to increment SMS usage for org %s", org_id)

            # Log the successful send
            try:
                await log_sms_sent(
                    db, org_id=org_id, recipient=customer.phone,
                    template_type="customer_notify", body=message,
                    status="sent", sent_at=datetime.now(timezone.utc),
                )
            except Exception:
                logger.warning("Failed to log SMS send for customer %s", customer_id)

            logger.info("SMS sent to customer %s", customer_id)
        else:
            raise ValueError("SMS provider not configured. Set up an SMS provider in Admin > SMS Providers.")

    else:
        raise ValueError(f"Unsupported notification channel: {channel}")

    # Audit log the notification (no PII in log values)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action=f"customer.notify.{channel}",
        entity_type="customer",
        entity_id=customer_id,
        before_value=None,
        after_value={"channel": channel, "has_subject": subject is not None},
        ip_address=ip_address,
    )

    return {
        "message": f"Notification sent via {channel}",
        "channel": channel,
        "recipient": recipient,
    }


async def tag_vehicle_to_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    global_vehicle_id: uuid.UUID | None = None,
    org_vehicle_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Link a vehicle to a customer.

    Exactly one of ``global_vehicle_id`` or ``org_vehicle_id`` must be provided.

    vehicle-data-isolation Task 9.1: when ``global_vehicle_id`` is supplied,
    promote the vehicle for the calling org first via ``promote_vehicle`` and
    create the link with ``org_vehicle_id`` set / ``global_vehicle_id`` cleared
    so the resulting ``customer_vehicles`` row points at the per-org snapshot,
    not the cross-tenant cache (Req 2.3, 3.6).

    Pre-flight controller-guard check: ``app/modules/customers/router.py``
    exposes this via ``POST /api/v1/customers/{customer_id}/vehicles`` and
    performs no duplicate-link check before invoking us — silently allowing
    duplicate ``customer_vehicles`` rows for the same ``(org_id, customer_id,
    rego)`` is the same defect Task 11.7 fixes elsewhere. We add the guard
    here at the service layer using the post-promotion identity (rego-keyed
    via the matching ``OrgVehicle``/``GlobalVehicle.rego``), and raise
    ``ConflictError`` so the router can return HTTP 409.

    Requirements: 12.3, 2.3, 3.6
    Design: Code Changes per File → ``app/modules/customers/service.py``.
    """
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    # Validate exactly one vehicle reference
    if (global_vehicle_id is None) == (org_vehicle_id is None):
        raise ValueError(
            "Exactly one of global_vehicle_id or org_vehicle_id must be provided"
        )

    # Verify customer exists
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    # Verify vehicle exists. For a global_vehicle_id, promote the rego for
    # this org so the link points at the per-org snapshot; rebind every
    # variable that referenced the pre-promotion identity (gv) to the new
    # OrgVehicle (ov) BEFORE the link-existence check and the
    # ``CustomerVehicle`` constructor (Implementation Note — Local Variable
    # Rebinding After Promotion).
    vehicle_info: dict = {}
    target_rego: str | None = None
    if global_vehicle_id:
        gv_result = await db.execute(
            select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
        )
        gv = gv_result.scalar_one_or_none()
        if gv is None:
            raise ValueError("Global vehicle not found")

        # Promote first — returns the existing org_vehicles row idempotently
        # if the org has already been promoted for this rego.
        from app.modules.vehicles.service import promote_vehicle

        ov = await promote_vehicle(
            db,
            org_id=org_id,
            global_vehicle_id=gv.id,
            source_record=gv,
            user_id=user_id,
            trigger_site="customers.link",
            ip_address=ip_address,
        )

        # Rebind so the existence check and CustomerVehicle constructor
        # below see the post-promotion identity. global_vehicle_id is set
        # to None on the link to satisfy the either-or vehicle_link_check
        # constraint and Req 2.3.
        global_vehicle_id = None
        org_vehicle_id = ov.id
        target_rego = ov.rego
        vehicle_info = {
            "rego": ov.rego,
            "make": ov.make,
            "model": ov.model,
            "year": ov.year,
            "colour": ov.colour,
            "source": "org",
        }
    else:
        ov_result = await db.execute(
            select(OrgVehicle).where(
                OrgVehicle.id == org_vehicle_id,
                OrgVehicle.org_id == org_id,
            )
        )
        ov = ov_result.scalar_one_or_none()
        if ov is None:
            raise ValueError("Organisation vehicle not found")
        target_rego = ov.rego
        vehicle_info = {
            "rego": ov.rego,
            "make": ov.make,
            "model": ov.model,
            "year": ov.year,
            "colour": ov.colour,
            "source": "org",
        }

    # Pre-flight duplicate-link guard — same defect Task 11.7 fixes at the
    # invoice/booking/kiosk/fleet-portal sites. Use the post-promotion
    # identity (org_vehicle_id) — at this point all paths have set
    # global_vehicle_id=None and org_vehicle_id=<the resolved OrgVehicle.id>.
    # Also include the rego-keyed match against any unmigrated link still
    # pointing at a global_vehicles row for the same rego (covers the case
    # where promotion was a no-op because the OrgVehicle already existed
    # but a stale global-id-keyed link is still on file).
    duplicate_q = select(CustomerVehicle).where(
        CustomerVehicle.org_id == org_id,
        CustomerVehicle.customer_id == customer_id,
        CustomerVehicle.org_vehicle_id == org_vehicle_id,
    ).limit(1)
    existing = await db.execute(duplicate_q)
    if existing.scalar_one_or_none() is not None:
        raise LookupError(
            "Vehicle is already linked to this customer"
        )
    if target_rego:
        # Catch unmigrated legacy links keyed on global_vehicle_id for the
        # same rego (Task 11.7 fallout — duplicate-prevention must use the
        # post-promotion identity AND any pre-existing global-id-keyed link
        # for the same rego).
        legacy_q = (
            select(CustomerVehicle)
            .join(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
            .where(
                CustomerVehicle.org_id == org_id,
                CustomerVehicle.customer_id == customer_id,
                func.upper(GlobalVehicle.rego) == target_rego.upper(),
            )
            .limit(1)
        )
        legacy_existing = await db.execute(legacy_q)
        if legacy_existing.scalar_one_or_none() is not None:
            raise LookupError(
                "Vehicle is already linked to this customer"
            )

    # Create the link
    cv = CustomerVehicle(
        org_id=org_id,
        customer_id=customer_id,
        global_vehicle_id=global_vehicle_id,
        org_vehicle_id=org_vehicle_id,
    )
    db.add(cv)
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.vehicle_tagged",
        entity_type="customer_vehicle",
        entity_id=cv.id,
        before_value=None,
        after_value={
            "customer_id": str(customer_id),
            "global_vehicle_id": str(global_vehicle_id) if global_vehicle_id else None,
            "org_vehicle_id": str(org_vehicle_id) if org_vehicle_id else None,
        },
        ip_address=ip_address,
    )

    return {
        "id": str(cv.id),
        **vehicle_info,
        "linked_at": cv.linked_at.isoformat() if cv.linked_at else None,
    }


# ---------------------------------------------------------------------------
# Task 7.3 — Customer record merging
# Requirements: 12.4
# ---------------------------------------------------------------------------


async def merge_customers(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    target_customer_id: uuid.UUID,
    source_customer_id: uuid.UUID,
    preview_only: bool = True,
    ip_address: str | None = None,
) -> dict:
    """Merge source customer into target customer.

    When ``preview_only`` is True, returns a preview of what will be combined
    without making changes. When False, executes the merge:
    - Moves all invoices from source to target
    - Moves all vehicle links from source to target
    - Transfers fleet account if target has none
    - Fills contact detail gaps on target from source
    - Marks source customer as inactive (anonymised)
    - Writes audit log entry

    Requirements: 12.4
    """
    from app.modules.invoices.models import Invoice
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    if target_customer_id == source_customer_id:
        raise ValueError("Cannot merge a customer with themselves")

    # Fetch target customer
    target_result = await db.execute(
        select(Customer).where(
            Customer.id == target_customer_id,
            Customer.org_id == org_id,
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise ValueError("Target customer not found")

    if target.is_anonymised:
        raise ValueError("Cannot merge into an anonymised customer")

    # Fetch source customer
    source_result = await db.execute(
        select(Customer).where(
            Customer.id == source_customer_id,
            Customer.org_id == org_id,
        )
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise ValueError("Source customer not found")

    if source.is_anonymised:
        raise ValueError("Cannot merge from an anonymised customer")

    # Gather vehicles to transfer from source
    cv_stmt = select(CustomerVehicle).where(
        CustomerVehicle.customer_id == source_customer_id,
        CustomerVehicle.org_id == org_id,
    )
    cv_result = await db.execute(cv_stmt)
    source_vehicles = cv_result.scalars().all()

    vehicles_preview = []
    for cv in source_vehicles:
        info = {"id": str(cv.id), "rego": None, "make": None, "model": None, "year": None, "source": "global"}
        if cv.global_vehicle_id:
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == cv.global_vehicle_id)
            )
            gv = gv_result.scalar_one_or_none()
            if gv:
                info.update(rego=gv.rego, make=gv.make, model=gv.model, year=gv.year, source="global")
        elif cv.org_vehicle_id:
            ov_result = await db.execute(
                select(OrgVehicle).where(
                    OrgVehicle.id == cv.org_vehicle_id,
                    OrgVehicle.org_id == org_id,
                )
            )
            ov = ov_result.scalar_one_or_none()
            if ov:
                info.update(rego=ov.rego, make=ov.make, model=ov.model, year=ov.year, source="org")
        vehicles_preview.append(info)

    # Gather invoices to transfer from source
    inv_stmt = select(Invoice).where(
        Invoice.customer_id == source_customer_id,
        Invoice.org_id == org_id,
    )
    inv_result = await db.execute(inv_stmt)
    source_invoices = inv_result.scalars().all()

    invoices_preview = [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "status": inv.status,
            "total": str(inv.total),
        }
        for inv in source_invoices
    ]

    # Determine contact detail changes (target kept, source fills gaps)
    merged_email = target.email or source.email
    merged_phone = target.phone or source.phone
    merged_address = target.address or source.address

    # Combine notes
    merged_notes = target.notes
    if source.notes:
        if merged_notes:
            merged_notes = f"{merged_notes}\n---\n[Merged from {source.first_name} {source.last_name}]: {source.notes}"
        else:
            merged_notes = source.notes

    contact_changes = {
        "email": merged_email,
        "phone": merged_phone,
        "address": merged_address,
        "notes": merged_notes,
    }

    # Check fleet account transfer
    fleet_transfer = False
    if source.fleet_account_id and not target.fleet_account_id:
        fleet_transfer = True

    preview = {
        "target_customer": _customer_to_dict(target),
        "source_customer": _customer_to_dict(source),
        "vehicles_to_transfer": vehicles_preview,
        "invoices_to_transfer": invoices_preview,
        "contact_changes": contact_changes,
        "fleet_account_transfer": fleet_transfer,
    }

    if preview_only:
        return {
            "message": "Merge preview generated",
            "preview": preview,
            "merged": False,
        }

    # Execute the merge
    # 1. Move invoices from source to target
    for inv in source_invoices:
        inv.customer_id = target_customer_id

    # 2. Move vehicle links from source to target
    for cv in source_vehicles:
        cv.customer_id = target_customer_id

    # 3. Transfer fleet account if applicable
    if fleet_transfer:
        target.fleet_account_id = source.fleet_account_id
        source.fleet_account_id = None

    # 4. Fill contact detail gaps on target
    if not target.email and source.email:
        target.email = source.email
    if not target.phone and source.phone:
        target.phone = source.phone
    if not target.address and source.address:
        target.address = source.address
    target.notes = merged_notes

    # 5. Mark source as merged/inactive
    source.first_name = "Merged"
    source.last_name = "Customer"
    source.email = None
    source.phone = None
    source.address = None
    source.notes = f"Merged into customer {target_customer_id}"
    source.is_anonymised = True

    await db.flush()

    # 6. Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.merged",
        entity_type="customer",
        entity_id=target_customer_id,
        before_value={
            "source_customer_id": str(source_customer_id),
            "invoices_transferred": len(source_invoices),
            "vehicles_transferred": len(source_vehicles),
        },
        after_value={
            "target_customer_id": str(target_customer_id),
            "fleet_account_transferred": fleet_transfer,
            "contact_gaps_filled": {
                "email": bool(not _customer_to_dict(target).get("email") and source.email),
                "phone": bool(not _customer_to_dict(target).get("phone") and source.phone),
                "address": bool(not _customer_to_dict(target).get("address") and source.address),
            },
        },
        ip_address=ip_address,
    )

    return {
        "message": "Customers merged successfully",
        "preview": preview,
        "merged": True,
    }


# ---------------------------------------------------------------------------
# Task 7.4 — Privacy Act 2020 compliance
# Requirements: 13.1, 13.2, 13.3, 13.4
# ---------------------------------------------------------------------------


async def anonymise_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Anonymise a customer record for Privacy Act 2020 compliance.

    - Sets is_anonymised=True
    - Replaces name with "Anonymised Customer"
    - Clears email, phone, address, notes, portal_token
    - Preserves all linked invoices with financial data intact
    - Anonymises customer name on linked invoices (invoice_data_json)

    Requirements: 13.1, 13.2
    """
    from app.modules.invoices.models import Invoice

    # Fetch customer
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    if customer.is_anonymised:
        raise ValueError("Customer is already anonymised")

    # Capture before state for audit (no PII in logs per Req 13.4)
    before_value = {
        "customer_id": str(customer_id),
        "had_email": customer.email is not None,
        "had_phone": customer.phone is not None,
        "had_address": customer.address is not None,
        "had_notes": customer.notes is not None,
    }

    # Anonymise the customer record
    customer.first_name = "Anonymised"
    customer.last_name = "Customer"
    customer.email = None
    customer.phone = None
    customer.address = None
    customer.notes = None
    customer.portal_token = None
    customer.is_anonymised = True

    # Fetch and update linked invoices — preserve financial data,
    # but clear customer PII from the stored JSON snapshot
    inv_stmt = select(Invoice).where(
        Invoice.customer_id == customer_id,
        Invoice.org_id == org_id,
    )
    inv_result = await db.execute(inv_stmt)
    invoices = inv_result.scalars().all()

    invoices_anonymised = 0
    for inv in invoices:
        # Update the JSON snapshot if it contains customer details
        if inv.invoice_data_json and isinstance(inv.invoice_data_json, dict):
            updated_json = dict(inv.invoice_data_json)
            if "customer_name" in updated_json:
                updated_json["customer_name"] = "Anonymised Customer"
            if "customer_email" in updated_json:
                updated_json["customer_email"] = None
            if "customer_phone" in updated_json:
                updated_json["customer_phone"] = None
            if "customer_address" in updated_json:
                updated_json["customer_address"] = None
            inv.invoice_data_json = updated_json
        invoices_anonymised += 1

    await db.flush()

    # Audit log — no PII written (Req 13.4)
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.anonymised",
        entity_type="customer",
        entity_id=customer_id,
        before_value=before_value,
        after_value={
            "is_anonymised": True,
            "invoices_anonymised": invoices_anonymised,
        },
        ip_address=ip_address,
    )

    # Log without PII (Req 13.4)
    logger.info(
        "Customer %s anonymised by user %s (org %s). %d invoices updated.",
        customer_id,
        user_id,
        org_id,
        invoices_anonymised,
    )

    return {
        "customer_id": str(customer_id),
        "is_anonymised": True,
        "invoices_preserved": invoices_anonymised,
    }


async def export_customer_data(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict:
    """Export all data for a customer as JSON for Privacy Act 2020 compliance.

    Includes: customer record, linked vehicles, invoices (with line items),
    and payments.

    Requirements: 13.3
    """
    from app.modules.invoices.models import Invoice, LineItem
    from app.modules.payments.models import Payment
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    # 1. Fetch customer
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    customer_data = _customer_to_dict(customer)

    # 2. Fetch linked vehicles
    cv_stmt = select(CustomerVehicle).where(
        CustomerVehicle.customer_id == customer_id,
        CustomerVehicle.org_id == org_id,
    )
    cv_result = await db.execute(cv_stmt)
    customer_vehicles = cv_result.scalars().all()

    vehicles = []
    for cv in customer_vehicles:
        vehicle_info = {
            "link_id": str(cv.id),
            "linked_at": cv.linked_at.isoformat() if cv.linked_at else None,
        }
        if cv.global_vehicle_id:
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == cv.global_vehicle_id)
            )
            gv = gv_result.scalar_one_or_none()
            if gv:
                vehicle_info.update({
                    "source": "global",
                    "rego": gv.rego,
                    "make": gv.make,
                    "model": gv.model,
                    "year": gv.year,
                    "colour": gv.colour,
                    "body_type": gv.body_type,
                    "fuel_type": gv.fuel_type,
                })
        elif cv.org_vehicle_id:
            ov_result = await db.execute(
                select(OrgVehicle).where(
                    OrgVehicle.id == cv.org_vehicle_id,
                    OrgVehicle.org_id == org_id,
                )
            )
            ov = ov_result.scalar_one_or_none()
            if ov:
                vehicle_info.update({
                    "source": "org",
                    "rego": ov.rego,
                    "make": ov.make,
                    "model": ov.model,
                    "year": ov.year,
                    "colour": ov.colour,
                })
        vehicles.append(vehicle_info)

    # 3. Fetch invoices with line items
    inv_stmt = (
        select(Invoice)
        .where(
            Invoice.customer_id == customer_id,
            Invoice.org_id == org_id,
        )
        .order_by(Invoice.created_at.desc())
    )
    inv_result = await db.execute(inv_stmt)
    invoices = inv_result.scalars().all()

    invoice_list = []
    for inv in invoices:
        # Fetch line items for this invoice
        li_stmt = select(LineItem).where(
            LineItem.invoice_id == inv.id,
            LineItem.org_id == org_id,
        ).order_by(LineItem.sort_order)
        li_result = await db.execute(li_stmt)
        line_items = li_result.scalars().all()

        line_item_list = [
            {
                "id": str(li.id),
                "item_type": li.item_type,
                "description": li.description,
                "quantity": str(li.quantity),
                "unit_price": str(li.unit_price),
                "line_total": str(li.line_total),
                "is_gst_exempt": li.is_gst_exempt,
            }
            for li in line_items
        ]

        # Fetch payments for this invoice
        pay_stmt = select(Payment).where(
            Payment.invoice_id == inv.id,
            Payment.org_id == org_id,
        ).order_by(Payment.created_at)
        pay_result = await db.execute(pay_stmt)
        payments = pay_result.scalars().all()

        payment_list = [
            {
                "id": str(p.id),
                "amount": str(p.amount),
                "method": p.method,
                "is_refund": p.is_refund,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ]

        invoice_list.append({
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "status": inv.status,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "subtotal": str(inv.subtotal),
            "gst_amount": str(inv.gst_amount),
            "total": str(inv.total),
            "amount_paid": str(inv.amount_paid),
            "balance_due": str(inv.balance_due),
            "vehicle_rego": inv.vehicle_rego,
            "line_items": line_item_list,
            "payments": payment_list,
        })

    return {
        "customer": customer_data,
        "vehicles": vehicles,
        "invoices": invoice_list,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Task 7.5 — Fleet account management
# Requirements: 66.1, 66.2
# ---------------------------------------------------------------------------

from app.modules.customers.models import FleetAccount


def _fleet_account_to_dict(fa: FleetAccount, customer_count: int = 0) -> dict:
    """Convert a FleetAccount ORM instance to a serialisable dict."""
    return {
        "id": str(fa.id),
        "name": fa.name,
        "primary_contact_name": fa.primary_contact_name,
        "primary_contact_email": fa.primary_contact_email,
        "primary_contact_phone": fa.primary_contact_phone,
        "billing_address": fa.billing_address,
        "notes": fa.notes,
        "pricing_overrides": fa.pricing_overrides or {},
        "customer_count": customer_count,
        "created_at": fa.created_at.isoformat() if fa.created_at else None,
        "updated_at": fa.updated_at.isoformat() if fa.updated_at else None,
    }


async def list_fleet_accounts(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """List all fleet accounts for an organisation.

    Requirements: 66.1
    """
    base_filter = [FleetAccount.org_id == org_id]

    count_stmt = select(func.count(FleetAccount.id)).where(*base_filter)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(FleetAccount)
        .where(*base_filter)
        .order_by(FleetAccount.name)
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    fleet_accounts = result.scalars().all()

    # Get customer counts per fleet account
    items = []
    for fa in fleet_accounts:
        count_q = select(func.count(Customer.id)).where(
            Customer.org_id == org_id,
            Customer.fleet_account_id == fa.id,
            Customer.is_anonymised.is_(False),
        )
        cust_count = (await db.execute(count_q)).scalar() or 0
        items.append(_fleet_account_to_dict(fa, customer_count=cust_count))

    return {
        "fleet_accounts": items,
        "total": total,
    }


async def create_fleet_account(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    primary_contact_name: str | None = None,
    primary_contact_email: str | None = None,
    primary_contact_phone: str | None = None,
    billing_address: str | None = None,
    notes: str | None = None,
    pricing_overrides: dict | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new fleet account.

    Requirements: 66.1
    """
    fa = FleetAccount(
        org_id=org_id,
        name=name,
        primary_contact_name=primary_contact_name,
        primary_contact_email=primary_contact_email,
        primary_contact_phone=primary_contact_phone,
        billing_address=billing_address,
        notes=notes,
        pricing_overrides=pricing_overrides or {},
    )
    db.add(fa)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="fleet_account.created",
        entity_type="fleet_account",
        entity_id=fa.id,
        before_value=None,
        after_value={"name": name},
        ip_address=ip_address,
    )

    return _fleet_account_to_dict(fa, customer_count=0)


async def get_fleet_account(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    fleet_account_id: uuid.UUID,
) -> dict:
    """Retrieve a single fleet account by ID.

    Raises ValueError if not found.
    Requirements: 66.1
    """
    result = await db.execute(
        select(FleetAccount).where(
            FleetAccount.id == fleet_account_id,
            FleetAccount.org_id == org_id,
        )
    )
    fa = result.scalar_one_or_none()
    if fa is None:
        raise ValueError("Fleet account not found")

    count_q = select(func.count(Customer.id)).where(
        Customer.org_id == org_id,
        Customer.fleet_account_id == fa.id,
        Customer.is_anonymised.is_(False),
    )
    cust_count = (await db.execute(count_q)).scalar() or 0

    return _fleet_account_to_dict(fa, customer_count=cust_count)


async def update_fleet_account(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    fleet_account_id: uuid.UUID,
    ip_address: str | None = None,
    **kwargs,
) -> dict:
    """Update a fleet account. Only non-None kwargs are applied.

    Requirements: 66.1, 66.2
    """
    result = await db.execute(
        select(FleetAccount).where(
            FleetAccount.id == fleet_account_id,
            FleetAccount.org_id == org_id,
        )
    )
    fa = result.scalar_one_or_none()
    if fa is None:
        raise ValueError("Fleet account not found")

    allowed_fields = {
        "name", "primary_contact_name", "primary_contact_email",
        "primary_contact_phone", "billing_address", "notes",
        "pricing_overrides",
    }
    before_value = {}
    updated_fields = []

    for field in allowed_fields:
        value = kwargs.get(field)
        if value is not None:
            before_value[field] = getattr(fa, field)
            # Serialise dict fields for audit log
            if isinstance(before_value[field], dict):
                before_value[field] = dict(before_value[field])
            setattr(fa, field, value)
            updated_fields.append(field)

    if not updated_fields:
        count_q = select(func.count(Customer.id)).where(
            Customer.org_id == org_id,
            Customer.fleet_account_id == fa.id,
            Customer.is_anonymised.is_(False),
        )
        cust_count = (await db.execute(count_q)).scalar() or 0
        return _fleet_account_to_dict(fa, customer_count=cust_count)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="fleet_account.updated",
        entity_type="fleet_account",
        entity_id=fa.id,
        before_value=before_value,
        after_value={f: kwargs[f] for f in updated_fields},
        ip_address=ip_address,
    )

    count_q = select(func.count(Customer.id)).where(
        Customer.org_id == org_id,
        Customer.fleet_account_id == fa.id,
        Customer.is_anonymised.is_(False),
    )
    cust_count = (await db.execute(count_q)).scalar() or 0

    return _fleet_account_to_dict(fa, customer_count=cust_count)


async def delete_fleet_account(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    fleet_account_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Delete a fleet account and unlink all associated customers.

    Requirements: 66.1
    """
    result = await db.execute(
        select(FleetAccount).where(
            FleetAccount.id == fleet_account_id,
            FleetAccount.org_id == org_id,
        )
    )
    fa = result.scalar_one_or_none()
    if fa is None:
        raise ValueError("Fleet account not found")

    # Unlink all customers from this fleet account
    cust_stmt = select(Customer).where(
        Customer.org_id == org_id,
        Customer.fleet_account_id == fleet_account_id,
    )
    cust_result = await db.execute(cust_stmt)
    linked_customers = cust_result.scalars().all()
    for cust in linked_customers:
        cust.fleet_account_id = None

    await db.delete(fa)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="fleet_account.deleted",
        entity_type="fleet_account",
        entity_id=fleet_account_id,
        before_value={"name": fa.name, "customers_unlinked": len(linked_customers)},
        after_value=None,
        ip_address=ip_address,
    )

    return {
        "fleet_account_id": str(fleet_account_id),
    }


# ---------------------------------------------------------------------------
# Per-customer reminder configuration (stored in custom_fields JSONB)
# ---------------------------------------------------------------------------

REMINDER_CONFIG_KEY = "reminder_config"

DEFAULT_REMINDER_DAYS = 30

VALID_REMINDER_TYPES = {"service_due", "wof_expiry"}
VALID_CHANNELS = {"email", "sms", "both"}


def _default_reminder_entry() -> dict:
    return {
        "enabled": False,
        "days_before": DEFAULT_REMINDER_DAYS,
        "channel": "email",
    }


async def get_customer_reminder_config(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict:
    """Return per-customer reminder configuration with vehicle expiry data."""
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    custom_fields = customer.custom_fields or {}
    config = custom_fields.get(REMINDER_CONFIG_KEY, {})

    # Fetch linked vehicles with expiry dates.
    #
    # vehicle-data-isolation Task 11.2: use a double outerjoin so we
    # capture both link types — pre-promotion links pointing at
    # GlobalVehicle and post-promotion links pointing at OrgVehicle.
    # The previous inner-join on global_vehicle_id silently dropped any
    # link migrated to org_vehicle_id, hiding promoted vehicles from
    # the reminder configuration UI (Req 6.1, 6.2, 6.5, 15.5).
    cv_stmt = (
        select(CustomerVehicle, GlobalVehicle, OrgVehicle)
        .outerjoin(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
        .outerjoin(OrgVehicle, CustomerVehicle.org_vehicle_id == OrgVehicle.id)
        .where(
            CustomerVehicle.customer_id == customer_id,
            CustomerVehicle.org_id == org_id,
        )
    )
    cv_result = await db.execute(cv_stmt)
    vehicle_rows = cv_result.all()

    vehicles = []
    for cv, gv, ov in vehicle_rows:
        # Prefer the per-org snapshot when available (post-promotion);
        # fall back to the cross-tenant cache for unmigrated links
        # (Read_Fallback per Req 6.5). The vehicle_link_check CHECK
        # constraint guarantees exactly one of (gv, ov) is non-NULL.
        v = gv if gv is not None else ov
        if v is None:
            continue
        vehicles.append({
            # Preserve the existing payload key for backwards compatibility
            # (frontend keys `vehicleDateEdits` by this id). For promoted
            # links we report the org_vehicle id; for legacy links we
            # report the global_vehicle id. Either is valid input to
            # update_vehicle_expiry_dates which resolves both forms.
            "global_vehicle_id": str(v.id),
            "rego": v.rego,
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "service_due_date": v.service_due_date.isoformat() if v.service_due_date else None,
            "wof_expiry": v.wof_expiry.isoformat() if v.wof_expiry else None,
        })

    return {
        "service_due": config.get("service_due", _default_reminder_entry()),
        "wof_expiry": config.get("wof_expiry", _default_reminder_entry()),
        "vehicles": vehicles,
    }


async def update_customer_reminder_config(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    reminders: dict,
) -> dict:
    """Update per-customer reminder configuration.

    reminders should be a dict like:
    {
        "service_due": {"enabled": true, "days_before": 30, "channel": "both"},
        "wof_expiry": {"enabled": true, "days_before": 14, "channel": "sms"},
    }
    """
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    # Validate and build config
    validated: dict = {}
    for rtype in VALID_REMINDER_TYPES:
        entry = reminders.get(rtype, {})
        validated[rtype] = {
            "enabled": bool(entry.get("enabled", False)),
            "days_before": max(1, min(365, int(entry.get("days_before", DEFAULT_REMINDER_DAYS)))),
            "channel": entry.get("channel", "email") if entry.get("channel") in VALID_CHANNELS else "email",
        }

    # Merge into custom_fields
    custom_fields = dict(customer.custom_fields or {})
    custom_fields[REMINDER_CONFIG_KEY] = validated
    customer.custom_fields = custom_fields

    await db.flush()
    await db.refresh(customer)

    return validated


async def update_vehicle_expiry_dates(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    vehicle_updates: list[dict],
    user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> list[dict]:
    """Update service_due_date, wof_expiry, and cof_expiry on the calling
    org's per-org snapshot of vehicles linked to a customer.

    vehicle_updates is a list of dicts like::

        [
            {
                "global_vehicle_id": "...",
                "service_due_date": "2026-06-01",
                "wof_expiry": "2026-05-15",
                "cof_expiry": "2026-05-15",
            },
        ]

    Only updates fields that are provided (non-None). Returns updated
    vehicle data.

    vehicle-data-isolation Task 10.1: previously this function wrote
    ``service_due_date`` and ``wof_expiry`` directly to ``global_vehicles``,
    leaking customer-driven state across organisations (Req 1.2). It now:

    1. If the linked vehicle resolves to a ``GlobalVehicle`` and the org
       has not yet been promoted for this rego, calls ``promote_vehicle``
       to copy the row into ``org_vehicles`` for the calling org, then
       writes the new dates to that ``OrgVehicle`` (Req 2.2, 3.6, 14.1).
    2. Migrates the ``customer_vehicles`` link from ``global_vehicle_id``
       to ``org_vehicle_id`` via ``migrate_link_to_org_vehicle`` so
       subsequent reads resolve to the per-org snapshot (Req 2.4).
    3. If the linked vehicle already resolves to an ``OrgVehicle`` for
       this org (the link was migrated by an earlier promotion, but the
       client still keys ``vehicleDateEdits`` by the original
       ``global_vehicles`` id), writes directly without re-promoting.
    4. Adds the previously-missing ``cof_expiry`` branch — the endpoint
       was silently dropping ``cof_expiry`` from the request payload
       (frontend already sends it; backend was discarding it).

    The payload key remains ``global_vehicle_id`` for backwards
    compatibility — the frontend keys ``vehicleDateEdits`` by the id it
    receives from search/profile endpoints, which today is the
    ``global_vehicles`` row id. We accept that id and resolve the
    matching link via either ``cv.global_vehicle_id == :id`` (legacy
    unmigrated link) or by rego-matching when the link has already
    been migrated to ``org_vehicle_id`` for this org.

    Requirements: 1.2, 1.5, 2.2, 2.4, 3.6, 9.4, 9.5, 14.1
    Design: Code Changes per File → ``app/modules/customers/service.py``
            (extend ``update_vehicle_expiry_dates``).
    """
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.vehicles.service import (
        migrate_link_to_org_vehicle,
        promote_vehicle,
    )
    from app.modules.admin.models import GlobalVehicle
    from datetime import date

    # Verify customer exists
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    updated = []
    for vu in vehicle_updates:
        gv_id_str = vu.get("global_vehicle_id")
        if not gv_id_str:
            continue

        try:
            payload_id = uuid.UUID(gv_id_str)
        except (ValueError, TypeError):
            continue

        # Resolve the link for this customer. Two cases:
        #   (a) Legacy / pre-promotion link — cv.global_vehicle_id ==
        #       payload_id (the row in customer_vehicles still points
        #       at global_vehicles).
        #   (b) Already-promoted link — the frontend sent the original
        #       global_vehicle_id but the link was migrated to
        #       org_vehicle_id by a previous promotion; locate it by
        #       rego-matching the OrgVehicle row for this org.
        cv_result = await db.execute(
            select(CustomerVehicle).where(
                CustomerVehicle.customer_id == customer_id,
                CustomerVehicle.org_id == org_id,
                CustomerVehicle.global_vehicle_id == payload_id,
            )
        )
        cv = cv_result.scalar_one_or_none()

        target_ov: OrgVehicle | None = None
        target_gv: GlobalVehicle | None = None

        if cv is not None:
            # Legacy link path. Need to promote (or look up an existing
            # promoted org_vehicles row by rego) before writing.
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == payload_id)
            )
            target_gv = gv_result.scalar_one_or_none()
            if target_gv is None:
                continue
        else:
            # No legacy link found. Try the already-promoted path: look
            # up the GlobalVehicle by id (still cached cross-tenant), find
            # this org's OrgVehicle for that rego, then locate the
            # customer_vehicles row pointing at that OrgVehicle.
            gv_result = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == payload_id)
            )
            gv_for_lookup = gv_result.scalar_one_or_none()
            if gv_for_lookup is not None:
                ov_result = await db.execute(
                    select(OrgVehicle).where(
                        OrgVehicle.org_id == org_id,
                        func.upper(OrgVehicle.rego) == func.upper(gv_for_lookup.rego),
                    )
                )
                ov_lookup = ov_result.scalar_one_or_none()
                if ov_lookup is not None:
                    cv2_result = await db.execute(
                        select(CustomerVehicle).where(
                            CustomerVehicle.customer_id == customer_id,
                            CustomerVehicle.org_id == org_id,
                            CustomerVehicle.org_vehicle_id == ov_lookup.id,
                        )
                    )
                    cv = cv2_result.scalar_one_or_none()
                    if cv is not None:
                        target_ov = ov_lookup
            if cv is None:
                # No matching link for this customer — skip silently as
                # the legacy code did.
                continue

        # If we still have a GlobalVehicle to promote, do it now and
        # migrate the link so subsequent reads resolve to the per-org
        # snapshot. promote_vehicle is idempotent — if another path
        # already promoted this rego in the current transaction it
        # returns the existing OrgVehicle.
        if target_ov is None and target_gv is not None:
            target_ov = await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=target_gv.id,
                source_record=target_gv,
                user_id=user_id,
                trigger_site="customers.update_vehicle_dates",
                ip_address=ip_address,
            )
            # Migrate only when the link still points at the global row
            # (covers the case where target_ov pre-existed via a manual
            # entry but cv was created against global_vehicle_id).
            if cv.global_vehicle_id is not None and cv.org_vehicle_id is None:
                await migrate_link_to_org_vehicle(
                    db,
                    customer_vehicle_id=cv.id,
                    org_vehicle_id=target_ov.id,
                )

        if target_ov is None:
            continue

        # Apply the writes to the per-org snapshot. global_vehicles is
        # never touched (Req 1.2).
        sdd = vu.get("service_due_date")
        if sdd is not None:
            try:
                target_ov.service_due_date = date.fromisoformat(sdd) if sdd else None
            except (ValueError, TypeError):
                pass

        wof = vu.get("wof_expiry")
        if wof is not None:
            try:
                target_ov.wof_expiry = date.fromisoformat(wof) if wof else None
            except (ValueError, TypeError):
                pass

        cof = vu.get("cof_expiry")
        if cof is not None:
            try:
                target_ov.cof_expiry = date.fromisoformat(cof) if cof else None
            except (ValueError, TypeError):
                pass

        await db.flush()

        updated.append({
            # Preserve the request key name for backwards compatibility —
            # the frontend echoes this back when keying vehicleDateEdits.
            "global_vehicle_id": str(payload_id),
            "rego": target_ov.rego,
            "service_due_date": target_ov.service_due_date.isoformat() if target_ov.service_due_date else None,
            "wof_expiry": target_ov.wof_expiry.isoformat() if target_ov.wof_expiry else None,
            "cof_expiry": target_ov.cof_expiry.isoformat() if target_ov.cof_expiry else None,
        })

    return updated


# ---------------------------------------------------------------------------
# Task 5.2 — Send portal link to customer via email
# Requirements: 13.1, 13.2, 13.3, 13.4
# ---------------------------------------------------------------------------


async def send_portal_link(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    ip_address: str | None = None,
    base_url: str | None = None,
    # --- Send Email Modal override set (send-email-modal task 8.6) ---
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
    """Send the customer portal link to the customer's email address.

    Validates that the customer has portal access enabled, a valid portal
    token, and an email address on file. Sends the portal URL via the
    platform email infrastructure.

    This function serves two callers:

    1. **Auto-send / non-modal path** (the ``enable_portal`` transition in
       :func:`update_customer`, and any caller passing no override fields).
       This path is left EXACTLY as it was: it logs a ``"queued"``
       notification_log row and dispatches fire-and-forget via the async
       ``send_email_task``. The default subject/body strings are unchanged so
       the Send-Email-Modal byte-equivalence property (Property P1, portal_link
       case) holds.

    2. **Send Email Modal override path** (``POST
       /api/v2/customers/{id}/send-portal-link`` with an override payload).
       When ANY override field is set, the send switches to a **direct,
       synchronous** :func:`send_email` so the endpoint receives a
       ``SendResult`` and can map ``FailureKind`` → HTTP (R8.5–R8.8). It
       threads the full override set (recipients/cc/bcc, subject, sanitised
       body, ``allow_blocklisted``), writes the six notification_log audit
       columns on success, and raises :class:`EmailSendFailure` on failure.
       The portal_link surface offers NO attachments (R7.7) — any
       ``attachments`` token therefore raises
       :class:`InvalidAttachmentSelection`.

    Requirements: 2.6, 7.6, 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10,
                  11.2, 11.3, 11.5, 16.2
    """
    from app.config import settings
    from app.modules.admin.models import Organisation
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    # An override call is any invocation that sets at least one Send-Email-Modal
    # field. When none are set we are on the unchanged auto-send/queued path.
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

    # Fetch customer
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    # Validate portal access is enabled (Req 13.4)
    if not customer.enable_portal:
        raise ValueError("Portal access is not enabled for this customer")

    if customer.portal_token is None:
        raise ValueError("Customer does not have a portal token. Enable portal access first.")

    # Validate customer has an email address (Req 13.3). On the override path
    # the recipient may instead come from ``recipients``; that path resolves
    # and validates the recipient below.
    if not _is_override_call and not customer.email:
        raise ValueError("Customer has no email address on file")

    # Fetch org for branding
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Workshop"

    # Build portal URL — prefer caller-supplied base_url (from request
    # Origin header) over the static settings.frontend_base_url default.
    # See .kiro/specs/email-delivery-visibility-fixes/bugfix.md Bug 3.
    _base = (base_url or settings.frontend_base_url or "http://localhost").rstrip("/")
    portal_url = f"{_base}/portal/{customer.portal_token}"

    customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip()
    email_subject = f"Your Portal Access Link — {org_name}"

    html_body = f"""<p>Hi {customer_name or 'there'},</p>
<p>You can access your customer portal using the link below:</p>
<p><a href="{portal_url}" style="display:inline-block;padding:12px 24px;background-color:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;">Open Your Portal</a></p>
<p>Or copy this link: <a href="{portal_url}">{portal_url}</a></p>
<p>From your portal you can view invoices, quotes, bookings, and more.</p>
<p>Kind regards,<br/>{org_name}</p>"""

    text_body = (
        f"Hi {customer_name or 'there'},\n\n"
        f"You can access your customer portal using this link:\n"
        f"{portal_url}\n\n"
        f"From your portal you can view invoices, quotes, bookings, and more.\n\n"
        f"Kind regards,\n{org_name}"
    )

    # ------------------------------------------------------------------
    # Send Email Modal override path — direct synchronous send (R8.x).
    # ------------------------------------------------------------------
    if _is_override_call:
        from app.integrations.email_sender import EmailMessage, send_email
        from app.integrations.html_sanitise import sanitise_email_html
        from app.modules.email_compose.service import (
            EmailSendFailure,
            InvalidAttachmentSelection,
            compute_audit_hashes,
        )

        # The portal_link surface offers no attachments (R7.7). Any token is
        # therefore invalid; reject a non-empty selection. ``None`` or an empty
        # list proceeds with no attachments.
        if attachments:
            raise InvalidAttachmentSelection("Invalid attachment selection.")

        # Resolve the recipient: recipients[0] wins, else the customer email.
        _cc_list: list[str] = list(cc) if cc else []
        _bcc_list: list[str] = list(bcc) if bcc else []
        recipient_email: str | None = None
        if recipients:
            recipient_email = recipients[0]
            _cc_list = [*recipients[1:], *_cc_list]
        if not recipient_email:
            recipient_email = customer.email if customer.email else None
        if not recipient_email:
            raise ValueError(
                "Customer has no email address on file. Provide a recipient."
            )

        # Subject override or default (R8.1).
        final_subject = subject if subject is not None else email_subject

        # Body override (server-sanitised) or the default html body (R8.1, R10.1).
        final_html = (
            sanitise_email_html(body_html) if body_html is not None else html_body
        )

        # Audit hashes over the FINAL strings (R11.2, R11.3 / Property P4).
        _audit_hashes = compute_audit_hashes(final_subject, final_html)
        _edited_subject_hash = (
            _audit_hashes["subject_hash"] if subject_was_edited else None
        )
        _edited_body_hash = _audit_hashes["body_hash"] if body_was_edited else None

        message = EmailMessage(
            to_email=recipient_email,
            to_name=customer_name,
            subject=final_subject,
            html_body=final_html,
            text_body=text_body,
            attachments=[],
            cc=_cc_list,
            bcc=_bcc_list,
            org_id=org_id,
        )
        send_result = await send_email(
            db, message, allow_blocklisted=override_blocklist
        )

        if not send_result.success:
            last_error = send_result.error or "send failed"
            try:
                await log_email_sent(
                    db,
                    org_id=org_id,
                    recipient=recipient_email,
                    template_type="portal_link",
                    subject=final_subject,
                    status="failed",
                    error_message=str(last_error),
                )
            except Exception:
                logger.warning(
                    "Failed to log portal-link email failure for customer %s",
                    customer_id,
                )

            _last_attempt = (
                send_result.attempts[-1] if send_result.attempts else None
            )
            _failure_kind = (
                _last_attempt.failure_kind if _last_attempt else None
            )
            raise EmailSendFailure(
                _failure_kind,
                attempts=len(send_result.attempts),
                error=str(last_error),
            )

        # Success — write the notification_log row with the six audit columns.
        try:
            await log_email_sent(
                db,
                org_id=org_id,
                recipient=recipient_email,
                template_type="portal_link",
                subject=final_subject,
                status="sent",
                channel="email",
                sent_at=datetime.now(timezone.utc),
                provider_key=send_result.provider_key,
                provider_message_id=send_result.provider_message_id,
                subject_was_edited=subject_was_edited,
                body_was_edited=body_was_edited,
                edited_subject_hash=_edited_subject_hash,
                edited_body_hash=_edited_body_hash,
                cc_recipients=_cc_list,
                bcc_recipients=_bcc_list,
            )
        except Exception:
            logger.warning(
                "Failed to log portal-link email success for customer %s",
                customer_id,
            )

        # Audit log
        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="customer.portal_link_sent",
            entity_type="customer",
            entity_id=customer_id,
            before_value=None,
            after_value={"channel": "email", "has_email": True},
            ip_address=ip_address,
        )

        return {
            "message": "Portal link sent successfully",
            "recipient": recipient_email,
        }

    # ------------------------------------------------------------------
    # Default (non-modal) auto-send path — UNCHANGED queued behaviour.
    # ------------------------------------------------------------------
    # Log the email and dispatch via the async email task
    log_entry = await log_email_sent(
        db,
        org_id=org_id,
        recipient=customer.email,
        template_type="portal_link",
        subject=email_subject,
        status="queued",
    )

    await send_email_task(
        org_id=str(org_id),
        log_id=str(log_entry["id"]),
        to_email=customer.email,
        to_name=customer_name,
        subject=email_subject,
        html_body=html_body,
        text_body=text_body,
        org_sender_name=org_name,
        template_type="portal_link",
    )

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.portal_link_sent",
        entity_type="customer",
        entity_id=customer_id,
        before_value=None,
        after_value={"channel": "email", "has_email": True},
        ip_address=ip_address,
    )

    return {
        "message": "Portal link sent successfully",
        "recipient": customer.email,
    }


# ---------------------------------------------------------------------------
# Task 2.1 — Hard delete constants + preflight
# Requirements: 2.2, 2.3, 2.5, 2.6, 3.1, 6.1, 10.2, 10.3, 11.4
# ---------------------------------------------------------------------------

# Every invoice status that is NOT 'draft' — i.e. a legally-retained
# Financial_Document that blocks a customer hard delete (R2.1, R2.5).
ISSUED_INVOICE_STATUSES = (
    "issued",
    "partially_paid",
    "paid",
    "overdue",
    "voided",
    "refunded",
    "partially_refunded",
)

# New Zealand IRD seven-year retention warning shown before any hard-delete
# action (R3.1, R3.3).
NZ_RETENTION_WARNING = (
    "New Zealand tax law (IRD) requires tax invoices and business records to be "
    "kept for approximately 7 years. Deleting issued invoices or a customer with "
    "issued invoices may breach your record-keeping obligations. This action cannot "
    "be undone."
)


async def preflight_customer_deletion(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict:
    """Read-only assessment for the hard-delete confirmation screen.

    Returns whether the customer can be hard-deleted right now, the blocking
    documents that must be removed/resolved first (issued invoices, open
    claims, job cards, and fleet checklist submissions), the deletable draft
    invoices, and the vehicles that would be orphaned on a successful delete.

    Raises ``ValueError("Customer not found")`` when the customer does not
    exist within the requesting organisation (R9.4, R10.2).

    Requirements: 2.2, 2.3, 2.5, 2.6, 3.1, 6.1, 10.2, 10.3, 11.4
    """
    from app.modules.claims.models import CustomerClaim
    from app.modules.fleet_portal.models import FleetChecklistSubmission
    from app.modules.invoices.models import Invoice
    from app.modules.job_cards.models import JobCard
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    # ------------------------------------------------------------------
    # 1. Load the customer — org-scoped (R10.2, R10.3)
    # ------------------------------------------------------------------
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    # ------------------------------------------------------------------
    # 2. Issued (blocking) invoices — status IN ISSUED_INVOICE_STATUSES
    #    (R2.1, R2.2, R2.5)
    # ------------------------------------------------------------------
    issued_stmt = select(Invoice).where(
        Invoice.customer_id == customer_id,
        Invoice.org_id == org_id,
        Invoice.status.in_(ISSUED_INVOICE_STATUSES),
    )
    issued_result = await db.execute(issued_stmt)
    issued_invoices = issued_result.scalars().all()
    blocking_invoices = [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "status": inv.status,
        }
        for inv in issued_invoices
    ]

    # ------------------------------------------------------------------
    # 3. Draft invoices — surfaced so the UI can offer to delete them
    #    before proceeding (R2.5; drafts are non-blocking but require
    #    prior delete, per the Referential Integrity Matrix Row 2)
    # ------------------------------------------------------------------
    draft_stmt = select(Invoice).where(
        Invoice.customer_id == customer_id,
        Invoice.org_id == org_id,
        Invoice.status == "draft",
    )
    draft_result = await db.execute(draft_stmt)
    draft_invoices_orm = draft_result.scalars().all()
    draft_invoices = [
        {
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "status": inv.status,
        }
        for inv in draft_invoices_orm
    ]

    # ------------------------------------------------------------------
    # 4. Open customer claims — legal/financial records that block (D3,
    #    R11.4, Matrix Row 9)
    # ------------------------------------------------------------------
    claims_stmt = select(CustomerClaim).where(
        CustomerClaim.customer_id == customer_id,
        CustomerClaim.org_id == org_id,
    )
    claims_result = await db.execute(claims_stmt)
    claims_orm = claims_result.scalars().all()
    blocking_claims = [
        {
            "id": str(c.id),
            "claim_number": c.reference,
            "status": c.status,
        }
        for c in claims_orm
    ]

    # ------------------------------------------------------------------
    # 5. Job cards — work-order history blocks the delete (Matrix Row 8)
    # ------------------------------------------------------------------
    jc_stmt = select(JobCard).where(
        JobCard.customer_id == customer_id,
        JobCard.org_id == org_id,
    )
    jc_result = await db.execute(jc_stmt)
    jc_orm = jc_result.scalars().all()
    blocking_job_cards = [
        {
            "id": str(jc.id),
            "status": jc.status,
        }
        for jc in jc_orm
    ]

    # ------------------------------------------------------------------
    # 6. Fleet checklist submissions for the customer's vehicles —
    #    NZTA pre-trip inspection records block the delete (Matrix Row 20).
    #    These are linked via customer_vehicles.id, not directly via
    #    customer_id, so we first collect the customer's vehicle link IDs
    #    then query submissions for those IDs.
    # ------------------------------------------------------------------
    cv_stmt = select(CustomerVehicle).where(
        CustomerVehicle.customer_id == customer_id,
        CustomerVehicle.org_id == org_id,
    )
    cv_result = await db.execute(cv_stmt)
    customer_vehicles_all = cv_result.scalars().all()
    cv_ids = [cv.id for cv in customer_vehicles_all]

    blocking_fleet_checklists: list[dict] = []
    if cv_ids:
        fcs_stmt = select(FleetChecklistSubmission).where(
            FleetChecklistSubmission.customer_vehicle_id.in_(cv_ids),
        )
        fcs_result = await db.execute(fcs_stmt)
        fcs_orm = fcs_result.scalars().all()

        # Build a quick lookup: customer_vehicle_id → rego
        cv_to_rego: dict[uuid.UUID, str | None] = {}
        for cv in customer_vehicles_all:
            # Resolve rego from the linked vehicle row
            rego: str | None = None
            if cv.global_vehicle_id:
                gv_r = await db.execute(
                    select(GlobalVehicle.rego).where(
                        GlobalVehicle.id == cv.global_vehicle_id
                    )
                )
                rego = gv_r.scalar_one_or_none()
            elif cv.org_vehicle_id:
                ov_r = await db.execute(
                    select(OrgVehicle.rego).where(
                        OrgVehicle.id == cv.org_vehicle_id,
                        OrgVehicle.org_id == org_id,
                    )
                )
                rego = ov_r.scalar_one_or_none()
            cv_to_rego[cv.id] = rego

        blocking_fleet_checklists = [
            {
                "id": str(fcs.id),
                "vehicle_rego": cv_to_rego.get(fcs.customer_vehicle_id),
            }
            for fcs in fcs_orm
        ]

    # ------------------------------------------------------------------
    # 7. Orphan vehicles — vehicles that would be unlinked (but preserved)
    #    after the hard delete (R6.1, R6.2)
    # ------------------------------------------------------------------
    orphan_vehicles: list[dict] = []
    for cv in customer_vehicles_all:
        if cv.global_vehicle_id:
            gv_r = await db.execute(
                select(GlobalVehicle).where(GlobalVehicle.id == cv.global_vehicle_id)
            )
            gv = gv_r.scalar_one_or_none()
            if gv:
                orphan_vehicles.append({
                    "id": str(gv.id),
                    "rego": gv.rego,
                    "make": gv.make,
                    "model": gv.model,
                    "source": "global",
                })
        elif cv.org_vehicle_id:
            ov_r = await db.execute(
                select(OrgVehicle).where(
                    OrgVehicle.id == cv.org_vehicle_id,
                    OrgVehicle.org_id == org_id,
                )
            )
            ov = ov_r.scalar_one_or_none()
            if ov:
                orphan_vehicles.append({
                    "id": str(ov.id),
                    "rego": ov.rego,
                    "make": ov.make,
                    "model": ov.model,
                    "source": "org",
                })

    # ------------------------------------------------------------------
    # 8. can_delete — True only when no blocking sources present
    # ------------------------------------------------------------------
    can_delete = (
        len(blocking_invoices) == 0
        and len(blocking_claims) == 0
        and len(blocking_job_cards) == 0
        and len(blocking_fleet_checklists) == 0
    )

    return {
        "can_delete": can_delete,
        "blocking_invoices": blocking_invoices,
        "blocking_invoice_count": len(blocking_invoices),
        "blocking_claims": blocking_claims,
        "blocking_job_cards": blocking_job_cards,
        "blocking_fleet_checklists": blocking_fleet_checklists,
        "draft_invoices": draft_invoices,
        "orphan_vehicles": orphan_vehicles,
        "nz_retention_warning": NZ_RETENTION_WARNING,
    }


async def hard_delete_customer(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
    confirmation: str,
    ip_address: str | None = None,
) -> dict:
    """Guarded hard delete of a customer within one transaction.

    This function implements a secure, transactional customer deletion with
    multiple validation guards. The deletion order ensures referential
    integrity and preserves legally-retained financial records.

    Order of operations (all within the caller's session.begin()):
      1. Load customer (org-scoped). Not found -> ValueError (R9.4).
      2. Validate reason non-empty after strip (R4.1, R4.2) -> ValueError.
      3. Validate confirmation present/valid (R5.2) -> ValueError.
      4. Re-count blocking documents: issued invoices (R2.1), open claims
         (matrix Row 9), job_cards (Row 8), and fleet checklist submissions
         for the customer's vehicles (Row 20). If any -> CustomerDeletionBlockedError
         carrying the blocking payload (R2.2/2.3).
      5. [Task 3.5] Resolve each referencing table per the matrix (children first).
      6. [Task 3.5] Delete the customers row (R1.1).
      7. [Task 3.9] write_audit_log(action="customer.hard_deleted", ...) (R8).
      8. flush() — no commit (NFR2.2).

    Returns the result dict (R1.2).

    Requirements: 1.1, 1.2, 1.3, 2.x, 4.x, 5.x, 6.x, 7.x, 8.x, 9.x, 10.x, 11.x
    """
    from app.modules.claims.models import CustomerClaim
    from app.modules.customers.schemas import CustomerDeletionBlockedError
    from app.modules.fleet_portal.models import FleetChecklistSubmission
    from app.modules.invoices.models import Invoice
    from app.modules.job_cards.models import JobCard
    from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
    from app.modules.admin.models import GlobalVehicle

    # ------------------------------------------------------------------
    # STEP 1: Load customer org-scoped (R9.4, R10.2)
    # ------------------------------------------------------------------
    result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found")

    # ------------------------------------------------------------------
    # STEP 2: Validate reason non-empty after strip (R4.1, R4.2)
    # ------------------------------------------------------------------
    if not reason or not reason.strip():
        raise ValueError("A deletion reason is required")

    # ------------------------------------------------------------------
    # STEP 3: Validate confirmation (R5.2)
    #
    # Confirmation must equal the customer's display name (case-insensitive,
    # trimmed) OR the literal string "DELETE". The customer display name
    # falls back to "first_name last_name" if display_name is not set.
    # ------------------------------------------------------------------
    expected_name = customer.display_name
    if not expected_name or not expected_name.strip():
        # Fallback: construct from first_name + last_name
        expected_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip()

    confirmation_normalized = confirmation.strip().lower() if confirmation else ""
    expected_normalized = expected_name.strip().lower() if expected_name else ""
    literal_delete = "delete"

    if confirmation_normalized not in (expected_normalized, literal_delete):
        raise ValueError("Confirmation does not match")

    # ------------------------------------------------------------------
    # STEP 4: Re-count blocking documents (R2.1, R2.2, R2.3, R11.4)
    #
    # Even if preflight said can_delete=true, the state may have changed
    # between preflight and hard-delete. Re-validate:
    #   - Issued (non-draft) invoices
    #   - Open customer claims
    #   - Job cards
    #   - Fleet checklist submissions for this customer's vehicles
    # ------------------------------------------------------------------

    # 4a. Issued invoices
    issued_stmt = select(Invoice).where(
        Invoice.customer_id == customer_id,
        Invoice.org_id == org_id,
        Invoice.status.in_(ISSUED_INVOICE_STATUSES),
    )
    issued_result = await db.execute(issued_stmt)
    issued_invoices = issued_result.scalars().all()

    # 4b. Customer claims
    claims_stmt = select(CustomerClaim).where(
        CustomerClaim.customer_id == customer_id,
        CustomerClaim.org_id == org_id,
    )
    claims_result = await db.execute(claims_stmt)
    claims_orm = claims_result.scalars().all()

    # 4c. Job cards
    jc_stmt = select(JobCard).where(
        JobCard.customer_id == customer_id,
        JobCard.org_id == org_id,
    )
    jc_result = await db.execute(jc_stmt)
    jc_orm = jc_result.scalars().all()

    # 4d. Fleet checklist submissions for the customer's vehicles
    cv_stmt = select(CustomerVehicle).where(
        CustomerVehicle.customer_id == customer_id,
        CustomerVehicle.org_id == org_id,
    )
    cv_result = await db.execute(cv_stmt)
    customer_vehicles_all = cv_result.scalars().all()
    cv_ids = [cv.id for cv in customer_vehicles_all]

    fcs_orm: list = []
    if cv_ids:
        fcs_stmt = select(FleetChecklistSubmission).where(
            FleetChecklistSubmission.customer_vehicle_id.in_(cv_ids),
        )
        fcs_result = await db.execute(fcs_stmt)
        fcs_orm = fcs_result.scalars().all()

    # If ANY blocking documents exist, raise CustomerDeletionBlockedError
    if issued_invoices or claims_orm or jc_orm or fcs_orm:
        # Build the blocking payload (same shape as preflight)
        blocking_invoices = [
            {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "status": inv.status,
            }
            for inv in issued_invoices
        ]

        blocking_claims = [
            {
                "id": str(c.id),
                "claim_number": c.reference,
                "status": c.status,
            }
            for c in claims_orm
        ]

        blocking_job_cards = [
            {
                "id": str(jc.id),
                "status": jc.status,
            }
            for jc in jc_orm
        ]

        # Build rego lookup for fleet checklists
        cv_to_rego: dict[uuid.UUID, str | None] = {}
        for cv in customer_vehicles_all:
            rego: str | None = None
            if cv.global_vehicle_id:
                gv_r = await db.execute(
                    select(GlobalVehicle.rego).where(
                        GlobalVehicle.id == cv.global_vehicle_id
                    )
                )
                rego = gv_r.scalar_one_or_none()
            elif cv.org_vehicle_id:
                ov_r = await db.execute(
                    select(OrgVehicle.rego).where(
                        OrgVehicle.id == cv.org_vehicle_id,
                        OrgVehicle.org_id == org_id,
                    )
                )
                rego = ov_r.scalar_one_or_none()
            cv_to_rego[cv.id] = rego

        blocking_fleet_checklists = [
            {
                "id": str(fcs.id),
                "vehicle_rego": cv_to_rego.get(fcs.customer_vehicle_id),
            }
            for fcs in fcs_orm
        ]

        payload = {
            "blocking_invoices": blocking_invoices,
            "blocking_invoice_count": len(blocking_invoices),
            "blocking_claims": blocking_claims,
            "blocking_job_cards": blocking_job_cards,
            "blocking_fleet_checklists": blocking_fleet_checklists,
        }

        message = (
            "Customer has documents that must be resolved before deletion. "
            "Please delete or resolve the blocking items listed."
        )

        raise CustomerDeletionBlockedError(message, payload)

    # ------------------------------------------------------------------
    # STEP 5: Capture orphaned vehicle IDs (before deleting links)
    #
    # For each customer_vehicles link, resolve the vehicle ID from either
    # global_vehicle_id or org_vehicle_id. These will be returned in the
    # result dict and written to the audit log.
    # ------------------------------------------------------------------
    orphaned_vehicle_ids: list[str] = []
    for cv in customer_vehicles_all:
        vehicle_id = cv.global_vehicle_id or cv.org_vehicle_id
        if vehicle_id:
            orphaned_vehicle_ids.append(str(vehicle_id))

    # ------------------------------------------------------------------
    # STEP 6: Delete customer_vehicles links (R6.1, R6.2, R6.4)
    #
    # Remove the customer→vehicle links but preserve the vehicle rows.
    # customer_vehicles_all is already loaded from step 4.
    # ------------------------------------------------------------------
    vehicle_links_removed = len(customer_vehicles_all)
    for cv in customer_vehicles_all:
        await db.delete(cv)
    await db.flush()

    # ------------------------------------------------------------------
    # STEP 7: Delete-with-customer: quotes + quote_line_items
    #
    # Quotes are not financial records (R2.6), so we delete them.
    # First delete quote_line_items for those quotes, then delete the quotes.
    # ------------------------------------------------------------------
    try:
        from app.modules.quotes.models import Quote, QuoteLineItem
        from sqlalchemy import delete as sql_delete

        # Find all quotes for this customer
        quotes_stmt = select(Quote).where(
            Quote.customer_id == customer_id,
            Quote.org_id == org_id,
        )
        quotes_result = await db.execute(quotes_stmt)
        quotes = quotes_result.scalars().all()

        if quotes:
            quote_ids = [q.id for q in quotes]

            # Delete quote_line_items first (child records)
            qli_delete_stmt = sql_delete(QuoteLineItem).where(
                QuoteLineItem.quote_id.in_(quote_ids)
            )
            await db.execute(qli_delete_stmt)

            # Delete quotes
            for q in quotes:
                await db.delete(q)
            await db.flush()
    except ImportError:
        # Quotes module not installed — skip gracefully
        pass

    # ------------------------------------------------------------------
    # STEP 8: Delete-with-customer: recurring_schedules
    #
    # Recurring schedules for a deleted customer are dead config.
    # ------------------------------------------------------------------
    try:
        from app.modules.quotes.models import RecurringSchedule
        from sqlalchemy import delete as sql_delete

        rs_delete_stmt = sql_delete(RecurringSchedule).where(
            RecurringSchedule.customer_id == customer_id,
            RecurringSchedule.org_id == org_id,
        )
        await db.execute(rs_delete_stmt)
        await db.flush()
    except ImportError:
        # Recurring schedules module not available
        pass

    # ------------------------------------------------------------------
    # STEP 9: Delete-with-customer: reminder_queue
    #
    # Queued reminders for a gone customer are noise.
    # ------------------------------------------------------------------
    try:
        from app.modules.notifications.models import ReminderQueue
        from sqlalchemy import delete as sql_delete

        rq_delete_stmt = sql_delete(ReminderQueue).where(
            ReminderQueue.customer_id == customer_id,
            ReminderQueue.org_id == org_id,
        )
        await db.execute(rq_delete_stmt)
        await db.flush()
    except ImportError:
        # Reminder queue module not available
        pass

    # ------------------------------------------------------------------
    # STEP 10: Delete-with-customer: loyalty_transactions
    #
    # Loyalty transactions have customer_id NOT NULL, so they cannot be
    # set to NULL. Since the customer is gone, these ledger rows are
    # meaningless and must be deleted.
    # ------------------------------------------------------------------
    try:
        from app.modules.loyalty.models import LoyaltyTransaction
        from sqlalchemy import delete as sql_delete

        lt_delete_stmt = sql_delete(LoyaltyTransaction).where(
            LoyaltyTransaction.customer_id == customer_id,
            LoyaltyTransaction.org_id == org_id,
        )
        await db.execute(lt_delete_stmt)
        await db.flush()
    except ImportError:
        # Loyalty module not available
        pass

    # ------------------------------------------------------------------
    # STEP 11: Set-null: pos_transactions
    #
    # POS sale rows are financial records but customer_id is nullable.
    # Keep the sale, drop the customer link.
    # ------------------------------------------------------------------
    try:
        from app.modules.pos.models import POSTransaction
        from sqlalchemy import update as sql_update

        pos_update_stmt = sql_update(POSTransaction).where(
            POSTransaction.customer_id == customer_id,
            POSTransaction.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(pos_update_stmt)
        await db.flush()
    except ImportError:
        # POS module not available
        pass

    # ------------------------------------------------------------------
    # STEP 12: Set-null: bookings
    #
    # Keep the booking history; customer_name is denormalised on the row.
    # ------------------------------------------------------------------
    try:
        from app.modules.bookings_v2.models import Booking
        from sqlalchemy import update as sql_update

        booking_update_stmt = sql_update(Booking).where(
            Booking.customer_id == customer_id,
            Booking.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(booking_update_stmt)
        await db.flush()
    except ImportError:
        # Bookings module not available
        pass

    # ------------------------------------------------------------------
    # STEP 13: Set-null: projects
    #
    # No declared FK, nullable customer_id. Must set to NULL to avoid
    # dangling reference (R11.3).
    # ------------------------------------------------------------------
    try:
        from app.modules.projects.models import Project
        from sqlalchemy import update as sql_update

        project_update_stmt = sql_update(Project).where(
            Project.customer_id == customer_id,
            Project.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(project_update_stmt)
        await db.flush()
    except ImportError:
        # Projects module not available
        pass

    # ------------------------------------------------------------------
    # STEP 14: Set-null: pricing_rules
    #
    # No declared FK, nullable customer_id. Must set to NULL to avoid
    # dangling reference.
    # ------------------------------------------------------------------
    try:
        from app.modules.pricing_rules.models import PricingRule
        from sqlalchemy import update as sql_update

        pr_update_stmt = sql_update(PricingRule).where(
            PricingRule.customer_id == customer_id,
            PricingRule.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(pr_update_stmt)
        await db.flush()
    except ImportError:
        # Pricing rules module not available
        pass

    # ------------------------------------------------------------------
    # STEP 15: Set-null: expenses
    #
    # No declared FK, nullable customer_id. Keep the expense as a
    # financial record; only the customer link drops (R11.2).
    # ------------------------------------------------------------------
    try:
        from app.modules.expenses.models import Expense
        from sqlalchemy import update as sql_update

        expense_update_stmt = sql_update(Expense).where(
            Expense.customer_id == customer_id,
            Expense.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(expense_update_stmt)
        await db.flush()
    except ImportError:
        # Expenses module not available
        pass

    # ------------------------------------------------------------------
    # STEP 16: Set-null: jobs (jobs_v2 table)
    #
    # No declared FK, nullable customer_id. Keep the job/work-order
    # history; only the customer link drops.
    # ------------------------------------------------------------------
    try:
        from app.modules.jobs_v2.models import Job
        from sqlalchemy import update as sql_update

        job_update_stmt = sql_update(Job).where(
            Job.customer_id == customer_id,
            Job.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(job_update_stmt)
        await db.flush()
    except ImportError:
        # Jobs module not available
        pass

    # ------------------------------------------------------------------
    # STEP 17: Set-null: assets
    #
    # No declared FK, nullable customer_id. Asset survives, ownership
    # link dropped (mirrors the vehicle-orphaning intent, R6).
    # ------------------------------------------------------------------
    try:
        from app.modules.assets.models import Asset
        from sqlalchemy import update as sql_update

        asset_update_stmt = sql_update(Asset).where(
            Asset.customer_id == customer_id,
            Asset.org_id == org_id,
        ).values(customer_id=None)
        await db.execute(asset_update_stmt)
        await db.flush()
    except ImportError:
        # Assets module not available
        pass

    # ------------------------------------------------------------------
    # STEP 18: Delete the customers row (R1.1)
    #
    # portal_sessions, portal_accounts, portal_fleet_accounts cascade
    # via DB-level ON DELETE CASCADE (no app action needed).
    #
    # Capture PII-safe booleans BEFORE deletion (R8.5, NFR4.2).
    # After db.delete() SQLAlchemy expires the ORM attributes, so we must
    # read them now while the object is still live in the session.
    # ------------------------------------------------------------------
    _had_email = customer.email is not None
    _had_phone = customer.phone is not None
    _customer_type = customer.customer_type
    await db.delete(customer)
    await db.flush()

    # ------------------------------------------------------------------
    # STEP 19: Build the result dict for CustomerHardDeleteResponse
    # ------------------------------------------------------------------
    result_dict = {
        "message": "Customer permanently deleted",
        "deleted": True,
        "customer_id": str(customer_id),
        "vehicle_links_removed": vehicle_links_removed,
        "draft_invoices_deleted": 0,  # User already deleted them before this call
        "orphaned_vehicle_ids": orphaned_vehicle_ids,
    }

    # ------------------------------------------------------------------
    # STEP 20: Write the success audit log (R8.1–8.5)
    #
    # Distinct action "customer.hard_deleted" (R8.4).
    # before_value uses the PII-safe booleans captured before deletion.
    # after_value holds reason + ids only — no PII (R8.5, NFR4.2).
    # Inside the same session.begin() transaction, so if something raises
    # after this the audit row is also rolled back (R9.3).
    # flush() only — get_db_session commit handles the final commit (NFR2.2).
    # ------------------------------------------------------------------
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="customer.hard_deleted",
        entity_type="customer",
        entity_id=customer_id,
        before_value={
            "had_email": _had_email,
            "had_phone": _had_phone,
            "customer_type": _customer_type,
        },
        after_value={
            "reason": reason,
            "prerequisite_deleted_invoice_ids": [],   # user deleted them before this call
            "orphaned_vehicle_ids": orphaned_vehicle_ids,
            "vehicle_links_removed": vehicle_links_removed,
        },
        ip_address=ip_address,
    )

    return result_dict
