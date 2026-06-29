"""Shared FastAPI dependencies for the esignatures module.

Two reusable dependencies the ``/api/v2/esign`` router composes onto its
routes:

* :data:`require_esign_sender` — RBAC gate restricting sends/voids to the
  permitted Org_Sender roles (``org_admin`` / ``branch_admin`` /
  ``location_manager``) via :func:`app.modules.auth.rbac.require_role`; any
  other role gets HTTP 403 (R12.1/12.2/12.3). NB: the ``manager`` role does
  **not** exist in this codebase — the permitted roles are exactly the three
  constants above.
* :func:`require_esign_module` — module-enablement gate returning HTTP 403 when
  the ``esignatures`` module is disabled for the requesting org (R2.2). This
  mirrors the *pattern* of the staff module's ``_require_staff_management_module``
  router-level dependency, but deliberately returns **403** (not the staff
  module's 404) and uses the single canonical slug ``esignatures`` everywhere
  (Task 7.3) — there is no endpoint-map-value vs registry/``is_enabled`` slug
  split.

The runtime module gate is the **module only**: it consults
:meth:`app.core.modules.ModuleService.is_enabled` (backed by ``org_modules``),
never ``feature_flags``.

Refs: requirements 2.2, 12.1, 12.2, 12.3.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.modules import ModuleService
from app.modules.auth.rbac import (
    BRANCH_ADMIN,
    LOCATION_MANAGER,
    ORG_ADMIN,
    require_role,
)
from app.modules.esignatures.errors import (
    CODE_MODULE_DISABLED,
    esign_error,
)

#: The single canonical module slug, used identically by the MODULE_ENDPOINT_MAP
#: entry, the module_registry seed, this router-level dependency, and the
#: frontend ``isEnabled('esignatures')`` check (Task 7.3 slug-consistency rule).
ESIGN_MODULE_SLUG = "esignatures"


#: RBAC gate for sending / voiding agreements (R12). The ``manager`` role does
#: not exist in this codebase; the permitted Org_Sender roles are exactly
#: ``org_admin``, ``branch_admin`` and ``location_manager``. ``require_role``
#: returns a ready-to-use ``Depends(...)`` (raising 403 for any other role), so
#: this is consumed directly as ``dependencies=[require_esign_sender]`` or
#: ``Depends`` is not re-wrapped around it.
require_esign_sender = require_role(ORG_ADMIN, BRANCH_ADMIN, LOCATION_MANAGER)


def _get_org_id(request: Request) -> UUID:
    """Resolve the requesting organisation id from request state (else 401)."""
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        raise HTTPException(status_code=401, detail="Organisation context required")
    return UUID(str(org_id))


async def require_esign_module(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Raise HTTP 403 when the ``esignatures`` module is disabled for the org.

    Router-level defence-in-depth for R2.2: the ``ModuleMiddleware`` (which
    inspects the ``MODULE_ENDPOINT_MAP`` ``"/api/v2/esign"`` prefix) fails
    **open** on internal errors, so esign routes additionally carry this
    dependency. It resolves the org from request state and calls
    :meth:`ModuleService.is_enabled` with the canonical slug ``esignatures``.

    The 403 body uses the module's humanized ``{ message, code }`` shape with
    code ``module_disabled``.
    """
    org_id = _get_org_id(request)
    service = ModuleService(db)
    if not await service.is_enabled(str(org_id), ESIGN_MODULE_SLUG):
        raise HTTPException(
            status_code=403,
            detail=esign_error(CODE_MODULE_DISABLED).model_dump(),
        )
