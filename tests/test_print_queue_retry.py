"""Tests: print job retry logic exhausts retries and marks as failed.

**Validates: Requirement 22 — POS Module — Task 30.10**

Verifies that:
- A print job that always fails is retried up to MAX_RETRIES (3) times
- After exhausting retries, the job status is set to 'failed'
- The error_details field contains the last error message
- A successful dispatch on the first attempt marks the job as 'completed'
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.receipt_printer.models import PrintJob
from app.modules.receipt_printer.service import (
    MAX_RETRIES,
    PrinterService,
)


ORG_ID = uuid.uuid4()


def _make_job(**overrides) -> PrintJob:
    defaults = dict(
        id=uuid.uuid4(),
        org_id=ORG_ID,
        printer_id=uuid.uuid4(),
        job_type="receipt",
        payload={"type": "test"},
        status="pending",
        retry_count=0,
        error_details=None,
        completed_at=None,
    )
    defaults.update(overrides)
    return PrintJob(**defaults)


@pytest.mark.asyncio
@patch("app.modules.receipt_printer.service.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_exhaustion_marks_failed(mock_sleep):
    """Job that always fails should exhaust retries and be marked failed."""
    db = AsyncMock()
    svc = PrinterService(db)
    job = _make_job()

    # dispatch_fn that always raises
    async def always_fail(j):
        raise ConnectionError("Printer unreachable")

    await svc._process_single_job(job, dispatch_fn=always_fail)

    assert job.status == "failed"
    assert job.retry_count == MAX_RETRIES
    assert job.error_details == "Printer unreachable"
    assert job.completed_at is None
    # Sleep should have been called (MAX_RETRIES - 1) times (no sleep after last failure)
    assert mock_sleep.call_count == MAX_RETRIES - 1


@pytest.mark.asyncio
@patch("app.modules.receipt_printer.service.asyncio.sleep", new_callable=AsyncMock)
async def test_successful_dispatch_marks_completed(mock_sleep):
    """Job that succeeds on first attempt should be marked completed."""
    db = AsyncMock()
    svc = PrinterService(db)
    job = _make_job()

    async def succeed(j):
        pass  # no error

    await svc._process_single_job(job, dispatch_fn=succeed)

    assert job.status == "completed"
    assert job.retry_count == 0
    assert job.completed_at is not None
    assert job.error_details is None
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
@patch("app.modules.receipt_printer.service.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_succeeds_on_second_attempt(mock_sleep):
    """Job that fails once then succeeds should be completed with retry_count=1."""
    db = AsyncMock()
    svc = PrinterService(db)
    job = _make_job()

    call_count = 0

    async def fail_then_succeed(j):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Temporary failure")

    await svc._process_single_job(job, dispatch_fn=fail_then_succeed)

    assert job.status == "completed"
    assert job.retry_count == 1
    assert job.completed_at is not None
    assert mock_sleep.call_count == 1


@pytest.mark.asyncio
@patch("app.modules.receipt_printer.service.asyncio.sleep", new_callable=AsyncMock)
async def test_no_dispatch_fn_marks_completed_immediately(mock_sleep):
    """Job with no dispatch_fn (client-side printing) completes immediately."""
    db = AsyncMock()
    svc = PrinterService(db)
    job = _make_job()

    await svc._process_single_job(job, dispatch_fn=None)

    assert job.status == "completed"
    assert job.retry_count == 0
    assert job.completed_at is not None
    mock_sleep.assert_not_called()
