"""Public read-only staff roster viewer.

Token-gated, no-auth endpoint that renders a recipient's week roster
when they click the link from their roster SMS or email delivery
(C3, C6). Hosted under ``/api/v2/public/staff-roster/`` so the auth
middleware's ``/api/v2/public/`` prefix bypass already applies — no
JWT required.

A per-IP rate limit of **30 req/min** is layered on top by
``app/middleware/rate_limit.py`` (G5) to defend against accidental
scraping (e.g. a token leaked into a public Slack channel and
spidered by a crawler). The 32-byte token's entropy already makes
brute-force impractical; the limit is a belt-and-braces guard.

Failure modes (R9.4, G4):

- Token doesn't exist → **HTTP 404** ``{"detail": "token_not_found"}``.
- Token exists, ``expires_at <= now()``, AND the staff is
  deactivated (``is_active=false``) — the deactivation/termination
  flow (C11) sets ``expires_at = now()`` to revoke all of a staff's
  tokens, so a deactivated staff is the signal we use to distinguish
  this case → **HTTP 410** ``{"detail": "token_expired_staff_deactivated"}``.
- Token exists, ``expires_at <= now()``, staff still active —
  natural 30-day TTL expiry → **HTTP 410**
  ``{"detail": "token_expired"}``.

On success the response is::

    {
        "staff_name": "...",
        "week_start": "YYYY-MM-DD",
        "week_end":   "YYYY-MM-DD",   # week_start + 7 days
        "entries": [
            {
                "start_time": "...",   # ISO 8601, UTC
                "end_time":   "...",
                "title":      "...",   # nullable
                "notes":      "...",   # nullable
                "entry_type": "..."
            },
            ...
        ]
    }

The endpoint deliberately exposes the **bare minimum** — no employee
ID, no contact details, no pay info, no PII. Just the staff's display
name and their schedule for the week. The recipient already knows
who they are; the link only needs to confirm the schedule.

**Validates: Requirements R9.4, R9.8, G5** (Phase 1 task C7).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember, StaffRosterViewToken

public_router = APIRouter()


def _staff_display_name(staff: StaffMember) -> str:
    """Build a sensible display name for the public viewer.

    Prefers ``"first last"`` but falls back to whichever fields are
    populated. Defensive against legacy rows where ``first_name`` was
    introduced later (server_default empty string) and ``name`` was
    the original single-field column.
    """
    first = (staff.first_name or "").strip()
    last = (staff.last_name or "").strip()
    combined = f"{first} {last}".strip()
    if combined:
        return combined
    return (staff.name or "").strip() or "Staff member"


@public_router.get(
    "/{token}",
    summary="Public read-only staff roster viewer (token-gated, no auth)",
    responses={
        200: {"description": "Roster for the week the token was issued for."},
        404: {"description": "Token does not exist."},
        410: {
            "description": (
                "Token has expired — either the natural 30-day TTL "
                "lapsed, or the staff was deactivated (which revoked "
                "all of their tokens by setting expires_at=now())."
            )
        },
        429: {
            "description": (
                "Per-IP rate limit (30 req/min) exceeded. Retry-After "
                "header indicates when to retry."
            )
        },
    },
)
async def view_staff_roster(
    token: str,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return the staff's week roster for a given viewer token.

    No authentication. Token validity + expiry are the only gates.
    See the module docstring for the three failure modes.
    """
    # ------------------------------------------------------------------
    # 1. Token lookup. Three outcomes follow:
    #    - row missing → 404 token_not_found
    #    - row present + expired + staff deactivated → 410 token_expired_staff_deactivated
    #    - row present + expired + staff still active → 410 token_expired
    #    - row present + valid → render the schedule
    # ------------------------------------------------------------------
    token_row = (
        await db.execute(
            select(StaffRosterViewToken).where(
                StaffRosterViewToken.token == token,
            )
        )
    ).scalar_one_or_none()

    if token_row is None:
        # Distinct from the 410 cases — this is a token that was never
        # issued (or was hard-deleted via the ON DELETE CASCADE from a
        # staff/org delete, G8). Avoid leaking which possibility it is.
        raise HTTPException(status_code=404, detail="token_not_found")

    # Need the staff record both for the 410-distinguishing check and
    # for the success-path display name. Fetch once and reuse.
    staff = (
        await db.execute(
            select(StaffMember).where(
                StaffMember.id == token_row.staff_id,
                StaffMember.org_id == token_row.org_id,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if token_row.expires_at <= now:
        # 410-distinguishing: a deactivated staff is the signal that
        # the deactivation/termination flow (C11) revoked the token by
        # setting expires_at=now(). Natural 30-day TTL expiry happens
        # while the staff is still active.
        if staff is not None and not staff.is_active:
            raise HTTPException(
                status_code=410,
                detail="token_expired_staff_deactivated",
            )
        raise HTTPException(status_code=410, detail="token_expired")

    if staff is None:
        # Defensive: the FK is ON DELETE CASCADE so a missing staff
        # with a present token shouldn't happen, but if it ever does
        # (e.g., a manual DB tweak), treat the link as unusable rather
        # than 500. Behaviour mirrors the 404 path so we don't leak
        # internal state.
        raise HTTPException(status_code=404, detail="token_not_found")

    # ------------------------------------------------------------------
    # 2. Load the week's schedule entries. Mirrors the window logic
    #    in ``roster_delivery._load_week_entries`` — schedule_entries
    #    are stored UTC; we compare against UTC midnight at week_start
    #    and week_start + 7 days.
    # ------------------------------------------------------------------
    week_end = token_row.week_start + timedelta(days=7)
    start_dt = datetime.combine(token_row.week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(week_end, time.min, tzinfo=timezone.utc)

    entries = (
        await db.execute(
            select(ScheduleEntry)
            .where(
                ScheduleEntry.org_id == token_row.org_id,
                ScheduleEntry.staff_id == token_row.staff_id,
                ScheduleEntry.start_time >= start_dt,
                ScheduleEntry.start_time < end_dt,
            )
            .order_by(ScheduleEntry.start_time)
        )
    ).scalars().all()

    return {
        "staff_name": _staff_display_name(staff),
        "week_start": token_row.week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "entries": [
            {
                "start_time": e.start_time.isoformat() if e.start_time else None,
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "title": e.title,
                "notes": e.notes,
                "entry_type": e.entry_type,
            }
            for e in entries
        ],
    }
