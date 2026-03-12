"""Unit tests for Task 15.7 -- WOF and registration expiry reminders.

Requirements: 39.1, 39.2, 39.3, 39.4
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.modules.notifications.schemas import (
    WofRegoReminderSettingsRequest,
    WofRegoReminderSettingsResponse,
)
from app.modules.notifications.service import (
    DEFAULT_WOF_REGO_DAYS_IN_ADVANCE,
    WOF_REGO_NOTIFICATION_TYPE,
    get_wof_rego_settings,
    update_wof_rego_settings,
    process_wof_rego_reminders,
)

ORG_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestWofRegoReminderSchemas:
    """Test Pydantic schema validation for WOF/rego reminder settings."""

    def test_request_all_none_defaults(self):
        """All fields optional — empty body is valid."""
        schema = WofRegoReminderSettingsRequest()
        assert schema.enabled is None
        assert schema.days_in_advance is None
        assert schema.channel is None

    def test_request_enable_with_defaults(self):
        schema = WofRegoReminderSettingsRequest(enabled=True)
        assert schema.enabled is True
        assert schema.days_in_advance is None

    def test_request_custom_days(self):
        schema = WofRegoReminderSettingsRequest(days_in_advance=14)
        assert schema.days_in_advance == 14

    def test_request_channel_email(self):
        schema = WofRegoReminderSettingsRequest(channel="email")
        assert schema.channel == "email"

    def test_request_channel_sms(self):
        schema = WofRegoReminderSettingsRequest(channel="sms")
        assert schema.channel == "sms"

    def test_request_channel_both(self):
        schema = WofRegoReminderSettingsRequest(channel="both")
        assert schema.channel == "both"

    def test_request_rejects_invalid_channel(self):
        with pytest.raises(Exception):
            WofRegoReminderSettingsRequest(channel="push")

    def test_request_rejects_zero_days(self):
        with pytest.raises(Exception):
            WofRegoReminderSettingsRequest(days_in_advance=0)

    def test_request_rejects_negative_days(self):
        with pytest.raises(Exception):
            WofRegoReminderSettingsRequest(days_in_advance=-1)

    def test_request_rejects_over_365_days(self):
        with pytest.raises(Exception):
            WofRegoReminderSettingsRequest(days_in_advance=366)

    def test_response_defaults(self):
        resp = WofRegoReminderSettingsResponse(
            enabled=False, days_in_advance=30, channel="email"
        )
        assert resp.enabled is False
        assert resp.days_in_advance == 30
        assert resp.channel == "email"

    def test_response_enabled_with_both(self):
        resp = WofRegoReminderSettingsResponse(
            enabled=True, days_in_advance=14, channel="both"
        )
        assert resp.enabled is True
        assert resp.days_in_advance == 14
        assert resp.channel == "both"


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestWofRegoConstants:
    """Verify module-level constants."""

    def test_notification_type(self):
        assert WOF_REGO_NOTIFICATION_TYPE == "wof_rego_reminders"

    def test_default_days_in_advance(self):
        """Req 39.2: default 30 days."""
        assert DEFAULT_WOF_REGO_DAYS_IN_ADVANCE == 30


# ---------------------------------------------------------------------------
# Service layer tests — get_wof_rego_settings (mocked DB)
# ---------------------------------------------------------------------------


class TestGetWofRegoSettings:
    """Test get_wof_rego_settings with mocked DB."""

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_preference(self):
        """Req 39.1: disabled by default."""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        settings = await get_wof_rego_settings(db, org_id=ORG_ID)
        assert settings["enabled"] is False
        assert settings["days_in_advance"] == 30
        assert settings["channel"] == "email"

    @pytest.mark.asyncio
    async def test_returns_stored_preference(self):
        """Returns stored settings when preference exists."""
        db = AsyncMock()
        pref = MagicMock()
        pref.is_enabled = True
        pref.channel = "both"
        pref.config = {"days_in_advance": 14}

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = pref
        db.execute = AsyncMock(return_value=result_mock)

        settings = await get_wof_rego_settings(db, org_id=ORG_ID)
        assert settings["enabled"] is True
        assert settings["days_in_advance"] == 14
        assert settings["channel"] == "both"

    @pytest.mark.asyncio
    async def test_returns_default_days_when_config_empty(self):
        """Falls back to default 30 days when config has no days_in_advance."""
        db = AsyncMock()
        pref = MagicMock()
        pref.is_enabled = True
        pref.channel = "email"
        pref.config = {}

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = pref
        db.execute = AsyncMock(return_value=result_mock)

        settings = await get_wof_rego_settings(db, org_id=ORG_ID)
        assert settings["days_in_advance"] == 30


# ---------------------------------------------------------------------------
# Service layer tests — update_wof_rego_settings (mocked DB)
# ---------------------------------------------------------------------------


class TestUpdateWofRegoSettings:
    """Test update_wof_rego_settings with mocked DB."""

    @pytest.mark.asyncio
    async def test_creates_preference_when_none_exists(self):
        """Creates a new NotificationPreference row when none exists.

        We verify the function calls db.add() and returns correct settings.
        The actual ORM instantiation is tested via integration tests; here
        we verify the branch logic by checking that db.add is called and
        the returned dict reflects the requested values.
        """
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        # Capture what gets added to the session
        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)

        db.add = MagicMock(side_effect=capture_add)

        # After flush + refresh, the pref attributes are read back
        async def mock_refresh(obj):
            # The object was already constructed with the right values
            pass

        db.refresh = AsyncMock(side_effect=mock_refresh)

        settings = await update_wof_rego_settings(
            db,
            org_id=ORG_ID,
            enabled=True,
            days_in_advance=14,
            channel="both",
        )
        assert settings["enabled"] is True
        assert settings["days_in_advance"] == 14
        assert settings["channel"] == "both"
        assert len(added_objects) == 1
        pref = added_objects[0]
        assert pref.notification_type == WOF_REGO_NOTIFICATION_TYPE
        assert pref.is_enabled is True

    @pytest.mark.asyncio
    async def test_updates_existing_preference(self):
        """Updates an existing NotificationPreference row."""
        db = AsyncMock()
        pref = MagicMock()
        pref.is_enabled = False
        pref.channel = "email"
        pref.config = {"days_in_advance": 30}

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = pref
        db.execute = AsyncMock(return_value=result_mock)

        async def mock_refresh(obj):
            pass  # pref attributes already mutated in-place

        db.refresh = AsyncMock(side_effect=mock_refresh)

        settings = await update_wof_rego_settings(
            db,
            org_id=ORG_ID,
            enabled=True,
            channel="sms",
            days_in_advance=7,
        )
        assert pref.is_enabled is True
        assert pref.channel == "sms"
        assert pref.config["days_in_advance"] == 7


# ---------------------------------------------------------------------------
# Celery Beat task tests
# ---------------------------------------------------------------------------


class TestProcessWofRegoRemindersTask:
    """Test the Celery Beat task wrapper."""

    def test_task_registered(self):
        from app.tasks.notifications import process_wof_rego_reminders_task

        assert process_wof_rego_reminders_task.name == (
            "app.tasks.notifications.process_wof_rego_reminders_task"
        )

    def test_task_success(self):
        from app.tasks.notifications import process_wof_rego_reminders_task

        mock_result = {"orgs_processed": 1, "reminders_sent": 3, "errors": 0}
        with patch(
            "app.tasks.notifications._run_async", return_value=mock_result
        ):
            result = process_wof_rego_reminders_task()
        assert result["orgs_processed"] == 1
        assert result["reminders_sent"] == 3

    def test_task_handles_exception(self):
        from app.tasks.notifications import process_wof_rego_reminders_task

        with patch(
            "app.tasks.notifications._run_async",
            side_effect=RuntimeError("DB connection failed"),
        ):
            result = process_wof_rego_reminders_task()
        assert "error" in result
        assert "DB connection failed" in result["error"]


# ---------------------------------------------------------------------------
# Celery Beat schedule configuration test
# ---------------------------------------------------------------------------


class TestWofRegoBeatSchedule:
    """Verify the WOF/rego reminder task is importable."""

    def test_wof_rego_task_importable(self):
        from app.tasks.notifications import process_wof_rego_reminders_task
        assert callable(process_wof_rego_reminders_task)
