"""Router for global admin platform settings (Xero credentials, etc.).

Mounted at /api/v1/admin/platform-settings in main.py.
All endpoints require global_admin role.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.platform_settings.service import get_masked, set_setting

router = APIRouter()

# Xero credential keys
_XERO_CLIENT_ID = "XERO_CLIENT_ID"
_XERO_CLIENT_SECRET = "XERO_CLIENT_SECRET"
_XERO_WEBHOOK_KEY = "XERO_WEBHOOK_KEY"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class XeroCredentialsResponse(BaseModel):
    client_id_masked: Optional[str] = None
    client_secret_masked: Optional[str] = None
    webhook_key_masked: Optional[str] = None


class XeroCredentialsRequest(BaseModel):
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    webhook_key: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/xero",
    response_model=XeroCredentialsResponse,
    dependencies=[require_role("global_admin")],
    summary="Get masked Xero credentials",
)
async def get_xero_credentials(
    db: AsyncSession = Depends(get_db_session),
):
    """Return masked Xero credentials (last 4 chars visible)."""
    return XeroCredentialsResponse(
        client_id_masked=await get_masked(db, _XERO_CLIENT_ID),
        client_secret_masked=await get_masked(db, _XERO_CLIENT_SECRET),
        webhook_key_masked=await get_masked(db, _XERO_WEBHOOK_KEY),
    )


@router.post(
    "/xero",
    dependencies=[require_role("global_admin")],
    summary="Save Xero credentials",
)
async def save_xero_credentials(
    payload: XeroCredentialsRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Encrypt and store each non-null Xero credential field."""
    if payload.client_id is not None:
        await set_setting(db, _XERO_CLIENT_ID, payload.client_id)
    if payload.client_secret is not None:
        await set_setting(db, _XERO_CLIENT_SECRET, payload.client_secret)
    if payload.webhook_key is not None:
        await set_setting(db, _XERO_WEBHOOK_KEY, payload.webhook_key)

    return {"message": "Xero credentials saved"}


@router.post(
    "/xero/test",
    dependencies=[require_role("global_admin")],
    summary="Test Xero API credentials",
)
async def test_xero_credentials(
    db: AsyncSession = Depends(get_db_session),
):
    """Verify the stored Xero Client ID and Secret are valid.

    Attempts a token endpoint call with client_credentials to check
    that the credentials are accepted by Xero. Returns success/failure.
    """
    import httpx
    from app.modules.platform_settings.service import get_setting

    client_id = await get_setting(db, _XERO_CLIENT_ID)
    client_secret = await get_setting(db, _XERO_CLIENT_SECRET)

    if not client_id or not client_secret:
        return {"success": False, "message": "Client ID or Client Secret not configured"}

    # Validate by attempting to hit the Xero identity endpoint.
    # We use the token endpoint with an invalid grant to confirm the
    # credentials are recognized (Xero returns 400 "invalid_grant"
    # for valid credentials vs 401 "invalid_client" for bad ones).
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://identity.xero.com/connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            # Xero doesn't support client_credentials grant for web apps,
            # so we expect a 400 with "unsupported_grant_type" or "invalid_grant"
            # — both mean the credentials were accepted.
            # A 401 means invalid_client (bad credentials).
            if resp.status_code == 401:
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                error = body.get("error", "unknown")
                return {"success": False, "message": f"Invalid credentials: {error}"}

            if resp.status_code in (200, 400):
                return {"success": True, "message": "Xero credentials are valid"}

            return {"success": False, "message": f"Unexpected response from Xero: HTTP {resp.status_code}"}

    except httpx.ConnectError:
        return {"success": False, "message": "Could not connect to Xero API — check network"}
    except httpx.TimeoutException:
        return {"success": False, "message": "Connection to Xero timed out"}
    except Exception as exc:
        return {"success": False, "message": f"Test failed: {str(exc)[:200]}"}
