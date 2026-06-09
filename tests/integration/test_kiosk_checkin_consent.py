"""Integration tests for kiosk check-in consent co-persistence (C3).

Feature: customer-reminder-consent

Mirrors the mock-based setup of ``tests/test_kiosk_checkin_v2_integration.py``.
Covers:
  * happy-path: ``consent_provided()`` True → ``update_customer_reminder_config``
    is called once with the derived per-category config + a kiosk consent
    record (source ``kiosk_self_checkin``, ip/user-agent threaded through).
  * master-unchecked (Req 1.12): no consent block → the config function is
    NEVER called; the existing check-in path is untouched.
  * failure bubbling (Req 1.16): when the config write raises, the exception
    propagates so the surrounding ``session.begin()`` rolls back the check-in.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Configure ORM mappers.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.kiosk.schemas import KioskCheckInRequestV2
from app.modules.kiosk.service import kiosk_check_in_v2


def _make_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _request(*, with_consent: bool, empty_entries: bool = False) -> KioskCheckInRequestV2:
    body = {
        "first_name": "Alice",
        "last_name": "Wonder",
        "phone": "0279876543",
        "email": "alice@example.com",
        "vehicles": [],
        "existing_customer_id": None,
    }
    if with_consent:
        body["reminder_consent"] = {
            "consent_text_version": "2026-06-08-v1",
            "entries": []
            if empty_entries
            else [
                {"vehicle_id": str(uuid.uuid4()), "category": "wof_expiry", "channel": "sms"},
                {"vehicle_id": str(uuid.uuid4()), "category": "service_due", "channel": "email"},
            ],
        }
    return KioskCheckInRequestV2.model_validate(body)


_CUSTOMER_DICT = {
    "id": str(uuid.uuid4()),
    "first_name": "Alice",
    "last_name": "Wonder",
    "phone": "0279876543",
}


@pytest.mark.asyncio
async def test_consent_provided_copersists_derived_config_and_record():
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(None))
    db.flush = AsyncMock()
    db.add = MagicMock()

    with patch(
        "app.modules.customers.service.create_customer",
        new_callable=AsyncMock,
        return_value=_CUSTOMER_DICT,
    ), patch(
        "app.modules.customers.service.update_customer_reminder_config",
        new_callable=AsyncMock,
    ) as mock_update:
        await kiosk_check_in_v2(
            db,
            org_id=org_id,
            user_id=user_id,
            data=_request(with_consent=True),
            ip_address="10.0.0.1",
            user_agent="KioskTablet/1.0",
        )

    mock_update.assert_awaited_once()
    kwargs = mock_update.await_args.kwargs
    reminders = kwargs["reminders"]
    assert reminders["wof_expiry"] == {"enabled": True, "channel": "sms", "days_before": 30}
    assert reminders["service_due"]["enabled"] is True
    assert reminders["service_due"]["channel"] == "email"

    record = kwargs["consent_record"]
    assert record.source == "kiosk_self_checkin"
    assert record.consent_text_version == "2026-06-08-v1"
    assert record.ip_address == "10.0.0.1"
    assert record.user_agent == "KioskTablet/1.0"
    assert record.kiosk_session_id is not None
    # The kiosk consent record never carries staff-only attribution.
    assert record.recorded_by_user_id is None


@pytest.mark.asyncio
async def test_master_unchecked_writes_no_consent(monkeypatch=None):
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(None))
    db.flush = AsyncMock()
    db.add = MagicMock()

    with patch(
        "app.modules.customers.service.create_customer",
        new_callable=AsyncMock,
        return_value=_CUSTOMER_DICT,
    ), patch(
        "app.modules.customers.service.update_customer_reminder_config",
        new_callable=AsyncMock,
    ) as mock_update:
        # No consent block at all.
        await kiosk_check_in_v2(
            db, org_id=org_id, user_id=user_id,
            data=_request(with_consent=False), ip_address="10.0.0.1",
        )
        # Master toggle on but zero entries → still a no-op (Req 1.12).
        await kiosk_check_in_v2(
            db, org_id=org_id, user_id=user_id,
            data=_request(with_consent=True, empty_entries=True),
            ip_address="10.0.0.1",
        )

    mock_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_config_write_failure_bubbles_for_rollback():
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(None))
    db.flush = AsyncMock()
    db.add = MagicMock()

    with patch(
        "app.modules.customers.service.create_customer",
        new_callable=AsyncMock,
        return_value=_CUSTOMER_DICT,
    ), patch(
        "app.modules.customers.service.update_customer_reminder_config",
        new_callable=AsyncMock,
        side_effect=RuntimeError("audit insert failed"),
    ):
        with pytest.raises(RuntimeError, match="audit insert failed"):
            await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=_request(with_consent=True),
                ip_address="10.0.0.1",
                user_agent="KioskTablet/1.0",
            )
