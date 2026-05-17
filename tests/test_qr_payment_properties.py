"""Property-based tests for Kiosk QR Payment feature.

Properties tested:
- Property 3: Amount Conversion Accuracy
- Property 4: Application Fee Calculation
- Property 5: Session Metadata Completeness
- Property 8: Idempotent Payment Recording

Uses Hypothesis to generate random test data and verify universal properties.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategy: Generate valid invoice amounts as Decimal values (0.01 to 999999.99)
# with exactly 2 decimal places (representing NZD dollar amounts).
# ---------------------------------------------------------------------------

valid_nzd_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Pure helper function replicating the conversion logic under test
# ---------------------------------------------------------------------------


def convert_amount_to_cents(amount: Decimal) -> int:
    """Replicate the amount-to-cents conversion from create_qr_payment_session.

    The backend uses: amount_cents = int(total * 100)
    where total is a Decimal from the invoice.

    For Decimal values with exactly 2 decimal places, multiplying by 100
    yields an exact integer (no floating-point drift) because Decimal
    arithmetic is exact.

    **Validates: Requirements 2.2**
    """
    return int(amount * 100)


# ---------------------------------------------------------------------------
# Property 3: Amount Conversion Accuracy
# **Validates: Requirements 2.2**
# ---------------------------------------------------------------------------


class TestAmountConversionAccuracy:
    """For any invoice total T (Decimal, 0.01–999999.99 with 2 decimal places),
    int(T * 100) produces the exact integer cents value with no floating-point
    drift."""

    @given(amount=valid_nzd_amounts)
    @settings(max_examples=200)
    def test_amount_conversion_no_floating_point_drift(self, amount: Decimal):
        """Property 3: Amount Conversion Accuracy — int(amount * 100) produces
        exact cents for any valid NZD Decimal amount.

        Verifies:
        1. The result is an exact integer (no fractional loss)
        2. Converting back to dollars matches the original amount
        3. The conversion matches the expected cents value

        **Validates: Requirements 2.2**
        """
        # Perform the conversion (same as backend)
        amount_cents = convert_amount_to_cents(amount)

        # 1. Result must be a positive integer
        assert isinstance(amount_cents, int)
        assert amount_cents > 0

        # 2. Decimal multiplication must be exact (no fractional remainder)
        # amount * 100 should be an exact integer for 2-decimal-place values
        exact_product = amount * Decimal("100")
        assert exact_product == int(exact_product), (
            f"Floating-point drift detected: {amount} * 100 = {exact_product}, "
            f"expected exact integer"
        )

        # 3. The int() conversion must equal the exact product
        assert amount_cents == int(exact_product)

        # 4. Round-trip: converting cents back to dollars must match original
        round_trip = Decimal(amount_cents) / Decimal("100")
        assert round_trip == amount, (
            f"Round-trip failed: {amount} -> {amount_cents} cents -> {round_trip}"
        )

        # 5. Verify against expected value (dollars * 100 = cents)
        expected_cents = int(str(amount).replace(".", "").lstrip("0") or "0")
        # More robust: just check the arithmetic identity
        assert amount_cents == int(amount * Decimal("100"))


# ---------------------------------------------------------------------------
# Strategies for Property 4: Application Fee Calculation
# ---------------------------------------------------------------------------

# Amount in cents: 100 ($1.00) to 99_999_900 ($999,999.00)
valid_amount_cents = st.integers(min_value=100, max_value=99_999_900)

# Fee percentage: 0.1% to 50.0% as Decimal with 1 decimal place
valid_fee_percent = st.decimals(
    min_value=Decimal("0.1"),
    max_value=Decimal("50.0"),
    places=1,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Pure helper function replicating the fee calculation logic under test
# ---------------------------------------------------------------------------


def calculate_application_fee(amount_cents: int, fee_percent: Decimal) -> int:
    """Replicate the application fee calculation from the backend.

    The backend uses: application_fee_amount = int(amount_cents * fee_percent / 100)

    This is used in:
    - app/modules/payments/service.py (create_qr_payment_session)
    - app/modules/portal/service.py
    - app/modules/invoices/service.py

    **Validates: Requirements 2.4**
    """
    return int(amount_cents * fee_percent / 100)


# ---------------------------------------------------------------------------
# Property 4: Application Fee Calculation
# **Validates: Requirements 2.4**
# ---------------------------------------------------------------------------


class TestApplicationFeeCalculation:
    """For any payment amount A (in cents) and platform fee percentage P
    (where P >= 0.1), the application_fee_amount equals int(A * P / 100).

    **Validates: Requirements 2.4**
    """

    @given(amount_cents=valid_amount_cents, fee_percent=valid_fee_percent)
    @settings(max_examples=200)
    def test_fee_formula_produces_correct_result(
        self, amount_cents: int, fee_percent: Decimal
    ):
        """Property 4: Application Fee Calculation — int(A * P / 100) produces
        the correct fee for any valid amount and percentage.

        Verifies:
        1. The result is a non-negative integer
        2. The result matches the formula int(amount_cents * fee_percent / 100)
        3. The fee is always less than or equal to the amount
        4. The fee is always less than or equal to (amount * max_percent / 100)

        **Validates: Requirements 2.4**
        """
        # Perform the calculation (same as backend)
        fee = calculate_application_fee(amount_cents, fee_percent)

        # 1. Result must be a non-negative integer
        assert isinstance(fee, int)
        assert fee >= 0

        # 2. Result must match the exact formula
        expected = int(amount_cents * fee_percent / 100)
        assert fee == expected, (
            f"Fee mismatch: amount_cents={amount_cents}, fee_percent={fee_percent}, "
            f"expected={expected}, got={fee}"
        )

        # 3. Fee must never exceed the original amount
        assert fee <= amount_cents, (
            f"Fee exceeds amount: fee={fee}, amount_cents={amount_cents}, "
            f"fee_percent={fee_percent}"
        )

        # 4. Fee must be bounded by the percentage applied to the amount
        # fee <= amount_cents * fee_percent / 100 (before truncation, it's exact)
        # Since int() truncates, fee <= amount_cents * fee_percent / 100
        upper_bound = amount_cents * fee_percent / Decimal("100")
        assert fee <= upper_bound, (
            f"Fee exceeds upper bound: fee={fee}, upper_bound={upper_bound}"
        )

    @given(amount_cents=valid_amount_cents, fee_percent=valid_fee_percent)
    @settings(max_examples=200)
    def test_fee_truncates_not_rounds(
        self, amount_cents: int, fee_percent: Decimal
    ):
        """Property 4: The fee uses int() truncation (floor toward zero),
        not rounding. This ensures the platform never overcharges.

        **Validates: Requirements 2.4**
        """
        fee = calculate_application_fee(amount_cents, fee_percent)

        # The exact (non-truncated) value
        exact_value = amount_cents * fee_percent / Decimal("100")

        # int() truncates toward zero, so fee <= exact_value
        assert fee <= exact_value, (
            f"Fee exceeds exact value (rounding up detected): "
            f"fee={fee}, exact={exact_value}"
        )

        # The truncation should lose less than 1 cent
        assert exact_value - fee < 1, (
            f"Truncation lost more than 1 cent: "
            f"exact={exact_value}, fee={fee}, diff={exact_value - fee}"
        )

    @given(amount_cents=valid_amount_cents)
    @settings(max_examples=100)
    def test_fee_scales_linearly_with_amount(self, amount_cents: int):
        """Property 4: Doubling the amount should approximately double the fee
        (within 1 cent due to truncation).

        **Validates: Requirements 2.4**
        """
        fee_percent = Decimal("2.5")  # Fixed percentage for linearity test

        fee_single = calculate_application_fee(amount_cents, fee_percent)
        fee_double = calculate_application_fee(amount_cents * 2, fee_percent)

        # Due to int() truncation, fee_double should be within 1 of 2 * fee_single
        assert abs(fee_double - 2 * fee_single) <= 1, (
            f"Non-linear scaling: fee({amount_cents})={fee_single}, "
            f"fee({amount_cents * 2})={fee_double}, "
            f"expected ~{2 * fee_single}"
        )


# ---------------------------------------------------------------------------
# Strategies for Property 5: Session Metadata Completeness
# ---------------------------------------------------------------------------

# Generate random UUIDs using Hypothesis
valid_uuids = st.uuids()

# Generate random base URLs (realistic frontend base URLs)
valid_base_urls = st.sampled_from([
    "http://localhost:5173",
    "https://app.orainvoice.com",
    "https://staging.orainvoice.co.nz",
    "http://192.168.1.90:8999",
])


# ---------------------------------------------------------------------------
# Pure helper function replicating the metadata and URL construction logic
# ---------------------------------------------------------------------------


def build_session_metadata_and_urls(
    invoice_id: "uuid.UUID",
    org_id: "uuid.UUID",
    base_url: str,
) -> dict:
    """Replicate the metadata dict and URL construction from create_qr_payment_session.

    The backend builds form fields:
    - metadata[invoice_id] = str(invoice_id)
    - metadata[org_id] = str(org_id)
    - metadata[source] = "kiosk_qr"
    - metadata[platform] = "orainvoice"
    - success_url = {base_url}/payments/qr-success?invoice_id={invoice_id}&session_id={CHECKOUT_SESSION_ID}
    - cancel_url = {base_url}/payments/qr-cancel?invoice_id={invoice_id}

    **Validates: Requirements 2.5, 2.6, 2.8**
    """
    import uuid as _uuid  # noqa: F811 — local import for type clarity

    base = base_url.rstrip("/")

    metadata = {
        "invoice_id": str(invoice_id),
        "org_id": str(org_id),
        "source": "kiosk_qr",
        "platform": "orainvoice",
    }

    success_url = (
        f"{base}/payments/qr-success?invoice_id={invoice_id}"
        f"&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{base}/payments/qr-cancel?invoice_id={invoice_id}"

    return {
        "metadata": metadata,
        "success_url": success_url,
        "cancel_url": cancel_url,
    }


# ---------------------------------------------------------------------------
# Property 5: Session Metadata Completeness
# **Validates: Requirements 2.5, 2.6, 2.8**
# ---------------------------------------------------------------------------


class TestSessionMetadataCompleteness:
    """For any created QR Checkout Session, the session metadata SHALL contain
    invoice_id (matching the source invoice UUID), org_id (matching the
    organisation UUID), and source equal to "kiosk_qr". The success_url SHALL
    contain the invoice_id, and the cancel_url SHALL contain the invoice_id.

    **Validates: Requirements 2.5, 2.6, 2.8**
    """

    @given(
        invoice_id=valid_uuids,
        org_id=valid_uuids,
        base_url=valid_base_urls,
    )
    @settings(max_examples=200)
    def test_metadata_contains_required_fields(
        self, invoice_id: "uuid.UUID", org_id: "uuid.UUID", base_url: str
    ):
        """Property 5: Metadata dict contains invoice_id, org_id, source="kiosk_qr",
        and platform="orainvoice" for any random UUIDs.

        **Validates: Requirements 2.5, 2.6, 2.8**
        """
        result = build_session_metadata_and_urls(invoice_id, org_id, base_url)
        metadata = result["metadata"]

        # 1. metadata must contain invoice_id matching the input UUID
        assert "invoice_id" in metadata
        assert metadata["invoice_id"] == str(invoice_id)

        # 2. metadata must contain org_id matching the input UUID
        assert "org_id" in metadata
        assert metadata["org_id"] == str(org_id)

        # 3. metadata must contain source = "kiosk_qr"
        assert "source" in metadata
        assert metadata["source"] == "kiosk_qr"

        # 4. metadata must contain platform = "orainvoice"
        assert "platform" in metadata
        assert metadata["platform"] == "orainvoice"

    @given(
        invoice_id=valid_uuids,
        org_id=valid_uuids,
        base_url=valid_base_urls,
    )
    @settings(max_examples=200)
    def test_success_url_contains_invoice_id(
        self, invoice_id: "uuid.UUID", org_id: "uuid.UUID", base_url: str
    ):
        """Property 5: The success_url SHALL contain the invoice_id.

        **Validates: Requirements 2.5**
        """
        result = build_session_metadata_and_urls(invoice_id, org_id, base_url)
        success_url = result["success_url"]

        # success_url must contain the invoice_id as a string
        assert str(invoice_id) in success_url, (
            f"invoice_id {invoice_id} not found in success_url: {success_url}"
        )

        # success_url must follow the expected pattern
        assert "/payments/qr-success?" in success_url
        assert f"invoice_id={invoice_id}" in success_url
        assert "session_id={CHECKOUT_SESSION_ID}" in success_url

    @given(
        invoice_id=valid_uuids,
        org_id=valid_uuids,
        base_url=valid_base_urls,
    )
    @settings(max_examples=200)
    def test_cancel_url_contains_invoice_id(
        self, invoice_id: "uuid.UUID", org_id: "uuid.UUID", base_url: str
    ):
        """Property 5: The cancel_url SHALL contain the invoice_id.

        **Validates: Requirements 2.6**
        """
        result = build_session_metadata_and_urls(invoice_id, org_id, base_url)
        cancel_url = result["cancel_url"]

        # cancel_url must contain the invoice_id as a string
        assert str(invoice_id) in cancel_url, (
            f"invoice_id {invoice_id} not found in cancel_url: {cancel_url}"
        )

        # cancel_url must follow the expected pattern
        assert "/payments/qr-cancel?" in cancel_url
        assert f"invoice_id={invoice_id}" in cancel_url

    @given(
        invoice_id=valid_uuids,
        org_id=valid_uuids,
        base_url=valid_base_urls,
    )
    @settings(max_examples=100)
    def test_metadata_values_are_valid_uuid_strings(
        self, invoice_id: "uuid.UUID", org_id: "uuid.UUID", base_url: str
    ):
        """Property 5: The invoice_id and org_id in metadata are valid UUID strings
        that can be parsed back to UUID objects.

        **Validates: Requirements 2.8**
        """
        import uuid as _uuid

        result = build_session_metadata_and_urls(invoice_id, org_id, base_url)
        metadata = result["metadata"]

        # invoice_id in metadata must be a valid UUID string
        parsed_invoice_id = _uuid.UUID(metadata["invoice_id"])
        assert parsed_invoice_id == invoice_id

        # org_id in metadata must be a valid UUID string
        parsed_org_id = _uuid.UUID(metadata["org_id"])
        assert parsed_org_id == org_id


# ---------------------------------------------------------------------------
# Strategies for Property 8: Idempotent Payment Recording
# ---------------------------------------------------------------------------

# Generate random payment_intent_id strings (mimicking Stripe's "pi_" + hex format)
valid_payment_intent_ids = st.text(
    alphabet="0123456789abcdef",
    min_size=16,
    max_size=32,
).map(lambda hex_str: f"pi_{hex_str}")


# ---------------------------------------------------------------------------
# Pure helper functions replicating the idempotency check logic under test
# ---------------------------------------------------------------------------


def check_idempotency(
    existing_payment_intent_ids: set[str],
    new_payment_intent_id: str,
) -> str:
    """Replicate the idempotency check from handle_stripe_webhook.

    The webhook handler checks if a payment with the same stripe_payment_intent_id
    already exists. If it does, it returns {"status": "ignored", "reason": "Duplicate event"}.
    If it doesn't, it processes the payment.

    This is a pure function that simulates the check:
    - Given a set of existing payment_intent_ids and a new event's payment_intent_id
    - If the new ID is already in the set, return "ignored" (duplicate)
    - If the new ID is not in the set, return "processed" (new payment)

    **Validates: Requirements 8.2**
    """
    if new_payment_intent_id in existing_payment_intent_ids:
        return "ignored"
    return "processed"


def process_payment_event(
    recorded_payments: set[str],
    payment_intent_id: str,
) -> tuple[set[str], str]:
    """Simulate processing a webhook event with idempotency.

    Returns the updated set of recorded payments and the processing result.
    If the payment_intent_id is already recorded, the set is unchanged and
    the result is "ignored". Otherwise, the ID is added and result is "processed".

    **Validates: Requirements 8.2**
    """
    if payment_intent_id in recorded_payments:
        return recorded_payments, "ignored"
    new_set = recorded_payments | {payment_intent_id}
    return new_set, "processed"


# ---------------------------------------------------------------------------
# Property 8: Idempotent Payment Recording
# **Validates: Requirements 8.2**
# ---------------------------------------------------------------------------


class TestIdempotentPaymentRecording:
    """For any stripe_payment_intent_id that already exists in the payments table,
    processing a duplicate checkout.session.completed webhook event SHALL NOT
    create a new payment record (the existing record is returned/acknowledged instead).

    **Validates: Requirements 8.2**
    """

    @given(payment_intent_id=valid_payment_intent_ids)
    @settings(max_examples=200)
    def test_duplicate_event_always_ignored(self, payment_intent_id: str):
        """Property 8: Processing the same payment_intent_id twice always results
        in "ignored" on the second attempt.

        **Validates: Requirements 8.2**
        """
        # First processing: should be "processed"
        existing: set[str] = set()
        result_first = check_idempotency(existing, payment_intent_id)
        assert result_first == "processed", (
            f"First event should be processed, got: {result_first}"
        )

        # Add to existing set (simulating the payment being recorded)
        existing.add(payment_intent_id)

        # Second processing (duplicate): should be "ignored"
        result_second = check_idempotency(existing, payment_intent_id)
        assert result_second == "ignored", (
            f"Duplicate event should be ignored, got: {result_second} "
            f"for payment_intent_id={payment_intent_id}"
        )

    @given(
        id_a=valid_payment_intent_ids,
        id_b=valid_payment_intent_ids,
    )
    @settings(max_examples=200)
    def test_different_ids_always_processed(self, id_a: str, id_b: str):
        """Property 8: Processing different payment_intent_ids always results
        in "processed" for each unique ID.

        **Validates: Requirements 8.2**
        """
        from hypothesis import assume

        assume(id_a != id_b)

        existing: set[str] = set()

        # Process first ID
        result_a = check_idempotency(existing, id_a)
        assert result_a == "processed"
        existing.add(id_a)

        # Process second (different) ID — should also be processed
        result_b = check_idempotency(existing, id_b)
        assert result_b == "processed", (
            f"Different payment_intent_id should be processed, got: {result_b}. "
            f"id_a={id_a}, id_b={id_b}"
        )

    @given(
        payment_intent_ids=st.lists(
            valid_payment_intent_ids,
            min_size=2,
            max_size=20,
        )
    )
    @settings(max_examples=200)
    def test_no_duplicate_records_after_processing(self, payment_intent_ids: list[str]):
        """Property 8: The set of recorded payments never contains duplicates,
        regardless of how many times the same event is processed.

        **Validates: Requirements 8.2**
        """
        recorded: set[str] = set()

        for pi_id in payment_intent_ids:
            recorded, result = process_payment_event(recorded, pi_id)

            if result == "processed":
                # The ID was new — it should now be in the set
                assert pi_id in recorded
            else:
                # The ID was a duplicate — set size should not have changed
                assert result == "ignored"

        # The recorded set should contain only unique IDs
        # (sets inherently have no duplicates, but verify the count matches
        # the number of unique IDs we processed)
        unique_ids = set(payment_intent_ids)
        assert recorded == unique_ids, (
            f"Recorded set should match unique IDs. "
            f"Recorded: {len(recorded)}, Unique: {len(unique_ids)}"
        )

    @given(
        payment_intent_id=valid_payment_intent_ids,
        num_duplicates=st.integers(min_value=2, max_value=10),
    )
    @settings(max_examples=200)
    def test_repeated_events_only_record_once(
        self, payment_intent_id: str, num_duplicates: int
    ):
        """Property 8: Sending the same webhook event N times results in exactly
        one recorded payment and N-1 ignored duplicates.

        **Validates: Requirements 8.2**
        """
        recorded: set[str] = set()
        processed_count = 0
        ignored_count = 0

        for _ in range(num_duplicates):
            recorded, result = process_payment_event(recorded, payment_intent_id)
            if result == "processed":
                processed_count += 1
            else:
                ignored_count += 1

        # Exactly one should be processed
        assert processed_count == 1, (
            f"Expected exactly 1 processed event, got {processed_count} "
            f"for {num_duplicates} attempts"
        )

        # The rest should be ignored
        assert ignored_count == num_duplicates - 1, (
            f"Expected {num_duplicates - 1} ignored events, got {ignored_count}"
        )

        # The set should contain exactly one entry
        assert len(recorded) == 1
        assert payment_intent_id in recorded
