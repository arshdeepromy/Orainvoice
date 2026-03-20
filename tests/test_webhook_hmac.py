"""Unit tests for Connexus webhook HMAC signature verification (REM-03, REM-14).

Validates Requirements 4.1, 4.2, 4.3, 4.5.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.webhook_security import sign_webhook_payload
from app.modules.sms_chat.router_webhooks import router

app = FastAPI()
app.include_router(router)


@pytest.fixture
def sample_incoming_payload() -> dict:
    return {
        "messageId": "msg-001",
        "from": "+6421000001",
        "to": "+6421000002",
        "body": "Hello",
    }


@pytest.fixture
def sample_status_payload() -> dict:
    return {
        "messageId": "msg-001",
        "status": 1,
    }


# ── Dev mode: no secret configured → skip verification ──────────────


@pytest.mark.asyncio
async def test_incoming_no_secret_allows_request(sample_incoming_payload: dict):
    """When no webhook secret is configured, requests pass through (dev mode)."""
    body = json.dumps(sample_incoming_payload).encode()
    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = ""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Mock the service call to avoid DB dependency
            with patch("app.modules.sms_chat.router_webhooks.async_session_factory"):
                with patch("app.modules.sms_chat.router_webhooks.handle_incoming_sms"):
                    resp = await client.post(
                        "/api/webhooks/connexus/incoming",
                        content=body,
                        headers={"content-type": "application/json"},
                    )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_status_no_secret_allows_request(sample_status_payload: dict):
    """When no webhook secret is configured, status requests pass through."""
    body = json.dumps(sample_status_payload).encode()
    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = ""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.modules.sms_chat.router_webhooks.async_session_factory"):
                with patch("app.modules.sms_chat.router_webhooks.handle_delivery_status"):
                    resp = await client.post(
                        "/api/webhooks/connexus/status",
                        content=body,
                        headers={"content-type": "application/json"},
                    )
        assert resp.status_code == 200


# ── Secret configured: valid signature → 200 ────────────────────────


@pytest.mark.asyncio
async def test_incoming_valid_signature_passes(sample_incoming_payload: dict):
    """Valid HMAC signature allows the request through."""
    secret = "test-secret-123"
    body = json.dumps(sample_incoming_payload).encode()
    sig = sign_webhook_payload(body, secret)

    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = secret
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.modules.sms_chat.router_webhooks.async_session_factory"):
                with patch("app.modules.sms_chat.router_webhooks.handle_incoming_sms"):
                    resp = await client.post(
                        "/api/webhooks/connexus/incoming",
                        content=body,
                        headers={
                            "content-type": "application/json",
                            "x-connexus-signature": sig,
                        },
                    )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_status_valid_signature_passes(sample_status_payload: dict):
    """Valid HMAC signature allows the status request through."""
    secret = "test-secret-456"
    body = json.dumps(sample_status_payload).encode()
    sig = sign_webhook_payload(body, secret)

    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = secret
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.modules.sms_chat.router_webhooks.async_session_factory"):
                with patch("app.modules.sms_chat.router_webhooks.handle_delivery_status"):
                    resp = await client.post(
                        "/api/webhooks/connexus/status",
                        content=body,
                        headers={
                            "content-type": "application/json",
                            "x-connexus-signature": sig,
                        },
                    )
        assert resp.status_code == 200


# ── Secret configured: invalid/missing signature → 401 ──────────────


@pytest.mark.asyncio
async def test_incoming_invalid_signature_returns_401(sample_incoming_payload: dict):
    """Invalid HMAC signature returns 401."""
    secret = "test-secret-789"
    body = json.dumps(sample_incoming_payload).encode()

    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = secret
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/connexus/incoming",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": "bad-signature",
                },
            )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid webhook signature"


@pytest.mark.asyncio
async def test_incoming_missing_signature_returns_401(sample_incoming_payload: dict):
    """Missing signature header returns 401 when secret is configured."""
    secret = "test-secret-abc"
    body = json.dumps(sample_incoming_payload).encode()

    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = secret
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/connexus/incoming",
                content=body,
                headers={"content-type": "application/json"},
            )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_status_invalid_signature_returns_401(sample_status_payload: dict):
    """Invalid HMAC signature on status endpoint returns 401."""
    secret = "test-secret-def"
    body = json.dumps(sample_status_payload).encode()

    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = secret
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/connexus/status",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": "wrong-sig",
                },
            )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid webhook signature"


# ── Wrong secret → 401 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_incoming_wrong_secret_returns_401(sample_incoming_payload: dict):
    """Signature computed with a different secret returns 401."""
    body = json.dumps(sample_incoming_payload).encode()
    sig = sign_webhook_payload(body, "secret-A")

    with patch("app.modules.sms_chat.router_webhooks.settings") as mock_settings:
        mock_settings.connexus_webhook_secret = "secret-B"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/webhooks/connexus/incoming",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-connexus-signature": sig,
                },
            )
    assert resp.status_code == 401
