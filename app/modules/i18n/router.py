"""I18n API router.

Mounted at ``/api/v2/i18n``.

- GET /translations/{locale} — returns translations for a locale
- GET /locales — returns all supported locales with their configs

**Validates: Requirement 32**
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.i18n import (
    LOCALE_CONFIGS,
    SUPPORTED_LOCALES,
    i18n_service,
)
from app.modules.i18n.schemas import (
    LocaleConfig,
    LocaleListResponse,
    TranslationsResponse,
)

router = APIRouter()


@router.get(
    "/translations/{locale}",
    response_model=TranslationsResponse,
    summary="Get translations for a locale",
)
async def get_translations(locale: str):
    """Return all translation strings for the given locale.

    Falls back to English if the locale is not supported.
    """
    config = i18n_service.get_locale_config(locale)
    translations = i18n_service.get_translations(locale)
    return TranslationsResponse(
        locale=config["locale"],
        direction=config["direction"],
        translations=translations,
    )


@router.get(
    "/locales",
    response_model=LocaleListResponse,
    summary="List all supported locales",
)
async def list_locales():
    """Return all supported locales with their configuration."""
    locales = []
    for loc in SUPPORTED_LOCALES:
        config = i18n_service.get_locale_config(loc)
        locales.append(LocaleConfig(**config))
    return LocaleListResponse(locales=locales)
