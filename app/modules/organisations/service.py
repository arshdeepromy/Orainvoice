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
    "address_unit",
    "address_street",
    "address_city",
    "address_state",
    "address_country",
    "address_postcode",
    "website",
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
    "sidebar_display_mode",
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

_SIGNUP_TOKEN_EXPIRY_SECONDS = 48 * 3600  # 48 hours


def _hash_token(token: str) -> str:
    """SHA-256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _compute_trial_end(plan, now: datetime) -> datetime | None:
    """Compute trial end date from plan's trial_duration and trial_duration_unit.

    Returns None if the plan has no trial configured (duration <= 0).
    """
    duration = plan.trial_duration or 0
    unit = plan.trial_duration_unit or "days"

    if duration <= 0:
        return None

    if unit == "weeks":
        return now + timedelta(weeks=duration)
    elif unit == "months":
        # Approximate months as 30 days each
        return now + timedelta(days=duration * 30)
    else:
        return now + timedelta(days=duration)


async def _load_signup_billing_config() -> dict:
    """Load signup billing config (GST%, Stripe fees) from platform_settings."""
    from app.core.redis import redis_pool as _redis
    import json as _json

    # Try Redis cache first
    cached = await _redis.get("signup_billing_config")
    if cached:
        return _json.loads(cached)

    # Fall back to DB
    from app.core.database import async_session_factory
    from sqlalchemy import text as sa_text

    defaults = {
        "gst_percentage": 15.0,
        "stripe_fee_percentage": 2.9,
        "stripe_fee_fixed_cents": 30,
        "pass_fees_to_customer": True,
    }

    try:
        async with async_session_factory() as session:
            row = await session.execute(
                sa_text("SELECT value FROM platform_settings WHERE key = :k"),
                {"k": "signup_billing"},
            )
            sb_row = row.scalar_one_or_none()
            if sb_row:
                val = sb_row if isinstance(sb_row, dict) else _json.loads(sb_row)
                config = {
                    "gst_percentage": val.get("gst_percentage", 15.0),
                    "stripe_fee_percentage": val.get("stripe_fee_percentage", 2.9),
                    "stripe_fee_fixed_cents": val.get("stripe_fee_fixed_cents", 30),
                    "pass_fees_to_customer": val.get("pass_fees_to_customer", True),
                }
            else:
                config = defaults

        # Cache for 5 minutes
        await _redis.setex("signup_billing_config", 300, _json.dumps(config))
        return config
    except Exception:
        return defaults


def _compute_billing_breakdown(
    plan_amount_cents: int,
    billing_config: dict,
) -> dict:
    """Compute GST and Stripe processing fee on top of plan price.

    Returns dict with plan_amount_cents, gst_amount_cents,
    processing_fee_cents, and total_amount_cents.

    Formula:
      subtotal = plan_amount + GST
      processing_fee = (subtotal + fixed_fee) / (1 - stripe_pct/100) - subtotal
      total = subtotal + processing_fee
    """
    gst_pct = billing_config.get("gst_percentage", 15.0)
    stripe_pct = billing_config.get("stripe_fee_percentage", 2.9)
    stripe_fixed = billing_config.get("stripe_fee_fixed_cents", 30)
    pass_fees = billing_config.get("pass_fees_to_customer", True)

    gst_amount_cents = round(plan_amount_cents * gst_pct / 100)
    subtotal = plan_amount_cents + gst_amount_cents

    if pass_fees and subtotal > 0:
        # Reverse-engineer the Stripe fee so the net received = subtotal
        # Stripe takes: (total * stripe_pct/100) + stripe_fixed
        # We want: total - stripe_fee = subtotal
        # So: total = (subtotal + stripe_fixed) / (1 - stripe_pct/100)
        total = round((subtotal + stripe_fixed) / (1 - stripe_pct / 100))
        processing_fee_cents = total - subtotal
    else:
        processing_fee_cents = 0
        total = subtotal

    return {
        "plan_amount_cents": plan_amount_cents,
        "gst_amount_cents": gst_amount_cents,
        "gst_percentage": gst_pct,
        "processing_fee_cents": processing_fee_cents,
        "total_amount_cents": total,
    }


async def public_signup(
    db: AsyncSession,
    *,
    org_name: str,
    admin_email: str,
    admin_first_name: str,
    admin_last_name: str,
    password: str,
    plan_id: uuid.UUID,
    ip_address: str | None = None,
    base_url: str = "http://localhost",
    coupon_code: str | None = None,
) -> dict:
    """Handle public workshop signup — Requirement 8.6.

    Two code paths based on plan type:

    **Paid plan (trial_duration == 0):**
    Store validated form data in Redis as a Pending_Signup, create a
    Stripe PaymentIntent (without a Stripe Customer), and return the
    client secret.  No Organisation or User records are created.

    **Trial plan (trial_duration > 0):**
    Create Organisation + User immediately, send verification email,
    return organisation details.

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
        raise ValueError("Cannot sign up with an archived plan")
    if not plan.is_public:
        raise ValueError("Selected plan is not available for public signup")

    # 2. Check email uniqueness
    email_result = await db.execute(
        select(User).where(User.email == admin_email)
    )
    if email_result.scalar_one_or_none() is not None:
        raise ValueError("A user with this email already exists")

    now = datetime.now(timezone.utc)
    trial_ends_at = _compute_trial_end(plan, now)

    # -----------------------------------------------------------------------
    # PAID PLAN FLOW — trial_duration == 0
    # -----------------------------------------------------------------------
    if not trial_ends_at:
        plan_amount_cents = int(float(plan.monthly_price_nzd) * 100)

        # $0 plans should skip payment entirely (same as trial flow)
        if plan_amount_cents == 0 and not coupon_code:
            org = Organisation(
                name=org_name,
                plan_id=plan_id,
                status="active",
                storage_quota_gb=plan.storage_quota_gb,
            )
            db.add(org)
            await db.flush()

            from app.modules.auth.password import hash_password as _hash_pw

            admin_user = User(
                org_id=org.id,
                email=admin_email,
                first_name=admin_first_name or None,
                last_name=admin_last_name or None,
                role="org_admin",
                is_active=True,
                is_email_verified=False,
                password_hash=_hash_pw(password),
            )
            db.add(admin_user)
            await db.flush()

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
                    "status": "active",
                    "admin_email": admin_email,
                    "admin_user_id": str(admin_user.id),
                    "ip_address": ip_address,
                },
                ip_address=ip_address,
            )

            from app.modules.auth.service import (
                create_email_verification_token,
                send_verification_email,
            )
            user_name = (
                f"{admin_first_name} {admin_last_name}".strip()
                or admin_email.split("@")[0]
            )
            verification_token = await create_email_verification_token(
                admin_user.id, admin_email,
            )
            await send_verification_email(
                db,
                email=admin_email,
                user_name=user_name,
                org_name=org_name,
                verification_token=verification_token,
                base_url=base_url,
            )

            return {
                "organisation_id": str(org.id),
                "organisation_name": org_name,
                "plan_id": str(plan_id),
                "admin_user_id": str(admin_user.id),
                "admin_email": admin_email,
                "requires_payment": False,
                "payment_amount_cents": 0,
                "signup_token": signup_token,
            }

        # --- Coupon discount logic (Req 5.2, 5.3, 5.4) ---
        coupon_discount_type: str | None = None
        coupon_discount_value: float | None = None

        if coupon_code:
            from app.modules.admin.service import validate_coupon

            coupon_result = await validate_coupon(db, coupon_code)
            if not coupon_result.get("valid"):
                raise ValueError(
                    coupon_result.get("error", "Invalid coupon code")
                )

            coupon_info = coupon_result["coupon"]
            coupon_discount_type = coupon_info["discount_type"]
            coupon_discount_value = coupon_info["discount_value"]

            if coupon_discount_type == "trial_extension":
                # Convert paid plan to trial flow with extended duration
                # discount_value = number of days for the trial
                extended_days = int(coupon_discount_value)
                trial_ends_at = now + timedelta(days=extended_days)
                # Fall through to the trial plan flow below
                # (trial_ends_at is now set, so the `if not trial_ends_at`
                # block will end and the trial flow will execute)

            elif coupon_discount_type == "percentage":
                plan_amount_cents = round(
                    plan_amount_cents * (1 - coupon_discount_value / 100)
                )
            elif coupon_discount_type == "fixed_amount":
                discount_cents = int(coupon_discount_value * 100)
                plan_amount_cents = max(0, plan_amount_cents - discount_cents)

        # If a trial-extension coupon was applied, skip the paid flow
        # entirely and fall through to the trial plan flow below.
        if trial_ends_at:
            pass  # Will be handled by the trial plan flow below
        elif plan_amount_cents == 0:
            # Coupon reduced price to zero — create account immediately
            # (Req 5.3: skip PaymentIntent, return requires_payment=False)
            org = Organisation(
                name=org_name,
                plan_id=plan_id,
                status="active",
                storage_quota_gb=plan.storage_quota_gb,
            )
            db.add(org)
            await db.flush()

            from app.modules.auth.password import hash_password as _hash_pw

            admin_user = User(
                org_id=org.id,
                email=admin_email,
                first_name=admin_first_name or None,
                last_name=admin_last_name or None,
                role="org_admin",
                is_active=True,
                is_email_verified=False,
                password_hash=_hash_pw(password),
            )
            db.add(admin_user)
            await db.flush()

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
                    "status": "active",
                    "coupon_code": coupon_code,
                    "admin_email": admin_email,
                    "admin_user_id": str(admin_user.id),
                    "ip_address": ip_address,
                },
                ip_address=ip_address,
            )

            from app.modules.auth.service import (
                create_email_verification_token,
                send_verification_email,
            )
            user_name = (
                f"{admin_first_name} {admin_last_name}".strip()
                or admin_email.split("@")[0]
            )
            verification_token = await create_email_verification_token(
                admin_user.id, admin_email,
            )
            await send_verification_email(
                db,
                email=admin_email,
                user_name=user_name,
                org_name=org_name,
                verification_token=verification_token,
                base_url=base_url,
            )

            return {
                "organisation_id": str(org.id),
                "organisation_name": org_name,
                "plan_id": str(plan_id),
                "admin_user_id": str(admin_user.id),
                "admin_email": admin_email,
                "requires_payment": False,
                "payment_amount_cents": 0,
                "signup_token": signup_token,
            }
        # --- End coupon discount logic ---

        if not trial_ends_at:
            # Normal paid flow — compute billing breakdown, store pending signup, create PaymentIntent
            billing_config = await _load_signup_billing_config()
            breakdown = _compute_billing_breakdown(plan_amount_cents, billing_config)
            payment_amount_cents = breakdown["total_amount_cents"]

            from app.modules.auth.pending_signup import replace_pending_signup_for_email

            pending_data = {
                "org_name": org_name,
                "admin_email": admin_email,
                "admin_first_name": admin_first_name,
                "admin_last_name": admin_last_name,
                "password": password,
                "plan_id": str(plan_id),
                "plan_name": plan.name,
                "payment_amount_cents": payment_amount_cents,
                "plan_amount_cents": breakdown["plan_amount_cents"],
                "gst_amount_cents": breakdown["gst_amount_cents"],
                "gst_percentage": breakdown["gst_percentage"],
                "processing_fee_cents": breakdown["processing_fee_cents"],
                "coupon_code": coupon_code,
                "coupon_discount_type": coupon_discount_type,
                "coupon_discount_value": coupon_discount_value,
                "ip_address": ip_address,
                "created_at": now.isoformat(),
            }
            pending_signup_id = await replace_pending_signup_for_email(
                admin_email, pending_data,
            )

            # Create Stripe PaymentIntent WITHOUT a Stripe Customer
            from app.integrations.stripe_billing import create_payment_intent_no_customer

            try:
                pi_result = await create_payment_intent_no_customer(
                    amount_cents=payment_amount_cents,
                    currency="nzd",
                    metadata={
                        "pending_signup_id": pending_signup_id,
                        "plan_id": str(plan_id),
                        "signup": "true",
                    },
                )
                stripe_client_secret = pi_result["client_secret"]
                stripe_pi_id = pi_result["payment_intent_id"]
            except Exception as exc:
                logger.warning(
                    "Stripe PaymentIntent creation failed for %s: %s",
                    admin_email, exc,
                )
                raise ValueError("Payment setup failed. Please try again.")

            # Update the pending signup with the Stripe PI ID
            from app.modules.auth.pending_signup import get_pending_signup
            from app.core.redis import redis_pool as _redis

            stored = await get_pending_signup(pending_signup_id)
            if stored:
                stored["stripe_payment_intent_id"] = stripe_pi_id
                import json as _json
                await _redis.setex(
                    f"pending_signup:{pending_signup_id}",
                    1800,
                    _json.dumps(stored, default=str),
                )

            return {
                "requires_payment": True,
                "pending_signup_id": pending_signup_id,
                "stripe_client_secret": stripe_client_secret,
                "payment_amount_cents": payment_amount_cents,
                "plan_amount_cents": breakdown["plan_amount_cents"],
                "gst_amount_cents": breakdown["gst_amount_cents"],
                "gst_percentage": breakdown["gst_percentage"],
                "processing_fee_cents": breakdown["processing_fee_cents"],
                "plan_name": plan.name,
                "admin_email": admin_email,
            }

    # -----------------------------------------------------------------------
    # TRIAL PLAN FLOW — trial_duration > 0 (existing logic, unchanged)
    # -----------------------------------------------------------------------
    org = Organisation(
        name=org_name,
        plan_id=plan_id,
        status="trial",
        trial_ends_at=trial_ends_at,
        storage_quota_gb=plan.storage_quota_gb,
    )
    db.add(org)
    await db.flush()

    # Create Org_Admin user with hashed password
    from app.modules.auth.password import hash_password

    password_hash = hash_password(password)
    admin_user = User(
        org_id=org.id,
        email=admin_email,
        first_name=admin_first_name or None,
        last_name=admin_last_name or None,
        role="org_admin",
        is_active=True,
        is_email_verified=False,  # Must verify email before login
        password_hash=password_hash,
    )
    db.add(admin_user)
    await db.flush()

    # Generate signup token (stored in Redis, 48h TTL)
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

    # Audit log
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
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    # Send verification email
    from app.modules.auth.service import (
        create_email_verification_token,
        send_verification_email,
    )
    user_name = f"{admin_first_name} {admin_last_name}".strip() or admin_email.split("@")[0]
    verification_token = await create_email_verification_token(admin_user.id, admin_email)

    await send_verification_email(
        db,
        email=admin_email,
        user_name=user_name,
        org_name=org_name,
        verification_token=verification_token,
        base_url=base_url,
    )

    return {
        "organisation_id": str(org.id),
        "organisation_name": org_name,
        "plan_id": str(plan_id),
        "admin_user_id": str(admin_user.id),
        "admin_email": admin_email,
        "trial_ends_at": trial_ends_at,
        "requires_payment": False,
        "payment_amount_cents": 0,
        "signup_token": signup_token,
    }


async def list_salespeople(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
) -> list[dict]:
    """Return a simple list of active users for the salesperson dropdown.

    Returns only id and display name (email) for active users.
    This endpoint is accessible by both org_admin and salesperson roles.
    """
    result = await db.execute(
        select(User).where(
            User.org_id == org_id,
            User.is_active.is_(True),
        ).order_by(User.email)
    )
    users = result.scalars().all()

    return [
        {
            "id": str(u.id),
            "name": u.email,  # Use email as display name
        }
        for u in users
    ]
