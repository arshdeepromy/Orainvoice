"""Unit tests for notification dispatch tasks.

Tests the async functions in ``app/tasks/notifications.py``:
- send_email_task
- send_sms_task

Requirements: 37.1
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.notifications import (
    send_email_task,
    send_sms_task,
)

ORG_ID = str(uuid.uuid4())
LOG_ID = str(uuid.uuid4())


class TestSendEmailTask:
    """Test send_email_task async function."""

    @pytest.mark.asyncio
    async def test_success(self):
        with patch(
            "app.tasks.notifications._send_email_async",
            new_callable=AsyncMock,
            return_value={"success": True, "message_id": "m1"},
        ):
            result = await send_email_task(
                ORG_ID, LOG_ID, "t@e.com", "", "Subj",
                "", "", None, None, "invoice_issued",
            )
            assert result["success"] is True
            assert result["message_id"] == "m1"

    @pytest.mark.asyncio
    async def test_failure_marks_permanently_failed(self):
        with patch(
            "app.tasks.notifications._send_email_async",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "SMTP down"},
        ):
            with patch(
                "app.tasks.notifications._mark_permanently_failed",
                new_callable=AsyncMock,
            ) as mock_mark:
                result = await send_email_task(
                    ORG_ID, LOG_ID, "t@e.com", "", "Subj",
                    "", "", None, None, "invoice_issued",
                )
                assert result["success"] is False
                assert result["permanently_failed"] is True
                assert result["error"] == "SMTP down"
                mock_mark.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch(
            "app.tasks.notifications._send_email_async",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection reset"),
        ):
            result = await send_email_task(
                ORG_ID, LOG_ID, "t@e.com", "", "Subj",
                "", "", None, None, "test",
            )
            assert result["success"] is False
            assert "Connection reset" in result["error"]


class TestSendSmsTask:
    """Test send_sms_task async function."""

    @pytest.mark.asyncio
    async def test_success(self):
        with patch(
            "app.tasks.notifications._send_sms_async",
            new_callable=AsyncMock,
            return_value={"success": True, "message_sid": "SM1"},
        ):
            result = await send_sms_task(
                ORG_ID, LOG_ID, "+6421234567", "Test msg", None, "sms_reminder",
            )
            assert result["success"] is True
            assert result["message_sid"] == "SM1"

    @pytest.mark.asyncio
    async def test_failure_marks_permanently_failed(self):
        with patch(
            "app.tasks.notifications._send_sms_async",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "Twilio down"},
        ):
            with patch(
                "app.tasks.notifications._mark_permanently_failed",
                new_callable=AsyncMock,
            ) as mock_mark:
                result = await send_sms_task(
                    ORG_ID, LOG_ID, "+6421234567", "Test msg", None, "sms_reminder",
                )
                assert result["success"] is False
                assert result["permanently_failed"] is True
                mock_mark.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_returns_error(self):
        with patch(
            "app.tasks.notifications._send_sms_async",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Network error"),
        ):
            result = await send_sms_task(
                ORG_ID, LOG_ID, "+6421234567", "Test msg", None, "test",
            )
            assert result["success"] is False
            assert "Network error" in result["error"]


class TestTaskConfiguration:
    """Verify task functions are callable."""

    def test_email_task_callable(self):
        assert callable(send_email_task)

    def test_sms_task_callable(self):
        assert callable(send_sms_task)
