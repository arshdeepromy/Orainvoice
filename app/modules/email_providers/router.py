"""Router for Email Provider admin endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.email_providers.schemas import (
    EmailProviderActivateResponse,
    EmailProviderCredentialsRequest,
    EmailProviderCredentialsResponse,
    EmailProviderListResponse,
    EmailProviderPriorityRequest,
    EmailProviderPriorityResponse,
    EmailProviderTestRequest,
    EmailProviderTestResponse,
)
from app.modules.email_providers.service import (
    activate_email_provider,
    deactivate_email_provider,
    list_email_providers,
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
