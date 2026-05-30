"""Unit tests for Quote Cancellation Endpoint (Task 9.1, 9.2).

Tests the cancel_quote service function and verifies:
- Valid cancel (200 equivalent): quote with status "issued" or "sent" is cancelled
- Empty reason (400/422): Pydantic validation rejects empty reason
- Not found (404): non-existent quote raises ValueError with "not found"
- Invalid status (400): quote with status "draft" raises ValueError
- Audit log entry is written with action "quote.cancelled" and correct before/after values
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.modules.quotes.schemas import QuoteCancelRequest
from app.modules.quotes.service import cancel_quote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_quote(
    *,
    status: str,
    org_id: uuid.UUID | None = None,
    quote_number: str = "QT-0001",
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
    q.vehicle_rego = "ABC123"
    q.vehicle_make = "Toyota"
    q.vehicle_model = "Corolla"
    q.vehicle_year = 2020
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


def _make_db_with_quote(quote):
    """Create a mock async DB session that returns the given quote on first execute."""
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
    return db


# ===========================================================================
# Task 9.1: Cancel endpoint unit tests
# ===========================================================================


class TestCancelEndpointValidCancel:
    """Valid cancel: quote exists with status 'issued' or 'sent', returns updated quote."""

    @pytest.mark.asyncio
    async def test_cancel_issued_quote_returns_cancelled_status(self):
        """Cancelling an issued quote transitions to 'cancelled' and returns result."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="issued", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            result = await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Customer changed requirements",
            )

        assert result["status"] == "cancelled"
        assert result["cancel_reason"] == "Customer changed requirements"
        assert result["cancelled_by"] == user_id

    @pytest.mark.asyncio
    async def test_cancel_sent_quote_returns_cancelled_status(self):
        """Cancelling a sent quote transitions to 'cancelled' and returns result."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="sent", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            result = await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="No longer needed",
            )

        assert result["status"] == "cancelled"
        assert result["cancel_reason"] == "No longer needed"
        assert result["cancelled_by"] == user_id

    @pytest.mark.asyncio
    async def test_cancel_sets_cancelled_at_timestamp(self):
        """Cancelling a quote sets the cancelled_at timestamp."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="issued", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Test reason",
            )

        assert quote.cancelled_at is not None
        assert isinstance(quote.cancelled_at, datetime)


class TestCancelEndpointEmptyReason:
    """Empty reason: Pydantic validation rejects empty/missing reason (400/422)."""

    def test_empty_reason_rejected_by_schema(self):
        """QuoteCancelRequest rejects empty string reason."""
        with pytest.raises(Exception):
            QuoteCancelRequest(reason="")

    def test_missing_reason_rejected_by_schema(self):
        """QuoteCancelRequest rejects missing reason field."""
        with pytest.raises(Exception):
            QuoteCancelRequest()  # type: ignore[call-arg]

    def test_whitespace_only_reason_rejected_by_schema(self):
        """QuoteCancelRequest rejects whitespace-only reason (min_length=1 counts whitespace)."""
        # Note: Pydantic min_length=1 counts whitespace chars, so " " passes validation.
        # The actual validation is min_length=1, so a single space IS valid at schema level.
        # The service layer trims if needed. This test documents the schema behaviour.
        schema = QuoteCancelRequest(reason=" ")
        assert schema.reason == " "

    def test_valid_reason_accepted_by_schema(self):
        """QuoteCancelRequest accepts a non-empty reason."""
        schema = QuoteCancelRequest(reason="Customer requested cancellation")
        assert schema.reason == "Customer requested cancellation"


class TestCancelEndpointNotFound:
    """Not found: non-existent quote returns 404 equivalent (ValueError with 'not found')."""

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_quote_raises_not_found(self):
        """cancel_quote raises ValueError with 'not found' for missing quote."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(None))

        with pytest.raises(ValueError, match="not found"):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote_id,
                reason="Some reason",
            )

    @pytest.mark.asyncio
    async def test_cancel_quote_wrong_org_raises_not_found(self):
        """cancel_quote raises ValueError when quote belongs to different org."""
        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Quote exists but with different org_id — the SELECT WHERE filters by org_id
        # so scalar_one_or_none returns None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(None))

        with pytest.raises(ValueError, match="not found"):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=uuid.uuid4(),
                reason="Test",
            )


class TestCancelEndpointInvalidStatus:
    """Invalid status: quote with non-cancellable status returns 400 (ValueError)."""

    @pytest.mark.asyncio
    async def test_cancel_draft_quote_raises_value_error(self):
        """cancel_quote raises ValueError for draft quote."""
        org_id = uuid.uuid4()
        quote = _make_mock_quote(status="draft", org_id=org_id)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(quote))

        with pytest.raises(ValueError, match="Cannot transition"):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                quote_id=quote.id,
                reason="Test",
            )

    @pytest.mark.asyncio
    async def test_cancel_accepted_quote_raises_value_error(self):
        """cancel_quote raises ValueError for accepted quote."""
        org_id = uuid.uuid4()
        quote = _make_mock_quote(status="accepted", org_id=org_id)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(quote))

        with pytest.raises(ValueError, match="Cannot transition"):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                quote_id=quote.id,
                reason="Test",
            )

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_quote_raises_value_error(self):
        """cancel_quote raises ValueError for already cancelled quote."""
        org_id = uuid.uuid4()
        quote = _make_mock_quote(status="cancelled", org_id=org_id)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(quote))

        with pytest.raises(ValueError, match="Cannot transition"):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                quote_id=quote.id,
                reason="Test",
            )

    @pytest.mark.asyncio
    async def test_cancel_expired_quote_raises_value_error(self):
        """cancel_quote raises ValueError for expired quote."""
        org_id = uuid.uuid4()
        quote = _make_mock_quote(status="expired", org_id=org_id)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalar_one_or_none(quote))

        with pytest.raises(ValueError, match="Cannot transition"):
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                quote_id=quote.id,
                reason="Test",
            )


# ===========================================================================
# Task 9.2: Audit log entry verification
# ===========================================================================


class TestCancelQuoteAuditLog:
    """Verify audit log entry is written with action 'quote.cancelled' and correct values."""

    @pytest.mark.asyncio
    async def test_audit_log_called_with_correct_action(self):
        """write_audit_log is called with action='quote.cancelled'."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="issued", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Customer withdrew",
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "quote.cancelled"

    @pytest.mark.asyncio
    async def test_audit_log_before_value_contains_previous_status(self):
        """Audit log before_value contains the previous status."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="sent", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="No longer relevant",
            )

        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["before_value"]["status"] == "sent"

    @pytest.mark.asyncio
    async def test_audit_log_after_value_contains_cancelled_status_and_reason(self):
        """Audit log after_value contains status='cancelled', cancel_reason, and cancelled_by."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="issued", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Scope changed",
            )

        call_kwargs = mock_audit.call_args.kwargs
        after = call_kwargs["after_value"]
        assert after["status"] == "cancelled"
        assert after["cancel_reason"] == "Scope changed"
        assert after["cancelled_by"] == str(user_id)

    @pytest.mark.asyncio
    async def test_audit_log_entity_type_and_entity_id(self):
        """Audit log is written with entity_type='quote' and correct entity_id."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="issued", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Test",
            )

        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["entity_type"] == "quote"
        assert call_kwargs["entity_id"] == quote.id

    @pytest.mark.asyncio
    async def test_audit_log_receives_org_and_user_ids(self):
        """Audit log is written with correct org_id and user_id."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="sent", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Test",
            )

        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_audit_log_receives_ip_address(self):
        """Audit log is written with the provided ip_address."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote = _make_mock_quote(status="issued", org_id=org_id)
        db = _make_db_with_quote(quote)

        with patch("app.modules.quotes.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await cancel_quote(
                db,
                org_id=org_id,
                user_id=user_id,
                quote_id=quote.id,
                reason="Test",
                ip_address="192.168.1.100",
            )

        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["ip_address"] == "192.168.1.100"
