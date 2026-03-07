"""Tests for platform notification system (Task 48).

Covers:
- 48.7: targeted notification only visible to matching orgs
- 48.8: maintenance window notification shows countdown and auto-expires

Requirements: Platform Notification System
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.notifications_service import (
    PlatformNotificationService,
    _matches_target,
    _notification_to_dict,
)
from app.modules.admin.notifications_models import (
    NotificationDismissal,
    PlatformNotification,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeNotification:
    """Lightweight stand-in for PlatformNotification ORM model in tests."""

    def __init__(self, **kwargs):
        now = datetime.now(timezone.utc)
        defaults = {
            "id": uuid.uuid4(),
            "notification_type": "info",
            "title": "Test Notification",
            "message": "Test message",
            "severity": "info",
            "target_type": "all",
            "target_value": None,
            "scheduled_at": None,
            "published_at": now,
            "expires_at": now + timedelta(days=7),
            "maintenance_start": None,
            "maintenance_end": None,
            "is_active": True,
            "created_by": None,
            "created_at": now,
            "updated_at": now,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def _make_notification(**kwargs) -> _FakeNotification:
    """Create a fake notification with defaults."""
    return _FakeNotification(**kwargs)


def _mock_scalars_all(items):
    """Create a mock result that returns scalars().all() with items."""
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = items
    return mock


def _mock_all(items):
    """Create a mock result that returns .all() with items."""
    mock = MagicMock()
    mock.all.return_value = items
    return mock


# ---------------------------------------------------------------------------
# 48.7: Targeted notification only visible to matching orgs
# ---------------------------------------------------------------------------


class TestTargetedNotificationVisibility:
    """Validates: Task 48.7 — targeted notification only visible to matching orgs."""

    def test_all_target_matches_any_org(self):
        """Notification with target_type='all' is visible to every org."""
        notif = _make_notification(target_type="all")
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_country="NZ") is True

    def test_country_target_matches_correct_country(self):
        """Notification targeting country='NZ' is visible to NZ orgs."""
        notif = _make_notification(target_type="country", target_value='"NZ"')
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_country="NZ") is True

    def test_country_target_excludes_wrong_country(self):
        """Notification targeting country='NZ' is NOT visible to AU orgs."""
        notif = _make_notification(target_type="country", target_value='"NZ"')
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_country="AU") is False

    def test_country_target_with_json_array(self):
        """Notification targeting multiple countries via JSON array."""
        notif = _make_notification(target_type="country", target_value='["NZ", "AU"]')
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_country="NZ") is True
        assert _matches_target(notif, org_id=org_id, org_country="AU") is True
        assert _matches_target(notif, org_id=org_id, org_country="UK") is False

    def test_trade_family_target_matches(self):
        """Notification targeting trade_family='automotive' matches automotive orgs."""
        notif = _make_notification(target_type="trade_family", target_value='"automotive"')
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_trade_family="automotive") is True
        assert _matches_target(notif, org_id=org_id, org_trade_family="construction") is False

    def test_plan_tier_target_matches(self):
        """Notification targeting plan_tier='pro' matches pro-tier orgs."""
        notif = _make_notification(target_type="plan_tier", target_value='"pro"')
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_plan_tier="pro") is True
        assert _matches_target(notif, org_id=org_id, org_plan_tier="starter") is False

    def test_specific_orgs_target_matches_by_id(self):
        """Notification targeting specific org IDs matches only those orgs."""
        org1 = uuid.uuid4()
        org2 = uuid.uuid4()
        org3 = uuid.uuid4()
        notif = _make_notification(
            target_type="specific_orgs",
            target_value=json.dumps([str(org1), str(org2)]),
        )
        assert _matches_target(notif, org_id=org1) is True
        assert _matches_target(notif, org_id=org2) is True
        assert _matches_target(notif, org_id=org3) is False

    def test_no_target_value_matches_all(self):
        """When target_value is None, notification matches all orgs regardless of target_type."""
        notif = _make_notification(target_type="country", target_value=None)
        org_id = uuid.uuid4()
        assert _matches_target(notif, org_id=org_id, org_country="NZ") is True

    @pytest.mark.asyncio
    async def test_get_active_for_org_filters_by_target(self):
        """get_active_for_org only returns notifications matching the org's context."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Create notifications: one for NZ, one for AU
        nz_notif = _make_notification(
            target_type="country",
            target_value='"NZ"',
            published_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )
        au_notif = _make_notification(
            target_type="country",
            target_value='"AU"',
            published_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )
        all_notif = _make_notification(
            target_type="all",
            published_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )

        db = AsyncMock()
        # First call: fetch all active notifications
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_all([nz_notif, au_notif, all_notif]),
                _mock_all([]),  # no dismissals
            ]
        )

        service = PlatformNotificationService(db)
        result = await service.get_active_for_org(
            org_id=org_id,
            user_id=user_id,
            org_country="NZ",
        )

        # Should see NZ notification and 'all' notification, but NOT AU
        ids = {n["id"] for n in result}
        assert str(nz_notif.id) in ids
        assert str(all_notif.id) in ids
        assert str(au_notif.id) not in ids

    @pytest.mark.asyncio
    async def test_get_active_excludes_dismissed(self):
        """get_active_for_org excludes notifications the user has dismissed."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        notif1 = _make_notification(
            target_type="all",
            published_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )
        notif2 = _make_notification(
            target_type="all",
            published_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_all([notif1, notif2]),
                _mock_all([(notif1.id,)]),  # notif1 is dismissed
            ]
        )

        service = PlatformNotificationService(db)
        result = await service.get_active_for_org(
            org_id=org_id,
            user_id=user_id,
        )

        ids = {n["id"] for n in result}
        assert str(notif1.id) not in ids
        assert str(notif2.id) in ids

    @pytest.mark.asyncio
    async def test_get_active_excludes_expired(self):
        """get_active_for_org excludes expired notifications."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        expired = _make_notification(
            target_type="all",
            published_at=now - timedelta(days=2),
            expires_at=now - timedelta(hours=1),  # already expired
        )
        active = _make_notification(
            target_type="all",
            published_at=now - timedelta(minutes=5),
            expires_at=now + timedelta(days=1),
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_all([expired, active]),
                _mock_all([]),
            ]
        )

        service = PlatformNotificationService(db)
        result = await service.get_active_for_org(
            org_id=org_id,
            user_id=user_id,
        )

        ids = {n["id"] for n in result}
        assert str(expired.id) not in ids
        assert str(active.id) in ids


# ---------------------------------------------------------------------------
# 48.8: Maintenance window notification shows countdown and auto-expires
# ---------------------------------------------------------------------------


class TestMaintenanceWindowNotification:
    """Validates: Task 48.8 — maintenance window notification with countdown and auto-expiry."""

    @pytest.mark.asyncio
    async def test_schedule_maintenance_window_creates_notification(self):
        """schedule_maintenance_window creates a maintenance notification with correct fields."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PlatformNotificationService(db)
        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=2)
        end = now + timedelta(hours=4)

        result = await service.schedule_maintenance_window(
            title="Scheduled Maintenance",
            message="System will be down for upgrades",
            maintenance_start=start,
            maintenance_end=end,
        )

        assert result["notification_type"] == "maintenance"
        assert result["severity"] == "warning"
        assert result["title"] == "Scheduled Maintenance"
        assert result["maintenance_start"] == start
        assert result["maintenance_end"] == end
        assert result["expires_at"] == end  # auto-expires at maintenance_end
        assert result["published_at"] is not None  # published immediately

    @pytest.mark.asyncio
    async def test_maintenance_window_rejects_invalid_times(self):
        """schedule_maintenance_window rejects end before start."""
        db = AsyncMock()
        service = PlatformNotificationService(db)
        now = datetime.now(timezone.utc)

        with pytest.raises(ValueError, match="maintenance_end must be after maintenance_start"):
            await service.schedule_maintenance_window(
                title="Bad Window",
                message="Invalid times",
                maintenance_start=now + timedelta(hours=4),
                maintenance_end=now + timedelta(hours=2),
            )

    @pytest.mark.asyncio
    async def test_maintenance_notification_auto_expires(self):
        """Maintenance notification is not visible after maintenance_end passes."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Maintenance window that has already ended
        past_maintenance = _make_notification(
            notification_type="maintenance",
            severity="warning",
            target_type="all",
            published_at=now - timedelta(hours=6),
            expires_at=now - timedelta(hours=1),  # expired
            maintenance_start=now - timedelta(hours=4),
            maintenance_end=now - timedelta(hours=1),
        )

        # Active maintenance window
        active_maintenance = _make_notification(
            notification_type="maintenance",
            severity="warning",
            target_type="all",
            published_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
            maintenance_start=now + timedelta(hours=1),
            maintenance_end=now + timedelta(hours=2),
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_all([past_maintenance, active_maintenance]),
                _mock_all([]),
            ]
        )

        service = PlatformNotificationService(db)
        result = await service.get_active_for_org(
            org_id=org_id,
            user_id=user_id,
        )

        ids = {n["id"] for n in result}
        assert str(past_maintenance.id) not in ids  # expired, not visible
        assert str(active_maintenance.id) in ids  # still active

    @pytest.mark.asyncio
    async def test_maintenance_notification_includes_countdown_data(self):
        """Active maintenance notification includes start/end times for countdown display."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        start = now + timedelta(hours=1)
        end = now + timedelta(hours=3)

        maintenance = _make_notification(
            notification_type="maintenance",
            severity="warning",
            target_type="all",
            published_at=now - timedelta(minutes=30),
            expires_at=end,
            maintenance_start=start,
            maintenance_end=end,
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_scalars_all([maintenance]),
                _mock_all([]),
            ]
        )

        service = PlatformNotificationService(db)
        result = await service.get_active_for_org(
            org_id=org_id,
            user_id=user_id,
        )

        assert len(result) == 1
        notif = result[0]
        assert notif["notification_type"] == "maintenance"
        assert notif["maintenance_start"] == start
        assert notif["maintenance_end"] == end

    @pytest.mark.asyncio
    async def test_maintenance_window_with_targeting(self):
        """Maintenance window can target specific countries."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PlatformNotificationService(db)
        now = datetime.now(timezone.utc)

        result = await service.schedule_maintenance_window(
            title="NZ Maintenance",
            message="NZ region maintenance",
            maintenance_start=now + timedelta(hours=2),
            maintenance_end=now + timedelta(hours=4),
            target_type="country",
            target_value='"NZ"',
        )

        assert result["target_type"] == "country"
        assert result["target_value"] == '"NZ"'


# ---------------------------------------------------------------------------
# Service CRUD tests
# ---------------------------------------------------------------------------


class TestNotificationServiceCRUD:
    """Test basic CRUD operations on PlatformNotificationService."""

    @pytest.mark.asyncio
    async def test_create_notification_validates_type(self):
        """create_notification rejects invalid notification_type."""
        db = AsyncMock()
        service = PlatformNotificationService(db)

        with pytest.raises(ValueError, match="Invalid notification_type"):
            await service.create_notification(
                notification_type="invalid",
                title="Test",
                message="Test",
            )

    @pytest.mark.asyncio
    async def test_create_notification_validates_severity(self):
        """create_notification rejects invalid severity."""
        db = AsyncMock()
        service = PlatformNotificationService(db)

        with pytest.raises(ValueError, match="Invalid severity"):
            await service.create_notification(
                notification_type="info",
                title="Test",
                message="Test",
                severity="extreme",
            )

    @pytest.mark.asyncio
    async def test_create_notification_publishes_immediately_without_schedule(self):
        """Notification without scheduled_at is published immediately."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PlatformNotificationService(db)
        result = await service.create_notification(
            notification_type="info",
            title="Immediate",
            message="Published now",
        )

        assert result["published_at"] is not None

    @pytest.mark.asyncio
    async def test_create_notification_defers_with_schedule(self):
        """Notification with scheduled_at is not published immediately."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PlatformNotificationService(db)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        result = await service.create_notification(
            notification_type="feature",
            title="Scheduled",
            message="Published later",
            scheduled_at=future,
        )

        assert result["published_at"] is None
        assert result["scheduled_at"] == future

    @pytest.mark.asyncio
    async def test_dismiss_for_user(self):
        """dismiss_for_user creates a dismissal record."""
        notif_id = uuid.uuid4()
        user_id = uuid.uuid4()
        notif = _make_notification(id=notif_id)

        db = AsyncMock()
        # First call: find notification
        mock_notif_result = MagicMock()
        mock_notif_result.scalar_one_or_none.return_value = notif
        # Second call: check existing dismissal
        mock_existing = MagicMock()
        mock_existing.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(side_effect=[mock_notif_result, mock_existing])
        db.add = MagicMock()
        db.flush = AsyncMock()

        service = PlatformNotificationService(db)
        result = await service.dismiss_for_user(notif_id, user_id)

        assert result["status"] == "dismissed"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_due_notifications(self):
        """publish_due_notifications publishes scheduled notifications whose time has come."""
        now = datetime.now(timezone.utc)
        due_notif = _make_notification(
            scheduled_at=now - timedelta(minutes=5),
            published_at=None,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_all([due_notif]))
        db.flush = AsyncMock()

        service = PlatformNotificationService(db)
        count = await service.publish_due_notifications()

        assert count == 1
        assert due_notif.published_at is not None
