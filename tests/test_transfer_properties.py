"""Property-based tests for branch stock transfers.

Tests the pure logic of transfer status transitions and detail view
action button visibility without requiring a database.

Properties covered:
  P26 — Transfer rejection sets status to rejected
  P27 — Transfer receive sets status to received
  P28 — Transfer detail view shows correct action buttons per status

**Validates: Requirements 31.4, 33.2, 34.3**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_all_transfer_statuses = st.sampled_from([
    "pending", "approved", "executed", "received", "partially_received",
    "rejected", "cancelled",
])

_non_pending_statuses = st.sampled_from([
    "approved", "executed", "received", "rejected", "cancelled",
])

_non_executed_statuses = st.sampled_from([
    "pending", "approved", "received", "rejected", "cancelled",
])

_positive_decimal = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.999"),
    places=3,
    allow_nan=False,
    allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Pure functions extracted from service.py for testability
# ---------------------------------------------------------------------------


def reject_transfer(status: str) -> str:
    """Simulate the reject_transfer status transition.

    In the real code (app/modules/franchise/service.py → reject_transfer):
        if transfer.status != "pending":
            raise ValueError(f"Cannot reject transfer in '{transfer.status}' status")
        transfer.status = "rejected"

    Returns the new status if valid, raises ValueError otherwise.

    Mirrors: app/modules/franchise/service.py → reject_transfer
    """
    if status != "pending":
        raise ValueError(f"Cannot reject transfer in '{status}' status")
    return "rejected"


def receive_transfer(
    status: str,
    transfer_quantity: Decimal | None = None,
    received_quantity: Decimal | None = None,
) -> str:
    """Simulate the receive_transfer status transition with partial receive.

    In the real code (app/modules/franchise/service.py → receive_transfer):
        if transfer.status != "executed":
            raise ValueError(...)
        if received_quantity is not None:
            if received_quantity > transfer_qty:
                raise ValueError(...)
            if transfer_qty - received_quantity > 0:
                status = "partially_received"
            else:
                status = "received"
        else:
            status = "received"

    Returns the new status if valid, raises ValueError otherwise.

    Mirrors: app/modules/franchise/service.py → receive_transfer

    **Validates: Requirements 33.2, 54.1, 54.2, 54.3**
    """
    if status != "executed":
        raise ValueError(f"Cannot receive transfer in '{status}' status")

    if received_quantity is not None:
        if transfer_quantity is not None and received_quantity > transfer_quantity:
            raise ValueError(
                "Received quantity cannot exceed the transfer quantity",
            )
        if transfer_quantity is not None and received_quantity < transfer_quantity:
            return "partially_received"
    return "received"


def get_action_buttons(status: str, is_at_destination: bool = True) -> list[str]:
    """Determine which action buttons to show for a transfer status.

    Mirrors the button visibility logic in
    frontend/src/pages/franchise/TransferDetail.tsx:
        - pending → Approve, Reject
        - approved → Execute
        - executed (at destination) → Receive
        - received, partially_received, rejected, cancelled → no buttons

    Parameters
    ----------
    status:
        The current transfer status.
    is_at_destination:
        Whether the current user is at the destination location.
        Only affects the Receive button for executed transfers.

    Returns
    -------
    List of button labels that should be visible.
    """
    if status == "pending":
        return ["Approve", "Reject"]
    elif status == "approved":
        return ["Execute"]
    elif status == "executed":
        if is_at_destination:
            return ["Receive"]
        return []
    else:
        # received, partially_received, rejected, cancelled — no action buttons
        return []


# ===========================================================================
# Property 26: Transfer rejection sets status to rejected
# ===========================================================================


class TestP26TransferRejectionSetsStatusToRejected:
    """For any transfer in pending status, calling reject_transfer SHALL set
    the status to rejected. For transfers in other statuses, it SHALL raise
    a ValueError.

    **Validates: Requirements 31.4**
    """

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_pending_transfer_becomes_rejected(
        self, transfer_id: uuid.UUID, quantity: Decimal,
    ) -> None:
        """P26: A pending transfer is successfully rejected regardless of
        other transfer properties (id, quantity).

        **Validates: Requirements 31.4**
        """
        new_status = reject_transfer("pending")
        assert new_status == "rejected", (
            f"Expected status='rejected' after rejecting pending transfer "
            f"(id={transfer_id}, qty={quantity}), got '{new_status}'"
        )

    @given(status=_non_pending_statuses)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_non_pending_transfer_raises_on_reject(self, status: str) -> None:
        """P26: Rejecting a transfer that is not in 'pending' status raises
        a ValueError.

        **Validates: Requirements 31.4**
        """
        raised = False
        try:
            reject_transfer(status)
        except ValueError:
            raised = True

        assert raised, (
            f"Expected ValueError when rejecting transfer in '{status}' status, "
            f"but no exception was raised"
        )

    @given(status=_all_transfer_statuses)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_reject_only_valid_from_pending(self, status: str) -> None:
        """P26: reject_transfer succeeds if and only if the current status
        is 'pending'.

        **Validates: Requirements 31.4**
        """
        try:
            new_status = reject_transfer(status)
            # If no exception, status must have been pending
            assert status == "pending", (
                f"reject_transfer succeeded for status='{status}', "
                f"but should only succeed for 'pending'"
            )
            assert new_status == "rejected", (
                f"Expected new status='rejected', got '{new_status}'"
            )
        except ValueError:
            # If exception, status must NOT have been pending
            assert status != "pending", (
                f"reject_transfer raised ValueError for status='pending', "
                f"but should have succeeded"
            )


# ===========================================================================
# Property 27: Transfer receive sets status to received
# ===========================================================================


class TestP27TransferReceiveSetsStatusToReceived:
    """For any transfer in executed status, calling receive_transfer SHALL set
    the status to received (full receive) or partially_received (partial).
    For transfers in other statuses, it SHALL raise a ValueError.

    **Validates: Requirements 33.2, 54.1, 54.2, 54.3**
    """

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_executed_transfer_becomes_received(
        self, transfer_id: uuid.UUID, quantity: Decimal,
    ) -> None:
        """P27: An executed transfer is successfully received (full quantity)
        regardless of other transfer properties (id, quantity).

        **Validates: Requirements 33.2**
        """
        new_status = receive_transfer("executed", transfer_quantity=quantity, received_quantity=quantity)
        assert new_status == "received", (
            f"Expected status='received' after receiving executed transfer "
            f"(id={transfer_id}, qty={quantity}), got '{new_status}'"
        )

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_executed_transfer_default_receive_is_full(
        self, transfer_id: uuid.UUID, quantity: Decimal,
    ) -> None:
        """P27: When received_quantity is not specified, status becomes received.

        **Validates: Requirements 54.3**
        """
        new_status = receive_transfer("executed")
        assert new_status == "received", (
            f"Expected status='received' when no received_quantity specified, "
            f"got '{new_status}'"
        )

    @given(status=_non_executed_statuses)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_non_executed_transfer_raises_on_receive(self, status: str) -> None:
        """P27: Receiving a transfer that is not in 'executed' status raises
        a ValueError.

        **Validates: Requirements 33.2**
        """
        raised = False
        try:
            receive_transfer(status)
        except ValueError:
            raised = True

        assert raised, (
            f"Expected ValueError when receiving transfer in '{status}' status, "
            f"but no exception was raised"
        )

    @given(status=_all_transfer_statuses)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_receive_only_valid_from_executed(self, status: str) -> None:
        """P27: receive_transfer succeeds if and only if the current status
        is 'executed'.

        **Validates: Requirements 33.2**
        """
        try:
            new_status = receive_transfer(status)
            # If no exception, status must have been executed
            assert status == "executed", (
                f"receive_transfer succeeded for status='{status}', "
                f"but should only succeed for 'executed'"
            )
            assert new_status == "received", (
                f"Expected new status='received', got '{new_status}'"
            )
        except ValueError:
            # If exception, status must NOT have been executed
            assert status != "executed", (
                f"receive_transfer raised ValueError for status='executed', "
                f"but should have succeeded"
            )

    @given(
        transfer_qty=_positive_decimal,
        received_fraction=st.floats(min_value=0.01, max_value=0.99),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_partial_receive_sets_partially_received(
        self, transfer_qty: Decimal, received_fraction: float,
    ) -> None:
        """P27: When received_quantity < transfer_quantity, status becomes
        partially_received.

        **Validates: Requirements 54.2**
        """
        received_qty = (transfer_qty * Decimal(str(received_fraction))).quantize(Decimal("0.001"))
        if received_qty <= 0:
            received_qty = Decimal("0.001")
        if received_qty >= transfer_qty:
            return  # Skip edge case where rounding makes them equal

        new_status = receive_transfer(
            "executed",
            transfer_quantity=transfer_qty,
            received_quantity=received_qty,
        )
        assert new_status == "partially_received", (
            f"Expected 'partially_received' when received {received_qty} of "
            f"{transfer_qty}, got '{new_status}'"
        )

    @given(transfer_qty=_positive_decimal)
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_received_quantity_exceeding_transfer_raises(
        self, transfer_qty: Decimal,
    ) -> None:
        """P27: received_quantity > transfer_quantity raises ValueError.

        **Validates: Requirements 54.1**
        """
        over_qty = transfer_qty + Decimal("1")
        raised = False
        try:
            receive_transfer(
                "executed",
                transfer_quantity=transfer_qty,
                received_quantity=over_qty,
            )
        except ValueError:
            raised = True

        assert raised, (
            f"Expected ValueError when received_quantity ({over_qty}) exceeds "
            f"transfer_quantity ({transfer_qty})"
        )


# ===========================================================================
# Property 28: Transfer detail view shows correct action buttons per status
# ===========================================================================


class TestP28TransferDetailViewActionButtons:
    """For each transfer status, the detail view SHALL show the appropriate
    action buttons: Approve/Reject for pending, Execute for approved,
    Receive for executed (when at destination), none for other statuses.

    **Validates: Requirements 34.3**
    """

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_pending_shows_approve_and_reject(
        self, transfer_id: uuid.UUID, quantity: Decimal,
    ) -> None:
        """P28: Pending transfers show Approve and Reject buttons.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons("pending")
        assert "Approve" in buttons, (
            f"Expected 'Approve' button for pending transfer, got {buttons}"
        )
        assert "Reject" in buttons, (
            f"Expected 'Reject' button for pending transfer, got {buttons}"
        )
        assert len(buttons) == 2, (
            f"Expected exactly 2 buttons for pending, got {len(buttons)}: {buttons}"
        )

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_approved_shows_execute(
        self, transfer_id: uuid.UUID, quantity: Decimal,
    ) -> None:
        """P28: Approved transfers show only the Execute button.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons("approved")
        assert buttons == ["Execute"], (
            f"Expected ['Execute'] for approved transfer, got {buttons}"
        )

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
        is_at_destination=st.just(True),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_executed_at_destination_shows_receive(
        self,
        transfer_id: uuid.UUID,
        quantity: Decimal,
        is_at_destination: bool,
    ) -> None:
        """P28: Executed transfers show Receive button when user is at
        the destination location.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons("executed", is_at_destination=True)
        assert buttons == ["Receive"], (
            f"Expected ['Receive'] for executed transfer at destination, "
            f"got {buttons}"
        )

    @given(
        transfer_id=st.uuids(),
        quantity=_positive_decimal,
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_executed_not_at_destination_shows_no_buttons(
        self, transfer_id: uuid.UUID, quantity: Decimal,
    ) -> None:
        """P28: Executed transfers show no buttons when user is NOT at
        the destination location.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons("executed", is_at_destination=False)
        assert buttons == [], (
            f"Expected no buttons for executed transfer when not at destination, "
            f"got {buttons}"
        )

    @given(
        status=st.sampled_from(["received", "partially_received", "rejected", "cancelled"]),
        is_at_destination=st.booleans(),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_terminal_statuses_show_no_buttons(
        self, status: str, is_at_destination: bool,
    ) -> None:
        """P28: Terminal statuses (received, partially_received, rejected,
        cancelled) show no action buttons regardless of user location.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons(status, is_at_destination=is_at_destination)
        assert buttons == [], (
            f"Expected no buttons for terminal status '{status}', got {buttons}"
        )

    @given(
        status=_all_transfer_statuses,
        is_at_destination=st.booleans(),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_button_count_is_bounded(
        self, status: str, is_at_destination: bool,
    ) -> None:
        """P28: The number of action buttons is always between 0 and 2
        for any status.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons(status, is_at_destination=is_at_destination)
        assert 0 <= len(buttons) <= 2, (
            f"Expected 0-2 buttons for status '{status}', "
            f"got {len(buttons)}: {buttons}"
        )

    @given(
        status=_all_transfer_statuses,
        is_at_destination=st.booleans(),
    )
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_buttons_match_status_exactly(
        self, status: str, is_at_destination: bool,
    ) -> None:
        """P28: The action buttons returned match the expected set for
        each status exactly — no extra or missing buttons.

        **Validates: Requirements 34.3**
        """
        buttons = get_action_buttons(status, is_at_destination=is_at_destination)

        if status == "pending":
            expected = ["Approve", "Reject"]
        elif status == "approved":
            expected = ["Execute"]
        elif status == "executed":
            expected = ["Receive"] if is_at_destination else []
        else:
            expected = []

        assert buttons == expected, (
            f"For status='{status}', is_at_destination={is_at_destination}: "
            f"expected {expected}, got {buttons}"
        )
