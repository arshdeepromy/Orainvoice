"""Seed module_registry with all module slugs, display names, descriptions,
categories, dependency lists, and is_core flags.

Revision ID: 0021
Revises: 0020
Create Date: 2025-01-15

Requirements: 6.1, 6.5
"""

from __future__ import annotations

import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str = "0020"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

MODULE_REGISTRY = [
    # --- Core modules (always enabled) ---
    {
        "slug": "invoicing",
        "display_name": "Invoicing",
        "description": "Create, manage, search, and issue invoices.",
        "category": "core",
        "is_core": True,
        "dependencies": [],
    },
    {
        "slug": "customers",
        "display_name": "Customers",
        "description": "Customer management, profiles, and contact details.",
        "category": "core",
        "is_core": True,
        "dependencies": [],
    },
    {
        "slug": "notifications",
        "display_name": "Notifications",
        "description": "Email, SMS, and in-app notification delivery.",
        "category": "core",
        "is_core": True,
        "dependencies": [],
    },
    # --- Sales & Quoting ---
    {
        "slug": "quotes",
        "display_name": "Quotes & Estimates",
        "description": "Create quotes and estimates, send to customers, and convert to invoices.",
        "category": "sales",
        "is_core": False,
        "dependencies": [],
    },
    # --- Job & Project Management ---
    {
        "slug": "jobs",
        "display_name": "Jobs & Work Orders",
        "description": "Job lifecycle management from enquiry through to invoicing.",
        "category": "operations",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "projects",
        "display_name": "Projects",
        "description": "Group jobs, invoices, quotes, time entries, and expenses into projects with profitability tracking.",
        "category": "operations",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "time_tracking",
        "display_name": "Time Tracking",
        "description": "Manual and timer-based time entry linked to jobs and invoices.",
        "category": "operations",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "expenses",
        "display_name": "Expenses",
        "description": "Log expenses against jobs or projects with optional pass-through to invoices.",
        "category": "operations",
        "is_core": False,
        "dependencies": ["jobs"],
    },
    # --- Inventory & Stock ---
    {
        "slug": "inventory",
        "display_name": "Inventory & Products",
        "description": "Product catalogue, stock levels, movements, pricing rules, and barcode scanning.",
        "category": "inventory",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "purchase_orders",
        "display_name": "Purchase Orders",
        "description": "Raise purchase orders, receive goods, and link to jobs/projects/inventory.",
        "category": "inventory",
        "is_core": False,
        "dependencies": ["inventory"],
    },
    # --- Point of Sale ---
    {
        "slug": "pos",
        "display_name": "Point of Sale",
        "description": "POS mode with receipt printing and offline transaction queuing.",
        "category": "pos",
        "is_core": False,
        "dependencies": ["inventory"],
    },
    {
        "slug": "tipping",
        "display_name": "Tipping",
        "description": "Tip collection on invoices and POS transactions with staff allocation.",
        "category": "pos",
        "is_core": False,
        "dependencies": [],
    },
    # --- Hospitality ---
    {
        "slug": "tables",
        "display_name": "Tables & Floor Plans",
        "description": "Visual floor plan, table status tracking, and seat management.",
        "category": "hospitality",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "kitchen_display",
        "display_name": "Kitchen Display",
        "description": "Order item display and tick-off interface for food preparation.",
        "category": "hospitality",
        "is_core": False,
        "dependencies": ["tables", "pos"],
    },
    # --- Staff & Scheduling ---
    {
        "slug": "scheduling",
        "display_name": "Scheduling",
        "description": "Visual calendar, drag-and-drop scheduling, and resource allocation.",
        "category": "staff",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "staff",
        "display_name": "Staff & Contractors",
        "description": "Staff and contractor management, job assignment, and labour cost tracking.",
        "category": "staff",
        "is_core": False,
        "dependencies": ["scheduling"],
    },
    {
        "slug": "bookings",
        "display_name": "Bookings & Appointments",
        "description": "Customer-facing booking pages and appointment management.",
        "category": "staff",
        "is_core": False,
        "dependencies": [],
    },
    # --- Construction ---
    {
        "slug": "progress_claims",
        "display_name": "Progress Claims",
        "description": "Progress claims against contract values with variation tracking.",
        "category": "construction",
        "is_core": False,
        "dependencies": ["projects"],
    },
    {
        "slug": "retentions",
        "display_name": "Retentions",
        "description": "Construction retention tracking per project.",
        "category": "construction",
        "is_core": False,
        "dependencies": ["progress_claims"],
    },
    {
        "slug": "variations",
        "display_name": "Variations",
        "description": "Scope change orders, approval workflows, and contract value updates.",
        "category": "construction",
        "is_core": False,
        "dependencies": ["progress_claims"],
    },
    # --- Compliance & Documents ---
    {
        "slug": "compliance_docs",
        "display_name": "Compliance Documents",
        "description": "Certification and compliance document management linked to invoices.",
        "category": "compliance",
        "is_core": False,
        "dependencies": [],
    },
    # --- Finance ---
    {
        "slug": "multi_currency",
        "display_name": "Multi-Currency",
        "description": "Multi-currency invoicing, exchange rate management, and base currency consolidation.",
        "category": "finance",
        "is_core": False,
        "dependencies": [],
    },
    {
        "slug": "recurring",
        "display_name": "Recurring Invoices",
        "description": "Recurring invoice schedules with auto-generation.",
        "category": "finance",
        "is_core": False,
        "dependencies": [],
    },
    # --- Customer Engagement ---
    {
        "slug": "loyalty",
        "display_name": "Loyalty Program",
        "description": "Loyalty points, membership tiers, and auto-applied discounts.",
        "category": "engagement",
        "is_core": False,
        "dependencies": [],
    },
    # --- Enterprise ---
    {
        "slug": "franchise",
        "display_name": "Franchise & Multi-Location",
        "description": "Franchise and multi-location organisation support.",
        "category": "enterprise",
        "is_core": False,
        "dependencies": [],
    },
    # --- Ecommerce ---
    {
        "slug": "ecommerce",
        "display_name": "Ecommerce",
        "description": "WooCommerce integration, general ecommerce webhooks, and API-based order ingestion.",
        "category": "ecommerce",
        "is_core": False,
        "dependencies": ["inventory"],
    },
    # --- Branding ---
    {
        "slug": "branding",
        "display_name": "Branding",
        "description": "Platform branding, Powered By configuration, and white-label settings.",
        "category": "admin",
        "is_core": False,
        "dependencies": [],
    },
]


def upgrade() -> None:
    module_registry = sa.table(
        "module_registry",
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("is_core", sa.Boolean),
        sa.column("dependencies", postgresql.JSONB),
        sa.column("status", sa.String),
    )
    rows = []
    for mod in MODULE_REGISTRY:
        rows.append({
            "slug": mod["slug"],
            "display_name": mod["display_name"],
            "description": mod["description"],
            "category": mod["category"],
            "is_core": mod["is_core"],
            "dependencies": json.dumps(mod["dependencies"]),
            "status": "available",
        })
    op.bulk_insert(module_registry, rows)


def downgrade() -> None:
    slugs = [m["slug"] for m in MODULE_REGISTRY]
    op.execute(
        sa.text("DELETE FROM module_registry WHERE slug = ANY(:slugs)").bindparams(
            slugs=slugs
        )
    )
