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
from pydantic import EmailStr, Field
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

    sms_configured = await _detect_sms_provider_configured(db)

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


async def _detect_sms_provider_configured(db: AsyncSession) -> bool:
    """Return True iff there is an active Connexus SMS provider configured.

    Looks up ``sms_verification_providers`` with
    ``provider_key='connexus' AND is_active=true`` (the canonical store
    used by ``app/integrations/connexus_sms.py``). Returns ``False`` on
    any error so the UI is safe by default.
    """
    try:
        from sqlalchemy import select as _select
        from app.modules.admin.models import SmsVerificationProvider

        res = await db.execute(
            _select(SmsVerificationProvider.id).where(
                SmsVerificationProvider.provider_key == "connexus",
                SmsVerificationProvider.is_active.is_(True),
            ).limit(1)
        )
        return res.first() is not None
    except Exception:
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
    from app.modules.fleet_portal.models import FleetChecklistSubmissionItem
    from sqlalchemy import select

    try:
        submission = await checklist_service.start_submission(
            db, ctx=ctx, customer_vehicle_id=body.customer_vehicle_id
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Load the submission's items (snapshotted from template at start)
    items_res = await db.execute(
        select(FleetChecklistSubmissionItem)
        .where(FleetChecklistSubmissionItem.submission_id == submission.id)
        .order_by(FleetChecklistSubmissionItem.id)
    )
    items = [
        S.ChecklistSubmissionItemSchema(
            id=i.id,
            template_item_id=i.template_item_id,
            category=i.category,
            label=i.label,
            requires_photo_on_fail=i.requires_photo_on_fail,
            result=i.result,
            notes=i.notes,
            photo_urls=i.photo_urls or [],
            recorded_at=i.recorded_at,
        )
        for i in items_res.scalars().all()
    ]

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
        items=items,
    )


# Submission list + detail + item update + photo upload (Req 9.2–9.5, 9.8, 9.9)


@router.get("/checklists/submissions", response_model=S.ChecklistSubmissionListResponse)
async def list_submissions(
    offset: int = 0,
    limit: int = 50,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistSubmissionListResponse:
    """List submissions visible to the current session.

    Drivers see only their own submissions; admins see all in the fleet.
    Implements Req 9.8, 9.9.
    """
    from sqlalchemy import select, func
    from app.modules.fleet_portal.models import FleetChecklistSubmission

    if ctx.fleet_account_id is None:
        return S.ChecklistSubmissionListResponse(items=[], total=0, offset=offset, limit=limit)

    base = select(FleetChecklistSubmission).where(
        FleetChecklistSubmission.org_id == ctx.org_id,
        FleetChecklistSubmission.fleet_account_id == ctx.fleet_account_id,
    )
    if ctx.portal_user_role == "driver":
        base = base.where(FleetChecklistSubmission.portal_account_id == ctx.portal_account_id)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            base.order_by(FleetChecklistSubmission.started_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()

    items = [
        S.ChecklistSubmissionSchema(
            id=s.id,
            customer_vehicle_id=s.customer_vehicle_id,
            portal_account_id=s.portal_account_id,
            template_id=s.template_id,
            status=s.status,
            started_at=s.started_at,
            completed_at=s.completed_at,
            passed_item_count=s.passed_item_count or 0,
            failed_item_count=s.failed_item_count or 0,
            na_item_count=s.na_item_count or 0,
            items=[],  # items loaded only on detail view
        )
        for s in rows
    ]
    return S.ChecklistSubmissionListResponse(items=items, total=int(total), offset=offset, limit=limit)


@router.get(
    "/checklists/submissions/{submission_id}", response_model=S.ChecklistSubmissionSchema
)
async def get_submission_detail(
    submission_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
) -> S.ChecklistSubmissionSchema:
    """Return submission detail with all items.

    Drivers can only see their own submissions (403 otherwise).
    """
    from sqlalchemy import select
    from app.modules.fleet_portal.models import (
        FleetChecklistSubmission,
        FleetChecklistSubmissionItem,
    )

    res = await db.execute(
        select(FleetChecklistSubmission).where(
            FleetChecklistSubmission.id == submission_id,
            FleetChecklistSubmission.org_id == ctx.org_id,
        )
    )
    s = res.scalars().first()
    if s is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    if ctx.portal_user_role == "driver" and s.portal_account_id != ctx.portal_account_id:
        raise HTTPException(status_code=403, detail="Cannot access another driver's submission")

    items_res = await db.execute(
        select(FleetChecklistSubmissionItem)
        .where(FleetChecklistSubmissionItem.submission_id == s.id)
        .order_by(FleetChecklistSubmissionItem.id)
    )
    items = [
        S.ChecklistSubmissionItemSchema(
            id=i.id,
            template_item_id=i.template_item_id,
            category=i.category,
            label=i.label,
            requires_photo_on_fail=i.requires_photo_on_fail,
            result=i.result,
            notes=i.notes,
            photo_urls=i.photo_urls or [],
            recorded_at=i.recorded_at,
        )
        for i in items_res.scalars().all()
    ]

    return S.ChecklistSubmissionSchema(
        id=s.id,
        customer_vehicle_id=s.customer_vehicle_id,
        portal_account_id=s.portal_account_id,
        template_id=s.template_id,
        status=s.status,
        started_at=s.started_at,
        completed_at=s.completed_at,
        passed_item_count=s.passed_item_count or 0,
        failed_item_count=s.failed_item_count or 0,
        na_item_count=s.na_item_count or 0,
        items=items,
    )


class _ItemResultUpdate(S._StrictBase):
    result: str  # 'pass' | 'fail' | 'na'
    notes: str | None = None


@router.patch(
    "/checklists/{submission_id}/items/{item_id}", response_model=S.StatusResponse
)
async def update_submission_item(
    submission_id: uuid.UUID,
    item_id: uuid.UUID,
    body: _ItemResultUpdate,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Update a single submission item (set result, optional notes)."""
    from sqlalchemy import select
    from datetime import datetime, timezone
    from app.modules.fleet_portal.models import (
        FleetChecklistSubmission,
        FleetChecklistSubmissionItem,
    )

    if body.result not in {"pass", "fail", "na"}:
        raise HTTPException(status_code=400, detail="result must be one of: pass, fail, na")

    sub_res = await db.execute(
        select(FleetChecklistSubmission).where(
            FleetChecklistSubmission.id == submission_id,
            FleetChecklistSubmission.org_id == ctx.org_id,
        )
    )
    s = sub_res.scalars().first()
    if s is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if s.status != "in_progress":
        raise HTTPException(status_code=400, detail="Submission is no longer editable")
    if ctx.portal_user_role == "driver" and s.portal_account_id != ctx.portal_account_id:
        raise HTTPException(status_code=403, detail="Cannot edit another driver's submission")

    item_res = await db.execute(
        select(FleetChecklistSubmissionItem).where(
            FleetChecklistSubmissionItem.id == item_id,
            FleetChecklistSubmissionItem.submission_id == submission_id,
        )
    )
    item = item_res.scalars().first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    item.result = body.result
    item.notes = body.notes
    item.recorded_at = datetime.now(timezone.utc)
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post(
    "/checklists/{submission_id}/items/{item_id}/photo",
    response_model=S.StatusResponse,
)
async def upload_submission_photo(
    submission_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """Attach a photo to a submission item.

    Stored as a base64 data-URL in `photo_urls` JSONB. Max 5MB per photo,
    accepts JPEG/PNG/WebP. CSRF is validated manually since multipart
    bodies don't go through the JSON middleware path.
    """
    import base64
    from fastapi import UploadFile, File
    from sqlalchemy import select
    from app.modules.fleet_portal.models import (
        FleetChecklistSubmission,
        FleetChecklistSubmissionItem,
    )

    # Manual CSRF check (multipart bypasses validate_fleet_portal_csrf)
    cookie = request.cookies.get("fleet_portal_csrf")
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or cookie != header:
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="No file uploaded")

    # Read and validate
    content = await upload.read()  # type: ignore[union-attr]
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")

    mime = getattr(upload, "content_type", None) or "application/octet-stream"
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail=f"Invalid image type: {mime}")

    # Verify submission + item ownership
    sub_res = await db.execute(
        select(FleetChecklistSubmission).where(
            FleetChecklistSubmission.id == submission_id,
            FleetChecklistSubmission.org_id == ctx.org_id,
        )
    )
    s = sub_res.scalars().first()
    if s is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if s.status != "in_progress":
        raise HTTPException(status_code=400, detail="Submission is no longer editable")
    if ctx.portal_user_role == "driver" and s.portal_account_id != ctx.portal_account_id:
        raise HTTPException(status_code=403, detail="Cannot edit another driver's submission")

    item_res = await db.execute(
        select(FleetChecklistSubmissionItem).where(
            FleetChecklistSubmissionItem.id == item_id,
            FleetChecklistSubmissionItem.submission_id == submission_id,
        )
    )
    item = item_res.scalars().first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    # Encode as data URL and append
    data_url = f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
    existing = list(item.photo_urls or [])
    existing.append(data_url)
    item.photo_urls = existing
    await db.flush()
    return S.StatusResponse(ok=True)


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
    from app.modules.quotes.models import Quote

    if ctx.fleet_account_id is None:
        return S.QuoteRequestListResponse(items=[], total=0, offset=offset, limit=limit)

    base = select(FleetQuotationRequest).where(
        FleetQuotationRequest.org_id == ctx.org_id,
        FleetQuotationRequest.fleet_account_id == ctx.fleet_account_id,
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(FleetQuotationRequest.created_at.desc()).offset(offset).limit(limit))).scalars().all()

    # Resolve linked quotes (total + valid_until) in a single batch query
    linked_quote_ids = [r.quote_id for r in rows if r.quote_id is not None]
    quotes_by_id: dict = {}
    if linked_quote_ids:
        q_res = await db.execute(
            select(Quote).where(
                Quote.id.in_(linked_quote_ids),
                Quote.org_id == ctx.org_id,
            )
        )
        for q in q_res.scalars().all():
            quotes_by_id[q.id] = q

    items = []
    for r in rows:
        linked = quotes_by_id.get(r.quote_id) if r.quote_id else None
        items.append(
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
                quote_total=linked.total if linked is not None else None,
                quote_valid_until=linked.valid_until if linked is not None else None,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )
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
    if not await _detect_sms_provider_configured(db):
        raise HTTPException(status_code=400, detail="SMS provider not configured for this organisation.")

    customer_vehicle_id = body.get("customer_vehicle_id")
    reminder_type = body.get("reminder_type")
    custom_message = (body.get("message") or "").strip() or None

    # Audit-log the intent regardless of dispatch outcome
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

    # Best-effort dispatch via Connexus. The Connexus integration loads
    # its own credentials and recipients aren't auto-derived here — for
    # the MVP we accept the request and rely on the existing reminder
    # queue to do the actual sending. An explicit dispatch from this
    # endpoint requires resolving the recipient phone numbers which is
    # owned by reminder_service; we delegate there if available.
    try:
        from app.modules.fleet_portal.services import reminder_service
        send_now = getattr(reminder_service, "send_ad_hoc_sms", None)
        if send_now is not None and customer_vehicle_id and reminder_type:
            await send_now(
                db,
                ctx=ctx,
                customer_vehicle_id=uuid.UUID(str(customer_vehicle_id)),
                reminder_type=str(reminder_type),
                message=custom_message,
            )
    except Exception as exc:
        logger.warning("fleet_portal.send_sms.dispatch_failed err=%s", exc)
        # Still return ok=True — the audit log captures intent and the
        # queue will retry. Failing the click is worse UX than a silent
        # retry given that the dispatcher itself is best-effort.

    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Vehicle add / remove / edit (Req 6.5, 6.6, 6.7)
# ---------------------------------------------------------------------------


class _VehicleAddRequest(S._StrictBase):
    rego: str
    odometer_at_link: int | None = None


@router.post("/vehicles", response_model=S.IdResponse)
async def add_vehicle_to_fleet(
    body: _VehicleAddRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.IdResponse:
    """Add a vehicle to the current fleet (Req 6.5).

    Strategy: look up the rego in ``global_vehicles``; if a row exists,
    promote it for the calling org via :func:`promote_vehicle` and link
    via ``org_vehicle_id`` (vehicle-data-isolation Task 7.1). Otherwise
    create an ``org_vehicles`` row directly with ``is_manual_entry=True``
    and link that — the manual-entry path is born org-scoped and bypasses
    promotion (vehicle-data-isolation design, B2B Fleet Portal Impact).
    Either way, the ``customer_vehicles`` link is keyed to the fleet
    account's ``customer_id`` so RLS and join paths agree.

    Per the vehicle-data-isolation spec (Task 7.1), when a
    ``GlobalVehicle`` row resolves for the supplied rego we must:

    1. Call :func:`promote_vehicle` first so the per-org snapshot
       (``org_vehicles``) is created/found before any link is built.
    2. **Rebind ``gv = None`` and ``ov = <returned>``** before both the
       link-existence query and the ``CustomerVehicle(...)`` constructor.
       Without the rebind, the existence query would still filter on
       ``CustomerVehicle.global_vehicle_id == gv.id`` (the original gv
       id) and the constructor would still pass ``global_vehicle_id=
       gv.id``, atomically undoing the promotion at link-create time.
       This is the same rebind discipline as Task 4.1 (invoices) and
       Task 6.2 (fleet-portal edit_vehicle).
    """
    from sqlalchemy import (
        and_ as _and_,
        func as _func,
        or_ as _or_,
        select as _select,
    )
    from app.modules.admin.models import GlobalVehicle
    from app.modules.vehicles.models import (
        CustomerVehicle,
        OrgVehicle,
    )
    from app.modules.vehicles.service import promote_vehicle
    from app.modules.fleet_portal.models import (
        FleetReminderPreference,
        PortalFleetAccount,
    )

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")

    rego = (body.rego or "").strip().upper()
    if not rego:
        raise HTTPException(status_code=400, detail="Rego is required")

    # Resolve the fleet's customer_id
    fa_res = await db.execute(
        _select(PortalFleetAccount.customer_id).where(
            PortalFleetAccount.id == ctx.fleet_account_id
        )
    )
    fa_row = fa_res.first()
    if fa_row is None:
        raise HTTPException(status_code=404, detail="Fleet account not found")
    customer_id = fa_row[0]

    # Try GlobalVehicle first (CarJam-sourced). When a ``global_vehicles``
    # row exists for this rego, the calling org needs its own per-org
    # snapshot before we link — otherwise the resulting
    # ``customer_vehicles`` row would point at the cross-tenant cache and
    # any subsequent customer-driven write would leak into other orgs'
    # views (Req 1.4, 7.2). The same code path serves both the admin-link
    # workflow (admin selects an existing CarJam-cached rego) and the
    # CarJam-import workflow (frontend calls ``/api/v1/vehicles/lookup``
    # to populate ``global_vehicles`` immediately before this endpoint).
    gv_res = await db.execute(
        _select(GlobalVehicle).where(GlobalVehicle.rego == rego).limit(1)
    )
    gv = gv_res.scalars().first()

    ov: OrgVehicle | None = None
    if gv is not None:
        # Promote the rego for the calling org BEFORE any link query or
        # constructor sees the original gv reference (vehicle-data-
        # isolation Task 7.1). ``promote_vehicle`` is idempotent — if the
        # org already has an ``org_vehicles`` row for this rego (e.g. via
        # a prior promotion through invoices/kiosk/fleet-portal edit) it
        # returns that existing row.
        ov = await promote_vehicle(
            db,
            org_id=ctx.org_id,
            global_vehicle_id=gv.id,
            source_record=gv,
            user_id=ctx.portal_account_id,
            trigger_site="fleet_portal.admin_link",
        )
        # Rebind so the link-existence query and the ``CustomerVehicle``
        # constructor below operate on the post-promotion identity. This
        # is the discipline called out in the spec's "Implementation
        # Note — Local Variable Rebinding": failing to clear ``gv`` here
        # would silently re-link via ``global_vehicle_id`` and undo the
        # promotion atomically with the create.
        gv = None
    else:
        # No CarJam-sourced row for this rego — fall through to the
        # manual-entry path, which is born org-scoped and does not need
        # promotion (the row is already in ``org_vehicles``).
        ov_res = await db.execute(
            _select(OrgVehicle).where(
                OrgVehicle.org_id == ctx.org_id,
                OrgVehicle.rego == rego,
            ).limit(1)
        )
        ov = ov_res.scalars().first()
        if ov is None:
            ov = OrgVehicle(
                org_id=ctx.org_id,
                rego=rego,
                odometer_last_recorded=body.odometer_at_link,
                is_manual_entry=True,
            )
            db.add(ov)
            await db.flush()
            await db.refresh(ov)

    # Refuse to double-link the same vehicle to the same customer.
    # vehicle-data-isolation Task 11.7: widened, rego-keyed existence
    # check that catches legacy ``global_vehicle_id``-keyed links from
    # pre-promotion plus the post-promotion ``org_vehicle_id`` link, so
    # an admin attempting to add an already-promoted-elsewhere vehicle
    # to the fleet is rejected with HTTP 409 rather than creating a
    # duplicate ``customer_vehicles`` row (Req 3.4, 9.6, 13.3). Both
    # ``GlobalVehicle.rego`` (case-insensitive) and ``OrgVehicle.rego``
    # for the calling org are matched.
    existing_link_q = (
        _select(CustomerVehicle)
        .outerjoin(
            GlobalVehicle,
            CustomerVehicle.global_vehicle_id == GlobalVehicle.id,
        )
        .outerjoin(
            OrgVehicle,
            CustomerVehicle.org_vehicle_id == OrgVehicle.id,
        )
        .where(
            CustomerVehicle.org_id == ctx.org_id,
            CustomerVehicle.customer_id == customer_id,
            _or_(
                _func.upper(GlobalVehicle.rego) == rego,
                _and_(
                    OrgVehicle.org_id == ctx.org_id,
                    _func.upper(OrgVehicle.rego) == rego,
                ),
            ),
        )
        .limit(1)
    )
    existing_link = (await db.execute(existing_link_q)).scalars().first()
    if existing_link is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Vehicle {rego} is already in your fleet",
        )

    cv = CustomerVehicle(
        org_id=ctx.org_id,
        customer_id=customer_id,
        global_vehicle_id=gv.id if gv is not None else None,
        org_vehicle_id=ov.id if ov is not None else None,
        odometer_at_link=body.odometer_at_link,
    )
    db.add(cv)
    await db.flush()
    await db.refresh(cv)

    # Seed the three default reminder preferences (disabled — Req 10.9)
    for reminder_type in (
        "wof_expiry_reminder",
        "cof_expiry_reminder",
        "service_due_reminder",
    ):
        db.add(
            FleetReminderPreference(
                org_id=ctx.org_id,
                fleet_account_id=ctx.fleet_account_id,
                customer_vehicle_id=cv.id,
                reminder_type=reminder_type,
                enabled=False,
                lead_time_days=14,
                channels=["email"],
                recipients=["fleet_admin"],
            )
        )
    await db.flush()

    return S.IdResponse(id=cv.id)


@router.patch("/vehicles/{vehicle_id}", response_model=S.StatusResponse)
async def edit_vehicle(
    vehicle_id: uuid.UUID,
    body: S.VehicleEditRequest,
    ctx: FleetSessionCtx = Depends(require_driver_or_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Update editable fields on a vehicle (Req 6.6, 7.2/7.3/7.4).

    Per-role allowlist enforced via
    ``vehicle_service.allowed_fields_for_role``. Unknown or disallowed
    field names return HTTP 403.

    Per the vehicle-data-isolation spec (Task 6.2): when the resolved
    target is the shared ``global_vehicles`` row and the payload writes
    any Customer_Driven_Field (``odometer_last_recorded``,
    ``service_due_date``, ``wof_expiry``, ``cof_expiry``,
    ``inspection_type``), the vehicle is promoted for the calling org
    via :func:`promote_vehicle` and the local ``target`` reference is
    rebound to the new ``OrgVehicle`` BEFORE the ``setattr`` loop runs.
    Without the rebind, the loop would still write to
    ``cv.global_vehicle`` and one org's operational state would leak
    into the cross-tenant cache (Req 1.4, 3.5, 7.1, 7.4).
    """
    from sqlalchemy import select as _select
    from app.modules.admin.models import GlobalVehicle
    from app.modules.fleet_portal.services.vehicle_service import (
        _vehicle_query_for_session,
        allowed_fields_for_role,
    )
    from app.modules.vehicles.models import CustomerVehicle
    from app.modules.vehicles.service import (
        migrate_link_to_org_vehicle,
        promote_vehicle,
    )

    # Customer_Driven_Fields per the vehicle-data-isolation spec — when
    # any of these is in the payload AND the resolved target is the
    # shared ``global_vehicles`` row, we MUST promote the vehicle for
    # the calling org first so the writes land on the per-org snapshot
    # (Req 1.4, 3.5, 7.1, 7.4). Same five fields enumerated by every
    # other promotion trigger site in the spec.
    _CUSTOMER_DRIVEN_FIELDS: frozenset[str] = frozenset(
        {
            "odometer_last_recorded",
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        }
    )

    base = await _vehicle_query_for_session(db, ctx)
    cv = (
        await db.execute(base.where(CustomerVehicle.id == vehicle_id))
    ).scalars().first()
    if cv is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    payload = body.model_dump(exclude_unset=True)
    allowed = allowed_fields_for_role(ctx.portal_user_role)
    bad = [k for k in payload.keys() if k not in allowed]
    if bad:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot edit field(s) for role={ctx.portal_user_role}: {', '.join(bad)}",
        )

    # Apply per-vehicle override field directly on customer_vehicles
    if "fleet_checklist_template_id" in payload:
        cv.fleet_checklist_template_id = payload.pop("fleet_checklist_template_id")

    # All other fields land on the underlying global_vehicles or
    # org_vehicles row (we don't own a fleet-scoped overlay table).
    target = cv.global_vehicle if cv.global_vehicle is not None else cv.org_vehicle
    if target is None:
        await db.flush()
        return S.StatusResponse(ok=True)

    # Promotion gate (Task 6.2): if the resolved target is a
    # ``GlobalVehicle`` and the payload would write any
    # Customer_Driven_Field, promote the vehicle for the calling org
    # FIRST and then **rebind ``target`` to the new ``OrgVehicle``**
    # before the ``setattr`` loop runs. Without the rebind, ``setattr``
    # writes still target ``cv.global_vehicle`` because ``cv`` was
    # loaded earlier in the function and the relationship attribute
    # still points at the ``GlobalVehicle`` — that would silently leak
    # one org's odometer/WOF/COF/service-due/inspection-type values to
    # every other org sharing the same ``global_vehicles`` row.
    #
    # The same loop can write 1..N fields, each of which would
    # individually leak; promotion + rebind protects all of them.
    if isinstance(target, GlobalVehicle) and any(
        k in _CUSTOMER_DRIVEN_FIELDS for k in payload.keys()
    ):
        gv = target
        ov = await promote_vehicle(
            db,
            org_id=ctx.org_id,
            global_vehicle_id=gv.id,
            source_record=gv,
            user_id=ctx.portal_account_id,
            trigger_site="fleet_portal.update_field",
        )
        # Rebind so the setattr loop below writes to ``org_vehicles``,
        # not the shared ``global_vehicles`` cache.
        target = ov
        # Migrate the customer_vehicles link if it still points at the
        # ``global_vehicle_id`` so subsequent reads/edits resolve the
        # per-org snapshot natively.
        if cv.global_vehicle_id is not None and cv.org_vehicle_id is None:
            await migrate_link_to_org_vehicle(
                db,
                customer_vehicle_id=cv.id,
                org_vehicle_id=ov.id,
            )

    for key, value in payload.items():
        # Some fields (fleet_internal_name, fleet_number) only exist on
        # OrgVehicle in the current schema — skip silently if absent.
        if hasattr(target, key):
            setattr(target, key, value)

    await db.flush()
    return S.StatusResponse(ok=True)


@router.delete("/vehicles/{vehicle_id}", response_model=S.StatusResponse)
async def remove_vehicle_from_fleet(
    vehicle_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Remove a vehicle from the fleet (Req 6.7).

    Deletes the ``customer_vehicles`` link only — the underlying
    ``global_vehicles`` / ``org_vehicles`` row is kept since other
    customers may share it. Submissions, reminder prefs, and driver
    assignments cascade-delete via FK.
    """
    from sqlalchemy import delete as _delete, select as _select
    from app.modules.vehicles.models import CustomerVehicle

    res = await db.execute(
        _select(CustomerVehicle).where(
            CustomerVehicle.id == vehicle_id,
            CustomerVehicle.org_id == ctx.org_id,
        )
    )
    cv = res.scalars().first()
    if cv is None:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    await db.execute(
        _delete(CustomerVehicle).where(CustomerVehicle.id == vehicle_id)
    )
    await db.flush()
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Quote accept / decline (Req 12.5, 12.6)
# ---------------------------------------------------------------------------


@router.post("/quotes/{request_id}/accept", response_model=S.StatusResponse)
async def accept_quote_request(
    request_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Fleet admin accepts a quoted quote request (Req 12.5)."""
    from sqlalchemy import select as _select
    from app.modules.fleet_portal.models import FleetQuotationRequest
    from app.modules.fleet_portal.services.quote_service import can_transition

    res = await db.execute(
        _select(FleetQuotationRequest).where(
            FleetQuotationRequest.id == request_id,
            FleetQuotationRequest.org_id == ctx.org_id,
            FleetQuotationRequest.fleet_account_id == ctx.fleet_account_id,
        )
    )
    row = res.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Quote request not found")
    if not can_transition(row.status, "accepted"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot accept quote in status={row.status}",
        )
    row.status = "accepted"
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post("/quotes/{request_id}/decline", response_model=S.StatusResponse)
async def decline_quote_request(
    request_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Fleet admin declines a quoted quote request (Req 12.6)."""
    from sqlalchemy import select as _select
    from app.modules.fleet_portal.models import FleetQuotationRequest
    from app.modules.fleet_portal.services.quote_service import can_transition

    res = await db.execute(
        _select(FleetQuotationRequest).where(
            FleetQuotationRequest.id == request_id,
            FleetQuotationRequest.org_id == ctx.org_id,
            FleetQuotationRequest.fleet_account_id == ctx.fleet_account_id,
        )
    )
    row = res.scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Quote request not found")
    if not can_transition(row.status, "declined"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot decline quote in status={row.status}",
        )
    row.status = "declined"
    await db.flush()
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Change password (Req 3.12, 21.16)
# ---------------------------------------------------------------------------


class _ChangePasswordRequest(S._StrictBase):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)


@router.post("/auth/change-password", response_model=S.StatusResponse)
async def change_password(
    body: _ChangePasswordRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Change the current portal user's password while signed in.

    Verifies the current password, applies the same password rules used
    elsewhere (Property 7 — length plus not equal to email local-part),
    updates the bcrypt hash, and clears the must_change_password flag.
    """
    from sqlalchemy import select as _select

    res = await db.execute(
        _select(PortalAccount).where(PortalAccount.id == ctx.portal_account_id)
    )
    account = res.scalars().first()
    if account is None or not account.password_hash:
        raise HTTPException(status_code=404, detail="Account not found")

    if not fp_auth.verify_password(body.current_password, account.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=400, detail="New password must differ from the current password"
        )

    # Apply Property 7 password rules
    try:
        fp_auth.validate_password_rules(body.new_password, account.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from datetime import datetime as _dt, timezone as _tz
    account.password_hash = fp_auth.hash_password(body.new_password)
    account.password_changed_at = _dt.now(_tz.utc)
    account.must_change_password = False
    await db.flush()
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# MFA enrolment endpoints (Req 21.10) — wires existing mfa_service
# ---------------------------------------------------------------------------


class _TotpStartResponse(S._ResponseBase):
    secret: str
    provisioning_uri: str


class _TotpConfirmRequest(S._StrictBase):
    secret: str
    code: str = Field(..., min_length=6, max_length=6)


class _MfaMethodResponse(S._ResponseBase):
    id: uuid.UUID
    method: str
    verified: bool
    is_default: bool = False


@router.get("/auth/mfa/methods")
async def list_my_mfa_methods(
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    db: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """List the current user's enrolled MFA methods (Req 21.10)."""
    from app.modules.fleet_portal.services import mfa_service

    methods = await mfa_service.list_mfa_methods(
        db, portal_account_id=ctx.portal_account_id
    )
    return [
        {
            "id": str(m.id),
            "method": m.method,
            "verified": m.verified,
            "is_default": m.is_default,
        }
        for m in methods
    ]


@router.post("/auth/mfa/enroll/totp/start", response_model=_TotpStartResponse)
async def start_totp_enrol(
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> _TotpStartResponse:
    """Begin TOTP enrolment — returns secret + otpauth URI (Req 21.10)."""
    from app.modules.fleet_portal.services import mfa_service

    out = await mfa_service.start_totp_enrolment(
        db,
        org_id=ctx.org_id,
        portal_account_id=ctx.portal_account_id,
        email=ctx.email,
    )
    return _TotpStartResponse(
        secret=out["secret"], provisioning_uri=out["provisioning_uri"]
    )


@router.post("/auth/mfa/enroll/totp/confirm", response_model=S.StatusResponse)
async def confirm_totp_enrol(
    body: _TotpConfirmRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Confirm TOTP enrolment by verifying the first 6-digit code."""
    from app.modules.fleet_portal.services import mfa_service

    try:
        await mfa_service.confirm_totp_enrolment(
            db,
            org_id=ctx.org_id,
            portal_account_id=ctx.portal_account_id,
            secret=body.secret,
            code=body.code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return S.StatusResponse(ok=True)


@router.delete("/auth/mfa/{method_id}", response_model=S.StatusResponse)
async def remove_my_mfa_method(
    method_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Remove one of the current user's MFA methods (Req 21.10)."""
    from app.modules.fleet_portal.services import mfa_service

    ok = await mfa_service.remove_mfa_method(
        db, portal_account_id=ctx.portal_account_id, method_id=method_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="MFA method not found")
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Driver assignments — list + reactivate + edit (Req 5.5/5.6 + missing edits)
# ---------------------------------------------------------------------------


@router.get("/drivers/{driver_id}/assignments")
async def list_driver_assignments(
    driver_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Return the set of customer_vehicle_ids currently assigned to a driver."""
    from sqlalchemy import select as _select
    from app.modules.fleet_portal.models import FleetDriverAssignment

    res = await db.execute(
        _select(FleetDriverAssignment.customer_vehicle_id).where(
            FleetDriverAssignment.org_id == ctx.org_id,
            FleetDriverAssignment.portal_account_id == driver_id,
        )
    )
    ids = [str(row[0]) for row in res.all()]
    return {"customer_vehicle_ids": ids, "total": len(ids)}


class _DriverEditRequest(S._StrictBase):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)


@router.patch("/drivers/{driver_id}", response_model=S.StatusResponse)
async def edit_driver(
    driver_id: uuid.UUID,
    body: _DriverEditRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Edit a driver's profile fields (name, phone)."""
    from sqlalchemy import select as _select

    res = await db.execute(
        _select(PortalAccount).where(
            PortalAccount.id == driver_id,
            PortalAccount.org_id == ctx.org_id,
            PortalAccount.fleet_account_id == ctx.fleet_account_id,
            PortalAccount.portal_user_role == "driver",
        )
    )
    drv = res.scalars().first()
    if drv is None:
        raise HTTPException(status_code=404, detail="Driver not found")

    payload = body.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(drv, key, value)
    await db.flush()
    return S.StatusResponse(ok=True)


@router.post("/drivers/{driver_id}/reactivate", response_model=S.StatusResponse)
async def reactivate_driver(
    driver_id: uuid.UUID,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Re-activate a previously deactivated driver."""
    from sqlalchemy import select as _select

    res = await db.execute(
        _select(PortalAccount).where(
            PortalAccount.id == driver_id,
            PortalAccount.org_id == ctx.org_id,
            PortalAccount.fleet_account_id == ctx.fleet_account_id,
            PortalAccount.portal_user_role == "driver",
        )
    )
    drv = res.scalars().first()
    if drv is None:
        raise HTTPException(status_code=404, detail="Driver not found")
    drv.is_active = True
    drv.failed_login_attempts = 0
    drv.locked_until = None
    drv.is_locked_permanently = False
    await db.flush()
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Profile (own user — Req 3.12)
# ---------------------------------------------------------------------------


class _ProfileUpdateRequest(S._StrictBase):
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    phone: str | None = Field(None, max_length=50)


@router.patch("/me", response_model=S.StatusResponse)
async def update_own_profile(
    body: _ProfileUpdateRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.StatusResponse:
    """Edit own profile fields (name, phone). Email change is intentionally
    not exposed here — that's a security-sensitive operation handled by the
    workshop admin via account-detail / re-invite."""
    from sqlalchemy import select as _select

    res = await db.execute(
        _select(PortalAccount).where(PortalAccount.id == ctx.portal_account_id)
    )
    me = res.scalars().first()
    if me is None:
        raise HTTPException(status_code=404, detail="Account not found")

    payload = body.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(me, key, value)
    await db.flush()
    return S.StatusResponse(ok=True)


# ---------------------------------------------------------------------------
# Co-admin invite (admin invites another fleet_admin — Req 4.x)
# ---------------------------------------------------------------------------


class _AdminInviteRequest(S._StrictBase):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=50)


@router.get("/admins")
async def list_co_admins(
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """List the fleet_admin accounts attached to this fleet account.

    Used by the portal `/fleet/admins` page so a fleet admin can see
    who else is managing the fleet alongside them.
    """
    from sqlalchemy import select as _select

    if ctx.fleet_account_id is None:
        return {"items": [], "total": 0}

    res = await db.execute(
        _select(PortalAccount).where(
            PortalAccount.org_id == ctx.org_id,
            PortalAccount.fleet_account_id == ctx.fleet_account_id,
            PortalAccount.portal_user_role == "fleet_admin",
        ).order_by(PortalAccount.created_at.asc())
    )
    rows = res.scalars().all()
    items = [
        {
            "portal_account_id": str(a.id),
            "email": a.email,
            "first_name": a.first_name,
            "last_name": a.last_name,
            "phone": a.phone,
            "is_active": a.is_active,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        }
        for a in rows
    ]
    return {"items": items, "total": len(items)}


@router.post("/admins/invite", response_model=S.IdResponse)
async def invite_co_admin(
    body: _AdminInviteRequest,
    ctx: FleetSessionCtx = Depends(require_fleet_admin),
    _: None = Depends(validate_fleet_portal_csrf),
    db: AsyncSession = Depends(get_db_session),
) -> S.IdResponse:
    """Invite a second fleet admin for this fleet account.

    The new account is created with ``portal_user_role='fleet_admin'``,
    is_active=True, and an invite token. The invite email is dispatched
    by the same mechanism used for the initial fleet admin invite.
    """
    from sqlalchemy import select as _select
    from datetime import datetime as _dt, timezone as _tz
    import secrets as _secrets

    if ctx.fleet_account_id is None:
        raise HTTPException(status_code=403, detail="No fleet account context")

    # Reject duplicates — same email already exists in this org
    email_norm = body.email.strip().lower()
    dup_res = await db.execute(
        _select(PortalAccount).where(
            PortalAccount.org_id == ctx.org_id,
            PortalAccount.email == email_norm,
        )
    )
    if dup_res.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An account already exists for {email_norm}",
        )

    # Resolve the fleet account's customer_id — co-admin shares it
    fa_res = await db.execute(
        _select(PortalFleetAccount).where(
            PortalFleetAccount.id == ctx.fleet_account_id
        )
    )
    fa = fa_res.scalars().first()
    if fa is None:
        raise HTTPException(status_code=404, detail="Fleet account not found")

    invite_token = _secrets.token_urlsafe(32)
    new_account = PortalAccount(
        org_id=ctx.org_id,
        customer_id=fa.customer_id,
        fleet_account_id=fa.id,
        email=email_norm,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        portal_user_role="fleet_admin",
        is_active=True,
        invite_token=invite_token,
        invite_sent_at=_dt.now(_tz.utc),
    )
    db.add(new_account)
    await db.flush()
    await db.refresh(new_account)

    # Best-effort invite email reuses the workshop-side helper
    try:
        from app.modules.fleet_portal.admin_router import (
            _send_fleet_portal_invite_email,
        )
        await _send_fleet_portal_invite_email(
            db, org_id=ctx.org_id, account=new_account, base_url=None
        )
    except Exception as exc:
        logger.warning(
            "fleet_portal.coadmin_invite_email_failed err=%s", exc
        )

    return S.IdResponse(id=new_account.id)


# ---------------------------------------------------------------------------
# Notifications inbox (Req 9.7, 11.2, 12.2)
# ---------------------------------------------------------------------------


@router.get("/notifications")
async def list_my_notifications(
    offset: int = 0,
    limit: int = 50,
    unread_only: bool = False,
    ctx: FleetSessionCtx = Depends(require_fleet_portal_session),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """List in-app notifications for the current portal user.

    Filters on entity_type starting with 'fleet_' so we only show
    fleet-related notifications even if the staff app emits others.
    Visibility uses the same audience_roles model as the staff inbox.
    """
    from sqlalchemy import and_, select as _select, func as _func
    from app.modules.in_app_notifications.models import AppNotification

    role = ctx.portal_user_role  # 'fleet_admin' | 'driver'

    # Visibility: notifications targeted at the portal user's role with no
    # specific user_id (which is the FK to staff users). We never write
    # portal_account_id into AppNotification.user_id, so all portal-bound
    # notifications are broadcasts gated on audience_roles. Restrict to
    # entity_type starting with "fleet_" so we don't surface staff-side
    # notifications by accident.
    visibility = and_(
        AppNotification.org_id == ctx.org_id,
        AppNotification.entity_type.like("fleet_%"),
        AppNotification.user_id.is_(None),
        AppNotification.audience_roles.contains([role]),
    )

    base = _select(AppNotification).where(visibility)
    total = (
        await db.execute(_select(_func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(AppNotification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    items = [
        {
            "id": str(n.id),
            "category": n.category,
            "severity": n.severity,
            "title": n.title,
            "body": n.body,
            "link_url": n.link_url,
            "entity_type": n.entity_type,
            "entity_id": str(n.entity_id) if n.entity_id else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in rows
    ]
    return {"items": items, "total": int(total), "offset": offset, "limit": limit}


__all__ = ["router"]
