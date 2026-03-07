"""Business logic for Global Admin operations."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.config import settings
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User

logger = logging.getLogger(__name__)

_INVITE_TOKEN_EXPIRY_SECONDS = 48 * 3600  # 48 hours


def _hash_invite_token(token: str) -> str:
    """SHA-256 hash of an invitation token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def provision_organisation(
    db: AsyncSession,
    *,
    name: str,
    plan_id: uuid.UUID,
    admin_email: str,
    status: str = "active",
    provisioned_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Provision a new organisation, assign a plan, and invite an Org_Admin.

    Steps:
    1. Validate the subscription plan exists and is not archived.
    2. Check the admin email is not already registered.
    3. Create the organisation record with the assigned plan.
    4. Create an Org_Admin user record (unverified, no password).
    5. Generate an invitation token and store in Redis (48h TTL).
    6. Queue the invitation email.
    7. Write audit log entries.

    Returns a dict with organisation and invitation details.
    Raises ``ValueError`` on validation failures.
    """
    from app.core.redis import redis_pool

    # 1. Validate plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Subscription plan not found")
    if plan.is_archived:
        raise ValueError("Cannot assign an archived subscription plan")

    # 2. Validate status
    valid_statuses = ("trial", "active")
    if status not in valid_statuses:
        raise ValueError(f"Initial status must be one of: {', '.join(valid_statuses)}")

    # 3. Check admin email uniqueness
    email_result = await db.execute(
        select(User).where(User.email == admin_email)
    )
    if email_result.scalar_one_or_none() is not None:
        raise ValueError("A user with this email already exists")

    # 4. Create organisation
    org = Organisation(
        name=name,
        plan_id=plan_id,
        status=status,
        storage_quota_gb=plan.storage_quota_gb,
    )
    db.add(org)
    await db.flush()  # Get generated org ID

    # 5. Create Org_Admin user
    admin_user = User(
        org_id=org.id,
        email=admin_email,
        role="org_admin",
        is_active=True,
        is_email_verified=False,
        password_hash=None,
    )
    db.add(admin_user)
    await db.flush()  # Get generated user ID

    # 6. Generate invitation token
    invite_token = secrets.token_urlsafe(48)
    token_hash = _hash_invite_token(invite_token)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=_INVITE_TOKEN_EXPIRY_SECONDS)

    token_data = json.dumps({
        "user_id": str(admin_user.id),
        "email": admin_email,
        "org_id": str(org.id),
        "created_at": now.isoformat(),
    })
    await redis_pool.setex(
        f"invite:{token_hash}",
        _INVITE_TOKEN_EXPIRY_SECONDS,
        token_data,
    )

    # 7. Send invitation email
    await _send_org_admin_invitation_email(admin_email, invite_token, name)

    # 8. Audit log — organisation provisioned
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=provisioned_by,
        action="org.provisioned",
        entity_type="organisation",
        entity_id=org.id,
        after_value={
            "name": name,
            "plan_id": str(plan_id),
            "plan_name": plan.name,
            "status": status,
            "admin_email": admin_email,
            "admin_user_id": str(admin_user.id),
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    # 9. Audit log — admin user invited
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=provisioned_by,
        action="auth.user_invited",
        entity_type="user",
        entity_id=admin_user.id,
        after_value={
            "invited_email": admin_email,
            "role": "org_admin",
            "ip_address": ip_address,
            "expires_at": expires_at.isoformat(),
        },
        ip_address=ip_address,
    )

    return {
        "organisation_id": str(org.id),
        "organisation_name": name,
        "plan_id": str(plan_id),
        "admin_user_id": str(admin_user.id),
        "admin_email": admin_email,
        "invitation_expires_at": expires_at,
    }


async def _send_org_admin_invitation_email(
    email: str, token: str, org_name: str
) -> None:
    """Send an Org_Admin invitation email with the secure signup link.

    In production this dispatches via the notification infrastructure
    (Brevo/SendGrid). For now we log the intent.
    """
    logger.info(
        "Org_Admin invitation email queued for %s (org: %s) with token %s...",
        email,
        org_name,
        token[:8],
    )
    # TODO: Replace with Celery task dispatching a real email via
    # app.integrations.brevo once the Notification_Module is implemented.


# ---------------------------------------------------------------------------
# Carjam usage monitoring (Req 16.1, 16.4)
# ---------------------------------------------------------------------------

# Default per-lookup overage cost when not configured in integration_configs
_DEFAULT_CARJAM_PER_LOOKUP_COST_NZD = 0.15


async def get_carjam_per_lookup_cost(db: AsyncSession) -> float:
    """Return the per-lookup overage cost from integration_configs.

    The Carjam integration config may contain a ``per_lookup_cost_nzd``
    field.  Falls back to the default if not configured or not decryptable.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    config = result.scalar_one_or_none()
    if config is None:
        return _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD

    try:
        decrypted = envelope_decrypt_str(config.config_encrypted)
        data = json.loads(decrypted)
        return float(data.get("per_lookup_cost_nzd", _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD))
    except Exception:
        logger.warning("Failed to read Carjam per-lookup cost from integration_configs; using default")
        return _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD


def compute_carjam_overage(total_lookups: int, included: int) -> int:
    """Return the number of overage lookups (clamped to >= 0)."""
    return max(0, total_lookups - included)


async def get_all_orgs_carjam_usage(db: AsyncSession) -> list[dict]:
    """Return Carjam usage data for every non-deleted organisation.

    Each dict contains: organisation_id, organisation_name, total_lookups,
    included_in_plan, overage_count, overage_charge_nzd.

    Requirement 16.1.
    """
    per_lookup_cost = await get_carjam_per_lookup_cost(db)

    stmt = (
        select(Organisation, SubscriptionPlan)
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.status != "deleted")
        .order_by(Organisation.name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    usage_list: list[dict] = []
    for org, plan in rows:
        total = org.carjam_lookups_this_month
        included = plan.carjam_lookups_included
        overage = compute_carjam_overage(total, included)
        usage_list.append({
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "total_lookups": total,
            "included_in_plan": included,
            "overage_count": overage,
            "overage_charge_nzd": round(overage * per_lookup_cost, 2),
        })

    return usage_list, per_lookup_cost


async def get_org_carjam_usage(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Return Carjam usage data for a single organisation.

    Requirement 16.4.
    """
    per_lookup_cost = await get_carjam_per_lookup_cost(db)

    stmt = (
        select(Organisation, SubscriptionPlan)
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        raise ValueError("Organisation not found")

    org, plan = row
    total = org.carjam_lookups_this_month
    included = plan.carjam_lookups_included
    overage = compute_carjam_overage(total, included)

    return {
        "organisation_id": str(org.id),
        "organisation_name": org.name,
        "total_lookups": total,
        "included_in_plan": included,
        "overage_count": overage,
        "overage_charge_nzd": round(overage * per_lookup_cost, 2),
        "per_lookup_cost_nzd": per_lookup_cost,
    }


# ---------------------------------------------------------------------------
# SMTP / Email integration configuration (Req 33.1, 33.2, 33.3)
# ---------------------------------------------------------------------------


async def save_smtp_config(
    db: AsyncSession,
    *,
    provider: str,
    api_key: str,
    host: str,
    port: int,
    username: str,
    password: str,
    domain: str,
    from_email: str,
    from_name: str,
    reply_to: str,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Save or update the platform-wide SMTP configuration.

    The config is stored encrypted in the ``integration_configs`` table
    with name='smtp'.

    Returns a dict with the saved (non-secret) config fields.
    Requirement 33.1.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_encrypt

    valid_providers = ("brevo", "sendgrid", "smtp")
    if provider not in valid_providers:
        raise ValueError(f"Provider must be one of: {', '.join(valid_providers)}")

    config_data = json.dumps({
        "provider": provider,
        "api_key": api_key,
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "domain": domain,
        "from_email": from_email,
        "from_name": from_name,
        "reply_to": reply_to,
    })
    encrypted = envelope_encrypt(config_data)

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "smtp")
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.config_encrypted = encrypted
        existing.is_verified = False
    else:
        new_config = IntegrationConfig(
            name="smtp",
            config_encrypted=encrypted,
            is_verified=False,
        )
        db.add(new_config)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=updated_by,
        action="admin.smtp_config_updated",
        entity_type="integration_config",
        entity_id=None,
        after_value={
            "provider": provider,
            "domain": domain,
            "from_email": from_email,
            "from_name": from_name,
            "reply_to": reply_to,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return {
        "provider": provider,
        "domain": domain,
        "from_email": from_email,
        "from_name": from_name,
        "reply_to": reply_to,
        "is_verified": False,
    }


async def send_test_email(
    db: AsyncSession,
    *,
    admin_email: str,
    admin_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Send a test email to the Global_Admin to verify SMTP config.

    Requirement 33.2.
    """
    from app.integrations.brevo import get_email_client, EmailMessage

    client = await get_email_client(db)
    if client is None:
        return {
            "success": False,
            "message": "SMTP configuration not found. Please configure email settings first.",
            "provider": "",
            "error": "No SMTP config",
        }

    message = EmailMessage(
        to_email=admin_email,
        to_name="Global Admin",
        subject="WorkshopPro NZ — Test Email",
        html_body=(
            "<h2>Email Configuration Test</h2>"
            "<p>This is a test email from WorkshopPro NZ.</p>"
            "<p>If you received this, your email infrastructure is working correctly.</p>"
            f"<p><strong>Provider:</strong> {client.config.provider}</p>"
            f"<p><strong>Domain:</strong> {client.config.domain}</p>"
        ),
        text_body=(
            "Email Configuration Test\n\n"
            "This is a test email from WorkshopPro NZ.\n"
            "If you received this, your email infrastructure is working correctly.\n"
            f"Provider: {client.config.provider}\n"
            f"Domain: {client.config.domain}\n"
        ),
    )

    result = await client.send(message)

    if result.success:
        # Mark config as verified
        from app.modules.admin.models import IntegrationConfig

        config_result = await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "smtp")
        )
        config_row = config_result.scalar_one_or_none()
        if config_row is not None:
            config_row.is_verified = True
            await db.flush()

        await write_audit_log(
            session=db,
            org_id=None,
            user_id=admin_user_id,
            action="admin.smtp_test_email_sent",
            entity_type="integration_config",
            entity_id=None,
            after_value={
                "recipient": admin_email,
                "provider": result.provider,
                "success": True,
                "ip_address": ip_address,
            },
            ip_address=ip_address,
        )

    return {
        "success": result.success,
        "message": "Test email sent successfully" if result.success else "Test email failed",
        "provider": result.provider,
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Twilio / SMS integration configuration (Req 36.1)
# ---------------------------------------------------------------------------


async def save_twilio_config(
    db: AsyncSession,
    *,
    account_sid: str,
    auth_token: str,
    sender_number: str,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Save or update the platform-wide Twilio SMS configuration.

    The config is stored encrypted in the ``integration_configs`` table
    with name='twilio'.

    Returns a dict with the saved (non-secret) config fields.
    Requirement 36.1.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_encrypt

    config_data = json.dumps({
        "account_sid": account_sid,
        "auth_token": auth_token,
        "sender_number": sender_number,
    })
    encrypted = envelope_encrypt(config_data)

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "twilio")
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.config_encrypted = encrypted
        existing.is_verified = False
    else:
        new_config = IntegrationConfig(
            name="twilio",
            config_encrypted=encrypted,
            is_verified=False,
        )
        db.add(new_config)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=updated_by,
        action="admin.twilio_config_updated",
        entity_type="integration_config",
        entity_id=None,
        after_value={
            "account_sid_last4": account_sid[-4:] if len(account_sid) >= 4 else account_sid,
            "sender_number": sender_number,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return {
        "account_sid_last4": account_sid[-4:] if len(account_sid) >= 4 else account_sid,
        "sender_number": sender_number,
        "is_verified": False,
    }


async def send_test_sms(
    db: AsyncSession,
    *,
    to_number: str,
    admin_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Send a test SMS to verify Twilio config.

    Requirement 36.1.
    """
    from app.integrations.twilio_sms import get_sms_client, SmsMessage

    client = await get_sms_client(db)
    if client is None:
        return {
            "success": False,
            "message": "Twilio configuration not found. Please configure SMS settings first.",
            "error": "No Twilio config",
        }

    message = SmsMessage(
        to_number=to_number,
        body="WorkshopPro NZ — Test SMS. Your Twilio configuration is working correctly.",
    )

    result = await client.send(message)

    if result.success:
        from app.modules.admin.models import IntegrationConfig

        config_result = await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == "twilio")
        )
        config_row = config_result.scalar_one_or_none()
        if config_row is not None:
            config_row.is_verified = True
            await db.flush()

        await write_audit_log(
            session=db,
            org_id=None,
            user_id=admin_user_id,
            action="admin.twilio_test_sms_sent",
            entity_type="integration_config",
            entity_id=None,
            after_value={
                "recipient": to_number,
                "success": True,
                "ip_address": ip_address,
            },
            ip_address=ip_address,
        )

    return {
        "success": result.success,
        "message": "Test SMS sent successfully" if result.success else "Test SMS failed",
        "error": result.error,
    }


# ---------------------------------------------------------------------------
# Carjam integration configuration (Req 48.3)
# ---------------------------------------------------------------------------


async def save_carjam_config(
    db: AsyncSession,
    *,
    api_key: str,
    endpoint_url: str,
    per_lookup_cost_nzd: float,
    global_rate_limit_per_minute: int,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Save or update the platform-wide Carjam configuration.

    Stores encrypted in ``integration_configs`` with name='carjam'.
    Returns non-secret config fields.
    Requirement 48.3.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_encrypt

    config_data = json.dumps({
        "api_key": api_key,
        "endpoint_url": endpoint_url,
        "per_lookup_cost_nzd": per_lookup_cost_nzd,
        "global_rate_limit_per_minute": global_rate_limit_per_minute,
    })
    encrypted = envelope_encrypt(config_data)

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.config_encrypted = encrypted
        existing.is_verified = False
    else:
        new_config = IntegrationConfig(
            name="carjam",
            config_encrypted=encrypted,
            is_verified=False,
        )
        db.add(new_config)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=updated_by,
        action="admin.carjam_config_updated",
        entity_type="integration_config",
        entity_id=None,
        after_value={
            "endpoint_url": endpoint_url,
            "per_lookup_cost_nzd": per_lookup_cost_nzd,
            "global_rate_limit_per_minute": global_rate_limit_per_minute,
            "api_key_last4": api_key[-4:] if len(api_key) >= 4 else api_key,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return {
        "endpoint_url": endpoint_url,
        "per_lookup_cost_nzd": per_lookup_cost_nzd,
        "global_rate_limit_per_minute": global_rate_limit_per_minute,
        "api_key_last4": api_key[-4:] if len(api_key) >= 4 else api_key,
        "is_verified": False,
    }


async def test_carjam_connection(
    db: AsyncSession,
    *,
    admin_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Test the Carjam connection by making a lightweight API call.

    Requirement 48.2.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    config_row = result.scalar_one_or_none()

    if config_row is None:
        return {
            "success": False,
            "message": "Carjam configuration not found. Please configure Carjam settings first.",
            "error": "No Carjam config",
        }

    try:
        config = json.loads(envelope_decrypt_str(config_row.config_encrypted))
    except Exception:
        return {
            "success": False,
            "message": "Failed to decrypt Carjam configuration.",
            "error": "Decryption error",
        }

    api_key = config.get("api_key", "")
    base_url = config.get("endpoint_url", "").rstrip("/")

    if not api_key or not base_url:
        return {
            "success": False,
            "message": "Carjam configuration is incomplete.",
            "error": "Missing API key or endpoint URL",
        }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.get(
                f"{base_url}/car/TEST000",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        # A 404 means the API is reachable (just no vehicle for TEST000)
        if response.status_code in (200, 404):
            config_row.is_verified = True
            await db.flush()

            await write_audit_log(
                session=db,
                org_id=None,
                user_id=admin_user_id,
                action="admin.carjam_test_success",
                entity_type="integration_config",
                entity_id=None,
                after_value={"success": True, "ip_address": ip_address},
                ip_address=ip_address,
            )

            return {
                "success": True,
                "message": "Carjam connection verified successfully.",
                "error": None,
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "message": "Carjam API key is invalid (401 Unauthorized).",
                "error": f"HTTP {response.status_code}",
            }
        else:
            return {
                "success": False,
                "message": f"Carjam API returned unexpected status {response.status_code}.",
                "error": f"HTTP {response.status_code}",
            }
    except httpx.TimeoutException:
        return {
            "success": False,
            "message": "Carjam API connection timed out.",
            "error": "Timeout",
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Carjam connection test failed: {exc}",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Global Stripe integration configuration (Req 48.4)
# ---------------------------------------------------------------------------


async def save_stripe_config(
    db: AsyncSession,
    *,
    platform_account_id: str,
    webhook_endpoint: str,
    signing_secret: str,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Save or update the platform-wide Global Stripe configuration.

    Stores encrypted in ``integration_configs`` with name='stripe'.
    Returns non-secret config fields.
    Requirement 48.4.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_encrypt

    config_data = json.dumps({
        "platform_account_id": platform_account_id,
        "webhook_endpoint": webhook_endpoint,
        "signing_secret": signing_secret,
    })
    encrypted = envelope_encrypt(config_data)

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.config_encrypted = encrypted
        existing.is_verified = False
    else:
        new_config = IntegrationConfig(
            name="stripe",
            config_encrypted=encrypted,
            is_verified=False,
        )
        db.add(new_config)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=updated_by,
        action="admin.stripe_config_updated",
        entity_type="integration_config",
        entity_id=None,
        after_value={
            "platform_account_last4": platform_account_id[-4:] if len(platform_account_id) >= 4 else platform_account_id,
            "webhook_endpoint": webhook_endpoint,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return {
        "platform_account_last4": platform_account_id[-4:] if len(platform_account_id) >= 4 else platform_account_id,
        "webhook_endpoint": webhook_endpoint,
        "is_verified": False,
    }


async def test_stripe_connection(
    db: AsyncSession,
    *,
    admin_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Test the Stripe connection by verifying the platform account.

    Requirement 48.2.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
    )
    config_row = result.scalar_one_or_none()

    if config_row is None:
        return {
            "success": False,
            "message": "Stripe configuration not found. Please configure Stripe settings first.",
            "error": "No Stripe config",
        }

    try:
        config = json.loads(envelope_decrypt_str(config_row.config_encrypted))
    except Exception:
        return {
            "success": False,
            "message": "Failed to decrypt Stripe configuration.",
            "error": "Decryption error",
        }

    platform_account_id = config.get("platform_account_id", "")
    if not platform_account_id:
        return {
            "success": False,
            "message": "Stripe configuration is incomplete.",
            "error": "Missing platform account ID",
        }

    try:
        import stripe as stripe_lib

        stripe_lib.api_key = settings.stripe_secret_key if hasattr(settings, "stripe_secret_key") else ""
        account = stripe_lib.Account.retrieve(platform_account_id)

        if account and account.get("id"):
            config_row.is_verified = True
            await db.flush()

            await write_audit_log(
                session=db,
                org_id=None,
                user_id=admin_user_id,
                action="admin.stripe_test_success",
                entity_type="integration_config",
                entity_id=None,
                after_value={"success": True, "ip_address": ip_address},
                ip_address=ip_address,
            )

            return {
                "success": True,
                "message": "Stripe connection verified successfully.",
                "error": None,
            }
        else:
            return {
                "success": False,
                "message": "Stripe account not found.",
                "error": "Account not found",
            }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Stripe connection test failed: {exc}",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Generic integration config retrieval (Req 48.1, 48.5)
# ---------------------------------------------------------------------------

# Maps integration name → list of fields safe to return (non-secret)
_SAFE_FIELDS: dict[str, list[str]] = {
    "carjam": ["endpoint_url", "per_lookup_cost_nzd", "global_rate_limit_per_minute"],
    "stripe": ["webhook_endpoint"],
    "smtp": ["provider", "domain", "from_email", "from_name", "reply_to", "host", "port"],
    "twilio": ["sender_number"],
}

# Maps integration name → list of fields to show as masked (last 4 chars)
_MASKED_FIELDS: dict[str, list[str]] = {
    "carjam": ["api_key"],
    "stripe": ["platform_account_id", "signing_secret"],
    "smtp": ["api_key"],
    "twilio": ["account_sid"],
}


async def get_integration_config(
    db: AsyncSession,
    *,
    name: str,
) -> dict | None:
    """Retrieve non-secret fields for an integration config.

    Returns ``None`` if the integration is not configured.
    Never returns raw secrets — only masked (last 4 chars) versions.
    Requirement 48.1, 48.5.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    valid_names = ("carjam", "stripe", "smtp", "twilio")
    if name not in valid_names:
        return None

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == name)
    )
    config_row = result.scalar_one_or_none()

    if config_row is None:
        return {
            "name": name,
            "is_verified": False,
            "updated_at": None,
            "config": {},
        }

    try:
        config = json.loads(envelope_decrypt_str(config_row.config_encrypted))
    except Exception:
        return {
            "name": name,
            "is_verified": config_row.is_verified,
            "updated_at": config_row.updated_at.isoformat() if config_row.updated_at else None,
            "config": {},
        }

    safe_config: dict = {}

    # Add safe (non-secret) fields
    for field in _SAFE_FIELDS.get(name, []):
        if field in config:
            safe_config[field] = config[field]

    # Add masked secret fields (last 4 chars only)
    for field in _MASKED_FIELDS.get(name, []):
        val = config.get(field, "")
        if val:
            safe_config[f"{field}_last4"] = val[-4:] if len(val) >= 4 else val

    return {
        "name": name,
        "is_verified": config_row.is_verified,
        "updated_at": config_row.updated_at.isoformat() if config_row.updated_at else None,
        "config": safe_config,
    }


# ---------------------------------------------------------------------------
# Subscription Plan Management (Req 40.1, 40.2, 40.3, 40.4)
# ---------------------------------------------------------------------------


async def create_plan(
    db: AsyncSession,
    *,
    name: str,
    monthly_price_nzd: float,
    user_seats: int,
    storage_quota_gb: int,
    carjam_lookups_included: int,
    enabled_modules: list[str],
    is_public: bool = True,
    storage_tier_pricing: list[dict] | None = None,
    created_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new subscription plan.

    Requirement 40.1: plan name, monthly price (NZD), user seats,
    storage quota, Carjam lookups, enabled modules.
    Requirement 40.2: public/private plans.
    Requirement 40.4: storage tier pricing.
    """
    # Check for duplicate plan name
    existing = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.name == name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"A plan with name '{name}' already exists")

    plan = SubscriptionPlan(
        name=name,
        monthly_price_nzd=monthly_price_nzd,
        user_seats=user_seats,
        storage_quota_gb=storage_quota_gb,
        carjam_lookups_included=carjam_lookups_included,
        enabled_modules=enabled_modules,
        is_public=is_public,
        is_archived=False,
        storage_tier_pricing=storage_tier_pricing or [],
    )
    db.add(plan)
    await db.flush()

    await write_audit_log(
        db,
        event="plan_created",
        actor_id=created_by,
        ip_address=ip_address,
        resource_type="subscription_plan",
        resource_id=str(plan.id),
        details={"plan_name": name, "monthly_price_nzd": monthly_price_nzd},
    )

    logger.info("Created subscription plan %s (%s)", plan.id, name)

    return {
        "id": str(plan.id),
        "name": plan.name,
        "monthly_price_nzd": float(plan.monthly_price_nzd),
        "user_seats": plan.user_seats,
        "storage_quota_gb": plan.storage_quota_gb,
        "carjam_lookups_included": plan.carjam_lookups_included,
        "enabled_modules": plan.enabled_modules,
        "is_public": plan.is_public,
        "is_archived": plan.is_archived,
        "storage_tier_pricing": plan.storage_tier_pricing or [],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


async def list_plans(
    db: AsyncSession,
    *,
    include_archived: bool = False,
) -> list[dict]:
    """List all subscription plans.

    Requirement 40.1: list plans.
    Requirement 40.3: archived plans hidden by default.
    """
    query = select(SubscriptionPlan).order_by(SubscriptionPlan.created_at)
    if not include_archived:
        query = query.where(SubscriptionPlan.is_archived.is_(False))

    result = await db.execute(query)
    plans = result.scalars().all()

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "monthly_price_nzd": float(p.monthly_price_nzd),
            "user_seats": p.user_seats,
            "storage_quota_gb": p.storage_quota_gb,
            "carjam_lookups_included": p.carjam_lookups_included,
            "enabled_modules": p.enabled_modules,
            "is_public": p.is_public,
            "is_archived": p.is_archived,
            "storage_tier_pricing": p.storage_tier_pricing or [],
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in plans
    ]


async def get_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
) -> dict | None:
    """Get a single subscription plan by ID."""
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    p = result.scalar_one_or_none()
    if p is None:
        return None

    return {
        "id": str(p.id),
        "name": p.name,
        "monthly_price_nzd": float(p.monthly_price_nzd),
        "user_seats": p.user_seats,
        "storage_quota_gb": p.storage_quota_gb,
        "carjam_lookups_included": p.carjam_lookups_included,
        "enabled_modules": p.enabled_modules,
        "is_public": p.is_public,
        "is_archived": p.is_archived,
        "storage_tier_pricing": p.storage_tier_pricing or [],
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


async def update_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    *,
    updates: dict,
    updated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update a subscription plan without affecting existing subscribers.

    Requirement 40.3: edit plans without affecting existing subscribers.
    Requirement 40.4: configure storage tier pricing.
    """
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Plan not found")

    if plan.is_archived:
        raise ValueError("Cannot edit an archived plan")

    before = {}
    after = {}

    allowed_fields = {
        "name", "monthly_price_nzd", "user_seats", "storage_quota_gb",
        "carjam_lookups_included", "enabled_modules", "is_public",
        "storage_tier_pricing",
    }

    # If renaming, check for duplicate
    if "name" in updates and updates["name"] is not None and updates["name"] != plan.name:
        existing = await db.execute(
            select(SubscriptionPlan).where(
                SubscriptionPlan.name == updates["name"],
                SubscriptionPlan.id != plan_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError(f"A plan with name '{updates['name']}' already exists")

    for field, value in updates.items():
        if field in allowed_fields and value is not None:
            before[field] = getattr(plan, field)
            setattr(plan, field, value)
            after[field] = value

    if not after:
        raise ValueError("No valid fields to update")

    await db.flush()

    await write_audit_log(
        db,
        event="plan_updated",
        actor_id=updated_by,
        ip_address=ip_address,
        resource_type="subscription_plan",
        resource_id=str(plan.id),
        details={"before": _serialise_audit(before), "after": _serialise_audit(after)},
    )

    logger.info("Updated subscription plan %s", plan.id)

    return {
        "id": str(plan.id),
        "name": plan.name,
        "monthly_price_nzd": float(plan.monthly_price_nzd),
        "user_seats": plan.user_seats,
        "storage_quota_gb": plan.storage_quota_gb,
        "carjam_lookups_included": plan.carjam_lookups_included,
        "enabled_modules": plan.enabled_modules,
        "is_public": plan.is_public,
        "is_archived": plan.is_archived,
        "storage_tier_pricing": plan.storage_tier_pricing or [],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _serialise_audit(data: dict) -> dict:
    """Make audit log values JSON-serialisable."""
    out = {}
    for k, v in data.items():
        if isinstance(v, (datetime,)):
            out[k] = v.isoformat()
        elif isinstance(v, (uuid.UUID,)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


async def archive_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    *,
    archived_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Archive a subscription plan without affecting existing subscribers.

    Requirement 40.3: archive plans without affecting existing subscribers.
    """
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Plan not found")

    if plan.is_archived:
        raise ValueError("Plan is already archived")

    plan.is_archived = True
    await db.flush()

    await write_audit_log(
        db,
        event="plan_archived",
        actor_id=archived_by,
        ip_address=ip_address,
        resource_type="subscription_plan",
        resource_id=str(plan.id),
        details={"plan_name": plan.name},
    )

    logger.info("Archived subscription plan %s (%s)", plan.id, plan.name)

    return {
        "id": str(plan.id),
        "name": plan.name,
        "monthly_price_nzd": float(plan.monthly_price_nzd),
        "user_seats": plan.user_seats,
        "storage_quota_gb": plan.storage_quota_gb,
        "carjam_lookups_included": plan.carjam_lookups_included,
        "enabled_modules": plan.enabled_modules,
        "is_public": plan.is_public,
        "is_archived": plan.is_archived,
        "storage_tier_pricing": plan.storage_tier_pricing or [],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


# ---------------------------------------------------------------------------
# Global Admin Reports (Req 46.1–46.5)
# ---------------------------------------------------------------------------


async def get_mrr_report(db: AsyncSession) -> dict:
    """Platform MRR with plan breakdown and month-over-month trend.

    Requirement 46.2: MRR with breakdown by plan type and month-over-month trend.
    """
    from sqlalchemy import func as sa_func, case, extract, literal_column

    # Current MRR: sum of monthly_price for all active/trial orgs grouped by plan
    stmt = (
        select(
            SubscriptionPlan.id,
            SubscriptionPlan.name,
            SubscriptionPlan.monthly_price_nzd,
            sa_func.count(Organisation.id).label("active_orgs"),
        )
        .join(Organisation, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.status.in_(["active", "trial", "grace_period"]))
        .group_by(SubscriptionPlan.id, SubscriptionPlan.name, SubscriptionPlan.monthly_price_nzd)
        .order_by(SubscriptionPlan.name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    plan_breakdown = []
    total_mrr = 0.0
    for plan_id, plan_name, price, count in rows:
        mrr = float(price) * count
        total_mrr += mrr
        plan_breakdown.append({
            "plan_id": str(plan_id),
            "plan_name": plan_name,
            "active_orgs": count,
            "mrr_nzd": round(mrr, 2),
        })

    # Month-over-month trend: approximate from org created_at dates
    # For each of the last 6 months, count orgs that were active at that point
    now = datetime.now(timezone.utc)
    month_over_month = []
    for months_ago in range(5, -1, -1):
        # Calculate the first day of the target month
        year = now.year
        month = now.month - months_ago
        while month <= 0:
            month += 12
            year -= 1
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)

        # Count orgs that existed by end of that month and were not deleted
        stmt_month = (
            select(
                sa_func.coalesce(
                    sa_func.sum(SubscriptionPlan.monthly_price_nzd), 0
                )
            )
            .select_from(Organisation)
            .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
            .where(
                Organisation.created_at < month_start + timedelta(days=32),
                Organisation.status.in_(["active", "trial", "grace_period"]),
            )
        )
        res = await db.execute(stmt_month)
        month_mrr = float(res.scalar() or 0)
        month_label = f"{year:04d}-{month:02d}"
        month_over_month.append({
            "month": month_label,
            "mrr_nzd": round(month_mrr, 2),
        })

    return {
        "total_mrr_nzd": round(total_mrr, 2),
        "plan_breakdown": plan_breakdown,
        "month_over_month": month_over_month,
    }


async def get_org_overview_report(db: AsyncSession) -> dict:
    """Organisation overview table for all orgs.

    Requirement 46.3: table of all orgs with plan, signup date, trial status,
    billing status, storage, Carjam usage, last login.
    """
    from sqlalchemy import func as sa_func

    # Get last login per org via a subquery
    last_login_subq = (
        select(
            User.org_id,
            sa_func.max(User.last_login_at).label("last_login_at"),
        )
        .where(User.org_id.isnot(None))
        .group_by(User.org_id)
        .subquery()
    )

    stmt = (
        select(
            Organisation,
            SubscriptionPlan.name.label("plan_name"),
            last_login_subq.c.last_login_at,
        )
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .outerjoin(last_login_subq, Organisation.id == last_login_subq.c.org_id)
        .where(Organisation.status != "deleted")
        .order_by(Organisation.name)
    )
    result = await db.execute(stmt)
    rows = result.all()

    orgs = []
    for org, plan_name, last_login in rows:
        # Determine trial status
        if org.status == "trial":
            if org.trial_ends_at and org.trial_ends_at < datetime.now(timezone.utc):
                trial_status = "expired"
            else:
                trial_status = "trial"
        else:
            trial_status = "active"

        orgs.append({
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "plan_name": plan_name,
            "signup_date": org.created_at,
            "trial_status": trial_status,
            "billing_status": org.status,
            "storage_used_bytes": org.storage_used_bytes,
            "storage_quota_gb": org.storage_quota_gb,
            "carjam_lookups_this_month": org.carjam_lookups_this_month,
            "last_login_at": last_login,
        })

    return {
        "organisations": orgs,
        "total": len(orgs),
    }


async def get_carjam_cost_report(db: AsyncSession) -> dict:
    """Carjam cost vs revenue report.

    Requirement 46.1: Carjam Cost vs Revenue as a global report.
    """
    from sqlalchemy import func as sa_func

    per_lookup_cost = await get_carjam_per_lookup_cost(db)

    # Total lookups across all orgs
    stmt = select(
        sa_func.coalesce(sa_func.sum(Organisation.carjam_lookups_this_month), 0)
    ).where(Organisation.status != "deleted")
    result = await db.execute(stmt)
    total_lookups = int(result.scalar() or 0)

    # Total cost to platform = total_lookups × per_lookup_cost
    total_cost = round(total_lookups * per_lookup_cost, 2)

    # Revenue = sum of overage charges across all orgs
    stmt_revenue = (
        select(
            Organisation.carjam_lookups_this_month,
            SubscriptionPlan.carjam_lookups_included,
        )
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.status != "deleted")
    )
    result = await db.execute(stmt_revenue)
    rows = result.all()

    total_revenue = 0.0
    for lookups, included in rows:
        overage = compute_carjam_overage(lookups, included)
        total_revenue += overage * per_lookup_cost

    total_revenue = round(total_revenue, 2)

    return {
        "total_lookups": total_lookups,
        "total_cost_nzd": total_cost,
        "total_revenue_nzd": total_revenue,
        "net_nzd": round(total_revenue - total_cost, 2),
        "per_lookup_cost_nzd": per_lookup_cost,
    }


async def get_churn_report(db: AsyncSession) -> dict:
    """Churn report: cancelled/suspended orgs with plan type and duration.

    Requirement 46.5: orgs that cancelled or were suspended with plan type
    and subscription duration at cancellation.
    """
    stmt = (
        select(Organisation, SubscriptionPlan.name.label("plan_name"))
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.status.in_(["suspended", "deleted"]))
        .order_by(Organisation.updated_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    churned = []
    for org, plan_name in rows:
        churned_at = org.updated_at
        duration_days = (churned_at - org.created_at).days if churned_at and org.created_at else 0
        churned.append({
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "plan_name": plan_name,
            "status": org.status,
            "signup_date": org.created_at,
            "churned_at": churned_at,
            "subscription_duration_days": duration_days,
        })

    return {
        "churned_organisations": churned,
        "total": len(churned),
    }


async def get_vehicle_db_stats(db: AsyncSession) -> dict:
    """Global Vehicle Database stats.

    Requirement 46.4: total records, cache hit rate, total lookups.
    """
    from app.modules.admin.models import GlobalVehicle
    from sqlalchemy import func as sa_func

    # Total records in global_vehicles
    stmt_count = select(sa_func.count(GlobalVehicle.id))
    result = await db.execute(stmt_count)
    total_records = int(result.scalar() or 0)

    # Total lookups across all orgs this month
    stmt_lookups = select(
        sa_func.coalesce(sa_func.sum(Organisation.carjam_lookups_this_month), 0)
    ).where(Organisation.status != "deleted")
    result = await db.execute(stmt_lookups)
    total_lookups = int(result.scalar() or 0)

    # Cache hit rate: if we have records in the DB, lookups that hit cache
    # are those that didn't result in new records. Approximate as:
    # cache_hit_rate = 1 - (new_records_this_month / total_lookups)
    # Since we don't track new records per month precisely, use a simpler
    # heuristic: records / (records + lookups) as a proxy, or if total_lookups
    # is 0, rate is 0.
    if total_lookups > 0 and total_records > 0:
        # Approximate: the more records we have relative to lookups, the higher
        # the cache hit rate. A simple model: cache_hits ≈ total_lookups - new_records
        # But we don't know new_records exactly. Use total_records / (total_records + total_lookups)
        # as a rough estimate, capped at 1.0.
        cache_hit_rate = round(min(1.0, total_records / (total_records + total_lookups)), 4)
    else:
        cache_hit_rate = 0.0

    return {
        "total_records": total_records,
        "total_lookups_all_orgs": total_lookups,
        "cache_hit_rate": cache_hit_rate,
    }


# ---------------------------------------------------------------------------
# Organisation Management (Req 47.1, 47.2, 47.3)
# ---------------------------------------------------------------------------

_DELETE_CONFIRMATION_TTL = 300  # 5 minutes


async def list_organisations(
    db: AsyncSession,
    *,
    search: str | None = None,
    status: str | None = None,
    plan_id: uuid.UUID | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """List organisations with search, filter, sort, and pagination.

    Returns a dict with ``organisations`` list and ``total`` count.
    Requirement 47.1.
    """
    from sqlalchemy import func as sa_func, or_

    # Base query joining plan for plan_name
    base_q = select(Organisation, SubscriptionPlan.name.label("plan_name")).join(
        SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id
    )

    # Filters
    if search:
        base_q = base_q.where(Organisation.name.ilike(f"%{search}%"))
    if status:
        base_q = base_q.where(Organisation.status == status)
    if plan_id:
        base_q = base_q.where(Organisation.plan_id == plan_id)

    # Count total
    from sqlalchemy import func as sa_func
    count_q = select(sa_func.count()).select_from(base_q.subquery())
    count_result = await db.execute(count_q)
    total = count_result.scalar() or 0

    # Sorting
    allowed_sort_fields = {
        "created_at": Organisation.created_at,
        "updated_at": Organisation.updated_at,
        "name": Organisation.name,
        "status": Organisation.status,
    }
    sort_col = allowed_sort_fields.get(sort_by, Organisation.created_at)
    if sort_order == "asc":
        base_q = base_q.order_by(sort_col.asc())
    else:
        base_q = base_q.order_by(sort_col.desc())

    # Pagination
    offset = (page - 1) * page_size
    base_q = base_q.offset(offset).limit(page_size)

    result = await db.execute(base_q)
    rows = result.all()

    organisations = []
    for org, plan_name in rows:
        organisations.append({
            "id": str(org.id),
            "name": org.name,
            "plan_id": str(org.plan_id),
            "plan_name": plan_name,
            "status": org.status,
            "storage_quota_gb": org.storage_quota_gb,
            "storage_used_bytes": org.storage_used_bytes,
            "carjam_lookups_this_month": org.carjam_lookups_this_month,
            "created_at": org.created_at,
            "updated_at": org.updated_at,
        })

    return {"organisations": organisations, "total": total, "page": page, "page_size": page_size}


async def update_organisation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    action: str,
    reason: str | None = None,
    new_plan_id: uuid.UUID | None = None,
    notify_org_admin: bool = False,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Update an organisation: suspend, reinstate, delete_request, or move_plan.

    For ``delete_request``, generates a confirmation token (step 1 of multi-step delete).
    Requirements 47.2, 47.3.
    """
    from app.core.redis import redis_pool

    # Fetch org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    valid_actions = ("suspend", "reinstate", "delete_request", "move_plan")
    if action not in valid_actions:
        raise ValueError(f"Invalid action. Must be one of: {', '.join(valid_actions)}")

    previous_status = org.status

    if action == "suspend":
        if not reason:
            raise ValueError("Reason is required when suspending an organisation")
        if org.status == "suspended":
            raise ValueError("Organisation is already suspended")
        if org.status == "deleted":
            raise ValueError("Cannot suspend a deleted organisation")

        org.status = "suspended"
        await db.flush()

        await write_audit_log(
            session=db,
            user_id=updated_by,
            action="org.suspended",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": previous_status},
            after_value={"status": "suspended", "reason": reason},
            ip_address=ip_address,
        )

        if notify_org_admin:
            await _notify_org_admin_status_change(db, org, "suspended", reason)

        return {
            "message": "Organisation suspended",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "previous_status": previous_status,
        }

    elif action == "reinstate":
        if org.status != "suspended":
            raise ValueError("Only suspended organisations can be reinstated")

        org.status = "active"
        await db.flush()

        await write_audit_log(
            session=db,
            user_id=updated_by,
            action="org.reinstated",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": "suspended"},
            after_value={"status": "active"},
            ip_address=ip_address,
        )

        if notify_org_admin:
            await _notify_org_admin_status_change(db, org, "reinstated", None)

        return {
            "message": "Organisation reinstated",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "previous_status": "suspended",
        }

    elif action == "delete_request":
        if not reason:
            raise ValueError("Reason is required when requesting deletion")
        if org.status == "deleted":
            raise ValueError("Organisation is already deleted")

        # Generate confirmation token for multi-step delete
        token = secrets.token_urlsafe(32)
        token_data = json.dumps({
            "org_id": str(org.id),
            "reason": reason,
            "requested_by": str(updated_by),
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })
        await redis_pool.setex(
            f"org_delete_confirm:{token}",
            _DELETE_CONFIRMATION_TTL,
            token_data,
        )

        return {
            "message": "Deletion confirmation required. Use the confirmation_token with DELETE to proceed.",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "confirmation_token": token,
            "expires_in_seconds": _DELETE_CONFIRMATION_TTL,
        }

    elif action == "move_plan":
        if not new_plan_id:
            raise ValueError("new_plan_id is required for move_plan action")
        if org.status == "deleted":
            raise ValueError("Cannot move plan for a deleted organisation")

        # Validate new plan
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_id)
        )
        new_plan = plan_result.scalar_one_or_none()
        if new_plan is None:
            raise ValueError("Target subscription plan not found")
        if new_plan.is_archived:
            raise ValueError("Cannot move to an archived plan")

        previous_plan_id = str(org.plan_id)
        org.plan_id = new_plan_id
        org.storage_quota_gb = new_plan.storage_quota_gb
        await db.flush()

        await write_audit_log(
            session=db,
            user_id=updated_by,
            action="org.plan_changed",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"plan_id": previous_plan_id},
            after_value={"plan_id": str(new_plan_id), "plan_name": new_plan.name},
            ip_address=ip_address,
        )

        if notify_org_admin:
            await _notify_org_admin_status_change(db, org, "plan_changed", None)

        return {
            "message": f"Organisation moved to plan '{new_plan.name}'",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "previous_plan_id": previous_plan_id,
            "new_plan_id": str(new_plan_id),
        }

    raise ValueError(f"Unhandled action: {action}")


async def delete_organisation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    reason: str,
    confirmation_token: str,
    notify_org_admin: bool = False,
    deleted_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Permanently delete (soft-delete) an organisation after multi-step confirmation.

    Validates the confirmation token from Redis, then marks the org as deleted.
    Requirements 47.2, 47.3.
    """
    from app.core.redis import redis_pool

    # Validate confirmation token
    token_key = f"org_delete_confirm:{confirmation_token}"
    token_data_raw = await redis_pool.get(token_key)
    if not token_data_raw:
        raise ValueError("Invalid or expired confirmation token. Please initiate deletion again.")

    token_data = json.loads(token_data_raw)
    if token_data.get("org_id") != str(org_id):
        raise ValueError("Confirmation token does not match the organisation")

    # Consume the token
    await redis_pool.delete(token_key)

    # Fetch org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")
    if org.status == "deleted":
        raise ValueError("Organisation is already deleted")

    previous_status = org.status
    org.status = "deleted"
    await db.flush()

    await write_audit_log(
        session=db,
        user_id=deleted_by,
        action="org.deleted",
        entity_type="organisation",
        entity_id=org.id,
        before_value={"status": previous_status},
        after_value={"status": "deleted", "reason": reason},
        ip_address=ip_address,
    )

    if notify_org_admin:
        await _notify_org_admin_status_change(db, org, "deleted", reason)

    return {
        "message": "Organisation permanently deleted",
        "organisation_id": str(org.id),
        "organisation_name": org.name,
    }


async def _notify_org_admin_status_change(
    db: AsyncSession,
    org: Organisation,
    change_type: str,
    reason: str | None,
) -> None:
    """Send notification email to the Org_Admin about a status change.

    In production this dispatches via the notification infrastructure.
    For now we log the intent.
    """
    # Find org admin(s)
    result = await db.execute(
        select(User).where(User.org_id == org.id, User.role == "org_admin", User.is_active == True)
    )
    admins = result.scalars().all()

    for admin in admins:
        logger.info(
            "Org status change notification queued: org=%s, admin=%s, change=%s, reason=%s",
            org.name,
            admin.email,
            change_type,
            reason or "(none)",
        )


# ---------------------------------------------------------------------------
# Comprehensive Error Logging (Req 49.1–49.7)
# ---------------------------------------------------------------------------


async def get_error_dashboard(db: AsyncSession) -> dict:
    """Return real-time error counts for the dashboard.

    Counts errors for last 1h, 24h, and 7d grouped by severity and category.
    Requirement 49.4.
    """
    from sqlalchemy import text as sa_text

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(hours=24)
    seven_days_ago = now - timedelta(days=7)

    # Severity counts
    severity_rows = await db.execute(
        sa_text(
            """
            SELECT severity,
                   COUNT(*) FILTER (WHERE created_at >= :t1h) AS count_1h,
                   COUNT(*) FILTER (WHERE created_at >= :t24h) AS count_24h,
                   COUNT(*) FILTER (WHERE created_at >= :t7d) AS count_7d
            FROM error_log
            WHERE created_at >= :t7d
            GROUP BY severity
            """
        ),
        {"t1h": one_hour_ago, "t24h": one_day_ago, "t7d": seven_days_ago},
    )
    by_severity = []
    total_1h = total_24h = total_7d = 0
    for row in severity_rows:
        by_severity.append({
            "label": row[0],
            "count_1h": row[1],
            "count_24h": row[2],
            "count_7d": row[3],
        })
        total_1h += row[1]
        total_24h += row[2]
        total_7d += row[3]

    # Category counts
    category_rows = await db.execute(
        sa_text(
            """
            SELECT category,
                   COUNT(*) FILTER (WHERE created_at >= :t1h) AS count_1h,
                   COUNT(*) FILTER (WHERE created_at >= :t24h) AS count_24h,
                   COUNT(*) FILTER (WHERE created_at >= :t7d) AS count_7d
            FROM error_log
            WHERE created_at >= :t7d
            GROUP BY category
            """
        ),
        {"t1h": one_hour_ago, "t24h": one_day_ago, "t7d": seven_days_ago},
    )
    by_category = [
        {
            "label": row[0],
            "count_1h": row[1],
            "count_24h": row[2],
            "count_7d": row[3],
        }
        for row in category_rows
    ]

    return {
        "by_severity": by_severity,
        "by_category": by_category,
        "total_1h": total_1h,
        "total_24h": total_24h,
        "total_7d": total_7d,
    }


async def list_error_logs(
    db: AsyncSession,
    *,
    severity: str | None = None,
    category: str | None = None,
    status: str | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """List error logs with filtering, search, and pagination.

    Requirement 49.4: search/filter by organisation, severity, category,
    date range, and keyword.
    """
    from sqlalchemy import text as sa_text

    conditions = []
    params: dict = {}

    if severity:
        conditions.append("severity = :severity")
        params["severity"] = severity
    if category:
        conditions.append("category = :category")
        params["category"] = category
    if status:
        conditions.append("status = :status")
        params["status"] = status
    if org_id:
        conditions.append("org_id = :org_id")
        params["org_id"] = org_id
    if keyword:
        conditions.append("message ILIKE :keyword")
        params["keyword"] = f"%{keyword}%"
    if date_from:
        conditions.append("created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("created_at <= :date_to")
        params["date_to"] = date_to

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Count
    count_result = await db.execute(
        sa_text(f"SELECT COUNT(*) FROM error_log WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar() or 0

    # Fetch page
    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    rows = await db.execute(
        sa_text(
            f"""
            SELECT id, severity, category, module, function_name, message,
                   org_id, user_id, status, created_at
            FROM error_log
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    )

    errors = []
    for r in rows:
        errors.append({
            "id": str(r[0]),
            "severity": r[1],
            "category": r[2],
            "module": r[3],
            "function_name": r[4],
            "message": r[5],
            "org_id": str(r[6]) if r[6] else None,
            "user_id": str(r[7]) if r[7] else None,
            "status": r[8],
            "created_at": r[9],
        })

    return {"errors": errors, "total": total, "page": page, "page_size": page_size}


async def get_error_detail(db: AsyncSession, error_id: uuid.UUID) -> dict | None:
    """Get full error detail by ID.

    Requirement 49.6: full formatted stack trace, context, request/response,
    status with notes.
    """
    from sqlalchemy import text as sa_text

    result = await db.execute(
        sa_text(
            """
            SELECT id, severity, category, module, function_name, message,
                   stack_trace, org_id, user_id, http_method, http_endpoint,
                   request_body_sanitised, response_body_sanitised,
                   status, resolution_notes, created_at
            FROM error_log
            WHERE id = :error_id
            """
        ),
        {"error_id": str(error_id)},
    )
    row = result.one_or_none()
    if row is None:
        return None

    return {
        "id": str(row[0]),
        "severity": row[1],
        "category": row[2],
        "module": row[3],
        "function_name": row[4],
        "message": row[5],
        "stack_trace": row[6],
        "org_id": str(row[7]) if row[7] else None,
        "user_id": str(row[8]) if row[8] else None,
        "http_method": row[9],
        "http_endpoint": row[10],
        "request_body_sanitised": row[11],
        "response_body_sanitised": row[12],
        "status": row[13],
        "resolution_notes": row[14],
        "created_at": row[15],
    }


async def update_error_status(
    db: AsyncSession,
    error_id: uuid.UUID,
    *,
    status: str,
    resolution_notes: str | None = None,
) -> dict:
    """Update error status and resolution notes.

    Requirement 49.6: status (Open/Investigating/Resolved) with notes.
    """
    from sqlalchemy import text as sa_text

    valid_statuses = ("open", "investigating", "resolved")
    if status not in valid_statuses:
        raise ValueError(f"Status must be one of: {', '.join(valid_statuses)}")

    # Check error exists
    existing = await db.execute(
        sa_text("SELECT id FROM error_log WHERE id = :error_id"),
        {"error_id": str(error_id)},
    )
    if existing.one_or_none() is None:
        raise ValueError("Error log entry not found")

    await db.execute(
        sa_text(
            """
            UPDATE error_log
            SET status = :status, resolution_notes = :notes
            WHERE id = :error_id
            """
        ),
        {
            "error_id": str(error_id),
            "status": status,
            "notes": resolution_notes,
        },
    )

    return {
        "message": f"Error status updated to {status}",
        "id": str(error_id),
        "status": status,
        "resolution_notes": resolution_notes,
    }


async def export_error_logs(
    db: AsyncSession,
    *,
    fmt: str = "json",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    severity: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Export error logs for a date range.

    Requirement 49.7: retain 12 months, export CSV/JSON.
    Returns a list of dicts suitable for JSON or CSV serialisation.
    """
    from sqlalchemy import text as sa_text

    conditions = []
    params: dict = {}

    if date_from:
        conditions.append("created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        conditions.append("created_at <= :date_to")
        params["date_to"] = date_to
    if severity:
        conditions.append("severity = :severity")
        params["severity"] = severity
    if category:
        conditions.append("category = :category")
        params["category"] = category

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    rows = await db.execute(
        sa_text(
            f"""
            SELECT id, severity, category, module, function_name, message,
                   stack_trace, org_id, user_id, http_method, http_endpoint,
                   status, resolution_notes, created_at
            FROM error_log
            WHERE {where_clause}
            ORDER BY created_at DESC
            """
        ),
        params,
    )

    results = []
    for r in rows:
        results.append({
            "id": str(r[0]),
            "severity": r[1],
            "category": r[2],
            "module": r[3],
            "function_name": r[4],
            "message": r[5],
            "stack_trace": r[6],
            "org_id": str(r[7]) if r[7] else None,
            "user_id": str(r[8]) if r[8] else None,
            "http_method": r[9],
            "http_endpoint": r[10],
            "status": r[11],
            "resolution_notes": r[12],
            "created_at": r[13].isoformat() if r[13] else None,
        })

    return results


# ---------------------------------------------------------------------------
# Platform Settings (Task 23.4)
# ---------------------------------------------------------------------------


async def get_platform_settings(db: AsyncSession) -> dict:
    """Return current platform settings (T&C + announcement banner).

    Requirement 50.1: manage T&C with version history, announcement banner.
    """
    from sqlalchemy import text as sa_text

    # Fetch T&C setting
    row_tc = await db.execute(
        sa_text("SELECT key, value, version, updated_at FROM platform_settings WHERE key = :k"),
        {"k": "terms_and_conditions"},
    )
    tc_row = row_tc.first()

    terms_entry = None
    terms_history: list[dict] = []
    if tc_row:
        val = tc_row[1] if isinstance(tc_row[1], dict) else json.loads(tc_row[1])
        terms_entry = {
            "version": tc_row[2],
            "content": val.get("content", ""),
            "updated_at": tc_row[3].isoformat() if tc_row[3] else "",
        }
        # History is stored inside the value JSONB
        terms_history = val.get("history", [])

    # Fetch announcement banner setting
    row_ann = await db.execute(
        sa_text("SELECT key, value, version, updated_at FROM platform_settings WHERE key = :k"),
        {"k": "announcement_banner"},
    )
    ann_row = row_ann.first()

    announcement_banner = None
    announcement_active = False
    if ann_row:
        ann_val = ann_row[1] if isinstance(ann_row[1], dict) else json.loads(ann_row[1])
        announcement_banner = ann_val.get("text", None)
        announcement_active = ann_val.get("active", False)

    return {
        "terms_and_conditions": terms_entry,
        "terms_history": terms_history,
        "announcement_banner": announcement_banner,
        "announcement_active": announcement_active,
    }


async def update_platform_settings(
    db: AsyncSession,
    *,
    terms_and_conditions: str | None = None,
    announcement_banner: str | None = None,
    announcement_active: bool | None = None,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update platform settings.

    Requirement 50.1: manage T&C with version history, announcement banner.
    Requirement 50.2: prompt re-accept on T&C update.
    Requirement 50.3: announcement banner for maintenance/feature notices.
    """
    from sqlalchemy import text as sa_text

    result: dict = {"message": "Platform settings updated"}

    # --- Terms & Conditions ------------------------------------------------
    if terms_and_conditions is not None:
        row = await db.execute(
            sa_text("SELECT value, version FROM platform_settings WHERE key = :k FOR UPDATE"),
            {"k": "terms_and_conditions"},
        )
        existing = row.first()

        if existing:
            old_val = existing[0] if isinstance(existing[0], dict) else json.loads(existing[0])
            old_version = existing[1]
            new_version = old_version + 1

            # Preserve history
            history = old_val.get("history", [])
            history.append({
                "version": old_version,
                "content": old_val.get("content", ""),
                "updated_at": old_val.get("updated_at", ""),
            })

            new_val = {
                "content": terms_and_conditions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "history": history,
                "requires_reaccept": True,
            }

            await db.execute(
                sa_text(
                    "UPDATE platform_settings SET value = :v, version = :ver, "
                    "updated_at = now() WHERE key = :k"
                ),
                {"v": json.dumps(new_val), "ver": new_version, "k": "terms_and_conditions"},
            )
        else:
            new_version = 1
            new_val = {
                "content": terms_and_conditions,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "history": [],
                "requires_reaccept": False,
            }
            await db.execute(
                sa_text(
                    "INSERT INTO platform_settings (key, value, version, updated_at) "
                    "VALUES (:k, :v, :ver, now())"
                ),
                {"k": "terms_and_conditions", "v": json.dumps(new_val), "ver": new_version},
            )

        result["terms_version"] = new_version

        await write_audit_log(
            db,
            action="platform_settings.update_terms",
            entity_type="platform_settings",
            entity_id=None,
            user_id=actor_user_id,
            ip_address=ip_address,
            after_value={"version": new_version, "content_length": len(terms_and_conditions)},
        )

    # --- Announcement Banner -----------------------------------------------
    if announcement_banner is not None or announcement_active is not None:
        row = await db.execute(
            sa_text("SELECT value FROM platform_settings WHERE key = :k FOR UPDATE"),
            {"k": "announcement_banner"},
        )
        existing = row.scalar_one_or_none()

        if existing:
            old_val = existing if isinstance(existing, dict) else json.loads(existing)
        else:
            old_val = {"text": None, "active": False}

        new_val = dict(old_val)
        if announcement_banner is not None:
            new_val["text"] = announcement_banner if announcement_banner else None
        if announcement_active is not None:
            new_val["active"] = announcement_active

        if existing:
            await db.execute(
                sa_text(
                    "UPDATE platform_settings SET value = :v, updated_at = now() WHERE key = :k"
                ),
                {"k": "announcement_banner", "v": json.dumps(new_val)},
            )
        else:
            await db.execute(
                sa_text(
                    "INSERT INTO platform_settings (key, value, version, updated_at) "
                    "VALUES (:k, :v, 1, now())"
                ),
                {"k": "announcement_banner", "v": json.dumps(new_val)},
            )

        result["announcement_banner"] = new_val.get("text")
        result["announcement_active"] = new_val.get("active", False)

        await write_audit_log(
            db,
            action="platform_settings.update_announcement",
            entity_type="platform_settings",
            entity_id=None,
            user_id=actor_user_id,
            ip_address=ip_address,
            after_value=new_val,
        )

    return result


async def search_global_vehicles(
    db: AsyncSession,
    rego: str,
) -> dict:
    """Search the Global Vehicle DB by rego.

    Requirement 50.1: view, search the Global Vehicle DB.
    """
    from sqlalchemy import text as sa_text

    rows = await db.execute(
        sa_text(
            "SELECT id, rego, make, model, year, colour, body_type, fuel_type, "
            "engine_size, num_seats, wof_expiry, registration_expiry, "
            "odometer_last_recorded, last_pulled_at, created_at "
            "FROM global_vehicles WHERE rego ILIKE :rego ORDER BY rego LIMIT 50"
        ),
        {"rego": f"%{rego}%"},
    )

    results = []
    for r in rows:
        results.append({
            "id": str(r[0]),
            "rego": r[1],
            "make": r[2],
            "model": r[3],
            "year": r[4],
            "colour": r[5],
            "body_type": r[6],
            "fuel_type": r[7],
            "engine_size": r[8],
            "num_seats": r[9],
            "wof_expiry": r[10].isoformat() if r[10] else None,
            "registration_expiry": r[11].isoformat() if r[11] else None,
            "odometer_last_recorded": r[12],
            "last_pulled_at": r[13].isoformat() if r[13] else None,
            "created_at": r[14].isoformat() if r[14] else None,
        })

    return {"results": results, "total": len(results)}


async def delete_stale_vehicles(
    db: AsyncSession,
    stale_days: int = 365,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Delete stale records from the Global Vehicle DB.

    Requirement 50.1: delete stale records from Global Vehicle DB.
    Records older than *stale_days* since last pull are removed.
    """
    from sqlalchemy import text as sa_text

    cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)

    result = await db.execute(
        sa_text("DELETE FROM global_vehicles WHERE last_pulled_at < :cutoff"),
        {"cutoff": cutoff},
    )
    deleted_count = result.rowcount or 0

    await write_audit_log(
        db,
        action="platform_settings.delete_stale_vehicles",
        entity_type="global_vehicles",
        entity_id=None,
        user_id=actor_user_id,
        ip_address=ip_address,
        after_value={"deleted_count": deleted_count, "stale_days": stale_days},
    )

    return {"message": f"Deleted {deleted_count} stale vehicle records", "deleted_count": deleted_count}


async def _carjam_refresh_lookup(rego: str) -> dict | None:
    """Call Carjam API to refresh vehicle data.

    Separated for testability. Returns a dict of vehicle fields or None.
    """
    from app.integrations.carjam import CarjamClient, CarjamNotFoundError
    from app.core.redis import get_redis_pool

    redis = await get_redis_pool()
    client = CarjamClient(redis=redis)
    try:
        vehicle = await client.lookup_vehicle(rego)
        return {
            "make": vehicle.make,
            "model": vehicle.model,
            "year": vehicle.year,
            "colour": vehicle.colour,
            "body_type": vehicle.body_type,
            "fuel_type": vehicle.fuel_type,
            "engine_size": vehicle.engine_size,
            "num_seats": vehicle.seats,
            "wof_expiry": vehicle.wof_expiry,
            "registration_expiry": vehicle.rego_expiry,
            "odometer_last_recorded": vehicle.odometer,
        }
    except CarjamNotFoundError:
        return None


async def refresh_global_vehicle(
    db: AsyncSession,
    rego: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Force-refresh a vehicle record from Carjam.

    Requirement 50.1: force-refresh from Carjam.
    """
    from sqlalchemy import text as sa_text

    # Check if vehicle exists
    row = await db.execute(
        sa_text(
            "SELECT id, rego, make, model, year, colour, body_type, fuel_type, "
            "engine_size, num_seats, wof_expiry, registration_expiry, "
            "odometer_last_recorded, last_pulled_at, created_at "
            "FROM global_vehicles WHERE rego = :rego"
        ),
        {"rego": rego.upper().strip()},
    )
    existing = row.first()

    if not existing:
        return {"message": f"Vehicle with rego '{rego}' not found in Global Vehicle DB", "vehicle": None}

    # Attempt Carjam refresh
    try:
        carjam_data = await _carjam_refresh_lookup(rego.upper().strip())
        if carjam_data:
            await db.execute(
                sa_text(
                    "UPDATE global_vehicles SET "
                    "make = :make, model = :model, year = :year, colour = :colour, "
                    "body_type = :body_type, fuel_type = :fuel_type, "
                    "engine_size = :engine_size, num_seats = :num_seats, "
                    "wof_expiry = :wof_expiry, registration_expiry = :reg_expiry, "
                    "odometer_last_recorded = :odometer, last_pulled_at = now() "
                    "WHERE rego = :rego"
                ),
                {
                    "make": carjam_data.get("make"),
                    "model": carjam_data.get("model"),
                    "year": carjam_data.get("year"),
                    "colour": carjam_data.get("colour"),
                    "body_type": carjam_data.get("body_type"),
                    "fuel_type": carjam_data.get("fuel_type"),
                    "engine_size": carjam_data.get("engine_size"),
                    "num_seats": carjam_data.get("num_seats"),
                    "wof_expiry": carjam_data.get("wof_expiry"),
                    "reg_expiry": carjam_data.get("registration_expiry"),
                    "odometer": carjam_data.get("odometer_last_recorded"),
                    "rego": rego.upper().strip(),
                },
            )

            # Re-fetch updated record
            row2 = await db.execute(
                sa_text(
                    "SELECT id, rego, make, model, year, colour, body_type, fuel_type, "
                    "engine_size, num_seats, wof_expiry, registration_expiry, "
                    "odometer_last_recorded, last_pulled_at, created_at "
                    "FROM global_vehicles WHERE rego = :rego"
                ),
                {"rego": rego.upper().strip()},
            )
            refreshed = row2.first()
            vehicle = {
                "id": str(refreshed[0]),
                "rego": refreshed[1],
                "make": refreshed[2],
                "model": refreshed[3],
                "year": refreshed[4],
                "colour": refreshed[5],
                "body_type": refreshed[6],
                "fuel_type": refreshed[7],
                "engine_size": refreshed[8],
                "num_seats": refreshed[9],
                "wof_expiry": refreshed[10].isoformat() if refreshed[10] else None,
                "registration_expiry": refreshed[11].isoformat() if refreshed[11] else None,
                "odometer_last_recorded": refreshed[12],
                "last_pulled_at": refreshed[13].isoformat() if refreshed[13] else None,
                "created_at": refreshed[14].isoformat() if refreshed[14] else None,
            }

            await write_audit_log(
                db,
                action="platform_settings.refresh_vehicle",
                entity_type="global_vehicles",
                entity_id=None,
                user_id=actor_user_id,
                ip_address=ip_address,
                after_value={"rego": rego.upper().strip()},
            )

            return {"message": f"Vehicle '{rego}' refreshed from Carjam", "vehicle": vehicle}
        else:
            return {"message": f"Carjam returned no data for rego '{rego}'", "vehicle": None}
    except Exception as exc:
        logger.warning("Carjam refresh failed for rego %s: %s", rego, exc)
        # Return existing record without refresh
        vehicle = {
            "id": str(existing[0]),
            "rego": existing[1],
            "make": existing[2],
            "model": existing[3],
            "year": existing[4],
            "colour": existing[5],
            "body_type": existing[6],
            "fuel_type": existing[7],
            "engine_size": existing[8],
            "num_seats": existing[9],
            "wof_expiry": existing[10].isoformat() if existing[10] else None,
            "registration_expiry": existing[11].isoformat() if existing[11] else None,
            "odometer_last_recorded": existing[12],
            "last_pulled_at": existing[13].isoformat() if existing[13] else None,
            "created_at": existing[14].isoformat() if existing[14] else None,
        }
        return {"message": f"Carjam refresh failed: {exc}. Returning existing record.", "vehicle": vehicle}


# ---------------------------------------------------------------------------
# Audit log viewing (Req 51.1, 51.2, 51.4)
# ---------------------------------------------------------------------------


async def list_audit_logs(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    user_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Query audit log entries with optional filters and pagination.

    When *org_id* is provided the results are scoped to that organisation
    (Org_Admin view).  When *org_id* is ``None`` all entries are returned
    (Global_Admin view).

    Returns a dict with ``entries``, ``total``, ``page``, ``page_size``.
    """
    import json as _json

    from sqlalchemy import text as sa_text

    conditions: list[str] = []
    params: dict = {}

    if org_id is not None:
        conditions.append("org_id = :org_id")
        params["org_id"] = str(org_id)

    if action:
        conditions.append("action ILIKE :action")
        params["action"] = f"%{action}%"

    if entity_type:
        conditions.append("entity_type ILIKE :entity_type")
        params["entity_type"] = f"%{entity_type}%"

    if user_id:
        conditions.append("user_id = :user_id")
        params["user_id"] = user_id

    if date_from:
        conditions.append("created_at >= :date_from::timestamptz")
        params["date_from"] = date_from

    if date_to:
        conditions.append("created_at <= :date_to::timestamptz")
        params["date_to"] = date_to

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    # Total count
    count_row = await db.execute(
        sa_text(f"SELECT count(*) FROM audit_log WHERE {where_clause}"),
        params,
    )
    total = count_row.scalar() or 0

    # Paginated results
    offset = (max(page, 1) - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    rows = await db.execute(
        sa_text(
            f"SELECT id, org_id, user_id, action, entity_type, entity_id, "
            f"before_value, after_value, ip_address, device_info, created_at "
            f"FROM audit_log WHERE {where_clause} "
            f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    )

    entries = []
    for r in rows:
        before_val = r[6]
        after_val = r[7]
        # Handle JSON string or dict values
        if isinstance(before_val, str):
            try:
                before_val = _json.loads(before_val)
            except (ValueError, TypeError):
                before_val = None
        if isinstance(after_val, str):
            try:
                after_val = _json.loads(after_val)
            except (ValueError, TypeError):
                after_val = None

        entries.append({
            "id": str(r[0]),
            "org_id": str(r[1]) if r[1] else None,
            "user_id": str(r[2]) if r[2] else None,
            "action": r[3],
            "entity_type": r[4],
            "entity_id": str(r[5]) if r[5] else None,
            "before_value": before_val,
            "after_value": after_val,
            "ip_address": str(r[8]) if r[8] else None,
            "device_info": r[9],
            "created_at": r[10].isoformat() if r[10] else None,
        })

    return {
        "entries": entries,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
