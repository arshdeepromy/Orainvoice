"""Integration tests for the QR partial-payment flow.

Verifies the end-to-end orchestration of `create_qr_session_for_existing_invoice`,
the public payment page, the `update-surcharge` endpoint, the Stripe webhook
handler, and the post-webhook token / invoice cleanup on the success path.

Tests use AsyncMock-based DB sessions and patch the Stripe-touching
integration helpers (`create_payment_intent`, `_cancel_payment_intent`) so the
suite is hermetic — no real DB, no real network calls. The orchestration
itself (validation gates, reuse-branch guard, application-fee proportionality,
metadata, audit log emission, idempotency) is exercised against the real
service code.

**Validates: Requirements 3.x, 4.x, 5.x, 6.x, 7.x, 8.x, 9.x, 10.x, 11.x**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure SQLAlchemy mappers are configurable in any test that constructs
# select() statements that touch relationships across modules. Mirrors the
# model-loading block in app/main.py and tests/fleet_portal/conftest.py.
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
from app.modules.payments.models import Payment, PaymentToken
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
# Helpers — build mock domain objects and DB sessions
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
    inv.invoice_number = "INV-0001"
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


def _make_token(
    *,
    invoice_id: uuid.UUID,
    org_id: uuid.UUID,
    last_pi_amount_cents: int | None = None,
    amount_override: Decimal | None = None,
    is_active: bool = True,
    token_string: str | None = None,
) -> MagicMock:
    tok = MagicMock(spec=PaymentToken)
    tok.id = uuid.uuid4()
    tok.token = token_string or f"tok_{uuid.uuid4().hex}"
    tok.invoice_id = invoice_id
    tok.org_id = org_id
    tok.is_active = is_active
    tok.expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
    tok.last_pi_amount_cents = last_pi_amount_cents
    tok.amount_override = amount_override
    return tok


class _FakeDb:
    """An AsyncMock-flavoured DB that returns pre-programmed results.

    `select_results` is a list of values to return, in order, one per
    `select()` call. The queue advances on every `db.execute(select_stmt)`.
    `execute` calls for `update(...)` and `delete(...)` statements return a
    no-op result so the service code's `await db.execute(...)` never
    raises.
    """

    def __init__(self, select_results: list[Any] | None = None) -> None:
        self._select_queue: list[Any] = list(select_results or [])
        self.added: list[Any] = []
        self.flushes = 0
        self.refreshes = 0
        self.update_calls: list[Any] = []
        self.delete_calls: list[Any] = []
        self.refresh = AsyncMock(side_effect=self._refresh)
        self.execute = AsyncMock(side_effect=self._execute)
        self.flush = AsyncMock(side_effect=self._flush)
        self.add = MagicMock(side_effect=self._add)

    async def _flush(self) -> None:
        self.flushes += 1

    async def _refresh(self, obj: Any) -> None:
        self.refreshes += 1

    def _add(self, obj: Any) -> None:
        self.added.append(obj)

    async def _execute(self, stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        from sqlalchemy import Delete, Select, Update

        # Identify the kind of statement so we can pop the correct fixture.
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

        # Fallback (e.g. ad-hoc text/raw SQL) — return an empty result.
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result


def _patch_service(
    *,
    invoice: MagicMock,
    org: MagicMock,
    existing_token: MagicMock | None = None,
    new_pi_id: str = "pi_new_test_123",
    cancel_side_effect: Exception | None = None,
    fee_percent: Decimal = Decimal("2.5"),
):
    """Patch every external-effect dependency of
    `create_qr_session_for_existing_invoice` so the service can run end-to-end
    against a fake DB. Returns a tuple of patched mocks for assertions.

    The ``select_results`` queue is built to match the actual select() call
    order in the service:

    1. ``select(Invoice).where(...)``
    2. (only when ``invoice.payment_page_url`` AND
       ``invoice.stripe_payment_intent_id`` are set) ``select(PaymentToken)``
    3. ``select(Organisation)`` — skipped when the reuse branch returns
       early (i.e. ``existing_token`` matches the requested cents)
    """
    select_results: list[Any] = [invoice]
    if invoice.payment_page_url and invoice.stripe_payment_intent_id:
        select_results.append(existing_token)
    select_results.append(org)

    db = _FakeDb(select_results=select_results)

    create_pi_mock = AsyncMock(
        return_value={
            "payment_intent_id": new_pi_id,
            "client_secret": f"{new_pi_id}_secret_xyz",
        }
    )

    if cancel_side_effect is not None:
        cancel_pi_mock = AsyncMock(side_effect=cancel_side_effect)
    else:
        cancel_pi_mock = AsyncMock(return_value={"status": "canceled"})

    audit_log_mock = AsyncMock()

    async def _fake_generate_token(
        db_, *, org_id, invoice_id, base_url=None, amount_override=None,
    ):
        token_str = f"tok_{uuid.uuid4().hex}"
        return token_str, f"https://test.local/pay/{token_str}"

    return (
        db,
        create_pi_mock,
        cancel_pi_mock,
        audit_log_mock,
        _fake_generate_token,
    )


# ---------------------------------------------------------------------------
# Section 1 — Validation and amount resolution (Req 3.x, 4.x)
# ---------------------------------------------------------------------------


class TestPartialAmountResolution:
    """`create_qr_session_for_existing_invoice` resolves the billing amount
    correctly based on the optional `partial_amount` keyword.

    **Validates: Requirements 3.2-3.6, 4.1**
    """

    @pytest.mark.asyncio
    async def test_partial_amount_omitted_uses_balance(self):
        """Omitting `partial_amount` yields a PI for the full balance and a
        token row with `amount_override=NULL` (i.e. None).

        **Validates: Requirements 3.5, 4.1**
        """
        invoice = _make_invoice(balance_due=Decimal("250.00"))
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=None,
        )

        captured_overrides: list[Decimal | None] = []

        async def _capture_gen(db_, *, org_id, invoice_id, base_url=None, amount_override=None):
            captured_overrides.append(amount_override)
            tok = f"tok_{uuid.uuid4().hex}"
            return tok, f"https://test.local/pay/{tok}"

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=_capture_gen),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            result = await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=None,
            )

        # PI was created for the full balance.
        assert create_pi.await_count == 1
        kwargs = create_pi.await_args.kwargs
        assert kwargs["amount"] == 25000  # 250.00 × 100
        # Token override is NULL (None) on the new payment_token.
        assert captured_overrides == [None]
        # Response amount is the full balance.
        assert result["amount"] == Decimal("250.00")
        assert result["amount_cents"] == 25000

    @pytest.mark.asyncio
    async def test_partial_amount_below_stripe_min(self):
        """A partial amount below the per-currency Stripe minimum raises
        ValueError (HTTP 400 at the endpoint layer) with a friendly detail.

        **Validates: Requirements 3.3, 8.2**
        """
        invoice = _make_invoice(balance_due=Decimal("250.00"), currency="NZD")
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org,
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit,
        ):
            with pytest.raises(ValueError) as exc_info:
                await create_qr_session_for_existing_invoice(
                    db,
                    org_id=invoice.org_id,
                    user_id=uuid.uuid4(),
                    invoice_id=invoice.id,
                    partial_amount=Decimal("0.49"),
                )

        msg = str(exc_info.value)
        assert "0.50" in msg
        assert "NZD" in msg
        # No PaymentIntent was created.
        assert create_pi.await_count == 0

    @pytest.mark.asyncio
    async def test_partial_amount_above_balance(self):
        """A partial amount exceeding `invoice.balance_due` raises ValueError
        with a friendly detail.

        **Validates: Requirement 3.4**
        """
        invoice = _make_invoice(balance_due=Decimal("100.00"))
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org,
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit,
        ):
            with pytest.raises(ValueError) as exc_info:
                await create_qr_session_for_existing_invoice(
                    db,
                    org_id=invoice.org_id,
                    user_id=uuid.uuid4(),
                    invoice_id=invoice.id,
                    partial_amount=Decimal("100.01"),
                )

        msg = str(exc_info.value)
        assert "exceed" in msg.lower() or "balance" in msg.lower()
        assert create_pi.await_count == 0

    @pytest.mark.asyncio
    async def test_partial_amount_equal_balance_still_partial(self):
        """`partial_amount == invoice.balance_due` still routes through the
        partial path: token gets `amount_override=balance` and PI metadata
        carries `is_partial_payment="true"`.

        **Validates: Requirements 2.4, 3.6, 4.4**
        """
        invoice = _make_invoice(balance_due=Decimal("150.00"))
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org,
        )

        captured_overrides: list[Decimal | None] = []

        async def _capture_gen(db_, *, org_id, invoice_id, base_url=None, amount_override=None):
            captured_overrides.append(amount_override)
            tok = f"tok_{uuid.uuid4().hex}"
            return tok, f"https://test.local/pay/{tok}"

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=_capture_gen),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("150.00"),
            )

        # Token has amount_override == balance (NOT None) — we are explicitly
        # in the partial branch even when the partial equals the balance.
        assert captured_overrides == [Decimal("150.00")]

        # PI metadata records is_partial_payment="true".
        kwargs = create_pi.await_args.kwargs
        meta = kwargs["extra_metadata"]
        assert meta["is_partial_payment"] == "true"
        assert meta["original_amount"] == "150.00"


# ---------------------------------------------------------------------------
# Section 2 — Reuse branch (Req 5.1, 5.2, 5.3, 5.4, 9.x)
# ---------------------------------------------------------------------------


class TestReuseBranch:
    """The narrowed reuse-branch guard reuses an existing PI only when the
    cached `last_pi_amount_cents` matches the requested cents.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 9.1, 9.2, 9.3**
    """

    @pytest.mark.asyncio
    async def test_reuse_branch_same_amount(self):
        """Second call with the same amount reuses the existing PI: no new
        PaymentIntent created, no audit log entry emitted.

        **Validates: Requirements 5.1, 9.2**
        """
        invoice = _make_invoice(
            balance_due=Decimal("100.00"),
            stripe_payment_intent_id="pi_existing_abc",
            payment_page_url="https://test.local/pay/old",
        )
        existing_token = _make_token(
            invoice_id=invoice.id,
            org_id=invoice.org_id,
            last_pi_amount_cents=10000,  # matches requested 100.00
        )
        org = _make_org()
        db, create_pi, cancel_pi, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=existing_token,
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service._cancel_payment_intent", cancel_pi,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=gen_token),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            result = await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("100.00"),
            )

        # No new PI, no cancel, no audit entry — pure reuse.
        assert create_pi.await_count == 0
        assert cancel_pi.await_count == 0
        assert audit.await_count == 0
        # Returned session_id is the existing PI ID.
        assert result["session_id"] == "pi_existing_abc"
        assert result["amount"] == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_reuse_branch_different_amount_cancels_old_pi(self):
        """Second call with a different amount: cancel old PI, create new PI,
        old token marked inactive, both `payment.qr_session_superseded` and
        `payment.qr_session_created` audit entries emitted.

        **Validates: Requirements 5.2, 5.3, 5.4, 9.1, 9.3**
        """
        invoice = _make_invoice(
            balance_due=Decimal("300.00"),
            stripe_payment_intent_id="pi_old_xyz",
            payment_page_url="https://test.local/pay/old",
        )
        existing_token = _make_token(
            invoice_id=invoice.id,
            org_id=invoice.org_id,
            last_pi_amount_cents=10000,  # cached at 100.00 — request will be 200.00
        )
        org = _make_org()
        db, create_pi, cancel_pi, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=existing_token,
            new_pi_id="pi_new_after_cancel",
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service._cancel_payment_intent", cancel_pi,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=gen_token),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            result = await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("200.00"),
            )

        # Old PI cancellation attempted with the existing PI id.
        assert cancel_pi.await_count == 1
        assert cancel_pi.await_args.kwargs["pi_id"] == "pi_old_xyz"

        # Brand-new PI minted.
        assert create_pi.await_count == 1
        assert result["session_id"] == "pi_new_after_cancel"
        assert result["amount"] == Decimal("200.00")

        # Audit log: superseded fired BEFORE created.
        actions = [call.kwargs["action"] for call in audit.await_args_list]
        assert "payment.qr_session_superseded" in actions
        assert "payment.qr_session_created" in actions

        # Old token was deactivated at least once via update().
        # The narrowed reuse-branch path issues an UPDATE on payment_tokens.
        assert len(db.update_calls) >= 1

    @pytest.mark.asyncio
    async def test_reuse_branch_stripe_cancel_failure_continues(self):
        """When Stripe rejects the cancel call (e.g. 400 PI in terminal
        state), the service still creates the new PI and still emits the
        `payment.qr_session_superseded` audit entry. The error is logged at
        WARNING.

        **Validates: Requirement 5.3**
        """
        invoice = _make_invoice(
            balance_due=Decimal("300.00"),
            stripe_payment_intent_id="pi_dead_old",
            payment_page_url="https://test.local/pay/old",
        )
        existing_token = _make_token(
            invoice_id=invoice.id,
            org_id=invoice.org_id,
            last_pi_amount_cents=15000,
        )
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=existing_token,
            new_pi_id="pi_after_failed_cancel",
            cancel_side_effect=RuntimeError("Stripe 400 unexpected_state"),
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi,
        ), patch(
            "app.modules.payments.service._cancel_payment_intent",
            new=AsyncMock(side_effect=RuntimeError("Stripe rejected cancel")),
        ) as cancel_mock, patch(
            "app.modules.payments.service.write_audit_log", audit,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=gen_token),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            result = await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("100.00"),
            )

        # Cancel was attempted and failed — but creation continued.
        assert cancel_mock.await_count == 1
        assert create_pi.await_count == 1
        assert result["session_id"] == "pi_after_failed_cancel"

        # Both audit entries still emitted despite cancel failure.
        actions = [call.kwargs["action"] for call in audit.await_args_list]
        assert "payment.qr_session_superseded" in actions
        assert "payment.qr_session_created" in actions



# ---------------------------------------------------------------------------
# Section 3 — PaymentIntent + pending session shape (Req 4.1-4.6)
# ---------------------------------------------------------------------------


class TestPaymentIntentAndPendingSession:
    """The PaymentIntent and `pending_qr_sessions` row carry the resolved
    amount; the application fee scales with it; and the API response echoes
    it back to the org user.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6**
    """

    @pytest.mark.asyncio
    async def test_application_fee_proportional_to_partial(self):
        """`application_fee_amount = int(partial_cents × fee_pct / 100)` —
        proportional to the partial amount, never the invoice balance.

        **Validates: Requirement 4.2**
        """
        invoice = _make_invoice(balance_due=Decimal("500.00"))
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=None,
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
            new=AsyncMock(return_value=Decimal("2.5")),
        ):
            await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("100.00"),
            )

        # Fee on the partial: int(10000 × 2.5 / 100) = 250 cents.
        kwargs = create_pi.await_args.kwargs
        assert kwargs["amount"] == 10000  # partial only
        assert kwargs["application_fee_amount"] == 250  # 2.5% of 10000

        # Sanity check: the fee is NOT the proportion of the full balance
        # (would have been int(50000 × 2.5 / 100) = 1250).
        assert kwargs["application_fee_amount"] != 1250

    @pytest.mark.asyncio
    async def test_metadata_is_partial_payment_flag(self):
        """`metadata.is_partial_payment` is "true" for partial flows and
        "false" for full-balance flows; `original_amount` always carries the
        resolved amount.

        **Validates: Requirements 4.3, 4.4**
        """
        # Full-balance call (no partial_amount).
        invoice_full = _make_invoice(balance_due=Decimal("123.45"))
        org = _make_org()
        db_full, create_pi_full, _, audit_full, gen_token = _patch_service(
            invoice=invoice_full, org=org, existing_token=None,
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi_full,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit_full,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=gen_token),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            await create_qr_session_for_existing_invoice(
                db_full,
                org_id=invoice_full.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice_full.id,
                partial_amount=None,
            )

        meta_full = create_pi_full.await_args.kwargs["extra_metadata"]
        assert meta_full["is_partial_payment"] == "false"
        assert meta_full["original_amount"] == "123.45"
        assert meta_full["source"] == "kiosk_qr"

        # Partial call.
        invoice_partial = _make_invoice(balance_due=Decimal("250.00"))
        db_partial, create_pi_partial, _, audit_partial, gen_token = _patch_service(
            invoice=invoice_partial, org=org, existing_token=None,
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi_partial,
        ), patch(
            "app.modules.payments.service.write_audit_log", audit_partial,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=gen_token),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            await create_qr_session_for_existing_invoice(
                db_partial,
                org_id=invoice_partial.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice_partial.id,
                partial_amount=Decimal("75.50"),
            )

        meta_partial = create_pi_partial.await_args.kwargs["extra_metadata"]
        assert meta_partial["is_partial_payment"] == "true"
        assert meta_partial["original_amount"] == "75.50"
        assert meta_partial["source"] == "kiosk_qr"

    @pytest.mark.asyncio
    async def test_pending_qr_session_amount_matches_partial(self):
        """The inserted `pending_qr_sessions` row carries the resolved
        partial amount, not the invoice's full balance.

        **Validates: Requirement 4.5**
        """
        from app.modules.payments.models import PendingQrSession

        invoice = _make_invoice(balance_due=Decimal("300.00"))
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=None,
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
            await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("75.00"),
            )

        # The row added to pending_qr_sessions carries the partial.
        pending_rows = [
            row for row in db.added if isinstance(row, PendingQrSession)
        ]
        assert len(pending_rows) == 1
        assert pending_rows[0].amount == Decimal("75.00")
        # And NOT the balance.
        assert pending_rows[0].amount != invoice.balance_due

    @pytest.mark.asyncio
    async def test_response_amount_matches_partial(self):
        """The endpoint response's `amount` field equals the resolved
        partial amount.

        **Validates: Requirement 4.6**
        """
        invoice = _make_invoice(balance_due=Decimal("400.00"))
        org = _make_org()
        db, create_pi, _, audit, gen_token = _patch_service(
            invoice=invoice, org=org, existing_token=None,
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
            result = await create_qr_session_for_existing_invoice(
                db,
                org_id=invoice.org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("125.50"),
            )

        assert result["amount"] == Decimal("125.50")
        assert result["amount_cents"] == 12550
        assert result["amount"] != invoice.balance_due



# ---------------------------------------------------------------------------
# Section 4 — Public payment page honours amount_override (Req 6.x)
# ---------------------------------------------------------------------------


class TestPublicPaymentPageOverride:
    """`GET /public/pay/{token}` and `POST /public/pay/{token}/update-surcharge`
    both honour `payment_token.amount_override` when set, surfacing the partial
    amount as the authoritative balance instead of the invoice's full
    `balance_due`.

    **Validates: Requirements 6.2, 6.3, 6.4**
    """

    @pytest.mark.asyncio
    async def test_public_pay_get_uses_amount_override(self):
        """`GET /public/pay/{token}` returns `balance_due == amount_override`
        and `is_partial_payment == True` when the token carries an override.

        **Validates: Requirements 6.2, 6.3**
        """
        from app.modules.payments.public_router import get_payment_page

        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            balance_due=Decimal("300.00"),
            stripe_payment_intent_id="pi_partial_test",
            invoice_data_json={"stripe_client_secret": "pi_partial_test_secret_xyz"},
        )
        # The PaymentToken row visible to the endpoint carries the override.
        token_obj = _make_token(
            invoice_id=invoice.id,
            org_id=org_id,
            amount_override=Decimal("100.00"),
        )

        org = MagicMock()
        org.id = org_id
        org.name = "Test Org"
        org.settings = {"surcharge_enabled": False}
        org.stripe_connect_account_id = "acct_test"

        # Wire the invoice line items so selectinload() does not blow up:
        invoice.line_items = []
        invoice.subtotal = Decimal("260.87")
        invoice.gst_amount = Decimal("39.13")
        invoice.invoice_number = "INV-0099"
        invoice.issue_date = datetime.now(timezone.utc).date()
        invoice.due_date = datetime.now(timezone.utc).date()

        db = _FakeDb(select_results=[invoice, org])

        request = MagicMock()
        request.client.host = "127.0.0.1"

        with patch(
            "app.modules.payments.public_router.validate_payment_token",
            new=AsyncMock(return_value=token_obj),
        ), patch(
            "app.modules.payments.public_router._check_payment_page_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.integrations.stripe_billing.get_stripe_publishable_key",
            new=AsyncMock(return_value="pk_test_xxx"),
        ):
            response = await get_payment_page(token=token_obj.token, request=request, db=db)

        # The PaymentPageResponse echoes the override as the displayed
        # balance_due, and is_partial_payment flips True.
        assert hasattr(response, "balance_due")
        assert response.balance_due == Decimal("100.00")
        assert response.is_partial_payment is True
        # The full invoice balance is NOT what's surfaced.
        assert response.balance_due != invoice.balance_due

    @pytest.mark.asyncio
    async def test_update_surcharge_uses_amount_override(self):
        """`POST /public/pay/{token}/update-surcharge`: surcharge is computed
        against `amount_override` (the partial), not against the full invoice
        balance, and the PI is updated to `(override + surcharge) × 100`.

        **Validates: Requirement 6.4**
        """
        from app.modules.payments.public_router import update_surcharge
        from app.modules.payments.schemas import UpdateSurchargeRequest

        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            balance_due=Decimal("300.00"),
            stripe_payment_intent_id="pi_partial_surcharge",
        )
        token_obj = _make_token(
            invoice_id=invoice.id,
            org_id=org_id,
            amount_override=Decimal("100.00"),
        )

        org = MagicMock()
        org.id = org_id
        org.stripe_connect_account_id = "acct_test_connect"
        org.settings = {
            "surcharge_enabled": True,
            "surcharge_rates": {
                "card": {"percentage": "2.9", "fixed": "0.30", "enabled": True},
            },
        }

        db = _FakeDb(select_results=[invoice, org])

        request = MagicMock()
        request.client.host = "127.0.0.1"

        # Capture what's actually posted to Stripe.
        posted_payloads: list[dict] = []

        class _FakeStripeResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {}

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, url, *, data, auth=None, headers=None):
                posted_payloads.append({"url": url, "data": dict(data)})
                return _FakeStripeResponse()

        with patch(
            "app.modules.payments.public_router.validate_payment_token",
            new=AsyncMock(return_value=token_obj),
        ), patch(
            "app.modules.payments.public_router._check_payment_page_rate_limit",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.integrations.stripe_billing.get_stripe_secret_key",
            new=AsyncMock(return_value="sk_test_xxx"),
        ), patch(
            "httpx.AsyncClient",
            new=lambda *a, **kw: _FakeAsyncClient(),
        ):
            response = await update_surcharge(
                token=token_obj.token,
                body=UpdateSurchargeRequest(payment_method_type="card"),
                request=request,
                db=db,
            )

        # Surcharge gross-up against $100 (NOT $300).
        # Standard formula: (100 × 0.029 + 0.30) / (1 − 0.029) ≈ $3.30
        # The implementation uses get_surcharge_for_method which we don't
        # reproduce here — instead we assert: surcharge < 5 (sane upper
        # bound for $100 partial × ~3% card fee) and the PI was updated
        # to a total in the right range.
        from app.modules.payments.schemas import UpdateSurchargeResponse
        assert isinstance(response, UpdateSurchargeResponse)
        # The PI was updated.
        assert len(posted_payloads) == 1
        amount_cents = int(posted_payloads[0]["data"]["amount"])
        # PI total = (100 + surcharge) × 100. surcharge ≤ ~$5 cap.
        assert 10000 <= amount_cents <= 10500
        # And NOT scaled to the full invoice balance.
        assert amount_cents < 30000
        # Stripe metadata records original_amount as the override (100), not
        # the invoice balance (300).
        assert posted_payloads[0]["data"]["metadata[original_amount]"] == "100.00"



# ---------------------------------------------------------------------------
# Section 5 — Webhook records partial correctly (Req 7.x)
# ---------------------------------------------------------------------------


def _make_pi_succeeded_event(
    *,
    invoice_id: uuid.UUID,
    pi_id: str,
    amount_received_cents: int,
    original_amount: str | None,
    surcharge_amount: str = "0",
    is_partial_payment: str | None = None,
) -> dict:
    """Build a minimal ``payment_intent.succeeded`` event payload."""
    metadata: dict[str, str] = {
        "invoice_id": str(invoice_id),
        "platform": "workshoppro_nz",
        "source": "kiosk_qr",
    }
    if original_amount is not None:
        metadata["original_amount"] = original_amount
    if surcharge_amount:
        metadata["surcharge_amount"] = surcharge_amount
        metadata["surcharge_method"] = "card"
    if is_partial_payment is not None:
        metadata["is_partial_payment"] = is_partial_payment

    return {
        "id": pi_id,
        "amount_received": amount_received_cents,
        "metadata": metadata,
    }


class _WebhookFakeDb:
    """Fake DB tailored to the webhook handler's call sequence:

    1. ``SELECT invoice WHERE id = ... FOR UPDATE``
    2. ``SELECT Payment WHERE stripe_payment_intent_id = ...`` (idempotency)
    3. ``db.add(Payment(...))``
    4. ``db.execute(update(PaymentToken)...)`` (Task 18.2 deactivation)
    5. ``SELECT Customer WHERE id = ...`` (best-effort email)

    `existing_payments` is keyed by stripe_payment_intent_id and pre-populated
    with any prior Payment rows (used for the duplicate-event test).
    """

    def __init__(
        self,
        *,
        invoice: MagicMock,
        existing_payments: dict[str, MagicMock] | None = None,
    ) -> None:
        self.invoice = invoice
        self.existing_payments: dict[str, MagicMock] = dict(existing_payments or {})
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
        # When a Payment is added, register it in the idempotency map
        # by its stripe_payment_intent_id so subsequent duplicate webhook
        # events for the same PI find it via the SELECT.
        if isinstance(obj, Payment) and obj.stripe_payment_intent_id:
            self.existing_payments[obj.stripe_payment_intent_id] = obj

    async def _execute(self, stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        from sqlalchemy import Delete, Select, Update

        if isinstance(stmt, Select):
            # Determine which table this select reads FROM. The webhook
            # handler emits SELECTs against invoices, payments, and
            # customers, in that order.
            entity = self._select_entity(stmt)
            result = MagicMock()
            if entity == "invoices":
                result.scalar_one_or_none.return_value = self.invoice
                return result
            if entity == "payments":
                # Idempotency check — look up the PI literal that was bound
                # on the WHERE clause and return the registered payment for
                # that PI if any.
                pi_id_filter = self._extract_pi_id_filter(stmt)
                if pi_id_filter and pi_id_filter in self.existing_payments:
                    result.scalar_one_or_none.return_value = (
                        self.existing_payments[pi_id_filter]
                    )
                else:
                    result.scalar_one_or_none.return_value = None
                return result
            if entity == "customers":
                # No customer email — skip the best-effort receipt email.
                result.scalar_one_or_none.return_value = None
                return result
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
        """Return the lowercased table name a SELECT reads FROM, or None."""
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
        """Extract the stripe_payment_intent_id parameter value bound on the
        SELECT (used by the idempotency-check query). Falls back to None
        when the value isn't a literal we can read directly.
        """
        try:
            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            sql = str(compiled)
            # Look for the literal between quotes after stripe_payment_intent_id =
            import re
            m = re.search(r"stripe_payment_intent_id\s*=\s*'([^']+)'", sql)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None


class TestWebhookRecordsPartial:
    """The Stripe webhook handler records partial payments correctly: a
    Payment row of the partial amount is inserted, the invoice's
    `amount_paid` and `balance_due` move by exactly that partial, and the
    invoice transitions to `partially_paid` (or `paid` on the settling
    partial).

    **Validates: Requirements 7.1, 7.4**
    """

    @pytest.mark.asyncio
    async def test_webhook_records_partial_correctly(self):
        """Partial PI confirmation → exactly-one Payment row, balance_due
        decremented by the partial, status `partially_paid`.

        **Validates: Requirement 7.1**
        """
        invoice = _make_invoice(
            balance_due=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
            stripe_payment_intent_id="pi_partial_1",
            payment_page_url="https://test.local/pay/partial1",
            invoice_data_json={"stripe_client_secret": "pi_partial_1_secret"},
        )
        db = _WebhookFakeDb(invoice=invoice)

        event_data = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_partial_1",
            amount_received_cents=10330,  # partial $100 + $3.30 surcharge
            original_amount="100.00",
            surcharge_amount="3.30",
            is_partial_payment="true",
        )

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ):
            result = await handle_stripe_webhook(
                db,
                event_type="payment_intent.succeeded",
                event_data=event_data,
            )

        assert result["status"] == "processed"
        assert result["invoice_status"] == "partially_paid"
        # Exactly one Payment row added.
        payments_only = [p for p in db.payments_added if isinstance(p, Payment)]
        assert len(payments_only) == 1
        recorded = payments_only[0]
        assert recorded.amount == Decimal("100.00")
        assert recorded.surcharge_amount == Decimal("3.30")
        assert recorded.stripe_payment_intent_id == "pi_partial_1"
        # Invoice: balance_due decremented by the partial; status flipped.
        assert invoice.balance_due == Decimal("200.00")
        assert invoice.amount_paid == Decimal("100.00")
        assert invoice.status == "partially_paid"

    @pytest.mark.asyncio
    async def test_webhook_third_partial_settles_to_paid(self):
        """Three sequential $100 partials on a $300 invoice: status flips
        through partially_paid → partially_paid → paid; three Payment rows;
        cumulative amount_paid = $300.

        **Validates: Requirements 7.1, 7.4**
        """
        invoice = _make_invoice(
            balance_due=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
        )
        db = _WebhookFakeDb(invoice=invoice)

        all_results: list[dict] = []

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ) as audit_mock:
            for i, pi_id in enumerate(["pi_part_a", "pi_part_b", "pi_part_c"], start=1):
                # Reset stripe_payment_intent_id on the invoice for this
                # round (the webhook clears it on the success path of the
                # previous round).
                invoice.stripe_payment_intent_id = pi_id
                invoice.payment_page_url = f"https://test.local/pay/{pi_id}"
                invoice.invoice_data_json = {
                    "stripe_client_secret": f"{pi_id}_secret",
                }

                event_data = _make_pi_succeeded_event(
                    invoice_id=invoice.id,
                    pi_id=pi_id,
                    amount_received_cents=10000,
                    original_amount="100.00",
                    is_partial_payment="true",
                )

                result = await handle_stripe_webhook(
                    db,
                    event_type="payment_intent.succeeded",
                    event_data=event_data,
                )
                all_results.append(result)

        # All three processed.
        assert all(r["status"] == "processed" for r in all_results)
        # Status progression: partial → partial → paid.
        assert all_results[0]["invoice_status"] == "partially_paid"
        assert all_results[1]["invoice_status"] == "partially_paid"
        assert all_results[2]["invoice_status"] == "paid"

        # Three Payment rows.
        payments_only = [p for p in db.payments_added if isinstance(p, Payment)]
        assert len(payments_only) == 3
        # Three distinct PI IDs.
        pi_ids = {p.stripe_payment_intent_id for p in payments_only}
        assert pi_ids == {"pi_part_a", "pi_part_b", "pi_part_c"}
        # Cumulative.
        assert invoice.amount_paid == Decimal("300.00")
        assert invoice.balance_due == Decimal("0.00")
        assert invoice.status == "paid"

        # Three audit log entries fired.
        actions = [c.kwargs["action"] for c in audit_mock.await_args_list]
        assert actions.count("payment.stripe_webhook_received") == 3

    @pytest.mark.asyncio
    async def test_webhook_duplicate_event_for_partial_pi_idempotent(self):
        """Firing the SAME `payment_intent.succeeded` event twice for the
        same partial PI: exactly ONE Payment row, exactly ONE balance
        decrement, no double-spend. This is the highest-value test in the
        list — getting it wrong silently double-debits the customer.

        Stripe sends webhook events at-least-once. The existing
        `SELECT WHERE stripe_payment_intent_id = X AND is_refund = False`
        idempotency guard must protect partial flows the same way it protects
        full payments.

        **Validates: Requirement 7.3**
        """
        invoice = _make_invoice(
            balance_due=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
            stripe_payment_intent_id="pi_dup_test",
        )
        db = _WebhookFakeDb(invoice=invoice)

        event_data = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_dup_test",
            amount_received_cents=10000,
            original_amount="100.00",
            is_partial_payment="true",
        )

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ):
            first = await handle_stripe_webhook(
                db,
                event_type="payment_intent.succeeded",
                event_data=event_data,
            )
            second = await handle_stripe_webhook(
                db,
                event_type="payment_intent.succeeded",
                event_data=event_data,
            )

        # First call processed; second call ignored as duplicate.
        assert first["status"] == "processed"
        assert second["status"] == "ignored"
        assert "duplicate" in second["reason"].lower()

        # Exactly ONE Payment row.
        payments_only = [p for p in db.payments_added if isinstance(p, Payment)]
        assert len(payments_only) == 1

        # Exactly ONE balance decrement: 300 - 100 = 200, NOT 100.
        assert invoice.balance_due == Decimal("200.00")
        assert invoice.amount_paid == Decimal("100.00")
        assert invoice.status == "partially_paid"

    @pytest.mark.asyncio
    async def test_webhook_partial_then_duplicate_then_second_partial(self):
        """Sequence: fire partial PI #1 succeeded → fire DUPLICATE of PI #1
        succeeded (must be ignored) → fire partial PI #2 succeeded (must
        record). Confirms idempotency keys are per-PI, not per-invoice.

        **Validates: Requirement 7.3**
        """
        invoice = _make_invoice(
            balance_due=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
            stripe_payment_intent_id="pi_first",
        )
        db = _WebhookFakeDb(invoice=invoice)

        ev1 = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_first",
            amount_received_cents=10000,
            original_amount="100.00",
            is_partial_payment="true",
        )
        ev2 = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_second",
            amount_received_cents=10000,
            original_amount="100.00",
            is_partial_payment="true",
        )

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ):
            r1 = await handle_stripe_webhook(
                db, event_type="payment_intent.succeeded", event_data=ev1,
            )
            # Duplicate PI #1 — must be ignored.
            r1_dup = await handle_stripe_webhook(
                db, event_type="payment_intent.succeeded", event_data=ev1,
            )
            # Reset PI on invoice ahead of PI #2 (in real flow the org user
            # generates a fresh QR session which clears stale PI fields).
            invoice.stripe_payment_intent_id = "pi_second"
            r2 = await handle_stripe_webhook(
                db, event_type="payment_intent.succeeded", event_data=ev2,
            )

        assert r1["status"] == "processed"
        assert r1_dup["status"] == "ignored"
        assert "duplicate" in r1_dup["reason"].lower()
        assert r2["status"] == "processed"

        # TWO Payment rows total (one each for #1 and #2; duplicate ignored).
        payments_only = [p for p in db.payments_added if isinstance(p, Payment)]
        assert len(payments_only) == 2
        pi_ids = {p.stripe_payment_intent_id for p in payments_only}
        assert pi_ids == {"pi_first", "pi_second"}
        # Balance moved by exactly $200 across the two distinct partials.
        assert invoice.balance_due == Decimal("100.00")
        assert invoice.amount_paid == Decimal("200.00")



# ---------------------------------------------------------------------------
# Section 6 — Post-webhook cleanup and token lifecycle (Tasks 18.3-18.6)
# ---------------------------------------------------------------------------


class TestWebhookPostPaymentCleanup:
    """After a successful payment is recorded, the webhook handler clears
    the invoice's stale PI fields and deactivates active payment_tokens for
    the invoice. These regression-fixes were discovered during the qr-
    partial-payment code audit (Tasks 18.1, 18.2).

    **Validates: Requirements 7.1, 7.2 (multi-partial settlement)**
    """

    @pytest.mark.asyncio
    async def test_webhook_clears_stale_pi_fields(self):
        """After webhook records a successful payment:
        - invoice.stripe_payment_intent_id is None
        - invoice.payment_page_url is None
        - invoice.invoice_data_json["stripe_client_secret"] is None / absent

        **Validates: Task 18.3 (Tasks 18.1 implementation)**
        """
        invoice = _make_invoice(
            balance_due=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            stripe_payment_intent_id="pi_to_clear",
            payment_page_url="https://test.local/pay/old",
            invoice_data_json={
                "stripe_client_secret": "pi_to_clear_secret_xyz",
                "other_meta": "preserved",
            },
        )
        db = _WebhookFakeDb(invoice=invoice)

        event_data = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_to_clear",
            amount_received_cents=10000,
            original_amount="100.00",
            is_partial_payment="false",  # full payment for clarity
        )

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ):
            result = await handle_stripe_webhook(
                db,
                event_type="payment_intent.succeeded",
                event_data=event_data,
            )

        assert result["status"] == "processed"
        # PI fields wiped.
        assert invoice.stripe_payment_intent_id is None
        assert invoice.payment_page_url is None
        # `stripe_client_secret` removed from invoice_data_json, but other
        # keys preserved.
        assert invoice.invoice_data_json.get("stripe_client_secret") is None
        assert invoice.invoice_data_json.get("other_meta") == "preserved"

    @pytest.mark.asyncio
    async def test_webhook_deactivates_payment_tokens(self):
        """A token T1 is active on invoice I before payment. After the
        webhook records the payment:
        - T1.is_active is False
        - GET /public/pay/{T1} returns HTTP 404 "Invalid payment link"

        **Validates: Task 18.4 (Task 18.2 implementation)**
        """
        from app.modules.payments.public_router import get_payment_page

        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            balance_due=Decimal("100.00"),
            amount_paid=Decimal("0.00"),
            stripe_payment_intent_id="pi_with_token",
        )
        token_t1 = _make_token(
            invoice_id=invoice.id,
            org_id=org_id,
            amount_override=None,
        )
        # Verify the test fixture starts active.
        assert token_t1.is_active is True

        # The webhook handler issues an UPDATE on PaymentToken. We mirror
        # the effect into our token mock by intercepting the update_calls.
        class _DeactivatingDb(_WebhookFakeDb):
            def __init__(self, *, invoice, token_to_track):
                super().__init__(invoice=invoice)
                self._token = token_to_track

            async def _execute(self, stmt, *args, **kwargs):
                from sqlalchemy import Update
                if isinstance(stmt, Update):
                    # Look at the compiled statement to see if this is the
                    # PaymentToken-deactivation UPDATE.
                    try:
                        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                    except Exception:
                        compiled = str(stmt)
                    if "payment_tokens" in compiled.lower() and "is_active" in compiled.lower():
                        if (
                            self._token.invoice_id == self.invoice.id
                            and self._token.is_active is True
                        ):
                            self._token.is_active = False
                return await super()._execute(stmt, *args, **kwargs)

        db = _DeactivatingDb(invoice=invoice, token_to_track=token_t1)

        event_data = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_with_token",
            amount_received_cents=10000,
            original_amount="100.00",
            is_partial_payment="false",
        )

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ):
            await handle_stripe_webhook(
                db,
                event_type="payment_intent.succeeded",
                event_data=event_data,
            )

        # T1 deactivated by the webhook.
        assert token_t1.is_active is False

        # Now GET /public/pay/{T1} → 404 "Invalid payment link".
        # `validate_payment_token` only returns active tokens, so an
        # inactive token resolves to None.
        page_db = _FakeDb(select_results=[])

        request = MagicMock()
        request.client.host = "127.0.0.1"

        with patch(
            "app.modules.payments.public_router.validate_payment_token",
            new=AsyncMock(return_value=None),  # token is inactive
        ), patch(
            "app.modules.payments.public_router._check_payment_page_rate_limit",
            new=AsyncMock(return_value=True),
        ):
            response = await get_payment_page(
                token=token_t1.token, request=request, db=page_db,
            )

        # JSONResponse with status 404, "Invalid payment link" detail.
        from fastapi.responses import JSONResponse as _JSON
        assert isinstance(response, _JSON)
        assert response.status_code == 404
        # Body is bytes — decode and verify the detail.
        import json as _json
        body = _json.loads(bytes(response.body).decode("utf-8"))
        assert body["detail"] == "Invalid payment link"

    @pytest.mark.asyncio
    async def test_second_partial_creates_new_pi_after_first_settled(self):
        """Sequence:
        1. Invoice $300 → first partial QR for $100 → webhook records
           payment → assert PI fields cleared, T1 deactivated.
        2. Second partial QR for $100 → assert NEW PI created (not reuse),
           NEW token T2 generated and active, T1 still in DB but
           is_active=False.

        **Validates: Task 18.5 — regression-fix verification of the
        reuse-branch interaction with stale PI fields.**
        """
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            balance_due=Decimal("300.00"),
            amount_paid=Decimal("0.00"),
            stripe_payment_intent_id="pi_first_partial",
            payment_page_url="https://test.local/pay/first",
            invoice_data_json={"stripe_client_secret": "pi_first_partial_secret"},
        )
        token_t1 = _make_token(
            invoice_id=invoice.id,
            org_id=org_id,
            last_pi_amount_cents=10000,
            amount_override=Decimal("100.00"),
        )
        org = _make_org(org_id=org_id)

        # === Step 1: webhook records the first partial. ===
        class _DeactivatingWebhookDb(_WebhookFakeDb):
            def __init__(self, *, invoice, token_to_track):
                super().__init__(invoice=invoice)
                self._token = token_to_track

            async def _execute(self, stmt, *args, **kwargs):
                from sqlalchemy import Update
                if isinstance(stmt, Update):
                    try:
                        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                    except Exception:
                        compiled = str(stmt)
                    if "payment_tokens" in compiled.lower() and "is_active" in compiled.lower():
                        if self._token.is_active is True:
                            self._token.is_active = False
                return await super()._execute(stmt, *args, **kwargs)

        wh_db = _DeactivatingWebhookDb(invoice=invoice, token_to_track=token_t1)

        event_data = _make_pi_succeeded_event(
            invoice_id=invoice.id,
            pi_id="pi_first_partial",
            amount_received_cents=10000,
            original_amount="100.00",
            is_partial_payment="true",
        )

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ):
            wh_result = await handle_stripe_webhook(
                wh_db,
                event_type="payment_intent.succeeded",
                event_data=event_data,
            )

        assert wh_result["status"] == "processed"
        # PI fields cleared.
        assert invoice.stripe_payment_intent_id is None
        assert invoice.payment_page_url is None
        assert invoice.invoice_data_json.get("stripe_client_secret") is None
        # T1 deactivated.
        assert token_t1.is_active is False
        # Balance moved.
        assert invoice.balance_due == Decimal("200.00")
        assert invoice.status == "partially_paid"

        # === Step 2: second partial QR. ===
        # The reuse-branch guard short-circuits `if invoice.payment_page_url
        # and invoice.stripe_payment_intent_id` — both are None now, so the
        # service never even queries for the existing token. Pass an empty
        # select queue accordingly.
        sess_db = _FakeDb(select_results=[invoice, org])

        captured_overrides: list[Decimal | None] = []
        captured_token_strings: list[str] = []

        async def _capture_gen(db_, *, org_id, invoice_id, base_url=None, amount_override=None):
            captured_overrides.append(amount_override)
            tok = f"tok_T2_{uuid.uuid4().hex}"
            captured_token_strings.append(tok)
            return tok, f"https://test.local/pay/{tok}"

        create_pi_mock = AsyncMock(
            return_value={
                "payment_intent_id": "pi_second_partial_new",
                "client_secret": "pi_second_partial_new_secret",
            }
        )

        with patch(
            "app.modules.payments.service.create_payment_intent", create_pi_mock,
        ), patch(
            "app.modules.payments.service._cancel_payment_intent",
            new=AsyncMock(return_value={"status": "canceled"}),
        ) as cancel_mock, patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock,
        ), patch(
            "app.modules.payments.service.generate_payment_token",
            new=AsyncMock(side_effect=_capture_gen),
        ), patch(
            "app.integrations.stripe_billing.get_application_fee_percent",
            new=AsyncMock(return_value=Decimal("0")),
        ):
            sess_result = await create_qr_session_for_existing_invoice(
                sess_db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                partial_amount=Decimal("100.00"),
            )

        # A NEW PI was created (the reuse branch was correctly bypassed
        # because the webhook cleared invoice.stripe_payment_intent_id).
        assert create_pi_mock.await_count == 1
        # No cancel was attempted (no stale PI to cancel).
        assert cancel_mock.await_count == 0
        # Brand-new token (T2).
        assert len(captured_token_strings) == 1
        t2_token = captured_token_strings[0]
        assert t2_token != token_t1.token
        # T2 carries the partial override.
        assert captured_overrides == [Decimal("100.00")]
        # Session_id reflects the new PI.
        assert sess_result["session_id"] == "pi_second_partial_new"
        # T1 remains in the DB but inactive (we didn't delete it).
        assert token_t1.is_active is False

    @pytest.mark.asyncio
    async def test_three_partials_settle_correctly_with_token_lifecycle(self):
        """End-to-end multi-partial verification: invoice $200, three
        partials $50 + $50 + $100. After each settles:
        - balance_due reduces by exactly the partial
        - status: partially_paid → partially_paid → paid
        - the in-flight token gets deactivated
        - invoice PI fields cleared after each
        - GET /public/pay/{T1} returns 404 immediately after partial #1
        - GET /public/pay/{T2} returns is_payable=true while #2 is in flight

        Three Payment rows total, three distinct stripe_payment_intent_ids,
        cumulative amount_paid = $200 = invoice.total.

        **Validates: Task 18.6 — full lifecycle**
        """
        from app.modules.payments.public_router import get_payment_page

        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            total=Decimal("200.00"),
            balance_due=Decimal("200.00"),
            amount_paid=Decimal("0.00"),
        )

        # Build three tokens — one per partial.
        tokens = [
            _make_token(
                invoice_id=invoice.id, org_id=org_id,
                amount_override=Decimal("50.00"),
                token_string=f"tok_T1_{uuid.uuid4().hex}",
            ),
            _make_token(
                invoice_id=invoice.id, org_id=org_id,
                amount_override=Decimal("50.00"),
                token_string=f"tok_T2_{uuid.uuid4().hex}",
            ),
            _make_token(
                invoice_id=invoice.id, org_id=org_id,
                amount_override=Decimal("100.00"),
                token_string=f"tok_T3_{uuid.uuid4().hex}",
            ),
        ]
        partial_amounts = [Decimal("50.00"), Decimal("50.00"), Decimal("100.00")]
        partial_pi_ids = ["pi_partial_one", "pi_partial_two", "pi_partial_three"]

        class _MultiTokenDeactivatingDb(_WebhookFakeDb):
            """Deactivates the *currently active* token (assumed to be the
            one matching the in-flight PI on the invoice) when the webhook
            issues the PaymentToken-deactivation UPDATE.
            """

            def __init__(self, *, invoice, all_tokens):
                super().__init__(invoice=invoice)
                self._all_tokens = all_tokens

            async def _execute(self, stmt, *args, **kwargs):
                from sqlalchemy import Update
                if isinstance(stmt, Update):
                    try:
                        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
                    except Exception:
                        compiled = str(stmt)
                    if "payment_tokens" in compiled.lower() and "is_active" in compiled.lower():
                        for tok in self._all_tokens:
                            if (
                                tok.invoice_id == self.invoice.id
                                and tok.is_active is True
                            ):
                                tok.is_active = False
                return await super()._execute(stmt, *args, **kwargs)

        wh_db = _MultiTokenDeactivatingDb(invoice=invoice, all_tokens=tokens)
        all_results: list[dict] = []

        for i, (tok, partial, pi_id) in enumerate(
            zip(tokens, partial_amounts, partial_pi_ids), start=1
        ):
            # Set the in-flight PI on the invoice for this round (mirrors
            # what `create_qr_session_for_existing_invoice` would have done).
            invoice.stripe_payment_intent_id = pi_id
            invoice.payment_page_url = f"https://test.local/pay/{pi_id}"
            invoice.invoice_data_json = {"stripe_client_secret": f"{pi_id}_secret"}
            # Make sure the token is marked active again at the start of
            # its round (as if just-issued).
            tok.is_active = True

            # === Mid-flight assertion for partial #2: GET /public/pay/{T2}
            # returns is_payable=true with valid client_secret ===
            if i == 2:
                # Snapshot invoice state during partial #2 in flight.
                invoice.line_items = []
                invoice.subtotal = Decimal("173.91")
                invoice.gst_amount = Decimal("26.09")
                invoice.invoice_number = "INV-MULTI"
                invoice.issue_date = datetime.now(timezone.utc).date()
                invoice.due_date = datetime.now(timezone.utc).date()

                page_org = MagicMock()
                page_org.id = org_id
                page_org.name = "Test Org"
                page_org.settings = {"surcharge_enabled": False}
                page_org.stripe_connect_account_id = "acct_test"

                page_db = _FakeDb(select_results=[invoice, page_org])

                request = MagicMock()
                request.client.host = "127.0.0.1"

                with patch(
                    "app.modules.payments.public_router.validate_payment_token",
                    new=AsyncMock(return_value=tok),
                ), patch(
                    "app.modules.payments.public_router._check_payment_page_rate_limit",
                    new=AsyncMock(return_value=True),
                ), patch(
                    "app.integrations.stripe_billing.get_stripe_publishable_key",
                    new=AsyncMock(return_value="pk_test_xxx"),
                ):
                    page_response = await get_payment_page(
                        token=tok.token, request=request, db=page_db,
                    )

                assert page_response.is_payable is True
                assert page_response.client_secret == f"{pi_id}_secret"
                assert page_response.is_partial_payment is True
                assert page_response.balance_due == Decimal("50.00")

            event_data = _make_pi_succeeded_event(
                invoice_id=invoice.id,
                pi_id=pi_id,
                amount_received_cents=int(partial * 100),
                original_amount=str(partial),
                is_partial_payment="true",
            )

            with patch(
                "app.modules.payments.service.write_audit_log",
                new_callable=AsyncMock,
            ):
                result = await handle_stripe_webhook(
                    wh_db,
                    event_type="payment_intent.succeeded",
                    event_data=event_data,
                )
            all_results.append(result)

            # After each settle: PI fields cleared, the token for this
            # round is deactivated.
            assert invoice.stripe_payment_intent_id is None
            assert invoice.payment_page_url is None
            assert invoice.invoice_data_json.get("stripe_client_secret") is None
            assert tok.is_active is False

            # === Immediately after partial #1 settles: GET /public/pay/{T1}
            # returns 404 ===
            if i == 1:
                t1 = tok
                page_db = _FakeDb(select_results=[])
                request = MagicMock()
                request.client.host = "127.0.0.1"
                with patch(
                    "app.modules.payments.public_router.validate_payment_token",
                    new=AsyncMock(return_value=None),  # inactive → None
                ), patch(
                    "app.modules.payments.public_router._check_payment_page_rate_limit",
                    new=AsyncMock(return_value=True),
                ):
                    page_response = await get_payment_page(
                        token=t1.token, request=request, db=page_db,
                    )
                from fastapi.responses import JSONResponse as _JSON
                assert isinstance(page_response, _JSON)
                assert page_response.status_code == 404
                import json as _json
                body = _json.loads(bytes(page_response.body).decode("utf-8"))
                assert body["detail"] == "Invalid payment link"

        # === Final post-condition assertions ===
        # Three Payment rows total.
        payments_only = [p for p in wh_db.payments_added if isinstance(p, Payment)]
        assert len(payments_only) == 3
        # Three DISTINCT stripe_payment_intent_ids.
        pi_ids = {p.stripe_payment_intent_id for p in payments_only}
        assert pi_ids == set(partial_pi_ids)
        assert len(pi_ids) == 3
        # Cumulative balance reduction.
        assert invoice.balance_due == Decimal("0.00")
        assert invoice.amount_paid == Decimal("200.00")
        assert invoice.amount_paid == invoice.total
        assert invoice.status == "paid"
        # Status progression.
        assert all_results[0]["invoice_status"] == "partially_paid"
        assert all_results[1]["invoice_status"] == "partially_paid"
        assert all_results[2]["invoice_status"] == "paid"
        # All three tokens deactivated.
        assert all(t.is_active is False for t in tokens)
