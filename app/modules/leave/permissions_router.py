"""Family-violence leave-view permission management router.

Mounted at ``/api/v2/permissions/fv-leave-view`` (see
:mod:`app.main`). Surfaces three endpoints used by the
``Settings → People → Permissions`` page (D11) so org owners can grant
or revoke the ``leave.fv_view`` permission on a per-user basis.

Endpoints:

| Path                     | Method | Purpose                                |
|--------------------------|--------|----------------------------------------|
| ``""``                   | GET    | List org users + current FV-view state |
| ``"/{user_id}/grant"``   | POST   | Grant ``leave.fv_view`` to a user      |
| ``"/{user_id}/revoke"``  | POST   | Revoke ``leave.fv_view`` from a user   |

All three are :func:`_require_org_admin` per design §9.1 — only the
org owner / org admins may modify confidential-leave visibility. The
underlying helpers in :mod:`app.modules.auth.permission_overrides`
handle SELECT-then-INSERT-or-UPDATE idempotency and write audit rows
under ``permission_override.created`` / ``.updated`` / ``.deleted``.

Cross-org grants are blocked by verifying the target ``user_id``'s
``org_id`` matches the caller's ``request.state.org_id`` before any
mutation. The list endpoint scopes the user query by ``org_id``
identically.

The list endpoint returns ALL active org users (not just those with
the override) so the UI can render a checkbox per user — matches the
design §9.1 wireframe.

**Validates: R4.9, design §9.1 — Staff Management Phase 2 task B6a**
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.models import User
from app.modules.auth.permission_overrides import (
    UserPermissionOverride,
    create_or_update_permission_override,
    delete_permission_override,
)
from app.modules.leave.visibility import FV_LEAVE_VIEW_PERMISSION

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth + module gating helpers — mirror the patterns in
# ``app/modules/leave/router.py`` so the two surfaces behave
# identically. Re-defining (rather than importing) keeps the
# dependency graph flat: this router depends only on auth + db.
# If the helpers in the leave router change, update both copies.
# ---------------------------------------------------------------------------


def _get_org_id(request: Request) -> UUID:
    """Resolve the requesting organisation UUID from middleware state.

    AuthMiddleware populates ``request.state.org_id`` as a string. Raise
    HTTP 401 when the header is missing — matches the existing leave +
    staff routers so the frontend's error-toast logic works unchanged.
    """
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


def _get_user_id(request: Request) -> UUID:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="User context required")
    return UUID(str(user_id))


def _get_user_role(request: Request) -> str:
    return str(getattr(request.state, "role", "") or "")


async def _require_staff_management_module(
    request: Request, db: AsyncSession
) -> None:
    """Raise 404 ``not_enabled`` when ``staff_management`` is disabled
    for the requesting org. Identical semantics to the helper in
    ``app/modules/leave/router.py`` so the frontend's degrade-gracefully
    logic stays uniform across the two surfaces.
    """
    from app.core.modules import ModuleService

    org_id = _get_org_id(request)
    service = ModuleService(db)
    if not await service.is_enabled(str(org_id), "staff_management"):
        raise HTTPException(
            status_code=404,
            detail={"detail": "not_enabled", "module": "staff_management"},
        )


def _require_org_admin(request: Request) -> None:
    """Gate FV-permission endpoints to ``org_admin`` (or ``global_admin``
    operating in tenant context). Per design §9.1 only the org owner
    / org admins may grant or revoke the confidential-leave visibility
    permission.
    """
    role = _get_user_role(request)
    if role not in ("org_admin", "global_admin"):
        raise HTTPException(status_code=403, detail="org_admin role required")


async def _ensure_target_user_in_org(
    db: AsyncSession, user_id: UUID, org_id: UUID
) -> User:
    """Look up the target user and confirm same-org membership.

    Cross-org grants must be blocked: an org_admin in org A must not
    be able to grant a permission to a user in org B (the FV-view
    permission is checked org-locally by :mod:`app.modules.leave.visibility`,
    but the audit + governance story still requires us to refuse the
    grant outright).
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=404, detail={"detail": "user_not_found"}
        )
    if user.org_id != org_id:
        # 404 (not 403) — don't leak the existence of a user in
        # another org.
        raise HTTPException(
            status_code=404, detail={"detail": "user_not_found"}
        )
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List org users with their leave.fv_view permission status",
)
async def list_fv_leave_view_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Return every active user in the org plus their current
    ``leave.fv_view`` status.

    LEFT JOIN against ``user_permission_overrides`` filtered to
    ``permission_key = 'leave.fv_view' AND is_granted = true`` — users
    without a row resolve to ``has_fv_view = false`` (matching the
    semantics in :mod:`app.modules.auth.rbac`).

    The UI needs the full list (not just permitted users) so it can
    render an unchecked checkbox per user; toggling fires the grant /
    revoke endpoints below.
    """
    await _require_staff_management_module(request, db)
    _require_org_admin(request)
    org_id = _get_org_id(request)

    stmt = (
        select(User, UserPermissionOverride)
        .outerjoin(
            UserPermissionOverride,
            (UserPermissionOverride.user_id == User.id)
            & (UserPermissionOverride.permission_key == FV_LEAVE_VIEW_PERMISSION)
            & (UserPermissionOverride.is_granted.is_(True)),
        )
        .where(User.org_id == org_id, User.is_active.is_(True))
        .order_by(User.email)
    )

    result = await db.execute(stmt)
    rows = result.all()

    items: list[dict] = []
    for user, override in rows:
        first = user.first_name or ""
        last = user.last_name or ""
        name = f"{first} {last}".strip() or None
        items.append(
            {
                "user_id": str(user.id),
                "email": user.email,
                "name": name,
                "role": user.role,
                "has_fv_view": override is not None,
                "granted_at": (
                    override.created_at.isoformat()
                    if override is not None and override.created_at is not None
                    else None
                ),
            }
        )

    return {"items": items, "total": len(items)}


@router.post(
    "/{user_id}/grant",
    summary="Grant leave.fv_view to a user (org_admin only)",
)
async def grant_fv_leave_view(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Grant the ``leave.fv_view`` permission to a user in the same org.

    The existing helper handles idempotency: if the row already exists
    it's UPDATED (and audited under ``permission_override.updated``);
    if not, it's INSERTED (audited under ``permission_override.created``).
    """
    await _require_staff_management_module(request, db)
    _require_org_admin(request)
    org_id = _get_org_id(request)
    actor_id = _get_user_id(request)

    await _ensure_target_user_in_org(db, user_id, org_id)

    await create_or_update_permission_override(
        session=db,
        user_id=user_id,
        permission_key=FV_LEAVE_VIEW_PERMISSION,
        is_granted=True,
        granted_by=actor_id,
        org_id=org_id,
    )

    return {
        "user_id": str(user_id),
        "permission_key": FV_LEAVE_VIEW_PERMISSION,
        "is_granted": True,
    }


@router.post(
    "/{user_id}/revoke",
    summary="Revoke leave.fv_view from a user (org_admin only)",
)
async def revoke_fv_leave_view(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    """Revoke the ``leave.fv_view`` permission from a user in the same
    org. The helper deletes the row and writes an audit entry under
    ``permission_override.deleted``. If no override exists the call is
    a no-op (still returns 200) so the UI can issue the request
    optimistically without a pre-check.
    """
    await _require_staff_management_module(request, db)
    _require_org_admin(request)
    org_id = _get_org_id(request)
    actor_id = _get_user_id(request)

    await _ensure_target_user_in_org(db, user_id, org_id)

    await delete_permission_override(
        session=db,
        user_id=user_id,
        permission_key=FV_LEAVE_VIEW_PERMISSION,
        deleted_by=actor_id,
        org_id=org_id,
    )

    return {
        "user_id": str(user_id),
        "permission_key": FV_LEAVE_VIEW_PERMISSION,
        "deleted": True,
    }
