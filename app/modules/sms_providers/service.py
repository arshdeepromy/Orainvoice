"""Business logic for SMS Verification Providers."""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.admin.models import SmsVerificationProvider

logger = logging.getLogger(__name__)


async def list_sms_providers(db: AsyncSession) -> dict:
    """Return all SMS providers and the computed fallback chain."""
    result = await db.execute(
        select(SmsVerificationProvider).order_by(SmsVerificationProvider.priority)
    )
    providers = result.scalars().all()

    provider_list = []
    chain = []
    for p in providers:
        provider_list.append(_provider_to_dict(p))
        if p.is_active:
            chain.append({
                "provider_key": p.provider_key,
                "display_name": p.display_name,
                "priority": p.priority,
            })

    # Default provider goes first in chain, then remaining by priority
    chain.sort(key=lambda x: (0 if any(
        p.is_default and p.provider_key == x["provider_key"] for p in providers
    ) else 1, x["priority"]))

    return {"providers": provider_list, "fallback_chain": chain}


async def update_sms_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    is_active: bool | None = None,
    is_default: bool | None = None,
    priority: int | None = None,
    config: dict | None = None,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Update an SMS provider's settings."""
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == provider_key
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    before = _provider_to_dict(provider)

    if is_active is not None:
        provider.is_active = is_active
        # If deactivating the default, unset default
        if not is_active and provider.is_default:
            provider.is_default = False

    if is_default is not None and is_default:
        # Clear existing default first
        await db.execute(
            update(SmsVerificationProvider).values(is_default=False)
        )
        provider.is_default = True
        # Activating as default also activates the provider
        if not provider.is_active:
            provider.is_active = True

    if priority is not None:
        provider.priority = priority

    if config is not None:
        provider.config = config

    await db.flush()
    await db.refresh(provider)

    after = _provider_to_dict(provider)

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.sms_provider_updated",
        entity_type="sms_verification_provider",
        entity_id=provider.id,
        before_value=before,
        after_value=after,
        ip_address=ip_address,
    )

    return after


async def save_provider_credentials(
    db: AsyncSession,
    *,
    provider_key: str,
    credentials: dict,
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict | None:
    """Save encrypted credentials for a provider."""
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == provider_key
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        return None

    encrypted = envelope_encrypt(json.dumps(credentials))
    provider.credentials_encrypted = encrypted
    provider.credentials_set = True
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=admin_user_id,
        action="admin.sms_provider_credentials_saved",
        entity_type="sms_verification_provider",
        entity_id=provider.id,
        after_value={"provider_key": provider_key, "credentials_set": True},
        ip_address=ip_address,
    )

    return {"credentials_set": True}


async def get_provider_credentials(
    db: AsyncSession, provider_key: str
) -> dict | None:
    """Decrypt and return credentials for a provider (internal use)."""
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.provider_key == provider_key
        )
    )
    provider = result.scalar_one_or_none()
    if provider is None or not provider.credentials_set or provider.credentials_encrypted is None:
        return None
    return json.loads(envelope_decrypt_str(provider.credentials_encrypted))


def _provider_to_dict(p: SmsVerificationProvider) -> dict:
    """Convert a provider ORM instance to a serialisable dict."""
    return {
        "id": str(p.id),
        "provider_key": p.provider_key,
        "display_name": p.display_name,
        "description": p.description,
        "icon": p.icon,
        "is_active": p.is_active,
        "is_default": p.is_default,
        "priority": p.priority,
        "credentials_set": p.credentials_set,
        "config": p.config or {},
        "setup_guide": p.setup_guide,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


async def test_sms_provider(
    db: AsyncSession,
    *,
    provider_key: str,
    to_number: str,
    message: str = "Hello from OraInvoice! This is a test SMS.",
    admin_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Send a test SMS to verify provider configuration."""
    creds = await get_provider_credentials(db, provider_key)
    if creds is None:
        return {
            "success": False,
            "message": "No credentials configured for this provider.",
            "error": "No credentials",
        }

    try:
        if provider_key == "firebase_phone_auth":
            result = await _test_firebase(creds)
        elif provider_key == "connexus":
            result = await _test_connexus(creds, to_number, message)
        else:
            return {
                "success": False,
                "message": f"Test not implemented for provider '{provider_key}'.",
                "error": "Not implemented",
            }
    except Exception as exc:
        logger.exception("SMS test failed for %s: %s", provider_key, exc)
        return {
            "success": False,
            "message": f"Test failed: {exc}",
            "error": str(exc),
        }

    if result["success"]:
        await write_audit_log(
            session=db,
            org_id=None,
            user_id=admin_user_id,
            action="admin.sms_provider_test_success",
            entity_type="sms_verification_provider",
            entity_id=None,
            after_value={"provider_key": provider_key, "to_number": to_number},
            ip_address=ip_address,
        )

    return result




async def _test_firebase(creds: dict) -> dict:
    """Test Firebase credentials by calling the Firebase Installations API."""
    import httpx

    api_key = creds.get("api_key", "")
    project_id = creds.get("project_id", "")
    app_id = creds.get("app_id", "")

    if not api_key or not project_id:
        return {
            "success": False,
            "message": "Firebase credentials incomplete (need project_id and api_key).",
            "error": "Missing credentials",
        }

    # Use the Firebase Installations API to validate the API key + project + app_id.
    # This is a lightweight call that confirms all three values are correct.
    url = f"https://firebaseinstallations.googleapis.com/v1/projects/{project_id}/installations"
    payload = {
        "appId": app_id or "unknown",
        "authVersion": "FIS_v2",
        "sdkVersion": "w:0.6.4",
    }
    headers = {"x-goog-api-key": api_key}

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Connection to Firebase timed out. Check your network.",
            "error": "Timeout",
        }

    if resp.status_code == 200:
        return {
            "success": True,
            "message": f"Firebase connection verified for project '{project_id}'. API key and app ID are valid.",
            "error": None,
        }
    elif resp.status_code == 401 or resp.status_code == 403:
        return {
            "success": False,
            "message": "Firebase API key is invalid or restricted. Check your key in Firebase Console → Project Settings.",
            "error": f"HTTP {resp.status_code}",
        }
    else:
        body = resp.text[:200]
        return {
            "success": False,
            "message": f"Firebase returned status {resp.status_code}: {body}",
            "error": f"HTTP {resp.status_code}",
        }

async def _test_connexus(creds: dict, to_number: str, message: str) -> dict:
    """Test Connexus by checking balance as a connectivity test and optionally sending a test SMS."""
    from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
    from app.integrations.sms_types import SmsMessage

    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    sender_id = creds.get("sender_id", "")

    if not all([client_id, client_secret]):
        return {
            "success": False,
            "message": "Connexus credentials incomplete (need client_id and client_secret).",
            "error": "Missing credentials",
        }

    config = ConnexusConfig.from_dict(creds)
    client = ConnexusSmsClient(config)

    # First, check balance as a connectivity / auth test
    balance_result = await client.check_balance()
    if "error" in balance_result:
        return {
            "success": False,
            "message": f"Connexus connectivity check failed: {balance_result['error']}",
            "error": balance_result["error"],
        }

    # Send a test SMS — sender_id may be empty (uses WebSMS shared shortcode)
    sms = SmsMessage(to_number=to_number, body=message, from_number=sender_id or None)
    send_result = await client.send(sms)

    if send_result.success:
        balance_info = f" (Account balance: {balance_result.get('balance', 'N/A')} {balance_result.get('currency', 'NZD')})"
        return {
            "success": True,
            "message": f"SMS sent to {to_number} via Connexus. Message ID: {send_result.message_sid}{balance_info}",
            "error": None,
        }
    else:
        return {
            "success": False,
            "message": f"Connexus send failed: {send_result.error}",
            "error": send_result.error,
        }







