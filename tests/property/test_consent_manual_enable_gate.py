"""Property test — manual-enable consent gate (CP-2).

Feature: customer-reminder-consent, Property 2: Manual-enable consent gate —
for any newly-enabled (category, channel) pair not covered by existing consent
and with no consent_record supplied, the call raises
RemindersConsentRequiredError and the reminder_config is NOT mutated; when the
pair is already covered (or a covering consent_record is supplied) the config
persists.

Validates: Requirements 2.2, 2.3, 2.10, 2.11, 2.12, 2.13.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.customers.consent import (
    RemindersConsentEntry,
    RemindersConsentRecord,
)
from app.modules.customers.exceptions import RemindersConsentRequiredError
from app.modules.customers.models import Customer
from app.modules.customers.service import update_customer_reminder_config

CATEGORIES = ["service_due", "wof_expiry", "cof_expiry", "registration_expiry"]
# Restrict to the binary alphabet so coverage reasoning is exact.
CHANNELS = ["sms", "email"]


def _make_customer(org_id, custom_fields=None) -> MagicMock:
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.custom_fields = custom_fields or {}
    return c


def _make_db(customer) -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    def _execute(stmt, *a, **k):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=customer)
        r.scalar_one = MagicMock(return_value=customer)
        return r

    db.execute = AsyncMock(side_effect=_execute)
    return db


def _existing_consent(pairs):
    return {
        "entries": [
            {"vehicle_id": None, "category": c, "channel": ch} for c, ch in pairs
        ]
    }


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    category=st.sampled_from(CATEGORIES),
    channel=st.sampled_from(CHANNELS),
    already_covered=st.booleans(),
    supply_record=st.booleans(),
)
@pytest.mark.asyncio
async def test_manual_enable_gate(category, channel, already_covered, supply_record):
    org_id = uuid.uuid4()
    custom_fields = {}
    if already_covered:
        custom_fields["reminder_consent"] = _existing_consent([(category, channel)])
    customer = _make_customer(org_id, custom_fields)
    db = _make_db(customer)

    reminders = {category: {"enabled": True, "channel": channel, "days_before": 30}}

    consent_record = None
    if supply_record:
        consent_record = RemindersConsentRecord(
            given_at=datetime.now(timezone.utc),
            source="manually_recorded_by_staff:phone",
            entries=[RemindersConsentEntry(vehicle_id=None, category=category, channel=channel)],
            consent_text_version="2026-06-08-v1",
            recorded_by_user_id=uuid.uuid4(),
            recorded_by_user_email="staff@example.com",
        )

    gate_should_fire = (not already_covered) and (not supply_record)

    with patch("app.modules.customers.consent.flag_modified", lambda *a, **k: None), patch(
        "app.modules.customers.service.flag_modified", lambda *a, **k: None
    ), patch(
        "app.modules.customers.consent.write_audit_log", new=AsyncMock()
    ):
        if gate_should_fire:
            with pytest.raises(RemindersConsentRequiredError) as exc:
                await update_customer_reminder_config(
                    db, org_id=org_id, customer_id=customer.id, reminders=reminders
                )
            # The missing payload carries exactly the uncovered pair.
            assert {"category": category, "channel": channel} in exc.value.missing
            # reminder_config was NOT written (no mutation on the gate path).
            assert "reminder_config" not in customer.custom_fields
        else:
            await update_customer_reminder_config(
                db,
                org_id=org_id,
                customer_id=customer.id,
                reminders=reminders,
                consent_record=consent_record,
            )
            assert customer.custom_fields["reminder_config"][category]["enabled"] is True
