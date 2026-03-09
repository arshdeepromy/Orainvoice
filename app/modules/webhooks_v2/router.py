"""Outbound webhook management API router.

Endpoints:
- GET    /api/v2/outbound-webhooks              — list webhooks
- POST   /api/v2/outbound-webhooks              — register webhook
- GET    /api/v2/outbound-webhooks/{id}          — get webhook
- PUT    /api/v2/outbound-webhooks/{id}          — update webhook
- DELETE /api/v2/outbound-webhooks/{id}          — delete webhook
- POST   /api/v2/outbound-webhooks/{id}/test     — test webhook
- GET    /api/v2/outbound-webhooks/{id}/deliveries — delivery log

**Validates: Requirement 47 — Webhook Management and Security**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.webhooks_v2.schemas import (
    DeliveryLogResponse,
    WebhookCreate,
    WebhookResponse,
    WebhookTestResponse,
    WebhookUpdate,
)
from app.modules.webhooks_v2.service import WebhookService

router = APIRouter()


def _get_org_id(request: Request) -> UUID:
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


# ------------------------------------------------------------------
# List & Create
# ------------------------------------------------------------------

@router.get("", response_model=list[WebhookResponse], summary="List outbound webhooks", dependencies=[require_role("org_admin")])
async def list_webhooks(request: Request, db: AsyncSession = Depends(get_db_session)):
    org_id = _get_org_id(request)
    svc = WebhookService(db)
    webhooks = await svc.list_for_org(org_id)
    return [WebhookResponse.model_validate(w) for w in webhooks]


@router.post("", response_model=WebhookResponse, status_code=201, summary="Register webhook")
async def create_webhook(
    payload: WebhookCreate, request: Request, db: AsyncSession = Depends(get_db_session),
):
    org_id = _get_org_id(request)
    svc = WebhookService(db)
    webhook = await svc.register(
        org_id,
        target_url=payload.target_url,
        event_types=payload.event_types,
        is_active=payload.is_active,
    )
    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


# ------------------------------------------------------------------
# Get, Update, Delete
# ------------------------------------------------------------------

@router.get("/{webhook_id}", response_model=WebhookResponse, summary="Get webhook")
async def get_webhook(
    webhook_id: UUID, request: Request, db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)
    svc = WebhookService(db)
    webhook = await svc.get(webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return WebhookResponse.model_validate(webhook)


@router.put("/{webhook_id}", response_model=WebhookResponse, summary="Update webhook")
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)
    svc = WebhookService(db)
    webhook = await svc.update(
        webhook_id,
        target_url=payload.target_url,
        event_types=payload.event_types,
        is_active=payload.is_active,
    )
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


@router.delete("/{webhook_id}", status_code=204, summary="Delete webhook")
async def delete_webhook(
    webhook_id: UUID, request: Request, db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)
    svc = WebhookService(db)
    deleted = await svc.delete(webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await db.commit()


# ------------------------------------------------------------------
# Test & Delivery Log
# ------------------------------------------------------------------

@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResponse,
    summary="Test webhook",
)
async def test_webhook(
    webhook_id: UUID, request: Request, db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)
    svc = WebhookService(db)
    result = await svc.test_webhook(webhook_id)
    await db.commit()
    return WebhookTestResponse(**result)


@router.get(
    "/{webhook_id}/deliveries",
    response_model=list[DeliveryLogResponse],
    summary="Get delivery log",
)
async def get_delivery_log(
    webhook_id: UUID,
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db_session),
):
    _get_org_id(request)
    svc = WebhookService(db)
    logs = await svc.get_delivery_log(webhook_id, limit=limit)
    return [DeliveryLogResponse.model_validate(log) for log in logs]
