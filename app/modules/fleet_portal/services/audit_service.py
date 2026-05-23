"""Portal audit log writer.

Implements: B2B Fleet Portal task 4A.7 — Requirements 21.15, 21.17.

Every state-changing fleet portal endpoint should call :func:`log_event`
with the appropriate ``action`` string from :data:`AUDIT_ACTIONS`. The
writer never raises — failures are logged at WARNING level so audit
issues never break the primary flow.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fleet_portal.models import PortalAuditLog

logger = logging.getLogger(__name__)


# Canonical action strings — keep this list in one place so log
# aggregation queries are easy to write. Add new actions here as the
# spec grows.
AUDIT_ACTIONS: dict[str, str] = {
    "login_success": "portal_auth.login_success",
    "login_failure": "portal_auth.login_failure",
    "logout": "portal_auth.logout",
    "password_reset_requested": "portal_auth.password_reset_requested",
    "password_reset_completed": "portal_auth.password_reset_completed",
    "password_changed": "portal_auth.password_changed",
    "invite_sent": "portal_auth.invite_sent",
    "invite_accepted": "portal_auth.invite_accepted",
    "account_locked": "portal_auth.account_locked",
    "account_unlocked": "portal_auth.account_unlocked",
    "session_revoked": "portal_auth.session_revoked",
    "mfa_enrolled": "portal_auth.mfa_enrolled",
    "mfa_disabled": "portal_auth.mfa_disabled",
    "mfa_verified": "portal_auth.mfa_verified",
    "mfa_failed": "portal_auth.mfa_failed",
    "impersonation_started": "portal_auth.impersonation_started",
    "impersonation_ended": "portal_auth.impersonation_ended",
    "security_settings_updated": "portal_admin.security_settings_updated",
}


async def log_event(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    action: str,
    portal_account_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one row to ``portal_audit_log``. Never raises."""
    try:
        row = PortalAuditLog(
            org_id=org_id,
            portal_account_id=portal_account_id,
            actor_user_id=actor_user_id,
            action=action,
            ip_address=ip,
            user_agent=(user_agent or "")[:500] or None,
            details=details,
        )
        db.add(row)
        await db.flush()
    except Exception as exc:  # noqa: BLE001 — defensive; audit must not break flow
        logger.warning(
            "fleet_portal.audit_log_failed action=%s org_id=%s err=%s",
            action,
            org_id,
            exc,
        )


__all__ = ["AUDIT_ACTIONS", "log_event"]
