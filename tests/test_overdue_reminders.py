"""Unit tests for Task 15.6 -- Automated overdue payment reminders.

Requirements: 38.1, 38.2, 38.3, 38.4
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.notifications.schemas import (
    OverdueReminderRuleCreate,
    OverdueReminderRuleListResponse,
    OverdueReminderRuleResponse,
    OverdueReminderRuleUpdate,
)
from app.modules.notifications.service import (
    MAX_OVERDUE_RULES_PER_ORG,
    _rule_to_dict,
    create_reminder_rule,
    delete_reminder_rule,
    list_reminder_rules,
    update_reminder_rule,
    process_overdue_reminders,
)

ORG_ID = uuid.uuid4()
RULE_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestOverdueReminderRuleSchemas:
    """Test Pydantic schema validation for overdue reminder rules."""

    def test_create_schema_defaults(self):
        """send_email defaults True, send_sms defaults False, is_enabled defaults True."""
        schema = OverdueReminderRuleCreate(days_after_due=7)
        assert schema.days_after_due == 7
        assert schema.send_email is True
        assert schema.send_sms is False
        assert schema.is_enabled is True

    def test_create_schema_custom_values(self):
        schema = OverdueReminderRuleCreate(
            days_after_due=14, send_email=False, send_sms=True, is_enabled=False
        )
        assert schema.days_after_due == 14
        assert schema.send_email is False
        assert schema.send_sms is True
        assert schema.is_enabled is False

    def test_create_schema_min_days(self):
        schema = OverdueReminderRuleCreate(days_after_due=1)
        assert schema.days_after_due == 1

    def test_create_schema_max_days(self):
        schema = OverdueReminderRuleCreate(days_after_due=365)
        assert schema.days_after_due == 365

    def test_create_schema_rejects_zero_days(self):
        with pytest.raises(Exception):
            OverdueReminderRuleCreate(days_after_due=0)

    def test_create_schema_rejects_negative_days(self):
        with pytest.raises(Exception):
            OverdueReminderRuleCreate(days_after_due=-1)

    def test_create_schema_rejects_over_365_days(self):
        with pytest.raises(Exception):
            OverdueReminderRuleCreate(days_after_due=366)

    def test_update_schema_all_optional(self):
        schema = OverdueReminderRuleUpdate()
        assert schema.days_after_due is None
        assert schema.send_email is None
        assert schema.send_sms is None
        assert schema.is_enabled is None

    def test_update_schema_partial(self):
        schema = OverdueReminderRuleUpdate(send_sms=True)
        assert schema.send_sms is True
        assert schema.days_after_due is None

    def test_response_schema(self):
        resp = OverdueReminderRuleResponse(
            id=str(RULE_ID),
            org_id=str(ORG_ID),
            days_after_due=7,
            send_email=True,
            send_sms=False,
            sort_order=0,
            is_enabled=True,
        )
        assert resp.id == str(RULE_ID)
        assert resp.days_after_due == 7

    def test_list_response_schema(self):
        resp = OverdueReminderRuleListResponse(
            rules=[], total=0, reminders_enabled=False
        )
        assert resp.rules == []
        assert resp.reminders_enabled is False


# ---------------------------------------------------------------------------
# Service layer tests (with mocked DB)
# ---------------------------------------------------------------------------


def _make_mock_rule(
    rule_id=None, org_id=None, days=7, email=True, sms=False, enabled=True, order=0
):
    """Create a mock OverdueReminderRule-like object."""
    rule = MagicMock()
    rule.id = rule_id or uuid.uuid4()
    rule.org_id = org_id or ORG_ID
    rule.days_after_due = days
    rule.send_email = email
    rule.send_sms = sms
    rule.sort_order = order
    rule.is_enabled = enabled
    return rule


class TestRuleToDict:
    """Test the _rule_to_dict helper."""

    def test_converts_rule_to_dict(self):
        rule = _make_mock_rule(rule_id=RULE_ID, org_id=ORG_ID)
        result = _rule_to_dict(rule)
        assert result["id"] == str(RULE_ID)
        assert result["org_id"] == str(ORG_ID)
        assert result["days_after_due"] == 7
        assert result["send_email"] is True
        assert result["send_sms"] is False
        assert result["sort_order"] == 0
        assert result["is_enabled"] is True


class TestMaxRulesConstant:
    """Verify the max rules per org constant."""

    def test_max_rules_is_three(self):
        """Req 38.1: up to 3 rules per org."""
        assert MAX_OVERDUE_RULES_PER_ORG == 3


# ---------------------------------------------------------------------------
# Celery Beat task tests
# ---------------------------------------------------------------------------


class TestProcessOverdueRemindersTask:
    """Test the Celery Beat task wrapper."""

    def test_task_registered(self):
        from app.tasks.notifications import process_overdue_reminders_task
        assert process_overdue_reminders_task.name == (
            "app.tasks.notifications.process_overdue_reminders_task"
        )

    def test_task_success(self):
        from app.tasks.notifications import process_overdue_reminders_task
        mock_result = {"orgs_processed": 2, "reminders_sent": 5, "errors": 0}
        with patch(
            "app.tasks.notifications._run_async", return_value=mock_result
        ):
            result = process_overdue_reminders_task()
        assert result["orgs_processed"] == 2
        assert result["reminders_sent"] == 5

    def test_task_handles_exception(self):
        from app.tasks.notifications import process_overdue_reminders_task
        with patch(
            "app.tasks.notifications._run_async",
            side_effect=RuntimeError("DB connection failed"),
        ):
            result = process_overdue_reminders_task()
        assert "error" in result
        assert "DB connection failed" in result["error"]


# ---------------------------------------------------------------------------
# Celery Beat schedule configuration test
# ---------------------------------------------------------------------------


class TestCeleryBeatSchedule:
    """Verify the Celery Beat schedule includes overdue reminders."""

    def test_beat_schedule_includes_overdue_reminders(self):
        from app.tasks import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "process-overdue-reminders" in schedule
        entry = schedule["process-overdue-reminders"]
        assert entry["task"] == "app.tasks.notifications.process_overdue_reminders_task"
        assert entry["schedule"] == 300.0  # Every 5 minutes


# ---------------------------------------------------------------------------
# Integration-style tests for create/list/update/delete (mocked DB)
# ---------------------------------------------------------------------------


class TestCreateReminderRuleValidation:
    """Test create_reminder_rule business logic with mocked DB."""

    @pytest.mark.asyncio
    async def test_rejects_when_max_rules_reached(self):
        """Req 38.1: max 3 rules per org."""
        db = AsyncMock()
        # Mock count query returning 3
        count_result = MagicMock()
        count_result.scalar.return_value = 3
        db.execute = AsyncMock(return_value=count_result)

        result = await create_reminder_rule(
            db, org_id=ORG_ID, days_after_due=7
        )
        assert isinstance(result, str)
        assert "Maximum" in result

    @pytest.mark.asyncio
    async def test_rejects_duplicate_days(self):
        """Req 38.1: unique days_after_due per org."""
        db = AsyncMock()
        # First call: count returns 1 (under limit)
        count_result = MagicMock()
        count_result.scalar.return_value = 1
        # Second call: duplicate check returns existing rule
        dup_result = MagicMock()
        dup_result.scalar_one_or_none.return_value = _make_mock_rule(days=7)

        db.execute = AsyncMock(side_effect=[count_result, dup_result])

        result = await create_reminder_rule(
            db, org_id=ORG_ID, days_after_due=7
        )
        assert isinstance(result, str)
        assert "already exists" in result
