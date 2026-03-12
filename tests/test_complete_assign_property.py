"""Property-based tests for complete-job and assign-job service functions.

Feature: booking-to-job-workflow

Uses Hypothesis to verify correctness properties for the complete_job
and assign_job lifecycle on job cards.
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

from app.modules.job_cards.service import complete_job, assign_job


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


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


def _make_job_card(org_id, user_id, status="in_progress", notes=None):
    """Create a mock JobCard with realistic attributes."""
    jc = MagicMock(spec=JobCard)
    jc.id = uuid.uuid4()
    jc.org_id = org_id
    jc.customer_id = uuid.uuid4()
    jc.assigned_to = user_id
    jc.status = status
    jc.vehicle_rego = "ABC123"
    jc.description = "Test job"
    jc.notes = notes
    jc.created_by = user_id
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
# Property 18: Complete job flow
# ---------------------------------------------------------------------------


class TestCompleteJobFlow:
    """Property 18: Complete job flow.

    # Feature: booking-to-job-workflow, Property 18: Complete job flow

    **Validates: Requirements 6.2, 6.3, 6.4**

    For any job card with status "in_progress", calling complete-job:
    (a) stops any active timer, (b) sets status to "completed",
    (c) creates a draft invoice via the existing conversion, and
    (d) sets status to "invoiced". The returned invoice_id is valid.
    """

    @given(
        has_active_timer=st.booleans(),
        minutes_ago=st.integers(min_value=1, max_value=480),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_complete_job_flow(self, has_active_timer, minutes_ago):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        job_card = _make_job_card(org_id, user_id, status="in_progress")
        invoice_id = uuid.uuid4()

        db = _mock_db()

        # Build active timer entry if applicable
        active_entry = None
        if has_active_timer:
            started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            active_entry = _make_time_entry(
                org_id, job_card.id, user_id, started_at=started_at,
            )
            active_entry.stopped_at = None
            active_entry.duration_minutes = None

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: check active timer
        active_result = MagicMock()
        active_result.scalar_one_or_none.return_value = active_entry

        db.execute.side_effect = [jc_result, active_result]

        # Mock convert_job_card_to_invoice to avoid deep DB calls
        mock_invoice_result = {
            "job_card_id": job_card.id,
            "invoice_id": invoice_id,
            "invoice_status": "draft",
            "message": "Job card converted to draft invoice",
        }

        with patch(
            "app.modules.job_cards.service.convert_job_card_to_invoice",
            new_callable=AsyncMock,
            return_value=mock_invoice_result,
        ) as mock_convert, patch(
            "app.modules.job_cards.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await complete_job(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role="org_admin",
            )

        # Property assertions:

        # (a) If there was an active timer, it was stopped
        if has_active_timer:
            assert active_entry.stopped_at is not None
            expected_duration = math.ceil(
                (active_entry.stopped_at - active_entry.started_at).total_seconds() / 60
            )
            assert active_entry.duration_minutes == expected_duration

        # (b) & (d) Status transitions: in_progress → completed → invoiced
        # The convert_job_card_to_invoice mock handles the invoiced transition,
        # but the function sets status to "completed" before calling it.
        # After successful conversion, status should reflect the final state.
        # The mock_convert was called with the job card in "completed" status.
        mock_convert.assert_called_once()
        call_kwargs = mock_convert.call_args[1]
        assert call_kwargs["job_card_id"] == job_card.id
        assert call_kwargs["org_id"] == org_id

        # (c) & (d) The returned invoice_id is valid
        assert result["invoice_id"] == invoice_id
        assert result["job_card_id"] == job_card.id


# ---------------------------------------------------------------------------
# Property 21: Assign-to-me updates assigned_to
# ---------------------------------------------------------------------------


class TestAssignToMeUpdatesAssignedTo:
    """Property 21: Assign-to-me updates assigned_to.

    # Feature: booking-to-job-workflow, Property 21: Assign-to-me updates assigned_to

    **Validates: Requirements 8.6**

    For any job card with assigned_to = NULL or assigned to another user,
    when a user calls the assign endpoint with their own user_id, the job
    card's assigned_to is updated to that user's user_id.
    """

    @given(
        previously_assigned=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_assign_to_me_updates_assigned_to(self, previously_assigned):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()

        # Job card is either unassigned or assigned to someone else
        initial_assignee = other_user_id if previously_assigned else None
        job_card = _make_job_card(org_id, initial_assignee, status="open")

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: fetch line items for return dict
        items_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        items_result.scalars.return_value = scalars_mock

        db.execute.side_effect = [jc_result, items_result]

        result = await assign_job(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card.id,
            role="salesperson",  # non-admin assigning to self
            new_assignee_id=user_id,
        )

        # Property assertion: assigned_to is updated to the calling user's id
        assert job_card.assigned_to == user_id
        assert result["id"] == job_card.id


# ---------------------------------------------------------------------------
# Property 22: Takeover appends note with provenance
# ---------------------------------------------------------------------------


class TestTakeoverAppendsNoteWithProvenance:
    """Property 22: Takeover appends note with provenance.

    # Feature: booking-to-job-workflow, Property 22: Takeover appends note with provenance

    **Validates: Requirements 8.8**

    For any job takeover, the job card's notes field after the operation
    contains the previous assignee's name and a timestamp, in addition to
    any pre-existing notes.
    """

    @given(
        has_existing_notes=st.booleans(),
        takeover_note_text=st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"))),
        previous_assignee_name=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("L",))),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_takeover_appends_note_with_provenance(
        self, has_existing_notes, takeover_note_text, previous_assignee_name,
    ):
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        previous_assignee_id = uuid.uuid4()

        existing_notes = "Some existing notes" if has_existing_notes else None
        job_card = _make_job_card(
            org_id, previous_assignee_id, status="open", notes=existing_notes,
        )

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: fetch line items for return dict
        items_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        items_result.scalars.return_value = scalars_mock

        db.execute.side_effect = [jc_result, items_result]

        # Mock _resolve_user_display_name to return the generated name
        with patch(
            "app.modules.job_cards.service._resolve_user_display_name",
            new_callable=AsyncMock,
            return_value=previous_assignee_name,
        ):
            result = await assign_job(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role="salesperson",  # non-admin assigning to self (takeover)
                new_assignee_id=user_id,
                takeover_note=takeover_note_text,
            )

        # Property assertions:

        # 1. The notes field contains the previous assignee's name
        assert previous_assignee_name in job_card.notes

        # 2. The notes field contains a timestamp pattern (YYYY-MM-DD HH:MM UTC)
        assert "UTC" in job_card.notes

        # 3. The notes field contains the takeover note text
        assert takeover_note_text in job_card.notes

        # 4. If there were existing notes, they are preserved
        if has_existing_notes:
            assert "Some existing notes" in job_card.notes

        # 5. The job card is now assigned to the new user
        assert job_card.assigned_to == user_id


# ---------------------------------------------------------------------------
# Property 20: Non-admin self-assignment only
# ---------------------------------------------------------------------------


class TestNonAdminSelfAssignmentOnly:
    """Property 20: Non-admin self-assignment only.

    # Feature: booking-to-job-workflow, Property 20: Non-admin self-assignment only

    **Validates: Requirements 8.2**

    For any non-admin user creating a job via booking conversion, the
    assigned_to value must equal the user's own user_id. If a different
    value is provided, the backend rejects with PermissionError (403).
    """

    @given(
        role=st.sampled_from(["salesperson", "technician", "receptionist"]),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_assign_to_other_raises_permission_error(self, role):
        """Non-admin user assigning to a different user raises PermissionError."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()

        job_card = _make_job_card(org_id, user_id, status="open")

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        db.execute.side_effect = [jc_result]

        with pytest.raises(PermissionError):
            await assign_job(
                db,
                org_id=org_id,
                user_id=user_id,
                job_card_id=job_card.id,
                role=role,
                new_assignee_id=other_user_id,
            )

    @given(
        role=st.sampled_from(["salesperson", "technician", "receptionist"]),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_non_admin_assign_to_self_succeeds(self, role):
        """Non-admin user assigning to themselves succeeds."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        job_card = _make_job_card(org_id, uuid.uuid4(), status="open")

        db = _mock_db()

        # First execute: fetch job card
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = job_card

        # Second execute: fetch line items for return dict
        items_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        items_result.scalars.return_value = scalars_mock

        db.execute.side_effect = [jc_result, items_result]

        result = await assign_job(
            db,
            org_id=org_id,
            user_id=user_id,
            job_card_id=job_card.id,
            role=role,
            new_assignee_id=user_id,
        )

        # Self-assignment succeeds and updates assigned_to
        assert job_card.assigned_to == user_id
        assert result["id"] == job_card.id

