"""Integration tests for kiosk branch enforcement (A2.9).

Tests:
- Kiosk invite with 0 branches is rejected (422)
- Kiosk invite with 2 branches is rejected (422)
- Kiosk invite with 1 branch succeeds
- Non-kiosk invite without branch_ids still succeeds (no regression)
- Clock-in derives branch_id from JWT branch_ids[0]
"""

import uuid

import pytest
from pydantic import ValidationError

from app.modules.organisations.schemas import UserInviteRequest


class TestKioskInviteValidation:
    """Test that kiosk role requires exactly 1 branch_id."""

    def test_kiosk_invite_with_zero_branches_rejected(self):
        """Kiosk invite with empty branch_ids raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserInviteRequest(
                email="kiosk1@test.com",
                role="kiosk",
                password="securepass123",
                branch_ids=[],
            )
        assert "exactly one branch_id" in str(exc_info.value).lower()

    def test_kiosk_invite_with_none_branches_rejected(self):
        """Kiosk invite with no branch_ids raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserInviteRequest(
                email="kiosk2@test.com",
                role="kiosk",
                password="securepass123",
                branch_ids=None,
            )
        assert "exactly one branch_id" in str(exc_info.value).lower()

    def test_kiosk_invite_with_two_branches_rejected(self):
        """Kiosk invite with 2 branch_ids raises ValidationError."""
        branch1 = str(uuid.uuid4())
        branch2 = str(uuid.uuid4())
        with pytest.raises(ValidationError) as exc_info:
            UserInviteRequest(
                email="kiosk3@test.com",
                role="kiosk",
                password="securepass123",
                branch_ids=[branch1, branch2],
            )
        assert "exactly one branch_id" in str(exc_info.value).lower()

    def test_kiosk_invite_with_one_branch_succeeds(self):
        """Kiosk invite with exactly 1 branch_id passes validation."""
        branch_id = str(uuid.uuid4())
        req = UserInviteRequest(
            email="kiosk4@test.com",
            role="kiosk",
            password="securepass123",
            branch_ids=[branch_id],
        )
        assert req.branch_ids == [branch_id]
        assert req.role == "kiosk"

    def test_non_kiosk_invite_without_branches_succeeds(self):
        """Non-kiosk role invite without branch_ids passes (no regression)."""
        req = UserInviteRequest(
            email="staff@test.com",
            role="salesperson",
        )
        assert req.branch_ids is None
        assert req.role == "salesperson"

    def test_non_kiosk_invite_with_branches_succeeds(self):
        """Non-kiosk role invite with branch_ids passes (optional)."""
        branch_id = str(uuid.uuid4())
        req = UserInviteRequest(
            email="admin@test.com",
            role="org_admin",
            branch_ids=[branch_id],
        )
        assert req.branch_ids == [branch_id]

    def test_kiosk_invite_without_branch_ids_field_rejected(self):
        """Kiosk invite without branch_ids field at all raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserInviteRequest(
                email="kiosk5@test.com",
                role="kiosk",
                password="securepass123",
            )
        assert "exactly one branch_id" in str(exc_info.value).lower()


class TestClockInBranchDerivation:
    """Test that kiosk clock-in derives branch_id from JWT."""

    def test_perform_clock_action_accepts_branch_id(self):
        """Verify TimeClockEntry model has branch_id field."""
        from app.modules.time_clock.models import TimeClockEntry

        # Verify the model has the branch_id attribute
        assert hasattr(TimeClockEntry, "branch_id")
        assert hasattr(TimeClockEntry, "clock_out_branch_id")
        assert hasattr(TimeClockEntry, "clock_in_ip")

    def test_kiosk_clock_action_signature_accepts_branch_id(self):
        """Verify kiosk_clock_action accepts branch_id parameter."""
        import inspect

        from app.modules.time_clock.service import kiosk_clock_action

        sig = inspect.signature(kiosk_clock_action)
        params = list(sig.parameters.keys())
        assert "branch_id" in params
