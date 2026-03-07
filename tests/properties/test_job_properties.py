"""Comprehensive property-based tests for job and quote properties.

Properties covered:
  P5 — Job Status Transition Validity
  P6 — Quote-to-Invoice Referential Integrity

**Validates: Requirements 5, 6**
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, assume
from hypothesis import strategies as st

from tests.properties.conftest import (
    PBT_SETTINGS,
    job_status_strategy,
    price_strategy,
    quantity_strategy,
    safe_text_strategy,
)

from app.modules.jobs_v2.models import Job
from app.modules.jobs_v2.schemas import JOB_STATUSES, VALID_TRANSITIONS
from app.modules.jobs_v2.service import InvalidStatusTransition, JobService
from app.modules.quotes_v2.models import Quote
from app.modules.quotes_v2.service import QuoteService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_job(status: str = "draft") -> Job:
    return Job(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        job_number="JOB-00001",
        title="Test Job",
        status=status,
    )


# ===========================================================================
# Property 5: Job Status Transition Validity
# ===========================================================================


class TestP5JobStatusTransitions:
    """Only valid status transitions succeed; invalid ones are rejected.

    **Validates: Requirements 5**
    """

    @given(from_status=job_status_strategy, to_status=job_status_strategy)
    @PBT_SETTINGS
    def test_valid_transitions_succeed_invalid_rejected(
        self, from_status: str, to_status: str,
    ) -> None:
        """P5: validate_transition matches VALID_TRANSITIONS map."""
        is_valid = JobService.validate_transition(from_status, to_status)
        expected = to_status in VALID_TRANSITIONS.get(from_status, [])
        assert is_valid == expected

    @given(transitions=st.lists(job_status_strategy, min_size=1, max_size=20))
    @PBT_SETTINGS
    def test_only_valid_transitions_applied(self, transitions: list[str]) -> None:
        """P5: starting from draft, only valid transitions change status."""
        import asyncio

        job = _make_job("draft")
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        async def fake_execute(stmt):
            result = MagicMock()
            result.scalar_one_or_none.return_value = job
            return result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)
        history: list[tuple[str, str]] = []

        async def run():
            for target in transitions:
                current = job.status
                if svc.validate_transition(current, target):
                    await svc.change_status(job.org_id, job.id, target)
                    history.append((current, target))
                    assert job.status == target
                else:
                    with pytest.raises(InvalidStatusTransition):
                        await svc.change_status(job.org_id, job.id, target)
                    assert job.status == current

        asyncio.run(run())

        for from_s, to_s in history:
            assert to_s in VALID_TRANSITIONS[from_s]

    @given(transitions=st.lists(job_status_strategy, min_size=1, max_size=20))
    @PBT_SETTINGS
    def test_status_history_chain_is_consistent(self, transitions: list[str]) -> None:
        """P5: simulated history chain is internally consistent."""
        current = "draft"
        valid_history: list[tuple[str, str]] = []

        for target in transitions:
            if target in VALID_TRANSITIONS.get(current, []):
                valid_history.append((current, target))
                current = target

        if valid_history:
            assert valid_history[0][0] == "draft"
            for i in range(1, len(valid_history)):
                assert valid_history[i][0] == valid_history[i - 1][1]


# ===========================================================================
# Property 6: Quote-to-Invoice Referential Integrity
# ===========================================================================

_line_item_st = st.fixed_dictionaries({
    "description": safe_text_strategy,
    "quantity": st.decimals(
        min_value=Decimal("0.01"), max_value=Decimal("999"),
        places=2, allow_nan=False, allow_infinity=False,
    ),
    "unit_price": st.decimals(
        min_value=Decimal("0.01"), max_value=Decimal("9999"),
        places=2, allow_nan=False, allow_infinity=False,
    ),
    "tax_rate": st.decimals(
        min_value=Decimal("0"), max_value=Decimal("25"),
        places=2, allow_nan=False, allow_infinity=False,
    ),
})


def _make_accepted_quote(line_items: list[dict]) -> Quote:
    serialised = []
    for item in line_items:
        serialised.append({
            "description": item["description"],
            "quantity": str(item["quantity"]),
            "unit_price": str(item["unit_price"]),
            "tax_rate": str(item["tax_rate"]),
        })
    subtotal, tax_amount, total = QuoteService._compute_totals(serialised)
    return Quote(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        quote_number="QT-00001",
        customer_id=uuid.uuid4(),
        status="accepted",
        line_items=serialised,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        version_number=1,
    )


class TestP6QuoteInvoiceLinkage:
    """Converted quote has exactly one linked invoice with matching line items.

    **Validates: Requirements 6**
    """

    @given(line_items=st.lists(_line_item_st, min_size=1, max_size=10))
    @PBT_SETTINGS
    def test_converted_quote_has_matching_invoice(
        self, line_items: list[dict],
    ) -> None:
        """P6: converted quote → one invoice with matching line items."""
        import asyncio

        async def _run():
            quote = _make_accepted_quote(line_items)
            mock_db = AsyncMock()
            mock_db.flush = AsyncMock()
            mock_db.add = MagicMock()

            result_mock = MagicMock()
            result_mock.scalar_one_or_none.return_value = quote

            async def fake_execute(stmt):
                return result_mock

            mock_db.execute = fake_execute
            svc = QuoteService(mock_db)
            result = await svc.convert_to_invoice(quote.org_id, quote.id)

            assert result["invoice_id"] is not None
            assert quote.converted_invoice_id == result["invoice_id"]
            assert quote.status == "converted"
            assert result["line_items_count"] == len(line_items)

            for original, converted in zip(quote.line_items, result["line_items"]):
                assert original["description"] == converted["description"]
                assert original["quantity"] == converted["quantity"]
                assert original["unit_price"] == converted["unit_price"]

            # Cannot convert again
            try:
                await svc.convert_to_invoice(quote.org_id, quote.id)
                assert False, "Should have raised ValueError"
            except ValueError:
                pass

        asyncio.run(_run())
