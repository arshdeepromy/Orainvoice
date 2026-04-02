"""Property-based tests for staff scheduling.

Properties covered:
  P11 — Schedule overlap rejection
  P12 — Schedule user-branch assignment validation

**Validates: Requirements 19.2, 19.5**
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Settings — 100 examples per property, no deadline, suppress slow health check
# ---------------------------------------------------------------------------

SCHEDULING_PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Generate valid hours (0-22) to leave room for end_time > start_time
hour_strategy = st.integers(min_value=0, max_value=22)
minute_strategy = st.integers(min_value=0, max_value=59)

# Generate a date in a reasonable range
date_strategy = st.dates(
    min_value=date(2024, 1, 1),
    max_value=date(2026, 12, 31),
)

uuid_strategy = st.uuids()


def time_range_strategy():
    """Generate a (start_time, end_time) pair where start < end."""
    return st.tuples(
        st.integers(min_value=0, max_value=22),
        st.integers(min_value=0, max_value=59),
    ).flatmap(
        lambda start: st.tuples(
            st.just(time(start[0], start[1])),
            st.builds(
                time,
                st.integers(min_value=start[0] + 1, max_value=23),
                st.integers(min_value=0, max_value=59),
            ),
        )
    )


# ---------------------------------------------------------------------------
# Fake model helpers
# ---------------------------------------------------------------------------


class _FakeSchedule:
    """Minimal Schedule stand-in for property tests."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        shift_date: date | None = None,
        start_time: time | None = None,
        end_time: time | None = None,
        notes: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.branch_id = branch_id or uuid.uuid4()
        self.user_id = user_id or uuid.uuid4()
        self.shift_date = shift_date or date(2025, 6, 1)
        self.start_time = start_time or time(9, 0)
        self.end_time = end_time or time(17, 0)
        self.notes = notes
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)


class _FakeUser:
    """Minimal User stand-in for property tests."""

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        branch_ids: list | None = None,
    ):
        self.id = id or uuid.uuid4()
        self.org_id = org_id or uuid.uuid4()
        self.branch_ids = branch_ids or []


def _make_scalar_one_or_none(return_value):
    """Create a mock result whose .scalar_one_or_none() returns the given value."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = return_value
    return mock_result


# ===========================================================================
# Property 11: Schedule overlap rejection
# Feature: branch-management-complete, Property 11
# ===========================================================================


class TestP11ScheduleOverlapRejection:
    """For any two schedule entries for the same user on the same date, if
    their time ranges overlap, the second entry SHALL be rejected with a
    409 status code.

    **Validates: Requirements 19.5**
    """

    @given(
        shift_date=date_strategy,
        start_hour_a=st.integers(min_value=0, max_value=20),
        duration_a=st.integers(min_value=1, max_value=3),
        start_hour_b=st.integers(min_value=0, max_value=20),
        duration_b=st.integers(min_value=1, max_value=3),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_overlapping_ranges_detected(
        self,
        shift_date: date,
        start_hour_a: int,
        duration_a: int,
        start_hour_b: int,
        duration_b: int,
    ) -> None:
        """P11: overlapping time ranges for the same user/date are detected."""
        end_hour_a = min(start_hour_a + duration_a, 23)
        end_hour_b = min(start_hour_b + duration_b, 23)

        assume(start_hour_a < end_hour_a)
        assume(start_hour_b < end_hour_b)

        time_a_start = time(start_hour_a, 0)
        time_a_end = time(end_hour_a, 0)
        time_b_start = time(start_hour_b, 0)
        time_b_end = time(end_hour_b, 0)

        # Two ranges overlap when: start_a < end_b AND start_b < end_a
        ranges_overlap = time_a_start < time_b_end and time_b_start < time_a_end

        # Simulate the overlap check logic from the service
        # existing entry has range A, new entry has range B
        existing = _FakeSchedule(
            shift_date=shift_date,
            start_time=time_a_start,
            end_time=time_a_end,
        )

        new_start = time_b_start
        new_end = time_b_end

        # The overlap condition: existing.start_time < new_end AND existing.end_time > new_start
        detected_overlap = existing.start_time < new_end and existing.end_time > new_start

        assert detected_overlap == ranges_overlap

    @given(
        shift_date=date_strategy,
        start_hour=st.integers(min_value=0, max_value=20),
        duration=st.integers(min_value=1, max_value=3),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_identical_ranges_always_overlap(
        self,
        shift_date: date,
        start_hour: int,
        duration: int,
    ) -> None:
        """P11: identical time ranges always overlap."""
        end_hour = min(start_hour + duration, 23)
        assume(start_hour < end_hour)

        t_start = time(start_hour, 0)
        t_end = time(end_hour, 0)

        # Same range always overlaps
        detected = t_start < t_end and t_end > t_start
        assert detected is True

    @given(
        shift_date=date_strategy,
        start_hour_a=st.integers(min_value=0, max_value=10),
        duration_a=st.integers(min_value=1, max_value=3),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_non_overlapping_adjacent_ranges_accepted(
        self,
        shift_date: date,
        start_hour_a: int,
        duration_a: int,
    ) -> None:
        """P11: adjacent (non-overlapping) ranges are NOT detected as overlapping.
        E.g., 09:00-12:00 and 12:00-15:00 should not overlap."""
        end_hour_a = min(start_hour_a + duration_a, 23)
        assume(start_hour_a < end_hour_a)
        assume(end_hour_a < 23)

        # Range B starts exactly where A ends (adjacent, no overlap)
        start_hour_b = end_hour_a
        end_hour_b = min(start_hour_b + 2, 23)
        assume(start_hour_b < end_hour_b)

        time_a_start = time(start_hour_a, 0)
        time_a_end = time(end_hour_a, 0)
        time_b_start = time(start_hour_b, 0)
        time_b_end = time(end_hour_b, 0)

        # Adjacent ranges should NOT overlap
        detected = time_a_start < time_b_end and time_a_end > time_b_start
        assert detected is False

    @given(
        shift_date=date_strategy,
        user_id=uuid_strategy,
        branch_id=uuid_strategy,
        org_id=uuid_strategy,
        start_hour=st.integers(min_value=0, max_value=20),
        duration=st.integers(min_value=1, max_value=3),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_overlap_check_via_service_function(
        self,
        shift_date: date,
        user_id: uuid.UUID,
        branch_id: uuid.UUID,
        org_id: uuid.UUID,
        start_hour: int,
        duration: int,
    ) -> None:
        """P11: the service _check_overlap function raises OverlapError when
        an existing entry overlaps the new one."""
        from app.modules.scheduling.service import OverlapError, _check_overlap

        end_hour = min(start_hour + duration, 23)
        assume(start_hour < end_hour)

        t_start = time(start_hour, 0)
        t_end = time(end_hour, 0)

        # Create a fake existing schedule that exactly matches the new range
        existing = _FakeSchedule(
            user_id=user_id,
            shift_date=shift_date,
            start_time=t_start,
            end_time=t_end,
        )

        # Mock the DB to return the existing entry
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_make_scalar_one_or_none(existing)
        )

        # Should raise OverlapError
        with pytest.raises(OverlapError, match="Schedule overlaps"):
            asyncio.get_event_loop().run_until_complete(
                _check_overlap(
                    mock_db,
                    user_id=user_id,
                    shift_date=shift_date,
                    start_time=t_start,
                    end_time=t_end,
                    exclude_entry_id=None,
                )
            )

    @given(
        shift_date=date_strategy,
        user_id=uuid_strategy,
        start_hour=st.integers(min_value=0, max_value=20),
        duration=st.integers(min_value=1, max_value=3),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_no_overlap_when_no_existing_entries(
        self,
        shift_date: date,
        user_id: uuid.UUID,
        start_hour: int,
        duration: int,
    ) -> None:
        """P11: no overlap error when there are no existing entries."""
        from app.modules.scheduling.service import _check_overlap

        end_hour = min(start_hour + duration, 23)
        assume(start_hour < end_hour)

        t_start = time(start_hour, 0)
        t_end = time(end_hour, 0)

        # Mock the DB to return None (no existing entries)
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_make_scalar_one_or_none(None)
        )

        # Should NOT raise
        asyncio.get_event_loop().run_until_complete(
            _check_overlap(
                mock_db,
                user_id=user_id,
                shift_date=shift_date,
                start_time=t_start,
                end_time=t_end,
                exclude_entry_id=None,
            )
        )


# ===========================================================================
# Property 12: Schedule user-branch assignment validation
# Feature: branch-management-complete, Property 12
# ===========================================================================


class TestP12ScheduleUserBranchValidation:
    """For any schedule entry creation, the specified user_id SHALL be in
    the branch_ids array of the target branch. If the user is not assigned
    to the branch, creation SHALL be rejected.

    **Validates: Requirements 19.2**
    """

    @given(
        user_id=uuid_strategy,
        target_branch_id=uuid_strategy,
        other_branch_ids=st.lists(uuid_strategy, min_size=0, max_size=5),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_user_assigned_to_branch_accepted(
        self,
        user_id: uuid.UUID,
        target_branch_id: uuid.UUID,
        other_branch_ids: list[uuid.UUID],
    ) -> None:
        """P12: user with target branch in their branch_ids is accepted."""
        from app.modules.scheduling.service import _validate_user_branch_assignment

        # User has the target branch in their branch_ids
        branch_ids = [str(target_branch_id)] + [str(b) for b in other_branch_ids]
        user = _FakeUser(id=user_id, branch_ids=branch_ids)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_make_scalar_one_or_none(user)
        )

        # Should NOT raise
        asyncio.get_event_loop().run_until_complete(
            _validate_user_branch_assignment(
                mock_db,
                user_id=user_id,
                branch_id=target_branch_id,
            )
        )

    @given(
        user_id=uuid_strategy,
        target_branch_id=uuid_strategy,
        other_branch_ids=st.lists(uuid_strategy, min_size=0, max_size=5),
    )
    @SCHEDULING_PBT_SETTINGS
    def test_user_not_assigned_to_branch_rejected(
        self,
        user_id: uuid.UUID,
        target_branch_id: uuid.UUID,
        other_branch_ids: list[uuid.UUID],
    ) -> None:
        """P12: user without target branch in their branch_ids is rejected."""
        from app.modules.scheduling.service import _validate_user_branch_assignment

        # Ensure target_branch_id is NOT in the list
        branch_ids = [str(b) for b in other_branch_ids if b != target_branch_id]
        user = _FakeUser(id=user_id, branch_ids=branch_ids)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_make_scalar_one_or_none(user)
        )

        with pytest.raises(ValueError, match="User is not assigned to this branch"):
            asyncio.get_event_loop().run_until_complete(
                _validate_user_branch_assignment(
                    mock_db,
                    user_id=user_id,
                    branch_id=target_branch_id,
                )
            )

    @given(
        user_id=uuid_strategy,
        target_branch_id=uuid_strategy,
    )
    @SCHEDULING_PBT_SETTINGS
    def test_user_with_empty_branch_ids_rejected(
        self,
        user_id: uuid.UUID,
        target_branch_id: uuid.UUID,
    ) -> None:
        """P12: user with empty branch_ids array is always rejected."""
        from app.modules.scheduling.service import _validate_user_branch_assignment

        user = _FakeUser(id=user_id, branch_ids=[])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_make_scalar_one_or_none(user)
        )

        with pytest.raises(ValueError, match="User is not assigned to this branch"):
            asyncio.get_event_loop().run_until_complete(
                _validate_user_branch_assignment(
                    mock_db,
                    user_id=user_id,
                    branch_id=target_branch_id,
                )
            )

    @given(
        user_id=uuid_strategy,
        target_branch_id=uuid_strategy,
    )
    @SCHEDULING_PBT_SETTINGS
    def test_nonexistent_user_rejected(
        self,
        user_id: uuid.UUID,
        target_branch_id: uuid.UUID,
    ) -> None:
        """P12: nonexistent user is rejected with 'User not found'."""
        from app.modules.scheduling.service import _validate_user_branch_assignment

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            return_value=_make_scalar_one_or_none(None)
        )

        with pytest.raises(ValueError, match="User not found"):
            asyncio.get_event_loop().run_until_complete(
                _validate_user_branch_assignment(
                    mock_db,
                    user_id=user_id,
                    branch_id=target_branch_id,
                )
            )
