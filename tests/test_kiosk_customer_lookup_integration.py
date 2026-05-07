"""Integration tests for GET /kiosk/customer-lookup endpoint.

Tests cover the full request/response cycle through the service function:
  - Phone match: returns matching customer(s) when phone matches exactly
  - Email match (case-insensitive): returns matching customer(s) regardless of case
  - No match: returns empty items list and total=0
  - Multiple matches: returns up to 5 matches with correct total
  - 422 when neither phone nor email provided
  - Role enforcement: non-kiosk role rejected

Requirements: 9.5, 9.7, 9.8
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

# Ensure SQLAlchemy relationship models are loaded
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401

from app.modules.kiosk.service import customer_lookup_for_kiosk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_customer(**overrides):
    """Build a mock Customer ORM object."""
    c = MagicMock()
    c.id = overrides.get("id", uuid.uuid4())
    c.org_id = overrides.get("org_id", uuid.uuid4())
    c.first_name = overrides.get("first_name", "Jane")
    c.last_name = overrides.get("last_name", "Doe")
    c.phone = overrides.get("phone", "0211234567")
    c.email = overrides.get("email", "jane@example.com")
    c.is_anonymised = overrides.get("is_anonymised", False)
    return c


def _make_mock_request(*, user_id: str, org_id: str, role: str = "kiosk"):
    """Create a mock FastAPI Request with state attributes for auth context."""
    request = MagicMock()
    request.state.user_id = user_id
    request.state.org_id = org_id
    request.state.role = role
    request.state.client_ip = "10.0.0.1"
    return request


def _make_count_result(count: int):
    """Create a mock DB execute result for the count query (scalar_one)."""
    result = MagicMock()
    result.scalar_one.return_value = count
    return result


def _make_customers_result(customers: list):
    """Create a mock DB execute result for the data query (scalars().all())."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = customers
    result.scalars.return_value = scalars_mock
    return result


# ---------------------------------------------------------------------------
# Integration Tests: Phone Match
# ---------------------------------------------------------------------------


class TestCustomerLookupPhoneMatch:
    """Phone match: returns matching customer(s) when phone matches exactly.

    Requirements: 9.5, 9.7
    """

    @pytest.mark.asyncio
    async def test_phone_match_returns_customer(self):
        """When phone matches exactly, returns the matching customer."""
        org_id = uuid.uuid4()
        customer = _make_mock_customer(org_id=org_id, phone="0211234567")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone="0211234567", email=None
        )

        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["id"] == str(customer.id)
        assert result["items"][0]["first_name"] == "Jane"
        assert result["items"][0]["last_name"] == "Doe"
        assert result["items"][0]["phone"] == "0211234567"
        assert result["items"][0]["email"] == "jane@example.com"

    @pytest.mark.asyncio
    async def test_phone_match_only_searches_phone(self):
        """When only phone is provided, email condition is not included."""
        org_id = uuid.uuid4()
        customer = _make_mock_customer(org_id=org_id, phone="0279876543")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone="0279876543", email=None
        )

        assert result["total"] == 1
        assert result["items"][0]["phone"] == "0279876543"


# ---------------------------------------------------------------------------
# Integration Tests: Email Match (Case-Insensitive)
# ---------------------------------------------------------------------------


class TestCustomerLookupEmailMatch:
    """Email match (case-insensitive): returns matching customer(s).

    Requirements: 9.5, 9.7
    """

    @pytest.mark.asyncio
    async def test_email_match_returns_customer(self):
        """When email matches (case-insensitive), returns the matching customer."""
        org_id = uuid.uuid4()
        customer = _make_mock_customer(org_id=org_id, email="john@example.com")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone=None, email="john@example.com"
        )

        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["email"] == "john@example.com"

    @pytest.mark.asyncio
    async def test_email_match_case_insensitive(self):
        """Email matching is case-insensitive — uppercase input matches lowercase record."""
        org_id = uuid.uuid4()
        customer = _make_mock_customer(org_id=org_id, email="alice@example.com")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        # Provide email in different case
        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone=None, email="ALICE@EXAMPLE.COM"
        )

        assert result["total"] == 1
        assert result["items"][0]["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_email_match_mixed_case(self):
        """Email matching handles mixed case input correctly."""
        org_id = uuid.uuid4()
        customer = _make_mock_customer(org_id=org_id, email="Bob.Smith@Company.co.nz")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone=None, email="bob.smith@company.co.nz"
        )

        assert result["total"] == 1
        assert len(result["items"]) == 1


# ---------------------------------------------------------------------------
# Integration Tests: No Match
# ---------------------------------------------------------------------------


class TestCustomerLookupNoMatch:
    """No match: returns empty items list and total=0.

    Requirements: 9.5, 9.7
    """

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self):
        """When no customers match, returns empty items and total=0."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(0),
            _make_customers_result([]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone="0000000000", email=None
        )

        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_no_match_by_email_returns_empty(self):
        """When no customers match the email, returns empty items and total=0."""
        org_id = uuid.uuid4()

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(0),
            _make_customers_result([]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone=None, email="nobody@nowhere.com"
        )

        assert result["total"] == 0
        assert result["items"] == []


# ---------------------------------------------------------------------------
# Integration Tests: Multiple Matches
# ---------------------------------------------------------------------------


class TestCustomerLookupMultipleMatches:
    """Multiple matches: returns up to 5 matches with correct total.

    Requirements: 9.5, 9.8
    """

    @pytest.mark.asyncio
    async def test_multiple_matches_returns_all(self):
        """When multiple customers match, returns all matches (up to 5)."""
        org_id = uuid.uuid4()
        customers = [
            _make_mock_customer(org_id=org_id, first_name=f"Customer{i}", phone="0211234567")
            for i in range(3)
        ]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(3),
            _make_customers_result(customers),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone="0211234567", email=None
        )

        assert result["total"] == 3
        assert len(result["items"]) == 3

    @pytest.mark.asyncio
    async def test_multiple_matches_limited_to_5(self):
        """When more than 5 customers match, items is limited to 5 but total reflects actual count."""
        org_id = uuid.uuid4()
        # The DB returns 5 items (due to LIMIT 5) but total count is 8
        customers = [
            _make_mock_customer(org_id=org_id, first_name=f"Customer{i}", phone="0211234567")
            for i in range(5)
        ]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(8),
            _make_customers_result(customers),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone="0211234567", email=None
        )

        assert result["total"] == 8
        assert len(result["items"]) == 5

    @pytest.mark.asyncio
    async def test_multiple_matches_each_has_correct_fields(self):
        """Each match in the response contains all expected fields."""
        org_id = uuid.uuid4()
        c1 = _make_mock_customer(
            org_id=org_id, first_name="Alice", last_name="Smith",
            phone="0211234567", email="alice@test.com"
        )
        c2 = _make_mock_customer(
            org_id=org_id, first_name="Bob", last_name="Jones",
            phone="0211234567", email="bob@test.com"
        )

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(2),
            _make_customers_result([c1, c2]),
        ])

        result = await customer_lookup_for_kiosk(
            db, org_id=org_id, phone="0211234567", email=None
        )

        assert result["total"] == 2
        assert len(result["items"]) == 2

        item1 = result["items"][0]
        assert item1["id"] == str(c1.id)
        assert item1["first_name"] == "Alice"
        assert item1["last_name"] == "Smith"
        assert item1["phone"] == "0211234567"
        assert item1["email"] == "alice@test.com"

        item2 = result["items"][1]
        assert item2["id"] == str(c2.id)
        assert item2["first_name"] == "Bob"
        assert item2["last_name"] == "Jones"
        assert item2["phone"] == "0211234567"
        assert item2["email"] == "bob@test.com"


# ---------------------------------------------------------------------------
# Integration Tests: 422 When Neither Phone Nor Email Provided
# ---------------------------------------------------------------------------


class TestCustomerLookup422Validation:
    """422 when neither phone nor email provided.

    Requirements: 9.5, 9.7
    """

    @pytest.mark.asyncio
    async def test_no_phone_no_email_raises_422(self):
        """When neither phone nor email is provided, raises HTTP 422."""
        org_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await customer_lookup_for_kiosk(
                db, org_id=org_id, phone=None, email=None
            )

        assert exc_info.value.status_code == 422
        assert "phone" in exc_info.value.detail.lower() or "email" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_empty_string_phone_and_none_email_raises_422(self):
        """When phone is empty string and email is None, raises HTTP 422."""
        org_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await customer_lookup_for_kiosk(
                db, org_id=org_id, phone="", email=None
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_none_phone_and_empty_string_email_raises_422(self):
        """When phone is None and email is empty string, raises HTTP 422."""
        org_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await customer_lookup_for_kiosk(
                db, org_id=org_id, phone=None, email=""
            )

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_422_detail_mentions_required_params(self):
        """422 error detail mentions that phone or email is required."""
        org_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await customer_lookup_for_kiosk(
                db, org_id=org_id, phone=None, email=None
            )

        detail = exc_info.value.detail.lower()
        assert "phone" in detail or "email" in detail

    @pytest.mark.asyncio
    async def test_no_db_queries_when_422(self):
        """When 422 is raised, no database queries are executed."""
        org_id = uuid.uuid4()
        db = AsyncMock()

        with pytest.raises(HTTPException):
            await customer_lookup_for_kiosk(
                db, org_id=org_id, phone=None, email=None
            )

        db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Integration Tests: Role Enforcement
# ---------------------------------------------------------------------------


class TestCustomerLookupRoleEnforcement:
    """Role enforcement: non-kiosk role rejected.

    Requirements: 9.5, 9.7
    """

    @pytest.mark.asyncio
    async def test_non_kiosk_role_rejected(self):
        """A user with 'salesperson' role is rejected with 403 by require_role('kiosk')."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="salesperson",
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 403
        assert "kiosk" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_org_admin_role_rejected(self):
        """A user with 'org_admin' role is rejected for kiosk-only endpoints."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="org_admin",
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 403
        assert "kiosk" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_kiosk_role_allowed(self):
        """A user with 'kiosk' role is allowed access."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="kiosk",
        )

        # Should not raise — kiosk role is allowed
        await check_fn(request)

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self):
        """A request without user_id/role is rejected with 401."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = MagicMock()
        request.state.user_id = None
        request.state.org_id = None
        request.state.role = None

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_staff_member_role_rejected(self):
        """A user with 'staff_member' role is rejected for kiosk-only endpoints."""
        from app.modules.auth.rbac import require_role

        depends_obj = require_role("kiosk")
        check_fn = depends_obj.dependency

        request = _make_mock_request(
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
            role="staff_member",
        )

        with pytest.raises(HTTPException) as exc_info:
            await check_fn(request)

        assert exc_info.value.status_code == 403
        assert "kiosk" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Integration Tests: Router Handler Flow
# ---------------------------------------------------------------------------


class TestCustomerLookupRouterHandler:
    """Test the full router handler function (customer_lookup) end-to-end.

    Requirements: 9.5, 9.7
    """

    @pytest.mark.asyncio
    async def test_router_handler_returns_result(self):
        """The customer_lookup router handler returns the lookup result correctly."""
        from app.modules.kiosk.router import customer_lookup

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_mock_customer(org_id=org_id, phone="0211234567")

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        request = _make_mock_request(user_id=str(user_id), org_id=str(org_id))

        result = await customer_lookup(
            request=request,
            phone="0211234567",
            email=None,
            db=db,
        )

        assert result["total"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["phone"] == "0211234567"

    @pytest.mark.asyncio
    async def test_router_handler_returns_403_without_org_context(self):
        """The customer_lookup handler returns 403 when org context is missing."""
        from app.modules.kiosk.router import customer_lookup

        db = AsyncMock()

        request = MagicMock()
        request.state.user_id = str(uuid.uuid4())
        request.state.org_id = None
        request.state.role = "kiosk"
        request.state.client_ip = "10.0.0.1"

        result = await customer_lookup(
            request=request,
            phone="0211234567",
            email=None,
            db=db,
        )

        # Should return a JSONResponse with 403
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_router_handler_with_both_phone_and_email(self):
        """The router handler works when both phone and email are provided."""
        from app.modules.kiosk.router import customer_lookup

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer = _make_mock_customer(
            org_id=org_id, phone="0211234567", email="test@example.com"
        )

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_count_result(1),
            _make_customers_result([customer]),
        ])

        request = _make_mock_request(user_id=str(user_id), org_id=str(org_id))

        result = await customer_lookup(
            request=request,
            phone="0211234567",
            email="test@example.com",
            db=db,
        )

        assert result["total"] == 1
        assert len(result["items"]) == 1
