"""Shared fixtures for integration tests.

Provides:
- mock_db: AsyncMock database session
- test_org_factory: factory for creating test organisation dicts
- authenticated_client: mock authenticated HTTP client fixture
- Common mock helpers for services used across integration tests
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Test org factory
# ---------------------------------------------------------------------------

def make_test_org(
    *,
    org_id: uuid.UUID | None = None,
    name: str = "Test Organisation",
    country_code: str = "NZ",
    trade_category_slug: str = "general-automotive",
    base_currency: str = "NZD",
    tax_label: str = "GST",
    default_tax_rate: float = 15.0,
    timezone_str: str = "Pacific/Auckland",
    modules: list[str] | None = None,
) -> dict:
    """Create a test organisation dict with sensible defaults."""
    return {
        "id": org_id or uuid.uuid4(),
        "name": name,
        "country_code": country_code,
        "trade_category_slug": trade_category_slug,
        "base_currency": base_currency,
        "tax_label": tax_label,
        "default_tax_rate": default_tax_rate,
        "timezone": timezone_str,
        "tax_inclusive_default": True,
        "date_format": "dd/MM/yyyy",
        "number_format": "en-NZ",
        "locale": "en-NZ",
        "modules": modules or ["invoicing", "customers"],
        "setup_wizard_state": {},
        "storage_used_bytes": 0,
        "storage_quota_bytes": 5368709120,
        "is_multi_location": False,
        "white_label_enabled": False,
    }


@pytest.fixture
def test_org_factory():
    """Fixture that returns the make_test_org factory function."""
    return make_test_org


# ---------------------------------------------------------------------------
# Mock database session
# ---------------------------------------------------------------------------

def _create_mock_db():
    """Create a mock async DB session with common operations."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.delete = AsyncMock()
    db.refresh = AsyncMock()

    # Default execute returns empty result
    default_result = MagicMock()
    default_result.scalar_one_or_none.return_value = None
    default_result.scalar.return_value = 0
    default_result.scalars.return_value.all.return_value = []
    default_result.fetchall.return_value = []
    db.execute = AsyncMock(return_value=default_result)

    return db


@pytest.fixture
def mock_db():
    """Provide a mock async database session."""
    return _create_mock_db()


# ---------------------------------------------------------------------------
# Authenticated client fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def authenticated_client(test_org_factory):
    """Provide a mock authenticated HTTP client with org context."""
    org = test_org_factory()
    user_id = uuid.uuid4()

    client = MagicMock()
    client.org_id = org["id"]
    client.user_id = user_id
    client.org = org

    # Mock HTTP methods
    for method in ("get", "post", "put", "patch", "delete"):
        mock_method = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={}),
        ))
        setattr(client, method, mock_method)

    return client


# ---------------------------------------------------------------------------
# Common mock helpers
# ---------------------------------------------------------------------------

def make_mock_result(value=None, scalars_list=None):
    """Create a mock DB execute result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar.return_value = value
    if scalars_list is not None:
        result.scalars.return_value.all.return_value = scalars_list
    else:
        result.scalars.return_value.all.return_value = []
    return result
