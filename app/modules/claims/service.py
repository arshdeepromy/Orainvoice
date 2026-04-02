"""Service layer for Customer Claims & Returns module.

Handles claim lifecycle management, validation, and audit logging.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 2.4, 2.5, 3.1-3.8, 11.4, 12.1, 12.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import write_audit_log
from app.modules.auth.models import User
from app.modules.claims.models import (
    VALID_CLAIM_TRANSITIONS,
    ClaimAction,
    ClaimStatus,
    ClaimType,
    CustomerClaim,
    ResolutionType,
)
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.job_cards.models import JobCard


async def create_claim(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    claim_type: ClaimType,
    description: str,
    invoice_id: uuid.UUID | None = None,
    job_card_id: uuid.UUID | None = None,
    line_item_ids: list[uuid.UUID] | None = None,
    branch_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new claim in 'open' status.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 11.4, 12.1
    """

    # --- Validate customer belongs to organisation ---
    cust_result = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    customer = cust_result.scalar_one_or_none()
    if customer is None:
        raise ValueError("Customer not found in this organisation")

    # --- Validate at least one source reference (Req 1.2) ---
    if invoice_id is None and job_card_id is None and not line_item_ids:
        raise ValueError(
            "At least one of invoice_id, job_card_id, or line_item_id is required"
        )

    # --- Validate referenced invoice belongs to same org (Req 1.3, 1.8) ---
    invoice = None
    if invoice_id is not None:
        inv_result = await db.execute(
            select(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.org_id == org_id,
            )
        )
        invoice = inv_result.scalar_one_or_none()
        if invoice is None:
            raise ValueError("Invoice not found in this organisation")

    # --- Validate referenced job card belongs to same org (Req 1.3, 1.8) ---
    job_card = None
    if job_card_id is not None:
        jc_result = await db.execute(
            select(JobCard).where(
                JobCard.id == job_card_id,
                JobCard.org_id == org_id,
            )
        )
        job_card = jc_result.scalar_one_or_none()
        if job_card is None:
            raise ValueError("Job card not found in this organisation")

    # --- Inherit branch_id from linked invoice/job card (Req 11.4) ---
    if branch_id is None:
        if invoice is not None and invoice.branch_id is not None:
            branch_id = invoice.branch_id
        elif job_card is not None and job_card.branch_id is not None:
            branch_id = job_card.branch_id

    # --- Create claim record (Req 1.1, 1.7) ---
    now = datetime.now(timezone.utc)
    claim = CustomerClaim(
        org_id=org_id,
        branch_id=branch_id,
        customer_id=customer_id,
        invoice_id=invoice_id,
        job_card_id=job_card_id,
        line_item_ids=[str(lid) for lid in line_item_ids] if line_item_ids else [],
        claim_type=claim_type.value if isinstance(claim_type, ClaimType) else claim_type,
        status=ClaimStatus.OPEN.value,
        description=description,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(claim)
    await db.flush()

    # --- Create initial ClaimAction record ---
    action = ClaimAction(
        org_id=org_id,
        claim_id=claim.id,
        action_type="status_change",
        from_status=None,
        to_status=ClaimStatus.OPEN.value,
        action_data={"claim_type": claim.claim_type},
        notes=None,
        performed_by=user_id,
        performed_at=now,
    )
    db.add(action)
    await db.flush()

    # --- Write audit log entry (Req 12.1) ---
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="claim.created",
        entity_type="claim",
        entity_id=claim.id,
        before_value=None,
        after_value={
            "status": claim.status,
            "claim_type": claim.claim_type,
            "customer_id": str(customer_id),
            "invoice_id": str(invoice_id) if invoice_id else None,
            "job_card_id": str(job_card_id) if job_card_id else None,
            "branch_id": str(branch_id) if branch_id else None,
            "description": description[:200],
        },
        ip_address=ip_address,
    )

    return {
        "id": claim.id,
        "org_id": claim.org_id,
        "branch_id": claim.branch_id,
        "customer_id": claim.customer_id,
        "invoice_id": claim.invoice_id,
        "job_card_id": claim.job_card_id,
        "line_item_ids": claim.line_item_ids,
        "claim_type": claim.claim_type,
        "status": claim.status,
        "description": claim.description,
        "cost_to_business": claim.cost_to_business,
        "cost_breakdown": claim.cost_breakdown,
        "created_by": claim.created_by,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
    }


async def update_claim_status(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    claim_id: uuid.UUID,
    new_status: ClaimStatus,
    notes: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Transition claim to new status with workflow validation.

    Requirements: 2.1, 2.2, 2.3, 2.6, 2.7, 12.2
    """

    # --- Fetch claim scoped to organisation ---
    result = await db.execute(
        select(CustomerClaim).where(
            CustomerClaim.id == claim_id,
            CustomerClaim.org_id == org_id,
        )
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise ValueError("Claim not found in this organisation")

    # --- Validate status transition (Req 2.1, 2.2, 2.3, 2.6) ---
    current_status = claim.status
    target_status = new_status.value if isinstance(new_status, ClaimStatus) else new_status
    allowed = VALID_CLAIM_TRANSITIONS.get(current_status, set())

    if target_status not in allowed:
        allowed_list = sorted(allowed) if allowed else []
        raise ValueError(
            f"Cannot transition from '{current_status}' to '{target_status}'. "
            f"Allowed: {allowed_list}"
        )

    # --- Update claim status and timestamp (Req 2.7) ---
    now = datetime.now(timezone.utc)
    claim.status = target_status
    claim.updated_at = now

    # --- Create ClaimAction record (Req 2.7) ---
    action = ClaimAction(
        org_id=org_id,
        claim_id=claim.id,
        action_type="status_change",
        from_status=current_status,
        to_status=target_status,
        action_data={},
        notes=notes,
        performed_by=user_id,
        performed_at=now,
    )
    db.add(action)
    await db.flush()

    # --- Write audit log entry (Req 12.2) ---
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="claim.status_changed",
        entity_type="claim",
        entity_id=claim.id,
        before_value={"status": current_status},
        after_value={"status": target_status},
        ip_address=ip_address,
    )

    return {
        "id": claim.id,
        "org_id": claim.org_id,
        "branch_id": claim.branch_id,
        "customer_id": claim.customer_id,
        "invoice_id": claim.invoice_id,
        "job_card_id": claim.job_card_id,
        "line_item_ids": claim.line_item_ids,
        "claim_type": claim.claim_type,
        "status": claim.status,
        "description": claim.description,
        "resolution_type": claim.resolution_type,
        "resolution_amount": claim.resolution_amount,
        "resolution_notes": claim.resolution_notes,
        "resolved_at": claim.resolved_at,
        "resolved_by": claim.resolved_by,
        "cost_to_business": claim.cost_to_business,
        "cost_breakdown": claim.cost_breakdown,
        "created_by": claim.created_by,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
    }


# ---------------------------------------------------------------------------
# get_claim  (Task 3.9)
# Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
# ---------------------------------------------------------------------------


async def get_claim(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    claim_id: uuid.UUID,
) -> dict:
    """Return full claim details with timeline, related entities, and cost breakdown.

    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
    """

    result = await db.execute(
        select(CustomerClaim)
        .where(
            CustomerClaim.id == claim_id,
            CustomerClaim.org_id == org_id,
        )
        .options(
            selectinload(CustomerClaim.customer),
            selectinload(CustomerClaim.invoice),
            selectinload(CustomerClaim.job_card),
            selectinload(CustomerClaim.actions).selectinload(
                ClaimAction.performed_by_user
            ),
        )
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise ValueError("Claim not found in this organisation")

    # --- Build customer info (Req 7.1) ---
    customer_info = None
    if claim.customer is not None:
        c = claim.customer
        customer_info = {
            "id": c.id,
            "first_name": c.first_name,
            "last_name": c.last_name,
            "email": c.email,
            "phone": c.phone,
            "company_name": getattr(c, "company_name", None),
        }

    # --- Build invoice summary (Req 7.3) ---
    invoice_info = None
    if claim.invoice is not None:
        inv = claim.invoice
        invoice_info = {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "total": inv.total,
            "status": inv.status,
        }

    # --- Build job card summary (Req 7.3) ---
    job_card_info = None
    if claim.job_card is not None:
        jc = claim.job_card
        job_card_info = {
            "id": jc.id,
            "description": getattr(jc, "description", None),
            "status": getattr(jc, "status", None),
            "vehicle_rego": getattr(jc, "vehicle_rego", None),
        }

    # --- Build timeline of actions with user names (Req 7.2, 7.5) ---
    timeline = []
    for action in sorted(claim.actions, key=lambda a: a.performed_at):
        user = action.performed_by_user
        performed_by_name = None
        if user is not None:
            parts = [user.first_name or "", user.last_name or ""]
            performed_by_name = " ".join(p for p in parts if p) or user.email
        timeline.append(
            {
                "id": action.id,
                "action_type": action.action_type,
                "from_status": action.from_status,
                "to_status": action.to_status,
                "action_data": action.action_data,
                "notes": action.notes,
                "performed_by": action.performed_by,
                "performed_by_name": performed_by_name,
                "performed_at": action.performed_at,
            }
        )

    # --- Build cost breakdown (Req 7.4) ---
    raw_breakdown = claim.cost_breakdown or {}
    cost_breakdown = {
        "labour_cost": raw_breakdown.get("labour_cost", 0),
        "parts_cost": raw_breakdown.get("parts_cost", 0),
        "write_off_cost": raw_breakdown.get("write_off_cost", 0),
    }

    return {
        "id": claim.id,
        "org_id": claim.org_id,
        "branch_id": claim.branch_id,
        "customer_id": claim.customer_id,
        "customer": customer_info,
        # Source references
        "invoice_id": claim.invoice_id,
        "invoice": invoice_info,
        "job_card_id": claim.job_card_id,
        "job_card": job_card_info,
        "line_item_ids": claim.line_item_ids,
        # Claim details
        "claim_type": claim.claim_type,
        "status": claim.status,
        "description": claim.description,
        # Resolution details
        "resolution_type": claim.resolution_type,
        "resolution_amount": claim.resolution_amount,
        "resolution_notes": claim.resolution_notes,
        "resolved_at": claim.resolved_at,
        "resolved_by": claim.resolved_by,
        # Downstream entity references (Req 7.3)
        "refund_id": claim.refund_id,
        "credit_note_id": claim.credit_note_id,
        "return_movement_ids": claim.return_movement_ids,
        "warranty_job_id": claim.warranty_job_id,
        # Cost tracking (Req 7.4)
        "cost_to_business": claim.cost_to_business,
        "cost_breakdown": cost_breakdown,
        # Audit
        "created_by": claim.created_by,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
        # Timeline (Req 7.2, 7.5)
        "actions": timeline,
    }


# ---------------------------------------------------------------------------
# list_claims  (Task 3.10)
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
# ---------------------------------------------------------------------------


async def list_claims(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    status: str | None = None,
    claim_type: str | None = None,
    customer_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Return paginated claim list with total count.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """

    # --- Base query scoped to org ---
    base = select(CustomerClaim).where(CustomerClaim.org_id == org_id)

    # --- Apply filters (Req 6.2) ---
    if status is not None:
        base = base.where(CustomerClaim.status == status)
    if claim_type is not None:
        base = base.where(CustomerClaim.claim_type == claim_type)
    if customer_id is not None:
        base = base.where(CustomerClaim.customer_id == customer_id)
    if branch_id is not None:
        base = base.where(CustomerClaim.branch_id == branch_id)
    if date_from is not None:
        base = base.where(CustomerClaim.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to is not None:
        base = base.where(CustomerClaim.created_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc))

    # --- Search by customer name, invoice number, or description (Req 6.3) ---
    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        base = base.outerjoin(Customer, CustomerClaim.customer_id == Customer.id)
        base = base.outerjoin(Invoice, CustomerClaim.invoice_id == Invoice.id)
        base = base.where(
            or_(
                (Customer.first_name + " " + Customer.last_name).ilike(pattern),
                Invoice.invoice_number.ilike(pattern),
                CustomerClaim.description.ilike(pattern),
            )
        )

    # --- Count total matching claims (Req 6.1) ---
    count_q = select(func.count()).select_from(base.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # --- Fetch paginated items ordered by created_at desc (Req 6.4) ---
    items_q = (
        base.options(selectinload(CustomerClaim.customer))
        .order_by(CustomerClaim.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items_result = await db.execute(items_q)
    claims = items_result.scalars().all()

    items = []
    for claim in claims:
        customer_name = None
        if claim.customer is not None:
            parts = [claim.customer.first_name or "", claim.customer.last_name or ""]
            customer_name = " ".join(p for p in parts if p) or None
        items.append(
            {
                "id": claim.id,
                "customer_id": claim.customer_id,
                "customer_name": customer_name,
                "claim_type": claim.claim_type,
                "status": claim.status,
                "description": claim.description,
                "cost_to_business": claim.cost_to_business,
                "branch_id": claim.branch_id,
                "created_at": claim.created_at,
            }
        )

    return {"items": items, "total": total}


# ---------------------------------------------------------------------------
# get_customer_claims_summary  (Task 3.13)
# Requirements: 9.1, 9.2, 9.3
# ---------------------------------------------------------------------------


async def get_customer_claims_summary(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> dict:
    """Return all claims for a customer with summary statistics.

    Requirements: 9.1, 9.2, 9.3
    """

    # --- Fetch all claims for this customer in the org (Req 9.1) ---
    result = await db.execute(
        select(CustomerClaim)
        .where(
            CustomerClaim.org_id == org_id,
            CustomerClaim.customer_id == customer_id,
        )
        .order_by(CustomerClaim.created_at.desc())
    )
    claims = result.scalars().all()

    # --- Build summary statistics (Req 9.2) ---
    total_claims = len(claims)
    open_claims = sum(1 for c in claims if c.status == ClaimStatus.OPEN.value)
    total_cost_to_business = sum(c.cost_to_business for c in claims)

    # --- Build claim list items (Req 9.3) ---
    items = []
    for claim in claims:
        items.append(
            {
                "id": claim.id,
                "customer_id": claim.customer_id,
                "customer_name": None,
                "claim_type": claim.claim_type,
                "status": claim.status,
                "description": claim.description,
                "cost_to_business": claim.cost_to_business,
                "branch_id": claim.branch_id,
                "created_at": claim.created_at,
            }
        )

    return {
        "total_claims": total_claims,
        "open_claims": open_claims,
        "total_cost_to_business": total_cost_to_business,
        "claims": items,
    }


# ---------------------------------------------------------------------------
# resolve_claim  (Task 5.1)
# Requirements: 2.4, 2.5, 3.1-3.8, 12.3
# ---------------------------------------------------------------------------


async def resolve_claim(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    claim_id: uuid.UUID,
    resolution_type: ResolutionType,
    resolution_amount: Decimal | None = None,
    resolution_notes: str | None = None,
    return_stock_item_ids: list[uuid.UUID] | None = None,
    ip_address: str | None = None,
) -> dict:
    """Apply resolution to a claim and trigger downstream actions.

    1. Fetches the claim
    2. Validates status is 'approved' (or 'rejected' for no_action)
    3. Calls ResolutionEngine.execute_resolution
    4. Updates claim with resolution details
    5. Creates ClaimAction with action_type 'resolution_applied'
    6. Writes audit log

    Requirements: 2.4, 2.5, 3.1-3.8, 12.3
    """
    from app.modules.claims.resolution_engine import ResolutionEngine

    # --- Fetch claim scoped to organisation ---
    result = await db.execute(
        select(CustomerClaim).where(
            CustomerClaim.id == claim_id,
            CustomerClaim.org_id == org_id,
        )
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise ValueError("Claim not found in this organisation")

    rt = resolution_type.value if isinstance(resolution_type, ResolutionType) else resolution_type

    # --- Status validation ---
    if rt == ResolutionType.NO_ACTION.value:
        if claim.status not in (ClaimStatus.APPROVED.value, ClaimStatus.REJECTED.value):
            raise ValueError(
                "Claim must be in 'approved' or 'rejected' status for no_action resolution"
            )
    else:
        if claim.status != ClaimStatus.APPROVED.value:
            raise ValueError("Claim must be in 'approved' status before resolution")

    # --- Execute resolution via engine ---
    engine = ResolutionEngine(db)
    resolution_result = await engine.execute_resolution(
        claim=claim,
        resolution_type=resolution_type,
        resolution_amount=resolution_amount,
        return_stock_item_ids=return_stock_item_ids,
        user_id=user_id,
        ip_address=ip_address,
    )

    # --- Store resolution notes ---
    if resolution_notes:
        claim.resolution_notes = resolution_notes
        await db.flush()

    # --- Create ClaimAction record ---
    now = datetime.now(timezone.utc)
    action = ClaimAction(
        org_id=org_id,
        claim_id=claim.id,
        action_type="resolution_applied",
        from_status=ClaimStatus.APPROVED.value,
        to_status=ClaimStatus.RESOLVED.value,
        action_data={
            "resolution_type": rt,
            "resolution_amount": str(resolution_amount) if resolution_amount else None,
            "refund_id": str(resolution_result.refund_id) if resolution_result.refund_id else None,
            "credit_note_id": str(resolution_result.credit_note_id) if resolution_result.credit_note_id else None,
            "return_movement_ids": [
                str(m["movement_id"]) for m in resolution_result.return_movement_ids
            ],
            "warranty_job_id": str(resolution_result.warranty_job_id) if resolution_result.warranty_job_id else None,
        },
        notes=resolution_notes,
        performed_by=user_id,
        performed_at=now,
    )
    db.add(action)
    await db.flush()

    return {
        "id": claim.id,
        "org_id": claim.org_id,
        "branch_id": claim.branch_id,
        "customer_id": claim.customer_id,
        "invoice_id": claim.invoice_id,
        "job_card_id": claim.job_card_id,
        "line_item_ids": claim.line_item_ids,
        "claim_type": claim.claim_type,
        "status": claim.status,
        "description": claim.description,
        "resolution_type": claim.resolution_type,
        "resolution_amount": claim.resolution_amount,
        "resolution_notes": claim.resolution_notes,
        "resolved_at": claim.resolved_at,
        "resolved_by": claim.resolved_by,
        "refund_id": claim.refund_id,
        "credit_note_id": claim.credit_note_id,
        "return_movement_ids": claim.return_movement_ids,
        "warranty_job_id": claim.warranty_job_id,
        "cost_to_business": claim.cost_to_business,
        "cost_breakdown": claim.cost_breakdown,
        "created_by": claim.created_by,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
    }


# ---------------------------------------------------------------------------
# add_claim_note  (Task 8.6)
# Requirements: 7.5, 12.4
# ---------------------------------------------------------------------------


async def add_claim_note(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    claim_id: uuid.UUID,
    notes: str,
    ip_address: str | None = None,
) -> dict:
    """Add an internal note to a claim's timeline.

    Creates a ClaimAction with action_type "note_added" and writes an audit log.

    Requirements: 7.5, 12.4
    """

    # --- Fetch claim scoped to organisation ---
    result = await db.execute(
        select(CustomerClaim)
        .where(
            CustomerClaim.id == claim_id,
            CustomerClaim.org_id == org_id,
        )
        .options(
            selectinload(CustomerClaim.customer),
            selectinload(CustomerClaim.invoice),
            selectinload(CustomerClaim.job_card),
            selectinload(CustomerClaim.actions).selectinload(
                ClaimAction.performed_by_user
            ),
        )
    )
    claim = result.scalar_one_or_none()
    if claim is None:
        raise ValueError("Claim not found in this organisation")

    # --- Create ClaimAction record with action_type "note_added" ---
    now = datetime.now(timezone.utc)
    action = ClaimAction(
        org_id=org_id,
        claim_id=claim.id,
        action_type="note_added",
        from_status=claim.status,
        to_status=claim.status,
        action_data={},
        notes=notes,
        performed_by=user_id,
        performed_at=now,
    )
    db.add(action)
    claim.updated_at = now
    await db.flush()

    # --- Write audit log entry (Req 12.4) ---
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="claim.note_added",
        entity_type="claim",
        entity_id=claim.id,
        before_value=None,
        after_value={"notes": notes[:200]},
        ip_address=ip_address,
    )

    # --- Return full claim detail (reuse get_claim) ---
    return await get_claim(db, org_id=org_id, claim_id=claim_id)
