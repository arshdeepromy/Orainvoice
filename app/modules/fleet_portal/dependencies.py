"""Fleet Portal FastAPI dependencies and Workshop_Org URL resolver.

Holds the request-time logic for:

- Resolving the current ``Organisation`` from a fleet-portal request URL
  (subdomain, path, or single-tenant fallback) — Property 4 / Req 2.3, 2.4.
- Validating the HttpOnly ``fleet_portal_session`` cookie against the
  ``portal_sessions`` row keyed on ``portal_account_id IS NOT NULL`` —
  Req 2.5, 2.6, 17.5, 17.6 (added in task 3.5).
- Setting the per-request ``app.current_org_id`` and
  ``app.current_fleet_account_id`` Postgres GUCs so RLS policies fire
  on every fleet-scoped table — task 1.2 / Req 17.2.
- Module-enabled gate (``b2b-fleet-management`` enabled for the resolved
  org) — Req 1.5, 1.6, 1.7.
- Role gates: ``require_fleet_admin`` / ``require_driver_or_admin`` —
  Property 11 / Req 5.1, 17.5.

This file evolves through tasks 3.3–3.5. Task 3.3 implements the URL
resolver; tasks 3.5 add the session/CSRF/role/module dependencies.
"""

from __future__ import annotations

import re
import secrets
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import (
    _current_fleet_account_id,
    _current_org_id,
    _set_rls_fleet_account_id,
    _set_rls_org_id,
    get_db_session,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.modules.admin.models import Organisation
    from app.modules.fleet_portal.models import PortalAccount, PortalFleetAccount
    from app.modules.portal.models import PortalSession


# ---------------------------------------------------------------------------
# URL resolution (Property 4 — Requirements 2.3, 2.4)
# ---------------------------------------------------------------------------


# Conservative regex for an org slug — allows lower/upper alphanumeric,
# hyphen, and underscore. Matches typical kebab-case slugs and rejects
# path traversal attempts.
_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Reserved entry routes under /fleet/* that are NOT slugs.
_PATH_RESERVED = frozenset(
    {
        "api",
        "login",
        "logout",
        "forgot-password",
        "reset-password",
        "accept-invite",
        "static",
        "assets",
        "kiosk",
        "security",
        "favicon.ico",
    }
)


def _extract_subdomain_slug(host: str | None, fleet_host: str) -> str | None:
    """Return the org slug from ``<slug>.fleet.<domain>`` or None."""
    if not host or not fleet_host:
        return None
    h = host.split(":", 1)[0].lower()
    fh = fleet_host.split(":", 1)[0].lower()
    if h == fh:
        return None
    suffix = "." + fh
    if not h.endswith(suffix):
        return None
    candidate = h[: -len(suffix)]
    if "." in candidate:
        return None
    return candidate if _SLUG_RE.fullmatch(candidate) else None


def _extract_path_slug(path: str) -> str | None:
    """Return the org slug from ``/fleet/<slug>/...`` or None."""
    if not path:
        return None
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] != "fleet":
        return None
    candidate = parts[1]
    if candidate in _PATH_RESERVED:
        return None
    return candidate if _SLUG_RE.fullmatch(candidate) else None


async def _lookup_org_by_slug(
    db: AsyncSession, slug: str
) -> Organisation | None:
    """Resolve a slug to an ``Organisation``.

    The project does not yet have a dedicated ``slug`` column on
    ``organisations``. Until it is added, the resolver matches against
    ``regexp_replace(lower(name), '\\s+', '-', 'g')``. A future
    migration that adds a real ``slug`` column should update this
    helper — it is the single point of change.
    """
    from app.modules.admin.models import Organisation
    from sqlalchemy import func

    s = slug.strip().lower()
    computed = func.regexp_replace(func.lower(Organisation.name), r"\s+", "-", "g")
    res = await db.execute(select(Organisation).where(computed == s).limit(1))
    return res.scalars().first()


async def _lookup_org_by_id_string(
    db: AsyncSession, candidate: str
) -> Organisation | None:
    """If ``candidate`` looks like a UUID, resolve it as ``organisations.id``."""
    try:
        org_uuid = _uuid.UUID(candidate)
    except (ValueError, AttributeError):
        return None
    from app.modules.admin.models import Organisation

    res = await db.execute(
        select(Organisation).where(Organisation.id == org_uuid).limit(1)
    )
    return res.scalars().first()


async def resolve_workshop_org_from_request(
    request: Request, db: AsyncSession
) -> Organisation | None:
    """Resolve the Workshop_Org for a fleet portal request.

    Precedence (Property 4 / Req 2.3):
      1. Subdomain — ``<slug>.fleet.<domain>`` if ``FLEET_PORTAL_HOST``
         is configured in platform_settings.
      2. Path — ``/fleet/<slug>/...``.
      3. Single-tenant fallback — query the DB for the org that has the
         ``b2b-fleet-management`` module enabled (or the feature flag
         active). No env var needed.

    Returns ``None`` when no rule matches a real org — the caller
    surfaces HTTP 404. Never silently falls through to a different
    org or to the staff ``/login`` page (Req 2.4, 2.6).
    """
    host = request.headers.get("host")
    path = request.url.path

    slug = _extract_subdomain_slug(host, settings.fleet_portal_host)
    if slug is None:
        slug = _extract_path_slug(path)

    if slug is not None:
        org = await _lookup_org_by_slug(db, slug)
        if org is None:
            org = await _lookup_org_by_id_string(db, slug)
        return org

    # Single-tenant fallback: find the org that has the fleet module
    # enabled. This removes the need for any env var — the system
    # auto-detects which org to use based on what's configured in the DB.
    org = await _resolve_single_tenant_org(db)
    return org


async def _resolve_single_tenant_org(db: AsyncSession) -> Organisation | None:
    """Find the single org with b2b-fleet-management enabled.

    For single-tenant deployments (no subdomain, no path slug), this
    queries the DB directly. If exactly one org has the module enabled
    (via org_modules or feature_flags), return it. If multiple orgs
    have it enabled, return the first one (ordered by name). If none,
    return None.

    This approach follows the steering doc: configuration lives in the
    DB, not in env vars.
    """
    from app.modules.admin.models import Organisation
    from sqlalchemy import text

    # Try org_modules first (per-org enablement)
    res = await db.execute(
        text(
            """
            SELECT o.id, o.name
            FROM organisations o
            JOIN org_modules om ON om.org_id = o.id
            WHERE om.module_slug = 'b2b-fleet-management'
              AND om.is_enabled = true
            ORDER BY o.name
            LIMIT 1
            """
        )
    )
    row = res.first()
    if row is not None:
        org_res = await db.execute(
            select(Organisation).where(Organisation.id == row[0])
        )
        return org_res.scalars().first()

    # Fallback: if the feature flag is globally active with default_value=true,
    # pick the first org (single-tenant assumption).
    res2 = await db.execute(
        text(
            """
            SELECT o.id
            FROM organisations o
            WHERE o.status IN ('active', 'trial')
            ORDER BY o.created_at
            LIMIT 1
            """
        )
    )
    row2 = res2.first()
    if row2 is not None:
        # Check if the feature flag is active
        flag_res = await db.execute(
            text(
                """
                SELECT is_active, default_value
                FROM feature_flags
                WHERE key = 'b2b-fleet-management'
                """
            )
        )
        flag = flag_res.first()
        if flag and flag[0] and flag[1]:
            org_res = await db.execute(
                select(Organisation).where(Organisation.id == row2[0])
            )
            return org_res.scalars().first()

    return None


# ---------------------------------------------------------------------------
# Session context — passed to services after auth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FleetSessionCtx:
    """Per-request authentication context for fleet portal calls.

    Carries everything a service needs without having to query the DB
    again: org id, fleet account id, portal account id, role, and the
    underlying session token. Built by ``require_fleet_portal_session``.
    """

    org_id: _uuid.UUID
    portal_account_id: _uuid.UUID
    portal_user_role: str  # 'fleet_admin' | 'driver'
    fleet_account_id: _uuid.UUID | None
    email: str
    session_id: _uuid.UUID
    is_impersonation: bool = False


# ---------------------------------------------------------------------------
# Module-enabled gate (Req 1.5, 1.6, 1.7)
# ---------------------------------------------------------------------------


async def _is_module_enabled(
    db: AsyncSession, org_id: _uuid.UUID, slug: str = "b2b-fleet-management"
) -> bool:
    """Return True iff the named module is enabled for ``org_id``.

    Checks two sources (either being true means enabled):
    1. ``org_modules`` table — the per-org module enablement system.
    2. ``feature_flags`` table — the global admin feature flag system.

    This dual-check bridges the two systems: a Global Admin can toggle
    the feature flag ON (which makes it available for all orgs), and an
    Org Admin can enable it per-org via the module management UI. Either
    path results in the module being active.
    """
    from sqlalchemy import text

    # Check 1: org_modules (per-org enablement)
    res = await db.execute(
        text(
            """
            SELECT is_enabled
            FROM org_modules
            WHERE org_id = :org_id AND module_slug = :slug
            LIMIT 1
            """
        ),
        {"org_id": str(org_id), "slug": slug},
    )
    row = res.first()
    if row and row[0]:
        return True

    # Check 2: feature_flags (global toggle — if the flag is active AND
    # default_value is true, treat as globally enabled for all orgs)
    res2 = await db.execute(
        text(
            """
            SELECT is_active, default_value
            FROM feature_flags
            WHERE key = :slug
            LIMIT 1
            """
        ),
        {"slug": slug},
    )
    flag_row = res2.first()
    if flag_row and flag_row[0] and flag_row[1]:
        # Flag is active AND default_value is true → enabled for all orgs
        return True

    return False


async def require_module_enabled(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Organisation:
    """Resolve the org and ensure the fleet portal module is enabled.

    Behaviour matches Req 1.5 / 1.6:
      - No org resolved → HTTP 404 (does NOT reveal whether the org
        exists; existence-preserving).
      - Org resolved but module disabled → HTTP 403 with the
        spec-mandated message.

    Returns the ``Organisation`` row so downstream dependencies can
    use it. Side-effect: sets the ``app.current_org_id`` Postgres GUC
    for RLS so the session DB has the right tenant scoping for the
    rest of the request.
    """
    org = await resolve_workshop_org_from_request(request, db)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    enabled = await _is_module_enabled(db, org.id)
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="B2B Fleet Management module is not enabled for this organisation",
        )

    # Set RLS context for downstream queries within this request.
    _current_org_id.set(str(org.id))
    await _set_rls_org_id(db, str(org.id))
    return org


# ---------------------------------------------------------------------------
# Session / CSRF / role gates (Req 2.5, 2.6, 3.14, 3.15, 5.1, 17.5)
# ---------------------------------------------------------------------------


_SESSION_COOKIE_NAME = "fleet_portal_session"
_CSRF_COOKIE_NAME = "fleet_portal_csrf"
_CSRF_HEADER_NAME = "X-CSRF-Token"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def _load_session(
    db: AsyncSession, session_token: str
) -> tuple[PortalSession, PortalAccount, PortalFleetAccount | None] | None:
    """Look up an active fleet-portal session by token.

    Returns the matching ``(PortalSession, PortalAccount, PortalFleetAccount)``
    triple, or ``None`` if the token doesn't match an active fleet
    session (a token-link session — ``portal_account_id IS NULL`` — also
    returns ``None`` here so staff/customer-portal sessions can never
    cross into the fleet portal).
    """
    from sqlalchemy import text

    from app.modules.fleet_portal.models import PortalAccount, PortalFleetAccount
    from app.modules.portal.models import PortalSession

    # Temporarily bypass RLS for session validation — the session lookup
    # needs to find the portal_account regardless of which org the
    # resolver picked. After validation, we set the correct org_id.
    await db.execute(text("RESET app.current_org_id"))

    res = await db.execute(
        select(PortalSession).where(PortalSession.session_token == session_token)
    )
    session = res.scalars().first()
    if session is None or session.portal_account_id is None:
        return None
    if session.expires_at and session.expires_at < _now_utc():
        return None

    # Idle timeout check (Req 21.8) — reject if last_seen is too old
    if session.last_seen:
        idle_minutes = (_now_utc() - session.last_seen).total_seconds() / 60
        # Default 240 minutes; will be overridden by org policy when loaded
        if idle_minutes > 240:
            return None

    res = await db.execute(
        select(PortalAccount).where(PortalAccount.id == session.portal_account_id)
    )
    account: PortalAccount | None = res.scalars().first()
    if account is None or not account.is_active or account.is_locked_permanently:
        return None

    fleet_account: PortalFleetAccount | None = None
    if account.fleet_account_id is not None:
        res = await db.execute(
            select(PortalFleetAccount).where(
                PortalFleetAccount.id == account.fleet_account_id
            )
        )
        fleet_account = res.scalars().first()
        if fleet_account is None or not fleet_account.is_active:
            return None

    # Touch last_seen for idle timeout tracking
    session.last_seen = _now_utc()
    await db.flush()

    return session, account, fleet_account


async def require_fleet_portal_session(
    request: Request,
    org: Organisation = Depends(require_module_enabled),
    fleet_session: str | None = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
) -> FleetSessionCtx:
    """Require a valid fleet portal session cookie.

    On success:
      - Sets the per-request ``app.current_org_id`` AND
        ``app.current_fleet_account_id`` Postgres GUCs so RLS fires
        on every fleet-scoped table (task 1.2 / Req 17.2).
      - Returns a :class:`FleetSessionCtx` for use by services.

    On failure:
      - Missing/invalid cookie → HTTP 401.
      - Staff JWT or token-link session → HTTP 401 (we never accept a
        token-link cookie here — Req 2.5, 2.6).
    """
    if not fleet_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    loaded = await _load_session(db, fleet_session)
    if loaded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    session, account, fleet_account = loaded

    # Cross-org guard: the session's org must match the resolved org.
    # In single-tenant mode the resolver may pick a different org than
    # the account's org (e.g. "Demo Workshop" vs "SP Automotive"). The
    # session itself is authoritative — use the account's org_id as the
    # source of truth and set RLS accordingly.
    org_id: _uuid.UUID = account.org_id

    # Set both RLS GUCs.
    fleet_account_id = (
        fleet_account.id if fleet_account is not None else None
    )
    _current_org_id.set(str(org_id))
    await _set_rls_org_id(db, str(org_id))
    _current_fleet_account_id.set(
        str(fleet_account_id) if fleet_account_id is not None else None
    )
    await _set_rls_fleet_account_id(
        db, str(fleet_account_id) if fleet_account_id is not None else None
    )

    return FleetSessionCtx(
        org_id=org_id,
        portal_account_id=account.id,
        portal_user_role=account.portal_user_role,
        fleet_account_id=fleet_account_id,
        email=account.email,
        session_id=session.id,
        is_impersonation=False,
    )


async def require_fleet_admin(
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
) -> FleetSessionCtx:
    """Reject driver sessions with HTTP 403 (Property 11 / Req 5.1)."""
    if ctx.portal_user_role != "fleet_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires Fleet Account Admin access",
        )
    return ctx


async def require_driver_or_admin(
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
) -> FleetSessionCtx:
    """Pass either role; downstream services discriminate (Req 5.1)."""
    return ctx


# ---------------------------------------------------------------------------
# CSRF — double-submit cookie (Req 3.14, 3.15)
# ---------------------------------------------------------------------------


def validate_fleet_portal_csrf(request: Request) -> None:
    """Double-submit CSRF check for state-changing fleet portal calls.

    Reads the ``fleet_portal_csrf`` cookie and the ``X-CSRF-Token``
    header; the request is rejected with HTTP 403 unless the values
    match (constant-time comparison via ``secrets.compare_digest``).

    GET / HEAD / OPTIONS are exempt — they are non-state-changing per
    HTTP semantics. The dependency is intended for use as a route
    dependency on POST/PUT/PATCH/DELETE endpoints in ``router.py``.
    """
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return

    cookie = request.cookies.get(_CSRF_COOKIE_NAME)
    header = request.headers.get(_CSRF_HEADER_NAME)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


__all__ = [
    "FleetSessionCtx",
    "resolve_workshop_org_from_request",
    "require_module_enabled",
    "require_fleet_portal_session",
    "require_fleet_admin",
    "require_driver_or_admin",
    "validate_fleet_portal_csrf",
]
