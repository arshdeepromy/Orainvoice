"""Test: job attachments count toward org storage quota.

**Validates: Requirement 11.5**

Verifies that adding attachments to a job increments the
organisation's storage_used_bytes field.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.modules.jobs_v2.models import Job
from app.modules.jobs_v2.schemas import JobAttachmentCreate
from app.modules.jobs_v2.service import JobService


def _make_job() -> Job:
    return Job(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        job_number="JOB-00001",
        title="Test Job",
        status="in_progress",
    )


class TestJobAttachmentStorageQuota:
    """Validates: Requirement 11.5"""

    @pytest.mark.asyncio
    async def test_attachment_increments_storage_used(self):
        """Adding an attachment executes UPDATE to increment storage_used_bytes."""
        job = _make_job()
        mock_db = AsyncMock()
        executed_stmts: list = []

        async def fake_execute(stmt, params=None):
            if params is not None:
                executed_stmts.append({"stmt": str(stmt), "params": params})
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        svc = JobService(mock_db)
        data = JobAttachmentCreate(
            file_key="uploads/photo.jpg",
            file_name="photo.jpg",
            file_size=1_048_576,  # 1 MB
            content_type="image/jpeg",
        )
        attachment = await svc.add_attachment(job.org_id, job.id, data)

        assert attachment.file_name == "photo.jpg"
        assert attachment.file_size == 1_048_576

        # Verify the storage update SQL was executed
        storage_updates = [
            s for s in executed_stmts
            if "storage_used_bytes" in s["stmt"]
        ]
        assert len(storage_updates) == 1
        assert storage_updates[0]["params"]["size"] == 1_048_576
        assert storage_updates[0]["params"]["org_id"] == str(job.org_id)

    @pytest.mark.asyncio
    async def test_multiple_attachments_accumulate_storage(self):
        """Multiple attachments each increment storage independently."""
        job = _make_job()
        mock_db = AsyncMock()
        executed_stmts: list = []

        async def fake_execute(stmt, params=None):
            if params is not None:
                executed_stmts.append({"stmt": str(stmt), "params": params})
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = job
            return mock_result

        mock_db.execute = fake_execute
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()

        svc = JobService(mock_db)

        sizes = [500_000, 750_000, 1_200_000]
        for i, size in enumerate(sizes):
            data = JobAttachmentCreate(
                file_key=f"uploads/file_{i}.pdf",
                file_name=f"file_{i}.pdf",
                file_size=size,
                content_type="application/pdf",
            )
            await svc.add_attachment(job.org_id, job.id, data)

        storage_updates = [
            s for s in executed_stmts
            if "storage_used_bytes" in s["stmt"]
        ]
        assert len(storage_updates) == 3
        total_added = sum(s["params"]["size"] for s in storage_updates)
        assert total_added == sum(sizes)

    @pytest.mark.asyncio
    async def test_attachment_on_nonexistent_job_raises(self):
        """Adding attachment to a non-existent job raises ValueError."""
        mock_db = AsyncMock()

        async def fake_execute(stmt, params=None):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_db.execute = fake_execute
        svc = JobService(mock_db)

        data = JobAttachmentCreate(
            file_key="uploads/photo.jpg",
            file_name="photo.jpg",
            file_size=100,
        )
        with pytest.raises(ValueError, match="Job not found"):
            await svc.add_attachment(uuid.uuid4(), uuid.uuid4(), data)
