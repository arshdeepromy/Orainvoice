# Feature: customer-profile-vehicle-prefill
"""Regression test for the customer profile's linked vehicle response shape.

Root-cause investigated 2026-05-30: clicking "Issue Invoice" from a customer
profile took the user to ``/invoices/new?customer_id=...&vehicle_rego=...``
but the form left WOF / COF / odometer / service-due empty even though the
linked vehicle had those values stored on the OrgVehicle / GlobalVehicle.

The frontend pre-fill code reads ``customer.vehicles[i].wof_expiry`` etc.,
but the Pydantic ``LinkedVehicleResponse`` schema only declared
``id/rego/make/model/year/colour/source/origin/linked_at`` — Pydantic was
silently stripping the Customer Driven Field values that the service did
emit.

This module verifies the schema now declares the missing fields so a
service-side dict containing them serialises without loss.
"""
from __future__ import annotations

import uuid

from app.modules.customers.schemas import LinkedVehicleResponse


class TestLinkedVehicleResponseShape:
    def test_carries_wof_cof_odometer_inspection_service_due(self):
        """LinkedVehicleResponse declares every field the customer profile
        service emits, so Pydantic preserves them through serialisation."""
        resp = LinkedVehicleResponse(
            id=str(uuid.uuid4()),
            rego="NUD941",
            make="JEEP",
            model="GLADIATOR",
            year=2021,
            colour="Black",
            odometer=46127,
            service_due_date="2026-09-01",
            wof_expiry="2025-12-09",
            cof_expiry=None,
            inspection_type="wof",
            source="org",
            origin="carjam",
            linked_at="2026-05-29T22:00:00+00:00",
        )

        # Every field the InvoiceCreate "Issue Invoice" pre-fill consumer
        # reads from ``customer.vehicles[i]`` survives the round-trip.
        assert resp.odometer == 46127
        assert resp.service_due_date == "2026-09-01"
        assert resp.wof_expiry == "2025-12-09"
        assert resp.cof_expiry is None
        assert resp.inspection_type == "wof"

    def test_old_payload_without_extra_fields_still_validates(self):
        """Backwards compat: callers that don't supply the new fields keep working."""
        resp = LinkedVehicleResponse(
            id=str(uuid.uuid4()),
            rego="ABC123",
            make="Toyota",
            model="Corolla",
            year=2020,
            colour="White",
            source="global",
            linked_at="2024-06-01T00:00:00+00:00",
        )
        # New fields default to None.
        assert resp.odometer is None
        assert resp.wof_expiry is None
        assert resp.cof_expiry is None
        assert resp.inspection_type is None
        assert resp.service_due_date is None
