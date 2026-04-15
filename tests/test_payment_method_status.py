"""Unit tests for GET /billing/payment-method-status endpoint.

Covers:
- Org with 0 payment methods → has_payment_method=False
- Org with 1 non-expiring method → has_payment_method=True, has_expiring_soon=False
- Org with multiple methods, one expiring → correct expiring_method returned
- org_id=None (global_admin) → safe defaults
- Response contains only allowed fields (no stripe_payment_method_id leakage)

Requirements: 1.3, 4.2, 4.4, 4.5, 4.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db_session
from app.modules.billing.router import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payment_method(
    *,
    org_id: uuid.UUID,
    brand: str = "Visa",
    last4: str = "4242",
    exp_month: int = 12,
    exp_year: int = 2030,
    stripe_payment_method_id: str | None = None,
) -> MagicMock:
    """Create a mock OrgPaymentMethod row."""
    pm = MagicMock()
    pm.id = uuid.uuid4()
    pm.org_id = org_id
    pm.brand = brand
    pm.last4 = last4
    pm.exp_month = exp_month
    pm.exp_year = exp_year
    pm.stripe_payment_method_id = stripe_payment_method_id or f"pm_{uuid.uuid4().hex[:16]}"
    pm.is_default = False
    pm.is_verified = True
    pm.created_at = datetime.now(timezone.utc)
    return pm


def _build_app(
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    role: str = "org_admin",
    db_methods: list | None = None,
) -> FastAPI:
    """Build a minimal FastAPI app with the billing router and mocked deps.

    Sets request.state attributes via middleware and overrides get_db_session
    to return a mock that yields the given payment method rows.
    """
    app = FastAPI()

    # Middleware to set request.state (simulates auth middleware)
    @app.middleware("http")
    async def _inject_user(request: Request, call_next):
        request.state.user_id = user_id or str(uuid.uuid4())
        request.state.org_id = org_id
        request.state.role = role
        return await call_next(request)

    # Mock DB session
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = db_methods or []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    async def _override_db():
        yield mock_db

    app.dependency_overrides[get_db_session] = _override_db
    app.include_router(router, prefix="/api/v1/billing")

    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPaymentMethodStatusEndpoint:
    """Tests for GET /api/v1/billing/payment-method-status."""

    @pytest.mark.asyncio
    async def test_org_with_zero_payment_methods(self):
        """Org with 0 payment methods → has_payment_method=False.

        Requirements: 1.3, 4.2
        """
        org_id = str(uuid.uuid4())
        app = _build_app(org_id=org_id, db_methods=[])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/billing/payment-method-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_payment_method"] is False
        assert data["has_expiring_soon"] is False
        assert data["expiring_method"] is None

    @pytest.mark.asyncio
    async def test_org_with_one_non_expiring_method(self):
        """Org with 1 non-expiring method → has_payment_method=True, has_expiring_soon=False.

        Requirements: 1.3, 4.2
        """
        org_id = uuid.uuid4()
        pm = _make_payment_method(
            org_id=org_id,
            brand="Visa",
            last4="1234",
            exp_month=12,
            exp_year=2040,  # Far future — not expiring soon
        )
        app = _build_app(org_id=str(org_id), db_methods=[pm])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/billing/payment-method-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_payment_method"] is True
        assert data["has_expiring_soon"] is False
        assert data["expiring_method"] is None

    @pytest.mark.asyncio
    async def test_org_with_multiple_methods_one_expiring(self):
        """Org with multiple methods, one expiring → correct expiring_method returned.

        The endpoint should identify the soonest-expiring method among those
        within 30 days and return its details.

        Requirements: 1.3, 4.2
        """
        org_id = uuid.uuid4()
        # Use a date that is definitely in the past (already expired = expiring soon)
        pm_expiring = _make_payment_method(
            org_id=org_id,
            brand="Mastercard",
            last4="9999",
            exp_month=1,
            exp_year=2020,  # Already expired
        )
        pm_safe = _make_payment_method(
            org_id=org_id,
            brand="Visa",
            last4="1111",
            exp_month=12,
            exp_year=2040,  # Far future
        )
        app = _build_app(org_id=str(org_id), db_methods=[pm_safe, pm_expiring])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/billing/payment-method-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_payment_method"] is True
        assert data["has_expiring_soon"] is True
        assert data["expiring_method"] is not None
        assert data["expiring_method"]["brand"] == "Mastercard"
        assert data["expiring_method"]["last4"] == "9999"
        assert data["expiring_method"]["exp_month"] == 1
        assert data["expiring_method"]["exp_year"] == 2020

    @pytest.mark.asyncio
    async def test_global_admin_no_org_returns_safe_defaults(self):
        """org_id=None (global_admin) → safe defaults.

        Requirements: 4.4, 4.5
        """
        app = _build_app(org_id=None, role="global_admin")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/billing/payment-method-status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["has_payment_method"] is True
        assert data["has_expiring_soon"] is False
        assert data["expiring_method"] is None

    @pytest.mark.asyncio
    async def test_response_contains_only_allowed_fields(self):
        """Response contains only allowed fields — no stripe_payment_method_id leakage.

        Requirements: 4.7
        """
        org_id = uuid.uuid4()
        pm = _make_payment_method(
            org_id=org_id,
            brand="Amex",
            last4="0005",
            exp_month=1,
            exp_year=2020,  # Expired → will appear in expiring_method
            stripe_payment_method_id="pm_secret_should_not_leak",
        )
        app = _build_app(org_id=str(org_id), db_methods=[pm])

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/billing/payment-method-status")

        assert resp.status_code == 200
        data = resp.json()

        # Top-level fields must be exactly these three
        allowed_top_level = {"has_payment_method", "has_expiring_soon", "expiring_method"}
        assert set(data.keys()) == allowed_top_level

        # expiring_method must only contain safe card details
        assert data["expiring_method"] is not None
        allowed_expiring_fields = {"brand", "last4", "exp_month", "exp_year"}
        assert set(data["expiring_method"].keys()) == allowed_expiring_fields

        # Explicitly verify no sensitive fields leaked
        raw = resp.text
        assert "pm_secret_should_not_leak" not in raw
        assert "stripe_payment_method_id" not in raw
