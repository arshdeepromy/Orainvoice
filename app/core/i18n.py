"""Internationalisation and localisation service.

Provides locale-aware formatting for dates, numbers, and currencies,
plus translation loading from JSON files on disk.

Supported locales: en, mi, fr, es, de, pt, zh, ja, ar, hi

**Validates: Requirement 32**
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300
CACHE_KEY_PREFIX = "i18n:"

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "i18n"

SUPPORTED_LOCALES = ["en", "mi", "fr", "es", "de", "pt", "zh", "ja", "ar", "hi"]

RTL_LOCALES = {"ar"}

# ---------------------------------------------------------------------------
# Locale configuration — date/number/currency formatting rules per locale
# ---------------------------------------------------------------------------

LOCALE_CONFIGS: dict[str, dict[str, Any]] = {
    "en": {
        "name": "English",
        "native_name": "English",
        "direction": "ltr",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": ",",
        "decimal_separator": ".",
        "currency_symbol_position": "before",
    },
    "mi": {
        "name": "Māori",
        "native_name": "Te Reo Māori",
        "direction": "ltr",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": ",",
        "decimal_separator": ".",
        "currency_symbol_position": "before",
    },
    "fr": {
        "name": "French",
        "native_name": "Français",
        "direction": "ltr",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": " ",
        "decimal_separator": ",",
        "currency_symbol_position": "after",
    },
    "es": {
        "name": "Spanish",
        "native_name": "Español",
        "direction": "ltr",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": ".",
        "decimal_separator": ",",
        "currency_symbol_position": "after",
    },
    "de": {
        "name": "German",
        "native_name": "Deutsch",
        "direction": "ltr",
        "date_format": "dd.MM.yyyy",
        "thousands_separator": ".",
        "decimal_separator": ",",
        "currency_symbol_position": "after",
    },
    "pt": {
        "name": "Portuguese",
        "native_name": "Português",
        "direction": "ltr",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": ".",
        "decimal_separator": ",",
        "currency_symbol_position": "before",
    },
    "zh": {
        "name": "Chinese (Simplified)",
        "native_name": "简体中文",
        "direction": "ltr",
        "date_format": "yyyy-MM-dd",
        "thousands_separator": ",",
        "decimal_separator": ".",
        "currency_symbol_position": "before",
    },
    "ja": {
        "name": "Japanese",
        "native_name": "日本語",
        "direction": "ltr",
        "date_format": "yyyy/MM/dd",
        "thousands_separator": ",",
        "decimal_separator": ".",
        "currency_symbol_position": "before",
    },
    "ar": {
        "name": "Arabic",
        "native_name": "العربية",
        "direction": "rtl",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": "٬",
        "decimal_separator": "٫",
        "currency_symbol_position": "after",
    },
    "hi": {
        "name": "Hindi",
        "native_name": "हिन्दी",
        "direction": "ltr",
        "date_format": "dd/MM/yyyy",
        "thousands_separator": ",",
        "decimal_separator": ".",
        "currency_symbol_position": "before",
    },
}


# ---------------------------------------------------------------------------
# Required translation keys — every locale file must contain these
# ---------------------------------------------------------------------------

REQUIRED_TRANSLATION_KEYS: list[str] = [
    # Invoice labels
    "invoice.title",
    "invoice.number",
    "invoice.date",
    "invoice.due_date",
    "invoice.bill_to",
    "invoice.description",
    "invoice.quantity",
    "invoice.unit_price",
    "invoice.amount",
    "invoice.subtotal",
    "invoice.tax",
    "invoice.total",
    "invoice.paid",
    "invoice.balance_due",
    "invoice.notes",
    "invoice.terms",
    "invoice.status_draft",
    "invoice.status_sent",
    "invoice.status_paid",
    "invoice.status_overdue",
    "invoice.status_cancelled",
    # Common UI
    "common.save",
    "common.cancel",
    "common.delete",
    "common.edit",
    "common.create",
    "common.search",
    "common.filter",
    "common.loading",
    "common.error",
    "common.success",
    "common.confirm",
    "common.back",
    "common.next",
    "common.skip",
    "common.yes",
    "common.no",
    "common.close",
    "common.submit",
    # Error messages
    "error.not_found",
    "error.unauthorized",
    "error.forbidden",
    "error.validation",
    "error.server_error",
    "error.network_error",
    # Email templates
    "email.invoice_subject",
    "email.invoice_body",
    "email.reminder_subject",
    "email.reminder_body",
    "email.welcome_subject",
    "email.welcome_body",
    # Portal
    "portal.title",
    "portal.view_invoice",
    "portal.pay_now",
    "portal.download_pdf",
    "portal.payment_history",
    # Setup wizard
    "setup.welcome_title",
    "setup.welcome_subtitle",
    "setup.country_step",
    "setup.trade_step",
    "setup.business_step",
    "setup.branding_step",
    "setup.modules_step",
    "setup.catalogue_step",
    "setup.ready_step",
    "setup.complete",
]


class I18nService:
    """Internationalisation service for translations and locale-aware formatting.

    Loads translations from JSON files in ``app/i18n/`` and provides
    formatting methods that respect locale-specific rules.
    """

    def __init__(self) -> None:
        self._translation_cache: dict[str, dict[str, str]] = {}

    def get_translations(self, locale: str) -> dict[str, str]:
        """Load and return translations for the given locale.

        Falls back to English if the locale is not supported.
        Results are cached in-memory after first load.
        """
        if locale not in SUPPORTED_LOCALES:
            locale = "en"

        if locale in self._translation_cache:
            return self._translation_cache[locale]

        file_path = TRANSLATIONS_DIR / f"{locale}.json"
        if not file_path.exists():
            logger.warning("Translation file not found: %s, falling back to en", file_path)
            file_path = TRANSLATIONS_DIR / "en.json"

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                translations = json.load(f)
            self._translation_cache[locale] = translations
            return translations
        except Exception:
            logger.error("Failed to load translations for locale=%s", locale)
            return {}

    def get_locale_config(self, locale: str) -> dict[str, Any]:
        """Return locale configuration (date format, separators, direction)."""
        if locale not in SUPPORTED_LOCALES:
            locale = "en"
        config = dict(LOCALE_CONFIGS.get(locale, LOCALE_CONFIGS["en"]))
        config["locale"] = locale
        config["is_rtl"] = locale in RTL_LOCALES
        return config

    def format_date(self, d: date | datetime, locale: str) -> str:
        """Format a date according to locale-specific rules.

        Supported patterns:
        - dd/MM/yyyy (NZ, AU, UK, FR, ES, etc.)
        - MM/dd/yyyy (US)
        - yyyy-MM-dd (ISO / Chinese)
        - yyyy/MM/dd (Japanese)
        - dd.MM.yyyy (German)
        """
        if locale not in SUPPORTED_LOCALES:
            locale = "en"

        config = LOCALE_CONFIGS.get(locale, LOCALE_CONFIGS["en"])
        fmt = config["date_format"]

        if isinstance(d, datetime):
            d = d.date()

        day = str(d.day).zfill(2)
        month = str(d.month).zfill(2)
        year = str(d.year)

        result = fmt.replace("dd", day).replace("MM", month).replace("yyyy", year)
        return result

    def format_number(self, value: Decimal | float | int, locale: str, decimal_places: int = 2) -> str:
        """Format a number with locale-specific thousands and decimal separators."""
        if locale not in SUPPORTED_LOCALES:
            locale = "en"

        config = LOCALE_CONFIGS.get(locale, LOCALE_CONFIGS["en"])
        thousands_sep = config["thousands_separator"]
        decimal_sep = config["decimal_separator"]

        dec_val = Decimal(str(value))
        if decimal_places == 0:
            rounded = dec_val.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        else:
            quantizer = Decimal(10) ** -decimal_places
            rounded = dec_val.quantize(quantizer, rounding=ROUND_HALF_UP)

        sign = "-" if rounded < 0 else ""
        abs_val = abs(rounded)

        int_part = int(abs_val)
        if decimal_places > 0:
            raw = str(abs_val)
            if "." in raw:
                dec_part = raw.split(".")[-1].ljust(decimal_places, "0")[:decimal_places]
            else:
                dec_part = "0" * decimal_places
        else:
            dec_part = ""

        int_str = f"{int_part:,}".replace(",", thousands_sep)

        if dec_part:
            return f"{sign}{int_str}{decimal_sep}{dec_part}"
        return f"{sign}{int_str}"

    def format_currency(
        self,
        amount: Decimal | float | int,
        currency_code: str,
        locale: str,
    ) -> str:
        """Format a currency amount using locale rules and ISO 4217 currency info."""
        from app.modules.multi_currency.formatting import get_currency_format

        if locale not in SUPPORTED_LOCALES:
            locale = "en"

        config = LOCALE_CONFIGS.get(locale, LOCALE_CONFIGS["en"])
        fmt = get_currency_format(currency_code)

        number_str = self.format_number(amount, locale, decimal_places=fmt.decimal_places)

        symbol_pos = config["currency_symbol_position"]
        if symbol_pos == "after":
            return f"{number_str} {fmt.symbol}"
        return f"{fmt.symbol}{number_str}"

    def is_rtl(self, locale: str) -> bool:
        """Check if a locale uses right-to-left text direction."""
        return locale in RTL_LOCALES


# Module-level singleton for convenience
i18n_service = I18nService()
