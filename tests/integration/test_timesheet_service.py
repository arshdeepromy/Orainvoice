"""Integration tests for ``app.modules.timesheets.service`` — using MagicMock.

Tests cover:
  - get_or_create_timesheet: idempotent lazy creation.
  - transition_status: valid chains and invalid jumps.
  - adjust_timesheet: blocked when locked.
  - bulk_approve: skips entries with exceptions.
  - bulk_lock: only locks approved entries.

Uses ``unittest.mock.AsyncMock`` for the DB session, same pattern as
``test_customer_reminders_consent_gate.py``. No real DB needed — fast.

Refs: Requirements 1.2a, 1.6, 1.7, 3.6, 3.7, 8.6, 8.7.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.timesheets.models import Timesheet
from app.modules.timesheets.service import (
    adjust_timesheet,
    bulk_approve,
    bulk_lock,
    get_or_create_timesheet,
    transition_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
PAY_PERIOD_ID = uuid.uuid4()
BRANCH_ID = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


def _make_timesheet(
    *,
    status: str = "open",
    exception_flags: list | None = None,
    rostered_minutes: int = 480,
    actual_minutes: int = 480,
) -> MagicMock:
    """Build a Timesheet mock that behaves enough like the ORM model."""
    ts = MagicMock(spec=Timesheet)
    ts.id = uuid.uuid4()
    ts.org_id = ORG_ID
    ts.staff_id = STAFF_ID
    ts.pay_period_id = PAY_PERIOD_ID
    ts.branch_id = BRANCH_ID
    ts.status = status
    ts.exception_flags = exception_flags if exception_flags is not None else []
    ts.rostered_minutes = rostered_minutes
    ts.actual_minutes = actual_minutes
    ts.adjusted_minutes = None
    ts.notes = None
    ts.approved_by = None
    ts.approved_at = None
    ts.locked_by = None
    ts.locked_at = None
    ts.updated_at = datetime.now(timezone.utc)
    return ts


def _make_db(existing_timesheet: MagicMock | None = None) -> AsyncMock:
    """Build an AsyncMock DB session.

    - ``execute`` returns a result whose ``scalar_one_or_none`` yields
      ``existing_timesheet`` (or None for first call when testing creation).
    - ``scalars().all()`` returns a list for bulk queries.
    """
    db = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=existing_timesheet)
    result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(return_value=result_mock)
    return db


# ---------------------------------------------------------------------------
# Tests: get_or_create_timesheet
# ---------------------------------------------------------------------------


class TestGetOrCreateTimesheet:
    """Validates lazy creation is idempotent (Requirement 1.2a)."""

    @pytest.mark.asyncio
    async def test_creates_timesheet_on_first_call(self):
        """When no existing timesheet, a new one is created."""
        db = _make_db(existing_timesheet=None)

        result = await get_or_create_timesheet(
            db,
            org_id=ORG_ID,
            staff_id=STAFF_ID,
            pay_period_id=PAY_PERIOD_ID,
            branch_id=BRANCH_ID,
        )

        # Verify a new Timesheet was added to the session
        db.add.assert_called_once()
        added_obj = db.add.call_args[0][0]
        assert added_obj.org_id == ORG_ID
        assert added_obj.staff_id == STAFF_ID
        assert added_obj.pay_period_id == PAY_PERIOD_ID
        assert added_obj.branch_id == BRANCH_ID
        assert added_obj.status == "open"
        db.flush.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_existing_on_second_call(self):
        """When a timesheet already exists, it is returned without creation."""
        existing = _make_timesheet(status="pending_approval")
        db = _make_db(existing_timesheet=existing)

        result = await get_or_create_timesheet(
            db,
            org_id=ORG_ID,
            staff_id=STAFF_ID,
            pay_period_id=PAY_PERIOD_ID,
            branch_id=BRANCH_ID,
        )

        assert result is existing
        db.add.assert_not_called()
        db.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: transition_status
# ---------------------------------------------------------------------------


class TestTransitionStatus:
    """Validates status machine transitions (Requirement 1.3, 1.4, 1.5, 1.6)."""

    @pytest.fixture(autouse=True)
    def _patch_audit(self):
        with patch("app.modules.timesheets.service.write_audit_log", new_callable=AsyncMock):
            yield

    @pytest.mark.asyncio
    async def test_valid_open_to_pending(self):
        ts = _make_timesheet(status="open")
        db = _make_db()

        result = await transition_status(
            db, timesheet=ts, new_status="pending_approval",
            actor_id=ACTOR_ID, org_id=ORG_ID,
        )

        assert ts.status == "pending_approval"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_valid_pending_to_approved(self):
        ts = _make_timesheet(status="pending_approval")
        db = _make_db()

        await transition_status(
            db, timesheet=ts, new_status="approved",
            actor_id=ACTOR_ID, org_id=ORG_ID,
        )

        assert ts.status == "approved"
        assert ts.approved_by == ACTOR_ID

    @pytest.mark.asyncio
    async def test_valid_approved_to_locked(self):
        ts = _make_timesheet(status="approved")
        db = _make_db()

        await transition_status(
            db, timesheet=ts, new_status="locked",
            actor_id=ACTOR_ID, org_id=ORG_ID,
        )

        assert ts.status == "locked"
        assert ts.locked_by == ACTOR_ID

    @pytest.mark.asyncio
    async def test_invalid_open_to_locked_raises(self):
        """open → locked is not a valid transition."""
        ts = _make_timesheet(status="open")
        db = _make_db()

        with pytest.raises(ValueError, match="Invalid status transition"):
            await transition_status(
                db, timesheet=ts, new_status="locked",
                actor_id=ACTOR_ID, org_id=ORG_ID,
            )

    @pytest.mark.asyncio
    async def test_reject_approved_to_open(self):
        """approved → open (reject) is valid."""
        ts = _make_timesheet(status="approved")
        ts.approved_by = ACTOR_ID
        ts.approved_at = datetime.now(timezone.utc)
        db = _make_db()

        await transition_status(
            db, timesheet=ts, new_status="open",
            actor_id=ACTOR_ID, org_id=ORG_ID,
        )

        assert ts.status == "open"
        assert ts.approved_by is None
        assert ts.approved_at is None

    @pytest.mark.asyncio
    async def test_locked_is_terminal(self):
        """locked → anything raises ValueError."""
        ts = _make_timesheet(status="locked")
        db = _make_db()

        with pytest.raises(ValueError, match="Invalid status transition"):
            await transition_status(
                db, timesheet=ts, new_status="open",
                actor_id=ACTOR_ID, org_id=ORG_ID,
            )


# ---------------------------------------------------------------------------
# Tests: adjust_timesheet
# ---------------------------------------------------------------------------


class TestAdjustTimesheet:
    """Validates adjustment restrictions (Requirement 3.5, 3.6)."""

    @pytest.fixture(autouse=True)
    def _patch_audit(self):
        with patch("app.modules.timesheets.service.write_audit_log", new_callable=AsyncMock):
            yield

    @pytest.mark.asyncio
    async def test_adjust_on_locked_raises(self):
        """Cannot adjust a locked timesheet."""
        ts = _make_timesheet(status="locked")
        db = _make_db()

        with pytest.raises(ValueError, match="Cannot adjust"):
            await adjust_timesheet(
                db, timesheet=ts, adjusted_minutes=500,
                notes="test", actor_id=ACTOR_ID, org_id=ORG_ID,
            )

    @pytest.mark.asyncio
    async def test_adjust_on_approved_raises(self):
        """Cannot adjust an approved timesheet."""
        ts = _make_timesheet(status="approved")
        db = _make_db()

        with pytest.raises(ValueError, match="Cannot adjust"):
            await adjust_timesheet(
                db, timesheet=ts, adjusted_minutes=500,
                notes="test", actor_id=ACTOR_ID, org_id=ORG_ID,
            )

    @pytest.mark.asyncio
    async def test_adjust_on_open_succeeds(self):
        """Adjustment on open timesheet sets the value."""
        ts = _make_timesheet(status="open")
        db = _make_db()

        await adjust_timesheet(
            db, timesheet=ts, adjusted_minutes=500,
            notes="overtime correction", actor_id=ACTOR_ID, org_id=ORG_ID,
        )

        assert ts.adjusted_minutes == 500
        assert ts.notes == "overtime correction"
        db.flush.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: bulk_approve
# ---------------------------------------------------------------------------


class TestBulkApprove:
    """Validates bulk approve skips entries with exceptions (Requirement 8.6)."""

    @pytest.mark.asyncio
    async def test_skips_entries_with_exceptions(self):
        """Timesheets with exception_flags are skipped."""
        clean_ts = _make_timesheet(status="open", exception_flags=[])
        flagged_ts = _make_timesheet(
            status="open",
            exception_flags=[{"type": "missed_shift", "detail": "no clock entry"}],
        )
        all_ts = [clean_ts, flagged_ts]

        db = AsyncMock()
        db.flush = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=all_ts)))
        db.execute = AsyncMock(return_value=result_mock)

        result = await bulk_approve(
            db, org_id=ORG_ID, pay_period_id=PAY_PERIOD_ID,
            actor_id=ACTOR_ID,
        )

        assert result["affected_count"] == 1
        assert result["skipped_count"] == 1
        assert clean_ts.status == "approved"
        assert flagged_ts.status == "open"

    @pytest.mark.asyncio
    async def test_approves_all_clean(self):
        """All clean timesheets get approved."""
        ts1 = _make_timesheet(status="open", exception_flags=[])
        ts2 = _make_timesheet(status="pending_approval", exception_flags=[])
        all_ts = [ts1, ts2]

        db = AsyncMock()
        db.flush = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=all_ts)))
        db.execute = AsyncMock(return_value=result_mock)

        result = await bulk_approve(
            db, org_id=ORG_ID, pay_period_id=PAY_PERIOD_ID,
            actor_id=ACTOR_ID,
        )

        assert result["affected_count"] == 2
        assert result["skipped_count"] == 0
        assert ts1.status == "approved"
        assert ts2.status == "approved"


# ---------------------------------------------------------------------------
# Tests: bulk_lock
# ---------------------------------------------------------------------------


class TestBulkLock:
    """Validates bulk lock only locks approved entries (Requirement 8.7)."""

    @pytest.mark.asyncio
    async def test_only_locks_approved(self):
        """Only approved timesheets are locked; the query itself filters."""
        approved_ts = _make_timesheet(status="approved")
        all_ts = [approved_ts]

        db = AsyncMock()
        db.flush = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=all_ts)))
        db.execute = AsyncMock(return_value=result_mock)

        result = await bulk_lock(
            db, org_id=ORG_ID, pay_period_id=PAY_PERIOD_ID,
            actor_id=ACTOR_ID,
        )

        assert result["affected_count"] == 1
        assert result["skipped_count"] == 0
        assert approved_ts.status == "locked"
        assert approved_ts.locked_by == ACTOR_ID

    @pytest.mark.asyncio
    async def test_no_approved_returns_zero(self):
        """When no approved timesheets exist, nothing is locked."""
        db = AsyncMock()
        db.flush = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result_mock)

        result = await bulk_lock(
            db, org_id=ORG_ID, pay_period_id=PAY_PERIOD_ID,
            actor_id=ACTOR_ID,
        )

        assert result["affected_count"] == 0
        assert result["skipped_count"] == 0
        db.flush.assert_not_awaited()
