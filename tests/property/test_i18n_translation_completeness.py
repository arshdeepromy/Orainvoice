"""Property-based test: i18n translation key completeness.

**Validates: Requirements 32.1, 32.2**

Property 18 (extended): For any supported locale, all required translation
keys exist in the translation file. No key is missing.

This test verifies that every locale file contains all keys defined in
REQUIRED_TRANSLATION_KEYS, ensuring no user-facing string is untranslated.
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.core.i18n import (
    REQUIRED_TRANSLATION_KEYS,
    SUPPORTED_LOCALES,
    I18nService,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_locale_strategy = st.sampled_from(SUPPORTED_LOCALES)


# ===========================================================================
# Property 18 (extended): Translation Key Completeness
# ===========================================================================


class TestI18nTranslationCompleteness:
    """For any supported locale, all required translation keys exist.

    **Validates: Requirements 32.1, 32.2**
    """

    @given(locale=_locale_strategy)
    @PBT_SETTINGS
    def test_all_required_keys_present(self, locale: str) -> None:
        """Every supported locale has all required translation keys."""
        svc = I18nService()
        translations = svc.get_translations(locale)

        missing = [
            key for key in REQUIRED_TRANSLATION_KEYS
            if key not in translations
        ]
        assert not missing, (
            f"Locale '{locale}' is missing required translation keys: {missing}"
        )

    @given(locale=_locale_strategy)
    @PBT_SETTINGS
    def test_no_empty_translations(self, locale: str) -> None:
        """No required translation key has an empty string value."""
        svc = I18nService()
        translations = svc.get_translations(locale)

        empty_keys = [
            key for key in REQUIRED_TRANSLATION_KEYS
            if key in translations and not translations[key].strip()
        ]
        assert not empty_keys, (
            f"Locale '{locale}' has empty translations for keys: {empty_keys}"
        )

    @given(locale=_locale_strategy)
    @PBT_SETTINGS
    def test_translations_are_deterministic(self, locale: str) -> None:
        """Loading translations twice for the same locale returns identical results."""
        svc1 = I18nService()
        svc2 = I18nService()
        t1 = svc1.get_translations(locale)
        t2 = svc2.get_translations(locale)
        assert t1 == t2, (
            f"Translations for locale '{locale}' are not deterministic"
        )

    @given(locale=_locale_strategy)
    @PBT_SETTINGS
    def test_locale_config_exists(self, locale: str) -> None:
        """Every supported locale has a valid locale config."""
        svc = I18nService()
        config = svc.get_locale_config(locale)

        assert config["locale"] == locale
        assert config["direction"] in ("ltr", "rtl")
        assert config["date_format"]
        assert config["thousands_separator"]
        assert config["decimal_separator"]
        assert config["currency_symbol_position"] in ("before", "after")
