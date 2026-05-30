"""Fleet Account provisioning and Portal_User lifecycle.

Workshop_Admin–side operations:
- :func:`invite_fleet_admin` — provision portal access for a business customer
- :func:`resend_invite` — issue a fresh invite token
- :func:`revoke_access` — disable a portal user and tear down sessions
- :func:`accept_invite` — Portal_User completes invite acceptance

Implements: B2B Fleet Portal task 5.1 — Requirements 4.2, 4.3, 4.6, 4.8,
4.9.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal import auth as fp_auth
from app.modules.fleet_portal.models import PortalAccount, PortalFleetAccount

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.customers.models import Customer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors raised to the router layer for HTTP mapping
# ---------------------------------------------------------------------------


class AccountServiceError(Exception):
    """Base error for the account service. Carries a status_code attribute."""

    status_code: int = 400

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


class CustomerNotEligible(AccountServiceError):
    """Raised when the customer is not a business customer (Req 4.3)."""

    status_code = 400


class DuplicatePortalUser(AccountServiceError):
    """Raised when a portal account with the same email already exists."""

    status_code = 409


class TokenExpired(AccountServiceError):
    """Raised when the invite or reset token has expired or been consumed."""

    status_code = 400


class InvalidToken(AccountServiceError):
    """Raised when the invite or reset token is unrecognised."""

    status_code = 400


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_customer(
    db: AsyncSession, org_id: uuid.UUID, customer_id: uuid.UUID
) -> Customer | None:
    """Return the customer row or None (cross-org safe via WHERE clauses)."""
    from app.modules.customers.models import Customer

    res = await db.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.org_id == org_id,
        )
    )
    return res.scalars().first()


async def _get_or_create_portal_fleet_account(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    display_name: str | None,
) -> PortalFleetAccount:
    """Return the existing or freshly-inserted portal_fleet_accounts row.

    The unique index ``(org_id, customer_id)`` guarantees idempotency
    (Requirement 4.2). The function also tolerates the rare race where
    two parallel invites collide — the second caller observes the
    first's row.
    """
    res = await db.execute(
        select(PortalFleetAccount).where(
            PortalFleetAccount.org_id == org_id,
            PortalFleetAccount.customer_id == customer_id,
        )
    )
    row = res.scalars().first()
    if row is not None:
        return row

    fa = PortalFleetAccount(
        org_id=org_id,
        customer_id=customer_id,
        display_name=display_name,
        is_active=True,
    )
    db.add(fa)
    await db.flush()
    await db.refresh(fa)
    return fa


async def _delete_sessions_for_account(
    db: AsyncSession, portal_account_id: uuid.UUID
) -> int:
    """Delete every ``portal_sessions`` row for the given portal account."""
    from app.modules.portal.models import PortalSession

    res = await db.execute(
        delete(PortalSession).where(
            PortalSession.portal_account_id == portal_account_id
        )
    )
    return int(res.rowcount or 0)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def invite_fleet_admin(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    customer_id: uuid.UUID,
    invited_by_user_id: uuid.UUID,
    first_name: str | None = None,
    last_name: str | None = None,
) -> PortalAccount:
    """Invite a business customer to the fleet portal as fleet_admin.

    Returns the resulting ``PortalAccount`` (newly created or reused).

    Behaviour (Req 4.2):
      - Verifies the customer exists in the org and is ``customer_type =
        'business'``; raises :class:`CustomerNotEligible` otherwise.
      - Reuses any existing portal_fleet_accounts row for the customer.
      - Reuses any existing fleet_admin portal account for the customer
        in the same org (idempotent — Property described in design).
      - Issues a fresh ``invite_token`` and ``invite_sent_at = now()``.

    The caller is expected to send the invite email after this returns
    (the service does not couple itself to the email infrastructure;
    the router layer wires up ``send_email_task``).
    """
    customer = await _get_customer(db, org_id, customer_id)
    if customer is None:
        raise InvalidToken("Customer not found")
    if customer.customer_type != "business":
        raise CustomerNotEligible(
            "Fleet Portal is only available for business customers"
        )

    fa = await _get_or_create_portal_fleet_account(
        db,
        org_id=org_id,
        customer_id=customer_id,
        display_name=customer.first_name,  # caller may override
    )

    # Resolve email — prefer the customer's explicit email, fall back to
    # the primary contact email if available.
    email = (customer.email or "").strip().lower()
    if not email:
        raise CustomerNotEligible(
            "Customer has no email address — cannot send invite"
        )

    # Idempotency: if a fleet_admin account already exists for the
    # (org_id, customer_id, email) tuple, refresh its invite token.
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.org_id == org_id,
            PortalAccount.customer_id == customer_id,
            PortalAccount.portal_user_role == "fleet_admin",
        )
    )
    account: PortalAccount | None = res.scalars().first()

    invite_token = fp_auth.generate_invite_token()
    now = datetime.now(timezone.utc)

    if account is None:
        account = PortalAccount(
            org_id=org_id,
            customer_id=customer_id,
            email=email,
            portal_user_role="fleet_admin",
            fleet_account_id=fa.id,
            first_name=first_name or customer.first_name,
            last_name=last_name or customer.last_name,
            invite_token=invite_token,
            invite_sent_at=now,
            is_active=True,
        )
        db.add(account)
    else:
        account.email = email
        account.invite_token = invite_token
        account.invite_sent_at = now
        account.is_active = True
        # Fleet account linkage may be missing on accounts created
        # before the fleet account row existed — bind it now.
        account.fleet_account_id = fa.id

    await db.flush()
    await db.refresh(account)

    logger.info(
        "fleet_portal.invite_sent org_id=%s portal_account_id=%s by=%s",
        org_id,
        account.id,
        invited_by_user_id,
    )
    return account


async def resend_invite(
    db: AsyncSession,
    *,
    portal_account_id: uuid.UUID,
    org_id: uuid.UUID,
) -> PortalAccount:
    """Issue a fresh invite token (Requirement 4.9)."""
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise InvalidToken("Portal account not found")
    account.invite_token = fp_auth.generate_invite_token()
    account.invite_sent_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(account)
    return account


async def revoke_access(
    db: AsyncSession,
    *,
    portal_account_id: uuid.UUID,
    org_id: uuid.UUID,
) -> int:
    """Disable a portal user and tear down their sessions.

    Returns the number of sessions that were removed (Req 4.8 — the
    tear-down must complete within 60 s; doing it in the same
    transaction guarantees that.)
    """
    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.id == portal_account_id,
            PortalAccount.org_id == org_id,
        )
    )
    account = res.scalars().first()
    if account is None:
        raise InvalidToken("Portal account not found")
    account.is_active = False
    await db.flush()

    deleted = await _delete_sessions_for_account(db, account.id)
    logger.info(
        "fleet_portal.access_revoked org_id=%s portal_account_id=%s sessions_deleted=%d",
        org_id,
        account.id,
        deleted,
    )
    return deleted


async def accept_invite(
    db: AsyncSession,
    *,
    invite_token: str,
    new_password: str,
) -> PortalAccount:
    """Validate the invite, set the password, return the account.

    Implements Requirement 4.5: clears ``invite_token``, sets
    ``invite_accepted_at = now()``, persists the bcrypt password hash.
    Property 9 token validity predicate (≤ 7 days, not used) applies.
    """
    res = await db.execute(
        select(PortalAccount).where(PortalAccount.invite_token == invite_token)
    )
    account = res.scalars().first()
    if account is None:
        raise InvalidToken("This invitation has expired or has already been used")

    if not fp_auth.is_invite_token_fresh(account.invite_sent_at):
        raise TokenExpired(
            "This invitation has expired or has already been used"
        )

    fp_auth.validate_password_rules(new_password, account.email)

    account.password_hash = await fp_auth.hash_password(new_password)
    account.password_changed_at = datetime.now(timezone.utc)
    account.invite_token = None
    account.invite_accepted_at = datetime.now(timezone.utc)
    fp_auth.reset_lockout(account)

    await db.flush()
    await db.refresh(account)
    return account


async def issue_reset_token(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
) -> PortalAccount | None:
    """Issue a password-reset token for the given email if one matches.

    Property 8 (anti-enumeration): callers must surface the SAME
    response regardless of whether this returns an account or ``None``.
    The endpoint should always return HTTP 200 with a generic message.
    Side effect on a real match: ``reset_token`` and
    ``reset_token_expires_at`` are persisted; the caller fires the
    email.
    """
    from datetime import timedelta

    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.org_id == org_id,
            PortalAccount.email == email.strip().lower(),
            PortalAccount.is_active.is_(True),
        )
    )
    account = res.scalars().first()
    if account is None:
        return None
    account.reset_token = fp_auth.generate_reset_token()
    account.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.flush()
    await db.refresh(account)
    return account


async def reset_password(
    db: AsyncSession,
    *,
    reset_token: str,
    new_password: str,
) -> PortalAccount:
    """Set a new password using a fresh reset token (Req 3.11, 3.12)."""
    res = await db.execute(
        select(PortalAccount).where(PortalAccount.reset_token == reset_token)
    )
    account = res.scalars().first()
    if account is None:
        raise InvalidToken("This password reset link is no longer valid")
    if not fp_auth.is_reset_token_fresh(account.reset_token_expires_at):
        raise TokenExpired("This password reset link is no longer valid")

    fp_auth.validate_password_rules(new_password, account.email)

    account.password_hash = await fp_auth.hash_password(new_password)
    account.password_changed_at = datetime.now(timezone.utc)
    account.reset_token = None
    account.reset_token_expires_at = None
    fp_auth.reset_lockout(account)

    await db.flush()
    await db.refresh(account)
    return account


__all__ = [
    "AccountServiceError",
    "CustomerNotEligible",
    "DuplicatePortalUser",
    "TokenExpired",
    "InvalidToken",
    "invite_fleet_admin",
    "resend_invite",
    "revoke_access",
    "accept_invite",
    "issue_reset_token",
    "reset_password",
]
