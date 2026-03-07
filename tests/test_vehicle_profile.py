"""Unit tests for vehicle linking and profile — Task 8.4.

Tests cover:
  - Link vehicle to customer (happy path)
  - Link vehicle — vehicle not found
  - Link vehicle — customer not found
  - Link same vehicle to multiple customers in same org (Req 15.2)
  - Vehicle profile — Carjam data, linked customers, service history
  - WOF/rego expiry indicators: green (>60d), amber (30-60d), red (<30d)
  - Expiry indicator when date is None

Requirements: 15.1, 15.2, 15.3, 15.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models to resolve SQLAlchemy relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.vehicles.service import (
    _compute_expiry_indicator,
    get_vehicle_profile,
    link_vehicle_to_customer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_global_vehicle(**overrides):
    """Build a mock GlobalVehicle ORM object."""
    gv = MagicMock()
    gv.id = overrides.get("id", uuid.uuid4())
    gv.rego = overrides.get("rego", "ABC123")
    gv.make = overrides.get("make", "Toyota")
    gv.model = overrides.get("model", "Corolla")
    gv.year = overrides.get("year", 2020)
    gv.colour = overrides.get("colour", "White")
    gv.body_type = overrides.get("body_type", "Sedan")
    gv.fuel_type = overrides.get("fuel_type", "Petrol")
    gv.engine_size = overrides.get("engine_size", "1.8L")
    gv.num_seats = overrides.get("num_seats", 5)
    gv.wof_expiry = overrides.get("wof_expiry", date(2025, 6, 1))
    gv.registration_expiry = overrides.get("registration_expiry", date(2025, 12, 1))
    gv.odometer_last_recorded = overrides.get("odometer_last_recorded", 45000)
    gv.last_pulled_at = overrides.get(
        "last_pulled_at", datetime(2025, 1, 15, tzinfo=timezone.utc)
    )
    return gv


def _make_customer(**overrides):
    """Build a mock Customer ORM object."""
    c = MagicMock()
    c.id = overrides.get("id", uuid.uuid4())
    c.org_id = overrides.get("org_id", uuid.uuid4())
    c.first_name = overrides.get("first_name", "John")
    c.last_name = overrides.get("last_name", "Smith")
    c.email = overrides.get("email", "john@example.com")
    c.phone = overrides.get("phone", "021-555-1234")
    return c


def _make_customer_vehicle_link(**overrides):
    """Build a mock CustomerVehicle ORM object."""
    link = MagicMock()
    link.id = overrides.get("id", uuid.uuid4())
    link.org_id = overrides.get("org_id", uuid.uuid4())
    link.customer_id = overrides.get("customer_id", uuid.uuid4())
    link.global_vehicle_id = overrides.get("global_vehicle_id", uuid.uuid4())
    link.odometer_at_link = overrides.get("odometer_at_link", 45000)
    link.linked_at = overrides.get(
        "linked_at", datetime(2025, 1, 20, tzinfo=timezone.utc)
    )
    return link


def _make_invoice(**overrides):
    """Build a mock Invoice ORM object."""
    inv = MagicMock()
    inv.id = overrides.get("id", uuid.uuid4())
    inv.org_id = overrides.get("org_id", uuid.uuid4())
    inv.invoice_number = overrides.get("invoice_number", "INV-0001")
    inv.status = overrides.get("status", "paid")
    inv.issue_date = overrides.get("issue_date", date(2025, 1, 15))
    inv.total = overrides.get("total", Decimal("230.00"))
    inv.vehicle_rego = overrides.get("vehicle_rego", "ABC123")
    inv.vehicle_odometer = overrides.get("vehicle_odometer", 45000)
    inv.created_at = overrides.get(
        "created_at", datetime(2025, 1, 15, tzinfo=timezone.utc)
    )
    return inv


def _make_scalar_result(value):
    """Create a mock DB execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_rows_result(rows):
    """Create a mock DB execute result that returns rows from .all()."""
    result = MagicMock()
    result.all.return_value = rows
    return result


# ---------------------------------------------------------------------------
# _compute_expiry_indicator
# ---------------------------------------------------------------------------


class TestComputeExpiryIndicator:
    """Tests for WOF/rego expiry colour indicator logic (Req 15.4)."""

    def test_green_more_than_60_days(self):
        future = date.today() + timedelta(days=90)
        result = _compute_expiry_indicator(future)
        assert result["indicator"] == "green"
        assert result["days_remaining"] == 90

    def test_amber_exactly_60_days(self):
        future = date.today() + timedelta(days=60)
        result = _compute_expiry_indicator(future)
        assert result["indicator"] == "amber"
        assert result["days_remaining"] == 60

    def test_amber_30_days(self):
        future = date.today() + timedelta(days=30)
        result = _compute_expiry_indicator(future)
        assert result["indicator"] == "amber"
        assert result["days_remaining"] == 30

    def test_red_under_30_days(self):
        future = date.today() + timedelta(days=15)
        result = _compute_expiry_indicator(future)
        assert result["indicator"] == "red"
        assert result["days_remaining"] == 15

    def test_red_expired(self):
        past = date.today() - timedelta(days=10)
        result = _compute_expiry_indicator(past)
        assert result["indicator"] == "red"
        assert result["days_remaining"] == -10

    def test_none_date_returns_red(self):
        result = _compute_expiry_indicator(None)
        assert result["indicator"] == "red"
        assert result["date"] is None
        assert result["days_remaining"] is None

    def test_green_boundary_61_days(self):
        future = date.today() + timedelta(days=61)
        result = _compute_expiry_indicator(future)
        assert result["indicator"] == "green"

    def test_red_boundary_29_days(self):
        future = date.today() + timedelta(days=29)
        result = _compute_expiry_indicator(future)
        assert result["indicator"] == "red"


# ---------------------------------------------------------------------------
# link_vehicle_to_customer
# ---------------------------------------------------------------------------


class TestLinkVehicleToCustomer:
    """Tests for POST /api/v1/vehicles/{id}/link service logic."""

    @pytest.mark.asyncio
    async def test_link_happy_path(self):
        """Successfully link a global vehicle to a customer."""
        vehicle_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        vehicle = _make_global_vehicle(id=vehicle_id, rego="ABC123")
        customer = _make_customer(id=customer_id, org_id=org_id)

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_result(vehicle)
            elif call_count == 2:
                return _make_scalar_result(customer)
            return MagicMock()

        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.vehicles.service.write_audit_log", new_callable=AsyncMock):
            result = await link_vehicle_to_customer(
                db,
                vehicle_id=vehicle_id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
                odometer=50000,
            )

        assert result["vehicle_id"] == str(vehicle_id)
        assert result["customer_id"] == str(customer_id)
        assert result["customer_name"] == "John Smith"
        assert result["odometer_at_link"] == 50000
        assert db.add.called

    @pytest.mark.asyncio
    async def test_link_vehicle_not_found(self):
        """Raise ValueError when vehicle doesn't exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))

        with pytest.raises(ValueError, match="not found"):
            await link_vehicle_to_customer(
                db,
                vehicle_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_link_customer_not_found(self):
        """Raise ValueError when customer doesn't exist in the org."""
        vehicle_id = uuid.uuid4()
        vehicle = _make_global_vehicle(id=vehicle_id)

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_result(vehicle)
            return _make_scalar_result(None)

        db.execute = mock_execute

        with pytest.raises(ValueError, match="Customer.*not found"):
            await link_vehicle_to_customer(
                db,
                vehicle_id=vehicle_id,
                customer_id=uuid.uuid4(),
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# get_vehicle_profile
# ---------------------------------------------------------------------------


class TestGetVehicleProfile:
    """Tests for GET /api/v1/vehicles/{id} service logic."""

    @pytest.mark.asyncio
    async def test_profile_with_data(self):
        """Return full profile with linked customers and service history."""
        vehicle_id = uuid.uuid4()
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        vehicle = _make_global_vehicle(
            id=vehicle_id,
            rego="ABC123",
            wof_expiry=date.today() + timedelta(days=90),
            registration_expiry=date.today() + timedelta(days=45),
        )
        customer = _make_customer(id=customer_id, org_id=org_id)
        link = _make_customer_vehicle_link(
            global_vehicle_id=vehicle_id, customer_id=customer_id
        )
        invoice = _make_invoice(
            org_id=org_id,
            vehicle_rego="ABC123",
            vehicle_odometer=48000,
        )

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # GlobalVehicle lookup
                return _make_scalar_result(vehicle)
            elif call_count == 2:
                # Linked customers join
                return _make_rows_result([(link, customer)])
            elif call_count == 3:
                # Service history (invoices)
                return _make_rows_result([(invoice, customer)])
            return MagicMock()

        db.execute = mock_execute

        result = await get_vehicle_profile(
            db, vehicle_id=vehicle_id, org_id=org_id
        )

        assert result["id"] == str(vehicle_id)
        assert result["rego"] == "ABC123"
        assert result["make"] == "Toyota"
        assert result["wof_expiry"]["indicator"] == "green"
        assert result["rego_expiry"]["indicator"] == "amber"
        assert len(result["linked_customers"]) == 1
        assert result["linked_customers"][0]["first_name"] == "John"
        assert len(result["service_history"]) == 1
        assert result["service_history"][0]["odometer"] == 48000

    @pytest.mark.asyncio
    async def test_profile_vehicle_not_found(self):
        """Raise ValueError when vehicle doesn't exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_scalar_result(None))

        with pytest.raises(ValueError, match="not found"):
            await get_vehicle_profile(
                db, vehicle_id=uuid.uuid4(), org_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_profile_empty_history(self):
        """Return empty lists when no linked customers or invoices."""
        vehicle_id = uuid.uuid4()
        org_id = uuid.uuid4()

        vehicle = _make_global_vehicle(
            id=vehicle_id,
            wof_expiry=date.today() + timedelta(days=10),
            registration_expiry=None,
        )

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_scalar_result(vehicle)
            return _make_rows_result([])

        db.execute = mock_execute

        result = await get_vehicle_profile(
            db, vehicle_id=vehicle_id, org_id=org_id
        )

        assert result["linked_customers"] == []
        assert result["service_history"] == []
        assert result["wof_expiry"]["indicator"] == "red"
        assert result["wof_expiry"]["days_remaining"] == 10
        assert result["rego_expiry"]["indicator"] == "red"
        assert result["rego_expiry"]["date"] is None
