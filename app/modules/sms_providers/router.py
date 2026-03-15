"""Router for SMS Verification Providers admin endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.sms_providers.schemas import (
    SmsProviderCredentialsRequest,
    SmsProviderCredentialsResponse,
    SmsProviderListResponse,
    SmsProviderTestRequest,
    SmsProviderTestResponse,
    SmsProviderUpdateRequest,
    SmsProviderUpdateResponse,
)
from app.modules.sms_providers.service import (
    get_provider_credentials,
    list_sms_providers,
    save_provider_credentials,
    update_sms_provider,
)

router = APIRouter()


@router.get(
    "",
    response_model=SmsProviderListResponse,
    summary="List all SMS verification providers",
    dependencies=[require_role("global_admin")],
)
async def get_providers(db: AsyncSession = Depends(get_db_session)):
    """List all SMS verification providers with fallback chain."""
    data = await list_sms_providers(db)
    return SmsProviderListResponse(**data)


@router.patch(
    "/{provider_key}",
    response_model=SmsProviderUpdateResponse,
    summary="Update an SMS provider",
    dependencies=[require_role("global_admin")],
)
async def patch_provider(
    provider_key: str,
    payload: SmsProviderUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update provider settings (active, default, priority, config)."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    result = await update_sms_provider(
        db,
        provider_key=provider_key,
        is_active=payload.is_active,
        is_default=payload.is_default,
        priority=payload.priority,
        config=payload.config,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip_address,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})

    return SmsProviderUpdateResponse(
        message=f"Provider '{provider_key}' updated",
        provider=result,
    )


@router.put(
    "/{provider_key}/credentials",
    response_model=SmsProviderCredentialsResponse,
    summary="Save provider credentials",
    dependencies=[require_role("global_admin")],
)
async def put_credentials(
    provider_key: str,
    payload: SmsProviderCredentialsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Save encrypted credentials for an SMS provider."""
    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    try:
        result = await save_provider_credentials(
            db,
            provider_key=provider_key,
            credentials=payload.credentials,
            admin_user_id=uuid.UUID(user_id) if user_id else None,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Provider not found"})

    return SmsProviderCredentialsResponse(
        message=f"Credentials saved for '{provider_key}'",
        credentials_set=True,
    )


@router.get(
    "/{provider_key}/credentials",
    summary="Get saved credentials (masked)",
    dependencies=[require_role("global_admin")],
)
async def get_credentials(
    provider_key: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Return saved credentials with sensitive values masked."""
    creds = await get_provider_credentials(db, provider_key)
    if creds is None:
        return {"credentials": {}, "credentials_set": False}

    # Mask sensitive values — show first 4 chars + asterisks
    masked = {}
    for key, val in creds.items():
        val_str = str(val)
        if len(val_str) <= 4:
            masked[key] = val_str
        else:
            masked[key] = val_str[:4] + "•" * min(len(val_str) - 4, 12)
    return {"credentials": masked, "credentials_set": True}


@router.post(
    "/{provider_key}/test",
    response_model=SmsProviderTestResponse,
    summary="Send a test SMS via provider",
    dependencies=[require_role("global_admin")],
)
async def test_provider(
    provider_key: str,
    payload: SmsProviderTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a test SMS message to verify provider configuration."""
    from app.modules.sms_providers.service import test_sms_provider

    user_id = getattr(request.state, "user_id", None)
    ip_address = request.client.host if request.client else None

    result = await test_sms_provider(
        db,
        provider_key=provider_key,
        to_number=payload.to_number,
        message=payload.message,
        admin_user_id=uuid.UUID(user_id) if user_id else None,
        ip_address=ip_address,
    )
    return SmsProviderTestResponse(**result)
