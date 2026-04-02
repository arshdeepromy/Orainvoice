"""Unit tests for claims service — create_claim function.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8, 11.4, 12.1
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
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

from app.modules.claims.models import ClaimStatus, ClaimType
from app.modules.claims.service import create_claim
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.job_cards.models import JobCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CUSTOMER_ID = uuid.uuid4()
INVOICE_ID = uuid.uuid4()
JOB_CARD_ID = uuid.uuid4()
BRANCH_ID = uuid.uuid4()


def _make_customer(customer_id=CUSTOMER_ID, org_id=ORG_ID):
    c = MagicMock(spec=Customer)
    c.id = customer_id
    c.org_id = org_id
    return c


def _make_invoice(invoice_id=INVOICE_ID, org_id=ORG_ID, branch_id=None):
    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id
    inv.org_id = org_id
    inv.branch_id = branch_id
    return inv


def _make_job_card(job_card_id=JOB_CARD_ID, org_id=ORG_ID, branch_id=None):
    jc = MagicMock(spec=JobCard)
    jc.id = job_card_id
    jc.org_id = org_id
    jc.branch_id = branch_id
    return jc


def _mock_db_execute(customer=None, invoice=None, job_card=None):
    """Build a side_effect list for db.execute calls in create_claim."""
    results = []

    # 1st call: customer lookup
    cust_result = MagicMock()
    cust_result.scalar_one_or_none.return_value = customer
    results.append(cust_result)

    # 2nd call: invoice lookup (only if invoice_id provided)
    if invoice is not None or invoice == "missing":
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice if invoice != "missing" else None
        results.append(inv_result)

    # 3rd call: job_card lookup (only if job_card_id provided)
    if job_card is not None or job_card == "missing":
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card if job_card != "missing" else None
        results.append(jc_result)

    return results


def _make_db(execute_results):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateClaim:
    """Tests for create_claim function."""

    @pytest.mark.asyncio
    async def test_create_claim_with_invoice(self):
        """Valid claim creation with invoice_id sets status to open and records audit fields."""
        customer = _make_customer()
        invoice = _make_invoice()
        results = _mock_db_execute(customer=customer, invoice=invoice)
        db = _make_db(results)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.WARRANTY,
                description="Faulty part",
                invoice_id=INVOICE_ID,
            )

        assert result["status"] == "open"
        assert result["claim_type"] == "warranty"
        assert result["created_by"] == USER_ID
        assert result["created_at"] is not None
        assert result["customer_id"] == CUSTOMER_ID
        assert result["invoice_id"] == INVOICE_ID

    @pytest.mark.asyncio
    async def test_create_claim_with_job_card(self):
        """Valid claim creation with job_card_id."""
        customer = _make_customer()
        job_card = _make_job_card()
        results = _mock_db_execute(customer=customer, job_card=job_card)
        db = _make_db(results)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.SERVICE_REDO,
                description="Service not completed properly",
                job_card_id=JOB_CARD_ID,
            )

        assert result["status"] == "open"
        assert result["claim_type"] == "service_redo"
        assert result["job_card_id"] == JOB_CARD_ID

    @pytest.mark.asyncio
    async def test_customer_not_found_raises(self):
        """Claim creation fails when customer doesn't belong to org."""
        results = _mock_db_execute(customer=None)
        db = _make_db(results)

        with pytest.raises(ValueError, match="Customer not found"):
            await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=uuid.uuid4(),
                claim_type=ClaimType.DEFECT,
                description="Bad product",
                invoice_id=INVOICE_ID,
            )

    @pytest.mark.asyncio
    async def test_missing_source_reference_raises(self):
        """Claim creation fails when no source reference is provided."""
        customer = _make_customer()
        results = _mock_db_execute(customer=customer)
        db = _make_db(results)

        with pytest.raises(ValueError, match="At least one of"):
            await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.DEFECT,
                description="Bad product",
            )

    @pytest.mark.asyncio
    async def test_invoice_not_found_raises(self):
        """Claim creation fails when invoice doesn't exist in org."""
        customer = _make_customer()
        # Customer found, invoice not found
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = None
        db = _make_db([cust_result, inv_result])

        with pytest.raises(ValueError, match="Invoice not found"):
            await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.REFUND_REQUEST,
                description="Want refund",
                invoice_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_job_card_not_found_raises(self):
        """Claim creation fails when job card doesn't exist in org."""
        customer = _make_customer()
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = customer
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = None
        db = _make_db([cust_result, jc_result])

        with pytest.raises(ValueError, match="Job card not found"):
            await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.SERVICE_REDO,
                description="Bad service",
                job_card_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_branch_inherited_from_invoice(self):
        """Branch is inherited from linked invoice when not explicitly provided."""
        customer = _make_customer()
        invoice = _make_invoice(branch_id=BRANCH_ID)
        results = _mock_db_execute(customer=customer, invoice=invoice)
        db = _make_db(results)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.DEFECT,
                description="Defective part",
                invoice_id=INVOICE_ID,
            )

        assert result["branch_id"] == BRANCH_ID

    @pytest.mark.asyncio
    async def test_branch_inherited_from_job_card(self):
        """Branch is inherited from linked job card when not explicitly provided."""
        customer = _make_customer()
        job_card = _make_job_card(branch_id=BRANCH_ID)
        results = _mock_db_execute(customer=customer, job_card=job_card)
        db = _make_db(results)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.SERVICE_REDO,
                description="Redo needed",
                job_card_id=JOB_CARD_ID,
            )

        assert result["branch_id"] == BRANCH_ID

    @pytest.mark.asyncio
    async def test_explicit_branch_not_overridden(self):
        """Explicit branch_id is not overridden by invoice branch."""
        explicit_branch = uuid.uuid4()
        customer = _make_customer()
        invoice = _make_invoice(branch_id=BRANCH_ID)
        results = _mock_db_execute(customer=customer, invoice=invoice)
        db = _make_db(results)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.DEFECT,
                description="Defective part",
                invoice_id=INVOICE_ID,
                branch_id=explicit_branch,
            )

        assert result["branch_id"] == explicit_branch

    @pytest.mark.asyncio
    async def test_audit_log_written(self):
        """Audit log is written on claim creation."""
        customer = _make_customer()
        invoice = _make_invoice()
        results = _mock_db_execute(customer=customer, invoice=invoice)
        db = _make_db(results)

        with patch(
            "app.modules.claims.service.write_audit_log", new_callable=AsyncMock
        ) as mock_audit:
            await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.WARRANTY,
                description="Warranty claim",
                invoice_id=INVOICE_ID,
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "claim.created"
        assert call_kwargs["entity_type"] == "claim"
        assert call_kwargs["org_id"] == ORG_ID
        assert call_kwargs["user_id"] == USER_ID

    @pytest.mark.asyncio
    async def test_claim_action_record_created(self):
        """An initial ClaimAction record is created on claim creation."""
        customer = _make_customer()
        invoice = _make_invoice()
        results = _mock_db_execute(customer=customer, invoice=invoice)
        db = _make_db(results)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.WARRANTY,
                description="Warranty claim",
                invoice_id=INVOICE_ID,
            )

        # db.add is called twice: once for claim, once for action
        assert db.add.call_count == 2
        action_arg = db.add.call_args_list[1][0][0]
        assert action_arg.action_type == "status_change"
        assert action_arg.from_status is None
        assert action_arg.to_status == "open"
        assert action_arg.performed_by == USER_ID

    @pytest.mark.asyncio
    async def test_all_claim_types_accepted(self):
        """All valid claim types are accepted."""
        for ct in ClaimType:
            customer = _make_customer()
            invoice = _make_invoice()
            results = _mock_db_execute(customer=customer, invoice=invoice)
            db = _make_db(results)

            with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
                result = await create_claim(
                    db,
                    org_id=ORG_ID,
                    user_id=USER_ID,
                    customer_id=CUSTOMER_ID,
                    claim_type=ct,
                    description=f"Test {ct.value}",
                    invoice_id=INVOICE_ID,
                )

            assert result["claim_type"] == ct.value

    @pytest.mark.asyncio
    async def test_line_item_ids_stored(self):
        """Line item IDs are stored as strings in the claim."""
        customer = _make_customer()
        invoice = _make_invoice()
        results = _mock_db_execute(customer=customer, invoice=invoice)
        db = _make_db(results)
        line_ids = [uuid.uuid4(), uuid.uuid4()]

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await create_claim(
                db,
                org_id=ORG_ID,
                user_id=USER_ID,
                customer_id=CUSTOMER_ID,
                claim_type=ClaimType.DEFECT,
                description="Defective items",
                invoice_id=INVOICE_ID,
                line_item_ids=line_ids,
            )

        assert len(result["line_item_ids"]) == 2
        assert result["line_item_ids"] == [str(lid) for lid in line_ids]


# ---------------------------------------------------------------------------
# Imports for additional service functions
# ---------------------------------------------------------------------------
from app.modules.claims.service import (
    update_claim_status,
    list_claims,
    get_customer_claims_summary,
)
from app.modules.claims.models import CustomerClaim, VALID_CLAIM_TRANSITIONS
from decimal import Decimal


# ---------------------------------------------------------------------------
# Helpers for update_claim_status tests
# ---------------------------------------------------------------------------

def _make_claim_obj(
    claim_id=None,
    org_id=ORG_ID,
    branch_id=None,
    customer_id=CUSTOMER_ID,
    invoice_id=INVOICE_ID,
    job_card_id=None,
    status="open",
    claim_type="warranty",
    description="Test claim",
    cost_to_business=Decimal("0"),
    cost_breakdown=None,
):
    """Build a MagicMock that behaves like a CustomerClaim row."""
    claim = MagicMock(spec=CustomerClaim)
    claim.id = claim_id or uuid.uuid4()
    claim.org_id = org_id
    claim.branch_id = branch_id
    claim.customer_id = customer_id
    claim.invoice_id = invoice_id
    claim.job_card_id = job_card_id
    claim.line_item_ids = []
    claim.claim_type = claim_type
    claim.status = status
    claim.description = description
    claim.resolution_type = None
    claim.resolution_amount = None
    claim.resolution_notes = None
    claim.resolved_at = None
    claim.resolved_by = None
    claim.cost_to_business = cost_to_business
    claim.cost_breakdown = cost_breakdown or {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
    claim.created_by = USER_ID
    claim.created_at = datetime.now(timezone.utc)
    claim.updated_at = datetime.now(timezone.utc)
    return claim


# ---------------------------------------------------------------------------
# TestUpdateClaimStatus
# ---------------------------------------------------------------------------


class TestUpdateClaimStatus:
    """Tests for update_claim_status — valid and invalid transitions.

    Requirements: 2.1, 2.2, 2.3, 2.6, 2.7
    """

    # --- Valid transitions ---

    @pytest.mark.asyncio
    async def test_open_to_investigating(self):
        claim = _make_claim_obj(status="open")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.INVESTIGATING,
            )

        assert claim.status == "investigating"
        assert result["status"] == "investigating"

    @pytest.mark.asyncio
    async def test_investigating_to_approved(self):
        claim = _make_claim_obj(status="investigating")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.APPROVED,
            )

        assert claim.status == "approved"
        assert result["status"] == "approved"

    @pytest.mark.asyncio
    async def test_investigating_to_rejected(self):
        claim = _make_claim_obj(status="investigating")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.REJECTED,
            )

        assert claim.status == "rejected"
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_approved_to_resolved(self):
        claim = _make_claim_obj(status="approved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.RESOLVED,
            )

        assert claim.status == "resolved"
        assert result["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_rejected_to_resolved(self):
        claim = _make_claim_obj(status="rejected")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.RESOLVED,
            )

        assert claim.status == "resolved"
        assert result["status"] == "resolved"

    # --- Invalid transitions ---

    @pytest.mark.asyncio
    async def test_open_to_approved_invalid(self):
        claim = _make_claim_obj(status="open")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.APPROVED,
            )

    @pytest.mark.asyncio
    async def test_open_to_rejected_invalid(self):
        claim = _make_claim_obj(status="open")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.REJECTED,
            )

    @pytest.mark.asyncio
    async def test_open_to_resolved_invalid(self):
        claim = _make_claim_obj(status="open")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.RESOLVED,
            )

    @pytest.mark.asyncio
    async def test_investigating_to_open_invalid(self):
        claim = _make_claim_obj(status="investigating")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.OPEN,
            )

    @pytest.mark.asyncio
    async def test_approved_to_open_invalid(self):
        claim = _make_claim_obj(status="approved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.OPEN,
            )

    @pytest.mark.asyncio
    async def test_approved_to_investigating_invalid(self):
        claim = _make_claim_obj(status="approved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.INVESTIGATING,
            )

    @pytest.mark.asyncio
    async def test_resolved_to_open_invalid(self):
        claim = _make_claim_obj(status="resolved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.OPEN,
            )

    @pytest.mark.asyncio
    async def test_resolved_to_investigating_invalid(self):
        claim = _make_claim_obj(status="resolved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.INVESTIGATING,
            )

    @pytest.mark.asyncio
    async def test_resolved_to_approved_invalid(self):
        claim = _make_claim_obj(status="resolved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.APPROVED,
            )

    @pytest.mark.asyncio
    async def test_resolved_to_rejected_invalid(self):
        claim = _make_claim_obj(status="resolved")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Cannot transition"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.REJECTED,
            )

    # --- Claim not found ---

    @pytest.mark.asyncio
    async def test_claim_not_found_raises(self):
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValueError, match="Claim not found"):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=uuid.uuid4(), new_status=ClaimStatus.INVESTIGATING,
            )

    # --- Audit and action records ---

    @pytest.mark.asyncio
    async def test_claim_action_recorded_on_transition(self):
        """ClaimAction record is created with correct from/to status."""
        claim = _make_claim_obj(status="open")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.INVESTIGATING,
            )

        db.add.assert_called_once()
        action_arg = db.add.call_args[0][0]
        assert action_arg.action_type == "status_change"
        assert action_arg.from_status == "open"
        assert action_arg.to_status == "investigating"
        assert action_arg.performed_by == USER_ID

    @pytest.mark.asyncio
    async def test_audit_log_written_on_transition(self):
        """Audit log is written with correct before/after values."""
        claim = _make_claim_obj(status="investigating")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.service.write_audit_log", new_callable=AsyncMock
        ) as mock_audit:
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.APPROVED,
            )

        mock_audit.assert_called_once()
        kw = mock_audit.call_args.kwargs
        assert kw["action"] == "claim.status_changed"
        assert kw["before_value"] == {"status": "investigating"}
        assert kw["after_value"] == {"status": "approved"}

    @pytest.mark.asyncio
    async def test_notes_stored_on_transition(self):
        """Notes are passed through to the ClaimAction record."""
        claim = _make_claim_obj(status="open")
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            await update_claim_status(
                db, org_id=ORG_ID, user_id=USER_ID,
                claim_id=claim.id, new_status=ClaimStatus.INVESTIGATING,
                notes="Starting investigation",
            )

        action_arg = db.add.call_args[0][0]
        assert action_arg.notes == "Starting investigation"


# ---------------------------------------------------------------------------
# TestListClaims
# ---------------------------------------------------------------------------


class TestListClaims:
    """Tests for list_claims — listing, pagination, filtering.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """

    def _build_claim_row(self, **overrides):
        """Build a mock CustomerClaim row for list results."""
        defaults = dict(
            id=uuid.uuid4(),
            customer_id=CUSTOMER_ID,
            claim_type="warranty",
            status="open",
            description="Test claim",
            cost_to_business=Decimal("0"),
            branch_id=None,
            created_at=datetime.now(timezone.utc),
            customer=None,
        )
        defaults.update(overrides)
        row = MagicMock(spec=CustomerClaim)
        for k, v in defaults.items():
            setattr(row, k, v)
        return row

    def _mock_list_db(self, claims, total):
        """Build an AsyncMock db that returns count then items for list_claims."""
        db = AsyncMock()

        # list_claims does: count query, then items query
        count_result = MagicMock()
        count_result.scalar.return_value = total

        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = claims

        db.execute = AsyncMock(side_effect=[count_result, items_result])
        return db

    @pytest.mark.asyncio
    async def test_basic_listing(self):
        """Returns items and total count."""
        claims = [self._build_claim_row() for _ in range(3)]
        db = self._mock_list_db(claims, total=3)

        result = await list_claims(db, org_id=ORG_ID)

        assert result["total"] == 3
        assert len(result["items"]) == 3

    @pytest.mark.asyncio
    async def test_empty_listing(self):
        """Returns empty list when no claims exist."""
        db = self._mock_list_db([], total=0)

        result = await list_claims(db, org_id=ORG_ID)

        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_pagination_limit(self):
        """Respects limit parameter."""
        claims = [self._build_claim_row() for _ in range(2)]
        db = self._mock_list_db(claims, total=10)

        result = await list_claims(db, org_id=ORG_ID, limit=2, offset=0)

        assert result["total"] == 10
        assert len(result["items"]) == 2

    @pytest.mark.asyncio
    async def test_pagination_offset(self):
        """Respects offset parameter."""
        claims = [self._build_claim_row()]
        db = self._mock_list_db(claims, total=5)

        result = await list_claims(db, org_id=ORG_ID, limit=1, offset=4)

        assert result["total"] == 5
        assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_filter_by_status(self):
        """Passes status filter through to query."""
        claims = [self._build_claim_row(status="investigating")]
        db = self._mock_list_db(claims, total=1)

        result = await list_claims(db, org_id=ORG_ID, status="investigating")

        assert result["total"] == 1
        assert result["items"][0]["status"] == "investigating"

    @pytest.mark.asyncio
    async def test_filter_by_claim_type(self):
        """Passes claim_type filter through to query."""
        claims = [self._build_claim_row(claim_type="defect")]
        db = self._mock_list_db(claims, total=1)

        result = await list_claims(db, org_id=ORG_ID, claim_type="defect")

        assert result["total"] == 1
        assert result["items"][0]["claim_type"] == "defect"

    @pytest.mark.asyncio
    async def test_filter_by_customer_id(self):
        """Passes customer_id filter through to query."""
        cid = uuid.uuid4()
        claims = [self._build_claim_row(customer_id=cid)]
        db = self._mock_list_db(claims, total=1)

        result = await list_claims(db, org_id=ORG_ID, customer_id=cid)

        assert result["total"] == 1
        assert result["items"][0]["customer_id"] == cid

    @pytest.mark.asyncio
    async def test_filter_by_branch_id(self):
        """Passes branch_id filter through to query."""
        bid = uuid.uuid4()
        claims = [self._build_claim_row(branch_id=bid)]
        db = self._mock_list_db(claims, total=1)

        result = await list_claims(db, org_id=ORG_ID, branch_id=bid)

        assert result["total"] == 1
        assert result["items"][0]["branch_id"] == bid

    @pytest.mark.asyncio
    async def test_item_shape(self):
        """Each item has the expected keys."""
        claims = [self._build_claim_row()]
        db = self._mock_list_db(claims, total=1)

        result = await list_claims(db, org_id=ORG_ID)

        item = result["items"][0]
        expected_keys = {
            "id", "customer_id", "customer_name", "claim_type",
            "status", "description", "cost_to_business", "branch_id", "created_at",
        }
        assert set(item.keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_customer_name_populated(self):
        """Customer name is built from first_name + last_name."""
        customer = MagicMock()
        customer.first_name = "Jane"
        customer.last_name = "Doe"
        claims = [self._build_claim_row(customer=customer)]
        db = self._mock_list_db(claims, total=1)

        result = await list_claims(db, org_id=ORG_ID)

        assert result["items"][0]["customer_name"] == "Jane Doe"


# ---------------------------------------------------------------------------
# TestGetCustomerClaimsSummary
# ---------------------------------------------------------------------------


class TestGetCustomerClaimsSummary:
    """Tests for get_customer_claims_summary — summary with mixed statuses and costs.

    Requirements: 9.1, 9.2, 9.3
    """

    def _build_claim_row(self, **overrides):
        defaults = dict(
            id=uuid.uuid4(),
            customer_id=CUSTOMER_ID,
            claim_type="warranty",
            status="open",
            description="Test claim",
            cost_to_business=Decimal("0"),
            branch_id=None,
            created_at=datetime.now(timezone.utc),
        )
        defaults.update(overrides)
        row = MagicMock(spec=CustomerClaim)
        for k, v in defaults.items():
            setattr(row, k, v)
        return row

    def _mock_summary_db(self, claims):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = claims
        db.execute = AsyncMock(return_value=result_mock)
        return db

    @pytest.mark.asyncio
    async def test_empty_summary(self):
        """No claims returns zero counts."""
        db = self._mock_summary_db([])

        result = await get_customer_claims_summary(
            db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
        )

        assert result["total_claims"] == 0
        assert result["open_claims"] == 0
        assert result["total_cost_to_business"] == Decimal("0")
        assert result["claims"] == []

    @pytest.mark.asyncio
    async def test_mixed_statuses_counted(self):
        """Open claims are counted separately from total."""
        claims = [
            self._build_claim_row(status="open"),
            self._build_claim_row(status="open"),
            self._build_claim_row(status="investigating"),
            self._build_claim_row(status="resolved"),
        ]
        db = self._mock_summary_db(claims)

        result = await get_customer_claims_summary(
            db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
        )

        assert result["total_claims"] == 4
        assert result["open_claims"] == 2

    @pytest.mark.asyncio
    async def test_total_cost_summed(self):
        """total_cost_to_business sums across all claims."""
        claims = [
            self._build_claim_row(cost_to_business=Decimal("100.50")),
            self._build_claim_row(cost_to_business=Decimal("250.00")),
            self._build_claim_row(cost_to_business=Decimal("0")),
        ]
        db = self._mock_summary_db(claims)

        result = await get_customer_claims_summary(
            db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
        )

        assert result["total_cost_to_business"] == Decimal("350.50")

    @pytest.mark.asyncio
    async def test_claims_list_returned(self):
        """All claims are returned in the claims list."""
        claims = [
            self._build_claim_row(status="open", claim_type="defect"),
            self._build_claim_row(status="resolved", claim_type="warranty"),
        ]
        db = self._mock_summary_db(claims)

        result = await get_customer_claims_summary(
            db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
        )

        assert len(result["claims"]) == 2
        types = {c["claim_type"] for c in result["claims"]}
        assert types == {"defect", "warranty"}

    @pytest.mark.asyncio
    async def test_claim_item_shape(self):
        """Each claim item has the expected keys."""
        claims = [self._build_claim_row()]
        db = self._mock_summary_db(claims)

        result = await get_customer_claims_summary(
            db, org_id=ORG_ID, customer_id=CUSTOMER_ID,
        )

        item = result["claims"][0]
        expected_keys = {
            "id", "customer_id", "customer_name", "claim_type",
            "status", "description", "cost_to_business", "branch_id", "created_at",
        }
        assert set(item.keys()) == expected_keys
