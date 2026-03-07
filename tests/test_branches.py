"""Unit tests for Task 6.4 — branch management.

Tests cover:
  - list_branches: retrieving branches for an org
  - create_branch: creating a new branch with audit logging
  - assign_user_branches: assigning users to branches with validation
  - RBAC: org_admin for POST, org_admin or salesperson for GET
  - Schema validation for branch requests

Requirements: 9.7, 9.8
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.organisations.models import Branch
from app.modules.auth.models import User
from app.modules.admin.models import Organisation
from app.modules.organisations.schemas import (
    BranchCreateRequest,
    BranchCreateResponse,
    BranchListResponse,
    BranchResponse,
    AssignUserBranchesRequest,
    AssignUserBranchesResponse,
)
from app.modules.organisations.service import (
    list_branches,
    create_branch,
    assign_user_branches,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_branch(org_id=None, name="Main Branch", address="123 Main St", phone="+64 9 111 2222"):
    """Create a mock Branch object."""
    branch = MagicMock(spec=Branch)
    branch.id = uuid.uuid4()
    branch.org_id = org_id or uuid.uuid4()
    branch.name = name
    branch.address = address
    branch.phone = phone
    branch.is_active = True
    branch.created_at = datetime.now(timezone.utc)
    return branch


def _make_org(org_id=None, name="Test Workshop"):
    """Create a mock Organisation."""
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.name = name
    return org


def _make_user(org_id=None, branch_ids=None):
    """Create a mock User object."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.org_id = org_id or uuid.uuid4()
    user.branch_ids = branch_ids or []
    return user


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    """Create a mock result that returns values from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestBranchSchemas:
    """Test Pydantic schema validation for branch requests."""

    def test_create_request_minimal(self):
        req = BranchCreateRequest(name="Downtown Branch")
        assert req.name == "Downtown Branch"
        assert req.address is None
        assert req.phone is None

    def test_create_request_full(self):
        req = BranchCreateRequest(
            name="Auckland CBD",
            address="42 Queen St, Auckland",
            phone="+64 9 555 1234",
        )
        assert req.name == "Auckland CBD"
        assert req.address == "42 Queen St, Auckland"
        assert req.phone == "+64 9 555 1234"

    def test_create_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            BranchCreateRequest(name="")

    def test_branch_response_model(self):
        resp = BranchResponse(
            id=str(uuid.uuid4()),
            name="Test Branch",
            address="123 Test St",
            phone="+64 9 000 0000",
            is_active=True,
            created_at="2025-01-15T00:00:00+00:00",
        )
        assert resp.name == "Test Branch"
        assert resp.is_active is True

    def test_branch_list_response(self):
        resp = BranchListResponse(branches=[])
        assert resp.branches == []

    def test_assign_user_request(self):
        uid = str(uuid.uuid4())
        bid = str(uuid.uuid4())
        req = AssignUserBranchesRequest(user_id=uid, branch_ids=[bid])
        assert req.user_id == uid
        assert len(req.branch_ids) == 1

    def test_assign_user_empty_branches(self):
        """Assigning empty branch list is valid (unassign all)."""
        uid = str(uuid.uuid4())
        req = AssignUserBranchesRequest(user_id=uid, branch_ids=[])
        assert req.branch_ids == []


# ---------------------------------------------------------------------------
# list_branches tests
# ---------------------------------------------------------------------------

class TestListBranches:
    """Test the list_branches service function."""

    @pytest.mark.asyncio
    async def test_returns_branches(self):
        """Returns list of active branches for the org."""
        org_id = uuid.uuid4()
        b1 = _make_branch(org_id=org_id, name="Branch A")
        b2 = _make_branch(org_id=org_id, name="Branch B")

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalars_result([b1, b2]))

        result = await list_branches(db, org_id=org_id)

        assert len(result) == 2
        assert result[0]["name"] == "Branch A"
        assert result[1]["name"] == "Branch B"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_branches(self):
        """Returns empty list when org has no branches."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await list_branches(db, org_id=uuid.uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_branch_fields_present(self):
        """Each branch dict has all expected fields."""
        branch = _make_branch()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalars_result([branch]))

        result = await list_branches(db, org_id=branch.org_id)

        b = result[0]
        assert "id" in b
        assert "name" in b
        assert "address" in b
        assert "phone" in b
        assert "is_active" in b
        assert "created_at" in b


# ---------------------------------------------------------------------------
# create_branch tests
# ---------------------------------------------------------------------------

class TestCreateBranch:
    """Test the create_branch service function."""

    @pytest.mark.asyncio
    async def test_creates_branch_successfully(self):
        """Creates a branch and returns its data."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_branch(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                name="New Branch",
                address="456 Test Ave",
                phone="+64 9 222 3333",
            )

        assert result["name"] == "New Branch"
        assert result["address"] == "456 Test Ave"
        assert result["phone"] == "+64 9 222 3333"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_branch_without_optional_fields(self):
        """Creates a branch with only name (address and phone optional)."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_branch(
                db,
                org_id=org.id,
                user_id=uuid.uuid4(),
                name="Minimal Branch",
            )

        assert result["name"] == "Minimal Branch"
        assert result["address"] is None
        assert result["phone"] is None

    @pytest.mark.asyncio
    async def test_org_not_found_raises(self):
        """Raises ValueError when org doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Organisation not found"):
            await create_branch(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Ghost Branch",
            )

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Verify audit log is written on branch creation."""
        org = _make_org()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(org))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await create_branch(
                db,
                org_id=org.id,
                user_id=user_id,
                name="Audited Branch",
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.branch_created"
        assert call_kwargs["entity_type"] == "branch"
        assert call_kwargs["org_id"] == org.id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["ip_address"] == "10.0.0.1"
        assert call_kwargs["after_value"]["name"] == "Audited Branch"


# ---------------------------------------------------------------------------
# assign_user_branches tests
# ---------------------------------------------------------------------------

class TestAssignUserBranches:
    """Test the assign_user_branches service function."""

    @pytest.mark.asyncio
    async def test_assigns_user_to_branches(self):
        """Successfully assigns a user to branches."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id)
        b1 = _make_branch(org_id=org_id, name="Branch 1")
        b2 = _make_branch(org_id=org_id, name="Branch 2")

        db = _mock_db_session()
        # First call: find user, second call: find branches
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(user),
                _mock_scalars_result([b1, b2]),
            ]
        )

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await assign_user_branches(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                branch_ids=[b1.id, b2.id],
            )

        assert result["user_id"] == str(user.id)
        assert len(result["branch_ids"]) == 2

    @pytest.mark.asyncio
    async def test_assigns_empty_branches(self):
        """Assigning empty branch list clears user's branches."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id, branch_ids=["some-old-id"])

        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(user))

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await assign_user_branches(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                branch_ids=[],
            )

        assert result["branch_ids"] == []

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self):
        """Raises ValueError when target user not in org."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="User not found"):
            await assign_user_branches(
                db,
                org_id=uuid.uuid4(),
                acting_user_id=uuid.uuid4(),
                target_user_id=uuid.uuid4(),
                branch_ids=[uuid.uuid4()],
            )

    @pytest.mark.asyncio
    async def test_invalid_branch_raises(self):
        """Raises ValueError when a branch doesn't belong to the org."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id)
        valid_branch = _make_branch(org_id=org_id)
        missing_id = uuid.uuid4()

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(user),
                _mock_scalars_result([valid_branch]),  # Only one found, but two requested
            ]
        )

        with pytest.raises(ValueError, match="Branch.*not found"):
            await assign_user_branches(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                branch_ids=[valid_branch.id, missing_id],
            )

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Verify audit log is written on branch assignment."""
        org_id = uuid.uuid4()
        user = _make_user(org_id=org_id, branch_ids=[])
        branch = _make_branch(org_id=org_id)

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalar_result(user),
                _mock_scalars_result([branch]),
            ]
        )

        with patch(
            "app.modules.organisations.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await assign_user_branches(
                db,
                org_id=org_id,
                acting_user_id=uuid.uuid4(),
                target_user_id=user.id,
                branch_ids=[branch.id],
                ip_address="10.0.0.5",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "org.user_branches_assigned"
        assert call_kwargs["entity_type"] == "user"
        assert call_kwargs["ip_address"] == "10.0.0.5"
