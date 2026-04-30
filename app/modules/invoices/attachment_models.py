"""SQLAlchemy ORM model for invoice attachments.

Tables:
- invoice_attachments: file attachments linked to invoices (RLS enabled)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InvoiceAttachment(Base):
    """File attachment linked to an invoice.

    Stores metadata for images (JPEG, PNG, WebP, GIF) and PDFs attached
    to invoices. The actual file content is stored encrypted on disk
    at the path specified by file_key.
    """

    __tablename__ = "invoice_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id"),
        nullable=False,
    )
    file_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Path to encrypted file on disk",
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Original filename",
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Size in bytes after compression/encryption",
    )
    mime_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="MIME type, e.g. image/jpeg, application/pdf",
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    invoice = relationship("Invoice", backref="attachments")
    organisation = relationship("Organisation", backref="invoice_attachments")
    uploaded_by_user = relationship(
        "User",
        foreign_keys=[uploaded_by],
        backref="uploaded_invoice_attachments",
    )
