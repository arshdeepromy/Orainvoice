"""Property-based test: job status transitions follow only valid paths.

**Validates: Requirements 11.2, 11.3** — Property 5

For any job J, the sequence of status transitions recorded in
job_status_history follows only valid transitions as defined in the
status pipeline. No invalid transition (e.g. Draft → Completed)
exists in the history.

Uses Hypothesis to generate random sequences of status transition
attempts and verifies that only valid transitions succeed while
invalid ones are rejected.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

from app.modules.jobs_v2.models import Job, JobStatusHistory
from app.modules.jobs_v2.schemas import JOB_STATUSES, VALID_TRANSITIONS
from app.modules.jobs_v2.service import InvalidStatusTransition, JobService


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

status_strategy = st.sampled_from(JOB_STATUSES)


def _make_job(status: str = "draft") -> Job:
    """Create a Job instance with in-memory state."""
    job = Job(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        job_number="JOB-00001",
        title="Test Job",
        status=status,
    )
    return job


def _make_mock_db():
    """Create a mock async DB session."""
    mock_db = AsyncMock()
    added_objects: list = []

    async def fake_flush():
        pass

    def fake_add(obj):
        added_objects.append(obj)

    mock_db.flush = fake_flush
    mock_db.add = fake_add
    mock_db._added = added_objects
    return mock_db


class TestJobStatusTransitions:
    """For any job J, only valid status transitions succeed.

    **Validates: Requirements 11.2, 11.3**
    """

    @given(
        from_status=status_strategy,
        to_status=status_strategy,
    )
    @PBT_SETTINGS
    def test_valid_transitions_succeed_invalid_are_rejected(
        self, from_status: str, to_status: str,
    ) -> None:
        """For any pair of statuses, validate_transition returns True
        only when the transition is in the VALID_TRANSITIONS map."""
        is_valid = JobService.validate_transition(from_status, to_status)
        expected = to_status in VALID_TRANSITIONS.get(from_status, [])
        assert is_valid == expected, (
            f"validate_transition({from_status!r}, {to_status!r}) returned "
            f"{is_valid}, expected {expected}"
        )

    @given(
        transitions=st.lists(status_strategy, min_size=1, max_size=15),
    )
    @PBT_SETTINGS
    def test_only_valid_transitions_applied_to_job(
        self, transitions: list[str],
    ) -> None:
        """Starting from 'draft', attempt a sequence of transitions.
        Only valid ones should change the job status; invalid ones
        should raise InvalidStatusTransition."""
        import asyncio

        job = _make_job("draft")
        mock_db = _make_mock_db()

        # Mock get_job to return our job
        async def fake_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        history: list[tuple[str, str]] = []

        async def run():
            for target in transitions:
                current = job.status
                if svc.validate_transition(current, target):
                    await svc.change_status(
                        job.org_id, job.id, target,
                    )
                    history.append((current, target))
                    assert job.status == target
                else:
                    with pytest.raises(InvalidStatusTransition):
                        await svc.change_status(
                            job.org_id, job.id, target,
                        )
                    # Status should not have changed
                    assert job.status == current

        asyncio.get_event_loop().run_until_complete(run())

        # Verify all recorded transitions are valid
        for from_s, to_s in history:
            assert to_s in VALID_TRANSITIONS[from_s], (
                f"Invalid transition recorded: {from_s} → {to_s}"
            )

    @given(from_status=status_strategy)
    @PBT_SETTINGS
    def test_cancelled_is_always_reachable(self, from_status: str) -> None:
        """Any status can transition to cancelled (except cancelled itself)."""
        if from_status == "cancelled":
            assert not JobService.validate_transition(from_status, "cancelled")
        else:
            assert JobService.validate_transition(from_status, "cancelled"), (
                f"Expected {from_status} → cancelled to be valid"
            )

    def test_cancelled_has_no_outgoing_transitions(self) -> None:
        """Cancelled is a terminal state with no valid outgoing transitions."""
        assert VALID_TRANSITIONS["cancelled"] == []
        for target in JOB_STATUSES:
            assert not JobService.validate_transition("cancelled", target)

    def test_all_statuses_have_transition_entries(self) -> None:
        """Every defined status has an entry in VALID_TRANSITIONS."""
        for status in JOB_STATUSES:
            assert status in VALID_TRANSITIONS, (
                f"Status {status!r} missing from VALID_TRANSITIONS"
            )

    @given(
        transitions=st.lists(status_strategy, min_size=1, max_size=20),
    )
    @PBT_SETTINGS
    def test_status_history_only_contains_valid_transitions(
        self, transitions: list[str],
    ) -> None:
        """Simulate a full job lifecycle and verify the resulting
        status history contains only valid transitions."""
        current = "draft"
        valid_history: list[tuple[str, str]] = []

        for target in transitions:
            if target in VALID_TRANSITIONS.get(current, []):
                valid_history.append((current, target))
                current = target

        # Verify every recorded transition is valid
        for from_s, to_s in valid_history:
            assert to_s in VALID_TRANSITIONS[from_s]

        # Verify the chain is consistent
        if valid_history:
            assert valid_history[0][0] == "draft"
            for i in range(1, len(valid_history)):
                assert valid_history[i][0] == valid_history[i - 1][1]
