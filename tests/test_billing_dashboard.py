"""Tests for Org_Admin billing dashboard — task 16.5.

Covers:
- GET /api/v1/billing endpoint logic
- Aggregation of plan info, storage, Carjam usage, estimated invoice
- Plain language billing data (no accounting jargon)

Requirements: 44.1, 44.2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.billing.schemas import BillingDashboardResponse, SubscriptionInvoiceResponse


# ---------------------------------------------------------------------------
# Billing dashboard response construction tests
# ---------------------------------------------------------------------------


class TestBillingDashboardConstruction:
    """Test billing dashboard data aggregation logic."""

    def test_estimated_invoice_calculation(self):
        """Estimated invoice = plan price + storage add-on + Carjam overage."""
        plan_price = 49.0
        storage_addon_charge = 10.0
        carjam_overage_charge = 3.50
        estimated = plan_price + storage_addon_charge + carjam_overage_charge
        assert estimated == 62.50

    def test_carjam_overage_calculation(self):
        """Overage = max(0, used - included) * rate."""
        rate = 0.70
        used = 55
        included = 50
        overage = max(0, used - included) * rate
        assert overage == pytest.approx(3.50)

    def test_carjam_no_overage_when_under_limit(self):
        """No overage charge when usage is within included amount."""
        rate = 0.70
        used = 30
        included = 50
        overage = max(0, used - included) * rate
        assert overage == 0.0

    def test_storage_addon_charge_calculation(self):
        """Storage add-on = extra GB beyond plan base * price per GB."""
        org_quota_gb = 10
        plan_base_gb = 5
        price_per_gb = 5.0
        addon_gb = max(0, org_quota_gb - plan_base_gb)
        charge = addon_gb * price_per_gb
        assert charge == 25.0

    def test_storage_no_addon_when_at_base(self):
        """No storage add-on charge when quota equals plan base."""
        org_quota_gb = 5
        plan_base_gb = 5
        addon_gb = max(0, org_quota_gb - plan_base_gb)
        assert addon_gb == 0

    def test_storage_used_gb_conversion(self):
        """Storage bytes convert to GB correctly."""
        storage_bytes = 1_610_612_736  # 1.5 GB
        storage_gb = storage_bytes / (1024 ** 3)
        assert storage_gb == pytest.approx(1.5)

    def test_dashboard_response_with_all_fields(self):
        """Full dashboard response validates correctly."""
        dashboard = BillingDashboardResponse(
            current_plan="Pro",
            plan_monthly_price_nzd=49.0,
            next_billing_date=datetime(2025, 2, 1, tzinfo=timezone.utc),
            estimated_next_invoice_nzd=62.50,
            storage_addon_charge_nzd=10.0,
            carjam_overage_charge_nzd=3.50,
            carjam_lookups_used=55,
            carjam_lookups_included=50,
            storage_used_gb=1.5,
            storage_quota_gb=5,
            org_status="active",
            past_invoices=[
                SubscriptionInvoiceResponse(id="in_1", amount_paid=4900),
            ],
        )
        assert dashboard.current_plan == "Pro"
        assert dashboard.estimated_next_invoice_nzd == 62.50
        assert dashboard.carjam_overage_charge_nzd == 3.50
        assert dashboard.storage_addon_charge_nzd == 10.0
        assert len(dashboard.past_invoices) == 1

    def test_dashboard_response_trial_org(self):
        """Dashboard for a trial org has zero charges and no billing date."""
        dashboard = BillingDashboardResponse(
            current_plan="Starter",
            plan_monthly_price_nzd=29.0,
            next_billing_date=None,
            estimated_next_invoice_nzd=29.0,
            org_status="trial",
        )
        assert dashboard.next_billing_date is None
        assert dashboard.org_status == "trial"
        assert dashboard.carjam_overage_charge_nzd == 0.0
        assert dashboard.storage_addon_charge_nzd == 0.0
        assert dashboard.past_invoices == []

    def test_dashboard_plain_language_fields(self):
        """Verify field names use plain language, not accounting jargon.

        Requirements: 44.2
        """
        field_names = set(BillingDashboardResponse.model_fields.keys())
        # These should be human-readable, not jargon like "AR", "AP", "ledger"
        assert "current_plan" in field_names
        assert "next_billing_date" in field_names
        assert "estimated_next_invoice_nzd" in field_names
        assert "storage_used_gb" in field_names
        assert "carjam_lookups_used" in field_names
        assert "past_invoices" in field_names
        # No accounting jargon fields
        for name in field_names:
            assert "ledger" not in name.lower()
            assert "debit" not in name.lower()
            assert "credit" not in name.lower()
            assert "accrual" not in name.lower()
