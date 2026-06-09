"""Property test — audit completeness for consent events (CP-3).

Feature: customer-reminder-consent, Property 3: Audit completeness for consent
events — every consent grant / revocation writes exactly one audit_log row
with the correct action string, and its after_value omits the redacted PII
keys (ip_address / user_agent for grants; recorded_by_user_id /
recorded_by_user_email for revocations).

Validates: Requirements 1.17, 2.9, 3.7, 7.1, 7.2.
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
    RemindersRevocationRecord,
)
from app.modules.customers.models import Customer
from app.modules.customers.service import (
    revoke_customer_reminders,
    update_customer_reminder_config,
)

CATEGORIES = ["service_due", "wof_expiry", "cof_expiry", "registration_expiry"]


def _make_customer(org_id, custom_fields=None):
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.custom_fields = custom_fields or {}
    return c


def _make_db(customer):
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


cats_strategy = st.lists(st.sampled_from(CATEGORIES), min_size=1, max_size=4, unique=True)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cats=cats_strategy)
@pytest.mark.asyncio
async def test_given_writes_one_redacted_audit_row(cats):
    org_id = uuid.uuid4()
    customer = _make_customer(org_id)
    db = _make_db(customer)
    calls: list[dict] = []

    with patch("app.modules.customers.consent.flag_modified", lambda *a, **k: None), patch(
        "app.modules.customers.service.flag_modified", lambda *a, **k: None
    ), patch(
        "app.modules.customers.consent.write_audit_log",
        new=AsyncMock(side_effect=lambda *a, **k: calls.append(k)),
    ):
        await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders={c: {"enabled": True, "channel": "both", "days_before": 30} for c in cats},
            consent_record=RemindersConsentRecord(
                given_at=datetime.now(timezone.utc),
                source="manually_recorded_by_staff:phone",
                entries=[RemindersConsentEntry(vehicle_id=None, category=c, channel="both") for c in cats],
                consent_text_version="2026-06-08-v1",
                recorded_by_user_id=uuid.uuid4(),
                recorded_by_user_email="staff@example.com",
                ip_address="203.0.113.1",
                user_agent="Mozilla/5.0",
            ),
            ip_address="203.0.113.1",
            user_agent="Mozilla/5.0",
        )

    assert len(calls) == 1
    assert calls[0]["action"] == "customer.reminder_consent.given"
    after = calls[0]["after_value"]
    assert "ip_address" not in after
    assert "user_agent" not in after


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cats=cats_strategy)
@pytest.mark.asyncio
async def test_revoked_writes_one_redacted_audit_row(cats):
    org_id = uuid.uuid4()
    # All target categories currently enabled so the revoke actually fires.
    config = {c: {"enabled": True, "channel": "sms", "days_before": 30} for c in CATEGORIES}
    customer = _make_customer(org_id, {"reminder_config": config})
    db = _make_db(customer)
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "staff@example.com"
    calls: list[dict] = []

    record = RemindersRevocationRecord(
        revoked_at=datetime.now(timezone.utc),
        source="manually_recorded_by_staff:phone",
        recorded_by_user_id=user.id,
        recorded_by_user_email=user.email,
        channel="sms",
        categories_affected=cats,
        reason_note="Customer asked",
    )

    with patch("app.modules.customers.consent.flag_modified", lambda *a, **k: None), patch(
        "app.modules.customers.service.flag_modified", lambda *a, **k: None
    ), patch(
        "app.modules.customers.consent.write_audit_log",
        new=AsyncMock(side_effect=lambda *a, **k: calls.append(k)),
    ):
        await revoke_customer_reminders(
            db, org_id=org_id, customer_id=customer.id, current_user=user, record=record
        )

    assert len(calls) == 1
    assert calls[0]["action"] == "customer.reminder_consent.revoked"
    after = calls[0]["after_value"]
    assert "recorded_by_user_id" not in after
    assert "recorded_by_user_email" not in after
