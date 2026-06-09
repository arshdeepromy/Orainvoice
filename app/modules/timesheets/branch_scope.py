"""Branch-scoped query dependency for the timesheets module.

Enforces branch-level data isolation as a SECURITY boundary — not just
UI filtering. Branch admins and users with timesheet.approve permission
only see data for their assigned branches.

Usage in router:
    @router.get("/timesheets")
    async def list_timesheets(
        scope: BranchScopedTimesheets = Depends(),
        ...
    ):
        query = scope.apply_filter(query, Timesheet.branch_id)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Request


class BranchScopedTimesheets:
    """FastAPI dependency that enforces branch-level data isolation.

    For org_admin and global_admin: no filter applied (full org visibility).
    For branch_admin and other non-admin roles: filters queries to
    branch_id ∈ request.state.branch_ids.
    """

    def __init__(self, request: Request):
        self.role: str | None = getattr(request.state, "role", None)
        self.branch_ids: list[UUID] = []
        self.should_filter: bool = False

        # org_admin and global_admin see everything
        if self.role in ("org_admin", "global_admin"):
            self.should_filter = False
        else:
            # All other roles (branch_admin, staff_member, salesperson, etc.)
            # are scoped to their assigned branches
            raw_ids = getattr(request.state, "branch_ids", None) or []
            self.branch_ids = [UUID(str(bid)) for bid in raw_ids if bid]
            self.should_filter = True

    def apply_filter(self, query, branch_id_column):
        """Apply branch filtering to a SQLAlchemy query.

        Returns the query unchanged for org_admin/global_admin.
        Adds WHERE branch_id IN (...) for scoped users.
        NULL branch_id entries are excluded from scoped views.
        """
        if not self.should_filter:
            return query
        if not self.branch_ids:
            # Scoped user with no assigned branches — show nothing
            return query.where(branch_id_column == None)  # noqa: E711 (IS NULL)
        return query.where(branch_id_column.in_(self.branch_ids))

    def can_access_branch(self, branch_id: UUID | None) -> bool:
        """Check if the current user can access a specific branch's data."""
        if not self.should_filter:
            return True
        if branch_id is None:
            return False  # NULL branch_id not visible to branch-scoped users
        return branch_id in self.branch_ids
