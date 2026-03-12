"""Business logic for Customer module — CRUD, search, profile, notify, vehicle tagging, privacy.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 13.1, 13.2, 13.3, 13.4
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
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
    }


async def search_customers(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    query: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_vehicles: bool = False,
) -> dict:
    """Search customers by name, phone, or email.

    Uses PostgreSQL full-text search (GIN index) when a query is provided.
    Falls back to listing all customers when no query is given.

    Returns a dict with ``customers`` list, ``total`` count, and
    ``has_exact_match`` flag.
    
    If include_vehicles is True, also returns linked vehicles for each customer.

    Requirements: 11.1, 11.2, 11.3, 11.6
    """
    from app.modules.vehicles.models import CustomerVehicle
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
            # Fetch linked vehicles for this customer
            cv_stmt = (
                select(CustomerVehicle, GlobalVehicle)
                .outerjoin(GlobalVehicle, CustomerVehicle.global_vehicle_id == GlobalVehicle.id)
                .where(
                    CustomerVehicle.customer_id == c.id,
                    CustomerVehicle.org_id == org_id,
                )
                .order_by(CustomerVehicle.linked_at.desc())
            )
            cv_result = await db.execute(cv_stmt)
            linked_vehicles = []
            for cv, gv in cv_result.all():
                if gv:
                    linked_vehicles.append({
                        "id": str(gv.id),
                        "rego": gv.rego,
                        "make": gv.make,
                        "model": gv.model,
                        "year": gv.year,
                        "colour": gv.colour,
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
    last_name: str,
    email: str | None = None,
    phone: str | None = None,
    mobile_phone: str | None = None,
    work_phone: str | None = None,
    address: str | None = None,
    notes: str | None = None,
    ip_address: str | None = None,
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
    # Auto-generate display_name if not provided
    if not display_name:
        if customer_type == "business" and company_name:
            display_name = company_name
        else:
            display_name = f"{first_name} {last_name}"
    
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

    allowed_fields = {"first_name", "last_name", "email", "phone", "address", "notes"}
    before_value = {}
    updated_fields = []

    for field in allowed_fields:
        value = kwargs.get(field)
        if value is not None:
            before_value[field] = getattr(customer, field)
            setattr(customer, field, value)
            updated_fields.append(field)

    if not updated_fields:
        return _customer_to_dict(customer)

    await db.flush()

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
                "source": "global",
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
                "source": "org",
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

    recipient = None

    if channel == "email":
        if not customer.email:
            raise ValueError("Customer has no email address on file")
        recipient = customer.email
        # Mock email sending — actual Brevo integration in Task 15.1
        logger.info(
            "Sending email to customer %s at %s (subject: %s)",
            customer_id,
            "[REDACTED]",
            subject or "(no subject)",
        )
    elif channel == "sms":
        if not customer.phone:
            raise ValueError("Customer has no phone number on file")
        recipient = customer.phone
        # Mock SMS sending — actual Twilio integration in Task 15.4
        logger.info(
            "Sending SMS to customer %s at %s",
            customer_id,
            "[REDACTED]",
        )
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
        "message": f"Notification queued via {channel}",
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

    Requirements: 12.3
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

    # Verify vehicle exists
    vehicle_info = {}
    if global_vehicle_id:
        gv_result = await db.execute(
            select(GlobalVehicle).where(GlobalVehicle.id == global_vehicle_id)
        )
        gv = gv_result.scalar_one_or_none()
        if gv is None:
            raise ValueError("Global vehicle not found")
        vehicle_info = {
            "rego": gv.rego,
            "make": gv.make,
            "model": gv.model,
            "year": gv.year,
            "colour": gv.colour,
            "source": "global",
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
        vehicle_info = {
            "rego": ov.rego,
            "make": ov.make,
            "model": ov.model,
            "year": ov.year,
            "colour": ov.colour,
            "source": "org",
        }

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
