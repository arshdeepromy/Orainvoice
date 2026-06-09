# Feature: customer-reminder-consent
"""Unit tests for the customer reminder consent helpers and exceptions.

This file is seeded by Task A3 with a single round-trip assertion for
:class:`RemindersConsentRequiredError`. Task A2 will append further tests
for the pure helpers (``coverage_for``, ``compute_missing_consent``,
``union_channel_for_category``, ``current_consent_text``).
"""

from __future__ import annotations

from app.modules.customers.exceptions import RemindersConsentRequiredError


def test_consent_required_error_carries_missing() -> None:
    """The ``missing`` payload round-trips with both ``category`` and ``channel`` keys.

    This is the wire contract for the HTTP 409 response body that
    ``PUT /customers/{id}/reminders`` returns when consent is required.
    """
    payload = [{"category": "wof_expiry", "channel": "sms"}]

    err = RemindersConsentRequiredError(missing=payload)

    assert err.missing == payload
    assert err.missing[0]["category"] == "wof_expiry"
    assert err.missing[0]["channel"] == "sms"
    assert set(err.missing[0].keys()) == {"category", "channel"}


# ---------------------------------------------------------------------------
# Pure helper tests appended by Task A2.
# ---------------------------------------------------------------------------

from app.modules.customers.consent import (
    RemindersConsentEntry,
    compute_missing_consent,
    coverage_for,
    current_consent_text,
    union_channel_for_category,
)
from app.modules.customers.consent_text import KIOSK_CONSENT_TEXT_VERSION


def test_coverage_for_with_both_channel_expansion() -> None:
    """``channel == "both"`` expands into separate sms + email coverage entries."""
    consent = {
        "entries": [
            {"vehicle_id": None, "category": "wof_expiry", "channel": "both"}
        ]
    }

    covered = coverage_for(consent)

    assert covered == {("wof_expiry", "sms"), ("wof_expiry", "email")}


def test_coverage_for_with_no_consent() -> None:
    """``coverage_for`` is empty for None / empty dict / empty entries."""
    assert coverage_for(None) == set()
    assert coverage_for({}) == set()
    assert coverage_for({"entries": []}) == set()


def test_compute_missing_consent_covered() -> None:
    """When existing consent covers every newly-enabled pair, missing is empty."""
    existing_consent = {
        "entries": [
            {"vehicle_id": None, "category": "wof_expiry", "channel": "sms"},
            {"vehicle_id": None, "category": "service_due", "channel": "email"},
        ]
    }
    new_config = {
        "wof_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
        "service_due": {"enabled": True, "channel": "email", "days_before": 30},
    }

    assert compute_missing_consent(existing_consent, new_config) == []


def test_compute_missing_consent_uncovered() -> None:
    """When no existing consent covers the new pair, missing has one entry."""
    new_config = {
        "wof_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
    }

    missing = compute_missing_consent(None, new_config)

    assert missing == [{"category": "wof_expiry", "channel": "sms"}]


def test_compute_missing_consent_already_enabled_no_gate() -> None:
    """When consent covers the pair, the gate does not trigger.

    Per design §3.2, ``compute_missing_consent`` only checks new_config
    against existing_consent — the "newly transitioning" check happens
    at the caller (A4). For this helper test we assert the bare contract:
    covered pair -> empty list; uncovered pair -> non-empty list.
    """
    existing_consent = {
        "entries": [
            {"vehicle_id": None, "category": "wof_expiry", "channel": "sms"},
        ]
    }
    new_config_covered = {
        "wof_expiry": {"enabled": True, "channel": "sms", "days_before": 30},
    }
    new_config_uncovered = {
        "service_due": {"enabled": True, "channel": "email", "days_before": 30},
    }

    assert compute_missing_consent(existing_consent, new_config_covered) == []
    assert compute_missing_consent(existing_consent, new_config_uncovered) == [
        {"category": "service_due", "channel": "email"}
    ]


def test_compute_missing_consent_with_both_channel_in_new_config() -> None:
    """``channel == "both"`` in new_config requires both sms AND email coverage."""
    new_config = {
        "wof_expiry": {"enabled": True, "channel": "both", "days_before": 30},
    }

    # No consent at all -> two missing entries (sms + email).
    missing_none = compute_missing_consent(None, new_config)
    assert {(m["category"], m["channel"]) for m in missing_none} == {
        ("wof_expiry", "sms"),
        ("wof_expiry", "email"),
    }
    assert len(missing_none) == 2

    # Consent covers only sms -> one missing entry (email).
    existing_sms_only = {
        "entries": [
            {"vehicle_id": None, "category": "wof_expiry", "channel": "sms"}
        ]
    }
    missing_sms_only = compute_missing_consent(existing_sms_only, new_config)
    assert missing_sms_only == [{"category": "wof_expiry", "channel": "email"}]


def _entry(category: str, channel: str) -> RemindersConsentEntry:
    return RemindersConsentEntry(
        vehicle_id=None, category=category, channel=channel  # type: ignore[arg-type]
    )


def test_union_channel_for_category_single() -> None:
    """A single sms entry resolves to ``"sms"``."""
    entries = [_entry("wof_expiry", "sms")]

    assert union_channel_for_category(entries, "wof_expiry") == "sms"


def test_union_channel_for_category_mixed() -> None:
    """Mixed sms + email entries resolve to ``"both"`` (Req 1.14)."""
    entries = [_entry("wof_expiry", "sms"), _entry("wof_expiry", "email")]

    assert union_channel_for_category(entries, "wof_expiry") == "both"


def test_union_channel_for_category_both_explicit() -> None:
    """A single explicit ``"both"`` entry resolves to ``"both"``."""
    entries = [_entry("wof_expiry", "both")]

    assert union_channel_for_category(entries, "wof_expiry") == "both"


def test_union_channel_for_category_both_dominates() -> None:
    """``"both"`` mixed with a single channel still resolves to ``"both"``."""
    entries = [_entry("wof_expiry", "sms"), _entry("wof_expiry", "both")]

    assert union_channel_for_category(entries, "wof_expiry") == "both"


def test_current_consent_text_returns_text_and_version() -> None:
    """``current_consent_text`` returns ``(text, version)`` from the constant module."""
    text, version = current_consent_text()

    assert isinstance(text, str)
    assert isinstance(version, str)
    assert text  # non-empty
    assert version == KIOSK_CONSENT_TEXT_VERSION
