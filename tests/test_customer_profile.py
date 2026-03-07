"""Unit tests for Task 7.2 — customer profile, notify, and vehicle tagging.

Tests cover:
  - get_customer_profile: linked vehicles, invoice history, total spend, outstanding balance
  - notify_customer: email and SMS sending with validation
  - tag_vehicle_to_customer: linking global/org vehicles to customers

Requirements: 12.1, 12.2, 12.3
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.schemas import (
    CustomerNotifyRequest,
    CustomerNotifyResponse,
    CustomerProfileResponse,
    CustomerVehicleTagRequest,
    CustomerVehicleTagResponse,
    InvoiceHistoryItem,
    LinkedVehicleResponse,
)
from app.modules.customers.service import (
    get_customer_profile,
    notify_customer,
    tag_vehicle_to_customer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_customer(
    org_id=None,
    first_name="John",
    last_name="Smith",
    email="john@example.com",
    phone="+64 21 123 4567",
    address="123 Main St, Auckland",
    notes=None,
    is_anonymised=False,
):
    customer = MagicMock(spec=Customer)
    customer.id = uuid.uuid4()
    customer.org_id = org_id or uuid.uuid4()
    customer.first_name = first_name
    customer.last_name = last_name
    customer.email = email
    customer.phone = phone
    customer.address = address
    customer.notes = notes
    customer.is_anonymised = is_anonymised
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


def _make_invoice(
    org_id=None,
    customer_id=None,
    status="issued",
    total=Decimal("100.00"),
    amount_paid=Decimal("0"),
    balance_due=Decimal("100.00"),
    invoice_number="INV-001",
    vehicle_rego="ABC123",
):
    inv = MagicMock()
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = customer_id or uuid.uuid4()
    inv.invoice_number = invoice_number
    inv.vehicle_rego = vehicle_rego
    inv.status = status
    inv.issue_date = date(2024, 6, 1)
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.created_at = datetime.now(timezone.utc)
    return inv


def _make_customer_vehicle(
    org_id=None,
    customer_id=None,
    global_vehicle_id=None,
    org_vehicle_id=None,
):
    cv = MagicMock()
    cv.id = uuid.uuid4()
    cv.org_id = org_id or uuid.uuid4()
    cv.customer_id = customer_id or uuid.uuid4()
    cv.global_vehicle_id = global_vehicle_id
    cv.org_vehicle_id = org_vehicle_id
    cv.linked_at = datetime.now(timezone.utc)
    return cv


def _make_global_vehicle(rego="ABC123", make="Toyota", model="Corolla", year=2020, colour="White"):
    gv = MagicMock()
    gv.id = uuid.uuid4()
    gv.rego = rego
    gv.make = make
    gv.model = model
    gv.year = year
    gv.colour = colour
    return gv


def _make_org_vehicle(org_id=None, rego="XYZ789", make="Honda", model="Civic", year=2019, colour="Blue"):
    ov = MagicMock()
    ov.id = uuid.uuid4()
    ov.org_id = org_id or uuid.uuid4()
    ov.rego = rego
    ov.make = make
    ov.model = model
    ov.year = year
    ov.colour = colour
    return ov


def _mock_db_session():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_scalar_value(value):
    """Mock result for scalar() calls (e.g. aggregate queries)."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestProfileSchemas:
    """Test the new schemas for task 7.2."""

    def test_notify_request_email(self):
        req = CustomerNotifyRequest(channel="email", subject="Hello", message="Test body")
        assert req.channel == "email"
        assert req.subject == "Hello"

    def test_notify_request_sms(self):
        req = CustomerNotifyRequest(channel="sms", message="Test SMS")
        assert req.channel == "sms"
        assert req.subject is None

    def test_notify_request_invalid_channel(self):
        with pytest.raises(Exception):
            CustomerNotifyRequest(channel="fax", message="Nope")

    def test_vehicle_tag_request_global(self):
        vid = str(uuid.uuid4())
        req = CustomerVehicleTagRequest(global_vehicle_id=vid)
        assert req.global_vehicle_id == vid
        assert req.org_vehicle_id is None

    def test_vehicle_tag_request_org(self):
        vid = str(uuid.uuid4())
        req = CustomerVehicleTagRequest(org_vehicle_id=vid)
        assert req.org_vehicle_id == vid
        assert req.global_vehicle_id is None

    def test_linked_vehicle_response(self):
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
        assert resp.source == "global"

    def test_invoice_history_item(self):
        item = InvoiceHistoryItem(
            id=str(uuid.uuid4()),
            invoice_number="INV-001",
            vehicle_rego="ABC123",
            status="issued",
            issue_date="2024-06-01",
            total="100.00",
            balance_due="100.00",
        )
        assert item.status == "issued"

    def test_profile_response_defaults(self):
        resp = CustomerProfileResponse(
            id=str(uuid.uuid4()),
            first_name="John",
            last_name="Smith",
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.vehicles == []
        assert resp.invoices == []
        assert resp.total_spend == "0.00"
        assert resp.outstanding_balance == "0.00"


# ---------------------------------------------------------------------------
# get_customer_profile tests
# ---------------------------------------------------------------------------


class TestGetCustomerProfile:
    """Test the get_customer_profile service function."""

    @pytest.mark.asyncio
    async def test_returns_profile_with_no_vehicles_or_invoices(self):
        """Profile for a customer with no linked vehicles or invoices."""
        c = _make_customer()
        db = _mock_db_session()

        # Call sequence: customer lookup, vehicles, invoices, total_spend, outstanding
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),       # customer
            _mock_scalars_result([]),      # vehicles
            _mock_scalars_result([]),      # invoices
            _mock_scalar_value(Decimal("0")),  # total_spend
            _mock_scalar_value(Decimal("0")),  # outstanding
        ])

        result = await get_customer_profile(db, org_id=c.org_id, customer_id=c.id)

        assert result["id"] == str(c.id)
        assert result["vehicles"] == []
        assert result["invoices"] == []
        assert result["total_spend"] == "0"
        assert result["outstanding_balance"] == "0"

    @pytest.mark.asyncio
    async def test_returns_profile_with_global_vehicle(self):
        """Profile includes a linked global vehicle."""
        c = _make_customer()
        gv = _make_global_vehicle()
        cv = _make_customer_vehicle(
            org_id=c.org_id,
            customer_id=c.id,
            global_vehicle_id=gv.id,
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),           # customer
            _mock_scalars_result([cv]),        # customer_vehicles
            _mock_scalar_result(gv),          # global vehicle lookup
            _mock_scalars_result([]),          # invoices
            _mock_scalar_value(Decimal("0")), # total_spend
            _mock_scalar_value(Decimal("0")), # outstanding
        ])

        result = await get_customer_profile(db, org_id=c.org_id, customer_id=c.id)

        assert len(result["vehicles"]) == 1
        assert result["vehicles"][0]["rego"] == "ABC123"
        assert result["vehicles"][0]["source"] == "global"

    @pytest.mark.asyncio
    async def test_returns_profile_with_org_vehicle(self):
        """Profile includes a linked org-scoped vehicle."""
        c = _make_customer()
        ov = _make_org_vehicle(org_id=c.org_id)
        cv = _make_customer_vehicle(
            org_id=c.org_id,
            customer_id=c.id,
            org_vehicle_id=ov.id,
        )

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),           # customer
            _mock_scalars_result([cv]),        # customer_vehicles
            _mock_scalar_result(ov),          # org vehicle lookup
            _mock_scalars_result([]),          # invoices
            _mock_scalar_value(Decimal("0")), # total_spend
            _mock_scalar_value(Decimal("0")), # outstanding
        ])

        result = await get_customer_profile(db, org_id=c.org_id, customer_id=c.id)

        assert len(result["vehicles"]) == 1
        assert result["vehicles"][0]["rego"] == "XYZ789"
        assert result["vehicles"][0]["source"] == "org"

    @pytest.mark.asyncio
    async def test_returns_invoice_history(self):
        """Profile includes full invoice history."""
        c = _make_customer()
        inv = _make_invoice(org_id=c.org_id, customer_id=c.id)

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),               # customer
            _mock_scalars_result([]),              # vehicles
            _mock_scalars_result([inv]),           # invoices
            _mock_scalar_value(Decimal("50.00")), # total_spend
            _mock_scalar_value(Decimal("50.00")), # outstanding
        ])

        result = await get_customer_profile(db, org_id=c.org_id, customer_id=c.id)

        assert len(result["invoices"]) == 1
        assert result["invoices"][0]["invoice_number"] == "INV-001"
        assert result["invoices"][0]["status"] == "issued"

    @pytest.mark.asyncio
    async def test_calculates_total_spend_and_balance(self):
        """Profile correctly reports total spend and outstanding balance."""
        c = _make_customer()

        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),                  # customer
            _mock_scalars_result([]),                 # vehicles
            _mock_scalars_result([]),                 # invoices
            _mock_scalar_value(Decimal("1500.00")),  # total_spend
            _mock_scalar_value(Decimal("250.00")),   # outstanding
        ])

        result = await get_customer_profile(db, org_id=c.org_id, customer_id=c.id)

        assert result["total_spend"] == "1500.00"
        assert result["outstanding_balance"] == "250.00"

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await get_customer_profile(
                db, org_id=uuid.uuid4(), customer_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# notify_customer tests
# ---------------------------------------------------------------------------


class TestNotifyCustomer:
    """Test the notify_customer service function."""

    @pytest.mark.asyncio
    async def test_sends_email_successfully(self):
        """Sends email when customer has an email address."""
        c = _make_customer(email="test@example.com")
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await notify_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                channel="email",
                subject="Test Subject",
                message="Hello there",
            )

        assert result["channel"] == "email"
        assert result["recipient"] == "test@example.com"
        assert "queued" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_sends_sms_successfully(self):
        """Sends SMS when customer has a phone number."""
        c = _make_customer(phone="+64 21 555 1234")
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await notify_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                channel="sms",
                message="Your car is ready",
            )

        assert result["channel"] == "sms"
        assert result["recipient"] == "+64 21 555 1234"

    @pytest.mark.asyncio
    async def test_email_fails_without_email(self):
        """Raises ValueError when customer has no email."""
        c = _make_customer(email=None)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with pytest.raises(ValueError, match="no email"):
            await notify_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                channel="email",
                message="Hello",
            )

    @pytest.mark.asyncio
    async def test_sms_fails_without_phone(self):
        """Raises ValueError when customer has no phone."""
        c = _make_customer(phone=None)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with pytest.raises(ValueError, match="no phone"):
            await notify_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                channel="sms",
                message="Hello",
            )

    @pytest.mark.asyncio
    async def test_anonymised_customer_rejected(self):
        """Cannot notify an anonymised customer."""
        c = _make_customer(is_anonymised=True)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with pytest.raises(ValueError, match="anonymised"):
            await notify_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                channel="email",
                message="Hello",
            )

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await notify_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                channel="email",
                message="Hello",
            )

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Verify audit log is written on notification."""
        c = _make_customer(email="test@example.com")
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await notify_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                channel="email",
                subject="Test",
                message="Hello",
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "customer.notify.email"
        assert call_kwargs["entity_type"] == "customer"


# ---------------------------------------------------------------------------
# tag_vehicle_to_customer tests
# ---------------------------------------------------------------------------


class TestTagVehicleToCustomer:
    """Test the tag_vehicle_to_customer service function."""

    @pytest.mark.asyncio
    async def test_tags_global_vehicle(self):
        """Links a global vehicle to a customer."""
        c = _make_customer()
        gv = _make_global_vehicle()
        db = _mock_db_session()

        # Calls: customer lookup, global vehicle lookup
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),
            _mock_scalar_result(gv),
        ])

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await tag_vehicle_to_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                global_vehicle_id=gv.id,
            )

        assert result["rego"] == "ABC123"
        assert result["source"] == "global"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_tags_org_vehicle(self):
        """Links an org-scoped vehicle to a customer."""
        c = _make_customer()
        ov = _make_org_vehicle(org_id=c.org_id)
        db = _mock_db_session()

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),
            _mock_scalar_result(ov),
        ])

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await tag_vehicle_to_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                org_vehicle_id=ov.id,
            )

        assert result["rego"] == "XYZ789"
        assert result["source"] == "org"

    @pytest.mark.asyncio
    async def test_rejects_both_vehicle_ids(self):
        """Raises ValueError when both global and org vehicle IDs are provided."""
        db = _mock_db_session()

        with pytest.raises(ValueError, match="Exactly one"):
            await tag_vehicle_to_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                global_vehicle_id=uuid.uuid4(),
                org_vehicle_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_rejects_no_vehicle_ids(self):
        """Raises ValueError when neither vehicle ID is provided."""
        db = _mock_db_session()

        with pytest.raises(ValueError, match="Exactly one"):
            await tag_vehicle_to_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_customer_not_found(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await tag_vehicle_to_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                global_vehicle_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_global_vehicle_not_found(self):
        """Raises ValueError when global vehicle doesn't exist."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),
            _mock_scalar_result(None),
        ])

        with pytest.raises(ValueError, match="Global vehicle not found"):
            await tag_vehicle_to_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                global_vehicle_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_org_vehicle_not_found(self):
        """Raises ValueError when org vehicle doesn't exist."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),
            _mock_scalar_result(None),
        ])

        with pytest.raises(ValueError, match="Organisation vehicle not found"):
            await tag_vehicle_to_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                org_vehicle_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Verify audit log is written on vehicle tagging."""
        c = _make_customer()
        gv = _make_global_vehicle()
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(c),
            _mock_scalar_result(gv),
        ])

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await tag_vehicle_to_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                global_vehicle_id=gv.id,
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "customer.vehicle_tagged"
        assert call_kwargs["entity_type"] == "customer_vehicle"
