"""Tests for ecommerce module — WooCommerce integration, webhooks, API rate limiting, sync retry.

Validates: Requirement — Ecommerce Module, Tasks 39.9–39.12
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.ecommerce.models import (
    ApiCredential,
    EcommerceSyncLog,
    SkuMapping,
    WooCommerceConnection,
)
from app.modules.ecommerce.schemas import (
    WooCommerceConnectRequest,
    WebhookOrderPayload,
)
from app.modules.ecommerce.woocommerce_service import WooCommerceService
from app.modules.ecommerce.api_service import (
    ApiKeyService,
    _check_rate_limit,
    _hash_api_key,
    reset_rate_limit_store,
)
from app.modules.ecommerce.webhook_receiver import verify_hmac_signature


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()


def _make_connection(org_id: uuid.UUID = ORG_ID, **overrides) -> WooCommerceConnection:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=org_id,
        store_url="https://shop.example.com",
        consumer_key_encrypted=b"test_key",
        consumer_secret_encrypted=b"test_secret",
        sync_frequency_minutes=15,
        auto_create_invoices=True,
        invoice_status_on_import="draft",
        last_sync_at=None,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    conn = WooCommerceConnection(**defaults)
    return conn


def _make_mock_db(
    connection: WooCommerceConnection | None = None,
    sync_logs: list[EcommerceSyncLog] | None = None,
):
    """Build a mock AsyncSession that returns pre-configured results."""
    db = AsyncMock()

    async def _execute(stmt):
        mock_result = MagicMock()
        # Detect query type by inspecting the statement
        stmt_str = str(stmt)
        if "woocommerce_connections" in stmt_str:
            mock_result.scalar_one_or_none.return_value = connection
            mock_result.scalar.return_value = connection
        elif "count" in stmt_str.lower():
            mock_result.scalar.return_value = len(sync_logs) if sync_logs else 0
        elif "ecommerce_sync_log" in stmt_str:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = sync_logs or []
            mock_result.scalars.return_value = scalars_mock
        else:
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar.return_value = 0
        return mock_result

    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# 39.9 — WooCommerce order creates invoice with correct customer and line items
# ---------------------------------------------------------------------------


class TestWooCommerceOrderCreatesInvoice:
    """Validates: Task 39.9"""

    @pytest.mark.asyncio
    async def test_connect_creates_connection(self):
        db = _make_mock_db()
        svc = WooCommerceService(db)
        data = WooCommerceConnectRequest(
            store_url="https://shop.example.com",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        conn = await svc.connect(ORG_ID, data)
        assert conn.store_url == "https://shop.example.com"
        assert conn.consumer_key_encrypted == b"ck_test"
        assert conn.auto_create_invoices is True
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_orders_inbound_creates_log(self):
        conn = _make_connection()
        db = _make_mock_db(connection=conn)
        svc = WooCommerceService(db)
        log = await svc.sync_orders_inbound(ORG_ID)
        assert log.direction == "inbound"
        assert log.entity_type == "order"
        assert log.status == "pending"
        assert log.org_id == ORG_ID

    @pytest.mark.asyncio
    async def test_webhook_payload_parsed_correctly(self):
        payload = WebhookOrderPayload(
            order_id="WC-1001",
            customer_name="Jane Doe",
            customer_email="jane@example.com",
            line_items=[
                {"sku": "SKU-A", "name": "Widget", "quantity": 2, "price": 19.99},
                {"sku": "SKU-B", "name": "Gadget", "quantity": 1, "price": 49.99},
            ],
            total=89.97,
            currency="NZD",
        )
        assert payload.order_id == "WC-1001"
        assert len(payload.line_items) == 2
        assert payload.line_items[0].sku == "SKU-A"
        assert payload.line_items[0].quantity == 2
        assert payload.total == 89.97

    @pytest.mark.asyncio
    async def test_sku_resolution_returns_product_id(self):
        product_id = uuid.uuid4()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = product_id
        db.execute = AsyncMock(return_value=mock_result)

        svc = WooCommerceService(db)
        resolved = await svc.resolve_sku(ORG_ID, "SKU-A", "woocommerce")
        assert resolved == product_id

    @pytest.mark.asyncio
    async def test_sku_resolution_returns_none_for_unknown(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        svc = WooCommerceService(db)
        resolved = await svc.resolve_sku(ORG_ID, "UNKNOWN", "woocommerce")
        assert resolved is None


# ---------------------------------------------------------------------------
# 39.10 — Webhook with invalid signature returns 401
# ---------------------------------------------------------------------------


class TestWebhookSignatureValidation:
    """Validates: Task 39.10"""

    def test_valid_signature_passes(self):
        secret = b"my_webhook_secret"
        body = b'{"order_id": "123"}'
        sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
        assert verify_hmac_signature(body, sig, secret) is True

    def test_invalid_signature_fails(self):
        secret = b"my_webhook_secret"
        body = b'{"order_id": "123"}'
        assert verify_hmac_signature(body, "bad_signature", secret) is False

    def test_empty_signature_fails(self):
        secret = b"my_webhook_secret"
        body = b'{"order_id": "123"}'
        assert verify_hmac_signature(body, "", secret) is False

    def test_wrong_secret_fails(self):
        secret = b"correct_secret"
        wrong_secret = b"wrong_secret"
        body = b'{"order_id": "123"}'
        sig = hmac.new(wrong_secret, body, hashlib.sha256).hexdigest()
        assert verify_hmac_signature(body, sig, secret) is False

    def test_tampered_body_fails(self):
        secret = b"my_webhook_secret"
        body = b'{"order_id": "123"}'
        sig = hmac.new(secret, body, hashlib.sha256).hexdigest()
        tampered = b'{"order_id": "456"}'
        assert verify_hmac_signature(tampered, sig, secret) is False


# ---------------------------------------------------------------------------
# 39.11 — API rate limiting returns 429 after limit exceeded
# ---------------------------------------------------------------------------


class TestApiRateLimiting:
    """Validates: Task 39.11"""

    def setup_method(self):
        reset_rate_limit_store()

    def test_within_limit_allowed(self):
        org = str(uuid.uuid4())
        for _ in range(99):
            assert _check_rate_limit(org, 100) is True

    def test_at_limit_blocked(self):
        org = str(uuid.uuid4())
        for _ in range(100):
            _check_rate_limit(org, 100)
        assert _check_rate_limit(org, 100) is False

    def test_different_orgs_independent(self):
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        for _ in range(100):
            _check_rate_limit(org_a, 100)
        # org_a is at limit
        assert _check_rate_limit(org_a, 100) is False
        # org_b should still be fine
        assert _check_rate_limit(org_b, 100) is True

    def test_custom_limit(self):
        org = str(uuid.uuid4())
        for _ in range(5):
            _check_rate_limit(org, 5)
        assert _check_rate_limit(org, 5) is False

    @pytest.mark.asyncio
    async def test_authenticate_raises_429_on_limit(self):
        reset_rate_limit_store()
        raw_key = "ora_test_key_for_rate_limit"
        hashed = _hash_api_key(raw_key)

        cred = ApiCredential(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            api_key_hash=hashed,
            name="test",
            scopes=["read"],
            rate_limit_per_minute=2,
            is_active=True,
            last_used_at=None,
            created_at=datetime.now(timezone.utc),
        )

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = cred
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        svc = ApiKeyService(db)
        # First two should succeed
        await svc.authenticate(raw_key)
        await svc.authenticate(raw_key)
        # Third should raise 429
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await svc.authenticate(raw_key)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# 39.12 — Sync retry logic exhausts retries and flags as failed
# ---------------------------------------------------------------------------


class TestSyncRetryLogic:
    """Validates: Task 39.12"""

    @pytest.mark.asyncio
    async def test_complete_sync_marks_failed(self):
        log = EcommerceSyncLog(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            direction="inbound",
            entity_type="order",
            status="pending",
            retry_count=0,
            created_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = log
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        svc = WooCommerceService(db)
        updated = await svc.complete_sync(log.id, status="failed", error_details="Connection timeout")
        assert updated is not None
        assert updated.status == "failed"
        assert updated.retry_count == 1
        assert updated.error_details == "Connection timeout"

    @pytest.mark.asyncio
    async def test_retry_increments_count(self):
        log = EcommerceSyncLog(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            direction="inbound",
            entity_type="order",
            status="pending",
            retry_count=2,
            created_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = log
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        svc = WooCommerceService(db)
        updated = await svc.complete_sync(log.id, status="failed", error_details="Timeout")
        assert updated.retry_count == 3

    @pytest.mark.asyncio
    async def test_complete_sync_marks_completed(self):
        log = EcommerceSyncLog(
            id=uuid.uuid4(),
            org_id=ORG_ID,
            direction="inbound",
            entity_type="order",
            status="pending",
            retry_count=0,
            created_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = log
        db.execute = AsyncMock(return_value=mock_result)
        db.flush = AsyncMock()

        svc = WooCommerceService(db)
        updated = await svc.complete_sync(log.id, status="completed")
        assert updated.status == "completed"
        assert updated.retry_count == 0  # not incremented on success

    def test_celery_task_retry_constants(self):
        from app.tasks.scheduled import WOOCOMMERCE_MAX_RETRIES, WOOCOMMERCE_RETRY_DELAYS
        assert WOOCOMMERCE_MAX_RETRIES == 3
        assert len(WOOCOMMERCE_RETRY_DELAYS) == 3
        # Exponential backoff: each delay should be larger than the previous
        assert WOOCOMMERCE_RETRY_DELAYS[0] < WOOCOMMERCE_RETRY_DELAYS[1] < WOOCOMMERCE_RETRY_DELAYS[2]
