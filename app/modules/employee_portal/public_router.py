"""Public (no-auth) Organisation Employee Portal lookup surface.

This router carries the single public, unauthenticated endpoint used by the
mobile app's first-run Portal_Type_Selector to turn an organisation name or slug
into a branded-login target:

- task 11.2 — ``GET /api/v2/public/portal-resolve`` (Slug_Resolution_Endpoint).

It is mounted under ``/api/v2/public`` so the auth middleware's existing
``/api/v2/public/`` prefix bypass applies (no JWT — R9.2), and the per-IP rate
limit for ``/api/v2/public/portal-resolve`` (30 req/min, ``_PORTAL_RESOLVE_PATH``
in ``app/middleware/rate_limit.py``, task 12.2) keys off that exact path. It is
kept **separate** from the cookie-authenticated ``/e/api`` router
(``app/modules/employee_portal/router.py``) because that router is path-scoped to
``/e`` for its session/CSRF cookies; this lookup carries no cookies and lives on
the public API surface alongside the other ``/api/v2/public/*`` token/lookup
endpoints (staff-roster, bookings, quotes).

Resolution contract (design §Public API; R9.1, R9.3, R9.4, R9.5, R9.8, R8.3):

1. **Exact slug match first.** Normalise ``q`` (trim + lowercase) and look for an
   organisation whose ``lower(slug)`` equals it. Because the slug is globally
   unique this yields at most one org; when that org also has the requested
   portal type **enabled**, return ``200 {match}`` immediately (R9.1).
2. **Else name ``ILIKE`` match**, filtered to organisations that have the
   requested portal type enabled, capped at 10 candidates (R9.4). Exactly one
   enabled match → ``200 {match}`` (R9.1); more than one → ``200 {candidates}``
   (R9.4, the ambiguous name is never auto-resolved to a single identity).
3. **None matching, or only disabled-portal matches → ``404 not_found``**
   (R9.3, R9.8) — a neutral body that enumerates nothing and exposes no branding
   for a non-matching or disabled organisation (Property 21 minimal exposure).

"Enabled" per portal type:

- ``employee`` → ``employee_portal_enabled`` is true in Org_Settings **and** a
  slug is set (mirrors the login-enablement gate, R4.4).
- ``fleet`` → the ``b2b-fleet-management`` module gate is on for the org, reusing
  the fleet portal's own module-enabled check so the two stay in lockstep.

Every returned organisation exposes ONLY its name + Portal_Branding (logo + brand
colours) sourced from the existing Org_Settings — never any other org data (R9.5,
R13.4).

Implements: Organisation Employee Portal task 11.2 — Requirements 9.1, 9.2, 9.3,
9.4, 9.5, 9.8, 8.3.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.admin.models import Organisation
from app.modules.employee_portal import schemas as S
from app.modules.fleet_portal.dependencies import _is_module_enabled
from app.modules.organisations.slug_service import normalise_slug

logger = logging.getLogger(__name__)

public_router = APIRouter()

# Upper bound on rows pulled for the name ``ILIKE`` scan before enablement
# filtering. The platform has a small number of organisations, so a generous
# cap is ample headroom while still bounding the query; the enabled subset is
# then capped at ``_MAX_CANDIDATES`` (R9.4).
_NAME_SCAN_LIMIT = 100

# Maximum disambiguation candidates returned for an ambiguous name (R9.4).
_MAX_CANDIDATES = 10

# Neutral not-found message — does not enumerate or reveal any organisation
# (R9.3, R9.8). Identical for "no match" and "match exists but portal disabled".
_NOT_FOUND_MESSAGE = "No matching organisation portal was found."


def _ilike_pattern(raw: str) -> str:
    """Build a safe ``%term%`` ``ILIKE`` pattern from raw user input.

    Escapes the SQL ``LIKE`` wildcards (``%``, ``_``) and the escape character
    itself (``\\``) so a query containing them is matched literally rather than
    acting as a wildcard (defence against a query like ``%`` matching every org).
    Used with ``.ilike(pattern, escape="\\\\")``.
    """
    escaped = (
        raw.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


async def _is_portal_enabled(
    db: AsyncSession, org: Organisation, portal_type: str
) -> bool:
    """Return ``True`` iff ``org`` has the requested portal type enabled.

    - ``employee`` → ``employee_portal_enabled`` true in Org_Settings AND a slug
      set (the same gate the login endpoint enforces, R4.4).
    - ``fleet`` → the ``b2b-fleet-management`` module is enabled for the org,
      reusing the fleet portal's module gate.

    Reads the enablement flag straight off the already-loaded ``org.settings``
    JSONB (``organisations`` is the tenant-root table and carries no RLS policy),
    so no extra org-settings round trip is needed.
    """
    if portal_type == "employee":
        if not org.slug:
            return False
        settings = org.settings or {}
        return bool(settings.get("employee_portal_enabled"))
    # fleet
    return await _is_module_enabled(db, org.id)


def _branding(org: Organisation) -> S.PortalBranding:
    """Project the org's Portal_Branding fields (logo + colours) only (R9.5)."""
    settings = org.settings or {}
    return S.PortalBranding(
        logo_url=settings.get("logo_url"),
        primary_colour=settings.get("primary_colour"),
        secondary_colour=settings.get("secondary_colour"),
    )


def _match(org: Organisation) -> S.PortalResolveMatch:
    return S.PortalResolveMatch(
        org_id=org.id, org_name=org.name, branding=_branding(org)
    )


def _candidate(org: Organisation) -> S.PortalResolveCandidate:
    return S.PortalResolveCandidate(org_name=org.name, branding=_branding(org))


@public_router.get("/portal-resolve")
async def portal_resolve(
    q: str = Query(min_length=1, max_length=100),
    portal_type: Literal["employee", "fleet"] = Query(...),
    db: AsyncSession = Depends(get_db_session),
):
    """Resolve an org name or slug to a branded-login target (R9.1, R9.3–R9.5, R9.8).

    Public, unauthenticated (R9.2), and per-IP rate limited at 30 req/min by the
    middleware. See the module docstring for the full resolution contract. Reveals
    nothing about non-matching or disabled-portal organisations — a neutral
    ``404 not_found`` with no branding (R9.3, R9.8, Property 21).
    """
    # --- 1. Exact slug match first (globally unique → at most one). -----------
    slug = normalise_slug(q)
    if slug:
        slug_res = await db.execute(
            select(Organisation).where(func.lower(Organisation.slug) == slug)
        )
        slug_org = slug_res.scalars().first()
        if slug_org is not None and await _is_portal_enabled(
            db, slug_org, portal_type
        ):
            return {"match": _match(slug_org)}

    # --- 2. Name ILIKE match, filtered to enabled orgs, capped at 10. ---------
    name_res = await db.execute(
        select(Organisation)
        .where(Organisation.name.ilike(_ilike_pattern(q), escape="\\"))
        .order_by(Organisation.name)
        .limit(_NAME_SCAN_LIMIT)
    )
    enabled: list[Organisation] = []
    for org in name_res.scalars().all():
        if await _is_portal_enabled(db, org, portal_type):
            enabled.append(org)
            if len(enabled) >= _MAX_CANDIDATES:
                break

    # --- 3. Decide the response shape. ----------------------------------------
    if not enabled:
        # None matching, or every match has the portal disabled (R9.3, R9.8).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": _NOT_FOUND_MESSAGE, "code": "not_found"},
        )
    if len(enabled) == 1:
        # Exactly one organisation matches + enabled → resolved identity (R9.1).
        return {"match": _match(enabled[0])}
    # More than one NAME match → disambiguation, never auto-resolve (R9.4).
    return {"candidates": [_candidate(org) for org in enabled]}


__all__ = ["public_router"]
