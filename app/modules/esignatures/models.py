"""SQLAlchemy ORM models for the ``esignatures`` module.

Maps to the four org-scoped tables created by Migration A (rev ``0232``,
``alembic/versions/2026_06_28_0002-0232_esign_schema.py``). The migration is the
source of truth for columns, defaults, constraints and indexes — these models
mirror it exactly. All four tables live under Postgres row-level security
(``tenant_isolation`` keyed on ``app.current_org_id``); ``esign_recipients`` is
scoped through its parent envelope (it carries no ``org_id`` column).

  - :class:`EsignEnvelope` — the system-of-record mapping between an OraInvoice
    document/recipient set and a Documenso document.
  - :class:`EsignRecipient` — one row per recipient, cascade-FK'd to its parent
    envelope. ``signing_role`` is stored as the UPPERCASE Documenso role
    (``SIGNER``/``VIEWER``); ``signing_url`` is nullable.
  - :class:`EsignWebhookEvent` — idempotency ledger keyed on the synthesized
    ``dedupe_key`` (``TEXT NOT NULL UNIQUE``).
  - :class:`EsignOrgConnection` — the per-organisation Documenso connection
    record (``org_id`` UNIQUE; envelope-encrypted BYTEA secrets;
    ``webhook_routing_id`` UNIQUE).

Refs: requirements 1.1, 3.2, 4.1, 4.4, 8.3, 13.1, 13.7; design §"Data Models".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EsignEnvelope(Base):
    """An e-signature envelope — the system-of-record mapping between an
    OraInvoice originating entity and a Documenso document.

    Maps to ``esign_envelopes``. CHECK constraints on ``agreement_type``,
    ``originating_entity_type``, ``status`` and ``signed_doc_status`` are pinned
    by the migration (not redeclared here).
    """

    __tablename__ = "esign_envelopes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    agreement_type: Mapped[str] = mapped_column(Text, nullable=False)
    originating_entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    originating_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
    )
    documenso_document_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="draft",
    )
    signed_doc_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="none",
    )
    signed_doc_file_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )

    # Relationships
    recipients: Mapped[list[EsignRecipient]] = relationship(
        "EsignRecipient",
        back_populates="envelope",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class EsignRecipient(Base):
    """A single recipient of an :class:`EsignEnvelope`.

    Maps to ``esign_recipients`` (cascade FK to ``esign_envelopes``). Carries no
    ``org_id``; RLS visibility is inherited through the parent envelope.
    ``signing_role`` is stored as the UPPERCASE Documenso role
    (``SIGNER``/``VIEWER``); ``signing_url`` and ``documenso_recipient_id`` are
    nullable (captured from Documenso after the document is created).
    """

    __tablename__ = "esign_recipients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    envelope_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("esign_envelopes.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    signing_role: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending",
    )
    signing_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    documenso_recipient_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # Relationships
    envelope: Mapped[EsignEnvelope] = relationship(
        "EsignEnvelope", back_populates="recipients",
    )


class EsignWebhookEvent(Base):
    """Idempotency ledger for inbound Documenso webhooks.

    Maps to ``esign_webhook_events``. ``dedupe_key`` is the synthesized
    idempotency key (the Documenso payload carries no native event id) and is
    ``TEXT NOT NULL UNIQUE``.
    """

    __tablename__ = "esign_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    event_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    documenso_document_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class EsignOrgConnection(Base):
    """The per-organisation Documenso connection record.

    Maps to ``esign_org_connections`` (one row per org: ``org_id`` UNIQUE).
    ``service_token_encrypted`` / ``webhook_secret_encrypted`` are
    envelope-encrypted BYTEA; ``webhook_routing_id`` is the opaque per-org
    routing identifier embedded in the registered Documenso callback URL
    (UNIQUE); ``is_verified`` gates sends.
    """

    __tablename__ = "esign_org_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True,
    )
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    documenso_team_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_token_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    webhook_secret_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    webhook_routing_id: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )


class EsignFieldTemplate(Base):
    """An org-scoped, named, reusable field-placement template.

    Maps to ``esign_field_templates`` (migration ``0234``). Stores **roles, not
    people** (R17.1): each entry in ``fields`` carries a ``template_role`` slot
    and ``roles`` holds the distinct ``Template_Recipient_Role`` slots, so a
    template can be re-applied to a fresh send and mapped onto that send's actual
    recipients client-side. **No recipient name or email is ever stored.**
    ``agreement_type`` optionally associates the template with one agreement type
    (R17.2). RLS visibility is keyed on ``org_id`` via the ``tenant_isolation``
    policy, identical to the other esign tables.
    """

    __tablename__ = "esign_field_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    agreement_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields: Mapped[list] = mapped_column(JSONB, nullable=False)
    roles: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
