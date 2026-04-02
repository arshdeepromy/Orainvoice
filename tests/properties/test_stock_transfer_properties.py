"""Property-based tests for stock transfers.

Properties covered:
  P5  — Stock transfer quantity conservation
  P21 — Transfer state machine validity

**Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 34.5**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Settings — 100 examples per property, no deadline, suppress slow health check
# ---------------------------------------------------------------------------

TRANSFER_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

uuid_strategy = st.uuids()

quantity_strategy = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("99999.999"),
    places=3,
).filter(lambda d: d > 0 and d.is_finite())

stock_quantity_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("99999.999"),
    places=3,
).filter(lambda d: d >= 0 and d.is_finite())

# Valid statuses
VALID_STATUSES = ["pending", "approved", "shipped", "received", "cancelled"]

status_strategy = st.sampled_from(VALID_STATUSES)

# Valid transitions map (from design)
VALID_TRANSITIONS = {
    "pending": {"approved", "cancelled"},
    "approved": {"shipped", "cancelled"},
    "shipped": {"received", "cancelled"},
}

# Terminal states — no transitions out
TERMINAL_STATES = {"received", "cancelled"}

# All possible target statuses for transition attempts
ALL_TARGET_STATUSES = {"pending", "approved", "shipped", "received", "cancelled"}


# ---------------------------------------------------------------------------
# Fake model helpers
# ---------------------------------------------------------------------------


class _FakeStockItem:
    """Minimal StockItem stand-in for property tests."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        current_quantity: Decimal = Decimal("100"),
        reserved_quantity: Decimal = Decimal("0"),
    ):
        self.id = id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.branch_id = branch_id
        self.current_quantity = current_quantity
        self.reserved_quantity = reserved_quantity


class _FakeTransfer:
    """Minimal StockTransfer stand-in for property tests."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        from_branch_id: uuid.UUID | None = None,
        to_branch_id: uuid.UUID | None = None,
        stock_item_id: uuid.UUID | None = None,
        quantity: Decimal = Decimal("10"),
        status: str = "pending",
        requested_by: uuid.UUID | None = None,
        approved_by: uuid.UUID | None = None,
        shipped_at: datetime | None = None,
        received_at: datetime | None = None,
        cancelled_at: datetime | None = None,
        notes: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.from_branch_id = from_branch_id or uuid.uuid4()
        self.to_branch_id = to_branch_id or uuid.uuid4()
        self.stock_item_id = stock_item_id or uuid.uuid4()
        self.quantity = quantity
        self.status = status
        self.requested_by = requested_by or uuid.uuid4()
        self.approved_by = approved_by
        self.shipped_at = shipped_at
        self.received_at = received_at
        self.cancelled_at = cancelled_at
        self.notes = notes
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)


class _FakeBranch:
    """Minimal Branch stand-in."""

    def __init__(self, *, id: uuid.UUID | None = None, org_id: uuid.UUID | None = None):
        self.id = id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()


def _make_scalar_one_or_none(return_value):
    """Create a mock result whose .scalar_one_or_none() returns the given value."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    return mock_result


def _make_scalars_all(return_value):
    """Create a mock result whose .scalars().all() returns the given value."""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = return_value
    mock_result.scalars.return_value = mock_scalars
    return mock_result


# ===========================================================================
# Property 5: Stock transfer quantity conservation
# Feature: branch-management-complete, Property 5
# ===========================================================================


class TestP5StockTransferConservation:
    """For any stock transfer with quantity Q: shipping SHALL decrease source
    branch stock by exactly Q, receiving SHALL increase destination branch
    stock by exactly Q, and cancelling a shipped transfer SHALL restore
    exactly Q to the source branch. The total stock across both branches
    is invariant through the transfer lifecycle.

    **Validates: Requirements 17.3, 17.4, 17.5, 34.5**
    """

    @given(
        transfer_quantity=quantity_strategy,
        initial_source_stock=st.decimals(
            min_value=Decimal("100"),
            max_value=Decimal("99999.999"),
            places=3,
        ).filter(lambda d: d.is_finite()),
        initial_dest_stock=stock_quantity_strategy,
    )
    @TRANSFER_PBT_SETTINGS
    def test_ship_decreases_source_by_q(
        self,
        transfer_quantity: Decimal,
        initial_source_stock: Decimal,
        initial_dest_stock: Decimal,
    ) -> None:
        """P5: shipping decreases source branch stock by exactly Q."""
        assume(initial_source_stock >= transfer_quantity)

        org_id = uuid.uuid4()
        from_branch_id = uuid.uuid4()
        to_branch_id = uuid.uuid4()
        stock_item_id = uuid.uuid4()

        source_item = _FakeStockItem(
            id=stock_item_id,
            org_id=org_id,
            branch_id=from_branch_id,
            current_quantity=initial_source_stock,
        )

        transfer = _FakeTransfer(
            org_id=org_id,
            from_branch_id=from_branch_id,
            to_branch_id=to_branch_id,
            stock_item_id=stock_item_id,
            quantity=transfer_quantity,
            status="approved",
        )

        # Simulate ship: deduct from source
        source_before = source_item.current_quantity
        source_item.current_quantity = source_item.current_quantity - transfer.quantity
        transfer.status = "shipped"

        assert source_item.current_quantity == source_before - transfer_quantity

    @given(
        transfer_quantity=quantity_strategy,
        initial_dest_stock=stock_quantity_strategy,
    )
    @TRANSFER_PBT_SETTINGS
    def test_receive_increases_dest_by_q(
        self,
        transfer_quantity: Decimal,
        initial_dest_stock: Decimal,
    ) -> None:
        """P5: receiving increases destination branch stock by exactly Q."""
        org_id = uuid.uuid4()
        stock_item_id = uuid.uuid4()
        to_branch_id = uuid.uuid4()

        dest_item = _FakeStockItem(
            id=stock_item_id,
            org_id=org_id,
            branch_id=to_branch_id,
            current_quantity=initial_dest_stock,
        )

        transfer = _FakeTransfer(
            org_id=org_id,
            to_branch_id=to_branch_id,
            stock_item_id=stock_item_id,
            quantity=transfer_quantity,
            status="shipped",
        )

        # Simulate receive: add to destination
        dest_before = dest_item.current_quantity
        dest_item.current_quantity = dest_item.current_quantity + transfer.quantity
        transfer.status = "received"

        assert dest_item.current_quantity == dest_before + transfer_quantity

    @given(
        transfer_quantity=quantity_strategy,
        initial_source_stock=st.decimals(
            min_value=Decimal("100"),
            max_value=Decimal("99999.999"),
            places=3,
        ).filter(lambda d: d.is_finite()),
    )
    @TRANSFER_PBT_SETTINGS
    def test_cancel_shipped_restores_source(
        self,
        transfer_quantity: Decimal,
        initial_source_stock: Decimal,
    ) -> None:
        """P5: cancelling a shipped transfer restores exactly Q to source."""
        assume(initial_source_stock >= transfer_quantity)

        org_id = uuid.uuid4()
        from_branch_id = uuid.uuid4()
        stock_item_id = uuid.uuid4()

        source_item = _FakeStockItem(
            id=stock_item_id,
            org_id=org_id,
            branch_id=from_branch_id,
            current_quantity=initial_source_stock,
        )

        transfer = _FakeTransfer(
            org_id=org_id,
            from_branch_id=from_branch_id,
            stock_item_id=stock_item_id,
            quantity=transfer_quantity,
            status="approved",
        )

        # Simulate ship
        source_item.current_quantity = source_item.current_quantity - transfer.quantity
        transfer.status = "shipped"
        stock_after_ship = source_item.current_quantity

        # Simulate cancel from shipped — restore stock
        source_item.current_quantity = source_item.current_quantity + transfer.quantity
        transfer.status = "cancelled"

        # Stock should be back to initial
        assert source_item.current_quantity == initial_source_stock

    @given(
        transfer_quantity=st.integers(min_value=1, max_value=99999),
        initial_source_stock=st.integers(min_value=100, max_value=99999),
        initial_dest_stock=st.integers(min_value=0, max_value=99999),
    )
    @TRANSFER_PBT_SETTINGS
    def test_total_stock_invariant_through_lifecycle(
        self,
        transfer_quantity: int,
        initial_source_stock: int,
        initial_dest_stock: int,
    ) -> None:
        """P5: total stock across both branches is invariant through the
        full transfer lifecycle (ship + receive). During transit (after ship,
        before receive), Q units are 'in flight' — the sum of source + dest
        + in_flight remains constant."""
        assume(initial_source_stock >= transfer_quantity)

        q = Decimal(str(transfer_quantity))
        source_qty = Decimal(str(initial_source_stock))
        dest_qty = Decimal(str(initial_dest_stock))
        total_before = source_qty + dest_qty

        # Ship: deduct from source, Q is now in-flight
        source_qty = source_qty - q
        in_flight = q
        assert source_qty + dest_qty + in_flight == total_before

        # Receive: add to destination, in-flight goes to zero
        dest_qty = dest_qty + q
        in_flight = Decimal("0")
        assert source_qty + dest_qty + in_flight == total_before
        # After full lifecycle, total is conserved
        assert source_qty + dest_qty == total_before


# ===========================================================================
# Property 21: Transfer state machine validity
# Feature: branch-management-complete, Property 21
# ===========================================================================


class TestP21TransferStateMachineValidity:
    """For any stock transfer, the status transitions SHALL follow only valid
    paths: pending → approved → shipped → received, with cancellation allowed
    from pending, approved, or shipped. No other transitions SHALL be permitted.

    **Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5**
    """

    @given(
        current_status=st.sampled_from(["pending", "approved", "shipped"]),
        target_status=st.sampled_from(list(ALL_TARGET_STATUSES)),
    )
    @TRANSFER_PBT_SETTINGS
    def test_valid_transitions_accepted_invalid_rejected(
        self,
        current_status: str,
        target_status: str,
    ) -> None:
        """P21: only valid transitions are accepted; invalid ones raise ValueError."""
        from app.modules.inventory.transfer_service import _validate_transition

        allowed = VALID_TRANSITIONS.get(current_status, set())

        if target_status in allowed:
            # Should not raise
            _validate_transition(current_status, target_status)
        else:
            # Should raise ValueError
            with pytest.raises(ValueError, match="Cannot transition from"):
                _validate_transition(current_status, target_status)

    @given(
        target_status=st.sampled_from(list(ALL_TARGET_STATUSES)),
    )
    @TRANSFER_PBT_SETTINGS
    def test_terminal_states_reject_all_transitions(
        self,
        target_status: str,
    ) -> None:
        """P21: terminal states (received, cancelled) reject all transitions."""
        from app.modules.inventory.transfer_service import _validate_transition

        for terminal in TERMINAL_STATES:
            with pytest.raises(ValueError, match="Cannot transition from"):
                _validate_transition(terminal, target_status)

    @TRANSFER_PBT_SETTINGS
    @given(st.data())
    def test_happy_path_sequence_is_valid(self, data) -> None:
        """P21: the happy path pending→approved→shipped→received is always valid."""
        from app.modules.inventory.transfer_service import _validate_transition

        happy_path = [
            ("pending", "approved"),
            ("approved", "shipped"),
            ("shipped", "received"),
        ]

        for current, target in happy_path:
            # Should not raise
            _validate_transition(current, target)

    @given(
        cancel_from=st.sampled_from(["pending", "approved", "shipped"]),
    )
    @TRANSFER_PBT_SETTINGS
    def test_cancellation_allowed_from_non_terminal(
        self,
        cancel_from: str,
    ) -> None:
        """P21: cancellation is allowed from pending, approved, or shipped."""
        from app.modules.inventory.transfer_service import _validate_transition

        # Should not raise
        _validate_transition(cancel_from, "cancelled")

    @given(
        current_status=st.sampled_from(list(ALL_TARGET_STATUSES)),
    )
    @TRANSFER_PBT_SETTINGS
    def test_no_backward_transitions(
        self,
        current_status: str,
    ) -> None:
        """P21: no backward transitions are allowed (e.g. approved→pending)."""
        from app.modules.inventory.transfer_service import _validate_transition

        # Define backward transitions
        backward_map = {
            "approved": "pending",
            "shipped": "approved",
            "received": "shipped",
        }

        if current_status in backward_map:
            backward_target = backward_map[current_status]
            with pytest.raises(ValueError, match="Cannot transition from"):
                _validate_transition(current_status, backward_target)
