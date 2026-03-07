"""ISO 4217 currency formatting utilities.

Provides currency-aware formatting for amounts including:
- Correct decimal places per currency
- Symbol position (before/after amount)
- Thousands and decimal separators

**Validates: Requirement — MultiCurrency Module, Task 40.8**
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.modules.multi_currency.schemas import CurrencyFormat

# ISO 4217 currency definitions
# (code, symbol, decimal_places, symbol_position, thousands_sep, decimal_sep)
CURRENCY_REGISTRY: dict[str, CurrencyFormat] = {
    "NZD": CurrencyFormat(code="NZD", symbol="$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "AUD": CurrencyFormat(code="AUD", symbol="A$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "USD": CurrencyFormat(code="USD", symbol="$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "GBP": CurrencyFormat(code="GBP", symbol="£", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "EUR": CurrencyFormat(code="EUR", symbol="€", decimal_places=2, symbol_position="before", thousands_separator=".", decimal_separator=","),
    "JPY": CurrencyFormat(code="JPY", symbol="¥", decimal_places=0, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "CAD": CurrencyFormat(code="CAD", symbol="C$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "CHF": CurrencyFormat(code="CHF", symbol="CHF", decimal_places=2, symbol_position="before", thousands_separator="'", decimal_separator="."),
    "CNY": CurrencyFormat(code="CNY", symbol="¥", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "SGD": CurrencyFormat(code="SGD", symbol="S$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "HKD": CurrencyFormat(code="HKD", symbol="HK$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "KRW": CurrencyFormat(code="KRW", symbol="₩", decimal_places=0, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "INR": CurrencyFormat(code="INR", symbol="₹", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "MXN": CurrencyFormat(code="MXN", symbol="$", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
    "BRL": CurrencyFormat(code="BRL", symbol="R$", decimal_places=2, symbol_position="before", thousands_separator=".", decimal_separator=","),
    "ZAR": CurrencyFormat(code="ZAR", symbol="R", decimal_places=2, symbol_position="before", thousands_separator=" ", decimal_separator="."),
    "SEK": CurrencyFormat(code="SEK", symbol="kr", decimal_places=2, symbol_position="after", thousands_separator=" ", decimal_separator=","),
    "NOK": CurrencyFormat(code="NOK", symbol="kr", decimal_places=2, symbol_position="after", thousands_separator=" ", decimal_separator=","),
    "DKK": CurrencyFormat(code="DKK", symbol="kr", decimal_places=2, symbol_position="after", thousands_separator=".", decimal_separator=","),
    "THB": CurrencyFormat(code="THB", symbol="฿", decimal_places=2, symbol_position="before", thousands_separator=",", decimal_separator="."),
}


# Default format for unknown currencies
_DEFAULT_FORMAT = CurrencyFormat(
    code="???",
    symbol="",
    decimal_places=2,
    symbol_position="before",
    thousands_separator=",",
    decimal_separator=".",
)


def get_currency_format(currency_code: str) -> CurrencyFormat:
    """Get the formatting rules for a currency code."""
    code = currency_code.upper()
    fmt = CURRENCY_REGISTRY.get(code)
    if fmt is not None:
        return fmt
    # Return a generic format with the code as symbol
    return CurrencyFormat(
        code=code,
        symbol=code,
        decimal_places=2,
        symbol_position="before",
        thousands_separator=",",
        decimal_separator=".",
    )


def format_currency(amount: Decimal, currency_code: str) -> str:
    """Format an amount according to ISO 4217 rules for the given currency.

    Examples:
        format_currency(Decimal("1234.56"), "NZD") -> "$1,234.56"
        format_currency(Decimal("1234.56"), "EUR") -> "€1.234,56"
        format_currency(Decimal("1234"), "JPY") -> "¥1,234"
        format_currency(Decimal("1234.56"), "SEK") -> "1 234,56 kr"
    """
    fmt = get_currency_format(currency_code)

    # Round to correct decimal places
    if fmt.decimal_places == 0:
        rounded = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    else:
        quantizer = Decimal(10) ** -fmt.decimal_places
        rounded = amount.quantize(quantizer, rounding=ROUND_HALF_UP)

    # Split into integer and decimal parts
    abs_val = abs(rounded)
    sign = "-" if rounded < 0 else ""

    if fmt.decimal_places > 0:
        int_part = int(abs_val)
        dec_part = str(abs_val).split(".")[-1] if "." in str(abs_val) else "0" * fmt.decimal_places
        dec_part = dec_part.ljust(fmt.decimal_places, "0")[:fmt.decimal_places]
    else:
        int_part = int(abs_val)
        dec_part = ""

    # Format integer part with thousands separator
    int_str = f"{int_part:,}".replace(",", fmt.thousands_separator)

    # Combine
    if dec_part:
        number_str = f"{int_str}{fmt.decimal_separator}{dec_part}"
    else:
        number_str = int_str

    # Apply symbol position
    if fmt.symbol_position == "after":
        return f"{sign}{number_str} {fmt.symbol}"
    return f"{sign}{fmt.symbol}{number_str}"
