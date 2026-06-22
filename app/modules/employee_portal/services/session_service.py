"""Employee Portal session creation, validation, and destruction.

Mirrors the B2B Fleet Portal session flow
(``app/modules/fleet_portal/services/session_service.py``) but writes to the
**dedicated** ``employee_portal_sessions`` table so cross-portal cookie
rejection is structural: a token minted for the customer portal, fleet
portal, or staff app simply does not exist here, so it can never validate
(R6.2, R16.8).

Unlike the fleet portal, the employee portal stores only the **SHA-256 hash**
of the raw session token (``session_token_hash``); the raw 32-byte
``secrets.token_urlsafe(32)`` token lives only in the HttpOnly cookie. A DB-read
attacker therefore cannot replay a live session.

Session lifetime (R6.10): absolute lifetime **12 hours**
(``expires_at = created_at + 12h``) plus a **30-minute idle window** on
``last_seen_at``. A request whose ``now - last_seen_at > 30 min`` is rejected;
a valid request touches ``last_seen_at``.

Bulk invalidation (R4.6, R5.10, R5.11, R14.8): disable-portal, revoke,
deactivate, and reset-complete all delete sessions by ``org_id`` or
``portal_user_id`` in the same transaction as the triggering change.

Implements: Organisation Employee Portal task 5.2 — Requirements 6.1, 6.2,
6.9, 6.10.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.employee_portal.models import (
    EmployeePortalSession,
    EmployeePortalUser,
)


# Absolute session lifetime — 12 hours from creation (R6.10). Matches the
# fleet portal's ``SESSION_ABSOLUTE_LIFETIME``.
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)

# Idle window — a session inactive for longer than this is invalid (R6.10).
# This is the employee-portal-specific 30-minute window.
SESSION_IDLE_TIMEOUT = timedelta(minutes=30)


def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a raw token for storage.

    The raw token is never persisted; only this deterministic hash is, so a
    lookup hashes the cookie value and matches on ``session_token_hash``.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def hash_token(token: str) -> str:
    """Public alias of :func:`_hash_token`.

    The router's session dependency hashes the raw ``emp_portal_session`` cookie
    value to look the session row up by ``session_token_hash``; exposing the
    canonical hasher keeps that hashing in one place rather than re-deriving it
    in the router.
    """
    return _hash_token(token)


def is_session_valid(
    created_at: datetime,
    last_seen_at: datetime,
    now: datetime,
) -> bool:
    """Pure predicate: is a session valid at ``now`` (R6.10)?

    A session is valid **iff** both windows hold:

    * **Absolute lifetime** — it was created no more than 12 hours ago
      (``now - created_at <= 12h``), and
    * **Idle window** — it was last seen no more than 30 minutes ago
      (``now - last_seen_at <= 30 min``).

    This function performs no I/O and has no side effects so it can be
    exhaustively property-tested (task 5.4). Boundary values (exactly 12h /
    exactly 30 min) are treated as still valid; strictly greater is invalid,
    matching R6.10's "more than 30 minutes" / "more than 12 hours" wording.

    Validates: Requirements 6.10.
    """
    within_absolute = (now - created_at) <= SESSION_ABSOLUTE_LIFETIME
    within_idle = (now - last_seen_at) <= SESSION_IDLE_TIMEOUT
    return within_absolute and within_idle


async def create_session(
    db: AsyncSession,
    user: EmployeePortalUser,
) -> tuple[EmployeePortalSession, str]:
    """Create a new employee portal session for ``user``.

    Mints a 32-byte URL-safe raw session token (``secrets.token_urlsafe(32)``)
    and a separate CSRF token. Only the SHA-256 hash of the session token is
    persisted (``session_token_hash``); the CSRF token is stored as-is because
    it is a readable double-submit value, not a bearer secret.

    ``expires_at`` is set to ``created_at + 12h`` (R6.10). ``created_at`` and
    ``last_seen_at`` are pinned to the same ``now`` so the absolute window is
    deterministic rather than relying on staggered server defaults.

    Returns ``(session, raw_session_token)``. The raw token is returned exactly
    once so the caller can set it in the HttpOnly cookie; it cannot be
    recovered afterward. The session's ``csrf_token`` is read from the returned
    object for the readable CSRF cookie.

    Validates: Requirements 6.1, 6.2.
    """
    raw_session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    session = EmployeePortalSession(
        org_id=user.org_id,
        portal_user_id=user.id,
        session_token_hash=_hash_token(raw_session_token),
        csrf_token=csrf_token,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_ABSOLUTE_LIFETIME,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session, raw_session_token


async def touch_session(
    db: AsyncSession,
    session: EmployeePortalSession,
) -> None:
    """Update ``last_seen_at`` to ``now()`` for a valid request (R6.10).

    Called after :func:`is_session_valid` confirms the session is still live,
    so the 30-minute idle window slides forward on each authenticated request.
    """
    session.last_seen_at = datetime.now(timezone.utc)
    await db.flush()


async def destroy_session(
    db: AsyncSession,
    raw_session_token: str,
) -> bool:
    """Delete the session matching ``raw_session_token`` (logout — R6.9).

    Hashes the raw cookie value and deletes the row whose
    ``session_token_hash`` matches. Returns ``True`` if a row was deleted.
    """
    res = await db.execute(
        delete(EmployeePortalSession).where(
            EmployeePortalSession.session_token_hash
            == _hash_token(raw_session_token)
        )
    )
    return (res.rowcount or 0) > 0


async def delete_sessions_for_org(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> int:
    """Invalidate **all** sessions for an organisation (R4.6 disable-portal).

    Returns the number of session rows deleted.
    """
    res = await db.execute(
        delete(EmployeePortalSession).where(
            EmployeePortalSession.org_id == org_id
        )
    )
    return int(res.rowcount or 0)


async def delete_sessions_for_user(
    db: AsyncSession,
    portal_user_id: uuid.UUID,
) -> int:
    """Invalidate every session for a single portal user.

    Used by revoke (R5.10), staff deactivation (R5.11), and reset-complete
    (R14.8). Returns the number of session rows deleted.
    """
    res = await db.execute(
        delete(EmployeePortalSession).where(
            EmployeePortalSession.portal_user_id == portal_user_id
        )
    )
    return int(res.rowcount or 0)


__all__ = [
    "SESSION_ABSOLUTE_LIFETIME",
    "SESSION_IDLE_TIMEOUT",
    "hash_token",
    "is_session_valid",
    "create_session",
    "touch_session",
    "destroy_session",
    "delete_sessions_for_org",
    "delete_sessions_for_user",
]
