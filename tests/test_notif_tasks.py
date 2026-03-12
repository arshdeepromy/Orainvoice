"""Unit tests for notification dispatch tasks.

Tests the async functions in ``app/tasks/notifications.py``:
- send_email_task
- send_sms_task
- _get_retry_delay
- Constants: MAX_RETRIES, RETRY_DELAYS

Requirements: 37.1, 37.2, 37.3
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.notifications import (
    MAX_RETRIES,
    RETRY_DELAYS,
    _get_retry_delay,
    send_email_task,
    send_sms_task,
)

ORG_ID = str(uuid.uuid4())
LOG_ID = str(uuid.uuid4())


class TestGetRetryDelay:
    def test_first_retry_60s(self):
        assert _get_retry_delay(0) == 60

    def test_second_retry_300s(self):
        assert _get_retry_delay(1) == 300

    def test_third_retry_900s(self):
        assert _get_retry_delay(2) == 900

    def test_beyond_max_uses_last(self):
        assert _get_retry_delay(5) == 900

    def test_delays_match_spec(self):
        assert RETRY_DELAYS == (60, 300, 900)

    def test_max_retries_is_three(self):
        assert MAX_RETRIES == 3


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
    """Verify task functions are callable and constants are correct."""

    def test_email_task_callable(self):
        assert callable(send_email_task)

    def test_sms_task_callable(self):
        assert callable(send_sms_task)

    def test_max_retries_value(self):
        assert MAX_RETRIES == 3

    def test_retry_delays_tuple(self):
        assert RETRY_DELAYS == (60, 300, 900)
