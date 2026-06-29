"""E-Signature Integration (Migration A) — esign tables, CHECK constraints, RLS, inline indexes, seeds.

Creates the four org-scoped tables that anchor the ``esignatures`` module, all
under Postgres row-level security, plus the mandatory ``module_registry``
catalogue row (and an optional ``feature_flags`` visibility row):

  - **``esign_envelopes``** — the system-of-record mapping between an OraInvoice
    document/recipient set and a Documenso document. Carries ``org_id``, the
    ``agreement_type`` (one of 5), the originating-entity reference
    (``originating_entity_type`` ∈ invoice/quote/staff + id), the mapped
    ``documenso_document_id``, the lifecycle ``status`` (one of 8), the
    ``signed_doc_status`` (none/pending_retrieval/stored) + ``signed_doc_file_key``,
    and a ``last_error`` slot. Four CHECK constraints pin the enum domains.

  - **``esign_recipients``** — one row per recipient, cascade-FK'd to its parent
    envelope. ``recipient_status`` defaults to ``pending``, ``signing_url`` is
    nullable (captured from Documenso's per-recipient ``signingUrl``), and
    ``signing_role`` is stored as the UPPERCASE Documenso role (SIGNER/VIEWER).
    RLS is scoped **through the parent envelope** (a recipient is visible iff its
    envelope's ``org_id`` matches the current org).

  - **``esign_webhook_events``** — idempotency ledger. ``dedupe_key`` is the
    synthesized idempotency key (the Documenso payload carries no native event
    id) and is ``TEXT NOT NULL UNIQUE``.

  - **``esign_org_connections``** — the per-organisation Documenso connection
    record (analogous to the per-org accounting/Xero connection). ``org_id`` is
    UNIQUE (one connection per org); ``service_token_encrypted`` /
    ``webhook_secret_encrypted`` are envelope-encrypted BYTEA;
    ``webhook_routing_id`` is the opaque per-org routing identifier embedded in
    the registered Documenso callback URL (TEXT NOT NULL UNIQUE);
    ``is_verified`` gates sends.

RLS posture follows the standard ``tenant_isolation`` pattern keyed on
``current_setting('app.current_org_id', true)::uuid`` (migrations 0209, 0218,
0223, 0224). ``esign_envelopes``, ``esign_webhook_events`` and
``esign_org_connections`` are scoped directly by ``org_id``; ``esign_recipients``
is scoped through its parent envelope.

Only indexes **intrinsic to table creation** are created here — PK indexes
(implicit), the inline UNIQUE constraints (``dedupe_key``, ``org_id``,
``webhook_routing_id``) and the ``esign_recipients(envelope_id)`` FK lookup index
(``CREATE INDEX IF NOT EXISTS``, never ``op.create_index`` and never
``CONCURRENTLY``). All performance indexes live in Migration B (0233).

Idempotent throughout: every ``CREATE TABLE`` uses ``IF NOT EXISTS``; each CHECK
constraint is added via ``DROP CONSTRAINT IF EXISTS`` then ``ADD CONSTRAINT`` so
re-running re-asserts the domain; each policy uses ``DROP POLICY IF EXISTS`` then
``CREATE POLICY``; the FK index uses ``IF NOT EXISTS``; the seeds use
``INSERT ... ON CONFLICT DO NOTHING``.

The ``module_registry`` seed (slug ``esignatures``, display name 'Agreements',
category ``documents``, ``is_core=false``, no trade-family gating, with
``setup_question`` / ``setup_question_description``) is **mandatory** — it drives
per-org enablement and the sidebar. The ``feature_flags`` row (keyed by
``key='esignatures'``) is **optional / catalogue-visibility only** — it is NOT a
runtime gate and is deliberately NOT wired into ``FLAG_ENDPOINT_MAP``.

``downgrade()`` drops the policies, disables RLS, drops all four tables, removes
the mandatory ``module_registry`` seed, and removes the optional
``feature_flags`` row.

Refs: requirements 1.1, 1.2, 2.1, 2.5, 3.2, 3.6, 6.1, 8.3, 8.4, 13.1, 13.2, 13.7;
       design §"Data Models" / §"Module registration and gating".

Revision ID: 0232
Revises: 0231
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

revision: str = "0232"
down_revision: str = "0231"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ==================================================================
    # 1. esign_envelopes — system-of-record envelope (RLS, org-scoped).
    # ==================================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS esign_envelopes (
            id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                  uuid NOT NULL,
            agreement_type          text NOT NULL,
            originating_entity_type text NOT NULL,
            originating_entity_id   uuid NOT NULL,
            documenso_document_id   text NULL,
            status                  text NOT NULL DEFAULT 'draft',
            signed_doc_status       text NOT NULL DEFAULT 'none',
            signed_doc_file_key     text NULL,
            last_error              text NULL,
            created_at              timestamptz NOT NULL DEFAULT now(),
            updated_at              timestamptz NOT NULL DEFAULT now(),
            created_by              uuid NULL
        )
        """
    )

    # CHECK constraints — DROP IF EXISTS then ADD so the domain is re-asserted
    # on a re-run even when the table already existed (CREATE TABLE IF NOT
    # EXISTS would otherwise skip them).
    op.execute(
        "ALTER TABLE esign_envelopes "
        "DROP CONSTRAINT IF EXISTS ck_esign_envelopes_agreement_type"
    )
    op.execute(
        """
        ALTER TABLE esign_envelopes
            ADD CONSTRAINT ck_esign_envelopes_agreement_type
            CHECK (agreement_type IN (
                'sales_agreement', 'purchase_agreement', 'nda',
                'employment_agreement', 'contractor_agreement'
            ))
        """
    )

    op.execute(
        "ALTER TABLE esign_envelopes "
        "DROP CONSTRAINT IF EXISTS ck_esign_envelopes_originating_entity_type"
    )
    op.execute(
        """
        ALTER TABLE esign_envelopes
            ADD CONSTRAINT ck_esign_envelopes_originating_entity_type
            CHECK (originating_entity_type IN ('invoice', 'quote', 'staff'))
        """
    )

    op.execute(
        "ALTER TABLE esign_envelopes "
        "DROP CONSTRAINT IF EXISTS ck_esign_envelopes_status"
    )
    op.execute(
        """
        ALTER TABLE esign_envelopes
            ADD CONSTRAINT ck_esign_envelopes_status
            CHECK (status IN (
                'draft', 'sent', 'viewed', 'partially_signed',
                'completed', 'declined', 'voided', 'error'
            ))
        """
    )

    op.execute(
        "ALTER TABLE esign_envelopes "
        "DROP CONSTRAINT IF EXISTS ck_esign_envelopes_signed_doc_status"
    )
    op.execute(
        """
        ALTER TABLE esign_envelopes
            ADD CONSTRAINT ck_esign_envelopes_signed_doc_status
            CHECK (signed_doc_status IN ('none', 'pending_retrieval', 'stored'))
        """
    )

    # RLS — standard tenant isolation keyed on app.current_org_id.
    op.execute("ALTER TABLE esign_envelopes ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_envelopes")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON esign_envelopes
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ==================================================================
    # 2. esign_recipients — child of esign_envelopes (cascade FK).
    #    RLS is scoped THROUGH the parent envelope (no org_id column).
    #    signing_role is stored UPPERCASE (Documenso role); signing_url
    #    is nullable (captured from Documenso's per-recipient signingUrl).
    # ==================================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS esign_recipients (
            id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            envelope_id            uuid NOT NULL
                                   REFERENCES esign_envelopes(id) ON DELETE CASCADE,
            name                   text NOT NULL,
            email                  text NOT NULL,
            signing_role           text NOT NULL,
            recipient_status       text NOT NULL DEFAULT 'pending',
            signing_url            text NULL,
            documenso_recipient_id text NULL,
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # FK lookup index — intrinsic to the child table; empty table so a plain
    # CREATE INDEX IF NOT EXISTS is safe (NOT op.create_index, NOT CONCURRENTLY).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_esign_recipients_envelope "
        "ON esign_recipients (envelope_id)"
    )

    # RLS — a recipient is visible iff its parent envelope belongs to the
    # current org (recipients carry no org_id; they inherit it via the parent).
    op.execute("ALTER TABLE esign_recipients ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_recipients")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON esign_recipients
            USING (
                envelope_id IN (
                    SELECT id FROM esign_envelopes
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
            WITH CHECK (
                envelope_id IN (
                    SELECT id FROM esign_envelopes
                    WHERE org_id = current_setting('app.current_org_id', true)::uuid
                )
            )
        """
    )

    # ==================================================================
    # 3. esign_webhook_events — idempotency ledger (RLS, org-scoped).
    #    dedupe_key is the synthesized idempotency key (no native event id
    #    in the Documenso payload) — TEXT NOT NULL UNIQUE (inline).
    # ==================================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS esign_webhook_events (
            id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                uuid NOT NULL,
            dedupe_key            text NOT NULL,
            event_type            text NULL,
            documenso_document_id text NULL,
            payload               jsonb NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_esign_webhook_events_dedupe_key UNIQUE (dedupe_key)
        )
        """
    )
    op.execute("ALTER TABLE esign_webhook_events ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_webhook_events")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON esign_webhook_events
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ==================================================================
    # 4. esign_org_connections — per-org Documenso connection (RLS,
    #    org-scoped). One row per org: org_id UNIQUE. Secrets are
    #    envelope-encrypted BYTEA. webhook_routing_id is the opaque per-org
    #    routing identifier (TEXT NOT NULL UNIQUE). Both UNIQUE constraints
    #    are declared INLINE (not via op.create_index).
    # ==================================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS esign_org_connections (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id                   uuid NOT NULL,
            base_url                 text NOT NULL,
            documenso_team_id        text NULL,
            service_token_encrypted  bytea NULL,
            webhook_secret_encrypted bytea NULL,
            webhook_routing_id       text NOT NULL,
            is_verified              boolean NOT NULL DEFAULT false,
            created_at               timestamptz NOT NULL DEFAULT now(),
            updated_at               timestamptz NOT NULL DEFAULT now(),
            created_by               uuid NULL,
            CONSTRAINT uq_esign_org_connections_org UNIQUE (org_id),
            CONSTRAINT uq_esign_org_connections_routing_id UNIQUE (webhook_routing_id)
        )
        """
    )
    op.execute("ALTER TABLE esign_org_connections ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_org_connections")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON esign_org_connections
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ==================================================================
    # 5. module_registry seed (MANDATORY) — drives per-org enablement +
    #    sidebar. Universal opt-in: category 'documents', is_core=false,
    #    NOT in any trade-family gating list. Includes setup-guide columns
    #    so the new-org setup wizard auto-shows the opt-in question.
    # ==================================================================
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category, is_core,
            dependencies, incompatibilities, status,
            setup_question, setup_question_description
        )
        VALUES (
            gen_random_uuid(),
            'esignatures',
            'Agreements',
            'Send PDFs for legally-binding digital signature, track signing progress, and store the completed signed document — powered by a self-hosted Documenso instance.',
            'documents',
            false,
            '[]'::jsonb,
            '[]'::jsonb,
            'available',
            'Do you need to send documents for digital signature (sales/purchase agreements, NDAs, employment or contractor agreements)?',
            'Send PDFs for legally-binding e-signature and track them from an Agreements dashboard. Signed documents are stored securely and attached to the originating invoice, quote, or staff member.'
        )
        ON CONFLICT (slug) DO NOTHING
        """
    )

    # ==================================================================
    # 6. feature_flags row (OPTIONAL — catalogue/visibility ONLY).
    #
    #    Keyed by `key` (NOT `slug`). This makes the capability visible in
    #    the Global Admin → Feature Flags page. It is NOT the runtime gate
    #    (ModuleService.is_enabled does not consult feature_flags) and MUST
    #    NOT be wired into FLAG_ENDPOINT_MAP. Real columns per
    #    app/modules/feature_flags/models.py — no `scope`/`default_enabled`.
    # ==================================================================
    op.execute(
        """
        INSERT INTO feature_flags (
            id, key, display_name, description, category,
            access_level, dependencies, default_value,
            is_active, targeting_rules, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'esignatures',
            'Agreements',
            'E-signature module — send PDFs for digital signature via a self-hosted Documenso instance, track signing status, and store signed documents. Catalogue/visibility flag only; the runtime gate is the esignatures module.',
            'documents',
            'all_users',
            '[]'::jsonb,
            true,
            true,
            '[]'::jsonb,
            now(),
            now()
        )
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Reverse order: seeds first, then policies + tables. Dropping a table also
    # drops its policies/constraints/indexes, but the explicit DROP POLICY keeps
    # the downgrade self-documenting and re-runnable.

    # 6/5. Remove the optional feature_flags row and the mandatory
    #      module_registry seed.
    op.execute("DELETE FROM feature_flags WHERE key = 'esignatures'")
    op.execute("DELETE FROM module_registry WHERE slug = 'esignatures'")

    # 4. esign_org_connections
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_org_connections")
    op.execute("DROP TABLE IF EXISTS esign_org_connections")

    # 3. esign_webhook_events
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_webhook_events")
    op.execute("DROP TABLE IF EXISTS esign_webhook_events")

    # 2. esign_recipients (drop before parent to satisfy the FK)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_recipients")
    op.execute("DROP TABLE IF EXISTS esign_recipients")

    # 1. esign_envelopes
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON esign_envelopes")
    op.execute("DROP TABLE IF EXISTS esign_envelopes")
