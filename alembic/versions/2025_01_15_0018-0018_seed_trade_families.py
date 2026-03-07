"""Seed trade_families with 15 families.

Revision ID: 0018
Revises: 0017
Create Date: 2025-01-15

Requirements: 3.1, 3.4
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str = "0017"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

TRADE_FAMILIES = [
    {"slug": "automotive-transport", "display_name": "Automotive & Transport", "icon": "truck", "display_order": 1},
    {"slug": "electrical-mechanical", "display_name": "Electrical & Mechanical", "icon": "zap", "display_order": 2},
    {"slug": "plumbing-gas", "display_name": "Plumbing & Gas", "icon": "droplet", "display_order": 3},
    {"slug": "building-construction", "display_name": "Building & Construction", "icon": "hard-hat", "display_order": 4},
    {"slug": "landscaping-outdoor", "display_name": "Landscaping & Outdoor", "icon": "tree", "display_order": 5},
    {"slug": "cleaning-facilities", "display_name": "Cleaning & Facilities", "icon": "sparkles", "display_order": 6},
    {"slug": "it-technology", "display_name": "IT & Technology", "icon": "monitor", "display_order": 7},
    {"slug": "creative-professional", "display_name": "Creative & Professional Services", "icon": "palette", "display_order": 8},
    {"slug": "accounting-legal-financial", "display_name": "Accounting Legal & Financial", "icon": "briefcase", "display_order": 9},
    {"slug": "health-wellness", "display_name": "Health & Wellness", "icon": "heart-pulse", "display_order": 10},
    {"slug": "food-hospitality", "display_name": "Food & Hospitality", "icon": "utensils", "display_order": 11},
    {"slug": "retail", "display_name": "Retail", "icon": "shopping-bag", "display_order": 12},
    {"slug": "hair-beauty-personal-care", "display_name": "Hair Beauty & Personal Care", "icon": "scissors", "display_order": 13},
    {"slug": "trades-support-hire", "display_name": "Trades Support & Hire", "icon": "wrench", "display_order": 14},
    {"slug": "freelancing-contracting", "display_name": "Freelancing & Contracting", "icon": "user", "display_order": 15},
]


def upgrade() -> None:
    trade_families = sa.table(
        "trade_families",
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("icon", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(trade_families, [
        {**f, "is_active": True} for f in TRADE_FAMILIES
    ])


def downgrade() -> None:
    slugs = [f["slug"] for f in TRADE_FAMILIES]
    op.execute(
        sa.text("DELETE FROM trade_families WHERE slug = ANY(:slugs)").bindparams(
            slugs=slugs
        )
    )
