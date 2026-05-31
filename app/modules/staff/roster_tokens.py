"""Service for managing public read-only roster viewer tokens.

Used by the SMS-roster delivery flow (C6) — and by the email-roster
flow (C3) when a tokenised "view full schedule" link is included — to
mint links the recipient can open without logging in. Tokens are
**one-per-(staff, week)** so re-sending the same week is idempotent
(no row proliferation), and they're revoked when the staff is
deactivated/terminated (C11) or hard-deleted (G8 — handled by the FK
``ON DELETE CASCADE`` set up in migration 0203).

Mirrors ``app/modules/staff/roster_delivery.py`` in shape (helper
module the C6 router + the D1 scheduled task can both import).

**Validates: Requirements R9.4, G8 — Staff Phase 1 task C5.**
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff.models import StaffRosterViewToken

# R9.4 — viewer link expires 30 days after issue.
_TOKEN_TTL_DAYS = 30

# 32 bytes of entropy → 43-char URL-safe base64 string. Matches the
# ``secrets.token_urlsafe(32)`` pattern used by the customer portal
# (``app/modules/portal/service.py``) so the public URL has the same
# unguessability properties.
_TOKEN_NBYTES = 32


def _new_token() -> str:
    """Mint a fresh URL-safe token string (43 chars, ~256 bits of entropy)."""
    return secrets.token_urlsafe(_TOKEN_NBYTES)


async def get_or_create_viewer_token(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    staff_id: uuid.UUID,
    week_start: date,
) -> StaffRosterViewToken:
    """Return the existing valid token for ``(staff_id, week_start)`` or mint one.

    Behaviour:

    1. If a row already exists for this (staff, week) AND
       ``expires_at > now()``, return it unchanged. This is the
       "resend the same week" path — the caller (C6 SMS endpoint) gets
       the same URL it sent the first time, so the recipient doesn't
       end up with two competing links.
    2. If a row exists but is expired (natural 30-day TTL, OR
       deliberately revoked by C11's deactivation flow), mint a fresh
       token + bump ``expires_at`` on the same row. Reusing the row is
       required by the ``UNIQUE (staff_id, week_start)`` constraint
       in migration 0203 — INSERTing a second row would raise
       ``IntegrityError``. Per R9.7/G4, expiring then re-issuing here
       is the correct behaviour: deactivation revoked the prior link,
       and an admin sending a new roster after re-activation should
       get a working link again.
    3. If no row exists, INSERT a new one with a freshly minted token
       and an ``expires_at`` 30 days in the future.

    Always ``flush()`` + ``refresh()`` so the caller sees an attached
    ORM object with the server-defaulted ``created_at`` populated
    (mirrors the ``StaffService`` pattern in P1-N15).
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=_TOKEN_TTL_DAYS)

    stmt = select(StaffRosterViewToken).where(
        StaffRosterViewToken.staff_id == staff_id,
        StaffRosterViewToken.week_start == week_start,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is not None:
        # Case 1 — still valid: hand back the same token string.
        if existing.expires_at > now:
            return existing
        # Case 2 — expired: re-mint in place. The unique
        # ``(staff_id, week_start)`` constraint forbids INSERTing a
        # second row, so we update the existing one.
        existing.token = _new_token()
        existing.expires_at = expires_at
        # Keep ``org_id`` on the row in step with the live staff record
        # — defensive against the (rare) case where a staff was
        # transferred between orgs and the prior row's ``org_id`` is
        # stale. The RLS policy filters on ``org_id`` so this matters
        # for correctness, not just hygiene.
        existing.org_id = org_id
        await db.flush()
        await db.refresh(existing)
        return existing

    # Case 3 — no row yet: create it.
    new_row = StaffRosterViewToken(
        org_id=org_id,
        staff_id=staff_id,
        token=_new_token(),
        week_start=week_start,
        expires_at=expires_at,
    )
    db.add(new_row)
    await db.flush()
    await db.refresh(new_row)
    return new_row
