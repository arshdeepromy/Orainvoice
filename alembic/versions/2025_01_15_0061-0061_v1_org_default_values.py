"""Add default values for new organisation columns for V1 orgs.

Backfills existing V1 organisations with NZ defaults:
- trade_category_id → 'general-automotive' trade category
- country_code → 'NZ'
- base_currency → 'NZD'
- locale → 'en-NZ'
- tax_label → 'GST'
- default_tax_rate → 15.0
- tax_inclusive_default → true
- date_format → 'dd/MM/yyyy'
- timezone → 'Pacific/Auckland'

Revision ID: 0061
Revises: 0060
Create Date: 2025-01-15

Requirements: 7.1 — V1 Organisation Data Migration (Task 53.1)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0061"
down_revision: str = "0060"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Backfill trade_category_id for orgs that don't have one set.
    # Look up the 'general-automotive' trade category by slug.
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET trade_category_id = tc.id
            FROM trade_categories tc
            WHERE tc.slug = 'general-automotive'
              AND organisations.trade_category_id IS NULL
            """
        )
    )

    # Backfill country_code for orgs that don't have one set.
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET country_code = 'NZ'
            WHERE country_code IS NULL
            """
        )
    )

    # Backfill compliance_profile_id for orgs that don't have one set.
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET compliance_profile_id = cp.id
            FROM compliance_profiles cp
            WHERE cp.country_code = 'NZ'
              AND organisations.compliance_profile_id IS NULL
            """
        )
    )

    # The remaining columns already have server defaults from migration 0013,
    # but explicitly set them for any rows where they might be NULL
    # (shouldn't happen, but defensive).
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET base_currency = 'NZD'
            WHERE base_currency IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET locale = 'en-NZ'
            WHERE locale IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET tax_label = 'GST'
            WHERE tax_label IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET default_tax_rate = 15.0
            WHERE default_tax_rate IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET tax_inclusive_default = true
            WHERE tax_inclusive_default IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET date_format = 'dd/MM/yyyy'
            WHERE date_format IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET timezone = 'Pacific/Auckland'
            WHERE timezone IS NULL
            """
        )
    )

    # Set setup_wizard_state to completed for existing V1 orgs
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET setup_wizard_state = '{"status": "completed", "migrated_from_v1": true}'::jsonb
            WHERE setup_wizard_state = '{}'::jsonb
               OR setup_wizard_state IS NULL
            """
        )
    )


def downgrade() -> None:
    # Revert trade_category_id and compliance_profile_id to NULL
    # for orgs that were backfilled (those with the v1 migration marker).
    op.execute(
        sa.text(
            """
            UPDATE organisations
            SET trade_category_id = NULL,
                compliance_profile_id = NULL,
                country_code = NULL,
                setup_wizard_state = '{}'::jsonb
            WHERE (setup_wizard_state->>'migrated_from_v1')::boolean = true
            """
        )
    )
