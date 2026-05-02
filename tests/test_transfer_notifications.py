"""Unit tests for transfer event notifications.

Tests that the correct recipients are notified for each transfer event:
  - create: destination branch manager(s) only
  - approve/execute: both source and destination managers

Uses mocks to avoid database and email dependencies.

**Validates: Requirements 55.1, 55.2, 55.3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
SOURCE_BRANCH_ID = uuid.uuid4()
DEST_BRANCH_ID = uuid.uuid4()


def _make_transfer(
    *,
    org_id: uuid.UUID = ORG_ID,
    from_branch_id: uuid.UUID = SOURCE_BRANCH_ID,
    to_branch_id: uuid.UUID = DEST_BRANCH_ID,
    status: str = "pending",
    quantity: Decimal = Decimal("10"),
) -> MagicMock:
    """Create a mock StockTransfer object."""
    transfer = MagicMock()
    transfer.id = uuid.uuid4()
    transfer.org_id = org_id
    transfer.from_branch_id = from_branch_id
    transfer.to_branch_id = to_branch_id
    transfer.status = status
    transfer.quantity = quantity
    return transfer


def _make_branch(branch_id: uuid.UUID, name: str) -> MagicMock:
    """Create a mock Branch object."""
    branch = MagicMock()
    branch.id = branch_id
    branch.name = name
    return branch


def _make_user(
    *,
    role: str = "org_admin",
    email: str = "admin@example.com",
    branch_ids: list | None = None,
    first_name: str = "Test",
    last_name: str = "User",
) -> MagicMock:
    """Create a mock User object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.org_id = ORG_ID
    user.role = role
    user.email = email
    user.is_active = True
    user.branch_ids = branch_ids or []
    user.first_name = first_name
    user.last_name = last_name
    return user


# Patch targets
PATCH_LOG_EMAIL = "app.modules.notifications.service.log_email_sent"
PATCH_SEND_EMAIL = "app.tasks.notifications.send_email_task"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTransferNotificationRecipients:
    """Verify correct recipients are selected for each transfer event."""

    @pytest.mark.asyncio
    async def test_create_notifies_destination_only(self):
        """On create, only destination branch managers are notified.

        **Validates: Requirement 55.1**
        """
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Source Branch")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Dest Branch")

        dest_manager = _make_user(
            role="location_manager",
            email="dest@example.com",
            branch_ids=[str(DEST_BRANCH_ID)],
        )
        source_manager = _make_user(
            role="location_manager",
            email="source@example.com",
            branch_ids=[str(SOURCE_BRANCH_ID)],
        )

        transfer = _make_transfer(status="pending")

        db = AsyncMock()

        # db.get returns the correct branch based on ID
        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        # db.execute returns users — for the dest branch query
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [dest_manager, source_manager]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            mock_log.return_value = {"id": uuid.uuid4()}

            await svc._notify_transfer_event(transfer, "created")

            # Only dest_manager should be notified (source_manager's branch
            # doesn't match the destination branch)
            assert mock_log.call_count == 1
            assert mock_send.call_count == 1
            assert mock_send.call_args.kwargs["to_email"] == "dest@example.com"

    @pytest.mark.asyncio
    async def test_approve_notifies_both_branches(self):
        """On approve, both source and destination managers are notified.

        **Validates: Requirement 55.2**
        """
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Source Branch")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Dest Branch")

        dest_manager = _make_user(
            role="location_manager",
            email="dest@example.com",
            branch_ids=[str(DEST_BRANCH_ID)],
        )
        source_manager = _make_user(
            role="location_manager",
            email="source@example.com",
            branch_ids=[str(SOURCE_BRANCH_ID)],
        )

        transfer = _make_transfer(status="approved")

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        # Return both managers for each query
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [dest_manager, source_manager]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            mock_log.return_value = {"id": uuid.uuid4()}

            await svc._notify_transfer_event(transfer, "approved")

            # Both managers should be notified
            assert mock_log.call_count == 2
            assert mock_send.call_count == 2
            emails_sent = {call.kwargs["to_email"] for call in mock_send.call_args_list}
            assert "dest@example.com" in emails_sent
            assert "source@example.com" in emails_sent

    @pytest.mark.asyncio
    async def test_execute_notifies_both_branches(self):
        """On execute, both source and destination managers are notified.

        **Validates: Requirement 55.2**
        """
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Source Branch")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Dest Branch")

        org_admin = _make_user(
            role="org_admin",
            email="admin@example.com",
        )

        transfer = _make_transfer(status="executed")

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [org_admin]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            mock_log.return_value = {"id": uuid.uuid4()}

            await svc._notify_transfer_event(transfer, "executed")

            # org_admin is notified once (deduplicated across both branches)
            assert mock_log.call_count == 1
            assert mock_send.call_count == 1


class TestTransferNotificationContent:
    """Verify notification content includes required transfer details."""

    @pytest.mark.asyncio
    async def test_notification_includes_transfer_details(self):
        """Notification subject and body include action, branches, quantity.

        **Validates: Requirement 55.3**
        """
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Auckland HQ")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Wellington Branch")

        admin = _make_user(role="org_admin", email="admin@example.com")
        transfer = _make_transfer(status="pending", quantity=Decimal("25.5"))

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [admin]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            mock_log.return_value = {"id": uuid.uuid4()}

            await svc._notify_transfer_event(transfer, "created")

            # Check subject
            subject = mock_send.call_args.kwargs["subject"]
            assert "New transfer request" in subject
            assert "Auckland HQ" in subject
            assert "Wellington Branch" in subject
            assert "25.5" in subject

            # Check HTML body
            html = mock_send.call_args.kwargs["html_body"]
            assert "Auckland HQ" in html
            assert "Wellington Branch" in html
            assert "25.5" in html
            assert "New transfer request" in html

    @pytest.mark.asyncio
    async def test_notification_uses_correct_template_type(self):
        """Email log uses template_type matching the action.

        **Validates: Requirement 55.3**
        """
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Branch A")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Branch B")

        admin = _make_user(role="org_admin", email="admin@example.com")
        transfer = _make_transfer(status="approved")

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [admin]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock):
            mock_log.return_value = {"id": uuid.uuid4()}

            await svc._notify_transfer_event(transfer, "approved")

            assert mock_log.call_args.kwargs["template_type"] == "transfer_approved"


class TestTransferNotificationEdgeCases:
    """Edge cases for transfer notifications."""

    @pytest.mark.asyncio
    async def test_no_recipients_skips_notification(self):
        """When no managers are found, no emails are sent."""
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Branch A")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Branch B")

        transfer = _make_transfer(status="pending")

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        # No users returned
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            await svc._notify_transfer_event(transfer, "created")

            mock_log.assert_not_called()
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_recipient_without_email_skipped(self):
        """Users without email addresses are skipped."""
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Branch A")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Branch B")

        no_email_admin = _make_user(role="org_admin", email=None)
        transfer = _make_transfer(status="pending")

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [no_email_admin]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            await svc._notify_transfer_event(transfer, "created")

            mock_log.assert_not_called()
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_email_failure_does_not_raise(self):
        """If email sending fails, the notification method does not raise."""
        from app.modules.franchise.service import FranchiseService

        source_branch = _make_branch(SOURCE_BRANCH_ID, "Branch A")
        dest_branch = _make_branch(DEST_BRANCH_ID, "Branch B")

        admin = _make_user(role="org_admin", email="admin@example.com")
        transfer = _make_transfer(status="pending")

        db = AsyncMock()

        async def fake_get(model, branch_id):
            if branch_id == SOURCE_BRANCH_ID:
                return source_branch
            if branch_id == DEST_BRANCH_ID:
                return dest_branch
            return None

        db.get = fake_get

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [admin]
        db.execute = AsyncMock(return_value=mock_result)

        svc = FranchiseService(db)

        with patch(PATCH_LOG_EMAIL, new_callable=AsyncMock) as mock_log, \
             patch(PATCH_SEND_EMAIL, new_callable=AsyncMock) as mock_send:
            mock_log.return_value = {"id": uuid.uuid4()}
            mock_send.side_effect = Exception("SMTP error")

            # Should not raise
            await svc._notify_transfer_event(transfer, "created")
