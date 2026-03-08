"""Pydantic request/response schemas for the auth module."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login request body."""
    email: EmailStr
    password: str
    remember_me: bool = False


class TokenResponse(BaseModel):
    """Successful login response with JWT pair."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MFARequiredResponse(BaseModel):
    """Response when MFA verification is needed before issuing tokens."""
    mfa_required: bool = True
    mfa_token: str
    mfa_methods: list[str]


class RefreshTokenRequest(BaseModel):
    """POST /api/v1/auth/token/refresh request body."""
    refresh_token: str


class GoogleLoginRequest(BaseModel):
    """POST /api/v1/auth/login/google request body."""
    code: str
    redirect_uri: str


class LoginErrorResponse(BaseModel):
    """Generic error returned for invalid credentials."""
    detail: str


# ---------------------------------------------------------------------------
# Passkey (WebAuthn) schemas
# ---------------------------------------------------------------------------

class PasskeyRegisterOptionsRequest(BaseModel):
    """POST /api/v1/auth/passkey/register/options request body."""
    device_name: str = "My Passkey"


class PasskeyRegisterOptionsResponse(BaseModel):
    """Registration options returned to the client for navigator.credentials.create()."""
    options: dict


class PasskeyRegisterVerifyRequest(BaseModel):
    """POST /api/v1/auth/passkey/register/verify request body."""
    credential: dict
    """Dict with keys: client_data_b64, attestation_b64, credential_id_b64"""


class PasskeyRegisterVerifyResponse(BaseModel):
    """Successful passkey registration response."""
    credential_id: str
    device_name: str


class PasskeyLoginOptionsRequest(BaseModel):
    """POST /api/v1/auth/passkey/login/options request body."""
    email: EmailStr


class PasskeyLoginOptionsResponse(BaseModel):
    """Authentication options returned to the client for navigator.credentials.get()."""
    options: dict


class PasskeyLoginVerifyRequest(BaseModel):
    """POST /api/v1/auth/passkey/login/verify request body."""
    email: EmailStr
    credential: dict
    """Dict with keys: client_data_b64, authenticator_b64, signature_b64, credential_id_b64"""


# ---------------------------------------------------------------------------
# MFA schemas
# ---------------------------------------------------------------------------

class MFAEnrolRequest(BaseModel):
    """POST /api/v1/auth/mfa/enrol request body."""
    method: str  # "totp", "sms", "email"
    phone_number: str | None = None


class MFAEnrolResponse(BaseModel):
    """MFA enrolment response with method-specific setup data."""
    method: str
    qr_uri: str | None = None
    message: str


class MFAVerifyRequest(BaseModel):
    """POST /api/v1/auth/mfa/verify request body."""
    mfa_token: str
    code: str
    method: str  # "totp", "sms", "email", "backup"


class MFABackupCodesResponse(BaseModel):
    """Response containing generated backup codes (one-time display)."""
    codes: list[str]



# ---------------------------------------------------------------------------
# Password check schemas (HIBP)
# ---------------------------------------------------------------------------

class PasswordCheckRequest(BaseModel):
    """POST /api/v1/auth/password/check request body."""
    password: str


class PasswordCheckResponse(BaseModel):
    """Response indicating whether a password is compromised."""
    compromised: bool
    message: str


# ---------------------------------------------------------------------------
# Session invalidation schemas
# ---------------------------------------------------------------------------

class InvalidateAllSessionsResponse(BaseModel):
    """Response from the 'This wasn't me' session invalidation endpoint."""
    sessions_revoked: int
    message: str


# ---------------------------------------------------------------------------
# Session management schemas
# ---------------------------------------------------------------------------

class SessionResponse(BaseModel):
    """Single active session in the list."""
    id: str
    device_type: str | None = None
    browser: str | None = None
    ip_address: str | None = None
    last_activity_at: datetime | None = None
    created_at: datetime | None = None
    current: bool = False


class SessionListResponse(BaseModel):
    """GET /api/v1/auth/sessions response."""
    sessions: list[SessionResponse]


class SessionTerminateResponse(BaseModel):
    """DELETE /api/v1/auth/sessions/{session_id} response."""
    message: str


# ---------------------------------------------------------------------------
# Password recovery schemas
# ---------------------------------------------------------------------------

class PasswordResetRequestSchema(BaseModel):
    """POST /api/v1/auth/password/reset-request request body."""
    email: EmailStr


class PasswordResetCompleteSchema(BaseModel):
    """POST /api/v1/auth/password/reset request body."""
    token: str
    new_password: str


class PasswordResetBackupCodeSchema(BaseModel):
    """POST /api/v1/auth/password/reset-backup request body."""
    email: EmailStr
    backup_code: str
    new_password: str


class PasswordResetResponse(BaseModel):
    """Uniform response for password reset operations."""
    message: str


# ---------------------------------------------------------------------------
# IP Allowlist schemas
# ---------------------------------------------------------------------------

class IPAllowlistUpdateRequest(BaseModel):
    """PUT /api/v1/org/settings/ip-allowlist request body."""
    ip_allowlist: list[str]
    """List of IP addresses or CIDR ranges to allow. Empty list disables allowlisting."""


class IPAllowlistResponse(BaseModel):
    """Response for IP allowlist operations."""
    ip_allowlist: list[str]
    message: str




# ---------------------------------------------------------------------------
# Email verification / invitation schemas (Task 4.11)
# ---------------------------------------------------------------------------

class InviteUserRequest(BaseModel):
    """POST /api/v1/auth/invite request body."""
    email: EmailStr
    role: str = "salesperson"  # "org_admin" or "salesperson"


class InviteUserResponse(BaseModel):
    """Response after creating an invitation."""
    message: str
    user_id: str
    invitation_expires_at: datetime


class VerifyEmailRequest(BaseModel):
    """POST /api/v1/auth/verify-email request body."""
    token: str
    password: str


class VerifyEmailResponse(BaseModel):
    """Response after verifying email and setting password."""
    message: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ResendInviteRequest(BaseModel):
    """POST /api/v1/auth/resend-invite request body."""
    email: EmailStr


class ResendInviteResponse(BaseModel):
    """Response after resending an invitation."""
    message: str
    invitation_expires_at: datetime


# ---------------------------------------------------------------------------
# Public plan schemas (public signup flow)
# ---------------------------------------------------------------------------

class PublicPlanResponse(BaseModel):
    """Single plan returned by the public plans endpoint."""
    id: str
    name: str
    monthly_price_nzd: Decimal
    trial_duration: int = 0
    trial_duration_unit: str = "days"
    sms_included: bool = False
    sms_included_quota: int = 0
    per_sms_cost_nzd: float = 0


class PublicPlanListResponse(BaseModel):
    """GET /api/v1/auth/plans response."""
    plans: list[PublicPlanResponse]
