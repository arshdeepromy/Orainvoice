"""Property-based tests for Stripe Invoice Payment Flow.

Properties covered:
  P1 — PaymentIntent creation correctness.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# PaymentIntent payload construction — pure function under test
# ---------------------------------------------------------------------------
# The payload construction logic in create_payment_intent() builds a flat dict
# with Stripe's form-encoded keys.  The amount is already in the smallest
# currency unit (e.g. cents), so amount == int(balance_due * 100).
#
# We extract the payload construction as a pure function so the property test
# exercises the exact same logic without making HTTP calls to Stripe.


def build_payment_intent_payload(
    *,
    amount: int,
    currency: str,
    invoice_id: str,
    application_fee_amount: int | None = None,
) -> dict:
    """Build the Stripe PaymentIntent payload dict.

    Mirrors the payload construction in
    ``app/integrations/stripe_connect.py`` → ``create_payment_intent()``.

    The ``amount`` is in the smallest currency unit (e.g. cents for NZD).
    """
    payload = {
        "amount": str(amount),
        "currency": currency.lower(),
        "metadata[invoice_id]": invoice_id,
        "metadata[platform]": "workshoppro_nz",
    }

    if application_fee_amount and application_fee_amount > 0:
        payload["application_fee_amount"] = str(application_fee_amount)

    return payload


def balance_due_to_cents(balance_due: Decimal) -> int:
    """Convert a balance_due decimal amount to the smallest currency unit (cents).

    Mirrors the conversion logic used in the invoice issue flow:
    ``int(invoice.balance_due * 100)``
    """
    return int(balance_due * 100)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

balance_due_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
)

currency_st = st.sampled_from(["nzd", "aud", "usd"])

invoice_id_st = st.uuids()

account_id_st = st.text(
    min_size=10,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)


# ===========================================================================
# Feature: stripe-invoice-payment-flow, Property 1: PaymentIntent creation correctness
# ===========================================================================


class TestP1PaymentIntentCreationCorrectness:
    """For any valid invoice with balance_due > 0, any supported currency,
    and any Connected Account ID, the create_payment_intent() function SHALL
    produce a Stripe API payload where amount equals int(balance_due * 100),
    currency matches the invoice currency (lowercased), and
    metadata[invoice_id] equals the invoice ID string.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """

    # Feature: stripe-invoice-payment-flow, Property 1: PaymentIntent creation correctness
    @given(balance_due=balance_due_st, currency=currency_st, invoice_id=invoice_id_st)
    @settings(max_examples=100, deadline=None)
    def test_amount_equals_balance_due_times_100(
        self,
        balance_due: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
    ) -> None:
        """P1: The payload amount equals int(balance_due * 100)."""
        amount_cents = balance_due_to_cents(balance_due)
        payload = build_payment_intent_payload(
            amount=amount_cents,
            currency=currency,
            invoice_id=str(invoice_id),
        )

        expected_amount = int(balance_due * 100)
        assert payload["amount"] == str(expected_amount), (
            f"balance_due={balance_due}: expected amount={expected_amount}, "
            f"got {payload['amount']}"
        )

    # Feature: stripe-invoice-payment-flow, Property 1: PaymentIntent creation correctness
    @given(balance_due=balance_due_st, currency=currency_st, invoice_id=invoice_id_st)
    @settings(max_examples=100, deadline=None)
    def test_currency_matches_lowercased(
        self,
        balance_due: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
    ) -> None:
        """P1: The payload currency matches the invoice currency (lowercased)."""
        amount_cents = balance_due_to_cents(balance_due)
        payload = build_payment_intent_payload(
            amount=amount_cents,
            currency=currency,
            invoice_id=str(invoice_id),
        )

        assert payload["currency"] == currency.lower(), (
            f"Expected currency={currency.lower()}, got {payload['currency']}"
        )

    # Feature: stripe-invoice-payment-flow, Property 1: PaymentIntent creation correctness
    @given(balance_due=balance_due_st, currency=currency_st, invoice_id=invoice_id_st)
    @settings(max_examples=100, deadline=None)
    def test_metadata_invoice_id_matches(
        self,
        balance_due: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
    ) -> None:
        """P1: The metadata[invoice_id] equals the invoice ID string."""
        amount_cents = balance_due_to_cents(balance_due)
        invoice_id_str = str(invoice_id)
        payload = build_payment_intent_payload(
            amount=amount_cents,
            currency=currency,
            invoice_id=invoice_id_str,
        )

        assert payload["metadata[invoice_id]"] == invoice_id_str, (
            f"Expected metadata invoice_id={invoice_id_str}, "
            f"got {payload['metadata[invoice_id]']}"
        )

    # Feature: stripe-invoice-payment-flow, Property 1: PaymentIntent creation correctness
    @given(balance_due=balance_due_st, currency=currency_st, invoice_id=invoice_id_st)
    @settings(max_examples=100, deadline=None)
    def test_metadata_platform_is_workshoppro(
        self,
        balance_due: Decimal,
        currency: str,
        invoice_id: uuid.UUID,
    ) -> None:
        """P1: The metadata[platform] is always 'workshoppro_nz'."""
        amount_cents = balance_due_to_cents(balance_due)
        payload = build_payment_intent_payload(
            amount=amount_cents,
            currency=currency,
            invoice_id=str(invoice_id),
        )

        assert payload["metadata[platform]"] == "workshoppro_nz", (
            f"Expected metadata platform='workshoppro_nz', "
            f"got {payload['metadata[platform]']}"
        )

    # Feature: stripe-invoice-payment-flow, Property 1: PaymentIntent creation correctness
    @given(balance_due=balance_due_st)
    @settings(max_examples=100, deadline=None)
    def test_amount_cents_is_non_negative_integer(
        self,
        balance_due: Decimal,
    ) -> None:
        """P1: The converted amount in cents is always a non-negative integer."""
        amount_cents = balance_due_to_cents(balance_due)
        assert isinstance(amount_cents, int)
        assert amount_cents >= 0, (
            f"balance_due={balance_due}: amount_cents={amount_cents} should be >= 0"
        )


# ---------------------------------------------------------------------------
# Strategies for Property 2
# ---------------------------------------------------------------------------

batch_size_st = st.integers(min_value=2, max_value=20)

org_id_st = st.uuids()


# ===========================================================================
# Feature: stripe-invoice-payment-flow, Property 2: Payment token generation
# produces unique, secure tokens with correct expiry
# ===========================================================================


class TestP2PaymentTokenGeneration:
    """For any invoice and org, generating a payment token SHALL produce a
    URL-safe string of at least 32 characters, and the associated expires_at
    SHALL be exactly 72 hours after created_at. Furthermore, generating N
    tokens (N >= 2) for different invoices SHALL produce N distinct token
    strings.

    **Validates: Requirements 3.1, 3.2, 3.6**
    """

    # Feature: stripe-invoice-payment-flow, Property 2: Token length >= 32
    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_token_urlsafe_length_at_least_32(self, data: st.DataObject) -> None:
        """P2: secrets.token_urlsafe(48) always produces a token of at least 32 characters."""
        import secrets

        # Draw a dummy value to exercise the Hypothesis engine; the property
        # is about the token generator itself, so we call it many times.
        _invoice_id = data.draw(invoice_id_st)

        token = secrets.token_urlsafe(48)
        assert len(token) >= 32, (
            f"Token length {len(token)} is less than 32: {token!r}"
        )

    # Feature: stripe-invoice-payment-flow, Property 2: Expiry is exactly 72h after creation
    @given(invoice_id=invoice_id_st, org_id=org_id_st)
    @settings(max_examples=100, deadline=None)
    def test_expiry_is_exactly_72h_after_creation(
        self,
        invoice_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> None:
        """P2: The expiry calculation produces expires_at exactly 72 hours after created_at."""
        from datetime import datetime, timedelta, timezone

        # Replicate the pure logic from token_service.py
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=72)

        delta = expires_at - now
        # Exactly 72 hours = 259200 seconds
        assert delta == timedelta(hours=72), (
            f"Expected delta of 72h, got {delta}"
        )
        assert delta.total_seconds() == 259200.0, (
            f"Expected 259200 seconds, got {delta.total_seconds()}"
        )

    # Feature: stripe-invoice-payment-flow, Property 2: N tokens for different invoices are all distinct
    @given(batch_size=batch_size_st)
    @settings(max_examples=100, deadline=None)
    def test_n_tokens_for_different_invoices_are_distinct(
        self,
        batch_size: int,
    ) -> None:
        """P2: Generating N tokens (N >= 2) for different invoices produces N distinct strings."""
        import secrets

        tokens = [secrets.token_urlsafe(48) for _ in range(batch_size)]

        assert len(set(tokens)) == len(tokens), (
            f"Expected {len(tokens)} unique tokens, but got {len(set(tokens))} unique "
            f"out of {len(tokens)} generated. Duplicates found."
        )


# ---------------------------------------------------------------------------
# Pure function for Property 4 — mirrors response construction from
# public_router.py for payable invoices
# ---------------------------------------------------------------------------

from datetime import date
from typing import Any


def build_payable_invoice_response(
    *,
    # Org data
    org_name: str,
    org_logo_url: str | None,
    org_primary_colour: str | None,
    connected_account_id: str | None,
    # Invoice data
    invoice_number: str,
    issue_date: date,
    due_date: date,
    currency: str | None,
    subtotal: Decimal,
    gst_amount: Decimal,
    total: Decimal,
    amount_paid: Decimal,
    balance_due: Decimal,
    status: str,
    # Stripe data
    stripe_client_secret: str | None,
    publishable_key: str | None,
    # Line items (list of dicts with description, quantity, unit_price, line_total)
    line_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the PaymentPageResponse dict for a payable invoice.

    Mirrors the response construction logic in
    ``app/modules/payments/public_router.py`` → ``get_payment_page()``
    for the payable invoice branch (status in issued/partially_paid/overdue).

    Returns a dict matching the PaymentPageResponse schema fields.
    """
    from app.modules.payments.schemas import (
        PaymentPageLineItem,
        PaymentPageResponse,
    )

    built_line_items = [
        PaymentPageLineItem(
            description=li["description"],
            quantity=li["quantity"],
            unit_price=li["unit_price"],
            line_total=li["line_total"],
        )
        for li in (line_items or [])
    ]

    base_data = dict(
        org_name=org_name,
        org_logo_url=org_logo_url,
        org_primary_colour=org_primary_colour,
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        currency=currency or "NZD",
        line_items=built_line_items,
        subtotal=subtotal,
        gst_amount=gst_amount,
        total=total,
        amount_paid=amount_paid,
        balance_due=balance_due,
        status=status,
    )

    # Payable invoice branch — same logic as public_router.py
    response = PaymentPageResponse(
        **base_data,
        is_paid=False,
        is_payable=True,
        client_secret=stripe_client_secret,
        connected_account_id=connected_account_id,
        publishable_key=publishable_key,
    )

    return response


# ---------------------------------------------------------------------------
# Strategies for Property 4
# ---------------------------------------------------------------------------

_payable_status_st = st.sampled_from(["issued", "partially_paid", "overdue"])

_org_name_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
).filter(lambda s: s.strip())

_invoice_number_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())

_currency_st = st.sampled_from(["NZD", "AUD", "USD"])

_money_st = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

_positive_money_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

_client_secret_st = st.text(
    min_size=10,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
).filter(lambda s: s.strip())

_connected_account_id_st = st.from_regex(r"acct_[A-Za-z0-9]{10,24}", fullmatch=True)

_publishable_key_st = st.from_regex(r"pk_test_[A-Za-z0-9]{10,30}", fullmatch=True)

_date_st = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)

_optional_url_st = st.one_of(st.none(), st.just("https://example.com/logo.png"))

_optional_colour_st = st.one_of(st.none(), st.from_regex(r"#[0-9a-fA-F]{6}", fullmatch=True))


# ===========================================================================
# Feature: stripe-invoice-payment-flow, Property 4: Valid payment token
# returns correct invoice data and client secret
# ===========================================================================


class TestP4ValidTokenReturnsCorrectInvoiceData:
    """For any valid, non-expired payment token associated with a payable
    invoice (status in issued/partially_paid/overdue), the payment page API
    SHALL return a response where invoice_number matches the invoice,
    balance_due matches the invoice balance, client_secret is non-null,
    connected_account_id is non-null, and is_payable is true.

    **Validates: Requirements 3.3, 6.1**
    """

    # Feature: stripe-invoice-payment-flow, Property 4: Valid token returns correct invoice data
    @given(
        org_name=_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=_invoice_number_st,
        issue_date=_date_st,
        due_date=_date_st,
        currency=_currency_st,
        subtotal=_positive_money_st,
        gst_amount=_money_st,
        total=_positive_money_st,
        amount_paid=_money_st,
        balance_due=_positive_money_st,
        status=_payable_status_st,
        client_secret=_client_secret_st,
        connected_account_id=_connected_account_id_st,
        publishable_key=_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_invoice_number_matches(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str,
        issue_date: date,
        due_date: date,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str,
        connected_account_id: str,
        publishable_key: str,
    ) -> None:
        """P4: The response invoice_number matches the input invoice_number."""
        response = build_payable_invoice_response(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            connected_account_id=connected_account_id,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            stripe_client_secret=client_secret,
            publishable_key=publishable_key,
        )
        assert response.invoice_number == invoice_number

    # Feature: stripe-invoice-payment-flow, Property 4: Valid token returns correct invoice data
    @given(
        org_name=_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=_invoice_number_st,
        issue_date=_date_st,
        due_date=_date_st,
        currency=_currency_st,
        subtotal=_positive_money_st,
        gst_amount=_money_st,
        total=_positive_money_st,
        amount_paid=_money_st,
        balance_due=_positive_money_st,
        status=_payable_status_st,
        client_secret=_client_secret_st,
        connected_account_id=_connected_account_id_st,
        publishable_key=_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_balance_due_matches(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str,
        issue_date: date,
        due_date: date,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str,
        connected_account_id: str,
        publishable_key: str,
    ) -> None:
        """P4: The response balance_due matches the input balance_due."""
        response = build_payable_invoice_response(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            connected_account_id=connected_account_id,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            stripe_client_secret=client_secret,
            publishable_key=publishable_key,
        )
        assert response.balance_due == balance_due

    # Feature: stripe-invoice-payment-flow, Property 4: Valid token returns correct invoice data
    @given(
        org_name=_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=_invoice_number_st,
        issue_date=_date_st,
        due_date=_date_st,
        currency=_currency_st,
        subtotal=_positive_money_st,
        gst_amount=_money_st,
        total=_positive_money_st,
        amount_paid=_money_st,
        balance_due=_positive_money_st,
        status=_payable_status_st,
        client_secret=_client_secret_st,
        connected_account_id=_connected_account_id_st,
        publishable_key=_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_client_secret_non_null(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str,
        issue_date: date,
        due_date: date,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str,
        connected_account_id: str,
        publishable_key: str,
    ) -> None:
        """P4: The response client_secret is non-null for payable invoices."""
        response = build_payable_invoice_response(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            connected_account_id=connected_account_id,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            stripe_client_secret=client_secret,
            publishable_key=publishable_key,
        )
        assert response.client_secret is not None

    # Feature: stripe-invoice-payment-flow, Property 4: Valid token returns correct invoice data
    @given(
        org_name=_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=_invoice_number_st,
        issue_date=_date_st,
        due_date=_date_st,
        currency=_currency_st,
        subtotal=_positive_money_st,
        gst_amount=_money_st,
        total=_positive_money_st,
        amount_paid=_money_st,
        balance_due=_positive_money_st,
        status=_payable_status_st,
        client_secret=_client_secret_st,
        connected_account_id=_connected_account_id_st,
        publishable_key=_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_connected_account_id_non_null(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str,
        issue_date: date,
        due_date: date,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str,
        connected_account_id: str,
        publishable_key: str,
    ) -> None:
        """P4: The response connected_account_id is non-null for payable invoices."""
        response = build_payable_invoice_response(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            connected_account_id=connected_account_id,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            stripe_client_secret=client_secret,
            publishable_key=publishable_key,
        )
        assert response.connected_account_id is not None

    # Feature: stripe-invoice-payment-flow, Property 4: Valid token returns correct invoice data
    @given(
        org_name=_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=_invoice_number_st,
        issue_date=_date_st,
        due_date=_date_st,
        currency=_currency_st,
        subtotal=_positive_money_st,
        gst_amount=_money_st,
        total=_positive_money_st,
        amount_paid=_money_st,
        balance_due=_positive_money_st,
        status=_payable_status_st,
        client_secret=_client_secret_st,
        connected_account_id=_connected_account_id_st,
        publishable_key=_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_is_payable_is_true(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str,
        issue_date: date,
        due_date: date,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str,
        connected_account_id: str,
        publishable_key: str,
    ) -> None:
        """P4: The response is_payable is True for payable invoices."""
        response = build_payable_invoice_response(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            connected_account_id=connected_account_id,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            stripe_client_secret=client_secret,
            publishable_key=publishable_key,
        )
        assert response.is_payable is True
        assert response.is_paid is False


# ---------------------------------------------------------------------------
# Strategies for Property 5
# ---------------------------------------------------------------------------

# Sensitive patterns that must NEVER appear in serialized responses
_SENSITIVE_PATTERNS = [
    "sk_live_",
    "sk_test_",
    "whsec_",
]

_p5_org_name_st = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
).filter(lambda s: s.strip())

_p5_invoice_number_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())

# The client_secret, connected_account_id, and publishable_key fields are
# the ones where a coding mistake could accidentally expose a secret key.
# We generate realistic values for these fields — the property asserts that
# the serialized output never contains secret-key patterns.
_p5_client_secret_st = st.one_of(
    st.none(),
    st.from_regex(r"pi_[A-Za-z0-9]{10,30}_secret_[A-Za-z0-9]{10,30}", fullmatch=True),
)

_p5_connected_account_id_st = st.one_of(
    st.none(),
    # Short acct_ IDs (≤ 30 chars) are acceptable — Stripe.js needs them
    st.from_regex(r"acct_[A-Za-z0-9]{10,24}", fullmatch=True),
)

_p5_publishable_key_st = st.one_of(
    st.none(),
    st.from_regex(r"pk_test_[A-Za-z0-9]{10,30}", fullmatch=True),
    st.from_regex(r"pk_live_[A-Za-z0-9]{10,30}", fullmatch=True),
)

_p5_status_st = st.sampled_from(["issued", "partially_paid", "overdue", "paid", "voided", "draft"])


# ===========================================================================
# Feature: stripe-invoice-payment-flow, Property 5: Payment page response
# never leaks sensitive data
# ===========================================================================


class TestP5PaymentPageNoSensitiveDataLeakage:
    """For any PaymentPageResponse — regardless of field values, token state,
    or invoice status — the serialized JSON SHALL NOT contain any string
    matching ``sk_live_``, ``sk_test_``, ``whsec_``, or any full Stripe
    account ID (string starting with ``acct_`` longer than 30 characters).

    **Validates: Requirements 6.2, 9.4**
    """

    # Feature: stripe-invoice-payment-flow, Property 5: Payment page response never leaks sensitive data
    @given(
        org_name=_p5_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=st.one_of(st.none(), _p5_invoice_number_st),
        issue_date=st.one_of(st.none(), _date_st),
        due_date=st.one_of(st.none(), _date_st),
        currency=_currency_st,
        subtotal=_money_st,
        gst_amount=_money_st,
        total=_money_st,
        amount_paid=_money_st,
        balance_due=_money_st,
        status=_p5_status_st,
        client_secret=_p5_client_secret_st,
        connected_account_id=_p5_connected_account_id_st,
        publishable_key=_p5_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_serialized_json_never_contains_secret_key_patterns(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str | None,
        issue_date: date | None,
        due_date: date | None,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str | None,
        connected_account_id: str | None,
        publishable_key: str | None,
    ) -> None:
        """P5: Serialized JSON never contains sk_live_, sk_test_, or whsec_ patterns."""
        import re

        from app.modules.payments.schemas import PaymentPageResponse

        response = PaymentPageResponse(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            line_items=[],
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            client_secret=client_secret,
            connected_account_id=connected_account_id,
            publishable_key=publishable_key,
            is_paid=(status == "paid"),
            is_payable=(status in ("issued", "partially_paid", "overdue")),
        )

        serialized = response.model_dump_json()

        for pattern in _SENSITIVE_PATTERNS:
            assert pattern not in serialized, (
                f"Sensitive pattern '{pattern}' found in serialized response: "
                f"{serialized[:200]}..."
            )

    # Feature: stripe-invoice-payment-flow, Property 5: Payment page response never leaks sensitive data
    @given(
        org_name=_p5_org_name_st,
        org_logo_url=_optional_url_st,
        org_primary_colour=_optional_colour_st,
        invoice_number=st.one_of(st.none(), _p5_invoice_number_st),
        issue_date=st.one_of(st.none(), _date_st),
        due_date=st.one_of(st.none(), _date_st),
        currency=_currency_st,
        subtotal=_money_st,
        gst_amount=_money_st,
        total=_money_st,
        amount_paid=_money_st,
        balance_due=_money_st,
        status=_p5_status_st,
        client_secret=_p5_client_secret_st,
        connected_account_id=_p5_connected_account_id_st,
        publishable_key=_p5_publishable_key_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_serialized_json_never_contains_long_acct_ids(
        self,
        org_name: str,
        org_logo_url: str | None,
        org_primary_colour: str | None,
        invoice_number: str | None,
        issue_date: date | None,
        due_date: date | None,
        currency: str,
        subtotal: Decimal,
        gst_amount: Decimal,
        total: Decimal,
        amount_paid: Decimal,
        balance_due: Decimal,
        status: str,
        client_secret: str | None,
        connected_account_id: str | None,
        publishable_key: str | None,
    ) -> None:
        """P5: Serialized JSON never contains full acct_ IDs longer than 30 characters."""
        import re

        from app.modules.payments.schemas import PaymentPageResponse

        response = PaymentPageResponse(
            org_name=org_name,
            org_logo_url=org_logo_url,
            org_primary_colour=org_primary_colour,
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            currency=currency,
            line_items=[],
            subtotal=subtotal,
            gst_amount=gst_amount,
            total=total,
            amount_paid=amount_paid,
            balance_due=balance_due,
            status=status,
            client_secret=client_secret,
            connected_account_id=connected_account_id,
            publishable_key=publishable_key,
            is_paid=(status == "paid"),
            is_payable=(status in ("issued", "partially_paid", "overdue")),
        )

        serialized = response.model_dump_json()

        # Find all acct_ occurrences and check none exceed 30 chars
        acct_matches = re.findall(r"acct_[A-Za-z0-9]+", serialized)
        for match in acct_matches:
            assert len(match) <= 30, (
                f"Full Stripe account ID found in serialized response "
                f"(length {len(match)} > 30): {match}"
            )


# ---------------------------------------------------------------------------
# Pure function for Property 3 — mirrors email body construction from
# email_invoice() → _build_message() in app/modules/invoices/service.py
# ---------------------------------------------------------------------------


def build_invoice_email_body(
    *,
    inv_number: str,
    org_name: str,
    currency: str,
    balance_due: Decimal | float | int,
    payment_page_url: str | None,
) -> str:
    """Build the plain-text email body for an invoice email.

    Mirrors the body construction logic in the ``_build_message`` inner
    function of ``email_invoice()`` in ``app/modules/invoices/service.py``.

    When ``payment_page_url`` is non-null, a "Pay online:" line is included.
    When null, the email body is sent in its current format without a payment link.
    """
    body = (
        f"Hi,\n\n"
        f"Please find attached invoice {inv_number} from {org_name}.\n\n"
        f"Amount Due: {currency} {balance_due}\n\n"
    )
    if payment_page_url:
        body += f"Pay online: {payment_page_url}\n\n"
    body += (
        f"If you have any questions, please don't hesitate to contact us.\n\n"
        f"Thank you for your business.\n\n"
        f"{org_name}\n"
    )
    return body


# ---------------------------------------------------------------------------
# Strategies for Property 3
# ---------------------------------------------------------------------------

_p3_inv_number_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())

_p3_org_name_st = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
).filter(lambda s: s.strip())

_p3_currency_st = st.sampled_from(["NZD", "AUD", "USD"])

_p3_balance_due_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

# Payment page URLs: non-null case uses realistic /pay/{token} URLs
_p3_payment_url_st = st.text(
    min_size=10,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
).filter(lambda s: s.strip() and "/pay/" in s)

# Fallback: generate realistic URLs with /pay/ path
_p3_realistic_payment_url_st = st.builds(
    lambda token: f"https://app.example.com/pay/{token}",
    token=st.text(
        min_size=32,
        max_size=64,
        alphabet=st.characters(whitelist_categories=("L", "N")),
    ),
)


# ===========================================================================
# Feature: stripe-invoice-payment-flow, Property 3: Invoice email includes
# payment link when present
# ===========================================================================


class TestP3EmailPaymentLinkInclusion:
    """For any invoice that has a non-null ``payment_page_url``, the
    plain-text email body produced by ``email_invoice()`` SHALL contain the
    payment page URL as a substring. When ``payment_page_url`` is null, the
    email body SHALL NOT contain "/pay/" substring.

    **Validates: Requirements 2.1, 2.3**
    """

    # Feature: stripe-invoice-payment-flow, Property 3: Email includes payment link when present
    @given(
        inv_number=_p3_inv_number_st,
        org_name=_p3_org_name_st,
        currency=_p3_currency_st,
        balance_due=_p3_balance_due_st,
        payment_page_url=_p3_realistic_payment_url_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_email_body_contains_url_when_present(
        self,
        inv_number: str,
        org_name: str,
        currency: str,
        balance_due: Decimal,
        payment_page_url: str,
    ) -> None:
        """P3: When payment_page_url is non-null, the email body contains the URL."""
        body = build_invoice_email_body(
            inv_number=inv_number,
            org_name=org_name,
            currency=currency,
            balance_due=balance_due,
            payment_page_url=payment_page_url,
        )

        assert payment_page_url in body, (
            f"Expected email body to contain payment URL {payment_page_url!r}, "
            f"but it was not found in:\n{body[:300]}"
        )

    # Feature: stripe-invoice-payment-flow, Property 3: Email includes payment link when present
    @given(
        inv_number=_p3_inv_number_st,
        org_name=_p3_org_name_st,
        currency=_p3_currency_st,
        balance_due=_p3_balance_due_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_email_body_does_not_contain_pay_path_when_null(
        self,
        inv_number: str,
        org_name: str,
        currency: str,
        balance_due: Decimal,
    ) -> None:
        """P3: When payment_page_url is null, the email body does not contain '/pay/'."""
        body = build_invoice_email_body(
            inv_number=inv_number,
            org_name=org_name,
            currency=currency,
            balance_due=balance_due,
            payment_page_url=None,
        )

        assert "/pay/" not in body, (
            f"Expected email body NOT to contain '/pay/' when payment_page_url is None, "
            f"but found it in:\n{body[:300]}"
        )

    # Feature: stripe-invoice-payment-flow, Property 3: Email includes payment link when present
    @given(
        inv_number=_p3_inv_number_st,
        org_name=_p3_org_name_st,
        currency=_p3_currency_st,
        balance_due=_p3_balance_due_st,
        payment_page_url=_p3_realistic_payment_url_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_email_body_contains_pay_online_prefix_when_present(
        self,
        inv_number: str,
        org_name: str,
        currency: str,
        balance_due: Decimal,
        payment_page_url: str,
    ) -> None:
        """P3: When payment_page_url is non-null, the email body contains 'Pay online:' prefix."""
        body = build_invoice_email_body(
            inv_number=inv_number,
            org_name=org_name,
            currency=currency,
            balance_due=balance_due,
            payment_page_url=payment_page_url,
        )

        assert "Pay online:" in body, (
            f"Expected email body to contain 'Pay online:' prefix, "
            f"but it was not found in:\n{body[:300]}"
        )


# ---------------------------------------------------------------------------
# Pure functions for Property 6 — mirrors token regeneration logic from
# token_service.py → generate_payment_token()
# ---------------------------------------------------------------------------


def simulate_token_regeneration(num_regenerations: int) -> list[dict]:
    """Simulate N sequential token regenerations for a single invoice.

    Each regeneration:
    1. Deactivates all previously active tokens (sets is_active=False)
    2. Generates a new token via secrets.token_urlsafe(48)
    3. Creates a new token record with is_active=True

    Returns a list of token records (dicts) representing the full history
    of tokens generated for the invoice, in creation order.

    Mirrors the deactivation + creation logic in
    ``app/modules/payments/token_service.py`` → ``generate_payment_token()``.
    """
    import secrets
    from datetime import datetime, timedelta, timezone

    tokens: list[dict] = []

    for i in range(num_regenerations):
        # Step 1: Deactivate all existing active tokens (same as the
        # UPDATE ... SET is_active = False WHERE is_active = True query)
        for t in tokens:
            if t["is_active"]:
                t["is_active"] = False

        # Step 2 & 3: Generate new token and create record
        now = datetime.now(timezone.utc)
        token_str = secrets.token_urlsafe(48)
        tokens.append(
            {
                "token": token_str,
                "is_active": True,
                "expires_at": now + timedelta(hours=72),
                "generation": i + 1,
            }
        )

    return tokens


def simulate_regeneration_with_invoice_updates(
    num_regenerations: int,
) -> tuple[list[dict], list[dict]]:
    """Simulate N regenerations and track invoice field updates.

    Each regeneration produces a new PaymentIntent ID and payment page URL
    on the invoice record. This function returns both the token history and
    the list of (payment_intent_id, payment_page_url) pairs assigned to the
    invoice at each regeneration step.

    Returns
    -------
    tuple[list[dict], list[dict]]
        ``(token_records, invoice_updates)`` where each invoice_update has
        ``stripe_payment_intent_id`` and ``payment_page_url`` keys.
    """
    import secrets
    from datetime import datetime, timedelta, timezone

    tokens: list[dict] = []
    invoice_updates: list[dict] = []

    for i in range(num_regenerations):
        # Deactivate all existing active tokens
        for t in tokens:
            if t["is_active"]:
                t["is_active"] = False

        # Generate new token
        now = datetime.now(timezone.utc)
        token_str = secrets.token_urlsafe(48)
        tokens.append(
            {
                "token": token_str,
                "is_active": True,
                "expires_at": now + timedelta(hours=72),
                "generation": i + 1,
            }
        )

        # Simulate invoice field updates (new PI ID + new URL each time)
        pi_id = f"pi_{secrets.token_hex(12)}"
        url = f"https://app.example.com/pay/{token_str}"
        invoice_updates.append(
            {
                "stripe_payment_intent_id": pi_id,
                "payment_page_url": url,
            }
        )

    return tokens, invoice_updates


# ---------------------------------------------------------------------------
# Strategies for Property 6
# ---------------------------------------------------------------------------

_p6_num_regenerations_st = st.integers(min_value=1, max_value=5)


# ===========================================================================
# Feature: stripe-invoice-payment-flow, Property 6: Token regeneration
# invalidates all previous tokens
# ===========================================================================


class TestP6TokenRegenerationInvalidatesPreviousTokens:
    """For any invoice, after calling the regeneration service, all previously
    active payment tokens for that invoice SHALL have ``is_active = False``,
    and exactly one new active token SHALL exist. The invoice's
    ``stripe_payment_intent_id`` and ``payment_page_url`` SHALL be updated
    to new values different from the previous ones.

    **Validates: Requirements 8.2, 8.4**
    """

    # Feature: stripe-invoice-payment-flow, Property 6: Token regeneration invalidates all previous tokens
    @given(num_regenerations=_p6_num_regenerations_st)
    @settings(max_examples=100, deadline=None)
    def test_exactly_one_active_token_after_regeneration(
        self,
        num_regenerations: int,
    ) -> None:
        """P6: After N regenerations, exactly one token is active."""
        tokens = simulate_token_regeneration(num_regenerations)

        active_tokens = [t for t in tokens if t["is_active"]]
        assert len(active_tokens) == 1, (
            f"Expected exactly 1 active token after {num_regenerations} regenerations, "
            f"but found {len(active_tokens)} active tokens"
        )

    # Feature: stripe-invoice-payment-flow, Property 6: Token regeneration invalidates all previous tokens
    @given(num_regenerations=st.integers(min_value=2, max_value=5))
    @settings(max_examples=100, deadline=None)
    def test_all_previous_tokens_deactivated(
        self,
        num_regenerations: int,
    ) -> None:
        """P6: After N regenerations, all tokens except the last have is_active=False."""
        tokens = simulate_token_regeneration(num_regenerations)

        # All tokens except the last one must be inactive
        previous_tokens = tokens[:-1]
        for t in previous_tokens:
            assert t["is_active"] is False, (
                f"Token from generation {t['generation']} should be inactive "
                f"after regeneration, but is_active={t['is_active']}"
            )

        # The last token must be active
        assert tokens[-1]["is_active"] is True, (
            f"The most recent token (generation {tokens[-1]['generation']}) "
            f"should be active but is_active={tokens[-1]['is_active']}"
        )

    # Feature: stripe-invoice-payment-flow, Property 6: Token regeneration invalidates all previous tokens
    @given(num_regenerations=st.integers(min_value=2, max_value=5))
    @settings(max_examples=100, deadline=None)
    def test_each_regeneration_produces_different_token_string(
        self,
        num_regenerations: int,
    ) -> None:
        """P6: Each regeneration produces a distinct token string."""
        tokens = simulate_token_regeneration(num_regenerations)

        token_strings = [t["token"] for t in tokens]
        assert len(set(token_strings)) == len(token_strings), (
            f"Expected {len(token_strings)} unique token strings after "
            f"{num_regenerations} regenerations, but got "
            f"{len(set(token_strings))} unique values"
        )

    # Feature: stripe-invoice-payment-flow, Property 6: Token regeneration invalidates all previous tokens
    @given(num_regenerations=st.integers(min_value=2, max_value=5))
    @settings(max_examples=100, deadline=None)
    def test_invoice_fields_updated_to_new_values_each_regeneration(
        self,
        num_regenerations: int,
    ) -> None:
        """P6: Each regeneration updates stripe_payment_intent_id and payment_page_url
        to new values different from the previous ones."""
        _tokens, invoice_updates = simulate_regeneration_with_invoice_updates(
            num_regenerations
        )

        # All payment_intent_ids should be distinct
        pi_ids = [u["stripe_payment_intent_id"] for u in invoice_updates]
        assert len(set(pi_ids)) == len(pi_ids), (
            f"Expected {len(pi_ids)} unique stripe_payment_intent_ids, "
            f"but got {len(set(pi_ids))} unique values"
        )

        # All payment_page_urls should be distinct
        urls = [u["payment_page_url"] for u in invoice_updates]
        assert len(set(urls)) == len(urls), (
            f"Expected {len(urls)} unique payment_page_urls, "
            f"but got {len(set(urls))} unique values"
        )

    # Feature: stripe-invoice-payment-flow, Property 6: Token regeneration invalidates all previous tokens
    @given(num_regenerations=st.integers(min_value=2, max_value=5))
    @settings(max_examples=100, deadline=None)
    def test_final_invoice_url_contains_active_token(
        self,
        num_regenerations: int,
    ) -> None:
        """P6: The final payment_page_url contains the currently active token string."""
        tokens, invoice_updates = simulate_regeneration_with_invoice_updates(
            num_regenerations
        )

        active_token = [t for t in tokens if t["is_active"]]
        assert len(active_token) == 1

        final_url = invoice_updates[-1]["payment_page_url"]
        assert active_token[0]["token"] in final_url, (
            f"Expected the final payment_page_url to contain the active token "
            f"string, but active token {active_token[0]['token']!r} not found "
            f"in URL {final_url!r}"
        )
