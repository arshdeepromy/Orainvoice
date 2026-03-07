"""Property-based tests for customer anonymisation (Task 7.7).

Property 14: Customer Anonymisation Preserves Financial Records
— verify deletion anonymises customer but preserves invoice amounts,
  line items, and payment history.

**Validates: Requirements 13.2**

Uses Hypothesis to generate random customer data, invoices with line items,
and payments, then verifies that after anonymisation:
  1. Customer PII is replaced/cleared
  2. Invoice financial amounts are unchanged
  3. Line items are unchanged
  4. Payment history is unchanged
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Ensure relationship models are loaded
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.service import anonymise_customer
from app.modules.invoices.models import Invoice, LineItem
from app.modules.payments.models import Payment


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies — generate realistic customer / invoice / payment data
# ---------------------------------------------------------------------------

nz_first_names = st.sampled_from([
    "Aroha", "Tane", "Maia", "Nikau", "Kaia", "Wiremu", "Hana", "Rawiri",
    "Anika", "Matiu", "Sophie", "James", "Olivia", "Liam", "Emma",
])

nz_last_names = st.sampled_from([
    "Smith", "Williams", "Brown", "Wilson", "Taylor", "Anderson", "Thomas",
    "Harris", "Martin", "Thompson", "Walker", "White", "Robinson", "Clark",
])

nz_emails = st.builds(
    lambda first, last, domain: f"{first.lower()}.{last.lower()}@{domain}",
    first=nz_first_names,
    last=nz_last_names,
    domain=st.sampled_from(["gmail.com", "xtra.co.nz", "outlook.co.nz", "workshop.nz"]),
)

nz_phones = st.from_regex(r"\+64 2[0-9] [0-9]{3} [0-9]{4}", fullmatch=True)

nz_addresses = st.builds(
    lambda num, street, city: f"{num} {street}, {city}",
    num=st.integers(1, 999),
    street=st.sampled_from(["Queen St", "Lambton Quay", "Colombo St", "George St", "Victoria Ave"]),
    city=st.sampled_from(["Auckland", "Wellington", "Christchurch", "Hamilton", "Dunedin"]),
)

# Monetary amounts: positive, 2 decimal places, reasonable range
money = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"),
                    places=2, allow_nan=False, allow_infinity=False)

positive_quantity = st.decimals(min_value=Decimal("0.001"), max_value=Decimal("999.999"),
                                places=3, allow_nan=False, allow_infinity=False)

line_item_types = st.sampled_from(["service", "part", "labour"])

line_item_descriptions = st.sampled_from([
    "Oil Change", "Brake Pad Replacement", "WOF Inspection",
    "Tyre Rotation", "Engine Diagnostic", "Spark Plug Replacement",
    "Air Filter", "Transmission Fluid", "Wheel Alignment",
    "Battery Replacement", "Coolant Flush", "Timing Belt",
])

payment_methods = st.sampled_from(["cash", "stripe"])

invoice_statuses = st.sampled_from(["issued", "partially_paid", "paid", "overdue"])


@st.composite
def customer_data(draw):
    """Generate random customer data."""
    return {
        "first_name": draw(nz_first_names),
        "last_name": draw(nz_last_names),
        "email": draw(nz_emails),
        "phone": draw(nz_phones),
        "address": draw(nz_addresses),
        "notes": draw(st.text(min_size=0, max_size=100)),
    }


@st.composite
def line_item_data(draw, invoice_id, org_id):
    """Generate a random line item."""
    item_type = draw(line_item_types)
    quantity = draw(positive_quantity)
    unit_price = draw(money)
    line_total = (quantity * unit_price).quantize(Decimal("0.01"))

    li = MagicMock(spec=LineItem)
    li.id = uuid.uuid4()
    li.invoice_id = invoice_id
    li.org_id = org_id
    li.item_type = item_type
    li.description = draw(line_item_descriptions)
    li.quantity = quantity
    li.unit_price = unit_price
    li.line_total = line_total
    li.is_gst_exempt = draw(st.booleans())
    li.warranty_note = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))
    li.sort_order = draw(st.integers(0, 10))
    li.hours = draw(st.one_of(st.none(), money)) if item_type == "labour" else None
    li.hourly_rate = draw(st.one_of(st.none(), money)) if item_type == "labour" else None
    li.part_number = draw(st.one_of(st.none(), st.text(min_size=1, max_size=20))) if item_type == "part" else None
    li.discount_type = draw(st.one_of(st.none(), st.sampled_from(["percentage", "fixed"])))
    li.discount_value = draw(st.one_of(st.none(), money))
    li.created_at = datetime.now(timezone.utc)
    return li


@st.composite
def payment_data(draw, invoice_id, org_id):
    """Generate a random payment record."""
    p = MagicMock(spec=Payment)
    p.id = uuid.uuid4()
    p.invoice_id = invoice_id
    p.org_id = org_id
    p.amount = draw(money)
    p.method = draw(payment_methods)
    p.is_refund = draw(st.booleans())
    p.refund_note = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))) if p.is_refund else None
    p.stripe_payment_intent_id = draw(st.one_of(st.none(), st.text(min_size=5, max_size=30)))
    p.recorded_by = uuid.uuid4()
    p.created_at = datetime.now(timezone.utc)
    return p


@st.composite
def invoice_with_items_and_payments(draw, customer_id, org_id, customer_name, customer_email, customer_phone, customer_address):
    """Generate an invoice with random line items and payments."""
    inv_id = uuid.uuid4()
    subtotal = draw(money)
    gst_amount = (subtotal * Decimal("0.15")).quantize(Decimal("0.01"))
    total = subtotal + gst_amount
    amount_paid = draw(st.decimals(
        min_value=Decimal("0"), max_value=total, places=2,
        allow_nan=False, allow_infinity=False,
    ))
    balance_due = total - amount_paid

    inv = MagicMock(spec=Invoice)
    inv.id = inv_id
    inv.org_id = org_id
    inv.customer_id = customer_id
    inv.invoice_number = draw(st.from_regex(r"INV-[0-9]{3,5}", fullmatch=True))
    inv.status = draw(invoice_statuses)
    inv.issue_date = date(2024, draw(st.integers(1, 12)), draw(st.integers(1, 28)))
    inv.due_date = date(2024, draw(st.integers(1, 12)), draw(st.integers(1, 28)))
    inv.vehicle_rego = draw(st.from_regex(r"[A-Z]{3}[0-9]{3}", fullmatch=True))
    inv.subtotal = subtotal
    inv.gst_amount = gst_amount
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.discount_amount = draw(st.decimals(
        min_value=Decimal("0"), max_value=Decimal("999.99"), places=2,
        allow_nan=False, allow_infinity=False,
    ))
    inv.currency = "NZD"
    inv.invoice_data_json = {
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
        "customer_address": customer_address,
    }
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)

    # Generate 1-5 line items
    items = [draw(line_item_data(inv_id, org_id)) for _ in range(draw(st.integers(1, 5)))]
    inv.line_items = items

    # Generate 0-3 payments
    payments = [draw(payment_data(inv_id, org_id)) for _ in range(draw(st.integers(0, 3)))]
    inv.payments = payments

    return inv


# ---------------------------------------------------------------------------
# Composite strategy: full anonymisation scenario
# ---------------------------------------------------------------------------

@st.composite
def anonymisation_scenario(draw):
    """Generate a complete scenario: customer + invoices with items & payments."""
    org_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    user_id = uuid.uuid4()

    cust_data = draw(customer_data())
    full_name = f"{cust_data['first_name']} {cust_data['last_name']}"

    # Build mock customer
    customer = MagicMock(spec=Customer)
    customer.id = customer_id
    customer.org_id = org_id
    customer.first_name = cust_data["first_name"]
    customer.last_name = cust_data["last_name"]
    customer.email = cust_data["email"]
    customer.phone = cust_data["phone"]
    customer.address = cust_data["address"]
    customer.notes = cust_data["notes"]
    customer.is_anonymised = False
    customer.portal_token = uuid.uuid4()
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)

    # Generate 1-4 invoices with line items and payments
    num_invoices = draw(st.integers(1, 4))
    invoices = [
        draw(invoice_with_items_and_payments(
            customer_id=customer_id,
            org_id=org_id,
            customer_name=full_name,
            customer_email=cust_data["email"],
            customer_phone=cust_data["phone"],
            customer_address=cust_data["address"],
        ))
        for _ in range(num_invoices)
    ]

    return {
        "org_id": org_id,
        "customer_id": customer_id,
        "user_id": user_id,
        "customer": customer,
        "customer_data": cust_data,
        "invoices": invoices,
    }


# ---------------------------------------------------------------------------
# Helper: set up mock DB session for anonymisation
# ---------------------------------------------------------------------------

def _setup_mock_db(customer, invoices):
    """Configure a mock AsyncSession that returns the customer and invoices."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    call_count = {"n": 0}

    async def mock_execute(stmt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: customer lookup
            result = MagicMock()
            result.scalar_one_or_none.return_value = customer
            return result
        else:
            # Second call: invoice lookup
            result = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = invoices
            result.scalars.return_value = scalars_mock
            return result

    db.execute = mock_execute
    return db


# ---------------------------------------------------------------------------
# Property 14: Customer Anonymisation Preserves Financial Records
# ---------------------------------------------------------------------------


class TestCustomerAnonymisationPreservesFinancialRecords:
    """Property 14: Customer Anonymisation Preserves Financial Records.

    **Validates: Requirements 13.2**

    For any customer deletion (Privacy Act request), all linked invoice
    records shall remain in the database with the customer name replaced
    by "Anonymised Customer" and all contact details (email, phone, address)
    cleared. The invoice amounts, line items, and payment history shall
    remain unchanged.
    """

    @pytest.mark.asyncio
    @given(scenario=anonymisation_scenario())
    @PBT_SETTINGS
    async def test_pii_is_removed_after_anonymisation(self, scenario):
        """After anonymisation, customer PII must be replaced/cleared.

        **Validates: Requirements 13.2**
        """
        customer = scenario["customer"]
        invoices = scenario["invoices"]
        db = _setup_mock_db(customer, invoices)

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await anonymise_customer(
                db,
                org_id=scenario["org_id"],
                user_id=scenario["user_id"],
                customer_id=scenario["customer_id"],
            )

        # Customer name replaced with "Anonymised Customer"
        assert customer.first_name == "Anonymised"
        assert customer.last_name == "Customer"

        # All contact details cleared
        assert customer.email is None
        assert customer.phone is None
        assert customer.address is None
        assert customer.notes is None
        assert customer.portal_token is None
        assert customer.is_anonymised is True

    @pytest.mark.asyncio
    @given(scenario=anonymisation_scenario())
    @PBT_SETTINGS
    async def test_invoice_amounts_preserved_after_anonymisation(self, scenario):
        """After anonymisation, all invoice financial amounts must be unchanged.

        **Validates: Requirements 13.2**
        """
        customer = scenario["customer"]
        invoices = scenario["invoices"]

        # Snapshot financial data before anonymisation
        before_financials = []
        for inv in invoices:
            before_financials.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "subtotal": inv.subtotal,
                "gst_amount": inv.gst_amount,
                "total": inv.total,
                "amount_paid": inv.amount_paid,
                "balance_due": inv.balance_due,
                "discount_amount": inv.discount_amount,
                "status": inv.status,
                "currency": inv.currency,
            })

        db = _setup_mock_db(customer, invoices)

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await anonymise_customer(
                db,
                org_id=scenario["org_id"],
                user_id=scenario["user_id"],
                customer_id=scenario["customer_id"],
            )

        # Verify every invoice's financial data is unchanged
        for inv, before in zip(invoices, before_financials):
            assert inv.id == before["id"]
            assert inv.invoice_number == before["invoice_number"]
            assert inv.subtotal == before["subtotal"]
            assert inv.gst_amount == before["gst_amount"]
            assert inv.total == before["total"]
            assert inv.amount_paid == before["amount_paid"]
            assert inv.balance_due == before["balance_due"]
            assert inv.discount_amount == before["discount_amount"]
            assert inv.status == before["status"]
            assert inv.currency == before["currency"]

    @pytest.mark.asyncio
    @given(scenario=anonymisation_scenario())
    @PBT_SETTINGS
    async def test_line_items_preserved_after_anonymisation(self, scenario):
        """After anonymisation, all invoice line items must be unchanged.

        **Validates: Requirements 13.2**
        """
        customer = scenario["customer"]
        invoices = scenario["invoices"]

        # Snapshot line items before anonymisation
        before_items = {}
        for inv in invoices:
            before_items[inv.id] = [
                {
                    "id": li.id,
                    "item_type": li.item_type,
                    "description": li.description,
                    "quantity": li.quantity,
                    "unit_price": li.unit_price,
                    "line_total": li.line_total,
                    "is_gst_exempt": li.is_gst_exempt,
                }
                for li in inv.line_items
            ]

        db = _setup_mock_db(customer, invoices)

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await anonymise_customer(
                db,
                org_id=scenario["org_id"],
                user_id=scenario["user_id"],
                customer_id=scenario["customer_id"],
            )

        # Verify every line item is unchanged
        for inv in invoices:
            for li, before in zip(inv.line_items, before_items[inv.id]):
                assert li.id == before["id"]
                assert li.item_type == before["item_type"]
                assert li.description == before["description"]
                assert li.quantity == before["quantity"]
                assert li.unit_price == before["unit_price"]
                assert li.line_total == before["line_total"]
                assert li.is_gst_exempt == before["is_gst_exempt"]

    @pytest.mark.asyncio
    @given(scenario=anonymisation_scenario())
    @PBT_SETTINGS
    async def test_payment_history_preserved_after_anonymisation(self, scenario):
        """After anonymisation, all payment records must be unchanged.

        **Validates: Requirements 13.2**
        """
        customer = scenario["customer"]
        invoices = scenario["invoices"]

        # Snapshot payments before anonymisation
        before_payments = {}
        for inv in invoices:
            before_payments[inv.id] = [
                {
                    "id": p.id,
                    "amount": p.amount,
                    "method": p.method,
                    "is_refund": p.is_refund,
                }
                for p in inv.payments
            ]

        db = _setup_mock_db(customer, invoices)

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await anonymise_customer(
                db,
                org_id=scenario["org_id"],
                user_id=scenario["user_id"],
                customer_id=scenario["customer_id"],
            )

        # Verify every payment is unchanged
        for inv in invoices:
            for p, before in zip(inv.payments, before_payments[inv.id]):
                assert p.id == before["id"]
                assert p.amount == before["amount"]
                assert p.method == before["method"]
                assert p.is_refund == before["is_refund"]

    @pytest.mark.asyncio
    @given(scenario=anonymisation_scenario())
    @PBT_SETTINGS
    async def test_invoice_json_pii_anonymised(self, scenario):
        """After anonymisation, customer PII in invoice_data_json must be cleared.

        **Validates: Requirements 13.2**
        """
        customer = scenario["customer"]
        invoices = scenario["invoices"]
        db = _setup_mock_db(customer, invoices)

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            await anonymise_customer(
                db,
                org_id=scenario["org_id"],
                user_id=scenario["user_id"],
                customer_id=scenario["customer_id"],
            )

        # Verify PII in invoice JSON snapshots is anonymised
        for inv in invoices:
            json_data = inv.invoice_data_json
            assert json_data["customer_name"] == "Anonymised Customer"
            assert json_data["customer_email"] is None
            assert json_data["customer_phone"] is None
            assert json_data["customer_address"] is None
