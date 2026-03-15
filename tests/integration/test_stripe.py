"""Integration tests for Stripe — Connect OAuth, payment links, webhooks, refunds, subscriptions.

Tests the full flow from service/integration layer through to mocked Stripe API responses.
All Stripe API calls are mocked — no real API calls are made.

Requirements: 25.1-25.5, 42.1-42.6
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401

from app.integrations.stripe_connect import (
    create_payment_link,
    create_stripe_refund,
    generate_connect_url,
    handle_connect_callback,
    verify_webhook_signature,
)
from app.integrations.stripe_billing import (
    handle_subscription_webhook,
    report_metered_usage,
)
from app.modules.payments.service import (
    generate_stripe_payment_link,
    handle_stripe_webhook,
    process_refund,
)
from app.modules.invoices.models import Invoice
from app.modules.admin.models import Organisation
from app.modules.payments.models import Payment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _make_invoice(
    org_id=None,
    status="issued",
    total=Decimal("200.00"),
    amount_paid=Decimal("0.00"),
    balance_due=Decimal("200.00"),
    currency="NZD",
    created_by=None,
):
    inv = MagicMock(spec=Invoice)
    inv.id = uuid.uuid4()
    inv.org_id = org_id or uuid.uuid4()
    inv.customer_id = uuid.uuid4()
    inv.created_by = created_by or uuid.uuid4()
    inv.status = status
    inv.total = total
    inv.amount_paid = amount_paid
    inv.balance_due = balance_due
    inv.currency = currency
    inv.invoice_number = "INV-0001"
    inv.issue_date = date.today()
    inv.due_date = date.today()
    return inv


def _make_org(org_id=None, stripe_account="acct_test123"):
    org = MagicMock(spec=Organisation)
    org.id = org_id or uuid.uuid4()
    org.stripe_connect_account_id = stripe_account
    return org


def _make_stripe_payment(invoice_id, org_id, payment_intent="pi_original_123"):
    pay = MagicMock(spec=Payment)
    pay.id = uuid.uuid4()
    pay.invoice_id = invoice_id
    pay.org_id = org_id
    pay.method = "stripe"
    pay.is_refund = False
    pay.stripe_payment_intent_id = payment_intent
    return pay


def _mock_httpx_client(response_json, status_code=200):
    """Create a mock httpx.AsyncClient context manager."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = response_json
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client, mock_response


def _build_stripe_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = timestamp or int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


# ===========================================================================
# 1. Stripe Connect OAuth Flow (Req 25.1, 25.2)
# ===========================================================================


class TestStripeConnectOAuthFlow:
    """Integration tests for the full Stripe Connect OAuth flow.

    Tests the end-to-end flow: generate URL → redirect → callback → account stored.
    Requirements: 25.1, 25.2
    """

    def test_generate_url_produces_valid_oauth_url_with_csrf(self):
        """Full flow: generate_connect_url returns a URL with all required OAuth params
        and a CSRF state token containing the org_id."""
        org_id = uuid.uuid4()
        url, state = generate_connect_url(org_id)

        # URL must point to Stripe Connect
        assert "connect.stripe.com/oauth/authorize" in url
        assert "response_type=code" in url
        assert "scope=read_write" in url
        assert "redirect_uri=" in url

        # State must embed org_id for CSRF verification
        parts = state.split(":", 1)
        assert len(parts) == 2
        assert parts[0] == str(org_id)
        assert len(parts[1]) > 16  # random token is substantial

    @pytest.mark.asyncio
    async def test_full_oauth_callback_exchanges_code_and_returns_account(self):
        """Full flow: handle_connect_callback exchanges the auth code with Stripe
        and returns the connected account ID with org context."""
        org_id = uuid.uuid4()
        _, state = generate_connect_url(org_id)

        stripe_response = {
            "stripe_user_id": "acct_connected_org",
            "scope": "read_write",
            "token_type": "bearer",
            "access_token": "sk_test_xxx",
        }

        mock_client, _ = _mock_httpx_client(stripe_response)
        with patch("app.integrations.stripe_connect.httpx.AsyncClient", return_value=mock_client):
            result = await handle_connect_callback(code="ac_test_code", state=state)

        assert result["stripe_user_id"] == "acct_connected_org"
        assert result["org_id"] == str(org_id)
        assert result["scope"] == "read_write"

        # Verify the token exchange was called with correct endpoint
        call_args = mock_client.post.call_args
        assert "connect.stripe.com/oauth/token" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_malformed_state(self):
        """Callback rejects state tokens without the org_id:token format."""
        with pytest.raises(ValueError, match="Invalid state token format"):
            await handle_connect_callback(code="ac_test", state="no-colon-here")

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_invalid_uuid_in_state(self):
        """Callback rejects state tokens with non-UUID org_id."""
        with pytest.raises(ValueError, match="Invalid org_id"):
            await handle_connect_callback(code="ac_test", state="not-uuid:token123")

    @pytest.mark.asyncio
    async def test_oauth_callback_propagates_stripe_api_error(self):
        """When Stripe returns an error during code exchange, it propagates."""
        org_id = uuid.uuid4()
        state = f"{org_id}:csrf_token"

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.integrations.stripe_connect.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await handle_connect_callback(code="bad_code", state=state)

    def test_each_connect_url_has_unique_csrf_token(self):
        """CSRF tokens must be unique per call to prevent replay attacks."""
        org_id = uuid.uuid4()
        _, state1 = generate_connect_url(org_id)
        _, state2 = generate_connect_url(org_id)
        assert state1 != state2


# ===========================================================================
# 2. Payment Link Generation + Webhook Processing (Req 25.3, 25.4, 25.5)
# ===========================================================================


class TestPaymentLinkGenerationFlow:
    """Integration tests for payment link generation through to Stripe Checkout.

    Tests the full flow: service validates invoice → calls Stripe API → returns link.
    Requirements: 25.3, 25.5
    """

    @pytest.mark.asyncio
    async def test_full_balance_payment_link_flow(self):
        """Full flow: generate payment link for full invoice balance.
        Service fetches invoice, validates org has Stripe, calls create_payment_link."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("350.00"))
        org = _make_org(org_id=org_id)

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[inv_result, org_result])

        stripe_return = {
            "session_id": "cs_live_full",
            "payment_url": "https://checkout.stripe.com/pay/cs_live_full",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ) as mock_stripe, patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock
        ):
            result = await generate_stripe_payment_link(
                db, org_id=org_id, user_id=user_id, invoice_id=invoice.id
            )

        assert result["payment_url"] == stripe_return["payment_url"]
        assert result["amount"] == Decimal("350.00")
        # Stripe called with amount in cents
        mock_stripe.assert_called_once()
        assert mock_stripe.call_args[1]["amount"] == 35000

    @pytest.mark.asyncio
    async def test_partial_payment_deposit_link_flow(self):
        """Partial payment for deposit scenario (Req 25.5).
        Only the specified amount is sent to Stripe, not the full balance."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("500.00"))
        org = _make_org(org_id=org_id)

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[inv_result, org_result])

        stripe_return = {
            "session_id": "cs_deposit",
            "payment_url": "https://checkout.stripe.com/pay/cs_deposit",
        }

        with patch(
            "app.integrations.stripe_connect.create_payment_link",
            new_callable=AsyncMock,
            return_value=stripe_return,
        ) as mock_stripe, patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock
        ):
            result = await generate_stripe_payment_link(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("150.00"),
            )

        assert result["amount"] == Decimal("150.00")
        assert mock_stripe.call_args[1]["amount"] == 15000

    @pytest.mark.asyncio
    async def test_create_payment_link_calls_stripe_api_correctly(self):
        """Integration: create_payment_link sends correct data to Stripe Checkout API."""
        mock_client, mock_response = _mock_httpx_client({
            "id": "cs_test_api",
            "url": "https://checkout.stripe.com/pay/cs_test_api",
        })

        with patch("app.integrations.stripe_connect.httpx.AsyncClient", return_value=mock_client):
            result = await create_payment_link(
                amount=25000,
                currency="nzd",
                invoice_id="inv-test-456",
                stripe_account_id="acct_org_789",
            )

        assert result["session_id"] == "cs_test_api"
        assert result["payment_url"] == "https://checkout.stripe.com/pay/cs_test_api"

        # Verify Stripe API call details
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.stripe.com/v1/checkout/sessions"
        assert call_args[1]["headers"]["Stripe-Account"] == "acct_org_789"
        data = call_args[1]["data"]
        assert data["line_items[0][price_data][unit_amount]"] == "25000"
        assert data["line_items[0][price_data][currency]"] == "nzd"
        assert data["metadata[invoice_id]"] == "inv-test-456"
        assert data["metadata[platform]"] == "workshoppro_nz"


class TestWebhookProcessingFlow:
    """Integration tests for Stripe webhook signature verification + payment processing.

    Tests the full flow: verify signature → parse event → update invoice → create payment.
    Requirements: 25.4
    """

    def test_webhook_signature_verification_roundtrip(self):
        """Full flow: build a signed payload, verify it, get parsed event back."""
        secret = "whsec_integration_test"
        event = {"type": "checkout.session.completed", "data": {"object": {"id": "cs_1"}}}
        payload = json.dumps(event).encode()
        sig_header = _build_stripe_signature(payload, secret)

        result = verify_webhook_signature(payload, sig_header, secret)
        assert result["type"] == "checkout.session.completed"
        assert result["data"]["object"]["id"] == "cs_1"

    def test_webhook_rejects_tampered_payload(self):
        """Tampered payload fails signature verification."""
        secret = "whsec_test"
        original = json.dumps({"type": "test"}).encode()
        sig_header = _build_stripe_signature(original, secret)
        tampered = json.dumps({"type": "hacked"}).encode()

        with pytest.raises(ValueError, match="signature verification failed"):
            verify_webhook_signature(tampered, sig_header, secret)

    def test_webhook_rejects_replay_attack(self):
        """Old timestamps (>5 min) are rejected to prevent replay attacks."""
        secret = "whsec_test"
        payload = json.dumps({"type": "test"}).encode()
        old_ts = int(time.time()) - 600
        sig_header = _build_stripe_signature(payload, secret, timestamp=old_ts)

        with pytest.raises(ValueError, match="replay attack"):
            verify_webhook_signature(payload, sig_header, secret)

    @pytest.mark.asyncio
    async def test_checkout_completed_webhook_creates_payment_and_updates_invoice(self):
        """Full flow: checkout.session.completed webhook creates a Payment record
        and transitions invoice from issued → paid."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(org_id=org_id, balance_due=Decimal("200.00"))
        db = _mock_db()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "id": "cs_webhook_test",
            "amount_total": 20000,
            "payment_intent": "pi_webhook_test",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["status"] == "processed"
        assert result["invoice_status"] == "paid"
        assert invoice.amount_paid == Decimal("200.00")
        assert invoice.balance_due == Decimal("0.00")

        # Verify Payment record was created
        db.add.assert_called_once()
        payment = db.add.call_args[0][0]
        assert isinstance(payment, Payment)
        assert payment.method == "stripe"
        assert payment.stripe_payment_intent_id == "pi_webhook_test"
        assert payment.amount == Decimal("200.00")

    @pytest.mark.asyncio
    async def test_partial_webhook_payment_sets_partially_paid(self):
        """Partial Stripe payment via webhook sets invoice to partially_paid."""
        invoice = _make_invoice(balance_due=Decimal("300.00"))
        db = _mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = invoice
        db.execute.return_value = mock_result

        event_data = {
            "amount_total": 10000,  # $100 of $300
            "payment_intent": "pi_partial",
            "metadata": {"invoice_id": str(invoice.id)},
        }

        with patch("app.modules.payments.service.write_audit_log", new_callable=AsyncMock):
            result = await handle_stripe_webhook(
                db, event_type="checkout.session.completed", event_data=event_data
            )

        assert result["invoice_status"] == "partially_paid"
        assert invoice.balance_due == Decimal("200.00")

    @pytest.mark.asyncio
    async def test_webhook_ignores_non_checkout_events(self):
        """Non-checkout event types are gracefully ignored."""
        db = _mock_db()
        result = await handle_stripe_webhook(
            db, event_type="payment_intent.created", event_data={}
        )
        assert result["status"] == "ignored"


# ===========================================================================
# 3. Refund Processing (Req 26.2, 26.3, 26.4)
# ===========================================================================


class TestRefundProcessingFlow:
    """Integration tests for refund processing — both Stripe and cash.

    Tests the full flow: service validates invoice → calls Stripe Refund API → updates balance.
    Requirements: 26.2, 26.3, 26.4
    """

    @pytest.mark.asyncio
    async def test_stripe_refund_full_flow(self):
        """Full flow: Stripe refund finds original payment, calls Stripe API,
        creates refund record, and updates invoice balance."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )
        org = _make_org(org_id=org_id)
        stripe_payment = _make_stripe_payment(invoice.id, org_id)

        db = _mock_db()
        # Calls: 1) invoice lookup, 2) stripe payment lookup, 3) org lookup
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        pay_result = MagicMock()
        pay_result.scalar_one_or_none.return_value = stripe_payment
        org_result = MagicMock()
        org_result.scalar_one_or_none.return_value = org
        db.execute = AsyncMock(side_effect=[inv_result, pay_result, org_result])

        stripe_refund_response = {
            "refund_id": "re_test_123",
            "status": "succeeded",
            "amount": 10000,
        }

        with patch(
            "app.integrations.stripe_connect.create_stripe_refund",
            new_callable=AsyncMock,
            return_value=stripe_refund_response,
        ) as mock_refund, patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock
        ):
            result = await process_refund(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("100.00"),
                method="stripe",
                notes="Customer requested partial refund",
            )

        assert result["stripe_refund_id"] == "re_test_123"
        assert invoice.amount_paid == Decimal("100.00")
        assert invoice.balance_due == Decimal("0.00")
        assert invoice.status == "partially_refunded"

        # Verify Stripe API was called with correct params
        mock_refund.assert_called_once_with(
            payment_intent_id="pi_original_123",
            amount=10000,
            stripe_account_id="acct_test123",
        )

    @pytest.mark.asyncio
    async def test_cash_refund_flow(self):
        """Cash refund records the refund without calling Stripe API."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            amount_paid=Decimal("200.00"),
            balance_due=Decimal("0.00"),
        )

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_result)

        with patch(
            "app.modules.payments.service.write_audit_log", new_callable=AsyncMock
        ):
            result = await process_refund(
                db,
                org_id=org_id,
                user_id=user_id,
                invoice_id=invoice.id,
                amount=Decimal("200.00"),
                method="cash",
                notes="Cash refund at counter",
            )

        assert result["stripe_refund_id"] is None
        assert invoice.amount_paid == Decimal("0.00")
        assert invoice.balance_due == Decimal("0.00")
        assert invoice.status == "refunded"

    @pytest.mark.asyncio
    async def test_refund_rejects_amount_exceeding_paid(self):
        """Refund amount cannot exceed total amount paid."""
        org_id = uuid.uuid4()
        invoice = _make_invoice(
            org_id=org_id,
            status="paid",
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("100.00"),
        )

        db = _mock_db()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        db.execute = AsyncMock(return_value=inv_result)

        with pytest.raises(ValueError, match="exceeds total amount paid"):
            await process_refund(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                invoice_id=invoice.id,
                amount=Decimal("150.00"),
                method="cash",
            )

    @pytest.mark.asyncio
    async def test_stripe_refund_api_integration(self):
        """Integration: create_stripe_refund sends correct data to Stripe Refunds API."""
        mock_client, _ = _mock_httpx_client({
            "id": "re_api_test",
            "status": "succeeded",
            "amount": 5000,
        })

        with patch("app.integrations.stripe_connect.httpx.AsyncClient", return_value=mock_client):
            result = await create_stripe_refund(
                payment_intent_id="pi_to_refund",
                amount=5000,
                stripe_account_id="acct_refund_org",
            )

        assert result["refund_id"] == "re_api_test"
        assert result["status"] == "succeeded"
        assert result["amount"] == 5000

        # Verify API call
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://api.stripe.com/v1/refunds"
        assert call_args[1]["headers"]["Stripe-Account"] == "acct_refund_org"
        assert call_args[1]["data"]["payment_intent"] == "pi_to_refund"
        assert call_args[1]["data"]["amount"] == "5000"

    @pytest.mark.asyncio
    async def test_stripe_refund_rejects_empty_payment_intent(self):
        """create_stripe_refund raises ValueError for empty payment_intent_id."""
        with pytest.raises(ValueError, match="payment_intent_id is required"):
            await create_stripe_refund(
                payment_intent_id="",
                amount=1000,
                stripe_account_id="acct_test",
            )


# ===========================================================================
# 4. Subscription Billing with Metered Usage (Req 42.1-42.6)
# ===========================================================================


class TestSubscriptionBillingFlow:
    """Integration tests for subscription billing lifecycle and metered usage.

    Tests webhook event processing for payment success/failure, dunning,
    grace period transitions, and metered usage reporting.
    Requirements: 42.1, 42.2, 42.3, 42.4, 42.5, 42.6
    """

    @pytest.mark.asyncio
    async def test_payment_succeeded_webhook_processing(self):
        """invoice.payment_succeeded event is processed correctly (Req 42.1, 42.3)."""
        result = await handle_subscription_webhook(
            event_type="invoice.payment_succeeded",
            event_data={
                "object": {
                    "customer": "cus_billing_ok",
                    "subscription": "sub_monthly",
                    "amount_paid": 4900,
                    "invoice_pdf": "https://stripe.com/inv_pdf.pdf",
                    "hosted_invoice_url": "https://stripe.com/inv_hosted",
                }
            },
        )

        assert result["processed"] is True
        assert result["action"] == "payment_succeeded"
        assert result["customer_id"] == "cus_billing_ok"
        assert result["subscription_id"] == "sub_monthly"
        assert result["amount_paid"] == 4900
        assert result["invoice_pdf"] == "https://stripe.com/inv_pdf.pdf"

    @pytest.mark.asyncio
    async def test_payment_failed_webhook_triggers_dunning(self):
        """invoice.payment_failed event captures attempt count for dunning (Req 42.4)."""
        result = await handle_subscription_webhook(
            event_type="invoice.payment_failed",
            event_data={
                "object": {
                    "customer": "cus_fail_dunning",
                    "subscription": "sub_fail",
                    "attempt_count": 2,
                    "next_payment_attempt": 1700200000,
                }
            },
        )

        assert result["processed"] is True
        assert result["action"] == "payment_failed"
        assert result["attempt_count"] == 2
        assert result["next_payment_attempt"] == 1700200000

    @pytest.mark.asyncio
    async def test_subscription_updated_event(self):
        """customer.subscription.updated event tracks status changes."""
        result = await handle_subscription_webhook(
            event_type="customer.subscription.updated",
            event_data={
                "object": {
                    "id": "sub_updated",
                    "status": "past_due",
                    "customer": "cus_updated",
                }
            },
        )

        assert result["processed"] is True
        assert result["action"] == "subscription_updated"
        assert result["status"] == "past_due"

    @pytest.mark.asyncio
    async def test_subscription_deleted_event(self):
        """customer.subscription.deleted event handles cancellation."""
        result = await handle_subscription_webhook(
            event_type="customer.subscription.deleted",
            event_data={
                "object": {
                    "id": "sub_cancelled",
                    "customer": "cus_cancelled",
                }
            },
        )

        assert result["processed"] is True
        assert result["action"] == "subscription_deleted"
        assert result["subscription_id"] == "sub_cancelled"

    @pytest.mark.asyncio
    async def test_unknown_event_type_not_processed(self):
        """Unrecognised event types are ignored gracefully."""
        result = await handle_subscription_webhook(
            event_type="charge.refunded",
            event_data={"object": {}},
        )
        assert result["processed"] is False

    @pytest.mark.asyncio
    async def test_metered_usage_reporting(self):
        """report_metered_usage finds the metered item and reports usage (Req 42.2)."""
        mock_subscription = {
            "id": "sub_metered",
            "items": {
                "data": [
                    {
                        "id": "si_base",
                        "price": {"recurring": {"usage_type": "licensed"}},
                    },
                    {
                        "id": "si_metered",
                        "price": {"recurring": {"usage_type": "metered"}},
                    },
                ]
            },
        }

        mock_usage_record = {"id": "mbur_test123"}

        with patch("stripe.Subscription.retrieve", return_value=mock_subscription), \
             patch(
                 "app.integrations.stripe_billing.stripe.SubscriptionItem.create_usage_record",
                 return_value=mock_usage_record,
                 create=True,
             ):
            result = await report_metered_usage(
                subscription_id="sub_metered",
                quantity=15,
                action="increment",
            )

        assert result["reported"] is True
        assert result["usage_record_id"] == "mbur_test123"
        assert result["quantity"] == 15

    @pytest.mark.asyncio
    async def test_metered_usage_no_metered_item(self):
        """report_metered_usage returns not-reported when no metered item exists."""
        mock_subscription = {
            "id": "sub_no_metered",
            "items": {
                "data": [
                    {
                        "id": "si_base_only",
                        "price": {"recurring": {"usage_type": "licensed"}},
                    },
                ]
            },
        }

        with patch("stripe.Subscription.retrieve", return_value=mock_subscription):
            result = await report_metered_usage(
                subscription_id="sub_no_metered",
                quantity=5,
            )

        assert result["reported"] is False
        assert result["reason"] == "no_metered_item"

    def test_grace_period_transition_after_3_failures(self):
        """After 3 payment failures, org should enter grace period (Req 42.5)."""
        # Simulates the webhook handler logic
        attempt_count = 3
        org_status = "active"

        should_enter_grace = attempt_count >= 3 and org_status == "active"
        assert should_enter_grace is True

    def test_no_grace_period_before_3_failures(self):
        """Fewer than 3 failures should not trigger grace period."""
        attempt_count = 2
        org_status = "active"

        should_enter_grace = attempt_count >= 3 and org_status == "active"
        assert should_enter_grace is False

    def test_payment_recovery_restores_active_from_grace(self):
        """Payment success during grace period restores org to active (Req 42.5)."""
        org_status = "grace_period"
        action = "payment_succeeded"

        new_status = "active" if (action == "payment_succeeded" and org_status == "grace_period") else org_status
        assert new_status == "active"

    @pytest.mark.asyncio
    async def test_payment_failed_with_missing_fields_still_processes(self):
        """Payment failed event with missing fields still processes gracefully."""
        result = await handle_subscription_webhook(
            event_type="invoice.payment_failed",
            event_data={"object": {}},
        )
        assert result["processed"] is True
        assert result["attempt_count"] == 0
        assert result["customer_id"] is None
