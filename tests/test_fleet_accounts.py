"""Unit tests for Task 7.5 — fleet account management.

Tests cover:
  - Schema validation for fleet account requests/responses
  - create_fleet_account: creation with audit logging
  - get_fleet_account: retrieval by ID within org
  - update_fleet_account: partial updates including pricing overrides
  - delete_fleet_account: deletion with customer unlinking
  - list_fleet_accounts: listing with customer counts
  - Pricing overrides: fleet-specific pricing on catalogue items

Requirements: 66.1, 66.2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import admin and auth models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.customers.models import Customer, FleetAccount
from app.modules.customers.schemas import (
    FleetAccountCreateRequest,
    FleetAccountCreateResponse,
    FleetAccountDeleteResponse,
    FleetAccountListResponse,
    FleetAccountResponse,
    FleetAccountUpdateRequest,
    FleetAccountUpdateResponse,
)
from app.modules.customers.service import (
    create_fleet_account,
    delete_fleet_account,
    get_fleet_account,
    list_fleet_accounts,
    update_fleet_account,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fleet_account(
    org_id=None,
    name="Acme Transport Ltd",
    primary_contact_name="Jane Doe",
    primary_contact_email="jane@acme.co.nz",
    primary_contact_phone="+64 21 555 0001",
    billing_address="100 Fleet St, Auckland",
    notes="Major fleet client",
    pricing_overrides=None,
):
    """Create a mock FleetAccount object."""
    fa = MagicMock(spec=FleetAccount)
    fa.id = uuid.uuid4()
    fa.org_id = org_id or uuid.uuid4()
    fa.name = name
    fa.primary_contact_name = primary_contact_name
    fa.primary_contact_email = primary_contact_email
    fa.primary_contact_phone = primary_contact_phone
    fa.billing_address = billing_address
    fa.notes = notes
    fa.pricing_overrides = pricing_overrides or {}
    fa.created_at = datetime.now(timezone.utc)
    fa.updated_at = datetime.now(timezone.utc)
    return fa


def _make_customer(org_id=None, fleet_account_id=None):
    """Create a mock Customer object."""
    customer = MagicMock(spec=Customer)
    customer.id = uuid.uuid4()
    customer.org_id = org_id or uuid.uuid4()
    customer.fleet_account_id = fleet_account_id
    customer.is_anonymised = False
    return customer


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    return db


def _mock_scalar_result(value):
    """Create a mock result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    """Create a mock result that returns values from scalars().all()."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_count_result(count):
    """Create a mock result that returns a count from scalar()."""
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestFleetAccountSchemas:
    """Validate Pydantic schema constraints for fleet accounts."""

    def test_create_request_minimal(self):
        req = FleetAccountCreateRequest(name="Test Fleet")
        assert req.name == "Test Fleet"
        assert req.primary_contact_name is None
        assert req.pricing_overrides is None

    def test_create_request_full(self):
        overrides = {str(uuid.uuid4()): {"price": "85.00"}}
        req = FleetAccountCreateRequest(
            name="Acme Transport",
            primary_contact_name="Jane Doe",
            primary_contact_email="jane@acme.co.nz",
            primary_contact_phone="+64 21 555 0001",
            billing_address="100 Fleet St",
            notes="VIP fleet",
            pricing_overrides=overrides,
        )
        assert req.name == "Acme Transport"
        assert req.pricing_overrides == overrides

    def test_create_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            FleetAccountCreateRequest(name="")

    def test_update_request_all_optional(self):
        req = FleetAccountUpdateRequest()
        assert req.name is None
        assert req.pricing_overrides is None

    def test_update_request_partial(self):
        req = FleetAccountUpdateRequest(name="New Name")
        assert req.name == "New Name"
        assert req.billing_address is None

    def test_response_model(self):
        resp = FleetAccountResponse(
            id=str(uuid.uuid4()),
            name="Test Fleet",
            customer_count=3,
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.name == "Test Fleet"
        assert resp.customer_count == 3
        assert resp.pricing_overrides == {}

    def test_list_response_model(self):
        resp = FleetAccountListResponse(fleet_accounts=[], total=0)
        assert resp.total == 0
        assert resp.fleet_accounts == []

    def test_response_with_pricing_overrides(self):
        """Requirements: 66.2 — pricing overrides are included in response."""
        service_id = str(uuid.uuid4())
        overrides = {service_id: {"price": "75.00"}}
        resp = FleetAccountResponse(
            id=str(uuid.uuid4()),
            name="Fleet Co",
            pricing_overrides=overrides,
            customer_count=0,
            created_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        assert resp.pricing_overrides == overrides


# ---------------------------------------------------------------------------
# Service function tests
# ---------------------------------------------------------------------------


class TestCreateFleetAccount:
    """Test fleet account creation service."""

    @pytest.mark.asyncio
    async def test_creates_fleet_account_successfully(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await create_fleet_account(
                db,
                org_id=org_id,
                user_id=user_id,
                name="Acme Transport Ltd",
                primary_contact_name="Jane Doe",
                primary_contact_email="jane@acme.co.nz",
                billing_address="100 Fleet St, Auckland",
            )

        assert result["name"] == "Acme Transport Ltd"
        assert result["primary_contact_name"] == "Jane Doe"
        assert result["primary_contact_email"] == "jane@acme.co.nz"
        assert result["billing_address"] == "100 Fleet St, Auckland"
        assert result["customer_count"] == 0
        assert result["pricing_overrides"] == {}
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_with_pricing_overrides(self):
        """Requirements: 66.2 — fleet-specific pricing overrides."""
        db = _mock_db_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        service_id = str(uuid.uuid4())
        overrides = {service_id: {"price": "85.00"}}

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await create_fleet_account(
                db,
                org_id=org_id,
                user_id=user_id,
                name="Fleet Co",
                pricing_overrides=overrides,
            )

        assert result["pricing_overrides"] == overrides

    @pytest.mark.asyncio
    async def test_audit_log_written_on_create(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await create_fleet_account(
                db,
                org_id=org_id,
                user_id=user_id,
                name="Audit Test Fleet",
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "fleet_account.created"
        assert call_kwargs["entity_type"] == "fleet_account"
        assert call_kwargs["after_value"]["name"] == "Audit Test Fleet"


class TestGetFleetAccount:
    """Test fleet account retrieval service."""

    @pytest.mark.asyncio
    async def test_returns_fleet_account(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa = _make_fleet_account(org_id=org_id)

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(fa),
            _mock_count_result(2),
        ])

        result = await get_fleet_account(
            db, org_id=org_id, fleet_account_id=fa.id
        )

        assert result["id"] == str(fa.id)
        assert result["name"] == fa.name
        assert result["customer_count"] == 2

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Fleet account not found"):
            await get_fleet_account(
                db, org_id=uuid.uuid4(), fleet_account_id=uuid.uuid4()
            )


class TestUpdateFleetAccount:
    """Test fleet account update service."""

    @pytest.mark.asyncio
    async def test_updates_fleet_account_fields(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa = _make_fleet_account(org_id=org_id)

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(fa),
            _mock_count_result(1),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await update_fleet_account(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                fleet_account_id=fa.id,
                name="Updated Fleet Name",
            )

        assert fa.name == "Updated Fleet Name"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_pricing_overrides(self):
        """Requirements: 66.2 — update fleet-specific pricing."""
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa = _make_fleet_account(org_id=org_id, pricing_overrides={})

        service_id = str(uuid.uuid4())
        new_overrides = {service_id: {"price": "50.00"}}

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(fa),
            _mock_count_result(0),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await update_fleet_account(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                fleet_account_id=fa.id,
                pricing_overrides=new_overrides,
            )

        assert fa.pricing_overrides == new_overrides

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Fleet account not found"):
            await update_fleet_account(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                fleet_account_id=uuid.uuid4(),
                name="Nope",
            )

    @pytest.mark.asyncio
    async def test_no_op_when_no_fields(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa = _make_fleet_account(org_id=org_id)

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(fa),
            _mock_count_result(0),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            result = await update_fleet_account(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                fleet_account_id=fa.id,
            )

        # No flush or audit when nothing changed
        db.flush.assert_not_awaited()
        mock_audit.assert_not_awaited()


class TestDeleteFleetAccount:
    """Test fleet account deletion service."""

    @pytest.mark.asyncio
    async def test_deletes_and_unlinks_customers(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa = _make_fleet_account(org_id=org_id)
        cust1 = _make_customer(org_id=org_id, fleet_account_id=fa.id)
        cust2 = _make_customer(org_id=org_id, fleet_account_id=fa.id)

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(fa),
            _mock_scalars_result([cust1, cust2]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock):
            result = await delete_fleet_account(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                fleet_account_id=fa.id,
            )

        assert result["fleet_account_id"] == str(fa.id)
        assert cust1.fleet_account_id is None
        assert cust2.fleet_account_id is None
        db.delete.assert_called_once_with(fa)

    @pytest.mark.asyncio
    async def test_delete_not_found_raises(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Fleet account not found"):
            await delete_fleet_account(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                fleet_account_id=uuid.uuid4(),
            )

    @pytest.mark.asyncio
    async def test_audit_log_written_on_delete(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa = _make_fleet_account(org_id=org_id)

        db.execute = AsyncMock(side_effect=[
            _mock_scalar_result(fa),
            _mock_scalars_result([]),
        ])

        with patch("app.modules.customers.service.write_audit_log", new_callable=AsyncMock) as mock_audit:
            await delete_fleet_account(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                fleet_account_id=fa.id,
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args[1]
        assert call_kwargs["action"] == "fleet_account.deleted"


class TestListFleetAccounts:
    """Test fleet account listing service."""

    @pytest.mark.asyncio
    async def test_returns_fleet_accounts_with_counts(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        fa1 = _make_fleet_account(org_id=org_id, name="Alpha Fleet")
        fa2 = _make_fleet_account(org_id=org_id, name="Beta Fleet")

        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result([fa1, fa2]),
            _mock_count_result(3),  # customer count for fa1
            _mock_count_result(1),  # customer count for fa2
        ])

        result = await list_fleet_accounts(db, org_id=org_id)

        assert result["total"] == 2
        assert len(result["fleet_accounts"]) == 2
        assert result["fleet_accounts"][0]["name"] == "Alpha Fleet"
        assert result["fleet_accounts"][0]["customer_count"] == 3
        assert result["fleet_accounts"][1]["customer_count"] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_fleet_accounts(self):
        db = _mock_db_session()
        org_id = uuid.uuid4()

        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await list_fleet_accounts(db, org_id=org_id)

        assert result["total"] == 0
        assert result["fleet_accounts"] == []
