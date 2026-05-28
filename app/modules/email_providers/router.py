"""Router for Email Provider admin endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.request_utils import extract_request_base_url
from app.modules.auth.rbac import require_role
from app.modules.email_providers.schemas import (
    ClearBounceResponse,
    DeliveryHealthResponse,
    EmailProviderActivateResponse,
    EmailProviderCredentialsRequest,
    EmailProviderCredentialsResponse,
    EmailProviderListResponse,
    EmailProviderPriorityRequest,
    EmailProviderPriorityResponse,
    EmailProviderTestRequest,
    EmailProviderTestResponse,
    WebhookConfigResponse,
    WebhookTokenRegenerateResponse,
)
from app.modules.email_providers.service import (
    activate_email_provider,
    clear_bounced_address,
    deactivate_email_provider,
    get_delivery_health,
    get_webhook_config,
    list_email_providers,
    regenerate_webhook_token,
    save_email_credentials,
    test_email_provider,
    update_email_provider_priority,
)

router = APIRouter()


@router.get(
    "",
    response_model=EmailProviderListResponse,
    summary="List all email providers",
    dependencies=[require_role("global_admin")],
)
async def get_providers(db: AsyncSession = Depends(get_db_session)):
    data = await list_email_providers(db)
    return EmailProviderListResponse(**data)


@router.post(
    "/{provider_key}/activate",
    response_model=EmailProviderActivateResponse,
    summary="Set a provider as active",
    dependencies=[require_role("global_admin")],
)
async def post_activate(
    provider_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    user_id = getattr(request.state, "user_id", None)
    ip = getattr(request.state, "client_ip", None)
    result = await activate_email_provider(
        db, provider_key=provider_key,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})
    return EmailProviderActivateResponse(
        message=f"'{provider_key}' is now the active email provider", provider=result,
    )


@router.post(
    "/{provider_key}/deactivate",
    response_model=EmailProviderActivateResponse,
    summary="Deactivate a provider",
    dependencies=[require_role("global_admin")],
)
async def post_deactivate(
    provider_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    user_id = getattr(request.state, "user_id", None)
    ip = getattr(request.state, "client_ip", None)
    result = await deactivate_email_provider(
        db, provider_key=provider_key,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})
    return EmailProviderActivateResponse(
        message=f"'{provider_key}' deactivated", provider=result,
    )


@router.put(
    "/{provider_key}/credentials",
    response_model=EmailProviderCredentialsResponse,
    summary="Save provider credentials",
    dependencies=[require_role("global_admin")],
)
async def put_credentials(
    provider_key: str,
    payload: EmailProviderCredentialsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    user_id = getattr(request.state, "user_id", None)
    ip = getattr(request.state, "client_ip", None)
    result = await save_email_credentials(
        db,
        provider_key=provider_key,
        credentials=payload.credentials,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_encryption=payload.smtp_encryption,
        from_email=payload.from_email,
        from_name=payload.from_name,
        reply_to=payload.reply_to,
        webhook_secret=payload.webhook_secret,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})
    return EmailProviderCredentialsResponse(
        message=f"Credentials saved for '{provider_key}'", credentials_set=True,
    )


@router.post(
    "/{provider_key}/test",
    response_model=EmailProviderTestResponse,
    summary="Send a test email",
    dependencies=[require_role("global_admin")],
)
async def post_test(
    provider_key: str,
    request: Request,
    payload: EmailProviderTestRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a test email using the specified provider."""
    user_id = getattr(request.state, "user_id", None)
    user_email = getattr(request.state, "email", None)
    ip = getattr(request.state, "client_ip", None)
    
    # Use provided email or fall back to admin's email
    to_email = payload.to_email if payload else user_email
    
    result = await test_email_provider(
        db,
        provider_key=provider_key,
        to_email=to_email,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    return EmailProviderTestResponse(**result)


@router.put(
    "/{provider_key}/priority",
    response_model=EmailProviderPriorityResponse,
    summary="Update provider priority",
    dependencies=[require_role("global_admin")],
)
async def put_priority(
    provider_key: str,
    payload: EmailProviderPriorityRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update the priority of an email provider (lower = higher priority)."""
    user_id = getattr(request.state, "user_id", None)
    ip = getattr(request.state, "client_ip", None)
    
    result = await update_email_provider_priority(
        db,
        provider_key=provider_key,
        priority=payload.priority,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})
    return EmailProviderPriorityResponse(
        message=f"Priority updated for '{provider_key}'",
        priority=result,
    )


# ---------------------------------------------------------------------------
# Webhook token management (replaces the legacy HMAC webhook_secret flow)
# ---------------------------------------------------------------------------


@router.post(
    "/{provider_key}/webhook-token/regenerate",
    response_model=WebhookTokenRegenerateResponse,
    summary="Generate a new webhook auth token",
    dependencies=[require_role("global_admin")],
)
async def post_regenerate_webhook_token(
    provider_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a fresh webhook token for a provider.

    The plaintext token is returned ONLY in this response. The admin
    must copy it and paste it into the provider's webhook UI under
    "Token Authentication" with header name X-OraInvoice-Webhook-Token.
    Subsequent reads of the provider config redact the token to "***".
    """
    user_id = getattr(request.state, "user_id", None)
    ip = getattr(request.state, "client_ip", None)
    result = await regenerate_webhook_token(
        db,
        provider_key=provider_key,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})
    return WebhookTokenRegenerateResponse(**result)


@router.get(
    "/{provider_key}/webhook-config",
    response_model=WebhookConfigResponse,
    summary="Get webhook configuration for a provider",
    dependencies=[require_role("global_admin")],
)
async def get_webhook_config_endpoint(
    provider_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the webhook URL, required header name, and token status.

    Never returns the token plaintext — use the regenerate endpoint
    to mint a new one.
    """
    from app.config import settings as app_settings

    base_url = extract_request_base_url(request) or getattr(app_settings, "frontend_base_url", "") or "http://localhost"
    result = await get_webhook_config(
        db,
        provider_key=provider_key,
        base_url=base_url,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})
    return WebhookConfigResponse(**result)


# ---------------------------------------------------------------------------
# Delivery Health (Phase 8c, task 9.9)
# ---------------------------------------------------------------------------


@router.get(
    "/delivery-health",
    response_model=DeliveryHealthResponse,
    summary="Aggregate bounce stats and recent bounce rows",
    dependencies=[require_role("global_admin", "org_admin")],
)
async def get_delivery_health_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(
        100, ge=1, le=500, description="Max rows to return (1-500)"
    ),
):
    """Return aggregate bounce stats + the recent bounce rows table.

    Pagination is ``offset`` / ``limit`` per the v2 API convention; the
    legacy ``skip`` parameter is intentionally rejected (FastAPI strips
    it because it isn't declared). Both ``global_admin`` and
    ``org_admin`` roles are admitted (Req 18.5); RLS scopes the rows
    visible to ``org_admin`` to their own org plus the platform-wide
    rows (``org_id IS NULL``).
    """
    org_id_raw = getattr(request.state, "org_id", None)
    org_uuid: uuid.UUID | None
    try:
        org_uuid = uuid.UUID(org_id_raw) if org_id_raw else None
    except (ValueError, TypeError):
        org_uuid = None

    role = getattr(request.state, "role", None)
    data = await get_delivery_health(
        db,
        org_id=None if role == "global_admin" else org_uuid,
        offset=offset,
        limit=limit,
    )
    return DeliveryHealthResponse(**data)


@router.delete(
    "/bounced-addresses/{bounce_id}",
    response_model=ClearBounceResponse,
    summary="Clear a bounce row",
    dependencies=[require_role("global_admin", "org_admin")],
)
async def delete_bounced_address(
    bounce_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a single ``bounced_addresses`` row.

    After this returns 200, the next outbound to that address will be
    attempted normally (the pre-send blocklist check no longer matches).
    Same role gate as the GET — both ``global_admin`` and ``org_admin``.
    """
    try:
        bid = uuid.UUID(bounce_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid bounce id"},
        )
    user_id = getattr(request.state, "user_id", None)
    ip = getattr(request.state, "client_ip", None)
    cleared = await clear_bounced_address(
        db,
        bounce_id=bid,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip,
    )
    if not cleared:
        return JSONResponse(
            status_code=404,
            content={"detail": "Bounce row not found"},
        )
    return ClearBounceResponse(
        message="Bounce cleared", cleared=True,
    )
