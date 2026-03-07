"""Unit tests for Task 7.3 — customer record merging.

Tests cover:
  - Merge preview generation (vehicles, invoices, contact changes)
  - Merge execution (invoices moved, vehicles moved, contacts filled, source deactivated)
  - Validation: cannot merge with self, anonymised customers, missing customers
  - Audit log written on merge
  - Fleet account transfer logic

Requirements: 12.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import admin and auth models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.schemas import (
    CustomerMergePreview,
    CustomerMergeRequest,
    CustomerMergeResponse,
    CustomerResponse,
    MergePreviewContactChanges,
    MergePreviewInvoice,
    MergePreviewVehicle,
)
from app.modules.customers.service import merge_customers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


def _make_customer(
    customer_id=None,
    org_id=None,
    first_name="John",
    last_name="Smith",
    email="john@example.com",
    phone="+64 21 123 4567",
    address="123 Main St, Auckland",
    notes=None,
    is_anonymised=False,
    fleet_account_id=None,
):
    """Create a mock Customer object."""
    customer = MagicMock(spec=Customer)
    customer.id = customer_id or uuid.uuid4()
    customer.org_id = org_id or ORG_ID
    customer.first_name = first_name
    customer.last_name = last_name
    customer.email = email
    customer.phone = phone
    customer.address = address
    customer.notes = notes
    customer.is_anonymised = is_anonymised
    customer.fleet_account_id = fleet_account_id
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


def _make_invoice(
    customer_id=None,
    org_id=None,
    invoice_number="INV-001",
    status="issued",
    total=Decimal("100.00"),
):
    """Create a mock Invoice object."""
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.org_id = org_id or ORG_ID
    inv.customer_id = customer_id or uuid.uuid4()
    inv.invoice_number = invoice_number
    inv.status = status
    inv.total = total
    return inv


def _make_customer_vehicle(
    customer_id=None,
    org_id=None,
    global_vehicle_id=None,
    org_vehicle_id=None,
):
    """Create a mock CustomerVehicle object."""
    cv = MagicMock()
    cv.id = uuid.uuid4()
    cv.org_id = org_id or ORG_ID
    cv.customer_id = customer_id or uuid.uuid4()
    cv.global_vehicle_id = global_vehicle_id
    cv.org_vehicle_id = org_vehicle_id
    cv.linked_at = datetime.now(timezone.utc)
    return cv


def _make_global_vehicle(rego="ABC123", make="Toyota", model="Corolla", year=2020):
    """Create a mock GlobalVehicle object."""
    gv = MagicMock()
    gv.id = uuid.uuid4()
    gv.rego = rego
    gv.make = make
    gv.model = model
    gv.year = year
    return gv


def _make_org_vehicle(org_id=None, rego="XYZ789", make="Honda", model="Civic", year=2019):
    """Create a mock OrgVehicle object."""
    ov = MagicMock()
    ov.id = uuid.uuid4()
    ov.org_id = org_id or ORG_ID
    ov.rego = rego
    ov.make = make
    ov.model = model
    ov.year = year
    return ov


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    """Create a mock result that returns values from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestMergeSchemas:
    """Test merge-related Pydantic schemas."""

    def test_merge_request_defaults_to_preview(self):
        req = CustomerMergeRequest(source_customer_id=str(uuid.uuid4()))
        assert req.preview_only is True

    def test_merge_request_execute(self):
        req = CustomerMergeRequest(
            source_customer_id=str(uuid.uuid4()), preview_only=False
        )
        assert req.preview_only is False

    def test_merge_preview_vehicle(self):
        v = MergePreviewVehicle(
            id=str(uuid.uuid4()), rego="ABC123", make="Toyota",
            model="Corolla", year=2020, source="global",
        )
        assert v.source == "global"

    def test_merge_preview_invoice(self):
        i = MergePreviewInvoice(
            id=str(uuid.uuid4()), invoice_number="INV-001",
            status="issued", total="100.00",
        )
        assert i.status == "issued"

    def test_merge_preview_contact_changes(self):
        c = MergePreviewContactChanges(
            email="a@b.com", phone="+64 21 000", address="1 St", notes="note"
        )
        assert c.email == "a@b.com"

    def test_merge_response_model(self):
        resp = CustomerMergeResponse(
            message="ok",
            preview=CustomerMergePreview(
                target_customer=CustomerResponse(
                    id=str(uuid.uuid4()), first_name="A", last_name="B",
                    is_anonymised=False, created_at="2024-01-01T00:00:00",
                    updated_at="2024-01-01T00:00:00",
                ),
                source_customer=CustomerResponse(
                    id=str(uuid.uuid4()), first_name="C", last_name="D",
                    is_anonymised=False, created_at="2024-01-01T00:00:00",
                    updated_at="2024-01-01T00:00:00",
                ),
                vehicles_to_transfer=[],
                invoices_to_transfer=[],
                contact_changes=MergePreviewContactChanges(),
                fleet_account_transfer=False,
            ),
            merged=False,
        )
        assert resp.merged is False


# ---------------------------------------------------------------------------
# Service tests — merge_customers
# ---------------------------------------------------------------------------


class TestMergeCustomersPreview:
    """Test merge preview generation."""

    @pytest.mark.asyncio
    async def test_preview_with_no_vehicles_or_invoices(self):
        """Preview when source has no vehicles or invoices."""
        target = _make_customer(first_name="Target", last_name="Customer")
        source = _make_customer(
            first_name="Source", last_name="Customer",
            email="source@example.com", phone="+64 22 999",
        )

        db = _mock_db_session()
        # target lookup, source lookup, vehicles query, invoices query
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),  # no vehicles
            _mock_scalars_result([]),  # no invoices
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=True,
            )

        assert result["merged"] is False
        assert result["preview"]["vehicles_to_transfer"] == []
        assert result["preview"]["invoices_to_transfer"] == []

    @pytest.mark.asyncio
    async def test_preview_shows_invoices_to_transfer(self):
        """Preview lists source invoices that will be transferred."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(first_name="Source", last_name="Cust")
        inv1 = _make_invoice(customer_id=source.id, invoice_number="INV-010")
        inv2 = _make_invoice(customer_id=source.id, invoice_number="INV-011", status="paid")

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),  # no vehicles
            _mock_scalars_result([inv1, inv2]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=True,
            )

        invoices = result["preview"]["invoices_to_transfer"]
        assert len(invoices) == 2
        assert invoices[0]["invoice_number"] == "INV-010"
        assert invoices[1]["invoice_number"] == "INV-011"

    @pytest.mark.asyncio
    async def test_preview_shows_vehicles_to_transfer(self):
        """Preview lists source vehicles that will be transferred."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(first_name="Source", last_name="Cust")
        gv = _make_global_vehicle(rego="ABC123")
        cv = _make_customer_vehicle(
            customer_id=source.id, global_vehicle_id=gv.id
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([cv]),  # one vehicle
            _mock_scalar_result(gv),     # global vehicle lookup
            _mock_scalars_result([]),     # no invoices
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=True,
            )

        vehicles = result["preview"]["vehicles_to_transfer"]
        assert len(vehicles) == 1
        assert vehicles[0]["rego"] == "ABC123"
        assert vehicles[0]["source"] == "global"

    @pytest.mark.asyncio
    async def test_preview_contact_changes_fills_gaps(self):
        """Preview shows target contact kept, source fills gaps."""
        target = _make_customer(
            first_name="Target", last_name="Cust",
            email="target@example.com", phone=None, address=None,
        )
        source = _make_customer(
            first_name="Source", last_name="Cust",
            email="source@example.com", phone="+64 22 999",
            address="456 Other St",
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=True,
            )

        changes = result["preview"]["contact_changes"]
        # Target email kept
        assert changes["email"] == "target@example.com"
        # Source fills gaps
        assert changes["phone"] == "+64 22 999"
        assert changes["address"] == "456 Other St"


class TestMergeCustomersExecution:
    """Test merge execution (preview_only=False)."""

    @pytest.mark.asyncio
    async def test_merge_moves_invoices_to_target(self):
        """Invoices are reassigned from source to target."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(first_name="Source", last_name="Cust")
        inv = _make_invoice(customer_id=source.id)

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),   # no vehicles
            _mock_scalars_result([inv]),  # one invoice
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        assert result["merged"] is True
        assert inv.customer_id == target.id

    @pytest.mark.asyncio
    async def test_merge_moves_vehicles_to_target(self):
        """Vehicle links are reassigned from source to target."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(first_name="Source", last_name="Cust")
        gv = _make_global_vehicle()
        cv = _make_customer_vehicle(
            customer_id=source.id, global_vehicle_id=gv.id
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([cv]),
            _mock_scalar_result(gv),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        assert result["merged"] is True
        assert cv.customer_id == target.id

    @pytest.mark.asyncio
    async def test_merge_fills_contact_gaps(self):
        """Target contact details are filled from source where missing."""
        target = _make_customer(
            first_name="Target", last_name="Cust",
            email="target@example.com", phone=None, address=None,
        )
        source = _make_customer(
            first_name="Source", last_name="Cust",
            email="source@example.com", phone="+64 22 999",
            address="456 Other St",
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        # Target email kept (not overwritten)
        assert target.email == "target@example.com"
        # Gaps filled from source
        assert target.phone == "+64 22 999"
        assert target.address == "456 Other St"

    @pytest.mark.asyncio
    async def test_merge_marks_source_as_inactive(self):
        """Source customer is marked as anonymised after merge."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(first_name="Source", last_name="Cust")

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        assert source.is_anonymised is True
        assert source.first_name == "Merged"
        assert source.last_name == "Customer"
        assert source.email is None
        assert source.phone is None
        assert source.address is None

    @pytest.mark.asyncio
    async def test_merge_transfers_fleet_account(self):
        """Fleet account transferred from source to target when target has none."""
        fleet_id = uuid.uuid4()
        target = _make_customer(
            first_name="Target", last_name="Cust", fleet_account_id=None
        )
        source = _make_customer(
            first_name="Source", last_name="Cust", fleet_account_id=fleet_id
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        assert target.fleet_account_id == fleet_id
        assert source.fleet_account_id is None
        assert result["preview"]["fleet_account_transfer"] is True

    @pytest.mark.asyncio
    async def test_merge_does_not_overwrite_target_fleet_account(self):
        """Fleet account NOT transferred when target already has one."""
        target_fleet = uuid.uuid4()
        source_fleet = uuid.uuid4()
        target = _make_customer(
            first_name="Target", last_name="Cust", fleet_account_id=target_fleet
        )
        source = _make_customer(
            first_name="Source", last_name="Cust", fleet_account_id=source_fleet
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        # Target fleet account unchanged
        assert target.fleet_account_id == target_fleet
        assert result["preview"]["fleet_account_transfer"] is False

    @pytest.mark.asyncio
    async def test_merge_writes_audit_log(self):
        """Audit log is written when merge is executed."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(first_name="Source", last_name="Cust")

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "customer.merged"
        assert call_kwargs["entity_type"] == "customer"
        assert call_kwargs["entity_id"] == target.id

    @pytest.mark.asyncio
    async def test_merge_combines_notes(self):
        """Notes from source are appended to target notes."""
        target = _make_customer(
            first_name="Target", last_name="Cust", notes="Target note"
        )
        source = _make_customer(
            first_name="Source", last_name="Cust", notes="Source note"
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=False,
            )

        assert "Target note" in target.notes
        assert "Source note" in target.notes
        assert "Merged from Source Cust" in target.notes


class TestMergeCustomersValidation:
    """Test merge validation and error cases."""

    @pytest.mark.asyncio
    async def test_cannot_merge_with_self(self):
        """Merging a customer with themselves raises ValueError."""
        customer_id = uuid.uuid4()
        db = _mock_db_session()

        with pytest.raises(ValueError, match="Cannot merge a customer with themselves"):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=customer_id,
                source_customer_id=customer_id,
                preview_only=True,
            )

    @pytest.mark.asyncio
    async def test_target_not_found(self):
        """Raises ValueError when target customer not found."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Target customer not found"):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=uuid.uuid4(),
                source_customer_id=uuid.uuid4(),
                preview_only=True,
            )

    @pytest.mark.asyncio
    async def test_source_not_found(self):
        """Raises ValueError when source customer not found."""
        target = _make_customer(first_name="Target", last_name="Cust")
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(None),
        ])

        with pytest.raises(ValueError, match="Source customer not found"):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=uuid.uuid4(),
                preview_only=True,
            )

    @pytest.mark.asyncio
    async def test_cannot_merge_into_anonymised_target(self):
        """Raises ValueError when target is anonymised."""
        target = _make_customer(
            first_name="Anon", last_name="Cust", is_anonymised=True
        )
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(target))

        with pytest.raises(ValueError, match="Cannot merge into an anonymised customer"):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=uuid.uuid4(),
                preview_only=True,
            )

    @pytest.mark.asyncio
    async def test_cannot_merge_from_anonymised_source(self):
        """Raises ValueError when source is anonymised."""
        target = _make_customer(first_name="Target", last_name="Cust")
        source = _make_customer(
            first_name="Anon", last_name="Cust", is_anonymised=True
        )
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
        ])

        with pytest.raises(ValueError, match="Cannot merge from an anonymised customer"):
            await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=True,
            )

    @pytest.mark.asyncio
    async def test_preview_does_not_modify_records(self):
        """Preview mode does not change any customer, invoice, or vehicle records."""
        target = _make_customer(
            first_name="Target", last_name="Cust",
            email="target@example.com", phone=None,
        )
        source = _make_customer(
            first_name="Source", last_name="Cust",
            email="source@example.com", phone="+64 22 999",
        )
        inv = _make_invoice(customer_id=source.id)
        original_customer_id = inv.customer_id

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(target),
            _mock_scalar_result(source),
            _mock_scalars_result([]),
            _mock_scalars_result([inv]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            result = await merge_customers(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                target_customer_id=target.id,
                source_customer_id=source.id,
                preview_only=True,
            )

        assert result["merged"] is False
        # Invoice not moved
        assert inv.customer_id == original_customer_id
        # Target phone not filled
        assert target.phone is None
        # Source not anonymised
        assert source.is_anonymised is False
        # No audit log written for preview
        mock_audit.assert_not_called()
        # db.flush not called for preview
        db.flush.assert_not_called()
