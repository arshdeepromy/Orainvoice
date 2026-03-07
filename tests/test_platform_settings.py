"""Unit tests for Task 23.4 — Platform Settings.

Tests cover:
  - Platform settings schemas (T&C, announcement banner, vehicle DB)
  - get_platform_settings service (empty state, with data)
  - update_platform_settings service (create T&C, update T&C with history,
    announcement banner create/update)
  - T&C version history and re-accept flag
  - search_global_vehicles service
  - delete_stale_vehicles service
  - refresh_global_vehicle service (Carjam success, failure, not found)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.admin.schemas import (
    GlobalVehicleDeleteResponse,
    GlobalVehicleRefreshResponse,
    GlobalVehicleSearchResponse,
    GlobalVehicleSearchResult,
    PlatformSettingsResponse,
    PlatformSettingsUpdateRequest,
    PlatformSettingsUpdateResponse,
    TermsAndConditionsEntry,
)
from app.modules.admin.service import (
    delete_stale_vehicles,
    get_platform_settings,
    refresh_global_vehicle,
    search_global_vehicles,
    update_platform_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def _make_execute_result(rows):
    """Create a mock execute result that supports .first() and iteration."""
    result = MagicMock()
    result.first.return_value = rows[0] if rows else None
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    result.__iter__ = lambda self: iter(rows)
    result.rowcount = len(rows)
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestPlatformSettingsSchemas:
    """Validate Pydantic schema construction and defaults."""

    def test_terms_and_conditions_entry(self):
        entry = TermsAndConditionsEntry(version=1, content="Terms v1", updated_at="2025-01-01T00:00:00Z")
        assert entry.version == 1
        assert entry.content == "Terms v1"

    def test_platform_settings_response_defaults(self):
        resp = PlatformSettingsResponse()
        assert resp.terms_and_conditions is None
        assert resp.terms_history == []
        assert resp.announcement_banner is None
        assert resp.announcement_active is False

    def test_platform_settings_response_with_data(self):
        tc = TermsAndConditionsEntry(version=2, content="Terms v2", updated_at="2025-06-01T00:00:00Z")
        resp = PlatformSettingsResponse(
            terms_and_conditions=tc,
            terms_history=[TermsAndConditionsEntry(version=1, content="Terms v1", updated_at="2025-01-01T00:00:00Z")],
            announcement_banner="Maintenance tonight",
            announcement_active=True,
        )
        assert resp.terms_and_conditions.version == 2
        assert len(resp.terms_history) == 1
        assert resp.announcement_banner == "Maintenance tonight"
        assert resp.announcement_active is True

    def test_update_request_all_none(self):
        req = PlatformSettingsUpdateRequest()
        assert req.terms_and_conditions is None
        assert req.announcement_banner is None
        assert req.announcement_active is None

    def test_update_request_with_values(self):
        req = PlatformSettingsUpdateRequest(
            terms_and_conditions="New terms",
            announcement_banner="Hello",
            announcement_active=True,
        )
        assert req.terms_and_conditions == "New terms"
        assert req.announcement_banner == "Hello"
        assert req.announcement_active is True

    def test_update_response(self):
        resp = PlatformSettingsUpdateResponse(
            message="Platform settings updated",
            terms_version=3,
            announcement_banner="Banner text",
            announcement_active=True,
        )
        assert resp.terms_version == 3
        assert resp.announcement_active is True

    def test_global_vehicle_search_result(self):
        v = GlobalVehicleSearchResult(
            id="abc-123",
            rego="ABC123",
            make="Toyota",
            model="Corolla",
            year=2020,
        )
        assert v.rego == "ABC123"
        assert v.make == "Toyota"
        assert v.colour is None

    def test_global_vehicle_search_response(self):
        resp = GlobalVehicleSearchResponse(results=[], total=0)
        assert resp.total == 0

    def test_global_vehicle_refresh_response(self):
        resp = GlobalVehicleRefreshResponse(message="Refreshed", vehicle=None)
        assert resp.vehicle is None

    def test_global_vehicle_delete_response(self):
        resp = GlobalVehicleDeleteResponse(message="Deleted 5", deleted_count=5)
        assert resp.deleted_count == 5


# ---------------------------------------------------------------------------
# Service: get_platform_settings
# ---------------------------------------------------------------------------

class TestGetPlatformSettings:
    """Test get_platform_settings service function."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_empty_state(self, mock_audit):
        """When no settings exist, returns defaults."""
        db = _mock_db()
        # Both queries return no rows
        db.execute = AsyncMock(side_effect=[
            _make_execute_result([]),  # T&C query
            _make_execute_result([]),  # announcement query
        ])

        result = await get_platform_settings(db)
        assert result["terms_and_conditions"] is None
        assert result["terms_history"] == []
        assert result["announcement_banner"] is None
        assert result["announcement_active"] is False

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_with_tc_and_announcement(self, mock_audit):
        """When settings exist, returns them correctly."""
        db = _mock_db()
        now = datetime.now(timezone.utc)
        tc_value = {
            "content": "Current terms",
            "updated_at": now.isoformat(),
            "history": [{"version": 1, "content": "Old terms", "updated_at": "2025-01-01T00:00:00Z"}],
        }
        ann_value = {"text": "Maintenance tonight", "active": True}

        tc_row = (
            "terms_and_conditions",
            tc_value,
            2,
            now,
        )
        ann_row = (
            "announcement_banner",
            ann_value,
            1,
            now,
        )

        db.execute = AsyncMock(side_effect=[
            _make_execute_result([tc_row]),
            _make_execute_result([ann_row]),
        ])

        result = await get_platform_settings(db)
        assert result["terms_and_conditions"]["version"] == 2
        assert result["terms_and_conditions"]["content"] == "Current terms"
        assert len(result["terms_history"]) == 1
        assert result["terms_history"][0]["version"] == 1
        assert result["announcement_banner"] == "Maintenance tonight"
        assert result["announcement_active"] is True


# ---------------------------------------------------------------------------
# Service: update_platform_settings
# ---------------------------------------------------------------------------

class TestUpdatePlatformSettings:
    """Test update_platform_settings service function."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_create_new_tc(self, mock_audit):
        """First T&C creation inserts a new row with version 1."""
        db = _mock_db()
        # SELECT FOR UPDATE returns no existing row
        select_result = _make_execute_result([])
        # INSERT result
        insert_result = MagicMock()
        db.execute = AsyncMock(side_effect=[select_result, insert_result])

        result = await update_platform_settings(
            db,
            terms_and_conditions="First terms",
            actor_user_id=uuid.uuid4(),
        )

        assert result["terms_version"] == 1
        assert result["message"] == "Platform settings updated"
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_tc_increments_version(self, mock_audit):
        """Updating T&C increments version and preserves history."""
        db = _mock_db()
        old_val = {
            "content": "Old terms",
            "updated_at": "2025-01-01T00:00:00Z",
            "history": [],
        }
        existing_row = (old_val, 1)
        select_result = _make_execute_result([existing_row])
        update_result = MagicMock()
        db.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await update_platform_settings(
            db,
            terms_and_conditions="Updated terms",
            actor_user_id=uuid.uuid4(),
        )

        assert result["terms_version"] == 2
        # Verify the UPDATE call included the new content
        update_call = db.execute.call_args_list[1]
        params = update_call[0][1]
        new_val = json.loads(params["v"])
        assert new_val["content"] == "Updated terms"
        assert new_val["requires_reaccept"] is True
        assert len(new_val["history"]) == 1
        assert new_val["history"][0]["content"] == "Old terms"

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_create_announcement_banner(self, mock_audit):
        """Creating announcement banner when none exists."""
        db = _mock_db()
        # SELECT returns no existing row
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = None
        insert_result = MagicMock()
        db.execute = AsyncMock(side_effect=[select_result, insert_result])

        result = await update_platform_settings(
            db,
            announcement_banner="System maintenance at 2am",
            announcement_active=True,
        )

        assert result["announcement_banner"] == "System maintenance at 2am"
        assert result["announcement_active"] is True

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_announcement_banner(self, mock_audit):
        """Updating existing announcement banner."""
        db = _mock_db()
        existing_val = {"text": "Old banner", "active": True}
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = existing_val
        update_result = MagicMock()
        db.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await update_platform_settings(
            db,
            announcement_banner="New banner",
            announcement_active=False,
        )

        assert result["announcement_banner"] == "New banner"
        assert result["announcement_active"] is False

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_clear_announcement_banner(self, mock_audit):
        """Clearing announcement banner with empty string."""
        db = _mock_db()
        existing_val = {"text": "Old banner", "active": True}
        select_result = MagicMock()
        select_result.scalar_one_or_none.return_value = existing_val
        update_result = MagicMock()
        db.execute = AsyncMock(side_effect=[select_result, update_result])

        result = await update_platform_settings(
            db,
            announcement_banner="",
            announcement_active=False,
        )

        assert result["announcement_banner"] is None
        assert result["announcement_active"] is False

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_tc_and_announcement_together(self, mock_audit):
        """Updating both T&C and announcement in one call."""
        db = _mock_db()
        # T&C SELECT returns no existing
        tc_select = _make_execute_result([])
        tc_insert = MagicMock()
        # Announcement SELECT returns no existing
        ann_select = MagicMock()
        ann_select.scalar_one_or_none.return_value = None
        ann_insert = MagicMock()
        db.execute = AsyncMock(side_effect=[tc_select, tc_insert, ann_select, ann_insert])

        result = await update_platform_settings(
            db,
            terms_and_conditions="Terms v1",
            announcement_banner="Hello world",
            announcement_active=True,
        )

        assert result["terms_version"] == 1
        assert result["announcement_banner"] == "Hello world"
        assert result["announcement_active"] is True
        assert mock_audit.call_count == 2  # one for T&C, one for announcement


# ---------------------------------------------------------------------------
# Service: search_global_vehicles
# ---------------------------------------------------------------------------

class TestSearchGlobalVehicles:
    """Test search_global_vehicles service function."""

    @pytest.mark.asyncio
    async def test_no_results(self):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        result = await search_global_vehicles(db, "XYZ999")
        assert result["total"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_with_results(self):
        db = _mock_db()
        vid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        row = (
            vid, "ABC123", "Toyota", "Corolla", 2020, "White",
            "Sedan", "Petrol", "1.8L", 5, None, None, 50000, now, now,
        )
        db.execute = AsyncMock(return_value=_make_execute_result([row]))

        result = await search_global_vehicles(db, "ABC")
        assert result["total"] == 1
        assert result["results"][0]["rego"] == "ABC123"
        assert result["results"][0]["make"] == "Toyota"


# ---------------------------------------------------------------------------
# Service: delete_stale_vehicles
# ---------------------------------------------------------------------------

class TestDeleteStaleVehicles:
    """Test delete_stale_vehicles service function."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_deletes_stale_records(self, mock_audit):
        db = _mock_db()
        delete_result = MagicMock()
        delete_result.rowcount = 10
        db.execute = AsyncMock(return_value=delete_result)

        result = await delete_stale_vehicles(db, stale_days=180)
        assert result["deleted_count"] == 10
        assert "10" in result["message"]
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_no_stale_records(self, mock_audit):
        db = _mock_db()
        delete_result = MagicMock()
        delete_result.rowcount = 0
        db.execute = AsyncMock(return_value=delete_result)

        result = await delete_stale_vehicles(db, stale_days=365)
        assert result["deleted_count"] == 0


# ---------------------------------------------------------------------------
# Service: refresh_global_vehicle
# ---------------------------------------------------------------------------

class TestRefreshGlobalVehicle:
    """Test refresh_global_vehicle service function."""

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    async def test_vehicle_not_found(self, mock_audit):
        db = _mock_db()
        db.execute = AsyncMock(return_value=_make_execute_result([]))

        result = await refresh_global_vehicle(db, "NOTFOUND")
        assert result["vehicle"] is None
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._carjam_refresh_lookup", new_callable=AsyncMock)
    async def test_carjam_refresh_success(self, mock_carjam, mock_audit):
        """Successful Carjam refresh updates the record."""
        db = _mock_db()
        vid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        existing_row = (
            vid, "ABC123", "Toyota", "Corolla", 2020, "White",
            "Sedan", "Petrol", "1.8L", 5, None, None, 50000, now, now,
        )
        updated_row = (
            vid, "ABC123", "Toyota", "Corolla", 2020, "Silver",
            "Sedan", "Petrol", "1.8L", 5, None, None, 55000, now, now,
        )

        mock_carjam.return_value = {
            "make": "Toyota", "model": "Corolla", "year": 2020,
            "colour": "Silver", "body_type": "Sedan", "fuel_type": "Petrol",
            "engine_size": "1.8L", "num_seats": 5, "wof_expiry": None,
            "registration_expiry": None, "odometer_last_recorded": 55000,
        }

        # First execute: SELECT existing, second: UPDATE, third: SELECT refreshed
        db.execute = AsyncMock(side_effect=[
            _make_execute_result([existing_row]),
            MagicMock(),  # UPDATE
            _make_execute_result([updated_row]),
        ])

        result = await refresh_global_vehicle(db, "ABC123")

        assert result["vehicle"] is not None
        assert "refreshed" in result["message"].lower() or "Carjam" in result["message"]

    @pytest.mark.asyncio
    @patch("app.modules.admin.service.write_audit_log", new_callable=AsyncMock)
    @patch("app.modules.admin.service._carjam_refresh_lookup", new_callable=AsyncMock)
    async def test_carjam_refresh_failure_returns_existing(self, mock_carjam, mock_audit):
        """When Carjam fails, returns existing record with error message."""
        db = _mock_db()
        vid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        existing_row = (
            vid, "ABC123", "Toyota", "Corolla", 2020, "White",
            "Sedan", "Petrol", "1.8L", 5, None, None, 50000, now, now,
        )
        db.execute = AsyncMock(return_value=_make_execute_result([existing_row]))

        mock_carjam.side_effect = Exception("API timeout")

        result = await refresh_global_vehicle(db, "ABC123")

        assert result["vehicle"] is not None
        assert result["vehicle"]["rego"] == "ABC123"
        assert "failed" in result["message"].lower()
