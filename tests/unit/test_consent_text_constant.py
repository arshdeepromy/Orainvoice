# Feature: customer-reminder-consent
"""Unit tests for ``app/modules/customers/consent_text.py``.

These tests guard the legally-reviewed kiosk Consent_Text and its version
string. They assert that the version string is non-empty, that the text
contains the three substance-bearing clauses required by the Unsolicited
Electronic Messages Act 2007 (categories of message, revoke-by-phone, and
without-penalty), and that the ``{workshop_name}`` placeholder is present
so that the backend can substitute the org name at render time.
"""

from app.modules.customers.consent_text import (
    KIOSK_CONSENT_TEXT,
    KIOSK_CONSENT_TEXT_VERSION,
)


def test_kiosk_consent_text_version_is_non_empty_string() -> None:
    assert isinstance(KIOSK_CONSENT_TEXT_VERSION, str)
    assert KIOSK_CONSENT_TEXT_VERSION.strip() != ""


def test_kiosk_consent_text_mentions_required_categories() -> None:
    """The Consent_Text must clearly identify the categories of message
    that will be sent (Req 1.8a, Req 6.1)."""
    assert "WOF" in KIOSK_CONSENT_TEXT
    assert "COF" in KIOSK_CONSENT_TEXT
    assert "registration" in KIOSK_CONSENT_TEXT
    assert "service" in KIOSK_CONSENT_TEXT


def test_kiosk_consent_text_states_revoke_by_phone() -> None:
    """The Consent_Text must tell the Customer they can revoke consent by
    phoning the workshop (Req 1.8b, Req 6.1)."""
    assert "phoning the workshop" in KIOSK_CONSENT_TEXT


def test_kiosk_consent_text_states_without_penalty() -> None:
    """The Consent_Text must state that withdrawal carries no penalty
    (Req 1.8c, Req 6.1)."""
    assert "without penalty" in KIOSK_CONSENT_TEXT


def test_kiosk_consent_text_contains_workshop_name_placeholder() -> None:
    """The Consent_Text must contain the ``{workshop_name}`` placeholder so
    the backend can substitute the org name at render time without needing
    to bump ``KIOSK_CONSENT_TEXT_VERSION`` (Req 6.2)."""
    assert "{workshop_name}" in KIOSK_CONSENT_TEXT
