"""Property-based tests for vehicle lookup caching (Task 8.6).

Property 15: Vehicle Lookup Cache-First with Accurate Counter
— verify cache hit → no API call + no counter increment;
  cache miss → API call + counter increment by 1.

**Validates: Requirements 14.1, 14.2, 14.3**

Uses Hypothesis to generate random rego strings, vehicle data, and org
state, then verifies the cache-first lookup behaviour:
  1. Cache hit: GlobalVehicle exists → no Carjam call, counter unchanged
  2. Cache miss: no GlobalVehicle → Carjam called once, result stored,
     counter incremented by exactly 1
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Ensure relationship models are loaded
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.integrations.carjam import CarjamVehicleData
from app.modules.vehicles.service import lookup_vehicle


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# NZ-style rego plates: 3 uppercase letters + 3 digits
rego_strategy = st.from_regex(r"[A-Z]{2,4}[0-9]{1,4}", fullmatch=True)

vehicle_makes = st.sampled_from([
    "Toyota", "Honda", "Mazda", "Ford", "Nissan", "Subaru",
    "Mitsubishi", "Suzuki", "Hyundai", "Kia",
])

vehicle_models = st.sampled_from([
    "Corolla", "Civic", "CX-5", "Ranger", "Leaf", "Outback",
    "Outlander", "Swift", "Tucson", "Sportage",
])

vehicle_colours = st.sampled_from([
    "White", "Black", "Silver", "Blue", "Red", "Grey", "Green",
])

vehicle_years = st.integers(min_value=1990, max_value=2025)

vehicle_seats = st.integers(min_value=2, max_value=8)

odometer_values = st.integers(min_value=0, max_value=500000)

initial_counter = st.integers(min_value=0, max_value=9999)


@st.composite
def global_vehicle_mock(draw, rego: str | None = None):
    """Generate a mock GlobalVehicle ORM object with random data."""
    gv = MagicMock()
    gv.id = uuid.uuid4()
    gv.rego = rego or draw(rego_strategy)
    gv.make = draw(vehicle_makes)
    gv.model = draw(vehicle_models)
    gv.year = draw(vehicle_years)
    gv.colour = draw(vehicle_colours)
    gv.body_type = draw(st.sampled_from(["Sedan", "Hatchback", "SUV", "Ute", "Van"]))
    gv.fuel_type = draw(st.sampled_from(["Petrol", "Diesel", "Hybrid", "Electric"]))
    gv.engine_size = draw(st.sampled_from(["1.3L", "1.5L", "1.8L", "2.0L", "2.5L", "3.0L"]))
    gv.num_seats = draw(vehicle_seats)
    gv.wof_expiry = date(draw(st.integers(2024, 2027)), draw(st.integers(1, 12)), draw(st.integers(1, 28)))
    gv.registration_expiry = date(draw(st.integers(2024, 2027)), draw(st.integers(1, 12)), draw(st.integers(1, 28)))
    gv.odometer_last_recorded = draw(odometer_values)
    gv.last_pulled_at = datetime(2025, 1, 15, tzinfo=timezone.utc)
    return gv


@st.composite
def carjam_vehicle_data(draw, rego: str):
    """Generate a CarjamVehicleData with random fields for a given rego."""
    return CarjamVehicleData(
        rego=rego,
        make=draw(vehicle_makes),
        model=draw(vehicle_models),
        year=draw(vehicle_years),
        colour=draw(vehicle_colours),
        body_type=draw(st.sampled_from(["Sedan", "Hatchback", "SUV", "Ute", "Van"])),
        fuel_type=draw(st.sampled_from(["Petrol", "Diesel", "Hybrid", "Electric"])),
        engine_size=draw(st.sampled_from(["1.3L", "1.5L", "1.8L", "2.0L", "2.5L"])),
        seats=draw(vehicle_seats),
        wof_expiry=str(date(draw(st.integers(2024, 2027)), draw(st.integers(1, 12)), draw(st.integers(1, 28)))),
        rego_expiry=str(date(draw(st.integers(2024, 2027)), draw(st.integers(1, 12)), draw(st.integers(1, 28)))),
        odometer=draw(odometer_values),
    )


@st.composite
def cache_hit_scenario(draw):
    """Generate a scenario where the rego exists in GlobalVehicle (cache hit)."""
    rego = draw(rego_strategy)
    gv = draw(global_vehicle_mock(rego=rego))
    counter_before = draw(initial_counter)
    return {
        "rego": rego,
        "global_vehicle": gv,
        "org_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "counter_before": counter_before,
    }


@st.composite
def cache_miss_scenario(draw):
    """Generate a scenario where the rego does NOT exist in GlobalVehicle (cache miss)."""
    rego = draw(rego_strategy)
    carjam_data = draw(carjam_vehicle_data(rego=rego))
    counter_before = draw(initial_counter)
    return {
        "rego": rego,
        "carjam_data": carjam_data,
        "org_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "counter_before": counter_before,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scalar_result(value):
    """Create a mock DB execute result returning value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _make_org(org_id, counter):
    """Build a mock Organisation with a given counter value."""
    org = MagicMock()
    org.id = org_id
    org.carjam_lookups_this_month = counter
    return org


# ---------------------------------------------------------------------------
# Property 15: Vehicle Lookup Cache-First with Accurate Counter
# ---------------------------------------------------------------------------


class TestVehicleLookupCacheFirstWithAccurateCounter:
    """Property 15: Vehicle Lookup Cache-First with Accurate Counter.

    **Validates: Requirements 14.1, 14.2, 14.3**

    For any vehicle registration lookup:
    - If the rego exists in the Global_Vehicle_DB, the result shall be
      returned without a Carjam API call and the organisation's
      carjam_lookups_this_month counter shall not increment.
    - If the rego does not exist, a Carjam API call shall be made, the
      result stored in Global_Vehicle_DB, and the counter shall increment
      by exactly 1.
    """

    @pytest.mark.asyncio
    @given(scenario=cache_hit_scenario())
    @PBT_SETTINGS
    async def test_cache_hit_no_api_call_no_counter_increment(self, scenario):
        """Cache hit: no Carjam API call and counter NOT incremented.

        **Validates: Requirements 14.1, 14.2**
        """
        gv = scenario["global_vehicle"]
        org = _make_org(scenario["org_id"], scenario["counter_before"])

        db = AsyncMock()
        # DB returns the cached GlobalVehicle
        db.execute = AsyncMock(return_value=_make_scalar_result(gv))

        redis = MagicMock()

        with patch("app.modules.vehicles.service.CarjamClient") as mock_client_cls:
            result = await lookup_vehicle(
                db, redis,
                rego=scenario["rego"],
                org_id=scenario["org_id"],
                user_id=scenario["user_id"],
            )

            # Carjam client should NOT have been instantiated or called
            mock_client_cls.assert_not_called()

        # Result comes from cache
        assert result["source"] == "cache"
        assert result["rego"] == scenario["rego"]

        # Org counter must NOT have changed
        assert org.carjam_lookups_this_month == scenario["counter_before"]

    @pytest.mark.asyncio
    @given(scenario=cache_miss_scenario())
    @PBT_SETTINGS
    async def test_cache_miss_api_called_counter_incremented_by_one(self, scenario):
        """Cache miss: Carjam API called once, result stored, counter += 1.

        **Validates: Requirements 14.1, 14.3**
        """
        org = _make_org(scenario["org_id"], scenario["counter_before"])
        carjam_data = scenario["carjam_data"]

        execute_calls = []

        async def _side_effect_execute(stmt, *args, **kwargs):
            execute_calls.append(stmt)
            if len(execute_calls) == 1:
                # First call: select GlobalVehicle → cache miss
                return _make_scalar_result(None)
            elif len(execute_calls) == 2:
                # Second call: select Organisation
                return _make_scalar_result(org)
            # Subsequent calls (audit log etc.)
            return MagicMock()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=_side_effect_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        redis = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.lookup_vehicle = AsyncMock(return_value=carjam_data)

        with patch(
            "app.modules.vehicles.service.CarjamClient",
            return_value=mock_client_instance,
        ):
            with patch(
                "app.modules.vehicles.service.write_audit_log",
                new_callable=AsyncMock,
            ):
                result = await lookup_vehicle(
                    db, redis,
                    rego=scenario["rego"],
                    org_id=scenario["org_id"],
                    user_id=scenario["user_id"],
                )

        # Result comes from Carjam
        assert result["source"] == "carjam"
        assert result["rego"] == scenario["rego"]

        # Carjam API was called exactly once with the correct rego
        mock_client_instance.lookup_vehicle.assert_called_once_with(
            scenario["rego"].upper().strip()
        )

        # Vehicle was stored in DB
        db.add.assert_called_once()

        # Counter incremented by exactly 1
        assert org.carjam_lookups_this_month == scenario["counter_before"] + 1
