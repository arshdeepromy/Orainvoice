"""Add provider tracking + bounce/delivery columns to notification_log.

Phase 2 + Phase 8a of the email-provider-unification spec. The unified
``send_email()`` writes back ``provider_key`` and ``provider_message_id``
on every successful send so the admin notification log can show which
provider actually delivered each message and so the Phase 8c bounce
webhook can correlate inbound bounce events back to the originating
``notification_log`` row.

Columns (all nullable — existing rows are unaffected):

- ``provider_key VARCHAR(50)``        — populated by ``update_log_status``
  after a successful send (e.g. ``brevo``, ``sendgrid``, ``custom_smtp``).
- ``provider_message_id TEXT``        — Brevo ``messageId`` /
  SendGrid ``X-Message-Id`` / RFC 5322 SMTP ``Message-ID``. Used as the
  correlation key by bounce/delivery webhooks.
- ``bounced_at TIMESTAMPTZ``          — set by the bounce webhook when
  the row's ``provider_message_id`` matches an inbound hard/soft bounce
  event.
- ``bounce_reason TEXT``              — verbatim reason string from the
  webhook event.
- ``delivered_at TIMESTAMPTZ``        — set by the Brevo ``delivered``
  event for end-to-end delivery confirmation.

Indexes:

- ``ix_notification_log_provider_message_id`` — partial index that
  excludes the (large) NULL legacy rows; supports webhook lookup by
  message id.
- ``ix_notification_log_provider_key`` — non-partial; supports forensic
  queries grouped by provider.

HA replication
--------------
``notification_log`` was created in migration 0007 and is not on the
publication-exclusion list (``ha_config``, ``dead_letter_queue``,
``ha_event_log``, ``alembic_version``). It is already a member of
``orainvoice_ha_pub`` (and any legacy ``ora_publication`` if that's
also present), so no ``_HA_ADD_TPL`` snippet is required: additive
nullable column changes are replicated automatically by PostgreSQL
logical replication.

Idempotency
-----------
Uses raw SQL ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` and
``CREATE INDEX IF NOT EXISTS`` so a re-run of this migration on a
partially-applied environment is a no-op. Downgrade uses
``DROP INDEX IF EXISTS`` and ``DROP COLUMN IF EXISTS`` for symmetry.

Revision ID: 0195
Revises: 0194
Create Date: 2026-05-27
"""

from __future__ import annotations

from alembic import op


revision: str = "0195"
down_revision: str = "0194"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Additive nullable columns — safe on a hot table, no rewrite.
    op.execute(
        "ALTER TABLE notification_log "
        "ADD COLUMN IF NOT EXISTS provider_key VARCHAR(50)"
    )
    op.execute(
        "ALTER TABLE notification_log "
        "ADD COLUMN IF NOT EXISTS provider_message_id TEXT"
    )
    op.execute(
        "ALTER TABLE notification_log "
        "ADD COLUMN IF NOT EXISTS bounced_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE notification_log "
        "ADD COLUMN IF NOT EXISTS bounce_reason TEXT"
    )
    op.execute(
        "ALTER TABLE notification_log "
        "ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ"
    )

    # Partial index — webhook correlation lookup; excludes the (large)
    # NULL legacy rows so the index stays small.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notification_log_provider_message_id "
        "ON notification_log (provider_message_id) "
        "WHERE provider_message_id IS NOT NULL"
    )
    # Non-partial index — forensic lookup by provider.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notification_log_provider_key "
        "ON notification_log (provider_key)"
    )


def downgrade() -> None:
    # Drop indexes first so the columns are unencumbered.
    op.execute("DROP INDEX IF EXISTS ix_notification_log_provider_key")
    op.execute("DROP INDEX IF EXISTS ix_notification_log_provider_message_id")

    # Drop columns in reverse order of addition.
    op.execute(
        "ALTER TABLE notification_log DROP COLUMN IF EXISTS delivered_at"
    )
    op.execute(
        "ALTER TABLE notification_log DROP COLUMN IF EXISTS bounce_reason"
    )
    op.execute(
        "ALTER TABLE notification_log DROP COLUMN IF EXISTS bounced_at"
    )
    op.execute(
        "ALTER TABLE notification_log DROP COLUMN IF EXISTS provider_message_id"
    )
    op.execute(
        "ALTER TABLE notification_log DROP COLUMN IF EXISTS provider_key"
    )
