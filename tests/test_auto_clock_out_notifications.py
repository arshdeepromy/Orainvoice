"""Unit tests for Task 3.2 — auto clock-out notification helpers.

Example-based (pytest) coverage of the two notification helpers added in Task
3.1 to ``app/tasks/scheduled.py``:

  - ``_notify_staff_auto_clock_out(session, *, entry, staff, end, channels)``
    — the staff notification that GATES the closure (REQ 4.1/4.2). Returns
    ``True`` only when a notification was actually dispatched over a contactable
    channel; ``False`` on a send failure or when the staff member has no
    contactable channel (so the caller defers the closure and retries).
  - ``_notify_manager_auto_clock_out(session, *, entry, staff, manager, end,
    channels)`` — best-effort manager notification (REQ 4.3/4.5). A send failure
    is logged and swallowed so it never propagates / reverts the closure.

Both helpers build their message from the shift's clock-in time and the auto
clock-out time (REQ 4.4).

The helpers use lazy imports of the senders inside the functions
(``from app.integrations.sms_sender import send_sms`` /
``from app.integrations.email_sender import EmailMessage, send_email``), so the
senders are patched at their SOURCE modules.

Requirements: 4.1, 4.2, 4.4, 4.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.tasks.scheduled import (
    _notify_manager_auto_clock_out,
    _notify_staff_auto_clock_out,
)

SMS_TARGET = "app.integrations.sms_sender.send_sms"
EMAIL_TARGET = "app.integrations.email_sender.send_email"


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _make_entry(*, clock_in_at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        clock_in_at=clock_in_at or _utc(2024, 1, 1, 8, 30),
    )


def _make_person(*, phone=None, email=None, first_name="Sam", name="Sam Smith"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        phone=phone,
        email=email,
        first_name=first_name,
        name=name,
    )


# Clock-in 08:30 -> "08:30"; auto clock-out 17:45 -> "17:45".
CLOCK_IN = _utc(2024, 1, 1, 8, 30)
END = _utc(2024, 1, 1, 17, 45)


# ---------------------------------------------------------------------------
# _notify_staff_auto_clock_out — dispatch gating (REQ 4.1/4.2)
# ---------------------------------------------------------------------------

class TestNotifyStaffDispatch:
    """The staff helper returns True only when a notification is dispatched."""

    @pytest.mark.asyncio
    async def test_returns_true_on_sms_dispatch(self):
        entry = _make_entry()
        staff = _make_person(phone="+64211234567")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["sms"],
            )
        assert result is True
        mock_sms.assert_awaited_once()
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_true_on_email_dispatch(self):
        entry = _make_entry()
        staff = _make_person(email="sam@example.com")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["email"],
            )
        assert result is True
        mock_email.assert_awaited_once()
        mock_sms.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_on_send_failure(self):
        """A send failure on the only channel yields False (deferral, REQ 4.2)."""
        entry = _make_entry()
        staff = _make_person(phone="+64211234567")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock, side_effect=RuntimeError("sms down")), \
             patch(EMAIL_TARGET, new_callable=AsyncMock):
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["sms"],
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_no_contactable_channel(self):
        """SMS channel configured but staff has no phone -> nothing dispatched."""
        entry = _make_entry()
        staff = _make_person(phone=None, email="sam@example.com")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            # Only the SMS channel is enabled, but there is no phone on file.
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["sms"],
            )
        assert result is False
        mock_sms.assert_not_awaited()
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_staff_is_none(self):
        entry = _make_entry()
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=None, end=END, channels=["sms", "email"],
            )
        assert result is False
        mock_sms.assert_not_awaited()
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_channel_matches_contact(self):
        """Email-only channel but staff has only a phone -> nothing dispatched."""
        entry = _make_entry()
        staff = _make_person(phone="+64211234567", email=None)
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["email"],
            )
        assert result is False
        mock_sms.assert_not_awaited()
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_true_when_one_of_two_channels_succeeds(self):
        """If SMS fails but email succeeds, a notification WAS dispatched -> True."""
        entry = _make_entry()
        staff = _make_person(phone="+64211234567", email="sam@example.com")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock, side_effect=RuntimeError("sms down")), \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            result = await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["sms", "email"],
            )
        assert result is True
        mock_email.assert_awaited_once()


# ---------------------------------------------------------------------------
# _notify_staff_auto_clock_out — message content (REQ 4.4)
# ---------------------------------------------------------------------------

class TestNotifyStaffMessageContent:
    """The message states both the clock-in time and the auto clock-out time."""

    @pytest.mark.asyncio
    async def test_sms_body_includes_both_times(self):
        entry = _make_entry(clock_in_at=CLOCK_IN)
        staff = _make_person(phone="+64211234567")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock):
            await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["sms"],
            )
        body = mock_sms.await_args.kwargs["body"]
        assert "08:30" in body  # clock-in time
        assert "17:45" in body  # auto clock-out time

    @pytest.mark.asyncio
    async def test_email_body_includes_both_times(self):
        entry = _make_entry(clock_in_at=CLOCK_IN)
        staff = _make_person(email="sam@example.com")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock), \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            await _notify_staff_auto_clock_out(
                session, entry=entry, staff=staff, end=END, channels=["email"],
            )
        message = mock_email.await_args.args[1]
        assert "08:30" in message.text_body
        assert "17:45" in message.text_body
        assert "08:30" in message.html_body
        assert "17:45" in message.html_body


# ---------------------------------------------------------------------------
# _notify_manager_auto_clock_out — best-effort (REQ 4.3/4.5)
# ---------------------------------------------------------------------------

class TestNotifyManagerBestEffort:
    """The manager helper never propagates a send failure."""

    @pytest.mark.asyncio
    async def test_sms_send_failure_does_not_propagate(self):
        entry = _make_entry()
        staff = _make_person()
        manager = _make_person(phone="+64217654321")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock, side_effect=RuntimeError("sms down")), \
             patch(EMAIL_TARGET, new_callable=AsyncMock):
            # Must not raise.
            result = await _notify_manager_auto_clock_out(
                session, entry=entry, staff=staff, manager=manager,
                end=END, channels=["sms"],
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_email_send_failure_does_not_propagate(self):
        entry = _make_entry()
        staff = _make_person()
        manager = _make_person(email="boss@example.com")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock), \
             patch(EMAIL_TARGET, new_callable=AsyncMock, side_effect=RuntimeError("email down")):
            result = await _notify_manager_auto_clock_out(
                session, entry=entry, staff=staff, manager=manager,
                end=END, channels=["email"],
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_manager_none_sends_nothing(self):
        entry = _make_entry()
        staff = _make_person()
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock) as mock_email:
            result = await _notify_manager_auto_clock_out(
                session, entry=entry, staff=staff, manager=None,
                end=END, channels=["sms", "email"],
            )
        assert result is None
        mock_sms.assert_not_awaited()
        mock_email.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_manager_sms_body_includes_both_times(self):
        entry = _make_entry(clock_in_at=CLOCK_IN)
        staff = _make_person(first_name="Sam")
        manager = _make_person(phone="+64217654321")
        session = AsyncMock()
        with patch(SMS_TARGET, new_callable=AsyncMock) as mock_sms, \
             patch(EMAIL_TARGET, new_callable=AsyncMock):
            await _notify_manager_auto_clock_out(
                session, entry=entry, staff=staff, manager=manager,
                end=END, channels=["sms"],
            )
        body = mock_sms.await_args.kwargs["body"]
        assert "08:30" in body  # clock-in time
        assert "17:45" in body  # auto clock-out time
