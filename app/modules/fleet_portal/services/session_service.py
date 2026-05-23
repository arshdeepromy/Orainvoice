"""Fleet Portal session creation, validation, and destruction.

Mirrors the existing customer-portal session flow in
``app/modules/portal/service.py`` but writes ``portal_account_id`` so
the discriminator pattern (added in migration 0191) routes the row to
the fleet portal auth path.

Implements: B2B Fleet Portal task 3.6 — Requirements 3.2, 3.13, 4.8.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.models import PortalAccount
from app.modules.portal.models import PortalSession


# Default fleet portal session lifetime — 12 hours absolute, 4 hours
# idle. The 12-hour window is the same as the staff app; the per-org
# ``portal_security_policy.session_policy.idle_timeout_minutes`` (task
# 4A.6) overrides the idle timeout when the policy row is present.
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)
DEFAULT_IDLE_TIMEOUT_MINUTES = 240


async def create_fleet_portal_session(
    db: AsyncSession,
    *,
    portal_account: PortalAccount,
) -> tuple[str, str]:
    """Create a new fleet portal session.

    Enforces max concurrent sessions (Req 21.8): if the account already
    has >= max_sessions active, the oldest session is deleted (FIFO).

    Returns ``(session_token, csrf_token)``. Both are 32-byte
    URL-safe random strings (~43 chars).
    """
    session_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)

    # Enforce max concurrent sessions (default 5, configurable via policy)
    max_sessions = 5
    existing_count_res = await db.execute(
        select(func.count()).where(
            PortalSession.portal_account_id == portal_account.id,
            PortalSession.expires_at > now,
        )
    )
    existing_count = int(existing_count_res.scalar() or 0)
    if existing_count >= max_sessions:
        # Delete the oldest session(s) to make room
        oldest_res = await db.execute(
            select(PortalSession.id)
            .where(
                PortalSession.portal_account_id == portal_account.id,
                PortalSession.expires_at > now,
            )
            .order_by(PortalSession.created_at.asc())
            .limit(existing_count - max_sessions + 1)
        )
        for row in oldest_res.all():
            await db.execute(
                delete(PortalSession).where(PortalSession.id == row[0])
            )

    session = PortalSession(
        portal_account_id=portal_account.id,
        customer_id=portal_account.customer_id,
        session_token=session_token,
        expires_at=now + SESSION_ABSOLUTE_LIFETIME,
        last_seen=now,
    )
    db.add(session)
    await db.flush()
    return session_token, csrf_token


async def destroy_fleet_portal_session(
    db: AsyncSession,
    *,
    session_token: str,
) -> bool:
    """Delete a fleet portal session row. Returns True if a row was deleted."""
    res = await db.execute(
        delete(PortalSession).where(PortalSession.session_token == session_token)
    )
    return (res.rowcount or 0) > 0


async def destroy_all_sessions_for_portal_account(
    db: AsyncSession,
    *,
    portal_account_id: uuid.UUID,
) -> int:
    """Tear down every active session for a portal account (Req 4.8)."""
    res = await db.execute(
        delete(PortalSession).where(
            PortalSession.portal_account_id == portal_account_id
        )
    )
    return int(res.rowcount or 0)


async def touch_session(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> None:
    """Update ``last_seen`` to ``now()`` (idle-timeout enforcement)."""
    res = await db.execute(
        select(PortalSession).where(PortalSession.id == session_id)
    )
    sess = res.scalars().first()
    if sess is None:
        return
    sess.last_seen = datetime.now(timezone.utc)
    await db.flush()


__all__ = [
    "SESSION_ABSOLUTE_LIFETIME",
    "DEFAULT_IDLE_TIMEOUT_MINUTES",
    "create_fleet_portal_session",
    "destroy_fleet_portal_session",
    "destroy_all_sessions_for_portal_account",
    "touch_session",
]
