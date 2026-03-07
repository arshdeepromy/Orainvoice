"""I18n-aware email template helpers.

Provides translated email subjects and body text for invoice emails,
reminders, and welcome messages based on the org's configured language.

**Validates: Requirement 32, Task 50.8**
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import SUPPORTED_LOCALES, i18n_service


def get_email_translations(locale: str) -> dict[str, str]:
    """Return translated email strings for the given locale.

    Falls back to English for unsupported locales.
    """
    if locale not in SUPPORTED_LOCALES:
        locale = "en"

    translations = i18n_service.get_translations(locale)

    return {
        "invoice_subject": translations.get(
            "email.invoice_subject",
            "Invoice {invoice_number} from {business_name}",
        ),
        "invoice_body": translations.get(
            "email.invoice_body",
            "Please find attached invoice {invoice_number} for {amount}.",
        ),
        "reminder_subject": translations.get(
            "email.reminder_subject",
            "Payment reminder for invoice {invoice_number}",
        ),
        "reminder_body": translations.get(
            "email.reminder_body",
            "This is a reminder that invoice {invoice_number} for {amount} is due on {due_date}.",
        ),
        "welcome_subject": translations.get(
            "email.welcome_subject",
            "Welcome to {platform_name}",
        ),
        "welcome_body": translations.get(
            "email.welcome_body",
            "Your account has been created. Get started by completing the setup wizard.",
        ),
    }


def render_email_subject(
    template_key: str,
    locale: str,
    **kwargs: Any,
) -> str:
    """Render a translated email subject with variable substitution.

    Parameters
    ----------
    template_key:
        One of: invoice_subject, reminder_subject, welcome_subject
    locale:
        The locale code (e.g. "en", "fr", "ar")
    **kwargs:
        Template variables (invoice_number, business_name, amount, etc.)
    """
    templates = get_email_translations(locale)
    template = templates.get(template_key, template_key)
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


def render_email_body(
    template_key: str,
    locale: str,
    **kwargs: Any,
) -> str:
    """Render a translated email body with variable substitution.

    Parameters
    ----------
    template_key:
        One of: invoice_body, reminder_body, welcome_body
    locale:
        The locale code (e.g. "en", "fr", "ar")
    **kwargs:
        Template variables (invoice_number, business_name, amount, etc.)
    """
    templates = get_email_translations(locale)
    template = templates.get(template_key, template_key)
    try:
        return template.format(**kwargs)
    except KeyError:
        return template
