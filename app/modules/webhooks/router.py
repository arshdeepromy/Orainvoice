"""API router for outbound webhook management.

Endpoints:
  GET    /api/v1/webhooks                        — list webhooks
  POST   /api/v1/webhooks                        — register webhook URL
  PUT    /api/v1/webhooks/{webhook_id}            — update webhook
  DELETE /api/v1/webhooks/{webhook_id}            — remove webhook
  GET    /api/v1/webhooks/{webhook_id}/deliveries — delivery log

Requirements: 70.1, 70.2, 70.3, 70.4
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.webhooks.schemas import (
    WEBHOOK_EVENT_TYPES,
    WebhookCreate,
    WebhookDeliveryListResponse,
    WebhookDeliveryResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookUpdate,
)
from app.modules.webhooks.service import (
    create_webhook,
    delete_webhook,
    list_deliveries,
    list_webhooks,
    update_webhook,
)

router = APIRouter()


def _extract_org_context(
    request: Request,
) -> tuple[uuid.UUID | None, str | None]:
    """Extract org_id and role from request state."""
    org_id = getattr(request.state, "org_id", None)
    role = getattr(request.state, "role", None)
    try:
        org_uuid = uuid.UUID(org_id) if org_id else None
    except (ValueError, TypeError):
        return None, role
    return org_uuid, role


@router.get("", response_model=WebhookListResponse)
async def list_webhooks_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List all configured webhooks for the organisation.

    Org_Admin only.
    Requirements: 70.1
    """
    org_uuid, role = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage webhooks"},
        )

    result = await list_webhooks(db, org_id=org_uuid)
    return WebhookListResponse(
        webhooks=[WebhookResponse(**w) for w in result["webhooks"]],
        total=result["total"],
    )


@router.post("", response_model=WebhookResponse, status_code=201)
async def create_webhook_endpoint(
    body: WebhookCreate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Register a new webhook URL for an event type.

    Org_Admin only.
    Requirements: 70.1
    """
    org_uuid, role = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage webhooks"},
        )

    if body.event_type not in WEBHOOK_EVENT_TYPES:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Invalid event type: {body.event_type}. "
                f"Must be one of: {', '.join(WEBHOOK_EVENT_TYPES)}"
            },
        )

    result = await create_webhook(
        db,
        org_id=org_uuid,
        event_type=body.event_type,
        url=body.url,
        secret=body.secret,
        is_active=body.is_active,
    )

    if isinstance(result, str):
        return JSONResponse(status_code=400, content={"detail": result})

    return WebhookResponse(**result)


@router.put("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook_endpoint(
    webhook_id: str,
    body: WebhookUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update an existing webhook configuration.

    Org_Admin only.
    Requirements: 70.1
    """
    org_uuid, role = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage webhooks"},
        )

    try:
        wh_uuid = uuid.UUID(webhook_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid webhook ID"}
        )

    if body.event_type is not None and body.event_type not in WEBHOOK_EVENT_TYPES:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Invalid event type: {body.event_type}. "
                f"Must be one of: {', '.join(WEBHOOK_EVENT_TYPES)}"
            },
        )

    result = await update_webhook(
        db,
        org_id=org_uuid,
        webhook_id=wh_uuid,
        event_type=body.event_type,
        url=body.url,
        secret=body.secret,
        is_active=body.is_active,
    )

    if result is None:
        return JSONResponse(
            status_code=404, content={"detail": "Webhook not found"}
        )
    if isinstance(result, str):
        return JSONResponse(status_code=400, content={"detail": result})

    return WebhookResponse(**result)


@router.delete("/{webhook_id}")
async def delete_webhook_endpoint(
    webhook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a webhook registration.

    Org_Admin only.
    Requirements: 70.1
    """
    org_uuid, role = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage webhooks"},
        )

    try:
        wh_uuid = uuid.UUID(webhook_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid webhook ID"}
        )

    deleted = await delete_webhook(db, org_id=org_uuid, webhook_id=wh_uuid)
    if not deleted:
        return JSONResponse(
            status_code=404, content={"detail": "Webhook not found"}
        )

    return JSONResponse(content={"message": "Webhook deleted"})


@router.get(
    "/{webhook_id}/deliveries",
    response_model=WebhookDeliveryListResponse,
)
async def list_deliveries_endpoint(
    webhook_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """List delivery attempts for a specific webhook.

    Org_Admin only.
    Requirements: 70.4
    """
    org_uuid, role = _extract_org_context(request)
    if not org_uuid:
        return JSONResponse(
            status_code=403,
            content={"detail": "Organisation context required"},
        )
    if role not in ("org_admin", "global_admin"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can manage webhooks"},
        )

    try:
        wh_uuid = uuid.UUID(webhook_id)
    except ValueError:
        return JSONResponse(
            status_code=400, content={"detail": "Invalid webhook ID"}
        )

    result = await list_deliveries(db, org_id=org_uuid, webhook_id=wh_uuid)
    if result is None:
        return JSONResponse(
            status_code=404, content={"detail": "Webhook not found"}
        )

    return WebhookDeliveryListResponse(
        deliveries=[
            WebhookDeliveryResponse(**d) for d in result["deliveries"]
        ],
        total=result["total"],
    )
