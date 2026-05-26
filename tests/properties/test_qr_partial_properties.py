"""Property-based tests for the QR partial-payment flow.

Three Hypothesis-driven properties guard the partial-amount mechanics end-to-end:

  P1 - Cents round-trip preserves the partial amount exactly. For any Decimal
       ``d`` in [0.50, 99999.99] with at most 2dp, ``int(d * 100)`` round-trips
       losslessly (no fractional cents are silently dropped between the org
       user's input and Stripe's cents-based PaymentIntent.amount).

  P2 - Service validation envelope is exact. For any (amount, balance) pair
       with ``0.50 <= amount <= balance``, ``create_qr_session_for_existing_invoice``
       accepts the request; outside that envelope it rejects with ValueError
       (HTTP 400 at the endpoint layer).

  P3 - Webhook records exactly the partial amount. For any partial ``a`` and
       any surcharge ``(p, f)``, after ``handle_stripe_webhook`` processes a
       successful PaymentIntent succeeded event,
       ``invoice.balance_due_after == invoice.balance_due_before - a`` within
       1c rounding tolerance.

The tests are hermetic: they use AsyncMock-based DB sessions and patch the
Stripe-touching helpers (mirroring the convention in
``tests/test_qr_partial_payment_integration.py``) so no real DB or network is
involved.

**Validates: Requirements 3.x, 7.x**
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, assume, given, settings as h_settings
from hypothesis import strategies as st

# Ensure SQLAlchemy mappers are configurable in any test that constructs
# select() statements that touch relationships across modules. Mirrors the
# model-loading block in app/main.py and tests/test_qr_partial_payment_integration.py.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.catalogue.fluid_oil_models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.invoices.attachment_models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.service_types.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.sms_chat.models  # noqa: F401
import app.modules.ha.models  # noqa: F401
import app.modules.ha.volume_sync_models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.quotes.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.platform_settings.models  # noqa: F401
import app.modules.ledger.models  # noqa: F401
import app.modules.banking.models  # noqa: F401
import app.modules.tax_wallets.models  # noqa: F401
import app.modules.ird.models  # noqa: F401
import app.modules.in_app_notifications.models  # noqa: F401
import app.modules.fleet_portal.models  # noqa: F401
import app.modules.portal.models  # noqa: F401

from app.modules.invoices.models import Invoice
from app.modules.payments.models import Payment
from app.modules.payments.service import (
    create_qr_session_for_existing_invoice,
    handle_stripe_webhook,
)


# ---------------------------------------------------------------------------
# Autouse — neutralise flag_modified() so mock Invoices (which lack the
# SQLAlchemy ``_sa_instance_state`` attribute) can be passed through the
# service without tripping ``instance_state(...)``. The flag is irrelevant
# in test contexts that mock the DB layer wholesale.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _neutralise_flag_modified():
    with patch(
        "app.modules.payments.service.flag_modified",
        new=MagicMock(return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# Test helpers (mirror tests/test_qr_partial_payment_integration.py)
# ---------------------------------------------------------------------------


def _make_invoice(
    *,
    org_id: uuid.UUID | None = None,
    invoice_id: uuid.UUID | None = None,
    status: str = "issued",
    total: Decimal = Decimal("300.00"),
    amount_paid: Decimal = Decimal("0.00"),
    balance_due: Decimal = Decimal("300.00"),
    currency: str = "NZD",
    stripe_payment_intent_id: str | None = None,
    payment_page_url: str | None = None,
    invoice_data_json: dict | None = None,
) -> MagicMock:
    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id or uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = uuid.uuid4()
    inv.created_by = uuid.uuid4()
    inv.status = status
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.currency = currency
    inv.invoice_number = "INV-PROP"
    inv.stripe_payment_intent_id = stripe_payment_intent_id
    inv.payment_page_url = payment_page_url
    inv.invoice_data_json = dict(invoice_data_json) if invoice_data_json else {}
    return inv


def _make_org(
    *,
    org_id: uuid.UUID | None = None,
    stripe_connect_account_id: str = "acct_test_connect",
) -> MagicMock:
    org = MagicMock()
    org.id = org_id or uuid.uuid4()
    org.stripe_connect_account_id = stripe_connect_account_id
    return org


class _FakeDb:
    """An AsyncMock-flavoured DB that returns pre-programmed select results.

    Mirrors the helper in ``tests/test_qr_partial_payment_integration.py``.
    The select queue is consumed in order on each ``db.execute(select_stmt)``
    call. Update/delete statements are no-ops that record the statement for
    later assertion.
    """

    def __init__(self, select_results: list[Any] | None = None) -> None:
        self._select_queue: list[Any] = list(select_results or [])
        self.added: list[Any] = []
        self.flushes = 0
        self.update_calls: list[Any] = []
        self.delete_calls: list[Any] = []
        self.refresh = AsyncMock()
        self.execute = AsyncMock(side_effect=self._execute)
        self.flush = AsyncMock(side_effect=self._flush)
        self.add = MagicMock(side_effect=self._add)

    async def _flush(self) -> None:
        self.flushes += 1

    def _add(self, obj: Any) -> None:
        self.added.append(obj)

    async def _execute(self, stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        from sqlalchemy import Delete, Select, Update

        if isinstance(stmt, Select):
            value = self._select_queue.pop(0) if self._select_queue else None
            result = MagicMock()
            if isinstance(value, list):
                scalars = MagicMock()
                scalars.all.return_value = value
                result.scalars.return_value = scalars
                result.scalar_one_or_none.return_value = value[0] if value else None
            else:
                result.scalar_one_or_none.return_value = value
                scalars = MagicMock()
                scalars.all.return_value = [value] if value is not None else []
                result.scalars.return_value = scalars
            return result

        if isinstance(stmt, Update):
            self.update_calls.append(stmt)
            return MagicMock()

        if isinstance(stmt, Delete):
            self.delete_calls.append(stmt)
            return MagicMock()

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result


class _WebhookFakeDb:
    """Fake DB for the webhook-handler property test.

    The webhook issues SELECTs against invoices, payments (idempotency check)
    and customers (best-effort email lookup) plus UPDATE/DELETE on
    PaymentToken and PendingQrSession. We dispatch by the SELECT's FROM
    table so we can answer correctly without depending on call order.
    """

    def __init__(self, *, invoice: MagicMock) -> None:
        self.invoice = invoice
        self.existing_payments: dict[str, MagicMock] = {}
        self.payments_added: list[Any] = []
        self.update_calls: list[Any] = []
        self.delete_calls: list[Any] = []
        self.flushes = 0
        self.execute = AsyncMock(side_effect=self._execute)
        self.flush = AsyncMock(side_effect=self._flush)
        self.refresh = AsyncMock()
        self.add = MagicMock(side_effect=self._add)

    async def _flush(self) -> None:
        self.flushes += 1

    def _add(self, obj: Any) -> None:
        self.payments_added.append(obj)
        if isinstance(obj, Payment) and obj.stripe_payment_intent_id:
            self.existing_payments[obj.stripe_payment_intent_id] = obj

    async def _execute(self, stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        from sqlalchemy import Delete, Select, Update

        if isinstance(stmt, Select):
            entity = self._select_entity(stmt)
            result = MagicMock()
            if entity == "invoices":
                result.scalar_one_or_none.return_value = self.invoice
                return result
            if entity == "payments":
                pi_id = self._extract_pi_id_filter(stmt)
                if pi_id and pi_id in self.existing_payments:
                    result.scalar_one_or_none.return_value = (
                        self.existing_payments[pi_id]
                    )
                else:
                    result.scalar_one_or_none.return_value = None
                return result
            # Customer / fall-through — return None so the best-effort email
            # path is silently skipped.
            result.scalar_one_or_none.return_value = None
            return result

        if isinstance(stmt, Update):
            self.update_calls.append(stmt)
            return MagicMock()

        if isinstance(stmt, Delete):
            self.delete_calls.append(stmt)
            return MagicMock()

        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    def _select_entity(self, stmt: Any) -> str | None:
        try:
            tables = stmt.get_final_froms()
            for t in tables:
                name = getattr(t, "name", None)
                if name:
                    return name.lower()
        except Exception:
            pass
        return None

    def _extract_pi_id_filter(self, stmt: Any) -> str | None:
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            sql = str(compiled)
            import re
            m = re.search(r"stripe_payment_intent_id\s*=\s*'([^']+)'", sql)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Decimal in [0.50, 99999.99] with at most 2dp — the partial-amount domain
# defined by the spec (Stripe NZD minimum 0.50 up to a sane invoice ceiling).
partial_amount_st = st.decimals(
    min_value=Decimal("0.50"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Surcharge percentage (0% to 10%) and fixed surcharge ($0 to $5) — same
# bounds as test_surcharge_properties.py.
surcharge_pct_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("10"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

surcharge_fixed_st = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("5"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def amount_within_balance(draw):
    """Generate (balance, amount) where 0.50 <= amount <= balance <= 99999.99
    and both have at most 2dp.
    """
    balance = draw(
        st.decimals(
            min_value=Decimal("0.50"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    amount = draw(
        st.decimals(
            min_value=Decimal("0.50"),
            max_value=balance,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return balance, amount


@st.composite
def amount_outside_envelope(draw):
    """Generate (balance, amount) where the amount is outside the accept
    envelope — either below the Stripe minimum (and > 0, since the schema
    rejects <= 0 before the service is even reached) OR above the balance.
    Both balance and amount have at most 2dp.
    """
    balance = draw(
        st.decimals(
            min_value=Decimal("0.50"),
            max_value=Decimal("99999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    # Either below the Stripe minimum (in (0, 0.50)) or above balance.
    too_low = st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("0.49"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
    too_high = st.decimals(
        min_value=balance + Decimal("0.01"),
        max_value=Decimal("100000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
    amount = draw(st.one_of(too_low, too_high))
    return balance, amount


# ===========================================================================
# Property 1: Cents round-trip
# ===========================================================================


class TestP1CentsRoundTrip:
    """For any Decimal d in [0.50, 99999.99] with at most 2dp,
    ``int(d * 100) / 100 == d`` — i.e. converting to integer cents and back
    to dollars preserves the value exactly. This is the fundamental
    invariant relied on by ``create_qr_session_for_existing_invoice`` when
    it computes ``target_cents = int(resolved_amount * 100)`` to send to
    Stripe.

    **Validates: Requirements 3.x**
    """

    # Property 1: Cents round-trip
    @given(d=partial_amount_st)
    @h_settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_cents_round_trip_lossless(self, d: Decimal) -> None:
        """``int(d * 100) / 100 == d`` for any 2dp Decimal in the partial-
        amount envelope. No fractional cents leak between user input and
        Stripe's cents-based PI.amount."""
        cents = int(d * 100)
        round_tripped = Decimal(cents) / Decimal("100")
        # Compare quantized forms so both sides have the same exponent
        # (e.g., Decimal("100.00") vs Decimal("100.0") would otherwise
        # differ in representation despite being numerically equal).
        assert round_tripped.quantize(Decimal("0.01")) == d.quantize(Decimal("0.01")), (
            f"Round-trip lost precision for d={d}: "
            f"int(d*100)={cents}, back to dollars={round_tripped}"
        )

    # Property 1: Cents round-trip
    @given(d=partial_amount_st)
    @h_settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_cents_are_positive_integer(self, d: Decimal) -> None:
        """``int(d * 100)`` is a positive integer for any d in the partial-
        amount envelope. Stripe rejects PaymentIntents with a non-positive
        amount."""
        cents = int(d * 100)
        assert isinstance(cents, int)
        assert cents > 0, f"Cents must be positive for d={d}, got {cents}"
        # And the cents value matches the schema's >= $0.50 floor.
        assert cents >= 50, f"Cents must be >= 50 (Stripe minimum), got {cents}"


# ===========================================================================
# Property 2: Validation envelope
# ===========================================================================


def _patch_service_for_property(
    *,
    invoice: MagicMock,
    org: MagicMock,
    new_pi_id: str = "pi_property_new",
):
    """Prepare the patched dependencies and a FakeDb for a single call to
    ``create_qr_session_for_existing_invoice`` with no existing PI on the
    invoice (i.e. fresh path, no reuse-branch interaction).

    Returns a tuple (db, create_pi_mock, audit_log_mock, fake_generate_token).
    """
    # Fresh invoice — no payment_page_url, no stripe_payment_intent_id —
    # so the service skips the existing-token select. The select queue is
    # therefore [invoice, org].
    select_results: list[Any] = [invoice, org]
    db = _FakeDb(select_results=select_results)

    create_pi_mock = AsyncMock(
        return_value={
            "payment_intent_id": new_pi_id,
            "client_secret": f"{new_pi_id}_secret",
        }
    )
    audit_log_mock = AsyncMock()

    async def _fake_generate_token(
        db_, *, org_id, invoice_id, base_url=None, amount_override=None,
    ):
        token_str = f"tok_{uuid.uuid4().hex}"
        return token_str, f"https://test.local/pay/{token_str}"

    return db, create_pi_mock, audit_log_mock, _fake_generate_token


class TestP2ValidationEnvelope:
    """For any (amount, balance) pair where ``0.50 <= amount <= balance``,
    the service accepts the request — the PaymentIntent is created and the
    response carries the resolved partial amount.

    For any (amount, balance) outside this envelope, the service rejects
    with ``ValueError`` (translated to HTTP 400 at the endpoint layer).

    Both halves of the envelope are tested exhaustively via Hypothesis to
    guard against drift in the inequality directions or off-by-one
    confusions at the boundary.

    **Validates: Requirements 3.2, 3.3, 3.4, 3.6**
    """

    # Property 2: Validation envelope (accept side)
    @given(pair=amount_within_balance())
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_inside_envelope_is_accepted(self, pair: tuple[Decimal, Decimal]) -> None:
        """For any (balance, amount) with ``0.50 <= amount <= balance``, the
        service accepts the partial request: the PI is created with the
        partial cents and the response echoes the partial amount.

        **Validates: Requirements 3.2, 3.6**
        """
        balance, amount = pair

        async def _run() -> dict:
            invoice = _make_invoice(balance_due=balance, currency="NZD")
            org = _make_org()
            db, create_pi, audit, gen_token = _patch_service_for_property(
                invoice=invoice, org=org,
            )

            with patch(
                "app.modules.payments.service.create_payment_intent", create_pi,
            ), patch(
                "app.modules.payments.service.write_audit_log", audit,
            ), patch(
                "app.modules.payments.service.generate_payment_token",
                new=AsyncMock(side_effect=gen_token),
            ), patch(
                "app.integrations.stripe_billing.get_application_fee_percent",
                new=AsyncMock(return_value=Decimal("0")),
            ):
                return await create_qr_session_for_existing_invoice(
                    db,
                    org_id=invoice.org_id,
                    user_id=uuid.uuid4(),
                    invoice_id=invoice.id,
                    partial_amount=amount,
                )

        result = asyncio.run(_run())

        # Response carries the resolved partial amount and matching cents.
        expected_amount = amount.quantize(Decimal("0.01"))
        assert result["amount"] == expected_amount, (
            f"balance={balance}, amount={amount}: "
            f"response amount {result['amount']} != expected {expected_amount}"
        )
        assert result["amount_cents"] == int(expected_amount * 100), (
            f"balance={balance}, amount={amount}: "
            f"response amount_cents {result['amount_cents']} != expected "
            f"{int(expected_amount * 100)}"
        )

    # Property 2: Validation envelope (reject side)
    @given(pair=amount_outside_envelope())
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_outside_envelope_is_rejected(self, pair: tuple[Decimal, Decimal]) -> None:
        """For any (balance, amount) outside the accept envelope (either
        ``amount < 0.50`` or ``amount > balance``), the service raises
        ``ValueError`` and never calls Stripe.

        **Validates: Requirements 3.3, 3.4**
        """
        balance, amount = pair

        async def _run() -> None:
            invoice = _make_invoice(balance_due=balance, currency="NZD")
            org = _make_org()
            db, create_pi, audit, gen_token = _patch_service_for_property(
                invoice=invoice, org=org,
            )

            with patch(
                "app.modules.payments.service.create_payment_intent", create_pi,
            ), patch(
                "app.modules.payments.service.write_audit_log", audit,
            ), patch(
                "app.modules.payments.service.generate_payment_token",
                new=AsyncMock(side_effect=gen_token),
            ), patch(
                "app.integrations.stripe_billing.get_application_fee_percent",
                new=AsyncMock(return_value=Decimal("0")),
            ):
                with pytest.raises(ValueError):
                    await create_qr_session_for_existing_invoice(
                        db,
                        org_id=invoice.org_id,
                        user_id=uuid.uuid4(),
                        invoice_id=invoice.id,
                        partial_amount=amount,
                    )

            # No PaymentIntent created on the reject path.
            assert create_pi.await_count == 0, (
                f"balance={balance}, amount={amount}: rejected request "
                f"should not create a PaymentIntent"
            )

        asyncio.run(_run())


# ===========================================================================
# Property 3: Webhook records exactly partial
# ===========================================================================


def _make_pi_succeeded_event(
    *,
    invoice_id: uuid.UUID,
    pi_id: str,
    partial_amount: Decimal,
    surcharge_amount: Decimal,
) -> dict:
    """Build a minimal ``payment_intent.succeeded`` event payload for a
    partial payment with the given surcharge breakdown."""
    gross_cents = int((partial_amount + surcharge_amount) * 100)
    return {
        "id": pi_id,
        "amount_received": gross_cents,
        "metadata": {
            "invoice_id": str(invoice_id),
            "platform": "workshoppro_nz",
            "source": "kiosk_qr",
            "original_amount": str(partial_amount.quantize(Decimal("0.01"))),
            "surcharge_amount": str(surcharge_amount.quantize(Decimal("0.01"))),
            "surcharge_method": "card",
            "is_partial_payment": "true",
        },
    }


@st.composite
def partial_with_balance_and_surcharge(draw):
    """Generate (balance, partial, surcharge_pct, surcharge_fixed) where
    the partial fits inside the balance and both stay within sane bounds.
    Returns (balance, partial, pct, fixed).
    """
    balance = draw(
        st.decimals(
            min_value=Decimal("0.50"),
            max_value=Decimal("9999.99"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    partial = draw(
        st.decimals(
            min_value=Decimal("0.50"),
            max_value=balance,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    pct = draw(surcharge_pct_st)
    fixed = draw(surcharge_fixed_st)
    return balance, partial, pct, fixed


class TestP3WebhookRecordsExactlyPartial:
    """For any partial amount ``a`` and surcharge configuration ``(p, f)``,
    after a successful ``payment_intent.succeeded`` event is processed by
    ``handle_stripe_webhook``,

        invoice.balance_due_after == invoice.balance_due_before - a
        invoice.amount_paid_after  == invoice.amount_paid_before  + a

    within 1 cent rounding tolerance. The surcharge ``s`` is recorded
    separately on the Payment row and never contaminates the invoice
    balance ledger.

    **Validates: Requirements 7.1, 7.4**
    """

    # Property 3: Webhook records exactly partial
    @given(args=partial_with_balance_and_surcharge())
    @h_settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_balance_decremented_by_exact_partial(
        self, args: tuple[Decimal, Decimal, Decimal, Decimal],
    ) -> None:
        """``invoice.balance_due_after == balance_before - partial`` (within
        1 cent), regardless of the surcharge amount carried alongside it on
        the PaymentIntent. The surcharge does NOT affect the invoice
        balance ledger.
        """
        balance, partial, pct, fixed = args

        # Compute a surcharge that sits within sane bounds for the partial
        # (balance gross-up formula approximation; we just need a non-
        # negative amount to put on the PI alongside the partial — the
        # webhook handler's behaviour is invariant of the surcharge value).
        from decimal import ROUND_HALF_EVEN
        pct_decimal = pct / Decimal("100")
        # Avoid pct == 100% (which would explode the gross-up); 10% is the
        # MAX_PERCENTAGE in test_surcharge_properties so we are always safe.
        assume(pct_decimal < Decimal("1"))
        denominator = Decimal("1") - pct_decimal
        surcharge_raw = (partial * pct_decimal + fixed) / denominator
        surcharge = surcharge_raw.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN,
        )

        async def _run() -> dict:
            invoice = _make_invoice(
                balance_due=balance,
                amount_paid=Decimal("0.00"),
                total=balance,
                stripe_payment_intent_id="pi_property_partial",
                payment_page_url="https://test.local/pay/property",
                invoice_data_json={
                    "stripe_client_secret": "pi_property_partial_secret",
                },
            )
            db = _WebhookFakeDb(invoice=invoice)
            event_data = _make_pi_succeeded_event(
                invoice_id=invoice.id,
                pi_id="pi_property_partial",
                partial_amount=partial,
                surcharge_amount=surcharge,
            )

            with patch(
                "app.modules.payments.service.write_audit_log",
                new_callable=AsyncMock,
            ):
                result = await handle_stripe_webhook(
                    db,
                    event_type="payment_intent.succeeded",
                    event_data=event_data,
                )
            return {
                "result": result,
                "invoice": invoice,
                "payments_added": db.payments_added,
            }

        captured = asyncio.run(_run())
        result = captured["result"]
        invoice: MagicMock = captured["invoice"]
        payments_added = captured["payments_added"]

        assert result["status"] == "processed", (
            f"balance={balance}, partial={partial}, surcharge=({pct}%, {fixed}): "
            f"webhook unexpectedly returned {result}"
        )

        # Exactly one Payment row inserted.
        payments_only = [p for p in payments_added if isinstance(p, Payment)]
        assert len(payments_only) == 1, (
            f"Expected exactly one Payment row, got {len(payments_only)}"
        )
        recorded = payments_only[0]

        # The Payment row carries the partial as ``amount`` and the
        # surcharge separately — never combined into the invoice balance.
        # The webhook may cap pay_amount at balance_due, so account for
        # that when comparing.
        expected_pay = min(partial, balance).quantize(Decimal("0.01"))
        assert abs(recorded.amount - expected_pay) <= Decimal("0.01"), (
            f"Payment.amount {recorded.amount} differs from partial "
            f"{expected_pay} by more than 1c"
        )

        # invoice.balance_due decremented by exactly the recorded partial,
        # within 1 cent rounding tolerance.
        expected_balance_after = (balance - expected_pay).quantize(Decimal("0.01"))
        assert abs(invoice.balance_due - expected_balance_after) <= Decimal("0.01"), (
            f"balance_before={balance}, partial={partial}, surcharge=({pct}%, {fixed}): "
            f"balance_after={invoice.balance_due}, expected "
            f"{expected_balance_after} (diff > 1c)"
        )

        # invoice.amount_paid incremented by exactly the recorded partial.
        assert abs(invoice.amount_paid - expected_pay) <= Decimal("0.01"), (
            f"amount_paid={invoice.amount_paid}, expected {expected_pay} "
            f"(diff > 1c)"
        )

        # Invariant: balance_after + amount_paid_after == balance_before
        # (within 1c rounding) — the ledger never silently absorbs the
        # surcharge.
        ledger_total = invoice.balance_due + invoice.amount_paid
        assert abs(ledger_total - balance) <= Decimal("0.01"), (
            f"Ledger drift: balance_after + amount_paid_after = {ledger_total}, "
            f"expected {balance} (within 1c)"
        )
