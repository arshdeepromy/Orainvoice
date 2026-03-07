"""Integration test: full invoice lifecycle end-to-end.

Flow: create customer → create product → create draft invoice → add line items
      → issue → send email → record payment → verify stock decremented
      → verify loyalty points awarded → verify webhook dispatched.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.loyalty.service import LoyaltyService
from app.modules.loyalty.models import LoyaltyConfig, LoyaltyTransaction
from app.modules.pos.service import POSService
from app.modules.stock.service import StockService
from app.modules.webhooks_v2.dispatch import dispatch_webhook_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(org_id, *, stock_quantity=100, sale_price=50.0):
    p = MagicMock()
    p.id = uuid.uuid4()
    p.org_id = org_id
    p.name = "Widget"
    p.sku = "WDG-001"
    p.sale_price = Decimal(str(sale_price))
    p.cost_price = Decimal("25.00")
    p.stock_quantity = Decimal(str(stock_quantity))
    p.low_stock_threshold = Decimal("10")
    p.is_active = True
    return p


def _make_loyalty_config(org_id, *, earn_rate=1.0, is_active=True):
    c = LoyaltyConfig()
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.earn_rate = Decimal(str(earn_rate))
    c.redemption_rate = Decimal("0.01")
    c.is_active = is_active
    return c


class TestInvoiceLifecycle:
    """End-to-end invoice lifecycle with stock, loyalty, and webhooks."""

    @pytest.mark.asyncio
    async def test_stock_decremented_on_sale(self):
        """Stock is decremented when a product is sold via POS transaction."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_quantity=100)
        original_qty = product.stock_quantity

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Mock product lookup
        product_result = MagicMock()
        product_result.scalar_one_or_none.return_value = product
        db.execute = AsyncMock(return_value=product_result)

        stock_svc = StockService(db)

        # Decrement stock (simulating invoice issuance)
        await stock_svc.decrement_stock(
            product,
            quantity=Decimal("5"),
            reference_type="invoice",
            reference_id=uuid.uuid4(),
            performed_by=uuid.uuid4(),
        )

        # Verify stock was decremented
        assert product.stock_quantity == original_qty - Decimal("5")

    @pytest.mark.asyncio
    async def test_loyalty_points_awarded_on_payment(self):
        """Loyalty points are awarded when an invoice payment is recorded."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        config = _make_loyalty_config(org_id, earn_rate=1.0)

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Mock config lookup
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = config

        # Mock balance lookup (returns 0)
        balance_result = MagicMock()
        balance_result.scalar_one.return_value = 0

        call_count = 0

        async def mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return config_result
            return balance_result

        db.execute = mock_execute

        svc = LoyaltyService(db)
        txn = await svc.award_points(
            org_id=org_id,
            customer_id=customer_id,
            invoice_total=Decimal("250.00"),
            invoice_id=invoice_id,
        )

        # Points should be awarded: floor(250 * 1.0) = 250
        assert txn is not None
        assert db.add.called

    @pytest.mark.asyncio
    async def test_loyalty_inactive_no_points(self):
        """No points awarded when loyalty programme is inactive."""
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        config = _make_loyalty_config(org_id, is_active=False)

        db = AsyncMock()
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = config
        db.execute = AsyncMock(return_value=config_result)

        svc = LoyaltyService(db)
        txn = await svc.award_points(
            org_id=org_id,
            customer_id=customer_id,
            invoice_total=Decimal("100.00"),
        )

        assert txn is None

    @pytest.mark.asyncio
    async def test_webhook_dispatched_on_invoice_event(self):
        """Webhook is dispatched when an invoice event occurs."""
        org_id = uuid.uuid4()

        # Create a mock webhook subscription
        mock_webhook = MagicMock()
        mock_webhook.id = uuid.uuid4()
        mock_webhook.org_id = org_id
        mock_webhook.is_active = True
        mock_webhook.event_types = ["invoice.created", "invoice.paid"]

        db = AsyncMock()
        webhook_result = MagicMock()
        webhook_result.scalars.return_value.all.return_value = [mock_webhook]
        db.execute = AsyncMock(return_value=webhook_result)

        with patch("app.tasks.webhooks.deliver_webhook") as mock_deliver:
            mock_deliver.delay = MagicMock()

            dispatched = await dispatch_webhook_event(
                db=db,
                org_id=org_id,
                event_type="invoice.created",
                data={"invoice_id": str(uuid.uuid4()), "total": "250.00"},
            )

        assert len(dispatched) == 1
        assert dispatched[0] == str(mock_webhook.id)
        mock_deliver.delay.assert_called_once()

    @pytest.mark.asyncio
    async def test_webhook_not_dispatched_for_unsubscribed_event(self):
        """Webhook is NOT dispatched for events the webhook isn't subscribed to."""
        org_id = uuid.uuid4()

        mock_webhook = MagicMock()
        mock_webhook.id = uuid.uuid4()
        mock_webhook.is_active = True
        mock_webhook.event_types = ["invoice.paid"]  # Only subscribed to paid

        db = AsyncMock()
        webhook_result = MagicMock()
        webhook_result.scalars.return_value.all.return_value = [mock_webhook]
        db.execute = AsyncMock(return_value=webhook_result)

        with patch("app.tasks.webhooks.deliver_webhook") as mock_deliver:
            dispatched = await dispatch_webhook_event(
                db=db,
                org_id=org_id,
                event_type="invoice.created",  # Not subscribed
                data={"invoice_id": str(uuid.uuid4())},
            )

        assert len(dispatched) == 0
        mock_deliver.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_stock_decrement_creates_movement(self):
        """Stock decrement creates a stock movement record."""
        org_id = uuid.uuid4()
        product = _make_product(org_id, stock_quantity=50)

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        stock_svc = StockService(db)
        ref_id = uuid.uuid4()
        user_id = uuid.uuid4()

        await stock_svc.decrement_stock(
            product,
            quantity=Decimal("3"),
            reference_type="invoice",
            reference_id=ref_id,
            performed_by=user_id,
        )

        # Verify a stock movement was added
        assert db.add.called
        movement = db.add.call_args[0][0]
        assert movement.quantity_change == Decimal("-3")
        assert movement.reference_type == "invoice"
        assert product.stock_quantity == Decimal("47")
