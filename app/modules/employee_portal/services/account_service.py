"""Employee Portal credential lifecycle — issue / accept / reset / revoke.

Org_Admin–side and Portal_User–side operations on ``employee_portal_users``:

- :func:`issue_access` — Org_Admin provisions portal access for a Staff_Member
  (app-level dup check, INSERT with a hashed single-use invite token).
- :func:`accept_invite` — the invited Staff_Member sets their password using
  the emailed invite link (single-use, ≤7-day validity).
- :func:`request_reset` / :func:`complete_reset` — password-reset issuance and
  completion (single-use token, 60-minute / 3600-second validity, sessions
  torn down on success).
- :func:`revoke_access` / :func:`revoke_portal_access_for_staff` — Org_Admin
  revoke and auto-revoke-on-deactivation: deactivate the Portal_User and delete
  its sessions in the same transaction.

Mirrors the B2B Fleet Portal's ``app/modules/fleet_portal/services/
account_service.py`` but with two deliberate security uplifts (per design):

1. Invite and reset tokens are generated with ``secrets.token_urlsafe(32)`` and
   persisted **only** as SHA-256 hashes (``invite_token_hash`` /
   ``reset_token_hash``); the raw token lives only in the emailed URL. A
   DB-read attacker therefore cannot replay a live credential link.
2. Tokens are strictly single-use: the stored hash is cleared on successful
   consumption, and an expired / already-used / unknown token is rejected and
   leaves the stored hash unchanged.

This module uses ``flush()`` (never ``commit()``): the ``get_db_session``
dependency wraps the request in ``session.begin()`` and auto-commits, so every
write here (the credential row, the audit row, the session deletions) commits
or rolls back atomically with the request.

Implements: Organisation Employee Portal task 6.1 — Requirements 5.3, 5.5,
5.7, 5.8, 5.9, 5.10, 5.11, 14.3, 14.5, 14.6, 14.8.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal.models import (
    EmployeePortalAuditLog,
    EmployeePortalUser,
)
from app.modules.employee_portal.services import session_service

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.staff.models import StaffMember

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token validity windows (design / R5.8, R5.9, R14.3)
# ---------------------------------------------------------------------------

# Invite (set-password) link validity — 7 days from issuance (R5.8, R5.9).
INVITE_VALIDITY = timedelta(days=7)

# Password-reset token validity — 60 minutes / 3600 seconds from issuance
# (R14.3).
RESET_VALIDITY = timedelta(seconds=3600)


# ---------------------------------------------------------------------------
# Errors raised to the router layer for HTTP mapping
# ---------------------------------------------------------------------------


class AccountServiceError(Exception):
    """Base error for the account service.

    Carries ``status_code`` (the HTTP status the router should emit) and a
    machine-readable ``code`` matching the design's documented error codes
    (``email_required``, ``duplicate``, ``invite_expired``,
    ``password_length``, ``invite_not_found``, ``reset_token_invalid``).
    """

    status_code: int = 400
    code: str = "account_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class EmailRequired(AccountServiceError):
    """Staff_Member has no email — cannot issue portal access (R15.6)."""

    status_code = 422
    code = "email_required"


class DuplicatePortalUser(AccountServiceError):
    """An active Portal_User with the same normalised email already exists (R5.7)."""

    status_code = 409
    code = "duplicate"


class InviteExpired(AccountServiceError):
    """The invitation's 7-day validity has elapsed, or it was already used (R5.9)."""

    status_code = 410
    code = "invite_expired"


class InviteNotFound(AccountServiceError):
    """The invite token is unknown or already consumed."""

    status_code = 404
    code = "invite_not_found"


class PasswordLengthError(AccountServiceError):
    """The submitted password is not 8..128 characters (R5.6, R14.7)."""

    status_code = 422
    code = "password_length"


class ResetTokenInvalid(AccountServiceError):
    """The reset token is expired, already used, or unrecognised (R14.6)."""

    status_code = 400
    code = "reset_token_invalid"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return the current UTC time. Hoisted so tests can monkey-patch it."""
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a raw token for storage.

    Mirrors ``session_service._hash_token`` so the whole portal uses a single
    token-hashing convention. The raw token is never persisted; only this
    deterministic hash is, so a lookup hashes the supplied value and matches on
    the stored ``*_token_hash`` column.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _as_aware(value: datetime) -> datetime:
    """Normalise a possibly-naive datetime to timezone-aware UTC.

    Token timestamps are timezone-aware in the database, but a caller (or a
    property-test generator) may hand us a naive value; comparing naive and
    aware datetimes raises ``TypeError``. Normalising here keeps the freshness
    checks total over their input domain.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _normalise_email(email: str | None) -> str:
    """Trim + lowercase — the single normalisation used for dedup and storage.

    Matches the partial unique index ``uq_emp_portal_users_org_email_active``
    (keyed on ``lower(email)``) and the app-level dup check, so the application
    and the database reach identical duplicate determinations (R5.2, R5.7).
    """
    return (email or "").strip().lower()


def _write_audit(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    action: str,
    outcome: str,
    portal_user_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    """Append an ``employee_portal_audit_log`` row (R16.5).

    Added to the session only — it commits/rolls back atomically with the
    triggering change because the request runs inside ``session.begin()``.
    """
    db.add(
        EmployeePortalAuditLog(
            org_id=org_id,
            portal_user_id=portal_user_id,
            actor_user_id=actor_user_id,
            action=action,
            outcome=outcome,
            ip_address=ip_address,
            details=details,
        )
    )


# ---------------------------------------------------------------------------
# Credential issuance (R5.3, R5.5, R5.7, R5.8)
# ---------------------------------------------------------------------------


async def issue_access(
    db: AsyncSession,
    org_id: uuid.UUID,
    staff: StaffMember,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> tuple[EmployeePortalUser, str]:
    """Issue Employee_Portal access for ``staff`` and return ``(user, raw_token)``.

    Flow (R5.3, R5.5, R5.7, R5.8):
      1. Require ``staff.email`` — raise :class:`EmailRequired` otherwise (R15.6).
      2. App-level dup check: reject if an **active** Portal_User in this org
         already holds the same normalised (``lower(btrim(email))``) email,
         raising :class:`DuplicatePortalUser` and leaving everything unchanged
         (R5.7). The DB partial unique index is the authoritative guard.
      3. INSERT an ``employee_portal_users`` row with ``is_active=True``,
         ``invite_token_hash = sha256(raw)``, ``invite_sent_at = now``, and
         ``password_hash = NULL`` (set only when the invite is accepted, R5.5).
      4. Write a ``credential_issued`` audit row.

    The raw invite token is returned exactly once so the API layer can build the
    branded ``/e/{slug}/accept-invite/{token}`` URL and email it; only its
    SHA-256 hash is persisted, so it cannot be recovered afterward.
    """
    email = _normalise_email(staff.email)
    if not email:
        raise EmailRequired("Staff member has no email address — cannot issue access")

    # App-level duplicate check — identical normalisation to the DB index.
    existing = await db.execute(
        select(EmployeePortalUser.id).where(
            EmployeePortalUser.org_id == org_id,
            func.lower(EmployeePortalUser.email) == email,
            EmployeePortalUser.is_active.is_(True),
        )
    )
    if existing.first() is not None:
        raise DuplicatePortalUser(
            "An active portal user already exists for this email address"
        )

    raw_token = secrets.token_urlsafe(32)
    now = _now_utc()

    user = EmployeePortalUser(
        org_id=org_id,
        staff_id=staff.id,
        email=email,
        password_hash=None,
        is_active=True,
        invite_token_hash=_hash_token(raw_token),
        invite_sent_at=now,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    _write_audit(
        db,
        org_id=org_id,
        action="credential_issued",
        outcome="success",
        portal_user_id=user.id,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        details={"staff_id": str(staff.id)},
    )

    logger.info(
        "employee_portal.credential_issued org_id=%s portal_user_id=%s staff_id=%s",
        org_id,
        user.id,
        staff.id,
    )
    return user, raw_token


# ---------------------------------------------------------------------------
# Invite acceptance — set password (R5.5, R5.6, R5.8, R5.9)
# ---------------------------------------------------------------------------


async def accept_invite(
    db: AsyncSession,
    raw_token: str,
    new_password: str,
) -> EmployeePortalUser:
    """Set the password for an invited Portal_User using a single-use invite.

    Resolves the Portal_User by ``sha256(raw_token)``; requires the invite to be
    fresh (issued ≤7 days ago **and** not already accepted, R5.9); validates the
    password length (8..128, R5.6); then sets ``password_hash = bcrypt(pw)``,
    ``invite_accepted_at = now``, clears the lockout state, and clears
    ``invite_token_hash`` so the link is single-use (the plaintext is never
    stored, R5.5).

    On any failure the stored credential state is left unchanged:
      - unknown / already-consumed token → :class:`InviteNotFound`
      - invite older than 7 days or already accepted → :class:`InviteExpired`
      - password not 8..128 chars → :class:`PasswordLengthError`
    """
    token_hash = _hash_token(raw_token)
    res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.invite_token_hash == token_hash
        )
    )
    user = res.scalars().first()
    if user is None:
        raise InviteNotFound("This invitation is invalid or has already been used")

    # Fresh iff not yet accepted and within the 7-day validity window (R5.9).
    if user.invite_accepted_at is not None:
        raise InviteExpired("This invitation has expired or has already been used")
    if user.invite_sent_at is None or _as_aware(user.invite_sent_at) + INVITE_VALIDITY < _now_utc():
        raise InviteExpired("This invitation has expired or has already been used")

    ok, message = ep_auth.validate_password_length(new_password)
    if not ok:
        raise PasswordLengthError(message)

    now = _now_utc()
    user.password_hash = await ep_auth.hash_password(new_password)
    user.invite_accepted_at = now
    user.invite_token_hash = None  # single-use — consume the token
    user.failed_login_attempts, user.locked_until = ep_auth.reset_lockout()

    await db.flush()
    await db.refresh(user)

    logger.info(
        "employee_portal.invite_accepted org_id=%s portal_user_id=%s",
        user.org_id,
        user.id,
    )
    return user


# ---------------------------------------------------------------------------
# Password reset (R14.3, R14.5, R14.6, R14.8)
# ---------------------------------------------------------------------------


async def request_reset(
    db: AsyncSession,
    org_id: uuid.UUID,
    email: str,
) -> tuple[EmployeePortalUser, str] | None:
    """Issue a single-use reset token for an active Portal_User, or ``None``.

    Resolves the active Portal_User in ``org_id`` by normalised email. If none
    matches, returns ``None`` and writes nothing — the API layer must surface a
    byte-for-byte identical confirmation either way so account existence is not
    revealed (anti-enumeration, R14.1).

    On a match: sets ``reset_token_hash = sha256(raw)`` and
    ``reset_token_expires_at = now + 3600s`` (R14.3), and returns
    ``(user, raw_token)`` so the API layer can build and email the reset URL.
    Only the hash is persisted.
    """
    normalised = _normalise_email(email)
    if not normalised:
        return None

    res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.org_id == org_id,
            func.lower(EmployeePortalUser.email) == normalised,
            EmployeePortalUser.is_active.is_(True),
        )
    )
    user = res.scalars().first()
    if user is None:
        return None

    raw_token = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_token(raw_token)
    user.reset_token_expires_at = _now_utc() + RESET_VALIDITY

    await db.flush()
    await db.refresh(user)
    return user, raw_token


async def complete_reset(
    db: AsyncSession,
    raw_token: str,
    new_password: str,
) -> EmployeePortalUser:
    """Complete a password reset using a single-use, unexpired reset token.

    Resolves the Portal_User by ``sha256(raw_token)``; requires the token to be
    unexpired and unused (R14.5, R14.6); validates the password length (R14.7);
    then sets the new ``password_hash``, clears ``reset_token_hash`` /
    ``reset_token_expires_at`` (single-use, R14.5), clears the lockout state,
    and **deletes all of the Portal_User's sessions** in the same transaction
    (R14.8).

    On any failure the stored password hash is left unchanged:
      - expired / already-used / unknown token → :class:`ResetTokenInvalid`
      - password not 8..128 chars → :class:`PasswordLengthError`
    """
    token_hash = _hash_token(raw_token)
    res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.reset_token_hash == token_hash
        )
    )
    user = res.scalars().first()
    if user is None:
        raise ResetTokenInvalid("This password reset link is invalid or has expired")

    if (
        user.reset_token_expires_at is None
        or _as_aware(user.reset_token_expires_at) < _now_utc()
    ):
        raise ResetTokenInvalid("This password reset link is invalid or has expired")

    ok, message = ep_auth.validate_password_length(new_password)
    if not ok:
        raise PasswordLengthError(message)

    user.password_hash = await ep_auth.hash_password(new_password)
    user.reset_token_hash = None  # single-use — consume the token (R14.5)
    user.reset_token_expires_at = None
    user.failed_login_attempts, user.locked_until = ep_auth.reset_lockout()
    await db.flush()

    # Invalidate every existing session for this user (R14.8).
    await session_service.delete_sessions_for_user(db, user.id)

    await db.refresh(user)
    logger.info(
        "employee_portal.password_reset org_id=%s portal_user_id=%s",
        user.org_id,
        user.id,
    )
    return user


# ---------------------------------------------------------------------------
# Revocation (R5.10, R5.11)
# ---------------------------------------------------------------------------


async def _deactivate_and_teardown(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    ip_address: str | None,
) -> int:
    """Deactivate every active Portal_User for a staff member and drop sessions.

    Sets ``is_active = false`` and deletes the user's sessions in the same
    transaction (R5.10, R5.11). Writes one ``access_revoked`` audit row per
    affected Portal_User. Returns the number of sessions deleted.
    """
    res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.org_id == org_id,
            EmployeePortalUser.staff_id == staff_id,
            EmployeePortalUser.is_active.is_(True),
        )
    )
    users = list(res.scalars().all())

    sessions_deleted = 0
    for user in users:
        user.is_active = False
        await db.flush()
        sessions_deleted += await session_service.delete_sessions_for_user(db, user.id)
        _write_audit(
            db,
            org_id=org_id,
            action=action,
            outcome="success",
            portal_user_id=user.id,
            actor_user_id=actor_user_id,
            ip_address=ip_address,
            details={"staff_id": str(staff_id)},
        )
        logger.info(
            "employee_portal.access_revoked org_id=%s portal_user_id=%s action=%s",
            org_id,
            user.id,
            action,
        )

    return sessions_deleted


async def revoke_access(
    db: AsyncSession,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> int:
    """Org_Admin revoke: deactivate the Portal_User and drop its sessions (R5.10).

    Returns the number of sessions invalidated. Performing the deactivation and
    the session tear-down in the same transaction guarantees no prior session
    survives the revoke.
    """
    return await _deactivate_and_teardown(
        db,
        org_id=org_id,
        staff_id=staff_id,
        action="access_revoked",
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )


async def revoke_portal_access_for_staff(
    db: AsyncSession,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> int:
    """Auto-revoke on staff deactivation (R5.11).

    Sibling of :func:`revoke_access`, called from ``deactivate_staff`` and the
    ``update_staff`` termination branch in the **same transaction** as the
    ``is_active = False`` flip on the staff row, so a deactivated Staff_Member's
    Portal_User can no longer authenticate and its sessions are gone. Returns
    the number of sessions invalidated.
    """
    return await _deactivate_and_teardown(
        db,
        org_id=org_id,
        staff_id=staff_id,
        action="access_revoked",
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )


__all__ = [
    "INVITE_VALIDITY",
    "RESET_VALIDITY",
    "AccountServiceError",
    "EmailRequired",
    "DuplicatePortalUser",
    "InviteExpired",
    "InviteNotFound",
    "PasswordLengthError",
    "ResetTokenInvalid",
    "issue_access",
    "accept_invite",
    "request_reset",
    "complete_reset",
    "revoke_access",
    "revoke_portal_access_for_staff",
]
