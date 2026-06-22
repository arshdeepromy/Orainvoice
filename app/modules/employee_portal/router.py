"""Organisation Employee Portal router — ``/e/api/*`` surface for Portal_Users.

Auth is via the HttpOnly ``emp_portal_session`` cookie; state-changing endpoints
additionally require the double-submit CSRF cookie/header pair
(``emp_portal_csrf`` / ``X-CSRF-Token``). The portal is a deliberate near-clone
of the B2B Fleet Portal (``app/modules/fleet_portal/router.py``) but is rooted at
``staff_members`` instead of customer fleets and stores all auth tokens as
SHA-256 hashes. It runs in parallel to the fleet/customer portals and never
crosses cookies with them — the ``/e`` cookie path keeps the cookies off
``/api/*`` (staff app), ``/fleet`` (fleet portal), and the customer portal.

This module is grown across several tasks; see
``.kiro/specs/organisation-employee-portal/tasks.md`` (tasks 10.x, 11.x) for the
list of endpoints that land in each pass. The current pass implements:

- task 10.1 — ``POST /e/api/auth/login`` (org resolution by slug, enablement
  gate, lockout, anti-enumeration generic 401, session + cookies on success).
- task 10.2 — the portal **session dependency** (``require_portal_session``)
  and the **CSRF double-submit dependency** (``validate_emp_portal_csrf``),
  plus ``POST /e/api/auth/logout`` and ``GET /e/api/auth/me``.
- task 10.3 — the public, single-use-token ``GET``/``POST
  /e/api/auth/accept-invite/{token}`` set-password endpoints.
- task 10.4 — the public password-reset endpoints ``POST
  /e/api/auth/password/reset-request`` (always returns a byte-for-byte
  identical confirmation, anti-enumeration) and ``POST
  /e/api/auth/password/reset`` (single-use reset token → new password).
- task 11.1 — the public, no-session ``GET /e/api/branding/{slug}`` endpoint
  that backs the org-branded login page (case-insensitive slug match; returns
  name + branding only when the slug resolves AND the portal is enabled; a
  neutral ``404 portal_unavailable`` otherwise — no existence leak).
- task 11.3 — the authenticated ``GET /e/api/profile`` endpoint: the MVP
  profile view sourcing the session's own ``staff_members`` row (RLS-scoped to
  the session's org), with IRD/bank PII masked via ``mask_ird`` /
  ``mask_bank_account``; ``409 not_linked`` when the portal user has no linked
  staff (R7.7); own record only — no fields/existence disclosure for any
  non-owned record (R7.5, R16.4).
- task 11.4 — the authenticated ``GET /e/api/roster`` endpoint: the MVP
  roster/schedule view sourcing the session's own ``schedule_entries`` for a UTC
  week window (``week_start`` query param, default = current week's Monday),
  reusing the public staff roster viewer's data path / window logic
  (``app/modules/staff/public_router.py``) rather than duplicating it (R7.4),
  scoped to the session's ``staff_id`` + ``org_id`` (own roster only, R7.1);
  ``409 not_linked`` when the portal user has no linked staff (R7.7).

Cookie scoping (R6.1, R6.2): the session/CSRF cookies are set with ``path=/e``
and the router is mounted under ``/e/api`` so both the SPA navigation and its XHR
calls carry the cookies, and they are never transmitted to any other surface.

Implements: Organisation Employee Portal tasks 10.1, 10.2, 10.3, 10.4, 11.1,
11.3, 11.4 — Requirements 4.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9,
6.10, 6.11, 7.1, 7.2, 7.4, 7.5, 7.7, 8.1, 8.2, 8.3, 13.1, 13.4, 14.1, 14.5,
14.6, 14.7, 14.8, 15.5, 16.3, 16.4, 16.6.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import _set_rls_org_id, get_db_session
from app.core.encryption import envelope_decrypt_str
from app.modules.admin.models import Organisation
from app.modules.employee_portal import auth as ep_auth
from app.modules.employee_portal import schemas as S
from app.modules.employee_portal.models import (
    EmployeePortalAuditLog,
    EmployeePortalSession,
    EmployeePortalUser,
)
from app.modules.employee_portal.services import session_service
from app.modules.employee_portal.services import account_service
from app.modules.employee_portal import employee_portal_delivery
from app.modules.organisations.service import get_org_settings
from app.modules.organisations.slug_service import normalise_slug
from app.modules.scheduling_v2.models import ScheduleEntry
from app.modules.staff.models import StaffMember
from app.modules.staff.security import mask_bank_account, mask_ird

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Cookie helpers (mirror the fleet portal's _set/_clear_session_cookies, but
# with the employee-portal cookie names and the /e path scope — R6.1, R6.2).
# ---------------------------------------------------------------------------

_SESSION_COOKIE_NAME = "emp_portal_session"
_CSRF_COOKIE_NAME = "emp_portal_csrf"
_CSRF_HEADER_NAME = "X-CSRF-Token"
_COOKIE_PATH = "/e"


def _is_secure_origin() -> bool:
    """Return ``True`` when cookies should be marked ``Secure``.

    In ``development`` we keep ``Secure`` off so cookies work over plain HTTP on
    localhost. In ``staging`` and ``production`` we always mark them Secure (SSL
    is enforced by nginx) — matching the fleet portal.
    """
    return settings.environment in {"staging", "production"}


def _set_session_cookies(
    response: JSONResponse, *, session_token: str, csrf_token: str
) -> None:
    """Set the HttpOnly session cookie and the readable CSRF cookie (path=/e)."""
    secure = _is_secure_origin()
    max_age = int(session_service.SESSION_ABSOLUTE_LIFETIME.total_seconds())
    # Path is /e so the cookies are never sent to the staff app at /api/*, the
    # fleet portal at /fleet, or the customer portal (R6.1, R6.2, Property 18).
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=_COOKIE_PATH,
    )
    response.set_cookie(
        key=_CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=max_age,
        httponly=False,  # JS reads this and echoes it as X-CSRF-Token (R6.7).
        secure=secure,
        samesite="lax",
        path=_COOKIE_PATH,
    )


def _clear_session_cookies(response: JSONResponse) -> None:
    response.delete_cookie(_SESSION_COOKIE_NAME, path=_COOKIE_PATH)
    response.delete_cookie(_CSRF_COOKIE_NAME, path=_COOKIE_PATH)


# ---------------------------------------------------------------------------
# Anti-enumeration constants
# ---------------------------------------------------------------------------

# Identical text returned for every bad-credential outcome (R6.4, R16.6). A
# non-matching email and a matching email with the wrong password produce the
# byte-for-byte same body so account existence is never revealed (Property 13).
_INVALID_CREDENTIALS_MESSAGE = "Invalid email or password"

# Neutral message for a disabled portal / unknown slug — does not reveal whether
# the organisation exists (R4.5, R6.11, no enumeration).
_PORTAL_UNAVAILABLE_MESSAGE = "This portal is unavailable"

# Message surfaced when the account is temporarily locked after repeated failures
# (R6.5). This is only ever reachable for an account that exists and is locked.
_ACCOUNT_LOCKED_MESSAGE = (
    "Your account is temporarily locked due to repeated failed sign-in attempts. "
    "Please try again later."
)

# A pre-computed bcrypt hash burned on the no-user / no-password path so the
# response timing does not betray whether the email matched an active account
# (defence-in-depth for anti-enumeration; verifying against it always fails).
_DUMMY_PASSWORD_HASH = ep_auth.hash_password_sync("anti-enumeration-dummy")

# Returned when the session cookie is missing / unknown / expired / idle-timed-out
# (R6.10). Identical body for every invalid-session cause — no reason leak.
_SESSION_INVALID_MESSAGE = "Your session has expired. Please sign in again."

# Returned when the double-submit CSRF check fails on a state-changing request
# (R6.8). No state change is performed before this is raised.
_CSRF_FAILED_MESSAGE = "CSRF validation failed"

# Returned when an authenticated portal user has no linked staff record (R7.7).
# Human-readable so the SPA can surface "your account is not yet linked".
_NOT_LINKED_MESSAGE = (
    "Your account is not yet linked to a staff record. Please contact your "
    "organisation administrator."
)

# Byte-for-byte identical confirmation returned by the password-reset request
# endpoint for EVERY outcome — unknown slug, non-matching email, or a genuine
# match (anti-enumeration, R14.1). It must never vary by whether an account
# exists, so it is a single fixed string returned on all paths.
_RESET_REQUEST_CONFIRMATION = (
    "If an account matches that email address, we've sent a link to reset its "
    "password. Please check your inbox."
)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# ---------------------------------------------------------------------------
# Portal session dependency (R6.10) + CSRF double-submit dependency (R6.7, R6.8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmployeePortalSessionCtx:
    """Per-request auth context for an authenticated ``/e/api`` call.

    Built by :func:`require_portal_session` once the ``emp_portal_session``
    cookie has been validated. Carries everything a downstream handler needs
    without re-querying: the tenant ``org_id`` (also pushed into the RLS GUC),
    the portal user + its linked ``staff_id``, the user's email, the session row
    id, and the session's CSRF token.
    """

    org_id: uuid.UUID
    portal_user_id: uuid.UUID
    staff_id: uuid.UUID
    email: str
    session_id: uuid.UUID
    csrf_token: str


def _session_invalid_exc() -> HTTPException:
    """401 with the neutral ``session_invalid`` envelope (R6.10)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"message": _SESSION_INVALID_MESSAGE, "code": "session_invalid"},
    )


async def _resolve_session_ctx(
    db: AsyncSession, raw_token: str, now: datetime
) -> EmployeePortalSessionCtx | None:
    """Resolve + validate a raw session token into a context, or ``None``.

    Steps (R6.10):

    1. Hash the raw cookie value and look the session row up by
       ``session_token_hash``. The lookup is intentionally tenant-agnostic — a
       ``/e/api`` request carries no slug, so the GUC is unset for it and the
       session row is the only thing that tells us which org we are in.
    2. Reject (``None``) when the row is missing or fails
       :func:`session_service.is_session_valid` (past the 12h absolute window or
       idle for more than 30 min).
    3. Set the RLS ``app.current_org_id`` GUC from the **session's** ``org_id``
       (server-trusted) so every subsequent tenant-scoped read is correctly
       isolated.
    4. Resolve the still-active portal user; reject if the user is gone or has
       been deactivated/revoked (its sessions are deleted on revoke, but guard
       anyway).
    5. On a valid request, slide the 30-min idle window forward by touching
       ``last_seen_at``.
    """
    sess_res = await db.execute(
        select(EmployeePortalSession).where(
            EmployeePortalSession.session_token_hash
            == session_service.hash_token(raw_token)
        )
    )
    session: EmployeePortalSession | None = sess_res.scalars().first()
    if session is None:
        return None
    if not session_service.is_session_valid(
        session.created_at, session.last_seen_at, now
    ):
        return None

    # Trust the session row for tenant scoping (R6.10) — set RLS from its org.
    await _set_rls_org_id(db, str(session.org_id))

    user_res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.id == session.portal_user_id,
            EmployeePortalUser.is_active.is_(True),
        )
    )
    user: EmployeePortalUser | None = user_res.scalars().first()
    if user is None:
        return None

    # Valid request → slide the idle window forward (R6.10).
    await session_service.touch_session(db, session)

    return EmployeePortalSessionCtx(
        org_id=session.org_id,
        portal_user_id=user.id,
        staff_id=user.staff_id,
        email=user.email,
        session_id=session.id,
        csrf_token=session.csrf_token,
    )


async def require_portal_session(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> EmployeePortalSessionCtx:
    """FastAPI dependency: require a valid ``emp_portal_session`` cookie.

    Returns an :class:`EmployeePortalSessionCtx` and sets the RLS org GUC on
    success. Raises a neutral ``401 session_invalid`` for a missing cookie, an
    unknown/expired/idle-timed-out session, or a deactivated user (R6.10) — the
    identical body for every cause so nothing leaks about why auth failed.
    """
    raw_token = request.cookies.get(_SESSION_COOKIE_NAME)
    if not raw_token:
        raise _session_invalid_exc()
    ctx = await _resolve_session_ctx(db, raw_token, datetime.now(timezone.utc))
    if ctx is None:
        raise _session_invalid_exc()
    return ctx


def validate_emp_portal_csrf(
    request: Request,
    emp_portal_csrf: str | None = Cookie(default=None, alias=_CSRF_COOKIE_NAME),
) -> None:
    """Double-submit CSRF gate for state-changing ``/e/api`` requests (R6.7, R6.8).

    The request is rejected with ``403 csrf_failed`` — **before** any state
    change — unless the ``X-CSRF-Token`` header is present and equals the
    ``emp_portal_csrf`` cookie (constant-time compare). Safe methods
    (GET/HEAD/OPTIONS) are exempt as they perform no state change. Use this as a
    route dependency on every POST/PUT/PATCH/DELETE ``/e/api`` endpoint.

    The cookie value equals the session's ``csrf_token`` by construction (it is
    minted alongside the session and set as the readable ``emp_portal_csrf``
    cookie), so a matching header proves the caller can read the cookie — which
    a cross-site attacker cannot.
    """
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    header = request.headers.get(_CSRF_HEADER_NAME)
    if (
        not emp_portal_csrf
        or not header
        or not secrets.compare_digest(emp_portal_csrf, header)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": _CSRF_FAILED_MESSAGE, "code": "csrf_failed"},
        )


# ---------------------------------------------------------------------------
# POST /e/api/auth/login  (task 10.1 — R4.5, R6.1–R6.6, R6.11, R16.6)
# ---------------------------------------------------------------------------


@router.post("/auth/login")
async def login(
    body: S.LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Authenticate a portal user against an org-branded portal and open a session.

    Flow (design §Login sequence, R6.3–R6.6):

    1. Resolve the org by ``normalise_slug(slug)``. Unknown slug → neutral
       ``404 portal_unavailable`` (R6.11, no enumeration).
    2. Require ``employee_portal_enabled``; disabled → neutral
       ``403 portal_unavailable`` (R4.5).
    3. Set the RLS ``app.current_org_id`` GUC from the *resolved* org
       (server-trusted — never from client input) so every portal-table read /
       write below is correctly tenant-scoped.
    4. Look up the active portal user by ``lower(email)``. Honour the lockout
       window (``403 account_locked``, R6.5).
    5. On a bad email/password, record a failed attempt **only when the user
       exists** (5th consecutive failure locks for 15 min, R6.5/R6.6), write a
       ``login_failed`` audit row (with a null ``portal_user_id`` for an unknown
       email, R16.6), and return the generic ``401 invalid_credentials`` — the
       identical body regardless of whether the email matched (R6.4).
    6. On success, reset the lockout, mint a session, write a ``login_success``
       audit row, and set the ``emp_portal_session`` (HttpOnly) + ``emp_portal_csrf``
       (readable) cookies scoped to ``/e`` (R6.1, R6.2).

    Failure responses are returned as :class:`JSONResponse` rather than raised as
    ``HTTPException`` so the failed-attempt increment and the audit row commit
    with the request transaction (raising would roll the session's
    ``begin()`` block back, losing both the lockout progress and the audit
    trail). The body uses the ``{message, code}`` envelope.
    """
    now = datetime.now(timezone.utc)
    ip = _client_ip(request)

    # --- 1. Resolve org by slug (R6.11). organisations is the tenant-root table
    #        and carries no RLS policy, so this lookup runs before any GUC is set.
    slug = normalise_slug(body.slug)
    org_res = await db.execute(
        select(Organisation).where(func.lower(Organisation.slug) == slug)
    )
    org = org_res.scalars().first()
    if org is None:
        # Unknown slug — neutral not-found, no DB write (cannot scope an audit
        # row without a resolved org, and revealing nothing avoids enumeration).
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "message": _PORTAL_UNAVAILABLE_MESSAGE,
                "code": "portal_unavailable",
            },
        )

    # --- 2. Require the portal to be enabled for this org (R4.5). -------------
    org_settings = await get_org_settings(db, org_id=org.id)
    if not org_settings.get("employee_portal_enabled"):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "message": _PORTAL_UNAVAILABLE_MESSAGE,
                "code": "portal_unavailable",
            },
        )

    # --- 3. Set RLS context from the trusted, server-resolved org id. ---------
    # Every employee_portal_* read/write below is now tenant-scoped to org.id.
    await _set_rls_org_id(db, str(org.id))

    # --- 4. Look up the active portal user by case-insensitive email. ---------
    email = (body.email or "").strip().lower()
    user_res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.org_id == org.id,
            func.lower(EmployeePortalUser.email) == email,
            EmployeePortalUser.is_active.is_(True),
        )
    )
    user: EmployeePortalUser | None = user_res.scalars().first()

    # --- 4a. Honour the lockout window (R6.5). Only an existing account can be
    #         locked; an unknown email never reports "locked" (anti-enumeration).
    if user is not None and ep_auth.is_locked(
        user.failed_login_attempts, user.locked_until, now
    ):
        _write_audit(
            db,
            org_id=org.id,
            portal_user_id=user.id,
            action="login_failed",
            ip=ip,
            details={"reason": "account_locked"},
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"message": _ACCOUNT_LOCKED_MESSAGE, "code": "account_locked"},
        )

    # --- 5. Verify the password. A missing user or unaccepted invite (no
    #        password_hash) is treated as a bad credential; we still burn a
    #        bcrypt verify against a dummy hash so timing does not leak whether
    #        the email matched (R6.4 anti-enumeration).
    stored_hash = user.password_hash if user is not None else None
    password_ok = await ep_auth.verify_password(
        body.password, stored_hash or _DUMMY_PASSWORD_HASH
    )
    if user is None or not stored_hash or not password_ok:
        # Record a failed attempt ONLY when the account actually exists (R6.5);
        # the lockout state machine increments and may lock on the 5th failure.
        if user is not None:
            user.failed_login_attempts, user.locked_until = (
                ep_auth.record_failed_attempt(
                    user.failed_login_attempts, user.locked_until, now
                )
            )
            await db.flush()
        # A failed unknown-email login still writes an audit row with a null
        # portal_user_id (R16.6) — same generic 401 either way (R6.4).
        _write_audit(
            db,
            org_id=org.id,
            portal_user_id=user.id if user is not None else None,
            action="login_failed",
            ip=ip,
            details={"reason": "invalid_credentials"},
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "message": _INVALID_CREDENTIALS_MESSAGE,
                "code": "invalid_credentials",
            },
        )

    # --- 6. Success — reset lockout, mint a session, audit, set cookies. ------
    user.failed_login_attempts, user.locked_until = ep_auth.reset_lockout()
    user.last_login_at = now
    user.last_login_ip = ip
    await db.flush()

    session, raw_session_token = await session_service.create_session(db, user)

    # first_name is sourced from the linked staff_members row (own identity only).
    first_name: str | None = None
    staff_res = await db.execute(
        select(StaffMember.first_name).where(StaffMember.id == user.staff_id)
    )
    first_row = staff_res.first()
    if first_row is not None:
        first_name = first_row[0]

    _write_audit(
        db,
        org_id=org.id,
        portal_user_id=user.id,
        action="login_success",
        outcome="success",
        ip=ip,
    )

    logger.info(
        "employee_portal.login_success org_id=%s portal_user_id=%s",
        org.id,
        user.id,
    )

    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "portal_user_id": str(user.id),
            "email": user.email,
            "first_name": first_name,
            "staff_id": str(user.staff_id),
        },
    )
    _set_session_cookies(
        response, session_token=raw_session_token, csrf_token=session.csrf_token
    )
    return response


# ---------------------------------------------------------------------------
# POST /e/api/auth/logout  (task 10.2 — R6.7, R6.8, R6.9)
# ---------------------------------------------------------------------------


@router.post("/auth/logout")
async def logout(
    request: Request,
    _: None = Depends(validate_emp_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Destroy the current session and clear both cookies (R6.9).

    CSRF-validated via the double-submit dependency (R6.7, R6.8): the
    ``X-CSRF-Token`` header must equal the ``emp_portal_csrf`` cookie or the
    request is rejected ``403`` before anything is deleted. The session row is
    deleted by its ``session_token_hash`` so the token can never be replayed;
    the response clears both ``/e``-scoped cookies. Idempotent — logging out
    with a missing/already-deleted cookie still returns ``200 {ok}``.
    """
    raw_token = request.cookies.get(_SESSION_COOKIE_NAME)
    if raw_token:
        await session_service.destroy_session(db, raw_token)

    response = JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    _clear_session_cookies(response)
    return response


# ---------------------------------------------------------------------------
# GET /e/api/auth/me  (task 10.2 — R6.10)
# ---------------------------------------------------------------------------


@router.get("/auth/me")
async def me(
    ctx: EmployeePortalSessionCtx = Depends(require_portal_session),
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return the current portal user's identity + org branding (R6.10).

    The :func:`require_portal_session` dependency validates the session (row
    exists, within the 12h absolute window, not idle > 30 min), touches
    ``last_seen_at``, sets the RLS org from the session, and raises
    ``401 session_invalid`` otherwise. Here we source ``first_name`` from the
    linked ``staff_members`` row (RLS-scoped to the session's org) and the
    ``org_name`` + branding (logo + brand colours) from the org settings, and
    return them alongside the portal user's own identity.
    """
    staff_res = await db.execute(
        select(StaffMember.first_name).where(StaffMember.id == ctx.staff_id)
    )
    staff_row = staff_res.first()
    first_name: str | None = staff_row[0] if staff_row is not None else None

    org_settings = await get_org_settings(db, org_id=ctx.org_id)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "portal_user_id": str(ctx.portal_user_id),
            "email": ctx.email,
            "first_name": first_name,
            "staff_id": str(ctx.staff_id),
            "org_name": org_settings.get("org_name"),
            "branding": {
                "logo_url": org_settings.get("logo_url"),
                "primary_colour": org_settings.get("primary_colour"),
                "secondary_colour": org_settings.get("secondary_colour"),
            },
        },
    )


# ---------------------------------------------------------------------------
# GET  /e/api/auth/accept-invite/{token}  (task 10.3 — R5.5, R5.8, R5.9)
# POST /e/api/auth/accept-invite/{token}  (task 10.3 — R5.5, R5.6, R5.9)
#
# Public (no session) endpoints — they live under /e/api which is JWT-bypassed
# and they predate the user having any session. They are therefore NOT gated by
# require_portal_session or validate_emp_portal_csrf: the state-changing POST is
# authenticated by the single-use invite token itself (which a cross-site
# attacker cannot read), so the session-based double-submit CSRF check does not
# apply (there is no session yet — the user is setting their initial password).
# ---------------------------------------------------------------------------


@router.get("/auth/accept-invite/{token}")
async def accept_invite_status(
    token: str,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Preview an invite's status without consuming it (R5.8, R5.9).

    Resolves the Portal_User by ``sha256(token)`` against ``invite_token_hash``
    and returns ``{status, org_name, email}`` where ``status`` is one of:

    - ``not_found`` — the token matches no outstanding invite (unknown token, or
      an already-accepted invite whose hash has been cleared). Neutral response
      with ``org_name``/``email`` omitted so nothing about an org or account is
      revealed.
    - ``used`` — the invite was already accepted (``invite_accepted_at`` set).
    - ``expired`` — the invite is older than 7 days (R5.9).
    - ``valid`` — fresh, unaccepted, within the 7-day window.

    This is a read-only status preview — it never consumes the token (the GET
    leaves ``invite_token_hash`` untouched; only the POST consumes it). The
    lookup is intentionally tenant-agnostic (a ``/e/api`` request carries no
    slug) — the invite-hash index is unique across orgs, and the matched row's
    own ``org_id`` is used to read the org branding for ``org_name``.
    """
    res = await db.execute(
        select(EmployeePortalUser).where(
            EmployeePortalUser.invite_token_hash == session_service.hash_token(token)
        )
    )
    user: EmployeePortalUser | None = res.scalars().first()
    if user is None:
        # Neutral not-found — reveal nothing about org/account existence.
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "not_found", "org_name": None, "email": None},
        )

    now = datetime.now(timezone.utc)
    if user.invite_accepted_at is not None:
        invite_status = "used"
    else:
        sent_at = user.invite_sent_at
        if sent_at is not None and sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        if sent_at is None or sent_at + account_service.INVITE_VALIDITY < now:
            invite_status = "expired"
        else:
            invite_status = "valid"

    # Read org branding scoped to the matched row's own org (server-trusted).
    await _set_rls_org_id(db, str(user.org_id))
    org_settings = await get_org_settings(db, org_id=user.org_id)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": invite_status,
            "org_name": org_settings.get("org_name"),
            "email": user.email,
        },
    )


@router.post("/auth/accept-invite/{token}")
async def accept_invite(
    token: str,
    body: S.AcceptInviteRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Set the initial password for an invited Portal_User (R5.5, R5.6, R5.9).

    Delegates to :func:`account_service.accept_invite`, which resolves the
    invite by ``sha256(token)``, enforces the 7-day single-use validity, and
    validates the 8..128 password length before writing ``password_hash``,
    stamping ``invite_accepted_at``, and clearing ``invite_token_hash`` (the
    plaintext is never stored, R5.5).

    Error mapping (the service raises with the matching ``status_code``/``code``,
    so a single catch translates all of them to the ``{message, code}``
    envelope):

    - :class:`InviteExpired` → ``410 invite_expired`` (now > invite_sent_at + 7d)
    - :class:`PasswordLengthError` → ``422 password_length``
    - :class:`InviteNotFound` → ``404 invite_not_found`` (unknown/used token)

    On any failure the service leaves all Portal_User state unchanged, so
    raising ``HTTPException`` (which rolls the request transaction back) commits
    nothing — there is no partial state to undo.
    """
    try:
        await account_service.accept_invite(db, token, body.new_password)
    except account_service.AccountServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ---------------------------------------------------------------------------
# POST /e/api/auth/password/reset-request  (task 10.4 — R14.1, R14.5, R15.5)
# POST /e/api/auth/password/reset          (task 10.4 — R14.6, R14.7, R14.8)
#
# Public (no session) endpoints — they live under /e/api which is JWT-bypassed
# and CSRF-exempt (the user has no session yet). Neither is gated by
# require_portal_session or validate_emp_portal_csrf: reset-request is
# unauthenticated by design, and reset is authenticated by the single-use reset
# token itself (which a cross-site attacker cannot read), so the session-based
# double-submit CSRF check does not apply.
# ---------------------------------------------------------------------------


@router.post("/auth/password/reset-request")
async def request_password_reset(
    body: S.PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Begin a password reset, always returning an identical confirmation (R14.1).

    Flow (design §Public API — password reset):

    1. Resolve the org by ``normalise_slug(slug)`` — ``organisations`` is the
       tenant-root table and carries no RLS policy, so this runs before any GUC
       is set.
    2. When the org resolves, set the RLS ``app.current_org_id`` GUC from the
       server-resolved org and ask :func:`account_service.request_reset` to
       issue a single-use reset token (``sha256(raw)`` hash + 3600s expiry,
       R14.3) for the active Portal_User matching the email — or ``None`` when
       no active user matches.
    3. On a genuine match, build the branded ``/e/{slug}/reset/{token}`` reset
       URL and dispatch :func:`send_password_reset_email` **after** the token
       row is flushed (R14.2, R15.5). The email helper never raises on a
       provider failure, so the confirmation is unaffected.
    4. **Always** return the byte-for-byte identical ``200`` confirmation,
       whether or not the slug resolved or the email matched, so account (and
       org) existence is never revealed (anti-enumeration, R14.1).

    The response is a :class:`JSONResponse` rather than a raised exception so the
    issued reset-token write commits with the request transaction (raising would
    roll the session's ``begin()`` block back, discarding the token). This
    endpoint is not CSRF-gated — there is no session yet.
    """
    slug = normalise_slug(body.slug)
    org_res = await db.execute(
        select(Organisation).where(func.lower(Organisation.slug) == slug)
    )
    org = org_res.scalars().first()

    if org is not None:
        # Scope every employee_portal_* read/write to the resolved org (R16.3).
        await _set_rls_org_id(db, str(org.id))
        result = await account_service.request_reset(db, org.id, body.email)
        if result is not None:
            user, raw_token = result
            # Branded reset URL — same origin precedence as the credential-setup
            # link (request Origin → configured base → localhost).
            base = (
                request.headers.get("origin")
                or settings.frontend_base_url
                or "http://localhost"
            ).rstrip("/")
            reset_url = f"{base}/e/{org.slug}/reset/{raw_token}"

            org_settings = await get_org_settings(db, org_id=org.id)
            org_name = org_settings.get("org_name") or org.name or "Your organisation"

            # AFTER the reset-token row is flushed (inside request_reset):
            # dispatch the reset email. Never raises on a provider failure
            # (R15.3), so the identical confirmation below is unaffected.
            await employee_portal_delivery.send_password_reset_email(
                db,
                staff_email=user.email,
                org_name=org_name,
                reset_url=reset_url,
                org_id=org.id,
            )

    # ALWAYS the same body — unknown slug, non-matching email, or a real match
    # are indistinguishable to the caller (anti-enumeration, R14.1).
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"ok": True, "message": _RESET_REQUEST_CONFIRMATION},
    )


@router.post("/auth/password/reset")
async def complete_password_reset(
    body: S.PasswordResetCompleteRequest,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Complete a password reset with a single-use token (R14.6, R14.7, R14.8).

    Delegates to :func:`account_service.complete_reset`, which resolves the
    Portal_User by ``sha256(token)``, requires the token to be unexpired and
    unused, validates the 8..128 password length, sets the new ``password_hash``,
    clears the reset token (single-use, R14.5), and deletes all of the user's
    sessions (R14.8).

    Error mapping (the service raises with the matching ``status_code``/``code``,
    so a single catch translates all of them to the ``{message, code}``
    envelope):

    - :class:`ResetTokenInvalid` → ``400 reset_token_invalid`` (expired / used /
      unknown — the stored hash is left unchanged, R14.6).
    - :class:`PasswordLengthError` → ``422 password_length`` (R14.7).

    On any failure the service leaves all Portal_User state unchanged, so raising
    ``HTTPException`` (which rolls the request transaction back) commits nothing.
    This endpoint is not CSRF-gated — it is authenticated by the reset token
    itself and the user has no session yet.
    """
    try:
        await account_service.complete_reset(db, body.token, body.new_password)
    except account_service.AccountServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})


# ---------------------------------------------------------------------------
# GET /e/api/branding/{slug}  (task 11.1 — R8.1, R8.2, R8.3, R13.1, R13.4)
#
# Public (no session) endpoint — it backs the org-branded login page, which the
# visitor reaches before authenticating. It lives under /e/api (JWT-bypassed)
# and is a safe GET, so it is gated by neither require_portal_session nor
# validate_emp_portal_csrf.
# ---------------------------------------------------------------------------


@router.get("/branding/{slug}")
async def branding(
    slug: str,
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return an org's name + Portal_Branding for the branded login page.

    Flow (design §Public API — web branding resolve, R8.1–R8.3, R13.1, R13.4):

    1. Resolve the org by ``normalise_slug(slug)`` with a case-insensitive
       ``lower(slug)`` match (R8.2). ``organisations`` is the tenant-root table
       and carries no RLS policy, so this lookup runs before any GUC is set.
    2. Require ``employee_portal_enabled`` for the resolved org.
    3. Return ``200 {org_name, logo_url, primary_colour, secondary_colour}`` —
       sourced from the existing Org_Settings branding fields (R13.4) — ONLY
       when the slug resolves AND the portal is enabled. The colour/logo fields
       are nullable so the SPA can fall back to a neutral default (R13.2). No
       other org data is returned (R13.4).
    4. For an unknown slug OR a disabled portal, return the **identical** neutral
       ``404 portal_unavailable`` with no body fields, so it is impossible to
       tell whether the organisation exists (no existence leak, R8.3).

    This is an anti-enumeration response: the unknown-slug and disabled-portal
    paths are byte-for-byte indistinguishable.
    """
    normalised = normalise_slug(slug)

    org_res = await db.execute(
        select(Organisation).where(func.lower(Organisation.slug) == normalised)
    )
    org = org_res.scalars().first()

    if org is not None:
        org_settings = await get_org_settings(db, org_id=org.id)
        if org_settings.get("employee_portal_enabled"):
            # Slug resolves AND portal enabled → return name + branding only.
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "org_name": org_settings.get("org_name"),
                    "logo_url": org_settings.get("logo_url"),
                    "primary_colour": org_settings.get("primary_colour"),
                    "secondary_colour": org_settings.get("secondary_colour"),
                },
            )

    # Unknown slug OR portal disabled — neutral, identical 404 (R8.3, no leak).
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "message": _PORTAL_UNAVAILABLE_MESSAGE,
            "code": "portal_unavailable",
        },
    )


# ---------------------------------------------------------------------------
# GET /e/api/profile  (task 11.3 — R7.1, R7.5, R7.7, R16.3, R16.4)
#
# Authenticated (session required) endpoint backing the MVP profile view. The
# require_portal_session dependency validates the cookie, sets the RLS org GUC
# from the session, and raises 401 session_invalid otherwise. It is a safe GET
# so the CSRF double-submit gate does not apply.
# ---------------------------------------------------------------------------


def _not_linked_exc() -> HTTPException:
    """409 with the human-readable ``not_linked`` envelope (R7.7)."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"message": _NOT_LINKED_MESSAGE, "code": "not_linked"},
    )


@router.get("/profile")
async def profile(
    ctx: EmployeePortalSessionCtx = Depends(require_portal_session),
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return the authenticated Portal_User's **own** staff profile (R7.1, R7.5).

    Flow (design §Portal API — authenticated profile & roster, R7.1/R7.5/R7.7):

    1. :func:`require_portal_session` validates the session, touches
       ``last_seen_at``, and sets the RLS ``app.current_org_id`` GUC from the
       session's ``org_id`` so every read below is tenant-scoped (R16.3).
    2. Load the ``staff_members`` row for the session's ``staff_id`` — scoped to
       the session's ``org_id`` as an explicit defence-in-depth filter on top of
       RLS (own record only, R7.1). A request can therefore only ever resolve
       the caller's own staff record; a foreign/other-org id never matches and
       yields no fields and no existence disclosure (R7.5, R16.4).
    3. If the portal user has no linked staff (``staff_id`` unset) or the staff
       row does not resolve within the session's org, return ``409 not_linked``
       with a human-readable message (R7.7) — no staff-scoped fields are
       returned.
    4. Decrypt the ``ird_number_encrypted`` / ``bank_account_number_encrypted``
       ciphertext columns (best-effort — a missing key or corrupt envelope masks
       to ``None`` rather than raising) and immediately **mask** the plaintext
       via :func:`mask_ird` / :func:`mask_bank_account`. The plaintext is never
       placed on the wire; only the masked display value (e.g. ``"***123"``) is
       returned. Mirrors the staff router's ``_enrich_reporting_to`` decrypt+mask.
    5. Return the staff member's own identity, contact, and employment basics.
    """
    # R7.7 — a portal user with no linked staff cannot access staff-scoped data.
    if ctx.staff_id is None:
        raise _not_linked_exc()

    # Own record only: filter on both the session's staff_id AND its org_id
    # (RLS already scopes to the org; the explicit org filter is defence-in-depth
    # so a foreign/other-org id can never resolve — R7.1, R7.5, R16.4).
    staff_res = await db.execute(
        select(StaffMember).where(
            StaffMember.id == ctx.staff_id,
            StaffMember.org_id == ctx.org_id,
        )
    )
    staff: StaffMember | None = staff_res.scalars().first()

    # No linked / resolvable staff record → not_linked (R7.7). No fields and no
    # existence disclosure for any non-owned record (R7.5, R16.4).
    if staff is None:
        raise _not_linked_exc()

    # Decrypt + mask PII (mirror staff router _enrich_reporting_to). Best-effort:
    # a missing key or corrupt envelope yields the masked value of None (None).
    ird_masked: str | None = None
    ird_ct = getattr(staff, "ird_number_encrypted", None)
    if ird_ct:
        try:
            ird_masked = mask_ird(envelope_decrypt_str(ird_ct))
        except Exception:  # noqa: BLE001 - best-effort PII decryption
            ird_masked = None

    bank_masked: str | None = None
    bank_ct = getattr(staff, "bank_account_number_encrypted", None)
    if bank_ct:
        try:
            bank_masked = mask_bank_account(envelope_decrypt_str(bank_ct))
        except Exception:  # noqa: BLE001 - best-effort PII decryption
            bank_masked = None

    resp = S.ProfileResponse(
        staff_id=staff.id,
        first_name=staff.first_name,
        last_name=staff.last_name,
        name=staff.name,
        email=staff.email,
        phone=staff.phone,
        position=staff.position,
        employee_id=staff.employee_id,
        employment_basis=staff.employment_basis,
        employment_type=staff.employment_type,
        working_arrangement=staff.working_arrangement,
        employment_start_date=staff.employment_start_date,
        tax_code=staff.tax_code,
        kiwisaver_enrolled=staff.kiwisaver_enrolled,
        ird_number=ird_masked,
        bank_account_number=bank_masked,
        emergency_contact_name=staff.emergency_contact_name,
        emergency_contact_phone=staff.emergency_contact_phone,
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK, content=resp.model_dump(mode="json")
    )


# ---------------------------------------------------------------------------
# GET /e/api/roster  (task 11.4 — R7.1, R7.2, R7.4)
#
# Authenticated (session required) endpoint backing the MVP roster/schedule
# view. The require_portal_session dependency validates the cookie, sets the RLS
# org GUC from the session, and raises 401 session_invalid otherwise. It is a
# safe GET so the CSRF double-submit gate does not apply.
# ---------------------------------------------------------------------------


def _current_week_start(today: date) -> date:
    """Return the Monday of the week containing ``today`` (UTC week start).

    ``date.weekday()`` is 0 for Monday, so subtracting it lands on Monday.
    """
    return today - timedelta(days=today.weekday())


@router.get("/roster")
async def roster(
    ctx: EmployeePortalSessionCtx = Depends(require_portal_session),
    week_start: date | None = Query(
        default=None,
        description=(
            "ISO date (YYYY-MM-DD) for the start of the week to view; defaults "
            "to the current week's Monday when omitted."
        ),
    ),
    db: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Return the authenticated Portal_User's **own** weekly roster (R7.1, R7.4).

    Flow (design §Portal API — authenticated profile & roster, R7.1/R7.2/R7.4):

    1. :func:`require_portal_session` validates the session, touches
       ``last_seen_at``, and sets the RLS ``app.current_org_id`` GUC from the
       session's ``org_id`` so every read below is tenant-scoped (R16.3).
    2. A portal user with no linked staff (``staff_id`` unset) cannot access the
       staff-scoped roster — return ``409 not_linked`` (R7.7), mirroring the
       profile endpoint.
    3. Resolve the week window: ``week_start`` defaults to the current week's
       Monday when the query param is omitted, and the window runs
       ``week_start .. week_start + 7 days`` against UTC midnight boundaries —
       the exact window logic the public staff roster viewer
       (``app/modules/staff/public_router.py`` ``view_staff_roster``) uses, so
       this reuses that data path rather than duplicating it (R7.4).
    4. Load the ``schedule_entries`` rows scoped to the SESSION's ``staff_id``
       **and** ``org_id`` (own roster only, R7.1 — the explicit org filter is
       defence-in-depth on top of RLS so no other staff's or org's entries can
       ever resolve), ordered by ``start_time``.
    5. Return ``200 {staff_id, week_start, week_end, entries}`` with only the
       display fields (start/end, title, notes, entry_type) — never another
       staff member's or org's entries (R7.1, R16.4).
    """
    # R7.7 — a portal user with no linked staff cannot access staff-scoped data.
    if ctx.staff_id is None:
        raise _not_linked_exc()

    # Resolve the week window (default = current week's Monday, UTC).
    resolved_week_start = week_start or _current_week_start(
        datetime.now(timezone.utc).date()
    )
    week_end = resolved_week_start + timedelta(days=7)

    # Mirror the public roster viewer's UTC-midnight window comparison: entries
    # are stored UTC; compare start_time against [week_start, week_start + 7d).
    start_dt = datetime.combine(resolved_week_start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(week_end, time.min, tzinfo=timezone.utc)

    # Own roster only: scope to the session's staff_id AND org_id (RLS already
    # scopes to the org; the explicit org filter is defence-in-depth so a
    # foreign/other-org entry can never resolve — R7.1, R16.4).
    entries_res = await db.execute(
        select(ScheduleEntry)
        .where(
            ScheduleEntry.org_id == ctx.org_id,
            ScheduleEntry.staff_id == ctx.staff_id,
            ScheduleEntry.start_time >= start_dt,
            ScheduleEntry.start_time < end_dt,
        )
        .order_by(ScheduleEntry.start_time)
    )
    entries = entries_res.scalars().all()

    resp = S.RosterResponse(
        staff_id=ctx.staff_id,
        week_start=resolved_week_start,
        week_end=week_end,
        entries=[
            S.RosterEntry(
                start_time=e.start_time,
                end_time=e.end_time,
                title=e.title,
                notes=e.notes,
                entry_type=e.entry_type,
            )
            for e in entries
        ],
    )

    return JSONResponse(
        status_code=status.HTTP_200_OK, content=resp.model_dump(mode="json")
    )


def _write_audit(
    db: AsyncSession,
    *,
    org_id,
    action: str,
    portal_user_id=None,
    outcome: str = "failure",
    ip: str | None = None,
    details: dict | None = None,
) -> None:
    """Append an ``employee_portal_audit_log`` row (R16.5, R16.6).

    Added to the request session only; it commits/rolls back atomically with the
    triggering response because the request runs inside ``session.begin()``.
    ``portal_user_id`` is left ``None`` for a failed login against an unknown
    email so the row is recorded without revealing account existence (R16.6).
    """
    db.add(
        EmployeePortalAuditLog(
            org_id=org_id,
            portal_user_id=portal_user_id,
            action=action,
            outcome=outcome,
            ip_address=ip,
            details=details,
        )
    )


__all__ = [
    "router",
    "require_portal_session",
    "validate_emp_portal_csrf",
    "EmployeePortalSessionCtx",
]
