"""Integration test: multi-currency invoice flow end-to-end.

Flow: enable currencies → create invoice in foreign currency
      → record payment → verify exchange gain/loss.

Uses mocked DB sessions and services — no real database required.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.multi_currency.service import CurrencyService
from app.modules.multi_currency.models import ExchangeRate, OrgCurrency
from app.modules.multi_currency.schemas import EnableCurrencyRequest, ExchangeGainLoss, ExchangeRateCreate


class TestMultiCurrencyFlow:
    """End-to-end multi-currency: enable → invoice → payment → gain/loss."""

    @pytest.mark.asyncio
    async def test_enable_currency(self):
        """Enabling a currency for an org creates an OrgCurrency record."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # No existing currency
        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        no_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=no_result)

        svc = CurrencyService(db)
        currency = await svc.enable_currency(
            org_id, EnableCurrencyRequest(currency_code="USD", is_base=False),
        )

        assert currency.currency_code == "USD"
        assert currency.org_id == org_id
        assert db.add.called

    def test_exchange_gain_on_rate_improvement(self):
        """Exchange gain when payment rate is better than invoice rate."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("1000.00"),
            invoice_currency="USD",
            base_currency="NZD",
            invoice_rate=Decimal("0.60"),   # 1 USD = 0.60 NZD at invoice
            payment_rate=Decimal("0.65"),   # 1 USD = 0.65 NZD at payment
        )

        assert isinstance(result, ExchangeGainLoss)
        assert result.invoice_currency == "USD"
        assert result.base_currency == "NZD"

        # At invoice: 1000 / 0.60 = 1666.67 NZD
        assert result.base_amount_at_invoice == Decimal("1666.67")
        # At payment: 1000 / 0.65 = 1538.46 NZD
        assert result.base_amount_at_payment == Decimal("1538.46")
        # Gain/loss = 1538.46 - 1666.67 = -128.21 (loss — we pay less NZD)
        assert result.gain_loss == Decimal("-128.21")

    def test_exchange_loss_on_rate_decline(self):
        """Exchange loss when payment rate is worse than invoice rate."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("500.00"),
            invoice_currency="GBP",
            base_currency="NZD",
            invoice_rate=Decimal("0.50"),   # 1 GBP = 0.50 NZD at invoice
            payment_rate=Decimal("0.45"),   # 1 GBP = 0.45 NZD at payment
        )

        # At invoice: 500 / 0.50 = 1000.00 NZD
        assert result.base_amount_at_invoice == Decimal("1000.00")
        # At payment: 500 / 0.45 = 1111.11 NZD
        assert result.base_amount_at_payment == Decimal("1111.11")
        # Gain = 1111.11 - 1000.00 = 111.11 (gain — we receive more NZD)
        assert result.gain_loss == Decimal("111.11")

    def test_no_gain_loss_same_rate(self):
        """No gain/loss when invoice and payment rates are the same."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("1000.00"),
            invoice_currency="AUD",
            base_currency="NZD",
            invoice_rate=Decimal("0.90"),
            payment_rate=Decimal("0.90"),
        )

        assert result.gain_loss == Decimal("0.00")
        assert result.base_amount_at_invoice == result.base_amount_at_payment

    @pytest.mark.asyncio
    async def test_set_exchange_rate(self):
        """Setting an exchange rate stores it in the database."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_result)

        svc = CurrencyService(db)
        rate = await svc.set_exchange_rate(
            ExchangeRateCreate(
                base_currency="NZD",
                target_currency="USD",
                rate=Decimal("0.62"),
                effective_date=date.today(),
            ),
            source="manual",
        )

        assert rate.base_currency == "NZD"
        assert rate.target_currency == "USD"
        assert rate.rate == Decimal("0.62")
        assert db.add.called

    @pytest.mark.asyncio
    async def test_lock_rate_on_invoice(self):
        """Locking a rate at invoice time returns the current rate."""
        db = AsyncMock()

        # Mock rate lookup
        mock_rate = ExchangeRate()
        mock_rate.id = uuid.uuid4()
        mock_rate.base_currency = "NZD"
        mock_rate.target_currency = "USD"
        mock_rate.rate = Decimal("0.62")
        mock_rate.effective_date = date.today()

        rate_result = MagicMock()
        rate_result.scalar_one_or_none.return_value = mock_rate
        db.execute = AsyncMock(return_value=rate_result)

        svc = CurrencyService(db)
        locked_rate = await svc.lock_rate_on_invoice("NZD", "USD")

        assert locked_rate == Decimal("0.62")

    @pytest.mark.asyncio
    async def test_lock_rate_no_rate_raises(self):
        """Locking a rate when no rate exists raises ValueError."""
        db = AsyncMock()

        no_result = MagicMock()
        no_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=no_result)

        svc = CurrencyService(db)

        with pytest.raises(ValueError, match="No exchange rate"):
            await svc.lock_rate_on_invoice("NZD", "JPY")
