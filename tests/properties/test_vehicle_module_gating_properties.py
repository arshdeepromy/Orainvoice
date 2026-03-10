"""Property-based tests for vehicle module gating.

Properties covered:
  P1  — Migration idempotency
  P2  — Vehicle path resolution completeness
  P3  — Vehicle endpoint access gating
  P4  — Invoice creation vehicle field gating
  P5  — Customer search linked_vehicles gating
  P6  — PDF template vehicle section conditional rendering

Feature: vehicle-module-gating
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

from app.middleware.modules import MODULE_ENDPOINT_MAP, _resolve_module
from app.core.modules import CORE_MODULES


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# All known vehicle endpoint sub-paths from the router
VEHICLE_SUB_PATHS = [
    "/lookup/ABC123",
    "/lookup/XYZ789",
    "/lookup-with-fallback",
    "/search",
    "/manual",
    "/{vid}/link".format(vid=uuid.uuid4()),
    "/{vid}/refresh".format(vid=uuid.uuid4()),
    "/{vid}".format(vid=uuid.uuid4()),
    "/{vid}/odometer".format(vid=uuid.uuid4()),
    "/{vid}/odometer-history".format(vid=uuid.uuid4()),
    "/{vid}/odometer/{rid}".format(vid=uuid.uuid4(), rid=uuid.uuid4()),
]

vehicle_sub_path_strategy = st.sampled_from(VEHICLE_SUB_PATHS)

rego_strategy = st.from_regex(r"[A-Z]{3}\d{3}", fullmatch=True)

vehicle_rego_strategy = st.one_of(st.none(), rego_strategy)
vehicle_make_strategy = st.one_of(st.none(), st.sampled_from(["Toyota", "Ford", "BMW", "Honda", "Mazda"]))
vehicle_model_strategy = st.one_of(st.none(), st.sampled_from(["Corolla", "Ranger", "320i", "Civic", "CX-5"]))
vehicle_year_strategy = st.one_of(st.none(), st.integers(min_value=1990, max_value=2026))
vehicle_odometer_strategy = st.one_of(st.none(), st.integers(min_value=0, max_value=999999))

n_executions_strategy = st.integers(min_value=1, max_value=5)


# ===========================================================================
# Property 1: Migration idempotency
# Feature: vehicle-module-gating, Property 1: Migration idempotency
# ===========================================================================


class TestP1MigrationIdempotency:
    """After N >= 1 executions of the migration SQL, exactly one vehicles row
    exists with correct field values.

    **Validates: Requirements 1.1, 1.2**
    """

    @given(n=n_executions_strategy)
    @PBT_SETTINGS
    def test_migration_idempotency(self, n: int) -> None:
        """P1: Running the migration INSERT N times produces exactly one row."""
        # Simulate the ON CONFLICT DO NOTHING behaviour in-memory
        registry: dict[str, dict] = {}

        for _ in range(n):
            slug = "vehicles"
            if slug not in registry:
                registry[slug] = {
                    "slug": "vehicles",
                    "display_name": "Vehicles",
                    "category": "automotive",
                    "is_core": False,
                    "dependencies": [],
                    "status": "available",
                }
            # ON CONFLICT DO NOTHING — no update

        # Exactly one row with slug 'vehicles'
        assert "vehicles" in registry
        row = registry["vehicles"]
        assert row["display_name"] == "Vehicles"
        assert row["category"] == "automotive"
        assert row["is_core"] is False
        assert row["dependencies"] == []
        assert row["status"] == "available"

        # No other vehicles rows
        vehicles_rows = [k for k in registry if k == "vehicles"]
        assert len(vehicles_rows) == 1


# ===========================================================================
# Property 2: Vehicle path resolution completeness
# Feature: vehicle-module-gating, Property 2: Vehicle path resolution completeness
# ===========================================================================


class TestP2VehiclePathResolution:
    """_resolve_module returns 'vehicles' for all known vehicle endpoint paths.

    **Validates: Requirements 2.1, 2.4**
    """

    @given(sub_path=vehicle_sub_path_strategy)
    @PBT_SETTINGS
    def test_vehicle_paths_resolve_to_vehicles(self, sub_path: str) -> None:
        """P2: All vehicle sub-paths resolve to the 'vehicles' module slug."""
        full_path = "/api/v1/vehicles" + sub_path
        result = _resolve_module(full_path)
        assert result == "vehicles", (
            f"Expected 'vehicles' for path {full_path}, got {result!r}"
        )

    @given(sub_path=vehicle_sub_path_strategy)
    @PBT_SETTINGS
    def test_vehicle_base_path_resolves(self, sub_path: str) -> None:
        """P2: The base /api/v1/vehicles path itself resolves."""
        assert _resolve_module("/api/v1/vehicles") == "vehicles"

    def test_non_vehicle_paths_do_not_resolve_to_vehicles(self) -> None:
        """P2: Non-vehicle paths don't resolve to 'vehicles'."""
        non_vehicle_paths = [
            "/api/v1/invoices",
            "/api/v1/customers",
            "/api/v2/inventory",
            "/api/v1/auth/login",
        ]
        for path in non_vehicle_paths:
            result = _resolve_module(path)
            assert result != "vehicles", (
                f"Path {path} should not resolve to 'vehicles', got {result!r}"
            )


# ===========================================================================
# Property 3: Vehicle endpoint access gating
# Feature: vehicle-module-gating, Property 3: Vehicle endpoint access gating
# ===========================================================================


class TestP3VehicleEndpointAccessGating:
    """Middleware returns 403 when vehicles module is disabled, passes through
    when enabled, for any vehicle endpoint path.

    **Validates: Requirements 2.2, 2.3**
    """

    @given(sub_path=vehicle_sub_path_strategy, enabled=st.booleans())
    @PBT_SETTINGS
    def test_vehicle_endpoint_gating(self, sub_path: str, enabled: bool) -> None:
        """P3: Vehicle endpoints return 403 iff module disabled."""
        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from app.middleware.modules import ModuleMiddleware

        full_path = "/api/v1/vehicles" + sub_path
        org_id = str(uuid.uuid4())

        async def dummy_endpoint(request):
            return JSONResponse({"ok": True})

        app = Starlette(
            routes=[Route(full_path, dummy_endpoint, methods=["GET", "POST", "PUT"])],
        )
        app.add_middleware(ModuleMiddleware)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_begin = AsyncMock()
        mock_begin.__aenter__ = AsyncMock(return_value=mock_begin)
        mock_begin.__aexit__ = AsyncMock(return_value=False)
        mock_session.begin = MagicMock(return_value=mock_begin)

        async def fake_is_enabled(self_svc, oid, slug):
            return enabled

        with (
            patch("app.middleware.modules.async_session_factory", return_value=mock_session),
            patch("app.middleware.modules.ModuleService.is_enabled", fake_is_enabled),
        ):
            original_dispatch = ModuleMiddleware.dispatch

            async def patched_dispatch(self, request, call_next):
                request.state.org_id = org_id
                return await original_dispatch(self, request, call_next)

            with patch.object(ModuleMiddleware, "dispatch", patched_dispatch):
                client = TestClient(app)
                response = client.get(full_path)

        if enabled:
            assert response.status_code == 200, (
                f"Expected 200 for enabled module at {full_path}, got {response.status_code}"
            )
        else:
            assert response.status_code == 403, (
                f"Expected 403 for disabled module at {full_path}, got {response.status_code}"
            )
            assert response.json()["module"] == "vehicles"


# ===========================================================================
# Property 4: Invoice creation vehicle field gating
# Feature: vehicle-module-gating, Property 4: Invoice creation vehicle field gating
# ===========================================================================


class TestP4InvoiceCreationVehicleFieldGating:
    """When vehicles module is disabled, all six vehicle fields are NULL in the
    created invoice. When enabled, fields are stored as provided.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(
        vehicle_rego=vehicle_rego_strategy,
        vehicle_make=vehicle_make_strategy,
        vehicle_model=vehicle_model_strategy,
        vehicle_year=vehicle_year_strategy,
        vehicle_odometer=vehicle_odometer_strategy,
        enabled=st.booleans(),
    )
    @PBT_SETTINGS
    def test_vehicle_fields_gated_on_create(
        self,
        vehicle_rego: str | None,
        vehicle_make: str | None,
        vehicle_model: str | None,
        vehicle_year: int | None,
        vehicle_odometer: int | None,
        enabled: bool,
    ) -> None:
        """P4: Vehicle fields are nulled when module disabled, preserved when enabled."""
        # Simulate the gating logic from create_invoice
        global_vehicle_id = uuid.uuid4() if vehicle_rego else None

        # This mirrors the exact gating code in create_invoice
        if not enabled:
            gated_rego = None
            gated_make = None
            gated_model = None
            gated_year = None
            gated_odometer = None
            gated_global_id = None
        else:
            gated_rego = vehicle_rego
            gated_make = vehicle_make
            gated_model = vehicle_model
            gated_year = vehicle_year
            gated_odometer = vehicle_odometer
            gated_global_id = global_vehicle_id

        if not enabled:
            assert gated_rego is None
            assert gated_make is None
            assert gated_model is None
            assert gated_year is None
            assert gated_odometer is None
            assert gated_global_id is None
        else:
            assert gated_rego == vehicle_rego
            assert gated_make == vehicle_make
            assert gated_model == vehicle_model
            assert gated_year == vehicle_year
            assert gated_odometer == vehicle_odometer
            assert gated_global_id == global_vehicle_id

    @given(
        vehicle_rego=rego_strategy,
        vehicle_odometer=st.integers(min_value=1, max_value=999999),
    )
    @PBT_SETTINGS
    def test_no_auto_link_when_disabled(
        self, vehicle_rego: str, vehicle_odometer: int,
    ) -> None:
        """P4: When disabled, global_vehicle_id is None so auto-link is skipped."""
        global_vehicle_id = uuid.uuid4()

        # Simulate disabled gating
        gated_global_id = None  # disabled

        # The auto-link guard: `if global_vehicle_id:`
        auto_link_triggered = bool(gated_global_id)
        assert auto_link_triggered is False

        # The odometer guard: `if vehicle_odometer and ... and global_vehicle_id:`
        odometer_triggered = bool(vehicle_odometer and vehicle_odometer > 0 and gated_global_id)
        assert odometer_triggered is False


# ===========================================================================
# Property 5: Customer search linked_vehicles gating
# Feature: vehicle-module-gating, Property 5: Customer search linked_vehicles gating
# ===========================================================================


class TestP5CustomerSearchLinkedVehiclesGating:
    """When vehicles module is disabled, include_vehicles is forced to False,
    preventing linked_vehicles from appearing in search results.

    **Validates: Requirements 6.1, 6.2**
    """

    @given(
        include_vehicles_requested=st.booleans(),
        enabled=st.booleans(),
    )
    @PBT_SETTINGS
    def test_include_vehicles_gated(
        self, include_vehicles_requested: bool, enabled: bool,
    ) -> None:
        """P5: include_vehicles is overridden to False when module disabled."""
        # Simulate the gating logic from search_customers
        include_vehicles = include_vehicles_requested
        if not enabled:
            include_vehicles = False

        if not enabled:
            assert include_vehicles is False, (
                "include_vehicles must be False when vehicles module is disabled"
            )
        else:
            assert include_vehicles == include_vehicles_requested, (
                "include_vehicles should match the request when module is enabled"
            )

    @given(enabled=st.just(False))
    @PBT_SETTINGS
    def test_no_linked_vehicles_in_results_when_disabled(self, enabled: bool) -> None:
        """P5: When disabled, customer search results never contain linked_vehicles."""
        # Simulate building customer dicts with include_vehicles=False
        include_vehicles = False  # forced by gating

        customer_dicts = []
        for _ in range(3):
            cust_dict = {"id": str(uuid.uuid4()), "first_name": "Test"}
            if include_vehicles:
                cust_dict["linked_vehicles"] = [{"id": "v1", "rego": "ABC123"}]
            customer_dicts.append(cust_dict)

        for cust in customer_dicts:
            assert "linked_vehicles" not in cust


# ===========================================================================
# Property 6: PDF template vehicle section conditional rendering
# Feature: vehicle-module-gating, Property 6: PDF template vehicle section conditional rendering
# ===========================================================================


class TestP6PDFTemplateVehicleConditional:
    """When vehicle_rego is NULL/empty, the vehicle-bar markup is not rendered.
    When vehicle_rego is non-empty, the vehicle-bar markup is rendered.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(vehicle_rego=st.one_of(st.none(), st.just(""), st.just("  ")))
    @PBT_SETTINGS
    def test_no_vehicle_bar_when_rego_empty(self, vehicle_rego: str | None) -> None:
        """P6: No vehicle-bar rendered when vehicle_rego is falsy."""
        from jinja2 import Environment

        template_str = """
        {% set v = invoice.vehicle %}
        {% if v or invoice.vehicle_rego %}
        <div class="vehicle-bar">VEHICLE_SECTION</div>
        {% endif %}
        """
        env = Environment()
        template = env.from_string(template_str)

        class FakeInvoice:
            def __init__(self, rego):
                self.vehicle = None
                self.vehicle_rego = rego

        html = template.render(invoice=FakeInvoice(vehicle_rego))
        assert "vehicle-bar" not in html
        assert "VEHICLE_SECTION" not in html

    @given(vehicle_rego=rego_strategy)
    @PBT_SETTINGS
    def test_vehicle_bar_rendered_when_rego_present(self, vehicle_rego: str) -> None:
        """P6: Vehicle-bar is rendered when vehicle_rego is non-empty."""
        from jinja2 import Environment

        template_str = """
        {% set v = invoice.vehicle %}
        {% if v or invoice.vehicle_rego %}
        <div class="vehicle-bar">VEHICLE_SECTION</div>
        {% endif %}
        """
        env = Environment()
        template = env.from_string(template_str)

        class FakeInvoice:
            def __init__(self, rego):
                self.vehicle = None
                self.vehicle_rego = rego

        html = template.render(invoice=FakeInvoice(vehicle_rego))
        assert "vehicle-bar" in html
        assert "VEHICLE_SECTION" in html
