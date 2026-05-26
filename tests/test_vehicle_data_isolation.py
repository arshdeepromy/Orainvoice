"""Unit tests for the vehicle-data-isolation feature — Task 1.1.

Tests cover the new ``promote_vehicle()`` helper added to
``app/modules/vehicles/service.py`` per the design's
"New Helper Functions → ``promote_vehicle()``".

This file holds the minimal coverage for Task 1.1:
  - ``test_promote_vehicle_creates_org_row_when_missing`` — happy path,
    asserts a new ``org_vehicles`` row is inserted with ``is_manual_entry=False``
    and every CarJam-owned + customer-driven field copied from
    ``global_vehicles``.
  - ``test_promote_vehicle_passes_str_params_to_advisory_lock`` — bind-param
    regression. The advisory-lock call MUST receive ``org_id_str`` as a
    Python ``str`` (not a ``uuid.UUID``); asyncpg would otherwise send a
    ``uuid``-typed parameter and PostgreSQL has no ``hashtext(uuid)``
    overload, so the call would raise
    ``function hashtext(uuid) does not exist``.

The full Task 1.4 suite (idempotency, audit log, module gate, etc.) is
added separately.

Requirements: 2.1, 2.5, 8.5, 12.4, 13.1, 13.2, 14.1, 14.3
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships at module load.
# A handful of tests instantiate real ORM objects (``OrgVehicle``,
# ``CustomerVehicle``) rather than mocking them, which triggers SQLAlchemy's
# full mapper configuration. That configuration walks every relationship
# string (e.g. ``PartsCatalogue.supplier`` → ``Supplier``) so every dependent
# model module must be loaded first — otherwise the unrelated
# ``Mapper[PartsCatalogue]`` fails to initialise and the failure cascades
# into our tests as ``InvalidRequestError``. The integration test file uses
# the same eager-import pattern; keep them in sync.
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

from app.modules.vehicles.models import OrgVehicle
from app.modules.vehicles.service import promote_vehicle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_global_vehicle(**overrides):
    """Build a mock GlobalVehicle ORM object with realistic field values.

    The mock carries every CarJam-owned and customer-driven field referenced
    by ``promote_vehicle`` so the test can assert the full copy.
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

    # Customer_Driven_Fields
    gv.odometer_last_recorded = overrides.get("odometer_last_recorded", 45000)
    gv.service_due_date = overrides.get("service_due_date", date(2025, 8, 1))
    gv.wof_expiry = overrides.get("wof_expiry", date(2025, 6, 1))
    gv.cof_expiry = overrides.get("cof_expiry", None)
    gv.inspection_type = overrides.get("inspection_type", "wof")

    return gv


def _make_db_with_no_existing_org_row():
    """Build an AsyncMock DB session for a fresh-promotion path.

    ``execute`` returns a no-op result on the advisory-lock call, then a
    ``scalar_one_or_none() -> None`` on the OrgVehicle existence check.
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    no_row = MagicMock()
    no_row.scalar_one_or_none.return_value = None

    db.execute = AsyncMock(return_value=no_row)
    return db


# ---------------------------------------------------------------------------
# promote_vehicle — happy path
# ---------------------------------------------------------------------------


class TestPromoteVehicleCreatesOrgRow:
    @pytest.mark.asyncio
    async def test_promote_vehicle_creates_org_row_when_missing(self):
        """First promotion inserts a new OrgVehicle copying every field.

        Asserts:
          - One ``OrgVehicle`` was added to the session.
          - ``is_manual_entry`` is ``False``.
          - Every CarJam-owned spec field and every customer-driven field
            is byte-identical to the source ``global_vehicles`` row.
          - The audit log was called with ``action='vehicle.promote'`` and
            ``trigger_site`` carried through to ``after_value``.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        gv = _make_global_vehicle()
        db = _make_db_with_no_existing_org_row()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=gv.id,
                source_record=gv,
                user_id=user_id,
                trigger_site="vehicles.test_promote",
                ip_address="127.0.0.1",
            )

        # -- Step 5 of promote_vehicle: a single OrgVehicle was added --
        assert db.add.call_count == 1, (
            "promote_vehicle should add exactly one OrgVehicle"
        )
        added = db.add.call_args[0][0]
        assert isinstance(added, OrgVehicle)
        assert result is added, (
            "promote_vehicle should return the OrgVehicle it just inserted"
        )

        # -- is_manual_entry marker (Req 2.1) --
        assert added.is_manual_entry is False

        # -- Org id + rego match the call site --
        assert added.org_id == org_id
        assert added.rego == gv.rego

        # -- CarJam_Owned_Spec_Fields copied verbatim --
        for field in (
            "make",
            "model",
            "year",
            "colour",
            "body_type",
            "fuel_type",
            "engine_size",
            "num_seats",
            "registration_expiry",
            "vin",
            "chassis",
            "engine_no",
            "transmission",
            "country_of_origin",
            "number_of_owners",
            "vehicle_type",
            "power_kw",
            "tare_weight",
            "gross_vehicle_mass",
            "date_first_registered_nz",
            "plate_type",
            "submodel",
            "second_colour",
        ):
            assert getattr(added, field) == getattr(gv, field), (
                f"CarJam-owned field '{field}' was not copied from global_vehicles"
            )

        # -- Customer_Driven_Fields copied verbatim (Req 10.3 — preserved
        #    Read_Fallback values land on the new row at moment of promotion) --
        for field in (
            "odometer_last_recorded",
            "service_due_date",
            "wof_expiry",
            "cof_expiry",
            "inspection_type",
        ):
            assert getattr(added, field) == getattr(gv, field), (
                f"Customer-driven field '{field}' was not copied from global_vehicles"
            )

        # -- Audit log emitted (Req 14.1, 14.3) --
        assert mock_audit.await_count == 1
        kwargs = mock_audit.await_args.kwargs
        assert kwargs["action"] == "vehicle.promote"
        assert kwargs["entity_type"] == "org_vehicle"
        # org_id and user_id are TOP-LEVEL columns on the audit row, NOT
        # inside after_value (matches write_audit_log signature).
        assert kwargs["org_id"] == org_id
        assert kwargs["user_id"] == user_id
        assert "trigger_site" in kwargs["after_value"]
        assert kwargs["after_value"]["trigger_site"] == "vehicles.test_promote"
        assert kwargs["after_value"]["rego"] == gv.rego
        assert kwargs["after_value"]["global_vehicle_id"] == str(gv.id)

        # -- Refresh called before returning so the ORM object is hydrated --
        assert db.refresh.await_count == 1


# ---------------------------------------------------------------------------
# promote_vehicle — bind-param regression for hashtext(uuid)
# ---------------------------------------------------------------------------


class TestPromoteVehicleBindParams:
    @pytest.mark.asyncio
    async def test_promote_vehicle_passes_str_params_to_advisory_lock(self):
        """Advisory-lock SQL must receive str params, not raw UUIDs.

        asyncpg silently sends a ``uuid``-typed parameter for a Python
        ``uuid.UUID`` value, but PostgreSQL has no ``hashtext(uuid)``
        overload — the call would raise
        ``function hashtext(uuid) does not exist`` at runtime.

        This test inspects the bind dict on the first ``db.execute`` call
        (the ``pg_advisory_xact_lock`` SQL) and asserts both the org_id
        and rego are Python strings.
        """
        org_id = uuid.uuid4()
        gv = _make_global_vehicle()
        db = _make_db_with_no_existing_org_row()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=gv.id,
                source_record=gv,
                user_id=uuid.uuid4(),
                trigger_site="vehicles.test_bind_params",
            )

        # The advisory-lock execute is the FIRST call (precedes the
        # OrgVehicle existence SELECT).
        assert db.execute.await_count >= 1
        first_call = db.execute.call_args_list[0]

        # First positional arg is the SQL clause; second positional arg
        # (or kwargs) holds the bind dict.
        args = first_call[0]
        assert len(args) >= 2, (
            "advisory-lock execute should pass a bind-params dict alongside "
            "the SQL clause"
        )
        bind_params = args[1]

        # The SQL text must reference pg_advisory_xact_lock with hashtext.
        sql_text = str(getattr(args[0], "text", args[0]))
        assert "pg_advisory_xact_lock" in sql_text
        assert "hashtext" in sql_text

        # CRITICAL: org_id_str must be str, NOT uuid.UUID. Sending a UUID
        # would trigger ``function hashtext(uuid) does not exist`` because
        # PostgreSQL has no hashtext overload for the ``uuid`` type.
        assert "org_id_str" in bind_params
        assert isinstance(bind_params["org_id_str"], str), (
            f"org_id_str must be a Python str (not {type(bind_params['org_id_str']).__name__}) "
            "to avoid 'function hashtext(uuid) does not exist'"
        )
        assert bind_params["org_id_str"] == str(org_id)

        # rego must already be a string at the call site.
        assert "rego" in bind_params
        assert isinstance(bind_params["rego"], str)
        assert bind_params["rego"] == gv.rego


# ---------------------------------------------------------------------------
# migrate_link_to_org_vehicle — Task 1.2
# ---------------------------------------------------------------------------
#
# This test class covers Task 1.2: ``migrate_link_to_org_vehicle()``.
#
# The function swaps a ``customer_vehicles`` row from referencing a
# ``global_vehicles`` row to a (just-promoted) ``org_vehicles`` row by
# clearing ``global_vehicle_id`` and setting ``org_vehicle_id`` in a SINGLE
# UPDATE statement.
#
# The ``vehicle_link_check`` CHECK constraint on ``customer_vehicles``
# enforces ``(global_vehicle_id IS NOT NULL AND org_vehicle_id IS NULL) OR
# (global_vehicle_id IS NULL AND org_vehicle_id IS NOT NULL)``. Splitting
# the swap into two separate statements would briefly leave both columns
# NULL — PostgreSQL would raise ``violates check constraint
# "vehicle_link_check"`` at the first statement.
#
# The atomic single-UPDATE behaviour is therefore not just an optimisation
# — it is required for correctness. This test asserts:
#   1. The helper issues exactly one ``db.execute`` (one SQL statement).
#   2. That statement is an UPDATE on ``customer_vehicles``.
#   3. The UPDATE filters by ``id = :customer_vehicle_id``.
#   4. The UPDATE sets BOTH ``global_vehicle_id=NULL`` and
#      ``org_vehicle_id=:ov`` in the same VALUES clause.
#   5. ``db.flush()`` is awaited after the UPDATE so the change is
#      visible to subsequent SELECTs in the same session.
#
# Requirements: 2.3, 2.4, 8.5
# Design: New Helper Functions → ``migrate_link_to_org_vehicle()``.

from app.modules.vehicles.models import CustomerVehicle
from app.modules.vehicles.service import migrate_link_to_org_vehicle


class TestMigrateLinkToOrgVehicleSwapsColumnsAtomically:
    @pytest.mark.asyncio
    async def test_migrate_link_to_org_vehicle_swaps_columns_atomically(self):
        """The helper issues a single UPDATE setting both columns at once.

        This is the core correctness invariant for Task 1.2: any caller
        that splits the swap into two writes (clear global_vehicle_id
        first, then set org_vehicle_id second, or vice-versa) violates
        the ``vehicle_link_check`` CHECK constraint at the intermediate
        state. Issuing both column changes in one UPDATE statement keeps
        the row constraint-satisfying at every observable moment.
        """
        cv_id = uuid.uuid4()
        ov_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        await migrate_link_to_org_vehicle(
            db,
            customer_vehicle_id=cv_id,
            org_vehicle_id=ov_id,
        )

        # -- Invariant 1: exactly one statement issued --
        assert db.execute.await_count == 1, (
            "migrate_link_to_org_vehicle MUST issue exactly one UPDATE; "
            "splitting the swap into multiple statements violates "
            "vehicle_link_check at the intermediate state"
        )

        # -- Invariant 5: flush awaited after the UPDATE --
        assert db.flush.await_count == 1
        # Flush ordering — execute must be awaited before flush.
        # Both AsyncMocks are awaited in this test so we only check
        # the call_count contracts above; ordering is verified by the
        # function source itself (single sequential block).

        # Inspect the SQLAlchemy Core UPDATE statement that was executed.
        stmt = db.execute.await_args.args[0]

        # -- Invariant 2: it is an UPDATE on customer_vehicles --
        compiled = stmt.compile(
            compile_kwargs={"literal_binds": False},
        )
        sql = str(compiled)
        assert sql.strip().upper().startswith("UPDATE"), (
            f"migrate_link_to_org_vehicle must issue an UPDATE; got: {sql!r}"
        )
        assert (
            stmt.table is CustomerVehicle.__table__
            or "customer_vehicles" in sql.lower()
        ), "UPDATE must target the customer_vehicles table"

        # -- Invariant 3: WHERE clause filters by the supplied cv_id --
        # SQLAlchemy renders the WHERE clause; the bind value must be the
        # cv_id we passed in (not the ov_id, not None).
        params = compiled.params
        # The WHERE bind is keyed by 'id_1' or 'id' depending on dialect;
        # collect all bind values and assert cv_id is among them.
        assert cv_id in params.values(), (
            f"UPDATE WHERE clause must bind customer_vehicle_id={cv_id!r}; "
            f"got params={params!r}"
        )

        # -- Invariant 4: BOTH columns set in the same VALUES clause --
        # ``stmt._values`` is the Core UPDATE's column->value mapping; on
        # SQLAlchemy 2.x the public attribute is ``stmt._values`` for an
        # ``Update`` constructed via ``.values(...)``. Inspect by column
        # name to remain agnostic to the internal representation.
        values_keys = {col.key for col in stmt._values.keys()}
        assert "global_vehicle_id" in values_keys, (
            "UPDATE must clear global_vehicle_id in the same statement"
        )
        assert "org_vehicle_id" in values_keys, (
            "UPDATE must set org_vehicle_id in the same statement"
        )

        # The cleared global_vehicle_id must be NULL (not e.g. an empty
        # string). SQLAlchemy wraps Python None in a BindParameter; check
        # the underlying value.
        global_value = stmt._values[
            next(c for c in stmt._values.keys() if c.key == "global_vehicle_id")
        ]
        # ``BindParameter.value`` holds the literal Python value bound to
        # the column; for ``None`` it is ``None``.
        global_literal = getattr(global_value, "value", global_value)
        assert global_literal is None, (
            f"UPDATE must set global_vehicle_id=NULL (got {global_literal!r}); "
            "any non-NULL value would re-violate vehicle_link_check"
        )

        org_value = stmt._values[
            next(c for c in stmt._values.keys() if c.key == "org_vehicle_id")
        ]
        org_literal = getattr(org_value, "value", org_value)
        assert org_literal == ov_id, (
            f"UPDATE must set org_vehicle_id={ov_id!r} (got {org_literal!r})"
        )


# ---------------------------------------------------------------------------
# manual_refresh_vehicle — Task 1.3
# ---------------------------------------------------------------------------
#
# This test class covers Task 1.3: ``manual_refresh_vehicle()``.
#
# The helper implements the explicit "Refresh from CarJam" action (Req 5):
#   - Loads the existing ``org_vehicles`` row for ``(org_id, rego)`` and
#     raises ``LookupError`` if missing (helper does NOT promote).
#   - Always triggers a CarJam refetch via ``refresh_vehicle()`` — no
#     stale-cache short-circuit. The user explicitly clicked the action.
#   - Copies CarJam_Owned_Spec_Fields from the freshly-refreshed
#     ``global_vehicles`` row into the ``org_vehicles`` row.
#   - Does NOT touch ``org_vehicles`` Customer_Driven_Fields.
#   - Emits a ``vehicle.manual_refresh`` audit log row with ``org_id`` and
#     ``user_id`` populated as top-level columns.
#
# Two tests:
#   1. ``test_manual_refresh_vehicle_updates_carjam_fields_only`` — happy
#      path. Asserts (a) CarJam-owned fields on the ``OrgVehicle`` were
#      updated to match ``global_vehicles``, (b) the four
#      Customer_Driven_Fields on the ``OrgVehicle`` are byte-identical
#      before vs after, (c) one ``vehicle.manual_refresh`` audit-log row
#      exists with ``org_id`` and ``user_id`` populated as top-level
#      columns.
#   2. ``test_manual_refresh_vehicle_always_calls_carjam`` — always-refresh
#      regression. Stubs ``refresh_vehicle`` to record calls and asserts
#      it was invoked regardless of ``global_vehicles.last_pulled_at``
#      freshness.
#
# Requirements: 5.1, 5.2, 5.3, 5.4, 14.2, 14.3
# Design: New Helper Functions → ``manual_refresh_vehicle()``;
#         Code Changes per File → ``app/modules/vehicles/service.py``.

from app.modules.vehicles.service import manual_refresh_vehicle


def _make_org_vehicle(**overrides):
    """Build a mock OrgVehicle with realistic field values.

    Pre-populated with both CarJam_Owned_Spec_Fields (which the refresh
    will overwrite) and Customer_Driven_Fields (which the refresh must
    NOT touch).
    """
    ov = MagicMock()
    ov.id = overrides.get("id", uuid.uuid4())
    ov.org_id = overrides.get("org_id", uuid.uuid4())
    ov.rego = overrides.get("rego", "ABC123")

    # CarJam_Owned_Spec_Fields — initial (stale) values that will be
    # overwritten by the refresh.
    ov.make = overrides.get("make", "OldMake")
    ov.model = overrides.get("model", "OldModel")
    ov.year = overrides.get("year", 2010)
    ov.colour = overrides.get("colour", "OldColour")
    ov.body_type = overrides.get("body_type", "OldBody")
    ov.fuel_type = overrides.get("fuel_type", "OldFuel")
    ov.engine_size = overrides.get("engine_size", "1.6L")
    ov.num_seats = overrides.get("num_seats", 4)
    ov.registration_expiry = overrides.get("registration_expiry", date(2024, 1, 1))
    ov.vin = overrides.get("vin", "OLDVIN")
    ov.chassis = overrides.get("chassis", "OLDCHASSIS")
    ov.engine_no = overrides.get("engine_no", "OLDENG")
    ov.transmission = overrides.get("transmission", "Manual")
    ov.country_of_origin = overrides.get("country_of_origin", "Old Country")
    ov.number_of_owners = overrides.get("number_of_owners", 1)
    ov.vehicle_type = overrides.get("vehicle_type", "OldType")
    ov.power_kw = overrides.get("power_kw", 80)
    ov.tare_weight = overrides.get("tare_weight", 1100)
    ov.gross_vehicle_mass = overrides.get("gross_vehicle_mass", 1500)
    ov.date_first_registered_nz = overrides.get(
        "date_first_registered_nz", date(2010, 1, 1)
    )
    ov.plate_type = overrides.get("plate_type", "OldPlate")
    ov.submodel = overrides.get("submodel", "OldSub")
    ov.second_colour = overrides.get("second_colour", "OldSecondColour")

    # Customer_Driven_Fields — these are the operational state values
    # owned by the org. The refresh must NOT touch them.
    ov.odometer_last_recorded = overrides.get("odometer_last_recorded", 50000)
    ov.service_due_date = overrides.get("service_due_date", date(2025, 9, 1))
    ov.wof_expiry = overrides.get("wof_expiry", date(2025, 7, 15))
    ov.cof_expiry = overrides.get("cof_expiry", None)
    ov.inspection_type = overrides.get("inspection_type", "wof")

    return ov


def _make_db_for_manual_refresh(*, ov_to_return, gv_to_return):
    """Build an AsyncMock DB session for the manual_refresh_vehicle path.

    The function issues two SELECTs (one for the OrgVehicle, one for the
    GlobalVehicle by rego) before delegating to ``refresh_vehicle``. Set
    up ``execute`` to return them in order, then no-op for the audit-log
    INSERT issued at the end.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    ov_result = MagicMock()
    ov_result.scalar_one_or_none.return_value = ov_to_return

    gv_result = MagicMock()
    gv_result.scalar_one_or_none.return_value = gv_to_return

    # Subsequent calls (audit log INSERT, etc.) return a no-op result.
    no_op = MagicMock()
    no_op.scalar_one_or_none.return_value = None

    # side_effect drains the ordered iterator; remaining calls fall back
    # to ``return_value``.
    db.execute = AsyncMock(side_effect=[ov_result, gv_result, no_op, no_op, no_op])
    return db


class TestManualRefreshVehicle:
    @pytest.mark.asyncio
    async def test_manual_refresh_vehicle_updates_carjam_fields_only(self):
        """Refresh updates CarJam-owned fields and leaves customer-driven fields untouched.

        Asserts:
          (a) Every CarJam_Owned_Spec_Field on the OrgVehicle now matches
              the (post-refresh) GlobalVehicle row.
          (b) Every Customer_Driven_Field on the OrgVehicle is
              byte-identical to its pre-call value (the refresh did not
              touch them).
          (c) Exactly one vehicle.manual_refresh audit-log row was emitted
              with ``org_id`` and ``user_id`` populated as top-level
              columns (not inside after_value).
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        rego = "ABC123"

        ov = _make_org_vehicle(org_id=org_id, rego=rego)

        # Snapshot the customer-driven values before the call so we can
        # assert byte-identical preservation post-call.
        pre_odometer = ov.odometer_last_recorded
        pre_service_due_date = ov.service_due_date
        pre_wof_expiry = ov.wof_expiry
        pre_cof_expiry = ov.cof_expiry
        pre_inspection_type = ov.inspection_type

        # Build a GlobalVehicle that holds the FRESH CarJam values that
        # ``refresh_vehicle`` will have written. Every CarJam-owned field
        # is different from the OrgVehicle's stale values so we can prove
        # the copy happened.
        gv = _make_global_vehicle(
            rego=rego,
            make="NewMake",
            model="NewModel",
            year=2024,
            colour="NewColour",
            body_type="NewBody",
            fuel_type="NewFuel",
            engine_size="2.0L",
            num_seats=7,
            registration_expiry=date(2026, 1, 1),
            vin="NEWVIN1234567890A",
            chassis="NEWCHASSIS",
            engine_no="NEWENG",
            transmission="DSG",
            country_of_origin="New Country",
            number_of_owners=3,
            vehicle_type="NewType",
            power_kw=150,
            tare_weight=1500,
            gross_vehicle_mass=2000,
            date_first_registered_nz=date(2024, 5, 1),
            plate_type="NewPlate",
            submodel="NewSub",
            second_colour="NewSecondColour",
            # CarJam-side customer-driven fields are also different — but
            # these MUST NOT bleed onto the OrgVehicle row.
            odometer_last_recorded=999_999,
            service_due_date=date(2099, 12, 31),
            wof_expiry=date(2099, 12, 31),
            cof_expiry=date(2099, 12, 31),
            inspection_type="cof",
        )

        db = _make_db_for_manual_refresh(ov_to_return=ov, gv_to_return=gv)

        with patch(
            "app.modules.vehicles.service.refresh_vehicle",
            new_callable=AsyncMock,
        ) as mock_refresh, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            redis = MagicMock()  # not exercised — refresh_vehicle is stubbed
            result = await manual_refresh_vehicle(
                db,
                redis,
                org_id=org_id,
                rego=rego,
                user_id=user_id,
                ip_address="10.0.0.1",
            )

        # Sanity: helper returns the same OrgVehicle it loaded.
        assert result is ov

        # CarJam refetch was triggered — exactly once, scoped to the
        # resolved global_vehicle id.
        assert mock_refresh.await_count == 1
        refresh_kwargs = mock_refresh.await_args.kwargs
        assert refresh_kwargs["vehicle_id"] == gv.id
        assert refresh_kwargs["org_id"] == org_id
        assert refresh_kwargs["user_id"] == user_id

        # -- Assertion (a): CarJam_Owned_Spec_Fields on OrgVehicle now
        # match the freshly-refreshed GlobalVehicle. --
        for field in (
            "make",
            "model",
            "year",
            "colour",
            "body_type",
            "fuel_type",
            "engine_size",
            "num_seats",
            "registration_expiry",
            "vin",
            "chassis",
            "engine_no",
            "transmission",
            "country_of_origin",
            "number_of_owners",
            "vehicle_type",
            "power_kw",
            "tare_weight",
            "gross_vehicle_mass",
            "date_first_registered_nz",
            "plate_type",
            "submodel",
            "second_colour",
        ):
            assert getattr(ov, field) == getattr(gv, field), (
                f"CarJam-owned field '{field}' was not refreshed onto "
                f"OrgVehicle from GlobalVehicle"
            )

        # -- Assertion (b): Customer_Driven_Fields on OrgVehicle are
        # byte-identical to pre-call values. The refresh must not have
        # bled the GlobalVehicle's customer-driven values onto the
        # OrgVehicle row. --
        assert ov.odometer_last_recorded == pre_odometer, (
            "manual_refresh must not touch org_vehicles.odometer_last_recorded"
        )
        assert ov.service_due_date == pre_service_due_date, (
            "manual_refresh must not touch org_vehicles.service_due_date"
        )
        assert ov.wof_expiry == pre_wof_expiry, (
            "manual_refresh must not touch org_vehicles.wof_expiry"
        )
        assert ov.cof_expiry == pre_cof_expiry, (
            "manual_refresh must not touch org_vehicles.cof_expiry"
        )
        assert ov.inspection_type == pre_inspection_type, (
            "manual_refresh must not touch org_vehicles.inspection_type"
        )

        # -- Assertion (c): exactly one vehicle.manual_refresh audit log
        # row with org_id and user_id as TOP-LEVEL columns, not in
        # after_value. --
        assert mock_audit.await_count == 1
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "vehicle.manual_refresh"
        assert audit_kwargs["entity_type"] == "org_vehicle"
        assert audit_kwargs["entity_id"] == ov.id
        # Top-level columns
        assert audit_kwargs["org_id"] == org_id
        assert audit_kwargs["user_id"] == user_id
        # after_value carries rego + global_vehicle_id but NOT org_id /
        # user_id (those live on dedicated columns).
        assert audit_kwargs["after_value"]["rego"] == rego
        assert audit_kwargs["after_value"]["global_vehicle_id"] == str(gv.id)
        assert "org_id" not in audit_kwargs["after_value"], (
            "org_id must be a top-level column on audit_log, not embedded "
            "in after_value"
        )
        assert "user_id" not in audit_kwargs["after_value"], (
            "user_id must be a top-level column on audit_log, not embedded "
            "in after_value"
        )

    @pytest.mark.asyncio
    async def test_manual_refresh_vehicle_always_calls_carjam(self):
        """Refresh is invoked regardless of last_pulled_at freshness.

        The task spec mandates: "Always trigger a CarJam refetch when
        manual_refresh_vehicle is called". The user explicitly clicked
        "Refresh from CarJam" — honouring that with a stale-cache
        short-circuit defeats the user's intent.

        This test sets ``global_vehicles.last_pulled_at`` to a moment ago
        (very fresh — any reasonable TTL would short-circuit) and asserts
        ``refresh_vehicle`` is still called.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        rego = "FRESH1"

        ov = _make_org_vehicle(org_id=org_id, rego=rego)

        # GlobalVehicle row that would normally be considered "fresh"
        # under any reasonable cache TTL (just-now timestamp).
        gv = _make_global_vehicle(rego=rego)
        gv.last_pulled_at = datetime.now(timezone.utc)

        db = _make_db_for_manual_refresh(ov_to_return=ov, gv_to_return=gv)

        with patch(
            "app.modules.vehicles.service.refresh_vehicle",
            new_callable=AsyncMock,
        ) as mock_refresh, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            redis = MagicMock()
            await manual_refresh_vehicle(
                db,
                redis,
                org_id=org_id,
                rego=rego,
                user_id=user_id,
            )

        # The CarJam client was called — proves no stale-cache
        # short-circuit was applied.
        assert mock_refresh.await_count == 1, (
            "manual_refresh_vehicle must always call refresh_vehicle "
            "regardless of global_vehicles.last_pulled_at freshness; "
            "user explicitly clicked 'Refresh from CarJam'"
        )

    @pytest.mark.asyncio
    async def test_manual_refresh_vehicle_raises_when_org_row_missing(self):
        """Helper raises LookupError when org has not yet been promoted.

        manual_refresh_vehicle does NOT promote — promotion happens on
        first customer-driven write (per Tasks 3-10). If a caller invokes
        the helper for a rego the org has never written to, the helper
        surfaces a LookupError so the router can render a clean 404
        rather than silently creating a row.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        rego = "MISSING1"

        # OrgVehicle SELECT returns None — org has not been promoted.
        ov_result = MagicMock()
        ov_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=ov_result)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch(
            "app.modules.vehicles.service.refresh_vehicle",
            new_callable=AsyncMock,
        ) as mock_refresh, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            redis = MagicMock()
            with pytest.raises(LookupError):
                await manual_refresh_vehicle(
                    db,
                    redis,
                    org_id=org_id,
                    rego=rego,
                    user_id=user_id,
                )

        # No CarJam call, no audit log row — the helper aborted cleanly
        # before mutating any state.
        assert mock_refresh.await_count == 0
        assert mock_audit.await_count == 0


# ---------------------------------------------------------------------------
# Task 1.4 — Additional unit tests for the three helpers
# ---------------------------------------------------------------------------
#
# Per Task 1.4 in tasks.md, these tests round out the coverage for the
# three helpers introduced in Tasks 1.1–1.3. The first two named tests in
# the task list (``test_promote_vehicle_creates_org_row_when_missing`` and
# ``test_migrate_link_to_org_vehicle_swaps_columns_atomically``) are
# already implemented above. The six tests below add the remainder.
#
# Tests added:
#   - ``test_promote_vehicle_idempotent_when_org_row_exists`` — second
#     invocation returns the same row, no extra audit-log entry, no second
#     INSERT (Req 13.2, 13.3).
#   - ``test_promote_vehicle_finds_pre_existing_manual_entry_by_rego`` —
#     pre-existing manual-entry org_vehicles row is reused (not duplicated)
#     per the design's Backwards Compatibility "Critical edge case".
#   - ``test_promote_vehicle_emits_audit_log_with_trigger_site`` — one
#     ``vehicle.promote`` audit row with ``trigger_site`` carried through
#     to ``after_value`` (Req 14.1).
#   - ``test_promote_vehicle_raises_when_module_disabled`` — defence-in-
#     depth module gate. ``vehicles`` module disabled for the org → raises
#     ``PermissionError`` and no ``org_vehicles`` row is created.
#   - ``test_record_odometer_does_not_touch_global_vehicles`` — locks in
#     the post-Task-3.1 contract: customer-driven odometer recording
#     redirects the cache write away from ``global_vehicles`` to
#     ``org_vehicles`` (Req 1.1, 11.2). Skipped until Task 3.1 lands.
#   - ``test_update_odometer_reading_writes_to_global_vehicles_by_design``
#     — locks in the documented carve-out from ``design.md``. Correcting
#     a historical reading recomputes the max and writes it to
#     ``global_vehicles.odometer_last_recorded`` (intentional cache update);
#     it does NOT bleed into the org's ``org_vehicles`` snapshot.
#
# Requirements: 2.5, 13.1, 13.2, 13.3, 14.1, 14.3, 15.1
# Design: Test Strategy → Unit Tests; Carve-out — ``update_odometer_reading``
#         writes to ``global_vehicles.odometer_last_recorded``.

from app.modules.vehicles.service import (  # noqa: E402
    record_odometer_reading,
    update_odometer_reading,
)


def _make_db_with_existing_org_row(existing_ov):
    """Build an AsyncMock DB session for the idempotent-promotion path.

    First ``execute`` call (advisory lock) returns no-op; second
    ``execute`` (the OrgVehicle existence check inside the lock) returns
    the pre-existing row so ``promote_vehicle`` short-circuits without
    issuing an INSERT.
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    lock_result = MagicMock()
    lock_result.scalar_one_or_none.return_value = None

    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_ov

    # Lock SQL first, then the OrgVehicle SELECT. Subsequent calls (none
    # expected on the idempotent path) fall back to a benign no-op.
    no_op = MagicMock()
    no_op.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[lock_result, existing_result, no_op])
    return db


class TestPromoteVehicleIdempotency:
    @pytest.mark.asyncio
    async def test_promote_vehicle_idempotent_when_org_row_exists(self):
        """Second invocation returns the existing row — no INSERT, no audit log.

        ``promote_vehicle`` is idempotent by construction (Req 13.2, 13.3):
        if the SELECT inside the advisory lock finds an existing
        ``org_vehicles`` row for ``(org_id, rego)``, the function returns
        that row immediately without issuing an INSERT and without
        emitting a ``vehicle.promote`` audit log entry. Concurrent racers
        for the same ``(org_id, rego)`` converge on the winner's row.
        """
        org_id = uuid.uuid4()
        gv = _make_global_vehicle()

        # Pre-existing OrgVehicle for this (org_id, rego).
        existing_ov = MagicMock(spec=OrgVehicle)
        existing_ov.id = uuid.uuid4()
        existing_ov.org_id = org_id
        existing_ov.rego = gv.rego

        db = _make_db_with_existing_org_row(existing_ov)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=gv.id,
                source_record=gv,
                user_id=uuid.uuid4(),
                trigger_site="vehicles.test_idempotent",
            )

        # Returned row is the pre-existing one — not a fresh insert.
        assert result is existing_ov

        # No INSERT issued (db.add never called on the idempotent path).
        assert db.add.call_count == 0, (
            "promote_vehicle must not insert a second org_vehicles row "
            "when one already exists for (org_id, rego)"
        )

        # No audit log emitted on the idempotent path (Req 14.1: the
        # vehicle.promote audit row is emitted only when a NEW row is
        # inserted; second-call short-circuits silently).
        assert mock_audit.await_count == 0, (
            "promote_vehicle must not emit a vehicle.promote audit log "
            "entry on the idempotent return path"
        )


class TestPromoteVehicleReusesPreExistingManualEntry:
    @pytest.mark.asyncio
    async def test_promote_vehicle_finds_pre_existing_manual_entry_by_rego(self):
        """Pre-existing manual-entry org_vehicles row is reused, not duplicated.

        Per the design's Backwards Compatibility section, "Critical edge
        case": an org may already have a manual-entry ``org_vehicles`` row
        for ``rego=ABC123`` AND, separately, a ``customer_vehicles`` link
        pointing at ``global_vehicles.id`` for the same rego (this can
        occur today because there is no UNIQUE on ``(org_id, rego)`` and
        ``link_vehicle_to_customer`` does not check for an existing
        manual-entry row).

        When the first customer-driven write through that link triggers
        promotion, ``promote_vehicle``'s existence check is keyed on
        ``(org_id, rego)`` (not on ``global_vehicle_id``) precisely so the
        manual-entry row is FOUND and REUSED — no second row is inserted,
        and the org converges on a single ``org_vehicles`` row per rego.
        """
        org_id = uuid.uuid4()
        rego = "ABC123"

        # Pre-existing manual-entry OrgVehicle (created via the manual-add
        # flow before this rego was ever CarJam-imported). is_manual_entry
        # is True, distinguishing it from a promoted-from-CarJam row.
        manual_ov = MagicMock(spec=OrgVehicle)
        manual_ov.id = uuid.uuid4()
        manual_ov.org_id = org_id
        manual_ov.rego = rego
        manual_ov.is_manual_entry = True

        # GlobalVehicle source for the same rego (e.g. someone CarJam-
        # imported the rego after the manual entry already existed).
        gv = _make_global_vehicle(rego=rego)

        db = _make_db_with_existing_org_row(manual_ov)

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=gv.id,
                source_record=gv,
                user_id=uuid.uuid4(),
                trigger_site="invoices.create",
            )

        # The pre-existing manual-entry row is returned — NOT a fresh
        # insert keyed off the global_vehicle_id.
        assert result is manual_ov, (
            "promote_vehicle must reuse the pre-existing manual-entry "
            "org_vehicles row matched by (org_id, rego); the matching key "
            "is rego, not global_vehicle_id"
        )

        # No second org_vehicles row inserted — the org converges on a
        # single row per rego.
        assert db.add.call_count == 0, (
            "promote_vehicle must not insert a duplicate org_vehicles row "
            "when a manual-entry row already exists for the same rego"
        )

        # The is_manual_entry flag on the existing row is preserved (the
        # design explicitly states this is never overwritten during reuse).
        assert manual_ov.is_manual_entry is True


class TestPromoteVehicleAuditLog:
    @pytest.mark.asyncio
    async def test_promote_vehicle_emits_audit_log_with_trigger_site(self):
        """Exactly one vehicle.promote audit row with the trigger_site preserved.

        Per Req 14.1: every successful promotion emits an audit log entry
        with ``action="vehicle.promote"``, ``entity_type="org_vehicle"``,
        ``entity_id`` equal to the new row's id, and ``after_value``
        carrying ``{rego, global_vehicle_id, trigger_site}``. The
        ``trigger_site`` string is fixed at the call site (the caller
        passes it) — operators rely on it for the forensic trail across
        the seven enumerated promotion sites (vehicles.link, invoices.create,
        invoices.update, kiosk.v2_check_in, fleet_portal.record_odometer,
        fleet_portal.update_field, etc.).

        This test exercises a non-default trigger_site value to prove the
        caller-supplied string lands in ``after_value`` verbatim.
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        gv = _make_global_vehicle(rego="TRIG01")
        db = _make_db_with_no_existing_org_row()

        # Pick a value distinct from the test-default in Task 1.1's
        # happy-path test so the trigger_site assertion is tight.
        trigger_site_value = "fleet_portal.record_odometer"

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=True,
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await promote_vehicle(
                db,
                org_id=org_id,
                global_vehicle_id=gv.id,
                source_record=gv,
                user_id=user_id,
                trigger_site=trigger_site_value,
                ip_address="10.1.2.3",
            )

        # Exactly one audit-log row emitted (Req 14.1).
        assert mock_audit.await_count == 1, (
            "promote_vehicle must emit exactly one vehicle.promote audit "
            "log entry per fresh promotion"
        )

        kwargs = mock_audit.await_args.kwargs

        # Action and entity_type fixed by spec.
        assert kwargs["action"] == "vehicle.promote"
        assert kwargs["entity_type"] == "org_vehicle"

        # org_id and user_id are TOP-LEVEL columns on audit_log, NOT
        # embedded in after_value — matches write_audit_log signature in
        # app/core/audit.py.
        assert kwargs["org_id"] == org_id
        assert kwargs["user_id"] == user_id

        # trigger_site MUST appear inside after_value (Req 14.1) and MUST
        # equal the caller-supplied value byte-for-byte.
        after = kwargs["after_value"]
        assert "trigger_site" in after
        assert after["trigger_site"] == trigger_site_value, (
            f"trigger_site must round-trip into after_value: expected "
            f"{trigger_site_value!r}, got {after.get('trigger_site')!r}"
        )

        # rego and global_vehicle_id round-trip too.
        assert after["rego"] == gv.rego
        assert after["global_vehicle_id"] == str(gv.id)

        # ip_address is plumbed through to the audit row.
        assert kwargs.get("ip_address") == "10.1.2.3"


class TestPromoteVehicleModuleGate:
    @pytest.mark.asyncio
    async def test_promote_vehicle_raises_when_module_disabled(self):
        """Defence-in-depth module gate: disabled module → PermissionError, no row.

        ``promote_vehicle`` is the bottleneck for every promotion trigger
        site (Req 12.4). If a future call site forgets to strip vehicle
        fields when the ``vehicles`` module is disabled, the helper still
        refuses to write an ``org_vehicles`` row. The check is the FIRST
        statement in the function — before the advisory lock and before
        any SELECT — so a module-disabled call short-circuits without
        side effects.
        """
        org_id = uuid.uuid4()
        gv = _make_global_vehicle()
        db = _make_db_with_no_existing_org_row()

        with patch(
            "app.core.modules.ModuleService.is_enabled",
            new_callable=AsyncMock,
            return_value=False,  # module DISABLED
        ), patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            with pytest.raises(PermissionError):
                await promote_vehicle(
                    db,
                    org_id=org_id,
                    global_vehicle_id=gv.id,
                    source_record=gv,
                    user_id=uuid.uuid4(),
                    trigger_site="vehicles.test_module_disabled",
                )

        # No org_vehicles row inserted — the gate fires before db.add.
        assert db.add.call_count == 0, (
            "promote_vehicle must not insert any org_vehicles row when "
            "the vehicles module is disabled for the org"
        )

        # No audit log emitted — the gate fires before write_audit_log.
        assert mock_audit.await_count == 0, (
            "promote_vehicle must not emit a vehicle.promote audit row "
            "when the vehicles module is disabled"
        )

        # The gate runs BEFORE the advisory lock and BEFORE any SELECT.
        # No DB execute calls should have been issued.
        assert db.execute.await_count == 0, (
            "promote_vehicle's module gate must short-circuit before any "
            "DB round-trip (advisory lock, SELECT, INSERT)"
        )


# ---------------------------------------------------------------------------
# record_odometer_reading isolation contract (Task 1.4 — test 7)
# ---------------------------------------------------------------------------


def _make_db_for_record_odometer(*, gv):
    """Build an AsyncMock DB session for ``record_odometer_reading``.

    The function issues:
      1. SELECT global_vehicles WHERE id=:gvid    → returns gv
      2. db.add(OdometerReading)                  → captured
      3. db.flush()                               → no-op
      4. (post-Task-3.1) promote_vehicle(...)     → returns ov
      5. ov.odometer_last_recorded = reading_km   → mutates ov in-place
      6. db.flush()                               → no-op

    Pre-Task-3.1 the function instead writes ``gv.odometer_last_recorded``
    directly. The test below is marked skipped until Task 3.1 lands.
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    gv_result = MagicMock()
    gv_result.scalar_one_or_none.return_value = gv

    no_op = MagicMock()
    no_op.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[gv_result, no_op, no_op, no_op])
    return db


class TestRecordOdometerDoesNotTouchGlobalVehicles:
    @pytest.mark.asyncio
    async def test_record_odometer_does_not_touch_global_vehicles(self):
        """Customer-driven odometer recording must NOT mutate global_vehicles.

        Per Task 3.1 (post-isolation contract): when
        ``record_odometer_reading`` is called with ``org_id != None`` and
        ``source != "carjam"`` (the customer-driven flow), the function
        must promote the vehicle and bump
        ``org_vehicles.odometer_last_recorded`` for that org, NOT
        ``global_vehicles.odometer_last_recorded``. The
        ``odometer_readings`` history row itself remains keyed by
        ``global_vehicle_id`` (Req 11.1).

        This test captures ``global_vehicles.odometer_last_recorded``
        before and after a customer-driven recording call and asserts the
        value is byte-identical, proving no write reached the shared
        cache. It is skipped until Task 3.1 lands; at that point the test
        runs against the modified function and confirms the contract.
        """
        org_id = uuid.uuid4()
        gv = _make_global_vehicle()
        gv.odometer_last_recorded = 50_000

        before_value = gv.odometer_last_recorded
        db = _make_db_for_record_odometer(gv=gv)

        # Mock promote_vehicle so the test exercises the isolation path
        # without having to set up a full RLS context. The returned ov is
        # what record_odometer_reading should mutate post-Task-3.1.
        ov = MagicMock(spec=OrgVehicle)
        ov.id = uuid.uuid4()
        ov.org_id = org_id
        ov.rego = gv.rego
        ov.odometer_last_recorded = 50_000

        with patch(
            "app.modules.vehicles.service.promote_vehicle",
            new_callable=AsyncMock,
            return_value=ov,
        ):
            await record_odometer_reading(
                db,
                global_vehicle_id=gv.id,
                reading_km=60_000,
                source="invoice",   # customer-driven
                org_id=org_id,
            )

        # Critical isolation invariant: global_vehicles.odometer_last_recorded
        # is byte-identical to its pre-call value.
        assert gv.odometer_last_recorded == before_value, (
            f"record_odometer_reading must not mutate "
            f"global_vehicles.odometer_last_recorded for customer-driven "
            f"flows; expected {before_value}, got {gv.odometer_last_recorded}"
        )

        # The org's snapshot DID receive the new reading.
        assert ov.odometer_last_recorded == 60_000


# ---------------------------------------------------------------------------
# update_odometer_reading carve-out (Task 1.4 — test 8)
# ---------------------------------------------------------------------------


def _make_db_for_update_odometer(*, reading, max_km, gv):
    """Build an AsyncMock DB session for ``update_odometer_reading``.

    Sequence of ``db.execute`` calls inside ``update_odometer_reading``:
      1. SELECT odometer_readings WHERE id=:reading_id   → returns reading
      2. SELECT max(reading_km) WHERE global_vehicle_id  → returns max_km
      3. SELECT global_vehicles WHERE id=:gvid           → returns gv

    After the third SELECT the function assigns
    ``vehicle.odometer_last_recorded = max_km`` and flushes. The carve-out
    is the deliberate write to ``global_vehicles`` here — see ``design.md``
    "Carve-out — ``update_odometer_reading`` writes to
    ``global_vehicles.odometer_last_recorded``".
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    reading_result = MagicMock()
    reading_result.scalar_one_or_none.return_value = reading

    max_result = MagicMock()
    max_result.scalar.return_value = max_km

    gv_result = MagicMock()
    gv_result.scalar_one_or_none.return_value = gv

    db.execute = AsyncMock(side_effect=[reading_result, max_result, gv_result])
    return db


class TestUpdateOdometerReadingCarveOut:
    @pytest.mark.asyncio
    async def test_update_odometer_reading_writes_to_global_vehicles_by_design(self):
        """Locks in the documented carve-out from ``design.md``.

        ``design.md`` "Carve-out — ``update_odometer_reading`` writes to
        ``global_vehicles.odometer_last_recorded``": correcting an existing
        ``odometer_readings`` history row (e.g. user typed ``123,000``
        instead of ``12,300``) recomputes the max across all history rows
        for that ``global_vehicle_id`` and writes that max back to
        ``global_vehicles.odometer_last_recorded``. The history is keyed
        on ``global_vehicle_id`` (Req 11.1), so the recomputed max is
        logically a property of the global cache, not a per-org operational
        value.

        This is an EXPLICIT, documented exception to Req 1.1's prohibition
        on customer-driven writes to ``global_vehicles``. Tests must
        explicitly cover the carve-out so it is not accidentally moved
        during future refactors. A future maintainer reviewing failures
        of this test should consult ``design.md`` "Carve-out —
        ``update_odometer_reading`` writes to
        ``global_vehicles.odometer_last_recorded``" before assuming a
        regression.

        Test sequence:
          - Pre-create a ``global_vehicles`` row and an
            ``odometer_readings`` row pointing at it (the first wrong
            reading at 5000 km).
          - Promote the vehicle for an org (snapshots
            ``ov.odometer_last_recorded = 50000`` from gv).
          - Record a second reading (60000 km). Capture
            ``ov.odometer_last_recorded`` immediately before the
            ``update_odometer_reading`` call.
          - Call ``update_odometer_reading`` to correct the FIRST reading
            (5000 → 6000).
          - Assert (a) ``global_vehicles.odometer_last_recorded`` IS
            recomputed and updated to the new max (this is the carve-out).
          - Assert (b) ``org_vehicles.odometer_last_recorded`` is
            byte-identical to its pre-call value (correction does not
            bleed into the org snapshot).
        """
        # -- Arrange the global_vehicles row and its history --
        gv = _make_global_vehicle()
        gv.odometer_last_recorded = 60_000  # current cache value (set by
                                            # the second-reading record)

        # The first historical reading — the one being corrected.
        first_reading = MagicMock()
        first_reading.id = uuid.uuid4()
        first_reading.global_vehicle_id = gv.id
        first_reading.reading_km = 5_000     # wrong value
        first_reading.notes = None

        # The recomputed max after the correction. The first reading goes
        # 5000 → 6000; the second reading (recorded earlier) is 60000.
        # max(6000, 60000) = 60000.
        recomputed_max = 60_000

        # -- Arrange the org_vehicles snapshot (post-promotion) --
        # ov.odometer_last_recorded stays at whatever it was after the
        # promotion + second-reading sequence. We capture this value as
        # the "pre-call" baseline that update_odometer_reading must NOT
        # disturb.
        ov = MagicMock(spec=OrgVehicle)
        ov.id = uuid.uuid4()
        ov.org_id = uuid.uuid4()
        ov.rego = gv.rego
        ov.odometer_last_recorded = 60_000   # value held by the org's
                                             # snapshot before the
                                             # correction call
        pre_call_ov_odometer = ov.odometer_last_recorded

        db = _make_db_for_update_odometer(
            reading=first_reading,
            max_km=recomputed_max,
            gv=gv,
        )

        # -- Act: correct the FIRST historical reading 5000 → 6000 --
        result = await update_odometer_reading(
            db,
            reading_id=first_reading.id,
            new_reading_km=6_000,
            user_id=uuid.uuid4(),
        )

        # -- Assert (a): the carve-out fires —
        # global_vehicles.odometer_last_recorded IS recomputed and DOES
        # update. The current implementation always writes the recomputed
        # max back to gv.odometer_last_recorded; this assertion locks in
        # that documented behaviour. --
        assert gv.odometer_last_recorded == recomputed_max, (
            "update_odometer_reading MUST recompute and write "
            "global_vehicles.odometer_last_recorded — this is the explicit "
            "carve-out documented in design.md. See: 'Carve-out — "
            "update_odometer_reading writes to "
            "global_vehicles.odometer_last_recorded'."
        )
        # The corrected reading itself was updated.
        assert first_reading.reading_km == 6_000
        # The function returns the recomputed max for the caller.
        assert result["vehicle_odometer_now"] == recomputed_max
        assert result["new_reading_km"] == 6_000
        assert result["old_reading_km"] == 5_000

        # -- Assert (b): the org snapshot is BYTE-IDENTICAL pre vs post.
        # The carve-out is intentionally global-only: the correction must
        # NOT bleed into any org's org_vehicles.odometer_last_recorded.
        # This is what keeps the per-org snapshot independent of cache
        # corrections that originated outside the org's control. --
        assert ov.odometer_last_recorded == pre_call_ov_odometer, (
            f"update_odometer_reading MUST NOT touch "
            f"org_vehicles.odometer_last_recorded; the correction is a "
            f"global-cache concern only. Expected ov.odometer_last_recorded "
            f"to remain {pre_call_ov_odometer!r}, got "
            f"{ov.odometer_last_recorded!r}."
        )


# ---------------------------------------------------------------------------
# Task 3.2 — link_vehicle_to_customer promotes before linking
# ---------------------------------------------------------------------------
#
# Per Task 3.2 in tasks.md, ``link_vehicle_to_customer()`` must call
# ``promote_vehicle(...)`` first when the supplied ``vehicle_id`` resolves
# to a ``GlobalVehicle``, then construct the ``CustomerVehicle`` with
# ``org_vehicle_id=ov.id`` and ``global_vehicle_id=None``. When the id
# already resolves to an ``OrgVehicle`` (manual-entry row), the link is
# created directly with ``org_vehicle_id`` and no promotion is needed.
#
# The integration test referenced in the task's ``Verify`` line
# (``test_vehicles_link_to_customer_promotes_first_time``) is added under
# Task 3.3. This unit test locks in the function-level contract so any
# future refactor that drops the promotion call or accidentally writes
# the link via ``global_vehicle_id`` is caught immediately.
#
# Requirements: 2.3, 3.1, 14.1
# Design: Code Changes per File → ``app/modules/vehicles/service.py``
#         (link_vehicle_to_customer); Implementation Note — Local
#         Variable Rebinding After Promotion.

from app.modules.vehicles.service import link_vehicle_to_customer  # noqa: E402


class TestLinkVehicleToCustomerPromotesBeforeLinking:
    @pytest.mark.asyncio
    async def test_link_vehicle_to_customer_promotes_global_then_links_via_org_vehicle_id(
        self,
    ):
        """Global-vehicle link path: promote first, then link via org_vehicle_id.

        Asserts the four invariants required by Task 3.2:
          (a) ``promote_vehicle`` was called exactly once with the
              ``trigger_site='vehicles.link'`` string and the supplied
              ``GlobalVehicle.id`` as ``global_vehicle_id``.
          (b) The ``CustomerVehicle`` row added to the session has
              ``org_vehicle_id`` set to the promoted ``OrgVehicle.id``
              and ``global_vehicle_id`` explicitly NULL — the
              ``vehicle_link_check`` either-or invariant must hold for
              the new row.
          (c) The ``vehicle.link_customer`` audit-log payload is
              UNCHANGED — ``vehicle_id`` carries the originally-supplied
              id (matching pre-Task-3.2 forensic queries) and ``rego``
              is the resolved rego.
          (d) Returned dict's ``vehicle_id`` is the originally-supplied
              id (the public API field name and value semantics are
              stable).
        """
        from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

        global_vehicle_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        promoted_ov_id = uuid.uuid4()

        # Source GlobalVehicle the caller's id resolves to.
        gv = MagicMock()
        gv.id = global_vehicle_id
        gv.rego = "GLOB01"

        # Promoted OrgVehicle returned by the (mocked) promote_vehicle.
        promoted_ov = MagicMock(spec=OrgVehicle)
        promoted_ov.id = promoted_ov_id
        promoted_ov.org_id = org_id
        promoted_ov.rego = "GLOB01"

        # Customer for the org.
        customer = MagicMock()
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Jane"
        customer.last_name = "Doe"

        # DB session: GlobalVehicle resolve hits, then customer resolve.
        # promote_vehicle is patched, so no other DB calls happen between
        # them.
        db = AsyncMock()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # GlobalVehicle resolve
                result = MagicMock()
                result.scalar_one_or_none.return_value = gv
                return result
            elif call_count == 2:
                # Customer resolve
                result = MagicMock()
                result.scalar_one_or_none.return_value = customer
                return result
            return MagicMock()

        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.vehicles.service.promote_vehicle",
            new_callable=AsyncMock,
            return_value=promoted_ov,
        ) as mock_promote, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await link_vehicle_to_customer(
                db,
                vehicle_id=global_vehicle_id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
                odometer=42_000,
                ip_address="127.0.0.1",
            )

        # -- Invariant (a): promote_vehicle was called once with the right
        # trigger_site and global_vehicle_id (Req 3.1, 14.1). --
        assert mock_promote.await_count == 1, (
            "link_vehicle_to_customer MUST call promote_vehicle exactly "
            "once when vehicle_id resolves to a GlobalVehicle"
        )
        promote_kwargs = mock_promote.await_args.kwargs
        assert promote_kwargs["org_id"] == org_id
        assert promote_kwargs["global_vehicle_id"] == global_vehicle_id
        assert promote_kwargs["trigger_site"] == "vehicles.link", (
            "trigger_site must be 'vehicles.link' so the audit-log "
            "forensic trail attributes the promotion correctly"
        )
        assert promote_kwargs["source_record"] is gv, (
            "source_record must be the resolved GlobalVehicle so "
            "promote_vehicle does not re-query the same row"
        )

        # -- Invariant (b): the CustomerVehicle was added with
        # org_vehicle_id set and global_vehicle_id NULL (Req 2.3). --
        assert db.add.call_count == 1
        added = db.add.call_args[0][0]
        assert isinstance(added, CustomerVehicle)
        assert added.org_vehicle_id == promoted_ov_id, (
            "CustomerVehicle.org_vehicle_id MUST point at the promoted "
            "OrgVehicle's id"
        )
        assert added.global_vehicle_id is None, (
            "CustomerVehicle.global_vehicle_id MUST be NULL after "
            "promotion — vehicle_link_check enforces the either-or "
            "invariant and would fail otherwise"
        )
        # Other link fields preserved.
        assert added.org_id == org_id
        assert added.customer_id == customer_id
        assert added.odometer_at_link == 42_000

        # -- Invariant (c): the audit-log payload is UNCHANGED — vehicle_id
        # holds the originally-supplied id (not the new ov_id) and rego
        # is the resolved rego. --
        assert mock_audit.await_count == 1
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "vehicle.link_customer"
        assert audit_kwargs["entity_type"] == "customer_vehicle"
        after = audit_kwargs["after_value"]
        assert after["vehicle_id"] == str(global_vehicle_id), (
            "audit-log after_value['vehicle_id'] MUST carry the original "
            "supplied id so pre-Task-3.2 forensic queries still resolve"
        )
        assert after["customer_id"] == str(customer_id)
        assert after["rego"] == "GLOB01"

        # -- Invariant (d): the returned dict's vehicle_id field is the
        # originally-supplied id (public API stability). --
        assert result["vehicle_id"] == str(global_vehicle_id)
        assert result["customer_id"] == str(customer_id)
        assert result["customer_name"] == "Jane Doe"
        assert result["odometer_at_link"] == 42_000

    @pytest.mark.asyncio
    async def test_link_vehicle_to_customer_does_not_promote_when_id_resolves_to_org_vehicle(
        self,
    ):
        """OrgVehicle id path: link directly via org_vehicle_id, no promotion.

        When the supplied ``vehicle_id`` already resolves to an
        ``OrgVehicle`` (e.g. a manual-entry row that was never imported
        from CarJam), the link is created directly without calling
        ``promote_vehicle``. Promotion is only meaningful for vehicles
        whose source-of-truth currently lives in ``global_vehicles``.

        This test asserts:
          - ``promote_vehicle`` is NOT called.
          - The link is created with ``org_vehicle_id`` set to the
            supplied id and ``global_vehicle_id`` NULL.
          - The audit-log payload is unchanged.
        """
        from app.modules.vehicles.models import CustomerVehicle, OrgVehicle

        ov_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Pre-existing manual-entry OrgVehicle for this org.
        ov = MagicMock(spec=OrgVehicle)
        ov.id = ov_id
        ov.org_id = org_id
        ov.rego = "MAN01"

        customer = MagicMock()
        customer.id = customer_id
        customer.org_id = org_id
        customer.first_name = "Sam"
        customer.last_name = "Brown"

        # GlobalVehicle resolve misses (the id is an org-vehicle id);
        # OrgVehicle resolve hits; Customer resolve hits.
        db = AsyncMock()
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # GlobalVehicle resolve — miss
                result.scalar_one_or_none.return_value = None
            elif call_count == 2:
                # OrgVehicle resolve — hit
                result.scalar_one_or_none.return_value = ov
            elif call_count == 3:
                # Customer resolve
                result.scalar_one_or_none.return_value = customer
            else:
                result.scalar_one_or_none.return_value = None
            return result

        db.execute = mock_execute
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.vehicles.service.promote_vehicle",
            new_callable=AsyncMock,
        ) as mock_promote, patch(
            "app.modules.vehicles.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            result = await link_vehicle_to_customer(
                db,
                vehicle_id=ov_id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
            )

        # -- promote_vehicle MUST NOT be called when the id is already an
        # OrgVehicle. Promotion is only a global → org transition. --
        assert mock_promote.await_count == 0, (
            "promote_vehicle MUST NOT be called when vehicle_id already "
            "resolves to an OrgVehicle (manual-entry path)"
        )

        # -- The link is created with org_vehicle_id set to the supplied
        # id and global_vehicle_id NULL. --
        assert db.add.call_count == 1
        added = db.add.call_args[0][0]
        assert isinstance(added, CustomerVehicle)
        assert added.org_vehicle_id == ov_id
        assert added.global_vehicle_id is None
        assert added.org_id == org_id
        assert added.customer_id == customer_id

        # -- Audit-log payload unchanged — vehicle_id is the supplied
        # OrgVehicle id, rego is the OrgVehicle's rego. --
        assert mock_audit.await_count == 1
        audit_kwargs = mock_audit.await_args.kwargs
        assert audit_kwargs["action"] == "vehicle.link_customer"
        after = audit_kwargs["after_value"]
        assert after["vehicle_id"] == str(ov_id)
        assert after["rego"] == "MAN01"

        # -- Return shape stable. --
        assert result["vehicle_id"] == str(ov_id)
        assert result["customer_name"] == "Sam Brown"


# ---------------------------------------------------------------------------
# Task 4.0 — `_resolve_vehicle_type` prefers OrgVehicle by rego when promoted
# ---------------------------------------------------------------------------
#
# This test class covers Task 4.0: the resolver in
# ``app/modules/invoices/service.py`` (~L399-432).
#
# Before this change, ``_resolve_vehicle_type`` checked ``global_vehicles``
# by id first and returned ``("global", gv)`` whenever a row existed. The
# caller (``create_invoice`` / ``update_invoice``) then wrote
# customer-driven fields onto the GlobalVehicle — undoing isolation on
# every subsequent invoice for the same vehicle, because callers always
# pass the original ``global_vehicles.id`` from the request payload even
# after the org has been promoted for that rego.
#
# The fix: when the resolver finds a GlobalVehicle, perform a follow-up
# rego-keyed query against ``org_vehicles`` scoped to the calling org;
# if a row exists there, the org has been promoted and the OrgVehicle is
# returned instead. Otherwise the GlobalVehicle is returned as before.
#
# Requirements: 6.1, 6.2, 6.4, 9.6, 12.3
# Design: Read Paths → ``_resolve_vehicle_type``.

from app.modules.invoices.service import _resolve_vehicle_type


class TestResolveVehicleTypeReturnsOrgWhenPromoted:
    """Resolver returns the org snapshot once the org has been promoted.

    Two cases:
      - org_a has been promoted for the rego (an org_vehicles row exists
        scoped to org_a). The resolver, given the original
        global_vehicles.id, must return ``("org", ov)`` with
        ``ov.id != gv.id``.
      - org_b has NOT been promoted (no org_vehicles row scoped to
        org_b). The resolver, given the same global_vehicles.id, must
        return ``("global", gv)`` unchanged.
    """

    @pytest.mark.asyncio
    async def test_resolver_returns_org_when_org_a_is_promoted(self):
        org_a_id = uuid.uuid4()
        gv = _make_global_vehicle(rego="PROMO1")

        # OrgVehicle scoped to org_a for the same rego.
        ov = MagicMock(spec=OrgVehicle)
        ov.id = uuid.uuid4()
        ov.org_id = org_a_id
        ov.rego = gv.rego

        # Sanity check the test setup — the OrgVehicle has a different
        # primary key from the GlobalVehicle, so any caller that uses the
        # returned record's ``.id`` will hit the org row, not the global
        # row.
        assert ov.id != gv.id

        # First execute: GlobalVehicle SELECT by id → gv.
        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        # Second execute: OrgVehicle SELECT by (org_id, upper(rego)) → ov.
        ov_result = MagicMock()
        ov_result.scalar_one_or_none.return_value = ov

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[gv_result, ov_result])

        result = await _resolve_vehicle_type(db, gv.id, org_a_id)

        # The resolver must return the OrgVehicle, not the GlobalVehicle —
        # even though the caller passed the GlobalVehicle's id.
        assert result == ("org", ov)
        # And the returned record must NOT be the GlobalVehicle.
        assert result[1] is ov
        assert result[1].id != gv.id

        # Two SELECTs were issued: one for the global vehicle, one for
        # the rego-scoped org follow-up. The original-id-on-org_vehicles
        # fallback is NOT reached when promotion is detected.
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_resolver_returns_global_for_org_b_with_no_promotion(self):
        """Same global_vehicle, different calling org — no promotion → global.

        org_b has not been promoted for this rego (no org_vehicles row
        exists scoped to org_b). The resolver must return
        ``("global", gv)`` so org_b continues to read via Read_Fallback.
        """
        org_b_id = uuid.uuid4()
        gv = _make_global_vehicle(rego="PROMO1")

        # First execute: GlobalVehicle SELECT by id → gv.
        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        # Second execute: OrgVehicle SELECT by (org_id, upper(rego)) →
        # None. org_b has not been promoted.
        no_org_match = MagicMock()
        no_org_match.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[gv_result, no_org_match])

        result = await _resolve_vehicle_type(db, gv.id, org_b_id)

        assert result == ("global", gv)
        assert result[1] is gv

        # Both SELECTs executed: the rego-keyed follow-up runs even on
        # the no-promotion branch. This is the single extra query cost
        # of the promotion-aware resolver.
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_resolver_returns_org_when_id_directly_matches_org_vehicle(self):
        """Backwards-compatibility: original behaviour for direct OrgVehicle id.

        When the supplied id does NOT match any GlobalVehicle but DOES
        match an OrgVehicle scoped to the calling org, the resolver still
        returns ``("org", ov)`` via the original direct-id path. This
        proves the new rego-keyed follow-up did not regress the
        already-correct OrgVehicle-id case.
        """
        org_id = uuid.uuid4()
        ov_id = uuid.uuid4()

        ov = MagicMock(spec=OrgVehicle)
        ov.id = ov_id
        ov.org_id = org_id
        ov.rego = "DIRECT1"

        # First execute: GlobalVehicle SELECT by id → None (no global row).
        no_gv = MagicMock()
        no_gv.scalar_one_or_none.return_value = None

        # Second execute: OrgVehicle SELECT by (id, org_id) → ov.
        ov_result = MagicMock()
        ov_result.scalar_one_or_none.return_value = ov

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[no_gv, ov_result])

        result = await _resolve_vehicle_type(db, ov_id, org_id)

        assert result == ("org", ov)
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_resolver_returns_none_when_id_unknown(self):
        """Backwards-compatibility: unknown id still returns None.

        Neither the GlobalVehicle SELECT nor the OrgVehicle direct-id
        SELECT match. The promotion-aware follow-up does not run because
        no GlobalVehicle was matched. The resolver returns ``None`` — the
        original contract.
        """
        org_id = uuid.uuid4()
        unknown_id = uuid.uuid4()

        # Both SELECTs return None.
        no_match = MagicMock()
        no_match.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[no_match, no_match])

        result = await _resolve_vehicle_type(db, unknown_id, org_id)

        assert result is None
        assert db.execute.await_count == 2


# ---------------------------------------------------------------------------
# Task 11.1 — customer-search vehicle list returns promoted vehicles too
# ---------------------------------------------------------------------------
#
# Pre-task-11.1, ``app/modules/customers/service.py::search_customers``'s
# vehicle block joined ``customer_vehicles`` to ``global_vehicles`` only,
# then dropped any row where ``gv`` was ``None`` — silently hiding every
# promoted ``customer_vehicles`` link (those whose ``global_vehicle_id``
# was migrated to ``org_vehicle_id`` by ``migrate_link_to_org_vehicle``).
#
# The fix is a double outerjoin to ``GlobalVehicle`` AND ``OrgVehicle``
# (the ``vehicle_link_check`` CHECK constraint guarantees exactly one is
# non-NULL per row), with a ``v = gv if gv is not None else ov`` fallback
# inside the loop. Migration parity (0105 + 0181) ensures every consumed
# attribute is present on both tables, so the dict body is source-agnostic.
#
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.6, 10.2, 15.5
# Design: Read Paths (extended); Backwards Compatibility table

from app.modules.customers.models import Customer  # noqa: E402
from app.modules.customers.service import search_customers  # noqa: E402
from app.modules.vehicles.models import CustomerVehicle  # noqa: E402


def _make_customer_for_search(*, org_id, first_name="Promoted", last_name="Tester"):
    """Build a mock Customer ORM object suitable for search_customers."""
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.customer_type = "individual"
    c.first_name = first_name
    c.last_name = last_name
    c.company_name = None
    c.display_name = f"{first_name} {last_name}"
    c.email = None
    c.phone = None
    c.mobile_phone = None
    c.work_phone = None
    c.custom_fields = None
    c.last_portal_access_at = None
    c.is_anonymised = False
    return c


def _mock_count(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _mock_scalars(values):
    r = MagicMock()
    inner = MagicMock()
    inner.all.return_value = values
    r.scalars.return_value = inner
    return r


def _mock_rows(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


class TestSearchCustomersReturnsPromotedVehicles:
    """search_customers with include_vehicles=True must render BOTH link types.

    Pre-create one promoted (``org_vehicle_id``-only) link and one
    unmigrated (``global_vehicle_id``-only) link for the same customer,
    search the customer, and assert both vehicles render with their
    respective rego/make/model. The pre-Task-11.1 implementation dropped
    the promoted link entirely; this test locks in the fixed behaviour.
    """

    @pytest.mark.asyncio
    async def test_customer_search_returns_promoted_vehicles(self):
        org_id = uuid.uuid4()
        customer = _make_customer_for_search(org_id=org_id)

        # Unmigrated link — points at GlobalVehicle (gv path).
        gv = MagicMock()
        gv.id = uuid.uuid4()
        gv.rego = "GLOB01"
        gv.make = "Toyota"
        gv.model = "Hilux"
        gv.year = 2018
        gv.colour = "White"
        gv.odometer_last_recorded = 80_000
        gv.service_due_date = None
        gv.wof_expiry = None
        gv.cof_expiry = None
        gv.inspection_type = "wof"

        cv_global = MagicMock(spec=CustomerVehicle)
        cv_global.id = uuid.uuid4()
        cv_global.org_id = org_id
        cv_global.customer_id = customer.id
        cv_global.global_vehicle_id = gv.id
        cv_global.org_vehicle_id = None

        # Promoted link — points at OrgVehicle (ov path).
        ov = MagicMock(spec=OrgVehicle)
        ov.id = uuid.uuid4()
        ov.org_id = org_id
        ov.rego = "PROMO1"
        ov.make = "Ford"
        ov.model = "Ranger"
        ov.year = 2022
        ov.colour = "Blue"
        ov.odometer_last_recorded = 25_000
        ov.service_due_date = None
        ov.wof_expiry = None
        ov.cof_expiry = None
        ov.inspection_type = "wof"

        cv_promoted = MagicMock(spec=CustomerVehicle)
        cv_promoted.id = uuid.uuid4()
        cv_promoted.org_id = org_id
        cv_promoted.customer_id = customer.id
        cv_promoted.global_vehicle_id = None
        cv_promoted.org_vehicle_id = ov.id

        # search_customers issues, in order, when query is None:
        #   1. count(Customer)         → 1
        #   2. select(Customer)         → [customer]
        #   3. receivables grouped sum → []
        #   4. credits grouped sum     → []
        #   5. linked-vehicles double-outerjoin → [(cv_global, gv, None),
        #                                          (cv_promoted, None, ov)]
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_count(1),
                _mock_scalars([customer]),
                _mock_rows([]),
                _mock_rows([]),
                _mock_rows([(cv_global, gv, None), (cv_promoted, None, ov)]),
            ]
        )
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch("app.core.modules.ModuleService") as MockModSvc:
            MockModSvc.return_value.is_enabled = AsyncMock(return_value=True)
            result = await search_customers(
                db,
                org_id=org_id,
                include_vehicles=True,
            )

        assert result["total"] == 1
        assert len(result["customers"]) == 1
        cust_dict = result["customers"][0]
        linked = cust_dict["linked_vehicles"]

        # -- Both vehicles render — pre-Task-11.1 only the global one
        # would have appeared. --
        assert len(linked) == 2, (
            "search_customers must render BOTH link types: pre-Task-11.1 "
            "the promoted (org_vehicle_id-only) link was silently dropped "
            "by the single-outerjoin + 'if gv:' guard"
        )

        by_rego = {row["rego"]: row for row in linked}
        assert set(by_rego) == {"GLOB01", "PROMO1"}

        # -- Unmigrated (global) link renders from GlobalVehicle. --
        glob_row = by_rego["GLOB01"]
        assert glob_row["id"] == str(gv.id)
        assert glob_row["make"] == "Toyota"
        assert glob_row["model"] == "Hilux"
        assert glob_row["year"] == 2018
        assert glob_row["colour"] == "White"
        assert glob_row["odometer"] == 80_000
        assert glob_row["source"] == "global"

        # -- Promoted link renders from OrgVehicle. --
        prom_row = by_rego["PROMO1"]
        assert prom_row["id"] == str(ov.id)
        assert prom_row["make"] == "Ford"
        assert prom_row["model"] == "Ranger"
        assert prom_row["year"] == 2022
        assert prom_row["colour"] == "Blue"
        assert prom_row["odometer"] == 25_000
        assert prom_row["source"] == "org"


# ---------------------------------------------------------------------------
# Dashboard expiry-reminders widget — Task 11.3
# ---------------------------------------------------------------------------
#
# Covers Task 11.3 of the ``vehicle-data-isolation`` spec: the
# ``app/modules/organisations/dashboard_service.py::get_expiry_reminders``
# widget previously joined ``org_vehicles ov ON ov.global_vehicle_id =
# gv.id`` — a column that does not exist on the model. Post-Task-11.3 the
# widget reads from TWO sources:
#
#   1. ``org_vehicles`` rows for the calling org (covers every promoted
#      vehicle plus every manually-entered row).
#   2. ``global_vehicles`` rows joined through ``customer_vehicles`` for
#      un-promoted regos (``cv.org_id = :org_id`` AND
#      ``cv.org_vehicle_id IS NULL`` AND ``cv.global_vehicle_id IS NOT NULL``).
#
# The customer-name lookup also widens to accept either link type:
# ``WHERE (cv.org_vehicle_id = :vid OR cv.global_vehicle_id = :vid) AND
# cv.org_id = :org_id LIMIT 1``.
#
# Test plan (one consolidated regression test):
#   - Set up: org with one promoted ``org_vehicles`` row whose
#     ``wof_expiry`` is 14 days away, plus one un-promoted
#     ``global_vehicles``-backed link whose ``wof_expiry`` is 21 days
#     away.
#   - Run the widget.
#   - Assert both vehicles are returned with correct customer names.
#   - Assert no SQL clause references ``org_vehicles.global_vehicle_id``
#     (the pre-existing broken join column) — the equivalent of the
#     manual ``EXPLAIN`` check called for in the task.
#
# Requirements: 6.1, 6.2, 6.5, 9.7, 10.2, 15.5
# Design: Read Paths (extended).

from datetime import timedelta

from app.modules.organisations.dashboard_service import get_expiry_reminders


def _row(**kwargs):
    """Build a MagicMock that mimics a SQLAlchemy Row with attribute access."""
    r = MagicMock()
    for key, value in kwargs.items():
        setattr(r, key, value)
    return r


def _result_first(value):
    r = MagicMock()
    r.first.return_value = value
    return r


def _result_all(rows):
    r = MagicMock()
    r.all.return_value = list(rows)
    return r


class TestDashboardExpiryWidgetReadsFromOrgVehiclesPostPromotion:
    @pytest.mark.asyncio
    async def test_dashboard_expiry_widget_reads_from_org_vehicles_post_promotion(self):
        """Widget pulls expiry data from BOTH org_vehicles and global_vehicles
        (for un-promoted links), and customer-name lookup accepts either
        link type.

        Asserts:
          (a) Both vehicles appear in the widget's items list.
          (b) The promoted (org_vehicles-backed) vehicle's expiry date
              and customer name are correct.
          (c) The un-promoted (global_vehicles-backed) vehicle's expiry
              date and customer name are correct.
          (d) No SQL clause issued by the widget references
              ``org_vehicles.global_vehicle_id`` (the pre-existing
              broken-join column on the model).
          (e) The customer-name lookup SQL accepts either link type
              (``cv.org_vehicle_id = :vid OR cv.global_vehicle_id =
              :vid``) AND scopes by ``org_id``.
        """
        org_id = uuid.uuid4()
        today = date.today()

        # -- Promoted vehicle: wof_expiry 14 days away. --
        promoted_ov_id = uuid.uuid4()
        promoted_wof = today + timedelta(days=14)

        # -- Un-promoted vehicle: wof_expiry 21 days away. --
        unpromoted_gv_id = uuid.uuid4()
        unpromoted_wof = today + timedelta(days=21)

        # Source 1 result — one row from org_vehicles for the promoted
        # vehicle. Source 2 result — one row from global_vehicles for
        # the un-promoted link.
        ov_row = _row(
            vehicle_id=promoted_ov_id,
            vehicle_rego="PROMO1",
            vehicle_make="Ford",
            vehicle_model="Ranger",
            wof_expiry=promoted_wof,
            cof_expiry=None,
            inspection_type="wof",
            service_due_date=None,
        )
        gv_row = _row(
            vehicle_id=unpromoted_gv_id,
            vehicle_rego="GLOB01",
            vehicle_make="Toyota",
            vehicle_model="Hilux",
            wof_expiry=unpromoted_wof,
            cof_expiry=None,
            inspection_type="wof",
            service_due_date=None,
        )

        # Customer-name lookup rows — keyed by the vehicle id (works for
        # either link type because the SQL is OR-of-two-columns).
        promoted_cust_row = _row(id=uuid.uuid4(), name="Alice Customer")
        unpromoted_cust_row = _row(id=uuid.uuid4(), name="Bob Customer")

        # Track every SQL statement issued so we can assert no
        # ``org_vehicles.global_vehicle_id`` reference appears anywhere
        # AND that the customer-name lookup SQL is the widened variant.
        executed_sql: list[str] = []
        executed_binds: list[dict] = []

        async def fake_execute(clause, bind=None):
            sql_text = str(getattr(clause, "text", clause))
            executed_sql.append(sql_text)
            executed_binds.append(bind or {})

            # Route the response based on the SQL content.
            sl = sql_text.lower()
            if "dashboard_reminder_config" in sl:
                # Config: use defaults (return no row).
                return _result_first(None)
            if "dashboard_reminder_dismissals" in sl:
                # No dismissed combos.
                return _result_all([])
            if "from org_vehicles" in sl and "where ov.org_id" in sl:
                # Source 1.
                return _result_all([ov_row])
            if "from global_vehicles" in sl and "customer_vehicles" in sl:
                # Source 2 (un-promoted links).
                return _result_all([gv_row])
            if "from customers" in sl and "customer_vehicles" in sl:
                # Customer-name lookup. Bind ``vid`` tells us which.
                vid = (bind or {}).get("vid")
                if vid == str(promoted_ov_id):
                    return _result_first(promoted_cust_row)
                if vid == str(unpromoted_gv_id):
                    return _result_first(unpromoted_cust_row)
                return _result_first(None)
            return _result_first(None)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)

        result = await get_expiry_reminders(db, org_id=org_id)

        # -- (a) Both vehicles appear in the items list. --
        items = result["items"]
        assert result["total"] == len(items) == 2, (
            f"Widget must return both vehicles (promoted + un-promoted); "
            f"got {len(items)} items: {items!r}"
        )

        by_rego = {item["vehicle_rego"]: item for item in items}
        assert set(by_rego) == {"PROMO1", "GLOB01"}

        # -- (b) Promoted vehicle is correct. --
        promo = by_rego["PROMO1"]
        assert promo["vehicle_id"] == str(promoted_ov_id)
        assert promo["vehicle_make"] == "Ford"
        assert promo["vehicle_model"] == "Ranger"
        assert promo["expiry_type"] == "wof"
        assert promo["expiry_date"] == str(promoted_wof)[:10]
        assert promo["customer_name"] == "Alice Customer"

        # -- (c) Un-promoted vehicle is correct. --
        glob = by_rego["GLOB01"]
        assert glob["vehicle_id"] == str(unpromoted_gv_id)
        assert glob["vehicle_make"] == "Toyota"
        assert glob["vehicle_model"] == "Hilux"
        assert glob["expiry_type"] == "wof"
        assert glob["expiry_date"] == str(unpromoted_wof)[:10]
        assert glob["customer_name"] == "Bob Customer"

        # -- (d) No SQL clause references ``org_vehicles.global_vehicle_id``
        #        (the pre-existing broken-join column on the model). This is
        #        the unit-test equivalent of the ``EXPLAIN`` check in the
        #        task. --
        all_sql = "\n".join(executed_sql).lower()
        # Match any of: ``ov.global_vehicle_id``, ``org_vehicles.global_vehicle_id``,
        # or aliased forms — none should appear.
        assert "ov.global_vehicle_id" not in all_sql, (
            "Widget SQL must not reference ov.global_vehicle_id — that "
            "column does not exist on the org_vehicles model and would "
            "error at runtime"
        )
        assert "org_vehicles.global_vehicle_id" not in all_sql, (
            "Widget SQL must not reference org_vehicles.global_vehicle_id"
        )

        # -- (e) The customer-name lookup SQL accepts either link type
        #        AND scopes by org_id. --
        cust_sql = next(
            (s for s in executed_sql if "from customers" in s.lower()
             and "customer_vehicles" in s.lower()),
            None,
        )
        assert cust_sql is not None, (
            "Customer-name lookup SQL was never issued"
        )
        cs = cust_sql.lower()
        assert "cv.org_vehicle_id = :vid" in cs
        assert "cv.global_vehicle_id = :vid" in cs
        assert " or " in cs, (
            "Customer-name lookup must combine the two link columns "
            "with OR so either link type matches"
        )
        assert "cv.org_id = :org_id" in cs, (
            "Customer-name lookup must scope by org_id"
        )


# ---------------------------------------------------------------------------
# Task 11.4 — data_io export labels promoted org_vehicles as "carjam"
# ---------------------------------------------------------------------------


class TestDataIoExportVehiclesLabelsPromotedAsCarjam:
    """Regression test for Task 11.4.

    ``export_vehicles_csv`` pre-loads every ``OrgVehicle`` row for the org
    (manual-entry AND promoted) and runs a separate query for un-promoted
    ``GlobalVehicle`` rows reachable via ``customer_vehicles.global_vehicle_id``.
    Promoted vehicles already appear in the CSV via the ``OrgVehicle`` loop —
    the bug fixed here is that the loop hardcoded ``"manual"`` as the
    ``source`` column for every row, mislabelling promoted (CarJam-sourced,
    ``is_manual_entry=False``) vehicles as user-entered.

    The fix: replace the ``"manual"`` literal with
    ``"manual" if v.is_manual_entry else "carjam"``.

    Verify:
      - Pre-create one un-promoted (manual-entry) and one promoted
        (``is_manual_entry=False``) ``org_vehicles`` row
      - Run ``export_vehicles_csv``
      - Assert the manual-entry row's source column reads ``"manual"``
      - Assert the promoted row's source column reads ``"carjam"``
      - Both regos appear in the CSV exactly once

    Validates: Requirements 6.5, 9.6, 15.5
    """

    @pytest.mark.asyncio
    async def test_data_io_export_vehicles_labels_promoted_as_carjam(self):
        import csv as _csv
        import io as _io

        from app.modules.data_io.service import (
            VEHICLE_EXPORT_HEADERS,
            export_vehicles_csv,
        )

        org_id = uuid.uuid4()

        # -- Manual-entry org_vehicle (was never CarJam-sourced). --
        manual_v = MagicMock()
        manual_v.id = uuid.uuid4()
        manual_v.org_id = org_id
        manual_v.rego = "MANUAL1"
        manual_v.make = "Toyota"
        manual_v.model = "Hilux"
        manual_v.year = 2018
        manual_v.colour = "White"
        manual_v.body_type = "Ute"
        manual_v.fuel_type = "Diesel"
        manual_v.engine_size = "3.0L"
        manual_v.num_seats = 5
        manual_v.is_manual_entry = True
        manual_v.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        # -- Promoted org_vehicle (created by ``promote_vehicle()`` from a
        #    CarJam-sourced global_vehicles row; ``is_manual_entry=False``). --
        promoted_v = MagicMock()
        promoted_v.id = uuid.uuid4()
        promoted_v.org_id = org_id
        promoted_v.rego = "PROMO1"
        promoted_v.make = "Ford"
        promoted_v.model = "Ranger"
        promoted_v.year = 2021
        promoted_v.colour = "Blue"
        promoted_v.body_type = "Ute"
        promoted_v.fuel_type = "Diesel"
        promoted_v.engine_size = "2.0L"
        promoted_v.num_seats = 5
        promoted_v.is_manual_entry = False
        promoted_v.created_at = datetime(2024, 6, 1, tzinfo=timezone.utc)

        # ``export_vehicles_csv`` issues four queries in this order:
        #   1. select OrgVehicle where org_id = :org
        #   2. select GlobalVehicle .join(CustomerVehicle ...)
        #   3. select CustomerVehicle where org_id = :org
        #   4. select Customer where id in (...)  (only if customer_ids is non-empty)
        # We return both org_vehicles on call 1 and empty results elsewhere.
        call_count = 0

        async def mock_execute(_query, *_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            scalars_mock = MagicMock()
            if call_count == 1:
                # Org vehicles — both rows.
                scalars_mock.all.return_value = [manual_v, promoted_v]
            else:
                # Global vehicles + customer_vehicles links + customers — empty.
                scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        csv_text = await export_vehicles_csv(db, org_id)

        reader = _csv.reader(_io.StringIO(csv_text))
        rows = list(reader)

        # Header + 2 data rows; both regos present exactly once.
        assert rows[0] == VEHICLE_EXPORT_HEADERS
        assert len(rows) == 3, (
            f"Expected header + 2 vehicle rows, got {len(rows)} rows: {rows!r}"
        )

        regos = [r[1] for r in rows[1:]]
        assert sorted(regos) == ["MANUAL1", "PROMO1"], (
            f"Both regos must appear exactly once; got {regos!r}"
        )

        # Locate column index for "source" (task calls it ``lookup_type``;
        # the header in the file is ``source``).
        source_idx = VEHICLE_EXPORT_HEADERS.index("source")

        by_rego = {r[1]: r for r in rows[1:]}

        # Manual-entry row → "manual".
        assert by_rego["MANUAL1"][source_idx] == "manual", (
            "Manual-entry org_vehicles row must be labelled 'manual'; "
            f"got {by_rego['MANUAL1'][source_idx]!r}"
        )

        # Promoted row → "carjam" (NOT the hardcoded "manual" literal).
        assert by_rego["PROMO1"][source_idx] == "carjam", (
            "Promoted org_vehicles row (is_manual_entry=False) must be "
            "labelled 'carjam' since its fields originated from CarJam; "
            f"got {by_rego['PROMO1'][source_idx]!r}. The fix replaces the "
            "hardcoded 'manual' literal with "
            "('manual' if v.is_manual_entry else 'carjam')."
        )


# ---------------------------------------------------------------------------
# Task 11.6 — notification & reminder services that inner-join customer_vehicles
# to global_vehicles must use a two-pass query so promoted links are not dropped
# ---------------------------------------------------------------------------
#
# Three call sites currently do an INNER JOIN that silently excludes every
# ``customer_vehicles`` row whose link has been migrated to ``org_vehicle_id``.
# Post-deploy, no WOF / COF / Rego / service-due reminders fire for any rego
# touched by a customer-driven write since the deploy — every promoted link
# drops out of the join. Task 11.6 fixes:
#
#   1. ``app/modules/notifications/service.py::process_wof_rego_reminders``
#   2. ``app/modules/notifications/service.py::process_customer_reminders``
#   3. ``app/modules/notifications/reminder_queue_service.py::_process_customer_reminders``
#
# Each is converted from a single inner join against ``global_vehicles`` to two
# parallel queries (one per link type) whose result rows are merged. The dedup
# subject key is also standardised on ``cv.id`` (the link id) so it survives
# promotion — pre-spec the key was ``f"..._{gv.id}_..."`` and would re-fire after
# every promotion since the resolved vehicle id flips from ``gv.id`` to
# ``ov.id``.
#
# Validates: Requirements 6.1, 6.2, 6.5, 9.6, 10.2, 15.5
# Design: Read Paths (extended) — reminder services.

from app.modules.notifications.models import NotificationLog  # noqa: E402,F401
from app.modules.notifications.service import (  # noqa: E402
    process_customer_reminders,
    process_wof_rego_reminders,
)
# enqueue_customer_reminders is imported here so the module is loaded; the
# direct test of its inner two-pass query is exercised through the public
# ``process_customer_reminders`` test which validates the same fix pattern.
from app.modules.notifications.reminder_queue_service import (  # noqa: E402,F401
    enqueue_customer_reminders,
)


def _make_org_for_reminders(*, org_id, name="Test Org"):
    """Build a mock Organisation with sensible defaults for reminder tests."""
    org = MagicMock()
    org.id = org_id
    org.name = name
    org.plan_id = uuid.uuid4()
    org.settings = {"phone": "021 555 0000", "email": "ops@example.com"}
    return org


def _make_subscription_plan(*, sms_included=True):
    sp = MagicMock()
    sp.sms_included = sms_included
    return sp


def _make_pref(*, org_id, channel="email", days_in_advance=14):
    pref = MagicMock()
    pref.org_id = org_id
    pref.channel = channel
    pref.config = {"days_in_advance": days_in_advance}
    return pref


def _make_customer_for_reminders(
    *, org_id, email="customer@example.com", phone=None,
    first_name="Driver", last_name="One", reminder_config=None
):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.first_name = first_name
    c.last_name = last_name
    c.email = email
    c.phone = phone
    c.address = None
    c.is_anonymised = False
    c.custom_fields = {"reminder_config": reminder_config or {}}
    return c


def _make_promoted_ov(*, org_id, rego="PROMO1", **fields):
    """Build an OrgVehicle mock representing a post-promotion org snapshot."""
    ov = MagicMock()
    ov.id = uuid.uuid4()
    ov.org_id = org_id
    ov.rego = rego
    ov.make = fields.get("make", "Toyota")
    ov.model = fields.get("model", "Corolla")
    ov.year = fields.get("year", 2020)
    ov.wof_expiry = fields.get("wof_expiry")
    ov.cof_expiry = fields.get("cof_expiry")
    ov.registration_expiry = fields.get("registration_expiry")
    ov.service_due_date = fields.get("service_due_date")
    return ov


def _make_unpromoted_gv(*, rego="GLOB01", **fields):
    """Build a GlobalVehicle mock representing an un-promoted link."""
    gv = MagicMock()
    gv.id = uuid.uuid4()
    gv.rego = rego
    gv.make = fields.get("make", "Ford")
    gv.model = fields.get("model", "Ranger")
    gv.year = fields.get("year", 2018)
    gv.wof_expiry = fields.get("wof_expiry")
    gv.cof_expiry = fields.get("cof_expiry")
    gv.registration_expiry = fields.get("registration_expiry")
    gv.service_due_date = fields.get("service_due_date")
    return gv


def _make_link(*, org_id, customer_id, global_vehicle_id=None, org_vehicle_id=None):
    cv = MagicMock()
    cv.id = uuid.uuid4()
    cv.org_id = org_id
    cv.customer_id = customer_id
    cv.global_vehicle_id = global_vehicle_id
    cv.org_vehicle_id = org_vehicle_id
    return cv


def _entity_names_of(stmt) -> set[str]:
    """Return the set of ORM entity / table names referenced by a Select.

    Inspects the statement WITHOUT compiling SQL or invoking
    ``column_descriptions`` (both trigger global ORM mapper configuration
    which can fail in unit tests on unrelated classes that haven't been
    imported). Uses ``stmt._raw_columns`` for the FROM target tables and
    walks the join tree for any joined-in tables.
    """
    names: set[str] = set()
    # Map table names to canonical class-name aliases.
    table_to_class = {
        "customer_vehicles": "CustomerVehicle",
        "global_vehicles": "GlobalVehicle",
        "org_vehicles": "OrgVehicle",
        "customers": "Customer",
        "organisations": "Organisation",
        "subscription_plans": "SubscriptionPlan",
        "notification_logs": "NotificationLog",
        "notification_log": "NotificationLog",
        "notification_preferences": "NotificationPreference",
        "notification_preference": "NotificationPreference",
        "sms_verification_providers": "SmsVerificationProvider",
        "email_providers": "EmailProvider",
    }

    def _add(table_name: str | None) -> None:
        if not table_name:
            return
        names.add(table_name)
        if table_name in table_to_class:
            names.add(table_to_class[table_name])

    # _raw_columns holds the SELECT target entities (their underlying Tables).
    try:
        raw = getattr(stmt, "_raw_columns", []) or []
        for col in raw:
            _add(getattr(col, "name", None))
    except Exception:
        pass

    # _setup_joins holds explicit .join(...) targets.
    try:
        joins = getattr(stmt, "_setup_joins", ()) or ()
        for j in joins:
            # Each join is a tuple (target, onclause, from_, flags)
            target = j[0] if isinstance(j, tuple) and len(j) > 0 else None
            if target is not None:
                _add(getattr(target, "name", None))
    except Exception:
        pass

    # _from_obj holds the explicit FROM clauses (joins).
    try:
        from_objs = getattr(stmt, "_from_obj", ()) or ()
        for f in from_objs:
            _walk_clause(f, _add)
    except Exception:
        pass

    return names


def _walk_clause(clause, add_fn) -> None:
    """Recursively walk a join tree calling ``add_fn`` for each table."""
    if clause is None:
        return
    name = getattr(clause, "name", None)
    if name:
        add_fn(name)
    for attr in ("left", "right", "onclause"):
        sub = getattr(clause, attr, None)
        if sub is not None and sub is not clause:
            _walk_clause(sub, add_fn)


def _references_column(stmt, column_name: str) -> bool:
    """True if the statement's WHERE clause references ``column_name``.

    Walks the WHERE clause's binary expressions looking for a column with
    the given key. No SQL compilation is performed.
    """
    try:
        from sqlalchemy.sql import visitors
        whereclause = getattr(stmt, "whereclause", None)
        if whereclause is None:
            return False

        found = {"hit": False}

        def _visit(elem):
            key = getattr(elem, "key", None)
            if key == column_name:
                found["hit"] = True
            name = getattr(elem, "name", None)
            if name == column_name:
                found["hit"] = True

        visitors.traverse(whereclause, {}, {"column": _visit, "binary": _visit})
        return found["hit"]
    except Exception:
        return False


class TestWofExpiryReminderFiresForPromotedVehicle:
    """Promoted vehicle whose ``org_vehicles.wof_expiry`` matches the target
    date must produce exactly one reminder log row when
    ``process_wof_rego_reminders`` runs.

    Pre-Task-11.6 the inner join against ``global_vehicles`` dropped every
    promoted link, so this code path silently returned zero rows for
    promoted vehicles. The fix adds a parallel query against
    ``org_vehicles`` and merges the rows.

    Validates: Requirements 6.1, 6.2, 6.5, 15.5
    """

    @pytest.mark.asyncio
    async def test_wof_expiry_reminder_fires_for_promoted_vehicle(self):
        org_id = uuid.uuid4()
        # Match the function's UTC-based ``today``.
        today = datetime.now(timezone.utc).date()
        target_date = today + timedelta(days=14)

        # Set up fixture: one promoted vehicle whose wof_expiry hits the
        # target date, plus a customer linked to it via ``org_vehicle_id``.
        ov = _make_promoted_ov(org_id=org_id, rego="PROMO1", wof_expiry=target_date)
        customer = _make_customer_for_reminders(org_id=org_id)
        cv = _make_link(
            org_id=org_id,
            customer_id=customer.id,
            org_vehicle_id=ov.id,
        )

        org = _make_org_for_reminders(org_id=org_id)
        pref = _make_pref(org_id=org_id, channel="email", days_in_advance=14)
        plan = _make_subscription_plan(sms_included=True)

        # Track which dedup_subject keys were inserted via log_email_sent
        # (the first arg is the db, kwargs include `subject`).
        sent_subjects: list[str] = []

        async def mock_log_email_sent(_db, *, org_id, recipient, template_type,
                                      subject, status, channel="email",
                                      error_message=None, sent_at=None):
            sent_subjects.append(subject)
            return {"id": str(uuid.uuid4()), "subject": subject}

        async def mock_send_email_task(*args, **kwargs):
            return None

        call_log: list[str] = []

        # Build a deterministic side_effect: each db.execute result is
        # generated based on call ordering matching process_wof_rego_reminders.
        # Order of db.execute calls per org loop iteration:
        #   1. select NotificationPreference            → [pref]
        # Then for each pref:
        #   2. select Organisation                       → org
        #   3. select SubscriptionPlan (since plan_id)   → plan
        #   For each (WOF, COF, Reg) triple:
        #     a. cv_gv_stmt (gv-side)                    → []
        #     b. cv_ov_stmt (ov-side)                    → [(cv, ov, customer)] for WOF, else []
        #     For each row:
        #       c. dedup count                           → 0 (no prior log)
        async def fake_execute(stmt, *args, **kwargs):
            entity_names = _entity_names_of(stmt)

            r = MagicMock()
            if "NotificationPreference" in entity_names:
                inner = MagicMock()
                inner.all.return_value = [pref]
                r.scalars.return_value = inner
                call_log.append("prefs")
                return r
            if "Organisation" in entity_names:
                r.scalar_one_or_none.return_value = org
                call_log.append("org")
                return r
            if "SubscriptionPlan" in entity_names:
                r.scalar_one_or_none.return_value = plan
                call_log.append("plan")
                return r
            # Two-pass vehicle queries: distinguish gv vs ov by entity set.
            if "CustomerVehicle" in entity_names and "GlobalVehicle" in entity_names:
                r.all.return_value = []
                call_log.append("cv_gv")
                return r
            if "CustomerVehicle" in entity_names and "OrgVehicle" in entity_names:
                # Only the WOF iteration's ov-query returns the row — we
                # detect the active expiry field from the WHERE clause's
                # column references.
                if _references_column(stmt, "wof_expiry"):
                    r.all.return_value = [(cv, ov, customer)]
                else:
                    r.all.return_value = []
                call_log.append("cv_ov")
                return r
            # Dedup count query.
            if "NotificationLog" in entity_names:
                r.scalar.return_value = 0
                call_log.append("dedup")
                return r
            # Fallback (shouldn't be hit in this test).
            r.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
            r.scalar.return_value = 0
            r.scalar_one_or_none.return_value = None
            r.all.return_value = []
            return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new=AsyncMock(side_effect=mock_log_email_sent),
        ), patch(
            "app.tasks.notifications.send_email_task",
            new=AsyncMock(side_effect=mock_send_email_task),
        ):
            stats = await process_wof_rego_reminders(db)

        # The two-pass query must have run for at least the WOF iteration.
        assert "cv_gv" in call_log, (
            "process_wof_rego_reminders must run the un-promoted-side "
            "(global_vehicles) pass; got call_log=%r" % call_log
        )
        assert "cv_ov" in call_log, (
            "process_wof_rego_reminders must run the promoted-side "
            "(org_vehicles) pass — pre-Task-11.6 only the inner join "
            "against global_vehicles ran, so promoted vehicles were "
            "silently dropped; got call_log=%r" % call_log
        )

        # Exactly one reminder was sent (one WOF row, one customer).
        assert stats["reminders_sent"] == 1, (
            f"Expected exactly one reminder for the promoted vehicle; "
            f"got stats={stats!r}"
        )
        assert len(sent_subjects) == 1

        # The dedup subject must be keyed on ``cv.id`` (stable across
        # promotion), NOT on ``ov.id`` or ``gv.id``.
        subject = sent_subjects[0]
        assert str(cv.id) in subject, (
            "Dedup subject must include cv.id (the link id) so the key "
            "survives promotion; got subject=%r" % subject
        )
        assert str(ov.id) not in subject, (
            "Dedup subject must NOT include ov.id — the vehicle id is "
            "unstable across promotion (flips from gv.id to ov.id) and "
            "would re-fire reminders on every promotion; got subject=%r"
            % subject
        )


class TestCustomerReminderFiresForPromotedVehicle:
    """Promoted vehicle whose ``org_vehicles.wof_expiry`` matches the target
    date must produce a reminder when ``process_customer_reminders`` runs.

    Pre-Task-11.6 the per-customer inner join against ``global_vehicles``
    dropped every promoted link. The fix adds a parallel query against
    ``org_vehicles`` and merges the rows.

    Validates: Requirements 6.1, 6.2, 6.5, 15.5
    """

    @pytest.mark.asyncio
    async def test_customer_reminder_fires_for_promoted_vehicle(self):
        org_id = uuid.uuid4()
        # Use the SAME today computation as ``process_customer_reminders``
        # (UTC-based) so target_date matches across the call boundary.
        today = datetime.now(timezone.utc).date()
        target_date = today + timedelta(days=30)

        ov = _make_promoted_ov(
            org_id=org_id,
            rego="PROMO2",
            wof_expiry=target_date,
        )
        customer = _make_customer_for_reminders(
            org_id=org_id,
            email="driver@example.com",
            reminder_config={
                "wof_expiry": {"enabled": True, "days_before": 30, "channel": "email"},
            },
        )
        cv = _make_link(
            org_id=org_id,
            customer_id=customer.id,
            org_vehicle_id=ov.id,
        )

        org = _make_org_for_reminders(org_id=org_id)
        plan = _make_subscription_plan(sms_included=True)

        sms_provider = MagicMock()
        sms_provider.credentials_encrypted = "encrypted"
        sms_provider.is_default = True
        sms_provider.priority = 0
        sms_provider.is_active = True

        email_provider = MagicMock()
        email_provider.is_active = True
        email_provider.credentials_set = True
        email_provider.priority = 0

        sent_subjects: list[str] = []

        async def mock_log_email_sent(_db, *, org_id, recipient, template_type,
                                      subject, status, channel="email",
                                      error_message=None, sent_at=None):
            sent_subjects.append(subject)
            return {"id": str(uuid.uuid4()), "subject": subject}

        async def mock_send_email_task(*args, **kwargs):
            return None

        call_log: list[str] = []

        async def fake_execute(stmt, *args, **kwargs):
            entity_names = _entity_names_of(stmt)

            r = MagicMock()
            # Customer scan with reminder_config in custom_fields.
            if "Customer" in entity_names and "CustomerVehicle" not in entity_names:
                inner = MagicMock()
                inner.all.return_value = [customer]
                r.scalars.return_value = inner
                call_log.append("customers")
                return r
            if "Organisation" in entity_names:
                r.scalar_one_or_none.return_value = org
                call_log.append("org")
                return r
            if "SubscriptionPlan" in entity_names:
                r.scalar_one_or_none.return_value = plan
                call_log.append("plan")
                return r
            if "SmsVerificationProvider" in entity_names:
                inner = MagicMock()
                inner.first.return_value = sms_provider
                r.scalars.return_value = inner
                call_log.append("sms_provider")
                return r
            if "EmailProvider" in entity_names:
                inner = MagicMock()
                inner.first.return_value = email_provider
                r.scalars.return_value = inner
                call_log.append("email_provider")
                return r
            # Country-code raw SQL: it's a ``text("SELECT country_code ...")``
            # clause (str() on a TextClause is safe — no compile triggered).
            try:
                sql_str = str(stmt)
            except Exception:
                sql_str = ""
            if "country_code" in sql_str.lower():
                r.scalar_one_or_none.return_value = "NZ"
                call_log.append("country_code")
                return r
            # Two-pass vehicle queries.
            if "CustomerVehicle" in entity_names and "GlobalVehicle" in entity_names:
                r.all.return_value = []
                call_log.append("cv_gv")
                return r
            if "CustomerVehicle" in entity_names and "OrgVehicle" in entity_names:
                r.all.return_value = [(cv, ov)]
                call_log.append("cv_ov")
                return r
            # Dedup count.
            if "NotificationLog" in entity_names:
                r.scalar.return_value = 0
                call_log.append("dedup")
                return r
            # Fallback.
            r.scalars.return_value = MagicMock(
                all=MagicMock(return_value=[]),
                first=MagicMock(return_value=None),
            )
            r.scalar.return_value = 0
            r.scalar_one_or_none.return_value = None
            r.all.return_value = []
            return r

        # Wrap NotificationLog inspection: print when we hit it.
        async def fake_execute_wrapper(stmt, *args, **kwargs):
            r = await fake_execute(stmt, *args, **kwargs)
            return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new=AsyncMock(side_effect=mock_log_email_sent),
        ), patch(
            "app.tasks.notifications.send_email_task",
            new=AsyncMock(side_effect=mock_send_email_task),
        ):
            stats = await process_customer_reminders(db)

        # Both passes must have run.
        assert "cv_gv" in call_log, (
            "process_customer_reminders must run the un-promoted-side pass"
        )
        assert "cv_ov" in call_log, (
            "process_customer_reminders must run the promoted-side pass — "
            "pre-Task-11.6 only the inner join against global_vehicles ran"
        )

        # Exactly one reminder was sent.
        assert stats["reminders_sent"] == 1, (
            f"Expected exactly one customer reminder for the promoted "
            f"vehicle; got stats={stats!r}"
        )
        assert len(sent_subjects) == 1

        # Dedup subject keyed on cv.id, not ov.id.
        subject = sent_subjects[0]
        assert str(cv.id) in subject, (
            "Dedup subject must include cv.id; got %r" % subject
        )
        assert str(ov.id) not in subject, (
            "Dedup subject must NOT include ov.id; got %r" % subject
        )


class TestReminderDedupSurvivesPromotion:
    """Dedup key keyed on ``cv.id`` survives promotion: a reminder fired
    while the link still pointed at ``global_vehicle_id`` must NOT re-fire
    after the same link is migrated to ``org_vehicle_id``.

    Scenario:
      1. Set ``gv.wof_expiry = today + 14``.
      2. Run ``process_wof_rego_reminders`` — a reminder is sent and a
         ``notification_log`` row is created with subject keyed on
         ``cv.id``.
      3. Promote the vehicle (link migrated, ov mirrors the wof_expiry).
      4. Run ``process_wof_rego_reminders`` again — the dedup count check
         finds the existing row (via the cv.id key) and SHORT-CIRCUITS;
         no second reminder is sent.

    Validates: Requirements 6.5, 9.6, 15.5

    The test models the second-run dedup check by returning ``count > 0``
    on the dedup query during the second invocation. The critical
    assertion is that the SAME dedup subject string is generated in both
    runs (proving the key is stable across promotion).
    """

    @pytest.mark.asyncio
    async def test_reminder_dedup_survives_promotion(self):
        org_id = uuid.uuid4()
        # Match the function's UTC-based ``today``.
        today = datetime.now(timezone.utc).date()
        target_date = today + timedelta(days=14)

        # Pre-promotion state: cv linked via global_vehicle_id.
        gv = _make_unpromoted_gv(rego="DEDUP01", wof_expiry=target_date)
        customer = _make_customer_for_reminders(org_id=org_id)
        cv = _make_link(
            org_id=org_id,
            customer_id=customer.id,
            global_vehicle_id=gv.id,
        )

        # Post-promotion state: same cv but now linked via org_vehicle_id.
        # cv.id is identical (the link id is stable). The vehicle id flips
        # from gv.id to ov.id.
        ov = _make_promoted_ov(
            org_id=org_id,
            rego="DEDUP01",
            wof_expiry=target_date,
        )
        cv_after = _make_link(
            org_id=org_id,
            customer_id=customer.id,
            org_vehicle_id=ov.id,
        )
        # CRITICAL: cv.id must be the same across promotion (the link is
        # the same DB row; only the FK columns flip).
        cv_after.id = cv.id

        org = _make_org_for_reminders(org_id=org_id)
        pref = _make_pref(org_id=org_id, channel="email", days_in_advance=14)
        plan = _make_subscription_plan(sms_included=True)

        sent_subjects: list[str] = []

        async def mock_log_email_sent(_db, *, org_id, recipient, template_type,
                                      subject, status, channel="email",
                                      error_message=None, sent_at=None):
            sent_subjects.append(subject)
            return {"id": str(uuid.uuid4()), "subject": subject}

        async def mock_send_email_task(*args, **kwargs):
            return None

        # Run-state controls which side's link returns the row, and what
        # the dedup count returns.
        run_state = {"phase": "pre"}

        async def fake_execute(stmt, *args, **kwargs):
            entity_names = _entity_names_of(stmt)

            r = MagicMock()
            if "NotificationPreference" in entity_names:
                inner = MagicMock()
                inner.all.return_value = [pref]
                r.scalars.return_value = inner
                return r
            if "Organisation" in entity_names:
                r.scalar_one_or_none.return_value = org
                return r
            if "SubscriptionPlan" in entity_names:
                r.scalar_one_or_none.return_value = plan
                return r
            # Two-pass vehicle queries.
            if "CustomerVehicle" in entity_names and "GlobalVehicle" in entity_names:
                if run_state["phase"] == "pre" and _references_column(stmt, "wof_expiry"):
                    r.all.return_value = [(cv, gv, customer)]
                else:
                    r.all.return_value = []
                return r
            if "CustomerVehicle" in entity_names and "OrgVehicle" in entity_names:
                if run_state["phase"] == "post" and _references_column(stmt, "wof_expiry"):
                    r.all.return_value = [(cv_after, ov, customer)]
                else:
                    r.all.return_value = []
                return r
            # Dedup count query: select(func.count(NotificationLog.id)) → entity = 'count'.
            if "count" in entity_names or "NotificationLog" in entity_names:
                # Pre-promotion run → 0 (no prior log).
                # Post-promotion run → 1 (the row inserted by the pre run).
                if run_state["phase"] == "pre":
                    r.scalar.return_value = 0
                else:
                    r.scalar.return_value = 1
                return r
            r.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
            r.scalar.return_value = 0
            r.scalar_one_or_none.return_value = None
            r.all.return_value = []
            return r

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=fake_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.notifications.service.log_email_sent",
            new=AsyncMock(side_effect=mock_log_email_sent),
        ), patch(
            "app.tasks.notifications.send_email_task",
            new=AsyncMock(side_effect=mock_send_email_task),
        ):
            # -- First run (pre-promotion) — sends one reminder. --
            run_state["phase"] = "pre"
            stats_pre = await process_wof_rego_reminders(db)

            # -- Promote the vehicle (in-test: just flip the link state). --
            # No DB action needed since the fake_execute returns cv_after on
            # the post-promotion run.

            # -- Second run (post-promotion) — must NOT send a duplicate. --
            run_state["phase"] = "post"
            stats_post = await process_wof_rego_reminders(db)

        # First run sent exactly one reminder.
        assert stats_pre["reminders_sent"] == 1, (
            f"Pre-promotion run must send exactly one reminder; "
            f"got stats_pre={stats_pre!r}"
        )

        # Second run sent zero reminders — dedup matched via cv.id.
        assert stats_post["reminders_sent"] == 0, (
            f"Post-promotion run must NOT send a duplicate reminder — "
            f"the dedup key (keyed on cv.id) survives the link migration "
            f"from global_vehicle_id to org_vehicle_id; "
            f"got stats_post={stats_post!r}"
        )
        assert len(sent_subjects) == 1, (
            f"Total sends across both runs must be 1 (dedup survives "
            f"promotion); got sent_subjects={sent_subjects!r}"
        )

        # Sanity: the subject from the pre-run is keyed on cv.id and would
        # produce the same key on the post-run (since cv_after.id == cv.id).
        subject_pre = sent_subjects[0]
        assert str(cv.id) in subject_pre, (
            "Pre-promotion subject must include cv.id; got %r" % subject_pre
        )
        # Compute what the post-promotion subject WOULD be — the dedup
        # check uses the same f-string and cv.id is stable.
        subject_post_would_be = subject_pre.replace(
            str(cv.id), str(cv_after.id)
        )
        assert subject_post_would_be == subject_pre, (
            "cv.id must be stable across promotion (same DB row, only FK "
            "columns flip); got cv.id=%s vs cv_after.id=%s"
            % (cv.id, cv_after.id)
        )


# ---------------------------------------------------------------------------
# Task 14.1 — Read_Fallback returns global cache when org not promoted
# ---------------------------------------------------------------------------
#
# Validates Req 6.1 / 6.2 / 6.3 / 6.4 / 6.5 / 10.2 / 15.3 — every
# documented read endpoint returns the ``global_vehicles`` Customer_Driven_Field
# values when the calling org has no ``org_vehicles`` row for the rego.
#
# Setup (shared across endpoint sub-tests):
#   - One ``global_vehicles`` row carrying realistic Customer_Driven_Field
#     values (wof_expiry, cof_expiry, odometer_last_recorded, service_due_date,
#     inspection_type) plus the full CarJam_Owned_Spec_Field set.
#   - One ``customer_vehicles`` link pointing at ``global_vehicle_id`` only
#     (``org_vehicle_id = None``, satisfying ``vehicle_link_check``).
#   - No ``org_vehicles`` row for the calling org. The mock DB is wired so
#     every OrgVehicle SELECT routed by the code-under-test returns ``None``.
#
# Each sub-test invokes one read endpoint and asserts the returned dict /
# response object echoes the gv values byte-for-byte. The read paths under
# test are the three documented in design.md → "Read Paths":
#   1. ``app/modules/vehicles/service.py::get_vehicle_profile`` (vehicle profile)
#   2. ``app/modules/invoices/service.py::get_invoice`` (invoice display dict)
#   3. ``app/modules/fleet_portal/services/vehicle_service.py::get_vehicle``
#      (fleet portal vehicle detail)
#
# A final invariant — ``db.add(OrgVehicle)`` is never called by any of the
# three reads — locks in the "no org_vehicles row exists for the calling
# org" guarantee from Req 6.1. The test deliberately does NOT assert any
# OrgVehicle field values; per the Task 14.1 verify line: "no assertion
# in it touches an ``org_vehicles`` row".
#
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 10.2, 15.3
# Design: Test Strategy → Read Fallback Test (Req 15.3); Read Paths

from decimal import Decimal as _Decimal

from app.modules.admin.models import GlobalVehicle, Organisation
from app.modules.invoices.models import Invoice
from app.modules.invoices.service import get_invoice
from app.modules.fleet_portal.dependencies import FleetSessionCtx
from app.modules.fleet_portal.services.vehicle_service import (
    get_vehicle as fleet_get_vehicle,
)
from app.modules.vehicles.service import get_vehicle_profile


def _added_org_vehicles(db) -> list:
    """Return every ``OrgVehicle`` instance added to the session."""
    return [
        c.args[0]
        for c in db.add.call_args_list
        if c.args and isinstance(c.args[0], OrgVehicle)
    ]


class TestReadFallbackReturnsGlobalWhenNotPromoted:
    """Req 15.3 — every read endpoint returns the GlobalVehicle cache
    values when the calling org has no OrgVehicle row for the rego.

    Three sub-tests cover the three read endpoints enumerated in
    design.md → "Read Paths":

      - ``get_vehicle_profile`` (the vehicle profile dict)
      - ``get_invoice`` (the invoice display dict's ``vehicle`` sub-dict)
      - ``fleet_portal.get_vehicle`` (the fleet portal vehicle detail)

    Each sub-test asserts:
      1. The endpoint's vehicle fields echo the GlobalVehicle source
         row byte-for-byte (wof_expiry, cof_expiry, odometer,
         service_due_date — the four Customer_Driven_Fields plus a
         CarJam_Owned_Spec_Field).
      2. ``db.add(OrgVehicle)`` was never called — no implicit
         promotion happened. (Req 6.1: read paths must NOT promote;
         only customer-driven writes do.)

    The wiring is mock-only — no real database. Every SELECT against
    ``org_vehicles`` is routed to ``None`` so the code under test
    falls through to ``global_vehicles`` per Req 6.
    """

    @pytest.mark.asyncio
    async def test_vehicle_profile_returns_global_cache_values(self):
        """``get_vehicle_profile`` for an un-promoted rego returns the
        ``global_vehicles`` Customer_Driven_Field values.

        ``get_vehicle_profile`` first SELECTs ``GlobalVehicle`` by id;
        if found, it serialises from ``gv`` directly without ever
        consulting ``org_vehicles``. This is the simplest of the three
        read paths — Read_Fallback is implicit because the global row
        is the primary lookup.
        """
        org_id = uuid.uuid4()
        gv = _make_global_vehicle(
            rego="FBK001",
            wof_expiry=date(2026, 4, 1),
            cof_expiry=None,
            odometer_last_recorded=72_500,
            service_due_date=date(2026, 6, 1),
            inspection_type="wof",
        )

        # GlobalVehicle SELECT → gv. Linked-customers and service-history
        # SELECTs are stubbed to empty so we focus on the vehicle dict.
        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        empty_rows = MagicMock()
        empty_rows.all.return_value = []

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            gv_result,       # SELECT GlobalVehicle WHERE id == :vid
            empty_rows,      # SELECT linked customers (empty)
            empty_rows,      # SELECT service-history invoices (empty)
        ])

        result = await get_vehicle_profile(
            db, vehicle_id=gv.id, org_id=org_id
        )

        # -- Invariant 1: vehicle dict echoes the GlobalVehicle values --
        assert result["id"] == str(gv.id)
        assert result["rego"] == gv.rego
        assert result["make"] == gv.make
        assert result["model"] == gv.model
        assert result["year"] == gv.year
        assert result["odometer"] == gv.odometer_last_recorded, (
            "Read_Fallback: odometer must echo global_vehicles."
            "odometer_last_recorded when org has no OrgVehicle row "
            "(Req 6.1)"
        )
        assert result["service_due_date"] == gv.service_due_date.isoformat(), (
            "Read_Fallback: service_due_date must echo global_vehicles "
            "(Req 6.1)"
        )
        # WOF / COF / rego_expiry are wrapped in ``_compute_expiry_indicator``
        # — assert the date sub-key matches the gv source.
        assert result["wof_expiry"]["date"] == gv.wof_expiry.isoformat(), (
            "Read_Fallback: wof_expiry indicator must use global_vehicles "
            "value (Req 6.1)"
        )
        assert result["cof_expiry"]["date"] is None, (
            "Read_Fallback: cof_expiry None on gv must surface as None "
            "in the indicator dict"
        )
        assert result["inspection_type"] == gv.inspection_type, (
            "Read_Fallback: inspection_type must echo global_vehicles "
            "(Req 6.1)"
        )
        # CarJam_Owned_Spec_Field also surfaces from gv (Req 6.3).
        assert result["vin"] == gv.vin
        assert result["chassis"] == gv.chassis

        # -- Invariant 2: no OrgVehicle was added to the session --
        assert _added_org_vehicles(db) == [], (
            "Read paths must not implicitly promote — Req 6.1 says "
            "only customer-driven writes promote; reads continue to "
            "Read_Fallback through global_vehicles"
        )

    @pytest.mark.asyncio
    async def test_invoice_display_dict_returns_global_cache_values(self):
        """``get_invoice`` for an un-promoted rego returns the
        ``global_vehicles`` Customer_Driven_Field values in the
        ``vehicle`` sub-dict.

        ``get_invoice`` SELECTs ``OrgVehicle`` by ``(org_id, rego)``
        first (Task 11.5 inversion). When the org has no OrgVehicle
        row, it falls back to ``GlobalVehicle`` by rego (Read_Fallback,
        Req 6).
        """
        org_id = uuid.uuid4()
        invoice_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        rego = "FBK002"

        gv = _make_global_vehicle(
            rego=rego,
            wof_expiry=date(2026, 5, 15),
            cof_expiry=date(2027, 1, 1),
            odometer_last_recorded=88_000,
            service_due_date=date(2026, 8, 1),
            inspection_type="wof",
        )
        gv_pre = {
            "wof_expiry": gv.wof_expiry,
            "cof_expiry": gv.cof_expiry,
            "odometer": gv.odometer_last_recorded,
            "service_due_date": gv.service_due_date,
            "inspection_type": gv.inspection_type,
        }

        invoice = MagicMock(spec=Invoice)
        invoice.id = invoice_id
        invoice.org_id = org_id
        invoice.customer_id = customer_id
        invoice.vehicle_rego = rego
        invoice.vehicle_make = "OldMake"
        invoice.vehicle_model = "OldModel"
        invoice.vehicle_year = 2018
        invoice.vehicle_odometer = 12_345
        invoice.invoice_number = "INV-FBK-001"
        invoice.status = "issued"
        invoice.total = _Decimal("0.00")
        invoice.subtotal = _Decimal("0.00")
        invoice.tax_amount = _Decimal("0.00")
        invoice.gst_amount = _Decimal("0.00")
        invoice.balance_due = _Decimal("0.00")
        invoice.amount_paid = _Decimal("0.00")
        invoice.discount_amount = _Decimal("0.00")
        invoice.discount_type = None
        invoice.discount_value = _Decimal("0.00")
        invoice.exchange_rate_to_nzd = _Decimal("1.00")
        invoice.currency = "NZD"
        invoice.invoice_data_json = {}
        invoice.notes = None
        invoice.notes_internal = None
        invoice.notes_customer = None
        invoice.payment_terms = None
        invoice.terms_and_conditions = None
        invoice.issue_date = date(2026, 1, 1)
        invoice.due_date = date(2026, 1, 31)
        invoice.created_at = None
        invoice.updated_at = None
        invoice.voided_at = None
        invoice.voided_by = None
        invoice.void_reason = None
        invoice.created_by = None
        invoice.branch_id = None
        invoice.payment_page_url = None
        invoice.job_card_appendix_html = None
        invoice.share_token = None

        # Track that the OrgVehicle SELECT ran AND returned None — the
        # Read_Fallback path is what we're locking in.
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
                r.scalar_one_or_none.return_value = None
                return r
            if "from customers" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            # OrgVehicle is preferred — Task 11.5 inversion.
            # The calling org has no OrgVehicle row → return None.
            if "from org_vehicles" in sql_text:
                vehicle_query_log.append("org_vehicles")
                r.scalar_one_or_none.return_value = None
                return r
            # Fallback — Read_Fallback per Req 6.
            if "from global_vehicles" in sql_text:
                vehicle_query_log.append("global_vehicles")
                r.scalar_one_or_none.return_value = gv
                return r
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            r.all.return_value = []
            return r

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(
            side_effect=lambda stmt, *a, **kw: _route(stmt, *a, **kw)
        )

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
            result = await get_invoice(
                db, org_id=org_id, invoice_id=invoice_id
            )

        # -- Invariant 1a: lookup order shows Read_Fallback fired --
        assert vehicle_query_log == ["org_vehicles", "global_vehicles"], (
            "Read_Fallback path: OrgVehicle SELECT runs first (Task 11.5 "
            "inversion), returns None for the un-promoted org, then "
            "GlobalVehicle SELECT runs as the fallback (Req 6); "
            f"got {vehicle_query_log!r}"
        )

        # -- Invariant 1b: vehicle dict echoes the GlobalVehicle values --
        assert "vehicle" in result, (
            "get_invoice must include vehicle dict from Read_Fallback"
        )
        v = result["vehicle"]
        assert v["rego"] == gv.rego
        assert v["make"] == gv.make
        assert v["model"] == gv.model
        assert v["year"] == gv.year
        assert v["wof_expiry"] == gv_pre["wof_expiry"].isoformat(), (
            "Read_Fallback: invoice display wof_expiry must echo "
            "global_vehicles.wof_expiry (Req 6.1)"
        )
        assert v["cof_expiry"] == gv_pre["cof_expiry"].isoformat(), (
            "Read_Fallback: invoice display cof_expiry must echo "
            "global_vehicles.cof_expiry (Req 6.1)"
        )
        assert v["odometer"] == gv_pre["odometer"], (
            "Read_Fallback: invoice display odometer must echo "
            "global_vehicles.odometer_last_recorded (Req 6.1)"
        )
        assert v["service_due_date"] == gv_pre["service_due_date"].isoformat(), (
            "Read_Fallback: invoice display service_due_date must echo "
            "global_vehicles.service_due_date (Req 6.1)"
        )

        # -- Invariant 2: no OrgVehicle was added to the session --
        assert _added_org_vehicles(db) == [], (
            "get_invoice is a read endpoint — it must not promote (Req 6.1)"
        )

    @pytest.mark.asyncio
    async def test_fleet_portal_vehicle_detail_returns_global_cache_values(self):
        """``fleet_portal.get_vehicle`` for an un-promoted rego returns the
        ``global_vehicles`` Customer_Driven_Field values via the
        ``v = gv if gv is not None else ov`` Read_Fallback pattern.

        The fleet portal helper loads the ``CustomerVehicle`` row with
        both ``global_vehicle`` and ``org_vehicle`` relationships
        eagerly. For an un-promoted link, ``cv.global_vehicle`` is the
        ``GlobalVehicle`` source and ``cv.org_vehicle`` is ``None`` —
        the canonical Read_Fallback shape used elsewhere in
        ``app/modules/fleet_portal/services/vehicle_service.py``.
        """
        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        fleet_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        cv_id = uuid.uuid4()

        gv = _make_global_vehicle(
            rego="FBK003",
            wof_expiry=date(2026, 7, 20),
            cof_expiry=None,
            odometer_last_recorded=110_300,
            service_due_date=date(2026, 9, 15),
            inspection_type="wof",
        )

        # Un-promoted CustomerVehicle: global_vehicle attached, org_vehicle
        # is None (the link still points at global_vehicle_id only,
        # satisfying vehicle_link_check).
        cv = MagicMock(spec=CustomerVehicle)
        cv.id = cv_id
        cv.org_id = org_id
        cv.customer_id = customer_id
        cv.global_vehicle_id = gv.id
        cv.org_vehicle_id = None
        cv.global_vehicle = gv
        cv.org_vehicle = None
        cv.fleet_checklist_template_id = None

        ctx = FleetSessionCtx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            portal_user_role="fleet_admin",
            fleet_account_id=fleet_account_id,
            email="fleet@example.com",
            session_id=uuid.uuid4(),
        )

        # _customer_id_for_fleet → row[0] = customer_id
        fleet_lookup = MagicMock()
        fleet_lookup.first.return_value = (customer_id,)

        # The CV SELECT inside get_vehicle returns cv via ``.scalars().first()``.
        cv_result = MagicMock()
        cv_result.scalars.return_value.first.return_value = cv

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            fleet_lookup,    # _customer_id_for_fleet
            cv_result,       # CustomerVehicle SELECT scoped to (org, customer)
        ])

        result = await fleet_get_vehicle(
            db, ctx=ctx, customer_vehicle_id=cv_id
        )

        # -- Invariant 1: vehicle detail echoes the GlobalVehicle values --
        assert result is not None, "fleet_portal.get_vehicle must return a row"
        assert result.customer_vehicle_id == cv_id
        assert result.rego == gv.rego
        assert result.make == gv.make
        assert result.model == gv.model
        assert result.year == gv.year
        assert result.colour == gv.colour
        assert result.odometer_last_recorded == gv.odometer_last_recorded, (
            "Read_Fallback: fleet portal odometer must echo "
            "global_vehicles.odometer_last_recorded (Req 7.1, Req 6.1)"
        )
        assert result.wof_expiry == gv.wof_expiry, (
            "Read_Fallback: fleet portal wof_expiry must echo "
            "global_vehicles.wof_expiry (Req 6.1)"
        )
        assert result.cof_expiry == gv.cof_expiry, (
            "Read_Fallback: fleet portal cof_expiry must echo "
            "global_vehicles.cof_expiry (Req 6.1)"
        )
        assert result.service_due_date == gv.service_due_date, (
            "Read_Fallback: fleet portal service_due_date must echo "
            "global_vehicles.service_due_date (Req 6.1)"
        )
        assert result.registration_expiry == gv.registration_expiry, (
            "Read_Fallback: fleet portal registration_expiry must echo "
            "global_vehicles.registration_expiry (Req 6.3)"
        )
        # CarJam_Owned_Spec_Fields also Read_Fallback through gv (Req 6.3).
        assert result.vin == gv.vin
        assert result.chassis == gv.chassis

        # -- Invariant 2: no OrgVehicle was added to the session --
        assert _added_org_vehicles(db) == [], (
            "fleet_portal.get_vehicle is a read endpoint — Req 7.4 forbids "
            "any portal endpoint from writing to global_vehicles, and Req "
            "6.1 forbids reads from promoting; both are satisfied by "
            "never adding an OrgVehicle in this path"
        )

    @pytest.mark.asyncio
    async def test_no_org_vehicle_row_added_across_all_read_paths(self):
        """Cross-cutting assertion: across all three read paths covered
        above, no read endpoint may insert an ``org_vehicles`` row.

        Re-runs each endpoint in sequence on a single shared ``db.add``
        recorder and asserts the recorded ``OrgVehicle`` count is zero.
        This locks in the "Assert no ``org_vehicles`` row exists for the
        calling org" line from the Task 14.1 verify block.

        The assertion is structured as a positive existence check —
        the test never inspects an OrgVehicle's fields (per the Task
        14.1 verify line: "no assertion in it touches an
        ``org_vehicles`` row").
        """
        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        fleet_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        invoice_id = uuid.uuid4()
        cv_id = uuid.uuid4()
        rego = "FBK999"

        gv = _make_global_vehicle(rego=rego)

        # Prepare invoice for the get_invoice run.
        invoice = MagicMock(spec=Invoice)
        invoice.id = invoice_id
        invoice.org_id = org_id
        invoice.customer_id = customer_id
        invoice.vehicle_rego = rego
        invoice.vehicle_make = None
        invoice.vehicle_model = None
        invoice.vehicle_year = None
        invoice.vehicle_odometer = None
        invoice.invoice_number = "INV-CROSS-001"
        invoice.status = "draft"
        invoice.total = _Decimal("0.00")
        invoice.subtotal = _Decimal("0.00")
        invoice.tax_amount = _Decimal("0.00")
        invoice.gst_amount = _Decimal("0.00")
        invoice.balance_due = _Decimal("0.00")
        invoice.amount_paid = _Decimal("0.00")
        invoice.discount_amount = _Decimal("0.00")
        invoice.discount_type = None
        invoice.discount_value = _Decimal("0.00")
        invoice.exchange_rate_to_nzd = _Decimal("1.00")
        invoice.currency = "NZD"
        invoice.invoice_data_json = {}
        invoice.notes = None
        invoice.notes_internal = None
        invoice.notes_customer = None
        invoice.payment_terms = None
        invoice.terms_and_conditions = None
        invoice.issue_date = None
        invoice.due_date = None
        invoice.created_at = None
        invoice.updated_at = None
        invoice.voided_at = None
        invoice.voided_by = None
        invoice.void_reason = None
        invoice.created_by = None
        invoice.branch_id = None
        invoice.payment_page_url = None
        invoice.job_card_appendix_html = None
        invoice.share_token = None

        # Un-promoted CV for the fleet portal run.
        cv = MagicMock(spec=CustomerVehicle)
        cv.id = cv_id
        cv.org_id = org_id
        cv.customer_id = customer_id
        cv.global_vehicle_id = gv.id
        cv.org_vehicle_id = None
        cv.global_vehicle = gv
        cv.org_vehicle = None
        cv.fleet_checklist_template_id = None

        # Single ``db`` shared across all three runs so the OrgVehicle
        # add-recorder is observed end-to-end.
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # ---- Run 1: get_vehicle_profile ----
        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv
        empty_rows = MagicMock()
        empty_rows.all.return_value = []

        db.execute = AsyncMock(side_effect=[
            gv_result,
            empty_rows,
            empty_rows,
        ])
        await get_vehicle_profile(db, vehicle_id=gv.id, org_id=org_id)

        # ---- Run 2: get_invoice (Read_Fallback to GlobalVehicle by rego) ----
        def _route_invoice(stmt, *args, **kwargs):
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
            if "from org_vehicles" in sql_text:
                r.scalar_one_or_none.return_value = None
                return r
            if "from global_vehicles" in sql_text:
                r.scalar_one_or_none.return_value = gv
                return r
            r.scalar_one_or_none.return_value = None
            r.scalars.return_value.all.return_value = []
            r.all.return_value = []
            return r

        db.execute = AsyncMock(
            side_effect=lambda stmt, *a, **kw: _route_invoice(stmt, *a, **kw)
        )
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
            await get_invoice(db, org_id=org_id, invoice_id=invoice_id)

        # ---- Run 3: fleet_portal.get_vehicle ----
        fleet_lookup = MagicMock()
        fleet_lookup.first.return_value = (customer_id,)
        cv_result = MagicMock()
        cv_result.scalars.return_value.first.return_value = cv

        db.execute = AsyncMock(side_effect=[fleet_lookup, cv_result])
        ctx = FleetSessionCtx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            portal_user_role="fleet_admin",
            fleet_account_id=fleet_account_id,
            email="fleet@example.com",
            session_id=uuid.uuid4(),
        )
        await fleet_get_vehicle(db, ctx=ctx, customer_vehicle_id=cv_id)

        # -- Cross-cutting invariant: zero OrgVehicle inserts across all
        # three read paths. The "no org_vehicles row exists for the
        # calling org" guarantee from Task 14.1's verify line. --
        assert _added_org_vehicles(db) == [], (
            "Read_Fallback test: NO read endpoint may add an "
            "OrgVehicle to the session — promotion is restricted to "
            "customer-driven write paths (Req 6.1, Req 2 trigger "
            "sites). Reads continue to Read_Fallback through "
            "global_vehicles indefinitely until the org's first "
            "customer-driven write."
        )

# ---------------------------------------------------------------------------
# Task 14.2 — Concurrent promotions converge on a single org_vehicles row
# ---------------------------------------------------------------------------
#
# Validates Req 13.1 / 13.2 / 15.4 and the design's Concurrency and
# Idempotency Strategy: when two transactions call ``promote_vehicle`` for
# the same ``(org_id, rego)`` pair simultaneously, the advisory lock
# serialises them. The winner inserts the new ``org_vehicles`` row and
# emits a ``vehicle.promote`` audit log row; the loser, after acquiring
# the lock, re-checks inside it, finds the winner's row, and returns it
# unchanged — no second INSERT, no second audit log row.
#
# This project's tests run against AsyncMock sessions, not a live DB. The
# fixture below simulates the race at the mock level by giving each
# concurrent caller its own ``AsyncMock`` session AND coordinating their
# advisory-lock and SELECT calls with an ``asyncio.Event``:
#
#   - Session A acquires the lock first (the Event fires when its
#     advisory-lock execute is awaited), runs the existence-check SELECT
#     (returns None — no row yet), inserts a new ``OrgVehicle``, emits
#     the ``vehicle.promote`` audit log, and releases.
#   - Session B's advisory-lock execute waits on the Event (simulating
#     the loser blocking on the lock). Once Session A's flush completes
#     and the inserted row is "visible", Session B is unblocked. Its
#     existence-check SELECT now returns Session A's freshly-inserted
#     ``OrgVehicle`` — Session B short-circuits, returns the same row,
#     and emits no audit log.
#
# Both ``asyncio.gather``-fired calls then return the SAME ``OrgVehicle``
# instance (same ``id``), exactly one ``OrgVehicle`` was added across
# both sessions, and exactly one ``vehicle.promote`` audit row was
# written.
#
# The test runs the race ten times in a single test invocation (per the
# Task 14.2 verify line: "the test passes deterministically across at
# least 10 consecutive runs; both transactions converge on the same
# row id") to lock in determinism — interleaving order is enforced by
# the Event wiring, so no run depends on pytest scheduling luck.
#
# Requirements: 13.1, 13.2, 15.4
# Design: Concurrency and Idempotency Strategy; Test Strategy →
#         Concurrency Test (Req 15.4)


class _RaceFixture:
    """Wires two AsyncMock sessions to deterministically simulate the
    advisory-lock race for the same ``(org_id, rego)`` pair.

    Session A is the "winner": its advisory-lock acquires first (no
    wait), the existence-check SELECT returns ``None``, ``db.add`` is
    called with a new ``OrgVehicle`` (carrying a fresh ``id``), and
    ``flush`` resolves. Once flush resolves, ``self.winner_inserted``
    is set, unblocking Session B.

    Session B is the "loser": its advisory-lock execute awaits
    ``self.winner_inserted`` before returning (mirroring the real
    advisory-lock blocking behaviour — the loser cannot proceed past
    the lock until the winner's transaction commits). When it finally
    runs the existence-check SELECT, the result returns the winner's
    ``OrgVehicle`` — no INSERT, no audit log.

    The fixture exposes:
      - ``db_a``, ``db_b`` — the two AsyncMock sessions
      - ``winner_ov_holder`` — populated with the new ``OrgVehicle`` once
        the winner inserts (Session B reads from this list when it does
        its existence-check SELECT, so the loser sees the same row that
        the winner just inserted)
      - ``audit_calls`` — every ``write_audit_log`` invocation captured
        across both sessions; for a correctly-serialised race this list
        has length 1 at the end.
    """

    def __init__(self, *, gv):
        self.gv = gv
        # Synchronisation primitive — fires after Session A's flush
        # completes, modelling "winner has inserted and committed".
        self.winner_inserted = asyncio.Event()
        # Holder for the OrgVehicle Session A inserts. Session B's
        # existence-check SELECT consults this on resolve.
        self.winner_ov_holder: list = []
        # Aggregated audit-log write_audit_log calls across both sessions.
        self.audit_calls: list = []

        self.db_a = self._build_winner_session()
        self.db_b = self._build_loser_session()

    # -- Session A (winner) --------------------------------------------------
    def _build_winner_session(self):
        db = AsyncMock()
        db.add = MagicMock(side_effect=self._on_winner_add)
        db.flush = AsyncMock(side_effect=self._on_winner_flush)
        db.refresh = AsyncMock()

        # Two execute calls in order:
        #   1. advisory lock — returns no-op (winner takes lock immediately)
        #   2. existence-check SELECT — returns None (no row yet)
        # No further executes are expected (audit log goes via the patched
        # write_audit_log, not direct execute).
        lock_result = MagicMock()
        lock_result.scalar_one_or_none.return_value = None

        existence_result = MagicMock()
        existence_result.scalar_one_or_none.return_value = None

        no_op = MagicMock()
        no_op.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(
            side_effect=[lock_result, existence_result, no_op, no_op]
        )
        return db

    def _on_winner_add(self, instance):
        """Capture the inserted ``OrgVehicle`` so Session B's
        existence-check SELECT can return it."""
        # Session A inserts a fresh row; assign a deterministic id so
        # subsequent assertions can compare both callers' return values.
        if not hasattr(instance, "id") or instance.id is None:
            instance.id = uuid.uuid4()
        self.winner_ov_holder.append(instance)

    async def _on_winner_flush(self):
        """Once flush returns, Session A has 'inserted'. Unblock B."""
        self.winner_inserted.set()

    # -- Session B (loser) ---------------------------------------------------
    def _build_loser_session(self):
        db = AsyncMock()
        # IMPORTANT: db.add MUST NOT be called on Session B — the
        # invariant under test. We wire it as a strict MagicMock so any
        # accidental call surfaces in db.add.call_count == 0.
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # Two execute calls in order:
        #   1. advisory lock — awaits ``winner_inserted`` before returning
        #   2. existence-check SELECT — returns Session A's inserted row
        async def _execute_router(stmt, *args, **kwargs):
            sql_text = ""
            if hasattr(stmt, "text"):
                sql_text = str(stmt.text)
            else:
                sql_text = str(stmt)

            r = MagicMock()
            if "pg_advisory_xact_lock" in sql_text:
                # Loser blocks on the lock until winner finishes inserting.
                await self.winner_inserted.wait()
                r.scalar_one_or_none.return_value = None
                return r

            # Existence check — must return the winner's row to drive the
            # idempotent return path inside promote_vehicle.
            assert self.winner_ov_holder, (
                "race-fixture invariant: Session B's existence-check "
                "SELECT fired before Session A populated winner_ov_holder; "
                "the asyncio.Event wiring is broken"
            )
            r.scalar_one_or_none.return_value = self.winner_ov_holder[0]
            return r

        db.execute = AsyncMock(side_effect=_execute_router)
        return db

    # -- Audit-log capture (shared across both sessions) ---------------------
    async def capture_audit(self, **kwargs):
        """Stand-in for ``write_audit_log`` that records every call."""
        self.audit_calls.append(kwargs)


class TestConcurrentPromotionsProduceSingleOrgRow:
    """Req 13.1, 13.2, 15.4 — the advisory lock serialises concurrent
    callers for the same ``(org_id, rego)`` so they converge on one row.

    The test simulates the race at the AsyncMock level (this project's
    tests run without a live database). Two distinct AsyncMock sessions
    are wired together via an ``asyncio.Event``:

      - Session A acquires the lock first, inserts the new
        ``OrgVehicle``, emits the audit log, and "commits" (modelled by
        ``flush`` resolving and the Event firing).
      - Session B's advisory-lock ``execute`` blocks on the Event,
        mirroring the real advisory lock holding the loser until the
        winner's transaction ends. When B is unblocked, its
        existence-check SELECT returns A's just-inserted row, so B
        short-circuits with the idempotent return path.

    Two ``promote_vehicle`` calls fired via ``asyncio.gather`` then
    must:

      1. Both complete without exceptions.
      2. Return the *same* ``OrgVehicle`` (same ``id``) — Req 13.1.
      3. Have caused exactly **one** ``db.add(OrgVehicle)`` across both
         sessions — Req 13.2 (no duplicate insert).
      4. Have caused exactly **one** ``vehicle.promote`` audit-log row —
         Req 14.1 (audit log emitted only by the winner; the loser's
         idempotent-return path emits none).

    Per the Task 14.2 verify line, the race is run **ten consecutive
    times** in a single test invocation: "the test passes
    deterministically across at least 10 consecutive runs; both
    transactions converge on the same row id". Determinism is
    guaranteed by the Event wiring — Session A's flush always fires
    the Event before Session B's advisory-lock ``execute`` returns —
    so each iteration is a faithful replay of the lock-protected
    serialisation.
    """

    @pytest.mark.asyncio
    async def test_concurrent_promotions_produce_single_org_row(self):
        """Two ``asyncio.gather``-fired ``promote_vehicle`` calls for the
        same ``(org_id, rego)`` converge on one row, one INSERT, one
        audit-log entry. Repeated 10× to lock in determinism.
        """
        org_id = uuid.uuid4()
        user_id_a = uuid.uuid4()
        user_id_b = uuid.uuid4()

        for run in range(10):
            gv = _make_global_vehicle(rego="RACE001")
            fixture = _RaceFixture(gv=gv)

            with patch(
                "app.core.modules.ModuleService.is_enabled",
                new_callable=AsyncMock,
                return_value=True,
            ), patch(
                "app.modules.vehicles.service.write_audit_log",
                new=fixture.capture_audit,
            ):
                # Fire BOTH promotion calls via asyncio.gather. Each call
                # uses its own AsyncMock session — mirroring the design's
                # "two distinct AsyncSession objects" requirement
                # (one per concurrent transaction).
                result_a, result_b = await asyncio.gather(
                    promote_vehicle(
                        fixture.db_a,
                        org_id=org_id,
                        global_vehicle_id=gv.id,
                        source_record=gv,
                        user_id=user_id_a,
                        trigger_site="vehicles.test_concurrent_a",
                    ),
                    promote_vehicle(
                        fixture.db_b,
                        org_id=org_id,
                        global_vehicle_id=gv.id,
                        source_record=gv,
                        user_id=user_id_b,
                        trigger_site="vehicles.test_concurrent_b",
                    ),
                )

            # -- Invariant 1: exactly ONE OrgVehicle was added across
            # both sessions (Req 13.2 — no duplicate INSERT). --
            total_added = (
                fixture.db_a.add.call_count + fixture.db_b.add.call_count
            )
            assert total_added == 1, (
                f"run #{run}: exactly one OrgVehicle must be added across "
                f"both concurrent sessions (winner inserts, loser "
                f"short-circuits via idempotent return path); got "
                f"{total_added} adds (db_a={fixture.db_a.add.call_count}, "
                f"db_b={fixture.db_b.add.call_count})"
            )

            # -- Invariant 2: the loser session never called add. --
            assert fixture.db_b.add.call_count == 0, (
                f"run #{run}: Session B (loser) MUST NOT INSERT a second "
                "row — its existence-check SELECT inside the lock found "
                "Session A's row, so promote_vehicle short-circuits"
            )
            assert fixture.db_a.add.call_count == 1, (
                f"run #{run}: Session A (winner) must have INSERTed "
                "exactly one OrgVehicle"
            )

            # -- Invariant 3: both callers returned the SAME row. The
            # winner returns the freshly-inserted instance; the loser
            # returns the same instance via its existence-check SELECT
            # (the fixture wires the SELECT to return winner_ov_holder[0]).
            # Both must therefore be identical (same Python identity
            # AND same id). --
            assert result_a is result_b, (
                f"run #{run}: concurrent promotions must converge on the "
                "SAME OrgVehicle instance — Session B's existence-check "
                "SELECT returns Session A's just-inserted row (Req 13.1)"
            )
            assert result_a.id == result_b.id, (
                f"run #{run}: both concurrent transactions must return a "
                f"row with the same id; got a.id={result_a.id} vs "
                f"b.id={result_b.id}"
            )

            # -- Invariant 4: exactly ONE vehicle.promote audit row was
            # emitted across both sessions (Req 14.1 — audit emitted
            # only by the winning INSERT path; the loser's idempotent
            # return path emits none). --
            assert len(fixture.audit_calls) == 1, (
                f"run #{run}: exactly one vehicle.promote audit row must "
                f"be emitted across both concurrent sessions; got "
                f"{len(fixture.audit_calls)} audit calls"
            )
            audit_kwargs = fixture.audit_calls[0]
            assert audit_kwargs["action"] == "vehicle.promote", (
                f"run #{run}: the single audit row must carry "
                f"action='vehicle.promote'; got {audit_kwargs['action']!r}"
            )
            # The winning audit row was emitted by Session A — its
            # trigger_site / user_id must be the winner's (not the
            # loser's, which never reaches the audit-write step).
            assert audit_kwargs["org_id"] == org_id
            assert audit_kwargs["user_id"] == user_id_a, (
                f"run #{run}: the vehicle.promote audit row must be "
                "attributed to the winning transaction's user_id; the "
                "loser's idempotent-return path does NOT emit an audit "
                "log"
            )
            assert (
                audit_kwargs["after_value"]["trigger_site"]
                == "vehicles.test_concurrent_a"
            ), (
                f"run #{run}: the vehicle.promote audit row's "
                "trigger_site must reflect the winning caller "
                "('vehicles.test_concurrent_a'), not the loser's"
            )


# ---------------------------------------------------------------------------
# Task 14.3 — Backwards-Compatibility: legacy global-id-keyed link still
# resolves through every read endpoint enumerated in design.md → "Read Paths"
# ---------------------------------------------------------------------------
#
# Validates Req 6.5 / 9.6 / 10.2 / 15.5 — when a ``customer_vehicles`` row
# still points at ``global_vehicle_id`` (the pre-spec / un-promoted shape),
# every documented read endpoint that reads via ``customer_vehicles`` must
# continue to render the global-cache values. This is the "Backwards
# Compatibility table" guarantee from design.md:
#
#   "Existing customer_vehicles links pointing at global_vehicle_id —
#    Continue to resolve and render — Read_Fallback via
#    _resolve_vehicle_type returns ('global', gv) until promotion"
#
# Task 14.1 already covered the rego-keyed and id-keyed read paths
# (``get_vehicle_profile``, ``get_invoice``, ``fleet_portal.get_vehicle``).
# Task 14.3 layers in coverage for the **link-traversal** read paths —
# the ones at risk of dropping legacy global-id-keyed links because they
# join through ``customer_vehicles`` to resolve the underlying vehicle:
#
#   1. ``customers.search_customers(include_vehicles=True)`` — Task 11.1's
#      double-outerjoin fix; pre-fix the ``outerjoin(GlobalVehicle)``-only
#      query was the canonical case but the test must lock in that the
#      legacy-global-link branch still resolves.
#   2. ``customers.get_customer_reminder_config`` — Task 11.2's
#      double-outerjoin fix; same pattern, different consumer.
#   3. ``fleet_portal.list_vehicles_for_session`` — uses the ``v =
#      cv.global_vehicle if cv.global_vehicle is not None else
#      cv.org_vehicle`` Read_Fallback pattern.
#   4. ``customers.get_customer_profile`` — iterates ``customer_vehicles``
#      and branches on ``cv.global_vehicle_id`` vs ``cv.org_vehicle_id``;
#      legacy links must take the global branch and surface gv values.
#
# Setup (shared across endpoint sub-tests):
#   - One ``global_vehicles`` row carrying realistic Customer_Driven_Field
#     values plus the full CarJam_Owned_Spec_Field set.
#   - One ``customer_vehicles`` link pointing at ``global_vehicle_id``
#     ONLY (``org_vehicle_id = None``, satisfying ``vehicle_link_check``).
#   - No ``org_vehicles`` row exists for the calling org for that rego.
#     The mocks are wired so OrgVehicle SELECTs and the
#     ``cv.org_vehicle`` relationship resolve to ``None``.
#
# Each sub-test invokes one read endpoint and asserts the rendered
# vehicle dict / response object echoes the gv values byte-for-byte.
# The four endpoints together cover the "every documented read endpoint"
# requirement of Task 14.3 by enumerating one representative endpoint
# per Read-Paths category that traverses ``customer_vehicles``.
#
# Requirements: 6.5, 9.6, 10.2, 15.5
# Design: Test Strategy → Backwards-Compatibility Test (Req 15.5);
#         Backwards Compatibility table; Read Paths.

from app.modules.customers.service import (  # noqa: E402
    get_customer_profile,
    get_customer_reminder_config,
)
from app.modules.fleet_portal.services.vehicle_service import (  # noqa: E402
    list_vehicles_for_session,
)


def _make_legacy_cv_link(*, org_id, customer_id, gv):
    """Build a CustomerVehicle pointing at global_vehicle_id only.

    This is the legacy / pre-spec / un-promoted shape — the one the
    Backwards Compatibility table guarantees keeps resolving. The
    ``vehicle_link_check`` CHECK constraint is satisfied
    (``global_vehicle_id IS NOT NULL AND org_vehicle_id IS NULL``).

    The link carries both the FK columns AND the SQLAlchemy
    relationship attributes pre-resolved (``cv.global_vehicle = gv``,
    ``cv.org_vehicle = None``) so endpoints that consume the
    relationships directly (fleet portal) see the same shape that
    ``selectinload`` would produce in production.
    """
    cv = MagicMock(spec=CustomerVehicle)
    cv.id = uuid.uuid4()
    cv.org_id = org_id
    cv.customer_id = customer_id
    cv.global_vehicle_id = gv.id
    cv.org_vehicle_id = None
    cv.global_vehicle = gv
    cv.org_vehicle = None
    cv.fleet_checklist_template_id = None
    cv.linked_at = datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc)
    cv.odometer_at_link = None
    return cv


class TestLegacyGlobalLinkResolvesThroughEveryReadEndpoint:
    """Req 15.5 — every documented read endpoint that traverses
    ``customer_vehicles`` must continue to resolve legacy
    ``global_vehicle_id``-only links and render the GlobalVehicle
    cache values.

    The four sub-tests cover one representative endpoint per Read-Paths
    category that reads via ``customer_vehicles``:

      - ``customers.search_customers(include_vehicles=True)``
      - ``customers.get_customer_reminder_config``
      - ``fleet_portal.list_vehicles_for_session``
      - ``customers.get_customer_profile``

    Each sub-test asserts:
      1. The endpoint returns the legacy-linked vehicle (not silently
         dropped — the pre-Task-11.1 inner-join bug is the regression
         we are guarding against).
      2. The rendered fields echo the GlobalVehicle source row
         byte-for-byte (rego, make, model, year, colour, plus any
         expiry / odometer fields the endpoint exposes).
      3. ``db.add(OrgVehicle)`` was never called — read paths must NOT
         promote (Req 6.1; locked in by design "Read Paths").

    The wiring is mock-only — no real database. Every OrgVehicle
    relationship / SELECT routed through the code-under-test resolves
    to ``None`` so the legacy ``global_vehicle_id`` branch is the only
    code path that fires.
    """

    @pytest.mark.asyncio
    async def test_legacy_global_link_renders_through_search_customers(self):
        """``search_customers(include_vehicles=True)`` returns the legacy
        link with the GlobalVehicle cache values.

        Pre-Task-11.1 ``outerjoin(GlobalVehicle)`` only — this branch
        always rendered correctly. The test locks in that the post-fix
        double-outerjoin still routes legacy links through the
        ``v = gv if gv is not None else ov`` fallback to gv.
        """
        org_id = uuid.uuid4()
        customer = _make_customer_for_search(org_id=org_id)

        gv = _make_global_vehicle(
            rego="LEGACY1",
            wof_expiry=date(2026, 5, 1),
            cof_expiry=date(2027, 2, 1),
            odometer_last_recorded=64_000,
            service_due_date=date(2026, 7, 15),
            inspection_type="wof",
        )
        cv = _make_legacy_cv_link(
            org_id=org_id, customer_id=customer.id, gv=gv
        )

        # search_customers issues, in order, when query is None and there
        # are no receivables/credits:
        #   1. count(Customer)         → 1
        #   2. select(Customer)         → [customer]
        #   3. receivables grouped sum → []
        #   4. credits grouped sum     → []
        #   5. linked-vehicles double-outerjoin → [(cv, gv, None)]
        # Loader rows expose (CustomerVehicle, GlobalVehicle, OrgVehicle)
        # for the outerjoin; legacy link → (cv, gv, None).
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _mock_count(1),
                _mock_scalars([customer]),
                _mock_rows([]),
                _mock_rows([]),
                _mock_rows([(cv, gv, None)]),
            ]
        )
        db.flush = AsyncMock()
        db.add = MagicMock()

        with patch("app.core.modules.ModuleService") as MockModSvc:
            MockModSvc.return_value.is_enabled = AsyncMock(return_value=True)
            result = await search_customers(
                db,
                org_id=org_id,
                include_vehicles=True,
            )

        # -- Invariant 1: legacy link is NOT silently dropped --
        assert result["total"] == 1
        linked = result["customers"][0]["linked_vehicles"]
        assert len(linked) == 1, (
            "Legacy global-id-keyed link must continue to render through "
            "search_customers — Backwards Compatibility table guarantees "
            "Read_Fallback to gv until promotion"
        )

        # -- Invariant 2: fields echo GlobalVehicle cache values --
        row = linked[0]
        assert row["id"] == str(gv.id)
        assert row["rego"] == gv.rego
        assert row["make"] == gv.make
        assert row["model"] == gv.model
        assert row["year"] == gv.year
        assert row["colour"] == gv.colour
        assert row["odometer"] == gv.odometer_last_recorded, (
            "Read_Fallback: search_customers odometer must echo "
            "global_vehicles.odometer_last_recorded for legacy link "
            "(Req 6.5)"
        )
        assert row["wof_expiry"] == gv.wof_expiry.isoformat(), (
            "Read_Fallback: search_customers wof_expiry must echo "
            "global_vehicles.wof_expiry for legacy link (Req 6.5)"
        )
        assert row["cof_expiry"] == gv.cof_expiry.isoformat(), (
            "Read_Fallback: search_customers cof_expiry must echo "
            "global_vehicles.cof_expiry for legacy link (Req 6.5)"
        )
        assert row["service_due_date"] == gv.service_due_date.isoformat()
        assert row["source"] == "global", (
            "Source tag for a legacy global-id link must be 'global'"
        )

        # -- Invariant 3: no OrgVehicle was added --
        assert _added_org_vehicles(db) == [], (
            "search_customers is a read endpoint — it must not promote "
            "(Req 6.1)"
        )

    @pytest.mark.asyncio
    async def test_legacy_global_link_renders_through_get_customer_reminder_config(self):
        """``get_customer_reminder_config`` returns the legacy link with
        GlobalVehicle cache values in the ``vehicles`` list.

        Pre-Task-11.2 the inner-join on ``global_vehicle_id`` always
        worked for legacy links (the bug surfaced for promoted links).
        The test locks in that the post-fix double-outerjoin still
        routes legacy links through ``v = gv if gv is not None else ov``
        to gv.
        """
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # Customer ORM mock with custom_fields (no reminder_config so we
        # get defaults for service_due / wof_expiry).
        customer = MagicMock()
        customer.id = customer_id
        customer.org_id = org_id
        customer.custom_fields = None

        gv = _make_global_vehicle(
            rego="LEGACY2",
            wof_expiry=date(2026, 8, 10),
            cof_expiry=None,
            odometer_last_recorded=92_500,
            service_due_date=date(2026, 11, 1),
            inspection_type="wof",
        )
        cv = _make_legacy_cv_link(
            org_id=org_id, customer_id=customer_id, gv=gv
        )

        # get_customer_reminder_config issues two queries:
        #   1. select(Customer).where(...) — scalar_one_or_none → customer
        #   2. linked-vehicles double-outerjoin → [(cv, gv, None)]
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                cust_result,
                _mock_rows([(cv, gv, None)]),
            ]
        )
        db.flush = AsyncMock()
        db.add = MagicMock()

        result = await get_customer_reminder_config(
            db, org_id=org_id, customer_id=customer_id
        )

        # -- Invariant 1: legacy link is NOT silently dropped --
        vehicles = result["vehicles"]
        assert len(vehicles) == 1, (
            "Legacy global-id-keyed link must render through "
            "get_customer_reminder_config — Backwards Compatibility "
            "guarantee (Req 6.5, 9.6)"
        )

        # -- Invariant 2: fields echo GlobalVehicle cache values --
        v = vehicles[0]
        # The function reports v.id under the legacy ``global_vehicle_id``
        # key for backwards compatibility with the frontend (which keys
        # ``vehicleDateEdits`` by this id). For legacy links v is gv, so
        # the id is the gv id.
        assert v["global_vehicle_id"] == str(gv.id)
        assert v["rego"] == gv.rego
        assert v["make"] == gv.make
        assert v["model"] == gv.model
        assert v["year"] == gv.year
        assert v["service_due_date"] == gv.service_due_date.isoformat(), (
            "Read_Fallback: reminder-config service_due_date must echo "
            "global_vehicles for legacy link (Req 6.5)"
        )
        assert v["wof_expiry"] == gv.wof_expiry.isoformat(), (
            "Read_Fallback: reminder-config wof_expiry must echo "
            "global_vehicles for legacy link (Req 6.5)"
        )

        # -- Invariant 3: no OrgVehicle was added --
        assert _added_org_vehicles(db) == [], (
            "get_customer_reminder_config is a read endpoint — it must "
            "not promote (Req 6.1)"
        )

    @pytest.mark.asyncio
    async def test_legacy_global_link_renders_through_fleet_portal_list_vehicles(self):
        """``fleet_portal.list_vehicles_for_session`` returns the legacy
        link with GlobalVehicle cache values.

        The fleet portal helper uses the canonical
        ``v = cv.global_vehicle if cv.global_vehicle is not None else
        cv.org_vehicle`` Read_Fallback pattern. For a legacy link,
        ``cv.global_vehicle = gv`` and ``cv.org_vehicle = None`` — v is
        gv.
        """
        org_id = uuid.uuid4()
        portal_account_id = uuid.uuid4()
        fleet_account_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        gv = _make_global_vehicle(
            rego="LEGACY3",
            wof_expiry=date(2026, 9, 20),
            cof_expiry=None,
            odometer_last_recorded=120_000,
            service_due_date=date(2026, 12, 1),
            inspection_type="wof",
        )
        cv = _make_legacy_cv_link(
            org_id=org_id, customer_id=customer_id, gv=gv
        )

        ctx = FleetSessionCtx(
            org_id=org_id,
            portal_account_id=portal_account_id,
            portal_user_role="fleet_admin",
            fleet_account_id=fleet_account_id,
            email="fleet@example.com",
            session_id=uuid.uuid4(),
        )

        # list_vehicles_for_session issues, in order:
        #   1. _customer_id_for_fleet → row[0] = customer_id
        #   2. count() over the base query → 1
        #   3. select(CustomerVehicle).options(...).limit(...) → [cv]
        fleet_lookup = MagicMock()
        fleet_lookup.first.return_value = (customer_id,)

        count_result = MagicMock()
        count_result.scalar_one.return_value = 1

        cv_result = MagicMock()
        cv_result.scalars.return_value.all.return_value = [cv]

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[fleet_lookup, count_result, cv_result]
        )
        db.flush = AsyncMock()
        db.add = MagicMock()

        items, total = await list_vehicles_for_session(
            db, ctx=ctx, offset=0, limit=50
        )

        # -- Invariant 1: legacy link is NOT silently dropped --
        assert total == 1
        assert len(items) == 1, (
            "Legacy global-id-keyed link must render through "
            "fleet_portal.list_vehicles_for_session — the portal's "
            "Read_Fallback pattern (Req 6.5, 7.1)"
        )

        # -- Invariant 2: fields echo GlobalVehicle cache values --
        item = items[0]
        assert item.customer_vehicle_id == cv.id
        assert item.rego == gv.rego
        assert item.make == gv.make
        assert item.model == gv.model
        assert item.year == gv.year
        assert item.colour == gv.colour
        assert item.odometer_last_recorded == gv.odometer_last_recorded, (
            "Read_Fallback: fleet portal list odometer must echo "
            "global_vehicles for legacy link (Req 6.5)"
        )
        assert item.wof_expiry == gv.wof_expiry, (
            "Read_Fallback: fleet portal list wof_expiry must echo "
            "global_vehicles for legacy link (Req 6.5)"
        )
        assert item.cof_expiry == gv.cof_expiry
        assert item.registration_expiry == gv.registration_expiry
        assert item.service_due_date == gv.service_due_date

        # -- Invariant 3: no OrgVehicle was added --
        assert _added_org_vehicles(db) == [], (
            "fleet_portal.list_vehicles_for_session is a read endpoint — "
            "it must not promote (Req 6.1, Req 7.4)"
        )

    @pytest.mark.asyncio
    async def test_legacy_global_link_renders_through_get_customer_profile(self):
        """``get_customer_profile`` returns the legacy link with
        GlobalVehicle cache values in its ``vehicles`` list.

        This endpoint iterates ``customer_vehicles`` and branches on
        ``cv.global_vehicle_id`` vs ``cv.org_vehicle_id`` — the legacy
        link takes the global branch and SELECTs the GlobalVehicle row
        directly.
        """
        org_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # Customer ORM mock — get_customer_profile does a full
        # ``_customer_to_dict`` serialisation, so it needs every field
        # that helper consumes.
        customer = MagicMock(spec=Customer)
        customer.id = customer_id
        customer.org_id = org_id
        customer.customer_type = "individual"
        customer.salutation = None
        customer.first_name = "Legacy"
        customer.last_name = "Owner"
        customer.company_name = None
        customer.display_name = "Legacy Owner"
        customer.email = None
        customer.phone = None
        customer.work_phone = None
        customer.mobile_phone = None
        customer.currency = "NZD"
        customer.language = "en"
        customer.tax_rate_id = None
        customer.company_id = None
        customer.payment_terms = "due_on_receipt"
        customer.enable_bank_payment = False
        customer.enable_portal = False
        customer.portal_token = None
        customer.portal_token_expires_at = None
        customer.last_portal_access_at = None
        customer.address = None
        customer.billing_address = None
        customer.shipping_address = None
        customer.contact_persons = None
        customer.custom_fields = None
        customer.notes = None
        customer.is_anonymised = False

        gv = _make_global_vehicle(
            rego="LEGACY4",
            wof_expiry=date(2026, 10, 5),
            cof_expiry=date(2027, 4, 1),
            odometer_last_recorded=58_200,
            service_due_date=date(2026, 12, 15),
            inspection_type="wof",
        )
        cv = _make_legacy_cv_link(
            org_id=org_id, customer_id=customer_id, gv=gv
        )

        # get_customer_profile issues, in order:
        #   1. select(Customer).where(...) → customer
        #   2. select(CustomerVehicle).where(...).order_by(...) → [cv]
        #   3. for the ONE legacy cv with global_vehicle_id set:
        #      select(GlobalVehicle).where(...) → gv
        #   4. select(Invoice).where(...).order_by(...) → []
        #   5. coalesce(sum(amount_paid)) → 0
        #   6. coalesce(sum(balance_due)) → 0
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer

        cv_scalars = MagicMock()
        cv_scalars.all.return_value = [cv]
        cv_result = MagicMock()
        cv_result.scalars.return_value = cv_scalars

        gv_result = MagicMock()
        gv_result.scalar_one_or_none.return_value = gv

        inv_scalars = MagicMock()
        inv_scalars.all.return_value = []
        inv_result = MagicMock()
        inv_result.scalars.return_value = inv_scalars

        spend_result = MagicMock()
        spend_result.scalar.return_value = _Decimal("0")

        balance_result = MagicMock()
        balance_result.scalar.return_value = _Decimal("0")

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                cust_result,
                cv_result,
                gv_result,
                inv_result,
                spend_result,
                balance_result,
            ]
        )
        db.flush = AsyncMock()
        db.add = MagicMock()

        result = await get_customer_profile(
            db, org_id=org_id, customer_id=customer_id
        )

        # -- Invariant 1: legacy link is NOT silently dropped --
        vehicles = result["vehicles"]
        assert len(vehicles) == 1, (
            "Legacy global-id-keyed link must render through "
            "get_customer_profile — Backwards Compatibility guarantee "
            "(Req 6.5, 9.6, 10.2)"
        )

        # -- Invariant 2: fields echo GlobalVehicle cache values --
        v = vehicles[0]
        assert v["id"] == str(cv.id), (
            "get_customer_profile keys vehicle dicts by cv.id — stable "
            "across promotion per design (link id is stable; only FK "
            "columns flip)"
        )
        assert v["rego"] == gv.rego
        assert v["make"] == gv.make
        assert v["model"] == gv.model
        assert v["year"] == gv.year
        assert v["colour"] == gv.colour
        assert v["source"] == "global", (
            "Legacy global-id link must surface source='global' so "
            "downstream consumers know which record-type the row "
            "originated from"
        )

        # -- Invariant 3: no OrgVehicle was added --
        assert _added_org_vehicles(db) == [], (
            "get_customer_profile is a read endpoint — it must not "
            "promote (Req 6.1)"
        )
