"""Unit tests for Online Payments status and disconnect endpoints (Task 1.5).

Tests cover:
  - GET /online-payments/status: connected vs not-connected states, masked ID
  - POST /online-payments/disconnect: clears account, writes audit log, 400 on no account
  - Auth: unauthenticated → 401, salesperson → 403
  - Security: response never contains full account ID

Requirements: 1.6, 1.7, 3.2, 3.4
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.payments.router import (
    get_online_payments_status,
    disconnect_online_payments,
)
from app.modules.payments.schemas import (
    OnlinePaymentsDisconnectResponse,
    OnlinePaymentsStatusResponse,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_request(org_id=None, user_id=None, ip="127.0.0.1"):
    """Create a mock Request with state attributes matching _extract_org_context."""
    request = MagicMock()
    request.state.org_id = str(org_id) if org_id else None
    request.state.user_id = str(user_id) if user_id else None
    request.state.client_ip = ip
    return request


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    return db


def _make_org(org_id=None, stripe_connect_account_id=None):
    """Create a mock Organisation with the fields the endpoints read."""
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    org.stripe_connect_account_id = stripe_connect_account_id
    return org


def _make_integration_config(config_data: dict):
    """Create a mock IntegrationConfig row with encrypted config."""
    config_row = MagicMock()
    config_row.config_encrypted = json.dumps(config_data).encode()
    return config_row


# ---------------------------------------------------------------------------
# 1. GET /online-payments/status — connected org
#    Validates: Requirements 1.6, 1.7
# ---------------------------------------------------------------------------


class TestOnlinePaymentsStatusConnected:
    """Status endpoint when org has a connected Stripe account."""

    @pytest.mark.asyncio
    async def test_connected_org_returns_is_connected_true(self):
        """Req 1.6: Status API returns is_connected=True when org has account."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        account_id = "acct_1234567890abcdef"

        org = _make_org(org_id=org_id, stripe_connect_account_id=account_id)

        db = _mock_db()
        # First execute: fetch Organisation
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        # Second execute: fetch IntegrationConfig (for application_fee_percent)
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[org_result, config_result])

        request = _mock_request(org_id=org_id, user_id=user_id)

        with patch(
            "app.integrations.stripe_billing.get_stripe_connect_client_id",
            new_callable=AsyncMock,
            return_value="ca_test_client_id",
        ):
            result = await get_online_payments_status(request=request, db=db)

        assert isinstance(result, OnlinePaymentsStatusResponse)
        assert result.is_connected is True
        assert result.account_id_last4 == "cdef"
        assert result.connect_client_id_configured is True

    @pytest.mark.asyncio
    async def test_masked_id_is_last_4_chars(self):
        """Req 1.7: Only last 4 characters of account ID are returned."""
        org_id = uuid.uuid4()
        account_id = "acct_xK3mTestValue"

        org = _make_org(org_id=org_id, stripe_connect_account_id=account_id)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[org_result, config_result])

        request = _mock_request(org_id=org_id, user_id=uuid.uuid4())

        with patch(
            "app.integrations.stripe_billing.get_stripe_connect_client_id",
            new_callable=AsyncMock,
            return_value="ca_test",
        ):
            result = await get_online_payments_status(request=request, db=db)

        assert result.account_id_last4 == "alue"
        assert len(result.account_id_last4) == 4


# ---------------------------------------------------------------------------
# 2. GET /online-payments/status — not connected org
#    Validates: Requirements 1.6, 1.7
# ---------------------------------------------------------------------------


class TestOnlinePaymentsStatusNotConnected:
    """Status endpoint when org has no connected Stripe account."""

    @pytest.mark.asyncio
    async def test_not_connected_org_returns_is_connected_false(self):
        """Req 1.6: Status API returns is_connected=False when no account."""
        org_id = uuid.uuid4()
        org = _make_org(org_id=org_id, stripe_connect_account_id=None)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[org_result, config_result])

        request = _mock_request(org_id=org_id, user_id=uuid.uuid4())

        with patch(
            "app.integrations.stripe_billing.get_stripe_connect_client_id",
            new_callable=AsyncMock,
            return_value="ca_test",
        ):
            result = await get_online_payments_status(request=request, db=db)

        assert isinstance(result, OnlinePaymentsStatusResponse)
        assert result.is_connected is False
        assert result.account_id_last4 == ""


# ---------------------------------------------------------------------------
# 3. Response never contains full account ID
#    Validates: Requirements 1.6, 1.7
# ---------------------------------------------------------------------------


class TestStatusNeverLeaksFullAccountId:
    """Security: the status response must never contain the full account ID."""

    @pytest.mark.asyncio
    async def test_response_does_not_contain_full_account_id(self):
        """Req 1.7: Full account ID must not appear in the response."""
        org_id = uuid.uuid4()
        full_account_id = "acct_1MqPPR2eZvKYlo2C"

        org = _make_org(org_id=org_id, stripe_connect_account_id=full_account_id)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[org_result, config_result])

        request = _mock_request(org_id=org_id, user_id=uuid.uuid4())

        with patch(
            "app.integrations.stripe_billing.get_stripe_connect_client_id",
            new_callable=AsyncMock,
            return_value="ca_test",
        ):
            result = await get_online_payments_status(request=request, db=db)

        # Serialize the response and check the full ID is not present
        response_json = result.model_dump_json()
        assert full_account_id not in response_json
        # But the last 4 chars should be there
        assert "o2C" in response_json or "lo2C" in response_json


# ---------------------------------------------------------------------------
# 4. POST /online-payments/disconnect — clears account
#    Validates: Requirement 3.2
# ---------------------------------------------------------------------------


class TestDisconnectClearsAccount:
    """Disconnect endpoint clears stripe_connect_account_id to None."""

    @pytest.mark.asyncio
    async def test_disconnect_sets_account_to_none(self):
        """Req 3.2: Disconnect clears the connected account ID."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        account_id = "acct_disconnect_test1234"

        org = _make_org(org_id=org_id, stripe_connect_account_id=account_id)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=org_result)

        request = _mock_request(org_id=org_id, user_id=user_id)

        with patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await disconnect_online_payments(request=request, db=db)

        assert isinstance(result, OnlinePaymentsDisconnectResponse)
        assert org.stripe_connect_account_id is None
        assert result.previous_account_last4 == "1234"

    @pytest.mark.asyncio
    async def test_disconnect_returns_masked_previous_id(self):
        """Req 3.2: Response contains only last 4 chars of previous account."""
        org_id = uuid.uuid4()
        account_id = "acct_abcdefghijklmnop"

        org = _make_org(org_id=org_id, stripe_connect_account_id=account_id)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=org_result)

        request = _mock_request(org_id=org_id, user_id=uuid.uuid4())

        with patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await disconnect_online_payments(request=request, db=db)

        assert result.previous_account_last4 == "mnop"
        # Full ID must not appear in the response
        response_json = result.model_dump_json()
        assert account_id not in response_json


# ---------------------------------------------------------------------------
# 5. POST /online-payments/disconnect — writes audit log
#    Validates: Requirement 3.4
# ---------------------------------------------------------------------------


class TestDisconnectWritesAuditLog:
    """Disconnect endpoint writes an audit log entry with masked ID."""

    @pytest.mark.asyncio
    async def test_audit_log_written_with_masked_id(self):
        """Req 3.4: Audit log records disconnection with masked previous ID."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        account_id = "acct_auditLogTest9876"

        org = _make_org(org_id=org_id, stripe_connect_account_id=account_id)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=org_result)

        request = _mock_request(org_id=org_id, user_id=user_id, ip="10.0.0.1")

        with patch(
            "app.core.audit.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await disconnect_online_payments(request=request, db=db)

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "stripe_connect.disconnected"
        assert call_kwargs["entity_type"] == "organisation"
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["ip_address"] == "10.0.0.1"
        # before_value should contain masked ID, not the full one
        assert call_kwargs["before_value"]["stripe_connect_account_id_last4"] == "9876"
        assert call_kwargs["after_value"]["stripe_connect_account_id"] is None


# ---------------------------------------------------------------------------
# 6. POST /online-payments/disconnect — no account → 400
#    Validates: Requirement 3.2
# ---------------------------------------------------------------------------


class TestDisconnectNoAccount:
    """Disconnect endpoint returns 400 when no Stripe account is connected."""

    @pytest.mark.asyncio
    async def test_disconnect_no_account_returns_400(self):
        """Req 3.2: Disconnect with no connected account returns 400."""
        org_id = uuid.uuid4()
        org = _make_org(org_id=org_id, stripe_connect_account_id=None)

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=org_result)

        request = _mock_request(org_id=org_id, user_id=uuid.uuid4())

        result = await disconnect_online_payments(request=request, db=db)

        # Should be a JSONResponse with 400 status
        assert result.status_code == 400
        assert b"No Stripe account" in result.body

    @pytest.mark.asyncio
    async def test_disconnect_empty_string_account_returns_400(self):
        """Edge case: empty string account ID also returns 400."""
        org_id = uuid.uuid4()
        org = _make_org(org_id=org_id, stripe_connect_account_id="")

        db = _mock_db()
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(return_value=org_result)

        request = _mock_request(org_id=org_id, user_id=uuid.uuid4())

        result = await disconnect_online_payments(request=request, db=db)

        assert result.status_code == 400


# ---------------------------------------------------------------------------
# 7. Auth: unauthenticated → 401, salesperson → 403
#    Validates: Requirements 1.6, 3.2
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """Auth enforcement via require_role dependency.

    Note: require_role is a FastAPI dependency that runs before the
    endpoint function. We test it by calling the dependency check
    directly, since the endpoint functions themselves don't re-check
    roles (they rely on the dependency).
    """

    @pytest.mark.asyncio
    async def test_unauthenticated_request_raises_401(self):
        """Unauthenticated user gets 401 from require_role dependency."""
        from fastapi import HTTPException
        from app.modules.auth.rbac import require_role

        # require_role returns Depends(_check), extract the inner function
        dep = require_role("org_admin", "global_admin")
        check_fn = dep.dependency

        request = MagicMock()
        request.state.user_id = None
        request.state.org_id = None
        request.state.role = None

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_salesperson_role_raises_403_for_status(self):
        """Salesperson role gets 403 from status endpoint's require_role."""
        from fastapi import HTTPException
        from app.modules.auth.rbac import require_role

        dep = require_role("org_admin", "global_admin")
        check_fn = dep.dependency

        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = str(uuid.uuid4())
        request.state.role = "salesperson"

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_salesperson_role_raises_403_for_disconnect(self):
        """Salesperson role gets 403 from disconnect endpoint's require_role."""
        from fastapi import HTTPException
        from app.modules.auth.rbac import require_role

        dep = require_role("org_admin")
        check_fn = dep.dependency

        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = str(uuid.uuid4())
        request.state.role = "salesperson"

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_org_admin_passes_status_role_check(self):
        """Org admin passes the status endpoint's role check."""
        from app.modules.auth.rbac import require_role

        dep = require_role("org_admin", "global_admin")
        check_fn = dep.dependency

        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = str(uuid.uuid4())
        request.state.role = "org_admin"

        # Should not raise
        await check_fn(request)

    @pytest.mark.asyncio
    async def test_global_admin_passes_status_role_check(self):
        """Global admin passes the status endpoint's role check."""
        from app.modules.auth.rbac import require_role

        dep = require_role("org_admin", "global_admin")
        check_fn = dep.dependency

        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = str(uuid.uuid4())
        request.state.role = "global_admin"

        # Should not raise
        await check_fn(request)
