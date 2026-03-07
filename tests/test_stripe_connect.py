"""Unit tests for Task 11.2 — Stripe Connect OAuth flow.

Tests cover:
  - generate_connect_url: URL structure, state token format, CSRF token
  - handle_connect_callback: code exchange, state validation, error handling
  - Schema validation for StripeConnectInitResponse / StripeConnectCallbackResponse
  - Billing router endpoint logic (initiate + callback)

Requirements: 25.1, 25.2
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.stripe_connect import (
    STRIPE_CONNECT_AUTHORIZE_URL,
    generate_connect_url,
    handle_connect_callback,
)
from app.modules.payments.schemas import (
    StripeConnectCallbackResponse,
    StripeConnectInitResponse,
)


# ---------------------------------------------------------------------------
# Tests for generate_connect_url
# ---------------------------------------------------------------------------


class TestGenerateConnectUrl:
    """Tests for the generate_connect_url helper."""

    def test_returns_url_and_state(self):
        org_id = uuid.uuid4()
        url, state = generate_connect_url(org_id)
        assert url.startswith(STRIPE_CONNECT_AUTHORIZE_URL)
        assert str(org_id) in state

    def test_state_contains_org_id_and_random_token(self):
        org_id = uuid.uuid4()
        _, state = generate_connect_url(org_id)
        parts = state.split(":", 1)
        assert len(parts) == 2
        assert parts[0] == str(org_id)
        assert len(parts[1]) > 10  # random token is non-trivial

    def test_url_contains_required_params(self):
        org_id = uuid.uuid4()
        url, _ = generate_connect_url(org_id)
        assert "response_type=code" in url
        assert "scope=read_write" in url
        assert "redirect_uri=" in url

    def test_unique_state_per_call(self):
        org_id = uuid.uuid4()
        _, state1 = generate_connect_url(org_id)
        _, state2 = generate_connect_url(org_id)
        assert state1 != state2  # CSRF tokens must be unique


# ---------------------------------------------------------------------------
# Tests for handle_connect_callback
# ---------------------------------------------------------------------------


class TestHandleConnectCallback:
    """Tests for the handle_connect_callback helper."""

    @pytest.mark.asyncio
    async def test_successful_exchange(self):
        org_id = uuid.uuid4()
        state = f"{org_id}:random_token_abc"
        code = "ac_test_code_123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "stripe_user_id": "acct_test123",
            "scope": "read_write",
            "token_type": "bearer",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.integrations.stripe_connect.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await handle_connect_callback(code, state)

        assert result["stripe_user_id"] == "acct_test123"
        assert result["org_id"] == str(org_id)

    @pytest.mark.asyncio
    async def test_invalid_state_format(self):
        with pytest.raises(ValueError, match="Invalid state token format"):
            await handle_connect_callback("code", "no_colon_here")

    @pytest.mark.asyncio
    async def test_invalid_org_id_in_state(self):
        with pytest.raises(ValueError, match="Invalid org_id"):
            await handle_connect_callback("code", "not-a-uuid:random")

    @pytest.mark.asyncio
    async def test_stripe_api_error_propagates(self):
        org_id = uuid.uuid4()
        state = f"{org_id}:token"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("app.integrations.stripe_connect.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await handle_connect_callback("bad_code", state)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestStripeConnectSchemas:
    """Tests for Stripe Connect Pydantic schemas."""

    def test_init_response_valid(self):
        resp = StripeConnectInitResponse(
            authorize_url="https://connect.stripe.com/oauth/authorize?foo=bar"
        )
        assert "stripe.com" in resp.authorize_url
        assert resp.message  # default message is set

    def test_callback_response_valid(self):
        org_id = uuid.uuid4()
        resp = StripeConnectCallbackResponse(
            stripe_account_id="acct_test123",
            org_id=org_id,
        )
        assert resp.stripe_account_id == "acct_test123"
        assert resp.org_id == org_id
        assert resp.message  # default message is set


# ---------------------------------------------------------------------------
# Billing router endpoint tests
# ---------------------------------------------------------------------------


class TestBillingRouterInitiate:
    """Tests for POST /billing/stripe/connect endpoint logic."""

    @pytest.mark.asyncio
    async def test_initiate_returns_authorize_url(self):
        """Verify the endpoint generates a valid Stripe Connect URL."""
        from app.modules.billing.router import initiate_stripe_connect

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        request = MagicMock()
        request.state.org_id = str(org_id)
        request.state.user_id = str(user_id)
        request.client.host = "127.0.0.1"

        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        with patch("app.modules.billing.router.write_audit_log", new_callable=AsyncMock):
            result = await initiate_stripe_connect(request=request, db=db)

        assert isinstance(result, StripeConnectInitResponse)
        assert STRIPE_CONNECT_AUTHORIZE_URL in result.authorize_url

    @pytest.mark.asyncio
    async def test_initiate_rejects_missing_org_context(self):
        """Verify the endpoint rejects requests without org context."""
        from app.modules.billing.router import initiate_stripe_connect

        request = MagicMock()
        request.state.org_id = None
        request.state.user_id = None
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        result = await initiate_stripe_connect(request=request, db=db)
        assert result.status_code == 403


class TestBillingRouterCallback:
    """Tests for GET /billing/stripe/connect/callback endpoint logic."""

    @pytest.mark.asyncio
    async def test_callback_stores_account_id(self):
        """Verify the callback stores the connected account on the org."""
        from app.modules.billing.router import stripe_connect_callback

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        state = f"{org_id}:random_csrf_token"

        request = MagicMock()
        request.state.org_id = str(org_id)
        request.state.user_id = str(user_id)
        request.client.host = "127.0.0.1"

        # Mock the organisation record
        mock_org = MagicMock()
        mock_org.id = org_id
        mock_org.stripe_connect_account_id = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_org

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch(
                "app.modules.billing.router.handle_connect_callback",
                new_callable=AsyncMock,
                return_value={
                    "stripe_user_id": "acct_connected_123",
                    "org_id": str(org_id),
                },
            ),
            patch("app.modules.billing.router.write_audit_log", new_callable=AsyncMock),
        ):
            result = await stripe_connect_callback(
                request=request, code="ac_test", state=state, db=db
            )

        assert isinstance(result, StripeConnectCallbackResponse)
        assert result.stripe_account_id == "acct_connected_123"
        assert mock_org.stripe_connect_account_id == "acct_connected_123"

    @pytest.mark.asyncio
    async def test_callback_rejects_mismatched_org(self):
        """Verify the callback rejects state tokens from a different org."""
        from app.modules.billing.router import stripe_connect_callback

        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()
        state = f"{other_org_id}:random_token"

        request = MagicMock()
        request.state.org_id = str(org_id)
        request.state.user_id = str(uuid.uuid4())
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        result = await stripe_connect_callback(
            request=request, code="ac_test", state=state, db=db
        )
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_callback_rejects_invalid_state(self):
        """Verify the callback rejects malformed state tokens."""
        from app.modules.billing.router import stripe_connect_callback

        org_id = uuid.uuid4()

        request = MagicMock()
        request.state.org_id = str(org_id)
        request.state.user_id = str(uuid.uuid4())
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        result = await stripe_connect_callback(
            request=request, code="ac_test", state="bad_state", db=db
        )
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_handles_stripe_exchange_failure(self):
        """Verify the callback handles Stripe API errors gracefully."""
        from app.modules.billing.router import stripe_connect_callback

        org_id = uuid.uuid4()
        state = f"{org_id}:random_token"

        request = MagicMock()
        request.state.org_id = str(org_id)
        request.state.user_id = str(uuid.uuid4())
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        with patch(
            "app.modules.billing.router.handle_connect_callback",
            new_callable=AsyncMock,
            side_effect=Exception("Stripe API error"),
        ):
            result = await stripe_connect_callback(
                request=request, code="bad_code", state=state, db=db
            )

        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_rejects_missing_stripe_user_id(self):
        """Verify the callback rejects responses without stripe_user_id."""
        from app.modules.billing.router import stripe_connect_callback

        org_id = uuid.uuid4()
        state = f"{org_id}:random_token"

        request = MagicMock()
        request.state.org_id = str(org_id)
        request.state.user_id = str(uuid.uuid4())
        request.client.host = "127.0.0.1"

        db = AsyncMock()

        with patch(
            "app.modules.billing.router.handle_connect_callback",
            new_callable=AsyncMock,
            return_value={"scope": "read_write"},  # no stripe_user_id
        ):
            result = await stripe_connect_callback(
                request=request, code="ac_test", state=state, db=db
            )

        assert result.status_code == 400
