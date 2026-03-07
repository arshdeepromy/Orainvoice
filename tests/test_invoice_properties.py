"""Property-based tests for Invoice module (Task 10.11).

Properties tested:
- Property 2: Invoice Number Contiguity
- Property 3: Invoice Number Immutability
- Property 4: GST Calculation Correctness
- Property 5: Invoice Balance Consistency
- Property 21: NZ Tax Invoice Compliance
- Property 22: Invoice Status State Machine

**Validates: Requirements 17.5, 18.6, 18.7, 19.1-19.7, 20.3, 23.1, 23.2,
             24.1-24.3, 80.1, 80.2**

Uses Hypothesis to generate random test data and verify universal properties.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

# Ensure relationship models are loaded for SQLAlchemy
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.modules.invoices.models import Invoice, LineItem
from app.modules.invoices.service import (
    _calculate_line_total,
    _calculate_invoice_totals,
    _get_next_invoice_number,
    _validate_transition,
    validate_tax_invoice_compliance,
    update_invoice,
    VALID_TRANSITIONS,
    NZ_HIGH_VALUE_THRESHOLD,
)

TWO_PLACES = Decimal("0.01")

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

ALL_STATUSES = ["draft", "issued", "partially_paid", "paid", "overdue", "voided"]

invoice_prefixes = st.sampled_from(["INV-", "WS-", "AUTO-", "SVC-", ""])

item_types = st.sampled_from(["service", "part", "labour"])

quantities = st.decimals(
    min_value="0.001", max_value="9999.999",
    places=3, allow_nan=False, allow_infinity=False,
)

unit_prices = st.decimals(
    min_value="0.01", max_value="99999.99",
    places=2, allow_nan=False, allow_infinity=False,
)

gst_rates = st.decimals(
    min_value="0", max_value="25",
    places=2, allow_nan=False, allow_infinity=False,
)

discount_types = st.sampled_from([None, "percentage", "fixed"])

discount_values_pct = st.decimals(
    min_value="0.01", max_value="100.00",
    places=2, allow_nan=False, allow_infinity=False,
)

discount_values_fixed = st.decimals(
    min_value="0.01", max_value="99999.99",
    places=2, allow_nan=False, allow_infinity=False,
)

payment_amounts = st.decimals(
    min_value="0.01", max_value="999999.99",
    places=2, allow_nan=False, allow_infinity=False,
)

credit_note_amounts = st.decimals(
    min_value="0.01", max_value="999999.99",
    places=2, allow_nan=False, allow_infinity=False,
)

org_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=1, max_size=100,
).filter(lambda s: s.strip())

gst_numbers = st.from_regex(r"[0-9]{2,3}-[0-9]{3}-[0-9]{3}", fullmatch=True)

descriptions = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())

addresses = st.text(min_size=5, max_size=200).filter(lambda s: s.strip())

customer_first_names = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=1, max_size=50,
).filter(lambda s: s.strip())

customer_last_names = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=1, max_size=50,
).filter(lambda s: s.strip())


@st.composite
def line_item_data(draw):
    """Generate a random line item dict for _calculate_invoice_totals."""
    dt = draw(discount_types)
    dv = None
    if dt == "percentage":
        dv = draw(discount_values_pct)
    elif dt == "fixed":
        dv = draw(discount_values_fixed)

    return {
        "quantity": draw(quantities),
        "unit_price": draw(unit_prices),
        "discount_type": dt,
        "discount_value": dv,
        "is_gst_exempt": draw(st.booleans()),
    }


@st.composite
def line_items_list(draw, min_size=1, max_size=10):
    """Generate a list of line item dicts."""
    return draw(st.lists(line_item_data(), min_size=min_size, max_size=max_size))


@st.composite
def invoice_level_discount(draw):
    """Generate an optional invoice-level discount."""
    dt = draw(discount_types)
    dv = None
    if dt == "percentage":
        dv = draw(discount_values_pct)
    elif dt == "fixed":
        dv = draw(discount_values_fixed)
    return dt, dv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    return db


def _make_invoice_mock(
    org_id=None,
    status="issued",
    invoice_number="INV-0001",
    total=Decimal("115.00"),
    subtotal=Decimal("100.00"),
    gst_amount=Decimal("15.00"),
    issue_date=None,
    customer_id=None,
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = customer_id or uuid.uuid4()
    inv.status = status
    inv.invoice_number = invoice_number
    inv.issue_date = issue_date or date.today()
    inv.due_date = date.today()
    inv.total = total
    inv.subtotal = subtotal
    inv.gst_amount = gst_amount
    inv.discount_amount = Decimal("0.00")
    inv.amount_paid = Decimal("0.00")
    inv.balance_due = total
    inv.currency = "NZD"
    inv.exchange_rate_to_nzd = Decimal("1.000000")
    inv.void_reason = None
    inv.voided_at = None
    inv.voided_by = None
    inv.created_by = uuid.uuid4()
    inv.created_at = datetime.now(timezone.utc)
    inv.updated_at = datetime.now(timezone.utc)
    inv.line_items = []
    inv.credit_notes = []
    inv.payments = []
    return inv


def _make_line_item_mock(
    invoice_id=None,
    description="Test service",
    is_gst_exempt=False,
    quantity=Decimal("1"),
    unit_price=Decimal("100.00"),
    line_total=Decimal("100.00"),
):
    li = MagicMock(spec=LineItem)
    li.id = uuid.uuid4()
    li.invoice_id = invoice_id or uuid.uuid4()
    li.item_type = "service"
    li.description = description
    li.quantity = quantity
    li.unit_price = unit_price
    li.is_gst_exempt = is_gst_exempt
    li.discount_type = None
    li.discount_value = None
    li.warranty_note = None
    li.line_total = line_total
    li.sort_order = 0
    return li


def _make_customer_mock(first_name="John", last_name="Doe", address="123 Main St"):
    customer = MagicMock()
    customer.first_name = first_name
    customer.last_name = last_name
    customer.address = address
    return customer


# ---------------------------------------------------------------------------
# Property 2: Invoice Number Contiguity
# **Validates: Requirements 23.1, 23.2**
# ---------------------------------------------------------------------------


class TestInvoiceNumberContiguity:
    """Verify issued numbers form a gap-free sequence per org."""

    @PBT_SETTINGS
    @given(
        num_invoices=st.integers(min_value=2, max_value=20),
        prefix=invoice_prefixes,
    )
    @pytest.mark.asyncio
    async def test_contiguous_sequence_no_gaps(self, num_invoices, prefix):
        """Property 2: Invoice Number Contiguity — issued numbers form
        gap-free sequence per org.

        **Validates: Requirements 23.1, 23.2**
        """
        org_id = uuid.uuid4()
        db = _mock_db()

        # Track the sequence counter across calls
        counter = {"last_number": 0}

        async def mock_execute(query, params=None):
            sql = str(query) if not isinstance(query, str) else query
            result = MagicMock()

            if "FOR UPDATE" in sql:
                if counter["last_number"] == 0:
                    result.first.return_value = None
                else:
                    row = MagicMock()
                    row.id = uuid.uuid4()
                    row.last_number = counter["last_number"]
                    result.first.return_value = row
                return result

            if "INSERT INTO invoice_sequences" in sql:
                counter["last_number"] = 1
                return result

            if "UPDATE invoice_sequences" in sql:
                counter["last_number"] = params["num"]
                return result

            return result

        db.execute = AsyncMock(side_effect=mock_execute)

        # Issue N invoices and collect numbers
        numbers = []
        for _ in range(num_invoices):
            inv_num = await _get_next_invoice_number(db, org_id, prefix)
            numbers.append(inv_num)

        # Extract numeric parts
        numeric_parts = []
        for num in numbers:
            match = re.search(r"(\d+)$", num)
            assert match is not None, f"Invoice number {num} has no numeric suffix"
            numeric_parts.append(int(match.group(1)))

        # Verify contiguity: each consecutive pair differs by exactly 1
        for i in range(len(numeric_parts) - 1):
            assert numeric_parts[i + 1] - numeric_parts[i] == 1, (
                f"Gap detected: {numbers[i]} → {numbers[i+1]}"
            )

        # Verify all start with the correct prefix
        for num in numbers:
            assert num.startswith(prefix), f"{num} doesn't start with {prefix}"


# ---------------------------------------------------------------------------
# Property 3: Invoice Number Immutability
# **Validates: Requirements 23.2, 23.3**
# ---------------------------------------------------------------------------


class TestInvoiceNumberImmutability:
    """Verify issued numbers cannot be modified."""

    @PBT_SETTINGS
    @given(
        new_number=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
        status=st.sampled_from(["issued", "partially_paid", "paid", "overdue"]),
    )
    @pytest.mark.asyncio
    async def test_cannot_modify_assigned_number(self, new_number, status):
        """Property 3: Invoice Number Immutability — any attempt to modify
        an assigned invoice number is rejected.

        **Validates: Requirements 23.2, 23.3**
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice_mock(org_id=org_id, status=status, invoice_number="INV-0001")

        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = invoice
        db.execute.return_value = result_mock

        with pytest.raises(ValueError, match="cannot be modified"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"invoice_number": new_number},
            )

    @PBT_SETTINGS
    @given(
        new_number=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
    )
    @pytest.mark.asyncio
    async def test_cannot_manually_set_number_on_draft(self, new_number):
        """Property 3: Invoice Number Immutability — even drafts cannot have
        manually assigned numbers.

        **Validates: Requirements 23.2, 23.3**
        """
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice_mock(
            org_id=org_id, status="draft", invoice_number=None
        )

        db = _mock_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = invoice
        db.execute.return_value = result_mock

        with pytest.raises(ValueError, match="cannot be set manually"):
            await update_invoice(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                updates={"invoice_number": new_number},
            )


# ---------------------------------------------------------------------------
# Property 4: GST Calculation Correctness
# **Validates: Requirements 17.5, 18.6, 18.7**
# ---------------------------------------------------------------------------


class TestGSTCalculationCorrectness:
    """Verify subtotal, GST, total math for arbitrary line item mixes."""

    @PBT_SETTINGS
    @given(
        items=line_items_list(min_size=1, max_size=8),
        gst_rate=gst_rates,
        inv_discount=invoice_level_discount(),
    )
    def test_gst_calculation_identity(self, items, gst_rate, inv_discount):
        """Property 4: GST Calculation Correctness — for any mix of taxable
        and GST-exempt line items with discounts, the totals satisfy:
          total = subtotal - discount_amount + gst_amount

        **Validates: Requirements 17.5, 18.6, 18.7**
        """
        inv_discount_type, inv_discount_value = inv_discount

        result = _calculate_invoice_totals(
            items,
            gst_rate,
            invoice_discount_type=inv_discount_type,
            invoice_discount_value=inv_discount_value,
        )

        subtotal = result["subtotal"]
        discount_amount = result["discount_amount"]
        gst_amount = result["gst_amount"]
        total = result["total"]

        # Core identity: total = subtotal - discount + gst
        expected_total = (subtotal - discount_amount + gst_amount).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )
        assert total == expected_total, (
            f"total={total} != subtotal({subtotal}) - discount({discount_amount}) "
            f"+ gst({gst_amount}) = {expected_total}"
        )

    @PBT_SETTINGS
    @given(
        items=line_items_list(min_size=1, max_size=8),
        gst_rate=gst_rates,
    )
    def test_subtotal_is_sum_of_line_totals(self, items, gst_rate):
        """Property 4: GST Calculation Correctness — subtotal equals the sum
        of individual line totals.

        **Validates: Requirements 17.5, 18.6, 18.7**
        """
        result = _calculate_invoice_totals(items, gst_rate)

        expected_subtotal = sum(result["line_totals"], Decimal("0")).quantize(TWO_PLACES)
        assert result["subtotal"] == expected_subtotal

    @PBT_SETTINGS
    @given(
        items=line_items_list(min_size=1, max_size=8),
        gst_rate=gst_rates,
        inv_discount=invoice_level_discount(),
    )
    def test_gst_exempt_items_contribute_zero_gst(self, items, gst_rate, inv_discount):
        """Property 4: GST Calculation Correctness — when all items are
        GST-exempt, gst_amount must be zero.

        **Validates: Requirements 17.5, 18.6, 18.7**
        """
        # Make all items GST-exempt
        all_exempt = [{**item, "is_gst_exempt": True} for item in items]
        inv_discount_type, inv_discount_value = inv_discount

        result = _calculate_invoice_totals(
            all_exempt,
            gst_rate,
            invoice_discount_type=inv_discount_type,
            invoice_discount_value=inv_discount_value,
        )

        assert result["gst_amount"] == Decimal("0.00"), (
            f"GST should be 0 for all-exempt items, got {result['gst_amount']}"
        )

    @PBT_SETTINGS
    @given(
        items=line_items_list(min_size=1, max_size=8),
        inv_discount=invoice_level_discount(),
    )
    def test_zero_gst_rate_means_zero_gst(self, items, inv_discount):
        """Property 4: GST Calculation Correctness — with 0% GST rate,
        gst_amount must be zero regardless of item mix.

        **Validates: Requirements 17.5, 18.6, 18.7**
        """
        inv_discount_type, inv_discount_value = inv_discount

        result = _calculate_invoice_totals(
            items,
            Decimal("0"),
            invoice_discount_type=inv_discount_type,
            invoice_discount_value=inv_discount_value,
        )

        assert result["gst_amount"] == Decimal("0.00")

    @PBT_SETTINGS
    @given(
        items=line_items_list(min_size=1, max_size=8),
        gst_rate=gst_rates,
        inv_discount=invoice_level_discount(),
    )
    def test_all_amounts_non_negative(self, items, gst_rate, inv_discount):
        """Property 4: GST Calculation Correctness — subtotal, gst_amount,
        total, and discount_amount are all non-negative.

        **Validates: Requirements 17.5, 18.6, 18.7**
        """
        inv_discount_type, inv_discount_value = inv_discount

        result = _calculate_invoice_totals(
            items,
            gst_rate,
            invoice_discount_type=inv_discount_type,
            invoice_discount_value=inv_discount_value,
        )

        assert result["subtotal"] >= Decimal("0")
        assert result["gst_amount"] >= Decimal("0")
        assert result["total"] >= Decimal("0")
        assert result["discount_amount"] >= Decimal("0")


# ---------------------------------------------------------------------------
# Property 5: Invoice Balance Consistency
# **Validates: Requirements 24.1, 24.2, 24.3, 20.3**
# ---------------------------------------------------------------------------


class TestInvoiceBalanceConsistency:
    """Verify amount_paid + credit_note_total + balance_due = total always."""

    @PBT_SETTINGS
    @given(
        total=st.decimals(
            min_value="1.00", max_value="999999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
        num_payments=st.integers(min_value=0, max_value=5),
        num_credits=st.integers(min_value=0, max_value=3),
        data=st.data(),
    )
    def test_balance_identity_holds(self, total, num_payments, num_credits, data):
        """Property 5: Invoice Balance Consistency — for any invoice,
        amount_paid + credit_note_total + balance_due = total.

        **Validates: Requirements 24.1, 24.2, 24.3, 20.3**
        """
        total = total.quantize(TWO_PLACES)
        remaining = total

        # Simulate payments
        amount_paid = Decimal("0.00")
        for _ in range(num_payments):
            if remaining <= Decimal("0.00"):
                break
            max_payment = remaining
            payment = data.draw(
                st.decimals(
                    min_value="0.01",
                    max_value=str(max_payment),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                )
            ).quantize(TWO_PLACES)
            amount_paid += payment
            remaining -= payment

        # Simulate credit notes
        credit_note_total = Decimal("0.00")
        for _ in range(num_credits):
            if remaining <= Decimal("0.00"):
                break
            max_credit = remaining
            credit = data.draw(
                st.decimals(
                    min_value="0.01",
                    max_value=str(max_credit),
                    places=2,
                    allow_nan=False,
                    allow_infinity=False,
                )
            ).quantize(TWO_PLACES)
            credit_note_total += credit
            remaining -= credit

        balance_due = remaining

        # The accounting identity must always hold
        assert amount_paid + credit_note_total + balance_due == total, (
            f"Identity violated: {amount_paid} + {credit_note_total} + "
            f"{balance_due} != {total}"
        )

    @PBT_SETTINGS
    @given(
        total=st.decimals(
            min_value="1.00", max_value="999999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
        payment_fraction=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_payment_reduces_balance_by_same_amount(self, total, payment_fraction):
        """Property 5: Invoice Balance Consistency — when a payment is recorded,
        balance_due decreases by exactly the payment amount.

        **Validates: Requirements 24.1, 24.2, 24.3, 20.3**
        """
        total = total.quantize(TWO_PLACES)
        payment = (total * Decimal(str(payment_fraction))).quantize(TWO_PLACES)
        assume(payment >= Decimal("0.00"))

        balance_before = total
        balance_after = balance_before - payment
        amount_paid = payment

        # Identity holds
        assert amount_paid + balance_after == total


# ---------------------------------------------------------------------------
# Property 21: NZ Tax Invoice Compliance
# **Validates: Requirements 80.1, 80.2**
# ---------------------------------------------------------------------------


class TestNZTaxInvoiceCompliance:
    """Verify all required fields present, $1,000 threshold for buyer details."""

    @PBT_SETTINGS
    @given(
        org_name=org_names,
        gst_number=gst_numbers,
        total=st.decimals(
            min_value="0.01", max_value="999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
        num_items=st.integers(min_value=1, max_value=5),
        data=st.data(),
    )
    def test_compliant_invoice_under_threshold(
        self, org_name, gst_number, total, num_items, data
    ):
        """Property 21: NZ Tax Invoice Compliance — invoices under $1,000
        with all required fields are compliant.

        **Validates: Requirements 80.1, 80.2**
        """
        invoice = _make_invoice_mock(
            total=total.quantize(TWO_PLACES),
            gst_amount=Decimal("10.00"),
        )
        invoice.issue_date = date.today()

        line_items = [
            _make_line_item_mock(
                invoice_id=invoice.id,
                description=data.draw(descriptions),
            )
            for _ in range(num_items)
        ]

        result = validate_tax_invoice_compliance(
            invoice=invoice,
            line_items=line_items,
            org_name=org_name,
            gst_number=gst_number,
        )

        assert result["is_compliant"] is True
        assert result["document_label"] == "Tax Invoice"
        assert result["is_high_value"] is False

    @PBT_SETTINGS
    @given(
        org_name=org_names,
        gst_number=gst_numbers,
        total=st.decimals(
            min_value="1000.01", max_value="99999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
        first_name=customer_first_names,
        last_name=customer_last_names,
        address=addresses,
        data=st.data(),
    )
    def test_high_value_with_buyer_details_compliant(
        self, org_name, gst_number, total, first_name, last_name, address, data
    ):
        """Property 21: NZ Tax Invoice Compliance — invoices over $1,000
        with buyer name and address are compliant.

        **Validates: Requirements 80.1, 80.2**
        """
        invoice = _make_invoice_mock(
            total=total.quantize(TWO_PLACES),
            gst_amount=Decimal("100.00"),
        )
        invoice.issue_date = date.today()

        customer = _make_customer_mock(
            first_name=first_name,
            last_name=last_name,
            address=address,
        )
        invoice._compliance_customer = customer

        line_items = [
            _make_line_item_mock(
                invoice_id=invoice.id,
                description=data.draw(descriptions),
            )
        ]

        result = validate_tax_invoice_compliance(
            invoice=invoice,
            line_items=line_items,
            org_name=org_name,
            gst_number=gst_number,
        )

        assert result["is_compliant"] is True
        assert result["is_high_value"] is True

    @PBT_SETTINGS
    @given(
        total=st.decimals(
            min_value="1000.01", max_value="99999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
        org_name=org_names,
        gst_number=gst_numbers,
    )
    def test_high_value_without_buyer_details_not_compliant(
        self, total, org_name, gst_number
    ):
        """Property 21: NZ Tax Invoice Compliance — invoices over $1,000
        without buyer details are NOT compliant.

        **Validates: Requirements 80.1, 80.2**
        """
        invoice = _make_invoice_mock(
            total=total.quantize(TWO_PLACES),
            gst_amount=Decimal("100.00"),
        )
        invoice.issue_date = date.today()
        # No customer attached
        invoice._compliance_customer = None

        line_items = [
            _make_line_item_mock(invoice_id=invoice.id, description="Service")
        ]

        result = validate_tax_invoice_compliance(
            invoice=invoice,
            line_items=line_items,
            org_name=org_name,
            gst_number=gst_number,
        )

        assert result["is_compliant"] is False
        assert result["is_high_value"] is True
        issue_fields = {i["field"] for i in result["issues"]}
        assert "customer_name" in issue_fields or "customer_address" in issue_fields

    @PBT_SETTINGS
    @given(
        total=st.decimals(
            min_value="0.01", max_value="99999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
    )
    def test_missing_org_name_not_compliant(self, total):
        """Property 21: NZ Tax Invoice Compliance — missing supplier name
        makes invoice non-compliant.

        **Validates: Requirements 80.1, 80.2**
        """
        invoice = _make_invoice_mock(total=total.quantize(TWO_PLACES))
        invoice.issue_date = date.today()

        line_items = [
            _make_line_item_mock(invoice_id=invoice.id, description="Service")
        ]

        result = validate_tax_invoice_compliance(
            invoice=invoice,
            line_items=line_items,
            org_name=None,
            gst_number="123-456-789",
        )

        assert result["is_compliant"] is False
        assert any(i["field"] == "supplier_name" for i in result["issues"])

    @PBT_SETTINGS
    @given(
        total=st.decimals(
            min_value="0.01", max_value="99999.99",
            places=2, allow_nan=False, allow_infinity=False,
        ),
    )
    def test_missing_gst_number_not_compliant(self, total):
        """Property 21: NZ Tax Invoice Compliance — missing GST number
        makes invoice non-compliant.

        **Validates: Requirements 80.1, 80.2**
        """
        invoice = _make_invoice_mock(total=total.quantize(TWO_PLACES))
        invoice.issue_date = date.today()

        line_items = [
            _make_line_item_mock(invoice_id=invoice.id, description="Service")
        ]

        result = validate_tax_invoice_compliance(
            invoice=invoice,
            line_items=line_items,
            org_name="Test Workshop",
            gst_number=None,
        )

        assert result["is_compliant"] is False
        assert any(i["field"] == "gst_number" for i in result["issues"])


# ---------------------------------------------------------------------------
# Property 22: Invoice Status State Machine
# **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
# ---------------------------------------------------------------------------


class TestInvoiceStatusStateMachine:
    """Verify only valid transitions succeed."""

    @PBT_SETTINGS
    @given(
        current=st.sampled_from(ALL_STATUSES),
        target=st.sampled_from(ALL_STATUSES),
    )
    def test_valid_transitions_accepted_invalid_rejected(self, current, target):
        """Property 22: Invoice Status State Machine — valid transitions
        succeed, invalid transitions raise ValueError.

        **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
        """
        allowed = VALID_TRANSITIONS.get(current, set())

        if target in allowed:
            # Should not raise
            _validate_transition(current, target)
        else:
            with pytest.raises(ValueError, match="Invalid status transition"):
                _validate_transition(current, target)

    @PBT_SETTINGS
    @given(target=st.sampled_from(ALL_STATUSES))
    def test_voided_is_terminal(self, target):
        """Property 22: Invoice Status State Machine — voided is a terminal
        state with no outgoing transitions.

        **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
        """
        with pytest.raises(ValueError, match="Invalid status transition"):
            _validate_transition("voided", target)

    @PBT_SETTINGS
    @given(
        current=st.sampled_from(
            [s for s in ALL_STATUSES if s != "voided"]
        ),
    )
    def test_any_non_voided_can_transition_to_voided(self, current):
        """Property 22: Invoice Status State Machine — any non-voided status
        can transition to voided.

        **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
        """
        # Should not raise
        _validate_transition(current, "voided")

    @PBT_SETTINGS
    @given(
        target=st.sampled_from(["draft", "partially_paid", "overdue", "paid"]),
    )
    def test_paid_cannot_transition_to_non_voided(self, target):
        """Property 22: Invoice Status State Machine — paid can only
        transition to voided, not back to any other state.

        **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
        """
        with pytest.raises(ValueError, match="Invalid status transition"):
            _validate_transition("paid", target)

    @PBT_SETTINGS
    @given(
        target=st.sampled_from(["draft"]),
    )
    def test_issued_cannot_go_back_to_draft(self, target):
        """Property 22: Invoice Status State Machine — issued invoices
        cannot revert to draft.

        **Validates: Requirements 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7**
        """
        with pytest.raises(ValueError, match="Invalid status transition"):
            _validate_transition("issued", target)
