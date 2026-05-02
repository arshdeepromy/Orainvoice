"""Unit tests for quote acceptance notification (Req 23.1, 23.2, 23.3).

Tests that when a customer accepts a quote via the portal, an email
notification is sent to the org's primary contact (org_admin) with
the quote number, customer name, and accepted date.

**Validates: Requirements 23.1, 23.2, 23.3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.portal.service import accept_portal_quote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
QUOTE_ID = uuid.uuid4()
TOKEN = uuid.uuid4()
ACCEPTANCE_TOKEN = "acc-tok-123"
QUOTE_NUMBER = "Q-0042"


def _make_customer() -> MagicMock:
    c = MagicMock()
    c.id = CUSTOMER_ID
    c.org_id = ORG_ID
    c.first_name = "Jane"
    c.last_name = "Doe"
    c.email = "jane@example.com"
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
    org.stripe_connect_account_id = None
    return org


def _make_admin_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@workshop.co.nz"
    user.role = "org_admin"
    user.is_active = True
    return user


def _make_accepted_quote() -> MagicMock:
    q = MagicMock()
    q.id = QUOTE_ID
    q.status = "accepted"
    q.accepted_at = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    q.quote_number = QUOTE_NUMBER
    return q


def _mock_db(admin_user=None):
    """Build a mock AsyncSession.

    Since _resolve_token is patched, the DB execute calls are:
      1. Quote lookup (raw SQL) — returns acceptance_token + quote_number
      2. Admin user lookup — returns admin_user or None
    """
    db = AsyncMock()
    call_count = {"n": 0}

    async def _execute_side_effect(stmt, params=None):
        call_count["n"] += 1
        result = MagicMock()

        # Call 1: quote lookup (raw SQL with sa_text)
        if call_count["n"] == 1:
            row = (ACCEPTANCE_TOKEN, QUOTE_NUMBER)
            result.one_or_none.return_value = row
            return result

        # Call 2: admin user lookup for notification
        if call_count["n"] == 2:
            result.scalar_one_or_none.return_value = admin_user
            return result

        return result

    db.execute = AsyncMock(side_effect=_execute_side_effect)
    return db


# Patch targets
PATCH_RESOLVE = "app.modules.portal.service._resolve_token"
PATCH_QUOTE_SVC = "app.modules.quotes_v2.service.QuoteService"
PATCH_LOG_EMAIL = "app.modules.notifications.service.log_email_sent"
PATCH_SEND_EMAIL = "app.tasks.notifications.send_email_task"


class TestQuoteAcceptanceNotification:
    """Req 23: Quote acceptance triggers email notification to org admin."""

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_QUOTE_SVC)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_notification_sent_on_acceptance(
        self, mock_resolve, mock_quote_svc_cls, mock_log_email, mock_send_task
    ):
        """23.1, 23.2: After quote acceptance, email is sent to org admin."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()
        accepted_quote = _make_accepted_quote()

        mock_resolve.return_value = (customer, org)

        mock_svc_instance = MagicMock()
        mock_svc_instance.accept_quote = AsyncMock(return_value=accepted_quote)
        mock_quote_svc_cls.return_value = mock_svc_instance

        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db(admin_user=admin_user)

        result = await accept_portal_quote(db, TOKEN, QUOTE_ID)

        assert result.status == "accepted"
        assert result.quote_id == QUOTE_ID

        # Verify email was logged and sent
        mock_log_email.assert_awaited_once()
        log_kwargs = mock_log_email.call_args.kwargs
        assert log_kwargs["template_type"] == "quote_accepted"
        assert log_kwargs["recipient"] == "admin@workshop.co.nz"

        mock_send_task.assert_awaited_once()
        send_kwargs = mock_send_task.call_args.kwargs
        assert send_kwargs["to_email"] == "admin@workshop.co.nz"
        assert send_kwargs["template_type"] == "quote_accepted"

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_QUOTE_SVC)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_notification_contains_required_fields(
        self, mock_resolve, mock_quote_svc_cls, mock_log_email, mock_send_task
    ):
        """23.3: Notification includes quote number, customer name, accepted date."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()
        accepted_quote = _make_accepted_quote()

        mock_resolve.return_value = (customer, org)

        mock_svc_instance = MagicMock()
        mock_svc_instance.accept_quote = AsyncMock(return_value=accepted_quote)
        mock_quote_svc_cls.return_value = mock_svc_instance

        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db(admin_user=admin_user)

        await accept_portal_quote(db, TOKEN, QUOTE_ID)

        send_kwargs = mock_send_task.call_args.kwargs
        subject = send_kwargs["subject"]
        html_body = send_kwargs["html_body"]

        # Subject contains quote number and customer name
        assert QUOTE_NUMBER in subject
        assert "Jane Doe" in subject

        # HTML body contains all three required fields
        assert QUOTE_NUMBER in html_body
        assert "Jane Doe" in html_body
        assert "15 Jun 2025" in html_body

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_QUOTE_SVC)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_no_admin_user_skips_notification(
        self, mock_resolve, mock_quote_svc_cls, mock_log_email, mock_send_task
    ):
        """When no org_admin exists, notification is skipped gracefully."""
        customer = _make_customer()
        org = _make_org()
        accepted_quote = _make_accepted_quote()

        mock_resolve.return_value = (customer, org)

        mock_svc_instance = MagicMock()
        mock_svc_instance.accept_quote = AsyncMock(return_value=accepted_quote)
        mock_quote_svc_cls.return_value = mock_svc_instance

        db = _mock_db(admin_user=None)

        result = await accept_portal_quote(db, TOKEN, QUOTE_ID)
        assert result.status == "accepted"

        # Email should NOT have been sent
        mock_log_email.assert_not_awaited()
        mock_send_task.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_QUOTE_SVC)
    @patch(PATCH_RESOLVE, new_callable=AsyncMock)
    async def test_email_failure_does_not_break_acceptance(
        self, mock_resolve, mock_quote_svc_cls, mock_log_email, mock_send_task
    ):
        """If email sending fails, the quote acceptance still succeeds."""
        customer = _make_customer()
        org = _make_org()
        admin_user = _make_admin_user()
        accepted_quote = _make_accepted_quote()

        mock_resolve.return_value = (customer, org)

        mock_svc_instance = MagicMock()
        mock_svc_instance.accept_quote = AsyncMock(return_value=accepted_quote)
        mock_quote_svc_cls.return_value = mock_svc_instance

        # Make email logging raise an exception
        mock_log_email.side_effect = Exception("SMTP connection failed")

        db = _mock_db(admin_user=admin_user)

        # Should not raise — acceptance succeeds even if notification fails
        result = await accept_portal_quote(db, TOKEN, QUOTE_ID)
        assert result.status == "accepted"
        assert result.quote_id == QUOTE_ID
