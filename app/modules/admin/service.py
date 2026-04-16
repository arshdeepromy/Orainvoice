"""Business logic for Global Admin operations."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from decimal import Decimal

from app.core.audit import write_audit_log
from app.config import settings
from app.modules.admin.models import AuditLog, Coupon, Organisation, OrganisationCoupon, OrgStorageAddon, SmsPackagePurchase, SmsVerificationProvider, StoragePackage, SubscriptionPlan
from app.modules.auth.models import User
from app.modules.billing.interval_pricing import (
    build_default_interval_config,
    compute_effective_price,
    compute_equivalent_monthly,
    compute_savings_amount,
    validate_interval_config,
)

logger = logging.getLogger(__name__)

_INVITE_TOKEN_EXPIRY_SECONDS = 48 * 3600  # 48 hours

# ---------------------------------------------------------------------------
# Dynamic SQL column name whitelist (REM-21)
# ---------------------------------------------------------------------------
_ALLOWED_SORT_COLUMNS: dict[str, set[str]] = {
    "organisations": {"created_at", "updated_at", "name", "status"},
    "users": {"created_at", "email", "role", "last_login_at", "is_active"},
    "invoices": {"created_at", "total", "status", "due_date"},
}


def validate_column_name(table: str, column: str) -> str:
    """Return *column* unchanged if it is in the allowlist for *table*.

    Raises ``ValueError`` and logs a warning when the column is not permitted,
    preventing SQL-injection via dynamic column names.
    """
    allowed = _ALLOWED_SORT_COLUMNS.get(table, set())
    if column not in allowed:
        logger.warning(
            "Rejected dynamic column name: table=%s, column=%s", table, column
        )
        raise ValueError(f"Invalid column name: {column}")
    return column


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

    # 10. Seed org_modules from the plan's enabled_modules
    await _sync_org_modules_from_plan(db, org.id, plan.enabled_modules or [])

    # 11. Seed Chart of Accounts for the new organisation (Req 1.1)
    try:
        from app.modules.ledger.service import seed_coa_for_org
        await seed_coa_for_org(db, org.id)
    except Exception as exc:
        logger.warning(
            "COA seeding failed for org %s: %s", org.id, exc
        )

    return {
        "organisation_id": str(org.id),
        "organisation_name": name,
        "plan_id": str(plan_id),
        "admin_user_id": str(admin_user.id),
        "admin_email": admin_email,
        "invitation_expires_at": expires_at,
    }


async def _sync_org_modules_from_plan(
    db: AsyncSession,
    org_id: uuid.UUID,
    enabled_modules: list[str],
) -> None:
    """Sync a single org's org_modules from a plan's enabled_modules list.

    Called during org provisioning to seed the initial module set.
    """
    from app.core.modules import CORE_MODULES
    from app.modules.module_management.models import OrgModule

    for slug in enabled_modules:
        if slug in CORE_MODULES:
            continue
        db.add(OrgModule(
            org_id=org_id,
            module_slug=slug,
            is_enabled=True,
        ))
    await db.flush()


# ---------------------------------------------------------------------------
# Global Admin user creation
# ---------------------------------------------------------------------------


async def create_global_admin(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    first_name: str | None = None,
    last_name: str | None = None,
    created_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Create a new global_admin user.

    - Validates email uniqueness
    - Hashes password with bcrypt
    - Creates user with role=global_admin, org_id=NULL
    - Writes audit log
    - Returns user details

    Raises ``ValueError`` on validation failures.
    """
    from app.modules.auth.password import hash_password

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ValueError("A user with this email already exists")

    user = User(
        email=email,
        password_hash=hash_password(password),
        role="global_admin",
        org_id=None,
        first_name=first_name,
        last_name=last_name,
        is_active=True,
        is_email_verified=True,  # Admin-created, no verification needed
    )
    db.add(user)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=created_by,
        action="create_global_admin",
        entity_type="user",
        entity_id=user.id,
        after_value={"email": email, "role": "global_admin"},
        ip_address=ip_address,
    )

    logger.info("Global admin created: %s by %s", email, created_by)

    return {
        "message": "Global admin user created successfully",
        "user_id": str(user.id),
        "email": email,
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
_DEFAULT_CARJAM_ABCD_PER_LOOKUP_COST_NZD = 0.05


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
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Failed to read Carjam per-lookup cost from integration_configs; using default: %s", exc)
        return _DEFAULT_CARJAM_PER_LOOKUP_COST_NZD


async def get_carjam_abcd_per_lookup_cost(db: AsyncSession) -> float:
    """Return the ABCD per-lookup cost from integration_configs.

    Falls back to the default (0.05) if not configured.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    config = result.scalar_one_or_none()
    if config is None:
        return _DEFAULT_CARJAM_ABCD_PER_LOOKUP_COST_NZD

    try:
        decrypted = envelope_decrypt_str(config.config_encrypted)
        data = json.loads(decrypted)
        return float(data.get("abcd_per_lookup_cost_nzd", _DEFAULT_CARJAM_ABCD_PER_LOOKUP_COST_NZD))
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Failed to read Carjam ABCD per-lookup cost; using default: %s", exc)
        return _DEFAULT_CARJAM_ABCD_PER_LOOKUP_COST_NZD


def compute_carjam_overage(total_lookups: int, included: int) -> int:
    """Return the number of overage lookups (clamped to >= 0)."""
    return max(0, total_lookups - included)

def compute_sms_overage(total_sent: int, included_quota: int) -> int:
    """Return the number of SMS overage messages (clamped to >= 0)."""
    return max(0, total_sent - included_quota)


async def get_effective_sms_quota(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Return the effective SMS quota for an organisation.

    If the plan has ``sms_included`` set to False, the effective quota is 0
    regardless of stored quota or purchased package credits.

    Otherwise the effective quota is ``sms_included_quota`` from the plan plus
    the sum of ``credits_remaining`` across all SMS package purchases.

    Requirements: 3.3, 3.4, 1.7.
    """
    from sqlalchemy import func as sa_func

    # Fetch the org's plan
    stmt = (
        select(SubscriptionPlan)
        .join(Organisation, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()

    if plan is None:
        return 0

    if not plan.sms_included:
        return 0

    # Sum credits_remaining from all SMS package purchases for this org
    pkg_stmt = select(sa_func.coalesce(sa_func.sum(SmsPackagePurchase.credits_remaining), 0)).where(
        SmsPackagePurchase.org_id == org_id
    )
    pkg_result = await db.execute(pkg_stmt)
    total_package_credits = int(pkg_result.scalar())

    return plan.sms_included_quota + total_package_credits

async def _get_provider_per_sms_cost(db: AsyncSession) -> float:
    """Return per-SMS cost from the active Connexus provider config.

    Falls back to 0.0 if no active provider or no cost configured.
    """
    result = await db.execute(
        select(SmsVerificationProvider.config).where(
            SmsVerificationProvider.provider_key == "connexus",
            SmsVerificationProvider.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if config and isinstance(config, dict):
        try:
            return float(config.get("per_sms_cost_nzd", 0))
        except (TypeError, ValueError):
            pass
    return 0.0

async def get_sms_per_message_cost(db: AsyncSession) -> float:
    """Return per-SMS cost for the organisation's plan or provider config.

    Public wrapper used by reports module. Falls back to provider config cost.
    """
    return await _get_provider_per_sms_cost(db)



async def _count_org_sms_this_month(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Count ALL outbound SMS for an org in the current calendar month.

    Combines two sources of truth (raw SQL to bypass RLS on both tables):
    - ``sms_messages``    — chat/conversation sends (direction='outbound')
    - ``notification_log`` — notification, reminder, booking & payment SMS
                             (channel='sms', status NOT 'failed')

    These two tables are mutually exclusive: chat sends only write to
    ``sms_messages``; all other SMS paths only write to ``notification_log``.
    """
    from datetime import date as _date, datetime as _dt, timezone as _tz
    from sqlalchemy import text as _text

    now = _dt.now(_tz.utc)
    month_start = _dt.combine(
        _date(now.year, now.month, 1), _dt.min.time(), tzinfo=_tz.utc,
    )

    result = await db.execute(
        _text(
            "SELECT "
            "  (SELECT COUNT(*) FROM sms_messages "
            "   WHERE org_id = :oid AND direction = 'outbound' "
            "   AND created_at >= :start) "
            "+ (SELECT COUNT(*) FROM notification_log "
            "   WHERE org_id = :oid AND channel = 'sms' "
            "   AND status != 'failed' "
            "   AND created_at >= :start) "
            "AS total"
        ),
        {"oid": str(org_id), "start": month_start},
    )
    return int(result.scalar() or 0)


async def get_all_orgs_sms_usage(db: AsyncSession) -> tuple[list[dict], float]:
    """Return SMS usage data for every non-deleted organisation.

    Each dict contains: organisation_id, organisation_name, total_sent,
    included_in_plan, package_credits_remaining, effective_quota,
    overage_count, overage_charge_nzd.

    Returns a tuple of (usage_list, 0.0) to mirror the carjam usage signature.

    Requirements: 2.6, 2.7.
    """
    from sqlalchemy import func as sa_func

    # Get provider-level per-SMS cost as fallback
    provider_cost = await _get_provider_per_sms_cost(db)

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
        total_sent = await _count_org_sms_this_month(db, org.id)
        included_in_plan = plan.sms_included_quota if plan.sms_included else 0
        per_sms_cost = float(plan.per_sms_cost_nzd) or provider_cost

        # Sum credits_remaining from all SMS package purchases for this org
        pkg_stmt = select(
            sa_func.coalesce(sa_func.sum(SmsPackagePurchase.credits_remaining), 0)
        ).where(SmsPackagePurchase.org_id == org.id)
        pkg_result = await db.execute(pkg_stmt)
        package_credits = int(pkg_result.scalar())

        effective_quota = (included_in_plan + package_credits) if plan.sms_included else 0
        overage = compute_sms_overage(total_sent, effective_quota)

        usage_list.append({
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "total_sent": total_sent,
            "included_in_plan": included_in_plan,
            "package_credits_remaining": package_credits,
            "effective_quota": effective_quota,
            "overage_count": overage,
            "overage_charge_nzd": round(overage * per_sms_cost, 2),
        })

    return usage_list, 0.0


async def get_org_sms_usage(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Return SMS usage data for a single organisation.

    Requirements: 2.6.
    """
    from sqlalchemy import func as sa_func

    # Get provider-level per-SMS cost as fallback
    provider_cost = await _get_provider_per_sms_cost(db)

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
    total_sent = await _count_org_sms_this_month(db, org_id)
    included_in_plan = plan.sms_included_quota if plan.sms_included else 0
    per_sms_cost = float(plan.per_sms_cost_nzd) or provider_cost

    # Sum credits_remaining from all SMS package purchases for this org
    pkg_stmt = select(
        sa_func.coalesce(sa_func.sum(SmsPackagePurchase.credits_remaining), 0)
    ).where(SmsPackagePurchase.org_id == org_id)
    pkg_result = await db.execute(pkg_stmt)
    package_credits = int(pkg_result.scalar())

    effective_quota = (included_in_plan + package_credits) if plan.sms_included else 0
    overage = compute_sms_overage(total_sent, effective_quota)

    return {
        "organisation_id": str(org.id),
        "organisation_name": org.name,
        "total_sent": total_sent,
        "included_in_plan": included_in_plan,
        "package_credits_remaining": package_credits,
        "effective_quota": effective_quota,
        "overage_count": overage,
        "overage_charge_nzd": round(overage * per_sms_cost, 2),
        "per_sms_cost_nzd": per_sms_cost,
    }


async def increment_sms_usage(db: AsyncSession, org_id: uuid.UUID) -> None:
    """Atomically increment sms_sent_this_month by 1 for the given org.

    Uses a SQL-level expression so the increment is safe under concurrent
    dispatches (no read-modify-write race).

    Requirements: 2.3.
    """
    stmt = (
        update(Organisation)
        .where(Organisation.id == org_id)
        .values(sms_sent_this_month=Organisation.sms_sent_this_month + 1)
    )
    await db.execute(stmt)
    await db.flush()

async def purchase_sms_package(
    db: AsyncSession, org_id: uuid.UUID, tier_name: str
) -> dict:
    """Purchase an SMS package for an organisation.

    1. Query the org's plan to get ``sms_package_pricing``.
    2. Find the tier matching *tier_name* in the pricing array.
    3. If not found, raise ``ValueError``.
    4. Create a Stripe one-time charge via ``PaymentIntent``.
    5. On success, create an ``SmsPackagePurchase`` record.
    6. On Stripe failure, raise ``RuntimeError`` without creating a record.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7.
    """
    import stripe as stripe_lib

    stripe_lib.api_key = settings.stripe_secret_key

    # 1. Fetch the org and its plan
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

    # 2. Find the matching tier in sms_package_pricing
    tiers = plan.sms_package_pricing or []
    matched_tier = None
    for tier in tiers:
        if tier.get("tier_name") == tier_name:
            matched_tier = tier
            break

    if matched_tier is None:
        raise ValueError("SMS package tier not found on plan")

    sms_quantity = matched_tier["sms_quantity"]
    price_nzd = float(matched_tier["price_nzd"])

    # 3. Validate org has a Stripe customer ID
    if not org.stripe_customer_id:
        raise ValueError(
            "No payment method on file. Please add a payment method before purchasing SMS packages."
        )

    # 4. Create Stripe one-time charge
    charge_amount_cents = int(price_nzd * 100)
    try:
        payment_intent = stripe_lib.PaymentIntent.create(
            amount=charge_amount_cents,
            currency="nzd",
            customer=org.stripe_customer_id,
            confirm=True,
            automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
            description=f"SMS package: {tier_name} ({sms_quantity} SMS) for {org.name}",
            metadata={
                "platform": "workshoppro_nz",
                "org_id": str(org_id),
                "type": "sms_package",
                "tier_name": tier_name,
                "sms_quantity": str(sms_quantity),
            },
        )
    except stripe_lib.error.CardError as exc:
        raise RuntimeError(f"Payment failed: {exc.user_message}") from exc
    except stripe_lib.error.StripeError as exc:
        raise RuntimeError(f"Stripe error: {str(exc)}") from exc

    # 5. Create SmsPackagePurchase record
    now = datetime.now(timezone.utc)
    purchase = SmsPackagePurchase(
        org_id=org_id,
        tier_name=tier_name,
        sms_quantity=sms_quantity,
        price_nzd=price_nzd,
        credits_remaining=sms_quantity,
        purchased_at=now,
    )
    db.add(purchase)
    await db.flush()

    return {
        "id": str(purchase.id),
        "tier_name": purchase.tier_name,
        "sms_quantity": purchase.sms_quantity,
        "price_nzd": float(purchase.price_nzd),
        "credits_remaining": purchase.credits_remaining,
        "purchased_at": purchase.purchased_at.isoformat(),
        "stripe_payment_intent_id": payment_intent.id,
    }


async def get_org_sms_packages(
    db: AsyncSession, org_id: uuid.UUID
) -> list[dict]:
    """Return active SMS package purchases for an organisation.

    Packages are ordered by ``purchased_at ASC`` (oldest first) to support
    FIFO credit deduction.

    Requirements: 6.5.
    """
    stmt = (
        select(SmsPackagePurchase)
        .where(SmsPackagePurchase.org_id == org_id)
        .where(SmsPackagePurchase.credits_remaining > 0)
        .order_by(SmsPackagePurchase.purchased_at.asc())
    )
    result = await db.execute(stmt)
    packages = result.scalars().all()

    return [
        {
            "id": str(pkg.id),
            "tier_name": pkg.tier_name,
            "sms_quantity": pkg.sms_quantity,
            "price_nzd": float(pkg.price_nzd),
            "credits_remaining": pkg.credits_remaining,
            "purchased_at": pkg.purchased_at.isoformat(),
        }
        for pkg in packages
    ]

async def compute_sms_overage_for_billing(
    db: AsyncSession, org_id: uuid.UUID
) -> dict:
    """Calculate SMS overage for a billing renewal, applying FIFO credit deduction.

    Steps:
    1. Query the org's plan for ``sms_included``, ``sms_included_quota``,
       ``per_sms_cost_nzd``.
    2. If ``sms_included`` is False, return zeros (no SMS billing).
    3. Get the org's ``sms_sent_this_month``.
    4. Compute ``raw_overage = max(0, sms_sent_this_month - sms_included_quota)``.
    5. Query all ``sms_package_purchases`` for the org ordered by
       ``purchased_at ASC`` (FIFO).
    6. Iterate packages oldest-first, deducting
       ``min(raw_overage, credits_remaining)`` from both ``raw_overage`` and
       the package's ``credits_remaining`` (persisted to DB).
    7. Return dict with ``overage_count``, ``per_sms_cost_nzd``,
       ``total_charge_nzd``.

    Requirements: 4.1, 4.2, 4.3.
    """
    # 1. Fetch the org and its plan
    stmt = (
        select(Organisation, SubscriptionPlan)
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.id == org_id)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()

    if row is None:
        return {
            "overage_count": 0,
            "per_sms_cost_nzd": 0.0,
            "total_charge_nzd": 0.0,
        }

    org, plan = row

    # 2. If sms_included is False, no SMS billing applies
    if not plan.sms_included:
        return {
            "overage_count": 0,
            "per_sms_cost_nzd": 0.0,
            "total_charge_nzd": 0.0,
        }

    per_sms_cost = float(plan.per_sms_cost_nzd) or await _get_provider_per_sms_cost(db)
    sms_included_quota = plan.sms_included_quota

    # 3. Count outbound SMS from sms_messages for the current month.
    #    This is the source of truth — survives counter resets and restarts.
    total_sent = await _count_org_sms_this_month(db, org_id)

    # 4. Compute raw overage against plan quota only
    raw_overage = max(0, total_sent - sms_included_quota)

    # 5. Query all SMS package purchases for FIFO deduction (oldest first)
    pkg_stmt = (
        select(SmsPackagePurchase)
        .where(SmsPackagePurchase.org_id == org_id)
        .where(SmsPackagePurchase.credits_remaining > 0)
        .order_by(SmsPackagePurchase.purchased_at.asc())
    )
    pkg_result = await db.execute(pkg_stmt)
    packages = pkg_result.scalars().all()

    # 6. FIFO deduction: consume credits from oldest package first
    for pkg in packages:
        if raw_overage <= 0:
            break
        deduction = min(raw_overage, pkg.credits_remaining)
        pkg.credits_remaining -= deduction
        raw_overage -= deduction

    await db.flush()

    # 7. Return billing summary
    overage_count = raw_overage
    return {
        "overage_count": overage_count,
        "per_sms_cost_nzd": per_sms_cost,
        "total_charge_nzd": round(overage_count * per_sms_cost, 2),
    }




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

    # SSRF protection: validate the SMTP host is not a private/internal address
    if host:
        from app.core.url_validation import validate_url_for_ssrf

        ok, reason = validate_url_for_ssrf(f"https://{host}")
        if not ok:
            raise ValueError(f"SMTP host rejected: {reason}")

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
    custom_message: str | None = None,
    admin_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Send a test SMS to verify SMS provider config.

    Resolves the active Connexus provider, decrypts credentials, and sends
    a test message via ConnexusSmsClient.
    Requirement 36.1.
    """
    from app.core.encryption import envelope_decrypt_str
    from app.integrations.connexus_sms import ConnexusConfig, ConnexusSmsClient
    from app.integrations.sms_types import SmsMessage
    from sqlalchemy import select as sa_select

    stmt = sa_select(SmsVerificationProvider).where(
        SmsVerificationProvider.provider_key == "connexus",
        SmsVerificationProvider.is_active == True,
    )
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()

    if provider is None or not provider.credentials_encrypted:
        return {
            "success": False,
            "message": "Connexus SMS provider not configured or not active",
            "error": "Connexus SMS provider not configured or active",
        }

    creds = json.loads(envelope_decrypt_str(provider.credentials_encrypted))
    if provider.config and provider.config.get("token_refresh_interval_seconds"):
        creds["token_refresh_interval_seconds"] = provider.config["token_refresh_interval_seconds"]
    config = ConnexusConfig.from_dict(creds)
    client = ConnexusSmsClient(config)

    test_body = custom_message or "OraInvoice test SMS — Connexus integration verified."
    sms = SmsMessage(to_number=to_number, body=test_body)
    send_result = await client.send(sms)

    if send_result.success:
        return {
            "success": True,
            "message": f"Test SMS sent to {to_number}",
            "message_sid": send_result.message_sid,
        }

    return {
        "success": False,
        "message": "Failed to send test SMS",
        "error": send_result.error or "Unknown SMS send error",
    }


# ---------------------------------------------------------------------------
# Carjam integration configuration (Req 48.3)
# ---------------------------------------------------------------------------


async def save_carjam_config(
    db: AsyncSession,
    *,
    api_key: str | None = None,
    endpoint_url: str | None = None,
    per_lookup_cost_nzd: float | None = None,
    abcd_per_lookup_cost_nzd: float | None = None,
    global_rate_limit_per_minute: int | None = None,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Save or update the platform-wide Carjam configuration.

    Stores encrypted in ``integration_configs`` with name='carjam'.
    Only updates fields that are provided (not None).
    Returns non-secret config fields.
    Requirement 48.3.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_encrypt, envelope_decrypt

    # Load existing config
    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "carjam")
    )
    existing = result.scalar_one_or_none()

    # Get current values or defaults
    if existing:
        current_data = json.loads(envelope_decrypt(existing.config_encrypted))
    else:
        current_data = {
            "api_key": "",
            "endpoint_url": "https://www.carjam.co.nz",
            "per_lookup_cost_nzd": 0.50,
            "abcd_per_lookup_cost_nzd": 0.05,
            "global_rate_limit_per_minute": 60,
        }

    # SSRF protection: validate the endpoint URL before persisting
    if endpoint_url is not None:
        from app.core.url_validation import validate_url_for_ssrf

        ok, reason = validate_url_for_ssrf(endpoint_url)
        if not ok:
            raise ValueError(f"Carjam endpoint URL rejected: {reason}")

    # Update only provided fields
    if api_key is not None:
        current_data["api_key"] = api_key
    if endpoint_url is not None:
        current_data["endpoint_url"] = endpoint_url
    if per_lookup_cost_nzd is not None:
        current_data["per_lookup_cost_nzd"] = per_lookup_cost_nzd
    if abcd_per_lookup_cost_nzd is not None:
        current_data["abcd_per_lookup_cost_nzd"] = abcd_per_lookup_cost_nzd
    if global_rate_limit_per_minute is not None:
        current_data["global_rate_limit_per_minute"] = global_rate_limit_per_minute

    # Encrypt and save
    config_data = json.dumps(current_data)
    encrypted = envelope_encrypt(config_data)

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

    # Audit log with updated values
    audit_data = {
        "ip_address": ip_address,
    }
    if api_key is not None:
        audit_data["api_key_last4"] = api_key[-4:] if len(api_key) >= 4 else api_key
    if endpoint_url is not None:
        audit_data["endpoint_url"] = endpoint_url
    if per_lookup_cost_nzd is not None:
        audit_data["per_lookup_cost_nzd"] = per_lookup_cost_nzd
    if abcd_per_lookup_cost_nzd is not None:
        audit_data["abcd_per_lookup_cost_nzd"] = abcd_per_lookup_cost_nzd
    if global_rate_limit_per_minute is not None:
        audit_data["global_rate_limit_per_minute"] = global_rate_limit_per_minute

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=updated_by,
        action="admin.carjam_config_updated",
        entity_type="integration_config",
        entity_id=None,
        after_value=audit_data,
        ip_address=ip_address,
    )

    return {
        "endpoint_url": current_data["endpoint_url"],
        "per_lookup_cost_nzd": current_data["per_lookup_cost_nzd"],
        "abcd_per_lookup_cost_nzd": current_data.get("abcd_per_lookup_cost_nzd", 0.05),
        "global_rate_limit_per_minute": current_data["global_rate_limit_per_minute"],
        "api_key_last4": current_data["api_key"][-4:] if len(current_data["api_key"]) >= 4 else current_data["api_key"],
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
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.error("Failed to decrypt Carjam configuration: %s", exc, exc_info=True)
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
    except (ConnectionError, OSError, ValueError) as exc:
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
    platform_account_id: str | None = None,
    webhook_endpoint: str | None = None,
    signing_secret: str | None = None,
    publishable_key: str | None = None,
    secret_key: str | None = None,
    connect_client_id: str | None = None,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Save or update the platform-wide Global Stripe configuration.

    Stores encrypted in ``integration_configs`` with name='stripe'.
    Supports partial updates — only provided fields are overwritten.
    Returns non-secret config fields.
    Requirement 48.4.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_encrypt, envelope_decrypt_str

    # Load existing config to merge with
    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
    )
    existing = result.scalar_one_or_none()

    old_config: dict = {}
    if existing is not None:
        try:
            old_config = json.loads(envelope_decrypt_str(existing.config_encrypted))
        except Exception:
            pass

    # Merge: new values override old, missing values preserved
    final_platform_account_id = platform_account_id or old_config.get("platform_account_id", "")
    final_webhook_endpoint = webhook_endpoint or old_config.get("webhook_endpoint", "")

    # SSRF protection: validate the webhook endpoint URL before persisting
    if webhook_endpoint:
        from app.core.url_validation import validate_url_for_ssrf

        ok, reason = validate_url_for_ssrf(webhook_endpoint)
        if not ok:
            raise ValueError(f"Stripe webhook endpoint rejected: {reason}")

    config_data_dict: dict = {
        "platform_account_id": final_platform_account_id,
        "webhook_endpoint": final_webhook_endpoint,
        "signing_secret": signing_secret or old_config.get("signing_secret", ""),
        "publishable_key": publishable_key or old_config.get("publishable_key", ""),
        "secret_key": secret_key or old_config.get("secret_key", ""),
        "connect_client_id": connect_client_id or old_config.get("connect_client_id", ""),
    }

    config_data = json.dumps(config_data_dict)
    encrypted = envelope_encrypt(config_data)

    if existing is not None:
        existing.config_encrypted = encrypted
        # Only reset verification when the critical auth fields change.
        key_changed = (
            config_data_dict.get("secret_key") != old_config.get("secret_key", "")
            or config_data_dict.get("platform_account_id") != old_config.get("platform_account_id", "")
        )
        if key_changed:
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
            "platform_account_last4": final_platform_account_id[-4:] if len(final_platform_account_id) >= 4 else final_platform_account_id,
            "webhook_endpoint": final_webhook_endpoint,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    # Determine current verified state after potential update
    current_verified = False
    if existing is not None:
        current_verified = existing.is_verified

    return {
        "platform_account_last4": final_platform_account_id[-4:] if len(final_platform_account_id) >= 4 else final_platform_account_id,
        "webhook_endpoint": final_webhook_endpoint,
        "is_verified": current_verified,
        "connect_client_id_last4": config_data_dict["connect_client_id"][-4:] if len(config_data_dict["connect_client_id"]) >= 4 else config_data_dict["connect_client_id"],
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
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.error("Failed to decrypt Stripe configuration: %s", exc, exc_info=True)
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

        # Use stored secret key if available, fall back to env var
        stored_secret_key = config.get("secret_key", "")
        stripe_lib.api_key = stored_secret_key or (settings.stripe_secret_key if hasattr(settings, "stripe_secret_key") else "")

        if not stripe_lib.api_key:
            return {
                "success": False,
                "message": "No Stripe secret key configured. Add your secret key (sk_test_... or sk_live_...) in the Stripe settings.",
                "error": "Missing secret key",
            }

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


async def test_stripe_api_keys(
    db: AsyncSession,
    *,
    admin_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Test the Stripe API keys by retrieving the account balance.

    Uses the stored secret key (with env var fallback) to verify API access.
    """
    from app.modules.admin.models import IntegrationConfig
    from app.core.encryption import envelope_decrypt_str

    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.name == "stripe")
    )
    config_row = result.scalar_one_or_none()

    stored_secret_key = ""
    if config_row is not None:
        try:
            config = json.loads(envelope_decrypt_str(config_row.config_encrypted))
            stored_secret_key = config.get("secret_key", "")
        except Exception:
            pass

    api_key = stored_secret_key or (settings.stripe_secret_key if hasattr(settings, "stripe_secret_key") else "")

    if not api_key:
        return {
            "success": False,
            "message": "No Stripe secret key configured. Enter your secret key (sk_test_... or sk_live_...) and save first.",
            "error": "Missing secret key",
        }

    try:
        import stripe as stripe_lib
        stripe_lib.api_key = api_key
        balance = stripe_lib.Balance.retrieve()

        # Stripe v15+ returns proper objects, not dicts
        balance_object = getattr(balance, "object", None) or (balance.get("object") if hasattr(balance, "get") else None)
        if balance and balance_object == "balance":
            is_test = api_key.startswith("sk_test_")
            mode = "test mode" if is_test else "live mode"
            return {
                "success": True,
                "message": f"Stripe API keys verified successfully ({mode}).",
                "error": None,
            }
        else:
            return {
                "success": False,
                "message": "Unexpected response from Stripe API.",
                "error": "Invalid response",
            }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Stripe API key test failed: {exc}",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Generic integration config retrieval (Req 48.1, 48.5)
# ---------------------------------------------------------------------------

# Maps integration name → list of fields safe to return (non-secret)
_SAFE_FIELDS: dict[str, list[str]] = {
    "carjam": ["endpoint_url", "per_lookup_cost_nzd", "abcd_per_lookup_cost_nzd", "global_rate_limit_per_minute"],
    "stripe": ["webhook_endpoint"],
    "smtp": ["provider", "domain", "from_email", "from_name", "reply_to", "host", "port"],
    "twilio": ["sender_number"],
}

# Maps integration name → list of fields to show as masked (last 4 chars)
_MASKED_FIELDS: dict[str, list[str]] = {
    "carjam": ["api_key"],
    "stripe": ["platform_account_id", "signing_secret", "publishable_key", "secret_key", "connect_client_id"],
    "smtp": ["api_key"],
    "twilio": ["account_sid", "auth_token"],
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
            "fields": {},
        }

    try:
        config = json.loads(envelope_decrypt_str(config_row.config_encrypted))
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.error("Failed to decrypt integration config '%s': %s", name, exc, exc_info=True)
        return {
            "name": name,
            "is_verified": config_row.is_verified,
            "updated_at": config_row.updated_at.isoformat() if config_row.updated_at else None,
            "fields": {},
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
        "fields": safe_config,
    }


# ---------------------------------------------------------------------------
# Subscription Plan Management (Req 40.1, 40.2, 40.3, 40.4)
# ---------------------------------------------------------------------------


def _build_intervals_from_config(
    interval_config: list[dict],
    monthly_price_nzd: float,
) -> list[dict]:
    """Compute IntervalPricing dicts from a plan's interval_config and base price."""
    base = Decimal(str(monthly_price_nzd))
    intervals = []
    for item in interval_config:
        interval = item.get("interval", "monthly")
        discount = Decimal(str(item.get("discount_percent", 0)))
        effective = compute_effective_price(base, interval, discount)
        savings = compute_savings_amount(base, interval, discount)
        eq_monthly = compute_equivalent_monthly(effective, interval)
        intervals.append({
            "interval": interval,
            "enabled": item.get("enabled", False),
            "discount_percent": float(discount),
            "effective_price": float(effective),
            "savings_amount": float(savings),
            "equivalent_monthly": float(eq_monthly),
        })
    return intervals


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
    trial_duration: int = 0,
    trial_duration_unit: str = "days",
    sms_included: bool = False,
    per_sms_cost_nzd: float = 0,
    sms_included_quota: int = 0,
    sms_package_pricing: list[dict] | None = None,
    interval_config: list[dict] | None = None,
    created_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new subscription plan.

    Requirement 40.1: plan name, monthly price (NZD), user seats,
    storage quota, Carjam lookups, enabled modules.
    Requirement 40.2: public/private plans.
    Requirement 40.4: storage tier pricing.
    Requirement 1.3, 1.4, 5.3: SMS pricing fields.
    """
    # Check for duplicate plan name
    existing = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.name == name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"A plan with name '{name}' already exists")

    # Validate or default interval_config
    if interval_config is None:
        resolved_interval_config = build_default_interval_config()
    else:
        resolved_interval_config = validate_interval_config(interval_config)

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
        trial_duration=trial_duration,
        trial_duration_unit=trial_duration_unit,
        sms_included=sms_included,
        per_sms_cost_nzd=per_sms_cost_nzd,
        sms_included_quota=sms_included_quota,
        sms_package_pricing=sms_package_pricing or [],
        interval_config=resolved_interval_config,
    )
    db.add(plan)
    await db.flush()

    await write_audit_log(
        db,
        action="plan.created",
        user_id=created_by,
        ip_address=ip_address,
        entity_type="subscription_plan",
        entity_id=plan.id,
        after_value={"plan_name": name, "monthly_price_nzd": monthly_price_nzd},
    )

    logger.info("Created subscription plan %s (%s)", plan.id, name)

    # Refresh server-generated timestamps to avoid MissingGreenlet on
    # lazy load in async context.
    await db.refresh(plan, ["created_at", "updated_at"])

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
        "trial_duration": plan.trial_duration or 0,
        "trial_duration_unit": plan.trial_duration_unit or "days",
        "sms_included": plan.sms_included,
        "per_sms_cost_nzd": float(plan.per_sms_cost_nzd),
        "sms_included_quota": plan.sms_included_quota,
        "sms_package_pricing": plan.sms_package_pricing or [],
        "interval_config": plan.interval_config or [],
        "intervals": _build_intervals_from_config(
            plan.interval_config or [], float(plan.monthly_price_nzd)
        ),
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
            "trial_duration": p.trial_duration or 0,
            "trial_duration_unit": p.trial_duration_unit or "days",
            "sms_included": p.sms_included,
            "interval_config": p.interval_config or [],
            "intervals": _build_intervals_from_config(
                p.interval_config or [], float(p.monthly_price_nzd)
            ),
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
        "trial_duration": p.trial_duration or 0,
        "trial_duration_unit": p.trial_duration_unit or "days",
        "sms_included": p.sms_included,
        "interval_config": p.interval_config or [],
        "intervals": _build_intervals_from_config(
            p.interval_config or [], float(p.monthly_price_nzd)
        ),
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


async def _sync_plan_modules_to_orgs(
    db: AsyncSession,
    plan_id: uuid.UUID,
    enabled_modules: list[str],
) -> None:
    """Sync a plan's enabled_modules to the org_modules table for every org on that plan.

    This does NOT force-enable or force-disable modules. It only ensures that
    modules newly added to the plan get an org_modules row (disabled by default)
    so they appear as "available" in the org admin's module configuration page.
    Modules removed from the plan are left as-is (the frontend uses in_plan to
    gate the toggle). Org admin enable/disable choices are always preserved.
    """
    from app.core.modules import CORE_MODULES, ModuleService
    from app.modules.module_management.models import OrgModule

    # Find all orgs on this plan
    result = await db.execute(
        select(Organisation.id).where(Organisation.plan_id == plan_id)
    )
    org_ids = [row[0] for row in result.all()]
    if not org_ids:
        return

    plan_modules = set(enabled_modules)

    for org_id in org_ids:
        org_id_str = str(org_id)

        # Get existing org_module rows
        stmt = select(OrgModule).where(OrgModule.org_id == org_id)
        result = await db.execute(stmt)
        existing = {om.module_slug: om for om in result.scalars().all()}

        # Add rows for newly available modules (disabled by default so org admin can choose)
        for slug in plan_modules:
            if slug in CORE_MODULES:
                continue
            if slug not in existing:
                db.add(OrgModule(
                    org_id=org_id,
                    module_slug=slug,
                    is_enabled=False,
                ))

        await db.flush()

        # Invalidate module cache for this org
        svc = ModuleService(db)
        await svc._invalidate_cache(org_id_str)

    logger.info(
        "Synced plan module availability from plan %s to %d org(s)",
        plan_id, len(org_ids),
    )


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
        "storage_tier_pricing", "trial_duration", "trial_duration_unit",
        "sms_included", "per_sms_cost_nzd", "sms_included_quota",
        "sms_package_pricing", "interval_config",
    }

    # Validate interval_config if provided
    if "interval_config" in updates and updates["interval_config"] is not None:
        updates["interval_config"] = validate_interval_config(updates["interval_config"])

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
        action="plan.updated",
        user_id=updated_by,
        ip_address=ip_address,
        entity_type="subscription_plan",
        entity_id=plan.id,
        before_value=_serialise_audit(before),
        after_value=_serialise_audit(after),
    )

    logger.info("Updated subscription plan %s", plan.id)

    # If enabled_modules changed, sync to all orgs on this plan
    if "enabled_modules" in after:
        await _sync_plan_modules_to_orgs(db, plan_id, plan.enabled_modules)

    # Refresh timestamps — onupdate=func.now() expires updated_at after
    # flush, and accessing it would trigger a lazy load that fails in
    # async context (MissingGreenlet).
    await db.refresh(plan, ["created_at", "updated_at"])

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
        "trial_duration": plan.trial_duration or 0,
        "trial_duration_unit": plan.trial_duration_unit or "days",
        "sms_included": plan.sms_included,
        "per_sms_cost_nzd": float(plan.per_sms_cost_nzd),
        "sms_included_quota": plan.sms_included_quota,
        "sms_package_pricing": plan.sms_package_pricing or [],
        "interval_config": plan.interval_config or [],
        "intervals": _build_intervals_from_config(
            plan.interval_config or [], float(plan.monthly_price_nzd)
        ),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def _serialise_audit(data: dict) -> dict:
    """Make audit log values JSON-serialisable."""
    from decimal import Decimal
    
    out = {}
    for k, v in data.items():
        if isinstance(v, (datetime,)):
            out[k] = v.isoformat()
        elif isinstance(v, (uuid.UUID,)):
            out[k] = str(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
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
        action="plan.archived",
        user_id=archived_by,
        ip_address=ip_address,
        entity_type="subscription_plan",
        entity_id=plan.id,
        after_value={"plan_name": plan.name},
    )

    logger.info("Archived subscription plan %s (%s)", plan.id, plan.name)

    # Refresh server-generated timestamps to avoid MissingGreenlet on
    # lazy load in async context.
    await db.refresh(plan, ["created_at", "updated_at"])

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
        "trial_duration": plan.trial_duration or 0,
        "trial_duration_unit": plan.trial_duration_unit or "days",
        "sms_included": plan.sms_included,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


async def delete_plan(
    db: AsyncSession,
    plan_id: uuid.UUID,
    *,
    deleted_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Permanently delete a subscription plan.

    Fails if any organisation is currently subscribed to this plan.
    """
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Plan not found")

    # Check if any org is using this plan
    from app.modules.admin.models import Organisation
    sub_count = await db.execute(
        select(func.count()).select_from(Organisation).where(
            Organisation.plan_id == plan_id,
            Organisation.status != 'deleted',
        )
    )
    count = sub_count.scalar() or 0
    if count > 0:
        raise ValueError(
            f"Cannot delete plan — {count} organisation(s) are currently subscribed. "
            "Move them to another plan first, or archive this plan instead."
        )

    plan_name = plan.name
    await db.delete(plan)
    await db.flush()

    await write_audit_log(
        db,
        action="plan.deleted",
        user_id=deleted_by,
        ip_address=ip_address,
        entity_type="subscription_plan",
        entity_id=plan_id,
        after_value={"plan_name": plan_name},
    )

    logger.info("Permanently deleted subscription plan %s (%s)", plan_id, plan_name)

    return {"id": str(plan_id), "name": plan_name, "deleted": True}


# ---------------------------------------------------------------------------
# Global Admin Reports (Req 46.1–46.5)
# ---------------------------------------------------------------------------


async def get_mrr_report(db: AsyncSession) -> dict:
    """Platform MRR with plan breakdown, month-over-month trend, and interval breakdown.

    Requirement 46.2, 12.1, 12.2, 12.3: MRR normalised across billing intervals.
    Each org's MRR contribution is computed via normalise_to_mrr(effective_price, interval).
    """
    from sqlalchemy import func as sa_func, case, extract, literal_column
    from app.modules.billing.interval_pricing import (
        compute_effective_price as _compute_effective_price,
        normalise_to_mrr as _normalise_to_mrr,
    )

    # Fetch all active/trial orgs with their plan data for per-org MRR calculation
    org_stmt = (
        select(
            Organisation.id,
            Organisation.billing_interval,
            SubscriptionPlan.id.label("plan_id"),
            SubscriptionPlan.name.label("plan_name"),
            SubscriptionPlan.monthly_price_nzd,
            SubscriptionPlan.interval_config,
        )
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .where(Organisation.status.in_(["active", "trial", "grace_period"]))
    )
    org_result = await db.execute(org_stmt)
    org_rows = org_result.all()

    # Compute per-org MRR and aggregate by plan and interval
    plan_mrr: dict[str, dict] = {}  # plan_id -> {plan_name, active_orgs, mrr_nzd}
    interval_mrr: dict[str, dict] = {}  # interval -> {org_count, mrr_nzd}
    total_mrr = Decimal("0")

    for org_id, billing_interval, plan_id, plan_name, monthly_price, interval_config in org_rows:
        base_price = Decimal(str(monthly_price))
        interval = billing_interval or "monthly"

        # Find the discount for this org's billing interval from the plan's interval_config
        discount = Decimal("0")
        if interval_config:
            for ic in interval_config:
                if ic.get("interval") == interval and ic.get("enabled", False):
                    discount = Decimal(str(ic.get("discount_percent", 0)))
                    break

        # Compute effective price for this org's interval, then normalise to MRR
        effective = _compute_effective_price(base_price, interval, discount)
        org_mrr = _normalise_to_mrr(effective, interval)
        total_mrr += org_mrr

        # Aggregate by plan
        pid = str(plan_id)
        if pid not in plan_mrr:
            plan_mrr[pid] = {"plan_id": pid, "plan_name": plan_name, "active_orgs": 0, "mrr_nzd": Decimal("0")}
        plan_mrr[pid]["active_orgs"] += 1
        plan_mrr[pid]["mrr_nzd"] += org_mrr

        # Aggregate by interval
        if interval not in interval_mrr:
            interval_mrr[interval] = {"interval": interval, "org_count": 0, "mrr_nzd": Decimal("0")}
        interval_mrr[interval]["org_count"] += 1
        interval_mrr[interval]["mrr_nzd"] += org_mrr

    # Build plan breakdown sorted by name
    plan_breakdown = sorted(
        [
            {
                "plan_id": v["plan_id"],
                "plan_name": v["plan_name"],
                "active_orgs": v["active_orgs"],
                "mrr_nzd": round(float(v["mrr_nzd"]), 2),
            }
            for v in plan_mrr.values()
        ],
        key=lambda x: x["plan_name"],
    )

    # Build interval breakdown in canonical order
    interval_order = ["weekly", "fortnightly", "monthly", "annual"]
    interval_breakdown = [
        {
            "interval": iv,
            "org_count": interval_mrr[iv]["org_count"],
            "mrr_nzd": round(float(interval_mrr[iv]["mrr_nzd"]), 2),
        }
        for iv in interval_order
        if iv in interval_mrr
    ]

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
        "total_mrr_nzd": round(float(total_mrr), 2),
        "plan_breakdown": plan_breakdown,
        "month_over_month": month_over_month,
        "interval_breakdown": interval_breakdown,
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
    from app.modules.auth.models import User

    # Subquery: most recent last_login_at per org
    last_login_sq = (
        select(
            User.org_id,
            sa_func.max(User.last_login_at).label("last_login_at"),
        )
        .group_by(User.org_id)
        .subquery()
    )

    # Base query joining plan for plan_name and last_login subquery
    base_q = (
        select(
            Organisation,
            SubscriptionPlan.name.label("plan_name"),
            last_login_sq.c.last_login_at.label("last_login_at"),
        )
        .join(SubscriptionPlan, Organisation.plan_id == SubscriptionPlan.id)
        .outerjoin(last_login_sq, Organisation.id == last_login_sq.c.org_id)
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

    # Sorting — validate against allowlist (REM-21)
    validate_column_name("organisations", sort_by)
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
    for org, plan_name, last_login_at in rows:
        organisations.append({
            "id": str(org.id),
            "name": org.name,
            "plan_id": str(org.plan_id),
            "plan_name": plan_name,
            "status": org.status,
            "storage_quota_gb": org.storage_quota_gb,
            "storage_used_bytes": org.storage_used_bytes,
            "carjam_lookups_this_month": org.carjam_lookups_this_month,
            "next_billing_date": org.next_billing_date,
            "billing_interval": getattr(org, "billing_interval", "monthly") or "monthly",
            "last_login_at": last_login_at.isoformat() if last_login_at else None,
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
    next_billing_date: str | None = None,
    notify_org_admin: bool = False,
    updated_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Update an organisation: suspend, reinstate, activate, deactivate, delete_request, hard_delete_request, or move_plan.

    For ``delete_request`` and ``hard_delete_request``, generates a confirmation token (step 1 of multi-step delete).
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

    valid_actions = ("suspend", "reinstate", "activate", "deactivate", "delete_request", "hard_delete_request", "move_plan", "set_billing_date")
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

    elif action == "activate":
        if org.status == "active":
            raise ValueError("Organisation is already active")
        if org.status == "deleted":
            raise ValueError("Cannot activate a deleted organisation. Create a new organisation instead.")

        org.status = "active"
        await db.flush()

        await write_audit_log(
            session=db,
            user_id=updated_by,
            action="org.activated",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": previous_status},
            after_value={"status": "active"},
            ip_address=ip_address,
        )

        if notify_org_admin:
            await _notify_org_admin_status_change(db, org, "activated", None)

        return {
            "message": "Organisation activated",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "previous_status": previous_status,
        }

    elif action == "deactivate":
        if not reason:
            raise ValueError("Reason is required when deactivating an organisation")
        if org.status == "suspended":
            raise ValueError("Organisation is already suspended (use suspend/reinstate for temporary suspension)")
        if org.status == "deleted":
            raise ValueError("Organisation is already deleted")

        org.status = "suspended"
        await db.flush()

        await write_audit_log(
            session=db,
            user_id=updated_by,
            action="org.deactivated",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"status": previous_status},
            after_value={"status": "suspended", "reason": reason},
            ip_address=ip_address,
        )

        if notify_org_admin:
            await _notify_org_admin_status_change(db, org, "deactivated", reason)

        return {
            "message": "Organisation deactivated",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "previous_status": previous_status,
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
            "delete_type": "soft",
        })
        await redis_pool.setex(
            f"org_delete_confirm:{token}",
            _DELETE_CONFIRMATION_TTL,
            token_data,
        )

        return {
            "message": "Soft deletion confirmation required. Use the confirmation_token with DELETE to proceed.",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "confirmation_token": token,
            "expires_in_seconds": _DELETE_CONFIRMATION_TTL,
        }

    elif action == "hard_delete_request":
        if not reason:
            raise ValueError("Reason is required when requesting permanent deletion")

        # Generate confirmation token for multi-step hard delete
        token = secrets.token_urlsafe(32)
        token_data = json.dumps({
            "org_id": str(org.id),
            "reason": reason,
            "requested_by": str(updated_by),
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "delete_type": "hard",
        })
        await redis_pool.setex(
            f"org_hard_delete_confirm:{token}",
            _DELETE_CONFIRMATION_TTL,
            token_data,
        )

        return {
            "message": "PERMANENT deletion confirmation required. This will remove ALL data. Use the confirmation_token with DELETE /organisations/{id}/hard to proceed.",
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

        # Sync the new plan's enabled_modules to this org's org_modules table
        await _sync_plan_modules_to_orgs(db, new_plan_id, new_plan.enabled_modules)

        return {
            "message": f"Organisation moved to plan '{new_plan.name}'",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
            "previous_plan_id": previous_plan_id,
            "new_plan_id": str(new_plan_id),
        }

    elif action == "set_billing_date":
        if not next_billing_date:
            raise ValueError("next_billing_date is required for set_billing_date action")

        from datetime import datetime as _dt, timezone as _tz

        try:
            # Accept ISO format or date-only (YYYY-MM-DD)
            if "T" in next_billing_date:
                new_date = _dt.fromisoformat(next_billing_date.replace("Z", "+00:00"))
            else:
                new_date = _dt.strptime(next_billing_date, "%Y-%m-%d").replace(tzinfo=_tz.utc)
        except (ValueError, TypeError):
            raise ValueError("Invalid date format. Use YYYY-MM-DD or ISO 8601.")

        previous_date = org.next_billing_date.isoformat() if org.next_billing_date else None
        org.next_billing_date = new_date
        await db.flush()

        await write_audit_log(
            session=db,
            user_id=updated_by,
            action="org.billing_date_changed",
            entity_type="organisation",
            entity_id=org.id,
            before_value={"next_billing_date": previous_date},
            after_value={"next_billing_date": new_date.isoformat()},
            ip_address=ip_address,
        )

        return {
            "message": f"Next billing date set to {new_date.strftime('%d %b %Y')}",
            "organisation_id": str(org.id),
            "organisation_name": org.name,
            "status": org.status,
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



async def hard_delete_organisation(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    reason: str,
    confirmation_token: str,
    confirm_text: str,
    deleted_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """PERMANENTLY delete an organisation and ALL related data from the database.

    This is irreversible and removes:
    - Organisation record
    - All users in the organisation
    - All vehicles, customers, invoices, quotes, etc.
    - All audit logs for the organisation

    Requires:
    1. Confirmation token from hard_delete_request
    2. User must type "PERMANENTLY DELETE" to confirm

    Requirements 47.2, 47.3.
    """
    from app.core.redis import redis_pool

    # Validate confirm text
    if confirm_text != "PERMANENTLY DELETE":
        raise ValueError("You must type 'PERMANENTLY DELETE' exactly to confirm permanent deletion")

    # Validate confirmation token
    token_key = f"org_hard_delete_confirm:{confirmation_token}"
    token_data_raw = await redis_pool.get(token_key)
    if not token_data_raw:
        raise ValueError("Invalid or expired confirmation token. Please initiate hard deletion again.")

    token_data = json.loads(token_data_raw)
    if token_data.get("org_id") != str(org_id):
        raise ValueError("Confirmation token does not match the organisation")
    if token_data.get("delete_type") != "hard":
        raise ValueError("This token is not valid for hard deletion")

    # Consume the token
    await redis_pool.delete(token_key)

    # Fetch org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    org_name = org.name
    records_deleted = {}

    # Write final audit log BEFORE deletion
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=deleted_by,
        action="org.hard_deleted",
        entity_type="organisation",
        entity_id=org.id,
        before_value={"status": org.status, "name": org_name},
        after_value={"reason": reason, "deleted_by": str(deleted_by)},
        ip_address=ip_address,
    )
    await db.flush()

    # Count users before deletion
    user_count_result = await db.execute(
        select(func.count()).select_from(User).where(User.org_id == org_id)
    )
    records_deleted["users"] = user_count_result.scalar()

    from sqlalchemy import text

    # Disable FK constraint triggers so deletion order does not matter.
    # Safe inside a transaction: rolls back on failure, restoring constraints.
    await db.execute(text("SET session_replication_role = 'replica';"))

    try:
        # Find every table that FKs to organisations.id
        fk_query = text(
            "SELECT DISTINCT kcu.table_name, kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "JOIN information_schema.referential_constraints rc "
            "  ON tc.constraint_name = rc.constraint_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON rc.unique_constraint_name = ccu.constraint_name "
            "WHERE tc.constraint_type = 'FOREIGN KEY' "
            "  AND ccu.table_name = 'organisations' "
            "  AND ccu.column_name = 'id' "
            "  AND kcu.table_name != 'organisations' "
            "ORDER BY kcu.table_name"
        )
        fk_result = await db.execute(fk_query)
        org_child_tables = [(row[0], row[1]) for row in fk_result.all()]

        # Delete users
        await db.execute(delete(User).where(User.org_id == org_id))

        # Delete from all org-child tables
        total_child_rows = 0
        for tbl_name, col_name in org_child_tables:
            if tbl_name == "users":
                continue
            del_result = await db.execute(
                text(f'DELETE FROM "{tbl_name}" WHERE "{col_name}" = :oid'),
                {"oid": str(org_id)},
            )
            total_child_rows += del_result.rowcount
        records_deleted["related_rows"] = total_child_rows

        # Delete the organisation itself
        await db.execute(delete(Organisation).where(Organisation.id == org_id))
        records_deleted["organisations"] = 1

        await db.flush()
    finally:
        # Re-enable FK constraint triggers
        await db.execute(text("SET session_replication_role = 'origin';"))

    return {
        "message": f"Organisation '{org_name}' and all related data permanently deleted from database",
        "organisation_id": str(org_id),
        "organisation_name": org_name,
        "records_deleted": records_deleted,
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

    # Fetch storage pricing setting
    row_sp = await db.execute(
        sa_text("SELECT key, value FROM platform_settings WHERE key = :k"),
        {"k": "storage_pricing"},
    )
    sp_row = row_sp.first()
    storage_pricing = {"increment_gb": 1, "price_per_gb_nzd": 0.50}
    if sp_row:
        sp_val = sp_row[1] if isinstance(sp_row[1], dict) else json.loads(sp_row[1])
        storage_pricing = {
            "increment_gb": sp_val.get("increment_gb", 1),
            "price_per_gb_nzd": sp_val.get("price_per_gb_nzd", 0.50),
        }

    # Fetch signup billing config
    row_sb = await db.execute(
        sa_text("SELECT key, value FROM platform_settings WHERE key = :k"),
        {"k": "signup_billing"},
    )
    sb_row = row_sb.first()
    signup_billing = {
        "gst_percentage": 15.0,
        "stripe_fee_percentage": 2.9,
        "stripe_fee_fixed_cents": 30,
        "pass_fees_to_customer": True,
    }
    if sb_row:
        sb_val = sb_row[1] if isinstance(sb_row[1], dict) else json.loads(sb_row[1])
        signup_billing = {
            "gst_percentage": sb_val.get("gst_percentage", 15.0),
            "stripe_fee_percentage": sb_val.get("stripe_fee_percentage", 2.9),
            "stripe_fee_fixed_cents": sb_val.get("stripe_fee_fixed_cents", 30),
            "pass_fees_to_customer": sb_val.get("pass_fees_to_customer", True),
        }

    return {
        "terms_and_conditions": terms_entry,
        "terms_history": terms_history,
        "announcement_banner": announcement_banner,
        "announcement_active": announcement_active,
        "storage_pricing": storage_pricing,
        "signup_billing": signup_billing,
    }


async def update_platform_settings(
    db: AsyncSession,
    *,
    terms_and_conditions: str | None = None,
    announcement_banner: str | None = None,
    announcement_active: bool | None = None,
    storage_pricing: dict | None = None,
    signup_billing: dict | None = None,
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

    # --- Storage Pricing ---------------------------------------------------
    if storage_pricing is not None:
        row = await db.execute(
            sa_text("SELECT value FROM platform_settings WHERE key = :k FOR UPDATE"),
            {"k": "storage_pricing"},
        )
        existing = row.scalar_one_or_none()

        new_val = {
            "increment_gb": storage_pricing.get("increment_gb", 1),
            "price_per_gb_nzd": storage_pricing.get("price_per_gb_nzd", 0.50),
        }

        if existing:
            await db.execute(
                sa_text(
                    "UPDATE platform_settings SET value = :v, updated_at = now() WHERE key = :k"
                ),
                {"k": "storage_pricing", "v": json.dumps(new_val)},
            )
        else:
            await db.execute(
                sa_text(
                    "INSERT INTO platform_settings (key, value, version, updated_at) "
                    "VALUES (:k, :v, 1, now())"
                ),
                {"k": "storage_pricing", "v": json.dumps(new_val)},
            )

        result["storage_pricing"] = new_val

    # --- Signup Billing Config ---------------------------------------------
    if signup_billing is not None:
        row = await db.execute(
            sa_text("SELECT value FROM platform_settings WHERE key = :k FOR UPDATE"),
            {"k": "signup_billing"},
        )
        existing = row.scalar_one_or_none()

        new_val = {
            "gst_percentage": signup_billing.get("gst_percentage", 15.0),
            "stripe_fee_percentage": signup_billing.get("stripe_fee_percentage", 2.9),
            "stripe_fee_fixed_cents": signup_billing.get("stripe_fee_fixed_cents", 30),
            "pass_fees_to_customer": signup_billing.get("pass_fees_to_customer", True),
        }

        if existing:
            await db.execute(
                sa_text(
                    "UPDATE platform_settings SET value = :v, updated_at = now() WHERE key = :k"
                ),
                {"k": "signup_billing", "v": json.dumps(new_val)},
            )
        else:
            await db.execute(
                sa_text(
                    "INSERT INTO platform_settings (key, value, version, updated_at) "
                    "VALUES (:k, :v, 1, now())"
                ),
                {"k": "signup_billing", "v": json.dumps(new_val)},
            )

        result["signup_billing"] = new_val

    return result


async def search_global_vehicles(
    db: AsyncSession,
    rego: str,
) -> dict:
    """Search the Global Vehicle DB by rego.

    Requirement 50.1: view, search the Global Vehicle DB.
    """
    import logging
    from sqlalchemy import text as sa_text
    
    logger = logging.getLogger(__name__)

    rows = await db.execute(
        sa_text(
            "SELECT id, rego, make, model, year, colour, body_type, fuel_type, "
            "engine_size, num_seats, wof_expiry, registration_expiry, "
            "odometer_last_recorded, last_pulled_at, created_at, "
            "vin, chassis, engine_no, transmission, country_of_origin, "
            "number_of_owners, vehicle_type, reported_stolen, power_kw, "
            "tare_weight, gross_vehicle_mass, date_first_registered_nz, "
            "plate_type, submodel, second_colour, lookup_type "
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
            # Extended fields
            "vin": r[15],
            "chassis": r[16],
            "engine_no": r[17],
            "transmission": r[18],
            "country_of_origin": r[19],
            "number_of_owners": r[20],
            "vehicle_type": r[21],
            "reported_stolen": r[22],
            "power_kw": r[23],
            "tare_weight": r[24],
            "gross_vehicle_mass": r[25],
            "date_first_registered_nz": r[26].isoformat() if r[26] else None,
            "plate_type": r[27],
            "submodel": r[28],
            "second_colour": r[29],
            "lookup_type": r[30],
        })

    logger.info(f"Vehicle DB search for '{rego}': found {len(results)} results")
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
    from app.core.redis import get_redis

    redis = await get_redis()
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
    except (ConnectionError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("Carjam refresh failed for rego %s: %s", rego, exc, exc_info=True)
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


# ---------------------------------------------------------------------------
# User Management — Global Admin (ISSUE-011)
# ---------------------------------------------------------------------------


async def list_all_users(
    db: AsyncSession,
    *,
    search: str | None = None,
    role: str | None = None,
    org_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """List all users across all organisations with filtering and pagination."""
    from sqlalchemy import func as sa_func, text as sa_text

    conditions = []
    params: dict = {}

    if search:
        conditions.append("u.email ILIKE :search")
        params["search"] = f"%{search}%"
    if role:
        conditions.append("u.role = :role")
        params["role"] = role
    if org_id:
        conditions.append("u.org_id = :org_id")
        params["org_id"] = str(org_id)
    if is_active is not None:
        conditions.append("u.is_active = :is_active")
        params["is_active"] = is_active

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Validate sort column against allowlist (REM-21)
    validate_column_name("users", sort_by)
    order_dir = "ASC" if sort_order.lower() == "asc" else "DESC"

    count_sql = sa_text(f"SELECT COUNT(*) FROM users u WHERE {where_clause}")
    count_result = await db.execute(count_sql, params)
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    data_sql = sa_text(
        f"""
        SELECT u.id, u.email, u.role, u.is_active, u.is_email_verified,
               u.last_login_at, u.created_at, u.org_id,
               o.name as org_name
        FROM users u
        LEFT JOIN organisations o ON u.org_id = o.id
        WHERE {where_clause}
        ORDER BY u.{sort_by} {order_dir}
        LIMIT :limit OFFSET :offset
        """
    )
    params["limit"] = page_size
    params["offset"] = offset

    result = await db.execute(data_sql, params)
    rows = result.all()

    users = []
    for r in rows:
        users.append({
            "id": str(r[0]),
            "email": r[1],
            "role": r[2],
            "is_active": r[3],
            "is_email_verified": r[4],
            "last_login_at": r[5].isoformat() if r[5] else None,
            "created_at": r[6].isoformat() if r[6] else None,
            "org_id": str(r[7]) if r[7] else None,
            "org_name": r[8],
        })

    return {
        "users": users,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def toggle_user_active(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    toggled_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Toggle a user's is_active status."""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    user.is_active = not user.is_active
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=toggled_by,
        action="admin.user_status_toggled",
        entity_type="user",
        entity_id=user.id,
        after_value={
            "email": user.email,
            "is_active": user.is_active,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return {
        "message": f"User {'activated' if user.is_active else 'deactivated'}",
        "user_id": str(user.id),
        "email": user.email,
        "is_active": user.is_active,
    }


async def delete_user_permanently(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    deleted_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Permanently delete a user and all their MFA data, sessions, etc."""
    from app.modules.auth.models import Session, UserMfaMethod, UserPasskeyCredential, UserBackupCode

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    if deleted_by and user.id == deleted_by:
        raise ValueError("Cannot delete your own account")

    email = user.email

    # Delete related records
    await db.execute(delete(UserMfaMethod).where(UserMfaMethod.user_id == user_id))
    await db.execute(delete(UserPasskeyCredential).where(UserPasskeyCredential.user_id == user_id))
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user_id))
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.delete(user)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=deleted_by,
        action="admin.user_deleted",
        entity_type="user",
        entity_id=user_id,
        after_value={"email": email, "deleted_permanently": True},
        ip_address=ip_address,
    )

    return {"message": f"User {email} permanently deleted", "user_id": str(user_id)}


async def admin_reset_user_mfa(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    reset_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Clear all MFA methods, passkeys, and backup codes for a user."""
    from app.modules.auth.models import UserMfaMethod, UserPasskeyCredential, UserBackupCode

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    del_mfa = await db.execute(delete(UserMfaMethod).where(UserMfaMethod.user_id == user_id))
    del_passkeys = await db.execute(delete(UserPasskeyCredential).where(UserPasskeyCredential.user_id == user_id))
    del_codes = await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user_id))

    total = (del_mfa.rowcount or 0) + (del_passkeys.rowcount or 0) + (del_codes.rowcount or 0)

    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=reset_by,
        action="admin.user_mfa_reset",
        entity_type="user",
        entity_id=user_id,
        after_value={"email": user.email, "methods_removed": total},
        ip_address=ip_address,
    )

    return {
        "message": f"MFA reset for {user.email} — {total} record(s) removed",
        "user_id": str(user_id),
        "email": user.email,
    }


# ---------------------------------------------------------------------------
# Integration Cost Dashboard (Global Admin)
# ---------------------------------------------------------------------------


async def get_integration_cost_dashboard(
    db: AsyncSession,
    *,
    period: str = "monthly",
) -> dict:
    """Aggregate cost/usage data for all integrations.

    Returns a dict with carjam, sms, smtp, stripe cards.
    """
    from datetime import datetime, timezone, timedelta, date
    from sqlalchemy import func as sa_func, text as sa_text
    from app.modules.admin.models import IntegrationConfig

    now = datetime.now(timezone.utc)

    if period == "daily":
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        period_start = now - timedelta(days=7)
    else:
        period_start = date(now.year, now.month, 1)
        period_start = datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)

    # --- CarJam ---
    per_lookup_cost = await get_carjam_per_lookup_cost(db)
    abcd_per_lookup_cost = await get_carjam_abcd_per_lookup_cost(db)

    carjam_stmt = select(
        sa_func.coalesce(sa_func.sum(Organisation.carjam_lookups_this_month), 0),
    ).where(Organisation.status != "deleted")
    carjam_result = await db.execute(carjam_stmt)
    total_carjam_lookups = int(carjam_result.scalar() or 0)

    # Breakdown by lookup type from audit log
    abcd_count_result = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action IN ('vehicle.carjam_abcd_lookup') "
            "AND created_at >= :start"
        ),
        {"start": period_start},
    )
    abcd_count = int(abcd_count_result.scalar() or 0)

    basic_count_result = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action IN ('vehicle.carjam_basic_lookup', 'vehicle.carjam_lookup') "
            "AND created_at >= :start"
        ),
        {"start": period_start},
    )
    basic_count = int(basic_count_result.scalar() or 0)

    refresh_count_result = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action = 'vehicle.refresh' "
            "AND created_at >= :start"
        ),
        {"start": period_start},
    )
    refresh_count = int(refresh_count_result.scalar() or 0)

    carjam_total_cost = round(abcd_count * abcd_per_lookup_cost + basic_count * per_lookup_cost, 2)

    # CarJam integration status
    carjam_config = await get_integration_config(db, name="carjam")
    carjam_status = "healthy" if carjam_config and carjam_config.get("is_verified") else (
        "not_configured" if not carjam_config or not carjam_config.get("fields") else "down"
    )

    carjam_card = {
        "name": "Carjam",
        "status": carjam_status,
        "total_cost_nzd": carjam_total_cost,
        "total_usage": total_carjam_lookups,
        "usage_label": "lookups",
        "breakdown": {
            "abcd_lookups": abcd_count,
            "abcd_cost_nzd": round(abcd_count * abcd_per_lookup_cost, 2),
            "abcd_per_lookup_nzd": abcd_per_lookup_cost,
            "basic_lookups": basic_count,
            "basic_cost_nzd": round(basic_count * per_lookup_cost, 2),
            "basic_per_lookup_nzd": per_lookup_cost,
            "refreshes": refresh_count,
        },
        "last_checked": carjam_config.get("updated_at") if carjam_config else None,
    }

    # --- SMS (Connexus) ---
    # Use raw SQL to bypass RLS (sms_messages has tenant isolation policy).
    # This is a global admin dashboard — we need counts across ALL orgs.
    # Combine sms_messages (chat sends) + notification_log (notification SMS).
    sms_count_result = await db.execute(
        sa_text(
            "SELECT "
            "  (SELECT COUNT(*) FROM sms_messages "
            "   WHERE direction = 'outbound' AND created_at >= :start) "
            "+ (SELECT COUNT(*) FROM notification_log "
            "   WHERE channel = 'sms' AND status != 'failed' "
            "   AND created_at >= :start) "
            "AS total_sent, "
            "  (SELECT COALESCE(SUM(cost_nzd), 0) FROM sms_messages "
            "   WHERE direction = 'outbound' AND created_at >= :start) "
            "AS total_cost"
        ),
        {"start": period_start},
    )
    sms_row = sms_count_result.one()
    total_sms_sent = int(sms_row[0] or 0)
    total_sms_cost_from_db = float(sms_row[1] or 0)

    # Get SMS per-message cost from provider config (sms_verification_providers.config)
    from app.modules.admin.models import SmsVerificationProvider
    sms_provider_result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.is_active.is_(True),
            SmsVerificationProvider.is_default.is_(True),
        )
    )
    default_sms_provider = sms_provider_result.scalar_one_or_none()
    sms_per_msg_cost = 0.0

    # Connexus balance
    sms_balance = None
    sms_currency = None
    # Determine SMS status from sms_verification_providers (where Connexus is configured)
    sms_status = "not_configured"
    sms_last_checked = None
    sms_provider_for_cost = default_sms_provider
    if default_sms_provider:
        sms_status = "healthy" if default_sms_provider.credentials_set else "down"
        sms_last_checked = default_sms_provider.updated_at.isoformat() if default_sms_provider.updated_at else None
    else:
        # Check if any active provider exists even if not default
        any_active_result = await db.execute(
            select(SmsVerificationProvider).where(
                SmsVerificationProvider.is_active.is_(True),
                SmsVerificationProvider.credentials_set.is_(True),
            )
        )
        any_active = any_active_result.scalar_one_or_none()
        if any_active:
            sms_status = "healthy"
            sms_last_checked = any_active.updated_at.isoformat() if any_active.updated_at else None
            sms_provider_for_cost = any_active

    # Read per-SMS cost from whichever provider we found
    if sms_provider_for_cost and sms_provider_for_cost.config:
        try:
            sms_per_msg_cost = float(sms_provider_for_cost.config.get("per_sms_cost_nzd", 0))
        except (TypeError, ValueError):
            pass

    total_sms_cost = round(total_sms_cost_from_db, 2) if total_sms_cost_from_db > 0 else round(total_sms_sent * sms_per_msg_cost, 2)

    # Token refresh timing from in-memory cache
    from app.integrations.connexus_sms import get_token_status
    token_status = get_token_status()

    sms_card = {
        "name": "Connexus SMS",
        "status": sms_status,
        "total_cost_nzd": round(total_sms_cost, 2),
        "total_usage": total_sms_sent,
        "usage_label": "messages sent",
        "breakdown": {
            "total_sent_this_month": total_sms_sent,
            "per_sms_cost_nzd": sms_per_msg_cost,
        },
        "balance": sms_balance,
        "balance_currency": sms_currency,
        "last_checked": sms_last_checked,
        "token_last_refresh": token_status["last_refresh_at"],
        "token_expires_at": token_status["expires_at"],
    }

    # --- SMTP ---
    email_count_result = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action = 'invoice.email_sent' "
            "AND created_at >= :start"
        ),
        {"start": period_start},
    )
    total_emails = int(email_count_result.scalar() or 0)

    # Check email_providers table for active, configured providers
    from app.modules.admin.models import EmailProvider as EmailProviderModel
    active_email_result = await db.execute(
        select(EmailProviderModel).where(
            EmailProviderModel.is_active.is_(True),
            EmailProviderModel.credentials_set.is_(True),
        ).order_by(EmailProviderModel.priority)
    )
    active_email_provider = active_email_result.scalars().first()

    if not active_email_provider:
        # Also check for any provider with credentials set (configured but not activated)
        creds_email_result = await db.execute(
            select(EmailProviderModel).where(
                EmailProviderModel.credentials_set.is_(True),
            ).order_by(EmailProviderModel.priority)
        )
        active_email_provider = creds_email_result.scalars().first()

    if active_email_provider:
        smtp_status = "healthy"
        smtp_provider = active_email_provider.display_name
        smtp_last_checked = (
            active_email_provider.updated_at.isoformat()
            if active_email_provider.updated_at else None
        )
    else:
        # Fallback: check legacy integration_configs table
        smtp_config = await get_integration_config(db, name="smtp")
        smtp_status = "healthy" if smtp_config and smtp_config.get("is_verified") else (
            "not_configured" if not smtp_config or not smtp_config.get("fields") else "down"
        )
        smtp_provider = "Unknown"
        if smtp_config and smtp_config.get("fields"):
            smtp_provider = smtp_config["fields"].get("provider", "smtp").capitalize()
        smtp_last_checked = smtp_config.get("updated_at") if smtp_config else None

    smtp_card = {
        "name": "SMTP",
        "status": smtp_status,
        "total_cost_nzd": 0.0,  # SMTP costs are typically bundled
        "total_usage": total_emails,
        "usage_label": "emails sent",
        "breakdown": {
            "provider": smtp_provider,
            "emails_this_period": total_emails,
        },
        "last_checked": smtp_last_checked,
    }

    # --- Stripe ---
    payment_count_result = await db.execute(
        sa_text(
            "SELECT COUNT(*) FROM audit_log "
            "WHERE action IN ('payment.stripe_link_generated', 'payment.stripe_webhook_received') "
            "AND created_at >= :start"
        ),
        {"start": period_start},
    )
    total_stripe_txns = int(payment_count_result.scalar() or 0)

    # Total payment volume from payments table
    from app.modules.payments.models import Payment
    payment_vol_result = await db.execute(
        select(
            sa_func.coalesce(sa_func.sum(Payment.amount), 0),
            sa_func.count(Payment.id),
        ).where(
            Payment.created_at >= period_start,
            Payment.method == "stripe",
        )
    )
    vol_row = payment_vol_result.one()
    total_volume = float(vol_row[0] or 0)
    stripe_payment_count = int(vol_row[1] or 0)

    # Estimate Stripe fees (2.9% + $0.30 per transaction for NZ)
    estimated_stripe_fees = round(total_volume * 0.029 + stripe_payment_count * 0.30, 2)

    stripe_config = await get_integration_config(db, name="stripe")
    stripe_status = "healthy" if stripe_config and stripe_config.get("is_verified") else (
        "not_configured" if not stripe_config or not stripe_config.get("fields") else "down"
    )

    stripe_card = {
        "name": "Stripe",
        "status": stripe_status,
        "total_cost_nzd": estimated_stripe_fees,
        "total_usage": stripe_payment_count,
        "usage_label": "transactions",
        "breakdown": {
            "total_volume_nzd": round(total_volume, 2),
            "payment_count": stripe_payment_count,
            "estimated_fees_nzd": estimated_stripe_fees,
            "fee_rate": "2.9% + $0.30",
        },
        "last_checked": stripe_config.get("updated_at") if stripe_config else None,
    }

    return {
        "period": period,
        "carjam": carjam_card,
        "sms": sms_card,
        "smtp": smtp_card,
        "stripe": stripe_card,
    }


# ---------------------------------------------------------------------------
# Public Holiday Calendar Sync
# ---------------------------------------------------------------------------

async def sync_public_holidays(
    db: AsyncSession,
    country_code: str,
    year: int,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Fetch public holidays from Nager.Date API and upsert into DB.

    Uses https://date.nager.at/api/v3/PublicHolidays/{year}/{countryCode}
    which is free and requires no API key.
    """
    import httpx
    from app.modules.admin.models import PublicHoliday

    url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{country_code}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        holidays_data = resp.json()

    # Delete existing holidays for this country+year before inserting
    await db.execute(
        delete(PublicHoliday).where(
            PublicHoliday.country_code == country_code,
            PublicHoliday.year == year,
        )
    )

    inserted = 0
    now = datetime.now(timezone.utc)
    for h in holidays_data:
        holiday = PublicHoliday(
            country_code=country_code,
            holiday_date=datetime.strptime(h["date"], "%Y-%m-%d").date(),
            name=h.get("name", ""),
            local_name=h.get("localName"),
            year=year,
            is_fixed=h.get("fixed", False),
            synced_at=now,
        )
        db.add(holiday)
        inserted += 1

    await db.flush()

    await write_audit_log(
        db,
        action="calendar.sync_public_holidays",
        entity_type="public_holidays",
        entity_id=None,
        user_id=actor_user_id,
        ip_address=ip_address,
        after_value={"country_code": country_code, "year": year, "count": inserted},
    )

    return {"country_code": country_code, "year": year, "synced": inserted}


async def list_public_holidays(
    db: AsyncSession,
    country_code: str | None = None,
    year: int | None = None,
) -> list[dict]:
    """List public holidays, optionally filtered by country and year."""
    from app.modules.admin.models import PublicHoliday

    stmt = select(PublicHoliday).order_by(PublicHoliday.holiday_date)
    if country_code:
        stmt = stmt.where(PublicHoliday.country_code == country_code)
    if year:
        stmt = stmt.where(PublicHoliday.year == year)

    result = await db.execute(stmt)
    holidays = result.scalars().all()

    return [
        {
            "id": str(h.id),
            "country_code": h.country_code,
            "holiday_date": h.holiday_date.isoformat(),
            "name": h.name,
            "local_name": h.local_name,
            "year": h.year,
            "is_fixed": h.is_fixed,
            "synced_at": h.synced_at.isoformat() if h.synced_at else None,
        }
        for h in holidays
    ]



# ---------------------------------------------------------------------------
# Coupon service functions
# ---------------------------------------------------------------------------


def calculate_effective_price(
    plan_price: float,
    discount_type: str,
    discount_value: float,
    is_expired: bool,
) -> float:
    """Pure function: compute discounted price using interval-aware coupon logic.

    Returns plan_price if expired or trial_extension type.
    Delegates to apply_coupon_to_interval_price for percentage/fixed coupons.
    Requirements 11.1–11.6.
    """
    if is_expired:
        return plan_price
    if discount_type == "trial_extension":
        return plan_price
    if discount_type in ("percentage", "fixed_amount"):
        from decimal import Decimal as _Dec
        from app.modules.billing.interval_pricing import apply_coupon_to_interval_price

        result = apply_coupon_to_interval_price(
            _Dec(str(plan_price)),
            discount_type,
            _Dec(str(discount_value)),
        )
        return float(result)
    return plan_price



def _coupon_to_dict(c: Coupon) -> dict:
    """Serialise a Coupon ORM instance to a dict matching CouponResponse."""
    return {
        "id": str(c.id),
        "code": c.code,
        "description": c.description,
        "discount_type": c.discount_type,
        "discount_value": float(c.discount_value),
        "duration_months": c.duration_months,
        "usage_limit": c.usage_limit,
        "times_redeemed": c.times_redeemed,
        "is_active": c.is_active,
        "starts_at": c.starts_at,
        "expires_at": c.expires_at,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


async def create_coupon(
    db: AsyncSession,
    *,
    code: str,
    description: str | None = None,
    discount_type: str,
    discount_value: float,
    duration_months: int | None = None,
    usage_limit: int | None = None,
    starts_at: datetime | None = None,
    expires_at: datetime | None = None,
    created_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new coupon. Normalise code to uppercase. Check for duplicates.

    Requirements 2.2, 2.6, 2.7.
    """
    normalised_code = code.strip().upper()

    # Check for duplicate code (case-insensitive)
    existing = await db.execute(
        select(Coupon).where(func.upper(Coupon.code) == normalised_code)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"A coupon with code '{normalised_code}' already exists")

    coupon = Coupon(
        code=normalised_code,
        description=description,
        discount_type=discount_type,
        discount_value=discount_value,
        duration_months=duration_months,
        usage_limit=usage_limit,
        starts_at=starts_at,
        expires_at=expires_at,
    )
    db.add(coupon)
    await db.flush()

    await write_audit_log(
        db,
        action="coupon.created",
        user_id=created_by,
        ip_address=ip_address,
        entity_type="coupon",
        entity_id=coupon.id,
        after_value={"code": normalised_code, "discount_type": discount_type},
    )

    logger.info("Created coupon %s (%s)", coupon.id, normalised_code)

    await db.refresh(coupon, ["created_at", "updated_at"])

    return _coupon_to_dict(coupon)



async def list_coupons(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """List coupons with pagination, ordered by created_at desc.

    Requirement 2.1.
    """
    query = select(Coupon).order_by(Coupon.created_at.desc())
    if not include_inactive:
        query = query.where(Coupon.is_active.is_(True))

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    coupons = result.scalars().all()

    return {
        "coupons": [_coupon_to_dict(c) for c in coupons],
        "total": total,
    }


async def get_coupon(
    db: AsyncSession,
    coupon_id: uuid.UUID,
) -> dict:
    """Get single coupon with redemption list (joined to organisations for names).

    Requirement 2.3.
    """
    result = await db.execute(
        select(Coupon).where(Coupon.id == coupon_id)
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise ValueError("Coupon not found")

    # Fetch redemptions with org names
    redemptions_result = await db.execute(
        select(OrganisationCoupon, Organisation.name)
        .join(Organisation, OrganisationCoupon.org_id == Organisation.id)
        .where(OrganisationCoupon.coupon_id == coupon_id)
    )
    redemption_rows = redemptions_result.all()

    redemptions = [
        {
            "id": str(oc.id),
            "org_id": str(oc.org_id),
            "organisation_name": org_name,
            "applied_at": oc.applied_at,
            "billing_months_used": oc.billing_months_used,
            "is_expired": oc.is_expired,
        }
        for oc, org_name in redemption_rows
    ]

    data = _coupon_to_dict(coupon)
    data["redemptions"] = redemptions
    return data


async def update_coupon(
    db: AsyncSession,
    coupon_id: uuid.UUID,
    *,
    updates: dict,
    updated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update coupon fields. Validate usage_limit >= times_redeemed.

    Requirements 2.4, 2.8, 6.3, 6.4.
    """
    result = await db.execute(
        select(Coupon).where(Coupon.id == coupon_id)
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise ValueError("Coupon not found")

    # Validate usage_limit constraint
    if "usage_limit" in updates and updates["usage_limit"] is not None:
        if updates["usage_limit"] < coupon.times_redeemed:
            raise ValueError(
                f"Usage limit cannot be less than current redemptions ({coupon.times_redeemed})"
            )

    allowed_fields = {
        "description", "discount_value", "duration_months", "usage_limit",
        "is_active", "starts_at", "expires_at",
    }

    before = {}
    after = {}
    for field, value in updates.items():
        if field in allowed_fields and value is not None:
            before[field] = getattr(coupon, field)
            setattr(coupon, field, value)
            after[field] = value

    await db.flush()

    await write_audit_log(
        db,
        action="coupon.updated",
        user_id=updated_by,
        ip_address=ip_address,
        entity_type="coupon",
        entity_id=coupon.id,
        before_value=_serialise_audit(before),
        after_value=_serialise_audit(after),
    )

    logger.info("Updated coupon %s", coupon.id)

    await db.refresh(coupon, ["created_at", "updated_at"])

    return _coupon_to_dict(coupon)



async def deactivate_coupon(
    db: AsyncSession,
    coupon_id: uuid.UUID,
    *,
    updated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Set is_active = False (soft delete).

    Requirement 2.5.
    """
    result = await db.execute(
        select(Coupon).where(Coupon.id == coupon_id)
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise ValueError("Coupon not found")

    coupon.is_active = False
    await db.flush()

    await write_audit_log(
        db,
        action="coupon.deactivated",
        user_id=updated_by,
        ip_address=ip_address,
        entity_type="coupon",
        entity_id=coupon.id,
        after_value={"code": coupon.code, "is_active": False},
    )

    logger.info("Deactivated coupon %s (%s)", coupon.id, coupon.code)

    await db.refresh(coupon, ["created_at", "updated_at"])

    return _coupon_to_dict(coupon)


async def reactivate_coupon(
    db: AsyncSession,
    coupon_id: uuid.UUID,
    *,
    updated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Set is_active = True.

    Requirement 2.5.
    """
    result = await db.execute(
        select(Coupon).where(Coupon.id == coupon_id)
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise ValueError("Coupon not found")

    coupon.is_active = True
    await db.flush()

    await write_audit_log(
        db,
        action="coupon.reactivated",
        user_id=updated_by,
        ip_address=ip_address,
        entity_type="coupon",
        entity_id=coupon.id,
        after_value={"code": coupon.code, "is_active": True},
    )

    logger.info("Reactivated coupon %s (%s)", coupon.id, coupon.code)

    await db.refresh(coupon, ["created_at", "updated_at"])

    return _coupon_to_dict(coupon)



async def validate_coupon(
    db: AsyncSession,
    code: str,
) -> dict:
    """Public validation: check is_active, usage_limit, starts_at, expires_at.

    Requirements 3.1–3.3.
    """
    normalised_code = code.strip().upper()

    result = await db.execute(
        select(Coupon).where(func.upper(Coupon.code) == normalised_code)
    )
    coupon = result.scalar_one_or_none()

    if coupon is None or not coupon.is_active:
        return {"valid": False, "error": "Coupon not found"}

    now = datetime.now(timezone.utc)

    if coupon.expires_at is not None and now > coupon.expires_at:
        return {"valid": False, "error": "Coupon has expired"}

    if coupon.starts_at is not None and now < coupon.starts_at:
        return {"valid": False, "error": "Coupon is not yet active"}

    if coupon.usage_limit is not None and coupon.times_redeemed >= coupon.usage_limit:
        return {"valid": False, "error": "Coupon usage limit reached"}

    return {"valid": True, "coupon": _coupon_to_dict(coupon)}



async def redeem_coupon(
    db: AsyncSession,
    *,
    code: str,
    org_id: str,
) -> dict:
    """Atomic redemption: SELECT FOR UPDATE, check limits, create org_coupon,
    increment times_redeemed, extend trial if trial_extension type.

    Requirements 3.4–3.8.
    """
    normalised_code = code.strip().upper()
    org_uuid = uuid.UUID(org_id)

    # Lock the coupon row for atomic update
    result = await db.execute(
        select(Coupon)
        .where(func.upper(Coupon.code) == normalised_code)
        .with_for_update()
    )
    coupon = result.scalar_one_or_none()

    if coupon is None or not coupon.is_active:
        raise ValueError("Coupon not found")

    now = datetime.now(timezone.utc)

    if coupon.expires_at is not None and now > coupon.expires_at:
        raise ValueError("Coupon has expired")

    if coupon.starts_at is not None and now < coupon.starts_at:
        raise ValueError("Coupon is not yet active")

    if coupon.usage_limit is not None and coupon.times_redeemed >= coupon.usage_limit:
        raise ValueError("Coupon usage limit reached")

    # Check org exists
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    # Check for duplicate redemption
    existing_redemption = await db.execute(
        select(OrganisationCoupon).where(
            OrganisationCoupon.org_id == org_uuid,
            OrganisationCoupon.coupon_id == coupon.id,
        )
    )
    if existing_redemption.scalar_one_or_none() is not None:
        raise ValueError("Coupon already redeemed by this organisation")

    # Create OrganisationCoupon record
    org_coupon = OrganisationCoupon(
        org_id=org_uuid,
        coupon_id=coupon.id,
        applied_at=now,
        billing_months_used=0,
        is_expired=False,
    )
    db.add(org_coupon)

    # Increment times_redeemed
    coupon.times_redeemed = coupon.times_redeemed + 1

    # If trial_extension, extend the organisation's trial
    if coupon.discount_type == "trial_extension":
        if org.trial_ends_at is not None:
            org.trial_ends_at = org.trial_ends_at + timedelta(days=float(coupon.discount_value))
        else:
            org.trial_ends_at = now + timedelta(days=float(coupon.discount_value))

    await db.flush()

    return {
        "message": "Coupon redeemed successfully",
        "organisation_coupon_id": str(org_coupon.id),
    }



async def get_coupon_redemptions(
    db: AsyncSession,
    coupon_id: uuid.UUID,
) -> list[dict]:
    """List all organisation_coupons for a given coupon.

    Requirement 5.6.
    """
    result = await db.execute(
        select(OrganisationCoupon, Organisation.name)
        .join(Organisation, OrganisationCoupon.org_id == Organisation.id)
        .where(OrganisationCoupon.coupon_id == coupon_id)
    )
    rows = result.all()

    return [
        {
            "id": str(oc.id),
            "org_id": str(oc.org_id),
            "organisation_name": org_name,
            "applied_at": oc.applied_at,
            "billing_months_used": oc.billing_months_used,
            "is_expired": oc.is_expired,
        }
        for oc, org_name in rows
    ]


# ---------------------------------------------------------------------------
# Storage Package CRUD  (Requirements 2.1–2.6, 7.1)
# ---------------------------------------------------------------------------


def _storage_package_to_dict(pkg: StoragePackage) -> dict:
    """Serialise a StoragePackage row to a plain dict."""
    return {
        "id": str(pkg.id),
        "name": pkg.name,
        "storage_gb": pkg.storage_gb,
        "price_nzd_per_month": float(pkg.price_nzd_per_month),
        "description": pkg.description,
        "is_active": pkg.is_active,
        "sort_order": pkg.sort_order,
        "created_at": pkg.created_at,
        "updated_at": pkg.updated_at,
    }


async def list_storage_packages(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
) -> list[dict]:
    """Return storage packages ordered by sort_order ascending.

    Requirements 2.1.
    """
    query = select(StoragePackage).order_by(StoragePackage.sort_order.asc())
    if not include_inactive:
        query = query.where(StoragePackage.is_active.is_(True))

    result = await db.execute(query)
    packages = result.scalars().all()

    return [_storage_package_to_dict(p) for p in packages]


async def create_storage_package(
    db: AsyncSession,
    *,
    name: str,
    storage_gb: int,
    price_nzd_per_month: float,
    description: str | None = None,
    sort_order: int = 0,
    created_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new storage package.

    Requirements 2.2, 2.5, 7.1.
    """
    if storage_gb <= 0:
        raise ValueError("storage_gb must be greater than 0")
    if price_nzd_per_month < 0:
        raise ValueError("price_nzd_per_month must be >= 0")

    pkg = StoragePackage(
        name=name,
        storage_gb=storage_gb,
        price_nzd_per_month=price_nzd_per_month,
        description=description,
        sort_order=sort_order,
    )
    db.add(pkg)
    await db.flush()

    await write_audit_log(
        db,
        action="storage_package.created",
        user_id=created_by,
        ip_address=ip_address,
        entity_type="storage_package",
        entity_id=pkg.id,
        after_value={
            "name": name,
            "storage_gb": storage_gb,
            "price_nzd_per_month": price_nzd_per_month,
            "description": description,
            "sort_order": sort_order,
        },
    )

    logger.info("Created storage package %s (%s)", pkg.id, name)

    await db.refresh(pkg, ["created_at", "updated_at"])
    return _storage_package_to_dict(pkg)


async def update_storage_package(
    db: AsyncSession,
    package_id: uuid.UUID,
    *,
    updated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
    **fields: object,
) -> dict:
    """Update storage package fields.

    Requirements 2.3, 2.5, 7.1.
    """
    result = await db.execute(
        select(StoragePackage).where(StoragePackage.id == package_id)
    )
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise ValueError("Storage package not found")

    allowed_fields = {
        "name", "storage_gb", "price_nzd_per_month",
        "description", "is_active", "sort_order",
    }

    # Validate numeric constraints if provided
    if "storage_gb" in fields and fields["storage_gb"] is not None:
        if fields["storage_gb"] <= 0:
            raise ValueError("storage_gb must be greater than 0")
    if "price_nzd_per_month" in fields and fields["price_nzd_per_month"] is not None:
        if fields["price_nzd_per_month"] < 0:
            raise ValueError("price_nzd_per_month must be >= 0")

    before: dict = {}
    after: dict = {}
    for field, value in fields.items():
        if field in allowed_fields and value is not None:
            before[field] = getattr(pkg, field)
            setattr(pkg, field, value)
            after[field] = value

    await db.flush()

    await write_audit_log(
        db,
        action="storage_package.updated",
        user_id=updated_by,
        ip_address=ip_address,
        entity_type="storage_package",
        entity_id=pkg.id,
        before_value=_serialise_audit(before),
        after_value=_serialise_audit(after),
    )

    logger.info("Updated storage package %s", pkg.id)

    await db.refresh(pkg, ["created_at", "updated_at"])
    return _storage_package_to_dict(pkg)


async def deactivate_storage_package(
    db: AsyncSession,
    package_id: uuid.UUID,
    *,
    deactivated_by: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> dict:
    """Soft-delete a storage package (set is_active = False).

    Always soft-deletes — never hard-deletes — especially when active
    org_storage_addons reference this package (Requirement 2.6).

    Requirements 2.4, 2.6, 7.1.
    """
    result = await db.execute(
        select(StoragePackage).where(StoragePackage.id == package_id)
    )
    pkg = result.scalar_one_or_none()
    if pkg is None:
        raise ValueError("Storage package not found")

    # Check for active org references (informational — we still soft-delete)
    ref_count_result = await db.execute(
        select(func.count()).select_from(OrgStorageAddon).where(
            OrgStorageAddon.storage_package_id == package_id
        )
    )
    active_refs = ref_count_result.scalar() or 0

    pkg.is_active = False
    await db.flush()

    await write_audit_log(
        db,
        action="storage_package.deactivated",
        user_id=deactivated_by,
        ip_address=ip_address,
        entity_type="storage_package",
        entity_id=pkg.id,
        after_value={
            "name": pkg.name,
            "is_active": False,
            "active_org_references": active_refs,
        },
    )

    logger.info(
        "Deactivated storage package %s (%s), %d active org refs",
        pkg.id, pkg.name, active_refs,
    )

    await db.refresh(pkg, ["created_at", "updated_at"])
    return _storage_package_to_dict(pkg)


# ---------------------------------------------------------------------------
# Integration Settings Backup / Restore
# ---------------------------------------------------------------------------

_REDACTED_FIELDS = {"api_key", "auth_token", "password", "secret", "token", "credentials"}


def _redact_config(config_dict: dict) -> dict:
    """Mask sensitive fields in a config dictionary with ***REDACTED***."""
    return {k: "***REDACTED***" if k in _REDACTED_FIELDS else v for k, v in config_dict.items()}


async def export_integration_settings(
    db: AsyncSession,
) -> dict:
    """Export all integration configs, SMS providers, and email providers as JSON.

    Decrypts stored configs so the backup contains the actual values.
    Returns a dict ready to be serialised as JSON.
    """
    from app.modules.admin.models import IntegrationConfig, SmsVerificationProvider, EmailProvider
    from app.core.encryption import envelope_decrypt_str

    backup: dict = {"version": 1, "integrations": {}, "sms_providers": [], "email_providers": []}

    # Integration configs (carjam, stripe, smtp, twilio)
    result = await db.execute(select(IntegrationConfig))
    for row in result.scalars().all():
        try:
            config_data = json.loads(envelope_decrypt_str(row.config_encrypted))
        except Exception:
            config_data = {}
        backup["integrations"][row.name] = {
            "config": _redact_config(config_data),
            "is_verified": row.is_verified,
        }

    # SMS verification providers
    result = await db.execute(select(SmsVerificationProvider))
    for row in result.scalars().all():
        entry: dict = {
            "provider_key": row.provider_key,
            "display_name": row.display_name,
            "description": row.description,
            "icon": row.icon,
            "is_active": row.is_active,
            "is_default": row.is_default,
            "priority": row.priority,
            "config": _redact_config(row.config) if row.config else {},
            "credentials_set": row.credentials_set,
        }
        # Include decrypted credentials if set
        if row.credentials_encrypted:
            try:
                entry["credentials"] = _redact_config(json.loads(envelope_decrypt_str(row.credentials_encrypted)))
            except Exception:
                entry["credentials"] = None
        else:
            entry["credentials"] = None
        backup["sms_providers"].append(entry)

    # Email providers
    result = await db.execute(select(EmailProvider))
    for row in result.scalars().all():
        entry = {
            "provider_key": row.provider_key,
            "display_name": row.display_name,
            "description": row.description,
            "smtp_host": row.smtp_host,
            "smtp_port": row.smtp_port,
            "smtp_encryption": row.smtp_encryption,
            "priority": row.priority,
            "is_active": row.is_active,
            "config": _redact_config(row.config) if row.config else {},
            "credentials_set": row.credentials_set,
        }
        if row.credentials_encrypted:
            try:
                entry["credentials"] = _redact_config(json.loads(envelope_decrypt_str(row.credentials_encrypted)))
            except Exception:
                entry["credentials"] = None
        else:
            entry["credentials"] = None
        backup["email_providers"].append(entry)

    return backup


async def import_integration_settings(
    db: AsyncSession,
    *,
    data: dict,
    imported_by: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Restore integration settings from a backup JSON dict.

    Overwrites existing configs. Returns a summary of what was restored.
    """
    from app.modules.admin.models import IntegrationConfig, SmsVerificationProvider, EmailProvider
    from app.core.encryption import envelope_encrypt

    restored: dict = {"integrations": [], "sms_providers": [], "email_providers": []}

    # Restore integration configs
    integrations = data.get("integrations", {})
    for name, entry in integrations.items():
        if name not in ("carjam", "stripe", "smtp", "twilio"):
            continue
        config_data = entry.get("config", {})
        if not config_data:
            continue
        encrypted = envelope_encrypt(json.dumps(config_data))
        is_verified = entry.get("is_verified", False)

        result = await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.name == name)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.config_encrypted = encrypted
            existing.is_verified = is_verified
        else:
            db.add(IntegrationConfig(
                name=name,
                config_encrypted=encrypted,
                is_verified=is_verified,
            ))
        restored["integrations"].append(name)

    # Restore SMS providers
    for entry in data.get("sms_providers", []):
        provider_key = entry.get("provider_key")
        if not provider_key:
            continue
        result = await db.execute(
            select(SmsVerificationProvider).where(
                SmsVerificationProvider.provider_key == provider_key
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.display_name = entry.get("display_name", existing.display_name)
            existing.description = entry.get("description", existing.description)
            existing.icon = entry.get("icon", existing.icon)
            existing.is_active = entry.get("is_active", existing.is_active)
            existing.is_default = entry.get("is_default", existing.is_default)
            existing.priority = entry.get("priority", existing.priority)
            existing.config = entry.get("config", existing.config)
            if entry.get("credentials"):
                existing.credentials_encrypted = envelope_encrypt(json.dumps(entry["credentials"]))
                existing.credentials_set = True
        else:
            creds_enc = None
            creds_set = False
            if entry.get("credentials"):
                creds_enc = envelope_encrypt(json.dumps(entry["credentials"]))
                creds_set = True
            db.add(SmsVerificationProvider(
                provider_key=provider_key,
                display_name=entry.get("display_name", provider_key),
                description=entry.get("description"),
                icon=entry.get("icon"),
                is_active=entry.get("is_active", False),
                is_default=entry.get("is_default", False),
                priority=entry.get("priority", 0),
                config=entry.get("config", {}),
                credentials_encrypted=creds_enc,
                credentials_set=creds_set,
            ))
        restored["sms_providers"].append(provider_key)

    # Restore email providers
    for entry in data.get("email_providers", []):
        provider_key = entry.get("provider_key")
        if not provider_key:
            continue
        result = await db.execute(
            select(EmailProvider).where(
                EmailProvider.provider_key == provider_key
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.display_name = entry.get("display_name", existing.display_name)
            existing.description = entry.get("description", existing.description)
            existing.smtp_host = entry.get("smtp_host", existing.smtp_host)
            existing.smtp_port = entry.get("smtp_port", existing.smtp_port)
            existing.smtp_encryption = entry.get("smtp_encryption", existing.smtp_encryption)
            existing.priority = entry.get("priority", existing.priority)
            existing.is_active = entry.get("is_active", existing.is_active)
            existing.config = entry.get("config", existing.config)
            if entry.get("credentials"):
                existing.credentials_encrypted = envelope_encrypt(json.dumps(entry["credentials"]))
                existing.credentials_set = True
        else:
            creds_enc = None
            creds_set = False
            if entry.get("credentials"):
                creds_enc = envelope_encrypt(json.dumps(entry["credentials"]))
                creds_set = True
            db.add(EmailProvider(
                provider_key=provider_key,
                display_name=entry.get("display_name", provider_key),
                description=entry.get("description"),
                smtp_host=entry.get("smtp_host"),
                smtp_port=entry.get("smtp_port"),
                smtp_encryption=entry.get("smtp_encryption", "tls"),
                priority=entry.get("priority", 1),
                is_active=entry.get("is_active", False),
                config=entry.get("config", {}),
                credentials_encrypted=creds_enc,
                credentials_set=creds_set,
            ))
        restored["email_providers"].append(provider_key)

    await db.flush()

    await write_audit_log(
        session=db,
        org_id=None,
        user_id=imported_by,
        action="admin.integration_settings_restored",
        entity_type="integration_config",
        entity_id=None,
        after_value={
            "restored": restored,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return restored
