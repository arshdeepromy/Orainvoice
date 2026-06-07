"""SQLAlchemy ORM models for the PPSR module.

Maps to the ``ppsr_searches`` table created by migration
``alembic/versions/2026_05_31_0908-0211_ppsr_module.py``. Every column
on the model mirrors a column on the migration one-to-one — the table
acts as both the per-search audit log and the 5-minute Redis-paired
cache (per design.md §3.1).

Key gap-closure columns:

  - ``options_hash`` (G30) — sha256 hex digest of the canonical-JSON
    serialisation of ``PpsrSearchOptions``. Drives the cache lookup so
    JSON-key-order doesn't break cache hits.
  - ``org_vehicle_id`` / ``global_vehicle_id`` (G13/G39) — read-side
    only; populated by ``PpsrService._resolve_vehicle_link`` without
    mutating the vehicle tables.
  - ``forgotten_at`` (G29) — payload-wipe timestamp. When set,
    ``response_encrypted`` is NULL and detail-fetch returns HTTP 410.
  - ``response_encrypted`` — envelope-encrypted CarJam response JSON
    (G31), typed ``bytes | None`` via ``LargeBinary``.

Refs: requirements R1, R3, R5; design.md §3.1, §3.3; tasks.md C1.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

__all__ = ["PpsrSearch"]


class PpsrSearch(Base):
    """One row per PPSR search — audit log + cache + vehicle link.

    Mirrors migration ``0211_ppsr_module`` column-for-column. Row-level
    security is enforced at the database layer via the
    ``tenant_isolation`` policy keyed on
    ``current_setting('app.current_org_id')``.
    """

    __tablename__ = "ppsr_searches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    rego: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # G30 — sha256(canonical_json(options)) hex digest, drives cache lookup.
    options_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # G13/G39 — read-side link to existing vehicle row; SET NULL on parent delete.
    org_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )
    global_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("global_vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # CHECK constraint at DB level enforces match IN ('Y','PY','M','PM','U','N').
    match: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    statement_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    has_warnings: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    has_ownership_data: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    # G31 — envelope-encrypted CarJam response JSON; NULL once forgotten (G26/G29).
    response_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True,
    )
    charges_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    not_found: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    carjam_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Ownership check (CarJam ``owner_check`` API product). ``owner_check_type``
    # is NULL when no ownership check was run for this search; ``owner_check_match``
    # captures whether the supplied identity matched the registered owner.
    owner_check_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_check_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    owner_check_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # G29 — payload-wipe timestamp; detail-fetch returns HTTP 410 when set.
    forgotten_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
