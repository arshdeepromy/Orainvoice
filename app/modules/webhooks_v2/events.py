"""Webhook event type constants and integration points.

Documents all supported webhook event types and provides convenience
functions for dispatching events from various modules.

Supported events:
- invoice.created   — when a new invoice is created
- invoice.paid      — when an invoice is fully paid
- customer.created  — when a new customer is created
- job.status_changed — when a job status changes
- booking.created   — when a new booking is created
- payment.received  — when a payment is recorded
- stock.low         — when stock falls below threshold

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.webhooks_v2.dispatch import dispatch_webhook_event

# Event type constants
INVOICE_CREATED = "invoice.created"
INVOICE_PAID = "invoice.paid"
CUSTOMER_CREATED = "customer.created"
JOB_STATUS_CHANGED = "job.status_changed"
BOOKING_CREATED = "booking.created"
PAYMENT_RECEIVED = "payment.received"
STOCK_LOW = "stock.low"

ALL_EVENT_TYPES = [
    INVOICE_CREATED,
    INVOICE_PAID,
    CUSTOMER_CREATED,
    JOB_STATUS_CHANGED,
    BOOKING_CREATED,
    PAYMENT_RECEIVED,
    STOCK_LOW,
]


async def on_invoice_created(
    db: AsyncSession, org_id: uuid.UUID, invoice_id: uuid.UUID, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, INVOICE_CREATED, {
        "invoice_id": str(invoice_id), **{k: str(v) for k, v in extra.items()},
    })


async def on_invoice_paid(
    db: AsyncSession, org_id: uuid.UUID, invoice_id: uuid.UUID, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, INVOICE_PAID, {
        "invoice_id": str(invoice_id), **{k: str(v) for k, v in extra.items()},
    })


async def on_customer_created(
    db: AsyncSession, org_id: uuid.UUID, customer_id: uuid.UUID, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, CUSTOMER_CREATED, {
        "customer_id": str(customer_id), **{k: str(v) for k, v in extra.items()},
    })


async def on_job_status_changed(
    db: AsyncSession, org_id: uuid.UUID, job_id: uuid.UUID,
    old_status: str, new_status: str, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, JOB_STATUS_CHANGED, {
        "job_id": str(job_id), "old_status": old_status, "new_status": new_status,
        **{k: str(v) for k, v in extra.items()},
    })


async def on_booking_created(
    db: AsyncSession, org_id: uuid.UUID, booking_id: uuid.UUID, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, BOOKING_CREATED, {
        "booking_id": str(booking_id), **{k: str(v) for k, v in extra.items()},
    })


async def on_payment_received(
    db: AsyncSession, org_id: uuid.UUID, payment_id: uuid.UUID, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, PAYMENT_RECEIVED, {
        "payment_id": str(payment_id), **{k: str(v) for k, v in extra.items()},
    })


async def on_stock_low(
    db: AsyncSession, org_id: uuid.UUID, product_id: uuid.UUID,
    current_quantity: str, threshold: str, **extra: object,
) -> list[str]:
    return await dispatch_webhook_event(db, org_id, STOCK_LOW, {
        "product_id": str(product_id),
        "current_quantity": current_quantity,
        "threshold": threshold,
        **{k: str(v) for k, v in extra.items()},
    })
