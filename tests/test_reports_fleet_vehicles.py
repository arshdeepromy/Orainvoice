"""Unit tests for the fleet per-vehicle aggregate (reports-remediation A5).

These exercise ``app.modules.reports.service.get_fleet_report`` at the service
level (mocked DB session), asserting the additive ``vehicles[]`` breakdown
introduced by the reports-remediation spec:

  - ``vehicles`` is present in the response and shaped
    ``{rego, make, model, total_spend, last_service_date}`` (R6.1).
  - ``Σ vehicles[i].total_spend <= total_spend`` — the sum of per-vehicle spend
    never exceeds the fleet total (it excludes invoices with no rego) (R6.1).
  - ``vehicles`` is an empty list when no qualifying vehicles exist for the
    fleet in the period (R6.2).

Requirements: 6.1, 6.2

The service issues DB queries in this order for a fleet that has customers:
  1. fleet account            -> .scalar_one_or_none()
  2. customer IDs             -> .all()
  3. spend / outstanding sums -> .one()
  4. distinct vehicle count   -> .scalar()
  5. per-vehicle aggregate    -> .all()
A fleet with no customers short-circuits after query 2.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure all ORM models are loaded for relationship resolution
import app.modules.admin.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.reports.service import get_fleet_report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _mock_row(**kwargs) -> MagicMock:
    """A mock SQLAlchemy result row exposing the given named attributes."""
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def _fleet_result(fleet) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = fleet
    return result


def _customer_ids_result(customer_ids) -> MagicMock:
    result = MagicMock()
    # Service reads each row as r[0]; mimic (uuid,) tuples.
    result.all.return_value = [(cid,) for cid in customer_ids]
    return result


def _spend_result(total_spend: Decimal, outstanding: Decimal) -> MagicMock:
    result = MagicMock()
    result.one.return_value = _mock_row(total_spend=total_spend, outstanding=outstanding)
    return result


def _vehicle_count_result(count: int) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = count
    return result


def _vehicle_rows_result(rows) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFleetVehiclesAggregate:
    """get_fleet_report — additive vehicles[] breakdown (A5)."""

    @pytest.mark.asyncio
    async def test_vehicles_present_and_sum_within_total_spend(self):
        """vehicles[] is present, correctly shaped, and the per-vehicle spend
        sum does not exceed the fleet total_spend (R6.1)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        fleet_id = uuid.uuid4()

        fleet = MagicMock()
        fleet.name = "ABC Transport"

        # total_spend (15000) is larger than the rego'd spend (13000) because
        # some invoices in the period carry no vehicle_rego — this is exactly
        # why the sum-of-vehicles must be <= the fleet total.
        veh_rows = [
            _mock_row(
                rego="ABC123",
                make="Toyota",
                model="Hilux",
                total_spend=Decimal("9000.00"),
                last_service_date=date(2024, 6, 1),
            ),
            _mock_row(
                rego="XYZ789",
                make="Ford",
                model="Ranger",
                total_spend=Decimal("4000.00"),
                last_service_date=date(2024, 5, 15),
            ),
        ]

        db.execute.side_effect = [
            _fleet_result(fleet),
            _customer_ids_result([uuid.uuid4(), uuid.uuid4()]),
            _spend_result(Decimal("15000.00"), Decimal("2000.00")),
            _vehicle_count_result(2),
            _vehicle_rows_result(veh_rows),
        ]

        data = await get_fleet_report(
            db, org_id, fleet_id, date(2024, 1, 1), date(2024, 12, 31)
        )

        assert data is not None
        # vehicles[] present and shaped {rego, make, model, total_spend, last_service_date}
        assert "vehicles" in data
        assert len(data["vehicles"]) == 2
        assert data["vehicles"][0] == {
            "rego": "ABC123",
            "make": "Toyota",
            "model": "Hilux",
            "total_spend": Decimal("9000.00"),
            "last_service_date": date(2024, 6, 1),
        }
        for v in data["vehicles"]:
            assert set(v.keys()) == {
                "rego", "make", "model", "total_spend", "last_service_date"
            }

        # Σ vehicles[i].total_spend <= total_spend
        vehicles_total = sum((v["total_spend"] for v in data["vehicles"]), Decimal("0"))
        assert vehicles_total == Decimal("13000.00")
        assert vehicles_total <= data["total_spend"]

    @pytest.mark.asyncio
    async def test_vehicles_sum_equals_total_when_all_have_rego(self):
        """When every qualifying invoice carries a rego, the per-vehicle sum
        equals the fleet total (boundary of the <= property) (R6.1)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        fleet_id = uuid.uuid4()

        fleet = MagicMock()
        fleet.name = "Equal Fleet"

        veh_rows = [
            _mock_row(
                rego="AAA111", make="Mazda", model="BT-50",
                total_spend=Decimal("7000.00"), last_service_date=date(2024, 3, 1),
            ),
            _mock_row(
                rego="BBB222", make=None, model=None,
                total_spend=Decimal("3000.00"), last_service_date=date(2024, 2, 1),
            ),
        ]

        db.execute.side_effect = [
            _fleet_result(fleet),
            _customer_ids_result([uuid.uuid4()]),
            _spend_result(Decimal("10000.00"), Decimal("0")),
            _vehicle_count_result(2),
            _vehicle_rows_result(veh_rows),
        ]

        data = await get_fleet_report(
            db, org_id, fleet_id, date(2024, 1, 1), date(2024, 12, 31)
        )

        vehicles_total = sum((v["total_spend"] for v in data["vehicles"]), Decimal("0"))
        assert vehicles_total == data["total_spend"] == Decimal("10000.00")
        assert vehicles_total <= data["total_spend"]
        # Nullable make/model are preserved as None.
        assert data["vehicles"][1]["make"] is None
        assert data["vehicles"][1]["model"] is None

    @pytest.mark.asyncio
    async def test_empty_vehicles_when_no_qualifying_invoices(self):
        """Fleet has customers but no qualifying vehicles (no rego'd invoices
        in the period) -> empty vehicles list (R6.2)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        fleet_id = uuid.uuid4()

        fleet = MagicMock()
        fleet.name = "No Vehicles Fleet"

        db.execute.side_effect = [
            _fleet_result(fleet),
            _customer_ids_result([uuid.uuid4()]),
            _spend_result(Decimal("0"), Decimal("0")),
            _vehicle_count_result(0),
            _vehicle_rows_result([]),
        ]

        data = await get_fleet_report(
            db, org_id, fleet_id, date(2024, 1, 1), date(2024, 12, 31)
        )

        assert data is not None
        assert data["vehicles"] == []
        # Trivially, the empty sum is within the (zero) total spend.
        vehicles_total = sum((v["total_spend"] for v in data["vehicles"]), Decimal("0"))
        assert vehicles_total <= data["total_spend"]

    @pytest.mark.asyncio
    async def test_empty_vehicles_when_fleet_has_no_customers(self):
        """Fleet with no customers short-circuits and returns an empty
        vehicles list (R6.2)."""
        db = _mock_db()
        org_id = uuid.uuid4()
        fleet_id = uuid.uuid4()

        fleet = MagicMock()
        fleet.name = "Empty Fleet"

        db.execute.side_effect = [
            _fleet_result(fleet),
            _customer_ids_result([]),
        ]

        data = await get_fleet_report(
            db, org_id, fleet_id, date(2024, 1, 1), date(2024, 12, 31)
        )

        assert data is not None
        assert data["vehicles"] == []
        assert data["total_spend"] == Decimal("0")
