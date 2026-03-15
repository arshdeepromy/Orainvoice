"""Unit tests for Task 15.8 -- Configurable notification preferences.

Requirements: 83.1, 83.2, 83.3, 83.4
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401

from app.modules.notifications.schemas import (
    ALL_NOTIFICATION_TYPES,
    NOTIFICATION_CATEGORIES,
    NotificationPreferenceItem,
    NotificationPreferenceCategoryGroup,
    NotificationPreferencesResponse,
    NotificationPreferenceUpdateRequest,
)
from app.modules.notifications.service import (
    list_notification_preferences,
    update_notification_preference,
)

ORG_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestNotificationPreferenceSchemas:
    """Test Pydantic schema validation for notification preference models."""

    def test_preference_item_defaults(self):
        """is_enabled defaults to False, channel defaults to email."""
        item = NotificationPreferenceItem(notification_type="invoice_issued")
        assert item.is_enabled is False
        assert item.channel == "email"

    def test_preference_item_enabled_sms(self):
        item = NotificationPreferenceItem(
            notification_type="payment_received", is_enabled=True, channel="sms"
        )
        assert item.is_enabled is True
        assert item.channel == "sms"

    def test_preference_item_channel_both(self):
        item = NotificationPreferenceItem(
            notification_type="login_alert", is_enabled=True, channel="both"
        )
        assert item.channel == "both"

    def test_preference_item_rejects_invalid_channel(self):
        with pytest.raises(Exception):
            NotificationPreferenceItem(
                notification_type="login_alert", channel="push"
            )

    def test_update_request_requires_notification_type(self):
        with pytest.raises(Exception):
            NotificationPreferenceUpdateRequest()

    def test_update_request_type_only(self):
        req = NotificationPreferenceUpdateRequest(notification_type="invoice_issued")
        assert req.notification_type == "invoice_issued"
        assert req.is_enabled is None
        assert req.channel is None

    def test_update_request_full(self):
        req = NotificationPreferenceUpdateRequest(
            notification_type="payment_received", is_enabled=True, channel="both"
        )
        assert req.is_enabled is True
        assert req.channel == "both"

    def test_update_request_rejects_invalid_channel(self):
        with pytest.raises(Exception):
            NotificationPreferenceUpdateRequest(
                notification_type="invoice_issued", channel="webhook"
            )

    def test_category_group_structure(self):
        group = NotificationPreferenceCategoryGroup(
            category="Invoicing",
            preferences=[
                NotificationPreferenceItem(notification_type="invoice_issued"),
            ],
        )
        assert group.category == "Invoicing"
        assert len(group.preferences) == 1

    def test_response_structure(self):
        resp = NotificationPreferencesResponse(
            categories=[
                NotificationPreferenceCategoryGroup(
                    category="Payments",
                    preferences=[
                        NotificationPreferenceItem(
                            notification_type="payment_received"
                        ),
                    ],
                )
            ]
        )
        assert len(resp.categories) == 1
        assert resp.categories[0].category == "Payments"


# ---------------------------------------------------------------------------
# Constants / category tests
# ---------------------------------------------------------------------------


class TestNotificationCategories:
    """Verify the category groupings and notification type constants."""

    def test_all_types_count(self):
        """All 19 notification types are defined."""
        assert len(ALL_NOTIFICATION_TYPES) == 19

    def test_six_categories(self):
        assert len(NOTIFICATION_CATEGORIES) == 6

    def test_invoicing_types(self):
        assert set(NOTIFICATION_CATEGORIES["Invoicing"]) == {
            "invoice_issued",
            "invoice_voided",
            "payment_overdue_reminder",
        }

    def test_payments_types(self):
        assert set(NOTIFICATION_CATEGORIES["Payments"]) == {"payment_received"}

    def test_vehicle_reminders_types(self):
        assert set(NOTIFICATION_CATEGORIES["Vehicle Reminders"]) == {
            "wof_expiry_reminder",
            "registration_expiry_reminder",
            "service_due_reminder",
        }

    def test_system_alerts_types(self):
        assert set(NOTIFICATION_CATEGORIES["System Alerts"]) == {
            "storage_warning_80",
            "storage_critical_90",
            "storage_full_100",
            "subscription_renewal_reminder",
            "subscription_payment_failed",
            "login_alert",
            "account_locked",
        }

    def test_quotes_types(self):
        assert set(NOTIFICATION_CATEGORIES["Quotes"]) == {
            "quote_sent",
            "quote_accepted",
            "quote_expired",
        }

    def test_bookings_types(self):
        assert set(NOTIFICATION_CATEGORIES["Bookings"]) == {
            "booking_confirmation",
            "booking_cancellation",
        }

    def test_all_types_is_union_of_categories(self):
        """ALL_NOTIFICATION_TYPES equals the union of all category lists."""
        union = set()
        for types in NOTIFICATION_CATEGORIES.values():
            union.update(types)
        assert ALL_NOTIFICATION_TYPES == union


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


def _make_pref(notification_type: str, is_enabled: bool = False, channel: str = "email"):
    """Create a mock NotificationPreference ORM object."""
    pref = MagicMock()
    pref.notification_type = notification_type
    pref.is_enabled = is_enabled
    pref.channel = channel
    pref.org_id = ORG_ID
    pref.config = {}
    return pref


def _mock_scalars_all(prefs):
    """Build a mock db.execute() result that returns prefs via scalars().all()."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = prefs
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


class TestListNotificationPreferences:
    """Test list_notification_preferences service function."""

    @pytest.mark.asyncio
    async def test_returns_all_categories_with_defaults(self):
        """When no preferences are stored, all types default to disabled/email."""
        db = AsyncMock()
        db.execute.return_value = _mock_scalars_all([])

        data = await list_notification_preferences(db, org_id=ORG_ID)

        assert "categories" in data
        assert len(data["categories"]) == 4

        # Verify every notification type appears
        all_returned = set()
        for cat in data["categories"]:
            for p in cat["preferences"]:
                all_returned.add(p["notification_type"])
                assert p["is_enabled"] is False
                assert p["channel"] == "email"

        assert all_returned == ALL_NOTIFICATION_TYPES

    @pytest.mark.asyncio
    async def test_stored_preferences_override_defaults(self):
        """Stored preferences should appear with their actual values."""
        stored = [
            _make_pref("invoice_issued", is_enabled=True, channel="both"),
            _make_pref("payment_received", is_enabled=True, channel="sms"),
        ]
        db = AsyncMock()
        db.execute.return_value = _mock_scalars_all(stored)

        data = await list_notification_preferences(db, org_id=ORG_ID)

        # Find invoice_issued in Invoicing category
        invoicing = next(c for c in data["categories"] if c["category"] == "Invoicing")
        inv_issued = next(
            p for p in invoicing["preferences"]
            if p["notification_type"] == "invoice_issued"
        )
        assert inv_issued["is_enabled"] is True
        assert inv_issued["channel"] == "both"

        # Find payment_received in Payments category
        payments = next(c for c in data["categories"] if c["category"] == "Payments")
        pay_recv = next(
            p for p in payments["preferences"]
            if p["notification_type"] == "payment_received"
        )
        assert pay_recv["is_enabled"] is True
        assert pay_recv["channel"] == "sms"

    @pytest.mark.asyncio
    async def test_category_order_matches_definition(self):
        """Categories should appear in the same order as NOTIFICATION_CATEGORIES."""
        db = AsyncMock()
        db.execute.return_value = _mock_scalars_all([])

        data = await list_notification_preferences(db, org_id=ORG_ID)

        expected_order = list(NOTIFICATION_CATEGORIES.keys())
        actual_order = [c["category"] for c in data["categories"]]
        assert actual_order == expected_order


class TestUpdateNotificationPreference:
    """Test update_notification_preference service function."""

    @pytest.mark.asyncio
    async def test_creates_new_preference(self):
        """When no preference exists, creates a new one."""
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute.return_value = scalar_mock

        # Mock refresh to set attributes on the added object
        async def fake_refresh(obj):
            obj.notification_type = "invoice_issued"
            obj.is_enabled = True
            obj.channel = "both"

        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await update_notification_preference(
            db,
            org_id=ORG_ID,
            notification_type="invoice_issued",
            is_enabled=True,
            channel="both",
        )

        assert result["notification_type"] == "invoice_issued"
        assert result["is_enabled"] is True
        assert result["channel"] == "both"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_preference(self):
        """When a preference exists, updates it in place."""
        existing = _make_pref("invoice_issued", is_enabled=False, channel="email")
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = existing
        db = AsyncMock()
        db.execute.return_value = scalar_mock

        async def fake_refresh(obj):
            pass  # attributes already set by the function

        db.refresh = AsyncMock(side_effect=fake_refresh)

        result = await update_notification_preference(
            db,
            org_id=ORG_ID,
            notification_type="invoice_issued",
            is_enabled=True,
            channel="sms",
        )

        assert existing.is_enabled is True
        assert existing.channel == "sms"

    @pytest.mark.asyncio
    async def test_rejects_unknown_notification_type(self):
        """Unknown notification types should raise ValueError."""
        db = AsyncMock()

        with pytest.raises(ValueError, match="Unknown notification type"):
            await update_notification_preference(
                db,
                org_id=ORG_ID,
                notification_type="nonexistent_type",
                is_enabled=True,
            )

    @pytest.mark.asyncio
    async def test_partial_update_only_enabled(self):
        """Updating only is_enabled should not change channel."""
        existing = _make_pref("payment_received", is_enabled=False, channel="sms")
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = existing
        db = AsyncMock()
        db.execute.return_value = scalar_mock
        db.refresh = AsyncMock()

        await update_notification_preference(
            db,
            org_id=ORG_ID,
            notification_type="payment_received",
            is_enabled=True,
        )

        assert existing.is_enabled is True
        assert existing.channel == "sms"  # unchanged

    @pytest.mark.asyncio
    async def test_partial_update_only_channel(self):
        """Updating only channel should not change is_enabled."""
        existing = _make_pref("login_alert", is_enabled=True, channel="email")
        scalar_mock = MagicMock()
        scalar_mock.scalar_one_or_none.return_value = existing
        db = AsyncMock()
        db.execute.return_value = scalar_mock
        db.refresh = AsyncMock()

        await update_notification_preference(
            db,
            org_id=ORG_ID,
            notification_type="login_alert",
            channel="both",
        )

        assert existing.is_enabled is True  # unchanged
        assert existing.channel == "both"
