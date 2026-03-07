"""Unit tests for multi-currency module.

Tests:
- 40.10: Payment in different currency records exchange gain/loss
- 40.11: Missing exchange rate requires manual entry before invoice can be issued

**Validates: Requirement — MultiCurrency Module**
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.multi_currency.service import CurrencyService
from app.modules.multi_currency.formatting import format_currency, get_currency_format


class TestExchangeGainLoss:
    """40.10: Payment in different currency records exchange gain/loss."""

    def test_gain_when_payment_rate_lower(self) -> None:
        """When the payment rate is lower than the invoice rate,
        we get more base currency per unit → exchange gain."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("1000.00"),
            invoice_currency="USD",
            base_currency="NZD",
            invoice_rate=Decimal("1.50"),   # 1 NZD = 1.50 USD at invoice
            payment_rate=Decimal("1.40"),   # 1 NZD = 1.40 USD at payment
        )

        assert result.invoice_currency == "USD"
        assert result.base_currency == "NZD"
        assert result.invoice_rate == Decimal("1.50")
        assert result.payment_rate == Decimal("1.40")
        assert result.invoice_amount == Decimal("1000.00")
        # At invoice: 1000 / 1.50 = 666.67 NZD
        assert result.base_amount_at_invoice == Decimal("666.67")
        # At payment: 1000 / 1.40 = 714.29 NZD
        assert result.base_amount_at_payment == Decimal("714.29")
        # Gain: 714.29 - 666.67 = 47.62
        assert result.gain_loss == Decimal("47.62")
        assert result.gain_loss > 0  # It's a gain

    def test_loss_when_payment_rate_higher(self) -> None:
        """When the payment rate is higher than the invoice rate,
        we get less base currency per unit → exchange loss."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("1000.00"),
            invoice_currency="USD",
            base_currency="NZD",
            invoice_rate=Decimal("1.50"),   # 1 NZD = 1.50 USD at invoice
            payment_rate=Decimal("1.60"),   # 1 NZD = 1.60 USD at payment
        )

        # At invoice: 1000 / 1.50 = 666.67 NZD
        assert result.base_amount_at_invoice == Decimal("666.67")
        # At payment: 1000 / 1.60 = 625.00 NZD
        assert result.base_amount_at_payment == Decimal("625.00")
        # Loss: 625.00 - 666.67 = -41.67
        assert result.gain_loss == Decimal("-41.67")
        assert result.gain_loss < 0  # It's a loss

    def test_no_gain_loss_when_rates_equal(self) -> None:
        """When invoice and payment rates are the same, no gain/loss."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("5000.00"),
            invoice_currency="GBP",
            base_currency="NZD",
            invoice_rate=Decimal("2.10"),
            payment_rate=Decimal("2.10"),
        )

        assert result.gain_loss == Decimal("0")
        assert result.base_amount_at_invoice == result.base_amount_at_payment

    def test_gain_loss_with_small_amounts(self) -> None:
        """Exchange gain/loss works correctly with small amounts."""
        result = CurrencyService.record_exchange_gain_loss(
            invoice_amount=Decimal("10.00"),
            invoice_currency="EUR",
            base_currency="NZD",
            invoice_rate=Decimal("0.55"),
            payment_rate=Decimal("0.50"),
        )

        # At invoice: 10 / 0.55 = 18.18 NZD
        assert result.base_amount_at_invoice == Decimal("18.18")
        # At payment: 10 / 0.50 = 20.00 NZD
        assert result.base_amount_at_payment == Decimal("20.00")
        assert result.gain_loss == Decimal("1.82")


class TestMissingExchangeRate:
    """40.11: Missing exchange rate requires manual entry before invoice can be issued."""

    @pytest.mark.asyncio
    async def test_lock_rate_raises_when_no_rate_exists(self) -> None:
        """lock_rate_on_invoice raises ValueError when no rate is available."""
        from unittest.mock import AsyncMock, MagicMock

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        svc = CurrencyService(mock_db)

        with pytest.raises(ValueError, match="No exchange rate available"):
            await svc.lock_rate_on_invoice("NZD", "USD")

    @pytest.mark.asyncio
    async def test_lock_rate_returns_one_for_same_currency(self) -> None:
        """lock_rate_on_invoice returns 1 when currencies match."""
        from unittest.mock import MagicMock

        mock_db = MagicMock()
        svc = CurrencyService(mock_db)

        rate = await svc.lock_rate_on_invoice("NZD", "NZD")
        assert rate == Decimal("1")


class TestCurrencyFormatting:
    """Tests for ISO 4217 currency formatting."""

    def test_format_nzd(self) -> None:
        assert format_currency(Decimal("1234.56"), "NZD") == "$1,234.56"

    def test_format_eur(self) -> None:
        assert format_currency(Decimal("1234.56"), "EUR") == "€1.234,56"

    def test_format_jpy_no_decimals(self) -> None:
        assert format_currency(Decimal("1234"), "JPY") == "¥1,234"

    def test_format_sek_symbol_after(self) -> None:
        assert format_currency(Decimal("1234.56"), "SEK") == "1 234,56 kr"

    def test_format_gbp(self) -> None:
        assert format_currency(Decimal("99.99"), "GBP") == "£99.99"

    def test_format_large_amount(self) -> None:
        assert format_currency(Decimal("1234567.89"), "USD") == "$1,234,567.89"

    def test_format_zero(self) -> None:
        assert format_currency(Decimal("0"), "NZD") == "$0.00"

    def test_format_negative(self) -> None:
        assert format_currency(Decimal("-500.00"), "NZD") == "-$500.00"

    def test_unknown_currency_uses_code(self) -> None:
        fmt = get_currency_format("XYZ")
        assert fmt.code == "XYZ"
        assert fmt.symbol == "XYZ"
        assert fmt.decimal_places == 2

    def test_format_brl(self) -> None:
        assert format_currency(Decimal("1234.56"), "BRL") == "R$1.234,56"
