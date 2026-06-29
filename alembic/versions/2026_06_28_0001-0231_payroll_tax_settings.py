"""Payroll Tax Settings — platform_tax_default + org_tax_settings tables + RLS + seed.

Creates the two-tier, GUI-editable NZ payroll tax configuration store:

  - **Creates ``platform_tax_default``** — the single, global baseline tax
    configuration record. A boolean ``is_singleton`` sentinel (always
    ``true``, ``UNIQUE``) structurally guarantees exactly one row exists, so a
    second insert conflicts (Req 1.1). The nested tax structures live in a
    single JSONB ``config`` document; the scalar ``tax_year_label`` is
    duplicated as a column for cheap display. Not org-scoped → **no RLS**.

  - **Creates ``org_tax_settings``** — one row per organisation that has ever
    set an override. The ``overrides`` JSONB holds a **sparse** set of only the
    Tax_Fields the org has explicitly overridden (a field absent from
    ``overrides`` inherits the platform default). ``UNIQUE(org_id)`` ensures
    one row per org (Req 3.4).

  - **RLS + ``tenant_isolation`` policy** on ``org_tax_settings`` using the
    standard ``current_setting('app.current_org_id', true)::uuid`` pattern,
    plus index ``ix_org_tax_settings_org`` on ``org_tax_settings(org_id)``.

  - **Seeds the single platform row** from the current hard-coded 2024/25
    constants (Req 1.2) via ``INSERT ... WHERE NOT EXISTS`` so that a
    pre-existing row is left untouched (Req 1.3). The seeded JSON mirrors the
    ``SAFETY_NET`` instance in ``app/modules/timesheets/paye.py`` exactly, so
    immediately after migration every org resolves to the same numbers the
    hard-coded engine produced — a zero-behaviour-change cutover.

Idempotent throughout — every CREATE uses IF NOT EXISTS, the policy uses
DROP POLICY IF EXISTS then CREATE POLICY, the index uses IF NOT EXISTS, and the
seed is guarded by WHERE NOT EXISTS.

``downgrade()`` drops the policy then the tables.

Refs: requirements 1.1, 1.2, 1.3; design §"Data Models" / §"Seed migration".

Revision ID: 0231
Revises: 0230
Create Date: 2026-06-28
"""

from __future__ import annotations

from alembic import op

revision: str = "0231"
down_revision: str = "0230"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. platform_tax_default — single global baseline (singleton).
    #    is_singleton is always true and UNIQUE, so a second insert
    #    conflicts → exactly one row (Req 1.1). No RLS (not org-scoped).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_tax_default (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            is_singleton    boolean NOT NULL DEFAULT true,
            config          jsonb NOT NULL,
            tax_year_label  text NOT NULL,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now(),
            updated_by      uuid,
            CONSTRAINT uq_platform_tax_default_singleton UNIQUE (is_singleton)
        )
        """
    )

    # ------------------------------------------------------------------
    # 2. org_tax_settings — per-org sparse overrides (RLS table).
    #    UNIQUE(org_id) → one row per org (Req 3.4).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS org_tax_settings (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id      uuid NOT NULL,
            overrides   jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now(),
            updated_by  uuid,
            CONSTRAINT uq_org_tax_settings_org UNIQUE (org_id)
        )
        """
    )

    # Index on org_id for tenant lookups.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_org_tax_settings_org
            ON org_tax_settings(org_id)
        """
    )

    # RLS policy — standard tenant isolation keyed on app.current_org_id.
    op.execute("ALTER TABLE org_tax_settings ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON org_tax_settings")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON org_tax_settings
            USING (org_id = current_setting('app.current_org_id', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
        """
    )

    # ------------------------------------------------------------------
    # 3. Seed the single platform row from the 2024/25 constants (Req 1.2).
    #    Guarded by WHERE NOT EXISTS so a pre-existing row is left
    #    untouched (Req 1.3). The config JSON mirrors SAFETY_NET in
    #    app/modules/timesheets/paye.py exactly. The open-ended top PAYE
    #    band uses upper_limit: null.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO platform_tax_default (config, tax_year_label)
        SELECT
            '{
                "paye_brackets": [
                    {"upper_limit": 15600, "rate": 0.105},
                    {"upper_limit": 53500, "rate": 0.175},
                    {"upper_limit": 78100, "rate": 0.30},
                    {"upper_limit": 180000, "rate": 0.33},
                    {"upper_limit": null, "rate": 0.39}
                ],
                "secondary_rates": {
                    "SB": 0.105,
                    "S": 0.175,
                    "SH": 0.30,
                    "ST": 0.33,
                    "SA": 0.39
                },
                "acc_levy_rate": 0.016,
                "acc_max_liable_earnings": 142283,
                "student_loan_rate": 0.12,
                "student_loan_threshold": 24128,
                "ietc": {
                    "amount": 520,
                    "lower": 24000,
                    "abatement_start": 44000,
                    "abatement_rate": 0.13,
                    "upper": 48000
                },
                "default_kiwisaver_employee_rate": 3.00,
                "default_kiwisaver_employer_rate": 3.00
            }'::jsonb,
            '2024/25'
        WHERE NOT EXISTS (SELECT 1 FROM platform_tax_default)
        """
    )


def downgrade() -> None:
    # Drop the RLS policy first, then the tables.
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON org_tax_settings")
    op.execute("DROP TABLE IF EXISTS org_tax_settings")
    op.execute("DROP TABLE IF EXISTS platform_tax_default")
