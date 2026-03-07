"""Shared Hypothesis strategies for the comprehensive PBT suite.

Provides reusable strategies for generating valid domain objects:
org, invoice, customer, product, job, and supporting types.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from hypothesis import strategies as st, settings as h_settings, HealthCheck

# ---------------------------------------------------------------------------
# Common PBT settings used across all property test modules
# ---------------------------------------------------------------------------

PBT_SETTINGS = h_settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Primitive strategies
# ---------------------------------------------------------------------------

uuid_strategy = st.uuids()
uuid_str_strategy = st.uuids().map(str)

price_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

quantity_strategy = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("9999"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

positive_int_quantity = st.integers(min_value=1, max_value=500)

tax_rate_strategy = st.sampled_from([
    Decimal("0"), Decimal("5"), Decimal("10"), Decimal("15"), Decimal("20"),
])

discount_strategy = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("50"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

currency_strategy = st.sampled_from(["NZD", "AUD", "GBP", "USD", "EUR", "CAD"])

country_code_strategy = st.sampled_from(["NZ", "AU", "UK", "US", "CA", "DE", "FR"])

trade_category_strategy = st.sampled_from([
    "vehicle-workshop", "electrician", "plumber", "builder",
    "landscaper", "cleaner", "it-services", "graphic-designer",
    "accountant", "physiotherapist", "cafe", "retail-store",
    "hairdresser", "tool-hire", "freelancer",
])

trade_family_strategy = st.sampled_from([
    "automotive-transport", "electrical-mechanical", "plumbing-gas",
    "building-construction", "landscaping-outdoor", "cleaning-facilities",
    "it-technology", "creative-professional", "accounting-legal-financial",
    "health-wellness", "food-hospitality", "retail",
    "hair-beauty-personal-care", "trades-support-hire", "freelancing-contracting",
])

module_slug_strategy = st.sampled_from([
    "invoicing", "customers", "notifications", "inventory", "jobs",
    "quotes", "time_tracking", "projects", "expenses", "purchase_orders",
    "staff", "scheduling", "bookings", "pos", "tipping", "tables",
    "kitchen_display", "retentions", "progress_claims", "variations",
    "compliance_docs", "multi_currency", "loyalty", "ecommerce",
    "franchise", "recurring_invoices", "branding",
])

plan_tier_strategy = st.sampled_from(["free", "starter", "professional", "enterprise"])

safe_text_strategy = st.text(
    min_size=1,
    max_size=80,
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
).filter(lambda s: s.strip())

email_strategy = st.emails()

phone_strategy = st.from_regex(r"\+?\d{7,15}", fullmatch=True)

date_strategy = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))

# ---------------------------------------------------------------------------
# Domain object strategies
# ---------------------------------------------------------------------------


def org_strategy():
    """Generate a valid organisation dict with random trade category, country, modules."""
    return st.fixed_dictionaries({
        "id": uuid_strategy,
        "name": safe_text_strategy,
        "trade_category_slug": trade_category_strategy,
        "trade_family_slug": trade_family_strategy,
        "country_code": country_code_strategy,
        "base_currency": currency_strategy,
        "plan_tier": plan_tier_strategy,
        "tax_rate": tax_rate_strategy,
        "tax_inclusive": st.booleans(),
        "enabled_modules": st.lists(module_slug_strategy, min_size=1, max_size=10, unique=True),
    })


def customer_strategy():
    """Generate a valid customer dict."""
    return st.fixed_dictionaries({
        "id": uuid_strategy,
        "name": safe_text_strategy,
        "email": st.one_of(st.none(), email_strategy),
        "phone": st.one_of(st.none(), phone_strategy),
        "is_active": st.just(True),
    })


def line_item_strategy():
    """Generate a single invoice line item."""
    return st.fixed_dictionaries({
        "description": safe_text_strategy,
        "quantity": quantity_strategy,
        "unit_price": price_strategy,
        "tax_rate": tax_rate_strategy,
        "discount": discount_strategy,
    })


def invoice_strategy():
    """Generate a valid invoice dict with random line items, tax, currency."""
    return st.fixed_dictionaries({
        "id": uuid_strategy,
        "org_id": uuid_strategy,
        "customer_id": uuid_strategy,
        "invoice_number": st.from_regex(r"INV-\d{5}", fullmatch=True),
        "currency": currency_strategy,
        "tax_rate": tax_rate_strategy,
        "tax_inclusive": st.booleans(),
        "line_items": st.lists(line_item_strategy(), min_size=1, max_size=10),
        "issue_date": date_strategy,
        "status": st.sampled_from(["draft", "issued", "paid", "overdue", "cancelled"]),
    })


def product_strategy():
    """Generate a valid product dict."""
    return st.fixed_dictionaries({
        "id": uuid_strategy,
        "org_id": uuid_strategy,
        "name": safe_text_strategy,
        "sku": st.from_regex(r"SKU-[A-Z0-9]{4,8}", fullmatch=True),
        "sale_price": price_strategy,
        "cost_price": price_strategy,
        "stock_quantity": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("10000"),
            places=3, allow_nan=False, allow_infinity=False,
        ),
        "low_stock_threshold": st.decimals(
            min_value=Decimal("0"), max_value=Decimal("100"),
            places=3, allow_nan=False, allow_infinity=False,
        ),
        "is_active": st.just(True),
    })


def job_strategy():
    """Generate a valid job dict."""
    return st.fixed_dictionaries({
        "id": uuid_strategy,
        "org_id": uuid_strategy,
        "job_number": st.from_regex(r"JOB-\d{5}", fullmatch=True),
        "title": safe_text_strategy,
        "status": st.sampled_from([
            "draft", "scheduled", "in_progress", "on_hold",
            "completed", "invoiced", "cancelled",
        ]),
        "customer_id": st.one_of(st.none(), uuid_strategy),
        "description": st.one_of(st.none(), safe_text_strategy),
    })


# ---------------------------------------------------------------------------
# Exchange rate strategy
# ---------------------------------------------------------------------------

exchange_rate_strategy = st.decimals(
    min_value=Decimal("0.001"),
    max_value=Decimal("10000"),
    places=6,
    allow_nan=False,
    allow_infinity=False,
)

# ---------------------------------------------------------------------------
# Movement type strategy
# ---------------------------------------------------------------------------

movement_type_strategy = st.sampled_from([
    "sale", "credit", "purchase", "adjustment", "transfer", "return", "stocktake",
])

# ---------------------------------------------------------------------------
# Job status strategies
# ---------------------------------------------------------------------------

from app.modules.jobs_v2.schemas import JOB_STATUSES, VALID_TRANSITIONS  # noqa: E402

job_status_strategy = st.sampled_from(JOB_STATUSES)
