"""Property test — consent persistence is transactional (CP-1).

Feature: customer-reminder-consent, Property 1: Consent persistence is
transactional — on success BOTH the reminder_consent record and the
reminder_config are persisted together with exactly one audit row; on an
injected audit failure the call raises so the surrounding session.begin()
rolls the whole request back (nothing committed).

Validates: Requirements 1.13, 1.14, 1.15, 1.16, 2.7, 2.8, 6.4, 7.3.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# Configure ORM mappers.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.customers.consent import (
    RemindersConsentEntry,
    RemindersConsentRecord,
)
from app.modules.customers.models import Customer
from app.modules.customers.service import update_customer_reminder_config

CATEGORIES = ["service_due", "wof_expiry", "cof_expiry", "registration_expiry"]
CHANNELS = ["sms", "email", "both"]


def _make_customer(org_id: uuid.UUID) -> MagicMock:
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.custom_fields = {}
    return c


def _make_db(customer: MagicMock) -> AsyncMock:
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


# A non-empty mapping {category: channel} of categories to enable.
enabled_config = st.dictionaries(
    keys=st.sampled_from(CATEGORIES),
    values=st.sampled_from(CHANNELS),
    min_size=1,
    max_size=4,
)


def _config(cfg: dict[str, str]) -> dict:
    return {
        cat: {"enabled": True, "channel": chan, "days_before": 30}
        for cat, chan in cfg.items()
    }


def _covering_record(cfg: dict[str, str]) -> RemindersConsentRecord:
    # Cover every enabled category with channel="both" so the gate never fires.
    return RemindersConsentRecord(
        given_at=datetime.now(timezone.utc),
        source="manually_recorded_by_staff:phone",
        entries=[
            RemindersConsentEntry(vehicle_id=None, category=cat, channel="both")
            for cat in cfg
        ],
        consent_text_version="2026-06-08-v1",
        recorded_by_user_id=uuid.uuid4(),
        recorded_by_user_email="staff@example.com",
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cfg=enabled_config)
@pytest.mark.asyncio
async def test_success_copersists_consent_config_and_one_audit(cfg):
    org_id = uuid.uuid4()
    customer = _make_customer(org_id)
    db = _make_db(customer)
    audit_calls: list[dict] = []

    async def _capture(*a, **k):
        audit_calls.append(k)

    with patch("app.modules.customers.consent.flag_modified", lambda *a, **k: None), patch(
        "app.modules.customers.service.flag_modified", lambda *a, **k: None
    ), patch(
        "app.modules.customers.consent.write_audit_log", new=AsyncMock(side_effect=_capture)
    ):
        await update_customer_reminder_config(
            db,
            org_id=org_id,
            customer_id=customer.id,
            reminders=_config(cfg),
            consent_record=_covering_record(cfg),
        )

    # BOTH fields co-persisted on the customer record.
    assert "reminder_consent" in customer.custom_fields
    assert "reminder_config" in customer.custom_fields
    for cat in cfg:
        assert customer.custom_fields["reminder_config"][cat]["enabled"] is True
    # Exactly one audit row for the consent grant.
    assert len(audit_calls) == 1
    assert audit_calls[0].get("action") == "customer.reminder_consent.given"


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cfg=enabled_config)
@pytest.mark.asyncio
async def test_audit_failure_propagates_for_rollback(cfg):
    org_id = uuid.uuid4()
    customer = _make_customer(org_id)
    db = _make_db(customer)

    with patch("app.modules.customers.consent.flag_modified", lambda *a, **k: None), patch(
        "app.modules.customers.service.flag_modified", lambda *a, **k: None
    ), patch(
        "app.modules.customers.consent.write_audit_log",
        new=AsyncMock(side_effect=RuntimeError("audit insert failed")),
    ):
        # The exception must propagate (the real session.begin rolls back).
        with pytest.raises(RuntimeError, match="audit insert failed"):
            await update_customer_reminder_config(
                db,
                org_id=org_id,
                customer_id=customer.id,
                reminders=_config(cfg),
                consent_record=_covering_record(cfg),
            )
