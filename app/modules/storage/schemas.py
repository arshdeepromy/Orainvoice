"""Pydantic schemas for the Storage module.

Requirements: 29.1, 29.2, 29.3, 29.4, 29.5
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

AlertLevel = Literal["none", "amber", "red", "blocked"]


class StorageUsageResponse(BaseModel):
    """GET /api/v1/storage/usage response.

    Requirements: 29.1, 29.2, 29.3, 29.4
    """

    storage_used_bytes: int = Field(..., description="Total storage used in bytes")
    storage_quota_bytes: int = Field(..., description="Total storage quota in bytes")
    usage_percentage: float = Field(
        ..., description="Usage as a percentage (0.0–100.0+)"
    )
    alert_level: AlertLevel = Field(
        ...,
        description=(
            "none (<80%), amber (80–89%), red (90–99%), blocked (>=100%)"
        ),
    )
    can_create_invoice: bool = Field(
        ..., description="Whether new invoices can be created"
    )
    storage_used_display: str = Field(
        ..., description="Human-readable storage used (e.g. '1.23 GB')"
    )
    storage_quota_display: str = Field(
        ..., description="Human-readable storage quota (e.g. '5.00 GB')"
    )

# ---------------------------------------------------------------------------
# Storage add-on purchase schemas — Requirements: 30.1, 30.2, 30.3, 30.4
# ---------------------------------------------------------------------------


class StoragePurchaseRequest(BaseModel):
    """POST /api/v1/billing/storage/purchase request body.

    Requirements: 30.1
    """

    quantity_gb: int = Field(
        ...,
        gt=0,
        description="Number of GB to purchase (must match a Global_Admin-configured increment)",
    )


class StoragePurchaseConfirmation(BaseModel):
    """Confirmation details shown before purchase is finalised.

    Requirements: 30.2
    """

    quantity_gb: int = Field(..., description="GB being purchased")
    price_per_gb_nzd: float = Field(..., description="Price per GB in NZD")
    additional_monthly_charge_nzd: float = Field(
        ..., description="Additional monthly charge in NZD"
    )
    new_total_quota_gb: int = Field(..., description="New total storage quota in GB")
    stripe_charge_amount_cents: int = Field(
        ..., description="Immediate Stripe charge amount in cents (NZD)"
    )


class StoragePurchaseResponse(BaseModel):
    """POST /api/v1/billing/storage/purchase response.

    Requirements: 30.3, 30.4
    """

    success: bool = Field(..., description="Whether the purchase succeeded")
    quantity_gb: int = Field(..., description="GB purchased")
    new_total_quota_gb: int = Field(..., description="New total storage quota in GB")
    charge_amount_nzd: float = Field(..., description="Amount charged in NZD")
    stripe_charge_id: str = Field(..., description="Stripe charge/payment intent ID")
    message: str = Field(..., description="Confirmation message")
