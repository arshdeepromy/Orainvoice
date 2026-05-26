"""Integration tests for the vehicle-data-isolation promotion trigger sites — Task 3.3.

Covers Task 3.3 of the ``vehicle-data-isolation`` spec: regression tests for
the two promotion trigger sites that live inside ``app/modules/vehicles/service.py``:

  - ``vehicles.link`` — exercised through ``link_vehicle_to_customer``
  - ``vehicles.record_odometer_reading`` — exercised through
    ``record_odometer_reading``

Each test asserts the five invariants enumerated in the design's
"Test Strategy → Integration Tests" section:

  1. ``org_vehicles`` row created for the calling org
  2. ``customer_vehicles`` link migrated to ``org_vehicle_id``
     (where applicable — only the link trigger creates a link)
  3. ``global_vehicles`` Customer_Driven_Fields unchanged
  4. ``org_vehicles`` Customer_Driven_Fields hold the new value
     (or the values copied at promotion when the trigger does not
     itself update those fields, e.g. the link trigger)
  5. One ``vehicle.promote`` audit-log row with the matching
     ``trigger_site`` string

The tests use AsyncMock-based DB sessions following the project pattern
already established in ``tests/test_vehicle_data_isolation.py`` and the
other ``tests/integration/`` files (see ``test_invoice_lifecycle.py``).
The advisory-lock SQL, the ``OrgVehicle`` existence check, and the audit
log call are routed through ``db.execute`` / ``write_audit_log`` so
mocking covers both ``promote_vehicle`` and the calling trigger site
without requiring a live database.

Requirements: 15.2
Design: Test Strategy → Integration Tests
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy resolves all relationships at module load.
# The Task 4.4 invoice tests below trigger SQL compilation against the
# ``Invoice`` mapper (via ``str(stmt)`` inside the routing side-effect),
# which forces SQLAlchemy to resolve relationship targets such as
# ``Supplier``, ``PartsCatalogue``, ``Quote`` etc. — so we eagerly import
# every dependency module here to avoid ``InvalidRequestError`` when those
# mappers fail to initialise on first use.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.banking.models  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.catalogue.fluid_oil_models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.ledger.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.quotes.models  # noqa: F401
import app.modules.service_types.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401

from app.modules.vehicles.models import (
    CustomerVehicle,
    OdometerReading,
    OrgVehicle,
)
from app.modules.vehicles.service import (
    link_vehicle_to_customer,
    record_odometer_reading,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_global_vehicle(**overrides):
    """Build a mock ``GlobalVehicle`` carrying every field referenced by
    ``promote_vehicle`` and the trigger sites under test.

    Pre-populated with realistic CarJam_Owned_Spec_Field values plus
    Customer_Driven_Field values that survive Read_Fallback.
    """
    gv = MagicMock()
    gv.id = overrides.get("id", uuid.uuid4())
    gv.rego = overrides.get("rego", "ABC123")

    # CarJam_Owned_Spec_Fields
    gv.make = overrides.get("make", "Toyota")
    gv.model = overrides.get("model", "Corolla")
    gv.year = overrides.get("year", 2020)
    gv.colour = overrides.get("colour", "White")
    gv.body_type = overrides.get("body_type", "Sedan")
    gv.fuel_type = overrides.get("fuel_type", "Petrol")
    gv.engine_size = overrides.get("engine_size", "1.8L")
    gv.num_seats = overrides.get("num_seats", 5)
    gv.registration_expiry = overrides.get("registration_expiry", date(2025, 12, 1))
    gv.vin = overrides.get("vin", "JT1234567890ABCDE")
    gv.chassis = overrides.get("chassis", "CHASSIS-12345")
    gv.engine_no = overrides.get("engine_no", "ENG-67890")
    gv.transmission = overrides.get("transmission", "Automatic")
    gv.country_of_origin = overrides.get("country_of_origin", "Japan")
    gv.number_of_owners = overrides.get("number_of_owners", 2)
    gv.vehicle_type = overrides.get("vehicle_type", "Passenger")
    gv.power_kw = overrides.get("power_kw", 100)
    gv.tare_weight = overrides.get("tare_weight", 1300)
    gv.gross_vehicle_mass = overrides.get("gross_vehicle_mass", 1800)
    gv.date_first_registered_nz = overrides.get(
        "date_first_registered_nz", date(2020, 3, 15)
    )
    gv.plate_type = overrides.get("plate_type", "Standard")
    gv.submodel = overrides.get("submodel", "GX")
    gv.second_colour = overrides.get("second_colour", None)

    # Customer_Driven_Fields (preserved at moment of promotion via
    # Read_Fallback continuity — Req 10.3).
    gv.odometer_last_recorded = overrides.get("odometer_last_recorded", 45000)
    gv.service_due_date = overrides.get("service_due_date", date(2025, 8, 1))
    gv.wof_expiry = overrides.get("wof_expiry", date(2025, 6, 1))
    gv.cof_expiry = overrides.get("cof_expiry", None)
    gv.inspection_type = overrides.get("inspection_type", "wof")

    return gv


def _snapshot_customer_driven_fields(vehicle):
    """Capture the five Customer_Driven_Fields for pre/post comparison."""
    return {
        "odometer_last_recorded": vehicle.odometer_last_recorded,
        "service_due_date": vehicle.service_due_date,
        "wof_expiry": vehicle.wof_expiry,
        "cof_expiry": vehicle.cof_expiry,
        "inspection_type": vehicle.inspection_type,
    }


def _added_of_type(db, cls):
    """Return the single instance of ``cls`` added to ``db``, or fail."""
    matches = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], cls)
    ]
    assert len(matches) == 1, (
        f"expected exactly one {cls.__name__} added to the session; "
        f"got {len(matches)}"
    )
    return matches[0]


def _promote_audit_calls(mock_audit):
    """Return the list of ``write_audit_log`` calls whose action is ``vehicle.promote``."""
    return [
        c for c in mock_audit.await_args_list
        if c.kwargs.get("action") == "vehicle.promote"
    ]


# ---------------------------------------------------------------------------
# Test 1 — vehicles.link trigger site
# ---------------------------------------------------------------------------


class TestVehiclesLinkToCustomerPromotesFirstTime:
    """Exercises ``link_vehicle_to_customer`` against a ``GlobalVehicle``-backed
    rego that the calling org has never linked before.

    Validates that the ``vehicles.link`` trigger site fires a single
    promotion via ``promote_vehicle``, creates the ``customer_vehicles``
    link via ``org_vehicle_id`` (not ``global_vehicle_id``), and leaves
    the shared ``global_vehicles`` Customer_Driven_Fields untouched.
    """

    @pytest.mark.asyncio
    async def test_vehicles_link_to_customer_promotes_first_time(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="LNK001")
        gv_pre = _snapshot_customer_driven_fields(gv)

        # Customer record looked up by link_vehicle_to_customer.
        customer = MagicMock()
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Sam"
        customer.last_name = "Smith"

        # Wire up ``db.execute`` to return — in order:
        #   1. GlobalVehicle SELECT (id == vehicle_id)        → gv
        #   2. Customer SELECT                                → customer
        #   3. promote_vehicle: pg_advisory_xact_lock         → no-op
        #   4. promote_vehicle: OrgVehicle existence SELECT   → None
        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            gv_result,
            customer_result,
            no_op,           # advisory lock
            ov_check,        # OrgVehicle existence check
        ])

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await link_vehicle_to_customer(
                db,
                vehicle_id=gv.id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
                odometer=42_000,
                ip_address="127.0.0.1",
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link created via org_vehicle_id --
        cv = _added_of_type(db, CustomerVehicle)
        assert cv.org_vehicle_id == ov.id, (
            "link must point at the freshly-promoted OrgVehicle"
        )
        assert cv.global_vehicle_id is None, (
            "link must clear global_vehicle_id so vehicle_link_check holds"
        )
        assert cv.org_id == org_id
        assert cv.customer_id == customer_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "vehicles.link must not mutate global_vehicles Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the value --
        # link_vehicle_to_customer does not itself write Customer_Driven_Fields,
        # so the OrgVehicle holds the values copied from global_vehicles at the
        # moment of promotion (preserving Read_Fallback continuity, Req 10.3).
        for field in (
            "odometer_last_recorded",
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
            )

        # -- Invariant 5: one vehicle.promote audit-log row with matching trigger_site --
        promote_calls = _promote_audit_calls(mock_audit)
        assert len(promote_calls) == 1, (
            "promote_vehicle must emit exactly one vehicle.promote audit-log row"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        # trigger_site lives in after_value per design's Audit Logging section.
        assert promote_kwargs["after_value"]["trigger_site"] == "vehicles.link"
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Test 2 — vehicles.record_odometer_reading trigger site
# ---------------------------------------------------------------------------


class TestVehiclesRecordOdometerPromotesFirstTime:
    """Exercises ``record_odometer_reading`` with ``org_id != None`` and
    ``source != 'carjam'`` (the customer-driven flow) against a
    ``GlobalVehicle``-backed rego the calling org has never recorded
    against.

    Validates that the ``vehicles.record_odometer_reading`` trigger site
    fires a single promotion, bumps ``org_vehicles.odometer_last_recorded``,
    leaves ``global_vehicles.odometer_last_recorded`` untouched, and
    inserts the history row keyed by ``global_vehicle_id`` (Req 11.1).
    """

    @pytest.mark.asyncio
    async def test_vehicles_record_odometer_promotes_first_time(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="ODO001", odometer_last_recorded=45_000)
        gv_pre = _snapshot_customer_driven_fields(gv)

        # ``record_odometer_reading`` issues, in order:
        #   1. GlobalVehicle SELECT                            → gv
        #   2. db.add(OdometerReading) ; db.flush()            (no execute call)
        #   3. promote_vehicle: pg_advisory_xact_lock          → no-op
        #   4. promote_vehicle: OrgVehicle existence SELECT    → None
        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            gv_result,
            no_op,           # advisory lock
            ov_check,        # OrgVehicle existence check
        ])

        new_reading_km = 60_000

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await record_odometer_reading(
                db,
                global_vehicle_id=gv.id,
                reading_km=new_reading_km,
                source="invoice",   # customer-driven (not "carjam")
                recorded_by=user_id,
                org_id=org_id,
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False

        # -- Invariant 2: ``customer_vehicles`` link migration is N/A here --
        # ``record_odometer_reading`` does not create or touch any
        # ``customer_vehicles`` rows; the (where applicable) clause in
        # the design's invariant explicitly carves this out.
        added_links = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_links == [], (
            "record_odometer_reading must not create or modify customer_vehicles"
        )

        # The OdometerReading history row is still keyed by global_vehicle_id
        # (Req 11.1, 11.2): the cache target moves to org_vehicles, but
        # the history row itself stays on the shared cache key.
        history_row = _added_of_type(db, OdometerReading)
        assert history_row.global_vehicle_id == gv.id, (
            "odometer_readings history row must remain keyed by global_vehicle_id"
        )
        assert history_row.reading_km == new_reading_km
        assert history_row.source == "invoice"
        assert history_row.org_id == org_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "record_odometer_reading must not mutate global_vehicles "
            "Customer_Driven_Fields for customer-driven flows; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )
        # Specifically the odometer cache field on the shared row must
        # not have moved with the new reading.
        assert gv.odometer_last_recorded == gv_pre["odometer_last_recorded"]

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the new value --
        # The fresh OrgVehicle's ``odometer_last_recorded`` reflects the new
        # reading (the customer-driven write). The other Customer_Driven_Fields
        # are copied from global_vehicles at promotion time.
        assert ov.odometer_last_recorded == new_reading_km, (
            "OrgVehicle.odometer_last_recorded must reflect the new reading"
        )
        for field in (
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
            )
        # And the result payload reports the cache update.
        assert result["vehicle_odometer_updated"] is True
        assert result["reading_km"] == new_reading_km
        assert result["global_vehicle_id"] == str(gv.id)

        # -- Invariant 5: one vehicle.promote audit-log row with matching trigger_site --
        promote_calls = _promote_audit_calls(mock_audit)
        assert len(promote_calls) == 1, (
            "promote_vehicle must emit exactly one vehicle.promote audit-log row"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert (
            promote_kwargs["after_value"]["trigger_site"]
            == "vehicles.record_odometer_reading"
        )
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Task 4.4 — Invoice service trigger sites
# ---------------------------------------------------------------------------
#
# The invoice trigger tests below exercise ``app/modules/invoices/service.py``
# at two trigger sites:
#
#   - ``invoices.create`` — exercised through ``create_invoice``
#   - ``invoices.update`` — exercised through ``update_invoice``
#
# ``create_invoice`` and ``update_invoice`` are large functions that issue
# many ``db.execute`` calls covering customer/org lookups, currency
# validation, line-item handling, audit logs, and vehicle resolution.
# The tests below use a *callable* ``db.execute`` side-effect that
# inspects each query (via SQL-string sniffing or compiled-clause
# attributes) and returns the appropriate mock — the same approach used
# in ``tests/property/test_org_detail_properties.py``. Heavy machinery
# (``ModuleService.is_enabled``, ``write_audit_log``, the GST-compliance
# helper, etc.) is patched out so the test focuses on the promotion
# trigger and its five invariants.
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


from app.modules.admin.models import GlobalVehicle, Organisation
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.invoices.service import create_invoice, update_invoice


def _make_customer(*, customer_id, org_id):
    """Build a mock Customer row for ``select(Customer)`` lookups."""
    c = MagicMock(spec=Customer)
    c.id = customer_id
    c.org_id = org_id
    c.first_name = "Pat"
    c.last_name = "Tester"
    c.email = "pat@example.com"
    c.phone = "021-555-0100"
    c.address = "1 Test Street"
    c.company_name = None
    return c


def _make_organisation(*, org_id):
    """Build a mock Organisation with vehicles module enabled."""
    org = MagicMock(spec=Organisation)
    org.id = org_id
    org.name = "Pat's Workshop"
    org.settings = {
        "gst_percentage": 15,
        "invoice_prefix": "INV-",
        "default_due_days": 0,
        "multi_currency_enabled": False,
        "allowed_currencies": ["NZD"],
    }
    # Stripe payment-intent shortcut: no connect account → skipped.
    org.stripe_connect_account_id = None
    return org


def _result_for(value):
    """Build a ``scalar_one_or_none``-shaped mock result."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    r.scalar.return_value = value
    return r


def _empty_scalars_result():
    """Build a ``scalars().all() -> []`` mock result."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = []
    return r


def _make_invoice_router(
    *,
    customer,
    org,
    gv,
    ov_existence_returns,
    cv_existence_returns,
    invoice_for_update=None,
):
    """Build a callable ``db.execute`` side-effect that routes queries
    to the right mock result by inspecting the compiled SQL.

    ``ov_existence_returns`` is a list (used as a stack) of values to
    return for each ``select(OrgVehicle)`` existence/limit check —
    matching the order the call sites issue them. The first None
    forces ``promote_vehicle`` to insert a new row; subsequent calls
    after the row is added to the session are stubbed to short-circuit
    the resolver into the org branch.

    ``cv_existence_returns`` is the value returned for the existing-
    customer-vehicle-link check (a ``CustomerVehicle`` row or ``None``).

    ``invoice_for_update`` is the ``Invoice`` instance returned by the
    initial ``update_invoice`` lookup (used by the update-flow tests).
    """
    ov_stack = list(ov_existence_returns)
    state = {"ov_inserted": None}

    def _route(stmt, *args, **kwargs):
        sql_text = str(stmt).lower()

        # Advisory lock: returns nothing meaningful.
        if "pg_advisory_xact_lock" in sql_text:
            return _result_for(None)

        # ModuleService internal query (org → settings/plan), if it ever
        # falls through to the DB rather than the patched is_enabled.
        if "trade_categories" in sql_text or "trade_families" in sql_text:
            return _result_for(None)

        # Customer lookup (initial validation in create_invoice + various
        # follow-up customer reads).
        if "from customers" in sql_text and "where" in sql_text:
            return _result_for(customer)

        # Organisation lookup.
        if "from organisations" in sql_text:
            return _result_for(org)

        # Invoice lookup at the top of update_invoice.
        if (
            invoice_for_update is not None
            and "from invoices" in sql_text
            and "where" in sql_text
        ):
            return _result_for(invoice_for_update)

        # Line-item ORDER BY for the final _invoice_to_dict serialisation.
        if "from line_items" in sql_text:
            return _empty_scalars_result()

        # GlobalVehicle lookup (both _resolve_vehicle_type's first SELECT
        # and ``record_odometer_reading``'s opener).
        if "from global_vehicles" in sql_text:
            return _result_for(gv)

        # OrgVehicle lookups: there are two distinct call sites —
        #   (a) ``_resolve_vehicle_type``'s rego-keyed limit(1) check, and
        #   (b) ``promote_vehicle``'s existence SELECT inside the lock.
        # Both consume from the same stack so the test wires them in call
        # order. Once an OrgVehicle has been inserted via db.add (state
        # tracking below), all *subsequent* OrgVehicle lookups return that
        # row to make ``promote_vehicle`` idempotent — which is what
        # happens for real after the first promotion in a transaction.
        if "from org_vehicles" in sql_text:
            if state["ov_inserted"] is not None:
                return _result_for(state["ov_inserted"])
            if ov_stack:
                return _result_for(ov_stack.pop(0))
            return _result_for(None)

        # CustomerVehicle existence check (auto-link duplicate guard).
        if "from customer_vehicles" in sql_text and "select" in sql_text:
            return _result_for(cv_existence_returns)

        # UPDATE customer_vehicles (link migration).
        if "update customer_vehicles" in sql_text:
            return _result_for(None)

        # Default: everything else (invoice_sequences, etc.) → empty.
        return _result_for(None)

    return _route, state


def _make_db_for_invoice_test(router, *, ov_capture):
    """Build an ``AsyncMock`` DB session wired to ``router`` and a list
    that captures every object passed to ``db.add``.
    """

    db = AsyncMock()

    captured = ov_capture

    def _add(obj):
        captured.append(obj)
        # The promote_vehicle code path expects the inserted OrgVehicle to
        # come back from a follow-up SELECT inside the same transaction.
        # We capture the first OrgVehicle added and feed it back through
        # the router state so subsequent ``from org_vehicles`` queries
        # short-circuit to the just-inserted row (idempotent path).
        if isinstance(obj, OrgVehicle):
            # pre-assign an id so downstream code that reads ov.id works
            # without needing a real refresh round-trip.
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            router_state = getattr(_add, "_router_state", None)
            if router_state is not None:
                router_state["ov_inserted"] = obj
        if isinstance(obj, Invoice):
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            # invoice_data_json default for downstream serialisation.
            if getattr(obj, "invoice_data_json", None) is None:
                obj.invoice_data_json = {}

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db, _add


# ---------------------------------------------------------------------------
# Test 3 — invoices.create trigger site
# ---------------------------------------------------------------------------


class TestInvoiceCreatePromotesFirstTime:
    """Exercises ``create_invoice`` against a ``GlobalVehicle``-backed rego
    that the calling org has never written against.

    Validates the five invariants from the design's Test Strategy →
    Integration Tests section, with particular emphasis on the per-task
    Verify line: ``global_vehicles.odometer_last_recorded`` is unchanged
    after the first invoice writes a new odometer value, while
    ``org_vehicles.odometer_last_recorded`` for the calling org reflects
    the new value.
    """

    @pytest.mark.asyncio
    async def test_invoice_create_promotes_first_time(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="INV001", odometer_last_recorded=45_000)
        gv_pre = _snapshot_customer_driven_fields(gv)

        customer = _make_customer(customer_id=customer_id, org_id=org_id)
        org = _make_organisation(org_id=org_id)

        # ``ov_existence_returns`` feeds OrgVehicle SELECT results in
        # call order:
        #   1. _resolve_vehicle_type @L875 (inspection_type) — None
        #   2. _resolve_vehicle_type @L946 (auto-link)        — None
        #   3. promote_vehicle existence check                — None
        # After the new OrgVehicle is added to the session, every
        # subsequent ``from org_vehicles`` SELECT short-circuits to it
        # via the router state (mirroring real idempotent behaviour).
        router, router_state = _make_invoice_router(
            customer=customer,
            org=org,
            gv=gv,
            ov_existence_returns=[None, None, None],
            cv_existence_returns=None,  # no pre-existing link
        )

        captured: list = []
        db, _add = _make_db_for_invoice_test(router, ov_capture=captured)
        _add._router_state = router_state
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: router(stmt, *a, **kw))

        # Customer-driven payload values that must land on the OrgVehicle.
        new_odometer = 60_000
        new_service_due = date(2026, 6, 1)
        new_wof = date(2026, 9, 1)
        new_cof = date(2026, 11, 1)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                global_vehicle_id=gv.id,
                vehicle_rego=gv.rego,
                vehicle_make=gv.make,
                vehicle_model=gv.model,
                vehicle_year=gv.year,
                vehicle_odometer=new_odometer,
                vehicle_service_due_date=new_service_due,
                vehicle_wof_expiry_date=new_wof,
                vehicle_cof_expiry_date=new_cof,
                status="draft",
                line_items_data=[],
                ip_address="127.0.0.1",
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link created via org_vehicle_id --
        cv = _added_of_type(db, CustomerVehicle)
        assert cv.org_vehicle_id == ov.id, (
            "auto-link must point at the freshly-promoted OrgVehicle"
        )
        assert cv.global_vehicle_id is None, (
            "link must clear global_vehicle_id so vehicle_link_check holds"
        )
        assert cv.org_id == org_id
        assert cv.customer_id == customer_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "invoices.create must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )
        # In particular, the per-task verify line for Task 4.4: the
        # odometer cache on global_vehicles must remain unchanged after
        # the first invoice writes a new odometer value.
        assert gv.odometer_last_recorded == gv_pre["odometer_last_recorded"]

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the
        #    payload values for the calling org --
        assert ov.odometer_last_recorded == new_odometer, (
            "OrgVehicle.odometer_last_recorded must reflect the invoice's "
            "new reading (the customer-driven write)"
        )
        assert ov.service_due_date == new_service_due
        assert ov.wof_expiry == new_wof
        assert ov.cof_expiry == new_cof

        # The history flow is preserved: exactly one OdometerReading row
        # inserted with source="invoice" — proving record_odometer_reading
        # ran end-to-end and not just the OrgVehicle direct-write fallback.
        history_row = _added_of_type(db, OdometerReading)
        assert history_row.global_vehicle_id == gv.id
        assert history_row.reading_km == new_odometer
        assert history_row.source == "invoice"
        assert history_row.org_id == org_id

        # -- Invariant 5: one vehicle.promote audit-log row with
        #    matching trigger_site --
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert len(promote_calls) == 1, (
            "create_invoice must emit exactly one vehicle.promote audit-log "
            "row even when promote_vehicle is called multiple times "
            "(idempotent)"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert promote_kwargs["after_value"]["trigger_site"] == "invoices.create"
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Test 4 — invoices.update trigger site (Customer_Driven_Field change)
# ---------------------------------------------------------------------------


def _make_invoice_for_update(*, invoice_id, org_id, customer_id, status="draft"):
    """Build a mock Invoice instance for update_invoice's initial lookup."""
    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id
    inv.org_id = org_id
    inv.customer_id = customer_id
    inv.status = status
    inv.invoice_number = None
    inv.is_gst_locked = False
    inv.vehicle_rego = None
    inv.notes_internal = None
    inv.notes_customer = None
    inv.due_date = None
    inv.discount_type = None
    inv.discount_value = None
    inv.invoice_data_json = {}
    return inv


class TestInvoiceUpdatePromotesWhenCustomerDrivenFieldChanges:
    """Exercises ``update_invoice`` against a ``GlobalVehicle``-backed rego
    when an update changes a Customer_Driven_Field.

    Asserts the five invariants from the design's Test Strategy →
    Integration Tests, plus the contrast case: when only non-vehicle
    fields change (e.g. ``notes_internal``), promotion does NOT fire.
    """

    @pytest.mark.asyncio
    async def test_invoice_update_promotes_when_customer_driven_field_changes(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="UPD001")
        gv_pre = _snapshot_customer_driven_fields(gv)

        customer = _make_customer(customer_id=customer_id, org_id=org_id)
        org = _make_organisation(org_id=org_id)
        invoice = _make_invoice_for_update(
            invoice_id=invoice_id, org_id=org_id, customer_id=customer_id,
        )

        # update_invoice issues OrgVehicle SELECTs in this order for our
        # Customer_Driven_Field flow:
        #   1. _resolve_vehicle_type's rego-keyed limit(1) — None
        #   2. promote_vehicle's existence check inside the lock — None
        # Subsequent calls are short-circuited via router state.
        router, router_state = _make_invoice_router(
            customer=customer,
            org=org,
            gv=gv,
            ov_existence_returns=[None, None],
            cv_existence_returns=None,
            invoice_for_update=invoice,
        )

        captured: list = []
        db, _add = _make_db_for_invoice_test(router, ov_capture=captured)
        _add._router_state = router_state
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: router(stmt, *a, **kw))

        new_wof = date(2027, 1, 15)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice_id,
                updates={
                    "global_vehicle_id": gv.id,
                    "vehicle_wof_expiry_date": new_wof,
                },
                ip_address="127.0.0.1",
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False

        # -- Invariant 2: customer_vehicles link migration is exposed via
        #    a bulk UPDATE rather than a new row added; verify the bulk
        #    UPDATE was issued by checking db.execute was called with
        #    a statement that compiles to "UPDATE customer_vehicles".
        update_cv_calls = [
            c for c in db.execute.await_args_list
            if "update customer_vehicles" in str(c.args[0]).lower()
        ]
        assert len(update_cv_calls) >= 1, (
            "update_invoice must issue a bulk UPDATE on customer_vehicles "
            "to migrate any link still pointing at global_vehicle_id"
        )

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "invoices.update must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )

        # -- Invariant 4: org_vehicles wof_expiry holds the new value --
        assert ov.wof_expiry == new_wof, (
            "OrgVehicle.wof_expiry must reflect the invoice update payload"
        )
        # Other Customer_Driven_Fields are copied at promotion time and
        # not changed by this update — they keep gv values.
        assert ov.service_due_date == gv.service_due_date
        assert ov.cof_expiry == gv.cof_expiry
        assert ov.odometer_last_recorded == gv.odometer_last_recorded

        # -- Invariant 5: one vehicle.promote audit-log row with
        #    matching trigger_site --
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert len(promote_calls) == 1
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert promote_kwargs["after_value"]["trigger_site"] == "invoices.update"
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)

    @pytest.mark.asyncio
    async def test_invoice_update_does_not_promote_when_only_non_vehicle_fields_change(self):
        """Contrast case (per Task 4.4 description): when only non-vehicle
        fields change (notes), promotion must NOT fire and no OrgVehicle
        is added.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="NOOP01")
        gv_pre = _snapshot_customer_driven_fields(gv)

        customer = _make_customer(customer_id=customer_id, org_id=org_id)
        org = _make_organisation(org_id=org_id)
        invoice = _make_invoice_for_update(
            invoice_id=invoice_id, org_id=org_id, customer_id=customer_id,
        )

        router, router_state = _make_invoice_router(
            customer=customer,
            org=org,
            gv=gv,
            ov_existence_returns=[],
            cv_existence_returns=None,
            invoice_for_update=invoice,
        )

        captured: list = []
        db, _add = _make_db_for_invoice_test(router, ov_capture=captured)
        _add._router_state = router_state
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: router(stmt, *a, **kw))

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice_id,
                updates={
                    "notes_internal": "internal note revision",
                    "notes_customer": "customer-facing note",
                },
                ip_address="127.0.0.1",
            )

        # No OrgVehicle inserted, no link added, no promotion audit row.
        added_ov = [obj for obj in captured if isinstance(obj, OrgVehicle)]
        assert added_ov == [], (
            "non-vehicle update must not add an OrgVehicle row"
        )
        added_cv = [obj for obj in captured if isinstance(obj, CustomerVehicle)]
        assert added_cv == [], (
            "non-vehicle update must not create any customer_vehicles links"
        )
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert promote_calls == [], (
            "non-vehicle update must not emit any vehicle.promote audit rows"
        )
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre


# ---------------------------------------------------------------------------
# Test 5 — invoices.update COF parity (Task 4.3 verify-line carry-over)
# ---------------------------------------------------------------------------


class TestInvoiceUpdateWritesCofExpiryToOrgVehicle:
    """COF parity test pulled forward from Task 4.3's verify line.

    Asserts that ``PUT /api/v1/invoices/{id}`` with only
    ``vehicle_cof_expiry_date`` set:

      (a) is accepted by the schema (no 422),
      (b) the new COF lands on ``org_vehicles.cof_expiry``,
      (c) ``global_vehicles.cof_expiry`` is byte-identical to its
          pre-edit value,
      (d) promotion fired (audit row with
          ``trigger_site='invoices.update'``).
    """

    def test_update_invoice_request_schema_accepts_only_vehicle_cof_expiry_date(self):
        """Schema-level assertion (a): ``vehicle_cof_expiry_date`` is a
        valid request field on its own — no 422 from Pydantic.
        """
        from app.modules.invoices.schemas import UpdateInvoiceRequest

        payload = UpdateInvoiceRequest.model_validate(
            {"vehicle_cof_expiry_date": "2027-03-15"},
        )
        assert payload.vehicle_cof_expiry_date == date(2027, 3, 15)

    @pytest.mark.asyncio
    async def test_invoice_update_writes_cof_expiry_to_org_vehicle(self):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        invoice_id = uuid.uuid4()

        gv = _make_global_vehicle(
            rego="COF001",
            cof_expiry=date(2025, 6, 1),
        )
        gv_pre = _snapshot_customer_driven_fields(gv)
        gv_cof_pre = gv.cof_expiry

        customer = _make_customer(customer_id=customer_id, org_id=org_id)
        org = _make_organisation(org_id=org_id)
        invoice = _make_invoice_for_update(
            invoice_id=invoice_id, org_id=org_id, customer_id=customer_id,
        )

        # Same wiring as the wof-expiry case — _resolve_vehicle_type then
        # promote_vehicle existence check, then router state takes over.
        router, router_state = _make_invoice_router(
            customer=customer,
            org=org,
            gv=gv,
            ov_existence_returns=[None, None],
            cv_existence_returns=None,
            invoice_for_update=invoice,
        )

        captured: list = []
        db, _add = _make_db_for_invoice_test(router, ov_capture=captured)
        _add._router_state = router_state
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: router(stmt, *a, **kw))

        new_cof = date(2027, 3, 15)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice_id,
                updates={
                    "global_vehicle_id": gv.id,
                    "vehicle_cof_expiry_date": new_cof,
                },
                ip_address="127.0.0.1",
            )

        # (b) New COF lands on the OrgVehicle.
        ov = _added_of_type(db, OrgVehicle)
        assert ov.cof_expiry == new_cof, (
            "vehicle_cof_expiry_date must land on org_vehicles.cof_expiry "
            "after promotion"
        )
        assert ov.org_id == org_id
        assert ov.rego == gv.rego

        # (c) global_vehicles.cof_expiry is byte-identical to pre-edit.
        assert gv.cof_expiry == gv_cof_pre, (
            "global_vehicles.cof_expiry must be unchanged after the edit"
        )
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre

        # (d) Promotion fired with trigger_site='invoices.update'.
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert len(promote_calls) == 1
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert promote_kwargs["after_value"]["trigger_site"] == "invoices.update"
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Test 6 — kiosk.v2_check_in trigger site (Task 5.2)
# ---------------------------------------------------------------------------
#
# Exercises ``app/modules/kiosk/service.py::kiosk_check_in_v2`` against a
# ``GlobalVehicle``-backed rego that the calling org has never recorded an
# odometer reading against. Per Task 5.2's spec note we patch
# ``_ensure_vehicle_linked`` (the link path is a separate promotion site
# already covered by ``TestVehiclesLinkToCustomerPromotesFirstTime``) and
# focus the assertions on the *odometer-write* promotion path:
#
#   - ``promote_vehicle(..., trigger_site="kiosk.v2_check_in")`` is called
#     after the ``OdometerReading`` history row is inserted.
#   - The history row stays keyed by ``global_vehicle_id`` (Req 11.1).
#   - ``ov.odometer_last_recorded`` is bumped, ``gv.odometer_last_recorded``
#     is left untouched.
#   - Exactly one ``vehicle.promote`` audit-log row is emitted with
#     ``trigger_site='kiosk.v2_check_in'`` (Req 14.1).
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


class TestKioskV2CheckInPromotesFirstTime:
    """Exercises ``kiosk_check_in_v2`` against a ``GlobalVehicle``-backed
    rego the calling org has never recorded against.

    Asserts the five invariants from the design's Test Strategy →
    Integration Tests section and shows the kiosk path produces a single
    ``vehicle.promote`` audit row with ``trigger_site='kiosk.v2_check_in'``.
    """

    @pytest.mark.asyncio
    async def test_kiosk_v2_check_in_promotes_first_time(self):
        from app.modules.kiosk.schemas import (
            KioskCheckInRequestV2,
            KioskVehicleEntry,
        )
        from app.modules.kiosk.service import kiosk_check_in_v2

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        new_customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="KSK001", odometer_last_recorded=45_000)
        gv_pre = _snapshot_customer_driven_fields(gv)

        new_odometer = 60_000

        request = KioskCheckInRequestV2(
            first_name="Alice",
            last_name="Wonder",
            phone="0279876543",
            email=None,
            vehicles=[
                KioskVehicleEntry(
                    global_vehicle_id=str(gv.id),
                    odometer_km=new_odometer,
                ),
            ],
            existing_customer_id=None,
        )

        # ``kiosk_check_in_v2`` issues, in order:
        #   1. ``_search_customer_by_phone`` (no existing_customer_id and
        #      no phone match) → None — falls through to ``create_customer``
        #      (patched below so it doesn't itself execute SQL).
        #   2. ``_ensure_vehicle_linked`` (patched — link path is exercised
        #      by ``TestVehiclesLinkToCustomerPromotesFirstTime``).
        #   3. ``promote_vehicle``: select(GlobalVehicle) → gv (the kiosk
        #      site does not pass ``source_record``, so ``promote_vehicle``
        #      loads it itself).
        #   4. ``promote_vehicle``: pg_advisory_xact_lock → no-op.
        #   5. ``promote_vehicle``: select(OrgVehicle) existence → None.
        phone_search = MagicMock()
        phone_search.scalar_one_or_none.return_value = None

        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            phone_search,
            gv_result,
            no_op,           # advisory lock
            ov_check,        # OrgVehicle existence check
        ])

        customer_dict = {
            "id": str(new_customer_id),
            "first_name": "Alice",
            "last_name": "Wonder",
            "phone": "0279876543",
        }

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=customer_dict,
        ), patch(
            "app.modules.kiosk.service._ensure_vehicle_linked",
            new_callable=AsyncMock,
        ) as mock_ensure_linked, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await kiosk_check_in_v2(
                db,
                org_id=org_id,
                user_id=user_id,
                data=request,
                ip_address="10.0.0.1",
            )

        # ``_ensure_vehicle_linked`` was patched — the link path is a
        # separate promotion site exercised by
        # ``TestVehiclesLinkToCustomerPromotesFirstTime``. This test
        # focuses on the odometer path's promotion firing.
        mock_ensure_linked.assert_awaited_once()

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link migration --
        # Link creation/migration is handled inside ``_ensure_vehicle_linked``
        # → ``link_vehicle_to_customer``, which is patched out here per
        # Task 5.2's instruction to focus on the odometer path. The kiosk
        # service therefore must not directly add any ``CustomerVehicle``
        # rows in this test.
        added_links = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_links == [], (
            "kiosk_check_in_v2 must not add customer_vehicles rows directly; "
            "all link work flows through _ensure_vehicle_linked"
        )

        # The ``OdometerReading`` history row remains keyed by
        # ``global_vehicle_id`` (Req 11.1, 11.2): the cache target moves
        # to ``org_vehicles`` but the history row stays on the shared
        # cache key, with ``source='kiosk'``.
        history_row = _added_of_type(db, OdometerReading)
        assert history_row.global_vehicle_id == gv.id
        assert history_row.reading_km == new_odometer
        assert history_row.source == "kiosk"
        assert history_row.recorded_by == user_id
        assert history_row.org_id == org_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "kiosk.v2_check_in must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )
        # In particular, the per-task verify line for Task 5.1: the
        # odometer cache on global_vehicles must remain unchanged after
        # the kiosk write.
        assert gv.odometer_last_recorded == gv_pre["odometer_last_recorded"]

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the new value --
        # The kiosk path bumps ``odometer_last_recorded`` only — the
        # other Customer_Driven_Fields are copied from ``global_vehicles``
        # at promotion time (preserving Read_Fallback continuity, Req 10.3).
        assert ov.odometer_last_recorded == new_odometer, (
            "OrgVehicle.odometer_last_recorded must reflect the new kiosk reading"
        )
        for field in (
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
            )

        # Response payload sanity-check — the kiosk path returned the
        # newly-created customer and reports the linked vehicle count.
        assert result.vehicles_linked == 1
        assert result.is_new_customer is True
        assert result.customer_first_name == "Alice"

        # -- Invariant 5: one vehicle.promote audit-log row with matching trigger_site --
        promote_calls = _promote_audit_calls(mock_audit)
        assert len(promote_calls) == 1, (
            "kiosk.v2_check_in must emit exactly one vehicle.promote "
            "audit-log row — _ensure_vehicle_linked is patched, so only "
            "the odometer path's promote_vehicle call fires here"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert (
            promote_kwargs["after_value"]["trigger_site"]
            == "kiosk.v2_check_in"
        )
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Task 6.3 — Fleet portal trigger sites
# ---------------------------------------------------------------------------
#
# Exercises the two fleet-portal promotion trigger sites:
#
#   - ``fleet_portal.record_odometer`` — exercised through
#     ``app/modules/fleet_portal/services/vehicle_service.py::log_odometer_reading``
#   - ``fleet_portal.update_field`` — exercised through
#     ``app/modules/fleet_portal/router.py::edit_vehicle``
#
# Both tests assert the five invariants from the design's Test Strategy
# → Integration Tests section:
#
#   1. ``org_vehicles`` row created for the calling org
#   2. ``customer_vehicles`` link migrated to ``org_vehicle_id``
#      (where applicable)
#   3. ``global_vehicles`` Customer_Driven_Fields unchanged
#   4. ``org_vehicles`` Customer_Driven_Fields hold the new value
#   5. One ``vehicle.promote`` audit-log row with the matching
#      ``trigger_site`` string
#
# A third test (``test_fleet_portal_record_odometer_does_not_raise_attribute_error``)
# is the regression for the column-name fix in Task 6.1: it asserts the
# odometer-row write uses ``reading_km`` (not the legacy ``odometer_km``)
# and that ``source='manual'`` satisfies the
# ``ck_odometer_readings_source`` CHECK constraint.
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.schemas import VehicleEditRequest


def _make_customer_vehicle_link(*, cv_id, org_id, customer_id, gv=None, ov=None):
    """Build a mock ``CustomerVehicle`` row for the fleet-portal CV
    lookup. Either ``gv`` or ``ov`` may be set (matching the either-or
    ``vehicle_link_check`` invariant the production schema enforces).
    """
    cv = MagicMock(spec=CustomerVehicle)
    cv.id = cv_id
    cv.org_id = org_id
    cv.customer_id = customer_id
    cv.global_vehicle = gv
    cv.org_vehicle = ov
    cv.global_vehicle_id = gv.id if gv is not None else None
    cv.org_vehicle_id = ov.id if ov is not None else None
    cv.fleet_checklist_template_id = None
    return cv


def _make_fleet_ctx(
    *,
    org_id,
    portal_account_id,
    role="fleet_admin",
    fleet_account_id=None,
):
    """Build a ``FleetSessionCtx`` carrying just enough state for the
    fleet-portal trigger sites under test.
    """
    return FleetSessionCtx(
        org_id=org_id,
        portal_account_id=portal_account_id,
        portal_user_role=role,
        fleet_account_id=fleet_account_id or uuid.uuid4(),
        email="fleet-admin@example.com",
        session_id=uuid.uuid4(),
        is_impersonation=False,
    )


# ---------------------------------------------------------------------------
# Test 7 — fleet_portal.record_odometer trigger site
# ---------------------------------------------------------------------------


class TestFleetPortalRecordOdometerPromotesFirstTime:
    """Exercises ``log_odometer_reading`` against a ``GlobalVehicle``-backed
    rego the calling fleet has never recorded against.

    Validates the five invariants from the design's Test Strategy →
    Integration Tests section, plus the per-task verify line: the
    audit-log row carries ``trigger_site='fleet_portal.record_odometer'``.
    """

    @pytest.mark.asyncio
    async def test_fleet_portal_record_odometer_promotes_first_time(self):
        from app.modules.fleet_portal.services.vehicle_service import (
            log_odometer_reading,
        )

        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        cv_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="FLT001", odometer_last_recorded=45_000)
        gv_pre = _snapshot_customer_driven_fields(gv)

        cv = _make_customer_vehicle_link(
            cv_id=cv_id,
            org_id=org_id,
            customer_id=customer_id,
            gv=gv,
            ov=None,
        )

        ctx = _make_fleet_ctx(org_id=org_id, portal_account_id=portal_account_id)

        # ``log_odometer_reading`` issues, in order:
        #   1. db.execute(base.where(CustomerVehicle.id == ...))          → cv
        #   2. db.execute(select(func.max(OdometerReading.reading_km))    → None
        #   3. promote_vehicle: pg_advisory_xact_lock                     → no-op
        #   4. promote_vehicle: OrgVehicle existence SELECT               → None
        cv_result = MagicMock()
        cv_result.scalars.return_value.first.return_value = cv

        max_result = MagicMock()
        max_result.scalar.return_value = None

        advisory_result = MagicMock()
        advisory_result.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            cv_result,
            max_result,
            advisory_result,
            ov_check,
        ])

        # ``_vehicle_query_for_session`` is patched to a stub select-like
        # object — the actual SQL is not exercised here; the test focuses
        # on the promotion + history-row + cache-write flow.
        mock_base = MagicMock()
        mock_base.where = MagicMock(return_value=MagicMock())

        new_value_km = 60_000

        with patch(
            "app.modules.fleet_portal.services.vehicle_service._vehicle_query_for_session",
            new_callable=AsyncMock,
            return_value=mock_base,
        ), patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            response = await log_odometer_reading(
                db,
                ctx=ctx,
                customer_vehicle_id=cv_id,
                value_km=new_value_km,
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link migration --
        # ``log_odometer_reading`` does not itself migrate the link;
        # the CV row stays where it was, and ``edit_vehicle`` (Task 6.2)
        # owns the migration on the field-update path. The "where
        # applicable" clause in the design's invariant 2 explicitly
        # carves this out — no ``CustomerVehicle`` rows are added
        # directly here.
        added_links = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_links == [], (
            "log_odometer_reading must not create or modify customer_vehicles rows"
        )

        # The OdometerReading history row remains keyed by
        # ``global_vehicle_id`` (Req 11.1, 11.2) and carries the
        # value passed in plus ``source='manual'`` (the only allowed
        # source for a fleet user logging by hand).
        history_row = _added_of_type(db, OdometerReading)
        assert history_row.global_vehicle_id == gv.id, (
            "odometer_readings history row must remain keyed by global_vehicle_id"
        )
        assert history_row.reading_km == new_value_km
        assert history_row.source == "manual"
        assert history_row.recorded_by == portal_account_id
        assert history_row.org_id == org_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "fleet_portal.record_odometer must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )
        # Specifically the odometer cache field on the shared row must
        # not have moved with the new fleet-portal reading.
        assert gv.odometer_last_recorded == gv_pre["odometer_last_recorded"]

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the new value --
        # The fleet-portal odometer path bumps ``odometer_last_recorded``
        # only — the other Customer_Driven_Fields are copied from
        # ``global_vehicles`` at promotion time (Req 10.3).
        assert ov.odometer_last_recorded == new_value_km, (
            "OrgVehicle.odometer_last_recorded must reflect the new fleet "
            "portal reading"
        )
        for field in (
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
            )

        # Response payload sanity-check.
        assert response.customer_vehicle_id == cv_id
        assert response.odometer_km == new_value_km

        # -- Invariant 5: one vehicle.promote audit-log row with matching trigger_site --
        promote_calls = _promote_audit_calls(mock_audit)
        assert len(promote_calls) == 1, (
            "fleet_portal.record_odometer must emit exactly one "
            "vehicle.promote audit-log row"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == portal_account_id
        assert (
            promote_kwargs["after_value"]["trigger_site"]
            == "fleet_portal.record_odometer"
        )
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Test 8 — fleet portal record_odometer column-name regression (Task 6.1)
# ---------------------------------------------------------------------------


class TestFleetPortalRecordOdometerDoesNotRaiseAttributeError:
    """Regression test for the column-name fix in Task 6.1.

    Before the fix, the fleet-portal helper referenced a non-existent
    ``OdometerReading.odometer_km`` column (the actual column on the
    model is ``reading_km``). Both the ``select(func.max(...))``
    aggregation and the ``OdometerReading(...)`` constructor would
    raise ``AttributeError`` / ``TypeError`` as soon as a fleet user
    logged an odometer reading.

    Asserts:
      (a) no ``AttributeError`` / ``TypeError`` is raised when
          ``log_odometer_reading`` runs end-to-end,
      (b) the inserted ``odometer_readings`` row has ``reading_km``
          equal to the value passed in,
      (c) the row's ``source`` column equals ``"manual"`` and
          satisfies the ``ck_odometer_readings_source`` CHECK
          constraint (which permits only ``carjam/manual/invoice/kiosk``).
    """

    @pytest.mark.asyncio
    async def test_fleet_portal_record_odometer_does_not_raise_attribute_error(self):
        from app.modules.fleet_portal.services.vehicle_service import (
            log_odometer_reading,
        )

        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        cv_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="FLT002", odometer_last_recorded=10_000)
        cv = _make_customer_vehicle_link(
            cv_id=cv_id,
            org_id=org_id,
            customer_id=customer_id,
            gv=gv,
            ov=None,
        )

        ctx = _make_fleet_ctx(org_id=org_id, portal_account_id=portal_account_id)

        cv_result = MagicMock()
        cv_result.scalars.return_value.first.return_value = cv

        max_result = MagicMock()
        max_result.scalar.return_value = None

        advisory_result = MagicMock()
        advisory_result.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            cv_result,
            max_result,
            advisory_result,
            ov_check,
        ])

        mock_base = MagicMock()
        mock_base.where = MagicMock(return_value=MagicMock())

        # The "value passed in" the regression assertion (b) refers to.
        passed_value_km = 25_000

        # Allowed source labels per the
        # ``ck_odometer_readings_source`` CHECK constraint defined on
        # ``app/modules/vehicles/models.py`` (mirrors the migration).
        ALLOWED_SOURCES = {"carjam", "manual", "invoice", "kiosk"}

        with patch(
            "app.modules.fleet_portal.services.vehicle_service._vehicle_query_for_session",
            new_callable=AsyncMock,
            return_value=mock_base,
        ), patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            # Assertion (a): the helper runs end-to-end without raising
            # AttributeError or TypeError. ``pytest`` would surface
            # either as the test failure cause; we explicitly catch the
            # two error classes the pre-fix code raised so the failure
            # message is readable when this regression resurfaces.
            try:
                await log_odometer_reading(
                    db,
                    ctx=ctx,
                    customer_vehicle_id=cv_id,
                    value_km=passed_value_km,
                )
            except (AttributeError, TypeError) as exc:
                pytest.fail(
                    "log_odometer_reading must not raise AttributeError or "
                    "TypeError — the OdometerReading column is named "
                    f"reading_km (NOT odometer_km). Underlying error: {exc!r}"
                )

        # Assertion (b): the inserted row has ``reading_km`` equal to
        # the value passed in.
        history_row = _added_of_type(db, OdometerReading)
        assert history_row.reading_km == passed_value_km, (
            "OdometerReading.reading_km must equal the value passed in; "
            f"expected {passed_value_km}, got {history_row.reading_km!r}"
        )
        # Defence-in-depth: the legacy attribute name must not exist on
        # the inserted instance — if a future refactor reintroduces it,
        # this assertion fires immediately.
        assert not any(
            "odometer_km" == k for k in history_row.__dict__
        ), (
            "OdometerReading instances must not carry the legacy "
            "odometer_km attribute — the model column is reading_km"
        )

        # Assertion (c): ``source='manual'`` and satisfies the
        # ``ck_odometer_readings_source`` CHECK constraint.
        assert history_row.source == "manual", (
            "fleet-portal manual entries must use source='manual' to "
            "satisfy the ck_odometer_readings_source CHECK constraint"
        )
        assert history_row.source in ALLOWED_SOURCES, (
            "history row source must be one of "
            f"{sorted(ALLOWED_SOURCES)} per the CHECK constraint; "
            f"got {history_row.source!r}"
        )


# ---------------------------------------------------------------------------
# Test 9 — fleet_portal.update_field trigger site
# ---------------------------------------------------------------------------


class TestFleetPortalServiceDueUpdatePromotesFirstTime:
    """Exercises ``edit_vehicle`` (the router function in
    ``app/modules/fleet_portal/router.py``) against a
    ``GlobalVehicle``-backed rego for which the calling fleet has never
    written a Customer_Driven_Field.

    The test patches the FastAPI dependencies and calls the route
    handler directly so the test exercises the same promotion +
    rebind-target + link-migration code path that real requests would
    take. The payload sets ``service_due_date`` (a Customer_Driven_Field
    in the per-role allowlist for ``fleet_admin``).

    Validates the five invariants from the design's Test Strategy →
    Integration Tests, plus the per-task verify line: the audit-log
    row carries ``trigger_site='fleet_portal.update_field'``.
    """

    @pytest.mark.asyncio
    async def test_fleet_portal_service_due_update_promotes_first_time(self):
        from app.modules.fleet_portal.router import edit_vehicle

        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        cv_id = uuid.uuid4()

        # ``edit_vehicle`` uses ``isinstance(target, GlobalVehicle)`` to
        # decide whether to promote — so the mock here MUST carry
        # ``spec=GlobalVehicle`` (a plain ``MagicMock`` would fail the
        # isinstance check and the test would silently skip the
        # promotion path). Build the gv via the shared helper, then
        # re-anchor it as a spec'd mock with the same field values.
        gv = MagicMock(spec=GlobalVehicle)
        _seed = _make_global_vehicle(
            rego="FLT003",
            service_due_date=date(2025, 8, 1),
        )
        for attr in (
            "id", "rego", "make", "model", "year", "colour", "body_type",
            "fuel_type", "engine_size", "num_seats", "registration_expiry",
            "vin", "chassis", "engine_no", "transmission",
            "country_of_origin", "number_of_owners", "vehicle_type",
            "power_kw", "tare_weight", "gross_vehicle_mass",
            "date_first_registered_nz", "plate_type", "submodel",
            "second_colour", "odometer_last_recorded", "service_due_date",
            "wof_expiry", "cof_expiry", "inspection_type",
        ):
            setattr(gv, attr, getattr(_seed, attr))
        gv_pre = _snapshot_customer_driven_fields(gv)

        cv = _make_customer_vehicle_link(
            cv_id=cv_id,
            org_id=org_id,
            customer_id=customer_id,
            gv=gv,
            ov=None,
        )

        ctx = _make_fleet_ctx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            role="fleet_admin",  # service_due_date is in the admin allowlist
        )

        new_service_due = date(2026, 6, 1)
        body = VehicleEditRequest(service_due_date=new_service_due)

        # ``edit_vehicle`` issues, in order (with promotion firing):
        #   1. db.execute(base.where(CustomerVehicle.id == ...)) → cv
        #   2. promote_vehicle: pg_advisory_xact_lock            → no-op
        #   3. promote_vehicle: OrgVehicle existence SELECT      → None
        #   4. migrate_link_to_org_vehicle: UPDATE customer_vehicles
        cv_result = MagicMock()
        cv_result.scalars.return_value.first.return_value = cv

        advisory_result = MagicMock()
        advisory_result.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            cv_result,
            advisory_result,
            ov_check,
            update_result,
        ])

        mock_base = MagicMock()
        mock_base.where = MagicMock(return_value=MagicMock())

        with patch(
            "app.modules.fleet_portal.services.vehicle_service._vehicle_query_for_session",
            new_callable=AsyncMock,
            return_value=mock_base,
        ), patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            # Call the route handler directly — bypasses FastAPI's
            # dependency injection. ``_=None`` short-circuits the CSRF
            # validator dependency (we are not running an HTTP request).
            response = await edit_vehicle(
                vehicle_id=cv_id,
                body=body,
                ctx=ctx,
                _=None,
                db=db,
            )

        assert response.ok is True

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link migrated to org_vehicle_id --
        # ``edit_vehicle`` calls ``migrate_link_to_org_vehicle`` which
        # issues a single UPDATE on ``customer_vehicles``. Verify the
        # UPDATE was issued by inspecting db.execute's call list.
        update_cv_calls = [
            c for c in db.execute.await_args_list
            if "update customer_vehicles" in str(c.args[0]).lower()
        ]
        assert len(update_cv_calls) == 1, (
            "edit_vehicle must issue exactly one UPDATE on customer_vehicles "
            "to migrate the link still pointing at global_vehicle_id; "
            f"got {len(update_cv_calls)} matching calls"
        )

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "fleet_portal.update_field must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )
        # Specifically: the service-due cache on the shared row must
        # not have moved with the fleet-admin's edit.
        assert gv.service_due_date == gv_pre["service_due_date"]

        # -- Invariant 4: org_vehicles.service_due_date holds the new value --
        assert ov.service_due_date == new_service_due, (
            "OrgVehicle.service_due_date must reflect the fleet-admin's edit"
        )
        # The other Customer_Driven_Fields are copied at promotion time
        # and not changed by this edit — they keep the gv values
        # captured at promotion (Req 10.3).
        assert ov.odometer_last_recorded == gv.odometer_last_recorded
        assert ov.wof_expiry == gv.wof_expiry
        assert ov.cof_expiry == gv.cof_expiry
        assert ov.inspection_type == gv.inspection_type

        # -- Invariant 5: one vehicle.promote audit-log row with matching trigger_site --
        promote_calls = _promote_audit_calls(mock_audit)
        assert len(promote_calls) == 1, (
            "fleet_portal.update_field must emit exactly one "
            "vehicle.promote audit-log row"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == portal_account_id
        assert (
            promote_kwargs["after_value"]["trigger_site"]
            == "fleet_portal.update_field"
        )
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Task 7.2 — Fleet portal admin-link and CarJam-import trigger sites
# ---------------------------------------------------------------------------
#
# Both tests below exercise ``app/modules/fleet_portal/router.py::add_vehicle_to_fleet``
# (the ``POST /fleet/api/vehicles`` handler). The handler funnels two
# user-facing flows through a single code path:
#
#   - **Admin link**: the fleet admin opens the "Add vehicle" dialog and
#     selects a rego that already lives in ``global_vehicles`` (e.g. a
#     CarJam cache hit from a prior lookup). The handler resolves the
#     existing ``GlobalVehicle`` row and calls ``promote_vehicle`` with
#     ``trigger_site="fleet_portal.admin_link"``.
#
#   - **CarJam import**: the frontend calls ``/api/v1/vehicles/lookup``
#     for a fresh rego (which inserts/refreshes the ``global_vehicles``
#     row) and immediately follows up with ``POST /fleet/api/vehicles``
#     to attach the vehicle to the fleet. From the handler's perspective
#     the ``global_vehicles`` row is already present — the CarJam side
#     happened upstream of this endpoint — so it takes the same code
#     path as the admin-link flow. The test name carries the scenario
#     intent; the audit ``trigger_site`` value is identical
#     (``fleet_portal.admin_link``) because both flows are
#     indistinguishable to the handler. See Task 7.2's note in
#     ``tasks.md`` for the rationale.
#
# Both tests assert the five invariants from the design's Test Strategy
# → Integration Tests section:
#
#   1. ``org_vehicles`` row created for the calling org
#   2. ``customer_vehicles`` link created via ``org_vehicle_id`` (NOT
#      ``global_vehicle_id``) — the handler builds the link itself
#   3. ``global_vehicles`` Customer_Driven_Fields unchanged
#   4. ``org_vehicles`` Customer_Driven_Fields hold the values copied
#      at promotion (the handler does not itself write Customer_Driven_
#      Fields, so the ov values match the gv values at the moment of
#      promotion — Req 10.3)
#   5. One ``vehicle.promote`` audit-log row with
#      ``trigger_site='fleet_portal.admin_link'``
#
# Both tests also verify the rebind worked: the inserted ``CustomerVehicle``
# row has ``org_vehicle_id`` set and ``global_vehicle_id`` cleared. Without
# the rebind documented in the spec's "Implementation Note — Local Variable
# Rebinding", the link would still point at ``global_vehicle_id`` and
# atomically undo the promotion at link-create time.
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


from app.modules.fleet_portal.models import (
    FleetReminderPreference,
    PortalFleetAccount,
)


def _added_first_of_type(db, cls):
    """Return the first instance of ``cls`` added to ``db``, or fail.

    The ``add_vehicle_to_fleet`` handler adds multiple
    ``FleetReminderPreference`` rows (one per reminder type), so the
    stricter ``_added_of_type`` helper (which asserts exactly one row)
    would fail there. For ``OrgVehicle`` and ``CustomerVehicle`` the
    handler still only adds one row each — but using the lenient
    helper keeps the test assertions decoupled from the reminder-seed
    count.
    """
    matches = [
        call.args[0]
        for call in db.add.call_args_list
        if call.args and isinstance(call.args[0], cls)
    ]
    assert matches, f"no {cls.__name__} added to the session"
    return matches[0]


def _setup_add_vehicle_to_fleet_db(*, gv, customer_id):
    """Build a side-effect callable for ``db.execute`` that routes the
    queries ``add_vehicle_to_fleet`` issues, in order:

      1. PortalFleetAccount.customer_id lookup  → row(customer_id)
      2. select(GlobalVehicle).where(rego=...)  → ``gv``
      3. promote_vehicle: pg_advisory_xact_lock → no-op
      4. promote_vehicle: OrgVehicle existence  → None
      5. existing-link guard select(CustomerVehicle) → None (no dup)

    After ``promote_vehicle`` inserts the new ``OrgVehicle`` via
    ``db.add``, this routing helper does not need to feed it back —
    the handler keeps its own ``ov`` reference and never re-queries
    ``org_vehicles``.
    """

    fa_row = MagicMock()
    fa_row.first.return_value = (customer_id,)

    gv_result = MagicMock()
    gv_result.scalars.return_value.first.return_value = gv

    advisory_result = MagicMock()
    advisory_result.scalar_one_or_none.return_value = None

    ov_existence_result = MagicMock()
    ov_existence_result.scalar_one_or_none.return_value = None

    existing_link_result = MagicMock()
    existing_link_result.scalars.return_value.first.return_value = None

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    async def _refresh(obj):
        # Mirror the post-flush identity hydration that real refresh()
        # performs. The handler reads ``cv.id`` after the refresh to
        # build the response and to seed reminder rows.
        if isinstance(obj, CustomerVehicle) and getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    db.refresh = AsyncMock(side_effect=_refresh)
    db.execute = AsyncMock(side_effect=[
        fa_row,
        gv_result,
        advisory_result,
        ov_existence_result,
        existing_link_result,
    ])
    return db


def _assert_five_invariants_for_fleet_admin_link(
    *,
    db,
    mock_audit,
    gv,
    gv_pre,
    org_id,
    portal_account_id,
    customer_id,
):
    """Shared assertion block exercising the five invariants for
    ``add_vehicle_to_fleet``.

    Both the admin-link and CarJam-import tests funnel through the
    same handler, so the invariants are identical. Pulled into a
    helper to keep the per-test bodies focused on the scenario setup.
    """
    # -- Invariant 1: org_vehicles row created for the calling org --
    ov = _added_first_of_type(db, OrgVehicle)
    assert ov.org_id == org_id, (
        "promote_vehicle must insert an OrgVehicle scoped to the calling org"
    )
    assert ov.rego == gv.rego
    assert ov.is_manual_entry is False, (
        "promoted-from-CarJam rows must have is_manual_entry=False"
    )

    # -- Invariant 2: customer_vehicles link created via org_vehicle_id --
    cv = _added_first_of_type(db, CustomerVehicle)
    assert cv.org_vehicle_id == ov.id, (
        "fleet-portal admin-link must point the new customer_vehicles row "
        "at the freshly-promoted OrgVehicle (post-rebind discipline)"
    )
    assert cv.global_vehicle_id is None, (
        "fleet-portal admin-link must clear global_vehicle_id on the link "
        "so vehicle_link_check holds and the rebind is observable"
    )
    assert cv.org_id == org_id
    assert cv.customer_id == customer_id

    # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
    gv_post = _snapshot_customer_driven_fields(gv)
    assert gv_post == gv_pre, (
        "fleet_portal.admin_link must not mutate global_vehicles "
        "Customer_Driven_Fields; "
        f"pre={gv_pre!r}, post={gv_post!r}"
    )

    # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the
    #    values copied from global_vehicles at promotion --
    # ``add_vehicle_to_fleet`` itself does not write Customer_Driven_
    # Fields, so the OrgVehicle holds the values copied at promotion
    # time (preserving Read_Fallback continuity, Req 10.3).
    for field in (
        "odometer_last_recorded",
        "service_due_date",
        "wof_expiry",
        "cof_expiry",
        "inspection_type",
    ):
        assert getattr(ov, field) == getattr(gv, field), (
            f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
        )

    # -- Invariant 5: one vehicle.promote audit-log row with matching
    #    trigger_site --
    promote_calls = _promote_audit_calls(mock_audit)
    assert len(promote_calls) == 1, (
        "add_vehicle_to_fleet must emit exactly one vehicle.promote "
        "audit-log row"
    )
    promote_kwargs = promote_calls[0].kwargs
    assert promote_kwargs["entity_type"] == "org_vehicle"
    assert promote_kwargs["entity_id"] == ov.id
    assert promote_kwargs["org_id"] == org_id
    assert promote_kwargs["user_id"] == portal_account_id
    assert (
        promote_kwargs["after_value"]["trigger_site"]
        == "fleet_portal.admin_link"
    ), (
        "fleet portal admin-link and CarJam-import flows funnel through "
        "the same handler; both emit trigger_site='fleet_portal.admin_link'"
    )
    assert promote_kwargs["after_value"]["rego"] == gv.rego
    assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Test 10 — fleet portal admin-link trigger site
# ---------------------------------------------------------------------------


class TestFleetPortalAdminLinkCreationPromotesFirstTime:
    """Scenario: a fleet admin selects an existing CarJam-cached rego
    from the "Add vehicle" dialog (the rego was previously looked up
    by some other org or by a prior portal session, so the
    ``global_vehicles`` row already exists at endpoint-call time).

    Asserts the five invariants from the design's Test Strategy →
    Integration Tests, plus the rebind verification: the resulting
    ``customer_vehicles`` row has ``org_vehicle_id`` set and
    ``global_vehicle_id`` cleared.
    """

    @pytest.mark.asyncio
    async def test_fleet_portal_admin_link_creation_promotes_first_time(self):
        from app.modules.fleet_portal.router import (
            _VehicleAddRequest,
            add_vehicle_to_fleet,
        )

        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        fleet_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # ``add_vehicle_to_fleet`` uses a plain ``scalars().first()``
        # over the GlobalVehicle SELECT (not an isinstance check), so
        # a regular MagicMock built by ``_make_global_vehicle`` is fine
        # here — unlike Task 6.2's ``edit_vehicle`` which needs a spec'd
        # mock for the ``isinstance(target, GlobalVehicle)`` check.
        gv = _make_global_vehicle(rego="ADM001")
        gv_pre = _snapshot_customer_driven_fields(gv)

        ctx = _make_fleet_ctx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            role="fleet_admin",
            fleet_account_id=fleet_account_id,
        )

        db = _setup_add_vehicle_to_fleet_db(gv=gv, customer_id=customer_id)

        body = _VehicleAddRequest(rego="adm001", odometer_at_link=42_000)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            response = await add_vehicle_to_fleet(
                body=body,
                ctx=ctx,
                _=None,
                db=db,
            )

        # Response payload sanity-check — the IdResponse carries the
        # newly-created ``customer_vehicles.id`` so the frontend can
        # navigate to the vehicle detail page.
        cv = _added_first_of_type(db, CustomerVehicle)
        assert response.id == cv.id

        # Reminder seed assertion — the handler must have queued the
        # three default reminder preferences disabled (Req 10.9). These
        # are out of scope for the five invariants but pinning the count
        # here catches accidental short-circuits in the success path.
        seeded_reminders = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], FleetReminderPreference)
        ]
        assert len(seeded_reminders) == 3, (
            "add_vehicle_to_fleet must seed three default reminder "
            "preferences (wof/cof/service_due) — proves the success path "
            "ran end-to-end through the post-link reminder seeding block"
        )

        _assert_five_invariants_for_fleet_admin_link(
            db=db,
            mock_audit=mock_audit,
            gv=gv,
            gv_pre=gv_pre,
            org_id=org_id,
            portal_account_id=portal_account_id,
            customer_id=customer_id,
        )


# ---------------------------------------------------------------------------
# Test 11 — fleet portal CarJam-import trigger site
# ---------------------------------------------------------------------------


class TestFleetPortalCarjamImportPromotesFirstTime:
    """Scenario: the fleet admin enters a brand-new rego, the frontend
    calls ``/api/v1/vehicles/lookup`` upstream (which inserts the
    ``global_vehicles`` row from CarJam), then immediately POSTs to
    ``/fleet/api/vehicles`` to attach the freshly-cached vehicle to
    the fleet.

    From the handler's perspective the ``global_vehicles`` row is
    already present at endpoint-call time — the CarJam side happened
    upstream — so it takes the same promotion path as the admin-link
    flow. Per Task 7.2's note, both tests assert
    ``trigger_site='fleet_portal.admin_link'`` because the audit string
    is identical from the handler's perspective. The test name carries
    the scenario intent for future maintainers.

    Asserts the five invariants from the design's Test Strategy →
    Integration Tests, plus the rebind verification.
    """

    @pytest.mark.asyncio
    async def test_fleet_portal_carjam_import_promotes_first_time(self):
        from app.modules.fleet_portal.router import (
            _VehicleAddRequest,
            add_vehicle_to_fleet,
        )

        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        fleet_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # Simulate the CarJam-import scenario: the frontend's
        # ``/api/v1/vehicles/lookup`` call has just inserted/refreshed
        # the ``global_vehicles`` row with realistic CarJam-sourced
        # data. The Customer_Driven_Fields are exactly what CarJam
        # returns (typically null on a freshly-cached rego because no
        # workshop has written customer-driven state yet). The test
        # uses a different rego from the admin-link test to avoid
        # cross-test mutation of the shared ``_make_global_vehicle``
        # fixture defaults.
        gv = _make_global_vehicle(
            rego="CJM001",
            # Fresh CarJam imports often have null Customer_Driven_Fields
            # — pick representative values to prove the snapshot at
            # promotion captures whatever CarJam returned.
            odometer_last_recorded=None,
            service_due_date=None,
            wof_expiry=date(2026, 4, 30),
            cof_expiry=None,
            inspection_type="wof",
        )
        gv_pre = _snapshot_customer_driven_fields(gv)

        ctx = _make_fleet_ctx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            role="fleet_admin",
            fleet_account_id=fleet_account_id,
        )

        db = _setup_add_vehicle_to_fleet_db(gv=gv, customer_id=customer_id)

        # Different odometer-at-link value to prove the field is round-
        # tripped from request body to ``CustomerVehicle.odometer_at_link``
        # (a per-link field that is independent of
        # ``OrgVehicle.odometer_last_recorded``).
        body = _VehicleAddRequest(rego="cjm001", odometer_at_link=15_500)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            response = await add_vehicle_to_fleet(
                body=body,
                ctx=ctx,
                _=None,
                db=db,
            )

        # The IdResponse carries the new customer_vehicles.id.
        cv = _added_first_of_type(db, CustomerVehicle)
        assert response.id == cv.id
        # The link captured the odometer-at-link supplied with the
        # request — proves the request body flowed through to the
        # ``CustomerVehicle`` constructor.
        assert cv.odometer_at_link == 15_500

        # Reminder seed assertion (same as admin-link case).
        seeded_reminders = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], FleetReminderPreference)
        ]
        assert len(seeded_reminders) == 3, (
            "add_vehicle_to_fleet must seed three default reminder "
            "preferences for CarJam-import flow as well"
        )

        _assert_five_invariants_for_fleet_admin_link(
            db=db,
            mock_audit=mock_audit,
            gv=gv,
            gv_pre=gv_pre,
            org_id=org_id,
            portal_account_id=portal_account_id,
            customer_id=customer_id,
        )


# ---------------------------------------------------------------------------
# Task 8.2 — bookings.link trigger site
# ---------------------------------------------------------------------------
#
# Exercises ``app/modules/bookings/service.py::create_booking``'s auto-link
# block (~L383-417) which, after Task 8.1, calls
# ``promote_vehicle(..., trigger_site="bookings.link")`` whenever the supplied
# ``vehicle_rego`` resolves to a ``GlobalVehicle`` row and the calling org
# has not yet promoted it. The link is constructed with
# ``org_vehicle_id=ov.id`` and ``global_vehicle_id=None`` so the post-rebind
# ``customer_vehicles`` row points at the per-org snapshot and never at the
# cross-tenant cache.
#
# The test asserts the five invariants from the design's Test Strategy →
# Integration Tests section:
#
#   1. ``org_vehicles`` row created for the calling org
#   2. ``customer_vehicles`` link created via ``org_vehicle_id``
#   3. ``global_vehicles`` Customer_Driven_Fields unchanged
#   4. ``org_vehicles`` Customer_Driven_Fields hold the values copied from
#      ``global_vehicles`` at promotion (link path itself does not write
#      Customer_Driven_Fields, preserving Read_Fallback continuity, Req 10.3)
#   5. One ``vehicle.promote`` audit-log row with
#      ``trigger_site='bookings.link'``
#
# ``_check_staff_availability`` is patched out (the staff module's schedule
# checks would issue many unrelated SQL queries that have no bearing on the
# promotion path under test). ``ModuleService.is_enabled`` is patched to
# return ``True`` so the vehicles-rego gate passes and ``promote_vehicle``'s
# defence-in-depth gate also passes.
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


from datetime import datetime, timedelta, timezone


class TestBookingsLinkCreationPromotesFirstTime:
    """Exercises ``create_booking`` against a ``GlobalVehicle``-backed rego
    the calling org has never linked before.

    Validates the five invariants from the design's Test Strategy →
    Integration Tests section. Per Task 8.1 this exercises the auto-link
    code path's ``("global", gv)`` branch which now calls
    ``promote_vehicle`` with ``trigger_site="bookings.link"`` before
    constructing the ``CustomerVehicle`` row.
    """

    @pytest.mark.asyncio
    async def test_bookings_link_creation_promotes_first_time(self):
        from app.modules.bookings.models import Booking
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="BKG001")
        gv_pre = _snapshot_customer_driven_fields(gv)

        # Customer record looked up by ``create_booking`` (~L271).
        customer = MagicMock(spec=Customer)
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Pat"
        customer.last_name = "Tester"
        customer.email = "pat@example.com"
        customer.phone = "021-555-0100"

        # ``create_booking`` issues, in order (with vehicle_rego set, no
        # service_catalogue_id, no parts/fluids, send_*_confirmation
        # both False, and ``_check_staff_availability`` patched out):
        #
        #   1. ModuleService.is_enabled('vehicles') gate at ~L248
        #      — patched, no execute.
        #   2. select(Customer) at ~L271                       → customer
        #   3. db.add(Booking); db.flush() — no execute
        #   4. Rego-keyed widened link-existence check (Task 11.7) → None
        #   5. select(GlobalVehicle) auto-link at ~L376        → gv
        #   6. promote_vehicle: ModuleService.is_enabled gate
        #      — patched, no execute.
        #   7. promote_vehicle: pg_advisory_xact_lock          → no-op
        #   8. promote_vehicle: select(OrgVehicle) existence   → None
        #   9. db.add(OrgVehicle); db.flush(); db.refresh()
        #      — no execute.
        #  10. db.add(CustomerVehicle); db.flush() — no execute
        #  11. write_audit_log('booking.created') — patched.
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer

        widened_check = MagicMock()
        widened_check.scalar_one_or_none.return_value = None

        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            customer_result,
            widened_check,   # Task 11.7 rego-keyed existence check
            gv_result,
            no_op,           # advisory lock
            ov_check,        # OrgVehicle existence check
        ])

        # Schedule the booking comfortably in the future to bypass the
        # backdated-booking guard at ~L233.
        scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)

        with patch(
            "app.modules.bookings.service._check_staff_availability",
            new_callable=AsyncMock,
        ), patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await create_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                vehicle_rego=gv.rego,
                service_type="WOF Inspection",
                scheduled_at=scheduled_at,
                duration_minutes=60,
                send_confirmation=False,
                send_email_confirmation=False,
                send_sms_confirmation=False,
                ip_address="127.0.0.1",
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link created via org_vehicle_id --
        cv = _added_of_type(db, CustomerVehicle)
        assert cv.org_vehicle_id == ov.id, (
            "bookings.link must point the new customer_vehicles row at the "
            "freshly-promoted OrgVehicle (post-rebind discipline — Task 8.1)"
        )
        assert cv.global_vehicle_id is None, (
            "bookings.link must clear global_vehicle_id on the link so "
            "vehicle_link_check holds and the rebind is observable"
        )
        assert cv.org_id == org_id
        assert cv.customer_id == customer_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "bookings.link must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the
        #    values copied from global_vehicles at promotion --
        # ``create_booking``'s auto-link path does not itself write
        # Customer_Driven_Fields, so the OrgVehicle holds the values
        # copied from ``global_vehicles`` at the moment of promotion
        # (preserving Read_Fallback continuity, Req 10.3).
        for field in (
            "odometer_last_recorded",
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
            )

        # Sanity-check: the booking row was added to the session as
        # part of the same transaction (proves we exercised
        # ``create_booking`` end-to-end and not just the auto-link block
        # by accident).
        booking = _added_of_type(db, Booking)
        assert booking.org_id == org_id
        assert booking.vehicle_rego == gv.rego

        # -- Invariant 5: one vehicle.promote audit-log row with
        #    matching trigger_site --
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert len(promote_calls) == 1, (
            "create_booking must emit exactly one vehicle.promote audit-log "
            "row when the auto-link path promotes a GlobalVehicle"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert promote_kwargs["after_value"]["trigger_site"] == "bookings.link"
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Task 9.2 — customers.link trigger site
# ---------------------------------------------------------------------------
#
# Exercises ``app/modules/customers/service.py::tag_vehicle_to_customer``
# against a ``GlobalVehicle``-backed rego the calling org has never linked
# before. Per Task 9.1 the function calls
# ``promote_vehicle(..., trigger_site="customers.link")`` first and then
# constructs the ``CustomerVehicle`` row with ``org_vehicle_id=ov.id`` and
# ``global_vehicle_id=None`` so the resulting link points at the per-org
# snapshot, not the cross-tenant cache.
#
# The Task 9.1 patch added two duplicate-prevention guards before the
# ``CustomerVehicle`` constructor (matching the Task 11.7 pattern at the
# other link-creation sites): a primary check on the post-promotion
# ``org_vehicle_id`` and a fallback rego-keyed legacy check that catches
# any unmigrated ``global_vehicle_id`` link for the same rego. The test's
# ``db.execute`` side-effect feeds the queries in the order the function
# issues them: customer SELECT, GlobalVehicle SELECT, advisory lock,
# OrgVehicle existence, duplicate-link guard, legacy-link guard.
#
# The test asserts the five invariants from the design's Test Strategy →
# Integration Tests section:
#
#   1. ``org_vehicles`` row created for the calling org
#   2. ``customer_vehicles`` link created via ``org_vehicle_id``
#   3. ``global_vehicles`` Customer_Driven_Fields unchanged
#   4. ``org_vehicles`` Customer_Driven_Fields hold the values copied from
#      ``global_vehicles`` at promotion (link path itself does not write
#      Customer_Driven_Fields, preserving Read_Fallback continuity, Req 10.3)
#   5. One ``vehicle.promote`` audit-log row with
#      ``trigger_site='customers.link'``
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


class TestCustomersLinkCreationPromotesFirstTime:
    """Exercises ``tag_vehicle_to_customer`` against a ``GlobalVehicle``-
    backed rego the calling org has never linked before.

    Validates the five invariants from the design's Test Strategy →
    Integration Tests section. Per Task 9.1 this exercises the
    ``global_vehicle_id`` branch which now calls ``promote_vehicle`` with
    ``trigger_site="customers.link"`` before constructing the
    ``CustomerVehicle`` row.
    """

    @pytest.mark.asyncio
    async def test_customers_link_creation_promotes_first_time(self):
        from app.modules.customers.service import tag_vehicle_to_customer

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="CST001")
        gv_pre = _snapshot_customer_driven_fields(gv)

        # Customer record looked up at the top of ``tag_vehicle_to_customer``.
        customer = MagicMock(spec=Customer)
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Sam"
        customer.last_name = "Smith"

        # ``tag_vehicle_to_customer`` issues, in order:
        #   1. select(Customer)                                → customer
        #   2. select(GlobalVehicle).where(id == gv.id)        → gv
        #   3. promote_vehicle: pg_advisory_xact_lock          → no-op
        #   4. promote_vehicle: select(OrgVehicle) existence   → None
        #   5. duplicate-link guard select(CustomerVehicle) by
        #      org_vehicle_id                                  → None
        #   6. legacy-link guard select(CustomerVehicle).join(
        #      GlobalVehicle) by upper(rego)                   → None
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer

        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        duplicate_check = MagicMock()
        duplicate_check.scalar_one_or_none.return_value = None

        legacy_check = MagicMock()
        legacy_check.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            customer_result,
            gv_result,
            no_op,             # advisory lock
            ov_check,          # OrgVehicle existence check
            duplicate_check,   # duplicate-link guard (org_vehicle_id)
            legacy_check,      # legacy-link guard (rego-keyed via gv)
        ])

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await tag_vehicle_to_customer(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                global_vehicle_id=gv.id,
                ip_address="127.0.0.1",
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link created via org_vehicle_id --
        cv = _added_of_type(db, CustomerVehicle)
        assert cv.org_vehicle_id == ov.id, (
            "customers.link must point the new customer_vehicles row at the "
            "freshly-promoted OrgVehicle (post-rebind discipline — Task 9.1)"
        )
        assert cv.global_vehicle_id is None, (
            "customers.link must clear global_vehicle_id on the link so "
            "vehicle_link_check holds and the rebind is observable"
        )
        assert cv.org_id == org_id
        assert cv.customer_id == customer_id

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "customers.link must not mutate global_vehicles "
            "Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the
        #    values copied from global_vehicles at promotion --
        # ``tag_vehicle_to_customer``'s link path does not itself write
        # Customer_Driven_Fields, so the OrgVehicle holds the values
        # copied from ``global_vehicles`` at the moment of promotion
        # (preserving Read_Fallback continuity, Req 10.3).
        for field in (
            "odometer_last_recorded",
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"OrgVehicle.{field} must be copied from global_vehicles at promotion"
            )

        # Response payload sanity-check — the dict the router returns to
        # the frontend reports the ``OrgVehicle``'s rego/make/model and
        # marks the link as sourced from the per-org snapshot.
        assert result["rego"] == gv.rego
        assert result["source"] == "org"

        # -- Invariant 5: one vehicle.promote audit-log row with
        #    matching trigger_site --
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert len(promote_calls) == 1, (
            "tag_vehicle_to_customer must emit exactly one vehicle.promote "
            "audit-log row when promoting a GlobalVehicle for the first time"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert promote_kwargs["after_value"]["trigger_site"] == "customers.link"
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Task 10.2 — customers.update_vehicle_dates trigger site
# ---------------------------------------------------------------------------
#
# Exercises ``app/modules/customers/service.py::update_vehicle_expiry_dates``
# against a ``GlobalVehicle``-backed rego that the calling org has never
# promoted. Per Task 10.1 the function calls
# ``promote_vehicle(..., trigger_site="customers.update_vehicle_dates")``
# whenever the linked vehicle resolves to a ``GlobalVehicle`` and writes
# ``service_due_date``, ``wof_expiry``, AND ``cof_expiry`` to the per-org
# ``OrgVehicle`` snapshot — closing the cross-tenant leak that previously
# wrote those fields directly to ``global_vehicles``. The function also
# migrates the ``customer_vehicles`` link from ``global_vehicle_id`` to
# ``org_vehicle_id`` via ``migrate_link_to_org_vehicle``.
#
# The test asserts the five invariants from the design's Test Strategy →
# Integration Tests section:
#
#   1. ``org_vehicles`` row created for the calling org
#   2. ``customer_vehicles`` link migrated to ``org_vehicle_id`` (the
#      function issues a bulk UPDATE on customer_vehicles)
#   3. ``global_vehicles`` Customer_Driven_Fields unchanged — including
#      ``cof_expiry`` specifically (the missing-COF-branch fix from
#      Task 10.1)
#   4. ``org_vehicles`` Customer_Driven_Fields hold the new payload
#      values for ``service_due_date``, ``wof_expiry``, AND ``cof_expiry``
#   5. One ``vehicle.promote`` audit-log row with
#      ``trigger_site='customers.update_vehicle_dates'``
#
# Plus the explicit Task 10.2 sub-assertion: posting ``cof_expiry`` lands
# on ``org_vehicles.cof_expiry`` and NOT on ``global_vehicles.cof_expiry``
# — the missing-COF-branch fix.
#
# Requirements: 15.2
# Design: Test Strategy → Integration Tests
# ---------------------------------------------------------------------------


class TestCustomersUpdateVehicleDatesPromotesFirstTime:
    """Exercises ``update_vehicle_expiry_dates`` against a
    ``GlobalVehicle``-backed rego the calling org has never promoted.

    Validates the five invariants from the design's Test Strategy →
    Integration Tests section, plus the per-task sub-assertion that
    ``cof_expiry`` lands on ``org_vehicles.cof_expiry`` and not on
    ``global_vehicles.cof_expiry`` — the missing-COF-branch fix from
    Task 10.1.
    """

    @pytest.mark.asyncio
    async def test_customers_update_vehicle_dates_promotes_first_time(self):
        from app.modules.customers.service import update_vehicle_expiry_dates

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # Pre-existing CarJam-cached row for this rego with a
        # representative ``cof_expiry`` value so the test can confirm
        # the value does not move on ``global_vehicles`` after the
        # endpoint writes a new COF date.
        gv = _make_global_vehicle(
            rego="UPD002",
            service_due_date=date(2025, 9, 1),
            wof_expiry=date(2025, 7, 1),
            cof_expiry=date(2025, 8, 15),
        )
        gv_pre = _snapshot_customer_driven_fields(gv)
        gv_cof_pre = gv.cof_expiry  # captured separately for the
                                    # explicit COF sub-assertion below

        # Customer record looked up at the top of
        # ``update_vehicle_expiry_dates``.
        customer = MagicMock(spec=Customer)
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Cam"
        customer.last_name = "Updater"

        # Pre-existing legacy link — the customer is linked to the rego
        # via ``cv.global_vehicle_id`` (not yet promoted). Task 10.1's
        # promote-then-migrate flow must:
        #   - resolve the link via the legacy ``global_vehicle_id`` SELECT
        #   - call ``promote_vehicle`` with the source_record passed in
        #   - migrate the link via ``migrate_link_to_org_vehicle``
        cv = MagicMock(spec=CustomerVehicle)
        cv.id = uuid.uuid4()
        cv.org_id = org_id
        cv.customer_id = customer_id
        cv.global_vehicle_id = gv.id
        cv.org_vehicle_id = None

        # ``update_vehicle_expiry_dates`` issues, in order, for the
        # legacy-link branch:
        #   1. select(Customer).where(...)                     → customer
        #   2. select(CustomerVehicle).where(global_vehicle_id == payload_id)
        #                                                       → cv
        #   3. select(GlobalVehicle).where(id == payload_id)    → gv
        #   4. promote_vehicle: pg_advisory_xact_lock           → no-op
        #     (ModuleService.is_enabled is patched, no execute;
        #      source_record is supplied so step 2 of promote_vehicle
        #      does not issue its own SELECT)
        #   5. promote_vehicle: select(OrgVehicle) existence    → None
        #   6. migrate_link_to_org_vehicle: UPDATE customer_vehicles
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer

        cv_result = MagicMock()
        cv_result.scalar_one_or_none.return_value = cv

        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        ov_check = MagicMock()
        ov_check.scalar_one_or_none.return_value = None

        update_result = MagicMock()
        update_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            customer_result,
            cv_result,
            gv_result,
            no_op,           # advisory lock
            ov_check,        # OrgVehicle existence check
            update_result,   # UPDATE customer_vehicles (link migration)
        ])

        # Customer-driven payload values that must land on the OrgVehicle.
        new_service_due = date(2026, 6, 1)
        new_wof = date(2026, 9, 1)
        new_cof = date(2026, 11, 1)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit:
            updated = await update_vehicle_expiry_dates(
                db,
                org_id=org_id,
                customer_id=customer_id,
                vehicle_updates=[
                    {
                        "global_vehicle_id": str(gv.id),
                        "service_due_date": new_service_due.isoformat(),
                        "wof_expiry": new_wof.isoformat(),
                        "cof_expiry": new_cof.isoformat(),
                    },
                ],
                user_id=user_id,
                ip_address="127.0.0.1",
            )

        # -- Invariant 1: org_vehicles row created for the calling org --
        ov = _added_of_type(db, OrgVehicle)
        assert ov.org_id == org_id, (
            "promote_vehicle must insert an OrgVehicle scoped to the "
            "calling org"
        )
        assert ov.rego == gv.rego
        assert ov.is_manual_entry is False, (
            "promoted-from-CarJam rows must have is_manual_entry=False"
        )

        # -- Invariant 2: customer_vehicles link migrated to org_vehicle_id --
        # ``migrate_link_to_org_vehicle`` issues a single bulk UPDATE on
        # ``customer_vehicles`` setting ``global_vehicle_id=NULL`` and
        # ``org_vehicle_id=:ov.id`` atomically. Verify the UPDATE was
        # issued by inspecting db.execute's call list.
        update_cv_calls = [
            c for c in db.execute.await_args_list
            if "update customer_vehicles" in str(c.args[0]).lower()
        ]
        assert len(update_cv_calls) == 1, (
            "update_vehicle_expiry_dates must issue exactly one UPDATE "
            "on customer_vehicles to migrate the link still pointing at "
            f"global_vehicle_id; got {len(update_cv_calls)} matching calls"
        )

        # -- Invariant 3: global_vehicles Customer_Driven_Fields unchanged --
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "customers.update_vehicle_dates must not mutate "
            "global_vehicles Customer_Driven_Fields; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )

        # -- Invariant 4: org_vehicles Customer_Driven_Fields hold the
        #    payload values for the calling org --
        assert ov.service_due_date == new_service_due, (
            "OrgVehicle.service_due_date must reflect the endpoint's "
            "new service_due_date payload"
        )
        assert ov.wof_expiry == new_wof, (
            "OrgVehicle.wof_expiry must reflect the endpoint's new "
            "wof_expiry payload"
        )
        assert ov.cof_expiry == new_cof, (
            "OrgVehicle.cof_expiry must reflect the endpoint's new "
            "cof_expiry payload (missing-COF-branch fix from Task 10.1)"
        )
        # The remaining Customer_Driven_Fields are copied at promotion
        # time and not changed by this endpoint — they keep gv values.
        assert ov.odometer_last_recorded == gv.odometer_last_recorded
        assert ov.inspection_type == gv.inspection_type

        # -- Task 10.2 explicit sub-assertion --
        # Posting ``cof_expiry`` MUST land on ``org_vehicles.cof_expiry``
        # and NOT on ``global_vehicles.cof_expiry``. This is the
        # regression-shield for the missing-COF-branch fix from Task 10.1
        # (the legacy code only handled ``service_due_date`` and
        # ``wof_expiry``, silently dropping ``cof_expiry`` from the
        # request payload).
        assert ov.cof_expiry == new_cof, (
            "the new cof_expiry must land on org_vehicles.cof_expiry"
        )
        assert gv.cof_expiry == gv_cof_pre, (
            "global_vehicles.cof_expiry must be byte-identical to its "
            "pre-call value — the new COF must NOT bleed into the "
            "shared CarJam cache"
        )
        assert ov.cof_expiry != gv.cof_expiry, (
            "the new cof_expiry must be observable on the OrgVehicle "
            "while leaving the GlobalVehicle untouched (cross-tenant "
            "isolation, Req 1.2)"
        )

        # Response payload sanity-check — the dict the router returns to
        # the frontend echoes the new dates keyed by the original
        # ``global_vehicle_id`` for backwards compatibility. Each key
        # is ISO-formatted so the frontend can parse it directly.
        assert len(updated) == 1
        echo = updated[0]
        assert echo["global_vehicle_id"] == str(gv.id), (
            "response must echo the request payload's global_vehicle_id "
            "for backwards compatibility with the frontend's "
            "vehicleDateEdits keying"
        )
        assert echo["rego"] == gv.rego
        assert echo["service_due_date"] == new_service_due.isoformat()
        assert echo["wof_expiry"] == new_wof.isoformat()
        assert echo["cof_expiry"] == new_cof.isoformat(), (
            "response must include cof_expiry — the missing-COF-branch "
            "fix added the response key alongside the existing "
            "service_due_date and wof_expiry keys"
        )

        # -- Invariant 5: one vehicle.promote audit-log row with
        #    matching trigger_site --
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert len(promote_calls) == 1, (
            "update_vehicle_expiry_dates must emit exactly one "
            "vehicle.promote audit-log row when promoting a "
            "GlobalVehicle for the first time"
        )
        promote_kwargs = promote_calls[0].kwargs
        assert promote_kwargs["entity_type"] == "org_vehicle"
        assert promote_kwargs["entity_id"] == ov.id
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["user_id"] == user_id
        assert (
            promote_kwargs["after_value"]["trigger_site"]
            == "customers.update_vehicle_dates"
        )
        assert promote_kwargs["after_value"]["rego"] == gv.rego
        assert promote_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


# ---------------------------------------------------------------------------
# Test 13 — invoice display reads serve OrgVehicle snapshot post-promotion
#           (Task 11.5)
# ---------------------------------------------------------------------------
#
# After Task 11.5 inverts the rego-keyed lookup order in
# ``get_invoice`` (and adds an OrgVehicle branch to ``public_router``),
# every workshop's invoice display must serve their own
# ``org_vehicles`` Customer_Driven_Field writes — not cross-tenant
# ``global_vehicles`` data written by another workshop.
#
# Scenario:
#   - Org A creates an invoice writing ``wof_expiry='2027-01-15'``.
#     Their post-promotion ``org_vehicles`` row holds that value;
#     ``global_vehicles.wof_expiry`` retains the (different) original.
#   - Org B has a ``customer_vehicles`` link still keyed via
#     ``global_vehicle_id`` (un-migrated). They have no
#     ``org_vehicles`` row for this rego.
#   - Org A's invoice detail must echo ``2027-01-15`` (the org
#     snapshot).
#   - Org B's invoice detail must echo the original
#     ``global_vehicles.wof_expiry`` (the Read_Fallback per Req 6),
#     never Org A's write — proving the cross-tenant leak is closed.
#   - The public (portal-token) view must apply the same precedence
#     so anonymous customer views never leak cross-tenant data.
#
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.6, 10.2, 15.5
# Design: Read Paths (extended) — invoice display section
# ---------------------------------------------------------------------------


def _make_invoice_for_detail(*, invoice_id, org_id, customer_id, rego):
    """Build a mock Invoice for the get_invoice / view_shared_invoice
    detail-read flow. Only the attributes referenced by the vehicle
    lookup branches under test are populated; the surrounding
    fields are stubbed with safe defaults so the surrounding
    serialisation steps don't fault the test.
    """
    from decimal import Decimal as _D

    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id
    inv.org_id = org_id
    inv.customer_id = customer_id
    inv.vehicle_rego = rego
    inv.vehicle_make = "OldMake"
    inv.vehicle_model = "OldModel"
    inv.vehicle_year = 2018
    inv.vehicle_odometer = 12_345
    inv.invoice_number = "INV-9001"
    inv.status = "issued"
    inv.total = _D("0.00")
    inv.subtotal = _D("0.00")
    inv.tax_amount = _D("0.00")
    inv.gst_amount = _D("0.00")
    inv.balance_due = _D("0.00")
    inv.amount_paid = _D("0.00")
    inv.discount_amount = _D("0.00")
    inv.discount_type = None
    inv.discount_value = _D("0.00")
    inv.exchange_rate_to_nzd = _D("1.00")
    inv.currency = "NZD"
    inv.invoice_data_json = {}
    inv.notes = None
    inv.notes_internal = None
    inv.notes_customer = None
    inv.payment_terms = None
    inv.terms_and_conditions = None
    inv.issue_date = date(2026, 1, 1)
    inv.due_date = date(2026, 1, 31)
    inv.created_at = None
    inv.updated_at = None
    inv.voided_at = None
    inv.voided_by = None
    inv.void_reason = None
    inv.created_by = None
    inv.branch_id = None
    inv.payment_page_url = None
    inv.job_card_appendix_html = None
    inv.share_token = None
    return inv


class TestInvoiceDetailServesOrgSnapshotAfterPromotion:
    """Validates the rego-keyed lookup inversion in
    ``app/modules/invoices/service.py::get_invoice``.

    Org A — promoted, has an OrgVehicle row whose ``wof_expiry``
    differs from the GlobalVehicle's original. Their invoice detail
    must echo the OrgVehicle value.

    Org B — un-promoted, has no OrgVehicle row. Their invoice detail
    must fall back to the GlobalVehicle value (Read_Fallback,
    Req 6) — never see Org A's write.
    """

    @pytest.mark.asyncio
    async def test_org_a_invoice_detail_returns_org_snapshot_wof(self):
        from app.modules.invoices.service import get_invoice

        org_a_id = uuid.uuid4()
        invoice_a_id = uuid.uuid4()
        customer_a_id = uuid.uuid4()
        rego = "ISO001"

        # The shared GlobalVehicle row — its wof_expiry is the pre-write
        # value that any un-promoted org continues to see.
        gv = _make_global_vehicle(rego=rego, wof_expiry=date(2025, 12, 1))

        # Org A's OrgVehicle snapshot — distinct wof_expiry written by
        # Org A's invoice flow.
        ov_a = MagicMock(spec=OrgVehicle)
        ov_a.id = uuid.uuid4()
        ov_a.org_id = org_a_id
        ov_a.rego = rego
        ov_a.make = "Toyota"
        ov_a.model = "Corolla"
        ov_a.year = 2020
        ov_a.wof_expiry = date(2027, 1, 15)
        ov_a.cof_expiry = None
        ov_a.odometer_last_recorded = 60_000
        ov_a.service_due_date = None

        invoice = _make_invoice_for_detail(
            invoice_id=invoice_a_id,
            org_id=org_a_id,
            customer_id=customer_a_id,
            rego=rego,
        )

        def _route(stmt, *args, **kwargs):
            sql_text = str(stmt).lower()
            r = MagicMock()

            if "from invoices" in sql_text and "where" in sql_text:
                r.scalar_one_or_none.return_value = invoice
                return r
            if "from line_items" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from organisations" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            if "from customers" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            # OrgVehicle is preferred — Task 11.5 inversion
            if "from org_vehicles" in sql_text:
                r.scalar_one_or_none.return_value = ov_a
                return r
            # Fallback path — should NOT fire for Org A
            if "from global_vehicles" in sql_text:
                r.scalar_one_or_none.return_value = gv
                return r
            if "from payments" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from credit_notes" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from users" in sql_text:
                r.all.return_value = []
                return r
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            r.all.return_value = []
            return r

        # Track which vehicle SELECTs ran, in order.
        vehicle_query_log: list[str] = []

        original_route = _route

        def _logged_route(stmt, *args, **kwargs):
            sql_text = str(stmt).lower()
            if "from org_vehicles" in sql_text:
                vehicle_query_log.append("org_vehicles")
            elif "from global_vehicles" in sql_text:
                vehicle_query_log.append("global_vehicles")
            return original_route(stmt, *args, **kwargs)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: _logged_route(stmt, *a, **kw))

        with patch(
            "app.modules.organisations.service.get_org_settings",
            new_callable=AsyncMock,
            return_value={
                "payment_terms_enabled": False,
                "terms_and_conditions_enabled": False,
            },
        ), patch(
            "app.modules.invoices.attachment_service.get_attachment_count",
            new_callable=AsyncMock,
            return_value=0,
        ):
            result = await get_invoice(db, org_id=org_a_id, invoice_id=invoice_a_id)

        # Org A reads the OrgVehicle snapshot, never the GlobalVehicle.
        assert "vehicle" in result, "vehicle dict must be present in invoice detail"
        v = result["vehicle"]
        assert v["wof_expiry"] == date(2027, 1, 15).isoformat(), (
            "Org A's invoice detail must echo their OrgVehicle.wof_expiry "
            "(2027-01-15) — the post-promotion org snapshot, not the "
            "pre-promotion GlobalVehicle value"
        )
        assert v["rego"] == rego
        assert v["odometer"] == 60_000

        # Lookup-order regression: OrgVehicle SELECT must run, and
        # because it returned a row, GlobalVehicle SELECT must NOT
        # fire afterwards. This is the inversion that Task 11.5
        # locks in.
        assert "org_vehicles" in vehicle_query_log, (
            "get_invoice must SELECT from org_vehicles first (Task 11.5 "
            "inversion); current call log: " + repr(vehicle_query_log)
        )
        # GlobalVehicle SELECT must not run after OrgVehicle returned a row.
        ov_idx = vehicle_query_log.index("org_vehicles")
        assert "global_vehicles" not in vehicle_query_log[ov_idx + 1:], (
            "GlobalVehicle SELECT must not fire after OrgVehicle returned "
            "a row for the calling org — the inverted fallback must "
            "short-circuit on the first OrgVehicle hit"
        )

    @pytest.mark.asyncio
    async def test_org_b_invoice_detail_falls_back_to_global_vehicle(self):
        """Org B — no OrgVehicle row — must fall back to GlobalVehicle
        (Read_Fallback, Req 6). They must NOT see Org A's write.
        """
        from app.modules.invoices.service import get_invoice

        org_b_id = uuid.uuid4()
        invoice_b_id = uuid.uuid4()
        customer_b_id = uuid.uuid4()
        rego = "ISO001"

        gv = _make_global_vehicle(rego=rego, wof_expiry=date(2025, 12, 1))
        gv_pre_wof = gv.wof_expiry

        invoice = _make_invoice_for_detail(
            invoice_id=invoice_b_id,
            org_id=org_b_id,
            customer_id=customer_b_id,
            rego=rego,
        )

        def _route(stmt, *args, **kwargs):
            sql_text = str(stmt).lower()
            r = MagicMock()
            if "from invoices" in sql_text and "where" in sql_text:
                r.scalar_one_or_none.return_value = invoice
                return r
            if "from line_items" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from organisations" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            if "from customers" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            # Org B has no OrgVehicle row for this rego.
            if "from org_vehicles" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            if "from global_vehicles" in sql_text:
                r.scalar_one_or_none.return_value = gv
                return r
            if "from payments" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from credit_notes" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from users" in sql_text:
                r.all.return_value = []
                return r
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            r.all.return_value = []
            return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: _route(stmt, *a, **kw))

        with patch(
            "app.modules.organisations.service.get_org_settings",
            new_callable=AsyncMock,
            return_value={
                "payment_terms_enabled": False,
                "terms_and_conditions_enabled": False,
            },
        ), patch(
            "app.modules.invoices.attachment_service.get_attachment_count",
            new_callable=AsyncMock,
            return_value=0,
        ):
            result = await get_invoice(db, org_id=org_b_id, invoice_id=invoice_b_id)

        v = result["vehicle"]
        # Org B sees the GlobalVehicle Read_Fallback value, never Org A's
        # write of 2027-01-15.
        assert v["wof_expiry"] == gv_pre_wof.isoformat(), (
            "Org B (no OrgVehicle row) must Read_Fallback to "
            "GlobalVehicle.wof_expiry — never observe Org A's "
            "OrgVehicle write (cross-tenant isolation, Req 6)"
        )
        assert v["wof_expiry"] != date(2027, 1, 15).isoformat()
        assert v["rego"] == rego


class TestPublicInvoiceViewServesOrgSnapshotAfterPromotion:
    """Mirrors the get_invoice test against the public portal-token
    endpoint (``app/modules/invoices/public_router.py::view_shared_invoice``).

    Without Task 11.5's structural addition of the OrgVehicle branch,
    the anonymous customer view served cross-tenant ``global_vehicles``
    Customer_Driven_Fields written by other workshops.
    """

    @pytest.mark.asyncio
    async def test_public_view_org_a_returns_org_snapshot(self):
        from app.modules.invoices.public_router import view_shared_invoice

        org_a_id = uuid.uuid4()
        invoice_a_id = uuid.uuid4()
        customer_a_id = uuid.uuid4()
        rego = "PUB001"
        share_token = "share-token-abc"

        gv = _make_global_vehicle(rego=rego, wof_expiry=date(2025, 12, 1))

        ov_a = MagicMock(spec=OrgVehicle)
        ov_a.id = uuid.uuid4()
        ov_a.org_id = org_a_id
        ov_a.rego = rego
        ov_a.make = "Toyota"
        ov_a.model = "Corolla"
        ov_a.year = 2020
        ov_a.wof_expiry = date(2027, 1, 15)
        ov_a.cof_expiry = None
        ov_a.odometer_last_recorded = 60_000
        ov_a.service_due_date = None

        invoice = _make_invoice_for_detail(
            invoice_id=invoice_a_id,
            org_id=org_a_id,
            customer_id=customer_a_id,
            rego=rego,
        )

        # view_shared_invoice exercises calculate_nzd_equivalent on totals;
        # the helper sets all totals to Decimal("0.00") so _invoice_to_dict
        # serialises cleanly without faulting on int * Decimal arithmetic.

        org_obj = MagicMock(spec=Organisation)
        org_obj.id = org_a_id
        org_obj.name = "Workshop A"
        org_obj.settings = {"gst_percentage": 15, "currency": "NZD"}

        # Track lookup order to lock in the inversion.
        vehicle_query_log: list[str] = []

        def _route(stmt, *args, **kwargs):
            sql_text = str(stmt).lower()
            r = MagicMock()

            if "from invoices" in sql_text and "where" in sql_text:
                r.scalar_one_or_none.return_value = invoice
                return r
            if "from line_items" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from organisations" in sql_text:
                r.scalar_one_or_none.return_value = org_obj
                return r
            if "from customers" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            if "from org_vehicles" in sql_text:
                vehicle_query_log.append("org_vehicles")
                r.scalar_one_or_none.return_value = ov_a
                return r
            if "from global_vehicles" in sql_text:
                vehicle_query_log.append("global_vehicles")
                r.scalar_one_or_none.return_value = gv
                return r
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: _route(stmt, *a, **kw))

        # Patch the HTML template render to capture the data dict the
        # router builds (we only need to verify the vehicle lookup
        # branched correctly — not the full template output).
        captured_render: dict = {}

        class _FakeTemplate:
            def render(self, **kwargs):
                captured_render.update(kwargs)
                return "<html></html>"

        class _FakeEnv:
            def __init__(self, *a, **kw):
                pass

            def get_template(self, name):
                return _FakeTemplate()

        with patch(
            "app.modules.invoices.public_router.Environment", _FakeEnv,
        ), patch(
            "app.modules.invoices.public_router.FileSystemLoader",
            lambda *a, **kw: None,
        ):
            await view_shared_invoice(share_token, db=db)

        # The Task 11.5 OrgVehicle branch must run first and short-
        # circuit before the GlobalVehicle SELECT.
        assert vehicle_query_log[0] == "org_vehicles", (
            "public_router must SELECT org_vehicles first (Task 11.5 "
            "structural addition); current call log: "
            + repr(vehicle_query_log)
        )
        assert "global_vehicles" not in vehicle_query_log, (
            "GlobalVehicle SELECT must not fire when the calling org "
            "has an OrgVehicle row — the public view must not leak "
            "cross-tenant GlobalVehicle Customer_Driven_Fields written "
            "by other workshops"
        )

        # The rendered invoice dict carries the OrgVehicle snapshot.
        invoice_dict = captured_render.get("invoice", {})
        v = invoice_dict.get("vehicle")
        assert v is not None, "public view must include vehicle dict"
        assert v["wof_expiry"] == date(2027, 1, 15).isoformat(), (
            "public view of Org A's invoice must echo their "
            "OrgVehicle.wof_expiry, not the pre-promotion GlobalVehicle "
            "value"
        )

    @pytest.mark.asyncio
    async def test_public_view_org_b_falls_back_to_global_vehicle(self):
        """Org B — no OrgVehicle row — public view must Read_Fallback to
        GlobalVehicle, never observe Org A's cross-tenant write.
        """
        from app.modules.invoices.public_router import view_shared_invoice

        org_b_id = uuid.uuid4()
        invoice_b_id = uuid.uuid4()
        customer_b_id = uuid.uuid4()
        rego = "PUB001"
        share_token = "share-token-org-b"

        gv = _make_global_vehicle(rego=rego, wof_expiry=date(2025, 12, 1))
        gv_pre_wof = gv.wof_expiry

        invoice = _make_invoice_for_detail(
            invoice_id=invoice_b_id,
            org_id=org_b_id,
            customer_id=customer_b_id,
            rego=rego,
        )

        org_obj = MagicMock(spec=Organisation)
        org_obj.id = org_b_id
        org_obj.name = "Workshop B"
        org_obj.settings = {"gst_percentage": 15, "currency": "NZD"}

        vehicle_query_log: list[str] = []

        def _route(stmt, *args, **kwargs):
            sql_text = str(stmt).lower()
            r = MagicMock()
            if "from invoices" in sql_text and "where" in sql_text:
                r.scalar_one_or_none.return_value = invoice
                return r
            if "from line_items" in sql_text:
                r.scalars.return_value.all.return_value = []
                return r
            if "from organisations" in sql_text:
                r.scalar_one_or_none.return_value = org_obj
                return r
            if "from customers" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            if "from org_vehicles" in sql_text:
                vehicle_query_log.append("org_vehicles")
                # Org B has no OrgVehicle row.
                r.scalar_one_or_none.return_value = None
                return r
            if "from global_vehicles" in sql_text:
                vehicle_query_log.append("global_vehicles")
                r.scalar_one_or_none.return_value = gv
                return r
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: _route(stmt, *a, **kw))

        captured_render: dict = {}

        class _FakeTemplate:
            def render(self, **kwargs):
                captured_render.update(kwargs)
                return "<html></html>"

        class _FakeEnv:
            def __init__(self, *a, **kw):
                pass

            def get_template(self, name):
                return _FakeTemplate()

        with patch(
            "app.modules.invoices.public_router.Environment", _FakeEnv,
        ), patch(
            "app.modules.invoices.public_router.FileSystemLoader",
            lambda *a, **kw: None,
        ):
            await view_shared_invoice(share_token, db=db)

        # OrgVehicle SELECT runs first (Task 11.5 structural addition);
        # because it returned None, the GlobalVehicle SELECT then runs.
        assert vehicle_query_log == ["org_vehicles", "global_vehicles"], (
            "Org B's public view must SELECT OrgVehicle first then fall "
            "back to GlobalVehicle when no row exists; got: "
            + repr(vehicle_query_log)
        )

        invoice_dict = captured_render.get("invoice", {})
        v = invoice_dict.get("vehicle")
        assert v is not None
        assert v["wof_expiry"] == gv_pre_wof.isoformat(), (
            "Org B's public view must Read_Fallback to GlobalVehicle — "
            "they must never observe Org A's OrgVehicle write of "
            "2027-01-15 (cross-tenant isolation, Req 6)"
        )
        assert v["wof_expiry"] != date(2027, 1, 15).isoformat()



# ---------------------------------------------------------------------------
# Task 11.7 — Widened link-existence checks at every link-creation site
# ---------------------------------------------------------------------------
#
# Today, four code paths check whether a customer-vehicle link already
# exists by matching only on a single FK column. After promotion migrates
# the link to ``org_vehicle_id``, the original ``global_vehicle_id``-only
# (or the post-promotion ``ov.id``-only-if-gv-set) check returns "no row
# found" and the calling flow happily creates a *second*
# ``customer_vehicles`` row. Result: duplicate links per
# ``(org_id, customer_id, vehicle)`` after the second touch of any
# promoted vehicle (Req 3.4, 9.6, 13.3).
#
# Task 11.7 widens the existence check at each site to be **rego-keyed**
# so it catches a link pointing at either the pre-promotion
# ``GlobalVehicle.id`` OR the post-promotion ``OrgVehicle.id`` for the
# same rego.
#
# The four tests below validate the post-fix behaviour — the calling
# flow must NOT create a second ``customer_vehicles`` row when a link
# for the same ``(org_id, customer_id, rego)`` already exists, regardless
# of which FK column the existing link uses.
#
# Requirements: 3.4, 9.6, 13.3
# Design: Read Paths (extended); Backwards Compatibility table
# ---------------------------------------------------------------------------


class TestKioskRepeatedCheckInAfterPromotionDoesNotDuplicateLink:
    """Promote a vehicle by issuing one invoice (simulated by a
    pre-existing ``customer_vehicles`` link with ``org_vehicle_id`` set
    and ``global_vehicle_id`` cleared), then run kiosk check-in for the
    same ``(customer, vehicle)`` pair. Assert the kiosk path's widened
    rego-keyed existence check finds the pre-promoted link and skips —
    no duplicate ``customer_vehicles`` row is added, and no second
    ``vehicle.promote`` audit row is emitted.
    """

    @pytest.mark.asyncio
    async def test_kiosk_repeated_check_in_after_promotion_does_not_duplicate_link(
        self,
    ):
        from app.modules.kiosk.service import _ensure_vehicle_linked

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="DUP001")

        # The kiosk path is called per check-in with the
        # ``global_vehicle_id`` from the lookup step, so the function
        # always receives the CarJam-cache id even when the customer
        # has already been promoted-and-linked via ``org_vehicle_id``.

        # Pre-existing promoted link — points at OrgVehicle, not
        # GlobalVehicle, simulating the state after one invoice has
        # already promoted this vehicle for the org.
        pre_existing_link = MagicMock(spec=CustomerVehicle)
        pre_existing_link.id = uuid.uuid4()
        pre_existing_link.org_id = org_id
        pre_existing_link.customer_id = customer_id
        pre_existing_link.org_vehicle_id = uuid.uuid4()
        pre_existing_link.global_vehicle_id = None

        # ``_ensure_vehicle_linked`` issues, in order, after Task 11.7:
        #   1. select(GlobalVehicle.rego).where(id=vehicle_id) → gv.rego
        #   2. widened CustomerVehicle SELECT (rego-keyed, both link
        #      types matched via outerjoin)                  → existing link
        #   ↳ returns early, no link_vehicle_to_customer call
        rego_lookup = MagicMock()
        rego_lookup.scalar_one_or_none.return_value = gv.rego

        widened_check = MagicMock()
        widened_check.scalar_one_or_none.return_value = pre_existing_link

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            rego_lookup,
            widened_check,
        ])

        with patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit, patch(
            "app.modules.vehicles.service.link_vehicle_to_customer",
            new_callable=AsyncMock,
        ) as mock_link:
            await _ensure_vehicle_linked(
                db,
                vehicle_id=gv.id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
                ip_address="10.0.0.1",
            )

        # No ``CustomerVehicle`` row added — the widened check found
        # the pre-existing promoted link and the function returned
        # early, before any link-creation work.
        added_cvs = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_cvs == [], (
            "kiosk._ensure_vehicle_linked must NOT add a duplicate "
            "customer_vehicles row when the same (customer, rego) is "
            "already linked via org_vehicle_id (Task 11.7)"
        )

        # No ``link_vehicle_to_customer`` call — the early-return path
        # must short-circuit before calling the helper.
        mock_link.assert_not_awaited()

        # No ``vehicle.promote`` audit row — promotion only fires
        # inside ``link_vehicle_to_customer`` which we just proved was
        # never called.
        promote_calls = _promote_audit_calls(mock_audit)
        assert promote_calls == [], (
            "kiosk._ensure_vehicle_linked must NOT trigger promotion "
            "when the link already exists via org_vehicle_id "
            "(Task 11.7 — duplicate-prevention via rego-keyed check)"
        )


class TestBookingRepeatedCreationAfterPromotionDoesNotDuplicateLink:
    """Promote a vehicle by issuing one invoice (simulated by a
    pre-existing ``customer_vehicles`` link with ``org_vehicle_id`` set
    and ``global_vehicle_id`` cleared), then create a booking for the
    same ``(customer, vehicle_rego)`` pair. Assert the bookings auto-link
    block's widened rego-keyed existence check finds the pre-promoted
    link and skips — no duplicate ``customer_vehicles`` row is added,
    and no second ``vehicle.promote`` audit row is emitted.
    """

    @pytest.mark.asyncio
    async def test_booking_repeated_creation_after_promotion_does_not_duplicate_link(
        self,
    ):
        from app.modules.bookings.models import Booking
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="DUP002")

        # Customer record looked up by ``create_booking`` (~L271).
        customer = MagicMock(spec=Customer)
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Pat"
        customer.last_name = "Tester"
        customer.email = "pat@example.com"
        customer.phone = "021-555-0100"

        # Pre-existing promoted link — points at OrgVehicle, not
        # GlobalVehicle, simulating the state after one invoice has
        # already promoted this vehicle for the org.
        pre_existing_link = MagicMock(spec=CustomerVehicle)
        pre_existing_link.id = uuid.uuid4()
        pre_existing_link.org_id = org_id
        pre_existing_link.customer_id = customer_id
        pre_existing_link.org_vehicle_id = uuid.uuid4()
        pre_existing_link.global_vehicle_id = None

        # ``create_booking`` issues, in order, with Task 11.7's widened
        # rego-keyed check at the front of the auto-link block:
        #   1. select(Customer)                              → customer
        #   2. db.add(Booking); db.flush() — no execute
        #   3. widened CustomerVehicle SELECT (rego-keyed)   → existing
        #   ↳ raises _BookingAutoLinkSkipped, exits the auto-link block
        #     without promoting or creating a link
        #   4. write_audit_log('booking.created') — patched
        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = customer

        widened_check = MagicMock()
        widened_check.scalar_one_or_none.return_value = pre_existing_link

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            customer_result,
            widened_check,
        ])

        scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)

        with patch(
            "app.modules.bookings.service._check_staff_availability",
            new_callable=AsyncMock,
        ), patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.bookings.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await create_booking(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                vehicle_rego=gv.rego,
                service_type="WOF Inspection",
                scheduled_at=scheduled_at,
                duration_minutes=60,
                send_confirmation=False,
                send_email_confirmation=False,
                send_sms_confirmation=False,
                ip_address="127.0.0.1",
            )

        # The booking row was still added — the auto-link skip does
        # NOT abort booking creation, only the redundant link work.
        booking = _added_of_type(db, Booking)
        assert booking.org_id == org_id
        assert booking.vehicle_rego == gv.rego

        # No new ``OrgVehicle`` row — the auto-link block exited via
        # the rego-keyed match before reaching the promote-and-link
        # branch.
        added_ovs = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], OrgVehicle)
        ]
        assert added_ovs == [], (
            "create_booking must NOT promote a vehicle when the link "
            "already exists via org_vehicle_id for the same rego"
        )

        # No new ``CustomerVehicle`` row — exactly one link still
        # exists for the (org, customer, rego), and it is the pre-
        # existing promoted one (Task 11.7 invariant).
        added_cvs = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_cvs == [], (
            "create_booking must NOT add a duplicate customer_vehicles "
            "row when the same (customer, rego) is already linked via "
            "org_vehicle_id (Task 11.7)"
        )

        # No ``vehicle.promote`` audit row — promotion was skipped.
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert promote_calls == [], (
            "create_booking must NOT trigger promotion when the link "
            "already exists via org_vehicle_id (Task 11.7)"
        )


class TestInvoiceRepeatedCreationAfterPromotionDoesNotDuplicateLink:
    """Promote a vehicle by issuing one invoice (simulated by a
    pre-existing ``customer_vehicles`` link with ``org_vehicle_id`` set
    and ``global_vehicle_id`` cleared, plus a pre-existing ``OrgVehicle``
    row for the rego), then create a *second* invoice for the same
    ``(customer, vehicle)`` pair.

    Asserts that Task 4.0's resolver extension (``_resolve_vehicle_type``
    returns ``("org", ov)`` for promoted vehicles) is sufficient to make
    the existing link-existence check at L955-994 work correctly: the
    check operates on ``effective_vehicle_id`` (= ``ov.id``
    post-resolution), which matches the pre-existing promoted link's
    ``org_vehicle_id``, so no duplicate ``customer_vehicles`` row is
    added and no second ``vehicle.promote`` audit row is emitted.
    """

    @pytest.mark.asyncio
    async def test_invoice_repeated_creation_after_promotion_does_not_duplicate_link(
        self,
    ):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        ov_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="DUP003")
        gv_pre = _snapshot_customer_driven_fields(gv)

        customer = _make_customer(customer_id=customer_id, org_id=org_id)
        org = _make_organisation(org_id=org_id)

        # Pre-existing promoted ``OrgVehicle`` row for the rego — once
        # ``_resolve_vehicle_type`` runs its rego follow-up query
        # (Task 4.0), it will return ``("org", ov)`` even though the
        # caller passes ``global_vehicle_id=gv.id``. We give it the
        # same field set as the GlobalVehicle so any field read works
        # interchangeably.
        ov = MagicMock(spec=OrgVehicle)
        ov.id = ov_id
        ov.org_id = org_id
        ov.rego = gv.rego
        for f in (
            "make", "model", "year", "colour", "body_type", "fuel_type",
            "engine_size", "num_seats", "registration_expiry", "vin",
            "chassis", "engine_no", "transmission", "country_of_origin",
            "number_of_owners", "vehicle_type", "power_kw", "tare_weight",
            "gross_vehicle_mass", "date_first_registered_nz", "plate_type",
            "submodel", "second_colour", "odometer_last_recorded",
            "service_due_date", "wof_expiry", "cof_expiry",
            "inspection_type",
        ):
            setattr(ov, f, getattr(gv, f))
        ov.is_manual_entry = False

        # Pre-existing promoted link — points at OrgVehicle (org_vehicle_id),
        # not GlobalVehicle. Returned by the CustomerVehicle existence
        # check at L955-994 inside ``create_invoice``.
        pre_existing_link = MagicMock(spec=CustomerVehicle)
        pre_existing_link.id = uuid.uuid4()
        pre_existing_link.org_id = org_id
        pre_existing_link.customer_id = customer_id
        pre_existing_link.org_vehicle_id = ov_id
        pre_existing_link.global_vehicle_id = None

        # ``_make_invoice_router`` consumes ``ov_existence_returns`` for
        # OrgVehicle SELECT results in call order. ``_resolve_vehicle_type``
        # issues two OrgVehicle SELECTs — one for the inspection_type
        # branch (~L875) which returns None, and one for the rego
        # follow-up (Task 4.0) which returns ``ov`` so the resolver
        # promotes ``vehicle_type`` to "org". After that, the auto-link
        # block sees ``vehicle_type == "org"`` and skips the
        # ``promote_vehicle`` call entirely (no third OrgVehicle SELECT
        # needed).
        router, router_state = _make_invoice_router(
            customer=customer,
            org=org,
            gv=gv,
            ov_existence_returns=[None, ov],
            cv_existence_returns=pre_existing_link,
        )

        captured: list = []
        db, _add = _make_db_for_invoice_test(router, ov_capture=captured)
        _add._router_state = router_state
        # Pre-seed the router state with the existing OrgVehicle so any
        # later org_vehicles SELECT short-circuits to it (mirrors the
        # idempotent path inside the same transaction).
        router_state["ov_inserted"] = ov
        db.execute = AsyncMock(side_effect=lambda stmt, *a, **kw: router(stmt, *a, **kw))

        # Customer-driven payload values that, in the first-touch test,
        # would land on the OrgVehicle. Here we use them to verify the
        # second-touch path also lands writes on the existing OrgVehicle
        # (not on global_vehicles, and not on a freshly-created OrgVehicle).
        new_odometer = 70_000
        new_service_due = date(2027, 1, 1)
        new_wof = date(2027, 3, 1)
        new_cof = date(2027, 5, 1)

        from app.modules.invoices.service import create_invoice

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_promote_audit, patch(
            "app.modules.invoices.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await create_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                global_vehicle_id=gv.id,
                vehicle_rego=gv.rego,
                vehicle_make=gv.make,
                vehicle_model=gv.model,
                vehicle_year=gv.year,
                vehicle_odometer=new_odometer,
                vehicle_service_due_date=new_service_due,
                vehicle_wof_expiry_date=new_wof,
                vehicle_cof_expiry_date=new_cof,
                status="draft",
                line_items_data=[],
                ip_address="127.0.0.1",
            )

        # No new ``OrgVehicle`` was added — the resolver returned the
        # pre-existing ``ov`` so no promotion was needed (Task 4.0 +
        # 11.7 — resolver-based duplicate-prevention).
        added_ovs = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], OrgVehicle)
        ]
        assert added_ovs == [], (
            "create_invoice must NOT promote a vehicle when the resolver "
            "returns an existing OrgVehicle for the rego (Task 4.0 + 11.7)"
        )

        # No new ``CustomerVehicle`` was added — the existence check at
        # L955-994 saw the pre-existing promoted link (matched on
        # ``org_vehicle_id == effective_vehicle_id``) and skipped the
        # link-creation block.
        added_cvs = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_cvs == [], (
            "create_invoice must NOT add a duplicate customer_vehicles "
            "row when (customer, rego) is already linked via "
            "org_vehicle_id (Task 4.0 + 11.7 — verifies the existence "
            "check uses vehicle_record.id / effective_vehicle_id, not "
            "the original global_vehicle_id parameter)"
        )

        # No ``vehicle.promote`` audit row — promotion was skipped.
        promote_calls = _promote_audit_calls(mock_promote_audit)
        assert promote_calls == [], (
            "create_invoice must NOT trigger promotion when the resolver "
            "returns an existing OrgVehicle (Task 4.0 — resolver-based "
            "duplicate-prevention)"
        )

        # ``global_vehicles`` Customer_Driven_Fields are unchanged —
        # the customer-driven writes landed on the existing OrgVehicle,
        # not on the cross-tenant cache.
        gv_post = _snapshot_customer_driven_fields(gv)
        assert gv_post == gv_pre, (
            "create_invoice must not mutate global_vehicles "
            "Customer_Driven_Fields on a second-touch invoice; "
            f"pre={gv_pre!r}, post={gv_post!r}"
        )


class TestFleetPortalAdminLinkAfterPromotionReturns409:
    """Admin attempts to add an already-promoted vehicle to a fleet
    account — the widened rego-keyed existence check must catch the
    promoted ``customer_vehicles`` row (pointing at ``org_vehicle_id``)
    and return HTTP 409, not silently create a second link.

    Also asserts the response detail message references the rego,
    matching today's behaviour.
    """

    @pytest.mark.asyncio
    async def test_fleet_portal_admin_link_after_promotion_returns_409(self):
        from fastapi import HTTPException

        from app.modules.fleet_portal.router import (
            _VehicleAddRequest,
            add_vehicle_to_fleet,
        )

        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        fleet_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="DUP004")

        # Pre-existing promoted link — points at OrgVehicle, not
        # GlobalVehicle, simulating the state after another flow
        # (e.g. invoice creation by a workshop user) promoted the
        # vehicle and migrated the link.
        pre_existing_link = MagicMock(spec=CustomerVehicle)
        pre_existing_link.id = uuid.uuid4()
        pre_existing_link.org_id = org_id
        pre_existing_link.customer_id = customer_id
        pre_existing_link.org_vehicle_id = uuid.uuid4()
        pre_existing_link.global_vehicle_id = None

        ctx = _make_fleet_ctx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            role="fleet_admin",
            fleet_account_id=fleet_account_id,
        )

        # ``add_vehicle_to_fleet`` issues, in order, when the org has
        # already promoted this rego:
        #   1. PortalFleetAccount.customer_id SELECT  → row(customer_id)
        #   2. select(GlobalVehicle).where(rego=...)  → gv
        #   3. promote_vehicle: pg_advisory_xact_lock → no-op
        #   4. promote_vehicle: OrgVehicle existence  → existing ov
        #      ↳ promote_vehicle returns the existing row (idempotent),
        #        no INSERT happens
        #   5. widened CustomerVehicle SELECT (rego-keyed, both link
        #      types matched via outerjoin)             → existing link
        #   ↳ HTTPException(409) raised before reminder seeding
        fa_row = MagicMock()
        fa_row.first.return_value = (customer_id,)

        gv_result = MagicMock()
        gv_result.scalars.return_value.first.return_value = gv

        advisory_result = MagicMock()
        advisory_result.scalar_one_or_none.return_value = None

        # promote_vehicle's existence check — return the same
        # ``OrgVehicle`` shape, simulating an already-promoted org.
        ov = MagicMock(spec=OrgVehicle)
        ov.id = pre_existing_link.org_vehicle_id
        ov.org_id = org_id
        ov.rego = gv.rego
        for f in (
            "make", "model", "year", "colour", "body_type", "fuel_type",
            "engine_size", "num_seats", "registration_expiry", "vin",
            "chassis", "engine_no", "transmission", "country_of_origin",
            "number_of_owners", "vehicle_type", "power_kw", "tare_weight",
            "gross_vehicle_mass", "date_first_registered_nz", "plate_type",
            "submodel", "second_colour", "odometer_last_recorded",
            "service_due_date", "wof_expiry", "cof_expiry",
            "inspection_type",
        ):
            setattr(ov, f, getattr(gv, f))
        ov.is_manual_entry = False

        ov_existence_result = MagicMock()
        ov_existence_result.scalar_one_or_none.return_value = ov

        existing_link_result = MagicMock()
        existing_link_result.scalars.return_value.first.return_value = (
            pre_existing_link
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            fa_row,
            gv_result,
            advisory_result,
            ov_existence_result,
            existing_link_result,
        ])

        body = _VehicleAddRequest(rego=gv.rego.lower(), odometer_at_link=42_000)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            with pytest.raises(HTTPException) as exc_info:
                await add_vehicle_to_fleet(
                    body=body,
                    ctx=ctx,
                    _=None,
                    db=db,
                )

        # HTTP 409 — admin must be told the vehicle is already in the
        # fleet rather than silently creating a duplicate.
        assert exc_info.value.status_code == 409, (
            "fleet_portal.admin_link must return HTTP 409 when the "
            "(customer, rego) is already linked via org_vehicle_id "
            "(Task 11.7)"
        )

        # Detail message references the rego — matches today's
        # behaviour ("Vehicle <REGO> is already in your fleet").
        assert gv.rego in exc_info.value.detail, (
            "fleet_portal.admin_link 409 detail must reference the "
            "rego so the admin can identify which vehicle conflicts"
        )

        # No new ``CustomerVehicle`` row was added — the 409 fires
        # before the constructor.
        added_cvs = [
            call.args[0]
            for call in db.add.call_args_list
            if call.args and isinstance(call.args[0], CustomerVehicle)
        ]
        assert added_cvs == [], (
            "fleet_portal.admin_link must NOT add a duplicate "
            "customer_vehicles row when the link already exists "
            "(Task 11.7)"
        )


# ---------------------------------------------------------------------------
# Task 12.1 — POST /api/v1/vehicles/{id}/refresh updates org_vehicles
# ---------------------------------------------------------------------------
#
# Exercises ``app/modules/vehicles/router.py::vehicle_refresh`` (the route
# handler, not the underlying ``refresh_vehicle`` service helper). Two
# tests:
#
#   - ``test_vehicle_refresh_route_updates_org_vehicles_when_promoted``
#     — set up a promoted ``org_vehicles`` row, mutate the underlying
#     ``global_vehicles`` CarJam fields via a stub, call the refresh
#     endpoint, assert (a) the ``org_vehicles`` row's CarJam-owned spec
#     fields now match the stubbed values, (b) its Customer_Driven_Fields
#     are byte-identical to before, (c) the audit log gets one
#     ``vehicle.refresh`` row plus one ``vehicle.manual_refresh`` row.
#
#   - ``test_vehicle_refresh_route_skips_manual_refresh_when_unpromoted``
#     — call the endpoint for an org that has no ``org_vehicles`` row;
#     assert no ``LookupError`` is raised, no ``vehicle.manual_refresh``
#     audit row is written, and only the standard ``vehicle.refresh``
#     audit row exists.
#
# Strategy: patch ``app.modules.vehicles.router.refresh_vehicle`` so the
# route's first call returns a deterministic dict and (in the promoted
# case) mutates ``gv`` in-place to simulate CarJam returning fresh
# CarJam_Owned_Spec_Field values. ``manual_refresh_vehicle`` is *not*
# patched in the promoted-case test — it runs its real logic of copying
# CarJam fields from the freshly-mutated ``gv`` into the existing ``ov``,
# which is exactly the integration-level invariant the task verifies.
# Inside ``manual_refresh_vehicle`` the call back into ``refresh_vehicle``
# is stubbed via ``app.modules.vehicles.service.refresh_vehicle`` — that
# inner call is a no-op for this test (the route's first call already
# applied the mutation).
#
# Requirements: 5.1, 5.2, 5.3, 5.4, 14.2
# Design: New Helper Functions → ``manual_refresh_vehicle()``;
#         Frontend Impact ("Refresh from CarJam" surface unchanged)
# ---------------------------------------------------------------------------


def _make_org_vehicle(*, org_id, rego, gv):
    """Build a mock ``OrgVehicle`` row pre-populated as if it had been
    promoted from ``gv``. CarJam_Owned_Spec_Fields start identical to
    ``gv``; Customer_Driven_Fields are deliberately set to org-owned
    values that differ from ``gv`` so the byte-identical-after assertion
    distinguishes the two field sets.
    """
    ov = MagicMock(spec=OrgVehicle)
    ov.id = uuid.uuid4()
    ov.org_id = org_id
    ov.rego = rego
    ov.is_manual_entry = False

    # CarJam_Owned_Spec_Fields (start matching gv — pre-refresh state).
    ov.make = gv.make
    ov.model = gv.model
    ov.year = gv.year
    ov.colour = gv.colour
    ov.body_type = gv.body_type
    ov.fuel_type = gv.fuel_type
    ov.engine_size = gv.engine_size
    ov.num_seats = gv.num_seats
    ov.registration_expiry = gv.registration_expiry
    ov.vin = gv.vin
    ov.chassis = gv.chassis
    ov.engine_no = gv.engine_no
    ov.transmission = gv.transmission
    ov.country_of_origin = gv.country_of_origin
    ov.number_of_owners = gv.number_of_owners
    ov.vehicle_type = gv.vehicle_type
    ov.power_kw = gv.power_kw
    ov.tare_weight = gv.tare_weight
    ov.gross_vehicle_mass = gv.gross_vehicle_mass
    ov.date_first_registered_nz = gv.date_first_registered_nz
    ov.plate_type = gv.plate_type
    ov.submodel = gv.submodel
    ov.second_colour = gv.second_colour

    # Customer_Driven_Fields — deliberately distinct from gv so the
    # "unchanged after refresh" assertion has teeth.
    ov.odometer_last_recorded = 99_999
    ov.service_due_date = date(2026, 11, 30)
    ov.wof_expiry = date(2026, 12, 31)
    ov.cof_expiry = None
    ov.inspection_type = "wof"

    return ov


def _make_request(*, org_id, user_id, ip_address="10.0.0.99"):
    """Build a mock ``fastapi.Request`` carrying just enough state for
    ``_extract_org_context`` to succeed.
    """
    request = MagicMock()
    request.state.org_id = str(org_id)
    request.state.user_id = str(user_id)
    request.state.client_ip = ip_address
    return request


class TestVehicleRefreshRouteUpdatesOrgVehiclesWhenPromoted:
    """The ``POST /api/v1/vehicles/{id}/refresh`` route must mirror the
    freshly-pulled CarJam_Owned_Spec_Fields into the calling org's
    ``org_vehicles`` row when one already exists. Customer_Driven_Fields
    on the org row remain untouched.
    """

    @pytest.mark.asyncio
    async def test_vehicle_refresh_route_updates_org_vehicles_when_promoted(self):
        from app.modules.vehicles.router import vehicle_refresh

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Pre-state: gv carries the OLD CarJam values; ov was promoted
        # from gv earlier and mirrors those OLD CarJam values, plus
        # carries org-owned Customer_Driven_Fields.
        gv = _make_global_vehicle(rego="REF001", make="Toyota", model="Corolla", colour="White")
        ov = _make_org_vehicle(org_id=org_id, rego=gv.rego, gv=gv)

        # Snapshot: ov's Customer_Driven_Fields BEFORE the refresh.
        ov_customer_driven_pre = _snapshot_customer_driven_fields(ov)

        # Stubbed CarJam response — what ``refresh_vehicle`` will write
        # into ``gv`` on the route's first call. The values differ from
        # the pre-state so we can distinguish "copied from gv" vs
        # "unchanged".
        new_make = "Toyota"
        new_model = "Camry"          # changed
        new_colour = "Silver"        # changed
        new_year = 2022              # changed
        new_engine_size = "2.5L"     # changed
        new_registration_expiry = date(2027, 6, 30)  # changed

        # Track what ``refresh_vehicle`` was called with so we can
        # distinguish the route's call from manual_refresh_vehicle's
        # internal call.
        refresh_calls = []

        async def _fake_refresh_vehicle(db, redis, *, vehicle_id, org_id, user_id, ip_address):
            """Mutate ``gv`` to simulate a fresh CarJam pull, then return
            the dict the route's first call expects. The second call —
            issued from inside ``manual_refresh_vehicle`` — is a no-op.
            """
            refresh_calls.append(vehicle_id)
            # Apply CarJam mutation only on the first call (the route's).
            # The second call (from manual_refresh_vehicle) re-pulls; for
            # this test we keep the values stable so the copy step is
            # deterministic.
            if len(refresh_calls) == 1:
                gv.make = new_make
                gv.model = new_model
                gv.colour = new_colour
                gv.year = new_year
                gv.engine_size = new_engine_size
                gv.registration_expiry = new_registration_expiry
            from app.modules.vehicles.service import _global_vehicle_to_dict
            gv.last_pulled_at = MagicMock()
            gv.last_pulled_at.isoformat = MagicMock(return_value="2026-05-08T12:00:00+00:00")
            gv.lookup_type = "abcd"
            return _global_vehicle_to_dict(gv, source="abcd")

        # DB execute side-effect: a callable router that returns the
        # right scalar for each query the route + manual_refresh_vehicle
        # issue. Call sequence:
        #   1. Route: ``select(OrgVehicle.id).where(...)`` → ov.id
        #   2. manual_refresh_vehicle: ``select(OrgVehicle).where(...)`` → ov
        #   3. manual_refresh_vehicle: ``select(GlobalVehicle).where(...)`` → gv
        ov_id_result = MagicMock()
        ov_id_result.scalar_one_or_none.return_value = ov.id

        ov_row_result = MagicMock()
        ov_row_result.scalar_one_or_none.return_value = ov

        gv_row_result = MagicMock()
        gv_row_result.scalar_one_or_none.return_value = gv

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            ov_id_result,
            ov_row_result,
            gv_row_result,
        ])

        redis = MagicMock()
        request = _make_request(org_id=org_id, user_id=user_id)

        with patch(
            "app.modules.vehicles.router.refresh_vehicle",
            new=_fake_refresh_vehicle,
        ), patch(
            "app.modules.vehicles.service.refresh_vehicle",
            new=_fake_refresh_vehicle,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            response = await vehicle_refresh(
                vehicle_id=gv.id,
                request=request,
                db=db,
                redis=redis,
            )

        # Route returned the standard VehicleRefreshResponse — not a
        # JSONResponse error.
        from app.modules.vehicles.schemas import VehicleRefreshResponse
        assert isinstance(response, VehicleRefreshResponse), (
            "vehicle_refresh must return VehicleRefreshResponse on success"
        )
        assert response.rego == gv.rego
        assert response.make == new_make
        assert response.model == new_model
        assert response.colour == new_colour

        # -- Invariant A: org_vehicles CarJam fields now match the stub --
        assert ov.make == new_make, (
            "manual_refresh_vehicle must copy gv.make → ov.make after the "
            "CarJam refresh"
        )
        assert ov.model == new_model, (
            "manual_refresh_vehicle must copy gv.model → ov.model"
        )
        assert ov.colour == new_colour
        assert ov.year == new_year
        assert ov.engine_size == new_engine_size
        assert ov.registration_expiry == new_registration_expiry

        # -- Invariant B: org_vehicles Customer_Driven_Fields byte-identical --
        ov_customer_driven_post = _snapshot_customer_driven_fields(ov)
        assert ov_customer_driven_post == ov_customer_driven_pre, (
            "manual_refresh_vehicle must NOT touch Customer_Driven_Fields "
            "on org_vehicles — those are operational state owned by the "
            "org and must survive the spec-cache refresh (Req 5.3, "
            "Task 1.3); "
            f"pre={ov_customer_driven_pre!r}, post={ov_customer_driven_post!r}"
        )

        # -- Invariant C: audit log has one vehicle.refresh and one
        # vehicle.manual_refresh row. ``refresh_vehicle`` is patched so
        # the ``vehicle.refresh`` row is not actually written by the
        # patched function — but ``manual_refresh_vehicle`` runs its real
        # audit logic, so we assert the manual-refresh side here.
        manual_refresh_calls = [
            c for c in mock_audit.await_args_list
            if c.kwargs.get("action") == "vehicle.manual_refresh"
        ]
        assert len(manual_refresh_calls) == 1, (
            "manual_refresh_vehicle must emit exactly one "
            "vehicle.manual_refresh audit-log row"
        )
        manual_refresh_kwargs = manual_refresh_calls[0].kwargs
        assert manual_refresh_kwargs["entity_type"] == "org_vehicle"
        assert manual_refresh_kwargs["entity_id"] == ov.id
        assert manual_refresh_kwargs["org_id"] == org_id
        assert manual_refresh_kwargs["user_id"] == user_id
        assert manual_refresh_kwargs["after_value"]["rego"] == gv.rego
        assert manual_refresh_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)


class TestVehicleRefreshRouteSkipsManualRefreshWhenUnpromoted:
    """When the calling org has no ``org_vehicles`` row for the rego, the
    route must skip the ``manual_refresh_vehicle`` follow-up silently.

    No ``LookupError`` is raised (because the existence check happens
    before the call). No ``vehicle.manual_refresh`` audit row is
    written. The user will pick up the fresh ``global_vehicles`` data on
    their next read via Read_Fallback.
    """

    @pytest.mark.asyncio
    async def test_vehicle_refresh_route_skips_manual_refresh_when_unpromoted(self):
        from app.modules.vehicles.router import vehicle_refresh

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        gv = _make_global_vehicle(rego="REF002")

        async def _fake_refresh_vehicle(db, redis, *, vehicle_id, org_id, user_id, ip_address):
            from app.modules.vehicles.service import _global_vehicle_to_dict
            gv.last_pulled_at = MagicMock()
            gv.last_pulled_at.isoformat = MagicMock(return_value="2026-05-08T12:00:00+00:00")
            gv.lookup_type = "abcd"
            return _global_vehicle_to_dict(gv, source="abcd")

        # Existence check returns None → manual_refresh_vehicle is NOT
        # called. Only the one execute call from the route runs.
        ov_id_result = MagicMock()
        ov_id_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[ov_id_result])

        redis = MagicMock()
        request = _make_request(org_id=org_id, user_id=user_id)

        # Patch ``manual_refresh_vehicle`` so we can assert it was NOT
        # called. (If the route's check-then-call ordering is inverted
        # and the helper runs anyway, the test will still pass because
        # it would raise LookupError, but the explicit assertion makes
        # the contract crisp.)
        with patch(
            "app.modules.vehicles.router.refresh_vehicle",
            new=_fake_refresh_vehicle,
        ), patch(
            "app.modules.vehicles.router.manual_refresh_vehicle",
            new_callable=AsyncMock,
        ) as mock_manual_refresh, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            response = await vehicle_refresh(
                vehicle_id=gv.id,
                request=request,
                db=db,
                redis=redis,
            )

        from app.modules.vehicles.schemas import VehicleRefreshResponse
        assert isinstance(response, VehicleRefreshResponse), (
            "vehicle_refresh must return VehicleRefreshResponse on success "
            "even when no org_vehicles row exists for the calling org"
        )

        # -- Invariant A: manual_refresh_vehicle was not invoked --
        mock_manual_refresh.assert_not_awaited()

        # -- Invariant B: no vehicle.manual_refresh audit row was written --
        manual_refresh_calls = [
            c for c in mock_audit.await_args_list
            if c.kwargs.get("action") == "vehicle.manual_refresh"
        ]
        assert manual_refresh_calls == [], (
            "no vehicle.manual_refresh audit row must be written when the "
            "org has no org_vehicles row for the rego (the route skips "
            "the helper silently — Read_Fallback covers the next read)"
        )


# ---------------------------------------------------------------------------
# Task 12.2 — POST /api/v1/vehicles/bulk-refresh updates org_vehicles
# ---------------------------------------------------------------------------
#
# Exercises ``app/modules/vehicles/router.py::bulk_refresh_vehicles``. Two
# tests cover the bulk path:
#
#   - ``test_bulk_refresh_route_updates_org_vehicles_for_promoted_regos``
#     — mixed batch of three vehicles where two are promoted and one is
#     not. Asserts (a) every promoted org_vehicles row has its
#     CarJam_Owned_Spec_Fields refreshed from the freshly-pulled
#     global_vehicles row, (b) the un-promoted vehicle silently skips
#     the manual_refresh_vehicle follow-up, (c) Customer_Driven_Fields
#     on the promoted org_vehicles rows are byte-identical before vs
#     after, (d) the response contains all three results with the
#     correct succeeded/failed totals.
#
#   - ``test_bulk_refresh_route_continues_when_manual_refresh_fails``
#     — when manual_refresh_vehicle raises, the bulk run must continue
#     processing remaining vehicles (best-effort follow-up). Asserts
#     the failing vehicle is still recorded as ``status='success'``
#     because the underlying refresh_vehicle call succeeded — only the
#     org-vehicle mirror step failed — and the next vehicle in the
#     batch is processed normally.
#
# Strategy: patch ``app.modules.vehicles.router.refresh_vehicle`` to
# return a deterministic result dict per call, and patch
# ``app.modules.vehicles.router.manual_refresh_vehicle`` so we can
# observe which regos triggered the per-org follow-up and inject
# failures on demand. The DB ``execute`` calls are routed through a
# scalar-side-effect list so each promoted/unpromoted lookup returns
# the right value.
#
# Requirements: 5.1, 5.2, 14.2
# Design: New Helper Functions → ``manual_refresh_vehicle()``
# ---------------------------------------------------------------------------


class TestBulkRefreshRouteUpdatesOrgVehiclesForPromotedRegos:
    """The bulk-refresh route must call ``manual_refresh_vehicle`` once
    per promoted rego in the batch, and skip the call silently for any
    rego that has not been promoted for the calling org.
    """

    @pytest.mark.asyncio
    async def test_bulk_refresh_route_updates_org_vehicles_for_promoted_regos(self):
        from app.modules.vehicles.router import bulk_refresh_vehicles
        from app.modules.vehicles.schemas import BulkRefreshRequest

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Three vehicles: promoted, un-promoted, promoted.
        gv1 = _make_global_vehicle(rego="BLK001", make="Toyota")
        gv2 = _make_global_vehicle(rego="BLK002", make="Honda")
        gv3 = _make_global_vehicle(rego="BLK003", make="Ford")

        # Org has been promoted for gv1 and gv3 only.
        ov1 = _make_org_vehicle(org_id=org_id, rego=gv1.rego, gv=gv1)
        ov3 = _make_org_vehicle(org_id=org_id, rego=gv3.rego, gv=gv3)

        # Snapshot Customer_Driven_Fields BEFORE the refresh so we can
        # assert byte-identical equality afterwards.
        ov1_pre = _snapshot_customer_driven_fields(ov1)
        ov3_pre = _snapshot_customer_driven_fields(ov3)

        # Fake refresh_vehicle returns a minimal dict per vehicle. The
        # bulk route never inspects fields beyond ``rego``, ``wof_expiry``,
        # and ``cof_expiry`` so a small dict is sufficient.
        refresh_calls: list[uuid.UUID] = []

        async def _fake_refresh_vehicle(
            db, redis, *, vehicle_id, org_id, user_id, ip_address
        ):
            refresh_calls.append(vehicle_id)
            mapping = {gv1.id: gv1, gv2.id: gv2, gv3.id: gv3}
            gv = mapping[vehicle_id]
            return {
                "rego": gv.rego,
                "make": gv.make,
                "model": gv.model,
                "wof_expiry": gv.wof_expiry.isoformat() if gv.wof_expiry else None,
                "cof_expiry": gv.cof_expiry.isoformat() if gv.cof_expiry else None,
            }

        # The route issues one ``select(OrgVehicle.id)`` lookup per
        # successful refresh, in vehicle_ids order. Returns:
        #   1. BLK001 → ov1.id  (promoted)
        #   2. BLK002 → None     (un-promoted)
        #   3. BLK003 → ov3.id  (promoted)
        ov1_id_result = MagicMock()
        ov1_id_result.scalar_one_or_none.return_value = ov1.id
        ov2_id_result = MagicMock()
        ov2_id_result.scalar_one_or_none.return_value = None
        ov3_id_result = MagicMock()
        ov3_id_result.scalar_one_or_none.return_value = ov3.id

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            ov1_id_result,
            ov2_id_result,
            ov3_id_result,
        ])

        # Track manual_refresh_vehicle calls so we can assert it fired
        # once per promoted rego and not at all for the un-promoted one.
        manual_refresh_calls: list[str] = []

        async def _fake_manual_refresh_vehicle(
            db, redis, *, org_id, rego, user_id, ip_address
        ):
            manual_refresh_calls.append(rego)
            mapping = {ov1.rego: ov1, ov3.rego: ov3}
            ov = mapping[rego]
            # Simulate the helper copying CarJam-owned spec fields from
            # the (already-refreshed) global_vehicles row into ov.
            gv_for_rego = {gv1.rego: gv1, gv3.rego: gv3}[rego]
            ov.make = gv_for_rego.make
            ov.model = gv_for_rego.model
            ov.colour = gv_for_rego.colour
            ov.year = gv_for_rego.year
            return ov

        redis = MagicMock()
        request = _make_request(org_id=org_id, user_id=user_id)

        body = BulkRefreshRequest(vehicle_ids=[gv1.id, gv2.id, gv3.id])

        with patch(
            "app.modules.vehicles.router.refresh_vehicle",
            new=_fake_refresh_vehicle,
        ), patch(
            "app.modules.vehicles.router.manual_refresh_vehicle",
            new=_fake_manual_refresh_vehicle,
        ), patch(
            "app.modules.vehicles.router.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            response = await bulk_refresh_vehicles(
                body=body,
                request=request,
                db=db,
                redis=redis,
            )

        # -- Invariant A: every promoted rego triggered manual_refresh_vehicle --
        assert sorted(manual_refresh_calls) == sorted([gv1.rego, gv3.rego]), (
            f"manual_refresh_vehicle must be called once per promoted "
            f"rego in the batch; got {manual_refresh_calls!r}"
        )

        # -- Invariant B: the un-promoted rego did NOT trigger the helper --
        assert gv2.rego not in manual_refresh_calls, (
            "un-promoted regos must skip manual_refresh_vehicle silently — "
            f"got {manual_refresh_calls!r}"
        )

        # -- Invariant C: Customer_Driven_Fields on ov1 and ov3 unchanged --
        assert _snapshot_customer_driven_fields(ov1) == ov1_pre, (
            "manual_refresh_vehicle must NOT touch Customer_Driven_Fields "
            "on ov1 — they are operational state owned by the org "
            "(Task 1.3 / Req 5.3)"
        )
        assert _snapshot_customer_driven_fields(ov3) == ov3_pre, (
            "manual_refresh_vehicle must NOT touch Customer_Driven_Fields "
            "on ov3"
        )

        # -- Invariant D: response shape is correct --
        assert response.total == 3
        assert response.succeeded == 3
        assert response.failed == 0
        assert len(response.results) == 3
        assert response.results[0].rego == gv1.rego
        assert response.results[0].status == "success"
        assert response.results[1].rego == gv2.rego
        assert response.results[1].status == "success"
        assert response.results[2].rego == gv3.rego
        assert response.results[2].status == "success"

        # -- Invariant E: refresh_vehicle was called once per vehicle --
        assert refresh_calls == [gv1.id, gv2.id, gv3.id]


class TestBulkRefreshRouteContinuesWhenManualRefreshFails:
    """``manual_refresh_vehicle`` is best-effort. When it raises, the
    bulk run must continue processing the remaining vehicle_ids. The
    failing vehicle stays recorded as ``status='success'`` because the
    underlying ``refresh_vehicle`` call succeeded — only the org-vehicle
    mirror step failed.
    """

    @pytest.mark.asyncio
    async def test_bulk_refresh_route_continues_when_manual_refresh_fails(self):
        from app.modules.vehicles.router import bulk_refresh_vehicles
        from app.modules.vehicles.schemas import BulkRefreshRequest

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        gv1 = _make_global_vehicle(rego="BLK101")
        gv2 = _make_global_vehicle(rego="BLK102")

        ov1 = _make_org_vehicle(org_id=org_id, rego=gv1.rego, gv=gv1)
        ov2 = _make_org_vehicle(org_id=org_id, rego=gv2.rego, gv=gv2)

        async def _fake_refresh_vehicle(
            db, redis, *, vehicle_id, org_id, user_id, ip_address
        ):
            mapping = {gv1.id: gv1, gv2.id: gv2}
            gv = mapping[vehicle_id]
            return {
                "rego": gv.rego,
                "make": gv.make,
                "model": gv.model,
                "wof_expiry": gv.wof_expiry.isoformat() if gv.wof_expiry else None,
                "cof_expiry": gv.cof_expiry.isoformat() if gv.cof_expiry else None,
            }

        # Both regos are promoted; the route therefore issues two
        # ``select(OrgVehicle.id)`` lookups, both returning a non-None id.
        ov1_id_result = MagicMock()
        ov1_id_result.scalar_one_or_none.return_value = ov1.id
        ov2_id_result = MagicMock()
        ov2_id_result.scalar_one_or_none.return_value = ov2.id

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock(side_effect=[ov1_id_result, ov2_id_result])

        manual_refresh_calls: list[str] = []

        async def _failing_then_succeeding_manual_refresh(
            db, redis, *, org_id, rego, user_id, ip_address
        ):
            manual_refresh_calls.append(rego)
            if rego == gv1.rego:
                # Simulate a transient failure (e.g. CarJam rate-limit
                # bubbling up out of the inner refresh, or a row-lock
                # timeout). The bulk run must absorb this and carry on.
                raise RuntimeError("simulated manual_refresh_vehicle failure")
            mapping = {gv2.rego: ov2}
            return mapping[rego]

        redis = MagicMock()
        request = _make_request(org_id=org_id, user_id=user_id)

        body = BulkRefreshRequest(vehicle_ids=[gv1.id, gv2.id])

        with patch(
            "app.modules.vehicles.router.refresh_vehicle",
            new=_fake_refresh_vehicle,
        ), patch(
            "app.modules.vehicles.router.manual_refresh_vehicle",
            new=_failing_then_succeeding_manual_refresh,
        ), patch(
            "app.modules.vehicles.router.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            response = await bulk_refresh_vehicles(
                body=body,
                request=request,
                db=db,
                redis=redis,
            )

        # -- Invariant A: both regos triggered manual_refresh_vehicle --
        # (the failure on the first did NOT short-circuit the second)
        assert manual_refresh_calls == [gv1.rego, gv2.rego], (
            "best-effort follow-up must continue past a manual_refresh_vehicle "
            "exception so subsequent vehicles still receive the per-org "
            f"refresh; got {manual_refresh_calls!r}"
        )

        # -- Invariant B: response treats both as succeeded — the
        # underlying refresh_vehicle call worked for each, the
        # follow-up failure is logged and absorbed. --
        assert response.total == 2
        assert response.succeeded == 2
        assert response.failed == 0
        assert response.results[0].rego == gv1.rego
        assert response.results[0].status == "success"
        assert response.results[1].rego == gv2.rego
        assert response.results[1].status == "success"
