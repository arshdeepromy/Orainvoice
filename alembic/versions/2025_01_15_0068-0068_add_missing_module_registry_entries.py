"""Add missing module_registry entries for modules that have feature flags
but were not in the original seed.

Adds: receipt_printer, portal, analytics, migration_tool, reports, webhooks,
i18n, assets.

Uses INSERT ... ON CONFLICT DO NOTHING for idempotency.

Revision ID: 0068
Revises: 0067
Create Date: 2025-01-15
"""

from __future__ import annotations

import json

from alembic import op

revision: str = "0068"
down_revision: str = "0067"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

MISSING_MODULES = [
    {
        "slug": "receipt_printer",
        "display_name": "Receipt Printer",
        "description": "Thermal receipt printing for POS transactions.",
        "category": "pos",
        "is_core": False,
        "dependencies": ["pos"],
    },
    {
        "slug": "portal",
        "display_name": "Client Portal",
        "description": "Customer-facing portal for invoices, quotes, bookings, and loyalty balances.",
        "category": "engagement",
        "is_core": False,
        "dependencies": ["customers"],
    },
    {
        "slug": "analytics",
        "display_name": "Analytics Dashboard",
        "description": "Platform analytics, MRR tracking, and usage metrics.",
        "category": "admin",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "migration_tool",
        "display_name": "Migration Tool",
        "description": "Data migration tool for importing from other platforms.",
        "category": "admin",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "reports",
        "display_name": "Reports",
        "description": "Financial and operational reporting suite with scheduled delivery.",
        "category": "finance",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "webhooks",
        "display_name": "Webhooks",
        "description": "Outbound webhook delivery for event notifications.",
        "category": "enterprise",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "i18n",
        "display_name": "Internationalisation",
        "description": "Multi-language support and locale management.",
        "category": "admin",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "assets",
        "display_name": "Assets",
        "description": "Asset register and lifecycle tracking.",
        "category": "operations",
        "is_core": False,
        "dependencies": [],
    },
]


def upgrade() -> None:
    for mod in MISSING_MODULES:
        deps_json = json.dumps(mod["dependencies"])
        op.execute(
            f"""
            INSERT INTO module_registry (
                id, slug, display_name, description, category,
                is_core, dependencies, status, created_at
            ) VALUES (
                gen_random_uuid(),
                '{mod["slug"]}',
                '{mod["display_name"]}',
                '{mod["description"]}',
                '{mod["category"]}',
                {'true' if mod["is_core"] else 'false'},
                '{deps_json}'::jsonb,
                'available',
                now()
            )
            ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING
            """
        )


def downgrade() -> None:
    slugs = ", ".join(f"'{m['slug']}'" for m in MISSING_MODULES)
    op.execute(f"DELETE FROM module_registry WHERE slug IN ({slugs})")
