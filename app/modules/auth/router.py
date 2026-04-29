"""Auth router — login endpoint and future auth routes."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
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
    MFAChallengeSendRequest,
    MFAChallengeResponse,
    MFADisableRequest,
    MFASetDefaultRequest,
    MFAEnrolRequest,
    MFAEnrolResponse,
    MFAEnrolVerifyRequest,
    MFAMethodStatus,
    MFARequiredResponse,
    MFAVerifyRequest,
    PasskeyCredentialInfo,
    PasskeyLoginOptionsRequest,
    PasskeyLoginOptionsResponse,
    PasskeyLoginVerifyRequest,
    PasskeyRegisterOptionsRequest,
    PasskeyRegisterOptionsResponse,
    PasskeyRegisterVerifyRequest,
    PasskeyRegisterVerifyResponse,
    PasskeyRemoveRequest,
    PasskeyRenameRequest,
    PasswordCheckRequest,
    PasswordCheckResponse,
    PasswordResetBackupCodeSchema,
    PasswordResetCompleteSchema,
    PasswordResetRequestSchema,
    PasswordResetResponse,
    PublicPlanListResponse,
    PublicPlanResponse,
    PublicIntervalPricing,
    RefreshTokenRequest,
    ResendInviteRequest,
    ResendInviteResponse,
    SessionListResponse,
    SessionResponse,
    SessionTerminateResponse,
    TokenResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    EmailChangeRequest,
    EmailChangeResponse,
    EmailChangeVerifyRequest,
    UpdateProfileRequest,
    UserProfileResponse,
)
from app.modules.auth.service import (
    authenticate_google,
    authenticate_user,
    complete_password_reset,
    create_invitation,
    generate_passkey_login_options,
    generate_passkey_register_options,
    invalidate_all_sessions,
    list_passkey_credentials,
    list_user_sessions,
    remove_passkey,
    rename_passkey,
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
    OTPRateLimitExceeded,
    enrol_mfa,
    generate_backup_codes,
    verify_enrolment,
    verify_mfa,
    send_challenge_otp,
    get_user_mfa_status,
    disable_mfa_method,
    set_default_mfa_method,
)
from app.modules.organisations.schemas import (
    ConfirmPaymentRequest,
    PublicSignupRequest,
    PublicSignupResponse,
)
from app.modules.organisations.service import public_signup
from app.modules.billing.interval_pricing import (
    build_default_interval_config,
    compute_effective_price,
    compute_equivalent_monthly,
    compute_savings_amount,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _cookie_secure() -> bool:
    """Return False in development so cookies work over plain HTTP."""
    import os
    return os.getenv("ENVIRONMENT", "production") != "development"


def _get_client_ip(request: Request) -> str | None:
    """Extract the real client IP, respecting reverse proxy headers.

    Checks X-Forwarded-For and X-Real-IP before falling back to
    request.client.host (which returns the Docker/proxy IP when
    running behind Nginx).
    """
    # X-Forwarded-For may contain multiple IPs: "client, proxy1, proxy2"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        # First IP is the original client
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else None


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


# ---------------------------------------------------------------------------
# CAPTCHA endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/captcha",
    summary="Generate a CAPTCHA challenge",
    responses={
        200: {"description": "CAPTCHA image generated", "content": {"image/png": {}}},
    },
)
async def get_captcha():
    """Generate a CAPTCHA challenge for signup protection.
    
    Returns a PNG image with a random code and a captcha_id cookie.
    The captcha_id is used to verify the user's response during signup.
    """
    from fastapi.responses import Response
    from app.core.captcha import create_captcha
    
    captcha_id, image_bytes = await create_captcha()
    
    response = Response(content=image_bytes, media_type="image/png")
    response.set_cookie(
        key="captcha_id",
        value=captcha_id,
        max_age=300,  # 5 minutes
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )
    
    return response


@router.post(
    "/verify-captcha",
    summary="Verify CAPTCHA code",
    responses={
        200: {"description": "CAPTCHA verified successfully"},
        400: {"description": "Invalid CAPTCHA code"},
    },
)
async def verify_captcha_endpoint(
    request: Request,
    payload: dict,
):
    """Verify a CAPTCHA code without creating an account.
    
    This allows the frontend to verify CAPTCHA before form submission.
    The code is NOT deleted so it can be used for actual signup.
    """
    from app.core.captcha import verify_captcha
    
    captcha_id = request.cookies.get("captcha_id")
    if not captcha_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "CAPTCHA verification required. Please refresh and try again."},
        )
    
    captcha_code = payload.get("captcha_code", "")
    # Don't delete the code - allow it to be used for signup
    is_valid = await verify_captcha(captcha_id, captcha_code, delete_after=False)
    
    if not is_valid:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid CAPTCHA code. Please try again."},
        )
    
    return JSONResponse(
        status_code=200,
        content={"message": "CAPTCHA verified successfully"},
    )


# ---------------------------------------------------------------------------
# Login endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=Union[TokenResponse, MFAChallengeResponse, MFARequiredResponse],
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
    ip_address = _get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = authenticate_user(
            db=db,
            payload=payload,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
            user_agent=user_agent,
        )
        # authenticate_user is async
        result = await result
    except ValueError as exc:
        error_msg = str(exc)
        # Pass through the email verification message so the frontend
        # can offer a "resend verification" link.
        if "verify your email" in error_msg.lower():
            return JSONResponse(
                status_code=401,
                content={"detail": error_msg},
            )
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
        )

    # If MFA is required, return the MFA challenge without setting a cookie
    # MFAChallengeResponse has .methods and .default_method (user has MFA configured)
    # MFARequiredResponse has .mfa_methods (user must set up MFA)
    if hasattr(result, 'mfa_required') and result.mfa_required:
        methods = getattr(result, 'methods', None) or getattr(result, 'mfa_methods', [])
        default_method = getattr(result, 'default_method', None)
        return JSONResponse(
            content={
                "mfa_required": True,
                "mfa_token": result.mfa_token,
                "methods": methods,
                "default_method": default_method,
            }
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

    ip_address = _get_client_ip(request)
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

    ip_address = _get_client_ip(request)
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
            user_agent=user_agent,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )

    # If MFA is required, return the MFA challenge without setting a cookie
    if hasattr(result, 'mfa_required') and result.mfa_required:
        methods = getattr(result, 'methods', None) or getattr(result, 'mfa_methods', [])
        default_method = getattr(result, 'default_method', None)
        return JSONResponse(
            content={
                "mfa_required": True,
                "mfa_token": result.mfa_token,
                "methods": methods,
                "default_method": default_method,
            }
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
            db=db,
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
    except Exception as exc:
        # py_webauthn raises InvalidRegistrationResponse / InvalidJSONStructure
        # on verification failures — catch them and return a meaningful error.
        import logging
        logging.getLogger(__name__).warning("Passkey registration verify failed: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": f"Passkey verification failed: {exc}"},
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
        from app.modules.auth.mfa_service import _get_challenge_session
        from sqlalchemy import select as sa_select
        from app.modules.auth.models import User

        # Resolve user from mfa_token challenge session
        session_data = await _get_challenge_session(payload.mfa_token)
        if session_data is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired MFA token"},
            )
        user_id = uuid.UUID(session_data["user_id"])
        user_result = await db.execute(sa_select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "No account found or account inactive"},
            )
        options = await generate_passkey_login_options(
            db=db,
            user_id=user.id,
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
    ip_address = _get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        # Resolve user from mfa_token challenge session
        from app.modules.auth.mfa_service import _get_challenge_session
        session_data = await _get_challenge_session(payload.mfa_token)
        if session_data is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired MFA token"},
            )

        credential_response = {
            "credential_id": payload.credential_id,
            "authenticator_data": payload.authenticator_data,
            "client_data_json": payload.client_data_json,
            "signature": payload.signature,
            "user_handle": payload.user_handle,
        }

        result = await verify_passkey_login(
            db=db,
            user_id=uuid.UUID(session_data["user_id"]),
            credential_response=credential_response,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
            user_agent=user_agent,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=401,
            content={"detail": str(exc)},
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Passkey login verify failed: %s", exc)
        return JSONResponse(
            status_code=401,
            content={"detail": f"Passkey authentication failed: {exc}"},
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
# Passkey management endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/passkey/credentials",
    response_model=list[PasskeyCredentialInfo],
    responses={401: {"description": "Authentication required"}},
    summary="List registered passkey credentials",
)
async def passkey_credentials_list(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return all passkey credentials for the authenticated user.

    Requires a valid JWT access token.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    credentials = await list_passkey_credentials(db=db, user=user)
    return [PasskeyCredentialInfo(**cred) for cred in credentials]


@router.patch(
    "/passkey/credentials/{credential_id}",
    responses={
        400: {"description": "Credential not found"},
        401: {"description": "Authentication required"},
    },
    summary="Rename a passkey credential",
)
async def passkey_credential_rename(
    credential_id: str,
    payload: PasskeyRenameRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Rename a passkey credential's friendly name.

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
        result = await rename_passkey(
            db=db,
            user=user,
            credential_id=credential_id,
            new_name=payload.device_name,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return result


@router.delete(
    "/passkey/credentials/{credential_id}",
    responses={
        400: {"description": "Credential not found"},
        401: {"description": "Authentication required or invalid password"},
        409: {"description": "Cannot remove last MFA method"},
    },
    summary="Remove a passkey credential",
)
async def passkey_credential_remove(
    credential_id: str,
    payload: PasskeyRemoveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Remove a passkey credential after password confirmation.

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
        await remove_passkey(
            db=db,
            user=user,
            credential_id=credential_id,
            password=payload.password,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "password" in error_msg.lower():
            return JSONResponse(
                status_code=401,
                content={"detail": error_msg},
            )
        if "cannot disable" in error_msg.lower():
            return JSONResponse(
                status_code=409,
                content={"detail": error_msg},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": error_msg},
        )

    return JSONResponse(content={"detail": "Passkey credential removed"})


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
    except OTPRateLimitExceeded as exc:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return result


@router.post(
    "/mfa/enrol/verify",
    responses={
        400: {"description": "Invalid code or missing enrolment"},
        401: {"description": "Authentication required"},
    },
    summary="Verify MFA enrolment code",
)
async def mfa_enrol_verify(
    payload: MFAEnrolVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify the enrolment code to activate an MFA method.

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
        await verify_enrolment(
            db=db,
            user=user,
            method=payload.method,
            code=payload.code,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return JSONResponse(content={"detail": "MFA method verified successfully"})


@router.post(
    "/mfa/enrol/firebase-verify",
    responses={
        400: {"description": "Missing enrolment"},
        401: {"description": "Authentication required"},
    },
    summary="Verify SMS MFA enrolment via Firebase Phone Auth",
)
async def mfa_enrol_firebase_verify(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Complete SMS MFA enrolment when Firebase Phone Auth is the MFA provider.

    With Firebase Phone Auth, the entire verification happens client-side:
    the frontend calls signInWithPhoneNumber (Firebase sends its own code),
    then confirm(code) verifies it.  Once that succeeds, the frontend calls
    this endpoint to mark the pending SMS enrolment as verified.

    Security: the request is already authenticated via JWT (the user must
    be logged in).  We also verify that Firebase is actually the configured
    MFA provider to prevent abuse.  The server now verifies the Firebase ID
    token server-side (REM-01) and checks that the phone_number claim
    matches the pending enrolment phone number.
    """
    from app.config import settings

    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(status_code=401, content={"detail": "Authentication required"})

    # Verify that Firebase is actually the configured MFA provider
    from app.modules.auth.mfa_service import _resolve_mfa_sms_provider

    provider = await _resolve_mfa_sms_provider(db)
    if provider is None or provider.provider_key != "firebase_phone_auth":
        return JSONResponse(
            status_code=400,
            content={"detail": "Firebase is not the configured MFA SMS provider"},
        )

    # Extract firebase_id_token from request body
    body = await request.json()
    firebase_id_token = body.get("firebase_id_token", "")

    # --- REM-01: Server-side Firebase ID token verification ---
    if firebase_id_token:
        from app.core.firebase_token import verify_firebase_id_token

        try:
            claims = await verify_firebase_id_token(
                firebase_id_token, settings.firebase_project_id
            )
        except ValueError as exc:
            logger.warning("Firebase token verification failed during enrolment: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing Firebase ID token"},
            )

    # Mark the pending SMS enrolment as verified
    from sqlalchemy import select
    from app.modules.auth.models import UserMfaMethod
    from datetime import datetime, timezone

    stmt = select(UserMfaMethod).where(
        UserMfaMethod.user_id == user.id,
        UserMfaMethod.method == "sms",
        UserMfaMethod.verified == False,  # noqa: E712
    )
    mfa_result = await db.execute(stmt)
    pending = mfa_result.scalar_one_or_none()
    if pending is None:
        return JSONResponse(status_code=400, content={"detail": "No pending SMS enrolment found"})

    # Compare phone_number claim against pending enrolment phone
    if firebase_id_token and pending.phone_number:
        if claims.get("phone_number") != pending.phone_number:
            return JSONResponse(
                status_code=400,
                content={"detail": "Phone number mismatch"},
            )

    pending.verified = True
    pending.verified_at = datetime.now(timezone.utc)

    from app.core.audit import write_audit_log
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.mfa_enrol_verified",
        entity_type="user",
        entity_id=user.id,
        after_value={"method": "sms", "provider": "firebase_phone_auth"},
    )

    return JSONResponse(content={"detail": "MFA method verified successfully"})



@router.post(
    "/mfa/challenge/send",
    responses={
        400: {"description": "Invalid method or MFA token"},
        429: {"description": "Rate limit exceeded"},
    },
    summary="Send MFA challenge OTP",
)
async def mfa_challenge_send(
    payload: MFAChallengeSendRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Send an OTP for the selected method during the MFA login challenge.

    Uses the mfa_token from the login response (not full JWT auth).
    Rate-limited to 5 sends per method per 15 minutes.
    """
    # Extract user_id from the challenge session (not JWT — this is mid-login)
    from app.modules.auth.mfa_service import _get_challenge_session

    session_data = await _get_challenge_session(payload.mfa_token)
    if session_data is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired MFA token"},
        )

    user_id = session_data["user_id"]

    try:
        import uuid as _uuid

        await send_challenge_otp(
            db=db,
            user_id=_uuid.UUID(user_id),
            method=payload.method,
            mfa_token=payload.mfa_token,
        )
    except OTPRateLimitExceeded as exc:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return JSONResponse(content={"detail": "Code sent"})


@router.get(
    "/mfa/provider-config",
    summary="Get MFA SMS provider configuration (public)",
)
async def mfa_provider_config(
    db: AsyncSession = Depends(get_db_session),
):
    """Return which SMS provider is the MFA default.

    This is a public endpoint (no auth) because it's needed during the
    MFA challenge flow before the user is fully authenticated.  It only
    exposes the provider key and, for Firebase, the client-side config
    needed to initialise the JS SDK.
    """
    from app.modules.admin.models import SmsVerificationProvider
    from sqlalchemy import select

    # Find the provider with mfa_default flag
    result = await db.execute(
        select(SmsVerificationProvider).where(
            SmsVerificationProvider.is_active == True,  # noqa: E712
        )
    )
    providers = result.scalars().all()

    mfa_provider = None
    for p in providers:
        if p.config and p.config.get("mfa_default"):
            mfa_provider = p
            break

    if mfa_provider is None:
        # Fall back to default provider, then any active one
        for p in providers:
            if p.is_default:
                mfa_provider = p
                break
        if mfa_provider is None and providers:
            mfa_provider = providers[0]

    if mfa_provider is None:
        return {"provider": "none", "firebase_config": None}

    resp: dict = {"provider": mfa_provider.provider_key, "firebase_config": None}

    if mfa_provider.provider_key == "firebase_phone_auth" and mfa_provider.credentials_encrypted:
        import json
        from app.core.encryption import envelope_decrypt_str

        try:
            creds = json.loads(envelope_decrypt_str(mfa_provider.credentials_encrypted))
            resp["firebase_config"] = {
                "apiKey": creds.get("api_key", ""),
                "projectId": creds.get("project_id", ""),
                "appId": creds.get("app_id", ""),
                "authDomain": f"{creds.get('project_id', '')}.firebaseapp.com",
            }
        except Exception:
            pass

    return resp


@router.post(
    "/mfa/provider-config",
    summary="Get MFA provider config with phone number for Firebase flow",
)
async def mfa_provider_config_with_phone(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return MFA provider config plus the user's phone number from the challenge session.

    Requires a valid mfa_token. Returns the phone number so the frontend
    can use Firebase JS SDK to send the verification code directly.
    """
    from app.modules.auth.mfa_service import _get_challenge_session

    body = await request.json()
    mfa_token = body.get("mfa_token", "")
    if not mfa_token:
        return JSONResponse(status_code=400, content={"detail": "mfa_token required"})

    session_data = await _get_challenge_session(mfa_token)
    if session_data is None:
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired MFA token"})

    phone_number = session_data.get("phone_number")

    # Get the provider config (same logic as GET endpoint)
    from app.modules.admin.models import SmsVerificationProvider
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(SmsVerificationProvider).where(
            SmsVerificationProvider.is_active == True,  # noqa: E712
        )
    )
    providers = result.scalars().all()

    mfa_provider = None
    for p in providers:
        if p.config and p.config.get("mfa_default"):
            mfa_provider = p
            break
    if mfa_provider is None:
        for p in providers:
            if p.is_default:
                mfa_provider = p
                break
        if mfa_provider is None and providers:
            mfa_provider = providers[0]

    resp: dict = {"provider": "none", "firebase_config": None, "phone_number": phone_number}
    if mfa_provider:
        resp["provider"] = mfa_provider.provider_key
        if mfa_provider.provider_key == "firebase_phone_auth" and mfa_provider.credentials_encrypted:
            import json
            from app.core.encryption import envelope_decrypt_str
            try:
                creds = json.loads(envelope_decrypt_str(mfa_provider.credentials_encrypted))
                resp["firebase_config"] = {
                    "apiKey": creds.get("api_key", ""),
                    "projectId": creds.get("project_id", ""),
                    "appId": creds.get("app_id", ""),
                    "authDomain": f"{creds.get('project_id', '')}.firebaseapp.com",
                }
            except Exception:
                pass

    return resp


@router.post(
    "/mfa/firebase-verify",
    summary="Complete MFA via Firebase Phone Auth verification",
)
async def mfa_firebase_verify(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Complete MFA challenge when Firebase Phone Auth was used.

    With Firebase Phone Auth, the entire SMS verification happens client-side.
    The frontend calls signInWithPhoneNumber + confirm(code).  Once that
    succeeds, it calls this endpoint with the mfa_token to complete login.

    Security: the mfa_token proves the user started a valid login flow.
    The server now verifies the Firebase ID token server-side (REM-01)
    and checks that the phone_number claim matches the challenge session.
    """
    from app.modules.auth.mfa_service import _get_challenge_session, _resolve_mfa_sms_provider
    from app.config import settings

    body = await request.json()
    mfa_token = body.get("mfa_token", "")
    firebase_id_token = body.get("firebase_id_token", "")

    if not mfa_token:
        return JSONResponse(status_code=400, content={"detail": "Missing mfa_token"})

    session_data = await _get_challenge_session(mfa_token)
    if session_data is None:
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired MFA token"})

    user_id = session_data["user_id"]

    # Verify that Firebase is actually the configured MFA provider
    provider = await _resolve_mfa_sms_provider(db)
    if provider is None or provider.provider_key != "firebase_phone_auth":
        return JSONResponse(
            status_code=400,
            content={"detail": "Firebase is not the configured MFA SMS provider"},
        )

    # --- REM-01: Server-side Firebase ID token verification ---
    if firebase_id_token:
        from app.core.firebase_token import verify_firebase_id_token

        try:
            claims = await verify_firebase_id_token(
                firebase_id_token, settings.firebase_project_id
            )
        except ValueError as exc:
            logger.warning("Firebase token verification failed: %s", exc)
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing Firebase ID token"},
            )

        # Compare phone_number claim against challenge session phone
        session_phone = session_data.get("phone_number")
        if session_phone and claims.get("phone_number") != session_phone:
            return JSONResponse(
                status_code=400,
                content={"detail": "Phone number mismatch"},
            )

    # Token is valid — complete the MFA flow
    # Reuse verify_mfa with firebase_verified=True to skip code check
    ip_address = _get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = await verify_mfa(
            db=db,
            mfa_token=mfa_token,
            code="",
            method="sms",
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
            firebase_verified=True,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

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
        secure=True,
        samesite="strict",
        max_age=30 * 24 * 3600,
        path="/",
    )
    return response



@router.get(
    "/mfa/methods",
    response_model=list[MFAMethodStatus],
    responses={401: {"description": "Authentication required"}},
    summary="List MFA method statuses",
)
async def mfa_methods_list(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the status of all MFA methods for the current user.

    Requires a valid JWT access token.
    """
    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    return await get_user_mfa_status(db=db, user=user)


@router.delete(
    "/mfa/methods/{method}",
    responses={
        400: {"description": "Invalid method"},
        401: {"description": "Authentication required or invalid password"},
        409: {"description": "Cannot disable last MFA method"},
    },
    summary="Disable an MFA method",
)
async def mfa_method_disable(
    method: str,
    payload: MFADisableRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Disable (remove) an MFA method after password confirmation.

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
        await disable_mfa_method(
            db=db,
            user=user,
            method=method,
            password=payload.password,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "password" in error_msg.lower():
            return JSONResponse(
                status_code=401,
                content={"detail": error_msg},
            )
        if "cannot disable" in error_msg.lower():
            return JSONResponse(
                status_code=409,
                content={"detail": error_msg},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": error_msg},
        )

    return JSONResponse(content={"detail": f"MFA method '{method}' disabled"})


@router.put(
    "/mfa/default",
    responses={
        400: {"description": "Invalid or unverified method"},
        401: {"description": "Authentication required"},
    },
    summary="Set default MFA method",
)
async def mfa_set_default(
    payload: MFASetDefaultRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Set the user's preferred/default MFA method.

    The default method is pre-selected during the MFA challenge flow.
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
        await set_default_mfa_method(db=db, user=user, method=payload.method)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    return JSONResponse(content={"detail": f"Default MFA method set to '{payload.method}'"})


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
    ip_address = _get_client_ip(request)
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
                headers={"Retry-After": "900"},
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
    ip_address = _get_client_ip(request)

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
    ip_address = _get_client_ip(request)

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
    ip_address = _get_client_ip(request)

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

    ip_address = _get_client_ip(request)

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

    ip_address = _get_client_ip(request)
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

    ip_address = _get_client_ip(request)
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

    ip_address = _get_client_ip(request)

    try:
        # Use the request Origin header to build invite URLs with the correct domain
        origin = request.headers.get("origin") or request.headers.get("referer", "").rstrip("/")
        # Strip any path from referer (e.g. "https://example.com/settings/users" → "https://example.com")
        if origin and "/" in origin.split("//", 1)[-1]:
            origin = origin.split("//", 1)[0] + "//" + origin.split("//", 1)[-1].split("/")[0]

        result = await create_invitation(
            db=db,
            inviter_user_id=user.id,
            org_id=user.org_id,
            email=payload.email,
            role=payload.role,
            ip_address=ip_address,
            base_url=origin or None,
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
    ip_address = _get_client_ip(request)
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

    ip_address = _get_client_ip(request)

    try:
        origin = request.headers.get("origin") or request.headers.get("referer", "").rstrip("/")
        if origin and "/" in origin.split("//", 1)[-1]:
            origin = origin.split("//", 1)[0] + "//" + origin.split("//", 1)[-1].split("/")[0]

        result = await resend_invitation(
            db=db,
            resender_user_id=user.id,
            org_id=user.org_id,
            email=payload.email,
            ip_address=ip_address,
            base_url=origin or None,
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
    "/signup-config",
    summary="Get signup billing configuration (GST, Stripe fees)",
)
async def get_signup_config(
    db: AsyncSession = Depends(get_db_session),
):
    """Return GST percentage and Stripe fee config for the signup page.

    No authentication required. Used by the public signup page to
    display price breakdowns.
    """
    from sqlalchemy import text as sa_text
    import json as _json

    row = await db.execute(
        sa_text("SELECT value FROM platform_settings WHERE key = :k"),
        {"k": "signup_billing"},
    )
    sb_row = row.scalar_one_or_none()

    config = {
        "gst_percentage": 15.0,
        "stripe_fee_percentage": 2.9,
        "stripe_fee_fixed_cents": 30,
        "pass_fees_to_customer": True,
    }
    if sb_row:
        val = sb_row if isinstance(sb_row, dict) else _json.loads(sb_row)
        config = {
            "gst_percentage": val.get("gst_percentage", 15.0),
            "stripe_fee_percentage": val.get("stripe_fee_percentage", 2.9),
            "stripe_fee_fixed_cents": val.get("stripe_fee_fixed_cents", 30),
            "pass_fees_to_customer": val.get("pass_fees_to_customer", True),
        }

    return config


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

    Requirements 3.1, 3.2, 3.3, 3.4.
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

    plan_responses = []
    for plan in plans:
        # Get interval config or default to monthly-only for legacy plans
        interval_config = plan.interval_config
        if not interval_config:
            interval_config = build_default_interval_config()

        base_price = Decimal(str(plan.monthly_price_nzd))

        # Build intervals array with only enabled intervals
        intervals = []
        for item in interval_config:
            if not item.get("enabled", False):
                continue
            interval = item["interval"]
            discount = Decimal(str(item.get("discount_percent", 0)))
            effective = compute_effective_price(base_price, interval, discount)
            savings = compute_savings_amount(base_price, interval, discount)
            equiv_monthly = compute_equivalent_monthly(effective, interval)
            intervals.append(
                PublicIntervalPricing(
                    interval=interval,
                    enabled=True,
                    discount_percent=float(discount),
                    effective_price=float(effective),
                    savings_amount=float(savings),
                    equivalent_monthly=float(equiv_monthly),
                )
            )

        plan_responses.append(
            PublicPlanResponse(
                id=str(plan.id),
                name=plan.name,
                monthly_price_nzd=plan.monthly_price_nzd,
                trial_duration=plan.trial_duration or 0,
                trial_duration_unit=plan.trial_duration_unit or "days",
                sms_included=plan.sms_included,
                sms_included_quota=plan.sms_included_quota or 0,
                per_sms_cost_nzd=float(plan.per_sms_cost_nzd or 0),
                intervals=intervals,
            )
        )

    return PublicPlanListResponse(plans=plan_responses)



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

    Creates the organisation with trial status, creates an
    Org_Admin user with password, and returns a signup token.
    
    Requires CAPTCHA verification to prevent automated bot signups.

    Requirement 8.6.
    """
    import uuid as _uuid
    from app.core.captcha import verify_captcha

    ip_address = _get_client_ip(request)

    # Verify CAPTCHA first
    captcha_id = request.cookies.get("captcha_id")
    if not captcha_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "CAPTCHA verification required. Please refresh and try again."},
        )
    
    is_valid_captcha = await verify_captcha(captcha_id, payload.captcha_code)
    if not is_valid_captcha:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid CAPTCHA code. Please try again."},
        )

    try:
        plan_uuid = _uuid.UUID(payload.plan_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid plan_id format"},
        )

    try:
        # Derive base URL from request origin for verification email links
        origin = request.headers.get("origin") or ""
        from app.config import settings as _settings
        base_url = origin or _settings.frontend_base_url or "http://localhost"

        result = await public_signup(
            db,
            org_name=payload.org_name,
            admin_email=payload.admin_email,
            admin_first_name=payload.admin_first_name,
            admin_last_name=payload.admin_last_name,
            password=payload.password,
            plan_id=plan_uuid,
            ip_address=ip_address,
            base_url=base_url,
            coupon_code=payload.coupon_code,
            billing_interval=payload.billing_interval,
            country_code=payload.country_code,
            trade_family_slug=payload.trade_family_slug,
        )
        # Commit the transaction after successful signup
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )
    except Exception as exc:
        await db.rollback()
        logger.exception("Unexpected error during signup")
        return JSONResponse(
            status_code=500,
            content={"detail": "An error occurred during signup. Please try again."},
        )

    if result.get("trial_ends_at"):
        msg = "Signup successful — trial started"
    elif result.get("requires_payment"):
        msg = "Signup successful — complete payment to activate"
    else:
        msg = "Signup successful — subscription active"

    return PublicSignupResponse(
        message=msg,
        **result,
    )


@router.post(
    "/signup/confirm-payment",
    summary="Confirm payment after signup and activate the organisation",
    responses={
        200: {"description": "Payment confirmed, organisation activated"},
        400: {"description": "Invalid payment or organisation"},
    },
)
async def confirm_signup_payment(
    payload: ConfirmPaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Called by the frontend after Stripe confirms the PaymentIntent.

    Retrieves the Pending_Signup from Redis using pending_signup_id,
    verifies the PaymentIntent status with Stripe, creates the Stripe
    Customer, Organisation, User, and saves the payment method.

    Requirements: 1.2, 1.3, 1.4, 7.1, 7.2
    """
    import json as _json
    import secrets as _secrets
    import uuid as _uuid
    from datetime import datetime, timezone

    import stripe as stripe_lib
    from sqlalchemy import select

    from app.core.audit import write_audit_log
    from app.core.redis import redis_pool
    from app.integrations.stripe_billing import (
        _ensure_stripe_key,
        create_stripe_customer,
    )
    from app.modules.admin.models import Organisation, SubscriptionPlan
    from app.modules.auth.models import User
    from app.modules.auth.pending_signup import delete_pending_signup, get_pending_signup
    from app.modules.billing.models import OrgPaymentMethod
    from app.modules.billing.interval_pricing import (
        compute_effective_price as _compute_eff,
        INTERVAL_PERIODS_PER_YEAR,
    )

    payment_intent_id = payload.payment_intent_id
    pending_signup_id = payload.pending_signup_id

    # 1. Retrieve Pending_Signup from Redis
    pending = await get_pending_signup(pending_signup_id)
    if pending is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid or expired signup session. Please start over."},
        )

    # 2. Verify PaymentIntent status with Stripe
    try:
        await _ensure_stripe_key()
        intent = stripe_lib.PaymentIntent.retrieve(payment_intent_id)
    except Exception as exc:
        logger.error("Failed to verify PaymentIntent %s: %s", payment_intent_id, exc)
        return JSONResponse(
            status_code=400,
            content={"detail": "Could not verify payment with Stripe"},
        )

    if intent.status != "succeeded":
        return JSONResponse(
            status_code=400,
            content={"detail": f"Payment not completed. Status: {intent.status}"},
        )

    # 3. Create Stripe Customer (now that payment is confirmed)
    admin_email = pending["admin_email"]
    admin_first = pending.get("admin_first_name", "")
    admin_last = pending.get("admin_last_name", "")
    customer_name = f"{admin_first} {admin_last}".strip() or admin_email.split("@")[0]

    try:
        stripe_customer_id = await create_stripe_customer(
            email=admin_email,
            name=customer_name,
            metadata={"pending_signup_id": pending_signup_id},
        )
    except Exception as exc:
        logger.error("Failed to create Stripe customer for %s: %s", admin_email, exc)
        return JSONResponse(
            status_code=400,
            content={"detail": "Could not create payment profile. Please try again."},
        )

    # 4. Create Organisation (status=active) and User in DB
    plan_id = _uuid.UUID(pending["plan_id"])
    billing_interval = pending.get("billing_interval", "monthly")

    # Look up plan for storage_quota_gb and interval config
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    storage_quota_gb = plan.storage_quota_gb if plan else 5

    # Look up trade_category_id from trade_family_slug (if provided)
    trade_category_id = None
    trade_family_slug = pending.get("trade_family_slug")
    if trade_family_slug:
        from app.modules.trade_categories.models import TradeFamily, TradeCategory
        family_result = await db.execute(
            select(TradeFamily).where(
                TradeFamily.slug == trade_family_slug,
                TradeFamily.is_active == True,
            )
        )
        family = family_result.scalar_one_or_none()
        if family:
            cat_result = await db.execute(
                select(TradeCategory.id).where(
                    TradeCategory.family_id == family.id,
                    TradeCategory.is_active == True,
                ).order_by(TradeCategory.display_name).limit(1)
            )
            cat_row = cat_result.first()
            if cat_row:
                trade_category_id = cat_row[0]

    # Build initial settings with country_code if provided
    initial_settings = {}
    country_code = pending.get("country_code")
    if country_code:
        initial_settings["address_country"] = country_code

    org = Organisation(
        name=pending["org_name"],
        plan_id=plan_id,
        status="active",
        billing_interval=billing_interval,
        stripe_customer_id=stripe_customer_id,
        storage_quota_gb=storage_quota_gb,
        trade_category_id=trade_category_id,
        country_code=country_code,
        settings=initial_settings,
    )
    db.add(org)
    await db.flush()

    # Auto-create default "Main" branch (Req 14.1, 14.2)
    from app.modules.organisations.service import create_default_main_branch
    await create_default_main_branch(db, org_id=org.id)

    # Hash the raw password from the pending signup data
    from app.modules.auth.password import hash_password as _hash_pw
    raw_password = pending.get("password", "")
    password_hash = _hash_pw(raw_password) if raw_password else pending.get("password_hash")

    admin_user = User(
        org_id=org.id,
        email=admin_email,
        first_name=pending.get("admin_first_name"),
        last_name=pending.get("admin_last_name"),
        role="org_admin",
        is_active=True,
        is_email_verified=False,
        password_hash=password_hash,
    )
    db.add(admin_user)
    await db.flush()

    # Link coupon to org so it appears in admin dashboard & billing
    _pending_coupon_code = pending.get("coupon_code")
    if _pending_coupon_code:
        from app.modules.organisations.service import _create_organisation_coupon
        await _create_organisation_coupon(
            db,
            org_id=org.id,
            coupon_code=_pending_coupon_code,
            now=datetime.now(timezone.utc),
        )

    # 5. Link payment to Stripe customer and save payment method
    try:
        pm_id = intent.payment_method
        if pm_id:
            # Attach the payment method to the new Stripe customer
            stripe_lib.PaymentMethod.attach(pm_id, customer=stripe_customer_id)
            # Set as default payment method for the customer
            stripe_lib.Customer.modify(
                stripe_customer_id,
                invoice_settings={"default_payment_method": pm_id},
            )
            # Update the PaymentIntent to link it to the customer
            # so Stripe shows the charge under this customer
            stripe_lib.PaymentIntent.modify(
                payment_intent_id,
                customer=stripe_customer_id,
            )

            pm_obj = stripe_lib.PaymentMethod.retrieve(pm_id)
            _card = getattr(pm_obj, "card", None)
            payment_method_record = OrgPaymentMethod(
                org_id=org.id,
                stripe_payment_method_id=pm_id,
                brand=getattr(_card, "brand", "unknown") if _card else "unknown",
                last4=getattr(_card, "last4", "0000") if _card else "0000",
                exp_month=getattr(_card, "exp_month", 0) if _card else 0,
                exp_year=getattr(_card, "exp_year", 0) if _card else 0,
                is_default=True,
                is_verified=True,
            )
            db.add(payment_method_record)
            await db.flush()
    except Exception as exc:
        logger.error(
            "Failed to save signup payment method for org %s: %s",
            org.id,
            exc,
        )

    # 5b. Set next_billing_date for paid plans (direct billing, no Stripe Subscription)
    try:
        from decimal import Decimal as _Dec
        from app.modules.billing.interval_pricing import (
            compute_interval_duration as _compute_interval_duration,
        )

        # Compute effective price for the selected billing interval
        interval_config = getattr(plan, "interval_config", None) or []
        discount_percent = _Dec("0")
        for ic in interval_config:
            if ic.get("interval") == billing_interval and ic.get("enabled"):
                discount_percent = _Dec(str(ic.get("discount_percent", 0)))
                break

        effective_price = _compute_eff(
            _Dec(str(plan.monthly_price_nzd)),
            billing_interval,
            discount_percent,
        )
        interval_amount_cents = int((effective_price * _Dec("100")).to_integral_value())

        if interval_amount_cents > 0:
            org.next_billing_date = datetime.now(timezone.utc) + _compute_interval_duration(billing_interval)
            await db.flush()
    except Exception as exc:
        logger.error(
            "Failed to set next_billing_date for org %s: %s",
            org.id,
            exc,
            exc_info=True,
        )

    # 6. Delete Pending_Signup from Redis (prevent replay)
    await delete_pending_signup(pending_signup_id)

    ip_address = _get_client_ip(request)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=org.id,
        user_id=admin_user.id,
        action="org.payment_confirmed",
        entity_type="organisation",
        entity_id=org.id,
        after_value={
            "name": pending["org_name"],
            "plan_id": str(plan_id),
            "plan_name": pending.get("plan_name", ""),
            "billing_interval": billing_interval,
            "status": "active",
            "admin_email": admin_email,
            "admin_user_id": str(admin_user.id),
            "stripe_customer_id": stripe_customer_id,
            "payment_intent_id": payment_intent_id,
            "ip_address": ip_address,
        },
        ip_address=ip_address,
    )

    # Generate verification token using the standard email_verify: key
    from app.modules.auth.service import create_email_verification_token

    verification_token = await create_email_verification_token(
        admin_user.id, admin_email,
    )

    # 7. Send receipt email with verification link (Requirements 4.1, 4.2)
    origin = request.headers.get("origin") or ""
    from app.config import settings as _settings
    base_url = origin or _settings.frontend_base_url or "http://localhost"

    plan_name = pending.get("plan_name", "Paid Plan")
    payment_amount_cents = pending.get("payment_amount_cents", 0)
    plan_amount_cents = pending.get("plan_amount_cents", 0)
    gst_amount_cents = pending.get("gst_amount_cents", 0)
    gst_percentage = pending.get("gst_percentage", 0)
    processing_fee_cents = pending.get("processing_fee_cents", 0)
    user_name = f"{admin_first} {admin_last}".strip() or admin_email.split("@")[0]

    from app.modules.auth.service import send_receipt_email

    try:
        await send_receipt_email(
            db,
            email=admin_email,
            user_name=user_name,
            org_name=pending["org_name"],
            plan_name=plan_name,
            amount_cents=payment_amount_cents,
            plan_amount_cents=plan_amount_cents,
            gst_amount_cents=gst_amount_cents,
            gst_percentage=gst_percentage,
            processing_fee_cents=processing_fee_cents,
            verification_token=verification_token,
            base_url=base_url,
        )
    except Exception as exc:
        logger.warning("Failed to send receipt email to %s: %s", admin_email, exc)

    await db.commit()

    return JSONResponse(
        content={
            "detail": "Payment confirmed. Your account is now active.",
            "status": "active",
            "organisation_id": str(org.id),
            "admin_email": admin_email,
        },
    )



@router.get(
    "/stripe-publishable-key",
    summary="Get the Stripe publishable key for the frontend",
)
async def get_stripe_publishable_key():
    """Return the Stripe publishable key so the frontend can initialise Stripe.js.

    This is a public endpoint — the publishable key is not secret.
    """
    from app.integrations.stripe_billing import get_stripe_publishable_key as _get_key

    key = await _get_key()
    if not key:
        return JSONResponse(
            status_code=503,
            content={"detail": "Stripe is not configured"},
        )
    return {"publishable_key": key}


# ---------------------------------------------------------------------------
# Signup email verification (Req 8.7)
# ---------------------------------------------------------------------------


@router.post(
    "/verify-signup-email",
    responses={
        400: {"description": "Invalid or expired token"},
    },
    summary="Verify signup email address",
)
async def verify_signup_email_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify a signup email using the token from the verification link.

    Marks the email as verified and returns a JWT pair so the user
    is logged in immediately.
    """
    from app.modules.auth.service import verify_signup_email

    body = await request.json()
    token = body.get("token")
    if not token:
        return JSONResponse(
            status_code=400,
            content={"detail": "Verification token is required"},
        )

    ip_address = _get_client_ip(request)
    user_agent = request.headers.get("user-agent")
    device_type, browser = _parse_user_agent(user_agent)

    try:
        result = await verify_signup_email(
            db,
            token=token,
            ip_address=ip_address,
            device_type=device_type,
            browser=browser,
        )
        await db.commit()
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
        )

    response = JSONResponse(
        content={
            "message": "Email verified successfully",
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
    "/resend-verification",
    summary="Resend signup verification email",
)
async def resend_verification_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Resend the verification email for a user who hasn't verified yet.

    Always returns success to avoid leaking whether the email exists.
    """
    from app.modules.auth.service import resend_verification_email

    body = await request.json()
    email = body.get("email", "").strip().lower()
    if not email:
        return JSONResponse(
            status_code=400,
            content={"detail": "Email is required"},
        )

    # Use the request origin to build the verification URL
    origin = request.headers.get("origin") or request.headers.get("referer", "")
    # Strip path from referer to get base URL
    if origin and "/" in origin.split("//", 1)[-1]:
        origin = origin.rsplit("/", 1)[0] if not origin.endswith("/") else origin.rstrip("/")

    from app.config import settings
    base_url = origin or settings.frontend_base_url or "http://localhost"

    result = await resend_verification_email(
        db,
        email=email,
        base_url=base_url,
    )
    await db.commit()

    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# User profile endpoints
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserProfileResponse)
async def get_profile(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return the current user's profile."""
    user = await _get_current_user(request, db)
    # Query verified MFA methods from normalised table
    from sqlalchemy import select
    from app.modules.auth.models import UserMfaMethod
    result = await db.execute(
        select(UserMfaMethod.method).where(
            UserMfaMethod.user_id == user.id,
            UserMfaMethod.verified.is_(True),
        )
    )
    verified_methods = [row[0] for row in result.all()]
    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        mfa_methods=verified_methods,
        has_password=user.password_hash is not None,
    )


@router.put("/me", response_model=UserProfileResponse)
async def update_profile(
    payload: UpdateProfileRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Update the current user's name."""
    user = await _get_current_user(request, db)

    if payload.first_name is not None:
        user.first_name = payload.first_name.strip()[:100] if payload.first_name.strip() else None
    if payload.last_name is not None:
        user.last_name = payload.last_name.strip()[:100] if payload.last_name.strip() else None

    await db.flush()

    # Query verified MFA methods from normalised table
    from sqlalchemy import select
    from app.modules.auth.models import UserMfaMethod
    result = await db.execute(
        select(UserMfaMethod.method).where(
            UserMfaMethod.user_id == user.id,
            UserMfaMethod.verified.is_(True),
        )
    )
    verified_methods = [row[0] for row in result.all()]
    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        mfa_methods=verified_methods,
        has_password=user.password_hash is not None,
    )


@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Change the current user's password.

    Validates against the org's password policy, checks password history,
    records the new hash in history, and updates password_changed_at.
    """
    from app.modules.auth.password import hash_password, verify_password
    from app.modules.auth.password_policy import (
        check_password_history,
        record_password_in_history,
        validate_password_against_policy,
    )
    from app.modules.auth.security_settings_service import get_security_settings

    user = await _get_current_user(request, db)

    # Must have an existing password to change it
    if not user.password_hash:
        return JSONResponse(
            status_code=400,
            content={"detail": "Account does not have a password set. Use password reset instead."},
        )

    if not verify_password(payload.current_password, user.password_hash):
        return JSONResponse(
            status_code=400,
            content={"detail": "Current password is incorrect."},
        )

    if payload.current_password == payload.new_password:
        return JSONResponse(
            status_code=400,
            content={"detail": "New password must be different from current password."},
        )

    # Validate against org password policy
    org_settings = await get_security_settings(db, user.org_id) if user.org_id else None
    if org_settings:
        policy = org_settings.password_policy
        errors = validate_password_against_policy(payload.new_password, policy)
        if errors:
            return JSONResponse(
                status_code=400,
                content={"detail": "; ".join(errors)},
            )

        # Check password history
        if policy.history_count > 0:
            history_match = await check_password_history(
                db, user.id, payload.new_password, policy.history_count,
            )
            if history_match:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Password was used recently. Choose a password you haven't used in the last {policy.history_count} changes."},
                )
    else:
        # Fallback: basic strength check (same rules as frontend)
        pw = payload.new_password
        if (
            len(pw) < 8
            or not any(c.isupper() for c in pw)
            or not any(c.islower() for c in pw)
            or not any(c.isdigit() for c in pw)
            or all(c.isalnum() for c in pw)
        ):
            return JSONResponse(
                status_code=400,
                content={"detail": "Password does not meet strength requirements."},
            )

    new_hash = hash_password(payload.new_password)
    user.password_hash = new_hash

    # Update password_changed_at timestamp
    from datetime import datetime, timezone
    user.password_changed_at = datetime.now(timezone.utc)

    # Record in password history
    if org_settings and org_settings.password_policy.history_count > 0:
        await record_password_in_history(db, user.id, new_hash)

    return ChangePasswordResponse(message="Password changed successfully.")


# ---------------------------------------------------------------------------
# Email change endpoints
# ---------------------------------------------------------------------------

@router.post("/email/change/request", response_model=EmailChangeResponse)
async def email_change_request(
    payload: EmailChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Request an email change. Sends a 6-digit OTP to the new email address.

    The change is not applied until the OTP is verified via
    ``POST /auth/email/change/verify``.
    """
    import json
    import secrets

    from sqlalchemy import select

    from app.core.redis import redis_pool
    from app.modules.auth.models import User
    from app.modules.auth.mfa_service import _generate_otp_code, _send_email_otp

    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    new_email = payload.new_email.lower().strip()

    # Validate: new email must differ from current
    if new_email == user.email.lower():
        return JSONResponse(
            status_code=400,
            content={"detail": "New email must be different from your current email."},
        )

    # Validate: new email must not already be taken
    existing = await db.execute(
        select(User.id).where(User.email == new_email)
    )
    if existing.scalar_one_or_none() is not None:
        return JSONResponse(
            status_code=400,
            content={"detail": "This email address is already in use."},
        )

    # Generate OTP and store in Redis
    code = _generate_otp_code()
    ttl = 600  # 10 minutes
    key = f"email_change:{user.id}"
    await redis_pool.setex(key, ttl, json.dumps({"email": new_email, "code": code}))

    # Send OTP to the NEW email
    await _send_email_otp(db, new_email, code)

    return EmailChangeResponse(
        message="Verification code sent to new email",
        expires_in=ttl,
    )


@router.post("/email/change/verify", response_model=UserProfileResponse)
async def email_change_verify(
    payload: EmailChangeVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Verify the OTP and apply the email change.

    On success the user's email is updated immediately and the pending
    change is removed from Redis.
    """
    import json
    import secrets

    from sqlalchemy import select

    from app.core.audit import write_audit_log
    from app.core.redis import redis_pool
    from app.modules.auth.models import User, UserMfaMethod

    try:
        user = await _get_current_user(request, db)
    except (ValueError, Exception):
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )

    # Retrieve pending email change from Redis
    key = f"email_change:{user.id}"
    raw = await redis_pool.get(key)
    if raw is None:
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid or expired verification code"},
        )

    data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    stored_code = data.get("code", "")
    new_email = data.get("email", "")

    # Timing-safe comparison
    if not secrets.compare_digest(payload.code, stored_code):
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid or expired verification code"},
        )

    # Race-condition check: ensure new email is still available
    existing = await db.execute(
        select(User.id).where(User.email == new_email, User.id != user.id)
    )
    if existing.scalar_one_or_none() is not None:
        await redis_pool.delete(key)
        return JSONResponse(
            status_code=400,
            content={"detail": "This email address is already in use."},
        )

    old_email = user.email

    # Apply the email change
    user.email = new_email
    await db.flush()
    await db.refresh(user)

    # Delete the pending change from Redis
    await redis_pool.delete(key)

    # Audit log
    await write_audit_log(
        session=db,
        org_id=user.org_id,
        user_id=user.id,
        action="auth.email_changed",
        entity_type="user",
        entity_id=user.id,
        before_value={"email": old_email},
        after_value={"email": new_email},
        ip_address=getattr(request.state, "client_ip", None),
        device_info=request.headers.get("user-agent"),
    )

    # Return updated profile
    result = await db.execute(
        select(UserMfaMethod.method).where(
            UserMfaMethod.user_id == user.id,
            UserMfaMethod.verified.is_(True),
        )
    )
    verified_methods = [row[0] for row in result.all()]
    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        mfa_methods=verified_methods,
        has_password=user.password_hash is not None,
    )
