"""Pydantic schemas for quote attachments.

Mirrors the invoice attachment schemas with quote-specific naming.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class QuoteAttachmentResponse(BaseModel):
    """Response schema for a single quote attachment."""

    id: uuid.UUID
    file_name: str
    mime_type: str
    file_size: int
    created_at: datetime
    uploaded_by_name: str | None = None


class QuoteAttachmentListResponse(BaseModel):
    """Response schema for listing quote attachments."""

    attachments: list[QuoteAttachmentResponse]
    total: int
