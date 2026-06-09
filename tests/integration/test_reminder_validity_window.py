"""Integration tests for the reminder validity-window gate (D1 + D2).

Feature: customer-reminder-consent

Drives the real ``enqueue_customer_reminders`` with a discriminating
``db.execute`` mock (routing per selected ORM entity) plus patched
collaborators (``resolve_template``, ``_insert_queue_item``). Covers:
  * past/expired date (<= today in org tz) → suppressed + debug log (Req 4.1, 4.4)
  * future date == today + days_before → enqueued (Req 4.7)
  * ``_today_in_org_tz`` valid + invalid-fallback (D2)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the full app so every ORM mapper is configured — the enqueue loop
# builds multi-entity selects whose ``column_descriptions`` require all
# related mappers (Customer → Branch → …) to be resolvable.
import app.main  # noqa: F401

from app.modules.notifications.reminder_queue_service import (
    _today_in_org_tz,
    enqueue_customer_reminders,
)

_LOGGER_NAME = "app.modules.notifications.reminder_queue_service"


# --------------------------------------------------------------------------
# D2 — _today_in_org_tz
# --------------------------------------------------------------------------


def test_today_in_org_tz_valid():
    assert _today_in_org_tz("UTC") == datetime.now(timezone.utc).date()


def test_today_in_org_tz_invalid_falls_back():
    # Must not raise; returns a date (Pacific/Auckland fallback).
    assert isinstance(_today_in_org_tz("Not/AZone"), date)


# --------------------------------------------------------------------------
# Discriminating db mock for the enqueue loop
# --------------------------------------------------------------------------


def _result(*, scalar=None, scalars_all=None, scalars_first="__unset__", all_rows=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar)
    sc = MagicMock()
    sc.all = MagicMock(return_value=list(scalars_all or []))
    if scalars_first != "__unset__":
        sc.first = MagicMock(return_value=scalars_first)
    r.scalars = MagicMock(return_value=sc)
    r.all = MagicMock(return_value=list(all_rows or []))
    return r


def _build_db(customer, org, vehicle_rows):
    email_provider = MagicMock()  # truthy → email_configured

    def _execute(stmt, *a, **k):
        try:
            descs = list(stmt.column_descriptions)
        except Exception:
            descs = []
        if not descs:
            # text() country-code query.
            return _result(scalar="NZ")
        names = [
            (d.get("entity").__name__ if d.get("entity") else None) for d in descs
        ]
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
        "reminder_config": {
            "wof_expiry": {"enabled": True, "days_before": 30, "channel": "email"}
        }
    }
    return c


def _org(org_id, tz="UTC"):
    o = MagicMock()
    o.id = org_id
    o.name = "Acme Motors"
    o.settings = {}
    o.plan_id = None  # skips the SubscriptionPlan query
    o.timezone = tz
    return o


def _vehicle(wof_expiry):
    v = MagicMock()
    v.rego = "ABC123"
    v.year = 2020
    v.make = "Toyota"
    v.model = "Hilux"
    v.wof_expiry = wof_expiry
    return v


def _cv():
    cv = MagicMock()
    cv.id = uuid.uuid4()
    return cv


@pytest.mark.asyncio
async def test_expired_date_is_suppressed_with_debug_log(caplog):
    org_id = uuid.uuid4()
    customer = _customer(org_id)
    org = _org(org_id, tz="UTC")
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    vehicle_rows = [(_cv(), _vehicle(yesterday))]
    db = _build_db(customer, org, vehicle_rows)

    with patch(
        "app.modules.notifications.reminder_queue_service._insert_queue_item",
        new_callable=AsyncMock,
    ) as mock_insert, patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ), caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
        stats = await enqueue_customer_reminders(db)

    mock_insert.assert_not_awaited()
    assert stats["reminders_enqueued"] == 0
    assert any(
        "on or before today" in rec.getMessage() for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_future_target_date_is_enqueued():
    org_id = uuid.uuid4()
    customer = _customer(org_id)
    org = _org(org_id, tz="UTC")
    target = datetime.now(timezone.utc).date() + timedelta(days=30)  # == days_before
    vehicle_rows = [(_cv(), _vehicle(target))]
    db = _build_db(customer, org, vehicle_rows)

    with patch(
        "app.modules.notifications.reminder_queue_service._insert_queue_item",
        new_callable=AsyncMock,
    ) as mock_insert, patch(
        "app.modules.notifications.service.resolve_template",
        new_callable=AsyncMock,
        return_value=None,
    ):
        stats = await enqueue_customer_reminders(db)

    mock_insert.assert_awaited_once()
    assert stats["reminders_enqueued"] == 1
