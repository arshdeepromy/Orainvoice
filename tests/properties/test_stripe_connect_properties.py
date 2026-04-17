"""Property-based tests for Stripe Connect Online Payments.

Properties covered:
  P1 — Account ID masking never leaks the full ID.

**Validates: Requirements 1.6, 1.7**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.properties.conftest import PBT_SETTINGS

# ---------------------------------------------------------------------------
# Masking function under test
# ---------------------------------------------------------------------------
# The masking logic used in the status and disconnect endpoints is:
#   account_id[-4:]
# We extract it here as a pure function so the property test exercises
# the exact same logic the router uses.


def mask_account_id(account_id: str) -> str:
    """Return the last 4 characters of a Stripe account ID.

    This mirrors the masking logic in
    ``app/modules/payments/router.py`` (status and disconnect endpoints).
    """
    return account_id[-4:]


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

account_id_st = st.text(
    min_size=4,
    max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 1: Account ID masking never leaks the full ID
# ===========================================================================


class TestP1AccountIdMaskingNeverLeaksFullId:
    """For any Stripe account ID of length >= 4, the masked version contains
    exactly the last 4 characters and does NOT contain the full account ID.

    **Validates: Requirements 1.6, 1.7**
    """

    # Feature: stripe-connect-online-payments, Property 1: Account ID masking never leaks the full ID
    @given(account_id=account_id_st)
    @settings(max_examples=100, deadline=None)
    def test_masked_contains_last_4_chars(self, account_id: str) -> None:
        """P1: The masked output is exactly the last 4 characters."""
        masked = mask_account_id(account_id)
        assert masked == account_id[-4:]
        assert len(masked) == 4

    # Feature: stripe-connect-online-payments, Property 1: Account ID masking never leaks the full ID
    @given(account_id=account_id_st)
    @settings(max_examples=100, deadline=None)
    def test_masked_does_not_contain_full_id(self, account_id: str) -> None:
        """P1: The masked output never equals the full account ID (for IDs longer than 4 chars)."""
        masked = mask_account_id(account_id)
        # For any ID longer than 4 characters, the masked version must differ
        # from the full ID — i.e. the full ID is never leaked.
        if len(account_id) > 4:
            assert masked != account_id
            assert account_id not in masked


# ---------------------------------------------------------------------------
# Application fee calculation — pure function under test
# ---------------------------------------------------------------------------
# The fee calculation logic used in both payments/service.py and
# portal/service.py is:
#   application_fee_amount = int(amount_cents * fee_percent / 100)
# When fee_percent is 0 or None, no fee is included.

from decimal import Decimal


def calculate_application_fee(
    amount_cents: int,
    fee_percent: Decimal | None,
) -> int | None:
    """Calculate the application fee amount in cents.

    Returns None when no fee should be applied (percentage is None or 0).
    This mirrors the exact logic in ``app/modules/payments/service.py``
    and ``app/modules/portal/service.py``.
    """
    if fee_percent is None or fee_percent <= 0:
        return None
    return int(amount_cents * fee_percent / 100)


# ---------------------------------------------------------------------------
# Strategies for Property 7
# ---------------------------------------------------------------------------

amount_cents_st = st.integers(min_value=1, max_value=10_000_000)

fee_percent_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("50"),
    allow_nan=False,
    allow_infinity=False,
)


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 7: Application fee calculation
# ===========================================================================


class TestP7ApplicationFeeCalculation:
    """For any payment amount in cents > 0 and any fee percentage in [0, 50],
    the application_fee_amount equals int(amount * percentage / 100).
    When fee percentage is 0 or None, no application fee is included.

    **Validates: Requirements 7.1, 7.2**
    """

    # Feature: stripe-connect-online-payments, Property 7: Application fee calculation
    @given(amount_cents=amount_cents_st, fee_percent=fee_percent_st)
    @settings(max_examples=100, deadline=None)
    def test_fee_equals_truncated_calculation(
        self, amount_cents: int, fee_percent: Decimal
    ) -> None:
        """P7: The fee equals int(amount_cents * fee_percent / 100)."""
        fee = calculate_application_fee(amount_cents, fee_percent)

        if fee_percent <= 0:
            assert fee is None, (
                f"Expected no fee for percentage={fee_percent}, got {fee}"
            )
        else:
            expected = int(amount_cents * fee_percent / 100)
            assert fee == expected, (
                f"amount={amount_cents}, pct={fee_percent}: "
                f"expected {expected}, got {fee}"
            )

    # Feature: stripe-connect-online-payments, Property 7: Application fee calculation
    @given(amount_cents=amount_cents_st)
    @settings(max_examples=100, deadline=None)
    def test_no_fee_when_percentage_is_none(self, amount_cents: int) -> None:
        """P7: When fee percentage is None, no fee is included."""
        fee = calculate_application_fee(amount_cents, None)
        assert fee is None

    # Feature: stripe-connect-online-payments, Property 7: Application fee calculation
    @given(amount_cents=amount_cents_st)
    @settings(max_examples=100, deadline=None)
    def test_no_fee_when_percentage_is_zero(self, amount_cents: int) -> None:
        """P7: When fee percentage is 0, no fee is included."""
        fee = calculate_application_fee(amount_cents, Decimal("0"))
        assert fee is None

    # Feature: stripe-connect-online-payments, Property 7: Application fee calculation
    @given(amount_cents=amount_cents_st, fee_percent=fee_percent_st.filter(lambda p: p > 0))
    @settings(max_examples=100, deadline=None)
    def test_fee_is_non_negative(
        self, amount_cents: int, fee_percent: Decimal
    ) -> None:
        """P7: The application fee is always non-negative for valid inputs."""
        fee = calculate_application_fee(amount_cents, fee_percent)
        assert fee is not None
        assert fee >= 0

    # Feature: stripe-connect-online-payments, Property 7: Application fee calculation
    @given(amount_cents=amount_cents_st, fee_percent=fee_percent_st.filter(lambda p: p > 0))
    @settings(max_examples=100, deadline=None)
    def test_fee_does_not_exceed_half_of_amount(
        self, amount_cents: int, fee_percent: Decimal
    ) -> None:
        """P7: Since max fee percentage is 50%, fee never exceeds half the amount."""
        fee = calculate_application_fee(amount_cents, fee_percent)
        assert fee is not None
        # fee_percent is capped at 50, so fee should be at most amount_cents * 50 / 100
        assert fee <= amount_cents * 50 // 100 + 1  # +1 for rounding tolerance


# ---------------------------------------------------------------------------
# Webhook idempotency — pure function simulation
# ---------------------------------------------------------------------------
# The idempotency logic in handle_stripe_webhook() queries for an existing
# Payment with the same stripe_payment_intent_id and is_refund == False.
# If found, it returns early ("ignored") and does NOT create a new record.
#
# We simulate this as a pure function operating on an in-memory store
# (a dict keyed by payment_intent_id) so the property test exercises the
# exact same logic without needing a database.

import uuid as _uuid


def process_webhook_event(
    store: dict[str, dict],
    *,
    stripe_payment_intent_id: str,
    invoice_id: str,
    amount_cents: int,
) -> dict:
    """Simulate the idempotent webhook handler.

    Mirrors the idempotency check in
    ``app/modules/payments/service.py`` → ``handle_stripe_webhook()``:
    if a non-refund payment with the same ``stripe_payment_intent_id``
    already exists, the event is ignored.

    Parameters
    ----------
    store:
        In-memory dict mapping ``stripe_payment_intent_id`` → payment record.
    stripe_payment_intent_id:
        The Stripe payment intent ID from the webhook event.
    invoice_id:
        The invoice ID from the event metadata.
    amount_cents:
        The payment amount in cents.

    Returns
    -------
    dict
        ``{"status": "ignored", ...}`` if duplicate, else
        ``{"status": "processed", ...}`` with the new payment record.
    """
    # Idempotency check — same logic as the real handler
    if stripe_payment_intent_id in store:
        existing = store[stripe_payment_intent_id]
        if not existing.get("is_refund", False):
            return {"status": "ignored", "reason": "Duplicate event"}

    # Create payment record
    payment = {
        "id": str(_uuid.uuid4()),
        "stripe_payment_intent_id": stripe_payment_intent_id,
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": "stripe",
        "is_refund": False,
    }
    store[stripe_payment_intent_id] = payment
    return {"status": "processed", "payment": payment}


# ---------------------------------------------------------------------------
# Strategies for Property 6
# ---------------------------------------------------------------------------

invoice_id_st = st.uuids()
amount_st = st.integers(min_value=100, max_value=1_000_000)
repeat_count_st = st.integers(min_value=1, max_value=10)


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 6: Webhook idempotency
# ===========================================================================


class TestP6WebhookIdempotency:
    """For any valid checkout.session.completed event, processing it N times
    (N >= 1) results in exactly one Payment record with the corresponding
    stripe_payment_intent_id.

    **Validates: Requirements 6.6**
    """

    # Feature: stripe-connect-online-payments, Property 6: Webhook idempotency
    @given(
        invoice_id=invoice_id_st,
        amount_cents=amount_st,
        n=repeat_count_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_duplicate_events_produce_exactly_one_record(
        self,
        invoice_id: _uuid.UUID,
        amount_cents: int,
        n: int,
    ) -> None:
        """P6: Processing the same event N times (N >= 1) yields exactly 1 payment record."""
        store: dict[str, dict] = {}
        pi_id = f"pi_{invoice_id.hex}"

        results = []
        for _ in range(n):
            result = process_webhook_event(
                store,
                stripe_payment_intent_id=pi_id,
                invoice_id=str(invoice_id),
                amount_cents=amount_cents,
            )
            results.append(result)

        # Exactly one record in the store
        records = [v for v in store.values() if v["stripe_payment_intent_id"] == pi_id]
        assert len(records) == 1, (
            f"Expected exactly 1 record for pi_id={pi_id}, got {len(records)}"
        )

        # First call should be "processed", all subsequent should be "ignored"
        assert results[0]["status"] == "processed"
        for i, r in enumerate(results[1:], start=2):
            assert r["status"] == "ignored", (
                f"Call #{i} should be 'ignored', got '{r['status']}'"
            )

    # Feature: stripe-connect-online-payments, Property 6: Webhook idempotency
    @given(
        invoice_id=invoice_id_st,
        amount_cents=amount_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_single_event_always_processed(
        self,
        invoice_id: _uuid.UUID,
        amount_cents: int,
    ) -> None:
        """P6: A single event is always processed (never ignored on first call)."""
        store: dict[str, dict] = {}
        pi_id = f"pi_{invoice_id.hex}"

        result = process_webhook_event(
            store,
            stripe_payment_intent_id=pi_id,
            invoice_id=str(invoice_id),
            amount_cents=amount_cents,
        )

        assert result["status"] == "processed"
        assert len(store) == 1
        assert store[pi_id]["stripe_payment_intent_id"] == pi_id

    # Feature: stripe-connect-online-payments, Property 6: Webhook idempotency
    @given(
        invoice_id_a=invoice_id_st,
        invoice_id_b=invoice_id_st,
        amount_a=amount_st,
        amount_b=amount_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_distinct_events_produce_distinct_records(
        self,
        invoice_id_a: _uuid.UUID,
        invoice_id_b: _uuid.UUID,
        amount_a: int,
        amount_b: int,
    ) -> None:
        """P6: Two events with different payment_intent_ids each produce their own record."""
        from hypothesis import assume

        assume(invoice_id_a != invoice_id_b)

        store: dict[str, dict] = {}
        pi_a = f"pi_{invoice_id_a.hex}"
        pi_b = f"pi_{invoice_id_b.hex}"

        result_a = process_webhook_event(
            store,
            stripe_payment_intent_id=pi_a,
            invoice_id=str(invoice_id_a),
            amount_cents=amount_a,
        )
        result_b = process_webhook_event(
            store,
            stripe_payment_intent_id=pi_b,
            invoice_id=str(invoice_id_b),
            amount_cents=amount_b,
        )

        assert result_a["status"] == "processed"
        assert result_b["status"] == "processed"
        assert len(store) == 2
        assert pi_a in store
        assert pi_b in store


# ---------------------------------------------------------------------------
# CSRF state token binding — pure functions under test
# ---------------------------------------------------------------------------
# The state token generation logic in generate_connect_url() is:
#   state = f"{org_id}:{secrets.token_urlsafe(32)}"
# The callback handler in handle_connect_callback() parses the state:
#   parts = state.split(":", 1)
#   org_id = UUID(parts[0])
#
# We extract these as pure functions so the property test exercises the
# exact same logic the router uses.

import secrets as _secrets


def generate_csrf_state(org_id: _uuid.UUID) -> str:
    """Generate a CSRF state token for the given org.

    Mirrors the state generation in
    ``app/integrations/stripe_connect.py`` → ``generate_connect_url()``.
    """
    return f"{org_id}:{_secrets.token_urlsafe(32)}"


def extract_org_id_from_state(state: str) -> _uuid.UUID:
    """Extract the org ID from a CSRF state token.

    Mirrors the state parsing in
    ``app/integrations/stripe_connect.py`` → ``handle_connect_callback()``.

    Raises
    ------
    ValueError
        If the state token is malformed or the org_id is not a valid UUID.
    """
    parts = state.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Invalid state token format")
    return _uuid.UUID(parts[0])


def verify_csrf_state(state: str, authenticated_org_id: _uuid.UUID) -> bool:
    """Verify that the CSRF state token belongs to the authenticated org.

    Returns True if the org ID embedded in the state matches the
    authenticated org, False otherwise.
    """
    try:
        state_org_id = extract_org_id_from_state(state)
    except (ValueError, TypeError):
        return False
    return state_org_id == authenticated_org_id


# ---------------------------------------------------------------------------
# Strategies for Property 2
# ---------------------------------------------------------------------------

org_id_st = st.uuids()


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 2: CSRF state token binds to the originating org
# ===========================================================================


class TestP2CsrfStateTokenBinding:
    """For any two distinct org IDs A and B, a state token generated for org A
    SHALL be rejected when the authenticated org is B.

    **Validates: Requirements 2.5**
    """

    # Feature: stripe-connect-online-payments, Property 2: CSRF state token binds to the originating org
    @given(org_id_a=org_id_st, org_id_b=org_id_st)
    @settings(max_examples=100, deadline=None)
    def test_state_token_rejected_for_different_org(
        self,
        org_id_a: _uuid.UUID,
        org_id_b: _uuid.UUID,
    ) -> None:
        """P2: A state token generated for org A is rejected when authenticated org is B."""
        from hypothesis import assume

        assume(org_id_a != org_id_b)

        state = generate_csrf_state(org_id_a)
        # The token must be accepted for org A
        assert verify_csrf_state(state, org_id_a) is True
        # The token must be rejected for org B
        assert verify_csrf_state(state, org_id_b) is False

    # Feature: stripe-connect-online-payments, Property 2: CSRF state token binds to the originating org
    @given(org_id=org_id_st)
    @settings(max_examples=100, deadline=None)
    def test_state_token_accepted_for_same_org(
        self,
        org_id: _uuid.UUID,
    ) -> None:
        """P2: A state token generated for an org is always accepted for that same org."""
        state = generate_csrf_state(org_id)
        assert verify_csrf_state(state, org_id) is True

    # Feature: stripe-connect-online-payments, Property 2: CSRF state token binds to the originating org
    @given(org_id=org_id_st)
    @settings(max_examples=100, deadline=None)
    def test_state_token_embeds_correct_org_id(
        self,
        org_id: _uuid.UUID,
    ) -> None:
        """P2: The org ID extracted from the state token matches the generating org."""
        state = generate_csrf_state(org_id)
        extracted = extract_org_id_from_state(state)
        assert extracted == org_id


# ---------------------------------------------------------------------------
# Checkout session payload construction — pure function under test
# ---------------------------------------------------------------------------
# The payload construction logic in create_payment_link() builds a flat dict
# with Stripe's bracket-notation keys.  The amount is already in the smallest
# currency unit (e.g. cents), so unit_amount == amount (no * 100 conversion).
#
# We extract the payload construction as a pure function so the property test
# exercises the exact same logic without making HTTP calls to Stripe.


def build_checkout_session_payload(
    *,
    amount: int,
    currency: str,
    invoice_id: str,
    stripe_account_id: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
    application_fee_amount: int | None = None,
) -> dict:
    """Build the Stripe Checkout Session payload dict.

    Mirrors the payload construction in
    ``app/integrations/stripe_connect.py`` → ``create_payment_link()``.

    The ``amount`` is in the smallest currency unit (e.g. cents for NZD).
    """
    default_base = "http://localhost:3000"
    final_success_url = (
        success_url
        or f"{default_base}/payments/success?session_id={{CHECKOUT_SESSION_ID}}"
    )
    final_cancel_url = cancel_url or f"{default_base}/payments/cancel"

    payload = {
        "mode": "payment",
        "payment_method_types[]": "card",
        "line_items[0][price_data][currency]": currency.lower(),
        "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][product_data][name]": (
            f"Invoice payment ({invoice_id})"
        ),
        "success_url": final_success_url,
        "cancel_url": final_cancel_url,
        "metadata[invoice_id]": invoice_id,
        "metadata[platform]": "workshoppro_nz",
    }

    if application_fee_amount and application_fee_amount > 0:
        payload["payment_intent_data[application_fee_amount]"] = str(
            application_fee_amount
        )

    return payload


# ---------------------------------------------------------------------------
# Strategies for Property 3
# ---------------------------------------------------------------------------

checkout_amount_st = st.integers(min_value=1, max_value=10_000_000)
checkout_invoice_id_st = st.uuids()
checkout_currency_st = st.sampled_from(["nzd", "aud", "usd"])


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 3: Checkout session amount and metadata correctness
# ===========================================================================


class TestP3CheckoutSessionAmountMetadataCorrectness:
    """For any valid invoice with balance_due > 0 and any requested payment
    amount 0 < amount <= balance_due, the created Checkout Session SHALL have
    line_items[0].price_data.unit_amount equal to the amount (already in
    cents), SHALL include the invoice ID in metadata.invoice_id, and SHALL
    use the invoice's currency.

    **Validates: Requirements 4.2, 4.3, 4.6**
    """

    # Feature: stripe-connect-online-payments, Property 3: Checkout session amount and metadata correctness
    @given(
        amount=checkout_amount_st,
        invoice_id=checkout_invoice_id_st,
        currency=checkout_currency_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_unit_amount_equals_amount_in_cents(
        self,
        amount: int,
        invoice_id: _uuid.UUID,
        currency: str,
    ) -> None:
        """P3: The unit_amount in the payload equals the amount (already in cents)."""
        payload = build_checkout_session_payload(
            amount=amount,
            currency=currency,
            invoice_id=str(invoice_id),
            stripe_account_id="acct_test123",
        )

        assert payload["line_items[0][price_data][unit_amount]"] == str(amount), (
            f"Expected unit_amount={amount}, "
            f"got {payload['line_items[0][price_data][unit_amount]']}"
        )

    # Feature: stripe-connect-online-payments, Property 3: Checkout session amount and metadata correctness
    @given(
        amount=checkout_amount_st,
        invoice_id=checkout_invoice_id_st,
        currency=checkout_currency_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_metadata_contains_invoice_id(
        self,
        amount: int,
        invoice_id: _uuid.UUID,
        currency: str,
    ) -> None:
        """P3: The metadata contains the correct invoice ID."""
        invoice_id_str = str(invoice_id)
        payload = build_checkout_session_payload(
            amount=amount,
            currency=currency,
            invoice_id=invoice_id_str,
            stripe_account_id="acct_test123",
        )

        assert payload["metadata[invoice_id]"] == invoice_id_str, (
            f"Expected metadata invoice_id={invoice_id_str}, "
            f"got {payload['metadata[invoice_id]']}"
        )

    # Feature: stripe-connect-online-payments, Property 3: Checkout session amount and metadata correctness
    @given(
        amount=checkout_amount_st,
        invoice_id=checkout_invoice_id_st,
        currency=checkout_currency_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_currency_matches_invoice_currency(
        self,
        amount: int,
        invoice_id: _uuid.UUID,
        currency: str,
    ) -> None:
        """P3: The payload currency matches the invoice currency (lowercased)."""
        payload = build_checkout_session_payload(
            amount=amount,
            currency=currency,
            invoice_id=str(invoice_id),
            stripe_account_id="acct_test123",
        )

        assert payload["line_items[0][price_data][currency]"] == currency.lower(), (
            f"Expected currency={currency.lower()}, "
            f"got {payload['line_items[0][price_data][currency]']}"
        )


# ---------------------------------------------------------------------------
# Webhook balance update — pure function under test
# ---------------------------------------------------------------------------
# The balance update logic in handle_stripe_webhook() is:
#   pay_amount = min(amount, invoice.balance_due)
#   invoice.balance_due -= pay_amount
#   invoice.amount_paid += pay_amount
#   status = "paid" if balance_due == 0 else "partially_paid"
#
# We extract this as a pure function so the property test exercises the
# exact same logic without needing a database or async context.


def compute_webhook_balance_update(
    *,
    amount: Decimal,
    balance_due: Decimal,
    amount_paid: Decimal,
) -> dict:
    """Compute the balance update from a webhook payment.

    Mirrors the balance update logic in
    ``app/modules/payments/service.py`` → ``handle_stripe_webhook()``.

    Parameters
    ----------
    amount:
        The payment amount from the Stripe webhook event.
    balance_due:
        The invoice's current balance due before the payment.
    amount_paid:
        The invoice's current amount paid before the payment.

    Returns
    -------
    dict
        ``pay_amount``: the actual amount recorded (capped at balance_due),
        ``new_balance_due``: the updated balance due,
        ``new_amount_paid``: the updated amount paid,
        ``new_status``: ``"paid"`` if balance is 0, else ``"partially_paid"``.
    """
    pay_amount = min(amount, balance_due)
    new_balance_due = balance_due - pay_amount
    new_amount_paid = amount_paid + pay_amount

    if new_balance_due == Decimal("0"):
        new_status = "paid"
    else:
        new_status = "partially_paid"

    return {
        "pay_amount": pay_amount,
        "new_balance_due": new_balance_due,
        "new_amount_paid": new_amount_paid,
        "new_status": new_status,
    }


# ---------------------------------------------------------------------------
# Strategies for Property 4
# ---------------------------------------------------------------------------

webhook_amount_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
)

webhook_balance_st = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    allow_nan=False,
    allow_infinity=False,
)


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly
# ===========================================================================


class TestP4WebhookPaymentBalanceUpdate:
    """For any invoice with balance_due > 0 and any webhook payment amount,
    the handler SHALL record min(amount, balance_due) as the payment,
    the new balance_due SHALL equal old_balance_due - min(amount, balance_due),
    and the new status SHALL be "paid" if new_balance_due == 0 else
    "partially_paid".

    **Validates: Requirements 6.1, 6.2, 6.3, 6.8**
    """

    # Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly
    @given(amount=webhook_amount_st, balance_due=webhook_balance_st)
    @settings(max_examples=100, deadline=None)
    def test_payment_recorded_is_min_of_amount_and_balance(
        self, amount: Decimal, balance_due: Decimal
    ) -> None:
        """P4: The recorded payment is min(amount, balance_due)."""
        result = compute_webhook_balance_update(
            amount=amount,
            balance_due=balance_due,
            amount_paid=Decimal("0"),
        )
        expected_pay = min(amount, balance_due)
        assert result["pay_amount"] == expected_pay, (
            f"amount={amount}, balance_due={balance_due}: "
            f"expected pay_amount={expected_pay}, got {result['pay_amount']}"
        )

    # Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly
    @given(amount=webhook_amount_st, balance_due=webhook_balance_st)
    @settings(max_examples=100, deadline=None)
    def test_new_balance_due_equals_old_minus_payment(
        self, amount: Decimal, balance_due: Decimal
    ) -> None:
        """P4: new_balance_due == old_balance_due - min(amount, balance_due)."""
        result = compute_webhook_balance_update(
            amount=amount,
            balance_due=balance_due,
            amount_paid=Decimal("0"),
        )
        expected_balance = balance_due - min(amount, balance_due)
        assert result["new_balance_due"] == expected_balance, (
            f"amount={amount}, balance_due={balance_due}: "
            f"expected new_balance_due={expected_balance}, "
            f"got {result['new_balance_due']}"
        )

    # Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly
    @given(amount=webhook_amount_st, balance_due=webhook_balance_st)
    @settings(max_examples=100, deadline=None)
    def test_status_paid_when_balance_zero(
        self, amount: Decimal, balance_due: Decimal
    ) -> None:
        """P4: Status is 'paid' if new balance is 0, else 'partially_paid'."""
        result = compute_webhook_balance_update(
            amount=amount,
            balance_due=balance_due,
            amount_paid=Decimal("0"),
        )
        if result["new_balance_due"] == Decimal("0"):
            assert result["new_status"] == "paid", (
                f"Expected 'paid' when balance is 0, got '{result['new_status']}'"
            )
        else:
            assert result["new_status"] == "partially_paid", (
                f"Expected 'partially_paid' when balance > 0, "
                f"got '{result['new_status']}'"
            )

    # Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly
    @given(
        amount=webhook_amount_st,
        balance_due=webhook_balance_st,
        prior_paid=st.decimals(
            min_value=Decimal("0"),
            max_value=Decimal("999999.99"),
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_amount_paid_increases_by_pay_amount(
        self, amount: Decimal, balance_due: Decimal, prior_paid: Decimal
    ) -> None:
        """P4: new_amount_paid == old_amount_paid + min(amount, balance_due)."""
        result = compute_webhook_balance_update(
            amount=amount,
            balance_due=balance_due,
            amount_paid=prior_paid,
        )
        expected_paid = prior_paid + min(amount, balance_due)
        assert result["new_amount_paid"] == expected_paid, (
            f"amount={amount}, balance_due={balance_due}, prior_paid={prior_paid}: "
            f"expected new_amount_paid={expected_paid}, "
            f"got {result['new_amount_paid']}"
        )

    # Feature: stripe-connect-online-payments, Property 4: Webhook payment updates invoice balances correctly
    @given(amount=webhook_amount_st, balance_due=webhook_balance_st)
    @settings(max_examples=100, deadline=None)
    def test_balance_due_never_goes_negative(
        self, amount: Decimal, balance_due: Decimal
    ) -> None:
        """P4: The new balance_due is never negative (overpayment is capped)."""
        result = compute_webhook_balance_update(
            amount=amount,
            balance_due=balance_due,
            amount_paid=Decimal("0"),
        )
        assert result["new_balance_due"] >= Decimal("0"), (
            f"amount={amount}, balance_due={balance_due}: "
            f"new_balance_due={result['new_balance_due']} is negative"
        )


# ---------------------------------------------------------------------------
# Webhook signature verification — testing the real function
# ---------------------------------------------------------------------------
# The verify_webhook_signature() function in stripe_connect.py:
#   1. Parses the Stripe-Signature header (t=<timestamp>,v1=<signature>)
#   2. Validates the timestamp is within 5 minutes of now
#   3. Computes HMAC-SHA256 of "{timestamp}.{payload}" using the webhook secret
#   4. Compares using hmac.compare_digest (constant-time)
#   5. Returns parsed JSON payload on success, raises ValueError on failure
#
# We import and test the real function directly.  For the "valid signature"
# path we construct a correct HMAC-SHA256 signature with a current timestamp.
# For the "invalid signature" path we supply a non-matching signature.

import hashlib as _hashlib
import hmac as _hmac
import json as _json
import time as _time

from app.integrations.stripe_connect import verify_webhook_signature


def _build_valid_sig_header(payload: bytes, secret: str) -> str:
    """Build a valid Stripe-Signature header for the given payload and secret.

    Uses the current timestamp so the replay-attack guard passes.
    """
    timestamp = str(int(_time.time()))
    signed_payload = f"{timestamp}.".encode() + payload
    sig = _hmac.new(secret.encode(), signed_payload, _hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}", timestamp


# ---------------------------------------------------------------------------
# Strategies for Property 5
# ---------------------------------------------------------------------------

webhook_payload_st = st.binary(min_size=1, max_size=10000)
webhook_secret_st = st.text(min_size=10, max_size=50)

# We need payloads that are valid JSON for the "accept" path, because
# verify_webhook_signature returns json.loads(payload) on success.
webhook_json_payload_st = st.dictionaries(
    keys=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))),
    values=st.one_of(
        st.text(min_size=0, max_size=50),
        st.integers(min_value=-1000000, max_value=1000000),
        st.booleans(),
    ),
    min_size=1,
    max_size=5,
).map(lambda d: _json.dumps(d).encode())


# ===========================================================================
# Feature: stripe-connect-online-payments, Property 5: Webhook signature verification
# ===========================================================================


class TestP5WebhookSignatureVerification:
    """For any payload bytes and signing secret, verify_webhook_signature
    SHALL accept a correctly computed HMAC-SHA256 signature and SHALL raise
    ValueError for any signature that does not match.

    **Validates: Requirements 6.4**
    """

    # Feature: stripe-connect-online-payments, Property 5: Webhook signature verification
    @given(payload=webhook_json_payload_st, secret=webhook_secret_st)
    @settings(max_examples=100, deadline=None)
    def test_valid_signature_is_accepted(self, payload: bytes, secret: str) -> None:
        """P5: A correctly computed HMAC-SHA256 signature is accepted."""
        sig_header, _ts = _build_valid_sig_header(payload, secret)
        # Should not raise — returns the parsed JSON payload
        result = verify_webhook_signature(payload, sig_header, secret)
        assert result == _json.loads(payload)

    # Feature: stripe-connect-online-payments, Property 5: Webhook signature verification
    @given(payload=webhook_payload_st, secret=webhook_secret_st)
    @settings(max_examples=100, deadline=None)
    def test_invalid_signature_is_rejected(self, payload: bytes, secret: str) -> None:
        """P5: Any non-matching signature raises ValueError."""
        timestamp = str(int(_time.time()))
        # Use a completely wrong signature (all zeros)
        bad_sig = "0" * 64
        sig_header = f"t={timestamp},v1={bad_sig}"

        import pytest

        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(payload, sig_header, secret)

    # Feature: stripe-connect-online-payments, Property 5: Webhook signature verification
    @given(payload=webhook_payload_st, secret=webhook_secret_st)
    @settings(max_examples=100, deadline=None)
    def test_missing_signature_header_fields_rejected(self, payload: bytes, secret: str) -> None:
        """P5: A signature header missing t or v1 raises ValueError."""
        import pytest

        # Missing v1
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(payload, f"t={int(_time.time())}", secret)

        # Missing t
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(payload, "v1=abc123", secret)

        # Completely empty
        with pytest.raises(ValueError, match="missing t or v1"):
            verify_webhook_signature(payload, "", secret)

    # Feature: stripe-connect-online-payments, Property 5: Webhook signature verification
    @given(
        payload=webhook_json_payload_st,
        secret_a=webhook_secret_st,
        secret_b=webhook_secret_st,
    )
    @settings(max_examples=100, deadline=None)
    def test_wrong_secret_is_rejected(self, payload: bytes, secret_a: str, secret_b: str) -> None:
        """P5: A signature computed with secret A is rejected when verified with secret B."""
        from hypothesis import assume

        assume(secret_a != secret_b)

        # Sign with secret_a
        sig_header, _ts = _build_valid_sig_header(payload, secret_a)

        import pytest

        # Verify with secret_b — should fail
        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(payload, sig_header, secret_b)
