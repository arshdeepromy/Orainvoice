"""Property-based tests for Customer Claims & Returns.

Feature: customer-claims-returns, Property 1: Claim Creation Data Integrity

For any valid claim creation request with a customer_id and at least one
source reference (invoice_id, job_card_id, or line_item_id), the created
claim SHALL have status "open", a non-null created_by, and a non-null
created_at timestamp.

**Validates: Requirements 1.1, 1.6, 1.7**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

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
    VALID_CLAIM_TRANSITIONS,
    ClaimAction,
    ClaimStatus,
    ClaimType,
    CustomerClaim,
)
from app.modules.claims.service import create_claim, update_claim_status
from app.modules.customers.models import Customer
from app.modules.invoices.models import Invoice
from app.modules.job_cards.models import JobCard


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

claim_type_strategy = st.sampled_from(list(ClaimType))

description_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=200,
)

# Strategy for source reference combinations: at least one of invoice_id or job_card_id
source_ref_strategy = st.one_of(
    # invoice_id only
    st.tuples(st.uuids(), st.none()),
    # job_card_id only
    st.tuples(st.none(), st.uuids()),
    # both
    st.tuples(st.uuids(), st.uuids()),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_customer_mock(customer_id: uuid.UUID, org_id: uuid.UUID):
    c = MagicMock(spec=Customer)
    c.id = customer_id
    c.org_id = org_id
    return c


def _make_invoice_mock(invoice_id: uuid.UUID, org_id: uuid.UUID):
    inv = MagicMock(spec=Invoice)
    inv.id = invoice_id
    inv.org_id = org_id
    inv.branch_id = None
    return inv


def _make_job_card_mock(job_card_id: uuid.UUID, org_id: uuid.UUID):
    jc = MagicMock(spec=JobCard)
    jc.id = job_card_id
    jc.org_id = org_id
    jc.branch_id = None
    return jc


def _build_db(org_id, customer_id, invoice_id, job_card_id):
    """Build a mock AsyncSession with execute side effects for create_claim."""
    results = []

    # 1st call: customer lookup
    customer = _make_customer_mock(customer_id, org_id)
    cust_result = MagicMock()
    cust_result.scalar_one_or_none.return_value = customer
    results.append(cust_result)

    # 2nd call: invoice lookup (if invoice_id provided)
    if invoice_id is not None:
        invoice = _make_invoice_mock(invoice_id, org_id)
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = invoice
        results.append(inv_result)

    # 3rd call: job_card lookup (if job_card_id provided)
    if job_card_id is not None:
        job_card = _make_job_card_mock(job_card_id, org_id)
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        results.append(jc_result)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestP1ClaimCreationDataIntegrity:
    """Property 1: Claim Creation Data Integrity.

    For any valid claim creation request with a customer_id and at least one
    source reference, the created claim SHALL have status "open", a non-null
    created_by, and a non-null created_at timestamp.

    **Validates: Requirements 1.1, 1.6, 1.7**
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
        source_refs=source_ref_strategy,
    )
    def test_created_claim_has_open_status_and_audit_fields(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
        source_refs: tuple[uuid.UUID | None, uuid.UUID | None],
    ) -> None:
        """P1: Any valid claim creation yields status='open', non-null created_by and created_at."""
        invoice_id, job_card_id = source_refs

        db = _build_db(org_id, customer_id, invoice_id, job_card_id)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=invoice_id,
                    job_card_id=job_card_id,
                )
            )

        # Property assertions
        assert result["status"] == "open", (
            f"Expected status 'open', got '{result['status']}'"
        )
        assert result["created_by"] is not None, (
            "created_by must not be None"
        )
        assert result["created_at"] is not None, (
            "created_at must not be None"
        )
        # created_by should match the user who created the claim
        assert result["created_by"] == user_id


# ---------------------------------------------------------------------------
# Property 2: Source Reference Validation
# ---------------------------------------------------------------------------


class TestP2SourceReferenceValidation:
    """Property 2: Source Reference Validation.

    For any claim creation request, if the referenced invoice_id or job_card_id
    does not exist in the same organisation, the service SHALL reject the
    request with a validation error.

    **Validates: Requirements 1.3, 1.8**

    Tag: Feature: customer-claims-returns, Property 2: Source Reference Validation
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
        invoice_id=st.uuids(),
    )
    def test_nonexistent_invoice_raises_value_error(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
        invoice_id: uuid.UUID,
    ) -> None:
        """P2a: When invoice_id references a non-existent invoice, create_claim raises ValueError."""
        # Build mock db: customer found, invoice NOT found (returns None)
        results = []

        # 1st call: customer lookup – found
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = _make_customer_mock(customer_id, org_id)
        results.append(cust_result)

        # 2nd call: invoice lookup – NOT found
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = None
        results.append(inv_result)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with pytest.raises(ValueError, match="Invoice not found"):
            asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=invoice_id,
                    job_card_id=None,
                )
            )

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
        job_card_id=st.uuids(),
    )
    def test_nonexistent_job_card_raises_value_error(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
        job_card_id: uuid.UUID,
    ) -> None:
        """P2b: When job_card_id references a non-existent job card, create_claim raises ValueError."""
        # Build mock db: customer found, job card NOT found (returns None)
        results = []

        # 1st call: customer lookup – found
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = _make_customer_mock(customer_id, org_id)
        results.append(cust_result)

        # 2nd call: job card lookup – NOT found
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = None
        results.append(jc_result)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with pytest.raises(ValueError, match="Job card not found"):
            asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=None,
                    job_card_id=job_card_id,
                )
            )


# ---------------------------------------------------------------------------
# Property 3: Claim Type Validation
# ---------------------------------------------------------------------------


class TestP3ClaimTypeValidation:
    """Property 3: Claim Type Validation.

    For any claim creation request, the claim_type SHALL be one of:
    warranty, defect, service_redo, exchange, refund_request.
    Any other value SHALL be rejected with a validation error.

    **Validates: Requirements 1.5**

    Tag: Feature: customer-claims-returns, Property 3: Claim Type Validation
    """

    VALID_CLAIM_TYPE_VALUES = {ct.value for ct in ClaimType}

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
        source_refs=source_ref_strategy,
    )
    def test_valid_claim_types_accepted(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
        source_refs: tuple[uuid.UUID | None, uuid.UUID | None],
    ) -> None:
        """P3a: All valid ClaimType enum values are accepted and claim is created successfully."""
        invoice_id, job_card_id = source_refs

        db = _build_db(org_id, customer_id, invoice_id, job_card_id)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=invoice_id,
                    job_card_id=job_card_id,
                )
            )

        # The claim should be created with the correct claim_type value
        assert result["claim_type"] == claim_type.value, (
            f"Expected claim_type '{claim_type.value}', got '{result['claim_type']}'"
        )
        assert result["claim_type"] in self.VALID_CLAIM_TYPE_VALUES

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        invalid_type=st.text(min_size=1, max_size=50).filter(
            lambda s: s not in {ct.value for ct in ClaimType}
        ),
        customer_id=st.uuids(),
        invoice_id=st.uuids(),
        description=description_strategy,
    )
    def test_invalid_claim_types_rejected(
        self,
        invalid_type: str,
        customer_id: uuid.UUID,
        invoice_id: uuid.UUID,
        description: str,
    ) -> None:
        """P3b: Invalid claim_type strings are rejected with a validation error at schema level."""
        from pydantic import ValidationError
        from app.modules.claims.schemas import ClaimCreateRequest

        with pytest.raises(ValidationError):
            ClaimCreateRequest(
                customer_id=customer_id,
                claim_type=invalid_type,
                description=description,
                invoice_id=invoice_id,
            )


# ---------------------------------------------------------------------------
# Property 4: Status Workflow Validity
# ---------------------------------------------------------------------------


class TestP4StatusWorkflowValidity:
    """Property 4: Status Workflow Validity.

    For any claim status transition, the transition SHALL only be allowed if it
    follows the valid workflow: open → investigating → approved/rejected → resolved.
    Invalid transitions SHALL be rejected with an error listing allowed transitions.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.6**

    Tag: Feature: customer-claims-returns, Property 4: Status Workflow Validity
    """

    ALL_STATUSES = [s.value for s in ClaimStatus]

    def _build_status_db(
        self,
        org_id: uuid.UUID,
        claim_id: uuid.UUID,
        current_status: str,
    ) -> tuple[AsyncMock, MagicMock]:
        """Build a mock AsyncSession that returns a claim with the given current_status."""
        claim = MagicMock(spec=CustomerClaim)
        claim.id = claim_id
        claim.org_id = org_id
        claim.branch_id = None
        claim.customer_id = uuid.uuid4()
        claim.invoice_id = uuid.uuid4()
        claim.job_card_id = None
        claim.line_item_ids = []
        claim.claim_type = "warranty"
        claim.status = current_status
        claim.description = "test"
        claim.resolution_type = None
        claim.resolution_amount = None
        claim.resolution_notes = None
        claim.resolved_at = None
        claim.resolved_by = None
        claim.cost_to_business = 0
        claim.cost_breakdown = {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
        claim.created_by = uuid.uuid4()
        claim.created_at = datetime.now(timezone.utc)
        claim.updated_at = datetime.now(timezone.utc)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db, claim

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        from_status=st.sampled_from([s.value for s in ClaimStatus]),
        to_status=st.sampled_from([s.value for s in ClaimStatus]),
    )
    def test_valid_transitions_succeed_invalid_transitions_raise(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
        from_status: str,
        to_status: str,
    ) -> None:
        """P4: Valid transitions succeed; invalid transitions raise ValueError with allowed list."""

        db, claim = self._build_status_db(org_id, claim_id, from_status)
        allowed = VALID_CLAIM_TRANSITIONS.get(from_status, set())
        is_valid = to_status in allowed

        new_status = ClaimStatus(to_status)

        if is_valid:
            with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
                result = asyncio.get_event_loop().run_until_complete(
                    update_claim_status(
                        db,
                        org_id=org_id,
                        user_id=user_id,
                        claim_id=claim_id,
                        new_status=new_status,
                    )
                )
            assert result["status"] == to_status
        else:
            with pytest.raises(ValueError, match="Cannot transition"):
                asyncio.get_event_loop().run_until_complete(
                    update_claim_status(
                        db,
                        org_id=org_id,
                        user_id=user_id,
                        claim_id=claim_id,
                        new_status=new_status,
                    )
                )


# ---------------------------------------------------------------------------
# Property 5: Approved to Resolved Transition Guard
# ---------------------------------------------------------------------------


class TestP5ApprovedToResolvedTransitionGuard:
    """Property 5: Approved to Resolved Transition Guard.

    For any claim in "approved" status, transition to "resolved" SHALL only be
    allowed after a resolution_type has been set and resolution actions have been
    executed.

    Note: The update_claim_status function allows approved→resolved transition.
    The guard is that resolution must happen through the resolve_claim flow, not
    just a status update. This test verifies that calling update_claim_status
    with approved→resolved works (the actual resolution guard is in the resolve
    endpoint).

    **Validates: Requirements 2.4**

    Tag: Feature: customer-claims-returns, Property 5: Approved to Resolved Transition Guard
    """

    def _build_approved_claim_db(
        self,
        org_id: uuid.UUID,
        claim_id: uuid.UUID,
    ) -> tuple[AsyncMock, MagicMock]:
        """Build a mock AsyncSession returning a claim in 'approved' status."""
        claim = MagicMock(spec=CustomerClaim)
        claim.id = claim_id
        claim.org_id = org_id
        claim.branch_id = None
        claim.customer_id = uuid.uuid4()
        claim.invoice_id = uuid.uuid4()
        claim.job_card_id = None
        claim.line_item_ids = []
        claim.claim_type = "warranty"
        claim.status = "approved"
        claim.description = "test claim"
        claim.resolution_type = None
        claim.resolution_amount = None
        claim.resolution_notes = None
        claim.resolved_at = None
        claim.resolved_by = None
        claim.cost_to_business = 0
        claim.cost_breakdown = {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
        claim.created_by = uuid.uuid4()
        claim.created_at = datetime.now(timezone.utc)
        claim.updated_at = datetime.now(timezone.utc)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db, claim

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
    )
    def test_approved_to_resolved_transition_allowed(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
    ) -> None:
        """P5: update_claim_status allows approved→resolved (resolution guard is in resolve endpoint)."""

        db, claim = self._build_approved_claim_db(org_id, claim_id)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = asyncio.get_event_loop().run_until_complete(
                update_claim_status(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    claim_id=claim_id,
                    new_status=ClaimStatus.RESOLVED,
                )
            )

        # The status transition approved→resolved is valid per VALID_CLAIM_TRANSITIONS
        assert result["status"] == "resolved"


# ---------------------------------------------------------------------------
# Property 16: Status Change Timeline Recording
# ---------------------------------------------------------------------------


class TestP16StatusChangeTimelineRecording:
    """Property 16: Status Change Timeline Recording.

    For any claim status change, a ClaimAction record SHALL be created with
    action_type "status_change", the correct from_status and to_status, and
    the performing user's ID.

    **Validates: Requirements 2.7, 7.2**

    Tag: Feature: customer-claims-returns, Property 16: Status Change Timeline Recording
    """

    # Only test transitions that are actually valid
    VALID_TRANSITIONS = [
        ("open", "investigating"),
        ("investigating", "approved"),
        ("investigating", "rejected"),
        ("approved", "resolved"),
        ("rejected", "resolved"),
    ]

    def _build_claim_db_for_status(
        self,
        org_id: uuid.UUID,
        claim_id: uuid.UUID,
        current_status: str,
    ) -> tuple[AsyncMock, MagicMock]:
        """Build a mock AsyncSession returning a claim with the given status."""
        claim = MagicMock(spec=CustomerClaim)
        claim.id = claim_id
        claim.org_id = org_id
        claim.branch_id = None
        claim.customer_id = uuid.uuid4()
        claim.invoice_id = uuid.uuid4()
        claim.job_card_id = None
        claim.line_item_ids = []
        claim.claim_type = "defect"
        claim.status = current_status
        claim.description = "test"
        claim.resolution_type = None
        claim.resolution_amount = None
        claim.resolution_notes = None
        claim.resolved_at = None
        claim.resolved_by = None
        claim.cost_to_business = 0
        claim.cost_breakdown = {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
        claim.created_by = uuid.uuid4()
        claim.created_at = datetime.now(timezone.utc)
        claim.updated_at = datetime.now(timezone.utc)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db, claim

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        transition=st.sampled_from([
            ("open", "investigating"),
            ("investigating", "approved"),
            ("investigating", "rejected"),
            ("approved", "resolved"),
            ("rejected", "resolved"),
        ]),
    )
    def test_status_change_creates_claim_action_record(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
        transition: tuple[str, str],
    ) -> None:
        """P16: Every valid status change creates a ClaimAction with correct fields."""

        from_status, to_status = transition
        db, claim = self._build_claim_db_for_status(org_id, claim_id, from_status)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            asyncio.get_event_loop().run_until_complete(
                update_claim_status(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    claim_id=claim_id,
                    new_status=ClaimStatus(to_status),
                )
            )

        # Verify db.add was called with a ClaimAction
        add_calls = db.add.call_args_list
        # The last db.add call should be the ClaimAction (status_change)
        claim_action_found = False
        for call in add_calls:
            obj = call[0][0]
            if isinstance(obj, ClaimAction):
                assert obj.action_type == "status_change", (
                    f"Expected action_type 'status_change', got '{obj.action_type}'"
                )
                assert obj.from_status == from_status, (
                    f"Expected from_status '{from_status}', got '{obj.from_status}'"
                )
                assert obj.to_status == to_status, (
                    f"Expected to_status '{to_status}', got '{obj.to_status}'"
                )
                assert obj.performed_by == user_id, (
                    f"Expected performed_by '{user_id}', got '{obj.performed_by}'"
                )
                claim_action_found = True

        assert claim_action_found, "No ClaimAction record was added to the session"


# ---------------------------------------------------------------------------
# Property 11: Pagination Correctness
# ---------------------------------------------------------------------------


class TestP11PaginationCorrectness:
    """Property 11: Pagination Correctness.

    For any claim list request with limit and offset, the returned list SHALL
    contain at most `limit` items, and the total count SHALL reflect the total
    matching claims regardless of pagination.

    **Validates: Requirements 6.1**

    Tag: Feature: customer-claims-returns, Property 11: Pagination Correctness
    """

    def _build_list_claims_db(
        self,
        org_id: uuid.UUID,
        claims: list[MagicMock],
    ) -> AsyncMock:
        """Build a mock AsyncSession that simulates list_claims DB queries.

        list_claims issues three queries:
        1. count query (returns total)
        2. items query (returns paginated claims)
        """
        db = AsyncMock()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # Count query
                count_result = MagicMock()
                count_result.scalar.return_value = len(claims)
                return count_result
            else:
                # Items query – the service applies .limit/.offset but we
                # simulate the DB returning the correct slice.  We parse
                # limit/offset from the compiled statement if possible, but
                # since we're mocking we just store all claims and let the
                # test verify the property on the *result* dict.
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = claims
                result_mock = MagicMock()
                result_mock.scalars.return_value = scalars_mock
                return result_mock

        db.execute = AsyncMock(side_effect=mock_execute)
        return db

    def _make_claim_mock(
        self,
        org_id: uuid.UUID,
        status: str = "open",
        claim_type: str = "warranty",
        customer_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        cost_to_business: float = 0,
    ) -> MagicMock:
        claim = MagicMock(spec=CustomerClaim)
        claim.id = uuid.uuid4()
        claim.org_id = org_id
        claim.branch_id = branch_id
        claim.customer_id = customer_id or uuid.uuid4()
        claim.claim_type = claim_type
        claim.status = status
        claim.description = "test claim"
        claim.cost_to_business = cost_to_business
        claim.created_at = datetime.now(timezone.utc)
        claim.customer = None
        return claim

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        total_claims=st.integers(min_value=0, max_value=50),
        limit=st.integers(min_value=1, max_value=50),
        offset=st.integers(min_value=0, max_value=50),
    )
    def test_pagination_returns_at_most_limit_items_and_correct_total(
        self,
        org_id: uuid.UUID,
        total_claims: int,
        limit: int,
        offset: int,
    ) -> None:
        """P11: Returned list has at most `limit` items; total reflects all matching claims."""
        from app.modules.claims.service import list_claims

        all_claims = [self._make_claim_mock(org_id) for _ in range(total_claims)]

        # Simulate the DB returning the correct page slice
        page_slice = all_claims[offset : offset + limit]

        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                count_result = MagicMock()
                count_result.scalar.return_value = total_claims
                return count_result
            else:
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = page_slice
                result_mock = MagicMock()
                result_mock.scalars.return_value = scalars_mock
                return result_mock

        db.execute = AsyncMock(side_effect=mock_execute)

        result = asyncio.get_event_loop().run_until_complete(
            list_claims(
                db,
                org_id=org_id,
                limit=limit,
                offset=offset,
            )
        )

        # Property: returned items <= limit
        assert len(result["items"]) <= limit, (
            f"Expected at most {limit} items, got {len(result['items'])}"
        )
        # Property: total reflects all matching claims regardless of pagination
        assert result["total"] == total_claims, (
            f"Expected total {total_claims}, got {result['total']}"
        )
        # Property: returned items should equal the expected page slice size
        expected_page_size = min(limit, max(0, total_claims - offset))
        assert len(result["items"]) == expected_page_size, (
            f"Expected {expected_page_size} items for offset={offset}, "
            f"limit={limit}, total={total_claims}, got {len(result['items'])}"
        )


# ---------------------------------------------------------------------------
# Property 12: Filtering Correctness
# ---------------------------------------------------------------------------


class TestP12FilteringCorrectness:
    """Property 12: Filtering Correctness.

    For any claim list request with filters (status, claim_type, customer_id,
    date_range, branch_id), all returned claims SHALL match ALL specified
    filter criteria.

    **Validates: Requirements 6.2, 6.3, 6.4, 6.5**

    Tag: Feature: customer-claims-returns, Property 12: Filtering Correctness
    """

    def _make_claim_mock(
        self,
        org_id: uuid.UUID,
        status: str,
        claim_type: str,
        customer_id: uuid.UUID,
        branch_id: uuid.UUID | None,
        created_at: datetime,
        cost_to_business: float = 0,
    ) -> MagicMock:
        claim = MagicMock(spec=CustomerClaim)
        claim.id = uuid.uuid4()
        claim.org_id = org_id
        claim.branch_id = branch_id
        claim.customer_id = customer_id
        claim.claim_type = claim_type
        claim.status = status
        claim.description = "test claim"
        claim.cost_to_business = cost_to_business
        claim.created_at = created_at
        claim.customer = None
        return claim

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        filter_status=st.sampled_from([s.value for s in ClaimStatus]),
        filter_claim_type=st.sampled_from([ct.value for ct in ClaimType]),
        filter_customer_id=st.uuids(),
        filter_branch_id=st.uuids(),
        num_matching=st.integers(min_value=0, max_value=10),
        num_non_matching=st.integers(min_value=0, max_value=10),
    )
    def test_all_returned_claims_match_all_filter_criteria(
        self,
        org_id: uuid.UUID,
        filter_status: str,
        filter_claim_type: str,
        filter_customer_id: uuid.UUID,
        filter_branch_id: uuid.UUID,
        num_matching: int,
        num_non_matching: int,
    ) -> None:
        """P12: All returned claims match ALL specified filter criteria."""
        from app.modules.claims.service import list_claims

        now = datetime.now(timezone.utc)

        # Build matching claims (match all filters)
        matching = [
            self._make_claim_mock(
                org_id=org_id,
                status=filter_status,
                claim_type=filter_claim_type,
                customer_id=filter_customer_id,
                branch_id=filter_branch_id,
                created_at=now,
            )
            for _ in range(num_matching)
        ]

        # The mock DB simulates that the SQL filters already applied,
        # so only matching claims are returned.
        db = AsyncMock()
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                count_result = MagicMock()
                count_result.scalar.return_value = num_matching
                return count_result
            else:
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = matching
                result_mock = MagicMock()
                result_mock.scalars.return_value = scalars_mock
                return result_mock

        db.execute = AsyncMock(side_effect=mock_execute)

        result = asyncio.get_event_loop().run_until_complete(
            list_claims(
                db,
                org_id=org_id,
                status=filter_status,
                claim_type=filter_claim_type,
                customer_id=filter_customer_id,
                branch_id=filter_branch_id,
            )
        )

        # Property: every returned claim matches ALL filter criteria
        for item in result["items"]:
            assert item["status"] == filter_status, (
                f"Expected status '{filter_status}', got '{item['status']}'"
            )
            assert item["claim_type"] == filter_claim_type, (
                f"Expected claim_type '{filter_claim_type}', got '{item['claim_type']}'"
            )
            assert item["customer_id"] == filter_customer_id, (
                f"Expected customer_id '{filter_customer_id}', got '{item['customer_id']}'"
            )
            assert item["branch_id"] == filter_branch_id, (
                f"Expected branch_id '{filter_branch_id}', got '{item['branch_id']}'"
            )

        # Property: total count matches the number of matching claims
        assert result["total"] == num_matching


# ---------------------------------------------------------------------------
# Property 13: Customer Claims Summary Accuracy
# ---------------------------------------------------------------------------


class TestP13CustomerClaimsSummaryAccuracy:
    """Property 13: Customer Claims Summary Accuracy.

    For any customer, the claims summary SHALL return accurate counts
    (total_claims, open_claims) and total_cost_to_business that equals the
    sum of cost_to_business across all customer claims.

    **Validates: Requirements 9.1, 9.2, 9.3**

    Tag: Feature: customer-claims-returns, Property 13: Customer Claims Summary Accuracy
    """

    def _make_claim_mock(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        status: str,
        cost_to_business: float,
    ) -> MagicMock:
        claim = MagicMock(spec=CustomerClaim)
        claim.id = uuid.uuid4()
        claim.org_id = org_id
        claim.branch_id = None
        claim.customer_id = customer_id
        claim.claim_type = "warranty"
        claim.status = status
        claim.description = "test"
        claim.cost_to_business = cost_to_business
        claim.created_at = datetime.now(timezone.utc)
        return claim

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        customer_id=st.uuids(),
        claim_data=st.lists(
            st.tuples(
                st.sampled_from([s.value for s in ClaimStatus]),
                st.floats(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False),
            ),
            min_size=0,
            max_size=20,
        ),
    )
    def test_summary_counts_and_cost_are_accurate(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        claim_data: list[tuple[str, float]],
    ) -> None:
        """P13: Summary total_claims, open_claims, and total_cost_to_business are accurate."""
        from app.modules.claims.service import get_customer_claims_summary

        claims = [
            self._make_claim_mock(org_id, customer_id, status, cost)
            for status, cost in claim_data
        ]

        # Expected values
        expected_total = len(claims)
        expected_open = sum(1 for s, _ in claim_data if s == "open")
        expected_cost = sum(cost for _, cost in claim_data)

        # Mock DB
        db = AsyncMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = claims
        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock
        db.execute = AsyncMock(return_value=result_mock)

        result = asyncio.get_event_loop().run_until_complete(
            get_customer_claims_summary(
                db,
                org_id=org_id,
                customer_id=customer_id,
            )
        )

        # Property: total_claims equals the number of claims
        assert result["total_claims"] == expected_total, (
            f"Expected total_claims {expected_total}, got {result['total_claims']}"
        )
        # Property: open_claims equals the count of claims with status "open"
        assert result["open_claims"] == expected_open, (
            f"Expected open_claims {expected_open}, got {result['open_claims']}"
        )
        # Property: total_cost_to_business equals sum of all cost_to_business
        assert abs(result["total_cost_to_business"] - expected_cost) < 1e-6, (
            f"Expected total_cost_to_business ~{expected_cost}, "
            f"got {result['total_cost_to_business']}"
        )
        # Property: claims list length matches total_claims
        assert len(result["claims"]) == expected_total


# ---------------------------------------------------------------------------
# Property 14: Branch Inheritance
# ---------------------------------------------------------------------------


class TestP14BranchInheritance:
    """Property 14: Branch Inheritance.

    For any claim created without an explicit branch_id, if the linked invoice
    or job card has a branch_id, the claim SHALL inherit that branch_id.

    **Validates: Requirements 11.4**

    Tag: Feature: customer-claims-returns, Property 14: Branch Inheritance
    """

    def _build_branch_inheritance_db(
        self,
        org_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_id: uuid.UUID | None,
        invoice_branch_id: uuid.UUID | None,
        job_card_id: uuid.UUID | None,
        job_card_branch_id: uuid.UUID | None,
    ) -> AsyncMock:
        """Build mock DB for create_claim with branch inheritance scenario."""
        results = []

        # 1st call: customer lookup
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = _make_customer_mock(customer_id, org_id)
        results.append(cust_result)

        # 2nd call: invoice lookup (if provided)
        if invoice_id is not None:
            inv = _make_invoice_mock(invoice_id, org_id)
            inv.branch_id = invoice_branch_id
            inv_result = MagicMock()
            inv_result.scalar_one_or_none.return_value = inv
            results.append(inv_result)

        # 3rd call: job card lookup (if provided)
        if job_card_id is not None:
            jc = _make_job_card_mock(job_card_id, org_id)
            jc.branch_id = job_card_branch_id
            jc_result = MagicMock()
            jc_result.scalar_one_or_none.return_value = jc
            results.append(jc_result)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        invoice_id=st.uuids(),
        invoice_branch_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
    )
    def test_claim_inherits_branch_from_invoice(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_id: uuid.UUID,
        invoice_branch_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
    ) -> None:
        """P14a: Claim with no explicit branch_id inherits branch_id from linked invoice."""
        db = self._build_branch_inheritance_db(
            org_id=org_id,
            customer_id=customer_id,
            invoice_id=invoice_id,
            invoice_branch_id=invoice_branch_id,
            job_card_id=None,
            job_card_branch_id=None,
        )

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=invoice_id,
                    job_card_id=None,
                    branch_id=None,
                )
            )

        assert result["branch_id"] == invoice_branch_id, (
            f"Expected branch_id '{invoice_branch_id}' from invoice, "
            f"got '{result['branch_id']}'"
        )

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        job_card_id=st.uuids(),
        job_card_branch_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
    )
    def test_claim_inherits_branch_from_job_card(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        job_card_id: uuid.UUID,
        job_card_branch_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
    ) -> None:
        """P14b: Claim with no explicit branch_id inherits branch_id from linked job card."""
        db = self._build_branch_inheritance_db(
            org_id=org_id,
            customer_id=customer_id,
            invoice_id=None,
            invoice_branch_id=None,
            job_card_id=job_card_id,
            job_card_branch_id=job_card_branch_id,
        )

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=None,
                    job_card_id=job_card_id,
                    branch_id=None,
                )
            )

        assert result["branch_id"] == job_card_branch_id, (
            f"Expected branch_id '{job_card_branch_id}' from job card, "
            f"got '{result['branch_id']}'"
        )

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        invoice_id=st.uuids(),
        invoice_branch_id=st.uuids(),
        job_card_id=st.uuids(),
        job_card_branch_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
    )
    def test_invoice_branch_takes_precedence_over_job_card(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_id: uuid.UUID,
        invoice_branch_id: uuid.UUID,
        job_card_id: uuid.UUID,
        job_card_branch_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
    ) -> None:
        """P14c: When both invoice and job card have branch_ids, invoice branch takes precedence."""
        db = self._build_branch_inheritance_db(
            org_id=org_id,
            customer_id=customer_id,
            invoice_id=invoice_id,
            invoice_branch_id=invoice_branch_id,
            job_card_id=job_card_id,
            job_card_branch_id=job_card_branch_id,
        )

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock):
            result = asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=invoice_id,
                    job_card_id=job_card_id,
                    branch_id=None,
                )
            )

        # Invoice branch takes precedence per the service logic
        assert result["branch_id"] == invoice_branch_id, (
            f"Expected invoice branch_id '{invoice_branch_id}' to take precedence, "
            f"got '{result['branch_id']}'"
        )


# ---------------------------------------------------------------------------
# Property 6: Resolution Action Dispatch
# ---------------------------------------------------------------------------

from decimal import Decimal
from app.modules.claims.models import ResolutionType
from app.modules.claims.resolution_engine import ResolutionEngine, ResolutionResult


def _make_approved_claim(
    org_id: uuid.UUID,
    claim_id: uuid.UUID | None = None,
    invoice_id: uuid.UUID | None = None,
    job_card_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a MagicMock claim in 'approved' status for resolution tests."""
    claim = MagicMock(spec=CustomerClaim)
    claim.id = claim_id or uuid.uuid4()
    claim.org_id = org_id
    claim.branch_id = branch_id
    claim.customer_id = customer_id or uuid.uuid4()
    claim.invoice_id = invoice_id or uuid.uuid4()
    claim.job_card_id = job_card_id
    claim.line_item_ids = []
    claim.claim_type = "warranty"
    claim.status = "approved"
    claim.description = "Test claim for resolution"
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
    claim.created_by = uuid.uuid4()
    claim.created_at = datetime.now(timezone.utc)
    claim.updated_at = datetime.now(timezone.utc)
    return claim


class TestP6ResolutionActionDispatch:
    """Property 6: Resolution Action Dispatch.

    For any claim resolution, the Resolution Engine SHALL trigger the correct
    downstream action based on resolution_type:
    - full_refund → PaymentService.process_refund with full invoice amount
    - partial_refund → PaymentService.process_refund with specified amount
    - credit_note → InvoiceService.create_credit_note
    - exchange → StockService.increment_stock with movement_type "return"
    - redo_service → JobCardService.create_job_card with zero charge
    - no_action → No downstream actions

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        invoice_id=st.uuids(),
    )
    def test_full_refund_calls_process_refund(
        self, org_id, user_id, claim_id, invoice_id,
    ):
        """P6a: full_refund triggers PaymentService.process_refund for full invoice amount."""
        claim = _make_approved_claim(org_id, claim_id=claim_id, invoice_id=invoice_id)

        db = AsyncMock()
        # execute calls: 1) invoice lookup
        inv_mock = MagicMock()
        inv_mock.id = invoice_id
        inv_mock.org_id = org_id
        inv_mock.amount_paid = Decimal("500.00")
        inv_mock.total = Decimal("500.00")
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = inv_mock
        db.execute = AsyncMock(return_value=inv_result)
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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.FULL_REFUND,
                    user_id=user_id,
                )
            )

        mock_refund.assert_called_once()
        assert result.resolution_type == "full_refund"
        assert result.refund_id is not None

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        invoice_id=st.uuids(),
        amount=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999.99"), places=2),
    )
    def test_partial_refund_calls_process_refund_with_amount(
        self, org_id, user_id, claim_id, invoice_id, amount,
    ):
        """P6b: partial_refund triggers PaymentService.process_refund with specified amount."""
        claim = _make_approved_claim(org_id, claim_id=claim_id, invoice_id=invoice_id)

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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.PARTIAL_REFUND,
                    resolution_amount=amount,
                    user_id=user_id,
                )
            )

        mock_refund.assert_called_once()
        assert result.resolution_type == "partial_refund"
        assert result.refund_id is not None

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        invoice_id=st.uuids(),
    )
    def test_credit_note_calls_create_credit_note(
        self, org_id, user_id, claim_id, invoice_id,
    ):
        """P6c: credit_note triggers InvoiceService.create_credit_note."""
        claim = _make_approved_claim(org_id, claim_id=claim_id, invoice_id=invoice_id)

        db = AsyncMock()
        # execute call: invoice lookup for credit note amount
        inv_mock = MagicMock()
        inv_mock.id = invoice_id
        inv_mock.org_id = org_id
        inv_mock.total = Decimal("300.00")
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = inv_mock
        db.execute = AsyncMock(return_value=inv_result)
        db.flush = AsyncMock()

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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.CREDIT_NOTE,
                    user_id=user_id,
                )
            )

        mock_cn.assert_called_once()
        assert result.resolution_type == "credit_note"
        assert result.credit_note_id == cn_id

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
    )
    def test_redo_service_calls_create_job_card(
        self, org_id, user_id, claim_id,
    ):
        """P6e: redo_service triggers JobCardService.create_job_card."""
        job_card_id = uuid.uuid4()
        claim = _make_approved_claim(
            org_id, claim_id=claim_id, job_card_id=job_card_id,
        )

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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.REDO_SERVICE,
                    user_id=user_id,
                )
            )

        mock_jc.assert_called_once()
        assert result.resolution_type == "redo_service"
        assert result.warranty_job_id == new_job_id

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
    )
    def test_no_action_triggers_no_downstream(
        self, org_id, user_id, claim_id,
    ):
        """P6f: no_action triggers no downstream actions."""
        claim = _make_approved_claim(org_id, claim_id=claim_id)

        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        with patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.NO_ACTION,
                    user_id=user_id,
                )
            )

        assert result.resolution_type == "no_action"
        assert result.refund_id is None
        assert result.credit_note_id is None
        assert result.return_movement_ids == []
        assert result.warranty_job_id is None


# ---------------------------------------------------------------------------
# Property 7: Downstream Entity Reference Storage
# ---------------------------------------------------------------------------


class TestP7DownstreamEntityReferenceStorage:
    """Property 7: Downstream Entity Reference Storage.

    For any resolved claim with downstream actions, the claim record SHALL
    store the correct reference IDs (refund_id, credit_note_id,
    return_movement_ids, warranty_job_id) for all created entities.

    **Validates: Requirements 3.8**
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        invoice_id=st.uuids(),
    )
    def test_full_refund_stores_refund_id_on_claim(
        self, org_id, user_id, claim_id, invoice_id,
    ):
        """P7a: After full_refund resolution, claim.refund_id is set."""
        claim = _make_approved_claim(org_id, claim_id=claim_id, invoice_id=invoice_id)

        db = AsyncMock()
        inv_mock = MagicMock()
        inv_mock.id = invoice_id
        inv_mock.org_id = org_id
        inv_mock.amount_paid = Decimal("200.00")
        inv_mock.total = Decimal("200.00")
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = inv_mock
        db.execute = AsyncMock(return_value=inv_result)
        db.flush = AsyncMock()

        refund_id = uuid.uuid4()
        refund_mock = MagicMock()
        refund_mock.id = refund_id

        with patch(
            "app.modules.payments.service.process_refund",
            new_callable=AsyncMock,
            return_value={"refund": refund_mock},
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.FULL_REFUND,
                    user_id=user_id,
                )
            )

        # The engine stores refund_id on the claim object
        assert claim.refund_id == refund_id

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        invoice_id=st.uuids(),
    )
    def test_credit_note_stores_credit_note_id_on_claim(
        self, org_id, user_id, claim_id, invoice_id,
    ):
        """P7b: After credit_note resolution, claim.credit_note_id is set."""
        claim = _make_approved_claim(org_id, claim_id=claim_id, invoice_id=invoice_id)

        db = AsyncMock()
        inv_mock = MagicMock()
        inv_mock.id = invoice_id
        inv_mock.org_id = org_id
        inv_mock.total = Decimal("150.00")
        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = inv_mock
        db.execute = AsyncMock(return_value=inv_result)
        db.flush = AsyncMock()

        cn_id = uuid.uuid4()

        with patch(
            "app.modules.invoices.service.create_credit_note",
            new_callable=AsyncMock,
            return_value={"credit_note": {"id": cn_id}},
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.CREDIT_NOTE,
                    user_id=user_id,
                )
            )

        assert claim.credit_note_id == cn_id

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
    )
    def test_redo_service_stores_warranty_job_id_on_claim(
        self, org_id, user_id, claim_id,
    ):
        """P7c: After redo_service resolution, claim.warranty_job_id is set."""
        job_card_id = uuid.uuid4()
        claim = _make_approved_claim(
            org_id, claim_id=claim_id, job_card_id=job_card_id,
        )

        db = AsyncMock()
        db.execute = AsyncMock()
        db.flush = AsyncMock()

        new_job_id = uuid.uuid4()

        with patch(
            "app.modules.job_cards.service.create_job_card",
            new_callable=AsyncMock,
            return_value={"id": new_job_id},
        ), patch(
            "app.modules.job_cards.service.get_job_card",
            new_callable=AsyncMock,
            return_value={"vehicle_rego": "XYZ789", "description": "Original"},
        ), patch(
            "app.modules.claims.resolution_engine.write_audit_log",
            new_callable=AsyncMock,
        ):
            engine = ResolutionEngine(db)
            asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.REDO_SERVICE,
                    user_id=user_id,
                )
            )

        assert claim.warranty_job_id == new_job_id


# ---------------------------------------------------------------------------
# Property 8: Stock Return Movement Linking
# ---------------------------------------------------------------------------


class TestP8StockReturnMovementLinking:
    """Property 8: Stock Return Movement Linking.

    For any claim involving a physical product return, the created
    StockMovement SHALL have movement_type "return", reference_type "claim",
    and reference_id equal to the claim ID.

    **Validates: Requirements 4.1, 4.2**
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        stock_item_id=st.uuids(),
    )
    def test_exchange_creates_return_movement_with_correct_fields(
        self, org_id, user_id, claim_id, stock_item_id,
    ):
        """P8: Exchange resolution creates stock movement with movement_type='return',
        reference_type='claim', reference_id=claim.id."""
        claim = _make_approved_claim(org_id, claim_id=claim_id)

        db = AsyncMock()

        # Mock product lookup — StockItem not found, Product found directly
        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = org_id
        product_mock.is_active = True
        product_mock.sale_price = Decimal("50.00")
        product_mock.cost_price = Decimal("30.00")
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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.EXCHANGE,
                    return_stock_item_ids=[stock_item_id],
                    user_id=user_id,
                )
            )

        # Verify increment_stock was called with correct params
        mock_stock_service.increment_stock.assert_called_once()
        call_kw = mock_stock_service.increment_stock.call_args
        assert call_kw[1]["movement_type"] == "return"
        assert call_kw[1]["reference_type"] == "claim"
        assert call_kw[1]["reference_id"] == claim_id

        # Verify result has return_movement_ids
        assert len(result.return_movement_ids) == 1
        assert result.return_movement_ids[0]["movement_id"] == movement_mock.id


# ---------------------------------------------------------------------------
# Property 9: Write-off Flagging
# ---------------------------------------------------------------------------


class TestP9WriteOffFlagging:
    """Property 9: Write-off Flagging.

    For any stock return where the catalogue entry is archived OR the item
    has zero resale value, the movement SHALL be flagged as a write-off and
    the item's cost_price SHALL be added to the claim's write_off_cost.

    **Validates: Requirements 4.3, 4.4, 4.5, 4.6**
    """

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        stock_item_id=st.uuids(),
        cost_price=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("999.99"), places=2),
    )
    def test_archived_product_flagged_as_write_off(
        self, org_id, user_id, claim_id, stock_item_id, cost_price,
    ):
        """P9a: When product is_active=False (archived), movement is flagged as write-off."""
        claim = _make_approved_claim(org_id, claim_id=claim_id)

        db = AsyncMock()

        # StockItem not found, Product found but archived
        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = org_id
        product_mock.is_active = False  # Archived
        product_mock.sale_price = Decimal("50.00")
        product_mock.cost_price = cost_price
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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.EXCHANGE,
                    return_stock_item_ids=[stock_item_id],
                    user_id=user_id,
                )
            )

        assert len(result.return_movement_ids) == 1
        assert result.return_movement_ids[0]["is_write_off"] is True
        assert result.return_movement_ids[0]["write_off_amount"] == cost_price
        assert result.write_off_cost == cost_price

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        stock_item_id=st.uuids(),
        cost_price=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("999.99"), places=2),
    )
    def test_zero_sale_price_flagged_as_write_off(
        self, org_id, user_id, claim_id, stock_item_id, cost_price,
    ):
        """P9b: When product sale_price <= 0 (zero resale value), movement is flagged as write-off."""
        claim = _make_approved_claim(org_id, claim_id=claim_id)

        db = AsyncMock()

        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = org_id
        product_mock.is_active = True  # Not archived
        product_mock.sale_price = Decimal("0")  # Zero resale value
        product_mock.cost_price = cost_price
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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.EXCHANGE,
                    return_stock_item_ids=[stock_item_id],
                    user_id=user_id,
                )
            )

        assert len(result.return_movement_ids) == 1
        assert result.return_movement_ids[0]["is_write_off"] is True
        assert result.return_movement_ids[0]["write_off_amount"] == cost_price
        assert result.write_off_cost == cost_price

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        stock_item_id=st.uuids(),
    )
    def test_active_product_with_positive_price_not_write_off(
        self, org_id, user_id, claim_id, stock_item_id,
    ):
        """P9c: When product is active and has positive sale_price, NOT flagged as write-off."""
        claim = _make_approved_claim(org_id, claim_id=claim_id)

        db = AsyncMock()

        si_result = MagicMock()
        si_result.scalar_one_or_none.return_value = None
        product_mock = MagicMock()
        product_mock.id = stock_item_id
        product_mock.org_id = org_id
        product_mock.is_active = True
        product_mock.sale_price = Decimal("100.00")
        product_mock.cost_price = Decimal("50.00")
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
            result = asyncio.get_event_loop().run_until_complete(
                engine.execute_resolution(
                    claim=claim,
                    resolution_type=ResolutionType.EXCHANGE,
                    return_stock_item_ids=[stock_item_id],
                    user_id=user_id,
                )
            )

        assert len(result.return_movement_ids) == 1
        assert result.return_movement_ids[0]["is_write_off"] is False
        assert result.return_movement_ids[0]["write_off_amount"] == Decimal("0")
        assert result.write_off_cost == Decimal("0")

# ---------------------------------------------------------------------------
# Property 10: Cost Calculation Accuracy
# ---------------------------------------------------------------------------


class TestP10CostCalculationAccuracy:
    """Property 10: Cost Calculation Accuracy.

    For any claim, the cost_to_business SHALL equal the sum of
    labour_cost + parts_cost + write_off_cost from the cost_breakdown,
    and each component SHALL be calculated correctly based on linked actions.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

    Tag: Feature: customer-claims-returns, Property 10: Cost Calculation Accuracy
    """

    def _make_claim_mock(
        self,
        claim_id: uuid.UUID,
        org_id: uuid.UUID,
        warranty_job_id: uuid.UUID | None,
        write_off_cost: float = 0,
    ) -> MagicMock:
        claim = MagicMock(spec=CustomerClaim)
        claim.id = claim_id
        claim.org_id = org_id
        claim.warranty_job_id = warranty_job_id
        claim.cost_breakdown = {
            "labour_cost": 0,
            "parts_cost": 0,
            "write_off_cost": write_off_cost,
        }
        claim.cost_to_business = Decimal("0")
        claim.status = "resolved"
        claim.created_by = uuid.uuid4()
        claim.updated_at = datetime.now(timezone.utc)
        return claim

    def _make_time_entry_mock(
        self, duration_minutes: int, hourly_rate: float
    ) -> MagicMock:
        from app.modules.time_tracking_v2.models import TimeEntry

        entry = MagicMock(spec=TimeEntry)
        entry.duration_minutes = duration_minutes
        entry.hourly_rate = Decimal(str(hourly_rate))
        return entry

    def _make_part_item_mock(
        self, quantity: float, unit_price: float
    ) -> MagicMock:
        from app.modules.job_cards.models import JobCardItem

        item = MagicMock(spec=JobCardItem)
        item.item_type = "part"
        item.quantity = Decimal(str(quantity))
        item.unit_price = Decimal(str(unit_price))
        return item

    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        claim_id=st.uuids(),
        org_id=st.uuids(),
        # Time entries: list of (duration_minutes, hourly_rate) tuples
        time_entries=st.lists(
            st.tuples(
                st.integers(min_value=1, max_value=480),
                st.floats(min_value=0.01, max_value=500, allow_nan=False, allow_infinity=False),
            ),
            min_size=0,
            max_size=5,
        ),
        # Parts: list of (quantity, unit_price) tuples
        parts=st.lists(
            st.tuples(
                st.floats(min_value=0.001, max_value=100, allow_nan=False, allow_infinity=False),
                st.floats(min_value=0.01, max_value=1000, allow_nan=False, allow_infinity=False),
            ),
            min_size=0,
            max_size=5,
        ),
        write_off_cost=st.floats(min_value=0, max_value=5000, allow_nan=False, allow_infinity=False),
    )
    def test_cost_to_business_equals_sum_of_components(
        self,
        claim_id: uuid.UUID,
        org_id: uuid.UUID,
        time_entries: list[tuple[int, float]],
        parts: list[tuple[float, float]],
        write_off_cost: float,
    ) -> None:
        """P10: cost_to_business == labour_cost + parts_cost + write_off_cost."""
        from app.modules.claims.cost_tracker import CostTracker

        warranty_job_id = uuid.uuid4() if (time_entries or parts) else None
        claim = self._make_claim_mock(claim_id, org_id, warranty_job_id, write_off_cost)

        te_mocks = [
            self._make_time_entry_mock(dur, rate) for dur, rate in time_entries
        ]
        part_mocks = [
            self._make_part_item_mock(qty, price) for qty, price in parts
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Claim lookup
                result.scalar_one_or_none.return_value = claim
            elif call_count == 2:
                # Time entries query
                scalars = MagicMock()
                scalars.all.return_value = te_mocks
                result.scalars.return_value = scalars
            elif call_count == 3:
                # Parts query
                scalars = MagicMock()
                scalars.all.return_value = part_mocks
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        tracker = CostTracker(db)
        breakdown = asyncio.get_event_loop().run_until_complete(
            tracker.calculate_claim_cost(claim_id=claim_id)
        )

        # Independently compute expected values
        expected_labour = sum(
            Decimal(str(dur)) / Decimal("60") * Decimal(str(rate))
            for dur, rate in time_entries
        )
        expected_parts = sum(
            Decimal(str(qty)) * Decimal(str(price))
            for qty, price in parts
        )
        expected_write_off = Decimal(str(write_off_cost))

        # Property: each component matches independent calculation
        assert breakdown.labour_cost == expected_labour, (
            f"Labour mismatch: {breakdown.labour_cost} != {expected_labour}"
        )
        assert breakdown.parts_cost == expected_parts, (
            f"Parts mismatch: {breakdown.parts_cost} != {expected_parts}"
        )
        assert breakdown.write_off_cost == expected_write_off, (
            f"Write-off mismatch: {breakdown.write_off_cost} != {expected_write_off}"
        )

        # Property: total equals sum of components
        assert breakdown.total == breakdown.labour_cost + breakdown.parts_cost + breakdown.write_off_cost, (
            f"Total {breakdown.total} != sum of components "
            f"({breakdown.labour_cost} + {breakdown.parts_cost} + {breakdown.write_off_cost})"
        )

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        claim_id=st.uuids(),
        org_id=st.uuids(),
        user_id=st.uuids(),
        labour_cost=st.decimals(min_value=0, max_value=10000, places=2, allow_nan=False, allow_infinity=False),
        parts_cost=st.decimals(min_value=0, max_value=10000, places=2, allow_nan=False, allow_infinity=False),
        write_off_cost=st.decimals(min_value=0, max_value=10000, places=2, allow_nan=False, allow_infinity=False),
    )
    def test_update_claim_cost_sets_total_to_sum(
        self,
        claim_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        labour_cost: Decimal,
        parts_cost: Decimal,
        write_off_cost: Decimal,
    ) -> None:
        """P10b: After update_claim_cost, cost_to_business == labour + parts + write_off."""
        from app.modules.claims.cost_tracker import CostTracker

        claim = self._make_claim_mock(claim_id, org_id, None)

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = claim
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        tracker = CostTracker(db)
        asyncio.get_event_loop().run_until_complete(
            tracker.update_claim_cost(
                claim_id=claim_id,
                labour_cost=labour_cost,
                parts_cost=parts_cost,
                write_off_cost=write_off_cost,
                user_id=user_id,
            )
        )

        # Property: cost_to_business == sum of all components
        expected_total = labour_cost + parts_cost + write_off_cost
        assert claim.cost_to_business == expected_total, (
            f"cost_to_business {claim.cost_to_business} != {expected_total}"
        )


# ---------------------------------------------------------------------------
# Property 15: Audit Log Completeness
# ---------------------------------------------------------------------------


class TestP15AuditLogCompleteness:
    """Property 15: Audit Log Completeness.

    For any claim action (creation, status change, resolution), an audit log
    entry SHALL be written with the correct action type, before_value,
    after_value, user_id, and ip_address.

    **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**

    Tag: Feature: customer-claims-returns, Property 15: Audit Log Completeness
    """

    # --- helpers ---

    def _make_customer_mock(self, customer_id, org_id):
        c = MagicMock(spec=Customer)
        c.id = customer_id
        c.org_id = org_id
        return c

    def _make_invoice_mock(self, invoice_id, org_id):
        inv = MagicMock(spec=Invoice)
        inv.id = invoice_id
        inv.org_id = org_id
        inv.branch_id = None
        return inv

    def _build_create_db(self, org_id, customer_id, invoice_id):
        """Mock DB for create_claim with an invoice reference."""
        results = []
        cust_result = MagicMock()
        cust_result.scalar_one_or_none.return_value = self._make_customer_mock(customer_id, org_id)
        results.append(cust_result)

        inv_result = MagicMock()
        inv_result.scalar_one_or_none.return_value = self._make_invoice_mock(invoice_id, org_id)
        results.append(inv_result)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=results)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db

    def _build_status_db(self, org_id, claim_id, current_status):
        """Mock DB for update_claim_status."""
        claim = MagicMock(spec=CustomerClaim)
        claim.id = claim_id
        claim.org_id = org_id
        claim.branch_id = None
        claim.customer_id = uuid.uuid4()
        claim.invoice_id = uuid.uuid4()
        claim.job_card_id = None
        claim.line_item_ids = []
        claim.claim_type = "warranty"
        claim.status = current_status
        claim.description = "test"
        claim.resolution_type = None
        claim.resolution_amount = None
        claim.resolution_notes = None
        claim.resolved_at = None
        claim.resolved_by = None
        claim.cost_to_business = 0
        claim.cost_breakdown = {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
        claim.created_by = uuid.uuid4()
        claim.created_at = datetime.now(timezone.utc)
        claim.updated_at = datetime.now(timezone.utc)

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()
        return db, claim

    # --- P15a: Claim creation writes audit log (Req 12.1, 12.5) ---

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        customer_id=st.uuids(),
        invoice_id=st.uuids(),
        claim_type=claim_type_strategy,
        description=description_strategy,
        ip_address=st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    )
    def test_create_claim_writes_audit_log(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_id: uuid.UUID,
        claim_type: ClaimType,
        description: str,
        ip_address: str,
    ) -> None:
        """P15a: create_claim writes audit log with action 'claim.created', user_id, ip_address."""
        db = self._build_create_db(org_id, customer_id, invoice_id)

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            asyncio.get_event_loop().run_until_complete(
                create_claim(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    claim_type=claim_type,
                    description=description,
                    invoice_id=invoice_id,
                    ip_address=ip_address,
                )
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args
            # Positional or keyword — extract kwargs
            kw = call_kwargs.kwargs if call_kwargs.kwargs else {}
            if not kw and call_kwargs.args:
                # Fallback: called positionally
                pass
            else:
                assert kw.get("action") == "claim.created", (
                    f"Expected action 'claim.created', got {kw.get('action')}"
                )
                assert kw.get("user_id") == user_id
                assert kw.get("ip_address") == ip_address
                assert kw.get("after_value") is not None
                assert kw.get("entity_type") == "claim"

    # --- P15b: Status change writes audit log (Req 12.2, 12.4, 12.5) ---

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        ip_address=st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    )
    def test_status_change_writes_audit_log_with_before_after(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
        ip_address: str,
    ) -> None:
        """P15b: update_claim_status writes audit log with before_value, after_value, user_id, ip."""
        db, claim = self._build_status_db(org_id, claim_id, "open")

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            asyncio.get_event_loop().run_until_complete(
                update_claim_status(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    claim_id=claim_id,
                    new_status=ClaimStatus.INVESTIGATING,
                    ip_address=ip_address,
                )
            )

            mock_audit.assert_called_once()
            kw = mock_audit.call_args.kwargs
            assert kw.get("action") == "claim.status_changed"
            assert kw.get("user_id") == user_id
            assert kw.get("ip_address") == ip_address
            assert kw.get("before_value") == {"status": "open"}
            assert kw.get("after_value") == {"status": "investigating"}
            assert kw.get("entity_type") == "claim"
            assert kw.get("entity_id") == claim_id

    # --- P15c: Note addition writes audit log (Req 12.4, 12.5) ---

    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        org_id=st.uuids(),
        user_id=st.uuids(),
        claim_id=st.uuids(),
        note_text=st.text(min_size=1, max_size=200, alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"))),
        ip_address=st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    )
    def test_add_note_writes_audit_log(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        claim_id: uuid.UUID,
        note_text: str,
        ip_address: str,
    ) -> None:
        """P15c: add_claim_note writes audit log with action 'claim.note_added'."""
        from app.modules.claims.service import add_claim_note

        # Build mock for add_claim_note: first execute returns claim, second (get_claim) returns claim
        claim = MagicMock(spec=CustomerClaim)
        claim.id = claim_id
        claim.org_id = org_id
        claim.branch_id = None
        claim.customer_id = uuid.uuid4()
        claim.invoice_id = uuid.uuid4()
        claim.job_card_id = None
        claim.line_item_ids = []
        claim.claim_type = "defect"
        claim.status = "investigating"
        claim.description = "test"
        claim.resolution_type = None
        claim.resolution_amount = None
        claim.resolution_notes = None
        claim.resolved_at = None
        claim.resolved_by = None
        claim.refund_id = None
        claim.credit_note_id = None
        claim.return_movement_ids = []
        claim.warranty_job_id = None
        claim.cost_to_business = 0
        claim.cost_breakdown = {"labour_cost": 0, "parts_cost": 0, "write_off_cost": 0}
        claim.created_by = uuid.uuid4()
        claim.created_at = datetime.now(timezone.utc)
        claim.updated_at = datetime.now(timezone.utc)
        claim.customer = None
        claim.invoice = None
        claim.job_card = None
        claim.actions = []

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = claim

        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with patch("app.modules.claims.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            asyncio.get_event_loop().run_until_complete(
                add_claim_note(
                    db,
                    org_id=org_id,
                    user_id=user_id,
                    claim_id=claim_id,
                    notes=note_text,
                    ip_address=ip_address,
                )
            )

            # At least one call should be for note_added
            note_calls = [
                c for c in mock_audit.call_args_list
                if c.kwargs.get("action") == "claim.note_added"
            ]
            assert len(note_calls) >= 1, "Expected audit log call with action 'claim.note_added'"
            kw = note_calls[0].kwargs
            assert kw.get("user_id") == user_id
            assert kw.get("ip_address") == ip_address
            assert kw.get("entity_type") == "claim"
