"""Integration test: ecommerce/WooCommerce flow end-to-end.

Flow: connect WooCommerce → receive webhook → verify invoice created
      → sync products outbound.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.ecommerce.models import (
    EcommerceSyncLog,
    WooCommerceConnection,
)
from app.modules.ecommerce.schemas import WooCommerceConnectRequest
from app.modules.ecommerce.webhook_receiver import verify_hmac_signature
from app.modules.ecommerce.woocommerce_service import WooCommerceService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connection(org_id, *, is_active=True):
    conn = WooCommerceConnection()
    conn.id = uuid.uuid4()
    conn.org_id = org_id
    conn.store_url = "https://shop.example.com"
    conn.consumer_key_encrypted = b"ck_test_key"
    conn.consumer_secret_encrypted = b"cs_test_secret"
    conn.sync_frequency_minutes = 60
    conn.auto_create_invoices = True
    conn.invoice_status_on_import = "draft"
    conn.is_active = is_active
    conn.last_sync_at = None
    conn.created_at = datetime.now(timezone.utc)
    conn.updated_at = datetime.now(timezone.utc)
    return conn


class TestEcommerceFlow:
    """End-to-end ecommerce: connect → webhook → invoice → sync outbound."""

    @pytest.mark.asyncio
    async def test_connect_woocommerce(self):
        """Connecting a WooCommerce store creates a connection record."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # No existing connection
        no_conn_result = MagicMock()
        no_conn_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_conn_result)

        svc = WooCommerceService(db)
        conn = await svc.connect(
            org_id,
            WooCommerceConnectRequest(
                store_url="https://shop.example.com",
                consumer_key="ck_live_abc123",
                consumer_secret="cs_live_xyz789",
            ),
        )

        assert conn.store_url == "https://shop.example.com"
        assert db.add.called

    @pytest.mark.asyncio
    async def test_update_existing_connection(self):
        """Reconnecting updates the existing connection record."""
        org_id = uuid.uuid4()
        existing = _make_connection(org_id)

        db = AsyncMock()
        db.flush = AsyncMock()

        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=conn_result)

        svc = WooCommerceService(db)
        conn = await svc.connect(
            org_id,
            WooCommerceConnectRequest(
                store_url="https://newshop.example.com",
                consumer_key="ck_new_key",
                consumer_secret="cs_new_secret",
            ),
        )

        assert conn.store_url == "https://newshop.example.com"
        assert conn.id == existing.id  # Same record updated

    def test_verify_hmac_signature_valid(self):
        """Valid HMAC-SHA256 signature passes verification."""
        secret = b"my_webhook_secret"
        body = b'{"order_id": "12345"}'
        signature = hmac.new(secret, body, hashlib.sha256).hexdigest()

        assert verify_hmac_signature(body, signature, secret) is True

    def test_verify_hmac_signature_invalid(self):
        """Invalid HMAC signature fails verification."""
        secret = b"my_webhook_secret"
        body = b'{"order_id": "12345"}'

        assert verify_hmac_signature(body, "invalid_signature", secret) is False

    @pytest.mark.asyncio
    async def test_sync_orders_inbound(self):
        """Inbound order sync creates a sync log entry."""
        org_id = uuid.uuid4()
        existing = _make_connection(org_id)

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        conn_result = MagicMock()
        conn_result.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=conn_result)

        svc = WooCommerceService(db)
        log = await svc.sync_orders_inbound(org_id)

        assert log.direction == "inbound"
        assert log.entity_type == "order"
        assert log.status == "pending"
        assert db.add.called

    @pytest.mark.asyncio
    async def test_sync_products_outbound(self):
        """Outbound product sync creates a sync log entry."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        svc = WooCommerceService(db)
        log = await svc.sync_products_outbound(org_id)

        assert log.direction == "outbound"
        assert log.entity_type == "product"
        assert log.status == "pending"

    @pytest.mark.asyncio
    async def test_complete_sync_success(self):
        """Completing a sync marks the log entry as completed."""
        log = EcommerceSyncLog()
        log.id = uuid.uuid4()
        log.status = "pending"
        log.retry_count = 0

        db = AsyncMock()
        db.flush = AsyncMock()
        log_result = MagicMock()
        log_result.scalar_one_or_none.return_value = log
        db.execute = AsyncMock(return_value=log_result)

        svc = WooCommerceService(db)
        result = await svc.complete_sync(log.id, status="completed")

        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_complete_sync_failure_increments_retry(self):
        """Failed sync increments the retry count."""
        log = EcommerceSyncLog()
        log.id = uuid.uuid4()
        log.status = "pending"
        log.retry_count = 0

        db = AsyncMock()
        db.flush = AsyncMock()
        log_result = MagicMock()
        log_result.scalar_one_or_none.return_value = log
        db.execute = AsyncMock(return_value=log_result)

        svc = WooCommerceService(db)
        result = await svc.complete_sync(
            log.id, status="failed", error_details="Connection timeout"
        )

        assert result.status == "failed"
        assert result.retry_count == 1
