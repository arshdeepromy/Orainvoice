"""Fix feature flag default_value for module-gated flags.

All module-gated feature flags were seeded with default_value=false, which
blocks any org that doesn't have an explicit org_override targeting rule.
Since the ModuleMiddleware + org_modules table already handles plan-based
module gating, feature flags should default to true (permissive) and only
be used for targeted rollout control.

This migration sets default_value=true for all non-admin feature flags.
Admin-only flags (analytics, branding, i18n, migration_tool, webhooks,
receipt_printer) remain false as they require explicit enablement.

Revision ID: 0171
Revises: 0170
Create Date: 2026-05-02
"""

from __future__ import annotations

from alembic import op

revision: str = "0171"
down_revision: str = "0170"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# Flags that should remain default_value=false (admin/internal tools)
ADMIN_ONLY_FLAGS = (
    "analytics",
    "branding",
    "i18n",
    "migration_tool",
    "webhooks",
    "receipt_printer",
)


def upgrade() -> None:
    excluded = ", ".join(f"'{k}'" for k in ADMIN_ONLY_FLAGS)
    op.execute(
        f"""
        UPDATE feature_flags
        SET default_value = true, updated_at = now()
        WHERE default_value = false
          AND key NOT IN ({excluded})
        """
    )


def downgrade() -> None:
    # Revert to original defaults (false for all non-core)
    op.execute(
        """
        UPDATE feature_flags
        SET default_value = false, updated_at = now()
        WHERE key NOT IN ('invoicing', 'customers', 'notifications')
        """
    )
