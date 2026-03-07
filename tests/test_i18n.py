"""Tests for internationalisation and localisation.

Covers:
- RTL locale produces correctly mirrored PDF layout (Task 50.10)
- Currency formatting matches ISO 4217 rules (Task 50.11)
- I18nService formatting methods
- Translation loading and fallback

**Validates: Requirement 32**
"""

from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal

from app.core.i18n import (
    I18nService,
    SUPPORTED_LOCALES,
    RTL_LOCALES,
    LOCALE_CONFIGS,
    REQUIRED_TRANSLATION_KEYS,
    i18n_service,
)
from app.core.rtl import (
    is_rtl_locale,
    get_direction,
    get_pdf_layout_config,
    get_rtl_css,
    RTL_PDF_STYLES,
)
from app.core.i18n_pdf import get_pdf_labels, get_pdf_context


# ===========================================================================
# Task 50.10: RTL locale produces correctly mirrored PDF layout
# ===========================================================================


class TestRTLPDFLayout:
    """Test that RTL locales produce correctly mirrored PDF layouts."""

    def test_arabic_is_rtl(self):
        """Arabic locale is identified as RTL."""
        assert is_rtl_locale("ar") is True

    def test_english_is_ltr(self):
        """English locale is identified as LTR."""
        assert is_rtl_locale("en") is False

    def test_rtl_direction(self):
        """RTL locales return 'rtl' direction."""
        assert get_direction("ar") == "rtl"

    def test_ltr_direction(self):
        """LTR locales return 'ltr' direction."""
        assert get_direction("en") == "ltr"
        assert get_direction("fr") == "ltr"

    def test_rtl_pdf_layout_mirrored(self):
        """RTL PDF layout has mirrored positions."""
        layout = get_pdf_layout_config("ar")
        assert layout["direction"] == "rtl"
        assert layout["text_align"] == "right"
        assert layout["logo_position"] == "right"
        assert layout["business_info_position"] == "right"
        assert layout["bill_to_position"] == "left"
        assert layout["column_order"] == "reversed"
        assert layout["css_direction"] == "rtl"

    def test_ltr_pdf_layout_normal(self):
        """LTR PDF layout has normal positions."""
        layout = get_pdf_layout_config("en")
        assert layout["direction"] == "ltr"
        assert layout["text_align"] == "left"
        assert layout["logo_position"] == "left"
        assert layout["column_order"] == "normal"

    def test_rtl_css_generated_for_arabic(self):
        """RTL CSS rules are generated for Arabic locale."""
        css = get_rtl_css("ar")
        assert "direction: rtl" in css
        assert "text-align: right" in css

    def test_no_rtl_css_for_ltr_locale(self):
        """No RTL CSS is generated for LTR locales."""
        css = get_rtl_css("en")
        assert css == ""

    def test_pdf_context_includes_rtl_styles_for_arabic(self):
        """PDF context includes RTL styles for Arabic."""
        ctx = get_pdf_context("ar")
        assert ctx["i18n_direction"] == "rtl"
        assert ctx["i18n_rtl_styles"] != ""
        assert "direction: rtl" in ctx["i18n_rtl_styles"]

    def test_pdf_context_no_rtl_styles_for_english(self):
        """PDF context has no RTL styles for English."""
        ctx = get_pdf_context("en")
        assert ctx["i18n_direction"] == "ltr"
        assert ctx["i18n_rtl_styles"] == ""

    def test_pdf_labels_translated_for_arabic(self):
        """PDF labels are translated for Arabic locale."""
        labels = get_pdf_labels("ar")
        assert labels["invoice_title"] == "فاتورة"
        assert labels["total"] == "الإجمالي"

    def test_pdf_labels_english_default(self):
        """PDF labels default to English."""
        labels = get_pdf_labels("en")
        assert labels["invoice_title"] == "Invoice"
        assert labels["total"] == "Total"

    def test_all_non_arabic_locales_are_ltr(self):
        """All locales except Arabic are LTR."""
        for locale in SUPPORTED_LOCALES:
            if locale == "ar":
                continue
            assert get_direction(locale) == "ltr", (
                f"Locale '{locale}' should be LTR"
            )


# ===========================================================================
# Task 50.11: Currency formatting matches ISO 4217 rules
# ===========================================================================


class TestCurrencyFormatting:
    """Test that currency formatting matches ISO 4217 rules."""

    def test_nzd_format(self):
        """NZD formats with $ symbol before, 2 decimal places."""
        result = i18n_service.format_currency(Decimal("1234.56"), "NZD", "en")
        assert result == "$1,234.56"

    def test_eur_format_english_locale(self):
        """EUR with English locale uses € before amount."""
        result = i18n_service.format_currency(Decimal("1234.56"), "EUR", "en")
        assert result == "€1,234.56"

    def test_eur_format_french_locale(self):
        """EUR with French locale uses € after amount with space separator."""
        result = i18n_service.format_currency(Decimal("1234.56"), "EUR", "fr")
        assert result == "1 234,56 €"

    def test_eur_format_german_locale(self):
        """EUR with German locale uses € after amount with dot separator."""
        result = i18n_service.format_currency(Decimal("1234.56"), "EUR", "de")
        assert result == "1.234,56 €"

    def test_jpy_zero_decimals(self):
        """JPY has 0 decimal places per ISO 4217."""
        result = i18n_service.format_currency(Decimal("1234"), "JPY", "en")
        assert result == "¥1,234"

    def test_jpy_rounds_decimals(self):
        """JPY rounds to 0 decimal places."""
        result = i18n_service.format_currency(Decimal("1234.56"), "JPY", "en")
        assert result == "¥1,235"

    def test_gbp_format(self):
        """GBP formats with £ symbol before."""
        result = i18n_service.format_currency(Decimal("1234.56"), "GBP", "en")
        assert result == "£1,234.56"

    def test_sek_english_locale(self):
        """SEK with English locale uses locale's symbol position (before)."""
        result = i18n_service.format_currency(Decimal("1234.56"), "SEK", "en")
        # English locale places symbol before; the multi_currency formatting
        # module handles currency-native positioning separately.
        assert "kr" in result
        assert "1,234.56" in result or "1234.56" in result

    def test_inr_format(self):
        """INR formats with ₹ symbol before."""
        result = i18n_service.format_currency(Decimal("1234.56"), "INR", "en")
        assert result == "₹1,234.56"

    def test_brl_format_portuguese(self):
        """BRL with Portuguese locale uses R$ before, dot thousands."""
        result = i18n_service.format_currency(Decimal("1234.56"), "BRL", "pt")
        assert result == "R$1.234,56"

    def test_negative_amount(self):
        """Negative amounts include minus sign."""
        result = i18n_service.format_currency(Decimal("-500.00"), "NZD", "en")
        assert result == "$-500.00"

    def test_zero_amount(self):
        """Zero amount formats correctly."""
        result = i18n_service.format_currency(Decimal("0"), "NZD", "en")
        assert result == "$0.00"

    def test_large_amount(self):
        """Large amounts have thousands separators."""
        result = i18n_service.format_currency(Decimal("1000000.00"), "USD", "en")
        assert result == "$1,000,000.00"

    def test_spanish_locale_formatting(self):
        """Spanish locale uses dot for thousands, comma for decimal."""
        result = i18n_service.format_currency(Decimal("1234.56"), "EUR", "es")
        assert result == "1.234,56 €"


# ===========================================================================
# I18nService formatting tests
# ===========================================================================


class TestI18nServiceFormatting:
    """Test I18nService date and number formatting."""

    def test_format_date_english(self):
        """English date format: dd/MM/yyyy."""
        d = date(2024, 3, 15)
        assert i18n_service.format_date(d, "en") == "15/03/2024"

    def test_format_date_chinese(self):
        """Chinese date format: yyyy-MM-dd."""
        d = date(2024, 3, 15)
        assert i18n_service.format_date(d, "zh") == "2024-03-15"

    def test_format_date_japanese(self):
        """Japanese date format: yyyy/MM/dd."""
        d = date(2024, 3, 15)
        assert i18n_service.format_date(d, "ja") == "2024/03/15"

    def test_format_date_german(self):
        """German date format: dd.MM.yyyy."""
        d = date(2024, 3, 15)
        assert i18n_service.format_date(d, "de") == "15.03.2024"

    def test_format_number_english(self):
        """English number format: 1,234.56."""
        result = i18n_service.format_number(Decimal("1234.56"), "en")
        assert result == "1,234.56"

    def test_format_number_french(self):
        """French number format: 1 234,56."""
        result = i18n_service.format_number(Decimal("1234.56"), "fr")
        assert result == "1 234,56"

    def test_format_number_german(self):
        """German number format: 1.234,56."""
        result = i18n_service.format_number(Decimal("1234.56"), "de")
        assert result == "1.234,56"

    def test_format_number_zero_decimals(self):
        """Number with 0 decimal places."""
        result = i18n_service.format_number(Decimal("1234"), "en", decimal_places=0)
        assert result == "1,234"

    def test_unsupported_locale_falls_back_to_english(self):
        """Unsupported locale falls back to English."""
        d = date(2024, 3, 15)
        assert i18n_service.format_date(d, "xx") == "15/03/2024"

    def test_get_translations_fallback(self):
        """Unsupported locale falls back to English translations."""
        svc = I18nService()
        translations = svc.get_translations("xx")
        en_translations = svc.get_translations("en")
        assert translations == en_translations

    def test_is_rtl_arabic(self):
        """Arabic is RTL."""
        assert i18n_service.is_rtl("ar") is True

    def test_is_rtl_english(self):
        """English is not RTL."""
        assert i18n_service.is_rtl("en") is False
