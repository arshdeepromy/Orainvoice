"""Multi-currency integration with invoice creation and issuance.

Provides helper functions to:
- Validate currency selection on invoice creation
- Lock exchange rate at invoice issue time
- Require manual rate entry when no rate exists

**Validates: Requirement — MultiCurrency Module, Task 40.5**
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.multi_currency.service import CurrencyService


async def validate_invoice_currency(
    db: AsyncSession,
    org_id: uuid.UUID,
    invoice_currency: str | None,
    base_currency: str = "NZD",
) -> tuple[str, Decimal]:
    """Validate and resolve currency + exchange rate for an invoice.

    Returns (currency_code, exchange_rate).
    Raises ValueError if the currency is not enabled or no rate exists.
    """
    svc = CurrencyService(db)

    if not invoice_currency or invoice_currency.upper() == base_currency.upper():
        return base_currency.upper(), Decimal("1")

    # Check currency is enabled for the org
    enabled = await svc.list_enabled_currencies(org_id)
    enabled_codes = {c.currency_code for c in enabled}
    if invoice_currency.upper() not in enabled_codes:
        raise ValueError(
            f"Currency {invoice_currency} is not enabled for this organisation"
        )

    # Lock the exchange rate
    rate = await svc.lock_rate_on_invoice(base_currency, invoice_currency)
    return invoice_currency.upper(), rate


async def lock_rate_at_issue_time(
    db: AsyncSession,
    invoice_currency: str,
    base_currency: str = "NZD",
) -> Decimal:
    """Lock the exchange rate when an invoice is issued.

    This is called at issue time to snapshot the current rate.
    The locked rate is stored on the invoice and never changes.
    """
    if invoice_currency.upper() == base_currency.upper():
        return Decimal("1")

    svc = CurrencyService(db)
    return await svc.lock_rate_on_invoice(base_currency, invoice_currency)
