"""HTTP routers for the Payroll_Tax_Settings module.

Two routers are exported and mounted in ``app/main.py`` (task 8.3):

* :data:`platform_router` — the Global_Admin platform tier, mounted under
  ``/api/v2/admin/platform-tax-default``. Effective authorisation is
  ``global_admin``, enforced by ``RBACMiddleware`` (the ``/api/v2/admin/*`` path
  gate) **plus** a defence-in-depth ``require_role("global_admin")`` on each
  route. The denial audit for this tier (Req 2.3) is emitted from the middleware
  layer (task 8.1), because ``RBACMiddleware`` rejects non-``global_admin`` roles
  before any route dependency runs — there is therefore deliberately **no**
  route-level denial audit here.

* :data:`org_router` — the Org_Admin organisation tier, mounted under
  ``/api/v2/payroll-tax-settings``. This prefix is **not** under
  ``/api/v2/admin/``, so ``RBACMiddleware`` does not pre-empt org-level roles or
  ``global_admin``; they all reach the route. Authorisation + the denial audit
  (Req 3.5) are handled by the **single** gate
  :func:`~app.modules.payroll_tax.dependencies.audit_denied_tax_access`, which
  performs the ``org_admin`` check itself, audits denials out-of-band, and raises
  ``403``. ``require_role("org_admin")`` is intentionally **not** also attached —
  pairing them risks the role check raising ``403`` before the denial is audited.

Both tiers delegate all persistence, validation, and audit logic to
:mod:`app.modules.payroll_tax.service`. The service raises ``HTTPException(422)``
with a per-field ``detail`` list (``[{"field", "message"}]``) on validation
failure, which FastAPI surfaces to the client unchanged.

Route paths are defined **relative** to the mount prefixes, so the bare
collection routes use ``""`` (matching the exact prefix with no trailing slash).

**Validates: Requirements 2.1, 2.2, 2.3, 3.2, 3.5, 4.3, 9.1, 9.2.**
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.modules.auth.rbac import require_role
from app.modules.payroll_tax.dependencies import audit_denied_tax_access
from app.modules.payroll_tax.models import PlatformTaxDefault
from app.modules.payroll_tax.schemas import (
    OrgOverridesUpdate,
    OrgTaxSettingsView,
    PlatformTaxDefaultUpdate,
    PlatformTaxDefaultView,
)
from app.modules.payroll_tax.service import (
    get_org_resolved_view,
    get_platform_default,
    reset_org_all,
    reset_org_field,
    set_org_overrides,
    update_platform_default,
)

__all__ = ["platform_router", "org_router"]

platform_router = APIRouter()
org_router = APIRouter()


# ---------------------------------------------------------------------------
# Request-state helpers
# ---------------------------------------------------------------------------


def _get_user_id(request: Request) -> uuid.UUID:
    """Extract the authenticated user id from the request, or raise ``401``."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uuid.UUID(str(user_id))


def _get_org_id(request: Request) -> uuid.UUID:
    """Extract the org id from the request, or raise ``401`` when absent."""
    org_id = getattr(request.state, "org_id", None)
    if not org_id:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return uuid.UUID(str(org_id))


def _platform_view(row: PlatformTaxDefault) -> PlatformTaxDefaultView:
    """Project a :class:`PlatformTaxDefault` ORM row into its editable view.

    The nested tax structures live in the JSONB ``config`` document; the
    display-only ``tax_year_label`` is a dedicated column. ``TaxDecimal``'s
    before-validator rehydrates the stored JSON numbers/strings into exact
    ``Decimal`` values during ``model_validate``.
    """
    data: dict = dict(row.config or {})
    data["tax_year_label"] = row.tax_year_label
    data["updated_at"] = row.updated_at
    data["updated_by"] = row.updated_by
    return PlatformTaxDefaultView.model_validate(data)


# ===========================================================================
# Platform tier (Global_Admin) — /api/v2/admin/platform-tax-default
# ===========================================================================


@platform_router.get(
    "",
    response_model=PlatformTaxDefaultView,
    dependencies=[require_role("global_admin")],
    summary="Get the editable platform tax default",
)
async def get_platform_tax_default(
    db: AsyncSession = Depends(get_db_session),
) -> PlatformTaxDefaultView:
    """Return the single Platform_Tax_Default with every editable field (Req 2.1)."""
    row = await get_platform_default(db)
    return _platform_view(row)


@platform_router.put(
    "",
    response_model=PlatformTaxDefaultView,
    dependencies=[require_role("global_admin")],
    summary="Update the platform tax default",
)
async def update_platform_tax_default(
    body: PlatformTaxDefaultUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> PlatformTaxDefaultView:
    """Validate and persist a Global_Admin change to the platform default.

    On success the change is audited with prior/new values (Req 2.2, 2.4); on a
    validation failure the service raises ``HTTPException(422)`` with per-field
    detail and persists nothing.
    """
    row = await update_platform_default(
        db,
        fields=body.model_dump(),
        user_id=_get_user_id(request),
        request=request,
    )
    return _platform_view(row)


# ===========================================================================
# Org tier (Org_Admin) — /api/v2/payroll-tax-settings
# ===========================================================================


@org_router.get(
    "",
    response_model=OrgTaxSettingsView,
    dependencies=[Depends(audit_denied_tax_access)],
    summary="Get the org's effective tax settings with inheritance flags",
)
async def get_org_tax_settings(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgTaxSettingsView:
    """Return the org's effective tax view + per-field inherited/override flags (Req 4.3)."""
    return await get_org_resolved_view(db, org_id=_get_org_id(request))


@org_router.put(
    "",
    response_model=OrgTaxSettingsView,
    dependencies=[Depends(audit_denied_tax_access)],
    summary="Set sparse org tax overrides",
)
async def update_org_tax_settings(
    body: OrgOverridesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgTaxSettingsView:
    """Validate and persist a sparse set of org overrides (Req 3.2, 3.3).

    Only fields explicitly present in the request body are treated as overrides
    (``exclude_unset=True``); absent fields continue to inherit the platform
    default. Validation failures surface as ``HTTPException(422)`` per-field.
    """
    return await set_org_overrides(
        db,
        org_id=_get_org_id(request),
        fields=body.model_dump(exclude_unset=True),
        user_id=_get_user_id(request),
        request=request,
    )


@org_router.delete(
    "/{field}",
    response_model=OrgTaxSettingsView,
    dependencies=[Depends(audit_denied_tax_access)],
    summary="Reset a single tax field to inherit the platform default",
)
async def reset_org_tax_field(
    field: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgTaxSettingsView:
    """Remove one override so the field inherits the platform default (Req 9.1, 9.3)."""
    return await reset_org_field(
        db,
        org_id=_get_org_id(request),
        field=field,
        user_id=_get_user_id(request),
        request=request,
    )


@org_router.delete(
    "",
    response_model=OrgTaxSettingsView,
    dependencies=[Depends(audit_denied_tax_access)],
    summary="Reset all tax fields to inherit the platform default",
)
async def reset_org_tax_all(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> OrgTaxSettingsView:
    """Remove all overrides so every field inherits the platform default (Req 9.2)."""
    return await reset_org_all(
        db,
        org_id=_get_org_id(request),
        user_id=_get_user_id(request),
        request=request,
    )
