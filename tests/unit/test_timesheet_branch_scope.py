"""Unit tests for BranchScopedTimesheets FastAPI dependency.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.7
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.timesheets.branch_scope import BranchScopedTimesheets


def _make_request(role: str | None = None, branch_ids: list | None = None) -> MagicMock:
    """Build a mock Request with the given state attributes."""
    request = MagicMock()
    request.state = MagicMock()
    request.state.role = role
    request.state.branch_ids = branch_ids
    return request


class TestBranchScopedTimesheetsInit:
    """Test __init__ role-based scoping logic."""

    def test_org_admin_no_filter(self):
        """org_admin should have full org visibility (should_filter=False)."""
        request = _make_request(role="org_admin", branch_ids=[str(uuid4())])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is False
        assert scope.branch_ids == []

    def test_global_admin_no_filter(self):
        """global_admin should have full org visibility (should_filter=False)."""
        request = _make_request(role="global_admin", branch_ids=[])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is False
        assert scope.branch_ids == []

    def test_branch_admin_scoped_to_branches(self):
        """branch_admin should be scoped to their assigned branches."""
        bid1 = uuid4()
        bid2 = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid1), str(bid2)])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is True
        assert set(scope.branch_ids) == {bid1, bid2}

    def test_staff_member_scoped_to_branches(self):
        """staff_member (non-admin) should be scoped to their branches."""
        bid = uuid4()
        request = _make_request(role="staff_member", branch_ids=[str(bid)])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is True
        assert scope.branch_ids == [bid]

    def test_other_role_scoped_to_branches(self):
        """Any non-admin role is branch-scoped."""
        bid = uuid4()
        request = _make_request(role="salesperson", branch_ids=[str(bid)])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is True
        assert scope.branch_ids == [bid]

    def test_none_role_scoped(self):
        """A request with no role should be scoped (safe default)."""
        request = _make_request(role=None, branch_ids=[])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is True

    def test_empty_branch_ids_still_scoped(self):
        """branch_admin with empty branch_ids is scoped but sees nothing."""
        request = _make_request(role="branch_admin", branch_ids=[])
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is True
        assert scope.branch_ids == []

    def test_none_branch_ids_treated_as_empty(self):
        """If branch_ids is None on request state, treat as empty list."""
        request = _make_request(role="branch_admin", branch_ids=None)
        scope = BranchScopedTimesheets(request)
        assert scope.should_filter is True
        assert scope.branch_ids == []

    def test_uuid_objects_in_branch_ids(self):
        """branch_ids can contain UUID objects (not just strings)."""
        bid = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[bid])
        scope = BranchScopedTimesheets(request)
        assert scope.branch_ids == [bid]

    def test_filters_out_falsy_branch_ids(self):
        """Empty strings or None values in branch_ids are filtered out."""
        bid = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid), "", None])
        scope = BranchScopedTimesheets(request)
        assert scope.branch_ids == [bid]


class TestApplyFilter:
    """Test apply_filter method with mock SQLAlchemy queries."""

    def test_unscoped_returns_query_unchanged(self):
        """org_admin query should be returned unchanged."""
        request = _make_request(role="org_admin")
        scope = BranchScopedTimesheets(request)

        mock_query = MagicMock()
        result = scope.apply_filter(mock_query, MagicMock())
        assert result is mock_query

    def test_scoped_with_branches_adds_in_filter(self):
        """Scoped user should get WHERE branch_id IN (...) clause."""
        bid = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid)])
        scope = BranchScopedTimesheets(request)

        mock_query = MagicMock()
        mock_column = MagicMock()
        scope.apply_filter(mock_query, mock_column)

        # Verify .in_() was called on the column with the branch_ids
        mock_column.in_.assert_called_once_with([bid])
        mock_query.where.assert_called_once()

    def test_scoped_with_no_branches_filters_to_null(self):
        """Scoped user with no branches should show nothing (WHERE col IS NULL)."""
        request = _make_request(role="branch_admin", branch_ids=[])
        scope = BranchScopedTimesheets(request)

        mock_query = MagicMock()
        mock_column = MagicMock()
        scope.apply_filter(mock_query, mock_column)

        # Should call query.where(column == None) which produces IS NULL
        mock_query.where.assert_called_once()


class TestCanAccessBranch:
    """Test can_access_branch method."""

    def test_unscoped_can_access_any_branch(self):
        """org_admin can access any branch."""
        request = _make_request(role="org_admin")
        scope = BranchScopedTimesheets(request)

        assert scope.can_access_branch(uuid4()) is True
        assert scope.can_access_branch(None) is True

    def test_scoped_can_access_assigned_branch(self):
        """branch_admin can access their assigned branches."""
        bid = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid)])
        scope = BranchScopedTimesheets(request)

        assert scope.can_access_branch(bid) is True

    def test_scoped_cannot_access_unassigned_branch(self):
        """branch_admin cannot access branches not in their list."""
        bid = uuid4()
        other_bid = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid)])
        scope = BranchScopedTimesheets(request)

        assert scope.can_access_branch(other_bid) is False

    def test_scoped_cannot_access_null_branch(self):
        """NULL branch_id is not visible to branch-scoped users (Req 6.7)."""
        bid = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid)])
        scope = BranchScopedTimesheets(request)

        assert scope.can_access_branch(None) is False

    def test_scoped_with_no_branches_cannot_access_anything(self):
        """Scoped user with empty branch_ids cannot access any branch."""
        request = _make_request(role="branch_admin", branch_ids=[])
        scope = BranchScopedTimesheets(request)

        assert scope.can_access_branch(uuid4()) is False
        assert scope.can_access_branch(None) is False

    def test_scoped_with_multiple_branches(self):
        """Scoped user can access any of their assigned branches."""
        bid1 = uuid4()
        bid2 = uuid4()
        bid3 = uuid4()
        request = _make_request(role="branch_admin", branch_ids=[str(bid1), str(bid2)])
        scope = BranchScopedTimesheets(request)

        assert scope.can_access_branch(bid1) is True
        assert scope.can_access_branch(bid2) is True
        assert scope.can_access_branch(bid3) is False
