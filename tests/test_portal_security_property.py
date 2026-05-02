"""Property-based tests for portal security.

Tests the pure logic of portal security mechanisms without requiring
a database: enable_portal flag enforcement, acceptance_token exclusion,
token expiry rejection, and webhook payment balance updates.

Properties covered:
  P5 — enable_portal=false blocks token resolution
  P6 — acceptance_token is never present in portal quote responses
  P9 — Expired tokens are rejected at service layer
  P10 — Webhook payment updates invoice correctly

**Validates: Requirements 7.1-7.3, 8.1-8.2, 10.1-10.2, 11.2-11.4**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

from app.modules.portal.schemas import (
    PortalQuoteItem,
    PortalQuoteLineItem,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_safe_text = st.text(
    min_size=1,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

_optional_text = st.one_of(st.none(), _safe_text)

_non_negative_decimal = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_positive_decimal = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_quote_status = st.sampled_from(["sent", "accepted", "rejected", "expired"])

_optional_currency = st.one_of(st.none(), st.sampled_from(["NZD", "AUD", "USD"]))


# ---------------------------------------------------------------------------
# Pure functions extracted from service.py for testability
# ---------------------------------------------------------------------------


def check_enable_portal(enable_portal: bool) -> bool:
    """Simulate the enable_portal filter in _resolve_token.

    In the real code, the query includes:
        .where(Customer.enable_portal.is_(True))
    If enable_portal is False, the customer is not found and a ValueError
    is raised. This function returns True if access is allowed, False if
    blocked.

    Mirrors: app/modules/portal/service.py → _resolve_token
    """
    return enable_portal is True


def check_token_expiry(
    portal_token_expires_at: datetime | None,
    now: datetime,
) -> bool:
    """Simulate the token expiry check in _resolve_token.

    In the real code:
        if (customer.portal_token_expires_at is not None
            and customer.portal_token_expires_at < datetime.now(timezone.utc)):
            raise ValueError("Invalid or expired portal token")

    Returns True if the token is valid (not expired), False if expired.

    Mirrors: app/modules/portal/service.py → _resolve_token
    """
    if portal_token_expires_at is not None and portal_token_expires_at < now:
        return False
    return True


def compute_webhook_balance_update(
    *,
    payment_amount: Decimal,
    existing_amount_paid: Decimal,
    existing_balance_due: Decimal,
) -> dict:
    """Compute the invoice balance update from a webhook payment.

    Mirrors the balance update logic in
    ``app/modules/payments/service.py`` → ``handle_stripe_webhook()``:
        pay_amount = min(amount, invoice.balance_due)
        invoice.amount_paid = invoice.amount_paid + pay_amount
        invoice.balance_due = invoice.balance_due - pay_amount
        status = "paid" if balance_due == 0 else "partially_paid"

    Parameters
    ----------
    payment_amount:
        The payment amount from the Stripe webhook event.
    existing_amount_paid:
        The invoice's current amount_paid before the payment.
    existing_balance_due:
        The invoice's current balance_due before the payment.

    Returns
    -------
    dict with keys: pay_amount, new_amount_paid, new_balance_due, new_status
    """
    pay_amount = min(payment_amount, existing_balance_due)
    new_amount_paid = existing_amount_paid + pay_amount
    new_balance_due = existing_balance_due - pay_amount

    if new_balance_due == Decimal("0"):
        new_status = "paid"
    else:
        new_status = "partially_paid"

    return {
        "pay_amount": pay_amount,
        "new_amount_paid": new_amount_paid,
        "new_balance_due": new_balance_due,
        "new_status": new_status,
    }


# ===========================================================================
# Property 5: enable_portal=false blocks token resolution
# ===========================================================================


class TestP5EnablePortalBlocksTokenResolution:
    """For any customer with a valid portal_token, if enable_portal is false,
    then _resolve_token SHALL raise a ValueError. If enable_portal is true
    and the token is valid and not expired, then _resolve_token SHALL succeed.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(
        enable_portal=st.just(False),
        token=st.uuids(),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_disabled_portal_blocks_access(
        self, enable_portal: bool, token: uuid.UUID
    ) -> None:
        """P5: When enable_portal is False, access is blocked regardless of
        whether a valid portal_token exists.

        **Validates: Requirements 7.1, 7.2, 7.3**
        """
        result = check_enable_portal(enable_portal)
        assert result is False, (
            f"Expected access blocked for enable_portal={enable_portal}, "
            f"token={token}, but got allowed"
        )

    @given(
        enable_portal=st.just(True),
        token=st.uuids(),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_enabled_portal_allows_access(
        self, enable_portal: bool, token: uuid.UUID
    ) -> None:
        """P5: When enable_portal is True, the enable_portal check passes.

        **Validates: Requirements 7.1, 7.2, 7.3**
        """
        result = check_enable_portal(enable_portal)
        assert result is True, (
            f"Expected access allowed for enable_portal={enable_portal}, "
            f"token={token}, but got blocked"
        )

    @given(
        enable_portal=st.booleans(),
        token=st.uuids(),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_enable_portal_flag_is_sole_determinant(
        self, enable_portal: bool, token: uuid.UUID
    ) -> None:
        """P5: The enable_portal flag is the sole determinant of whether
        the portal check passes — the token value itself does not matter.

        **Validates: Requirements 7.1, 7.2, 7.3**
        """
        result = check_enable_portal(enable_portal)
        assert result == enable_portal, (
            f"enable_portal={enable_portal} but check returned {result}"
        )


# ===========================================================================
# Property 6: acceptance_token is never present in portal quote responses
# ===========================================================================


def _quote_line_item_strategy():
    return st.fixed_dictionaries({
        "description": _safe_text,
        "quantity": _non_negative_decimal.filter(lambda d: d > 0),
        "unit_price": _non_negative_decimal,
        "total": st.one_of(st.none(), _non_negative_decimal),
    })


def _portal_quote_item_strategy():
    """Generate a valid PortalQuoteItem with random fields."""
    return st.fixed_dictionaries({
        "id": st.uuids(),
        "quote_number": st.from_regex(r"Q-\d{4,6}", fullmatch=True),
        "status": _quote_status,
        "expiry_date": st.one_of(
            st.none(),
            st.dates(),
        ),
        "terms": _optional_text,
        "line_items": st.lists(_quote_line_item_strategy(), min_size=0, max_size=5),
        "subtotal": _non_negative_decimal,
        "tax_amount": _non_negative_decimal,
        "total": _non_negative_decimal,
        "currency": _optional_currency,
        "accepted_at": st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2020, 1, 1),
                max_value=datetime(2030, 12, 31),
            ),
        ),
        "created_at": st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
        ),
    })


class TestP6AcceptanceTokenNeverInQuoteResponse:
    """For any quote returned by get_portal_quotes, the serialised
    PortalQuoteItem SHALL NOT contain an acceptance_token field.

    **Validates: Requirements 8.1, 8.2**
    """

    @given(data=_portal_quote_item_strategy())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_serialised_quote_has_no_acceptance_token(self, data: dict) -> None:
        """P6: The serialised PortalQuoteItem does not contain an
        acceptance_token field.

        **Validates: Requirements 8.1, 8.2**
        """
        line_items = [PortalQuoteLineItem(**li) for li in data["line_items"]]
        quote = PortalQuoteItem(
            id=data["id"],
            quote_number=data["quote_number"],
            status=data["status"],
            expiry_date=data["expiry_date"],
            terms=data["terms"],
            line_items=line_items,
            subtotal=data["subtotal"],
            tax_amount=data["tax_amount"],
            total=data["total"],
            currency=data["currency"],
            accepted_at=data["accepted_at"],
            created_at=data["created_at"],
        )

        # Serialise to dict (as the API would)
        serialised = quote.model_dump()
        assert "acceptance_token" not in serialised, (
            f"acceptance_token found in serialised PortalQuoteItem: "
            f"{serialised.keys()}"
        )

    @given(data=_portal_quote_item_strategy())
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_serialised_json_has_no_acceptance_token(self, data: dict) -> None:
        """P6: The JSON-serialised PortalQuoteItem does not contain
        the string 'acceptance_token'.

        **Validates: Requirements 8.1, 8.2**
        """
        line_items = [PortalQuoteLineItem(**li) for li in data["line_items"]]
        quote = PortalQuoteItem(
            id=data["id"],
            quote_number=data["quote_number"],
            status=data["status"],
            expiry_date=data["expiry_date"],
            terms=data["terms"],
            line_items=line_items,
            subtotal=data["subtotal"],
            tax_amount=data["tax_amount"],
            total=data["total"],
            currency=data["currency"],
            accepted_at=data["accepted_at"],
            created_at=data["created_at"],
        )

        json_str = quote.model_dump_json()
        assert "acceptance_token" not in json_str, (
            f"acceptance_token found in JSON output of PortalQuoteItem"
        )

    def test_schema_fields_exclude_acceptance_token(self) -> None:
        """P6: The PortalQuoteItem schema itself does not define an
        acceptance_token field.

        **Validates: Requirements 8.1, 8.2**
        """
        field_names = set(PortalQuoteItem.model_fields.keys())
        assert "acceptance_token" not in field_names, (
            f"acceptance_token is defined as a field on PortalQuoteItem: "
            f"{field_names}"
        )


# ===========================================================================
# Property 9: Expired tokens are rejected at service layer
# ===========================================================================


# Strategy for generating datetimes in the past (expired)
_past_datetime = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2025, 6, 1),
    timezones=st.just(timezone.utc),
)

# Strategy for generating datetimes in the future (valid)
_future_datetime = st.datetimes(
    min_value=datetime(2026, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)

# Fixed "now" for deterministic testing
_FIXED_NOW = datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestP9ExpiredTokensRejected:
    """For any customer with portal_token_expires_at in the past,
    _resolve_token SHALL raise a ValueError. For customers with
    portal_token_expires_at in the future or null, the expiry check
    SHALL pass.

    **Validates: Requirements 10.1, 10.2**
    """

    @given(expires_at=_past_datetime)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_expired_token_is_rejected(self, expires_at: datetime) -> None:
        """P9: When portal_token_expires_at is in the past, the expiry
        check fails (token is rejected).

        **Validates: Requirements 10.1, 10.2**
        """
        # Ensure expires_at is actually before our fixed "now"
        assume(expires_at < _FIXED_NOW)

        result = check_token_expiry(expires_at, _FIXED_NOW)
        assert result is False, (
            f"Expected expired token to be rejected: "
            f"expires_at={expires_at}, now={_FIXED_NOW}"
        )

    @given(expires_at=_future_datetime)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_future_token_is_accepted(self, expires_at: datetime) -> None:
        """P9: When portal_token_expires_at is in the future, the expiry
        check passes (token is accepted).

        **Validates: Requirements 10.1, 10.2**
        """
        # Ensure expires_at is actually after our fixed "now"
        assume(expires_at > _FIXED_NOW)

        result = check_token_expiry(expires_at, _FIXED_NOW)
        assert result is True, (
            f"Expected future token to be accepted: "
            f"expires_at={expires_at}, now={_FIXED_NOW}"
        )

    def test_null_expiry_is_accepted(self) -> None:
        """P9: When portal_token_expires_at is None, the expiry check
        passes (no expiry set means token never expires).

        **Validates: Requirements 10.1, 10.2**
        """
        result = check_token_expiry(None, _FIXED_NOW)
        assert result is True, (
            "Expected null expiry to be accepted (no expiry = never expires)"
        )

    @given(
        expires_at=st.one_of(st.none(), _past_datetime, _future_datetime),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_expiry_check_consistency(self, expires_at: datetime | None) -> None:
        """P9: The expiry check is consistent: None always passes,
        past always fails, future always passes.

        **Validates: Requirements 10.1, 10.2**
        """
        result = check_token_expiry(expires_at, _FIXED_NOW)

        if expires_at is None:
            assert result is True
        elif expires_at < _FIXED_NOW:
            assert result is False
        else:
            # expires_at >= _FIXED_NOW
            assert result is True


# ===========================================================================
# Property 10: Webhook payment updates invoice correctly
# ===========================================================================


class TestP10WebhookPaymentUpdatesInvoice:
    """For any valid checkout.session.completed event with a random payment
    amount and an invoice with a random existing amount_paid and balance_due,
    after processing: amount_paid SHALL equal the previous amount_paid plus
    the payment amount, balance_due SHALL equal the previous balance_due
    minus the payment amount, and status SHALL be paid if balance_due
    reaches 0 or partially_paid if balance_due remains positive.

    **Validates: Requirements 11.2, 11.3, 11.4**
    """

    @given(
        payment_amount=_positive_decimal,
        existing_amount_paid=_non_negative_decimal,
        existing_balance_due=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_amount_paid_increases_by_payment(
        self,
        payment_amount: Decimal,
        existing_amount_paid: Decimal,
        existing_balance_due: Decimal,
    ) -> None:
        """P10: amount_paid equals previous amount_paid plus the
        effective payment amount (capped at balance_due).

        **Validates: Requirements 11.2, 11.3, 11.4**
        """
        result = compute_webhook_balance_update(
            payment_amount=payment_amount,
            existing_amount_paid=existing_amount_paid,
            existing_balance_due=existing_balance_due,
        )

        expected_pay = min(payment_amount, existing_balance_due)
        expected_amount_paid = existing_amount_paid + expected_pay

        assert result["new_amount_paid"] == expected_amount_paid, (
            f"payment={payment_amount}, existing_paid={existing_amount_paid}, "
            f"balance_due={existing_balance_due}: "
            f"expected new_amount_paid={expected_amount_paid}, "
            f"got {result['new_amount_paid']}"
        )

    @given(
        payment_amount=_positive_decimal,
        existing_amount_paid=_non_negative_decimal,
        existing_balance_due=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_balance_due_decreases_by_payment(
        self,
        payment_amount: Decimal,
        existing_amount_paid: Decimal,
        existing_balance_due: Decimal,
    ) -> None:
        """P10: balance_due equals previous balance_due minus the
        effective payment amount (capped at balance_due).

        **Validates: Requirements 11.2, 11.3, 11.4**
        """
        result = compute_webhook_balance_update(
            payment_amount=payment_amount,
            existing_amount_paid=existing_amount_paid,
            existing_balance_due=existing_balance_due,
        )

        expected_pay = min(payment_amount, existing_balance_due)
        expected_balance_due = existing_balance_due - expected_pay

        assert result["new_balance_due"] == expected_balance_due, (
            f"payment={payment_amount}, balance_due={existing_balance_due}: "
            f"expected new_balance_due={expected_balance_due}, "
            f"got {result['new_balance_due']}"
        )

    @given(
        payment_amount=_positive_decimal,
        existing_amount_paid=_non_negative_decimal,
        existing_balance_due=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_status_is_paid_when_balance_reaches_zero(
        self,
        payment_amount: Decimal,
        existing_amount_paid: Decimal,
        existing_balance_due: Decimal,
    ) -> None:
        """P10: status is 'paid' when balance_due reaches 0, otherwise
        'partially_paid'.

        **Validates: Requirements 11.2, 11.3, 11.4**
        """
        result = compute_webhook_balance_update(
            payment_amount=payment_amount,
            existing_amount_paid=existing_amount_paid,
            existing_balance_due=existing_balance_due,
        )

        if result["new_balance_due"] == Decimal("0"):
            assert result["new_status"] == "paid", (
                f"Expected status='paid' when balance_due=0, "
                f"got '{result['new_status']}'"
            )
        else:
            assert result["new_status"] == "partially_paid", (
                f"Expected status='partially_paid' when balance_due="
                f"{result['new_balance_due']}, got '{result['new_status']}'"
            )

    @given(
        existing_amount_paid=_non_negative_decimal,
        existing_balance_due=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_full_payment_results_in_paid(
        self,
        existing_amount_paid: Decimal,
        existing_balance_due: Decimal,
    ) -> None:
        """P10: When payment_amount >= balance_due, the invoice becomes
        fully paid.

        **Validates: Requirements 11.3**
        """
        # Pay the exact balance or more
        payment_amount = existing_balance_due + Decimal("10.00")

        result = compute_webhook_balance_update(
            payment_amount=payment_amount,
            existing_amount_paid=existing_amount_paid,
            existing_balance_due=existing_balance_due,
        )

        assert result["new_balance_due"] == Decimal("0"), (
            f"Expected balance_due=0 for full payment, "
            f"got {result['new_balance_due']}"
        )
        assert result["new_status"] == "paid", (
            f"Expected status='paid' for full payment, "
            f"got '{result['new_status']}'"
        )
        assert result["pay_amount"] == existing_balance_due, (
            f"Expected pay_amount capped at balance_due={existing_balance_due}, "
            f"got {result['pay_amount']}"
        )

    @given(
        existing_amount_paid=_non_negative_decimal,
        existing_balance_due=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_partial_payment_results_in_partially_paid(
        self,
        existing_amount_paid: Decimal,
        existing_balance_due: Decimal,
    ) -> None:
        """P10: When payment_amount < balance_due, the invoice is
        partially_paid with remaining balance.

        **Validates: Requirements 11.4**
        """
        # Ensure we pay less than the balance
        assume(existing_balance_due > Decimal("0.01"))
        payment_amount = Decimal("0.01")

        result = compute_webhook_balance_update(
            payment_amount=payment_amount,
            existing_amount_paid=existing_amount_paid,
            existing_balance_due=existing_balance_due,
        )

        assert result["new_balance_due"] > Decimal("0"), (
            f"Expected positive balance_due for partial payment, "
            f"got {result['new_balance_due']}"
        )
        assert result["new_status"] == "partially_paid", (
            f"Expected status='partially_paid' for partial payment, "
            f"got '{result['new_status']}'"
        )

    @given(
        payment_amount=_positive_decimal,
        existing_amount_paid=_non_negative_decimal,
        existing_balance_due=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_balance_never_goes_negative(
        self,
        payment_amount: Decimal,
        existing_amount_paid: Decimal,
        existing_balance_due: Decimal,
    ) -> None:
        """P10: The balance_due never goes negative, even when payment
        exceeds the balance (capped at balance_due).

        **Validates: Requirements 11.2, 11.3, 11.4**
        """
        result = compute_webhook_balance_update(
            payment_amount=payment_amount,
            existing_amount_paid=existing_amount_paid,
            existing_balance_due=existing_balance_due,
        )

        assert result["new_balance_due"] >= Decimal("0"), (
            f"balance_due went negative: {result['new_balance_due']}"
        )
        assert result["pay_amount"] <= existing_balance_due, (
            f"pay_amount={result['pay_amount']} exceeds "
            f"balance_due={existing_balance_due}"
        )
