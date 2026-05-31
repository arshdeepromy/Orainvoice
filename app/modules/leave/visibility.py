"""Confidential-leave visibility filter (P2-N1, P2-N7, P2-N12).

Family-violence leave (and any future leave type with
``confidential_visibility=true``) is NOT visible to general approvers.
The list endpoints in :mod:`app.modules.leave.router` route their
``select(LeaveRequest)`` queries through :func:`_apply_confidential_filter`
before execution so the DB never even returns confidential rows to a
user without the right.

Two access paths into a confidential row:

  (a) **Subject** — the staff member whose request it is. Keyed by
      ``LeaveRequest.staff_id`` resolving to a ``StaffMember`` whose
      ``user_id`` matches the current user. P2-N12 fix: this join is
      against ``staff_id`` not ``requested_by`` — a manager submitting
      on behalf of a staff member who can't access the system would
      have ``requested_by = manager.user_id`` while ``staff_id =
      subject.staff_id``; the earlier draft would have hidden the row
      from the subject and shown it to the proxy.
  (b) **Permitted approver** — a user holding the ``leave.fv_view``
      permission via ``user_permission_overrides``. Backfilled to all
      ``org_admin`` users by migration 0205; org owners can grant /
      revoke per-user via Settings → People → Permissions (D11).

The filter is **synchronous** — it reads from
``request.state.permission_overrides`` which is already populated by
``RBACMiddleware`` from the existing 60-second Redis cache. There is
NO additional DB query per filter call. Revocation propagates within
60 seconds (the RBAC cache TTL), which is acceptable per R4.9.

Refs: design.md §4.4, R4.6, R4.9, P2-N1, P2-N7, P2-N12.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.sql import Select

from app.modules.auth.rbac import has_permission
from app.modules.leave.models import LeaveRequest, LeaveType
from app.modules.staff.models import StaffMember

if TYPE_CHECKING:
    from fastapi import Request


# ---------------------------------------------------------------------------
# Permission key
# ---------------------------------------------------------------------------

# Dot-separated to match the existing rbac convention (P2-N1).
# Granting this permission requires writing a ``user_permission_overrides``
# row explicitly per user — no role wildcard auto-grants it. The 0205
# migration backfilled the override for every existing ``org_admin``
# user; future grants happen via Settings → People → Permissions.
FV_LEAVE_VIEW_PERMISSION = "leave.fv_view"


__all__ = [
    "FV_LEAVE_VIEW_PERMISSION",
    "_apply_confidential_filter",
]


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


def _apply_confidential_filter(
    query: Select,
    request: "Request",
    user_id: uuid.UUID,
    user_role: str,
) -> Select:
    """Restrict confidential-leave-type rows on a ``LeaveRequest`` query.

    Args:
        query: A ``select(LeaveRequest)`` (or a derived select that still
            reads ``LeaveRequest.leave_type_id`` / ``staff_id``). Caller
            must compose the query around ``LeaveRequest`` for the
            ``or_`` clauses to bind correctly.
        request: The active FastAPI ``Request`` — used for
            ``request.state.permission_overrides`` and
            ``request.state.org_id``. Both are populated upstream by the
            auth + RBAC middleware.
        user_id: The current user's UUID.
        user_role: The current user's base role string (e.g. ``'org_admin'``,
            ``'branch_admin'``, ``'staff'``).

    Returns:
        The original query (unmodified) when the user holds the
        ``leave.fv_view`` permission. Otherwise returns the query with a
        ``WHERE`` clause that hides rows whose ``leave_type_id`` resolves
        to a ``confidential_visibility=true`` type, EXCEPT when
        ``LeaveRequest.staff_id`` resolves to a ``StaffMember`` whose
        ``user_id`` is the current user (the subject branch).

    Synchronous — performs no DB I/O.
    """
    overrides = getattr(request.state, "permission_overrides", None) or []
    has_fv_view = has_permission(user_role, FV_LEAVE_VIEW_PERMISSION, overrides=overrides)
    if has_fv_view:
        return query

    org_id = getattr(request.state, "org_id", None)

    # The current user's staff_id, if any. NULL for users not linked to
    # a staff record (e.g. ``global_admin`` or non-staff org users).
    current_staff_id_subq = (
        select(StaffMember.id)
        .where(StaffMember.user_id == user_id)
        .limit(1)
        .scalar_subquery()
    )

    # IDs of every leave_type in the current org with confidential_visibility=true.
    confidential_type_ids = select(LeaveType.id).where(
        LeaveType.org_id == org_id,
        LeaveType.confidential_visibility.is_(True),
    )

    return query.where(
        or_(
            LeaveRequest.leave_type_id.notin_(confidential_type_ids),
            LeaveRequest.staff_id == current_staff_id_subq,
        )
    )
