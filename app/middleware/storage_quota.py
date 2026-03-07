"""Storage quota enforcement dependency for file upload endpoints.

Provides a FastAPI dependency ``enforce_storage_quota`` that checks
the organisation's storage usage before accepting file uploads.
Returns HTTP 413 with usage details when quota is exceeded.

Requirements: 43.1, 43.2, 43.3
"""

from __future__ import annotations

import logging
from typing import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.storage_manager import StorageManager

logger = logging.getLogger(__name__)


async def enforce_storage_quota(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> StorageManager:
    """FastAPI dependency that enforces storage quota on upload endpoints.

    Reads Content-Length from the request to estimate file size.
    If the organisation's quota would be exceeded, raises HTTP 413.

    Returns the StorageManager instance so the endpoint can call
    ``increment_usage()`` after a successful upload.

    Usage::

        @router.post("/upload")
        async def upload(
            file: UploadFile,
            storage: StorageManager = Depends(enforce_storage_quota),
        ):
            # file accepted — storage quota was checked
            ...
            await storage.increment_usage(org_id, file_size)
    """
    org_id = getattr(request.state, "org_id", None)
    if org_id is None:
        # No org context (e.g. public endpoint) — skip quota check
        return StorageManager(db)

    content_length = request.headers.get("content-length")
    incoming_size = int(content_length) if content_length else 0

    manager = StorageManager(db)

    if incoming_size > 0:
        await manager.enforce_quota(str(org_id), incoming_size)

    return manager


def storage_quota_check(file_size_bytes: int) -> Callable:
    """Factory for a dependency that checks a specific file size against quota.

    Use when the file size is known from the request body (e.g. base64 payload)
    rather than Content-Length.

    Usage::

        @router.post("/attachments")
        async def add_attachment(
            payload: AttachmentCreate,
            storage: StorageManager = Depends(storage_quota_check(payload.file_size)),
        ):
            ...
    """

    async def _check(
        request: Request,
        db: AsyncSession = Depends(get_db_session),
    ) -> StorageManager:
        org_id = getattr(request.state, "org_id", None)
        if org_id is None:
            return StorageManager(db)

        manager = StorageManager(db)
        await manager.enforce_quota(str(org_id), file_size_bytes)
        return manager

    return _check
