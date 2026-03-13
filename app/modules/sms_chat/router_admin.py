"""Admin Connexus integration endpoints.

Provides balance checking and webhook configuration for Global Admins.

Requirements: 11.2, 13.2
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.sms_chat.service import _get_connexus_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/integrations/connexus", tags=["admin"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ConfigureWebhooksRequest(BaseModel):
    """POST /admin/integrations/connexus/configure-webhooks request body."""

    mo_webhook_url: Optional[str] = Field(
        None, description="Incoming SMS (MO) webhook URL. Uses platform default if omitted."
    )
    dlr_webhook_url: Optional[str] = Field(
        None, description="Delivery status (DLR) webhook URL. Uses platform default if omitted."
    )


# ---------------------------------------------------------------------------
# Default platform webhook paths (appended to frontend_base_url)
# ---------------------------------------------------------------------------

_MO_WEBHOOK_PATH = "/api/webhooks/connexus/incoming"
_DLR_WEBHOOK_PATH = "/api/webhooks/connexus/status"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/balance",
    summary="Check Connexus account balance",
    dependencies=[require_role("global_admin")],
)
async def get_balance(
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current Connexus account balance in NZD.

    Requirements: 11.2
    """
    try:
        client = await _get_connexus_client(db)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    result = await client.check_balance()
    if result.get("error"):
        return JSONResponse(status_code=502, content={"detail": result["error"]})

    return result


@router.post(
    "/configure-webhooks",
    summary="Configure Connexus webhook URLs",
    dependencies=[require_role("global_admin")],
)
async def configure_webhooks(
    payload: ConfigureWebhooksRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Configure incoming SMS and delivery status webhook URLs via the Connexus API.

    If URLs are not provided, platform default webhook paths are used.

    Requirements: 13.2
    """
    try:
        client = await _get_connexus_client(db)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    mo_url = payload.mo_webhook_url or f"{settings.frontend_base_url.rstrip('/')}{_MO_WEBHOOK_PATH}"
    dlr_url = payload.dlr_webhook_url or f"{settings.frontend_base_url.rstrip('/')}{_DLR_WEBHOOK_PATH}"

    result = await client.configure_webhooks(mo_url, dlr_url)
    if result.get("error"):
        return JSONResponse(status_code=502, content={"detail": result["error"]})

    return result
