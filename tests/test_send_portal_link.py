"""Unit tests for send_portal_link service function (Task 5.2).

Covers:
  1. Successful portal link send
  2. Validation: portal not enabled
  3. Validation: no portal token
  4. Validation: no email address
  5. Customer not found

Requirements: 13.1, 13.2, 13.3, 13.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.service import send_portal_link
from app.modules.admin.models import Organisation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
PORTAL_TOKEN = uuid.uuid4()


def _make_customer(
    customer_id=None,
    org_id=None,
    portal_token=None,
    enable_portal=True,
    email="jane@example.com",
):
    cust = MagicMock(spec=Customer)
    cust.id = customer_id or CUSTOMER_ID
    cust.org_id = org_id or ORG_ID
    cust.portal_token = portal_token or PORTAL_TOKEN
    cust.enable_portal = enable_portal
    cust.email = email
    cust.first_name = "Jane"
    cust.last_name = "Doe"
    cust.is_anonymised = False
    return cust


def _make_org(org_id=None, name="Test Workshop"):
    org = MagicMock(spec=Organisation)
    org.id = org_id or ORG_ID
    org.name = name
    return org


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _db_returning(db, *results):
    """Configure db.execute to return a sequence of scalar_one_or_none results."""
    side_effects = []
    for r in results:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = r
        side_effects.append(mock_result)
    db.execute = AsyncMock(side_effect=side_effects)


# Patch targets:
# - write_audit_log: imported at top of service.py, so patch at service module
# - log_email_sent: imported locally inside function, patch at source
# - send_email_task: imported locally inside function, patch at source
PATCH_AUDIT = "app.modules.customers.service.write_audit_log"
PATCH_LOG_EMAIL = "app.modules.notifications.service.log_email_sent"
PATCH_SEND_EMAIL = "app.tasks.notifications.send_email_task"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSendPortalLink:
    """Validates: Requirements 13.1, 13.2, 13.3, 13.4"""

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    async def test_successful_send(self, mock_audit, mock_log_email, mock_send_task):
        """Portal link is sent when customer has portal enabled, token, and email."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        _db_returning(db, customer, org)

        result = await send_portal_link(
            db,
            org_id=ORG_ID,
            user_id=USER_ID,
            customer_id=CUSTOMER_ID,
        )

        assert result["message"] == "Portal link sent successfully"
        assert result["recipient"] == "jane@example.com"
        mock_log_email.assert_awaited_once()
        mock_send_task.assert_awaited_once()
        mock_audit.assert_awaited_once()

        # Verify the email task was called with the correct portal URL
        call_kwargs = mock_send_task.call_args
        assert f"/portal/{PORTAL_TOKEN}" in call_kwargs.kwargs.get("html_body", "")

    @pytest.mark.asyncio
    async def test_customer_not_found(self):
        """Raises ValueError when customer does not exist."""
        db = _mock_db()
        _db_returning(db, None)

        with pytest.raises(ValueError, match="Customer not found"):
            await send_portal_link(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_portal_not_enabled(self):
        """Raises ValueError when enable_portal is False (Req 13.4)."""
        db = _mock_db()
        customer = _make_customer(enable_portal=False)
        _db_returning(db, customer)

        with pytest.raises(ValueError, match="Portal access is not enabled"):
            await send_portal_link(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
            )

    @pytest.mark.asyncio
    async def test_no_portal_token(self):
        """Raises ValueError when portal_token is None."""
        db = _mock_db()
        customer = _make_customer(portal_token=None)
        customer.portal_token = None
        _db_returning(db, customer)

        with pytest.raises(ValueError, match="does not have a portal token"):
            await send_portal_link(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
            )

    @pytest.mark.asyncio
    async def test_no_email_address(self):
        """Raises ValueError when customer has no email (Req 13.3)."""
        db = _mock_db()
        customer = _make_customer(email=None)
        customer.email = None
        _db_returning(db, customer)

        with pytest.raises(ValueError, match="no email address"):
            await send_portal_link(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
            )

    @pytest.mark.asyncio
    async def test_empty_email_address(self):
        """Raises ValueError when customer email is empty string."""
        db = _mock_db()
        customer = _make_customer(email="")
        customer.email = ""
        _db_returning(db, customer)

        with pytest.raises(ValueError, match="no email address"):
            await send_portal_link(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
            )

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    async def test_email_contains_portal_url(self, mock_audit, mock_log_email, mock_send_task):
        """The email body contains the correct portal URL format."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        _db_returning(db, customer, org)

        with patch("app.config.settings") as mock_settings:
            mock_settings.frontend_base_url = "https://app.example.com"

            await send_portal_link(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
            )

        call_kwargs = mock_send_task.call_args
        expected_url = f"https://app.example.com/portal/{PORTAL_TOKEN}"
        assert expected_url in call_kwargs.kwargs.get("html_body", "")
        assert expected_url in call_kwargs.kwargs.get("text_body", "")

    @pytest.mark.asyncio
    @patch(PATCH_SEND_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_LOG_EMAIL, new_callable=AsyncMock)
    @patch(PATCH_AUDIT, new_callable=AsyncMock)
    async def test_audit_log_written(self, mock_audit, mock_log_email, mock_send_task):
        """An audit log entry is written after sending the portal link."""
        mock_log_email.return_value = {"id": str(uuid.uuid4())}

        db = _mock_db()
        customer = _make_customer()
        org = _make_org()
        _db_returning(db, customer, org)

        await send_portal_link(
            db,
            org_id=ORG_ID,
            user_id=USER_ID,
            customer_id=CUSTOMER_ID,
            ip_address="192.168.1.1",
        )

        mock_audit.assert_awaited_once()
        audit_kwargs = mock_audit.call_args.kwargs
        assert audit_kwargs["action"] == "customer.portal_link_sent"
        assert audit_kwargs["entity_id"] == CUSTOMER_ID
        assert audit_kwargs["ip_address"] == "192.168.1.1"
