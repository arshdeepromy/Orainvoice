"""Unit tests for Task 4.7 — Kiosk check-in backend.

Tests cover:
  - Check-in with valid data creates customer and returns expected response
  - Check-in with existing phone returns existing customer (is_new_customer: false)
  - Check-in with rego triggers Carjam lookup and links vehicle
  - Check-in with rego when Carjam fails creates manual vehicle
  - Check-in with rego when vehicle already exists links without duplication
  - Check-in without rego returns vehicle_linked: false
  - Check-in with invalid phone returns 422
  - Check-in with empty first_name returns 422
  - Kiosk user cannot access /api/v1/invoices (403)
  - Kiosk user can GET /api/v1/org/settings (200)
  - Kiosk user cannot PUT /api/v1/org/settings (403)
  - Rate limiter blocks 31st request in 60 seconds (429)
  - Kiosk authentication produces 30-day session expiry

Requirements: 1.3, 1.4, 1.5, 1.6, 3.2, 3.3, 4.1, 4.2, 4.3, 4.5, 4.6, 4.7, 6.1, 6.5
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from redis.asyncio import Redis

# Ensure SQLAlchemy relationship models are loaded
import app.modules.admin.models  # noqa: F401

from app.modules.auth.models import Session, User
from app.modules.auth.password import hash_password
from app.modules.auth.rbac import check_role_path_access
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.service import authenticate_user
from app.modules.customers.models import Customer
from app.modules.kiosk.router import _check_kiosk_rate_limit, _KIOSK_RATE_LIMIT
from app.modules.kiosk.schemas import KioskCheckInRequest, KioskCheckInResponse
from app.modules.kiosk.service import kiosk_check_in
from app.integrations.carjam import CarjamError, CarjamNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_existing_customer(
    org_id: uuid.UUID,
    phone: str,
    first_name: str = "Existing",
    last_name: str = "Customer",
) -> MagicMock:
    """Build a mock Customer object for query results."""
    c = MagicMock(spec=Customer)
    c.id = uuid.uuid4()
    c.org_id = org_id
    c.first_name = first_name
    c.last_name = last_name
    c.phone = phone
    c.email = None
    c.customer_type = "individual"
    c.is_anonymised = False
    return c


def _mock_db_returning_customer(customer: Customer | None) -> AsyncMock:
    """Create a mock AsyncSession whose execute() returns the given customer."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer
    db.execute = AsyncMock(return_value=mock_result)
    db.commit = AsyncMock()
    return db


def _mock_db_for_vehicle_tests(
    customer: Customer | None,
    *,
    existing_link: bool = False,
) -> AsyncMock:
    """Create a mock AsyncSession for customer lookup + vehicle-link check.

    First execute() → customer lookup.
    Second execute() → existing link check.
    """
    db = AsyncMock()

    customer_result = MagicMock()
    customer_result.scalar_one_or_none.return_value = customer

    link_result = MagicMock()
    link_result.scalar_one_or_none.return_value = (
        MagicMock() if existing_link else None
    )

    db.execute = AsyncMock(side_effect=[customer_result, link_result])
    db.commit = AsyncMock()
    return db


def _mock_scalar_one_or_none(value):
    """Create a mock result whose scalar_one_or_none() returns value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_all(values):
    """Create a mock result whose scalars().all() returns values."""
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _make_kiosk_user(
    org_id: uuid.UUID,
    email: str = "kiosk@workshop.co.nz",
    password: str = "SecurePassword123!",
) -> MagicMock:
    """Build a mock User with role='kiosk'."""
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.org_id = org_id
    u.email = email
    u.password_hash = hash_password(password)
    u.role = "kiosk"
    u.is_active = True
    u.is_email_verified = True
    u.failed_login_count = 0
    u.locked_until = None
    u.last_login_at = None
    return u


def _make_mock_request(user_id: str) -> MagicMock:
    """Create a mock FastAPI Request with state.user_id set."""
    request = MagicMock()
    request.state.user_id = user_id
    return request


def _make_mock_redis_for_rate_limit(current_count: int) -> AsyncMock:
    """Create a mock Redis simulating a sorted-set sliding window."""
    redis = AsyncMock(spec=Redis)

    pipe1 = AsyncMock()
    pipe1.zremrangebyscore = MagicMock(return_value=pipe1)
    pipe1.zcard = MagicMock(return_value=pipe1)
    pipe1.execute = AsyncMock(return_value=[0, current_count])

    pipe2 = AsyncMock()
    pipe2.zadd = MagicMock(return_value=pipe2)
    pipe2.expire = MagicMock(return_value=pipe2)
    pipe2.execute = AsyncMock(return_value=[1, True])

    redis.pipeline = MagicMock(side_effect=[pipe1, pipe2])

    now = time.time()
    redis.zrange = AsyncMock(return_value=[(b"oldest", now - 50)])

    return redis


# ---------------------------------------------------------------------------
# Check-in service tests
# ---------------------------------------------------------------------------


class TestCheckInValidData:
    """Check-in with valid data creates customer and returns expected response.

    Requirements: 4.3, 4.4
    """

    @pytest.mark.asyncio
    async def test_valid_checkin_creates_new_customer(self):
        """Valid check-in with new phone creates a customer and returns is_new_customer=True."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = str(uuid.uuid4())

        db = _mock_db_returning_customer(None)
        redis = AsyncMock(spec=Redis)

        created = {
            "id": customer_id,
            "first_name": "Jane",
            "last_name": "Doe",
            "phone": "+6421555777",
            "email": "jane@example.com",
            "customer_type": "individual",
        }

        data = KioskCheckInRequest(
            first_name="Jane",
            last_name="Doe",
            phone="+6421555777",
            email="jane@example.com",
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=created,
        ) as mock_create:
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.is_new_customer is True
            assert result.customer_first_name == "Jane"
            assert result.vehicle_linked is False
            mock_create.assert_called_once()
            assert mock_create.call_args.kwargs["customer_type"] == "individual"


class TestCheckInExistingPhone:
    """Check-in with existing phone returns existing customer.

    Requirements: 4.1, 4.2
    """

    @pytest.mark.asyncio
    async def test_existing_phone_returns_not_new(self):
        """Check-in with a phone that already exists returns is_new_customer=False."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        existing = _make_existing_customer(org_id, "+6421555777", "Bob")
        db = _mock_db_returning_customer(existing)
        redis = AsyncMock(spec=Redis)

        data = KioskCheckInRequest(
            first_name="Robert",
            last_name="Jones",
            phone="+6421555777",
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
        ) as mock_create:
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.is_new_customer is False
            assert result.customer_first_name == "Bob"
            mock_create.assert_not_called()


class TestCheckInWithRego:
    """Check-in with rego triggers Carjam lookup and links vehicle.

    Requirements: 4.5, 4.6, 4.7
    """

    @pytest.mark.asyncio
    async def test_rego_triggers_carjam_and_links(self):
        """Providing a rego calls lookup_vehicle and links the result."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = str(uuid.uuid4())
        vehicle_id = str(uuid.uuid4())

        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": customer_id,
            "first_name": "Alice",
            "last_name": "Smith",
            "phone": "+6421999888",
            "email": None,
            "customer_type": "individual",
        }

        carjam_vehicle = {
            "id": vehicle_id,
            "rego": "ABC123",
            "make": "Toyota",
            "model": "Corolla",
            "source": "carjam",
        }

        data = KioskCheckInRequest(
            first_name="Alice",
            last_name="Smith",
            phone="+6421999888",
            vehicle_rego="abc123",
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=carjam_vehicle,
            ) as mock_lookup,
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.vehicle_linked is True
            mock_lookup.assert_called_once()
            mock_manual.assert_not_called()
            mock_link.assert_called_once()
            assert str(mock_link.call_args.kwargs["vehicle_id"]) == vehicle_id
            assert str(mock_link.call_args.kwargs["customer_id"]) == customer_id

    @pytest.mark.asyncio
    async def test_carjam_failure_creates_manual_vehicle(self):
        """When Carjam fails, a manual vehicle is created and linked."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = str(uuid.uuid4())
        vehicle_id = str(uuid.uuid4())

        db = _mock_db_for_vehicle_tests(None, existing_link=False)
        redis = AsyncMock(spec=Redis)

        created_customer = {
            "id": customer_id,
            "first_name": "Charlie",
            "last_name": "Brown",
            "phone": "+6421777666",
            "email": None,
            "customer_type": "individual",
        }

        manual_vehicle = {
            "id": vehicle_id,
            "rego": "XYZ789",
            "source": "manual",
        }

        data = KioskCheckInRequest(
            first_name="Charlie",
            last_name="Brown",
            phone="+6421777666",
            vehicle_rego="xyz789",
        )

        with (
            patch(
                "app.modules.customers.service.create_customer",
                new_callable=AsyncMock,
                return_value=created_customer,
            ),
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                side_effect=CarjamError("API unavailable"),
            ),
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
                return_value=manual_vehicle,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.vehicle_linked is True
            mock_manual.assert_called_once()
            assert mock_manual.call_args.kwargs["rego"] == "XYZ789"
            mock_link.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_vehicle_links_without_duplication(self):
        """When vehicle already exists and is already linked, no duplicate link is created."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        existing_vehicle_id = str(uuid.uuid4())

        existing_customer = _make_existing_customer(org_id, "+6421444333")
        db = _mock_db_for_vehicle_tests(existing_customer, existing_link=True)
        redis = AsyncMock(spec=Redis)

        existing_vehicle = {
            "id": existing_vehicle_id,
            "rego": "DEF456",
            "make": "Honda",
            "model": "Civic",
            "source": "cache",
        }

        data = KioskCheckInRequest(
            first_name="Dave",
            last_name="Wilson",
            phone="+6421444333",
            vehicle_rego="def456",
        )

        with (
            patch(
                "app.modules.vehicles.service.lookup_vehicle",
                new_callable=AsyncMock,
                return_value=existing_vehicle,
            ),
            patch(
                "app.modules.vehicles.service.create_manual_vehicle",
                new_callable=AsyncMock,
            ) as mock_manual,
            patch(
                "app.modules.vehicles.service.link_vehicle_to_customer",
                new_callable=AsyncMock,
            ) as mock_link,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.vehicle_linked is True
            mock_manual.assert_not_called()
            # link_vehicle_to_customer should NOT be called — existing link found
            mock_link.assert_not_called()


class TestCheckInWithoutRego:
    """Check-in without rego returns vehicle_linked: false.

    Requirements: 4.5
    """

    @pytest.mark.asyncio
    async def test_no_rego_returns_vehicle_linked_false(self):
        """When no rego is provided, vehicle_linked is False."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        db = _mock_db_returning_customer(None)
        redis = AsyncMock(spec=Redis)

        created = {
            "id": str(uuid.uuid4()),
            "first_name": "Eve",
            "last_name": "Taylor",
            "phone": "+6421222111",
            "email": None,
            "customer_type": "individual",
        }

        data = KioskCheckInRequest(
            first_name="Eve",
            last_name="Taylor",
            phone="+6421222111",
        )

        with patch(
            "app.modules.customers.service.create_customer",
            new_callable=AsyncMock,
            return_value=created,
        ):
            result = await kiosk_check_in(
                db, redis, org_id=org_id, user_id=user_id, data=data
            )

            assert result.vehicle_linked is False


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestCheckInValidation:
    """Check-in form validation rejects invalid inputs.

    Requirements: 3.2, 3.3
    """

    def test_invalid_phone_rejected(self):
        """Phone with fewer than 7 digits is rejected with ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            KioskCheckInRequest(
                first_name="Test",
                last_name="User",
                phone="12345",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("phone",) for e in errors)

    def test_empty_first_name_rejected(self):
        """Empty first_name is rejected with ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            KioskCheckInRequest(
                first_name="",
                last_name="User",
                phone="+6421555777",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("first_name",) for e in errors)


# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------


class TestKioskRBAC:
    """Kiosk role RBAC enforcement.

    Requirements: 1.5, 1.6, 6.1
    """

    def test_kiosk_cannot_access_invoices(self):
        """Kiosk user is denied access to /api/v1/invoices."""
        result = check_role_path_access("kiosk", "/api/v1/invoices", "GET")
        assert result is not None
        assert "kiosk" in result.lower()

    def test_kiosk_can_get_org_settings(self):
        """Kiosk user can GET /api/v1/org/settings."""
        result = check_role_path_access("kiosk", "/api/v1/org/settings", "GET")
        assert result is None

    def test_kiosk_cannot_put_org_settings(self):
        """Kiosk user cannot PUT /api/v1/org/settings."""
        result = check_role_path_access("kiosk", "/api/v1/org/settings", "PUT")
        assert result is not None
        assert "read-only" in result.lower()


# ---------------------------------------------------------------------------
# Rate limiting tests
# ---------------------------------------------------------------------------


class TestKioskRateLimiting:
    """Rate limiter blocks 31st request in 60 seconds.

    Requirements: 6.5
    """

    @pytest.mark.asyncio
    async def test_31st_request_blocked(self):
        """The 31st request within 60 seconds is rejected with HTTP 429."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id)
        redis = _make_mock_redis_for_rate_limit(_KIOSK_RATE_LIMIT)  # 30 already in window

        with pytest.raises(HTTPException) as exc_info:
            await _check_kiosk_rate_limit(request, redis=redis)

        assert exc_info.value.status_code == 429
        assert "rate limit" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_under_limit_allowed(self):
        """Requests under the limit are allowed through."""
        user_id = str(uuid.uuid4())
        request = _make_mock_request(user_id)
        redis = _make_mock_redis_for_rate_limit(10)

        # Should not raise
        await _check_kiosk_rate_limit(request, redis=redis)


# ---------------------------------------------------------------------------
# Kiosk authentication — 30-day session expiry
# ---------------------------------------------------------------------------


class TestKioskAuthentication:
    """Kiosk authentication produces 30-day session expiry.

    Requirements: 1.3, 1.4
    """

    @pytest.mark.asyncio
    async def test_kiosk_session_30_day_expiry(self):
        """Kiosk user authentication creates a session with ~30-day expiry."""
        org_id = uuid.uuid4()
        password = "SecurePassword123!"
        user = _make_kiosk_user(org_id, "kiosk@test.co.nz", password)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _mock_scalar_one_or_none(user),   # user lookup
            _mock_scalars_all([]),             # no MFA methods
            _mock_scalars_all([]),             # no previous sessions (anomaly check)
        ])
        db.add = MagicMock()

        before_auth = datetime.now(timezone.utc)

        with (
            patch("app.modules.auth.service.write_audit_log", new_callable=AsyncMock),
            patch("app.modules.auth.service.check_ip_allowlist", return_value=False),
            patch("app.modules.auth.service._check_anomalous_login", new_callable=AsyncMock),
            patch("app.modules.auth.service.enforce_session_limit", new_callable=AsyncMock, return_value=0),
        ):
            req = LoginRequest(email="kiosk@test.co.nz", password=password)
            result = await authenticate_user(db, req, "10.0.0.1", "Tablet", "Chrome")

        after_auth = datetime.now(timezone.utc)

        assert isinstance(result, TokenResponse)

        # Verify session was created with 30-day expiry
        assert db.add.call_count == 1
        session_obj = db.add.call_args[0][0]
        assert isinstance(session_obj, Session)

        expected_min = before_auth + timedelta(days=30) - timedelta(seconds=5)
        expected_max = after_auth + timedelta(days=30) + timedelta(seconds=5)
        assert expected_min <= session_obj.expires_at <= expected_max
