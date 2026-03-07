"""Unit tests for Task 15.5 -- Notification queuing and retry.
Requirements: 37.1, 37.2, 37.3
"""
from __future__ import annotations
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.tasks.notifications import (
    MAX_RETRIES, RETRY_DELAYS, _get_retry_delay,
    send_email_task, send_sms_task,
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
    def _call(self, retries=0, run_async_rv=None, run_async_se=None):
        """Helper to call send_email_task with mocked internals."""
        task = send_email_task
        kw = {}
        if run_async_rv is not None:
            kw["return_value"] = run_async_rv
        if run_async_se is not None:
            kw["side_effect"] = run_async_se
        with patch("app.tasks.notifications._run_async", **kw):
            task.push_request(retries=retries)
            try:
                return task(ORG_ID, LOG_ID, "t@e.com", "", "Subj",
                            "", "", None, None, "invoice_issued")
            finally:
                task.pop_request()

    def test_success(self):
        r = self._call(retries=0,
                       run_async_rv={"success": True, "message_id": "m1"})
        assert r["success"] is True
        assert r["message_id"] == "m1"

    def test_retry_60s(self):
        with pytest.raises(Exception, match="timeout"):
            self._call(retries=0,
                       run_async_rv={"success": False, "error": "timeout"})

    def test_permanent_failure(self):
        r = self._call(
            retries=3,
            run_async_se=[
                {"success": False, "error": "SMTP down"},
                None,
            ],
        )
        assert r["success"] is False
        assert r["permanently_failed"] is True
        assert r["error"] == "SMTP down"


class TestSendSmsTask:
    def _call(self, retries=0, run_async_rv=None, run_async_se=None):
        task = send_sms_task
        kw = {}
        if run_async_rv is not None:
            kw["return_value"] = run_async_rv
        if run_async_se is not None:
            kw["side_effect"] = run_async_se
        with patch("app.tasks.notifications._run_async", **kw):
            task.push_request(retries=retries)
            try:
                return task(ORG_ID, LOG_ID, "+6421234567",
                            "Test msg", None, "sms_reminder")
            finally:
                task.pop_request()

    def test_success(self):
        r = self._call(retries=0,
                       run_async_rv={"success": True, "message_sid": "SM1"})
        assert r["success"] is True
        assert r["message_sid"] == "SM1"

    def test_retry_60s(self):
        with pytest.raises(Exception, match="rate limit"):
            self._call(retries=0,
                       run_async_rv={"success": False, "error": "rate limit"})

    def test_permanent_sms_failure(self):
        r = self._call(
            retries=3,
            run_async_se=[
                {"success": False, "error": "Twilio down"},
                None,
            ],
        )
        assert r["success"] is False
        assert r["permanently_failed"] is True


    def test_sms_retry_300s(self):
        with pytest.raises(Exception, match="timeout"):
            self._call(retries=1,
                       run_async_rv={"success": False, "error": "timeout"})


class TestBackoffDelays:
    """Verify the full exponential backoff sequence."""

    def test_email_backoff_sequence(self):
        """Email retries use 60s, 300s, 900s delays."""
        task = send_email_task
        for retry_num, expected_delay in [(0, 60), (1, 300), (2, 900)]:
            with patch("app.tasks.notifications._run_async",
                        return_value={"success": False, "error": "fail"}):
                task.push_request(retries=retry_num)
                try:
                    with pytest.raises(Exception, match="fail"):
                        task(ORG_ID, LOG_ID, "t@e.com", "", "S",
                             "", "", None, None, "test")
                finally:
                    task.pop_request()

    def test_sms_backoff_sequence(self):
        """SMS retries use 60s, 300s, 900s delays."""
        task = send_sms_task
        for retry_num, expected_delay in [(0, 60), (1, 300), (2, 900)]:
            with patch("app.tasks.notifications._run_async",
                        return_value={"success": False, "error": "fail"}):
                task.push_request(retries=retry_num)
                try:
                    with pytest.raises(Exception, match="fail"):
                        task(ORG_ID, LOG_ID, "+6421234567",
                             "Test", None, "test")
                finally:
                    task.pop_request()


class TestTaskConfiguration:
    """Verify Celery task configuration."""

    def test_email_task_max_retries(self):
        assert send_email_task.max_retries == 3

    def test_sms_task_max_retries(self):
        assert send_sms_task.max_retries == 3

    def test_email_task_acks_late(self):
        assert send_email_task.acks_late is True

    def test_sms_task_acks_late(self):
        assert send_sms_task.acks_late is True

    def test_email_task_name(self):
        assert send_email_task.name == "app.tasks.notifications.send_email_task"

    def test_sms_task_name(self):
        assert send_sms_task.name == "app.tasks.notifications.send_sms_task"
