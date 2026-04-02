"""Pydantic schemas for Customer Claims & Returns module.

Requirements: 1.1, 1.5, 2.1, 3.1, 5.5, 7.1, 7.2, 9.2
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.claims.models import ClaimStatus, ClaimType, ResolutionType


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ClaimCreateRequest(BaseModel):
    """Request body for POST /api/claims.

    Requirements: 1.1, 1.2, 1.5, 1.6
    """

    customer_id: uuid.UUID = Field(..., description="Customer who raised the claim")
    claim_type: ClaimType = Field(..., description="Type of claim")
    description: str = Field(..., min_length=1, max_length=5000, description="Complaint details")
    invoice_id: uuid.UUID | None = Field(default=None, description="Linked invoice")
    job_card_id: uuid.UUID | None = Field(default=None, description="Linked job card")
    line_item_ids: list[uuid.UUID] | None = Field(default=None, description="Specific line items from invoice")
    branch_id: uuid.UUID | None = Field(default=None, description="Branch scope")


class ClaimStatusUpdateRequest(BaseModel):
    """Request body for PATCH /api/claims/{id}/status.

    Requirements: 2.1
    """

    new_status: ClaimStatus = Field(..., description="Target status")
    notes: str | None = Field(default=None, max_length=5000, description="Optional notes for the transition")


class ClaimResolveRequest(BaseModel):
    """Request body for POST /api/claims/{id}/resolve.

    Requirements: 3.1
    """

    resolution_type: ResolutionType = Field(..., description="How the claim is being resolved")
    resolution_amount: Decimal | None = Field(default=None, ge=0, description="Amount for partial_refund or credit_note")
    resolution_notes: str | None = Field(default=None, max_length=5000, description="Resolution notes")
    return_stock_item_ids: list[uuid.UUID] | None = Field(default=None, description="Stock items being returned (exchange)")


class ClaimNoteRequest(BaseModel):
    """Request body for POST /api/claims/{id}/notes.

    Requirements: 7.5
    """

    notes: str = Field(..., min_length=1, max_length=5000, description="Internal note text")


# ---------------------------------------------------------------------------
# Nested / embedded schemas
# ---------------------------------------------------------------------------


class ClaimCustomerSummary(BaseModel):
    """Embedded customer info in claim response."""

    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    company_name: str | None = None


class ClaimInvoiceSummary(BaseModel):
    """Embedded invoice info in claim response."""

    id: uuid.UUID
    invoice_number: str | None = None
    total: Decimal | None = None
    status: str | None = None


class ClaimJobCardSummary(BaseModel):
    """Embedded job card info in claim response."""

    id: uuid.UUID
    description: str | None = None
    status: str | None = None
    vehicle_rego: str | None = None


class CostBreakdownSchema(BaseModel):
    """Cost breakdown for a claim.

    Requirements: 5.5
    """

    labour_cost: Decimal = Field(default=Decimal("0"), description="Labour cost from warranty redo")
    parts_cost: Decimal = Field(default=Decimal("0"), description="Parts cost from warranty repair")
    write_off_cost: Decimal = Field(default=Decimal("0"), description="Write-off cost for unreturnable items")


class ClaimActionResponse(BaseModel):
    """Single timeline action entry.

    Requirements: 7.2
    """

    id: uuid.UUID
    action_type: str
    from_status: str | None = None
    to_status: str | None = None
    action_data: dict = Field(default_factory=dict)
    notes: str | None = None
    performed_by: uuid.UUID
    performed_by_name: str | None = None
    performed_at: datetime


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ClaimResponse(BaseModel):
    """Full claim detail response.

    Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
    """

    id: uuid.UUID
    org_id: uuid.UUID
    branch_id: uuid.UUID | None = None
    customer_id: uuid.UUID
    customer: ClaimCustomerSummary | None = None

    # Source references
    invoice_id: uuid.UUID | None = None
    invoice: ClaimInvoiceSummary | None = None
    job_card_id: uuid.UUID | None = None
    job_card: ClaimJobCardSummary | None = None
    line_item_ids: list[uuid.UUID] = Field(default_factory=list)

    # Claim details
    claim_type: str
    status: str
    description: str

    # Resolution details
    resolution_type: str | None = None
    resolution_amount: Decimal | None = None
    resolution_notes: str | None = None
    resolved_at: datetime | None = None
    resolved_by: uuid.UUID | None = None

    # Downstream entity references
    refund_id: uuid.UUID | None = None
    credit_note_id: uuid.UUID | None = None
    return_movement_ids: list[uuid.UUID] = Field(default_factory=list)
    warranty_job_id: uuid.UUID | None = None

    # Cost tracking
    cost_to_business: Decimal = Decimal("0")
    cost_breakdown: CostBreakdownSchema = Field(default_factory=CostBreakdownSchema)

    # Audit
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    # Timeline (included in detail view)
    actions: list[ClaimActionResponse] = Field(default_factory=list)


class ClaimListItem(BaseModel):
    """Single claim row in list response (lighter than full detail)."""

    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str | None = None
    claim_type: str
    status: str
    description: str
    cost_to_business: Decimal = Decimal("0")
    branch_id: uuid.UUID | None = None
    created_at: datetime


class ClaimListResponse(BaseModel):
    """Paginated claim list response.

    Requirements: 6.1
    """

    items: list[ClaimListItem] = Field(default_factory=list)
    total: int = 0


class ClaimTimelineResponse(BaseModel):
    """Timeline of all actions for a claim.

    Requirements: 7.2
    """

    claim_id: uuid.UUID
    actions: list[ClaimActionResponse] = Field(default_factory=list)


class CustomerClaimsSummaryResponse(BaseModel):
    """Claims summary for a customer profile.

    Requirements: 9.2
    """

    total_claims: int = 0
    open_claims: int = 0
    total_cost_to_business: Decimal = Decimal("0")
    claims: list[ClaimListItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Report response schemas (Requirements: 10.1-10.6)
# ---------------------------------------------------------------------------


class ClaimsByPeriodItem(BaseModel):
    """Single period row in claims-by-period report."""

    period: str | None = None
    claim_count: int = 0
    total_cost: Decimal = Decimal("0")
    average_resolution_hours: float = 0.0


class ClaimsByPeriodResponse(BaseModel):
    """Claims-by-period report response.

    Requirements: 10.1
    """

    periods: list[ClaimsByPeriodItem] = Field(default_factory=list)


class CostOverheadResponse(BaseModel):
    """Cost overhead report response.

    Requirements: 10.2
    """

    total_refunds: Decimal = Decimal("0")
    total_credit_notes: Decimal = Decimal("0")
    total_write_offs: Decimal = Decimal("0")
    total_labour_cost: Decimal = Decimal("0")


class SupplierQualityItem(BaseModel):
    """Single product row in supplier quality report."""

    product_id: uuid.UUID
    product_name: str
    sku: str | None = None
    return_count: int = 0


class SupplierQualityResponse(BaseModel):
    """Supplier quality report response.

    Requirements: 10.3
    """

    items: list[SupplierQualityItem] = Field(default_factory=list)


class ServiceQualityItem(BaseModel):
    """Single technician row in service quality report."""

    staff_id: uuid.UUID
    staff_name: str
    redo_count: int = 0


class ServiceQualityResponse(BaseModel):
    """Service quality report response.

    Requirements: 10.4
    """

    items: list[ServiceQualityItem] = Field(default_factory=list)
