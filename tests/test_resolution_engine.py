"""Unit tests for ResolutionEngine.

Tests each resolution type triggers the correct downstream action,
verifies downstream action results with mocked services, and tests
error handling (claim not approved, missing invoice for refund, etc.).

Requirements: 3.1-3.8, 4.1-4.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401

from app.modules.claims.models import (
    ClaimStatus,
    CustomerClaim,
    ResolutionType,
)
from app.modules.claims.resolution_engine import ResolutionEngine, ResolutionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
CLAIM_ID = uuid.uuid4()
JOB_CARD_ID = uuid.uuid4()
BRANCH_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()


def _make_claim(
    status="approved",
    invoice_id=INVOICE_ID,
    job_card_id=None,
    claim_id=None,
    org_id=None,
):
    """Build a MagicMock claim for resolution engine tests."""
    claim = MagicMock(spec=CustomerClaim)
    claim.id = claim_id or CLAIM_ID
    claim.org_id = org_id or ORG_ID
    claim.branch_id = BRANCH_ID
    claim.customer_id = CUSTOMER_ID
    claim.invoice_id = invoice_id
    claim.job_card_id = job_card_id
    claim.line_item_ids = []
    claim.claim_type = "warranty"
    claim.status = status
    claim.description = "Test claim for resolution engine"
    claim.resolution_type = None
    claim.resolution_amount = None
    claim.resolution_notes = None
    claim.resolved_at = None
    claim.resolved_by = None
    claim.refund_id = None
    claim.credit_note_id = None
    claim.return_movement_ids = []
    claim.warranty_job_id = None
    claim.cost_to_business = Decimal("0")
    claim.cost_breakdown = {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
    claim.created_by = USER_ID
    claim.created_at = datetime.now(timezone.utc)
    claim.updated_at = datetime.now(timezone.utc)
    return claim


def _make_invoice_mock(amount=Decimal("500.00")):
    inv = MagicMock()
    inv.id = INVOICE_ID
    inv.org_id = ORG_ID
    inv.amount_paid = amount
    inv.total = amount
    return inv


def _make_db_with_invoice(invoice_mock=None):
    db = AsyncMock()
    inv = invoice_mock or _make_invoice_mock()
    inv_result = MagicMock()
    inv_result.scalar_one_or_none.return_value = inv
    db.execute = AsyncMock(return_value=inv_result)
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Test: Full Refund Resolution
# ---------------------------------------------------------------------------


class TestFullRefundResolution:
    """Tests for _process_full_refund handler. Requirements: 3.2"""

    @pytest.mark.asyncio
    async def test_full_refund_calls_process_refund(self):
        """Full refund calls PaymentService.process_refund with full invoice amount."""
        claim = _make_claim()
        db = _make_db_with_invoice()

        refund_mock = MagicMock()
        refund_mock.id = uuid.uuid4()

        with patch(
            "app.modules.payments.service.process_refund",
            new_callable=AsyncMock,
            return_value={"refund": refund_mock},
        ) as mock_refund, patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.FULL_REFUND,
                user_id=USER_ID,
            )

        mock_refund.assert_called_once()
        assert result.resolution_type == "full_refund"
        assert result.refund_id == refund_mock.id
        assert claim.refund_id == refund_mock.id
        assert claim.status == ClaimStatus.RESOLVED.value

    @pytest.mark.asyncio
    async def test_full_refund_without_invoice_raises(self):
        """Full refund fails when claim has no linked invoice."""
        claim = _make_claim(invoice_id=None)
        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="Cannot process refund without a linked invoice"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.FULL_REFUND,
                    user_id=USER_ID,
                )

    @pytest.mark.asyncio
    async def test_full_refund_invoice_not_found_raises(self):
        """Full refund fails when linked invoice is not found in DB."""
        claim = _make_claim()
        db = AsyncMock()
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=inv_result)
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="Linked invoice not found"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.FULL_REFUND,
                    user_id=USER_ID,
                )


# ---------------------------------------------------------------------------
# Test: Partial Refund Resolution
# ---------------------------------------------------------------------------


class TestPartialRefundResolution:
    """Tests for _process_partial_refund handler. Requirements: 3.3"""

    @pytest.mark.asyncio
    async def test_partial_refund_calls_process_refund_with_amount(self):
        """Partial refund calls process_refund with the specified amount."""
        claim = _make_claim()
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        refund_mock = MagicMock()
        refund_mock.id = uuid.uuid4()

        with patch(
            "app.modules.payments.service.process_refund",
            new_callable=AsyncMock,
            return_value={"refund": refund_mock},
        ) as mock_refund, patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.PARTIAL_REFUND,
                resolution_amount=Decimal("150.00"),
                user_id=USER_ID,
            )

        mock_refund.assert_called_once()
        assert result.resolution_type == "partial_refund"
        assert result.refund_id == refund_mock.id
        assert claim.refund_id == refund_mock.id

    @pytest.mark.asyncio
    async def test_partial_refund_without_invoice_raises(self):
        """Partial refund fails when claim has no linked invoice."""
        claim = _make_claim(invoice_id=None)
        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="Cannot process refund without a linked invoice"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.PARTIAL_REFUND,
                    resolution_amount=Decimal("100.00"),
                    user_id=USER_ID,
                )

    @pytest.mark.asyncio
    async def test_partial_refund_without_amount_raises(self):
        """Partial refund fails when no resolution_amount is provided."""
        claim = _make_claim()
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="resolution_amount is required"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.PARTIAL_REFUND,
                    resolution_amount=None,
                    user_id=USER_ID,
                )


# ---------------------------------------------------------------------------
# Test: Credit Note Resolution
# ---------------------------------------------------------------------------


class TestCreditNoteResolution:
    """Tests for _process_credit_note handler. Requirements: 3.4"""

    @pytest.mark.asyncio
    async def test_credit_note_calls_create_credit_note(self):
        """Credit note resolution calls InvoiceService.create_credit_note."""
        claim = _make_claim()
        db = _make_db_with_invoice()

        cn_id = uuid.uuid4()

        with patch(
            "app.modules.invoices.service.create_credit_note",
            new_callable=AsyncMock,
            return_value={"credit_note": {"id": cn_id}},
        ) as mock_cn, patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.CREDIT_NOTE,
                user_id=USER_ID,
            )

        mock_cn.assert_called_once()
        assert result.resolution_type == "credit_note"
        assert result.credit_note_id == cn_id
        assert claim.credit_note_id == cn_id

    @pytest.mark.asyncio
    async def test_credit_note_without_invoice_raises(self):
        """Credit note fails when claim has no linked invoice."""
        claim = _make_claim(invoice_id=None)
        db = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="Cannot create credit note without a linked invoice"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.CREDIT_NOTE,
                    user_id=USER_ID,
                )


# ---------------------------------------------------------------------------
# Test: Exchange Resolution
# ---------------------------------------------------------------------------


class TestExchangeResolution:
    """Tests for _process_exchange handler. Requirements: 3.5, 4.1-4.5"""

    @pytest.mark.asyncio
    async def test_exchange_creates_stock_return_movement(self):
        """Exchange creates stock movement with correct movement_type and references."""
        claim = _make_claim()
        stock_item_id = uuid.uuid4()

        db = AsyncMock()
        # StockItem not found, Product found
        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = ORG_ID
        product_mock.is_active = True
        product_mock.sale_price = Decimal("80.00")
        product_mock.cost_price = Decimal("40.00")
        prod_result = MagicMock()
        prod_result.scalar_one_or_none.return_value = product_mock
        db.execute = AsyncMock(side_effect=[si_result, prod_result])
        db.flush = AsyncMock()

        movement_mock = MagicMock()
        movement_mock.id = uuid.uuid4()

        mock_stock_service = MagicMock()
        mock_stock_service.increment_stock = AsyncMock(return_value=movement_mock)

        with patch(
            "app.modules.stock.service.StockService",
            return_value=mock_stock_service,
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.EXCHANGE,
                return_stock_item_ids=[stock_item_id],
                user_id=USER_ID,
            )

        mock_stock_service.increment_stock.assert_called_once()
        call_kw = mock_stock_service.increment_stock.call_args[1]
        assert call_kw["movement_type"] == "return"
        assert call_kw["reference_type"] == "claim"
        assert call_kw["reference_id"] == claim.id
        assert result.resolution_type == "exchange"
        assert len(result.return_movement_ids) == 1

    @pytest.mark.asyncio
    async def test_exchange_archived_product_flagged_write_off(self):
        """Exchange with archived product flags movement as write-off."""
        claim = _make_claim()
        stock_item_id = uuid.uuid4()

        db = AsyncMock()
        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = ORG_ID
        product_mock.is_active = False  # Archived
        product_mock.sale_price = Decimal("0")
        product_mock.cost_price = Decimal("75.00")
        prod_result = MagicMock()
        prod_result.scalar_one_or_none.return_value = product_mock
        db.execute = AsyncMock(side_effect=[si_result, prod_result])
        db.flush = AsyncMock()

        movement_mock = MagicMock()
        movement_mock.id = uuid.uuid4()

        mock_stock_service = MagicMock()
        mock_stock_service.increment_stock = AsyncMock(return_value=movement_mock)

        with patch(
            "app.modules.stock.service.StockService",
            return_value=mock_stock_service,
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.EXCHANGE,
                return_stock_item_ids=[stock_item_id],
                user_id=USER_ID,
            )

        assert result.return_movement_ids[0]["is_write_off"] is True
        assert result.return_movement_ids[0]["write_off_amount"] == Decimal("75.00")
        assert result.write_off_cost == Decimal("75.00")

    @pytest.mark.asyncio
    async def test_exchange_zero_sale_price_flagged_write_off(self):
        """Exchange with zero sale_price flags movement as write-off."""
        claim = _make_claim()
        stock_item_id = uuid.uuid4()

        db = AsyncMock()
        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = ORG_ID
        product_mock.is_active = True
        product_mock.sale_price = Decimal("0")  # Zero resale
        product_mock.cost_price = Decimal("60.00")
        prod_result = MagicMock()
        prod_result.scalar_one_or_none.return_value = product_mock
        db.execute = AsyncMock(side_effect=[si_result, prod_result])
        db.flush = AsyncMock()

        movement_mock = MagicMock()
        movement_mock.id = uuid.uuid4()

        mock_stock_service = MagicMock()
        mock_stock_service.increment_stock = AsyncMock(return_value=movement_mock)

        with patch(
            "app.modules.stock.service.StockService",
            return_value=mock_stock_service,
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.EXCHANGE,
                return_stock_item_ids=[stock_item_id],
                user_id=USER_ID,
            )

        assert result.return_movement_ids[0]["is_write_off"] is True
        assert result.write_off_cost == Decimal("60.00")


# ---------------------------------------------------------------------------
# Test: Redo Service Resolution
# ---------------------------------------------------------------------------


class TestRedoServiceResolution:
    """Tests for _process_redo_service handler. Requirements: 3.6"""

    @pytest.mark.asyncio
    async def test_redo_service_creates_job_card(self):
        """Redo service creates a new job card with zero charge."""
        claim = _make_claim(job_card_id=JOB_CARD_ID)
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        new_job_id = uuid.uuid4()

        with patch(
            "app.modules.job_cards.service.create_job_card",
            new_callable=AsyncMock,
            return_value={"id": new_job_id},
        ) as mock_jc, patch(
            "app.modules.job_cards.service.get_job_card",
            new_callable=AsyncMock,
            return_value={"vehicle_rego": "ABC123", "description": "Original job"},
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.REDO_SERVICE,
                user_id=USER_ID,
            )

        mock_jc.assert_called_once()
        call_kw = mock_jc.call_args[1]
        assert call_kw["line_items_data"] == []  # Zero charge
        assert result.resolution_type == "redo_service"
        assert result.warranty_job_id == new_job_id
        assert claim.warranty_job_id == new_job_id

    @pytest.mark.asyncio
    async def test_redo_service_without_job_card_still_works(self):
        """Redo service works even without an original job card."""
        claim = _make_claim(job_card_id=None)
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        new_job_id = uuid.uuid4()

        with patch(
            "app.modules.job_cards.service.create_job_card",
            new_callable=AsyncMock,
            return_value={"id": new_job_id},
        ) as mock_jc, patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.REDO_SERVICE,
                user_id=USER_ID,
            )

        mock_jc.assert_called_once()
        assert result.warranty_job_id == new_job_id


# ---------------------------------------------------------------------------
# Test: No Action Resolution
# ---------------------------------------------------------------------------


class TestNoActionResolution:
    """Tests for _process_no_action handler. Requirements: 3.7"""

    @pytest.mark.asyncio
    async def test_no_action_triggers_no_downstream(self):
        """No action resolution creates no downstream entities."""
        claim = _make_claim()
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.NO_ACTION,
                user_id=USER_ID,
            )

        assert result.resolution_type == "no_action"
        assert result.refund_id is None
        assert result.credit_note_id is None
        assert result.return_movement_ids == []
        assert result.warranty_job_id is None
        assert claim.status == ClaimStatus.RESOLVED.value

    @pytest.mark.asyncio
    async def test_no_action_allowed_for_rejected_claim(self):
        """No action resolution is allowed for rejected claims."""
        claim = _make_claim(status="rejected")
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.NO_ACTION,
                user_id=USER_ID,
            )

        assert result.resolution_type == "no_action"
        assert claim.status == ClaimStatus.RESOLVED.value


# ---------------------------------------------------------------------------
# Test: Status Guard / Error Handling
# ---------------------------------------------------------------------------


class TestResolutionStatusGuard:
    """Tests for status validation in execute_resolution. Requirements: 2.4, 3.1"""

    @pytest.mark.asyncio
    async def test_non_approved_claim_raises_for_refund(self):
        """Resolution fails when claim is not in approved status."""
        for status in ["open", "investigating", "resolved"]:
            claim = _make_claim(status=status)
            db = AsyncMock()
            db.flush = AsyncMock()

            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="Claim must be in 'approved' status"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.FULL_REFUND,
                    user_id=USER_ID,
                )

    @pytest.mark.asyncio
    async def test_non_approved_non_rejected_claim_raises_for_no_action(self):
        """No action resolution fails when claim is not approved or rejected."""
        for status in ["open", "investigating", "resolved"]:
            claim = _make_claim(status=status)
            db = AsyncMock()
            db.flush = AsyncMock()

            engine = ResolutionEngine(db)
            with pytest.raises(ValueError, match="approved.*or.*rejected"):
                await engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.NO_ACTION,
                    user_id=USER_ID,
                )

    @pytest.mark.asyncio
    async def test_unknown_resolution_type_raises(self):
        """Unknown resolution type raises ValueError."""
        claim = _make_claim()
        db = AsyncMock()
        db.flush = AsyncMock()

        engine = ResolutionEngine(db)
        with pytest.raises(ValueError, match="Unknown resolution type"):
            await engine.execute_resolution(
                claim=claim,
                resolution_type="invalid_type",
                user_id=USER_ID,
            )


# ---------------------------------------------------------------------------
# Test: Claim fields updated after resolution
# ---------------------------------------------------------------------------


class TestClaimFieldsUpdatedAfterResolution:
    """Tests that claim fields are properly updated after resolution."""

    @pytest.mark.asyncio
    async def test_claim_status_set_to_resolved(self):
        """After resolution, claim.status is set to 'resolved'."""
        claim = _make_claim()
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.NO_ACTION,
                user_id=USER_ID,
            )

        assert claim.status == "resolved"
        assert claim.resolved_by == USER_ID
        assert claim.resolved_at is not None
        assert claim.resolution_type == "no_action"

    @pytest.mark.asyncio
    async def test_resolution_amount_stored_on_claim(self):
        """resolution_amount is stored on the claim when provided."""
        claim = _make_claim()
        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        refund_mock = MagicMock()
        refund_mock.id = uuid.uuid4()

        with patch(
            "app.modules.payments.service.process_refund",
            new_callable=AsyncMock,
            return_value={"refund": refund_mock},
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.PARTIAL_REFUND,
                resolution_amount=Decimal("123.45"),
                user_id=USER_ID,
            )

        assert claim.resolution_amount == Decimal("123.45")

    @pytest.mark.asyncio
    async def test_write_off_cost_updates_cost_breakdown(self):
        """Write-off cost is added to claim's cost_breakdown and cost_to_business."""
        claim = _make_claim()
        stock_item_id = uuid.uuid4()

        db = AsyncMock()
        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = ORG_ID
        product_mock.is_active = False  # Archived → write-off
        product_mock.sale_price = Decimal("0")
        product_mock.cost_price = Decimal("100.00")
        prod_result = MagicMock()
        prod_result.scalar_one_or_none.return_value = product_mock
        db.execute = AsyncMock(side_effect=[si_result, prod_result])
        db.flush = AsyncMock()

        movement_mock = MagicMock()
        movement_mock.id = uuid.uuid4()

        mock_stock_service = MagicMock()
        mock_stock_service.increment_stock = AsyncMock(return_value=movement_mock)

        with patch(
            "app.modules.stock.service.StockService",
            return_value=mock_stock_service,
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            await engine.execute_resolution(
                claim=claim,
                resolution_type=ResolutionType.EXCHANGE,
                return_stock_item_ids=[stock_item_id],
                user_id=USER_ID,
            )

        # cost_breakdown should have write_off_cost updated
        assert claim.cost_breakdown["write_off_cost"] == 100.0
        assert claim.cost_to_business == Decimal("100.00")
