# Feature: invoice-edit-vehicle-display-refresh
"""Regression tests for ``update_invoice`` refreshing ``vehicle_display``.

Root-cause investigated 2026-05-30: editing WOF / COF / odometer / service-due
on an existing invoice silently dropped on the rendered invoice when the
caller did not thread ``global_vehicle_id`` through the form (e.g.
quote-converted invoices, kiosk-driven invoices, mobile minimal-create).

This module verifies, against a mocked DB:

1. ``update_invoice`` rego-falls-back to the OrgVehicle when the caller
   omits ``global_vehicle_id``, then writes the new WOF onto the
   OrgVehicle snapshot (Customer Driven Field promotion path stays intact).
2. ``update_invoice`` refreshes ``invoice_data_json.vehicle_display`` so the
   invoice detail tile and PDF inspection-expiry gate read the just-edited
   value (the snapshot used to be only written by ``create_invoice``).
3. The ``wof_updated`` flag is forwarded into the snapshot so the existing
   "show even when expiry is in the past" rule works on edits.

Validates Requirement: invoice-edit reads → writes → reads round-trip.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.payments.models  # noqa: F401

from app.modules.invoices.models import Invoice
from app.modules.invoices.service import update_invoice
from app.modules.vehicles.models import OrgVehicle


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_invoice(*, org_id, vehicle_rego="NUD941", vehicle_display=None):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id
    inv.customer_id = uuid.uuid4()
    inv.invoice_number = "SPINV-0053"
    inv.vehicle_rego = vehicle_rego
    inv.vehicle_make = "JEEP"
    inv.vehicle_model = "GLADIATOR"
    inv.vehicle_year = 2021
    inv.vehicle_odometer = 46127
    inv.branch_id = None
    inv.status = "issued"
    inv.issue_date = date(2026, 5, 29)
    inv.due_date = date(2026, 6, 12)
    inv.currency = "NZD"
    inv.exchange_rate_to_nzd = Decimal("1.0")
    inv.subtotal = Decimal("6.65")
    inv.discount_amount = Decimal("0")
    inv.discount_type = None
    inv.discount_value = None
    inv.gst_amount = Decimal("1.00")
    inv.total = Decimal("7.65")
    inv.amount_paid = Decimal("0")
    inv.balance_due = Decimal("7.65")
    inv.notes_internal = None
    inv.notes_customer = None
    inv.invoice_data_json = {
        "vehicle_display": vehicle_display
        or {
            "rego": "NUD941",
            "make": "JEEP",
            "model": "GLADIATOR",
            "year": 2021,
            "odometer": 46127,
            "inspection_type": "wof",
            "wof_expiry": "2025-12-09",
            "cof_expiry": None,
            "service_due_date": None,
            "wof_updated": False,
            "cof_updated": False,
            "service_due_updated": False,
        }
    }
    inv.created_by = uuid.uuid4()
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    return inv


def _make_org_vehicle(org_id, *, wof_expiry: date | None = date(2025, 12, 9)):
    ov = MagicMock(spec=OrgVehicle)
    ov.id = uuid.uuid4()
    ov.org_id = org_id
    ov.rego = "NUD941"
    ov.make = "JEEP"
    ov.model = "GLADIATOR"
    ov.year = 2021
    ov.wof_expiry = wof_expiry
    ov.cof_expiry = None
    ov.inspection_type = None
    ov.service_due_date = None
    ov.odometer_last_recorded = 46127
    return ov


class TestUpdateInvoiceVehicleDisplayRefresh:
    """Edit-time refresh of ``invoice_data_json.vehicle_display``.

    Validates that an InvoiceCreate edit-mode save (which today does NOT
    send ``global_vehicle_id``) correctly persists the new WOF date onto
    both the OrgVehicle snapshot AND the invoice's ``vehicle_display``
    snapshot.
    """

    @pytest.mark.asyncio
    @patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_wof_refreshes_vehicle_display(self, mock_audit):
        """WOF edit lands on both OrgVehicle.wof_expiry AND
        invoice_data_json.vehicle_display.wof_expiry, with wof_updated=True
        propagated into the snapshot — even when the caller omits
        ``global_vehicle_id``."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org_vehicle = _make_org_vehicle(org_id)

        db = _mock_db()

        # Sequence of db.execute side effects, in the order update_invoice issues them:
        # 1. SELECT Invoice
        inv_lookup = MagicMock()
        inv_lookup.scalar_one_or_none.return_value = invoice
        # 2. Rego fallback → SELECT OrgVehicle for invoice.vehicle_rego
        ov_lookup = MagicMock()
        ov_lookup.scalar_one_or_none.return_value = org_vehicle
        # 3. SELECT LineItem (fetch existing line items at end of fn)
        empty_li = MagicMock()
        empty_li.scalars.return_value.all.return_value = []

        db.execute.side_effect = [inv_lookup, ov_lookup, empty_li]

        # Patch _resolve_vehicle_type so it returns the OrgVehicle directly,
        # avoiding a second DB round-trip in the test.
        with patch(
            "app.modules.invoices.service._resolve_vehicle_type",
            new_callable=AsyncMock,
            return_value=("org", org_vehicle),
        ), patch("sqlalchemy.orm.attributes.flag_modified"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                updates={
                    "vehicle_wof_expiry_date": date(2026, 12, 9),
                    "vehicle_wof_updated": True,
                },
            )

        # OrgVehicle snapshot was updated
        assert org_vehicle.wof_expiry == date(2026, 12, 9)

        # invoice_data_json.vehicle_display was refreshed
        vd = invoice.invoice_data_json["vehicle_display"]
        assert vd["wof_expiry"] == "2026-12-09"
        assert vd["wof_updated"] is True
        assert vd["inspection_type"] == "wof"

        # Existing fields preserved
        assert vd["rego"] == "NUD941"
        assert vd["make"] == "JEEP"
        assert vd["odometer"] == 46127

    @pytest.mark.asyncio
    @patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_cof_sets_inspection_type_cof(self, mock_audit):
        """COF edit re-derives ``inspection_type='cof'`` in the snapshot."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id)
        org_vehicle = _make_org_vehicle(org_id)

        db = _mock_db()
        inv_lookup = MagicMock()
        inv_lookup.scalar_one_or_none.return_value = invoice
        ov_lookup = MagicMock()
        ov_lookup.scalar_one_or_none.return_value = org_vehicle
        empty_li = MagicMock()
        empty_li.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_lookup, ov_lookup, empty_li]

        with patch(
            "app.modules.invoices.service._resolve_vehicle_type",
            new_callable=AsyncMock,
            return_value=("org", org_vehicle),
        ), patch("sqlalchemy.orm.attributes.flag_modified"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                updates={
                    "vehicle_cof_expiry_date": date(2026, 6, 1),
                    "vehicle_cof_updated": True,
                },
            )

        vd = invoice.invoice_data_json["vehicle_display"]
        assert vd["cof_expiry"] == "2026-06-01"
        assert vd["inspection_type"] == "cof"
        assert vd["cof_updated"] is True
        assert org_vehicle.cof_expiry == date(2026, 6, 1)

    @pytest.mark.asyncio
    @patch("app.modules.invoices.service.write_audit_log", new_callable=AsyncMock)
    async def test_no_vehicle_fields_in_update_does_not_touch_display(
        self, mock_audit
    ):
        """An update that touches only non-vehicle fields (e.g. notes) leaves
        ``vehicle_display`` unchanged — no spurious snapshot rewrite."""
        org_id = uuid.uuid4()
        original_display = {
            "rego": "NUD941",
            "make": "JEEP",
            "model": "GLADIATOR",
            "year": 2021,
            "odometer": 46127,
            "inspection_type": "wof",
            "wof_expiry": "2025-12-09",
            "cof_expiry": None,
            "service_due_date": None,
            "wof_updated": False,
            "cof_updated": False,
            "service_due_updated": False,
        }
        invoice = _make_invoice(org_id=org_id, vehicle_display=dict(original_display))

        db = _mock_db()
        inv_lookup = MagicMock()
        inv_lookup.scalar_one_or_none.return_value = invoice
        empty_li = MagicMock()
        empty_li.scalars.return_value.all.return_value = []
        db.execute.side_effect = [inv_lookup, empty_li]

        await update_invoice(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            invoice_id=invoice.id,
            updates={"notes_customer": "Updated note"},
        )

        # Snapshot unchanged
        assert invoice.invoice_data_json["vehicle_display"] == original_display
