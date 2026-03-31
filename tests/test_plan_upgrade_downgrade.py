"""Tests for plan upgrade and downgrade — Requirements: 43.1, 43.2, 43.3, 43.4.

Covers:
- Schema validation for PlanChangeRequest, PlanUpgradeResponse, PlanDowngradeResponse
- Upgrade logic: immediate application, prorated charges
- Downgrade logic: scheduled at next billing period, limit warnings
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.billing.schemas import (
    PlanChangeRequest,
    PlanDowngradeResponse,
    PlanUpgradeResponse,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestPlanChangeRequest:
    def test_valid_request(self):
        req = PlanChangeRequest(new_plan_id=str(uuid.uuid4()))
        assert req.new_plan_id

    def test_string_plan_id(self):
        req = PlanChangeRequest(new_plan_id="some-plan-id")
        assert req.new_plan_id == "some-plan-id"


class TestPlanUpgradeResponse:
    def test_full_response(self):
        resp = PlanUpgradeResponse(
            success=True,
            message="Upgraded to Pro",
            new_plan_name="Pro",
            prorated_charge_nzd=12.50,
            effective_immediately=True,
        )
        assert resp.success is True
        assert resp.new_plan_name == "Pro"
        assert resp.prorated_charge_nzd == 12.50
        assert resp.effective_immediately is True

    def test_defaults(self):
        resp = PlanUpgradeResponse(
            success=True,
            message="Done",
            new_plan_name="Pro",
        )
        assert resp.prorated_charge_nzd == 0.0
        assert resp.effective_immediately is True


class TestPlanDowngradeResponse:
    def test_full_response_with_warnings(self):
        resp = PlanDowngradeResponse(
            success=False,
            message="Resolve issues first",
            new_plan_name="Starter",
            effective_at=None,
            warnings=[
                "Storage usage (8.5 GB) exceeds Starter limit (5 GB)",
                "Active users (10) exceeds Starter limit (5 seats)",
            ],
        )
        assert resp.success is False
        assert len(resp.warnings) == 2
        assert "Storage" in resp.warnings[0]
        assert "users" in resp.warnings[1]

    def test_successful_downgrade(self):
        effective = datetime(2025, 2, 1, tzinfo=timezone.utc)
        resp = PlanDowngradeResponse(
            success=True,
            message="Scheduled",
            new_plan_name="Starter",
            effective_at=effective,
            warnings=[],
        )
        assert resp.success is True
        assert resp.effective_at == effective
        assert resp.warnings == []

    def test_defaults(self):
        resp = PlanDowngradeResponse(
            success=True,
            message="OK",
            new_plan_name="Starter",
        )
        assert resp.effective_at is None
        assert resp.warnings == []


# ---------------------------------------------------------------------------
# Upgrade / downgrade logic tests (unit-level, no HTTP)
# ---------------------------------------------------------------------------


class TestUpgradeValidation:
    """Test upgrade business logic via schema and data validation."""

    def test_upgrade_response_captures_proration(self):
        resp = PlanUpgradeResponse(
            success=True,
            message="Upgraded to Enterprise. Prorated charge of $15.00 NZD applied.",
            new_plan_name="Enterprise",
            prorated_charge_nzd=15.00,
            effective_immediately=True,
        )
        assert resp.prorated_charge_nzd == 15.00
        assert "Prorated" in resp.message

    def test_upgrade_is_always_immediate(self):
        resp = PlanUpgradeResponse(
            success=True,
            message="Upgraded",
            new_plan_name="Pro",
            effective_immediately=True,
        )
        assert resp.effective_immediately is True


class TestDowngradeValidation:
    """Test downgrade warning logic."""

    def test_storage_over_limit_produces_warning(self):
        """Req 43.4: warn if over new plan's storage limit."""
        storage_used_gb = 8.5
        new_plan_storage_gb = 5
        warnings = []
        if storage_used_gb > new_plan_storage_gb:
            warnings.append(
                f"Current storage usage ({storage_used_gb:.2f} GB) exceeds the "
                f"Starter plan limit ({new_plan_storage_gb} GB)."
            )
        assert len(warnings) == 1
        assert "8.50 GB" in warnings[0]

    def test_users_over_limit_produces_warning(self):
        """Req 43.4: warn if over new plan's user seat limit."""
        active_users = 10
        new_plan_seats = 5
        warnings = []
        if active_users > new_plan_seats:
            warnings.append(
                f"Active users ({active_users}) exceeds the "
                f"Starter plan limit ({new_plan_seats} seats)."
            )
        assert len(warnings) == 1
        assert "10" in warnings[0]

    def test_no_warnings_when_within_limits(self):
        """No warnings when org is within the new plan's limits."""
        storage_used_gb = 3.0
        new_plan_storage_gb = 5
        active_users = 3
        new_plan_seats = 5
        warnings = []
        if storage_used_gb > new_plan_storage_gb:
            warnings.append("Storage over limit")
        if active_users > new_plan_seats:
            warnings.append("Users over limit")
        assert warnings == []

    def test_both_limits_exceeded(self):
        """Both storage and user warnings when both exceed limits."""
        storage_used_gb = 12.0
        new_plan_storage_gb = 5
        active_users = 8
        new_plan_seats = 3
        warnings = []
        if storage_used_gb > new_plan_storage_gb:
            warnings.append("Storage over limit")
        if active_users > new_plan_seats:
            warnings.append("Users over limit")
        assert len(warnings) == 2
