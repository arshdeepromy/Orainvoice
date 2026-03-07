"""Pydantic schemas for the i18n module.

**Validates: Requirement 32**
"""

from __future__ import annotations

from pydantic import BaseModel


class LocaleConfig(BaseModel):
    """Configuration for a single locale."""
    locale: str
    name: str
    native_name: str
    direction: str
    date_format: str
    thousands_separator: str
    decimal_separator: str
    currency_symbol_position: str
    is_rtl: bool


class LocaleListResponse(BaseModel):
    """Response for GET /api/v2/i18n/locales."""
    locales: list[LocaleConfig]


class TranslationsResponse(BaseModel):
    """Response for GET /api/v2/i18n/translations/{locale}."""
    locale: str
    direction: str
    translations: dict[str, str]
