"""Unit tests for the kiosk consent schema extension (C2).

Feature: customer-reminder-consent

Round-trips ``KioskCheckInRequestV2`` with the new ``reminder_consent`` block
set and unset, and exercises the ``consent_provided()`` convenience method
(Req 1.12 master-unchecked no-op).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.kiosk.schemas import (
    KioskCheckInRequestV2,
    KioskReminderConsentBlock,
)


def _base_body() -> dict:
    return {
        "first_name": "Jo",
        "last_name": "Driver",
        "phone": "021555000",
        "email": "jo@example.com",
        "vehicles": [],
    }


def test_request_without_consent_block_defaults_none_and_not_provided():
    req = KioskCheckInRequestV2.model_validate(_base_body())
    assert req.reminder_consent is None
    assert req.consent_provided() is False


def test_request_with_consent_block_round_trips_and_is_provided():
    body = _base_body()
    body["reminder_consent"] = {
        "consent_text_version": "2026-06-08-v1",
        "entries": [
            {
                "vehicle_id": str(uuid.uuid4()),
                "category": "wof_expiry",
                "channel": "sms",
            },
            {
                "vehicle_id": None,
                "category": "service_due",
                "channel": "both",
            },
        ],
    }

    req = KioskCheckInRequestV2.model_validate(body)
    assert isinstance(req.reminder_consent, KioskReminderConsentBlock)
    assert req.reminder_consent.consent_text_version == "2026-06-08-v1"
    assert len(req.reminder_consent.entries) == 2
    assert req.reminder_consent.entries[0].category == "wof_expiry"
    assert req.reminder_consent.entries[1].channel == "both"
    assert req.consent_provided() is True


def test_consent_block_with_empty_entries_is_not_provided():
    body = _base_body()
    body["reminder_consent"] = {
        "consent_text_version": "2026-06-08-v1",
        "entries": [],
    }
    req = KioskCheckInRequestV2.model_validate(body)
    # Master toggle on but no rows ticked → treated as no consent (Req 1.12).
    assert req.consent_provided() is False


def test_invalid_category_is_rejected():
    body = _base_body()
    body["reminder_consent"] = {
        "consent_text_version": "2026-06-08-v1",
        "entries": [
            {"vehicle_id": None, "category": "not_a_category", "channel": "sms"}
        ],
    }
    with pytest.raises(ValueError):
        KioskCheckInRequestV2.model_validate(body)
