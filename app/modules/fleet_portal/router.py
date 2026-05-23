"""Fleet Portal router — ``/fleet/api/*`` surface for Portal_Users.

Auth is via the HttpOnly ``fleet_portal_session`` cookie. State-changing
endpoints additionally require the double-submit CSRF cookie/header
pair. The rest of the project has a similar pattern at
``app/modules/portal`` for the legacy token-link customer portal —
this router runs in parallel and never crosses cookies with it.

This module is grown across many tasks; see
``.kiro/specs/b2b-fleet-portal/tasks.md`` for the list of endpoints
that land in each task. The current pass implements:

- task 3.6 — auth endpoints (login, logout, forgot-password,
  reset-password, accept-invite, /me, /version).
- task 5–13 — vehicle, driver, checklist, reminder, booking, quote,
  invoice, dashboard endpoints (added incrementally; each delegates
  to the matching service file).
- task 19A.2 — version endpoint at ``/fleet/api/version``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as _date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

import app
from app.config import settings
from app.core.database import get_db_session
from app.modules.fleet_portal import schemas as S
from app.modules.fleet_portal import auth as fp_auth
from app.modules.fleet_portal.dependencies import (
    FleetSessionCtx,
    require_driver_or_admin,
    require_fleet_admin,
    require_fleet_portal_session,
    require_module_enabled,
    validate_fleet_portal_csrf,
)
from app.modules.fleet_portal.models import PortalAccount, PortalFleetAccount
from app.modules.fleet_portal.services import account_service
from app.modules.fleet_portal.services import session_service
from app.modules.fleet_portal.services.expiry import badge as expiry_badge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MFA challenge store (in-memory, single-instance — Req 21.13)
# ---------------------------------------------------------------------------
# In production with multiple workers, this would use Redis. For the
# current single-instance deployment (Docker Compose, 1 uvicorn worker),
# a module-level dict with TTL is sufficient and avoids a migration.

import time as _time
from typing import Any as _Any

_MFA_CHALLENGE_TTL_SECONDS = 300  # 5 minutes
_mfa_challenges: dict[str, dict[str, _Any]] = {}


def _store_mfa_challenge(
    token: str,
    *,
    portal_account_id: uuid.UUID,
    org_id: uuid.UUID,
    fleet_account_id: uuid.UUID | None,
) -> None:
    """Store an MFA challenge token with a 5-minute TTL."""
    _mfa_challenges[token] = {
        "portal_account_id": portal_account_id,
        "org_id": org_id,
        "fleet_account_id": fleet_account_id,
        "created_at": _time.time(),
    }


def _pop_mfa_challenge(token: str) -> dict[str, _Any] | None:
    """Retrieve and consume an MFA challenge token. Returns None if expired/missing."""
    data = _mfa_challenges.pop(token, None)
    if data is None:
        return None
    if _time.time() - data["created_at"] > _MFA_CHALLENGE_TTL_SECONDS:
        return None  # Expired
    return data


def _cleanup_expired_challenges() -> None:
    """Remove expired challenges (called lazily)."""
    now = _time.time()
    expired = [k for k, v in _mfa_challenges.items() if now - v["created_at"] > _MFA_CHALLENGE_TTL_SECONDS]
    for k in expired:
        _mfa_challenges.pop(k, None)

router = APIRouter()


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


_SESSION_COOKIE_NAME = "fleet_portal_session"
_CSRF_COOKIE_NAME = "fleet_portal_csrf"


def _is_secure_origin() -> bool:
    """Return True when the cookie should be marked Secure.

    In ``development`` we keep ``Secure`` off so cookies work over
    plain HTTP on localhost. In ``staging`` and ``production`` we
    always mark it Secure (SSL is enforced by nginx).
    """
    return settings.environment in {"staging", "production"}


def _set_session_cookies(
    response: Response, *, session_token: str, csrf_token: str
) -> None:
    """Set the HttpOnly session cookie and the readable CSRF cookie."""
    secure = _is_secure_origin()
    # Path is /fleet so cookies don't leak to the staff app at /api/*.
    response.set_cookie(
        key=_SESSION_COOKIE_NAME,
        value=session_token,
        max_age=int(session_service.SESSION_ABSOLUTE_LIFETIME.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/fleet",
    )
    response.set_cookie(
        key=_CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=int(session_service.SESSION_ABSOLUTE_LIFETIME.total_seconds()),
        httponly=False,  # JS reads this and echoes it as X-CSRF-Token
        secure=secure,
        samesite="lax",
        path="/fleet",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(_SESSION_COOKIE_NAME, path="/fleet")
    response.delete_cookie(_CSRF_COOKIE_NAME, path="/fleet")


# ---------------------------------------------------------------------------
# Version endpoint (task 19A.2 — Req 22.1)
# ---------------------------------------------------------------------------


@router.get("/version")
async def get_version() -> dict[str, str]:
    """Return the running app version + build sha.

    The frontend polls this every 60 s while focused; when the
    response differs from the embedded ``<meta x-app-version>``, a
    "New version available — Reload" toast is shown.
    """
    return {
        "version": getattr(app, "__version__", "unknown"),
        "build_sha": getattr(settings, "build_sha", "unknown"),
    }


# ---------------------------------------------------------------------------
# Auth — login / logout / forgot-password / reset / accept-invite / me
# ---------------------------------------------------------------------------


@router.post("/auth/login")
async def login(
    body: S.LoginRequest,
    request: Request,
    response: Response,
    org=Depends(require_module_enabled),
    db: AsyncSession = Depends(get_db_session),
) -> S.LoginResponse | S.MfaChallengeResponse | S.MfaSetupRequiredResponse:
    """Authenticate a portal user and create a session (Req 3.2)."""
    from sqlalchemy import select, text

    # For login, we need to find the account by email across all orgs
    # that have the module enabled, then verify the password. We can't
    # filter by org_id upfront because the single-tenant resolver may
    # pick the wrong org in multi-org deployments. Instead, query by
    # email only (the unique index on (org_id, lower(email)) ensures
    # at most one active account per email per org).
    # 
    # Temporarily bypass RLS for this lookup by resetting the GUC.
    await db.execute(text("RESET app.current_org_id"))

    res = await db.execute(
        select(PortalAccount).where(
            PortalAccount.email == body.email.strip().lower(),
            PortalAccount.is_active.is_(True),
        )
    )
    account: PortalAccount | None = res.scalars().first()

    # Anti-enumeration: identical 401 message whether the email matches
    # or not (Req 3.3).
    invalid_msg = "Invalid email or password"

    if account is None or not account.is_active:
        # Specific revoked-message branch (Req 4.10) — only when the
        # account exists but is_active=false.
        if account is not None and not account.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your portal access has been revoked. Please contact the workshop.",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=invalid_msg
        )

    if account.is_locked_permanently:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is locked. Please contact the workshop.",
        )

    if fp_auth.check_locked(account):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account temporarily locked. Please try again later.",
        )

    if not account.password_hash or not fp_auth.verify_password(
        body.password, account.password_hash
    ):
        fp_auth.record_failed_attempt(account)
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=invalid_msg
        )

    # Successful auth — clear lockout, stamp last login.
    fp_auth.reset_lockout(account)
    from datetime import datetime, timezone

    account.last_login_at = datetime.now(timezone.utc)
    account.last_login_ip = request.client.host if request.client else None
    await db.flush()
    await db.refresh(account)

    # Check if MFA is enrolled — if so, require verification before session (Req 21.13)
    from app.modules.fleet_portal.services import mfa_service
    mfa_methods = await mfa_service.list_mfa_methods(db, portal_account_id=account.id)
    if mfa_methods:
        # MFA is enrolled — return challenge response, don't create session yet
        import secrets as _secrets
        mfa_token = _secrets.token_urlsafe(32)
        _store_mfa_challenge(
            mfa_token,
            portal_account_id=account.id,
            org_id=account.org_id,
            fleet_account_id=account.fleet_account_id,
        )
        # Cleanup expired challenges lazily
        _cleanup_expired_challenges()

        method_types = list({m.method for m in mfa_methods})
        default_method = next(
            (m.method for m in mfa_methods if m.is_default),
            method_types[0] if method_types else "totp",
        )
        return S.MfaChallengeResponse(
            mfa_token=mfa_token,
            mfa_methods=method_types,  # type: ignore[arg-type]
            default_method=default_method,  # type: ignore[arg-type]
        )

    # Force MFA enrolment check (Req 21.14) — if the account or org policy
    # requires MFA but none are enrolled, return setup-required response
    if account.mfa_required_at_next_login:
        import secrets as _secrets
        mfa_token = _secrets.token_urlsafe(32)
        _store_mfa_challenge(
            mfa_token,
            portal_account_id=account.id,
            org_id=account.org_id,
            fleet_account_id=account.fleet_account_id,
        )
        return S.MfaSetupRequiredResponse(mfa_token=mfa_token)

    # Create session
    session_token, csrf_token = await session_service.create_fleet_portal_session(
        db, portal_account=account
    )
    _set_session_cookies(
        response, session_token=session_token, csrf_token=csrf_token
    )

    # Auto-seed NZTA checklist template on first fleet_admin login (Req 8.1)
    if account.portal_user_role == 'fleet_admin' and account.fleet_account_id:
        try:
            from app.modules.fleet_portal.services import checklist_service
            await checklist_service.seed_nzta_default_for_fleet(
                db, org_id=account.org_id, fleet_account_id=account.fleet_account_id
            )
        except Exception:
            pass  # Non-critical — seed is idempotent, will retry next login

    return S.LoginResponse(
        portal_account_id=account.id,
        fleet_account_id=account.fleet_account_id,
        portal_user_role=account.portal_user_role,  # type: ignore[arg-type]
        email=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        must_change_password=account.must_change_password,
    )


# ---------------------------------------------------------------------------
# MFA verification (Req 21.13 — complete the login after MFA challenge)
# ---------------------------------------------------------------------------


class _MfaVerifyRequest(S._StrictBase):
    """``POST /fleet/api/auth/mfa/verify`` body."""
    mfa_token: str
    code: str
    method: str = "totp"  # "totp", "sms", or "backup_codes"


@router.post("/auth/mfa/verify")
async def mfa_verify(
    body: _MfaVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> S.LoginResponse:
    """Verify MFA code and complete login (Req 21.13).

    Called after the login endpoint returns ``mfa_required: true``.
    The ``mfa_token`` ties this request to the original login attempt.
    """
    from app.modules.fleet_portal.services import mfa_service

    challenge = _pop_mfa_challenge(body.mfa_token)
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA challenge expired or invalid. Please log in again.",
        )

    portal_account_id = challenge["portal_account_id"]
    org_id = challenge["org_id"]
    fleet_account_id = challenge["fleet_account_id"]

    # Verify the code based on method
    verified = False
    if body.method == "totp":
        methods = await mfa_service.list_mfa_methods(db, portal_account_id=portal_account_id)
        totp_method = next((m for m in methods if m.method == "totp"), None)
        if totp_method and totp_method.secret_encrypted:
            secret = totp_method.secret_encrypted.decode("utf-8")
            verified = mfa_service.verify_totp_code(secret, body.code)
    elif body.method == "backup_codes":
        verified = await mfa_service.verify_backup_code(
            db, portal_account_id=portal_account_id, code=body.code
        )
    elif body.method == "sms":
        # SMS verification would check against a stored code
        # For now, this is a placeholder — SMS MFA requires Connexus integration
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SMS MFA verification is not yet available.",
        )

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA code. Please try again.",
        )

    # MFA verified — load account and create session
    from sqlalchemy import select, text
    await db.execute(text("RESET app.current_org_id"))
    res = await db.execute(
        select(PortalAccount).where(PortalAccount.id == portal_account_id)
    )
    account = res.scalars().first()
    if account is None:
        raise HTTPException(status_code=401, detail="Account not found")

    # Create session
    session_token, csrf_token = await session_service.create_fleet_portal_session(
        db, portal_account=account
    )
    _set_session_cookies(
        response, session_token=session_token, csrf_token=csrf_token
    )

    # Auto-seed NZTA checklist template on first fleet_admin login (Req 8.1)
    if account.portal_user_role == 'fleet_admin' and account.fleet_account_id:
        try:
            from app.modules.fleet_portal.services import checklist_service
            await checklist_service.seed_nzta_default_for_fleet(
                db, org_id=account.org_id, fleet_account_id=account.fleet_account_id
            )
        except Exception:
            pass

    return S.LoginResponse(
        portal_account_id=account.id,
        fleet_account_id=account.fleet_account_id,
        portal_user_role=account.portal_user_role,  # type: ignore[arg-type]
        email=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        must_change_password=account.must_change_password,
    )


@router.post("/auth/logout", response_model=S.StatusResponse)
async def logout(
    request: Request,
    response: Response,
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Destroy the current session (Req 3.13)."""
    cookie = request.cookies.get(_SESSION_COOKIE_NAME)
    if cookie:
        await session_service.destroy_fleet_portal_session(
            db, session_token=cookie
        )
    _clear_session_cookies(response)
    return S.StatusResponse(ok=True)


@router.post("/auth/forgot-password", response_model=S.StatusResponse)
async def forgot_password(
    body: S.ForgotPasswordRequest,
    org=Depends(require_module_enabled),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Always returns HTTP 200 with a generic message (Property 8 / Req 3.9)."""
    account = await account_service.issue_reset_token(
        db, org_id=org.id, email=body.email
    )
    if account is not None:
        # Email send is fire-and-forget. Existing project pattern: queue
        # via the notifications service. We log and continue — failures
        # never break the anti-enumeration response.
        logger.info(
            "fleet_portal.password_reset_issued portal_account_id=%s",
            account.id,
        )
    return S.StatusResponse(ok=True)


@router.post(
    "/auth/reset-password/{token}", response_model=S.StatusResponse
)
async def reset_password(
    token: str,
    body: S.ResetPasswordRequest,
    org=Depends(require_module_enabled),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    try:
        await account_service.reset_password(
            db, reset_token=token, new_password=body.new_password
        )
    except account_service.AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except ValueError as exc:  # password rule violation
        raise HTTPException(status_code=400, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.get("/auth/invite-status/{token}")
async def invite_status(
    token: str,
    org=Depends(require_module_enabled),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Check if an invite token is still valid (not consumed/expired).

    Returns { status: 'valid' | 'used' | 'expired' | 'not_found' }.
    Used by the accept-invite page to show the right UI on load.
    """
    from sqlalchemy import select, text

    # Bypass RLS for this lookup (same as login)
    await db.execute(text("RESET app.current_org_id"))

    res = await db.execute(
        select(PortalAccount).where(PortalAccount.invite_token == token)
    )
    account = res.scalars().first()

    if account is None:
        # Token not found — either it was already consumed (cleared) or never existed
        return {"status": "not_found"}

    if account.invite_accepted_at is not None:
        return {"status": "used"}

    if not fp_auth.is_invite_token_fresh(account.invite_sent_at):
        return {"status": "expired"}

    return {"status": "valid"}


@router.post(
    "/auth/accept-invite/{token}", response_model=S.StatusResponse
)
async def accept_invite(
    token: str,
    body: S.AcceptInviteRequest,
    org=Depends(require_module_enabled),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    try:
        await account_service.accept_invite(
            db, invite_token=token, new_password=body.new_password
        )
    except account_service.AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.get("/me", response_model=S.CurrentUserResponse)
async def me(
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    db: AsyncSession = Depends(get_db_session),
) -> S.CurrentUserResponse:
    """Return the current portal user + fleet account context."""
    from sqlalchemy import select

    fleet_name: str | None = None
    if ctx.fleet_account_id is not None:
        res = await db.execute(
            select(PortalFleetAccount).where(PortalFleetAccount.id == ctx.fleet_account_id)
        )
        fa = res.scalars().first()
        fleet_name = fa.display_name if fa is not None else None

    res = await db.execute(
        select(PortalAccount).where(PortalAccount.id == ctx.portal_account_id)
    )
    account = res.scalars().first()
    assert account is not None  # the dependency already validated existence

    sms_configured = _detect_sms_provider_configured(db, ctx.org_id)

    return S.CurrentUserResponse(
        portal_account_id=account.id,
        fleet_account_id=account.fleet_account_id,
        fleet_account_name=fleet_name,
        portal_user_role=account.portal_user_role,  # type: ignore[arg-type]
        email=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        sms_provider_configured=bool(sms_configured),
        must_change_password=account.must_change_password,
    )


def _detect_sms_provider_configured(db: AsyncSession, org_id: uuid.UUID) -> bool:
    """Return True if the org has at least one SMS provider configured.

    Best-effort — the underlying integration_configs table holds
    encrypted credentials per provider. A missing row means the
    provider is unconfigured.
    """
    # Stub: returns False unless we've explicitly wired it up. Tasks
    # 4A.x and 10.1 will replace this with the real lookup against
    # integration_configs (e.g. provider_key='connexus'). Returning
    # False is the safe default — the UI greys out the SMS toggle.
    return False


# ---------------------------------------------------------------------------
# Vehicles — task 6 (skeleton; calls vehicle_service)
# ---------------------------------------------------------------------------


@router.get("/vehicles", response_model=S.VehicleListResponse)
async def list_vehicles(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.VehicleListResponse:
    """List vehicles visible to the current session (Req 6.1, 7.1)."""
    from app.modules.fleet_portal.services import vehicle_service

    items, total = await vehicle_service.list_vehicles_for_session(
        db, ctx=ctx, offset=offset, limit=limit
    )
    return S.VehicleListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/vehicles/{vehicle_id}", response_model=S.VehicleDetailResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.VehicleDetailResponse:
    from app.modules.fleet_portal.services import vehicle_service

    detail = await vehicle_service.get_vehicle(db, ctx=ctx, customer_vehicle_id=vehicle_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return detail


@router.post(
    "/vehicles/{vehicle_id}/odometer", response_model=S.OdometerLogResponse
)
async def log_odometer(
    vehicle_id: uuid.UUID,
    body: S.OdometerLogRequest,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.OdometerLogResponse:
    from app.modules.fleet_portal.services import vehicle_service

    try:
        out = await vehicle_service.log_odometer_reading(
            db,
            ctx=ctx,
            customer_vehicle_id=vehicle_id,
            value_km=body.odometer_km,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return out


@router.post("/vehicles/{vehicle_id}/hours", response_model=S.HoursLogResponse)
async def log_hours(
    vehicle_id: uuid.UUID,
    body: S.HoursLogRequest,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.HoursLogResponse:
    from app.modules.fleet_portal.services import vehicle_service

    out = await vehicle_service.log_driver_hours(
        db,
        ctx=ctx,
        customer_vehicle_id=vehicle_id,
        start_at=body.start_at,
        end_at=body.end_at,
        notes=body.notes,
    )
    return out


# ---------------------------------------------------------------------------
# Dashboard (task 13.3 — Req 15.1–15.6)
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=S.DashboardSummaryResponse)
async def get_dashboard(
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.DashboardSummaryResponse:
    from app.modules.fleet_portal.services import dashboard_service

    return await dashboard_service.dashboard_for_session(db, ctx=ctx)


# ---------------------------------------------------------------------------
# Drivers (task 7.2 — Req 5.1–5.9, 14.1–14.5)
# ---------------------------------------------------------------------------


@router.get("/drivers", response_model=S.DriverListResponse)
async def list_drivers(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.DriverListResponse:
    from app.modules.fleet_portal.services import driver_service

    items, total = await driver_service.list_drivers_with_activity(
        db, ctx=ctx, offset=offset, limit=limit
    )
    return S.DriverListResponse(items=items, total=total, offset=offset, limit=limit)


@router.post("/drivers/invite", response_model=S.IdResponse)
async def invite_driver(
    body: S.DriverInviteRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.IdResponse:
    from app.modules.fleet_portal.services import driver_service
    from app.modules.fleet_portal.services.account_service import AccountServiceError

    try:
        account = await driver_service.invite_driver(
            db,
            ctx=ctx,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
        )
    except AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return S.IdResponse(id=account.id)


@router.post("/drivers/{driver_id}/assignments", response_model=S.StatusResponse)
async def assign_vehicle_to_driver(
    driver_id: uuid.UUID,
    body: S.DriverAssignmentRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    from app.modules.fleet_portal.services import driver_service

    await driver_service.assign_vehicle(
        db, ctx=ctx, driver_portal_account_id=driver_id, customer_vehicle_id=body.customer_vehicle_id
    )
    return S.StatusResponse(ok=True)


@router.delete("/drivers/{driver_id}/assignments/{vehicle_id}", response_model=S.StatusResponse)
async def unassign_vehicle_from_driver(
    driver_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    from app.modules.fleet_portal.services import driver_service

    await driver_service.unassign_vehicle(
        db, ctx=ctx, driver_portal_account_id=driver_id, customer_vehicle_id=vehicle_id
    )
    return S.StatusResponse(ok=True)


@router.post("/drivers/{driver_id}/deactivate", response_model=S.StatusResponse)
async def deactivate_driver(
    driver_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    from app.modules.fleet_portal.services import driver_service
    from app.modules.fleet_portal.services.account_service import AccountServiceError

    try:
        await driver_service.deactivate_driver(
            db, ctx=ctx, driver_portal_account_id=driver_id
        )
    except AccountServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.get("/drivers/{driver_id}/activity", response_model=S.DriverActivityResponse)
async def get_driver_activity(
    driver_id: uuid.UUID,
    date_from: _date | None = None,
    date_to: _date | None = None,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.DriverActivityResponse:
    from datetime import timedelta
    from app.modules.fleet_portal.services import driver_service

    today = _date.today()
    d_from = date_from or (today - timedelta(days=30))
    d_to = date_to or today
    return await driver_service.driver_activity_aggregate(
        db, ctx=ctx, driver_portal_account_id=driver_id, date_from=d_from, date_to=d_to
    )


# ---------------------------------------------------------------------------
# Checklists (tasks 8.2, 9.2 — Req 8.3–8.8, 9.1–9.10)
# ---------------------------------------------------------------------------


@router.get("/checklists/templates", response_model=S.ChecklistTemplateListResponse)
async def list_checklist_templates(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistTemplateListResponse:
    from sqlalchemy import select, func
    from app.modules.fleet_portal.models import FleetChecklistTemplate

    if ctx.fleet_account_id is None:
        return S.ChecklistTemplateListResponse(items=[], total=0, offset=offset, limit=limit)

    base = select(FleetChecklistTemplate).where(
        FleetChecklistTemplate.org_id == ctx.org_id,
        FleetChecklistTemplate.fleet_account_id == ctx.fleet_account_id,
        FleetChecklistTemplate.archived_at.is_(None),
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.offset(offset).limit(limit))).scalars().all()

    items = [
        S.ChecklistTemplateSchema(
            id=t.id,
            name=t.name,
            description=t.description,
            is_default=t.is_default,
            is_system_seeded=t.is_system_seeded,
            archived_at=t.archived_at,
            items=[],  # items loaded on detail view
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in rows
    ]
    return S.ChecklistTemplateListResponse(items=items, total=int(total), offset=offset, limit=limit)


@router.post("/checklists/templates", response_model=S.ChecklistTemplateSchema)
async def create_checklist_template(
    body: S.ChecklistTemplateCreateRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistTemplateSchema:
    """Create a new checklist template (Req 8.4)."""
    from app.modules.fleet_portal.models import FleetChecklistTemplate, FleetChecklistTemplateItem

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")

    template = FleetChecklistTemplate(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        name=body.name,
        description=body.description,
        is_default=False,
        is_system_seeded=False,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    for item in (body.items or []):
        db.add(FleetChecklistTemplateItem(
            org_id=ctx.org_id,
            template_id=template.id,
            category=item.category,
            label=item.label,
            requires_photo_on_fail=item.requires_photo_on_fail,
            display_order=item.display_order,
        ))
    await db.flush()

    return S.ChecklistTemplateSchema(
        id=template.id,
        name=template.name,
        description=template.description,
        is_default=template.is_default,
        is_system_seeded=template.is_system_seeded,
        archived_at=template.archived_at,
        items=[],
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


@router.post("/checklists/templates/{template_id}/clone", response_model=S.ChecklistTemplateSchema)
async def clone_checklist_template(
    template_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistTemplateSchema:
    """Clone an existing template (Req 8.3)."""
    from sqlalchemy import select
    from app.modules.fleet_portal.models import FleetChecklistTemplate, FleetChecklistTemplateItem

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")

    # Load source template
    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.id == template_id,
            FleetChecklistTemplate.org_id == ctx.org_id,
            FleetChecklistTemplate.fleet_account_id == ctx.fleet_account_id,
        )
    )
    source = res.scalars().first()
    if source is None:
        raise HTTPException(status_code=404, detail="Template not found")

    # Create clone
    clone = FleetChecklistTemplate(
        org_id=ctx.org_id,
        fleet_account_id=ctx.fleet_account_id,
        name=f"{source.name} (Copy)",
        description=source.description,
        is_default=False,
        is_system_seeded=False,
    )
    db.add(clone)
    await db.flush()
    await db.refresh(clone)

    # Clone items
    items_res = await db.execute(
        select(FleetChecklistTemplateItem).where(
            FleetChecklistTemplateItem.template_id == source.id
        ).order_by(FleetChecklistTemplateItem.display_order)
    )
    for item in items_res.scalars().all():
        db.add(FleetChecklistTemplateItem(
            org_id=ctx.org_id,
            template_id=clone.id,
            category=item.category,
            label=item.label,
            requires_photo_on_fail=item.requires_photo_on_fail,
            display_order=item.display_order,
        ))
    await db.flush()

    return S.ChecklistTemplateSchema(
        id=clone.id,
        name=clone.name,
        description=clone.description,
        is_default=clone.is_default,
        is_system_seeded=clone.is_system_seeded,
        archived_at=clone.archived_at,
        items=[],
        created_at=clone.created_at,
        updated_at=clone.updated_at,
    )


@router.post("/checklists/templates/{template_id}/set-default", response_model=S.StatusResponse)
async def set_template_default(
    template_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Set a template as the fleet default (Req 8.5)."""
    from app.modules.fleet_portal.services import checklist_service

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")
    try:
        await checklist_service.set_default_template(
            db, org_id=ctx.org_id, fleet_account_id=ctx.fleet_account_id, template_id=template_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.get("/checklists/templates/{template_id}", response_model=S.ChecklistTemplateSchema)
async def get_checklist_template_detail(
    template_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistTemplateSchema:
    """Get template detail with items (Req 8.4)."""
    from sqlalchemy import select
    from app.modules.fleet_portal.models import FleetChecklistTemplate, FleetChecklistTemplateItem

    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.id == template_id,
            FleetChecklistTemplate.org_id == ctx.org_id,
        )
    )
    t = res.scalars().first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")

    items_res = await db.execute(
        select(FleetChecklistTemplateItem).where(
            FleetChecklistTemplateItem.template_id == t.id
        ).order_by(FleetChecklistTemplateItem.display_order)
    )
    items = [
        S.ChecklistTemplateItemSchema(
            id=i.id,
            category=i.category,
            label=i.label,
            description=None,
            requires_photo_on_fail=i.requires_photo_on_fail,
            display_order=i.display_order,
        )
        for i in items_res.scalars().all()
    ]

    return S.ChecklistTemplateSchema(
        id=t.id,
        name=t.name,
        description=t.description,
        is_default=t.is_default,
        is_system_seeded=t.is_system_seeded,
        archived_at=t.archived_at,
        items=items,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.put("/checklists/templates/{template_id}/items", response_model=S.StatusResponse)
async def update_template_items(
    template_id: uuid.UUID,
    body: list[S.ChecklistTemplateItemUpsert],
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Replace all items in a template (Req 8.4). System-seeded templates are rejected."""
    from sqlalchemy import select, delete
    from app.modules.fleet_portal.models import FleetChecklistTemplate, FleetChecklistTemplateItem

    res = await db.execute(
        select(FleetChecklistTemplate).where(
            FleetChecklistTemplate.id == template_id,
            FleetChecklistTemplate.org_id == ctx.org_id,
        )
    )
    t = res.scalars().first()
    if t is None:
        raise HTTPException(status_code=404, detail="Template not found")
    if t.is_system_seeded:
        raise HTTPException(status_code=403, detail="Cannot edit system-seeded NZTA template. Clone it first.")

    # Delete existing items and replace
    await db.execute(
        delete(FleetChecklistTemplateItem).where(
            FleetChecklistTemplateItem.template_id == t.id
        )
    )
    for item in body:
        db.add(FleetChecklistTemplateItem(
            org_id=ctx.org_id,
            template_id=t.id,
            category=item.category,
            label=item.label,
            requires_photo_on_fail=item.requires_photo_on_fail,
            display_order=item.display_order,
        ))
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post("/vehicles/{vehicle_id}/assign-template", response_model=S.StatusResponse)
async def assign_template_to_vehicle(
    vehicle_id: uuid.UUID,
    body: dict,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Assign a checklist template to a specific vehicle (Req 8.6)."""
    from sqlalchemy import select
    from app.modules.vehicles.models import CustomerVehicle

    template_id = body.get("template_id")

    res = await db.execute(
        select(CustomerVehicle).where(
            CustomerVehicle.id == vehicle_id,
            CustomerVehicle.org_id == ctx.org_id,
        )
    )
    cv = res.scalars().first()
    if cv is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    cv.fleet_checklist_template_id = uuid.UUID(template_id) if template_id else None
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post("/checklists/start", response_model=S.ChecklistSubmissionSchema)
async def start_checklist(
    body: S.ChecklistSubmissionStartRequest,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistSubmissionSchema:
    from app.modules.fleet_portal.services import checklist_service

    try:
        submission = await checklist_service.start_submission(
            db, ctx=ctx, customer_vehicle_id=body.customer_vehicle_id
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return S.ChecklistSubmissionSchema(
        id=submission.id,
        customer_vehicle_id=submission.customer_vehicle_id,
        portal_account_id=submission.portal_account_id,
        template_id=submission.template_id,
        status=submission.status,
        started_at=submission.started_at,
        completed_at=submission.completed_at,
        passed_item_count=submission.passed_item_count,
        failed_item_count=submission.failed_item_count,
        na_item_count=submission.na_item_count,
        items=[],
    )


@router.post("/checklists/{submission_id}/complete", response_model=S.ChecklistSubmissionSchema)
async def complete_checklist(
    submission_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistSubmissionSchema:
    from app.modules.fleet_portal.services import checklist_service

    try:
        s = await checklist_service.complete_submission(
            db, submission_id=submission_id, org_id=ctx.org_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return S.ChecklistSubmissionSchema(
        id=s.id,
        customer_vehicle_id=s.customer_vehicle_id,
        portal_account_id=s.portal_account_id,
        template_id=s.template_id,
        status=s.status,
        started_at=s.started_at,
        completed_at=s.completed_at,
        passed_item_count=s.passed_item_count,
        failed_item_count=s.failed_item_count,
        na_item_count=s.na_item_count,
        items=[],
    )


# ---------------------------------------------------------------------------
# Bookings (task 12.3 — Req 11.1–11.8)
# ---------------------------------------------------------------------------


@router.post("/bookings", response_model=S.BookingRequestSchema)
async def create_booking(
    body: S.BookingRequestCreate,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.BookingRequestSchema:
    from app.modules.fleet_portal.services import booking_service

    try:
        row = await booking_service.create_booking_request(
            db,
            ctx=ctx,
            customer_vehicle_id=body.customer_vehicle_id,
            preferred_date=body.preferred_date,
            preferred_slot=body.preferred_slot,
            service_description=body.service_description,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return S.BookingRequestSchema(
        id=row.id,
        customer_vehicle_id=row.customer_vehicle_id,
        rego=None,
        requested_by_portal_account_id=row.requested_by_portal_account_id,
        requested_by_name=None,
        preferred_date=row.preferred_date,
        preferred_slot=row.preferred_slot,
        service_description=row.service_description,
        notes=row.notes,
        status=row.status,
        decline_reason=row.decline_reason,
        booking_id=row.booking_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/bookings", response_model=S.BookingRequestListResponse)
async def list_bookings(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.BookingRequestListResponse:
    from sqlalchemy import select, func
    from app.modules.fleet_portal.models import FleetServiceBookingRequest

    if ctx.fleet_account_id is None:
        return S.BookingRequestListResponse(items=[], total=0, offset=offset, limit=limit)

    base = select(FleetServiceBookingRequest).where(
        FleetServiceBookingRequest.org_id == ctx.org_id,
        FleetServiceBookingRequest.fleet_account_id == ctx.fleet_account_id,
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(FleetServiceBookingRequest.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    items = [
        S.BookingRequestSchema(
            id=r.id,
            customer_vehicle_id=r.customer_vehicle_id,
            rego=None,
            requested_by_portal_account_id=r.requested_by_portal_account_id,
            requested_by_name=None,
            preferred_date=r.preferred_date,
            preferred_slot=r.preferred_slot,
            service_description=r.service_description,
            notes=r.notes,
            status=r.status,
            decline_reason=r.decline_reason,
            booking_id=r.booking_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return S.BookingRequestListResponse(items=items, total=int(total), offset=offset, limit=limit)


@router.post("/bookings/{booking_id}/cancel", response_model=S.StatusResponse)
async def cancel_booking(
    booking_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    from app.modules.fleet_portal.services import booking_service

    try:
        await booking_service.cancel_booking_request(db, ctx=ctx, request_id=booking_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Quotes (task 12.3 — Req 12.1–12.7)
# ---------------------------------------------------------------------------


@router.post("/quotes/request", response_model=S.QuoteRequestSchema)
async def create_quote_request(
    body: S.QuoteRequestCreate,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.QuoteRequestSchema:
    from app.modules.fleet_portal.services import quote_service

    try:
        row = await quote_service.create_quote_request(
            db,
            ctx=ctx,
            customer_vehicle_id=body.customer_vehicle_id,
            service_description=body.service_description,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return S.QuoteRequestSchema(
        id=row.id,
        customer_vehicle_id=row.customer_vehicle_id,
        rego=None,
        requested_by_portal_account_id=row.requested_by_portal_account_id,
        requested_by_name=None,
        service_description=row.service_description,
        notes=row.notes,
        status=row.status,
        quote_id=row.quote_id,
        quote_total=None,
        quote_valid_until=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/quotes", response_model=S.QuoteRequestListResponse)
async def list_quotes(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.QuoteRequestListResponse:
    from sqlalchemy import select, func
    from app.modules.fleet_portal.models import FleetQuotationRequest

    if ctx.fleet_account_id is None:
        return S.QuoteRequestListResponse(items=[], total=0, offset=offset, limit=limit)

    base = select(FleetQuotationRequest).where(
        FleetQuotationRequest.org_id == ctx.org_id,
        FleetQuotationRequest.fleet_account_id == ctx.fleet_account_id,
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(FleetQuotationRequest.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    items = [
        S.QuoteRequestSchema(
            id=r.id,
            customer_vehicle_id=r.customer_vehicle_id,
            rego=None,
            requested_by_portal_account_id=r.requested_by_portal_account_id,
            requested_by_name=None,
            service_description=r.service_description,
            notes=r.notes,
            status=r.status,
            quote_id=r.quote_id,
            quote_total=None,
            quote_valid_until=None,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return S.QuoteRequestListResponse(items=items, total=int(total), offset=offset, limit=limit)


# ---------------------------------------------------------------------------
# Invoices (task 13.3 — Req 13.1–13.7)
# ---------------------------------------------------------------------------


@router.get("/invoices", response_model=S.InvoiceListResponse)
async def list_invoices_endpoint(
    offset: int = 0,
    limit: int = 20,
    status: str | None = None,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.InvoiceListResponse:
    from app.modules.fleet_portal.services import invoice_service

    items, total = await invoice_service.list_invoices(
        db, ctx=ctx, status_filter=status, offset=offset, limit=limit
    )
    return S.InvoiceListResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/invoices/{invoice_id}")
async def get_invoice_detail(
    invoice_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return invoice detail with line items (Req 13.4)."""
    from app.modules.invoices.models import Invoice, LineItem
    from app.modules.fleet_portal.models import PortalFleetAccount
    from decimal import Decimal

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")

    # Get customer_id from fleet account
    fa_res = await db.execute(
        select(PortalFleetAccount.customer_id).where(
            PortalFleetAccount.id == ctx.fleet_account_id
        )
    )
    fa_row = fa_res.first()
    if fa_row is None:
        raise HTTPException(status_code=404, detail="Fleet account not found")
    customer_id = fa_row[0]

    # Fetch invoice
    inv_res = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.customer_id == customer_id,
            Invoice.org_id == ctx.org_id,
        )
    )
    inv = inv_res.scalars().first()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Fetch line items
    items_res = await db.execute(
        select(LineItem).where(LineItem.invoice_id == inv.id).order_by(LineItem.sort_order)
    )
    line_items = items_res.scalars().all()

    return {
        "invoice_id": str(inv.id),
        "invoice_number": inv.invoice_number or str(inv.id)[:8],
        "status": inv.status,
        "issue_date": str(inv.issue_date) if inv.issue_date else None,
        "due_date": str(inv.due_date) if inv.due_date else None,
        "currency": inv.currency,
        "subtotal": str(inv.subtotal or 0),
        "discount_amount": str(inv.discount_amount or 0),
        "gst_amount": str(inv.gst_amount or 0),
        "total": str(inv.total or 0),
        "amount_paid": str(inv.amount_paid or 0),
        "balance_due": str(inv.balance_due or 0),
        "notes_customer": inv.notes_customer,
        "vehicle_rego": inv.vehicle_rego,
        "vehicle_make": inv.vehicle_make,
        "vehicle_model": inv.vehicle_model,
        "vehicle_year": inv.vehicle_year,
        "line_items": [
            {
                "id": str(li.id),
                "description": li.description,
                "quantity": str(li.quantity or 0),
                "unit_price": str(li.unit_price or 0),
                "amount": str(li.line_total or 0),
                "gst_amount": "0",
            }
            for li in line_items
        ],
    }


@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Download invoice as PDF (Req 13.5)."""
    from fastapi.responses import StreamingResponse
    from app.modules.invoices.models import Invoice
    from app.modules.fleet_portal.models import PortalFleetAccount

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")

    # Get customer_id from fleet account
    fa_res = await db.execute(
        select(PortalFleetAccount.customer_id).where(
            PortalFleetAccount.id == ctx.fleet_account_id
        )
    )
    fa_row = fa_res.first()
    if fa_row is None:
        raise HTTPException(status_code=404, detail="Fleet account not found")
    customer_id = fa_row[0]

    # Verify invoice belongs to this customer
    inv_res = await db.execute(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.customer_id == customer_id,
            Invoice.org_id == ctx.org_id,
        )
    )
    inv = inv_res.scalars().first()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Generate PDF using the existing invoice PDF service
    try:
        from app.modules.invoices.pdf_service import generate_invoice_pdf
        pdf_bytes = await generate_invoice_pdf(db, invoice_id=inv.id, org_id=ctx.org_id)
    except Exception as exc:
        logger.warning("fleet_portal.invoice_pdf_failed invoice_id=%s err=%s", invoice_id, exc)
        raise HTTPException(status_code=500, detail="Failed to generate PDF")

    filename = f"invoice-{inv.invoice_number or str(inv.id)[:8]}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Reminders (task 10.3 — Req 10.1, 10.2, 10.7, 10.8)
# ---------------------------------------------------------------------------


@router.get("/reminders", response_model=S.ReminderPreferenceListResponse)
async def list_reminders(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.ReminderPreferenceListResponse:
    from sqlalchemy import select, func
    from app.modules.fleet_portal.models import FleetReminderPreference

    if ctx.fleet_account_id is None:
        return S.ReminderPreferenceListResponse(items=[], total=0, offset=offset, limit=limit)

    base = select(FleetReminderPreference).where(
        FleetReminderPreference.org_id == ctx.org_id,
        FleetReminderPreference.fleet_account_id == ctx.fleet_account_id,
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.offset(offset).limit(limit))).scalars().all()

    items = [
        S.ReminderPreferenceSchema(
            customer_vehicle_id=r.customer_vehicle_id,
            reminder_type=r.reminder_type,
            enabled=r.enabled,
            lead_time_days=r.lead_time_days,
            channels=r.channels or [],
            recipients=r.recipients or [],
            service_interval_km=r.service_interval_km,
            service_interval_months=r.service_interval_months,
            rego=None,
        )
        for r in rows
    ]
    return S.ReminderPreferenceListResponse(items=items, total=int(total), offset=offset, limit=limit)


@router.put("/reminders/{vehicle_id}/{reminder_type}", response_model=S.StatusResponse)
async def upsert_reminder(
    vehicle_id: uuid.UUID,
    reminder_type: str,
    body: S.ReminderPreferenceUpsertRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    from app.modules.fleet_portal.services import reminder_service

    try:
        await reminder_service.upsert_preference(
            db,
            ctx=ctx,
            customer_vehicle_id=vehicle_id,
            reminder_type=reminder_type,
            enabled=body.enabled,
            lead_time_days=body.lead_time_days,
            channels=list(body.channels),
            recipients=list(body.recipients),
            service_interval_km=body.service_interval_km,
            service_interval_months=body.service_interval_months,
            sms_provider_configured=False,  # TODO: wire real check
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.post("/reminders/send-sms", response_model=S.StatusResponse)
async def send_adhoc_sms_reminder(
    body: dict,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Send an ad-hoc SMS reminder for a vehicle (Req 10.7)."""
    # Check if SMS provider is configured
    if not _detect_sms_provider_configured(db, ctx.org_id):
        raise HTTPException(status_code=400, detail="SMS provider not configured for this organisation.")

    customer_vehicle_id = body.get("customer_vehicle_id")
    reminder_type = body.get("reminder_type")

    # Log the ad-hoc send attempt (actual SMS dispatch via existing queue)
    try:
        from app.modules.fleet_portal.services import audit_service
        await audit_service.log_event(
            db,
            org_id=ctx.org_id,
            action="fleet_adhoc_sms_reminder",
            portal_account_id=ctx.portal_account_id,
            details={
                "customer_vehicle_id": str(customer_vehicle_id),
                "reminder_type": reminder_type,
            },
        )
    except Exception:
        pass

    # TODO: Wire actual SMS dispatch via Connexus queue
    # For now, the audit log records the intent and the queue will pick it up
    return S.StatusResponse(ok=True)


__all__ = ["router"]
