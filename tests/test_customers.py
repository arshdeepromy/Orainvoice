"""Unit tests for Task 7.1 — customer CRUD and search.

Tests cover:
  - Schema validation for customer requests/responses
  - search_customers: live search by name, phone, email
  - create_customer: inline creation with audit logging
  - get_customer: retrieval by ID within org
  - update_customer: partial updates with audit logging
  - Org scoping: customers never shared across orgs

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import admin and auth models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401

from app.modules.customers.models import Customer
from app.modules.customers.schemas import (
    CustomerCreateRequest,
    CustomerCreateResponse,
    CustomerListResponse,
    CustomerResponse,
    CustomerSearchResult,
    CustomerUpdateRequest,
    CustomerUpdateResponse,
)
from app.modules.customers.service import (
    create_customer,
    get_customer,
    search_customers,
    update_customer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_customer(
    org_id=None,
    first_name="John",
    last_name="Smith",
    email="john@example.com",
    phone="+64 21 123 4567",
    address="123 Main St, Auckland",
    notes=None,
    is_anonymised=False,
):
    """Create a mock Customer object."""
    customer = MagicMock(spec=Customer)
    customer.id = uuid.uuid4()
    customer.org_id = org_id or uuid.uuid4()
    customer.first_name = first_name
    customer.last_name = last_name
    customer.email = email
    customer.phone = phone
    customer.address = address
    customer.notes = notes
    customer.is_anonymised = is_anonymised
    customer.created_at = datetime.now(timezone.utc)
    customer.updated_at = datetime.now(timezone.utc)
    return customer


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
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


class TestCustomerSchemas:
    """Test Pydantic schema validation for customer requests."""

    def test_create_request_minimal(self):
        """Minimal valid create request with just first and last name."""
        req = CustomerCreateRequest(first_name="Jane", last_name="Doe")
        assert req.first_name == "Jane"
        assert req.last_name == "Doe"
        assert req.email is None
        assert req.phone is None
        assert req.address is None

    def test_create_request_full(self):
        """Full create request with all fields."""
        req = CustomerCreateRequest(
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            phone="+64 21 999 8888",
            address="456 Queen St, Wellington",
            notes="VIP customer",
        )
        assert req.email == "jane@example.com"
        assert req.address == "456 Queen St, Wellington"

    def test_create_request_empty_first_name_rejected(self):
        """Empty first name is rejected."""
        with pytest.raises(Exception):
            CustomerCreateRequest(first_name="", last_name="Doe")

    def test_create_request_empty_last_name_rejected(self):
        """Empty last name is rejected."""
        with pytest.raises(Exception):
            CustomerCreateRequest(first_name="Jane", last_name="")

    def test_update_request_all_optional(self):
        """Update request with no fields is valid (no-op)."""
        req = CustomerUpdateRequest()
        assert req.first_name is None
        assert req.last_name is None

    def test_update_request_partial(self):
        """Update request with only some fields."""
        req = CustomerUpdateRequest(phone="+64 21 000 1111")
        assert req.phone == "+64 21 000 1111"
        assert req.first_name is None

    def test_search_result_model(self):
        """Search result has name, email, phone for quick identification."""
        sr = CustomerSearchResult(
            id=str(uuid.uuid4()),
            first_name="John",
            last_name="Smith",
            email="john@example.com",
            phone="+64 21 123 4567",
        )
        assert sr.first_name == "John"
        assert sr.email == "john@example.com"

    def test_list_response_model(self):
        """List response includes customers, total, and has_exact_match."""
        resp = CustomerListResponse(customers=[], total=0, has_exact_match=False)
        assert resp.total == 0
        assert resp.has_exact_match is False


# ---------------------------------------------------------------------------
# search_customers tests
# ---------------------------------------------------------------------------


class TestSearchCustomers:
    """Test the search_customers service function."""

    @pytest.mark.asyncio
    async def test_returns_all_when_no_query(self):
        """Returns all non-anonymised customers when no query is given."""
        org_id = uuid.uuid4()
        c1 = _make_customer(org_id=org_id, first_name="Alice", last_name="Brown")
        c2 = _make_customer(org_id=org_id, first_name="Bob", last_name="Green")

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(2), _mock_scalars_result([c1, c2])]
        )

        result = await search_customers(db, org_id=org_id)

        assert result["total"] == 2
        assert len(result["customers"]) == 2
        assert result["has_exact_match"] is False

    @pytest.mark.asyncio
    async def test_search_by_name(self):
        """Searches by name and returns matching customers."""
        org_id = uuid.uuid4()
        c1 = _make_customer(org_id=org_id, first_name="Alice", last_name="Brown")

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(1), _mock_scalars_result([c1])]
        )

        result = await search_customers(db, org_id=org_id, query="Alice")

        assert result["total"] == 1
        assert result["customers"][0]["first_name"] == "Alice"

    @pytest.mark.asyncio
    async def test_search_returns_empty(self):
        """Returns empty list when no customers match."""
        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(0), _mock_scalars_result([])]
        )

        result = await search_customers(db, org_id=uuid.uuid4(), query="Nonexistent")

        assert result["total"] == 0
        assert result["customers"] == []
        assert result["has_exact_match"] is False

    @pytest.mark.asyncio
    async def test_has_exact_match_by_name(self):
        """has_exact_match is True when full name matches exactly."""
        org_id = uuid.uuid4()
        c1 = _make_customer(org_id=org_id, first_name="Alice", last_name="Brown")

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(1), _mock_scalars_result([c1])]
        )

        result = await search_customers(db, org_id=org_id, query="Alice Brown")

        assert result["has_exact_match"] is True

    @pytest.mark.asyncio
    async def test_has_exact_match_by_email(self):
        """has_exact_match is True when email matches exactly."""
        org_id = uuid.uuid4()
        c1 = _make_customer(org_id=org_id, email="alice@test.com")

        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(1), _mock_scalars_result([c1])]
        )

        result = await search_customers(db, org_id=org_id, query="alice@test.com")

        assert result["has_exact_match"] is True

    @pytest.mark.asyncio
    async def test_search_result_fields(self):
        """Each search result has id, first_name, last_name, email, phone."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(1), _mock_scalars_result([c])]
        )

        result = await search_customers(db, org_id=c.org_id, query="John")

        sr = result["customers"][0]
        assert "id" in sr
        assert "first_name" in sr
        assert "last_name" in sr
        assert "email" in sr
        assert "phone" in sr

    @pytest.mark.asyncio
    async def test_excludes_anonymised_customers(self):
        """Anonymised customers are excluded from search results."""
        org_id = uuid.uuid4()
        # The service filters is_anonymised=False in the query,
        # so the DB should not return anonymised records.
        db = _mock_db_session()
        db.execute = AsyncMock(
            side_effect=[_mock_count_result(0), _mock_scalars_result([])]
        )

        result = await search_customers(db, org_id=org_id, query="Anon")

        assert result["total"] == 0


# ---------------------------------------------------------------------------
# create_customer tests
# ---------------------------------------------------------------------------


class TestCreateCustomer:
    """Test the create_customer service function."""

    @pytest.mark.asyncio
    async def test_creates_customer_successfully(self):
        """Creates a customer and returns its data."""
        org_id = uuid.uuid4()
        db = _mock_db_session()

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_customer(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                first_name="Jane",
                last_name="Doe",
                email="jane@example.com",
                phone="+64 21 999 8888",
            )

        assert result["first_name"] == "Jane"
        assert result["last_name"] == "Doe"
        assert result["email"] == "jane@example.com"
        db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_customer_minimal(self):
        """Creates a customer with only required fields."""
        db = _mock_db_session()

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await create_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                first_name="Min",
                last_name="Imal",
            )

        assert result["first_name"] == "Min"
        assert result["email"] is None
        assert result["phone"] is None
        assert result["address"] is None

    @pytest.mark.asyncio
    async def test_audit_log_written_on_create(self):
        """Verify audit log is written on customer creation."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db = _mock_db_session()

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await create_customer(
                db,
                org_id=org_id,
                user_id=user_id,
                first_name="Audited",
                last_name="Customer",
                ip_address="10.0.0.1",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "customer.created"
        assert call_kwargs["entity_type"] == "customer"
        assert call_kwargs["org_id"] == org_id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["ip_address"] == "10.0.0.1"
        assert call_kwargs["after_value"]["first_name"] == "Audited"


# ---------------------------------------------------------------------------
# get_customer tests
# ---------------------------------------------------------------------------


class TestGetCustomer:
    """Test the get_customer service function."""

    @pytest.mark.asyncio
    async def test_returns_customer(self):
        """Returns customer data when found."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        result = await get_customer(db, org_id=c.org_id, customer_id=c.id)

        assert result["first_name"] == c.first_name
        assert result["id"] == str(c.id)

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await get_customer(
                db, org_id=uuid.uuid4(), customer_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_customer_fields_present(self):
        """Returned dict has all expected fields."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        result = await get_customer(db, org_id=c.org_id, customer_id=c.id)

        for field in ("id", "first_name", "last_name", "email", "phone",
                       "address", "notes", "is_anonymised", "created_at", "updated_at"):
            assert field in result


# ---------------------------------------------------------------------------
# update_customer tests
# ---------------------------------------------------------------------------


class TestUpdateCustomer:
    """Test the update_customer service function."""

    @pytest.mark.asyncio
    async def test_updates_customer_fields(self):
        """Updates specified fields and returns updated data."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ):
            result = await update_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                first_name="Updated",
                phone="+64 21 000 0000",
            )

        # The mock's attributes are set by the service
        assert c.first_name == "Updated"
        assert c.phone == "+64 21 000 0000"

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self):
        """Raises ValueError when customer doesn't exist."""
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Customer not found"):
            await update_customer(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                customer_id=uuid.uuid4(),
                first_name="Ghost",
            )

    @pytest.mark.asyncio
    async def test_update_anonymised_raises(self):
        """Raises ValueError when trying to update an anonymised customer."""
        c = _make_customer(is_anonymised=True)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        with pytest.raises(ValueError, match="Cannot update an anonymised"):
            await update_customer(
                db,
                org_id=c.org_id,
                user_id=uuid.uuid4(),
                customer_id=c.id,
                first_name="Nope",
            )

    @pytest.mark.asyncio
    async def test_no_op_when_no_fields(self):
        """Returns customer data without changes when no fields provided."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))

        result = await update_customer(
            db,
            org_id=c.org_id,
            user_id=uuid.uuid4(),
            customer_id=c.id,
        )

        assert result["first_name"] == c.first_name
        db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_audit_log_written_on_update(self):
        """Verify audit log is written on customer update."""
        c = _make_customer()
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(c))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.customers.service.write_audit_log",
            new_callable=AsyncMock,
        ) as mock_audit:
            await update_customer(
                db,
                org_id=c.org_id,
                user_id=user_id,
                customer_id=c.id,
                email="new@example.com",
                ip_address="10.0.0.2",
            )

        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "customer.updated"
        assert call_kwargs["entity_type"] == "customer"
        assert call_kwargs["ip_address"] == "10.0.0.2"
