"""Unit tests for Phase 2/8a — notification_log provider tracking columns.

Validates that the 5 new columns added in migration 0195 are correctly
persisted, updated, and serialised by the notification service:

  - provider_key
  - provider_message_id
  - bounced_at
  - bounce_reason
  - delivered_at

Requirements: 16.3, 16.4, 16.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import all ORM models so SQLAlchemy can resolve string-based relationship
# references at module load time. Mirrors the import block in app/main.py
# that runs during application startup before configure_mappers() is called.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.invoices import attachment_models as _invoice_attachment_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401

from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.modules.notifications.models import NotificationLog
from app.modules.notifications.service import (
    _log_entry_to_dict,
    log_email_sent,
    update_log_status,
)


ORG_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# log_email_sent — persists new provider tracking columns (Req 16.3)
# ---------------------------------------------------------------------------


class TestLogEmailSentProviderColumns:
    """log_email_sent must accept and persist the 5 new kwargs."""

    @pytest.mark.asyncio
    async def test_persists_provider_key_and_message_id(self):
        """Verify provider_key + provider_message_id are stored on insert."""
        db = AsyncMock()
        added: list[NotificationLog] = []
        db.add = lambda obj: added.append(obj)

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
            recipient="user@example.com",
            template_type="invoice_issued",
            subject="Invoice INV-0001",
            status="sent",
            provider_key="sendgrid",
            provider_message_id="msg-abc",
        )

        assert len(added) == 1
        entry = added[0]
        assert entry.provider_key == "sendgrid"
        assert entry.provider_message_id == "msg-abc"
        # Unspecified bounce/delivery fields default to None
        assert entry.bounced_at is None
        assert entry.bounce_reason is None
        assert entry.delivered_at is None

        # Returned dict must surface the new fields
        assert result["provider_key"] == "sendgrid"
        assert result["provider_message_id"] == "msg-abc"
        assert result["bounced_at"] is None
        assert result["bounce_reason"] is None
        assert result["delivered_at"] is None

    @pytest.mark.asyncio
    async def test_persists_all_five_new_columns(self):
        """Verify all five new kwargs are stored when supplied."""
        db = AsyncMock()
        added: list[NotificationLog] = []
        db.add = lambda obj: added.append(obj)

        async def fake_flush():
            pass

        async def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.flush = fake_flush
        db.refresh = fake_refresh

        bounced_at = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
        delivered_at = datetime(2026, 5, 27, 10, 5, tzinfo=timezone.utc)

        result = await log_email_sent(
            db,
            org_id=ORG_ID,
            recipient="user@example.com",
            template_type="payment_received",
            subject="Payment received",
            status="bounced",
            provider_key="brevo",
            provider_message_id="<msg-id-123@brevo>",
            bounced_at=bounced_at,
            bounce_reason="hard bounce: mailbox not found",
            delivered_at=delivered_at,
        )

        entry = added[0]
        assert entry.provider_key == "brevo"
        assert entry.provider_message_id == "<msg-id-123@brevo>"
        assert entry.bounced_at == bounced_at
        assert entry.bounce_reason == "hard bounce: mailbox not found"
        assert entry.delivered_at == delivered_at

        assert result["provider_key"] == "brevo"
        assert result["provider_message_id"] == "<msg-id-123@brevo>"
        assert result["bounced_at"] == bounced_at.isoformat()
        assert result["bounce_reason"] == "hard bounce: mailbox not found"
        assert result["delivered_at"] == delivered_at.isoformat()

    @pytest.mark.asyncio
    async def test_columns_default_to_none_when_omitted(self):
        """Verify omitting the new kwargs leaves columns NULL."""
        db = AsyncMock()
        added: list[NotificationLog] = []
        db.add = lambda obj: added.append(obj)

        async def fake_flush():
            pass

        async def fake_refresh(obj):
            obj.id = uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.flush = fake_flush
        db.refresh = fake_refresh

        await log_email_sent(
            db,
            org_id=ORG_ID,
            recipient="user@example.com",
            template_type="invoice_issued",
            subject="Subject",
            status="queued",
        )

        entry = added[0]
        assert entry.provider_key is None
        assert entry.provider_message_id is None
        assert entry.bounced_at is None
        assert entry.bounce_reason is None
        assert entry.delivered_at is None


# ---------------------------------------------------------------------------
# update_log_status — updates new provider tracking columns (Req 16.3)
# ---------------------------------------------------------------------------


def _make_log_entry(**overrides) -> NotificationLog:
    """Create a NotificationLog ORM instance with sensible defaults."""
    entry = NotificationLog()
    entry.id = overrides.get("id", uuid.uuid4())
    entry.org_id = overrides.get("org_id", ORG_ID)
    entry.channel = overrides.get("channel", "email")
    entry.recipient = overrides.get("recipient", "user@example.com")
    entry.template_type = overrides.get("template_type", "invoice_issued")
    entry.subject = overrides.get("subject", "Invoice")
    entry.status = overrides.get("status", "queued")
    entry.retry_count = overrides.get("retry_count", 0)
    entry.error_message = overrides.get("error_message", None)
    entry.sent_at = overrides.get("sent_at", None)
    entry.created_at = overrides.get(
        "created_at", datetime.now(timezone.utc)
    )
    entry.provider_key = overrides.get("provider_key", None)
    entry.provider_message_id = overrides.get("provider_message_id", None)
    entry.bounced_at = overrides.get("bounced_at", None)
    entry.bounce_reason = overrides.get("bounce_reason", None)
    entry.delivered_at = overrides.get("delivered_at", None)
    return entry


class TestUpdateLogStatusProviderColumns:
    """update_log_status must update the new provider tracking columns."""

    @pytest.mark.asyncio
    async def test_updates_provider_key_and_message_id(self):
        """Verify provider_key + provider_message_id can be updated."""
        log_id = uuid.uuid4()
        existing = _make_log_entry(id=log_id, status="queued")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await update_log_status(
            db,
            log_id=log_id,
            status="sent",
            provider_key="sendgrid",
            provider_message_id="msg-xyz",
        )

        # ORM entry was mutated in place
        assert existing.provider_key == "sendgrid"
        assert existing.provider_message_id == "msg-xyz"
        assert existing.status == "sent"

        # Returned dict reflects the update
        assert result is not None
        assert result["provider_key"] == "sendgrid"
        assert result["provider_message_id"] == "msg-xyz"
        assert result["status"] == "sent"

    @pytest.mark.asyncio
    async def test_updates_bounce_fields(self):
        """Verify bounced_at + bounce_reason can be updated together."""
        log_id = uuid.uuid4()
        existing = _make_log_entry(
            id=log_id, status="sent", provider_key="brevo"
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        bounced_at = datetime(2026, 5, 27, 11, 0, tzinfo=timezone.utc)

        result = await update_log_status(
            db,
            log_id=log_id,
            status="bounced",
            bounced_at=bounced_at,
            bounce_reason="hard bounce",
        )

        assert existing.bounced_at == bounced_at
        assert existing.bounce_reason == "hard bounce"
        assert existing.status == "bounced"
        # provider_key untouched (not supplied)
        assert existing.provider_key == "brevo"

        assert result is not None
        assert result["bounced_at"] == bounced_at.isoformat()
        assert result["bounce_reason"] == "hard bounce"

    @pytest.mark.asyncio
    async def test_updates_delivered_at(self):
        """Verify delivered_at can be updated independently."""
        log_id = uuid.uuid4()
        existing = _make_log_entry(id=log_id, status="sent")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        delivered_at = datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc)

        result = await update_log_status(
            db,
            log_id=log_id,
            status="delivered",
            delivered_at=delivered_at,
        )

        assert existing.delivered_at == delivered_at
        assert existing.status == "delivered"

        assert result is not None
        assert result["delivered_at"] == delivered_at.isoformat()

    @pytest.mark.asyncio
    async def test_omitted_fields_preserved(self):
        """Verify columns not supplied keep their existing values."""
        log_id = uuid.uuid4()
        existing = _make_log_entry(
            id=log_id,
            status="sent",
            provider_key="brevo",
            provider_message_id="<msg-1>",
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        # Update only the status — provider columns should be unchanged
        result = await update_log_status(
            db, log_id=log_id, status="opened"
        )

        assert existing.provider_key == "brevo"
        assert existing.provider_message_id == "<msg-1>"
        assert existing.status == "opened"

        assert result is not None
        assert result["provider_key"] == "brevo"
        assert result["provider_message_id"] == "<msg-1>"


# ---------------------------------------------------------------------------
# _log_entry_to_dict — serialises new fields (Req 16.4, 16.5)
# ---------------------------------------------------------------------------


class TestLogEntryToDictNewFields:
    """_log_entry_to_dict must surface the 5 new columns."""

    def test_serialises_all_new_fields(self):
        """Verify every new column appears in the dict with correct values."""
        bounced_at = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)
        delivered_at = datetime(2026, 5, 27, 10, 5, tzinfo=timezone.utc)

        entry = _make_log_entry(
            provider_key="sendgrid",
            provider_message_id="msg-abc",
            bounced_at=bounced_at,
            bounce_reason="hard bounce",
            delivered_at=delivered_at,
        )

        result = _log_entry_to_dict(entry)

        # All five keys must be present
        assert "provider_key" in result
        assert "provider_message_id" in result
        assert "bounced_at" in result
        assert "bounce_reason" in result
        assert "delivered_at" in result

        # Values match (datetimes serialised to ISO 8601)
        assert result["provider_key"] == "sendgrid"
        assert result["provider_message_id"] == "msg-abc"
        assert result["bounced_at"] == bounced_at.isoformat()
        assert result["bounce_reason"] == "hard bounce"
        assert result["delivered_at"] == delivered_at.isoformat()

    def test_serialises_null_new_fields(self):
        """Verify NULL columns serialise to None (not the string 'None')."""
        entry = _make_log_entry()  # all new fields default to None

        result = _log_entry_to_dict(entry)

        assert result["provider_key"] is None
        assert result["provider_message_id"] is None
        assert result["bounced_at"] is None
        assert result["bounce_reason"] is None
        assert result["delivered_at"] is None
