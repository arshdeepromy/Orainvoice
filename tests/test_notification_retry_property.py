"""Property-based tests for notification retry (Task 15.9).

Property 19: Notification Retry Bounded at Three
— verify max 4 total attempts (1 initial + 3 retries), then permanently failed.

**Validates: Requirements 37.2, 37.3**

Uses Hypothesis to generate random notification scenarios and verify:
  1. Total send attempts never exceed 4 (1 initial + 3 retries)
  2. After exhausting retries, the notification is marked as permanently failed
  3. Retry delays follow the exponential backoff pattern (60s, 300s, 900s)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch, call

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.tasks.notifications import (
    MAX_RETRIES,
    RETRY_DELAYS,
    _get_retry_delay,
    send_email_task,
    send_sms_task,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Channel type: email or sms
channel_strategy = st.sampled_from(["email", "sms"])

# Retry count: 0 to MAX_RETRIES (simulates which attempt we're on)
retry_count_strategy = st.integers(min_value=0, max_value=MAX_RETRIES)

# Arbitrary retry numbers including beyond max (for boundary testing)
any_retry_number_strategy = st.integers(min_value=0, max_value=20)

# Error messages that a provider might return
error_message_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

# Email addresses (simplified for property testing)
email_strategy = st.emails()

# Phone numbers (NZ format)
phone_strategy = st.from_regex(r"\+642\d{7,9}", fullmatch=True)

# Template types
template_type_strategy = st.sampled_from([
    "invoice_issued", "payment_receipt", "overdue_reminder",
    "wof_reminder", "sms_reminder", "unknown",
])


# ---------------------------------------------------------------------------
# Property 19: Notification Retry Bounded at Three
# ---------------------------------------------------------------------------


class TestNotificationRetryBoundedProperty:
    """Property 19: Notification Retry Bounded at Three.

    **Validates: Requirements 37.2, 37.3**
    """

    @given(retry_num=any_retry_number_strategy)
    @PBT_SETTINGS
    def test_retry_delay_follows_backoff_pattern(self, retry_num: int):
        """For any retry number, the delay matches the exponential backoff
        schedule (60s, 300s, 900s) or clamps to the last value.

        **Validates: Requirements 37.2**
        """
        delay = _get_retry_delay(retry_num)

        if retry_num < len(RETRY_DELAYS):
            assert delay == RETRY_DELAYS[retry_num], (
                f"Retry {retry_num} should have delay {RETRY_DELAYS[retry_num]}, "
                f"got {delay}"
            )
        else:
            # Beyond defined delays, should clamp to the last value
            assert delay == RETRY_DELAYS[-1], (
                f"Retry {retry_num} beyond schedule should clamp to "
                f"{RETRY_DELAYS[-1]}, got {delay}"
            )

    @given(retry_num=any_retry_number_strategy)
    @PBT_SETTINGS
    def test_retry_delay_is_always_positive(self, retry_num: int):
        """For any retry number, the delay is always a positive integer.

        **Validates: Requirements 37.2**
        """
        delay = _get_retry_delay(retry_num)
        assert isinstance(delay, int)
        assert delay > 0

    @given(retry_num=any_retry_number_strategy)
    @PBT_SETTINGS
    def test_retry_delays_are_monotonically_non_decreasing(self, retry_num: int):
        """For any consecutive retry numbers, delays never decrease.

        **Validates: Requirements 37.2**
        """
        if retry_num > 0:
            prev_delay = _get_retry_delay(retry_num - 1)
            curr_delay = _get_retry_delay(retry_num)
            assert curr_delay >= prev_delay, (
                f"Delay at retry {retry_num} ({curr_delay}) should be >= "
                f"delay at retry {retry_num - 1} ({prev_delay})"
            )

    @given(
        retry_count=st.integers(min_value=0, max_value=MAX_RETRIES - 1),
        error_msg=error_message_strategy,
    )
    @PBT_SETTINGS
    def test_email_retries_when_below_max(self, retry_count: int, error_msg: str):
        """For any email failure with retries remaining, the task raises
        to trigger a Celery retry (not permanently failed).

        Total attempts = retry_count + 1 (current) which is < MAX_RETRIES + 1 = 4.

        **Validates: Requirements 37.2**
        """
        org_id = str(uuid.uuid4())
        log_id = str(uuid.uuid4())

        with patch(
            "app.tasks.notifications._run_async",
            return_value={"success": False, "error": error_msg},
        ):
            send_email_task.push_request(retries=retry_count)
            try:
                with pytest.raises(Exception):
                    send_email_task(
                        org_id, log_id, "test@example.com", "Test",
                        "Subject", "<p>body</p>", "body", None, None,
                        "invoice_issued",
                    )
            finally:
                send_email_task.pop_request()

    @given(
        retry_count=st.integers(min_value=0, max_value=MAX_RETRIES - 1),
        error_msg=error_message_strategy,
    )
    @PBT_SETTINGS
    def test_sms_retries_when_below_max(self, retry_count: int, error_msg: str):
        """For any SMS failure with retries remaining, the task raises
        to trigger a Celery retry (not permanently failed).

        **Validates: Requirements 37.2**
        """
        org_id = str(uuid.uuid4())
        log_id = str(uuid.uuid4())

        with patch(
            "app.tasks.notifications._run_async",
            return_value={"success": False, "error": error_msg},
        ):
            send_sms_task.push_request(retries=retry_count)
            try:
                with pytest.raises(Exception):
                    send_sms_task(
                        org_id, log_id, "+64211234567",
                        "Test message", None, "sms_reminder",
                    )
            finally:
                send_sms_task.pop_request()

    @given(error_msg=error_message_strategy)
    @PBT_SETTINGS
    def test_email_permanently_fails_at_max_retries(self, error_msg: str):
        """For any email that has exhausted all retries (retry_count == MAX_RETRIES),
        the task marks it as permanently failed instead of retrying.

        Total attempts = MAX_RETRIES + 1 = 4 (1 initial + 3 retries).

        **Validates: Requirements 37.2, 37.3**
        """
        org_id = str(uuid.uuid4())
        log_id = str(uuid.uuid4())

        # First call returns failure, second call is _mark_permanently_failed
        with patch(
            "app.tasks.notifications._run_async",
            side_effect=[
                {"success": False, "error": error_msg},
                None,  # _mark_permanently_failed returns None
            ],
        ):
            send_email_task.push_request(retries=MAX_RETRIES)
            try:
                result = send_email_task(
                    org_id, log_id, "test@example.com", "Test",
                    "Subject", "<p>body</p>", "body", None, None,
                    "invoice_issued",
                )
            finally:
                send_email_task.pop_request()

        assert result["success"] is False
        assert result["permanently_failed"] is True

    @given(error_msg=error_message_strategy)
    @PBT_SETTINGS
    def test_sms_permanently_fails_at_max_retries(self, error_msg: str):
        """For any SMS that has exhausted all retries (retry_count == MAX_RETRIES),
        the task marks it as permanently failed instead of retrying.

        Total attempts = MAX_RETRIES + 1 = 4 (1 initial + 3 retries).

        **Validates: Requirements 37.2, 37.3**
        """
        org_id = str(uuid.uuid4())
        log_id = str(uuid.uuid4())

        with patch(
            "app.tasks.notifications._run_async",
            side_effect=[
                {"success": False, "error": error_msg},
                None,
            ],
        ):
            send_sms_task.push_request(retries=MAX_RETRIES)
            try:
                result = send_sms_task(
                    org_id, log_id, "+64211234567",
                    "Test message", None, "sms_reminder",
                )
            finally:
                send_sms_task.pop_request()

        assert result["success"] is False
        assert result["permanently_failed"] is True

    @given(channel=channel_strategy)
    @PBT_SETTINGS
    def test_max_retries_constant_is_three(self, channel: str):
        """For any channel, MAX_RETRIES is 3, meaning max 4 total attempts.

        **Validates: Requirements 37.2**
        """
        assert MAX_RETRIES == 3

        if channel == "email":
            assert send_email_task.max_retries == 3
        else:
            assert send_sms_task.max_retries == 3

    @given(channel=channel_strategy)
    @PBT_SETTINGS
    def test_total_attempts_never_exceed_four(self, channel: str):
        """For any channel, the total number of attempts is bounded:
        max_retries + 1 (initial) = 4.

        **Validates: Requirements 37.2**
        """
        if channel == "email":
            total_max_attempts = send_email_task.max_retries + 1
        else:
            total_max_attempts = send_sms_task.max_retries + 1

        assert total_max_attempts == 4, (
            f"Total max attempts for {channel} should be 4, got {total_max_attempts}"
        )

    @given(data=st.data())
    @PBT_SETTINGS
    def test_backoff_delays_match_spec_sequence(self, data):
        """The retry delay sequence is exactly (60, 300, 900) seconds
        for all three retry attempts.

        **Validates: Requirements 37.2**
        """
        assert len(RETRY_DELAYS) == MAX_RETRIES, (
            f"Should have {MAX_RETRIES} delay values, got {len(RETRY_DELAYS)}"
        )
        assert RETRY_DELAYS == (60, 300, 900), (
            f"Delays should be (60, 300, 900), got {RETRY_DELAYS}"
        )

        # Verify each retry index maps correctly
        for i in range(MAX_RETRIES):
            assert _get_retry_delay(i) == RETRY_DELAYS[i]
