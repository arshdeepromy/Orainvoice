"""FastAPI dependencies for the Payroll_Tax_Settings org tier.

The org tier is mounted under ``/api/v2/payroll-tax-settings`` — a prefix that is
**not** under ``/api/v2/admin/``. ``RBACMiddleware`` therefore does *not* pre-empt
the org-level roles (``org_admin``, ``branch_admin``, ``salesperson``,
``location_manager``) or ``global_admin`` on this prefix; they all reach the route.

:func:`audit_denied_tax_access` is the **sole** authorisation gate on the org
routes. Modelled on ``page_editor``'s ``require_global_admin_with_audit``, it:

1. requires authentication;
2. requires ``role == "org_admin"``;
3. on a role mismatch, writes a ``payroll_tax.org.access_denied`` Audit_Log entry
   **out-of-band** (a fresh ``async_session_factory()`` session) and then raises
   ``403`` (Req 3.5).

The out-of-band session is essential: when a ``403`` is raised the request session
may already have been rolled back, so reusing it would lose the audit row. The
``audit_log`` table has **no RLS** (it is append-only, see migration 0007/0008), so
the out-of-band write does not need an org GUC set.

**Do NOT also attach** ``require_role("org_admin")`` to the org routes: if it runs
before this dependency it raises ``403`` first and the denial audit is skipped. This
dependency performs the role check itself and is the only gate the routes need.

The audit write is wrapped in ``try/except`` so an audit failure can never convert a
correct ``403`` into a ``500``.

**Validates: Requirements 3.5 — unauthorised org tax-settings access is rejected and
audited.**
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, Request

from app.core.audit import write_audit_log
from app.core.database import async_session_factory
from app.modules.auth.rbac import ORG_ADMIN

logger = logging.getLogger(__name__)

__all__ = ["audit_denied_tax_access"]


def _coerce_uuid(raw: object) -> uuid.UUID | None:
    """Best-effort coercion of a request-state id to ``uuid.UUID``.

    Returns ``None`` for missing or malformed values so a bad id never breaks the
    denial path (we still raise the 403; we just record a null id).
    """
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


async def _audit_org_denial_out_of_band(
    request: Request,
    *,
    user_id: uuid.UUID | None,
    org_id: uuid.UUID | None,
    role: object,
) -> None:
    """Record a ``payroll_tax.org.access_denied`` entry using a fresh session.

    The request session may already be rolled back when the 403 is raised, so we
    open our own session/transaction to guarantee the audit row lands. Any failure
    here is swallowed (logged) so the audit can never turn a correct 403 into a 500.
    """
    ip_address = getattr(request.state, "client_ip", None)
    user_agent = request.headers.get("user-agent")
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await write_audit_log(
                    session=session,
                    action="payroll_tax.org.access_denied",
                    entity_type="org_tax_settings",
                    org_id=org_id,
                    user_id=user_id,
                    after_value={
                        "path": request.url.path,
                        "method": request.method,
                        "role": role,
                    },
                    ip_address=ip_address,
                    device_info=user_agent,
                )
    except Exception:  # pragma: no cover - audit must never break the request
        logger.exception(
            "Failed to write out-of-band org access-denied audit for path=%s",
            request.url.path,
        )


async def audit_denied_tax_access(request: Request) -> None:
    """Sole org-tier gate: require ``org_admin``; audit + 403 on denial (Req 3.5).

    Allows the request through only when the authenticated user's role is
    ``org_admin``. For any other authenticated role it writes a
    ``payroll_tax.org.access_denied`` Audit_Log entry out-of-band and raises ``403``.
    Unauthenticated requests raise ``401`` (no audit — there is no actor to record
    and ``RBACMiddleware``/auth already gate these).

    This dependency must be the **only** authorisation dependency on the org routes;
    pairing it with ``require_role("org_admin")`` would risk the role check raising
    ``403`` before the denial is audited.
    """
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "role", None)

    if not user_id or not role:
        raise HTTPException(status_code=401, detail="Authentication required")

    if role != ORG_ADMIN:
        await _audit_org_denial_out_of_band(
            request,
            user_id=_coerce_uuid(user_id),
            org_id=_coerce_uuid(getattr(request.state, "org_id", None)),
            role=role,
        )
        raise HTTPException(
            status_code=403,
            detail="Access denied. Required role(s): org_admin",
        )
