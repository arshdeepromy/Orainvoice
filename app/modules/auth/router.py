"""Auth router — login endpoint and future auth routes."""

from __future__ import annotations

from typing import Union

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.schemas import (
    GoogleLoginRequest,
    InvalidateAllSessionsResponse,
    InviteUserRequest,
    InviteUserResponse,
    IPAllowlistResponse,
    IPAllowlistUpdateRequest,
    LoginRequest,
    MFABackupCodesResponse,
    MFAEnrolRequest,
    MFAEnrolResponse,
    MFARequiredResponse,
    MFAVerifyRequest,
    PasskeyLoginOptionsRequest,
    PasskeyLoginOptionsResponse,
    PasskeyLoginVerifyRequest,
    PasskeyRegisterOptionsRequest,
    PasskeyRegisterOptionsResponse,
    PasskeyRegisterVerifyRequest,
    PasskeyRegisterVerifyResponse,
    PasswordCheckRequest,
    PasswordCheckResponse,
    PasswordResetBackupCodeSchema,
    PasswordResetCompleteSchema,
    PasswordResetRequestSchema,
    PasswordResetResponse,
    PublicPlanListResponse,
    PublicPlanResponse,
    RefreshTokenRequest,
    ResendInviteRequest,
    ResendInviteResponse,
    SessionListResponse,
    SessionResponse,
    SessionTerminateResponse,
    TokenResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.modules.auth.service import (
    authenticate_google,
    authenticate_user,
    complete_password_reset,
    create_invitation,
    generate_passkey_login_options,
    generate_passkey_register_options,
    invalidate_all_sessions,
    list_user_sessions,
    request_password_reset,
    resend_invitation,
    reset_via_backup_code,
    rotate_refresh_token,
    terminate_session,
    verify_email_and_set_password,
    verify_passkey_login,
    verify_passkey_registration,
)
from app.modules.auth.mfa_service import (
    enrol_mfa,
    generate_backup_codes,
    verify_mfa,
)
from app.modules.organisations.schemas import (
    PublicSignupRequest,
    PublicSignupResponse,
)
from app.modules.organisations.service import public_signup

router = APIRouter()


def _cookie_secure() -> bool:
    """Return False in development so cookies work over plain HTTP."""
    import os
    return os.getenv("ENVIRONMENT", "production") != "development"


def _parse_user_agent(ua: str | None) -> tuple[str | None, str | None]:
    """Extract a rough device type and browser name from User-Agent."""
    if not ua:
        return None, None

    ua_lower = ua.lower()

    # Device type
    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
        device_type = "mobile"
    elif "tablet" in ua_lower or "ipad" in ua_lower:
        device_type = "tablet"
    else:
        device_type = "desktop"

    # Browser (order matters — Edge and Chrome both contain "chrome")
    if "edg" in ua_lower:
        browser = "Edge"
    elif "chrome" in ua_lower and "chromium" not in ua_lower:
        browser = "Chrome"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "safari" in ua_lower or "applewebkit" in ua_lower:
        browser = "Safari"
    else:
        browser = ua[:100] if ua else None

    return device_type, browser


@router.post(
    "/login",
    response_model=Union[TokenResponse, MFARequiredResponse],
    responses={401: {"description": "Invalid credentials"}},
    summary="Email/password login",
)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Authenticate with email and password.

    Returns a JWT access/refresh token pair on success, or an MFA
    challenge if the user has MFA configured.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = authenticate_user(
            db=db,
            payload=payload,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
        # authenticate_user is async
        result = await result
    except ValueError:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
        )

    # If MFA is required, return the MFA challenge without setting a cookie
    if hasattr(result, 'mfa_required') and result.mfa_required:
        return result

    # Set the refresh token as httpOnly cookie
    response = JSONResponse(
        content={
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": result.token_type,
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


@router.post(
    "/token/refresh",
    response_model=TokenResponse,
    responses={401: {"description": "Invalid or revoked refresh token"}},
    summary="Refresh access token",
)
async def refresh_token(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Exchange a valid refresh token for a new access/refresh token pair.

    The refresh token is read from the httpOnly cookie (not the request body).
    Implements refresh-token rotation: the old token is invalidated and a
    new pair is returned.  If a previously-rotated token is reused, the
    entire session family is revoked and the user is alerted.
    """
    # Read refresh token from httpOnly cookie
    refresh_token_value = request.cookies.get("refresh_token")
    if not refresh_token_value:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing refresh token"},
        )

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = await rotate_refresh_token(
            db=db,
            refresh_token=refresh_token_value,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
    except ValueError as exc:
        response = JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )
        # Clear the invalid cookie
        response.delete_cookie(
            "refresh_token",
            path="/",
            httponly=True,
            secure=_cookie_secure(),
            samesite="strict",
        )
        return response

    # Set the new refresh token as httpOnly cookie
    response = JSONResponse(
        content={
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": result.token_type,
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


@router.post(
    "/logout",
    summary="Logout and clear refresh token cookie",
)
async def logout(request: Request):
    """Clear the httpOnly refresh token cookie to end the session."""
    response = JSONResponse(content={"detail": "Logged out"})
    response.delete_cookie(
        "refresh_token",
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
    )
    return response


@router.post(
    "/login/google",
    response_model=Union[TokenResponse, MFARequiredResponse],
    responses={
        401: {"description": "No account found or authentication failed"},
        502: {"description": "Google OAuth service error"},
    },
    summary="Google OAuth login",
)
async def login_google(
    payload: GoogleLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Authenticate via Google OAuth 2.0.

    Accepts an authorization code from the frontend, exchanges it for
    Google user info, and authenticates the user by email. Users must
    already have an account (no self-registration via OAuth).
    """
    from app.integrations.google_oauth import GoogleOAuthError, exchange_code_for_user_info

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    # Exchange authorization code for Google user info
    try:
        google_user_info = await exchange_code_for_user_info(
            code=payload.code,
            redirect_uri=payload.redirect_uri,
        )
    except GoogleOAuthError as exc:
        return JSONResponse(
            status_code=502,
            content={"detail": str(exc)},
        )

    # Authenticate or reject
    try:
        result = await authenticate_google(
            db=db,
            google_user_info=google_user_info,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )

    # If MFA is required, return the MFA challenge without setting a cookie
    if hasattr(result, 'mfa_required') and result.mfa_required:
        return result

    # Set the refresh token as httpOnly cookie
    response = JSONResponse(
        content={
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": result.token_type,
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# Passkey (WebAuthn) endpoints
# ---------------------------------------------------------------------------

async def _get_current_user(request: Request, db: AsyncSession) -> "User":
    """Extract the current authenticated user from the JWT in the request.

    This is a simplified helper — in production the auth middleware
    populates request.state.user_id.
    """
    from app.modules.auth.jwt import decode_access_token
    from app.modules.auth.models import User
    from sqlalchemy import select

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise ValueError("Missing or invalid authorization header")

    token = auth_header[len("Bearer "):]
    payload = decode_access_token(token)
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("Invalid token payload")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")
    return user


@router.post(
    "/passkey/register/options",
    response_model=PasskeyRegisterOptionsResponse,
    summary="Generate passkey registration options",
)
async def passkey_register_options(
    payload: PasskeyRegisterOptionsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate WebAuthn registration options for the authenticated user.

    The client should pass these options to navigator.credentials.create().
    Requires a valid JWT access token.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    try:
        options = await generate_passkey_register_options(
            user=user,
            device_name=payload.device_name,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return PasskeyRegisterOptionsResponse(options=options)


@router.post(
    "/passkey/register/verify",
    response_model=PasskeyRegisterVerifyResponse,
    summary="Verify passkey registration",
)
async def passkey_register_verify(
    payload: PasskeyRegisterVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify the WebAuthn registration response and store the credential.

    Requires a valid JWT access token.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    try:
        result = await verify_passkey_registration(
            db=db,
            user=user,
            credential_response=payload.credential,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return PasskeyRegisterVerifyResponse(**result)


@router.post(
    "/passkey/login/options",
    response_model=PasskeyLoginOptionsResponse,
    summary="Generate passkey login options",
)
async def passkey_login_options(
    payload: PasskeyLoginOptionsRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate WebAuthn authentication options for a user.

    The client should pass these options to navigator.credentials.get().
    No authentication required — this is the first step of passkey login.
    """
    try:
        options = await generate_passkey_login_options(
            db=db,
            email=payload.email,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return PasskeyLoginOptionsResponse(options=options)


@router.post(
    "/passkey/login/verify",
    response_model=TokenResponse,
    responses={401: {"description": "Authentication failed"}},
    summary="Verify passkey login",
)
async def passkey_login_verify(
    payload: PasskeyLoginVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify the WebAuthn authentication response and issue JWT tokens.

    Passkey login satisfies MFA requirements — no additional MFA prompt
    is needed (Requirement 2.9).
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = await verify_passkey_login(
            db=db,
            email=payload.email,
            credential_response=payload.credential,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )

    # Set the refresh token as httpOnly cookie
    response = JSONResponse(
        content={
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": result.token_type,
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


# ---------------------------------------------------------------------------
# MFA endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/mfa/enrol",
    response_model=MFAEnrolResponse,
    responses={
        400: {"description": "Invalid method or missing phone number"},
        401: {"description": "Authentication required"},
    },
    summary="Start MFA enrolment",
)
async def mfa_enrol(
    payload: MFAEnrolRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Enrol in an MFA method (TOTP, SMS, or email).

    Requires a valid JWT access token. For TOTP, returns a QR code URI.
    For SMS/email, sends a verification code.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    try:
        result = await enrol_mfa(
            db=db,
            user=user,
            method=payload.method,
            phone_number=payload.phone_number,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return result


@router.post(
    "/mfa/verify",
    response_model=TokenResponse,
    responses={
        400: {"description": "Invalid code or method"},
        401: {"description": "Invalid or expired MFA token"},
        429: {"description": "Too many failed attempts"},
    },
    summary="Verify MFA code",
)
async def mfa_verify(
    payload: MFAVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify a 6-digit MFA code and receive JWT tokens.

    Uses the mfa_token from the login response (not full auth).
    Supports TOTP, SMS, email, and backup code methods.
    Locks after 5 consecutive failures.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = await verify_mfa(
            db=db,
            mfa_token=payload.mfa_token,
            code=payload.code,
            method=payload.method,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "locked" in error_msg.lower():
            return JSONResponse(
                status_code=429,
                content={"detail": error_msg},
            )
        if "token" in error_msg.lower():
            return JSONResponse(
                status_code=401,
                content={"detail": error_msg},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": error_msg},
        )

    # Set the refresh token as httpOnly cookie
    response = JSONResponse(
        content={
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "token_type": result.token_type,
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


@router.post(
    "/mfa/backup-codes",
    response_model=MFABackupCodesResponse,
    responses={401: {"description": "Authentication required"}},
    summary="Generate backup recovery codes",
)
async def mfa_backup_codes(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Generate 10 single-use backup recovery codes.

    Requires a valid JWT access token. Previous backup codes are replaced.
    The plain codes are returned once — they cannot be retrieved again.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    codes = await generate_backup_codes(db=db, user=user)
    return MFABackupCodesResponse(codes=codes)


# ---------------------------------------------------------------------------
# Password check (HIBP) endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/password/check",
    response_model=PasswordCheckResponse,
    summary="Check password against HaveIBeenPwned",
)
async def password_check(payload: PasswordCheckRequest):
    """Check if a password appears in the HaveIBeenPwned breach database.

    Uses k-anonymity — only the first 5 characters of the SHA-1 hash are
    sent to the HIBP API. Intended for use during password setting/changing.
    """
    from app.integrations.hibp import is_password_compromised

    compromised = await is_password_compromised(payload.password)

    if compromised:
        return PasswordCheckResponse(
            compromised=True,
            message="This password has appeared in a known data breach. Please choose a different password.",
        )

    return PasswordCheckResponse(
        compromised=False,
        message="Password not found in known breaches.",
    )


# ---------------------------------------------------------------------------
# Password recovery endpoints
# ---------------------------------------------------------------------------

_RESET_UNIFORM_MESSAGE = (
    "If an account with that email exists, a password reset link has been sent."
)


@router.post(
    "/password/reset-request",
    response_model=PasswordResetResponse,
    summary="Request password reset email",
)
async def password_reset_request(
    payload: PasswordResetRequestSchema,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Request a password reset link.

    CRITICAL: Returns an identical 200 response whether the email exists
    or not, to prevent account enumeration (Requirement 4.4).
    The reset link expires after 1 hour (Requirement 4.2).
    """
    ip_address = request.client.host if request.client else None

    await request_password_reset(
        db=db,
        email=payload.email,
        ip_address=ip_address,
    )

    return PasswordResetResponse(message=_RESET_UNIFORM_MESSAGE)


@router.post(
    "/password/reset",
    response_model=PasswordResetResponse,
    responses={
        400: {"description": "Invalid token or compromised password"},
    },
    summary="Complete password reset",
)
async def password_reset_complete(
    payload: PasswordResetCompleteSchema,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Complete a password reset using the token from the reset email.

    Validates the token, checks the new password against HIBP,
    updates the password, and invalidates all active sessions
    (Requirement 4.3).
    """
    ip_address = request.client.host if request.client else None

    try:
        await complete_password_reset(
            db=db,
            token=payload.token,
            new_password=payload.new_password,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return PasswordResetResponse(
        message="Password has been reset successfully. All sessions have been invalidated."
    )


@router.post(
    "/password/reset-backup",
    response_model=PasswordResetResponse,
    responses={
        400: {"description": "Invalid backup code or compromised password"},
        401: {"description": "Invalid credentials"},
    },
    summary="Reset password via MFA backup code",
)
async def password_reset_backup(
    payload: PasswordResetBackupCodeSchema,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Reset password using an MFA backup code.

    Allows account recovery when all MFA methods are unavailable
    (Requirement 4.5). The backup code is consumed on use.
    """
    ip_address = request.client.host if request.client else None

    try:
        await reset_via_backup_code(
            db=db,
            email=payload.email,
            backup_code=payload.backup_code,
            new_password=payload.new_password,
            ip_address=ip_address,
        )
    except ValueError as exc:
        error_msg = str(exc)
        status = 401 if "credentials" in error_msg.lower() else 400
        return JSONResponse(
            status_code=status,
            content={"detail": error_msg},
        )

    return PasswordResetResponse(
        message="Password has been reset successfully. All sessions have been invalidated."
    )


# ---------------------------------------------------------------------------
# Session management endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/sessions",
    response_model=SessionListResponse,
    responses={401: {"description": "Authentication required"}},
    summary="List active sessions",
)
async def list_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all active (non-revoked, non-expired) sessions for the
    authenticated user, with a ``current`` flag on the requesting session.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    # Try to identify the current session from the JWT's session_id claim
    from app.modules.auth.jwt import decode_access_token
    import uuid as _uuid

    current_session_id = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = decode_access_token(auth_header[len("Bearer "):])
            sid = payload.get("session_id")
            if sid:
                current_session_id = _uuid.UUID(sid)
        except Exception:
            pass

    sessions = await list_user_sessions(
        db=db,
        user_id=user.id,
        current_session_id=current_session_id,
    )

    return SessionListResponse(
        sessions=[SessionResponse(**s) for s in sessions]
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionTerminateResponse,
    responses={
        401: {"description": "Authentication required"},
        404: {"description": "Session not found"},
    },
    summary="Terminate a session",
)
async def delete_session(
    session_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Revoke a specific session belonging to the authenticated user."""
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    import uuid as _uuid

    try:
        sid = _uuid.UUID(session_id)
    except ValueError:
        return JSONResponse(
            status_code=404,
            content={"detail": "Session not found"},
        )

    ip_address = request.client.host if request.client else None

    try:
        await terminate_session(
            db=db,
            session_id=sid,
            user_id=user.id,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    return SessionTerminateResponse(message="Session terminated successfully")


# ---------------------------------------------------------------------------
# Session invalidation ("This wasn't me") endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/sessions/invalidate-all",
    response_model=InvalidateAllSessionsResponse,
    responses={401: {"description": "Authentication required"}},
    summary="Invalidate all sessions (This wasn't me)",
)
async def sessions_invalidate_all(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Revoke all active sessions for the authenticated user.

    This is the handler for the 'This wasn't me' link sent in anomalous
    login alert emails. Invalidates every active session.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    ip_address = request.client.host if request.client else None
    count = await invalidate_all_sessions(
        db=db,
        user_id=user.id,
        ip_address=ip_address,
    )

    return InvalidateAllSessionsResponse(
        sessions_revoked=count,
        message=f"All {count} active session(s) have been revoked.",
    )


@router.put(
    "/ip-allowlist",
    response_model=IPAllowlistResponse,
    responses={
        400: {"description": "Invalid IP entries or self-lockout"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Update IP allowlist for the organisation",
)
async def update_ip_allowlist(
    payload: IPAllowlistUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update the organisation's IP allowlist.

    Only Org_Admin can update this setting. Before saving, validates that
    the current session IP is included in the new allowlist to prevent
    self-lockout (Requirement 6.2).
    """
    from sqlalchemy import text as sql_text

    from app.core.audit import write_audit_log
    from app.core.ip_allowlist import is_ip_in_allowlist, validate_allowlist_entries

    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    if user.role != "org_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can configure IP allowlisting"},
        )

    if not user.org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No organisation context"},
        )

    ip_address = request.client.host if request.client else None
    new_allowlist = payload.ip_allowlist

    # If setting a non-empty allowlist, validate entries
    if new_allowlist:
        errors = validate_allowlist_entries(new_allowlist)
        if errors:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Invalid allowlist entries: {'; '.join(errors)}"},
            )

        # Self-lockout prevention (Requirement 6.2)
        if ip_address and not is_ip_in_allowlist(ip_address, new_allowlist):
            return JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        f"Your current IP address ({ip_address}) is not included "
                        "in the new allowlist. Add it to prevent locking yourself out."
                    )
                },
            )

    # Fetch current settings
    result = await db.execute(
        sql_text("SELECT settings FROM organisations WHERE id = :org_id"),
        {"org_id": str(user.org_id)},
    )
    row = result.first()
    current_settings = row[0] if row and row[0] else {}
    old_allowlist = current_settings.get("ip_allowlist", [])

    # Update settings with new allowlist (empty list = disabled)
    current_settings["ip_allowlist"] = new_allowlist if new_allowlist else []

    await db.execute(
        sql_text(
            "UPDATE organisations SET settings = :settings, updated_at = now() "
            "WHERE id = :org_id"
        ),
        {"settings": __import__("json").dumps(current_settings), "org_id": str(user.org_id)},
    )

    # Audit log
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="org.ip_allowlist_updated",
        entity_type="organisation",
        entity_id=user.org_id,
        before_value={"ip_allowlist": old_allowlist},
        after_value={"ip_allowlist": new_allowlist},
        ip_address=ip_address,
    )

    return IPAllowlistResponse(
        ip_allowlist=new_allowlist,
        message="IP allowlist updated successfully"
        if new_allowlist
        else "IP allowlist disabled",
    )


# ---------------------------------------------------------------------------
# Email verification / invitation endpoints (Task 4.11)
# ---------------------------------------------------------------------------

@router.post(
    "/invite",
    response_model=InviteUserResponse,
    responses={
        400: {"description": "Invalid request or email already registered"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Invite a new user to the organisation",
)
async def invite_user(
    payload: InviteUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new user account via invitation.

    Generates a secure signup link valid for 48 hours and sends it
    to the invited email address. Only Org_Admin can invite users.
    (Requirement 7.1)
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    if user.role != "org_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can invite users"},
        )

    if not user.org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No organisation context"},
        )

    ip_address = request.client.host if request.client else None

    try:
        result = await create_invitation(
            db=db,
            inviter_user_id=user.id,
            org_id=user.org_id,
            email=payload.email,
            role=payload.role,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return InviteUserResponse(
        message="Invitation sent successfully",
        user_id=result["user_id"],
        invitation_expires_at=result["invitation_expires_at"],
    )


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    responses={
        400: {"description": "Invalid or expired token, or compromised password"},
    },
    summary="Verify email and set password",
)
async def verify_email(
    payload: VerifyEmailRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify email via invitation token and complete account setup.

    Marks the email as verified, sets the user's password, and returns
    a JWT pair so the user is logged in immediately.
    (Requirements 7.1, 7.2)
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = await verify_email_and_set_password(
            db=db,
            token=payload.token,
            new_password=payload.password,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    # Set the refresh token as httpOnly cookie
    response = JSONResponse(
        content={
            "message": "Email verified and password set successfully",
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
        }
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


@router.post(
    "/resend-invite",
    response_model=ResendInviteResponse,
    responses={
        400: {"description": "Invalid request or user already verified"},
        401: {"description": "Authentication required"},
        403: {"description": "Org_Admin role required"},
    },
    summary="Resend an expired invitation",
)
async def resend_invite(
    payload: ResendInviteRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Resend an invitation email with a fresh 48-hour token.

    Only Org_Admin can resend invitations. The user must belong to the
    same organisation and must not have already verified their email.
    (Requirement 7.3)
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    if user.role != "org_admin":
        return JSONResponse(
            status_code=403,
            content={"detail": "Only Org_Admin can resend invitations"},
        )

    if not user.org_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No organisation context"},
        )

    ip_address = request.client.host if request.client else None

    try:
        result = await resend_invitation(
            db=db,
            resender_user_id=user.id,
            org_id=user.org_id,
            email=payload.email,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return ResendInviteResponse(
        message="Invitation resent successfully",
        invitation_expires_at=result["invitation_expires_at"],
    )


# ---------------------------------------------------------------------------
# Public plans endpoint (Requirement 6.1, 6.2) — no auth required
# ---------------------------------------------------------------------------


@router.get(
    "/plans",
    response_model=PublicPlanListResponse,
    summary="List public subscription plans",
)
async def list_public_plans(
    db: AsyncSession = Depends(get_db_session),
):
    """Return all public, non-archived subscription plans.

    No authentication required. Used by the public signup page to
    populate the plan selector.

    Requirements 6.1, 6.2.
    """
    from sqlalchemy import select

    from app.modules.admin.models import SubscriptionPlan

    result = await db.execute(
        select(SubscriptionPlan).where(
            SubscriptionPlan.is_public.is_(True),
            SubscriptionPlan.is_archived.is_(False),
        )
    )
    plans = result.scalars().all()

    return PublicPlanListResponse(
        plans=[
            PublicPlanResponse(
                id=str(plan.id),
                name=plan.name,
                monthly_price_nzd=plan.monthly_price_nzd,
                trial_duration=plan.trial_duration or 0,
                trial_duration_unit=plan.trial_duration_unit or "days",
                sms_included=plan.sms_included,
                sms_included_quota=plan.sms_included_quota or 0,
                per_sms_cost_nzd=float(plan.per_sms_cost_nzd or 0),
            )
            for plan in plans
        ]
    )


# ---------------------------------------------------------------------------
# Public signup (Requirement 8.6) — no auth required
# ---------------------------------------------------------------------------


@router.post(
    "/signup",
    response_model=PublicSignupResponse,
    responses={
        400: {"description": "Validation error (bad plan, duplicate email, etc.)"},
    },
    summary="Public workshop signup — start 14-day trial",
)
async def signup(
    payload: PublicSignupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Public signup endpoint for new workshops.

    Creates the organisation with a 14-day free trial, creates an
    Org_Admin user, generates a Stripe SetupIntent for card collection
    (without charging), and returns a signup token for the onboarding
    wizard.

    Requirement 8.6.
    """
    import uuid as _uuid

    ip_address = request.client.host if request.client else None

    try:
        plan_uuid = _uuid.UUID(payload.plan_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid plan_id format"},
        )

    try:
        result = await public_signup(
            db,
            org_name=payload.org_name,
            admin_email=payload.admin_email,
            admin_first_name=payload.admin_first_name,
            admin_last_name=payload.admin_last_name,
            plan_id=plan_uuid,
            ip_address=ip_address,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return PublicSignupResponse(
        message="Signup successful — 14-day trial started",
        **result,
    )
