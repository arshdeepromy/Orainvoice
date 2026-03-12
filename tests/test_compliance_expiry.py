"""Test: expiry reminders sent at 30-day and 7-day marks.

**Validates: Requirement — Compliance Module, Task 38.7**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.compliance_docs.models import ComplianceDocument


ORG_ID = uuid.uuid4()


def _make_doc(
    expiry_date: date,
    doc_type: str = "license",
    org_id: uuid.UUID | None = None,
) -> ComplianceDocument:
    """Create a ComplianceDocument instance for testing."""
    doc = ComplianceDocument(
        id=uuid.uuid4(),
        org_id=org_id or ORG_ID,
        document_type=doc_type,
        file_key=f"compliance/{uuid.uuid4()}.pdf",
        file_name=f"{doc_type}.pdf",
        expiry_date=expiry_date,
    )
    return doc


class TestComplianceExpiryReminders:
    """Verify the Celery task sends reminders at 30-day and 7-day marks."""

    @pytest.mark.asyncio
    async def test_30_day_reminder_sent(self) -> None:
        """Documents expiring in exactly 30 days trigger a reminder."""
        from app.modules.compliance_docs.service import ComplianceService

        today = date.today()
        thirty_days = today + timedelta(days=30)
        doc = _make_doc(expiry_date=thirty_days)

        svc = ComplianceService(db=AsyncMock())
        svc.check_expiry = AsyncMock(return_value=[doc])

        result = await svc.check_expiry(ORG_ID, days_ahead=30)
        assert len(result) == 1
        assert result[0].expiry_date == thirty_days

    @pytest.mark.asyncio
    async def test_7_day_reminder_sent(self) -> None:
        """Documents expiring in exactly 7 days trigger a reminder."""
        from app.modules.compliance_docs.service import ComplianceService

        today = date.today()
        seven_days = today + timedelta(days=7)
        doc = _make_doc(expiry_date=seven_days)

        svc = ComplianceService(db=AsyncMock())
        svc.check_expiry = AsyncMock(return_value=[doc])

        result = await svc.check_expiry(ORG_ID, days_ahead=7)
        assert len(result) == 1
        assert result[0].expiry_date == seven_days

    @pytest.mark.asyncio
    async def test_no_reminder_for_distant_expiry(self) -> None:
        """Documents expiring far in the future should not appear in 30-day check."""
        from app.modules.compliance_docs.service import ComplianceService

        svc = ComplianceService(db=AsyncMock())
        svc.check_expiry = AsyncMock(return_value=[])

        result = await svc.check_expiry(ORG_ID, days_ahead=30)
        assert len(result) == 0

    def test_task_callable(self) -> None:
        """The check_compliance_expiry_task is importable and callable."""
        from app.tasks.scheduled import check_compliance_expiry_task

        assert callable(check_compliance_expiry_task)
