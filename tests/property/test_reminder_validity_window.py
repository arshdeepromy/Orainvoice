"""Property test — validity-window auto-suppression (CP-6).

Feature: customer-reminder-consent, Property 6 (CP-6): Validity-window
auto-suppression — for any expiry date, a reminder is suppressed when the date
is on or before today in the org timezone, and enqueued only on the exact
target day (today + days_before). The gate is read-time only: it never writes
reminder_config, never appends revocations, and never writes an audit row.

Validates: Requirements 4.1, 4.2, 4.3, 4.7.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

# Full app import so all ORM mappers (Customer -> Branch -> …) resolve for the
# multi-entity selects' column_descriptions inside the enqueue loop.
import app.main  # noqa: F401

from app.modules.notifications.reminder_queue_service import enqueue_customer_reminders


def _result(*, scalar=None, scalars_all=None, scalars_first="__u", all_rows=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar)
    sc = MagicMock()
    sc.all = MagicMock(return_value=list(scalars_all or []))
    if scalars_first != "__u":
        sc.first = MagicMock(return_value=scalars_first)
    r.scalars = MagicMock(return_value=sc)
    r.all = MagicMock(return_value=list(all_rows or []))
    return r


def _build(customer, org, vehicle_rows):
    email_provider = MagicMock()

    def _execute(stmt, *a, **k):
        try:
            descs = list(stmt.column_descriptions)
        except Exception:
            descs = []
        if not descs:
            return _result(scalar="NZ")
        names = [(d.get("entity").__name__ if d.get("entity") else None) for d in descs]
        first = names[0]
        if first == "Customer":
            return _result(scalars_all=[customer])
        if first == "Organisation":
            return _result(scalar=org)
        if first == "SmsVerificationProvider":
            return _result(scalars_first=None)
        if first == "EmailProvider":
            return _result(scalars_first=email_provider)
        if first == "CustomerVehicle":
            second = names[1] if len(names) > 1 else None
            return _result(all_rows=vehicle_rows if second == "GlobalVehicle" else [])
        return _result()

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    db.flush = AsyncMock()
    return db


def _customer(org_id):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.first_name = "Jo"
    c.last_name = "Driver"
    c.email = "jo@example.com"
    c.is_anonymised = False
    c.custom_fields = {
        "reminder_config": {"wof_expiry": {"enabled": True, "days_before": 30, "channel": "email"}}
    }
    return c


def _org(org_id):
    o = MagicMock()
    o.id = org_id
    o.name = "Acme"
    o.settings = {}
    o.plan_id = None
    o.timezone = "UTC"
    return o


def _veh(wof_expiry):
    v = MagicMock()
    v.rego = "ABC"
    v.year = 2020
    v.make = "T"
    v.model = "H"
    v.wof_expiry = wof_expiry
    return v


def _cv():
    cv = MagicMock()
    cv.id = uuid.uuid4()
    return cv


# offset_days: expiry = today + offset_days. days_before fixed at 30.
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(offset_days=st.integers(min_value=-60, max_value=120))
@pytest.mark.asyncio
async def test_validity_window(offset_days):
    org_id = uuid.uuid4()
    customer = _customer(org_id)
    org = _org(org_id)
    today = datetime.now(timezone.utc).date()
    expiry = today + timedelta(days=offset_days)
    db = _build(customer, org, [(_cv(), _veh(expiry))])

    with patch(
        "app.modules.notifications.reminder_queue_service._insert_queue_item",
        new_callable=AsyncMock,
    ) as mock_insert, patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ):
        snapshot = dict(customer.custom_fields)
        stats = await enqueue_customer_reminders(db)

    # days_before = 30 → enqueue only when expiry == today + 30 (and > today).
    if offset_days == 30:
        assert mock_insert.await_count == 1
        assert stats["reminders_enqueued"] == 1
    else:
        # Past/today (<= today) OR any non-target future day → suppressed.
        assert mock_insert.await_count == 0
        assert stats["reminders_enqueued"] == 0

    # Read-time only: config untouched, no revocations appended.
    assert customer.custom_fields == snapshot
    assert "reminder_consent_revocations" not in customer.custom_fields
