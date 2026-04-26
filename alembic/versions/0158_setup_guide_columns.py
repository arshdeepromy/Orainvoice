"""Add setup_question and setup_question_description columns to module_registry
and seed question text for all 23 non-core, non-trade-gated modules.

Revision ID: 0158
Revises: 0157
Create Date: 2026-04-18

Requirements: 1.1, 1.2, 1.5
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0158"
down_revision: str = "0157"
branch_labels = None
depends_on = None

# All 23 non-core, non-trade-gated modules with their setup questions.
# vehicles is excluded — it's trade-family-gated.
SETUP_QUESTIONS: list[dict[str, str]] = [
    {
        "slug": "quotes",
        "setup_question": "Will you be sending quotes or estimates to your customers?",
        "setup_question_description": "Create professional quotes, send them for approval, and convert accepted quotes into invoices.",
    },
    {
        "slug": "jobs",
        "setup_question": "Do you manage jobs or work orders for your customers?",
        "setup_question_description": "Track jobs from enquiry through to completion and invoicing.",
    },
    {
        "slug": "projects",
        "setup_question": "Do you work on projects that span multiple jobs or invoices?",
        "setup_question_description": "Group related jobs, invoices, and expenses into projects with profitability tracking.",
    },
    {
        "slug": "time_tracking",
        "setup_question": "Do you need to track time spent on jobs or projects?",
        "setup_question_description": "Log hours manually or with a timer, and link time entries to invoices.",
    },
    {
        "slug": "expenses",
        "setup_question": "Do you track business expenses against jobs or projects?",
        "setup_question_description": "Log expenses and optionally pass them through to customer invoices.",
    },
    {
        "slug": "inventory",
        "setup_question": "Do you sell or track physical products and stock?",
        "setup_question_description": "Manage product catalogues, stock levels, pricing rules, and barcode scanning.",
    },
    {
        "slug": "purchase_orders",
        "setup_question": "Do you raise purchase orders with suppliers?",
        "setup_question_description": "Create purchase orders, receive goods, and link them to inventory.",
    },
    {
        "slug": "pos",
        "setup_question": "Do you need a point-of-sale terminal for walk-in sales?",
        "setup_question_description": "POS mode with receipt printing and offline transaction queuing.",
    },
    {
        "slug": "tipping",
        "setup_question": "Would you like to accept tips on invoices or POS transactions?",
        "setup_question_description": "Collect tips and allocate them to staff members.",
    },
    {
        "slug": "tables",
        "setup_question": "Do you manage tables or seating in a venue?",
        "setup_question_description": "Visual floor plans, table status tracking, and reservations.",
    },
    {
        "slug": "kitchen_display",
        "setup_question": "Do you need a kitchen display for food preparation orders?",
        "setup_question_description": "Order display and tick-off interface for kitchen staff.",
    },
    {
        "slug": "scheduling",
        "setup_question": "Do you need a visual calendar for scheduling work?",
        "setup_question_description": "Drag-and-drop scheduling and resource allocation.",
    },
    {
        "slug": "staff",
        "setup_question": "Do you manage staff members or contractors?",
        "setup_question_description": "Staff profiles, job assignment, and labour cost tracking.",
    },
    {
        "slug": "bookings",
        "setup_question": "Do your customers book appointments with you?",
        "setup_question_description": "Customer-facing booking pages and appointment management.",
    },
    {
        "slug": "progress_claims",
        "setup_question": "Do you submit progress claims on construction contracts?",
        "setup_question_description": "Progress claims against contract values with variation tracking.",
    },
    {
        "slug": "retentions",
        "setup_question": "Do you track retentions on construction projects?",
        "setup_question_description": "Retention tracking per project with release scheduling.",
    },
    {
        "slug": "variations",
        "setup_question": "Do you handle scope change orders on projects?",
        "setup_question_description": "Variation orders, approval workflows, and contract value updates.",
    },
    {
        "slug": "compliance_docs",
        "setup_question": "Do you need to manage compliance certificates or documents?",
        "setup_question_description": "Certification and compliance document management linked to invoices.",
    },
    {
        "slug": "multi_currency",
        "setup_question": "Do you invoice in multiple currencies?",
        "setup_question_description": "Multi-currency invoicing with exchange rate management.",
    },
    {
        "slug": "recurring",
        "setup_question": "Do you send recurring invoices on a schedule?",
        "setup_question_description": "Automated recurring invoice generation.",
    },
    {
        "slug": "loyalty",
        "setup_question": "Would you like to offer a loyalty program to your customers?",
        "setup_question_description": "Points, membership tiers, and auto-applied discounts.",
    },
    {
        "slug": "franchise",
        "setup_question": "Do you operate multiple locations or a franchise?",
        "setup_question_description": "Multi-location support with centralised reporting.",
    },
    {
        "slug": "ecommerce",
        "setup_question": "Do you sell products online through an ecommerce store?",
        "setup_question_description": "WooCommerce integration and API-based order ingestion.",
    },
]


def upgrade() -> None:
    # -- Add setup_question column (idempotent) ------------------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'module_registry'
                  AND column_name = 'setup_question'
            ) THEN
                ALTER TABLE module_registry
                ADD COLUMN setup_question TEXT;
            END IF;
        END $$
    """)

    # -- Add setup_question_description column (idempotent) ------------------
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'module_registry'
                  AND column_name = 'setup_question_description'
            ) THEN
                ALTER TABLE module_registry
                ADD COLUMN setup_question_description TEXT;
            END IF;
        END $$
    """)

    # -- Seed setup questions for all 23 non-core modules --------------------
    for mod in SETUP_QUESTIONS:
        # Escape single quotes in text values for safe SQL
        slug = mod["slug"]
        question = mod["setup_question"].replace("'", "''")
        description = mod["setup_question_description"].replace("'", "''")
        op.execute(
            f"""
            UPDATE module_registry
            SET setup_question = '{question}',
                setup_question_description = '{description}'
            WHERE slug = '{slug}'
            """
        )


def downgrade() -> None:
    op.drop_column("module_registry", "setup_question_description")
    op.drop_column("module_registry", "setup_question")
