"""Add send-email-modal audit columns to notification_log.

Data Models §2 of the send-email-modal spec (R11.1). Adds six columns to
``notification_log`` so a modal-originated send records whether the user
edited the default subject/body before sending, a SHA-256 hash of the
*final* (post-sanitisation) edited value — never the raw content — and the
cc/bcc recipient lists when they differ from the surface defaults.

Columns:

- ``subject_was_edited BOOLEAN NOT NULL DEFAULT false`` — set true when the
  user changed the subject from the rendered default.
- ``body_was_edited BOOLEAN NOT NULL DEFAULT false`` — set true when the
  user changed the body from the rendered default.
- ``edited_subject_hash VARCHAR(64)`` (nullable) — SHA-256 hex digest of the
  final subject string when edited; NULL otherwise.
- ``edited_body_hash VARCHAR(64)`` (nullable) — SHA-256 hex digest of the
  final, sanitised body HTML when edited; NULL otherwise.
- ``cc_recipients JSONB NOT NULL DEFAULT '[]'::jsonb`` — the cc list sent.
- ``bcc_recipients JSONB NOT NULL DEFAULT '[]'::jsonb`` — the bcc list sent.

The two booleans and two JSONB columns carry a ``server_default`` so the
``NOT NULL`` add is safe on existing rows (no rewrite, no backfill needed —
PostgreSQL stores the constant default in catalog for additive columns).
Empty cc/bcc persist as the JSONB array ``[]``, never ``null`` (R11.5).

No index is added (these columns are written for audit and read per-row via
the notification-log serializer), so no ``CREATE INDEX CONCURRENTLY`` /
``autocommit_block`` is required per the database-migration-checklist.

HA replication
--------------
``notification_log`` is already a member of ``orainvoice_ha_pub`` and is not
on the publication-exclusion list, so these additive nullable-or-defaulted
columns replicate automatically — no ``_HA_ADD_TPL`` snippet required.

template_type allowed list
--------------------------
There is no DB-level CHECK constraint on
``notification_templates.template_type`` (the model only constrains
``channel``); the allowed-type list is enforced in the Pydantic/service
layer via ``EMAIL_TEMPLATE_TYPES`` in
``app/modules/notifications/schemas.py``. The three new template types
(``invoice_payment_link``, ``customer_statement``, ``portal_link``) are
therefore added there, not via DDL here. If a CHECK is added later, this
migration is where it would be extended.

Revision ID: 0214
Revises: 0213
Create Date: 2026-06-06
"""

from __future__ import annotations

import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0214"
down_revision: str = "0213"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.add_column(
        "notification_log",
        sa.Column(
            "subject_was_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "notification_log",
        sa.Column(
            "body_was_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "notification_log",
        sa.Column("edited_subject_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "notification_log",
        sa.Column("edited_body_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "notification_log",
        sa.Column(
            "cc_recipients",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "notification_log",
        sa.Column(
            "bcc_recipients",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    logger.info(
        "[0214] notification_log gained 6 send-email-modal audit columns"
    )


def downgrade() -> None:
    # Drop in reverse order of addition.
    for col in (
        "bcc_recipients",
        "cc_recipients",
        "edited_body_hash",
        "edited_subject_hash",
        "body_was_edited",
        "subject_was_edited",
    ):
        op.drop_column("notification_log", col)
    logger.info("[0214-DOWN] notification_log audit columns dropped")
