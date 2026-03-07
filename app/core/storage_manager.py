"""Storage quota management for per-organisation file uploads.

Provides StorageManager with methods to check, enforce, and track
storage usage against organisation quotas.

Requirements: 43.1, 43.2, 43.3
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Default quota: 5 GB in bytes
DEFAULT_QUOTA_BYTES: int = 5_368_709_120

# Warning threshold percentage
WARNING_THRESHOLD: float = 0.80


@dataclass
class StorageUsageReport:
    """Summary of an organisation's storage usage."""

    org_id: str
    used_bytes: int
    quota_bytes: int
    usage_percent: float
    remaining_bytes: int
    is_warning: bool
    is_exceeded: bool


class StorageManager:
    """Manages per-organisation storage quotas.

    All methods operate within the caller-provided async DB session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def check_quota(self, org_id: str) -> StorageUsageReport:
        """Return current storage usage report for an organisation."""
        row = await self._session.execute(
            text(
                "SELECT storage_used_bytes, storage_quota_bytes "
                "FROM organisations WHERE id = :org_id"
            ),
            {"org_id": org_id},
        )
        result = row.one_or_none()
        if result is None:
            raise HTTPException(status_code=404, detail="Organisation not found")

        used = result.storage_used_bytes or 0
        quota = result.storage_quota_bytes or DEFAULT_QUOTA_BYTES
        percent = (used / quota * 100) if quota > 0 else 0.0

        return StorageUsageReport(
            org_id=org_id,
            used_bytes=used,
            quota_bytes=quota,
            usage_percent=round(percent, 2),
            remaining_bytes=max(0, quota - used),
            is_warning=percent >= WARNING_THRESHOLD * 100,
            is_exceeded=used >= quota,
        )

    async def increment_usage(self, org_id: str, file_size_bytes: int) -> StorageUsageReport:
        """Add file_size_bytes to the organisation's storage usage."""
        await self._session.execute(
            text(
                "UPDATE organisations "
                "SET storage_used_bytes = COALESCE(storage_used_bytes, 0) + :size "
                "WHERE id = :org_id"
            ),
            {"org_id": org_id, "size": file_size_bytes},
        )
        return await self.check_quota(org_id)

    async def decrement_usage(self, org_id: str, file_size_bytes: int) -> StorageUsageReport:
        """Subtract file_size_bytes from the organisation's storage usage.

        Clamps to zero to avoid negative values.
        """
        await self._session.execute(
            text(
                "UPDATE organisations "
                "SET storage_used_bytes = GREATEST(0, COALESCE(storage_used_bytes, 0) - :size) "
                "WHERE id = :org_id"
            ),
            {"org_id": org_id, "size": file_size_bytes},
        )
        return await self.check_quota(org_id)

    async def get_usage_report(self, org_id: str) -> StorageUsageReport:
        """Alias for check_quota — returns a full usage report."""
        return await self.check_quota(org_id)

    async def enforce_quota(self, org_id: str, incoming_file_size: int) -> None:
        """Raise HTTP 413 if the upload would exceed the organisation's quota.

        Call this before accepting a file upload (attachments, logos,
        receipts, compliance docs).
        """
        report = await self.check_quota(org_id)

        if report.used_bytes + incoming_file_size > report.quota_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "error": "storage_quota_exceeded",
                    "message": (
                        "Upload rejected: organisation storage quota exceeded. "
                        "Delete unused files or upgrade your plan."
                    ),
                    "used_bytes": report.used_bytes,
                    "quota_bytes": report.quota_bytes,
                    "usage_percent": report.usage_percent,
                    "incoming_bytes": incoming_file_size,
                    "remaining_bytes": report.remaining_bytes,
                },
            )

        if report.is_warning:
            logger.warning(
                "Organisation %s at %.1f%% storage usage (%d / %d bytes)",
                org_id,
                report.usage_percent,
                report.used_bytes,
                report.quota_bytes,
            )
