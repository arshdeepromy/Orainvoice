"""Create bounced_addresses table for the bounce-correlation blocklist.

Phase 8c (task 9.1) of the email-provider-unification spec. The
``bounced_addresses`` table backs ``_check_bounce_blocklist`` in
``app/integrations/email_sender.py`` (the pre-send check that
short-circuits delivery to known-bad recipients) and stores rows
upserted by the Brevo / SendGrid bounce webhook handlers. See design
doc Data Model > Phase 8c for the full schema rationale.

Schema overview
---------------

- ``id``                — UUID PK, auto-generated.
- ``org_id``            — UUID, **nullable**. NULL means platform-wide
                          (visible to every org); a non-NULL value
                          scopes the row to that organisation.
- ``email_address``     — TEXT, the bounced recipient address.
- ``bounce_kind``       — VARCHAR(10), one of ``hard``, ``soft``, ``blocked``.
                          Hard bounces never expire; soft/blocked have
                          ``expires_at`` set to seven days out by the
                          webhook handler.
- ``reason``            — TEXT, verbatim from the webhook event.
- ``first_seen_at`` /
  ``last_seen_at``      — TIMESTAMPTZ, set by the upsert. ``last_seen_at``
                          bumps on every duplicate event.
- ``hit_count``         — INT, incremented on every duplicate event.
- ``expires_at``        — TIMESTAMPTZ nullable; daily cleanup task
                          deletes rows where this is in the past.

Indexes
-------

- Functional unique index on
  ``(COALESCE(org_id::text, ''), LOWER(email_address))`` — one row per
  ``(org, address)``. The COALESCE handles the nullable ``org_id``
  (PG treats NULL values as distinct in a UNIQUE constraint, which
  would let two NULL-org rows coexist for the same address).
  Functional unique indexes require PG 11+, all envs are PG 16.
- ``ix_bounced_addresses_email`` — non-unique, lowercased lookup for
  the pre-send blocklist check.
- ``ix_bounced_addresses_expires`` — partial; daily cleanup query
  filters ``expires_at IS NOT NULL AND expires_at < now()``.

RLS
---

Enabled with the project's standard ``<table>_org_isolation`` policy
shape. The predicate accepts both NULL ``org_id`` rows (platform-wide
blocks visible to every tenant) and rows whose ``org_id`` matches the
current request's ``app.current_org_id`` setting:

    org_id IS NULL OR org_id = current_setting('app.current_org_id')::uuid

The pre-send blocklist check in ``email_sender.py`` already mirrors
this predicate at the SQLAlchemy level so the RLS layer is purely
defence-in-depth.

HA replication
--------------

Added to the legacy ``ora_publication`` via the project's standard
``_HA_ADD_TPL`` snippet. The newer ``orainvoice_ha_pub`` publication
is configured to FOR ALL TABLES so no explicit add is required there
(matching the pattern used by 0185 and 0190).

Idempotency
-----------

All DDL is wrapped with ``IF NOT EXISTS`` / ``DROP POLICY IF EXISTS``
guards so a re-run on a partially-applied environment is a no-op.

Revision ID: 0197
Revises: 0196
Create Date: 2026-05-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0197"
down_revision: str = "0196"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


_TABLE = "bounced_addresses"


_HA_ADD_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

_HA_DROP_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'ora_publication' AND tablename = '{table}'
    ) THEN
        ALTER PUBLICATION ora_publication DROP TABLE {table};
    END IF;
END
$ha_block$
"""


def upgrade() -> None:
    # ── 1. Create the table (idempotent CREATE TABLE IF NOT EXISTS) ──────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS bounced_addresses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NULL REFERENCES organisations(id) ON DELETE CASCADE,
            email_address TEXT NOT NULL,
            bounce_kind VARCHAR(10) NOT NULL,
            reason TEXT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            hit_count INT NOT NULL DEFAULT 1,
            expires_at TIMESTAMPTZ NULL,
            CONSTRAINT ck_bounced_addresses_kind
                CHECK (bounce_kind IN ('hard', 'soft', 'blocked'))
        )
        """
    )

    # ── 2. Indexes ───────────────────────────────────────────────────────
    # Functional unique index — one row per (org, lowercase-address).
    # Wraps NULL org_id via COALESCE to '' so platform-wide rows can't
    # duplicate (PG would otherwise treat NULLs as distinct).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bounced_addresses_org_email "
        "ON bounced_addresses (COALESCE(org_id::text, ''), LOWER(email_address))"
    )
    # Lookup index for the pre-send blocklist check (lowercased).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bounced_addresses_email "
        "ON bounced_addresses (LOWER(email_address))"
    )
    # Partial index for the daily cleanup task; excludes hard bounces
    # (expires_at IS NULL) so the index stays small.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bounced_addresses_expires "
        "ON bounced_addresses (expires_at) WHERE expires_at IS NOT NULL"
    )

    # ── 3. Enable RLS + create org isolation policy ─────────────────────
    # NULL org_id rows are platform-wide (visible to every tenant);
    # non-NULL rows scope to the current request's app.current_org_id.
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_org_isolation ON {_TABLE}")
    op.execute(
        f"CREATE POLICY {_TABLE}_org_isolation ON {_TABLE} "
        "USING ("
        "org_id IS NULL "
        "OR org_id = current_setting('app.current_org_id', true)::uuid"
        ")"
    )

    # ── 4. HA replication publication membership ─────────────────────────
    op.execute(sa.text(_HA_ADD_TPL.format(table=_TABLE)))


def downgrade() -> None:
    # ── 1. Drop HA publication membership first ──────────────────────────
    op.execute(sa.text(_HA_DROP_TPL.format(table=_TABLE)))

    # ── 2. Drop RLS policy ───────────────────────────────────────────────
    op.execute(f"DROP POLICY IF EXISTS {_TABLE}_org_isolation ON {_TABLE}")

    # ── 3. Drop indexes ──────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS ix_bounced_addresses_expires")
    op.execute("DROP INDEX IF EXISTS ix_bounced_addresses_email")
    op.execute("DROP INDEX IF EXISTS uq_bounced_addresses_org_email")

    # ── 4. Drop the table ────────────────────────────────────────────────
    op.execute("DROP TABLE IF EXISTS bounced_addresses")
