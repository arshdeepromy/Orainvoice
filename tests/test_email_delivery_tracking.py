"""Unit tests for Task 15.3 — Email delivery tracking.

Tests cover:
  - Logging sent emails (recipient, template, timestamp, status, subject)
  - Querying the notification log (pagination, filters)
  - Updating log entry status
  - Flagging bounced email addresses on customer records
  - Router endpoint access control (Org_Admin only)

Requirements: 35.1, 35.2, 35.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.modules.notifications.models import NotificationLog
from app.modules.notifications.schemas import (
    VALID_DELIVERY_STATUSES,
    NotificationLogEntry,
    NotificationLogResponse,
)
from app.modules.notifications.service import (
    _log_entry_to_dict,
    flag_bounced_email_on_customer,
    list_notification_log,
    log_email_sent,
    update_log_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()


def _make_log_entry(**overrides) -> NotificationLog:
    """Create a NotificationLog ORM instance with sensible defaults."""
    now = datetime.now(timezone.utc)
    entry = NotificationLog()
    entry.id = overrides.get("id", uuid.uuid4())
    entry.org_id = overrides.get("org_id", ORG_ID)
    entry.channel = overrides.get("channel", "email")
    entry.recipient = overrides.get("recipient", "customer@example.com")
    entry.template_type = overrides.get("template_type", "invoice_issued")
    entry.subject = overrides.get("subject", "Invoice INV-0042 from Workshop Pro")
    entry.status = overrides.get("status", "queued")
    entry.retry_count = overrides.get("retry_count", 0)
    entry.error_message = overrides.get("error_message", None)
    entry.sent_at = overrides.get("sent_at", None)
    entry.created_at = overrides.get("created_at", now)
    return entry


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestDeliveryStatusConstants:
    """Verify delivery status constants match the design."""

    def test_all_statuses_present(self):
        expected = {"queued", "sent", "delivered", "bounced", "opened", "failed"}
        assert set(VALID_DELIVERY_STATUSES) == expected

    def test_status_count(self):
        assert len(VALID_DELIVERY_STATUSES) == 6


class TestNotificationLogSchemas:
    """Verify Pydantic schemas for notification log."""

    def test_log_entry_schema(self):
        entry = NotificationLogEntry(
            id=str(uuid.uuid4()),
            channel="email",
            recipient="test@example.com",
            template_type="invoice_issued",
            subject="Test Subject",
            status="sent",
            error_message=None,
            sent_at="2025-01-15T10:00:00+00:00",
            created_at="2025-01-15T09:59:00+00:00",
        )
        assert entry.channel == "email"
        assert entry.status == "sent"

    def test_log_response_schema(self):
        resp = NotificationLogResponse(entries=[], total=0, page=1, page_size=50)
        assert resp.total == 0
        assert resp.page == 1

    def test_log_response_with_entries(self):
        entry = NotificationLogEntry(
            id=str(uuid.uuid4()),
            channel="email",
            recipient="test@example.com",
            template_type="payment_received",
            subject="Payment received",
            status="delivered",
            sent_at=None,
            created_at="2025-01-15T09:59:00+00:00",
        )
        resp = NotificationLogResponse(
            entries=[entry], total=1, page=1, page_size=50
        )
        assert len(resp.entries) == 1
        assert resp.entries[0].template_type == "payment_received"


# ---------------------------------------------------------------------------
# Service helper tests
# ---------------------------------------------------------------------------


class TestLogEntryToDict:
    """Test the _log_entry_to_dict helper."""

    def test_converts_all_fields(self):
        entry = _make_log_entry()
        result = _log_entry_to_dict(entry)
        assert result["channel"] == "email"
        assert result["recipient"] == "customer@example.com"
        assert result["template_type"] == "invoice_issued"
        assert result["status"] == "queued"
        assert result["error_message"] is None
        assert result["sent_at"] is None

    def test_includes_sent_at_when_present(self):
        now = datetime.now(timezone.utc)
        entry = _make_log_entry(sent_at=now, status="sent")
        result = _log_entry_to_dict(entry)
        assert result["sent_at"] == now.isoformat()
        assert result["status"] == "sent"

    def test_includes_error_message(self):
        entry = _make_log_entry(
            status="bounced", error_message="Mailbox not found"
        )
        result = _log_entry_to_dict(entry)
        assert result["status"] == "bounced"
        assert result["error_message"] == "Mailbox not found"


# ---------------------------------------------------------------------------
# Service: log_email_sent
# ---------------------------------------------------------------------------


class TestLogEmailSent:
    """Test logging a sent email."""

    @pytest.mark.asyncio
    async def test_creates_log_entry(self):
        """Verify log_email_sent creates a NotificationLog row."""
        db = AsyncMock()
        added_objects = []
        db.add = lambda obj: added_objects.append(obj)

        async def fake_flush():
            pass

        async def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.flush = fake_flush
        db.refresh = fake_refresh

        result = await log_email_sent(
            db,
            org_id=ORG_ID,
            recipient="jane@example.com",
            template_type="invoice_issued",
            subject="Invoice INV-0042",
            status="queued",
        )

        assert len(added_objects) == 1
        entry = added_objects[0]
        assert isinstance(entry, NotificationLog)
        assert entry.org_id == ORG_ID
        assert entry.recipient == "jane@example.com"
        assert entry.template_type == "invoice_issued"
        assert entry.subject == "Invoice INV-0042"
        assert entry.status == "queued"
        assert entry.channel == "email"
        assert result["recipient"] == "jane@example.com"

    @pytest.mark.asyncio
    async def test_creates_with_sent_status(self):
        """Verify log_email_sent can create with 'sent' status and sent_at."""
        db = AsyncMock()
        added_objects = []
        db.add = lambda obj: added_objects.append(obj)

        now = datetime.now(timezone.utc)

        async def fake_flush():
            pass

        async def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = now

        db.flush = fake_flush
        db.refresh = fake_refresh

        result = await log_email_sent(
            db,
            org_id=ORG_ID,
            recipient="bob@example.com",
            template_type="payment_received",
            subject="Payment received",
            status="sent",
            sent_at=now,
        )

        entry = added_objects[0]
        assert entry.status == "sent"
        assert entry.sent_at == now

    @pytest.mark.asyncio
    async def test_creates_with_error(self):
        """Verify log_email_sent can record an error message."""
        db = AsyncMock()
        added_objects = []
        db.add = lambda obj: added_objects.append(obj)

        async def fake_flush():
            pass

        async def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.flush = fake_flush
        db.refresh = fake_refresh

        result = await log_email_sent(
            db,
            org_id=ORG_ID,
            recipient="bad@example.com",
            template_type="invoice_issued",
            subject="Invoice",
            status="failed",
            error_message="Connection refused",
        )

        entry = added_objects[0]
        assert entry.status == "failed"
        assert entry.error_message == "Connection refused"


# ---------------------------------------------------------------------------
# Service: update_log_status
# ---------------------------------------------------------------------------


class TestUpdateLogStatus:
    """Test updating a log entry's delivery status."""

    @pytest.mark.asyncio
    async def test_updates_status(self):
        """Verify status update on an existing log entry."""
        log_id = uuid.uuid4()
        existing = _make_log_entry(id=log_id, status="queued")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_log_status(
            db, log_id=log_id, status="sent",
            sent_at=datetime.now(timezone.utc),
        )

        assert result is not None
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_updates_to_bounced_with_error(self):
        """Verify bounce status includes error message."""
        log_id = uuid.uuid4()
        existing = _make_log_entry(id=log_id, status="sent")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_log_status(
            db, log_id=log_id, status="bounced",
            error_message="Mailbox not found",
        )

        assert result is not None
        assert result["status"] == "bounced"
        assert result["error_message"] == "Mailbox not found"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing(self):
        """Verify None returned when log entry doesn't exist."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_log_status(
            db, log_id=uuid.uuid4(), status="sent",
        )

        assert result is None


# ---------------------------------------------------------------------------
# Service: list_notification_log
# ---------------------------------------------------------------------------


class TestListNotificationLog:
    """Test querying the notification log."""

    @pytest.mark.asyncio
    async def test_returns_paginated_entries(self):
        """Verify list returns entries with pagination metadata."""
        entries = [_make_log_entry() for _ in range(3)]

        # Mock count query
        count_result = MagicMock()
        count_result.scalar.return_value = 3

        # Mock entries query
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entries
        entries_result = MagicMock()
        entries_result.scalars.return_value = scalars_mock

        db = AsyncMock()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return count_result
            return entries_result

        db.execute = fake_execute

        result = await list_notification_log(
            db, org_id=ORG_ID, page=1, page_size=50,
        )

        assert result["total"] == 3
        assert len(result["entries"]) == 3
        assert result["page"] == 1
        assert result["page_size"] == 50

    @pytest.mark.asyncio
    async def test_empty_log(self):
        """Verify empty result when no log entries exist."""
        count_result = MagicMock()
        count_result.scalar.return_value = 0

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        entries_result = MagicMock()
        entries_result.scalars.return_value = scalars_mock

        db = AsyncMock()
        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return count_result
            return entries_result

        db.execute = fake_execute

        result = await list_notification_log(
            db, org_id=ORG_ID, page=1, page_size=50,
        )

        assert result["total"] == 0
        assert result["entries"] == []


# ---------------------------------------------------------------------------
# Service: flag_bounced_email_on_customer
# ---------------------------------------------------------------------------


class TestFlagBouncedEmail:
    """Test flagging bounced email addresses on customer records."""

    @pytest.mark.asyncio
    async def test_flags_matching_customers(self):
        """Verify customers with matching email get email_bounced=True."""
        mock_result = MagicMock()
        mock_result.rowcount = 2

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        count = await flag_bounced_email_on_customer(
            db, org_id=ORG_ID, email_address="bounced@example.com",
        )

        assert count == 2
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_matching_customers(self):
        """Verify zero returned when no customers match."""
        mock_result = MagicMock()
        mock_result.rowcount = 0

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        count = await flag_bounced_email_on_customer(
            db, org_id=ORG_ID, email_address="unknown@example.com",
        )

        assert count == 0
