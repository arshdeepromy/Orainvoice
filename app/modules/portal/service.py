"""Business logic for the Customer Portal module.

All functions accept a raw AsyncSession (with RLS already set by the
caller where needed) and return Pydantic-serialisable dicts/objects.

Requirements: 61.1, 61.2, 61.3, 61.4, 61.5
Enhanced: Requirement 49 — Customer Portal Enhancements
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
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
from app.core.audit import write_audit_log
from app.modules.portal.schemas import (
    PortalAccessResponse,
    PortalAnalyticsDayItem,
    PortalAnalyticsResponse,
    PortalBranding,
    PortalCustomerInfo,
    PortalDocumentItem,
    PortalDocumentsResponse,
    PortalInvoiceItem,
    PortalInvoicesResponse,
    PortalPaymentSummary,
    PortalPayResponse,
    PortalProfileUpdateRequest,
    PortalProfileUpdateResponse,
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
    PortalJobItem,
    PortalJobsResponse,
    PortalClaimItem,
    PortalClaimActionItem,
    PortalClaimsResponse,
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


# ---------------------------------------------------------------------------
# Portal Analytics — Redis counters (Req 47.1, 47.2)
# ---------------------------------------------------------------------------

import logging as _logging

_analytics_logger = _logging.getLogger(__name__)

# Event types tracked for portal analytics
PORTAL_ANALYTICS_EVENT_TYPES = (
    "view",
    "quote_accepted",
    "booking_created",
    "payment_initiated",
)

# TTL for analytics keys — 90 days to auto-expire old data
_ANALYTICS_KEY_TTL_SECONDS = 90 * 24 * 60 * 60


async def track_portal_event(org_id: uuid.UUID, event_type: str) -> None:
    """Increment a Redis counter for a portal analytics event.

    Key format: ``portal:analytics:{org_id}:{YYYY-MM-DD}:{event_type}``

    The counter is atomically incremented via ``INCR`` and a TTL of 90 days
    is set on first creation so old data auto-expires.

    Requirements: 47.1
    """
    from app.core.redis import redis_pool

    today = date.today().isoformat()
    key = f"portal:analytics:{org_id}:{today}:{event_type}"
    try:
        pipe = redis_pool.pipeline()
        pipe.incr(key)
        pipe.expire(key, _ANALYTICS_KEY_TTL_SECONDS)
        await pipe.execute()
    except Exception:
        # Analytics tracking is best-effort — never block the main request
        _analytics_logger.warning(
            "Failed to track portal analytics event %s for org %s",
            event_type,
            org_id,
        )


async def get_portal_analytics(org_id: uuid.UUID) -> PortalAnalyticsResponse:
    """Aggregate portal analytics counters for the last 30 days.

    Requirements: 47.2, 47.3
    """
    from app.core.redis import redis_pool

    today = date.today()
    days: list[PortalAnalyticsDayItem] = []
    totals = {"view": 0, "quote_accepted": 0, "booking_created": 0, "payment_initiated": 0}

    for i in range(30):
        day = today - timedelta(days=i)
        day_str = day.isoformat()
        day_counts: dict[str, int] = {}

        # Fetch all event type counters for this day in a single pipeline
        try:
            pipe = redis_pool.pipeline()
            for event_type in PORTAL_ANALYTICS_EVENT_TYPES:
                key = f"portal:analytics:{org_id}:{day_str}:{event_type}"
                pipe.get(key)
            results = await pipe.execute()

            for idx, event_type in enumerate(PORTAL_ANALYTICS_EVENT_TYPES):
                count = int(results[idx] or 0)
                day_counts[event_type] = count
                totals[event_type] += count
        except Exception:
            _analytics_logger.warning(
                "Failed to read portal analytics for org %s date %s",
                org_id,
                day_str,
            )
            for event_type in PORTAL_ANALYTICS_EVENT_TYPES:
                day_counts[event_type] = 0

        days.append(PortalAnalyticsDayItem(
            date=day_str,
            **day_counts,
        ))

    # Reverse so oldest day is first
    days.reverse()

    return PortalAnalyticsResponse(
        days=days,
        totals=PortalAnalyticsDayItem(date="total", **totals),
    )


async def _resolve_token(
    db: AsyncSession, token: str
) -> tuple[Customer, Organisation]:
    """Look up a customer by portal_token and return (customer, org).

    Raises ValueError if the token is invalid or the customer is
    anonymised.
    """
    stmt = (
        select(Customer)
        .where(Customer.portal_token == token)
        .where(Customer.is_anonymised.is_(False))
        .where(Customer.enable_portal.is_(True))
    )
    result = await db.execute(stmt)
    customer = result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Invalid or expired portal token")

    # Defence-in-depth: reject expired portal tokens at the service layer (Req 10.1, 10.2)
    if (
        customer.portal_token_expires_at is not None
        and customer.portal_token_expires_at < datetime.now(timezone.utc)
    ):
        raise ValueError("Invalid or expired portal token")

    org_stmt = select(Organisation).where(Organisation.id == customer.org_id)
    org_result = await db.execute(org_stmt)
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Req 46.2: Global portal enable/disable per org
    org_settings = org.settings or {}
    if not org_settings.get("portal_enabled", True):
        raise PortalDisabledError("Customer portal is not available for this organisation")

    return customer, org


# ---------------------------------------------------------------------------
# Portal session management  (Req 40.1, 40.2, 40.3, 40.4)
# ---------------------------------------------------------------------------

# Session inactivity timeout: 4 hours
PORTAL_SESSION_INACTIVITY_TIMEOUT = timedelta(hours=4)
# Session absolute lifetime: 24 hours (hard cap)
PORTAL_SESSION_ABSOLUTE_LIFETIME = timedelta(hours=24)


async def create_portal_session(
    db: AsyncSession,
    customer_id: uuid.UUID,
) -> tuple[str, str]:
    """Create a new portal session and return (session_token, csrf_token).

    The session token is a cryptographically strong random string
    suitable for use in an HttpOnly cookie.  The CSRF token is a
    separate random string set as a non-HttpOnly cookie so the
    frontend JavaScript can read it and send it back as a header
    on state-changing requests (double-submit cookie pattern).

    Requirements: 40.3, 40.4, 41.1, 41.2
    """
    from app.modules.portal.models import PortalSession

    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    portal_session = PortalSession(
        customer_id=customer_id,
        session_token=session_token,
        expires_at=now + PORTAL_SESSION_ABSOLUTE_LIFETIME,
        last_seen=now,
    )
    db.add(portal_session)
    await db.flush()

    return session_token, csrf_token


async def validate_portal_session(
    db: AsyncSession,
    session_token: str,
) -> tuple[Customer, Organisation] | None:
    """Validate a portal session cookie and return (customer, org) or None.

    Checks:
    - Session exists and has not been deleted (logout)
    - Session has not exceeded absolute lifetime (expires_at)
    - Session has not exceeded inactivity timeout (last_seen + 4h)

    On success, updates ``last_seen`` to extend the inactivity window.

    Requirements: 40.3, 40.4
    """
    from app.modules.portal.models import PortalSession

    stmt = select(PortalSession).where(
        PortalSession.session_token == session_token,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        return None

    now = datetime.now(timezone.utc)

    # Check absolute expiry
    if session.expires_at < now:
        return None

    # Check inactivity timeout (4 hours)
    if session.last_seen + PORTAL_SESSION_INACTIVITY_TIMEOUT < now:
        return None

    # Update last_seen to extend inactivity window
    session.last_seen = now
    await db.flush()

    # Resolve customer and org
    cust_stmt = (
        select(Customer)
        .where(Customer.id == session.customer_id)
        .where(Customer.is_anonymised.is_(False))
        .where(Customer.enable_portal.is_(True))
    )
    customer = (await db.execute(cust_stmt)).scalar_one_or_none()
    if customer is None:
        return None

    org_stmt = select(Organisation).where(Organisation.id == customer.org_id)
    org = (await db.execute(org_stmt)).scalar_one_or_none()
    if org is None:
        return None

    return customer, org


async def destroy_portal_session(
    db: AsyncSession,
    session_token: str,
) -> bool:
    """Delete a portal session (logout).

    Returns True if a session was found and deleted, False otherwise.

    Requirements: 40.2
    """
    from app.modules.portal.models import PortalSession
    from sqlalchemy import delete

    result = await db.execute(
        delete(PortalSession).where(
            PortalSession.session_token == session_token,
        )
    )
    await db.flush()
    return (result.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# CSRF validation helper  (Req 41.1, 41.2, 41.3)
# ---------------------------------------------------------------------------


class CSRFValidationError(Exception):
    """Raised when portal CSRF validation fails."""
    pass


class PortalDisabledError(Exception):
    """Raised when the organisation has disabled the customer portal."""
    pass


def validate_portal_csrf(request) -> None:
    """Validate the portal CSRF double-submit cookie pattern.

    Compares the ``portal_csrf`` cookie value against the
    ``X-CSRF-Token`` request header.  Raises ``CSRFValidationError``
    if they do not match or are missing.

    Call this at the start of every state-changing portal endpoint
    (POST, PATCH, PUT, DELETE) except webhook and logout endpoints.

    Requirements: 41.1, 41.2, 41.3
    """
    csrf_cookie = request.cookies.get("portal_csrf")
    csrf_header = request.headers.get("x-csrf-token")

    if not csrf_cookie or not csrf_header:
        raise CSRFValidationError("Missing CSRF token")

    if not secrets.compare_digest(csrf_cookie, csrf_header):
        raise CSRFValidationError("CSRF token mismatch")


# ---------------------------------------------------------------------------
# Portal access  (Req 61.1, 61.5)
# ---------------------------------------------------------------------------


async def get_portal_access(
    db: AsyncSession,
    token: str,
) -> PortalAccessResponse:
    """Validate the portal token and return customer + org context."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Aggregate outstanding balance, invoice count, and total paid
    agg_stmt = select(
        sa_func.count(Invoice.id).label("cnt"),
        sa_func.coalesce(sa_func.sum(Invoice.balance_due), 0).label("outstanding"),
        sa_func.coalesce(sa_func.sum(Invoice.amount_paid), 0).label("paid"),
    ).where(
        Invoice.customer_id == customer.id,
        Invoice.org_id == customer.org_id,
        Invoice.status.notin_(["draft", "voided"]),
    )
    agg = (await db.execute(agg_stmt)).one()

    # Req 47.1: Track portal view event
    await track_portal_event(org.id, "view")

    # Req 48.1: Update last_portal_access_at timestamp
    customer.last_portal_access_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(customer)

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
        total_paid=Decimal(str(agg.paid)),
    )


# ---------------------------------------------------------------------------
# Invoice history  (Req 61.2)
# ---------------------------------------------------------------------------


async def get_portal_invoices(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> PortalInvoicesResponse:
    """Return the customer's invoice history with payment details."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Count total invoices for pagination
    count_stmt = select(sa_func.count(Invoice.id)).where(
        Invoice.customer_id == customer.id,
        Invoice.org_id == customer.org_id,
        Invoice.status.notin_(["draft", "voided"]),
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.payments), selectinload(Invoice.line_items))
        .where(
            Invoice.customer_id == customer.id,
            Invoice.org_id == customer.org_id,
            Invoice.status.notin_(["draft", "voided"]),
        )
        .order_by(Invoice.issue_date.desc().nullslast(), Invoice.created_at.desc())
        .limit(limit)
        .offset(offset)
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

        # Compute line items summary (Req 6.1, 6.4)
        summary = ", ".join(
            li.description for li in (inv.line_items or []) if li.description
        )
        line_items_summary = (summary[:120] + "…") if len(summary) > 120 else summary

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
                line_items_summary=line_items_summary,
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
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Invoice PDF download  (Req 18.1, 18.2, 18.3, 18.4)
# ---------------------------------------------------------------------------


async def get_portal_invoice_pdf(
    db: AsyncSession,
    token: str,
    invoice_id: uuid.UUID,
) -> tuple[bytes, str]:
    """Validate invoice ownership and generate PDF bytes.

    Returns a tuple of (pdf_bytes, invoice_number) so the router can
    build the Content-Disposition filename.

    Requirements: 18.1, 18.2, 18.3, 18.4
    """
    customer, org = await _resolve_token(db, token)

    # Verify the invoice belongs to this customer and org
    inv_stmt = select(Invoice).where(
        Invoice.id == invoice_id,
        Invoice.customer_id == customer.id,
        Invoice.org_id == org.id,
        Invoice.status.notin_(["draft"]),
    )
    invoice = (await db.execute(inv_stmt)).scalar_one_or_none()
    if invoice is None:
        raise ValueError("Invoice not found")

    # Reuse existing PDF generation from invoices module
    from app.modules.invoices.service import generate_invoice_pdf

    pdf_bytes = await generate_invoice_pdf(db, org_id=org.id, invoice_id=invoice_id)
    return pdf_bytes, invoice.invoice_number or str(invoice_id)


# ---------------------------------------------------------------------------
# Vehicle service history  (Req 61.4)
# ---------------------------------------------------------------------------


async def get_portal_vehicles(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
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
        wof_expiry = rego_expiry = None
        if cv.global_vehicle_id:
            gv_stmt = select(GlobalVehicle).where(
                GlobalVehicle.id == cv.global_vehicle_id
            )
            gv = (await db.execute(gv_stmt)).scalar_one_or_none()
            if gv:
                rego, make, model, year, colour = (
                    gv.rego, gv.make, gv.model, gv.year, gv.colour,
                )
                wof_expiry = gv.wof_expiry
                rego_expiry = gv.registration_expiry
        elif cv.org_vehicle_id:
            ov_stmt = select(OrgVehicle).where(
                OrgVehicle.id == cv.org_vehicle_id
            )
            ov = (await db.execute(ov_stmt)).scalar_one_or_none()
            if ov:
                rego, make, model, year, colour = (
                    ov.rego, ov.make, ov.model, ov.year, ov.colour,
                )
                wof_expiry = ov.wof_expiry
                rego_expiry = ov.registration_expiry

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
                wof_expiry=wof_expiry,
                rego_expiry=rego_expiry,
                service_history=service_history,
            )
        )

    return PortalVehiclesResponse(
        branding=_build_branding(org, powered_by),
        vehicles=vehicles[offset:offset + limit],
        total=len(vehicles),
    )


# ---------------------------------------------------------------------------
# Job status visibility  (Req 16)
# ---------------------------------------------------------------------------


async def get_portal_jobs(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> PortalJobsResponse:
    """Return the customer's job cards with status and staff info."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.job_cards.models import JobCard
    from app.modules.staff.models import StaffMember

    # Count total jobs for pagination
    count_stmt = select(sa_func.count(JobCard.id)).where(
        JobCard.customer_id == customer.id,
        JobCard.org_id == customer.org_id,
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(JobCard)
        .outerjoin(StaffMember, JobCard.assigned_to == StaffMember.id)
        .where(
            JobCard.customer_id == customer.id,
            JobCard.org_id == customer.org_id,
        )
        .order_by(JobCard.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    # Build a set of job card IDs to look up linked invoices
    job_ids = [jc.id for jc in rows]
    invoice_map: dict[uuid.UUID, str | None] = {}
    if job_ids:
        inv_stmt = (
            select(Invoice.job_card_id, Invoice.invoice_number)
            .where(
                Invoice.job_card_id.in_(job_ids),
                Invoice.org_id == customer.org_id,
            )
        )
        inv_rows = (await db.execute(inv_stmt)).all()
        for inv_row in inv_rows:
            invoice_map[inv_row[0]] = inv_row[1]

    # Resolve assigned staff names
    staff_ids = [jc.assigned_to for jc in rows if jc.assigned_to]
    staff_map: dict[uuid.UUID, str] = {}
    if staff_ids:
        staff_stmt = select(StaffMember.id, StaffMember.name).where(
            StaffMember.id.in_(staff_ids)
        )
        staff_rows = (await db.execute(staff_stmt)).all()
        for sr in staff_rows:
            staff_map[sr[0]] = sr[1]

    jobs: list[PortalJobItem] = []
    for jc in rows:
        jobs.append(
            PortalJobItem(
                id=jc.id,
                status=jc.status,
                description=jc.description,
                assigned_staff_name=staff_map.get(jc.assigned_to) if jc.assigned_to else None,
                vehicle_rego=jc.vehicle_rego,
                linked_invoice_number=invoice_map.get(jc.id),
                estimated_completion=None,
                created_at=jc.created_at,
            )
        )

    return PortalJobsResponse(
        branding=_build_branding(org, powered_by),
        jobs=jobs,
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Claims visibility  (Req 17)
# ---------------------------------------------------------------------------


async def get_portal_claims(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> PortalClaimsResponse:
    """Return the customer's claims with status and action timeline."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.claims.models import CustomerClaim, ClaimAction

    # Count total claims for pagination
    count_stmt = select(sa_func.count(CustomerClaim.id)).where(
        CustomerClaim.customer_id == customer.id,
        CustomerClaim.org_id == customer.org_id,
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(CustomerClaim)
        .options(selectinload(CustomerClaim.actions))
        .where(
            CustomerClaim.customer_id == customer.id,
            CustomerClaim.org_id == customer.org_id,
        )
        .order_by(CustomerClaim.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    claims: list[PortalClaimItem] = []
    for claim in rows:
        actions = [
            PortalClaimActionItem(
                action_type=a.action_type,
                from_status=a.from_status,
                to_status=a.to_status,
                notes=a.notes,
                performed_at=a.performed_at,
            )
            for a in sorted(
                (claim.actions or []),
                key=lambda a: a.performed_at,
            )
        ]
        claims.append(
            PortalClaimItem(
                id=claim.id,
                reference=claim.reference,
                claim_type=claim.claim_type,
                status=claim.status,
                description=claim.description,
                resolution_type=claim.resolution_type,
                resolution_notes=claim.resolution_notes,
                created_at=claim.created_at,
                actions=actions,
            )
        )

    return PortalClaimsResponse(
        branding=_build_branding(org, powered_by),
        claims=claims,
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Projects visibility  (Req 49)
# ---------------------------------------------------------------------------


async def get_portal_projects(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> "PortalProjectsResponse":
    """Return the customer's projects with status and details.

    Requirements: 49.1, 49.2, 49.3
    """
    from app.modules.projects.models import Project
    from app.modules.portal.schemas import PortalProjectItem, PortalProjectsResponse

    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Count total projects for pagination
    count_stmt = select(sa_func.count(Project.id)).where(
        Project.customer_id == customer.id,
        Project.org_id == org.id,
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Project)
        .where(
            Project.customer_id == customer.id,
            Project.org_id == org.id,
        )
        .order_by(Project.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    projects: list[PortalProjectItem] = []
    for proj in rows:
        projects.append(
            PortalProjectItem(
                id=proj.id,
                name=proj.name,
                status=proj.status,
                description=proj.description,
                budget_amount=proj.budget_amount,
                contract_value=proj.contract_value,
                start_date=proj.start_date,
                target_end_date=proj.target_end_date,
                created_at=proj.created_at,
            )
        )

    return PortalProjectsResponse(
        branding=_build_branding(org, powered_by),
        projects=projects,
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Progress Claims visibility  (Req 51)
# ---------------------------------------------------------------------------


async def get_portal_progress_claims(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> "PortalProgressClaimsResponse":
    """Return progress claims linked to the customer's projects.

    Requirements: 51.1, 51.2, 51.3
    """
    from app.modules.progress_claims.models import ProgressClaim
    from app.modules.projects.models import Project
    from app.modules.portal.schemas import PortalProgressClaimItem, PortalProgressClaimsResponse

    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Subquery: project IDs belonging to this customer and org
    project_ids_stmt = (
        select(Project.id)
        .where(
            Project.customer_id == customer.id,
            Project.org_id == org.id,
        )
    )

    # Count total progress claims for pagination
    count_stmt = select(sa_func.count(ProgressClaim.id)).where(
        ProgressClaim.org_id == org.id,
        ProgressClaim.project_id.in_(project_ids_stmt),
        ProgressClaim.status != "draft",
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(ProgressClaim)
        .where(
            ProgressClaim.org_id == org.id,
            ProgressClaim.project_id.in_(project_ids_stmt),
            ProgressClaim.status != "draft",
        )
        .order_by(ProgressClaim.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    claims: list[PortalProgressClaimItem] = []
    for claim in rows:
        claims.append(
            PortalProgressClaimItem(
                id=claim.id,
                project_id=claim.project_id,
                claim_number=claim.claim_number,
                status=claim.status,
                contract_value=claim.contract_value,
                revised_contract_value=claim.revised_contract_value,
                work_completed_to_date=claim.work_completed_to_date,
                work_completed_this_period=claim.work_completed_this_period,
                materials_on_site=claim.materials_on_site,
                retention_withheld=claim.retention_withheld,
                amount_due=claim.amount_due,
                completion_percentage=claim.completion_percentage,
                submitted_at=claim.submitted_at,
                approved_at=claim.approved_at,
                created_at=claim.created_at,
            )
        )

    return PortalProgressClaimsResponse(
        branding=_build_branding(org, powered_by),
        progress_claims=claims,
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Recurring invoice schedules  (Req 50)
# ---------------------------------------------------------------------------


async def get_portal_recurring(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> "PortalRecurringResponse":
    """Return the customer's recurring invoice schedules.

    Requirements: 50.1, 50.2, 50.3
    """
    from app.modules.recurring_invoices.models import RecurringSchedule
    from app.modules.portal.schemas import PortalRecurringItem, PortalRecurringResponse

    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Count total schedules for pagination
    count_stmt = select(sa_func.count(RecurringSchedule.id)).where(
        RecurringSchedule.customer_id == customer.id,
        RecurringSchedule.org_id == org.id,
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(RecurringSchedule)
        .where(
            RecurringSchedule.customer_id == customer.id,
            RecurringSchedule.org_id == org.id,
        )
        .order_by(RecurringSchedule.next_generation_date.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    schedules: list[PortalRecurringItem] = []
    for sched in rows:
        schedules.append(
            PortalRecurringItem(
                id=sched.id,
                frequency=sched.frequency,
                next_generation_date=sched.next_generation_date,
                status=sched.status,
                line_items=sched.line_items or [],
                start_date=sched.start_date,
                end_date=sched.end_date,
                auto_issue=sched.auto_issue,
                created_at=sched.created_at,
            )
        )

    return PortalRecurringResponse(
        branding=_build_branding(org, powered_by),
        schedules=schedules,
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Portal payment  (Req 61.3)
# ---------------------------------------------------------------------------


async def create_portal_payment(
    db: AsyncSession,
    token: str,
    invoice_id: uuid.UUID,
    amount: Decimal | None = None,
    ip_address: str | None = None,
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

    # --- Req 39.3: Audit log for portal payment initiation ---
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=None,
        action="portal.payment_initiated",
        entity_type="invoice",
        entity_id=invoice_id,
        after_value={
            "customer_id": str(customer.id),
            "invoice_number": invoice.invoice_number,
            "amount": str(pay_amount),
            "currency": invoice.currency,
        },
        ip_address=ip_address,
    )

    # Req 47.1: Track payment initiation event
    await track_portal_event(org.id, "payment_initiated")

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
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> PortalQuotesResponse:
    """Return the customer's quotes with acceptance capability."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    # Count total quotes for pagination
    count_sql = sa_text(
        "SELECT COUNT(*) FROM quotes "
        "WHERE customer_id = :cid AND org_id = :oid "
        "AND status NOT IN ('draft')"
    )
    total_count = (await db.execute(count_sql, {"cid": str(customer.id), "oid": str(org.id)})).scalar() or 0

    stmt = sa_text(
        "SELECT id, quote_number, status, expiry_date, terms, "
        "line_items, subtotal, tax_amount, total, currency, "
        "accepted_at, created_at "
        "FROM quotes "
        "WHERE customer_id = :cid AND org_id = :oid "
        "AND status NOT IN ('draft') "
        "ORDER BY created_at DESC "
        "LIMIT :lim OFFSET :off"
    )
    rows = await db.execute(stmt, {"cid": str(customer.id), "oid": str(org.id), "lim": limit, "off": offset})

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
            accepted_at=row[10],
            created_at=row[11],
        ))

    return PortalQuotesResponse(
        branding=_build_branding(org, powered_by),
        quotes=quotes,
        total=total_count,
    )


async def accept_portal_quote(
    db: AsyncSession,
    token: str,
    quote_id: uuid.UUID,
    ip_address: str | None = None,
) -> PortalAcceptQuoteResponse:
    """Accept a quote from the customer portal."""
    customer, org = await _resolve_token(db, token)

    from app.modules.quotes_v2.service import QuoteService

    # Verify the quote belongs to this customer
    row = await db.execute(
        sa_text(
            "SELECT acceptance_token, quote_number FROM quotes "
            "WHERE id = :qid AND customer_id = :cid AND org_id = :oid"
        ),
        {"qid": str(quote_id), "cid": str(customer.id), "oid": str(org.id)},
    )
    result = row.one_or_none()
    if result is None:
        raise ValueError("Quote not found")

    acceptance_token = result[0]
    quote_number = result[1]
    if not acceptance_token:
        raise ValueError("Quote does not have an acceptance token")

    svc = QuoteService(db)
    quote = await svc.accept_quote(acceptance_token)

    # --- Req 23: Notify org's primary contact about quote acceptance ---
    await _send_quote_acceptance_notification(
        db,
        org=org,
        customer=customer,
        quote_number=quote_number or str(quote_id),
        accepted_at=quote.accepted_at,
    )

    # --- Req 39.1: Audit log for portal quote acceptance ---
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=None,
        action="portal.quote_accepted",
        entity_type="quote",
        entity_id=quote_id,
        after_value={
            "customer_id": str(customer.id),
            "quote_number": quote_number,
            "status": quote.status,
        },
        ip_address=ip_address,
    )

    # Req 47.1: Track quote acceptance event
    await track_portal_event(org.id, "quote_accepted")

    return PortalAcceptQuoteResponse(
        quote_id=quote.id,
        status=quote.status,
        accepted_at=quote.accepted_at,
    )


async def _send_quote_acceptance_notification(
    db: AsyncSession,
    *,
    org: Organisation,
    customer: Customer,
    quote_number: str,
    accepted_at: datetime | None,
) -> None:
    """Send an email notification to the org's primary contact when a quote is accepted.

    Requirements: 23.1, 23.2, 23.3
    """
    import logging

    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    logger = logging.getLogger(__name__)

    # Resolve org's primary contact — the first active org_admin user
    admin_result = await db.execute(
        select(User).where(
            User.org_id == org.id,
            User.role == "org_admin",
            User.is_active.is_(True),
        ).limit(1)
    )
    admin_user = admin_result.scalar_one_or_none()
    if admin_user is None or not admin_user.email:
        logger.warning(
            "No active org_admin with email found for org %s — "
            "skipping quote acceptance notification",
            org.id,
        )
        return

    customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer"
    accepted_date_str = (
        accepted_at.strftime("%d %b %Y at %H:%M")
        if accepted_at
        else datetime.now(timezone.utc).strftime("%d %b %Y at %H:%M")
    )

    subject = f"Quote {quote_number} accepted by {customer_name}"

    html_body = (
        f"<p>Hi,</p>"
        f"<p>A customer has accepted a quote via the portal:</p>"
        f"<ul>"
        f"<li><strong>Quote Number:</strong> {quote_number}</li>"
        f"<li><strong>Customer:</strong> {customer_name}</li>"
        f"<li><strong>Accepted Date:</strong> {accepted_date_str}</li>"
        f"</ul>"
        f"<p>You can view the quote in your dashboard to take the next steps.</p>"
        f"<p>Kind regards,<br/>{org.name}</p>"
    )

    text_body = (
        f"Hi,\n\n"
        f"A customer has accepted a quote via the portal:\n\n"
        f"  Quote Number: {quote_number}\n"
        f"  Customer: {customer_name}\n"
        f"  Accepted Date: {accepted_date_str}\n\n"
        f"You can view the quote in your dashboard to take the next steps.\n\n"
        f"Kind regards,\n{org.name}"
    )

    try:
        log_entry = await log_email_sent(
            db,
            org_id=org.id,
            recipient=admin_user.email,
            template_type="quote_accepted",
            subject=subject,
            status="queued",
        )

        await send_email_task(
            org_id=str(org.id),
            log_id=str(log_entry["id"]),
            to_email=admin_user.email,
            to_name=admin_user.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            org_sender_name=org.name,
            template_type="quote_accepted",
        )
    except Exception:
        logger.exception(
            "Failed to send quote acceptance notification for quote %s org %s",
            quote_number,
            org.id,
        )


async def _send_portal_booking_notification(
    db: AsyncSession,
    *,
    org: Organisation,
    customer: Customer,
    booking: object,
) -> None:
    """Send an email notification to the org's primary contact when a booking is created via the portal.

    Requirements: 24.3
    """
    import logging

    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    logger = logging.getLogger(__name__)

    # Resolve org's primary contact — the first active org_admin user
    admin_result = await db.execute(
        select(User).where(
            User.org_id == org.id,
            User.role == "org_admin",
            User.is_active.is_(True),
        ).limit(1)
    )
    admin_user = admin_result.scalar_one_or_none()
    if admin_user is None or not admin_user.email:
        logger.warning(
            "No active org_admin with email found for org %s — "
            "skipping portal booking notification",
            org.id,
        )
        return

    customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip() or "Customer"
    booking_time = (
        booking.start_time.strftime("%d %b %Y at %H:%M")
        if booking.start_time
        else "Not specified"
    )
    service_type = getattr(booking, "service_type", None) or "General"

    subject = f"New portal booking from {customer_name}"

    html_body = (
        f"<p>Hi,</p>"
        f"<p>A customer has created a new booking via the portal:</p>"
        f"<ul>"
        f"<li><strong>Customer:</strong> {customer_name}</li>"
        f"<li><strong>Service Type:</strong> {service_type}</li>"
        f"<li><strong>Appointment Time:</strong> {booking_time}</li>"
        f"<li><strong>Status:</strong> {booking.status}</li>"
        f"</ul>"
        f"<p>You can view the booking in your dashboard to take the next steps.</p>"
        f"<p>Kind regards,<br/>{org.name}</p>"
    )

    text_body = (
        f"Hi,\n\n"
        f"A customer has created a new booking via the portal:\n\n"
        f"  Customer: {customer_name}\n"
        f"  Service Type: {service_type}\n"
        f"  Appointment Time: {booking_time}\n"
        f"  Status: {booking.status}\n\n"
        f"You can view the booking in your dashboard to take the next steps.\n\n"
        f"Kind regards,\n{org.name}"
    )

    try:
        log_entry = await log_email_sent(
            db,
            org_id=org.id,
            recipient=admin_user.email,
            template_type="portal_booking_created",
            subject=subject,
            status="queued",
        )

        await send_email_task(
            org_id=str(org.id),
            log_id=str(log_entry["id"]),
            to_email=admin_user.email,
            to_name=admin_user.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            org_sender_name=org.name,
            template_type="portal_booking_created",
        )
    except Exception:
        logger.exception(
            "Failed to send portal booking notification for org %s customer %s",
            org.id,
            customer.id,
        )


# ---------------------------------------------------------------------------
# Asset / service history  (Req 49.2)
# ---------------------------------------------------------------------------


async def get_portal_assets(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
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
        assets=portal_assets[offset:offset + limit],
        total=len(portal_assets),
    )


# ---------------------------------------------------------------------------
# Booking management  (Req 49.4)
# ---------------------------------------------------------------------------


async def get_portal_bookings(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> PortalBookingsResponse:
    """Return the customer's bookings."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.bookings_v2.models import Booking

    # Count total bookings for pagination
    count_stmt = select(sa_func.count(Booking.id)).where(
        Booking.customer_id == customer.id,
        Booking.org_id == org.id,
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Booking)
        .where(
            Booking.customer_id == customer.id,
            Booking.org_id == org.id,
        )
        .order_by(Booking.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).scalars().all()

    bookings = [
        PortalBookingItem(
            id=b.id,
            service_type=b.service_type,
            start_time=b.start_time,
            end_time=b.end_time,
            status=b.status,
            notes=b.notes,
            created_at=b.created_at,
        )
        for b in rows
    ]

    return PortalBookingsResponse(
        branding=_build_branding(org, powered_by),
        bookings=bookings,
        total=total_count,
    )


async def create_portal_booking(
    db: AsyncSession,
    token: str,
    service_type: str | None,
    start_time: datetime,
    notes: str | None,
    ip_address: str | None = None,
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

    # Req 24.1, 24.2: Confirm the booking (transition pending → confirmed)
    await svc.send_confirmation(org.id, booking.id)
    await db.refresh(booking)

    # Req 24.3: Notify org about the new portal booking
    await _send_portal_booking_notification(
        db,
        org=org,
        customer=customer,
        booking=booking,
    )

    # --- Req 39.2: Audit log for portal booking creation ---
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=None,
        action="portal.booking_created",
        entity_type="booking",
        entity_id=booking.id,
        after_value={
            "customer_id": str(customer.id),
            "service_type": service_type,
            "start_time": str(booking.start_time),
            "status": booking.status,
        },
        ip_address=ip_address,
    )

    # Req 47.1: Track booking creation event
    await track_portal_event(org.id, "booking_created")

    return PortalBookingCreateResponse(
        booking_id=booking.id,
        status=booking.status,
        start_time=booking.start_time,
        end_time=booking.end_time,
    )


async def get_portal_available_slots(
    db: AsyncSession,
    token: str,
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
    token: str,
    limit: int = 20,
    offset: int = 0,
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
            programme_configured=False,
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
        programme_configured=True,
        total_points=balance,
        current_tier=current_tier,
        next_tier=next_tier,
        points_to_next_tier=points_to_next,
        transactions=portal_transactions[offset:offset + limit],
        total=len(portal_transactions),
    )


# ---------------------------------------------------------------------------
# Profile update  (Req 21)
# ---------------------------------------------------------------------------

# Simple email regex — covers the vast majority of valid addresses
import re as _re

_EMAIL_RE = _re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
# Phone: allow digits, spaces, +, -, parentheses, dots
_PHONE_RE = _re.compile(r"^[\d\s\+\-\(\)\.]{3,30}$")


async def update_portal_profile(
    db: AsyncSession,
    token: str,
    payload: PortalProfileUpdateRequest,
    ip_address: str | None = None,
) -> PortalProfileUpdateResponse:
    """Validate and update the customer's contact details from the portal.

    Requirements: 21.1, 21.2, 21.3, 21.4
    """
    customer, _org = await _resolve_token(db, token)

    before_value: dict = {}
    after_value: dict = {"customer_id": str(customer.id)}

    if payload.email is not None:
        email = payload.email.strip()
        if not email:
            raise ValueError("Email cannot be empty")
        if not _EMAIL_RE.match(email):
            raise ValueError("Invalid email format")
        before_value["email"] = customer.email
        customer.email = email
        after_value["email"] = email

    if payload.phone is not None:
        phone = payload.phone.strip()
        if not phone:
            raise ValueError("Phone cannot be empty")
        if not _PHONE_RE.match(phone):
            raise ValueError("Invalid phone format")
        before_value["phone"] = customer.phone
        customer.phone = phone
        after_value["phone"] = phone

    await db.flush()
    await db.refresh(customer)

    # --- Req 39.4: Audit log for portal profile update ---
    await write_audit_log(
        session=db,
        org_id=_org.id,
        user_id=None,
        action="portal.profile_updated",
        entity_type="customer",
        entity_id=customer.id,
        before_value=before_value if before_value else None,
        after_value=after_value,
        ip_address=ip_address,
    )

    return PortalProfileUpdateResponse(
        email=customer.email,
        phone=customer.phone,
        message="Profile updated successfully",
    )


# ---------------------------------------------------------------------------
# Compliance documents  (Req 19)
# ---------------------------------------------------------------------------


async def get_portal_documents(
    db: AsyncSession,
    token: str,
    limit: int = 20,
    offset: int = 0,
) -> PortalDocumentsResponse:
    """Return compliance documents linked to the customer's invoices."""
    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    from app.modules.compliance_docs.models import ComplianceDocument

    # Get all invoice IDs for this customer
    inv_ids_stmt = select(Invoice.id).where(
        Invoice.customer_id == customer.id,
        Invoice.org_id == customer.org_id,
        Invoice.status.notin_(["draft", "voided"]),
    )
    inv_id_rows = (await db.execute(inv_ids_stmt)).scalars().all()

    if not inv_id_rows:
        return PortalDocumentsResponse(
            branding=_build_branding(org, powered_by),
            documents=[],
            total=0,
        )

    # Build a map of invoice_id -> invoice_number for display
    inv_num_stmt = select(Invoice.id, Invoice.invoice_number).where(
        Invoice.id.in_(inv_id_rows),
    )
    inv_num_rows = (await db.execute(inv_num_stmt)).all()
    inv_number_map: dict[uuid.UUID, str | None] = {
        row[0]: row[1] for row in inv_num_rows
    }

    # Query compliance documents linked to those invoices
    # Count total documents for pagination
    count_stmt = (
        select(sa_func.count(ComplianceDocument.id))
        .where(
            ComplianceDocument.org_id == org.id,
            ComplianceDocument.invoice_id.in_(inv_id_rows),
        )
    )
    total_count = (await db.execute(count_stmt)).scalar() or 0

    doc_stmt = (
        select(ComplianceDocument)
        .where(
            ComplianceDocument.org_id == org.id,
            ComplianceDocument.invoice_id.in_(inv_id_rows),
        )
        .order_by(ComplianceDocument.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    docs = (await db.execute(doc_stmt)).scalars().all()

    documents: list[PortalDocumentItem] = []
    for doc in docs:
        download_url = f"/api/v2/compliance-docs/{doc.id}/download"
        documents.append(
            PortalDocumentItem(
                id=doc.id,
                document_type=doc.document_type,
                description=doc.description,
                linked_invoice_number=inv_number_map.get(doc.invoice_id) if doc.invoice_id else None,
                download_url=download_url,
            )
        )

    return PortalDocumentsResponse(
        branding=_build_branding(org, powered_by),
        documents=documents,
        total=total_count,
    )


# ---------------------------------------------------------------------------
# Booking cancellation  (Req 22)
# ---------------------------------------------------------------------------

_CANCELLABLE_STATUSES = {"pending", "confirmed"}


async def cancel_portal_booking(
    db: AsyncSession,
    token: str,
    booking_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Cancel a portal booking after validating ownership and status.

    Requirements: 22.1, 22.2, 22.3
    """
    customer, org = await _resolve_token(db, token)

    from app.modules.bookings_v2.models import Booking

    stmt = select(Booking).where(
        Booking.id == booking_id,
        Booking.customer_id == customer.id,
        Booking.org_id == org.id,
    )
    booking = (await db.execute(stmt)).scalar_one_or_none()
    if booking is None:
        raise ValueError("Booking not found")

    if booking.status not in _CANCELLABLE_STATUSES:
        raise ValueError(
            f"Booking cannot be cancelled — current status is '{booking.status}'"
        )

    previous_status = booking.status
    booking.status = "cancelled"
    await db.flush()
    await db.refresh(booking)

    # --- Req 39.5: Audit log for portal booking cancellation ---
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=None,
        action="portal.booking_cancelled",
        entity_type="booking",
        entity_id=booking_id,
        before_value={"status": previous_status},
        after_value={
            "customer_id": str(customer.id),
            "status": "cancelled",
        },
        ip_address=ip_address,
    )

    return {
        "booking_id": booking.id,
        "status": booking.status,
        "message": "Booking cancelled successfully",
    }


# ---------------------------------------------------------------------------
# DSAR — Data Subject Access Request  (Req 45)
# ---------------------------------------------------------------------------

_VALID_DSAR_TYPES = {"export", "deletion"}


async def create_portal_dsar(
    db: AsyncSession,
    token: str,
    request_type: str,
    ip_address: str | None = None,
) -> dict:
    """Create a Data Subject Access Request and notify the org admin.

    Accepts ``request_type`` of ``"export"`` (data export) or
    ``"deletion"`` (account deletion).  The request is recorded via
    the audit log and the org admin is notified by email.

    Requirements: 45.1, 45.2, 45.3, 45.4, 45.5
    """
    customer, org = await _resolve_token(db, token)

    if request_type not in _VALID_DSAR_TYPES:
        raise ValueError(
            f"Invalid request_type '{request_type}'. Must be 'export' or 'deletion'."
        )

    # Record the DSAR via audit log
    action_label = (
        "portal.dsar_export" if request_type == "export" else "portal.dsar_deletion"
    )
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=None,
        action=action_label,
        entity_type="customer",
        entity_id=customer.id,
        after_value={
            "customer_id": str(customer.id),
            "customer_name": f"{customer.first_name or ''} {customer.last_name or ''}".strip(),
            "request_type": request_type,
        },
        ip_address=ip_address,
    )

    # Notify org admin via email
    await _send_dsar_notification(
        db,
        org=org,
        customer=customer,
        request_type=request_type,
    )

    friendly_type = "data export" if request_type == "export" else "account deletion"
    return {
        "request_type": request_type,
        "message": f"Your {friendly_type} request has been submitted and will be reviewed by the organisation.",
    }


async def _send_dsar_notification(
    db: AsyncSession,
    *,
    org: Organisation,
    customer: Customer,
    request_type: str,
) -> None:
    """Send an email notification to the org admin when a DSAR is submitted.

    Requirements: 45.4
    """
    import logging

    from app.modules.auth.models import User
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    logger = logging.getLogger(__name__)

    # Resolve org's primary contact — the first active org_admin user
    admin_result = await db.execute(
        select(User).where(
            User.org_id == org.id,
            User.role == "org_admin",
            User.is_active.is_(True),
        ).limit(1)
    )
    admin_user = admin_result.scalar_one_or_none()
    if admin_user is None or not admin_user.email:
        logger.warning(
            "No active org_admin with email found for org %s — "
            "skipping DSAR notification",
            org.id,
        )
        return

    customer_name = (
        f"{customer.first_name or ''} {customer.last_name or ''}".strip()
        or "Customer"
    )
    friendly_type = "Data Export" if request_type == "export" else "Account Deletion"

    subject = f"Privacy Request: {friendly_type} from {customer_name}"

    html_body = (
        f"<p>Hi,</p>"
        f"<p>A customer has submitted a privacy request via the portal:</p>"
        f"<ul>"
        f"<li><strong>Request Type:</strong> {friendly_type}</li>"
        f"<li><strong>Customer:</strong> {customer_name}</li>"
        f"<li><strong>Customer Email:</strong> {customer.email or 'Not provided'}</li>"
        f"</ul>"
        f"<p>Please review and action this request in accordance with your "
        f"privacy obligations.</p>"
        f"<p>Kind regards,<br/>{org.name}</p>"
    )

    text_body = (
        f"Hi,\n\n"
        f"A customer has submitted a privacy request via the portal:\n\n"
        f"  Request Type: {friendly_type}\n"
        f"  Customer: {customer_name}\n"
        f"  Customer Email: {customer.email or 'Not provided'}\n\n"
        f"Please review and action this request in accordance with your "
        f"privacy obligations.\n\n"
        f"Kind regards,\n{org.name}"
    )

    try:
        log_entry = await log_email_sent(
            db,
            org_id=org.id,
            recipient=admin_user.email,
            template_type="dsar_request",
            subject=subject,
            status="queued",
        )

        await send_email_task(
            org_id=str(org.id),
            log_id=str(log_entry["id"]),
            to_email=admin_user.email,
            to_name=admin_user.email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            org_sender_name=org.name,
            template_type="dsar_request",
        )
    except Exception:
        logger.exception(
            "Failed to send DSAR notification for customer %s org %s",
            customer.id,
            org.id,
        )


# ---------------------------------------------------------------------------
# Self-service token recovery  (Req 52.1, 52.2, 52.3, 52.4)
# ---------------------------------------------------------------------------


async def recover_portal_link(
    db: AsyncSession,
    email: str,
) -> dict:
    """Look up all portal-enabled customers with the given email and send
    portal links via email.

    Always returns a generic success message regardless of whether any
    matching customers were found — this prevents email enumeration.

    Requirements: 52.1, 52.2, 52.3, 52.4
    """
    from app.config import settings
    from app.modules.notifications.service import log_email_sent
    from app.tasks.notifications import send_email_task

    import logging
    logger = logging.getLogger(__name__)

    logger.info("Portal link recovery requested for email (redacted)")

    # Find all portal-enabled customers with this email
    stmt = (
        select(Customer)
        .where(
            Customer.email == email,
            Customer.enable_portal.is_(True),
            Customer.portal_token.isnot(None),
            Customer.is_anonymised.is_(False),
        )
    )
    result = await db.execute(stmt)
    customers = result.scalars().all()

    if not customers:
        # No matching customers — return silently to prevent enumeration
        return {
            "message": "If an account exists with that email, a portal link has been sent.",
        }

    # Send a portal link for each matching customer
    for customer in customers:
        # Fetch the org for branding
        org_stmt = select(Organisation).where(Organisation.id == customer.org_id)
        org = (await db.execute(org_stmt)).scalar_one_or_none()
        if org is None:
            continue

        # Check org-level portal enabled
        org_settings = org.settings or {}
        if not org_settings.get("portal_enabled", True):
            continue

        org_name = org.name or "Your Service Provider"
        customer_name = f"{customer.first_name or ''} {customer.last_name or ''}".strip()
        portal_url = f"{settings.frontend_base_url}/portal/{customer.portal_token}"

        email_subject = f"Your Portal Access Link — {org_name}"

        html_body = (
            f"<p>Hi {customer_name or 'there'},</p>"
            f"<p>We received a request to resend your customer portal link.</p>"
            f'<p><a href="{portal_url}" style="display:inline-block;padding:12px 24px;'
            f'background-color:#2563eb;color:#ffffff;text-decoration:none;border-radius:6px;'
            f'font-weight:600;">Open Your Portal</a></p>'
            f'<p>Or copy this link: <a href="{portal_url}">{portal_url}</a></p>'
            f"<p>If you did not request this, you can safely ignore this email.</p>"
            f"<p>Kind regards,<br/>{org_name}</p>"
        )

        text_body = (
            f"Hi {customer_name or 'there'},\n\n"
            f"We received a request to resend your customer portal link.\n\n"
            f"You can access your portal here:\n"
            f"{portal_url}\n\n"
            f"If you did not request this, you can safely ignore this email.\n\n"
            f"Kind regards,\n{org_name}"
        )

        try:
            log_entry = await log_email_sent(
                db,
                org_id=org.id,
                recipient=email,
                template_type="portal_recovery",
                subject=email_subject,
                status="queued",
            )

            await send_email_task(
                org_id=str(org.id),
                log_id=str(log_entry["id"]),
                to_email=email,
                to_name=customer_name,
                subject=email_subject,
                html_body=html_body,
                text_body=text_body,
                org_sender_name=org_name,
                template_type="portal_recovery",
            )
        except Exception:
            logger.exception(
                "Failed to send portal recovery email for customer %s org %s",
                customer.id,
                org.id,
            )

    return {
        "message": "If an account exists with that email, a portal link has been sent.",
    }


async def get_portal_messages(
    db: AsyncSession,
    token: str,
    limit: int = 50,
    offset: int = 0,
) -> "PortalMessagesResponse":
    """Return the customer's SMS conversation history.

    Queries sms_messages via the sms_conversations table, matching
    the customer's phone number and org_id.

    Requirements: 63.1, 63.2, 63.3, 63.4
    """
    from app.modules.portal.schemas import PortalMessageItem, PortalMessagesResponse
    from app.modules.sms_chat.models import SmsConversation, SmsMessage

    customer, org = await _resolve_token(db, token)
    powered_by = await _get_powered_by(db, org)

    phone = customer.phone
    if not phone:
        return PortalMessagesResponse(
            branding=_build_branding(org, powered_by),
            messages=[],
            total=0,
        )

    # Find the conversation for this customer's phone + org
    conv_stmt = (
        select(SmsConversation)
        .where(SmsConversation.org_id == org.id)
        .where(SmsConversation.phone_number == phone)
    )
    conv_result = await db.execute(conv_stmt)
    conversation = conv_result.scalar_one_or_none()

    if conversation is None:
        return PortalMessagesResponse(
            branding=_build_branding(org, powered_by),
            messages=[],
            total=0,
        )

    # Count total messages
    from sqlalchemy import func as sa_func
    count_stmt = (
        select(sa_func.count())
        .select_from(SmsMessage)
        .where(SmsMessage.conversation_id == conversation.id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch messages ordered chronologically (oldest first, Req 63.4)
    msg_stmt = (
        select(SmsMessage)
        .where(SmsMessage.conversation_id == conversation.id)
        .order_by(SmsMessage.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    msg_result = await db.execute(msg_stmt)
    messages = msg_result.scalars().all()

    portal_messages = [
        PortalMessageItem(
            id=m.id,
            direction=m.direction,
            body=m.body,
            created_at=m.created_at,
            status=m.status,
        )
        for m in messages
    ]

    return PortalMessagesResponse(
        branding=_build_branding(org, powered_by),
        messages=portal_messages,
        total=total,
    )
