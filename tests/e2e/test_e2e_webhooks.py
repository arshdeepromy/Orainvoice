"""E2E tests for Connexus webhook endpoints.

Covers:
  - Incoming SMS webhook: valid HMAC → 200, invalid HMAC → 401,
    missing signature → 401 (when secret configured), no secret → 200 (dev mode)
  - Delivery status webhook: same pattern as incoming SMS
  - Uses sign_webhook_payload from app/core/webhook_security.py to generate
    valid signatures

Uses httpx.AsyncClient with the FastAPI test client for full middleware stack
coverage.  External dependencies (Redis, database) are mocked.

Requirements: 19.4
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx

from app.core.webhook_security import sign_webhook_payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WEBHOOK_SECRET = "e2e-test-webhook-secret"

_INCOMING_SMS_URL = "/api/webhooks/connexus/incoming"
_DELIVERY_STATUS_URL = "/api/webhooks/connexus/status"


def _incoming_payload() -> dict:
    return {
        "messageId": "msg-e2e-001",
        "from": "+6421000001",
        "to": "+6421000002",
        "body": "Hello from E2E test",
    }


def _status_payload() -> dict:
    return {"messageId": "msg-e2e-001", "status": 1}


def _sign(payload_dict: dict, secret: str = _WEBHOOK_SECRET) -> str:
    """Sign a JSON payload and return the hex-digest signature."""
    return sign_webhook_payload(json.dumps(payload_dict).encode(), secret)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Provide a mock async database session."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    return db


@pytest.fixture
def app(mock_db):
    """Create a fresh FastAPI app with rate limiter and RBAC bypassed."""
    import app.middleware.rate_limit as rl_mod
    import app.middleware.rbac as rbac_mod

    # Bypass rate limiter
    orig_rl_call = rl_mod.RateLimitMiddleware.__call__

    async def _rl_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rl_mod.RateLimitMiddleware.__call__ = _rl_passthrough

    # Bypass RBAC middleware
    orig_rbac_call = rbac_mod.RBACMiddleware.__call__

    async def _rbac_passthrough(self, scope, receive, send):
        await self.app(scope, receive, send)

    rbac_mod.RBACMiddleware.__call__ = _rbac_passthrough

    from app.main import create_app

    application = create_app()

    # Override the database dependency with the mock
    from app.core.database import get_db_session

    async def _mock_db_session():
        yield mock_db

    application.dependency_overrides[get_db_session] = _mock_db_session

    yield application

    application.dependency_overrides.clear()
    rl_mod.RateLimitMiddleware.__call__ = orig_rl_call
    rbac_mod.RBACMiddleware.__call__ = orig_rbac_call


@pytest_asyncio.fixture
async def client(app):
    """Provide an httpx.AsyncClient wired to the FastAPI test app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# 1. Incoming SMS webhook — valid HMAC signature
# ---------------------------------------------------------------------------


class TestIncomingSmsWebhook:
    """E2E tests for the incoming SMS webhook endpoint."""

    @pytest.mark.asyncio
    async def test_valid_signature_returns_200(self, client):
        """Valid HMAC signature passes through the full middleware stack."""
        payload = _incoming_payload()
        body = json.dumps(payload).encode()
        sig = sign_webhook_payload(body, _WEBHOOK_SECRET)

        with (
            patch(
                "app.modules.sms_chat.router_webhooks.settings",
            ) as mock_settings,
            patch(
                "app.modules.sms_chat.router_webhooks.async_session_factory",
            ),
            patch(
                "app.modules.sms_chat.router_webhooks.handle_incoming_sms",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _INCOMING_SMS_URL,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": sig,
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, client):
        """Invalid HMAC signature returns 401 through the full stack."""
        payload = _incoming_payload()
        body = json.dumps(payload).encode()

        with patch(
            "app.modules.sms_chat.router_webhooks.settings",
        ) as mock_settings:
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _INCOMING_SMS_URL,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": "bad-signature",
                },
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid webhook signature"

    @pytest.mark.asyncio
    async def test_missing_signature_returns_401(self, client):
        """Missing signature header returns 401 when secret is configured."""
        payload = _incoming_payload()
        body = json.dumps(payload).encode()

        with patch(
            "app.modules.sms_chat.router_webhooks.settings",
        ) as mock_settings:
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _INCOMING_SMS_URL,
                content=body,
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid webhook signature"

    @pytest.mark.asyncio
    async def test_no_secret_configured_passes_dev_mode(self, client):
        """No webhook secret configured → request passes (dev mode)."""
        payload = _incoming_payload()
        body = json.dumps(payload).encode()

        with (
            patch(
                "app.modules.sms_chat.router_webhooks.settings",
            ) as mock_settings,
            patch(
                "app.modules.sms_chat.router_webhooks.async_session_factory",
            ),
            patch(
                "app.modules.sms_chat.router_webhooks.handle_incoming_sms",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.connexus_webhook_secret = ""
            resp = await client.post(
                _INCOMING_SMS_URL,
                content=body,
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_401(self, client):
        """Signature computed with a different secret returns 401."""
        payload = _incoming_payload()
        body = json.dumps(payload).encode()
        sig = sign_webhook_payload(body, "wrong-secret")

        with patch(
            "app.modules.sms_chat.router_webhooks.settings",
        ) as mock_settings:
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _INCOMING_SMS_URL,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": sig,
                },
            )

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. Delivery status webhook — same pattern
# ---------------------------------------------------------------------------


class TestDeliveryStatusWebhook:
    """E2E tests for the delivery status webhook endpoint."""

    @pytest.mark.asyncio
    async def test_valid_signature_returns_200(self, client):
        """Valid HMAC signature passes through the full middleware stack."""
        payload = _status_payload()
        body = json.dumps(payload).encode()
        sig = sign_webhook_payload(body, _WEBHOOK_SECRET)

        with (
            patch(
                "app.modules.sms_chat.router_webhooks.settings",
            ) as mock_settings,
            patch(
                "app.modules.sms_chat.router_webhooks.async_session_factory",
            ),
            patch(
                "app.modules.sms_chat.router_webhooks.handle_delivery_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _DELIVERY_STATUS_URL,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": sig,
                },
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self, client):
        """Invalid HMAC signature returns 401 through the full stack."""
        payload = _status_payload()
        body = json.dumps(payload).encode()

        with patch(
            "app.modules.sms_chat.router_webhooks.settings",
        ) as mock_settings:
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _DELIVERY_STATUS_URL,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": "bad-signature",
                },
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid webhook signature"

    @pytest.mark.asyncio
    async def test_missing_signature_returns_401(self, client):
        """Missing signature header returns 401 when secret is configured."""
        payload = _status_payload()
        body = json.dumps(payload).encode()

        with patch(
            "app.modules.sms_chat.router_webhooks.settings",
        ) as mock_settings:
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _DELIVERY_STATUS_URL,
                content=body,
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid webhook signature"

    @pytest.mark.asyncio
    async def test_no_secret_configured_passes_dev_mode(self, client):
        """No webhook secret configured → request passes (dev mode)."""
        payload = _status_payload()
        body = json.dumps(payload).encode()

        with (
            patch(
                "app.modules.sms_chat.router_webhooks.settings",
            ) as mock_settings,
            patch(
                "app.modules.sms_chat.router_webhooks.async_session_factory",
            ),
            patch(
                "app.modules.sms_chat.router_webhooks.handle_delivery_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.connexus_webhook_secret = ""
            resp = await client.post(
                _DELIVERY_STATUS_URL,
                content=body,
                headers={"content-type": "application/json"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_401(self, client):
        """Signature computed with a different secret returns 401."""
        payload = _status_payload()
        body = json.dumps(payload).encode()
        sig = sign_webhook_payload(body, "wrong-secret")

        with patch(
            "app.modules.sms_chat.router_webhooks.settings",
        ) as mock_settings:
            mock_settings.connexus_webhook_secret = _WEBHOOK_SECRET
            resp = await client.post(
                _DELIVERY_STATUS_URL,
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": sig,
                },
            )

        assert resp.status_code == 401
