"""Property-based tests for Quote Cancellation Workflow (Task 8).

Feature: quote-cancellation-workflow

Verifies the four correctness properties defined in the design document:
1. Valid cancellation transitions succeed
2. Invalid cancellation transitions are rejected
3. Cancellation preserves quote number and records metadata
4. Cancelled quotes are deletable

Uses Hypothesis to generate random inputs and verify properties hold universally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.quotes.service import (
    _validate_status_transition,
    cancel_quote,
    delete_quote,
    VALID_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Statuses from which cancellation is valid
cancellable_statuses = st.sampled_from(["issued", "sent"])

# Statuses from which cancellation is NOT valid
non_cancellable_statuses = st.sampled_from([
    "draft", "accepted", "declined", "expired", "cancelled",
])

# Non-empty reason strings (at least 1 non-whitespace character)
reason_strings = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=200,
)

# Any reason string (including empty) for invalid transition tests
any_reason_strings = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=0,
    max_size=200,
)

uuids = st.uuids()

quote_numbers = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=20,
).map(lambda s: f"Q-{s}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_quote(
    *,
    status: str,
    org_id: uuid.UUID | None = None,
    quote_number: str = "Q-0001",
):
    """Build a mock Quote object with the given status."""
    q = MagicMock()
    q.id = uuid.uuid4()
    q.org_id = org_id or uuid.uuid4()
    q.customer_id = uuid.uuid4()
    q.quote_number = quote_number
    q.status = status
    q.cancel_reason = None
    q.cancelled_at = None
    q.cancelled_by = None
    q.vehicle_rego = None
    q.vehicle_make = None
    q.vehicle_model = None
    q.vehicle_year = None
    q.vehicle_odometer = None
    q.vehicle_wof_expiry = None
    q.vehicle_cof_expiry = None
    q.project_id = None
    q.valid_until = None
    q.subtotal = None
    q.gst_amount = None
    q.total = None
    q.discount_type = None
    q.discount_value = None
    q.discount_amount = None
    q.shipping_charges = None
    q.adjustment = None
    q.notes = None
    q.terms = None
    q.subject = None
    q.acceptance_token = None
    q.converted_invoice_id = None
    q.order_number = None
    q.salesperson_id = None
    q.additional_vehicles = []
    q.fluid_usage = []
    q.created_by = uuid.uuid4()
    q.created_at = datetime.now(timezone.utc)
    q.updated_at = datetime.now(timezone.utc)
    return q


def _mock_scalar_one_or_none(value):
    """Create a mock execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_all(values):
    """Create a mock execute result that returns values from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


# ===========================================================================
# Property 1: Valid cancellation transitions succeed
# Feature: quote-cancellation-workflow, Property 1: Valid cancellation transitions succeed
# ===========================================================================


class TestProperty1ValidCancellationTransitionsSucceed:
    """Feature: quote-cancellation-workflow, Property 1: Valid cancellation transitions succeed

    For any quote with status in {"issued", "sent"} and any non-empty reason
    string, calling `cancel_quote` SHALL transition the quote status to
    "cancelled" without raising an error.

    **Validates: Requirements 1.1, 1.2**
    """

    @PBT_SETTINGS
    @given(status=cancellable_statuses, reason=reason_strings)
    def test_valid_status_transition_does_not_raise(self, status, reason):
        """_validate_status_transition does not raise for cancellable statuses.

        **Validates: Requirements 1.1, 1.2**
        """
        # Should not raise ValueError
        _validate_status_transition(status, "cancelled")

    @PBT_SETTINGS
    @given(
        status=cancellable_statuses,
        reason=reason_strings,
        org_id=uuids,
        user_id=uuids,
        quote_id=uuids,
    )
    @pytest.mark.asyncio
    async def test_cancel_quote_transitions_to_cancelled(
        self, status, reason, org_id, user_id, quote_id
    ):
        """cancel_quote transitions a cancellable quote to "cancelled" status.

        **Validates: Requirements 1.1, 1.2**
        """
        quote = _make_mock_quote(status=status, org_id=org_id)
        quote.id = quote_id

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First query: SELECT quote
                return _mock_scalar_one_or_none(quote)
            else:
                # Second query: SELECT line items after refresh
                return _mock_scalars_all([])

        db = AsyncMock()
        db.execute = mock_execute
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            result = await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote_id,
                reason=reason,
            )

        assert quote.status == "cancelled"
        assert result["status"] == "cancelled"


# ===========================================================================
# Property 2: Invalid cancellation transitions are rejected
# Feature: quote-cancellation-workflow, Property 2: Invalid cancellation transitions are rejected
# ===========================================================================


class TestProperty2InvalidCancellationTransitionsRejected:
    """Feature: quote-cancellation-workflow, Property 2: Invalid cancellation transitions are rejected

    For any quote with status in {"draft", "accepted", "declined", "expired",
    "cancelled"} and any reason string, calling `cancel_quote` SHALL raise a
    ValueError.

    **Validates: Requirements 1.3**
    """

    @PBT_SETTINGS
    @given(status=non_cancellable_statuses, reason=any_reason_strings)
    def test_invalid_status_transition_raises_value_error(self, status, reason):
        """_validate_status_transition raises ValueError for non-cancellable statuses.

        **Validates: Requirements 1.3**
        """
        with pytest.raises(ValueError, match="Cannot transition quote"):
            _validate_status_transition(status, "cancelled")

    @PBT_SETTINGS
    @given(
        status=non_cancellable_statuses,
        reason=any_reason_strings,
        org_id=uuids,
        user_id=uuids,
        quote_id=uuids,
    )
    @pytest.mark.asyncio
    async def test_cancel_quote_raises_for_invalid_status(
        self, status, reason, org_id, user_id, quote_id
    ):
        """cancel_quote raises ValueError for quotes with non-cancellable status.

        **Validates: Requirements 1.3**
        """
        quote = _make_mock_quote(status=status, org_id=org_id)
        quote.id = quote_id

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(quote))

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Cannot transition quote"):
                await cancel_quote(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    quote_id=quote_id,
                    reason=reason,
                )


# ===========================================================================
# Property 3: Cancellation preserves quote number and records metadata
# Feature: quote-cancellation-workflow, Property 3: Cancellation preserves quote number and records metadata
# ===========================================================================


class TestProperty3CancellationPreservesMetadata:
    """Feature: quote-cancellation-workflow, Property 3: Cancellation preserves quote number and records metadata

    For any cancellable quote, after calling `cancel_quote`, the resulting
    quote SHALL have the same quote_number, cancel_reason equal to the
    provided reason, and cancelled_by equal to the provided user_id.

    **Validates: Requirements 1.4, 1.5, 1.6**
    """

    @PBT_SETTINGS
    @given(
        status=cancellable_statuses,
        reason=reason_strings,
        org_id=uuids,
        user_id=uuids,
        quote_id=uuids,
        quote_number=quote_numbers,
    )
    @pytest.mark.asyncio
    async def test_quote_number_unchanged_after_cancellation(
        self, status, reason, org_id, user_id, quote_id, quote_number
    ):
        """After cancellation, quote_number is unchanged.

        **Validates: Requirements 1.4**
        """
        quote = _make_mock_quote(
            status=status, org_id=org_id, quote_number=quote_number
        )
        quote.id = quote_id

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalar_one_or_none(quote)
            else:
                return _mock_scalars_all([])

        db = AsyncMock()
        db.execute = mock_execute
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            result = await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote_id,
                reason=reason,
            )

        assert result["quote_number"] == quote_number

    @PBT_SETTINGS
    @given(
        status=cancellable_statuses,
        reason=reason_strings,
        org_id=uuids,
        user_id=uuids,
        quote_id=uuids,
    )
    @pytest.mark.asyncio
    async def test_cancel_reason_equals_provided_reason(
        self, status, reason, org_id, user_id, quote_id
    ):
        """After cancellation, cancel_reason equals the provided reason.

        **Validates: Requirements 1.5**
        """
        quote = _make_mock_quote(status=status, org_id=org_id)
        quote.id = quote_id

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalar_one_or_none(quote)
            else:
                return _mock_scalars_all([])

        db = AsyncMock()
        db.execute = mock_execute
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            result = await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote_id,
                reason=reason,
            )

        assert quote.cancel_reason == reason
        assert result["cancel_reason"] == reason

    @PBT_SETTINGS
    @given(
        status=cancellable_statuses,
        reason=reason_strings,
        org_id=uuids,
        user_id=uuids,
        quote_id=uuids,
    )
    @pytest.mark.asyncio
    async def test_cancelled_by_equals_provided_user_id(
        self, status, reason, org_id, user_id, quote_id
    ):
        """After cancellation, cancelled_by equals the provided user_id.

        **Validates: Requirements 1.6**
        """
        quote = _make_mock_quote(status=status, org_id=org_id)
        quote.id = quote_id

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalar_one_or_none(quote)
            else:
                return _mock_scalars_all([])

        db = AsyncMock()
        db.execute = mock_execute
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            result = await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote_id,
                reason=reason,
            )

        assert quote.cancelled_by == user_id
        assert result["cancelled_by"] == user_id


# ===========================================================================
# Property 4: Cancelled quotes are deletable
# Feature: quote-cancellation-workflow, Property 4: Cancelled quotes are deletable
# ===========================================================================


class TestProperty4CancelledQuotesAreDeletable:
    """Feature: quote-cancellation-workflow, Property 4: Cancelled quotes are deletable

    For any quote with status "cancelled", calling `delete_quote` SHALL
    succeed without raising a ValueError.

    **Validates: Requirements 4.1**
    """

    @PBT_SETTINGS
    @given(
        org_id=uuids,
        user_id=uuids,
        quote_id=uuids,
    )
    @pytest.mark.asyncio
    async def test_delete_quote_succeeds_for_cancelled_status(
        self, org_id, user_id, quote_id
    ):
        """delete_quote does not raise ValueError for cancelled quotes.

        **Validates: Requirements 4.1**
        """
        quote = _make_mock_quote(status="cancelled", org_id=org_id)
        quote.id = quote_id
        quote.quote_number = "Q-0001"

        call_count = 0

        async def mock_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First query: SELECT quote
                return _mock_scalar_one_or_none(quote)
            else:
                # Second query: SELECT line items
                return _mock_scalars_all([])

        db = AsyncMock()
        db.execute = mock_execute
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            # Should not raise ValueError
            result = await delete_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote_id,
            )

        assert result["deleted"] is True
        assert result["quote_id"] == quote_id
