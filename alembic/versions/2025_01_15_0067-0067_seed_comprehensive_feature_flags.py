"""Seed comprehensive feature flags for all platform modules.

Inserts ~45 feature flag rows covering every platform module with category,
access_level, dependencies, and default_value metadata.  Uses
INSERT ... ON CONFLICT (key) DO NOTHING for idempotency.

Revision ID: 0067
Revises: 0066
Create Date: 2025-01-15

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""

from __future__ import annotations

from alembic import op

revision: str = "0067"
down_revision: str = "0066"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# ---------------------------------------------------------------------------
# Seed data: each tuple is
#   (key, display_name, description, category, access_level, dependencies, default_value)
#
# Core modules default to true; everything else defaults to false.
# ---------------------------------------------------------------------------

SEED_FLAGS: list[tuple[str, str, str, str, str, str, bool]] = [
    # ── Core ──────────────────────────────────────────────────────────────
    (
        "invoicing",
        "Invoicing",
        "Create, send, and manage invoices",
        "Core",
        "all_users",
        "[]",
        True,
    ),
    (
        "customers",
        "Customers",
        "Customer contact management and CRM",
        "Core",
        "all_users",
        "[]",
        True,
    ),
    (
        "notifications",
        "Notifications",
        "Email, SMS, and in-app notification delivery",
        "Core",
        "all_users",
        "[]",
        True,
    ),
    # ── Sales ──────────────────────────────────────────────────────────────
    (
        "quotes",
        "Quotes",
        "Create and manage quotes with conversion to invoices",
        "Sales",
        "all_users",
        '["invoicing"]',
        False,
    ),
    # ── Operations ────────────────────────────────────────────────────────
    (
        "jobs",
        "Jobs",
        "Job tracking, scheduling, and management",
        "Operations",
        "all_users",
        "[]",
        False,
    ),
    (
        "projects",
        "Projects",
        "Project management with profitability tracking",
        "Operations",
        "all_users",
        '["jobs"]',
        False,
    ),
    (
        "time_tracking",
        "Time Tracking",
        "Track time entries against jobs and projects",
        "Operations",
        "all_users",
        '["jobs"]',
        False,
    ),
    (
        "expenses",
        "Expenses",
        "Expense recording and pass-through billing",
        "Operations",
        "all_users",
        '["invoicing"]',
        False,
    ),
    # ── Inventory ─────────────────────────────────────────────────────────
    (
        "inventory",
        "Inventory",
        "Product catalogue, stock levels, and stock movements",
        "Inventory",
        "all_users",
        "[]",
        False,
    ),
    (
        "purchase_orders",
        "Purchase Orders",
        "Create and receive purchase orders from suppliers",
        "Inventory",
        "all_users",
        '["inventory"]',
        False,
    ),
    # ── POS ───────────────────────────────────────────────────────────────
    (
        "pos",
        "Point of Sale",
        "POS terminal with offline support and payment processing",
        "POS",
        "all_users",
        '["inventory"]',
        False,
    ),
    (
        "tipping",
        "Tipping",
        "Tip prompts and tip management for POS transactions",
        "POS",
        "all_users",
        '["pos"]',
        False,
    ),
    (
        "receipt_printer",
        "Receipt Printer",
        "Thermal receipt printing for POS transactions",
        "POS",
        "all_users",
        '["pos"]',
        False,
    ),
    # ── Hospitality ───────────────────────────────────────────────────────
    (
        "tables",
        "Tables",
        "Table layout management and status tracking",
        "Hospitality",
        "all_users",
        "[]",
        False,
    ),
    (
        "kitchen_display",
        "Kitchen Display",
        "Kitchen display system for order management",
        "Hospitality",
        "all_users",
        '["tables"]',
        False,
    ),
    (
        "scheduling",
        "Scheduling",
        "Staff and resource scheduling with conflict detection",
        "Hospitality",
        "all_users",
        '["staff"]',
        False,
    ),
    (
        "bookings",
        "Bookings",
        "Online and in-person booking management",
        "Hospitality",
        "all_users",
        '["scheduling"]',
        False,
    ),
    # ── Staff ──────────────────────────────────────────────────────────────
    (
        "staff",
        "Staff",
        "Staff member profiles, roles, and labour cost tracking",
        "Staff",
        "all_users",
        "[]",
        False,
    ),
    # ── Construction ──────────────────────────────────────────────────────
    (
        "progress_claims",
        "Progress Claims",
        "Construction progress claim management and PDF generation",
        "Construction",
        "all_users",
        '["jobs"]',
        False,
    ),
    (
        "retentions",
        "Retentions",
        "Retention withholding and release tracking",
        "Construction",
        "all_users",
        '["invoicing"]',
        False,
    ),
    (
        "variations",
        "Variations",
        "Variation order management for construction projects",
        "Construction",
        "all_users",
        '["jobs"]',
        False,
    ),
    # ── Finance ───────────────────────────────────────────────────────────
    (
        "multi_currency",
        "Multi-Currency",
        "Multi-currency support with exchange rate locking",
        "Finance",
        "all_users",
        '["invoicing"]',
        False,
    ),
    (
        "recurring",
        "Recurring Invoices",
        "Automated recurring invoice generation",
        "Finance",
        "all_users",
        '["invoicing"]',
        False,
    ),
    # ── Compliance ────────────────────────────────────────────────────────
    (
        "compliance_docs",
        "Compliance Documents",
        "Document compliance tracking and expiry management",
        "Compliance",
        "all_users",
        "[]",
        False,
    ),
    # ── Engagement ────────────────────────────────────────────────────────
    (
        "loyalty",
        "Loyalty",
        "Customer loyalty points and rewards programme",
        "Engagement",
        "all_users",
        '["customers"]',
        False,
    ),
    (
        "portal",
        "Client Portal",
        "Customer-facing portal for invoices, quotes, and bookings",
        "Engagement",
        "all_users",
        '["customers"]',
        False,
    ),
    # ── Enterprise ────────────────────────────────────────────────────────
    (
        "franchise",
        "Franchise",
        "Multi-location franchise management and stock transfers",
        "Enterprise",
        "admin_only",
        "[]",
        False,
    ),
    # ── Ecommerce ─────────────────────────────────────────────────────────
    (
        "ecommerce",
        "Ecommerce",
        "WooCommerce integration and online store sync",
        "Ecommerce",
        "all_users",
        '["inventory"]',
        False,
    ),
    # ── Admin ─────────────────────────────────────────────────────────────
    (
        "branding",
        "Branding",
        "Custom branding, logos, and white-label configuration",
        "Admin",
        "admin_only",
        "[]",
        False,
    ),
    (
        "analytics",
        "Analytics",
        "Platform analytics dashboard and usage metrics",
        "Admin",
        "admin_only",
        "[]",
        False,
    ),
    (
        "migration_tool",
        "Migration Tool",
        "Data migration tool for importing from other platforms",
        "Admin",
        "admin_only",
        "[]",
        False,
    ),

    # ── Reports ───────────────────────────────────────────────────────────
    (
        "reports",
        "Reports",
        "Financial and operational reporting suite",
        "Reports",
        "all_users",
        "[]",
        False,
    ),
    # ── Data ──────────────────────────────────────────────────────────────
    (
        "webhooks",
        "Webhooks",
        "Outbound webhook delivery for event notifications",
        "Data",
        "all_users",
        "[]",
        False,
    ),
    (
        "i18n",
        "Internationalisation",
        "Multi-language support and locale management",
        "Data",
        "all_users",
        "[]",
        False,
    ),
    (
        "assets",
        "Assets",
        "Asset register and lifecycle tracking",
        "Data",
        "all_users",
        "[]",
        False,
    ),
]


def upgrade() -> None:
    for key, display_name, description, category, access_level, deps, default_value in SEED_FLAGS:
        op.execute(
            f"""
            INSERT INTO feature_flags (
                id, key, display_name, description, category,
                access_level, dependencies, default_value,
                is_active, targeting_rules, created_at, updated_at
            ) VALUES (
                gen_random_uuid(),
                '{key}',
                '{display_name}',
                '{description}',
                '{category}',
                '{access_level}',
                '{deps}'::jsonb,
                {'true' if default_value else 'false'},
                true,
                '[]'::jsonb,
                now(),
                now()
            )
            ON CONFLICT (key) DO NOTHING
            """
        )


def downgrade() -> None:
    keys = ", ".join(f"'{flag[0]}'" for flag in SEED_FLAGS)
    op.execute(f"DELETE FROM feature_flags WHERE key IN ({keys})")
