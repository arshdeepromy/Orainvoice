"""Pydantic schemas for org-level security settings."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Policy schemas
# ---------------------------------------------------------------------------

class MfaPolicy(BaseModel):
    mode: Literal["optional", "mandatory_all", "mandatory_admins_only"] = "optional"
    excluded_user_ids: list[UUID] = []


class PasswordPolicy(BaseModel):
    min_length: int = Field(default=8, ge=8, le=128)
    require_uppercase: bool = False
    require_lowercase: bool = False
    require_digit: bool = False
    require_special: bool = False
    expiry_days: int = Field(default=0, ge=0, le=365)
    history_count: int = Field(default=0, ge=0, le=24)


class LockoutPolicy(BaseModel):
    temp_lock_threshold: int = Field(default=5, ge=3, le=10)
    temp_lock_minutes: int = Field(default=15, ge=5, le=60)
    permanent_lock_threshold: int = Field(default=10, ge=5, le=20)


class SessionPolicy(BaseModel):
    access_token_expire_minutes: int = Field(default=30, ge=5, le=120)
    refresh_token_expire_days: int = Field(default=7, ge=1, le=90)
    max_sessions_per_user: int = Field(default=5, ge=1, le=10)
    excluded_user_ids: list[UUID] = []
    excluded_roles: list[str] = []


# ---------------------------------------------------------------------------
# Composite settings schemas
# ---------------------------------------------------------------------------

class OrgSecuritySettings(BaseModel):
    mfa_policy: MfaPolicy = MfaPolicy()
    password_policy: PasswordPolicy = PasswordPolicy()
    lockout_policy: LockoutPolicy = LockoutPolicy()
    session_policy: SessionPolicy = SessionPolicy()


class SecuritySettingsUpdate(BaseModel):
    """Partial update — all fields optional."""

    mfa_policy: MfaPolicy | None = None
    password_policy: PasswordPolicy | None = None
    lockout_policy: LockoutPolicy | None = None
    session_policy: SessionPolicy | None = None


class LockoutPolicyUpdate(LockoutPolicy):
    @model_validator(mode="after")
    def permanent_gt_temporary(self) -> "LockoutPolicyUpdate":
        if self.permanent_lock_threshold <= self.temp_lock_threshold:
            raise ValueError(
                "permanent_lock_threshold must be greater than temp_lock_threshold"
            )
        return self


# ---------------------------------------------------------------------------
# Custom roles schemas
# ---------------------------------------------------------------------------

class CustomRoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    permissions: list[str]


class CustomRoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    permissions: list[str] | None = None


class RoleResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    slug: str
    description: str | None
    permissions: list[str]
    is_system: bool
    user_count: int
    created_at: datetime


# ---------------------------------------------------------------------------
# Permission schemas
# ---------------------------------------------------------------------------

class PermissionItem(BaseModel):
    key: str
    label: str


class PermissionGroup(BaseModel):
    module_slug: str
    module_name: str
    permissions: list[PermissionItem]


# ---------------------------------------------------------------------------
# Audit log schemas
# ---------------------------------------------------------------------------

class AuditLogFilters(BaseModel):
    start_date: datetime | None = None
    end_date: datetime | None = None
    action: str | None = None
    user_id: UUID | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25)


class AuditLogEntry(BaseModel):
    id: UUID
    timestamp: datetime
    user_email: str | None
    action: str
    action_description: str
    ip_address: str | None
    browser: str | None
    os: str | None
    entity_type: str | None
    entity_id: str | None
    before_value: dict | None
    after_value: dict | None


class AuditLogPage(BaseModel):
    items: list[AuditLogEntry]
    total: int
    page: int
    page_size: int
    truncated: bool = False


class PlatformAuditLogEntry(AuditLogEntry):
    """Audit log entry enriched with organisation name for platform-wide view."""
    org_name: str | None = None


class PlatformAuditLogPage(BaseModel):
    items: list[PlatformAuditLogEntry]
    total: int
    page: int
    page_size: int
    truncated: bool = False


# ---------------------------------------------------------------------------
# Action description mapping
# ---------------------------------------------------------------------------

ACTION_DESCRIPTIONS: dict[str, str] = {
    "auth.login_success": "Successful Login",
    "auth.login_failed_invalid_password": "Failed Login — Invalid Password",
    "auth.login_failed_unknown_email": "Failed Login — Unknown Email",
    "auth.login_failed_account_inactive": "Failed Login — Account Inactive",
    "auth.login_failed_account_locked": "Failed Login — Account Locked",
    "auth.login_failed_ip_blocked": "Failed Login — IP Blocked",
    "auth.mfa_verified": "MFA Verified",
    "auth.mfa_failed": "MFA Failed",
    "auth.password_changed": "Password Changed",
    "auth.password_reset": "Password Reset",
    "auth.session_revoked": "Session Revoked",
    "auth.all_sessions_revoked": "All Sessions Revoked",
    "org.mfa_policy_updated": "MFA Policy Updated",
    "org.security_settings_updated": "Security Settings Updated",
    "org.custom_role_created": "Custom Role Created",
    "org.custom_role_updated": "Custom Role Updated",
    "org.custom_role_deleted": "Custom Role Deleted",
}
