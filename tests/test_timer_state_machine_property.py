"""Property-based tests for timer state machine.

Feature: booking-to-job-workflow

Uses Hypothesis to verify correctness properties for the timer
start/stop/get lifecycle on job cards.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# Model imports required for SQLAlchemy relationship resolution
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
from app.modules.organisations.models import Branch  # noqa: F401
from app.modules.payments.models import Payment  # noqa: F401
from app.modules.inventory.models import PartSupplier  # noqa: F401
from app.modules.suppliers.models import Supplier  # noqa: F401
from app.modules.invoices.models import Invoice, LineItem  # noqa: F401
from app.modules.catalogue.models import PartsCatalogue  # noqa: F401
from app.modules.quotes.models import Quote, QuoteLineItem  # noqa: F401
from app.modules.job_cards.models import JobCard, JobCardItem, TimeEntry  # noqa: F401
from app.modules.bookings.models import Booking  # noqa: F401

from app.modules.job_cards.service import start_timer, stop_timer, get_timer_entries


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

job_statuses_for_start = st.sampled_from(["open", "in_progress"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    """Create a mock AsyncSession with standard methods."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_job_card(org_id, user_id, status="open"):
    """Create a mock JobCard with realistic attributes."""
    jc = MagicMock(spec=JobCard)
    jc.id = uuid.uuid4()
    jc.org_id = org_id
    jc.assigned_to = user_id
    jc.status = status
    jc.created_at = datetime.now(timezone.utc)
    jc.updated_at = datetime.now(timezone.utc)
    return jc


def _make_time_entry(org_id, job_card_id, user_id, started_at, stopped_at=None, duration_minutes=None):
    """Create a mock TimeEntry."""
    te = MagicMock(spec=TimeEntry)
    te.id = uuid.uuid4()
    te.org_id = org_id
    te.job_card_id = job_card_id
    te.user_id = user_id
    te.started_at = started_at
    te.stopped_at = stopped_at
    te.duration_minutes = duration_minutes
    te.hourly_rate = None
    te.notes = None
    te.created_at = datetime.now(timezone.utc)
    return te


# ---------------------------------------------------------------------------
# Property 9: Start timer creates TimeEntry
# ---------------------------------------------------------------------------


class TestStartTimerCreatesTimeEntry:
    """Property 9: Start timer creates TimeEntry.

    # Feature: booking-to-job-workflow, Property 9: Start timer creates TimeEntry

    **Validates: Requirements 4.6, 7.1**

    For any job card with no active timer, calling start-timer creates a new
    TimeEntry with started_at set to a server timestamp and stopped_at = NULL,
    and updates the job card's status to "in_progress".
    """

    @given(
        initial_status=job_statuses_for_start,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_start_timer_creates_entry(self, initial_status):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status=initial_status)

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: check active timer (none active)
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [jc_result, active_result]

        # Track what gets added to the session
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        result = await start_timer(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card.id,
            role="org_admin",
        )

        # Property assertions:
        # 1. A TimeEntry was added to the session
        assert len(added_objects) == 1
        entry = added_objects[0]
        assert isinstance(entry, TimeEntry)

        # 2. started_at is set to a server timestamp (not None)
        assert entry.started_at is not None

        # 3. stopped_at is NULL
        assert entry.stopped_at is None

        # 4. Job card status updated to in_progress
        if initial_status == "open":
            assert job_card.status == "in_progress"
        else:
            # Already in_progress, stays in_progress
            assert job_card.status == "in_progress"

        # 5. The returned dict has the correct structure
        assert result["started_at"] is not None
        assert result["stopped_at"] is None
        assert result["job_card_id"] == job_card.id
        assert result["org_id"] == org_id


# ---------------------------------------------------------------------------
# Property 10: Stop timer sets stopped_at and duration
# ---------------------------------------------------------------------------


class TestStopTimerSetsStoppedAtAndDuration:
    """Property 10: Stop timer sets stopped_at and duration.

    # Feature: booking-to-job-workflow, Property 10: Stop timer sets stopped_at and duration

    **Validates: Requirements 4.9, 7.2**

    For any job card with an active timer, calling stop-timer sets stopped_at
    to a server timestamp and duration_minutes equals
    ceil((stopped_at - started_at).total_seconds() / 60). After stopping,
    no TimeEntry for that job card has stopped_at IS NULL.
    """

    @given(
        minutes_ago=st.integers(min_value=1, max_value=480),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_stop_timer_sets_duration(self, minutes_ago):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status="in_progress")

        started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        active_entry = _make_time_entry(
            org_id, job_card.id, user_id, started_at=started_at,
        )
        # Make stopped_at and duration_minutes writable on the mock
        active_entry.stopped_at = None
        active_entry.duration_minutes = None

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: find active timer
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = active_entry

        db.execute.side_effect = [jc_result, active_result]

        result = await stop_timer(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card.id,
            role="org_admin",
        )

        # Property assertions:
        # 1. stopped_at is set (not None)
        assert active_entry.stopped_at is not None

        # 2. duration_minutes = ceil((stopped_at - started_at).total_seconds() / 60)
        expected_duration = math.ceil(
            (active_entry.stopped_at - active_entry.started_at).total_seconds() / 60
        )
        assert active_entry.duration_minutes == expected_duration

        # 3. After stopping, stopped_at IS NOT NULL (no active timer remains)
        assert active_entry.stopped_at is not None

        # 4. The returned dict reflects the stopped state
        assert result["stopped_at"] is not None
        assert result["duration_minutes"] == expected_duration


# ---------------------------------------------------------------------------
# Property 13: Double start returns 409
# ---------------------------------------------------------------------------


class TestDoubleStartReturns409:
    """Property 13: Double start returns 409.

    # Feature: booking-to-job-workflow, Property 13: Double start returns 409

    **Validates: Requirements 7.3**

    For any job card that already has an active TimeEntry (stopped_at IS NULL),
    a start-timer request returns ValueError (409) and does not create a new
    TimeEntry.
    """

    @given(
        minutes_ago=st.integers(min_value=1, max_value=480),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_double_start_raises_value_error(self, minutes_ago):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status="in_progress")

        started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        existing_active = _make_time_entry(
            org_id, job_card.id, user_id, started_at=started_at,
        )
        existing_active.stopped_at = None

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: check active timer (one exists)
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = existing_active

        db.execute.side_effect = [jc_result, active_result]

        # Track adds to verify no new entry is created
        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        with pytest.raises(ValueError, match="timer is already running"):
            await start_timer(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role="org_admin",
            )

        # No new TimeEntry should have been added
        assert len(added_objects) == 0


# ---------------------------------------------------------------------------
# Property 14: Stop with no active timer returns 404
# ---------------------------------------------------------------------------


class TestStopWithNoActiveTimerReturns404:
    """Property 14: Stop with no active timer returns 404.

    # Feature: booking-to-job-workflow, Property 14: Stop with no active timer returns 404

    **Validates: Requirements 7.4**

    For any job card that has no active TimeEntry, a stop-timer request
    returns ValueError (404).
    """

    @given(
        status=st.sampled_from(["open", "in_progress"]),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_stop_no_active_timer_raises_value_error(self, status):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status=status)

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: find active timer (none)
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [jc_result, active_result]

        with pytest.raises(ValueError, match="No active timer found"):
            await stop_timer(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role="org_admin",
            )


# ---------------------------------------------------------------------------
# Property 15: GET timer returns entries with active flag
# ---------------------------------------------------------------------------


class TestGetTimerReturnsEntriesWithActiveFlag:
    """Property 15: GET timer returns entries with active flag.

    # Feature: booking-to-job-workflow, Property 15: GET timer returns entries with active flag

    **Validates: Requirements 7.5**

    For any job card, get_timer_entries returns all TimeEntry records and
    is_active is true iff exactly one TimeEntry has stopped_at IS NULL.
    """

    @given(
        num_completed=st.integers(min_value=0, max_value=5),
        has_active=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_get_timer_entries_active_flag(self, num_completed, has_active):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card_id = uuid.uuid4()

        # Build a list of time entries
        entries = []
        base_time = datetime.now(timezone.utc) - timedelta(hours=10)

        for i in range(num_completed):
            started = base_time + timedelta(hours=i * 2)
            stopped = started + timedelta(minutes=30)
            te = _make_time_entry(
                org_id, job_card_id, user_id,
                started_at=started,
                stopped_at=stopped,
                duration_minutes=30,
            )
            entries.append(te)

        if has_active:
            active_started = base_time + timedelta(hours=num_completed * 2)
            active_te = _make_time_entry(
                org_id, job_card_id, user_id,
                started_at=active_started,
                stopped_at=None,
                duration_minutes=None,
            )
            entries.append(active_te)

        db = _mock_db()

        # Mock the query result
        query_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = entries
        query_result.scalars.return_value = scalars_mock
        db.execute.return_value = query_result

        result = await get_timer_entries(
            db,
            org_id=org_id,
            job_card_id=job_card_id,
        )

        # Property assertions:
        # 1. All entries are returned
        assert len(result["entries"]) == len(entries)

        # 2. is_active is true iff exactly one entry has stopped_at IS NULL
        expected_active = has_active
        assert result["is_active"] == expected_active

        # 3. Each entry in the result has the expected structure
        for entry_dict in result["entries"]:
            assert "id" in entry_dict
            assert "started_at" in entry_dict
            assert "stopped_at" in entry_dict
            assert "job_card_id" in entry_dict


# ---------------------------------------------------------------------------
# Property 8: Role-based timer access control
# ---------------------------------------------------------------------------


# Strategies for role-based tests
non_admin_roles = st.sampled_from(["salesperson", "technician", "receptionist"])


class TestRoleBasedTimerAccessControl:
    """Property 8: Role-based timer access control.

    # Feature: booking-to-job-workflow, Property 8: Role-based timer access control

    **Validates: Requirements 4.2, 4.3, 8.1, 8.3, 8.9**

    For any user and any job card, the timer start/stop operation succeeds
    if and only if the user's role is "org_admin" OR the job card's
    assigned_to equals the user's user_id. Otherwise, the backend returns
    403 Forbidden (PermissionError).
    """

    # --- Scenario 1: org_admin can start timer on any job card ---

    @given(
        initial_status=job_statuses_for_start,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_admin_can_start_timer_on_any_job(self, initial_status):
        """org_admin can start timer regardless of assigned_to."""
        org_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        # Job is assigned to someone else
        job_card = _make_job_card(org_id, other_user_id, status=initial_status)

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [jc_result, active_result]

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        result = await start_timer(
            db,
            org_id=org_id,
            user_id=admin_id,
            job_card_id=job_card.id,
            role="org_admin",
        )

        # Admin succeeds — a TimeEntry was created
        assert len(added_objects) == 1
        assert isinstance(added_objects[0], TimeEntry)
        assert result["started_at"] is not None
        assert result["stopped_at"] is None

    # --- Scenario 1b: org_admin can stop timer on any job card ---

    @given(
        minutes_ago=st.integers(min_value=1, max_value=480),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_admin_can_stop_timer_on_any_job(self, minutes_ago):
        """org_admin can stop timer regardless of assigned_to."""
        org_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, other_user_id, status="in_progress")

        started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        active_entry = _make_time_entry(
            org_id, job_card.id, other_user_id, started_at=started_at,
        )
        active_entry.stopped_at = None
        active_entry.duration_minutes = None

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = active_entry
        db.execute.side_effect = [jc_result, active_result]

        result = await stop_timer(
            db,
            org_id=org_id,
            user_id=admin_id,
            job_card_id=job_card.id,
            role="org_admin",
        )

        # Admin succeeds
        assert active_entry.stopped_at is not None
        assert result["stopped_at"] is not None
        assert result["duration_minutes"] is not None

    # --- Scenario 2: Non-admin can start/stop timer if assigned_to == user_id ---

    @given(
        role=non_admin_roles,
        initial_status=job_statuses_for_start,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_assigned_can_start_timer(self, role, initial_status):
        """Non-admin user can start timer on job assigned to them."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status=initial_status)

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = None
        db.execute.side_effect = [jc_result, active_result]

        added_objects = []
        db.add.side_effect = lambda obj: added_objects.append(obj)

        result = await start_timer(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card.id,
            role=role,
        )

        assert len(added_objects) == 1
        assert isinstance(added_objects[0], TimeEntry)
        assert result["started_at"] is not None

    @given(
        role=non_admin_roles,
        minutes_ago=st.integers(min_value=1, max_value=480),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_assigned_can_stop_timer(self, role, minutes_ago):
        """Non-admin user can stop timer on job assigned to them."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status="in_progress")

        started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        active_entry = _make_time_entry(
            org_id, job_card.id, user_id, started_at=started_at,
        )
        active_entry.stopped_at = None
        active_entry.duration_minutes = None

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = active_entry
        db.execute.side_effect = [jc_result, active_result]

        result = await stop_timer(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card.id,
            role=role,
        )

        assert active_entry.stopped_at is not None
        assert result["stopped_at"] is not None

    # --- Scenario 3: Non-admin on job assigned to someone else → PermissionError ---

    @given(
        role=non_admin_roles,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_cannot_start_timer_on_others_job(self, role):
        """Non-admin attempting to start timer on job assigned to another user → PermissionError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, other_user_id, status="open")

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        db.execute.side_effect = [jc_result]

        with pytest.raises(PermissionError, match="You can only start jobs assigned to you"):
            await start_timer(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role=role,
            )

    @given(
        role=non_admin_roles,
        minutes_ago=st.integers(min_value=1, max_value=480),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_cannot_stop_timer_on_others_job(self, role, minutes_ago):
        """Non-admin attempting to stop timer on job assigned to another user → PermissionError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, other_user_id, status="in_progress")

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        db.execute.side_effect = [jc_result]

        with pytest.raises(PermissionError, match="You can only stop jobs assigned to you"):
            await stop_timer(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role=role,
            )

    # --- Scenario 4: Non-admin on unassigned job → PermissionError ---

    @given(
        role=non_admin_roles,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_cannot_start_timer_on_unassigned_job(self, role):
        """Non-admin attempting to start timer on unassigned job (assigned_to=None) → PermissionError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status="open")
        job_card.assigned_to = None  # Unassigned

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        db.execute.side_effect = [jc_result]

        with pytest.raises(PermissionError, match="You can only start jobs assigned to you"):
            await start_timer(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role=role,
            )

    @given(
        role=non_admin_roles,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_cannot_stop_timer_on_unassigned_job(self, role):
        """Non-admin attempting to stop timer on unassigned job (assigned_to=None) → PermissionError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status="in_progress")
        job_card.assigned_to = None  # Unassigned

        db = _mock_db()
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card
        db.execute.side_effect = [jc_result]

        with pytest.raises(PermissionError, match="You can only stop jobs assigned to you"):
            await stop_timer(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role=role,
            )
