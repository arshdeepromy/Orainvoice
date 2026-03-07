"""Business logic for Organisation module — onboarding wizard & public signup.

Requirements: 8.2, 8.3, 8.4, 8.5, 8.6
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.admin.models import Organisation, SubscriptionPlan
from app.modules.auth.models import User

logger = logging.getLogger(__name__)

# Keys in the Organisation.settings JSONB that the onboarding wizard manages.
ONBOARDING_SETTINGS_KEYS = {
    "logo_url",
    "primary_colour",
    "secondary_colour",
    "gst_number",
    "gst_percentage",
    "invoice_prefix",
    "invoice_start_number",
    "default_due_days",
    "payment_terms_text",
}

# All fields that indicate onboarding progress (settings + org name + first service).
ALL_ONBOARDING_FIELDS = ONBOARDING_SETTINGS_KEYS | {
    "org_name",
    "first_service_name",
}


async def save_onboarding_step(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    org_name: str | None = None,
    logo_url: str | None = None,
    primary_colour: str | None = None,
    secondary_colour: str | None = None,
    gst_number: str | None = None,
    gst_percentage: float | None = None,
    invoice_prefix: str | None = None,
    invoice_start_number: int | None = None,
    default_due_days: int | None = None,
    payment_terms_text: str | None = None,
    first_service_name: str | None = None,
    first_service_price: float | None = None,
    ip_address: str | None = None,
) -> dict:
    """Save one or more onboarding wizard fields for an organisation.

    Any field that is ``None`` is treated as skipped. The workspace is
    usable immediately regardless of how many fields are completed.

    Returns a dict with ``updated_fields``, ``onboarding_complete``, and
    ``skipped`` keys.
    """
    # Fetch current org
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    before_settings = dict(org.settings) if org.settings else {}
    before_name = org.name
    updated_fields: list[str] = []

    # --- Update org name (top-level column) ---
    if org_name is not None:
        org.name = org_name
        updated_fields.append("org_name")

    # --- Update settings JSONB ---
    new_settings = dict(org.settings) if org.settings else {}

    settings_updates = {
        "logo_url": logo_url,
        "primary_colour": primary_colour,
        "secondary_colour": secondary_colour,
        "gst_number": gst_number,
        "gst_percentage": gst_percentage,
        "invoice_prefix": invoice_prefix,
        "invoice_start_number": invoice_start_number,
        "default_due_days": default_due_days,
        "payment_terms_text": payment_terms_text,
    }

    for key, value in settings_updates.items():
        if value is not None:
            new_settings[key] = value
            updated_fields.append(key)

    # Track first service in settings for onboarding progress
    if first_service_name is not None:
        new_settings["first_service_name"] = first_service_name
        if first_service_price is not None:
            new_settings["first_service_price"] = first_service_price
        updated_fields.append("first_service_name")

    skipped = len(updated_fields) == 0

    if not skipped:
        # Mark onboarding progress
        completed_steps = set(new_settings.get("onboarding_completed_fields", []))
        completed_steps.update(updated_fields)
        new_settings["onboarding_completed_fields"] = sorted(completed_steps)

        org.settings = new_settings
        await db.flush()

        # Audit log
        after_value = {
            "updated_fields": updated_fields,
        }
        if org_name is not None:
            after_value["org_name"] = org_name
        for key in settings_updates:
            if settings_updates[key] is not None:
                after_value[key] = settings_updates[key]
        if first_service_name is not None:
            after_value["first_service_name"] = first_service_name
            if first_service_price is not None:
                after_value["first_service_price"] = first_service_price

        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=user_id,
            action="org.onboarding_step_saved",
            entity_type="organisation",
            entity_id=org_id,
            before_value={"settings": before_settings, "name": before_name},
            after_value=after_value,
            ip_address=ip_address,
        )

    # Check onboarding completeness
    completed_fields = set(new_settings.get("onboarding_completed_fields", []))
    onboarding_complete = ALL_ONBOARDING_FIELDS.issubset(completed_fields)

    return {
        "updated_fields": updated_fields,
        "onboarding_complete": onboarding_complete,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Organisation Settings CRUD (Task 6.3)
# Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
# ---------------------------------------------------------------------------

from app.modules.organisations.schemas import validate_ird_gst_number

# Settings keys stored in the Organisation.settings JSONB column.
SETTINGS_JSONB_KEYS = {
    "logo_url",
    "primary_colour",
    "secondary_colour",
    "address",
    "phone",
    "email",
    "invoice_header_text",
    "invoice_footer_text",
    "email_signature",
    "gst_number",
    "gst_percentage",
    "gst_inclusive",
    "invoice_prefix",
    "invoice_start_number",
    "default_due_days",
    "default_notes",
    "payment_terms_days",
    "payment_terms_text",
    "allow_partial_payments",
    "terms_and_conditions",
}


async def get_org_settings(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict:
    """Retrieve organisation settings for the given org.

    Returns a flat dict with org_name (from the name column) and all
    settings keys from the JSONB column.
    """
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    settings_data = dict(org.settings) if org.settings else {}

    return {
        "org_name": org.name,
        **{key: settings_data.get(key) for key in SETTINGS_JSONB_KEYS},
    }


async def update_org_settings(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    ip_address: str | None = None,
    **kwargs,
) -> dict:
    """Update organisation settings.

    Only non-None kwargs are applied. The org_name field updates the
    Organisation.name column; all other fields update the settings JSONB.

    Returns a dict with ``updated_fields`` list.

    Raises ValueError for validation failures or missing org.
    """
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    before_settings = dict(org.settings) if org.settings else {}
    before_name = org.name
    updated_fields: list[str] = []

    # --- Validate GST number if provided ---
    gst_number = kwargs.get("gst_number")
    if gst_number is not None:
        validate_ird_gst_number(gst_number)

    # --- Update org name (top-level column) ---
    org_name = kwargs.get("org_name")
    if org_name is not None:
        org.name = org_name
        updated_fields.append("org_name")

    # --- Update settings JSONB ---
    new_settings = dict(org.settings) if org.settings else {}

    for key in SETTINGS_JSONB_KEYS:
        value = kwargs.get(key)
        if value is not None:
            new_settings[key] = value
            updated_fields.append(key)

    if not updated_fields:
        return {"updated_fields": []}

    org.settings = new_settings
    await db.flush()

    # Audit log
    after_value = {k: kwargs[k] for k in updated_fields if k in kwargs}
    if org_name is not None:
        after_value["org_name"] = org_name

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="org.settings_updated",
        entity_type="organisation",
        entity_id=org_id,
        before_value={"settings": before_settings, "name": before_name},
        after_value=after_value,
        ip_address=ip_address,
    )

    return {"updated_fields": updated_fields}


# ---------------------------------------------------------------------------
# Branch Management (Task 6.4)
# Requirements: 9.7, 9.8
# ---------------------------------------------------------------------------

from app.modules.organisations.models import Branch
from app.modules.auth.models import User


async def list_branches(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[dict]:
    """Return all active branches for the given organisation.

    Returns a list of dicts with branch fields.
    """
    result = await db.execute(
        select(Branch)
        .where(Branch.org_id == org_id, Branch.is_active.is_(True))
        .order_by(Branch.created_at)
    )
    branches = result.scalars().all()

    return [
        {
            "id": str(branch.id),
            "name": branch.name,
            "address": branch.address,
            "phone": branch.phone,
            "is_active": branch.is_active,
            "created_at": branch.created_at.isoformat() if branch.created_at else None,
        }
        for branch in branches
    ]


async def create_branch(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str,
    address: str | None = None,
    phone: str | None = None,
    ip_address: str | None = None,
) -> dict:
    """Create a new branch for the organisation.

    Returns a dict with the created branch data.
    Raises ValueError if the org doesn't exist.
    """
    # Verify org exists
    result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    branch = Branch(
        org_id=org_id,
        name=name,
        address=address,
        phone=phone,
    )
    db.add(branch)
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="org.branch_created",
        entity_type="branch",
        entity_id=branch.id,
        before_value=None,
        after_value={
            "name": name,
            "address": address,
            "phone": phone,
        },
        ip_address=ip_address,
    )

    return {
        "id": str(branch.id),
        "name": branch.name,
        "address": branch.address,
        "phone": branch.phone,
        "is_active": branch.is_active,
        "created_at": branch.created_at.isoformat() if branch.created_at else None,
    }


async def assign_user_branches(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    branch_ids: list[uuid.UUID],
    ip_address: str | None = None,
) -> dict:
    """Assign a user to one or more branches within the organisation.

    Validates that all branch_ids belong to the org and the target user
    belongs to the org.

    Returns a dict with user_id and assigned branch_ids.
    Raises ValueError on validation failures.
    """
    # Verify target user exists and belongs to org
    result = await db.execute(
        select(User).where(User.id == target_user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found in this organisation")

    # Verify all branches exist and belong to org
    if branch_ids:
        result = await db.execute(
            select(Branch).where(
                Branch.id.in_(branch_ids),
                Branch.org_id == org_id,
                Branch.is_active.is_(True),
            )
        )
        found_branches = result.scalars().all()
        found_ids = {b.id for b in found_branches}
        missing = set(branch_ids) - found_ids
        if missing:
            raise ValueError(
                f"Branch(es) not found in this organisation: "
                f"{', '.join(str(m) for m in missing)}"
            )

    before_branch_ids = list(user.branch_ids) if user.branch_ids else []
    user.branch_ids = [str(bid) for bid in branch_ids]
    await db.flush()

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=acting_user_id,
        action="org.user_branches_assigned",
        entity_type="user",
        entity_id=target_user_id,
        before_value={"branch_ids": before_branch_ids},
        after_value={"branch_ids": [str(bid) for bid in branch_ids]},
        ip_address=ip_address,
    )

    return {
        "user_id": str(target_user_id),
        "branch_ids": [str(bid) for bid in branch_ids],
    }


# ---------------------------------------------------------------------------
# User Management (Task 6.5)
# Requirements: 10.1, 10.2, 10.3, 10.4, 10.5
# ---------------------------------------------------------------------------

from app.modules.auth.models import Session
from app.modules.admin.models import SubscriptionPlan


async def list_org_users(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> dict:
    """Return all users for the given organisation with seat limit info.

    Returns a dict with ``users`` list, ``total`` count, and ``seat_limit``.
    """
    result = await db.execute(
        select(User).where(User.org_id == org_id).order_by(User.created_at)
    )
    users = result.scalars().all()

    # Get seat limit from the org's subscription plan
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    seat_limit = 0
    if org is not None:
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
        )
        plan = plan_result.scalar_one_or_none()
        if plan is not None:
            seat_limit = plan.user_seats

    user_list = [
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "is_email_verified": u.is_email_verified,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]

    return {
        "users": user_list,
        "total": len(user_list),
        "seat_limit": seat_limit,
    }


async def _get_seat_limit_and_count(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> tuple[int, int]:
    """Return (seat_limit, active_user_count) for the organisation."""
    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == org.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    seat_limit = plan.user_seats if plan else 0

    from sqlalchemy import func as sa_func
    count_result = await db.execute(
        select(sa_func.count(User.id)).where(
            User.org_id == org_id,
            User.is_active.is_(True),
        )
    )
    active_count = count_result.scalar() or 0

    return seat_limit, active_count


async def invite_org_user(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    inviter_user_id: uuid.UUID,
    email: str,
    role: str,
    ip_address: str | None = None,
) -> dict:
    """Invite a new user to the organisation.

    Enforces seat limits per the subscription plan (Requirement 10.4).
    When the seat limit is reached, raises ValueError with upgrade message
    (Requirement 10.5).

    Delegates actual user creation and invitation token generation to
    ``auth.service.create_invitation``.

    Returns a dict with user details.
    """
    from app.modules.auth.service import create_invitation

    # Check seat limit (Requirement 10.4, 10.5)
    seat_limit, active_count = await _get_seat_limit_and_count(db, org_id)
    if seat_limit > 0 and active_count >= seat_limit:
        raise SeatLimitExceeded(
            current_users=active_count,
            seat_limit=seat_limit,
        )

    # Delegate to auth service for user creation + invitation token
    result = await create_invitation(
        db,
        inviter_user_id=inviter_user_id,
        org_id=org_id,
        email=email,
        role=role,
        ip_address=ip_address,
    )

    # Fetch the created user for response
    user_result = await db.execute(
        select(User).where(User.id == uuid.UUID(result["user_id"]))
    )
    user = user_result.scalar_one_or_none()

    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "is_email_verified": user.is_email_verified,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


class SeatLimitExceeded(Exception):
    """Raised when the organisation's user seat limit is reached."""

    def __init__(self, current_users: int, seat_limit: int):
        self.current_users = current_users
        self.seat_limit = seat_limit
        super().__init__(
            f"User seat limit reached ({current_users}/{seat_limit}). "
            "Please upgrade your plan to add more users."
        )


async def update_org_user(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role: str | None = None,
    is_active: bool | None = None,
    ip_address: str | None = None,
) -> dict:
    """Update a user's role or active status within the organisation.

    When deactivating (is_active=False), immediately invalidates all
    active sessions for that user (Requirement 10.2).

    Returns a dict with updated user details and sessions_invalidated count.
    Raises ValueError on validation failures.
    """
    # Fetch target user
    result = await db.execute(
        select(User).where(User.id == target_user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found in this organisation")

    before_value = {
        "role": user.role,
        "is_active": user.is_active,
    }
    updated_fields = []
    sessions_invalidated = 0

    # Update role
    if role is not None:
        if role not in ("org_admin", "salesperson"):
            raise ValueError("Role must be 'org_admin' or 'salesperson'")
        user.role = role
        updated_fields.append("role")

    # Update active status
    if is_active is not None:
        user.is_active = is_active
        updated_fields.append("is_active")

        # Deactivate: invalidate all sessions (Requirement 10.2, 3.8)
        if not is_active:
            sessions_invalidated = await _invalidate_user_sessions(
                db, user_id=target_user_id
            )

    if updated_fields:
        await db.flush()

        await write_audit_log(
            session=db,
            org_id=org_id,
            user_id=acting_user_id,
            action="org.user_updated",
            entity_type="user",
            entity_id=target_user_id,
            before_value=before_value,
            after_value={
                "role": user.role,
                "is_active": user.is_active,
                "updated_fields": updated_fields,
                "sessions_invalidated": sessions_invalidated,
            },
            ip_address=ip_address,
        )

    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "is_email_verified": user.is_email_verified,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "sessions_invalidated": sessions_invalidated,
    }


async def deactivate_org_user(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Deactivate a user and invalidate all their sessions.

    Requirement 10.2: deactivation immediately invalidates all active sessions.

    Returns a dict with user_id and sessions_invalidated count.
    Raises ValueError if user not found or trying to deactivate self.
    """
    if acting_user_id == target_user_id:
        raise ValueError("Cannot deactivate your own account")

    result = await db.execute(
        select(User).where(User.id == target_user_id, User.org_id == org_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found in this organisation")

    before_active = user.is_active
    user.is_active = False
    sessions_invalidated = await _invalidate_user_sessions(db, user_id=target_user_id)
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=acting_user_id,
        action="org.user_deactivated",
        entity_type="user",
        entity_id=target_user_id,
        before_value={"is_active": before_active},
        after_value={
            "is_active": False,
            "sessions_invalidated": sessions_invalidated,
        },
        ip_address=ip_address,
    )

    return {
        "user_id": str(target_user_id),
        "sessions_invalidated": sessions_invalidated,
    }


async def _invalidate_user_sessions(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> int:
    """Revoke all active sessions for a user. Returns count of revoked sessions."""
    from sqlalchemy import and_

    result = await db.execute(
        select(Session).where(
            and_(
                Session.user_id == user_id,
                Session.is_revoked.is_(False),
            )
        )
    )
    sessions = result.scalars().all()

    count = 0
    for sess in sessions:
        sess.is_revoked = True
        count += 1

    return count


async def update_mfa_policy(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    mfa_policy: str,
    ip_address: str | None = None,
) -> dict:
    """Update the organisation's MFA policy (optional or mandatory).

    Requirement 10.3: Org_Admin can configure MFA as optional or mandatory.

    Returns a dict with the updated mfa_policy.
    Raises ValueError on invalid policy value.
    """
    if mfa_policy not in ("optional", "mandatory"):
        raise ValueError("MFA policy must be 'optional' or 'mandatory'")

    org_result = await db.execute(
        select(Organisation).where(Organisation.id == org_id)
    )
    org = org_result.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation not found")

    before_policy = (org.settings or {}).get("mfa_policy", "optional")
    new_settings = dict(org.settings) if org.settings else {}
    new_settings["mfa_policy"] = mfa_policy
    org.settings = new_settings
    await db.flush()

    await write_audit_log(
        session=db,
        org_id=org_id,
        user_id=user_id,
        action="org.mfa_policy_updated",
        entity_type="organisation",
        entity_id=org_id,
        before_value={"mfa_policy": before_policy},
        after_value={"mfa_policy": mfa_policy},
        ip_address=ip_address,
    )

    return {"mfa_policy": mfa_policy}


# ---------------------------------------------------------------------------
# Public signup
# ---------------------------------------------------------------------------

_TRIAL_DAYS = 14
_SIGNUP_TOKEN_EXPIRY_SECONDS = 48 * 3600  # 48 hours


def _hash_token(token: str) -> str:
    """SHA-256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


async def public_signup(
    db: AsyncSession,
    *,
    org_name: str,
    admin_email: str,
    admin_first_name: str,
    admin_last_name: str,
    plan_id: uuid.UUID,
    ip_address: str | None = None,
) -> dict:
    """Handle public workshop signup — Requirement 8.6.

    Steps:
    1. Validate the subscription plan exists, is public, and not archived.
    2. Check the admin email is not already registered.
    3. Create the organisation with ``trial`` status and 14-day trial end.
    4. Create an Org_Admin user (unverified, no password).
    5. Create a Stripe customer and SetupIntent for card collection.
    6. Generate a signup token (for onboarding wizard access).
    7. Write audit log entries.

    Returns a dict with org details, Stripe SetupIntent client_secret,
    and a signup token for the frontend to drive the onboarding wizard.

    Raises ``ValueError`` on validation failures.
    """
    from app.core.redis import redis_pool
    from app.integrations.stripe_billing import (
        create_setup_intent,
        create_stripe_customer,
    )

    # 1. Validate plan
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise ValueError("Subscription plan not found")
    if plan.is_archived:
        raise ValueError("Cannot sign up with an archived plan")
    if not plan.is_public:
        raise ValueError("Selected plan is not available for public signup")

    # 2. Check email uniqueness
    email_result = await db.execute(
        select(User).where(User.email == admin_email)
    )
    if email_result.scalar_one_or_none() is not None:
        raise ValueError("A user with this email already exists")

    # 3. Create organisation with trial status
    now = datetime.now(timezone.utc)
    trial_ends_at = now + timedelta(days=_TRIAL_DAYS)

    org = Organisation(
        name=org_name,
        plan_id=plan_id,
        status="trial",
        trial_ends_at=trial_ends_at,
        storage_quota_gb=plan.storage_quota_gb,
    )
    db.add(org)
    await db.flush()

    # 4. Create Org_Admin user
    admin_user = User(
        org_id=org.id,
        email=admin_email,
        role="org_admin",
        is_active=True,
        is_email_verified=False,
        password_hash=None,
    )
    db.add(admin_user)
    await db.flush()

    # 5. Stripe customer + SetupIntent
    stripe_customer_id = await create_stripe_customer(
        email=admin_email,
        name=org_name,
        metadata={
            "org_id": str(org.id),
            "admin_user_id": str(admin_user.id),
        },
    )
    org.stripe_customer_id = stripe_customer_id
    await db.flush()

    setup_intent = await create_setup_intent(
        customer_id=stripe_customer_id,
        metadata={
            "org_id": str(org.id),
            "signup": "true",
        },
    )

    # 6. Generate signup token (stored in Redis, 48h TTL)
    signup_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(signup_token)
    token_data = json.dumps({
        "user_id": str(admin_user.id),
        "email": admin_email,
        "org_id": str(org.id),
        "created_at": now.isoformat(),
        "type": "signup",
    })
    await redis_pool.setex(
        f"signup:{token_hash}",
        _SIGNUP_TOKEN_EXPIRY_SECONDS,
        token_data,
    )

    # 7. Audit log
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=admin_user.id,
        action="org.public_signup",
        entity_type="organisation",
        entity_id=org.id,
        after_value={
            "name": org_name,
            "plan_id": str(plan_id),
            "plan_name": plan.name,
            "status": "trial",
            "trial_ends_at": trial_ends_at.isoformat(),
            "admin_email": admin_email,
            "admin_user_id": str(admin_user.id),
            "stripe_customer_id": stripe_customer_id,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    return {
        "organisation_id": str(org.id),
        "organisation_name": org_name,
        "plan_id": str(plan_id),
        "admin_user_id": str(admin_user.id),
        "admin_email": admin_email,
        "trial_ends_at": trial_ends_at,
        "stripe_setup_intent_client_secret": setup_intent["client_secret"],
        "signup_token": signup_token,
    }
