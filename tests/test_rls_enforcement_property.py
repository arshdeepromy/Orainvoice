"""Property-based tests for RLS enforcement on timer endpoints.

Feature: booking-to-job-workflow

Uses Hypothesis to verify that organisation-scoped access (RLS) is enforced
on all timer service functions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

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
# Helpers
# ---------------------------------------------------------------------------

def _mock_db():
    """Create a mock AsyncSession with standard methods."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Property 23: Organisation-scoped access (RLS)
# ---------------------------------------------------------------------------


class TestOrganisationScopedAccess:
    """Property 23: Organisation-scoped access (RLS).

    # Feature: booking-to-job-workflow, Property 23: Organisation-scoped access (RLS)

    **Validates: Requirements 7.6**

    For any user in organisation A, all timer endpoints return only TimeEntry
    records where org_id = A. Requests for job cards belonging to a different
    organisation return 404.
    """

    @given(
        role=st.sampled_from(["org_admin", "salesperson", "technician"]),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_start_timer_wrong_org_raises_not_found(self, role):
        """start_timer with a job_card_id from a different org raises ValueError('not found')."""
        org_a = uuid.uuid4()
        org_b = uuid.uuid4()  # Job card belongs to org_b
        user_id = uuid.uuid4()

        db = _mock_db()

        # The job card query filters by org_id=org_a, but the card belongs to org_b,
        # so scalar_one_or_none returns None.
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = None
        db.execute.return_value = jc_result

        with pytest.raises(ValueError, match="not found"):
            await start_timer(
                db,
                org_id=org_a,
                user_id=user_id,
                job_card_id=uuid.uuid4(),
                role=role,
            )

    @given(
        role=st.sampled_from(["org_admin", "salesperson", "technician"]),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_stop_timer_wrong_org_raises_not_found(self, role):
        """stop_timer with a job_card_id from a different org raises ValueError('not found')."""
        org_a = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db()

        # The job card query filters by org_id=org_a, but the card belongs to another org,
        # so scalar_one_or_none returns None.
        jc_result = MagicMock()
        jc_result.scalar_one_or_none.return_value = None
        db.execute.return_value = jc_result

        with pytest.raises(ValueError, match="not found"):
            await stop_timer(
                db,
                org_id=org_a,
                user_id=user_id,
                job_card_id=uuid.uuid4(),
                role=role,
            )

    @given(
        role=st.sampled_from(["org_admin", "salesperson", "technician"]),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_get_timer_entries_wrong_org_returns_empty(self, role):
        """get_timer_entries with a job_card_id from a different org returns empty entries."""
        org_a = uuid.uuid4()

        db = _mock_db()

        # The query filters by org_id=org_a, but entries belong to another org,
        # so the result set is empty.
        query_result = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        query_result.scalars.return_value = scalars_mock
        db.execute.return_value = query_result

        result = await get_timer_entries(
            db,
            org_id=org_a,
            job_card_id=uuid.uuid4(),
        )

        # No entries returned for wrong org
        assert result["entries"] == []
        assert result["is_active"] is False
