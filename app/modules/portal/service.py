"""Business logic for the Customer Portal module.

All functions accept a raw AsyncSession (with RLS already set by the
caller where needed) and return Pydantic-serialisable dicts/objects.

Requirements: 61.1, 61.2, 61.3, 61.4, 61.5
Enhanced: Requirement 49 — Customer Portal Enhancements
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func as sa_func, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.admin.models import Organisation
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice, LineItem
from app.modules.payments.models import Payment
from app.modules.vehicles.models import CustomerVehicle, OrgVehicle
from app.modules.admin.models import GlobalVehicle
from app.modules.portal.schemas import (
    PortalAccessResponse,
    PortalBranding,
    PortalCustomerInfo,
    PortalInvoiceItem,
    PortalInvoicesResponse,
    PortalPaymentSummary,
    PortalPayResponse,
    PortalServiceRecord,
    PortalVehicleItem,
    PortalVehiclesResponse,
    PortalQuoteItem,
    PortalQuoteLineItem,
    PortalQuotesResponse,
    PortalAcceptQuoteResponse,
    PortalAssetItem,
    PortalAssetServiceEntry,
    PortalAssetsResponse,
    PortalBookingItem,
    PortalBookingsResponse,
    PortalBookingCreateResponse,
    PortalLoyaltyResponse,
    PortalLoyaltyTier,
    PortalLoyaltyTransaction,
    PoweredByFooter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_branding(org: Organisation, powered_by: PoweredByFooter | None = None) -> PortalBranding:
    """Extract branding fields from the organisation settings JSONB."""
    settings = org.settings or {}
    locale = getattr(org, "locale", None)
    return PortalBranding(
        org_name=org.name,
        logo_url=settings.get("logo_url"),
        primary_colour=settings.get("primary_colour"),
        secondary_colour=settings.get("secondary_colour"),
        powered_by=powered_by,
        language=locale,
    )


async def _get_powered_by(db: AsyncSession, org: Organisation) -> PoweredByFooter:
    """Fetch the platform Powered By config for the portal footer."""
    from app.modules.branding.service import BrandingService

    svc = BrandingService(db)
    white_label = getattr(org, "white_label_enabled", False)
    config = await svc.get_powered_by_config(org_white_label_enabled=white_label)
    return PoweredByFooter(
        platform_name=config.platform_name,
        logo_url=config.logo_url,
        signup_url=config.signup_url,
        website_url=config.website_url,
        show_powered_by=config.show_powered_by,
    )


async def _resolve_token(
    db: AsyncSession, token: uuid.UUID
) -> tuple[Customer, Organisation]:
    """Look up a customer by portal_token and return (customer, org).

    Raises ValueError if the token is invalid or the customer is
    anonymised.
    """
    stmt = (
        select(Customer)
        .where(Customer.portal_token == token)
        .where(Customer.is_anonymised.is_(False))
    )
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Invalid or expired portal token")

    org_stmt = select(Organisation).where(Organisation.id == customer.org_id)
    org_result = await db.execute(org_stmt)
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    return customer, org


# ---------------------------------------------------------------------------
# Portal access  (Req 61.1, 61.5)
# ---------------------------------------------------------------------------


async def get_portal_access(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalAccessResponse:
    """Validate the portal token and return customer + org context."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Aggregate outstanding balance and invoice count
    agg_stmt = select(
        sa_func.count(Invoice.id).label("cnt"),
        sa_func.coalesce(sa_func.sum(Invoice.balance_due), 0).label("outstanding"),
    ).where(
        Invoice.customer_id == customer.id,
        Invoice.org_id == customer.org_id,
        Invoice.status.notin_(["draft", "voided"]),
    )
    agg = (await db.execute(agg_stmt)).one()

    return PortalAccessResponse(
        customer=PortalCustomerInfo(
            customer_id=customer.id,
            first_name=customer.first_name,
            last_name=customer.last_name,
            email=customer.email,
            phone=customer.phone,
        ),
        branding=_build_branding(org, powered_by),
        outstanding_balance=Decimal(str(agg.outstanding)),
        invoice_count=int(agg.cnt),
    )


# ---------------------------------------------------------------------------
# Invoice history  (Req 61.2)
# ---------------------------------------------------------------------------


async def get_portal_invoices(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalInvoicesResponse:
    """Return the customer's invoice history with payment details."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.payments))
        .where(
            Invoice.customer_id == customer.id,
            Invoice.org_id == customer.org_id,
            Invoice.status.notin_(["draft", "voided"]),
        )
        .order_by(Invoice.issue_date.desc().nullslast(), Invoice.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    total_outstanding = Decimal("0")
    total_paid = Decimal("0")
    items: list[PortalInvoiceItem] = []

    for inv in rows:
        payments = [
            PortalPaymentSummary(
                id=p.id,
                amount=p.amount,
                method=p.method,
                is_refund=p.is_refund,
                created_at=p.created_at,
            )
            for p in (inv.payments or [])
        ]
        items.append(
            PortalInvoiceItem(
                id=inv.id,
                invoice_number=inv.invoice_number,
                status=inv.status,
                issue_date=inv.issue_date,
                due_date=inv.due_date,
                currency=inv.currency,
                subtotal=inv.subtotal,
                gst_amount=inv.gst_amount,
                total=inv.total,
                amount_paid=inv.amount_paid,
                balance_due=inv.balance_due,
                vehicle_rego=inv.vehicle_rego,
                payments=payments,
            )
        )
        total_outstanding += inv.balance_due
        total_paid += inv.amount_paid

    return PortalInvoicesResponse(
        branding=_build_branding(org, powered_by),
        invoices=items,
        total_outstanding=total_outstanding,
        total_paid=total_paid,
        org_has_stripe_connect=bool(org.stripe_connect_account_id),
    )


# ---------------------------------------------------------------------------
# Vehicle service history  (Req 61.4)
# ---------------------------------------------------------------------------


async def get_portal_vehicles(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalVehiclesResponse:
    """Return the customer's vehicles with service history."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Fetch customer-vehicle links
    cv_stmt = select(CustomerVehicle).where(
        CustomerVehicle.customer_id == customer.id,
        CustomerVehicle.org_id == customer.org_id,
    )
    cv_rows = (await db.execute(cv_stmt)).scalars().all()

    vehicles: list[PortalVehicleItem] = []

    for cv in cv_rows:
        # Resolve vehicle details from global or org vehicle
        rego = make = model = year = colour = None
        if cv.global_vehicle_id:
            gv_stmt = select(GlobalVehicle).where(
                GlobalVehicle.id == cv.global_vehicle_id
            )
            gv = (await db.execute(gv_stmt)).scalar_one_or_none()
            if gv:
                rego, make, model, year, colour = (
                    gv.rego, gv.make, gv.model, gv.year, gv.colour,
                )
        elif cv.org_vehicle_id:
            ov_stmt = select(OrgVehicle).where(
                OrgVehicle.id == cv.org_vehicle_id
            )
            ov = (await db.execute(ov_stmt)).scalar_one_or_none()
            if ov:
                rego, make, model, year, colour = (
                    ov.rego, ov.make, ov.model, ov.year, ov.colour,
                )

        if not rego:
            continue

        # Fetch invoices for this rego
        inv_stmt = (
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(
                Invoice.customer_id == customer.id,
                Invoice.org_id == customer.org_id,
                Invoice.vehicle_rego == rego,
                Invoice.status.notin_(["draft", "voided"]),
            )
            .order_by(Invoice.issue_date.desc().nullslast())
        )
        inv_rows = (await db.execute(inv_stmt)).scalars().all()

        service_history = [
            PortalServiceRecord(
                invoice_id=inv.id,
                invoice_number=inv.invoice_number,
                date=inv.issue_date,
                status=inv.status,
                total=inv.total,
                description=", ".join(
                    li.description for li in (inv.line_items or [])
                ) or "Service",
            )
            for inv in inv_rows
        ]

        vehicles.append(
            PortalVehicleItem(
                rego=rego,
                make=make,
                model=model,
                year=year,
                colour=colour,
                service_history=service_history,
            )
        )

    return PortalVehiclesResponse(
        branding=_build_branding(org, powered_by),
        vehicles=vehicles,
    )


# ---------------------------------------------------------------------------
# Portal payment  (Req 61.3)
# ---------------------------------------------------------------------------


async def create_portal_payment(
    db: AsyncSession,
    token: uuid.UUID,
    invoice_id: uuid.UUID,
    amount: Decimal | None = None,
) -> PortalPayResponse:
    """Generate a Stripe payment link for an outstanding invoice.

    If ``amount`` is None the full ``balance_due`` is used.
    """
    from app.integrations.stripe_connect import create_payment_link
    from app.config import settings as app_settings

    customer, org = await _resolve_token(db, token)

    # Fetch the invoice and verify ownership
    inv_stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.customer_id == customer.id,
        Invoice.org_id == customer.org_id,
    )
    invoice = (await db.execute(inv_stmt)).scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found")

    if invoice.status in ("draft", "voided", "paid"):
        raise ValueError(
            f"Cannot pay an invoice with status '{invoice.status}'"
        )

    if invoice.balance_due <= 0:
        raise ValueError("Invoice has no outstanding balance")

    pay_amount = amount if amount is not None else invoice.balance_due
    if pay_amount > invoice.balance_due:
        raise ValueError("Payment amount exceeds outstanding balance")

    stripe_account = org.stripe_connect_account_id
    if not stripe_account:
        raise ValueError(
            "Organisation has not connected a Stripe account"
        )

    # Amount in smallest currency unit (cents)
    amount_cents = int(pay_amount * 100)

    # Calculate application fee if configured (Req 7.1, 7.2)
    from app.integrations.stripe_billing import get_application_fee_percent

    fee_percent = await get_application_fee_percent()
    application_fee_amount: int | None = None
    if fee_percent and fee_percent > 0:
        application_fee_amount = int(amount_cents * fee_percent / 100)

    portal_base = app_settings.frontend_base_url or "http://localhost:3000"
    success_url = f"{portal_base}/portal/{token}/payment-success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{portal_base}/portal/{token}/invoices"

    link_data = await create_payment_link(
        amount=amount_cents,
        currency=invoice.currency.lower(),
        invoice_id=str(invoice.id),
        stripe_account_id=stripe_account,
        success_url=success_url,
        cancel_url=cancel_url,
        application_fee_amount=application_fee_amount,
    )

    return PortalPayResponse(
        payment_url=link_data["payment_url"],
        invoice_id=invoice.id,
        amount=pay_amount,
        message="Payment link generated",
    )


# ---------------------------------------------------------------------------
# Quote acceptance  (Req 49.2)
# ---------------------------------------------------------------------------


async def get_portal_quotes(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalQuotesResponse:
    """Return the customer's quotes with acceptance capability."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    stmt = sa_text(
        "SELECT id, quote_number, status, expiry_date, terms, "
        "line_items, subtotal, tax_amount, total, currency, "
        "acceptance_token, accepted_at, created_at "
        "FROM quotes "
        "WHERE customer_id = :cid AND org_id = :oid "
        "AND status NOT IN ('draft') "
        "ORDER BY created_at DESC"
    )
    rows = await db.execute(stmt, {"cid": str(customer.id), "oid": str(org.id)})

    quotes: list[PortalQuoteItem] = []
    for row in rows:
        line_items_raw = row[5] or []
        line_items = [
            PortalQuoteLineItem(
                description=li.get("description", ""),
                quantity=Decimal(str(li.get("quantity", 1))),
                unit_price=Decimal(str(li.get("unit_price", 0))),
                total=Decimal(str(li.get("total", 0))) if li.get("total") else None,
            )
            for li in (line_items_raw if isinstance(line_items_raw, list) else [])
        ]
        quotes.append(PortalQuoteItem(
            id=row[0],
            quote_number=row[1],
            status=row[2],
            expiry_date=row[3],
            terms=row[4],
            line_items=line_items,
            subtotal=Decimal(str(row[6] or 0)),
            tax_amount=Decimal(str(row[7] or 0)),
            total=Decimal(str(row[8] or 0)),
            currency=row[9],
            acceptance_token=row[10],
            accepted_at=row[11],
            created_at=row[12],
        ))

    return PortalQuotesResponse(
        branding=_build_branding(org, powered_by),
        quotes=quotes,
    )


async def accept_portal_quote(
    db: AsyncSession,
    token: uuid.UUID,
    quote_id: uuid.UUID,
) -> PortalAcceptQuoteResponse:
    """Accept a quote from the customer portal."""
    customer, org = await _resolve_token(db, token)

    from app.modules.quotes_v2.service import QuoteService

    # Verify the quote belongs to this customer
    row = await db.execute(
        sa_text(
            "SELECT acceptance_token FROM quotes "
            "WHERE id = :qid AND customer_id = :cid AND org_id = :oid"
        ),
        {"qid": str(quote_id), "cid": str(customer.id), "oid": str(org.id)},
    )
    result = row.one_or_none()
    if result is None:
        raise ValueError("Quote not found")

    acceptance_token = result[0]
    if not acceptance_token:
        raise ValueError("Quote does not have an acceptance token")

    svc = QuoteService(db)
    quote = await svc.accept_quote(acceptance_token)

    return PortalAcceptQuoteResponse(
        quote_id=quote.id,
        status=quote.status,
        accepted_at=quote.accepted_at,
    )


# ---------------------------------------------------------------------------
# Asset / service history  (Req 49.2)
# ---------------------------------------------------------------------------


async def get_portal_assets(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalAssetsResponse:
    """Return the customer's assets with service history."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.assets.service import AssetService

    asset_svc = AssetService(db)
    assets = await asset_svc.list_assets(org.id, customer_id=customer.id)

    portal_assets: list[PortalAssetItem] = []
    for asset in assets:
        history = await asset_svc.get_service_history(org.id, asset.id)
        entries = [
            PortalAssetServiceEntry(
                reference_type=e.reference_type,
                reference_id=e.reference_id,
                reference_number=e.reference_number,
                description=e.description,
                date=e.date,
                status=e.status,
            )
            for e in history.entries
        ]
        portal_assets.append(PortalAssetItem(
            id=asset.id,
            asset_type=asset.asset_type,
            identifier=asset.identifier,
            make=asset.make,
            model=asset.model,
            year=asset.year,
            description=asset.description,
            serial_number=asset.serial_number,
            service_history=entries,
        ))

    return PortalAssetsResponse(
        branding=_build_branding(org, powered_by),
        assets=portal_assets,
    )


# ---------------------------------------------------------------------------
# Booking management  (Req 49.4)
# ---------------------------------------------------------------------------


async def get_portal_bookings(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalBookingsResponse:
    """Return the customer's bookings."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    stmt = sa_text(
        "SELECT id, service_type, start_time, end_time, status, notes, created_at "
        "FROM bookings "
        "WHERE customer_id = :cid AND org_id = :oid "
        "ORDER BY start_time DESC"
    )
    rows = await db.execute(stmt, {"cid": str(customer.id), "oid": str(org.id)})

    bookings = [
        PortalBookingItem(
            id=row[0],
            service_type=row[1],
            start_time=row[2],
            end_time=row[3],
            status=row[4],
            notes=row[5],
            created_at=row[6],
        )
        for row in rows
    ]

    return PortalBookingsResponse(
        branding=_build_branding(org, powered_by),
        bookings=bookings,
    )


async def create_portal_booking(
    db: AsyncSession,
    token: uuid.UUID,
    service_type: str | None,
    start_time: datetime,
    notes: str | None,
) -> PortalBookingCreateResponse:
    """Create a booking from the portal using the same rules as the public page."""
    customer, org = await _resolve_token(db, token)

    from app.modules.bookings_v2.service import BookingService
    from app.modules.bookings_v2.schemas import BookingCreate

    svc = BookingService(db)

    # Get booking rules to determine end_time
    rule = await svc.get_or_create_default_rule(org.id)
    duration_minutes = rule.duration_minutes if hasattr(rule, "duration_minutes") else 60
    from datetime import timedelta
    end_time = start_time + timedelta(minutes=duration_minutes)

    booking_data = BookingCreate(
        customer_name=f"{customer.first_name} {customer.last_name}",
        customer_email=customer.email,
        customer_phone=customer.phone,
        service_type=service_type,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
    )

    booking = await svc.create_booking(org.id, booking_data, customer_id=customer.id)

    return PortalBookingCreateResponse(
        booking_id=booking.id,
        status=booking.status,
        start_time=booking.start_time,
        end_time=booking.end_time,
    )


async def get_portal_available_slots(
    db: AsyncSession,
    token: uuid.UUID,
    target_date: date,
):
    """Return available booking slots for a given date."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.bookings_v2.service import BookingService
    from app.modules.portal.schemas import PortalAvailableSlotsResponse, PortalTimeSlot

    svc = BookingService(db)
    slots_response = await svc.get_available_slots(org.id, target_date)

    slots = [
        PortalTimeSlot(
            start_time=s.start_time,
            end_time=s.end_time,
            available=s.available,
        )
        for s in slots_response.slots
    ]

    return PortalAvailableSlotsResponse(
        branding=_build_branding(org, powered_by),
        date=target_date,
        slots=slots,
    )


# ---------------------------------------------------------------------------
# Loyalty balance  (Req 49.2, Req 38.6)
# ---------------------------------------------------------------------------


async def get_portal_loyalty(
    db: AsyncSession,
    token: uuid.UUID,
) -> PortalLoyaltyResponse:
    """Return the customer's loyalty balance, tier, and transaction history."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.loyalty.service import LoyaltyService

    svc = LoyaltyService(db)

    # Check if loyalty is configured for this org
    config = await svc.get_config(org.id)
    if config is None or not config.is_active:
        return PortalLoyaltyResponse(
            branding=_build_branding(org, powered_by),
            total_points=0,
        )

    balance = await svc.get_customer_balance(org.id, customer.id)
    current_tier_model = await svc.check_tier_upgrade(org.id, customer.id)
    next_tier_model = await svc.get_next_tier(org.id, balance)
    transactions = await svc.get_customer_transactions(org.id, customer.id)

    current_tier = None
    if current_tier_model:
        current_tier = PortalLoyaltyTier(
            name=current_tier_model.name,
            threshold_points=current_tier_model.threshold_points,
            discount_percent=current_tier_model.discount_percent,
        )

    next_tier = None
    points_to_next = None
    if next_tier_model:
        next_tier = PortalLoyaltyTier(
            name=next_tier_model.name,
            threshold_points=next_tier_model.threshold_points,
            discount_percent=next_tier_model.discount_percent,
        )
        points_to_next = next_tier_model.threshold_points - balance

    portal_transactions = [
        PortalLoyaltyTransaction(
            transaction_type=t.transaction_type,
            points=t.points,
            balance_after=t.balance_after,
            reference_type=t.reference_type,
            created_at=t.created_at,
        )
        for t in transactions
    ]

    return PortalLoyaltyResponse(
        branding=_build_branding(org, powered_by),
        total_points=balance,
        current_tier=current_tier,
        next_tier=next_tier,
        points_to_next_tier=points_to_next,
        transactions=portal_transactions,
    )
