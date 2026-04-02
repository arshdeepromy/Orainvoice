"""Unit tests for CostTracker.

Tests labour cost calculation from time entries, parts cost calculation
from job card items, write-off cost calculation, and cost_to_business
equals sum of components.

Requirements: 5.1-5.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401

from app.modules.claims.cost_tracker import (
    CostBreakdown,
    CostTracker,
    update_claim_cost_on_job_completion,
)
from app.modules.claims.models import ClaimAction, CustomerClaim
from app.modules.job_cards.models import JobCardItem
from app.modules.time_tracking_v2.models import TimeEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
USER_ID = uuid.uuid4()
CLAIM_ID = uuid.uuid4()
WARRANTY_JOB_ID = uuid.uuid4()


def _make_claim(
    claim_id=CLAIM_ID,
    org_id=ORG_ID,
    warranty_job_id=None,
    cost_breakdown=None,
    cost_to_business=Decimal("0"),
    status="resolved",
):
    claim = MagicMock(spec=CustomerClaim)
    claim.id = claim_id
    claim.org_id = org_id
    claim.warranty_job_id = warranty_job_id
    claim.cost_breakdown = cost_breakdown or {
        "labour_cost": 0, "parts_cost": 0, "write_off_cost": 0,
    }
    claim.cost_to_business = cost_to_business
    claim.status = status
    claim.created_by = USER_ID
    claim.updated_at = datetime.now(timezone.utc)
    return claim


def _make_time_entry(duration_minutes, hourly_rate):
    entry = MagicMock(spec=TimeEntry)
    entry.duration_minutes = duration_minutes
    entry.hourly_rate = Decimal(str(hourly_rate)) if hourly_rate is not None else None
    return entry


def _make_job_card_item(item_type, quantity, unit_price):
    item = MagicMock(spec=JobCardItem)
    item.item_type = item_type
    item.quantity = Decimal(str(quantity))
    item.unit_price = Decimal(str(unit_price))
    return item


# ---------------------------------------------------------------------------
# CostBreakdown dataclass tests
# ---------------------------------------------------------------------------


class TestCostBreakdown:
    def test_total_is_sum_of_components(self):
        cb = CostBreakdown(
            labour_cost=Decimal("100.50"),
            parts_cost=Decimal("200.75"),
            write_off_cost=Decimal("50.25"),
        )
        assert cb.total == Decimal("351.50")

    def test_default_values_are_zero(self):
        cb = CostBreakdown()
        assert cb.labour_cost == Decimal("0")
        assert cb.parts_cost == Decimal("0")
        assert cb.write_off_cost == Decimal("0")
        assert cb.total == Decimal("0")


# ---------------------------------------------------------------------------
# CostTracker.calculate_claim_cost tests
# ---------------------------------------------------------------------------


class TestCalculateClaimCost:
    @pytest.mark.asyncio
    async def test_claim_without_warranty_job_returns_zero_labour_and_parts(self):
        """A claim with no warranty_job_id should have zero labour and parts costs."""
        claim = _make_claim(warranty_job_id=None)

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Claim lookup
                result.scalar_one_or_none.return_value = claim
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        tracker = CostTracker(db)
        breakdown = await tracker.calculate_claim_cost(claim_id=CLAIM_ID)

        assert breakdown.labour_cost == Decimal("0")
        assert breakdown.parts_cost == Decimal("0")
        assert breakdown.write_off_cost == Decimal("0")
        assert breakdown.total == Decimal("0")

    @pytest.mark.asyncio
    async def test_labour_cost_from_time_entries(self):
        """Labour cost = sum of (duration_minutes/60 × hourly_rate) for each time entry."""
        claim = _make_claim(warranty_job_id=WARRANTY_JOB_ID)
        time_entries = [
            _make_time_entry(duration_minutes=120, hourly_rate=50),   # 2h × 50 = 100
            _make_time_entry(duration_minutes=90, hourly_rate=40),    # 1.5h × 40 = 60
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = claim
            elif call_count == 2:
                # Time entries query
                scalars = MagicMock()
                scalars.all.return_value = time_entries
                result.scalars.return_value = scalars
            elif call_count == 3:
                # Parts query
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        tracker = CostTracker(db)
        breakdown = await tracker.calculate_claim_cost(claim_id=CLAIM_ID)

        assert breakdown.labour_cost == Decimal("160")

    @pytest.mark.asyncio
    async def test_parts_cost_from_job_card_items(self):
        """Parts cost = sum of (quantity × unit_price) for part-type items."""
        claim = _make_claim(warranty_job_id=WARRANTY_JOB_ID)
        parts = [
            _make_job_card_item("part", quantity=2, unit_price=25),    # 2 × 25 = 50
            _make_job_card_item("part", quantity=1, unit_price=100),   # 1 × 100 = 100
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = claim
            elif call_count == 2:
                # Time entries query (empty)
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            elif call_count == 3:
                # Parts query
                scalars = MagicMock()
                scalars.all.return_value = parts
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        tracker = CostTracker(db)
        breakdown = await tracker.calculate_claim_cost(claim_id=CLAIM_ID)

        assert breakdown.parts_cost == Decimal("150")

    @pytest.mark.asyncio
    async def test_write_off_cost_from_existing_breakdown(self):
        """Write-off cost comes from the claim's existing cost_breakdown."""
        claim = _make_claim(
            warranty_job_id=None,
            cost_breakdown={"labour_cost": 0, "parts_cost": 0, "write_off_cost": 75.50},
        )

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

        tracker = CostTracker(db)
        breakdown = await tracker.calculate_claim_cost(claim_id=CLAIM_ID)

        assert breakdown.write_off_cost == Decimal("75.5")

    @pytest.mark.asyncio
    async def test_total_equals_sum_of_all_components(self):
        """cost_to_business = labour_cost + parts_cost + write_off_cost."""
        claim = _make_claim(
            warranty_job_id=WARRANTY_JOB_ID,
            cost_breakdown={"labour_cost": 0, "parts_cost": 0, "write_off_cost": 30},
        )
        time_entries = [_make_time_entry(60, 50)]  # 1h × 50 = 50
        parts = [_make_job_card_item("part", 3, 20)]  # 3 × 20 = 60

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = claim
            elif call_count == 2:
                scalars = MagicMock()
                scalars.all.return_value = time_entries
                result.scalars.return_value = scalars
            elif call_count == 3:
                scalars = MagicMock()
                scalars.all.return_value = parts
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        tracker = CostTracker(db)
        breakdown = await tracker.calculate_claim_cost(claim_id=CLAIM_ID)

        expected_total = Decimal("50") + Decimal("60") + Decimal("30")
        assert breakdown.total == expected_total

    @pytest.mark.asyncio
    async def test_claim_not_found_raises_error(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)

        tracker = CostTracker(db)
        with pytest.raises(ValueError, match="Claim not found"):
            await tracker.calculate_claim_cost(claim_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_time_entry_without_rate_is_skipped(self):
        """Time entries with no hourly_rate should not contribute to labour cost."""
        claim = _make_claim(warranty_job_id=WARRANTY_JOB_ID)
        time_entries = [
            _make_time_entry(duration_minutes=60, hourly_rate=None),
            _make_time_entry(duration_minutes=60, hourly_rate=50),  # 1h × 50 = 50
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = claim
            elif call_count == 2:
                scalars = MagicMock()
                scalars.all.return_value = time_entries
                result.scalars.return_value = scalars
            elif call_count == 3:
                scalars = MagicMock()
                scalars.all.return_value = []
                result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        tracker = CostTracker(db)
        breakdown = await tracker.calculate_claim_cost(claim_id=CLAIM_ID)

        assert breakdown.labour_cost == Decimal("50")


# ---------------------------------------------------------------------------
# CostTracker.update_claim_cost tests
# ---------------------------------------------------------------------------


class TestUpdateClaimCost:
    @pytest.mark.asyncio
    async def test_updates_cost_breakdown_and_total(self):
        """update_claim_cost should update breakdown fields and cost_to_business."""
        claim = _make_claim()

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
        await tracker.update_claim_cost(
            claim_id=CLAIM_ID,
            labour_cost=Decimal("100"),
            parts_cost=Decimal("50"),
            write_off_cost=Decimal("25"),
            user_id=USER_ID,
        )

        assert claim.cost_breakdown["labour_cost"] == 100.0
        assert claim.cost_breakdown["parts_cost"] == 50.0
        assert claim.cost_breakdown["write_off_cost"] == 25.0
        assert claim.cost_to_business == Decimal("175")

    @pytest.mark.asyncio
    async def test_creates_claim_action_record(self):
        """update_claim_cost should create a ClaimAction with action_type 'cost_updated'."""
        claim = _make_claim()

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
        await tracker.update_claim_cost(
            claim_id=CLAIM_ID,
            labour_cost=Decimal("100"),
            user_id=USER_ID,
        )

        # Verify ClaimAction was added
        add_calls = db.add.call_args_list
        action_found = False
        for call in add_calls:
            obj = call[0][0]
            if isinstance(obj, ClaimAction):
                assert obj.action_type == "cost_updated"
                assert obj.performed_by == USER_ID
                action_found = True
        assert action_found, "No ClaimAction record was added"

    @pytest.mark.asyncio
    async def test_partial_update_preserves_existing_values(self):
        """Updating only labour_cost should preserve existing parts_cost and write_off_cost."""
        claim = _make_claim(
            cost_breakdown={"labour_cost": 0, "parts_cost": 50, "write_off_cost": 25},
        )

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
        await tracker.update_claim_cost(
            claim_id=CLAIM_ID,
            labour_cost=Decimal("80"),
            user_id=USER_ID,
        )

        assert claim.cost_breakdown["labour_cost"] == 80.0
        assert claim.cost_breakdown["parts_cost"] == 50
        assert claim.cost_breakdown["write_off_cost"] == 25
        assert claim.cost_to_business == Decimal("155")

    @pytest.mark.asyncio
    async def test_claim_not_found_raises_error(self):
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        db.flush = AsyncMock()

        tracker = CostTracker(db)
        with pytest.raises(ValueError, match="Claim not found"):
            await tracker.update_claim_cost(
                claim_id=uuid.uuid4(),
                labour_cost=Decimal("100"),
            )


# ---------------------------------------------------------------------------
# update_claim_cost_on_job_completion hook tests
# ---------------------------------------------------------------------------


class TestUpdateClaimCostOnJobCompletion:
    @pytest.mark.asyncio
    async def test_updates_cost_when_claim_linked(self):
        """When a warranty job completes, linked claim costs should be updated."""
        claim = _make_claim(warranty_job_id=WARRANTY_JOB_ID)
        time_entries = [_make_time_entry(120, 50)]  # 2h × 50 = 100
        parts = [_make_job_card_item("part", 2, 30)]  # 2 × 30 = 60

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Find claim by warranty_job_id
                result.scalar_one_or_none.return_value = claim
            elif call_count == 2:
                # Time entries for labour cost
                scalars = MagicMock()
                scalars.all.return_value = time_entries
                result.scalars.return_value = scalars
            elif call_count == 3:
                # Parts for parts cost
                scalars = MagicMock()
                scalars.all.return_value = parts
                result.scalars.return_value = scalars
            elif call_count == 4:
                # update_claim_cost: claim lookup
                result.scalar_one_or_none.return_value = claim
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        await update_claim_cost_on_job_completion(
            db, job_card_id=WARRANTY_JOB_ID, user_id=USER_ID
        )

        assert claim.cost_breakdown["labour_cost"] == 100.0
        assert claim.cost_breakdown["parts_cost"] == 60.0

    @pytest.mark.asyncio
    async def test_no_op_when_no_claim_linked(self):
        """When no claim is linked to the job, the hook should do nothing."""
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.add = MagicMock()
        db.flush = AsyncMock()

        await update_claim_cost_on_job_completion(
            db, job_card_id=uuid.uuid4(), user_id=USER_ID
        )

        # Only one execute call (the claim lookup), no further processing
        assert call_count == 1
