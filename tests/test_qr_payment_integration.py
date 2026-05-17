"""Integration test for full QR payment flow (state machine simulation).

Tests the complete flow:
  create session → pending session stored → kiosk poll returns session →
  status poll returns complete → pending session cleared

This is a PURE LOGIC integration test — no real database or Stripe calls.
Uses Hypothesis to generate random inputs (org_ids, session_ids, amounts)
and verifies the state machine transitions are correct.

**Validates: Requirements 1.3, 3.1, 4.1, 7.1, 8.5**
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# State machine types — models the QR payment flow
# ---------------------------------------------------------------------------


class SessionStatus(str, Enum):
    """Stripe Checkout Session status values."""

    OPEN = "open"
    COMPLETE = "complete"
    EXPIRED = "expired"


@dataclass
class PendingQrSession:
    """Represents a row in the pending_qr_sessions table."""

    id: uuid.UUID
    org_id: uuid.UUID
    session_id: str
    checkout_url: str
    amount: Decimal
    invoice_number: str
    invoice_id: uuid.UUID
    expires_at: str  # ISO string


@dataclass
class QrPaymentState:
    """The full state of the QR payment system for testing.

    Models the pending_qr_sessions table as a dict keyed by org_id,
    and tracks Stripe session statuses.
    """

    # pending_qr_sessions table: org_id -> PendingQrSession
    pending_sessions: dict[uuid.UUID, PendingQrSession] = field(default_factory=dict)
    # Stripe session statuses: session_id -> SessionStatus
    stripe_statuses: dict[str, SessionStatus] = field(default_factory=dict)
    # Recorded payments: set of session_ids that have been paid
    recorded_payments: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Pure functions simulating each step of the QR payment flow
# ---------------------------------------------------------------------------


def create_qr_session(
    state: QrPaymentState,
    *,
    org_id: uuid.UUID,
    session_id: str,
    checkout_url: str,
    amount: Decimal,
    invoice_number: str,
    invoice_id: uuid.UUID,
) -> QrPaymentState:
    """Simulate creating a QR payment session.

    Replicates the backend logic:
    1. Delete any existing pending session for this org (upsert behavior)
    2. Insert new pending session
    3. Set Stripe session status to "open"

    **Validates: Requirements 1.3, 3.1**
    """
    # Remove existing session for this org (upsert — one active session per org)
    new_pending = dict(state.pending_sessions)
    new_pending[org_id] = PendingQrSession(
        id=uuid.uuid4(),
        org_id=org_id,
        session_id=session_id,
        checkout_url=checkout_url,
        amount=amount,
        invoice_number=invoice_number,
        invoice_id=invoice_id,
        expires_at="2026-05-08T14:30:00Z",
    )

    # Register session status as "open" in Stripe
    new_statuses = dict(state.stripe_statuses)
    new_statuses[session_id] = SessionStatus.OPEN

    return QrPaymentState(
        pending_sessions=new_pending,
        stripe_statuses=new_statuses,
        recorded_payments=set(state.recorded_payments),
    )


def kiosk_poll_pending(
    state: QrPaymentState,
    *,
    org_id: uuid.UUID,
) -> Optional[PendingQrSession]:
    """Simulate kiosk polling GET /payments/qr-session/pending.

    Returns the pending session for the org, or None if no session exists.

    **Validates: Requirements 4.1**
    """
    return state.pending_sessions.get(org_id)


def poll_session_status(
    state: QrPaymentState,
    *,
    session_id: str,
) -> Optional[dict]:
    """Simulate polling GET /payments/qr-session/{session_id}/status.

    Returns the session status and payment_intent_id (if complete).

    **Validates: Requirements 7.1**
    """
    status = state.stripe_statuses.get(session_id)
    if status is None:
        return None

    result: dict = {"status": status.value, "payment_intent_id": None}
    if status == SessionStatus.COMPLETE:
        result["payment_intent_id"] = f"pi_{session_id[-16:]}"
    return result


def simulate_payment_complete(
    state: QrPaymentState,
    *,
    session_id: str,
) -> QrPaymentState:
    """Simulate Stripe marking the session as complete (customer paid).

    This happens on Stripe's side when the customer completes checkout.
    """
    new_statuses = dict(state.stripe_statuses)
    if session_id in new_statuses:
        new_statuses[session_id] = SessionStatus.COMPLETE

    return QrPaymentState(
        pending_sessions=dict(state.pending_sessions),
        stripe_statuses=new_statuses,
        recorded_payments=set(state.recorded_payments),
    )


def webhook_clear_pending_session(
    state: QrPaymentState,
    *,
    session_id: str,
) -> QrPaymentState:
    """Simulate webhook handler clearing the pending session after payment.

    Replicates the backend logic in handle_stripe_webhook():
    - Records the payment
    - Clears the pending_qr_session by session_id

    **Validates: Requirements 8.5**
    """
    # Find and remove the pending session matching this session_id
    new_pending = {}
    for org_id, session in state.pending_sessions.items():
        if session.session_id != session_id:
            new_pending[org_id] = session

    # Record the payment
    new_recorded = set(state.recorded_payments)
    new_recorded.add(session_id)

    return QrPaymentState(
        pending_sessions=new_pending,
        stripe_statuses=dict(state.stripe_statuses),
        recorded_payments=new_recorded,
    )


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

valid_org_ids = st.uuids()
valid_invoice_ids = st.uuids()

valid_session_ids = st.text(
    alphabet="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_",
    min_size=10,
    max_size=40,
).map(lambda s: f"cs_{s}")

valid_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

valid_invoice_numbers = st.from_regex(r"INV-20[2-3][0-9]-[0-9]{3,5}", fullmatch=True)

valid_checkout_urls = valid_session_ids.map(
    lambda sid: f"https://checkout.stripe.com/c/pay/{sid}"
)


# ---------------------------------------------------------------------------
# Integration test: Full QR payment flow
# **Validates: Requirements 1.3, 3.1, 4.1, 7.1, 8.5**
# ---------------------------------------------------------------------------


class TestFullQrPaymentFlow:
    """Integration test verifying the complete QR payment state machine:
    create session → pending stored → kiosk poll → status poll → complete → cleared.

    **Validates: Requirements 1.3, 3.1, 4.1, 7.1, 8.5**
    """

    @given(
        org_id=valid_org_ids,
        session_id=valid_session_ids,
        amount=valid_amounts,
        invoice_number=valid_invoice_numbers,
        invoice_id=valid_invoice_ids,
    )
    @settings(max_examples=150)
    def test_full_flow_create_to_complete(
        self,
        org_id: uuid.UUID,
        session_id: str,
        amount: Decimal,
        invoice_number: str,
        invoice_id: uuid.UUID,
    ):
        """Full flow: create → store → kiosk poll → status open → payment →
        status complete → webhook clears pending.

        **Validates: Requirements 1.3, 3.1, 4.1, 7.1, 8.5**
        """
        checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"

        # --- Step 1: Create QR session (Req 1.3, 3.1) ---
        state = QrPaymentState()
        state = create_qr_session(
            state,
            org_id=org_id,
            session_id=session_id,
            checkout_url=checkout_url,
            amount=amount,
            invoice_number=invoice_number,
            invoice_id=invoice_id,
        )

        # Verify: pending session is stored
        assert org_id in state.pending_sessions
        stored = state.pending_sessions[org_id]
        assert stored.session_id == session_id
        assert stored.amount == amount
        assert stored.invoice_number == invoice_number
        assert stored.invoice_id == invoice_id
        assert stored.checkout_url == checkout_url

        # --- Step 2: Kiosk polls and finds the session (Req 4.1) ---
        polled = kiosk_poll_pending(state, org_id=org_id)
        assert polled is not None
        assert polled.session_id == session_id
        assert polled.checkout_url == checkout_url
        assert polled.amount == amount

        # --- Step 3: Status poll returns "open" (Req 7.1) ---
        status_result = poll_session_status(state, session_id=session_id)
        assert status_result is not None
        assert status_result["status"] == "open"
        assert status_result["payment_intent_id"] is None

        # --- Step 4: Customer pays — Stripe marks session complete ---
        state = simulate_payment_complete(state, session_id=session_id)

        # --- Step 5: Status poll now returns "complete" (Req 7.1) ---
        status_result = poll_session_status(state, session_id=session_id)
        assert status_result is not None
        assert status_result["status"] == "complete"
        assert status_result["payment_intent_id"] is not None

        # --- Step 6: Webhook clears pending session (Req 8.5) ---
        state = webhook_clear_pending_session(state, session_id=session_id)

        # Verify: pending session is gone
        assert org_id not in state.pending_sessions
        # Verify: payment is recorded
        assert session_id in state.recorded_payments

        # --- Step 7: Kiosk poll now returns None ---
        polled_after = kiosk_poll_pending(state, org_id=org_id)
        assert polled_after is None

    @given(
        org_id=valid_org_ids,
        session_id=valid_session_ids,
        amount=valid_amounts,
        invoice_number=valid_invoice_numbers,
        invoice_id=valid_invoice_ids,
    )
    @settings(max_examples=150)
    def test_pending_session_cleared_after_webhook(
        self,
        org_id: uuid.UUID,
        session_id: str,
        amount: Decimal,
        invoice_number: str,
        invoice_id: uuid.UUID,
    ):
        """After webhook processes payment, the pending session must be cleared
        and subsequent kiosk polls return None.

        **Validates: Requirements 3.1, 8.5**
        """
        checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"

        # Create session
        state = QrPaymentState()
        state = create_qr_session(
            state,
            org_id=org_id,
            session_id=session_id,
            checkout_url=checkout_url,
            amount=amount,
            invoice_number=invoice_number,
            invoice_id=invoice_id,
        )

        # Verify session exists
        assert kiosk_poll_pending(state, org_id=org_id) is not None

        # Simulate payment and webhook
        state = simulate_payment_complete(state, session_id=session_id)
        state = webhook_clear_pending_session(state, session_id=session_id)

        # Verify session is cleared
        assert kiosk_poll_pending(state, org_id=org_id) is None
        assert org_id not in state.pending_sessions

    @given(
        org_id=valid_org_ids,
        session_id_1=valid_session_ids,
        session_id_2=valid_session_ids,
        amount_1=valid_amounts,
        amount_2=valid_amounts,
        invoice_number_1=valid_invoice_numbers,
        invoice_number_2=valid_invoice_numbers,
        invoice_id_1=valid_invoice_ids,
        invoice_id_2=valid_invoice_ids,
    )
    @settings(max_examples=150)
    def test_new_session_replaces_existing_for_same_org(
        self,
        org_id: uuid.UUID,
        session_id_1: str,
        session_id_2: str,
        amount_1: Decimal,
        amount_2: Decimal,
        invoice_number_1: str,
        invoice_number_2: str,
        invoice_id_1: uuid.UUID,
        invoice_id_2: uuid.UUID,
    ):
        """Creating a new session for the same org replaces the old one.
        Only one active session per org at a time.

        **Validates: Requirements 3.1**
        """
        assume(session_id_1 != session_id_2)

        state = QrPaymentState()

        # Create first session
        state = create_qr_session(
            state,
            org_id=org_id,
            session_id=session_id_1,
            checkout_url=f"https://checkout.stripe.com/c/pay/{session_id_1}",
            amount=amount_1,
            invoice_number=invoice_number_1,
            invoice_id=invoice_id_1,
        )

        # Verify first session is stored
        polled = kiosk_poll_pending(state, org_id=org_id)
        assert polled is not None
        assert polled.session_id == session_id_1

        # Create second session for same org (replaces first)
        state = create_qr_session(
            state,
            org_id=org_id,
            session_id=session_id_2,
            checkout_url=f"https://checkout.stripe.com/c/pay/{session_id_2}",
            amount=amount_2,
            invoice_number=invoice_number_2,
            invoice_id=invoice_id_2,
        )

        # Verify second session replaced first
        polled = kiosk_poll_pending(state, org_id=org_id)
        assert polled is not None
        assert polled.session_id == session_id_2
        assert polled.amount == amount_2
        assert polled.invoice_number == invoice_number_2

        # Only one pending session for this org
        org_sessions = [
            s for s in state.pending_sessions.values() if s.org_id == org_id
        ]
        assert len(org_sessions) == 1

    @given(
        org_id_1=valid_org_ids,
        org_id_2=valid_org_ids,
        session_id_1=valid_session_ids,
        session_id_2=valid_session_ids,
        amount=valid_amounts,
        invoice_number=valid_invoice_numbers,
        invoice_id_1=valid_invoice_ids,
        invoice_id_2=valid_invoice_ids,
    )
    @settings(max_examples=150)
    def test_different_orgs_have_independent_sessions(
        self,
        org_id_1: uuid.UUID,
        org_id_2: uuid.UUID,
        session_id_1: str,
        session_id_2: str,
        amount: Decimal,
        invoice_number: str,
        invoice_id_1: uuid.UUID,
        invoice_id_2: uuid.UUID,
    ):
        """Different orgs can have independent pending sessions.
        Clearing one org's session does not affect the other.

        **Validates: Requirements 3.1, 4.1**
        """
        assume(org_id_1 != org_id_2)
        assume(session_id_1 != session_id_2)

        state = QrPaymentState()

        # Create sessions for both orgs
        state = create_qr_session(
            state,
            org_id=org_id_1,
            session_id=session_id_1,
            checkout_url=f"https://checkout.stripe.com/c/pay/{session_id_1}",
            amount=amount,
            invoice_number=invoice_number,
            invoice_id=invoice_id_1,
        )
        state = create_qr_session(
            state,
            org_id=org_id_2,
            session_id=session_id_2,
            checkout_url=f"https://checkout.stripe.com/c/pay/{session_id_2}",
            amount=amount,
            invoice_number=invoice_number,
            invoice_id=invoice_id_2,
        )

        # Both orgs have sessions
        assert kiosk_poll_pending(state, org_id=org_id_1) is not None
        assert kiosk_poll_pending(state, org_id=org_id_2) is not None

        # Complete and clear org_1's session
        state = simulate_payment_complete(state, session_id=session_id_1)
        state = webhook_clear_pending_session(state, session_id=session_id_1)

        # Org 1's session is gone, org 2's remains
        assert kiosk_poll_pending(state, org_id=org_id_1) is None
        assert kiosk_poll_pending(state, org_id=org_id_2) is not None

    @given(
        org_id=valid_org_ids,
        session_id=valid_session_ids,
        amount=valid_amounts,
        invoice_number=valid_invoice_numbers,
        invoice_id=valid_invoice_ids,
    )
    @settings(max_examples=150)
    def test_status_transitions_open_to_complete(
        self,
        org_id: uuid.UUID,
        session_id: str,
        amount: Decimal,
        invoice_number: str,
        invoice_id: uuid.UUID,
    ):
        """Session status transitions from open → complete when payment succeeds.
        Status poll reflects the current state at each step.

        **Validates: Requirements 7.1**
        """
        checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"

        state = QrPaymentState()
        state = create_qr_session(
            state,
            org_id=org_id,
            session_id=session_id,
            checkout_url=checkout_url,
            amount=amount,
            invoice_number=invoice_number,
            invoice_id=invoice_id,
        )

        # Initially open
        status = poll_session_status(state, session_id=session_id)
        assert status is not None
        assert status["status"] == "open"
        assert status["payment_intent_id"] is None

        # After payment
        state = simulate_payment_complete(state, session_id=session_id)
        status = poll_session_status(state, session_id=session_id)
        assert status is not None
        assert status["status"] == "complete"
        assert status["payment_intent_id"] is not None
        # payment_intent_id should be a non-empty string
        assert len(status["payment_intent_id"]) > 0

    @given(org_id=valid_org_ids)
    @settings(max_examples=100)
    def test_kiosk_poll_returns_none_when_no_session(self, org_id: uuid.UUID):
        """Kiosk poll returns None when no pending session exists for the org.

        **Validates: Requirements 4.1**
        """
        state = QrPaymentState()
        polled = kiosk_poll_pending(state, org_id=org_id)
        assert polled is None

    @given(
        org_id=valid_org_ids,
        session_id=valid_session_ids,
        amount=valid_amounts,
        invoice_number=valid_invoice_numbers,
        invoice_id=valid_invoice_ids,
    )
    @settings(max_examples=150)
    def test_webhook_idempotent_clear(
        self,
        org_id: uuid.UUID,
        session_id: str,
        amount: Decimal,
        invoice_number: str,
        invoice_id: uuid.UUID,
    ):
        """Calling webhook_clear_pending_session multiple times is safe
        (idempotent — second call is a no-op).

        **Validates: Requirements 8.5**
        """
        checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"

        state = QrPaymentState()
        state = create_qr_session(
            state,
            org_id=org_id,
            session_id=session_id,
            checkout_url=checkout_url,
            amount=amount,
            invoice_number=invoice_number,
            invoice_id=invoice_id,
        )

        # First clear
        state = webhook_clear_pending_session(state, session_id=session_id)
        assert org_id not in state.pending_sessions

        # Second clear (idempotent — no error, no change)
        state = webhook_clear_pending_session(state, session_id=session_id)
        assert org_id not in state.pending_sessions
        # Payment still recorded
        assert session_id in state.recorded_payments
