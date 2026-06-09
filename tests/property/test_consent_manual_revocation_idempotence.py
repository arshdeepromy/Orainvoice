"""Property test — manual-revocation idempotence (CP-5).

Feature: customer-reminder-consent, Property 5 (CP-5): Manual-revocation
idempotence — the first revocation that hits an active entry flips its config
to disabled and appends exactly one revocation row; subsequent revocations of
now-disabled entries leave the config unchanged and append no further rows and
write no audit row.

Validates: Requirement 3 / CP-5.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.customers.consent import RemindersRevocationRecord
from app.modules.customers.models import Customer
from app.modules.customers.service import revoke_customer_reminders

CATEGORIES = ["service_due", "wof_expiry", "cof_expiry", "registration_expiry"]


def _make_customer(org_id, custom_fields):
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.custom_fields = custom_fields
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


def _record(user, cats):
    return RemindersRevocationRecord(
        revoked_at=datetime.now(timezone.utc),
        source="manually_recorded_by_staff:phone",
        recorded_by_user_id=user.id,
        recorded_by_user_email=user.email,
        channel="sms",
        categories_affected=cats,
        reason_note="Customer asked",
    )


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cats=st.lists(st.sampled_from(CATEGORIES), min_size=1, max_size=4, unique=True))
@pytest.mark.asyncio
async def test_revocation_idempotent(cats):
    org_id = uuid.uuid4()
    # Target categories start enabled.
    config = {c: {"enabled": c in cats, "channel": "sms", "days_before": 30} for c in CATEGORIES}
    customer = _make_customer(org_id, {"reminder_config": config})
    db = _make_db(customer)
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "staff@example.com"
    audit_calls: list[dict] = []

    with patch("app.modules.customers.consent.flag_modified", lambda *a, **k: None), patch(
        "app.modules.customers.service.flag_modified", lambda *a, **k: None
    ), patch(
        "app.modules.customers.consent.write_audit_log",
        new=AsyncMock(side_effect=lambda *a, **k: audit_calls.append(k)),
    ):
        # First revocation — flips the affected categories off + 1 audit + 1 row.
        await revoke_customer_reminders(
            db, org_id=org_id, customer_id=customer.id, current_user=user, record=_record(user, cats)
        )
        for c in cats:
            assert customer.custom_fields["reminder_config"][c]["enabled"] is False
        assert len(customer.custom_fields["reminder_consent_revocations"]) == 1
        assert len(audit_calls) == 1

        # Second revocation of the now-disabled entries — no-op (CP-5).
        await revoke_customer_reminders(
            db, org_id=org_id, customer_id=customer.id, current_user=user, record=_record(user, cats)
        )
        assert len(customer.custom_fields["reminder_consent_revocations"]) == 1
        assert len(audit_calls) == 1
