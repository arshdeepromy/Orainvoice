"""Unit tests for DSAR (Data Subject Access Request) from portal (Req 45).

Tests that customers can submit data export and account deletion requests
via the portal, and that org admins are notified.

**Validates: Requirements 45.1, 45.2, 45.3, 45.4, 45.5**
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.portal.service import create_portal_dsar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
TOKEN = "test-portal-token-abc"


def _make_customer() -> MagicMock:
    c = MagicMock()
    c.id = CUSTOMER_ID
    c.org_id = ORG_ID
    c.first_name = "Alice"
    c.last_name = "Smith"
    c.email = "alice@example.com"
    c.phone = "+6421000000"
    c.portal_token = TOKEN
    c.is_anonymised = False
    c.enable_portal = True
    c.portal_token_expires_at = None
    return c


def _make_org() -> MagicMock:
    org = MagicMock()
    org.id = ORG_ID
    org.name = "Test Workshop"
    org.settings = {}
    org.locale = "en-NZ"
    org.white_label_enabled = False
    return org


def _make_admin_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@workshop.co.nz"
    user.role = "org_admin"
    user.is_active = True
    return user


def _mock_db(admin_user=None):
    """Build a mock AsyncSession.

    Since _resolve_token is patched, the DB execute calls are:
      1. write_audit_log (patched separately)
      2. Admin user lookup for notification
    """
    db = AsyncMock()

    async def _execute_side_effect(stmt, params=None):
        result = MagicMock()
        result.scalar_one_or_none.return_value = admin_user
        return result

    db.execute = AsyncMock(side_effect=_execute_side_effect)
    return db


# Patch targets
PATCH_RESOLVE = "app.modules.portal.service._resolve_token"
PATCH_AUDIT = "app.modules.portal.service.write_audit_log"
PATCH_LOG_EMAIL = "app.modules.notifications.service.log_email_sent"
PATCH_SEND_EMAIL = "app.tasks.notifications.send_email_task"


class TestPortalDSAR:
    """Req 45: DSAR from portal."""

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_export_request_creates_record_and_notifies(
        self, mock_resolve, mock_audit, mock_log_email, mock_send_task
    ):
        """45.2, 45.3, 45.4: Export request creates audit record and notifies admin."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()

        mock_resolve.return_value = (customer, org)
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db(admin_user=admin_user)

        result = await create_portal_dsar(db, TOKEN, "export")

        assert result["request_type"] == "export"
        assert "data export" in result["message"].lower()

        # Verify audit log was written
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "portal.dsar_export"
        assert audit_kwargs["entity_type"] == "customer"
        assert audit_kwargs["entity_id"] == CUSTOMER_ID

        # Verify email notification was sent
        mock_log_email.assert_awaited_once()
        log_kwargs = mock_log_email.call_args.kwargs
        assert log_kwargs["template_type"] == "dsar_request"
        assert log_kwargs["recipient"] == "admin@workshop.co.nz"

        mock_send_task.assert_awaited_once()
        send_kwargs = mock_send_task.call_args.kwargs
        assert send_kwargs["to_email"] == "admin@workshop.co.nz"
        assert "Data Export" in send_kwargs["subject"]
        assert "Alice Smith" in send_kwargs["subject"]

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_deletion_request_creates_record_and_notifies(
        self, mock_resolve, mock_audit, mock_log_email, mock_send_task
    ):
        """45.5, 45.3, 45.4: Deletion request creates audit record and notifies admin."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()

        mock_resolve.return_value = (customer, org)
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db(admin_user=admin_user)

        result = await create_portal_dsar(db, TOKEN, "deletion")

        assert result["request_type"] == "deletion"
        assert "account deletion" in result["message"].lower()

        # Verify audit log was written with deletion action
        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "portal.dsar_deletion"

        # Verify email notification was sent
        mock_send_task.assert_awaited_once()
        send_kwargs = mock_send_task.call_args.kwargs
        assert "Account Deletion" in send_kwargs["subject"]
        assert "Alice Smith" in send_kwargs["html_body"]

    @pytest.mark.asyncio
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_invalid_request_type_raises_error(
        self, mock_resolve, mock_audit
    ):
        """Invalid request_type is rejected with ValueError."""
        customer = _make_customer()
        org = _make_org()

        mock_resolve.return_value = (customer, org)

        db = _mock_db()

        with pytest.raises(ValueError, match="Invalid request_type"):
            await create_portal_dsar(db, TOKEN, "invalid_type")

        # Audit log should NOT have been written
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_no_admin_user_skips_notification(
        self, mock_resolve, mock_audit, mock_log_email, mock_send_task
    ):
        """When no org_admin exists, notification is skipped gracefully."""
        customer = _make_customer()
        org = _make_org()

        mock_resolve.return_value = (customer, org)

        db = _mock_db(admin_user=None)

        result = await create_portal_dsar(db, TOKEN, "export")

        # Request still succeeds
        assert result["request_type"] == "export"

        # Audit log was still written
        mock_audit.assert_awaited_once()

        # Email should NOT have been sent
        mock_log_email.assert_not_awaited()
        mock_send_task.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_email_failure_does_not_break_dsar(
        self, mock_resolve, mock_audit, mock_log_email, mock_send_task
    ):
        """If email sending fails, the DSAR still succeeds."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()

        mock_resolve.return_value = (customer, org)
        mock_log_email.side_effect = Exception("SMTP connection failed")

        db = _mock_db(admin_user=admin_user)

        # Should not raise — DSAR succeeds even if notification fails
        result = await create_portal_dsar(db, TOKEN, "export")
        assert result["request_type"] == "export"

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_notification_includes_customer_email(
        self, mock_resolve, mock_audit, mock_log_email, mock_send_task
    ):
        """45.4: Notification includes customer email for admin reference."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()

        mock_resolve.return_value = (customer, org)
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db(admin_user=admin_user)

        await create_portal_dsar(db, TOKEN, "export")

        send_kwargs = mock_send_task.call_args.kwargs
        assert "alice@example.com" in send_kwargs["html_body"]
        assert "alice@example.com" in send_kwargs["text_body"]
