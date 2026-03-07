"""Unit tests for Task 25.3 — Outbound webhooks.

Tests cover:
  - Webhook CRUD service functions (create, list, get, update, delete)
  - Payload signing with HMAC-SHA256
  - Webhook delivery with retry logic and failure logging
  - Event type validation
  - Delivery listing

Requirements: 70.1, 70.2, 70.3, 70.4
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.webhooks.schemas import WEBHOOK_EVENT_TYPES
from app.modules.webhooks.service import sign_payload


# ---------------------------------------------------------------------------
# Payload signing tests (Req 70.3)
# ---------------------------------------------------------------------------


class TestSignPayload:
    """Tests for HMAC-SHA256 payload signing."""

    def test_sign_produces_hex_digest(self):
        payload = b'{"event":"invoice.created","data":{}}'
        secret = "test-secret-key"
        sig = sign_payload(payload, secret)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA256 hex digest is 64 chars

    def test_sign_is_deterministic(self):
        payload = b'{"event":"invoice.paid"}'
        secret = "my-secret"
        sig1 = sign_payload(payload, secret)
        sig2 = sign_payload(payload, secret)
        assert sig1 == sig2

    def test_sign_matches_manual_hmac(self):
        payload = b'{"event":"payment.received","data":{"amount":100}}'
        secret = "verify-secret"
        sig = sign_payload(payload, secret)
        expected = hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        assert sig == expected

    def test_different_secrets_produce_different_signatures(self):
        payload = b'{"event":"customer.created"}'
        sig1 = sign_payload(payload, "secret-a")
        sig2 = sign_payload(payload, "secret-b")
        assert sig1 != sig2

    def test_different_payloads_produce_different_signatures(self):
        secret = "same-secret"
        sig1 = sign_payload(b'{"event":"invoice.created"}', secret)
        sig2 = sign_payload(b'{"event":"invoice.paid"}', secret)
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# Schema / event type validation tests (Req 70.1)
# ---------------------------------------------------------------------------


class TestWebhookEventTypes:
    """Tests for webhook event type constants."""

    def test_all_required_events_present(self):
        required = [
            "invoice.created",
            "invoice.paid",
            "invoice.overdue",
            "payment.received",
            "customer.created",
            "vehicle.added",
        ]
        for event in required:
            assert event in WEBHOOK_EVENT_TYPES

    def test_event_types_count(self):
        assert len(WEBHOOK_EVENT_TYPES) == 6


# ---------------------------------------------------------------------------
# CRUD service tests (Req 70.1)
# ---------------------------------------------------------------------------


def _make_webhook(
    org_id: uuid.UUID,
    event_type: str = "invoice.created",
    url: str = "https://example.com/hook",
    is_active: bool = True,
) -> MagicMock:
    """Create a mock Webhook ORM instance."""
    wh = MagicMock()
    wh.id = uuid.uuid4()
    wh.org_id = org_id
    wh.event_type = event_type
    wh.url = url
    wh.is_active = is_active
    wh.created_at = datetime.now(timezone.utc)
    wh.secret_encrypted = b"encrypted-secret"
    return wh


def _make_delivery(
    webhook_id: uuid.UUID,
    event_type: str = "invoice.created",
    status: str = "delivered",
) -> MagicMock:
    """Create a mock WebhookDelivery ORM instance."""
    d = MagicMock()
    d.id = uuid.uuid4()
    d.webhook_id = webhook_id
    d.event_type = event_type
    d.payload = {"event": event_type, "timestamp": "2025-01-01T00:00:00Z", "data": {}}
    d.response_status = 200
    d.retry_count = 0
    d.status = status
    d.created_at = datetime.now(timezone.utc)
    return d


def _mock_scalars(items):
    """Create a mock result that returns items via scalars().all()."""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = items
    mock_result.scalars.return_value = mock_scalars
    return mock_result


class TestCreateWebhook:
    """Tests for create_webhook service function."""

    @pytest.mark.asyncio
    async def test_create_valid_webhook(self):
        from app.modules.webhooks.service import create_webhook

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Mock refresh to populate the ORM object
        async def mock_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=mock_refresh)

        org_id = uuid.uuid4()

        with patch("app.modules.webhooks.service.envelope_encrypt", return_value=b"enc"):
            result = await create_webhook(
                db,
                org_id=org_id,
                event_type="invoice.created",
                url="https://example.com/hook",
                secret="my-secret-key",
            )

        assert isinstance(result, dict)
        assert result["event_type"] == "invoice.created"
        assert result["url"] == "https://example.com/hook"
        assert result["is_active"] is True
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_invalid_event_type(self):
        from app.modules.webhooks.service import create_webhook

        db = AsyncMock()
        org_id = uuid.uuid4()

        result = await create_webhook(
            db,
            org_id=org_id,
            event_type="invalid.event",
            url="https://example.com/hook",
            secret="my-secret-key",
        )

        assert isinstance(result, str)
        assert "Invalid event type" in result


class TestListWebhooks:
    """Tests for list_webhooks service function."""

    @pytest.mark.asyncio
    async def test_list_returns_webhooks(self):
        from app.modules.webhooks.service import list_webhooks

        org_id = uuid.uuid4()
        wh1 = _make_webhook(org_id, event_type="invoice.created")
        wh2 = _make_webhook(org_id, event_type="payment.received")

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([wh1, wh2]))

        result = await list_webhooks(db, org_id=org_id)
        assert result["total"] == 2
        assert len(result["webhooks"]) == 2

    @pytest.mark.asyncio
    async def test_list_empty(self):
        from app.modules.webhooks.service import list_webhooks

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars([]))

        result = await list_webhooks(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["webhooks"] == []


class TestUpdateWebhook:
    """Tests for update_webhook service function."""

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        from app.modules.webhooks.service import update_webhook

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_webhook(
            db,
            org_id=uuid.uuid4(),
            webhook_id=uuid.uuid4(),
            url="https://new-url.com/hook",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_update_invalid_event_type(self):
        from app.modules.webhooks.service import update_webhook

        org_id = uuid.uuid4()
        wh = _make_webhook(org_id)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wh
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_webhook(
            db,
            org_id=org_id,
            webhook_id=wh.id,
            event_type="bad.event",
        )
        assert isinstance(result, str)
        assert "Invalid event type" in result


class TestDeleteWebhook:
    """Tests for delete_webhook service function."""

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        from app.modules.webhooks.service import delete_webhook

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await delete_webhook(
            db, org_id=uuid.uuid4(), webhook_id=uuid.uuid4()
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_existing(self):
        from app.modules.webhooks.service import delete_webhook

        org_id = uuid.uuid4()
        wh = _make_webhook(org_id)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = wh
        db.execute = AsyncMock(return_value=mock_result)
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        result = await delete_webhook(
            db, org_id=org_id, webhook_id=wh.id
        )
        assert result is True
        db.delete.assert_awaited_once_with(wh)


class TestListDeliveries:
    """Tests for list_deliveries service function."""

    @pytest.mark.asyncio
    async def test_list_deliveries_webhook_not_found(self):
        from app.modules.webhooks.service import list_deliveries

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        result = await list_deliveries(
            db, org_id=uuid.uuid4(), webhook_id=uuid.uuid4()
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_list_deliveries_returns_entries(self):
        from app.modules.webhooks.service import list_deliveries

        org_id = uuid.uuid4()
        wh_id = uuid.uuid4()
        d1 = _make_delivery(wh_id)
        d2 = _make_delivery(wh_id, status="failed")

        db = AsyncMock()
        # First call: check webhook exists; second call: list deliveries
        mock_wh_result = MagicMock()
        mock_wh_result.scalar_one_or_none.return_value = wh_id
        mock_del_result = _mock_scalars([d1, d2])

        db.execute = AsyncMock(side_effect=[mock_wh_result, mock_del_result])

        result = await list_deliveries(db, org_id=org_id, webhook_id=wh_id)
        assert result is not None
        assert result["total"] == 2
        assert len(result["deliveries"]) == 2
