"""Multi-currency reporting integration.

Provides helpers to consolidate financial data to base currency for reports.
- For historical (issued) invoices: uses the locked exchange rate on the invoice.
- For unrealised/current amounts: uses the latest available exchange rate.

**Validates: Requirement — MultiCurrency Module, Task 40.6**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.multi_currency.service import CurrencyService


async def consolidate_to_base(
    db: AsyncSession,
    amount: Decimal,
    currency: str,
    base_currency: str,
    locked_rate: Decimal | None = None,
    on_date: date | None = None,
) -> Decimal:
    """Convert an amount to base currency for reporting.

    If locked_rate is provided (historical invoice), use it directly.
    Otherwise fetch the latest rate for unrealised amounts.
    """
    if currency.upper() == base_currency.upper():
        return amount

    if locked_rate is not None and locked_rate > 0:
        return (amount / locked_rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP,
        )

    svc = CurrencyService(db)
    result = await svc.convert_to_base(amount, currency, base_currency, on_date)
    return result.converted_amount


async def consolidate_invoice_list(
    db: AsyncSession,
    invoices: list[dict],
    base_currency: str,
) -> list[dict]:
    """Add base_currency_total to each invoice dict for report consolidation.

    Each invoice dict should have: total, currency, exchange_rate (locked).
    Returns the same list with an added 'base_currency_total' field.
    """
    for inv in invoices:
        inv_currency = inv.get("currency", base_currency)
        inv_total = Decimal(str(inv.get("total", 0)))
        locked_rate = inv.get("exchange_rate")
        if locked_rate is not None:
            locked_rate = Decimal(str(locked_rate))

        inv["base_currency_total"] = await consolidate_to_base(
            db, inv_total, inv_currency, base_currency, locked_rate,
        )

    return invoices
