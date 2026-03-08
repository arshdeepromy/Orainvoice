"""PrinterService — printer configuration and print queue management.

**Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.receipt_printer.models import PrinterConfig, PrintJob
from app.modules.receipt_printer.schemas import (
    PrinterConfigCreate,
    PrinterConfigUpdate,
    PrintJobCreate,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class PrinterService:
    """Manages printer configuration and print job queue."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Printer configuration
    # ------------------------------------------------------------------

    async def configure_printer(
        self, org_id: uuid.UUID, data: PrinterConfigCreate,
    ) -> PrinterConfig:
        """Create a new printer configuration."""
        # If this printer is set as default, unset other defaults first
        if data.is_default:
            await self._clear_default(org_id)

        printer = PrinterConfig(
            org_id=org_id,
            name=data.name,
            connection_type=data.connection_type,
            address=data.address,
            paper_width=data.paper_width,
            is_default=data.is_default,
            is_kitchen_printer=data.is_kitchen_printer,
            location_id=data.location_id,
        )
        self.db.add(printer)
        await self.db.flush()
        return printer

    async def update_printer(
        self, org_id: uuid.UUID, printer_id: uuid.UUID, data: PrinterConfigUpdate,
    ) -> PrinterConfig:
        """Update an existing printer configuration."""
        printer = await self._get_printer(org_id, printer_id)
        if printer is None:
            raise ValueError("Printer not found")

        update_data = data.model_dump(exclude_unset=True)
        if update_data.get("is_default"):
            await self._clear_default(org_id)

        for field, value in update_data.items():
            setattr(printer, field, value)
        await self.db.flush()
        return printer

    async def list_printers(self, org_id: uuid.UUID) -> list[PrinterConfig]:
        """List all printers for an organisation."""
        result = await self.db.execute(
            select(PrinterConfig)
            .where(PrinterConfig.org_id == org_id)
            .order_by(PrinterConfig.created_at),
        )
        return list(result.scalars().all())

    async def get_default_printer(self, org_id: uuid.UUID) -> PrinterConfig | None:
        """Get the default printer for an organisation."""
        result = await self.db.execute(
            select(PrinterConfig).where(
                PrinterConfig.org_id == org_id,
                PrinterConfig.is_default.is_(True),
                PrinterConfig.is_active.is_(True),
            ),
        )
        return result.scalar_one_or_none()

    async def delete_printer(
        self, org_id: uuid.UUID, printer_id: uuid.UUID,
    ) -> None:
        """Deactivate a printer (soft delete)."""
        printer = await self._get_printer(org_id, printer_id)
        if printer is None:
            raise ValueError("Printer not found")
        printer.is_active = False
        await self.db.flush()

    # ------------------------------------------------------------------
    # Test print
    # ------------------------------------------------------------------

    async def test_print(self, org_id: uuid.UUID, printer_id: uuid.UUID) -> PrintJob:
        """Queue a test print job for a printer."""
        printer = await self._get_printer(org_id, printer_id)
        if printer is None:
            raise ValueError("Printer not found")

        payload = {
            "type": "test",
            "org_name": "Test Print",
            "lines": [
                "================================",
                "     PRINTER TEST PAGE",
                "================================",
                f"Printer: {printer.name}",
                f"Paper: {printer.paper_width}mm",
                f"Connection: {printer.connection_type}",
                "================================",
                "  If you can read this,",
                "  your printer is working!",
                "================================",
            ],
        }
        return await self.queue_print_job(
            org_id, PrintJobCreate(printer_id=printer_id, job_type="receipt", payload=payload),
        )

    # ------------------------------------------------------------------
    # Print queue
    # ------------------------------------------------------------------

    async def queue_print_job(
        self, org_id: uuid.UUID, data: PrintJobCreate,
    ) -> PrintJob:
        """Add a print job to the queue."""
        job = PrintJob(
            org_id=org_id,
            printer_id=data.printer_id,
            job_type=data.job_type,
            payload=data.payload,
            status="pending",
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def get_print_jobs(
        self, org_id: uuid.UUID, status: str | None = None, limit: int = 50,
    ) -> list[PrintJob]:
        """List print jobs, optionally filtered by status."""
        stmt = select(PrintJob).where(PrintJob.org_id == org_id)
        if status:
            stmt = stmt.where(PrintJob.status == status)
        stmt = stmt.order_by(PrintJob.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def process_print_queue(self, org_id: uuid.UUID) -> list[PrintJob]:
        """Process pending print jobs with retry logic.

        Each job gets up to MAX_RETRIES attempts with RETRY_DELAY_SECONDS
        between retries. Jobs that exhaust retries are marked as 'failed'.
        """
        result = await self.db.execute(
            select(PrintJob).where(
                PrintJob.org_id == org_id,
                PrintJob.status == "pending",
            ).order_by(PrintJob.created_at),
        )
        pending_jobs = list(result.scalars().all())
        processed: list[PrintJob] = []

        for job in pending_jobs:
            await self._process_single_job(job)
            processed.append(job)

        await self.db.flush()
        return processed

    async def retry_job(self, org_id: uuid.UUID, job_id: uuid.UUID) -> PrintJob:
        """Retry a specific failed print job."""
        result = await self.db.execute(
            select(PrintJob).where(
                PrintJob.id == job_id,
                PrintJob.org_id == org_id,
            ),
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise ValueError("Print job not found")
        if job.status != "failed":
            raise ValueError("Only failed jobs can be retried")
        job.status = "pending"
        job.retry_count = 0
        job.error_details = None
        await self.db.flush()
        return job

    async def _process_single_job(
        self,
        job: PrintJob,
        dispatch_fn: object | None = None,
    ) -> None:
        """Attempt to process a single print job with retries.

        Args:
            job: The print job to process.
            dispatch_fn: Optional async callable that performs the actual
                print dispatch. If it raises, the job is retried. When
                ``None`` the job is marked completed immediately (actual
                printing is handled client-side).
        """
        while job.retry_count < MAX_RETRIES:
            try:
                job.status = "printing"
                if dispatch_fn is not None:
                    await dispatch_fn(job)  # type: ignore[operator]
                job.status = "completed"
                job.completed_at = datetime.now(timezone.utc)
                return
            except (ConnectionError, TimeoutError, OSError) as exc:
                logger.error("Print dispatch failed for job %s (attempt %d): %s", job.id, job.retry_count + 1, exc, exc_info=True)
                job.retry_count += 1
                job.error_details = str(exc)
                if job.retry_count >= MAX_RETRIES:
                    job.status = "failed"
                    return
                await asyncio.sleep(RETRY_DELAY_SECONDS)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_printer(
        self, org_id: uuid.UUID, printer_id: uuid.UUID,
    ) -> PrinterConfig | None:
        result = await self.db.execute(
            select(PrinterConfig).where(
                PrinterConfig.id == printer_id,
                PrinterConfig.org_id == org_id,
            ),
        )
        return result.scalar_one_or_none()

    async def _clear_default(self, org_id: uuid.UUID) -> None:
        """Unset is_default on all printers for the org."""
        await self.db.execute(
            update(PrinterConfig)
            .where(PrinterConfig.org_id == org_id, PrinterConfig.is_default.is_(True))
            .values(is_default=False),
        )
