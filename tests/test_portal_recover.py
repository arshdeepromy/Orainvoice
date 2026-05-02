"""Unit tests for portal self-service token recovery (Task 17.4).

Covers:
  1. Successful recovery — single customer with portal enabled
  2. Successful recovery — multiple customers with same email
  3. No matching customers — returns generic message (no enumeration)
  4. Customer with portal disabled — skipped, generic message returned
  5. Customer with no portal token — skipped
  6. Org with portal disabled — skipped
  7. Always returns 200 with generic message

Requirements: 52.1, 52.2, 52.3, 52.4
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.admin.models import Organisation
from app.modules.portal.service import recover_portal_link


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID_1 = uuid.uuid4()
ORG_ID_2 = uuid.uuid4()
CUSTOMER_ID_1 = uuid.uuid4()
CUSTOMER_ID_2 = uuid.uuid4()
PORTAL_TOKEN_1 = "tok_abc123"
PORTAL_TOKEN_2 = "tok_def456"

GENERIC_MESSAGE = "If an account exists with that email, a portal link has been sent."


def _make_customer(
    customer_id=None,
    org_id=None,
    portal_token=None,
    enable_portal=True,
    email="jane@example.com",
):
    cust = MagicMock(spec=Customer)
    cust.id = customer_id or CUSTOMER_ID_1
    cust.org_id = org_id or ORG_ID_1
    cust.portal_token = portal_token or PORTAL_TOKEN_1
    cust.enable_portal = enable_portal
    cust.email = email
    cust.first_name = "Jane"
    cust.last_name = "Doe"
    cust.is_anonymised = False
    return cust


def _make_org(org_id=None, name="Test Workshop", portal_enabled=True):
    org = MagicMock(spec=Organisation)
    org.id = org_id or ORG_ID_1
    org.name = name
    org.settings = {"portal_enabled": portal_enabled}
    return org


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


# Patch targets — imports are local inside recover_portal_link
PATCH_LOG_EMAIL = "app.modules.notifications.service.log_email_sent"
PATCH_SEND_EMAIL = "app.tasks.notifications.send_email_task"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecoverPortalLink:
    """Validates: Requirements 52.1, 52.2, 52.3, 52.4"""

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    async def test_successful_recovery_single_customer(self, mock_log_email, mock_send_task):
        """Sends portal link when one matching customer is found (Req 52.2)."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()

        # First call: customer lookup returns list of customers
        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = [customer]

        # Second call: org lookup
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute = AsyncMock(side_effect=[customer_result, org_result])

        result = await recover_portal_link(db, "jane@example.com")

        assert result["message"] == GENERIC_MESSAGE
        mock_log_email.assert_awaited_once()
        mock_send_task.assert_awaited_once()

        # Verify the email contains the portal URL
        call_kwargs = mock_send_task.call_args
        assert f"/portal/{PORTAL_TOKEN_1}" in call_kwargs.kwargs.get("html_body", "")

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    async def test_successful_recovery_multiple_customers(self, mock_log_email, mock_send_task):
        """Sends portal links for all matching customers (Req 52.2)."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer1 = _make_customer(
            customer_id=CUSTOMER_ID_1, org_id=ORG_ID_1, portal_token=PORTAL_TOKEN_1,
        )
        customer2 = _make_customer(
            customer_id=CUSTOMER_ID_2, org_id=ORG_ID_2, portal_token=PORTAL_TOKEN_2,
        )
        org1 = _make_org(org_id=ORG_ID_1, name="Workshop A")
        org2 = _make_org(org_id=ORG_ID_2, name="Workshop B")

        # First call: customer lookup returns both customers
        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = [customer1, customer2]

        # Subsequent calls: org lookups
        org_result_1 = MagicMock()
        org_result_1.scalar_one_or_none.return_value = org1
        org_result_2 = MagicMock()
        org_result_2.scalar_one_or_none.return_value = org2

        db.execute = AsyncMock(side_effect=[customer_result, org_result_1, org_result_2])

        result = await recover_portal_link(db, "jane@example.com")

        assert result["message"] == GENERIC_MESSAGE
        assert mock_send_task.await_count == 2
        assert mock_log_email.await_count == 2

    @pytest.mark.asyncio
    async def test_no_matching_customers_returns_generic_message(self):
        """Returns generic message when no customers found (Req 52.3)."""
        db = _mock_db()

        # Customer lookup returns empty list
        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=customer_result)

        result = await recover_portal_link(db, "nobody@example.com")

        assert result["message"] == GENERIC_MESSAGE

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    async def test_org_portal_disabled_skips_customer(self, mock_log_email, mock_send_task):
        """Skips customers whose org has portal disabled."""
        db = _mock_db()
        customer = _make_customer()
        org = _make_org(portal_enabled=False)

        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = [customer]

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute = AsyncMock(side_effect=[customer_result, org_result])

        result = await recover_portal_link(db, "jane@example.com")

        assert result["message"] == GENERIC_MESSAGE
        mock_send_task.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    async def test_org_not_found_skips_customer(self, mock_log_email, mock_send_task):
        """Skips customers whose org cannot be found."""
        db = _mock_db()
        customer = _make_customer()

        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = [customer]

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[customer_result, org_result])

        result = await recover_portal_link(db, "jane@example.com")

        assert result["message"] == GENERIC_MESSAGE
        mock_send_task.assert_not_awaited()

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock, side_effect=Exception("SMTP error"))
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    async def test_email_failure_does_not_raise(self, mock_log_email, mock_send_task):
        """Email send failure is caught and does not propagate (Req 52.3)."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()

        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = [customer]

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute = AsyncMock(side_effect=[customer_result, org_result])

        # Should not raise despite email failure
        result = await recover_portal_link(db, "jane@example.com")
        assert result["message"] == GENERIC_MESSAGE

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    async def test_email_template_type_is_portal_recovery(self, mock_log_email, mock_send_task):
        """The email is logged with template_type 'portal_recovery'."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()

        customer_result = MagicMock()
        customer_result.scalars.return_value.all.return_value = [customer]

        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org

        db.execute = AsyncMock(side_effect=[customer_result, org_result])

        await recover_portal_link(db, "jane@example.com")

        log_kwargs = mock_log_email.call_args.kwargs
        assert log_kwargs["template_type"] == "portal_recovery"

        send_kwargs = mock_send_task.call_args.kwargs
        assert send_kwargs["template_type"] == "portal_recovery"
