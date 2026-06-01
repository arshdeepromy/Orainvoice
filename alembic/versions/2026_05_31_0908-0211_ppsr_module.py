"""PPSR Module — schema + module registration.

Schema-additive migration that adds the PPSR (Personal Property Securities
Register) module per `.kiro/specs/ppsr-module/design.md` §3.1.

Creates:

  - ``ppsr_searches`` — per-search audit log + 5-minute Redis-paired cache.
    RLS-enabled with ``tenant_isolation`` policy keyed on
    ``current_setting('app.current_org_id')``. Encrypted-payload column
    ``response_encrypted`` typed ``BYTEA`` (envelope-encrypted via
    ``app.core.encryption.envelope_encrypt``). Includes the gap-closure
    columns: ``options_hash text NOT NULL`` (G30 — sha256 cache key),
    ``org_vehicle_id`` + ``global_vehicle_id`` FK columns (G13/G39 —
    Vehicle Profile embed link), and ``forgotten_at timestamptz`` (G29 —
    payload-wipe timestamp). CHECK constraint enforces ``match`` enum
    membership: ``Y/PY/M/PM/U/N``.

  - Two columns on ``subscription_plans`` — ``ppsr_lookups_included`` and
    ``ppsr_hidden_plate_lookups_included`` (G44 — renamed from
    ``ppsr_money_owing_*`` because ``ppsrh=1`` is the hidden-plate flag,
    not the money-owing flag).

  - Two columns on ``organisations`` — ``ppsr_lookups_this_month`` and
    ``ppsr_hidden_plate_lookups_this_month`` (G44). Re-uses the existing
    ``carjam_lookups_reset_at`` timestamp for monthly rollover.

  - One ``module_registry`` row for ``slug='ppsr'`` with
    ``setup_question`` + ``setup_question_description`` so the new-org
    setup wizard auto-shows the opt-in question (idempotent
    ``ON CONFLICT (slug) DO NOTHING``). Universal opt-in — NOT in
    ``TRADE_GATED_MODULES``.

  - One mirror ``feature_flags`` row for ``key='ppsr'`` with the
    actual column shape verified against
    ``app/modules/feature_flags/models.py:18-80`` — there is no
    ``default_enabled`` and no ``scope`` column; the real columns are
    ``id, key, display_name, description, category, access_level,
    dependencies, default_value, is_active, targeting_rules,
    created_at, updated_at``. ``default_value=true`` per the policy
    from migration ``0171`` — module gate is the real lever; the flag
    mirror is passive. Mirrors the
    ``2026_05_31_0900-0203_staff_phase1_schema.py:255-281`` pattern.

  - ``UPDATE subscription_plans SET enabled_modules`` to include
    ``'ppsr'`` for every unarchived plan via idempotent set-union (NOT
    a ``name ILIKE`` heuristic — ``WHERE is_archived = false`` per
    [0203_staff_phase1_schema.py:229-240]).

Index DDL is split into the next migration ``0212_ppsr_indexes`` because
``CREATE INDEX CONCURRENTLY`` cannot run inside the alembic transactional
wrapper. There are no UNIQUE constraints on ``options_hash`` — the column
is a cache-lookup key, not a uniqueness guarantor.

Refs: requirements R1, R3, R5; design.md §3.1; tasks.md A1.

Revision ID: 0211
Revises: 0210
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision: str = "0211"
down_revision: str = "0210"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. ppsr_searches table — audit log + cache + Vehicle Profile link.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ppsr_searches (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id             uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            user_id            uuid NOT NULL REFERENCES users(id),
            rego               text NOT NULL,
            options_json       jsonb NOT NULL,
            options_hash       text NOT NULL,
            org_vehicle_id     uuid REFERENCES org_vehicles(id) ON DELETE SET NULL,
            global_vehicle_id  uuid REFERENCES global_vehicles(id) ON DELETE SET NULL,
            match              text,
            match_description  text,
            statement_count    int NOT NULL DEFAULT 0,
            has_warnings       boolean NOT NULL DEFAULT false,
            has_ownership_data boolean NOT NULL DEFAULT false,
            response_encrypted bytea,
            charges_cents      int,
            not_found          boolean NOT NULL DEFAULT false,
            error_message      text,
            carjam_request_id  text,
            forgotten_at       timestamptz,
            created_at         timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_ppsr_searches_match
                CHECK (match IS NULL OR match IN ('Y','PY','M','PM','U','N'))
        )
        """
    )

    # RLS + tenant_isolation policy (mirrors migration 0008 pattern;
    # also matches 0203 staff_pay_rates / staff_roster_view_tokens).
    op.execute("ALTER TABLE ppsr_searches ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ppsr_searches")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ppsr_searches
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 2. subscription_plans quota columns (G44 — renamed for clarity:
    #    `hidden_plate` matches the actual CarJam `ppsrh=1` flag).
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE subscription_plans
            ADD COLUMN IF NOT EXISTS ppsr_lookups_included int NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS ppsr_hidden_plate_lookups_included int NOT NULL DEFAULT 0
        """
    )

    # ------------------------------------------------------------------
    # 3. organisations counter columns (G44). Reuses the existing
    #    ``carjam_lookups_reset_at`` timestamp for monthly rollover.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE organisations
            ADD COLUMN IF NOT EXISTS ppsr_lookups_this_month int NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS ppsr_hidden_plate_lookups_this_month int NOT NULL DEFAULT 0
        """
    )

    # ------------------------------------------------------------------
    # 4. module_registry insert (idempotent ON CONFLICT (slug)).
    #    Universal opt-in — not in TRADE_GATED_MODULES.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category, is_core,
            dependencies, incompatibilities, status,
            setup_question, setup_question_description
        )
        VALUES (
            gen_random_uuid(),
            'ppsr',
            'PPSR Vehicle Checks',
            'Run PPSR money-owing and ownership checks on NZ vehicles via CarJam.',
            'vehicles',
            false,
            '[]'::jsonb,
            '[]'::jsonb,
            'available',
            'Do you need to check if a vehicle has money owing on it (PPSR) or look up ownership history?',
            'Run finance-status, ownership, and warning checks on any NZ-registered vehicle. Uses the same CarJam connection as vehicle lookups.'
        )
        ON CONFLICT (slug) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 5. feature_flags mirror per implementation-completeness Rule 8.
    #
    #    Real columns (per app/modules/feature_flags/models.py:18-80):
    #    id, key, display_name [NOT NULL], description, category,
    #    access_level, dependencies, default_value, is_active,
    #    targeting_rules, created_at, updated_at.
    #
    #    There is NO ``scope`` column and NO ``default_enabled`` column —
    #    those names appear in steering text only and would crash on
    #    INSERT. Mirror the 0203_staff_phase1_schema.py:255-281 pattern
    #    exactly. ``default_value=true`` follows the policy set by
    #    migration 0171 — module gate is the real lever; the flag
    #    mirror is passive for the admin GUI.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO feature_flags (
            id, key, display_name, description, category,
            access_level, dependencies, default_value,
            is_active, targeting_rules, created_at, updated_at
        ) VALUES (
            gen_random_uuid(),
            'ppsr',
            'PPSR Vehicle Checks',
            'PPSR (Personal Property Securities Register) module — money-owing, ownership-history, warnings, and hidden-plate checks via the existing CarJam integration.',
            'operations',
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

    # ------------------------------------------------------------------
    # 6. Append 'ppsr' to enabled_modules JSONB of all unarchived plans.
    #    Idempotent set-union (DISTINCT inside jsonb_agg).  Mirrors
    #    [0203_staff_phase1_schema.py:229-240] — WHERE is_archived = false,
    #    NOT a name-ILIKE heuristic.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE subscription_plans
        SET enabled_modules = (
            SELECT jsonb_agg(DISTINCT m)
            FROM jsonb_array_elements_text(
                COALESCE(enabled_modules, '[]'::jsonb) || '["ppsr"]'::jsonb
            ) AS m
        )
        WHERE is_archived = false
        """
    )


def downgrade() -> None:
    # Reverse order: feature_flags + module_registry rows, then organisations
    # + subscription_plans columns, then ppsr_searches table. The
    # ``enabled_modules`` JSONB residue is left in place — once the slug
    # is out of the registry the bare string is harmless.
    op.execute("DELETE FROM feature_flags WHERE key = 'ppsr'")
    op.execute("DELETE FROM module_registry WHERE slug = 'ppsr'")

    op.execute(
        """
        ALTER TABLE organisations
            DROP COLUMN IF EXISTS ppsr_hidden_plate_lookups_this_month,
            DROP COLUMN IF EXISTS ppsr_lookups_this_month
        """
    )
    op.execute(
        """
        ALTER TABLE subscription_plans
            DROP COLUMN IF EXISTS ppsr_hidden_plate_lookups_included,
            DROP COLUMN IF EXISTS ppsr_lookups_included
        """
    )

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ppsr_searches")
    op.execute("DROP TABLE IF EXISTS ppsr_searches")
