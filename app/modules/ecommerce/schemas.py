"""Pydantic v2 schemas for the ecommerce module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- WooCommerce ---

class WooCommerceConnectRequest(BaseModel):
    store_url: str = Field(..., max_length=500)
    consumer_key: str
    consumer_secret: str
    sync_frequency_minutes: int = Field(15, ge=15)
    auto_create_invoices: bool = True
    invoice_status_on_import: str = "draft"


class WooCommerceConnectionResponse(BaseModel):
    id: UUID
    org_id: UUID
    store_url: str
    sync_frequency_minutes: int
    auto_create_invoices: bool
    invoice_status_on_import: str
    last_sync_at: datetime | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncTriggerResponse(BaseModel):
    message: str
    sync_log_id: UUID | None = None


# --- Sync log ---

class SyncLogResponse(BaseModel):
    id: UUID
    org_id: UUID
    direction: str
    entity_type: str
    entity_id: str | None = None
    status: str
    error_details: str | None = None
    retry_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SyncLogListResponse(BaseModel):
    logs: list[SyncLogResponse]
    total: int


# --- SKU mappings ---

class SkuMappingCreate(BaseModel):
    external_sku: str = Field(..., max_length=100)
    internal_product_id: UUID | None = None
    platform: str = Field(..., max_length=50)


class SkuMappingResponse(BaseModel):
    id: UUID
    org_id: UUID
    external_sku: str
    internal_product_id: UUID | None = None
    platform: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SkuMappingListResponse(BaseModel):
    mappings: list[SkuMappingResponse]
    total: int


# --- API credentials ---

class ApiCredentialCreate(BaseModel):
    name: str = Field(..., max_length=100)
    scopes: list[str] = Field(default=["read"])
    rate_limit_per_minute: int = Field(100, ge=1, le=10000)


class ApiCredentialResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    scopes: list[str]
    rate_limit_per_minute: int
    is_active: bool
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApiCredentialCreatedResponse(ApiCredentialResponse):
    """Returned only on creation — includes the raw API key (shown once)."""
    api_key: str


class ApiCredentialListResponse(BaseModel):
    credentials: list[ApiCredentialResponse]
    total: int


# --- Webhook ---

class WebhookOrderLineItem(BaseModel):
    sku: str | None = None
    name: str
    quantity: int = 1
    price: float = 0.0


class WebhookOrderPayload(BaseModel):
    order_id: str
    customer_name: str | None = None
    customer_email: str | None = None
    line_items: list[WebhookOrderLineItem] = []
    total: float = 0.0
    currency: str = "NZD"
