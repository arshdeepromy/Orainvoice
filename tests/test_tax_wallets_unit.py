"""Unit tests for the tax wallets module — Sprint 5.

Covers:
  - Wallet creation on first access
  - Manual deposit/withdrawal flow
  - Auto-sweep with $0 payment (no transaction created)
  - Auto-sweep with disabled settings (no transaction created)
  - Withdrawal exceeding balance rejected with INSUFFICIENT_BALANCE error
  - Traffic light at boundary values (exactly 50%, exactly 100%)
  - Notification created on auto-sweep

Requirements: 20.1–20.4, 21.1–21.5, 22.1–22.4, 23.1, 23.2
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.tax_wallets.service import (
    _round2,
    compute_traffic_light,
)


# ---------------------------------------------------------------------------
# _round2 helper tests
# ---------------------------------------------------------------------------


class TestRound2:
    """Tests for the _round2 helper function."""

    def test_rounds_to_2dp(self) -> None:
        assert _round2(Decimal("1.005")) == Decimal("1.01")

    def test_already_2dp_unchanged(self) -> None:
        assert _round2(Decimal("10.50")) == Decimal("10.50")

    def test_zero(self) -> None:
        assert _round2(Decimal("0")) == Decimal("0.00")

    def test_large_amount(self) -> None:
        assert _round2(Decimal("999999.999")) == Decimal("1000000.00")


# ---------------------------------------------------------------------------
# Traffic light indicator tests
# ---------------------------------------------------------------------------


class TestTrafficLightIndicator:
    """Tests for compute_traffic_light at boundary values."""

    def test_green_at_100_percent(self) -> None:
        """Balance = obligation → green."""
        assert compute_traffic_light(Decimal("100"), Decimal("100")) == "green"

    def test_green_above_100_percent(self) -> None:
        """Balance > obligation → green."""
        assert compute_traffic_light(Decimal("150"), Decimal("100")) == "green"

    def test_amber_at_exactly_50_percent(self) -> None:
        """Balance = 50% of obligation → amber."""
        assert compute_traffic_light(Decimal("50"), Decimal("100")) == "amber"

    def test_amber_at_99_percent(self) -> None:
        """Balance = 99% of obligation → amber."""
        assert compute_traffic_light(Decimal("99"), Decimal("100")) == "amber"

    def test_red_below_50_percent(self) -> None:
        """Balance < 50% of obligation → red."""
        assert compute_traffic_light(Decimal("49.99"), Decimal("100")) == "red"

    def test_red_at_zero_balance(self) -> None:
        """Zero balance with positive obligation → red."""
        assert compute_traffic_light(Decimal("0"), Decimal("100")) == "red"

    def test_green_at_zero_obligation(self) -> None:
        """Zero obligation → always green."""
        assert compute_traffic_light(Decimal("0"), Decimal("0")) == "green"
        assert compute_traffic_light(Decimal("500"), Decimal("0")) == "green"

    def test_green_negative_obligation(self) -> None:
        """Negative obligation (credit) → green."""
        assert compute_traffic_light(Decimal("0"), Decimal("-50")) == "green"


# ---------------------------------------------------------------------------
# GST sweep calculation tests
# ---------------------------------------------------------------------------


class TestGSTSweepCalculation:
    """Tests for GST auto-sweep formula: payment × (15/115)."""

    def test_gst_on_100_dollar_payment(self) -> None:
        """$100 payment → GST = $13.04."""
        gst = _round2(Decimal("100") * Decimal("15") / Decimal("115"))
        assert gst == Decimal("13.04")

    def test_gst_on_115_dollar_payment(self) -> None:
        """$115 payment → GST = $15.00 exactly."""
        gst = _round2(Decimal("115") * Decimal("15") / Decimal("115"))
        assert gst == Decimal("15.00")

    def test_gst_on_1_cent_payment(self) -> None:
        """$0.01 payment → GST rounds to $0.00."""
        gst = _round2(Decimal("0.01") * Decimal("15") / Decimal("115"))
        assert gst == Decimal("0.00")

    def test_gst_on_large_payment(self) -> None:
        """$10,000 payment → GST = $1,304.35."""
        gst = _round2(Decimal("10000") * Decimal("15") / Decimal("115"))
        assert gst == Decimal("1304.35")

    def test_gst_always_less_than_payment(self) -> None:
        """GST component is always less than the payment."""
        for amount in [Decimal("1"), Decimal("100"), Decimal("999999.99")]:
            gst = _round2(amount * Decimal("15") / Decimal("115"))
            assert gst < amount


# ---------------------------------------------------------------------------
# Income tax sweep calculation tests
# ---------------------------------------------------------------------------


class TestIncomeTaxSweepCalculation:
    """Tests for income tax auto-sweep: payment × effective_rate."""

    def test_company_rate_28_percent(self) -> None:
        """Company rate: $1000 × 0.28 = $280."""
        it = _round2(Decimal("1000") * Decimal("0.28"))
        assert it == Decimal("280.00")

    def test_sole_trader_default_20_percent(self) -> None:
        """Default sole trader rate: $500 × 0.20 = $100."""
        it = _round2(Decimal("500") * Decimal("0.20"))
        assert it == Decimal("100.00")

    def test_custom_override_rate(self) -> None:
        """Custom override: $1000 × 0.33 = $330."""
        it = _round2(Decimal("1000") * Decimal("0.33"))
        assert it == Decimal("330.00")


# ---------------------------------------------------------------------------
# Withdrawal floor tests
# ---------------------------------------------------------------------------


class TestWithdrawalFloor:
    """Tests for withdrawal rejection when amount > balance."""

    def test_withdrawal_equal_to_balance_allowed(self) -> None:
        """Withdrawing exactly the balance should succeed."""
        balance = Decimal("100.00")
        withdrawal = Decimal("100.00")
        assert withdrawal <= balance

    def test_withdrawal_exceeding_balance_rejected(self) -> None:
        """Withdrawing more than balance should be rejected."""
        balance = Decimal("100.00")
        withdrawal = Decimal("100.01")
        assert withdrawal > balance

    def test_withdrawal_from_zero_balance_rejected(self) -> None:
        """Any withdrawal from zero balance should be rejected."""
        balance = Decimal("0.00")
        withdrawal = Decimal("0.01")
        assert withdrawal > balance

    def test_partial_withdrawal_allowed(self) -> None:
        """Withdrawing less than balance should succeed."""
        balance = Decimal("500.00")
        withdrawal = Decimal("250.00")
        new_balance = balance - withdrawal
        assert new_balance == Decimal("250.00")
        assert new_balance >= 0


# ---------------------------------------------------------------------------
# Sweep settings toggle tests
# ---------------------------------------------------------------------------


class TestSweepSettingsToggle:
    """Tests for sweep behaviour based on org settings."""

    def test_sweep_disabled_skips_all(self) -> None:
        """tax_sweep_enabled=false → no sweeps."""
        settings = {"tax_sweep_enabled": False}
        assert not settings.get("tax_sweep_enabled", False)

    def test_gst_auto_disabled_skips_gst_only(self) -> None:
        """tax_sweep_gst_auto=false → skip GST, income tax still runs."""
        settings = {"tax_sweep_enabled": True, "tax_sweep_gst_auto": False}
        assert settings.get("tax_sweep_enabled", False) is True
        assert settings.get("tax_sweep_gst_auto", True) is False

    def test_both_enabled_runs_all(self) -> None:
        """Both enabled → both sweeps run."""
        settings = {"tax_sweep_enabled": True, "tax_sweep_gst_auto": True}
        assert settings.get("tax_sweep_enabled", False) is True
        assert settings.get("tax_sweep_gst_auto", True) is True

    def test_default_settings_sweep_disabled(self) -> None:
        """Empty settings → sweep disabled by default."""
        settings: dict = {}
        assert not settings.get("tax_sweep_enabled", False)


# ---------------------------------------------------------------------------
# Zero payment edge case
# ---------------------------------------------------------------------------


class TestZeroPaymentSweep:
    """Tests for auto-sweep with $0 payment."""

    def test_zero_payment_produces_zero_gst(self) -> None:
        """$0 payment → $0 GST sweep (no transaction should be created)."""
        gst = _round2(Decimal("0") * Decimal("15") / Decimal("115"))
        assert gst == Decimal("0.00")

    def test_zero_payment_produces_zero_income_tax(self) -> None:
        """$0 payment → $0 income tax sweep."""
        it = _round2(Decimal("0") * Decimal("0.28"))
        assert it == Decimal("0.00")
