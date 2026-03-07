"""Currency service: enable currencies, exchange rates, conversions, gain/loss.

Business rules:
- enable_currency(): enables a currency for an org, optionally as base.
- get_exchange_rate(): retrieves the latest rate for a currency pair.
- lock_rate_on_invoice(): returns the rate to lock at invoice issue time.
- convert_to_base(): converts an amount from a foreign currency to base.
- record_exchange_gain_loss(): calculates gain/loss between invoice and payment rates.
- refresh_rates_from_provider(): fetches rates from Open Exchange Rates API.

**Validates: Requirement — MultiCurrency Module**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.multi_currency.models import ExchangeRate, OrgCurrency
from app.modules.multi_currency.schemas import (
    ConvertedAmount,
    EnableCurrencyRequest,
    ExchangeGainLoss,
    ExchangeRateCreate,
)


class CurrencyService:
    """Service layer for multi-currency management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Org currency management
    # ------------------------------------------------------------------

    async def enable_currency(
        self,
        org_id: uuid.UUID,
        payload: EnableCurrencyRequest,
    ) -> OrgCurrency:
        """Enable a currency for an organisation."""
        code = payload.currency_code.upper()

        # Check if already exists
        stmt = select(OrgCurrency).where(
            and_(
                OrgCurrency.org_id == org_id,
                OrgCurrency.currency_code == code,
            )
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.enabled = True
            if payload.is_base:
                await self._clear_base(org_id)
                existing.is_base = True
            await self.db.flush()
            return existing

        if payload.is_base:
            await self._clear_base(org_id)

        currency = OrgCurrency(
            org_id=org_id,
            currency_code=code,
            is_base=payload.is_base,
            enabled=True,
        )
        self.db.add(currency)
        await self.db.flush()
        return currency

    async def _clear_base(self, org_id: uuid.UUID) -> None:
        """Remove base flag from all org currencies."""
        stmt = select(OrgCurrency).where(
            and_(OrgCurrency.org_id == org_id, OrgCurrency.is_base.is_(True))
        )
        result = await self.db.execute(stmt)
        for c in result.scalars().all():
            c.is_base = False
        await self.db.flush()

    async def list_enabled_currencies(
        self, org_id: uuid.UUID,
    ) -> list[OrgCurrency]:
        """List all enabled currencies for an org."""
        stmt = (
            select(OrgCurrency)
            .where(and_(OrgCurrency.org_id == org_id, OrgCurrency.enabled.is_(True)))
            .order_by(OrgCurrency.is_base.desc(), OrgCurrency.currency_code)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def disable_currency(
        self, org_id: uuid.UUID, currency_code: str,
    ) -> None:
        """Disable a currency for an org."""
        stmt = select(OrgCurrency).where(
            and_(
                OrgCurrency.org_id == org_id,
                OrgCurrency.currency_code == currency_code.upper(),
            )
        )
        result = await self.db.execute(stmt)
        currency = result.scalar_one_or_none()
        if currency is None:
            raise ValueError(f"Currency {currency_code} not found for org")
        if currency.is_base:
            raise ValueError("Cannot disable the base currency")
        currency.enabled = False
        await self.db.flush()

    # ------------------------------------------------------------------
    # Exchange rate management
    # ------------------------------------------------------------------

    async def get_exchange_rate(
        self,
        base_currency: str,
        target_currency: str,
        on_date: date | None = None,
    ) -> ExchangeRate | None:
        """Get the latest exchange rate for a currency pair on or before a date."""
        effective = on_date or date.today()
        stmt = (
            select(ExchangeRate)
            .where(
                and_(
                    ExchangeRate.base_currency == base_currency.upper(),
                    ExchangeRate.target_currency == target_currency.upper(),
                    ExchangeRate.effective_date <= effective,
                )
            )
            .order_by(ExchangeRate.effective_date.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def set_exchange_rate(
        self,
        payload: ExchangeRateCreate,
        source: str = "manual",
    ) -> ExchangeRate:
        """Create or update an exchange rate for a currency pair on a date."""
        base = payload.base_currency.upper()
        target = payload.target_currency.upper()

        # Check for existing rate on same date
        stmt = select(ExchangeRate).where(
            and_(
                ExchangeRate.base_currency == base,
                ExchangeRate.target_currency == target,
                ExchangeRate.effective_date == payload.effective_date,
            )
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.rate = payload.rate
            existing.source = source
            await self.db.flush()
            return existing

        rate = ExchangeRate(
            base_currency=base,
            target_currency=target,
            rate=payload.rate,
            source=source,
            effective_date=payload.effective_date,
        )
        self.db.add(rate)
        await self.db.flush()
        return rate

    async def list_exchange_rates(
        self,
        base_currency: str | None = None,
        target_currency: str | None = None,
        limit: int = 50,
    ) -> list[ExchangeRate]:
        """List exchange rates with optional filtering."""
        stmt = select(ExchangeRate)
        if base_currency:
            stmt = stmt.where(ExchangeRate.base_currency == base_currency.upper())
        if target_currency:
            stmt = stmt.where(ExchangeRate.target_currency == target_currency.upper())
        stmt = stmt.order_by(ExchangeRate.effective_date.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Invoice integration
    # ------------------------------------------------------------------

    async def lock_rate_on_invoice(
        self,
        base_currency: str,
        invoice_currency: str,
    ) -> Decimal:
        """Return the current exchange rate to lock on an invoice at issue time.

        Raises ValueError if no rate is available.
        """
        if base_currency.upper() == invoice_currency.upper():
            return Decimal("1")

        rate_record = await self.get_exchange_rate(base_currency, invoice_currency)
        if rate_record is None:
            raise ValueError(
                f"No exchange rate available for {base_currency}/{invoice_currency}. "
                "Please enter a manual rate before issuing the invoice."
            )
        return rate_record.rate

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    async def convert_to_base(
        self,
        amount: Decimal,
        from_currency: str,
        base_currency: str,
        on_date: date | None = None,
    ) -> ConvertedAmount:
        """Convert an amount from a foreign currency to the base currency."""
        if from_currency.upper() == base_currency.upper():
            return ConvertedAmount(
                original_amount=amount,
                original_currency=from_currency.upper(),
                converted_amount=amount,
                target_currency=base_currency.upper(),
                rate=Decimal("1"),
                effective_date=on_date or date.today(),
            )

        rate_record = await self.get_exchange_rate(base_currency, from_currency, on_date)
        if rate_record is None:
            raise ValueError(
                f"No exchange rate for {base_currency}/{from_currency}"
            )

        # rate is base_currency per 1 unit of target_currency
        # So to convert from target to base: amount / rate
        converted = (amount / rate_record.rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        return ConvertedAmount(
            original_amount=amount,
            original_currency=from_currency.upper(),
            converted_amount=converted,
            target_currency=base_currency.upper(),
            rate=rate_record.rate,
            effective_date=rate_record.effective_date,
        )

    # ------------------------------------------------------------------
    # Exchange gain/loss
    # ------------------------------------------------------------------

    @staticmethod
    def record_exchange_gain_loss(
        invoice_amount: Decimal,
        invoice_currency: str,
        base_currency: str,
        invoice_rate: Decimal,
        payment_rate: Decimal,
    ) -> ExchangeGainLoss:
        """Calculate exchange gain or loss between invoice and payment rates.

        A positive gain_loss means a gain; negative means a loss.
        """
        base_at_invoice = (invoice_amount / invoice_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        base_at_payment = (invoice_amount / payment_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )
        gain_loss = base_at_payment - base_at_invoice

        return ExchangeGainLoss(
            invoice_currency=invoice_currency.upper(),
            base_currency=base_currency.upper(),
            invoice_rate=invoice_rate,
            payment_rate=payment_rate,
            invoice_amount=invoice_amount,
            base_amount_at_invoice=base_at_invoice,
            base_amount_at_payment=base_at_payment,
            gain_loss=gain_loss,
        )

    # ------------------------------------------------------------------
    # Provider refresh
    # ------------------------------------------------------------------

    async def refresh_rates_from_provider(
        self,
        base_currency: str,
        target_currencies: list[str] | None = None,
    ) -> list[ExchangeRate]:
        """Fetch latest rates from Open Exchange Rates API and store them.

        In production this calls the external API. Here we define the
        interface; the actual HTTP call is in the Celery task wrapper.
        """
        import httpx

        app_id = _get_oxr_app_id()
        if not app_id:
            raise ValueError("Open Exchange Rates API key not configured")

        url = f"https://openexchangerates.org/api/latest.json?app_id={app_id}&base={base_currency.upper()}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        rates_data = data.get("rates", {})
        today = date.today()
        created: list[ExchangeRate] = []

        for code, rate_value in rates_data.items():
            if target_currencies and code.upper() not in [c.upper() for c in target_currencies]:
                continue
            if code.upper() == base_currency.upper():
                continue
            rate_record = await self.set_exchange_rate(
                ExchangeRateCreate(
                    base_currency=base_currency.upper(),
                    target_currency=code.upper(),
                    rate=Decimal(str(rate_value)),
                    effective_date=today,
                ),
                source="openexchangerates",
            )
            created.append(rate_record)

        return created


def _get_oxr_app_id() -> str | None:
    """Retrieve the Open Exchange Rates app ID from settings."""
    try:
        from app.config import settings
        return getattr(settings, "oxr_app_id", None)
    except Exception:
        return None
