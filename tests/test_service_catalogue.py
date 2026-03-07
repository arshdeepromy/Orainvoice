"""Unit tests for Task 12.1 — service catalogue CRUD.

Tests cover:
  - Schema validation for service create/update requests
  - list_services: listing with active_only and category filters
  - create_service: creation with audit logging and validation
  - update_service: partial updates with audit logging
  - get_service: retrieval by ID within org

Requirements: 27.1, 27.2, 27.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import admin and auth models so SQLAlchemy can resolve all relationships
import app.modules.admin.models  # noqa: F401
from app.modules.auth.models import User  # noqa: F401
import app.modules.inventory.models  # noqa: F401

from app.modules.catalogue.models import ServiceCatalogue
from app.modules.catalogue.schemas import (
    ServiceCreateRequest,
    ServiceListResponse,
    ServiceResponse,
    ServiceUpdateRequest,
)
from app.modules.catalogue.service import (
    create_service,
    get_service,
    list_services,
    update_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    org_id=None,
    name="WOF Inspection",
    description="Warrant of Fitness inspection",
    default_price=Decimal("55.00"),
    is_gst_exempt=False,
    category="warrant",
    is_active=True,
):
    """Create a mock ServiceCatalogue object."""
    service = MagicMock(spec=ServiceCatalogue)
    service.id = uuid.uuid4()
    service.org_id = org_id or uuid.uuid4()
    service.name = name
    service.description = description
    service.default_price = default_price
    service.is_gst_exempt = is_gst_exempt
    service.category = category
    service.is_active = is_active
    service.created_at = datetime.now(timezone.utc)
    service.updated_at = datetime.now(timezone.utc)
    return service


def _mock_db_session():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    return db


def _mock_scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _mock_scalars_result(values):
    result = MagicMock()
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result.scalars.return_value = scalars_mock
    return result


def _mock_count_result(count):
    result = MagicMock()
    result.scalar.return_value = count
    return result


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestServiceSchemas:
    """Validate Pydantic schema constraints for service catalogue."""

    def test_create_request_valid(self):
        req = ServiceCreateRequest(
            name="Oil Change",
            default_price="45.00",
            category="service",
        )
        assert req.name == "Oil Change"
        assert req.default_price == "45.00"
        assert req.category == "service"
        assert req.is_gst_exempt is False
        assert req.is_active is True

    def test_create_request_all_fields(self):
        req = ServiceCreateRequest(
            name="Brake Repair",
            description="Full brake pad replacement",
            default_price="250.00",
            is_gst_exempt=True,
            category="repair",
            is_active=False,
        )
        assert req.description == "Full brake pad replacement"
        assert req.is_gst_exempt is True
        assert req.is_active is False

    def test_create_request_empty_name_rejected(self):
        with pytest.raises(Exception):
            ServiceCreateRequest(
                name="",
                default_price="10.00",
                category="service",
            )

    def test_create_request_invalid_category_rejected(self):
        with pytest.raises(Exception):
            ServiceCreateRequest(
                name="Test",
                default_price="10.00",
                category="invalid",
            )

    def test_update_request_all_optional(self):
        req = ServiceUpdateRequest()
        assert req.name is None
        assert req.default_price is None
        assert req.category is None

    def test_update_request_partial(self):
        req = ServiceUpdateRequest(name="Updated Name", is_active=False)
        assert req.name == "Updated Name"
        assert req.is_active is False
        assert req.default_price is None


# ---------------------------------------------------------------------------
# list_services tests
# ---------------------------------------------------------------------------


class TestListServices:
    """Test service catalogue listing with filters."""

    @pytest.mark.asyncio
    async def test_returns_all_services(self):
        org_id = uuid.uuid4()
        services = [_make_service(org_id=org_id), _make_service(org_id=org_id, name="Brake Check")]
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(2),
            _mock_scalars_result(services),
        ])

        result = await list_services(db, org_id=org_id)
        assert result["total"] == 2
        assert len(result["services"]) == 2

    @pytest.mark.asyncio
    async def test_active_only_filter(self):
        org_id = uuid.uuid4()
        active_svc = _make_service(org_id=org_id, is_active=True)
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([active_svc]),
        ])

        result = await list_services(db, org_id=org_id, active_only=True)
        assert result["total"] == 1
        assert result["services"][0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_category_filter(self):
        org_id = uuid.uuid4()
        warrant_svc = _make_service(org_id=org_id, category="warrant")
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(1),
            _mock_scalars_result([warrant_svc]),
        ])

        result = await list_services(db, org_id=org_id, category="warrant")
        assert result["total"] == 1
        assert result["services"][0]["category"] == "warrant"

    @pytest.mark.asyncio
    async def test_empty_catalogue(self):
        db = _mock_db_session()
        db.execute = AsyncMock(side_effect=[
            _mock_count_result(0),
            _mock_scalars_result([]),
        ])

        result = await list_services(db, org_id=uuid.uuid4())
        assert result["total"] == 0
        assert result["services"] == []


# ---------------------------------------------------------------------------
# create_service tests
# ---------------------------------------------------------------------------


class TestCreateService:
    """Test service creation with validation and audit logging."""

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_creates_service_successfully(self, mock_audit):
        db = _mock_db_session()
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        result = await create_service(
            db,
            org_id=org_id,
            user_id=user_id,
            name="WOF Inspection",
            default_price="55.00",
            category="warrant",
            description="Standard WOF check",
        )

        assert result["name"] == "WOF Inspection"
        assert result["default_price"] == "55.00"
        assert result["category"] == "warrant"
        assert result["is_active"] is True
        assert result["is_gst_exempt"] is False
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_audit_log_written_on_create(self, mock_audit):
        db = _mock_db_session()
        await create_service(
            db,
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            name="Test",
            default_price="10.00",
            category="service",
        )
        mock_audit.assert_awaited_once()
        call_kwargs = mock_audit.call_args.kwargs
        assert call_kwargs["action"] == "catalogue.service.created"
        assert call_kwargs["entity_type"] == "service_catalogue"

    @pytest.mark.asyncio
    async def test_invalid_price_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Invalid price format"):
            await create_service(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                default_price="not-a-number",
                category="service",
            )

    @pytest.mark.asyncio
    async def test_negative_price_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Price cannot be negative"):
            await create_service(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                default_price="-10.00",
                category="service",
            )

    @pytest.mark.asyncio
    async def test_invalid_category_raises(self):
        db = _mock_db_session()
        with pytest.raises(ValueError, match="Invalid category"):
            await create_service(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                name="Test",
                default_price="10.00",
                category="invalid",
            )


# ---------------------------------------------------------------------------
# get_service tests
# ---------------------------------------------------------------------------


class TestGetService:
    """Test service retrieval by ID."""

    @pytest.mark.asyncio
    async def test_returns_service(self):
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        result = await get_service(db, org_id=org_id, service_id=service.id)
        assert result["name"] == "WOF Inspection"
        assert result["id"] == str(service.id)

    @pytest.mark.asyncio
    async def test_not_found_raises(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Service not found"):
            await get_service(db, org_id=uuid.uuid4(), service_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# update_service tests
# ---------------------------------------------------------------------------


class TestUpdateService:
    """Test service updates with partial fields and audit logging."""

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_updates_service_fields(self, mock_audit):
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id, name="Old Name")
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        result = await update_service(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            service_id=service.id,
            name="New Name",
        )

        assert service.name == "New Name"
        db.flush.assert_awaited_once()
        mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_not_found_raises(self):
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with pytest.raises(ValueError, match="Service not found"):
            await update_service(
                db,
                org_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                service_id=uuid.uuid4(),
                name="Test",
            )

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_no_op_when_no_fields(self, mock_audit):
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        result = await update_service(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            service_id=service.id,
        )

        db.flush.assert_not_awaited()
        mock_audit.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_deactivate_service(self, mock_audit):
        """Req 27.2 — toggle service to inactive."""
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id, is_active=True)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        await update_service(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            service_id=service.id,
            is_active=False,
        )

        assert service.is_active is False

    @pytest.mark.asyncio
    @patch("app.modules.catalogue.service.write_audit_log", new_callable=AsyncMock)
    async def test_update_price(self, mock_audit):
        """Req 27.1 — update default price."""
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id, default_price=Decimal("55.00"))
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        await update_service(
            db,
            org_id=org_id,
            user_id=uuid.uuid4(),
            service_id=service.id,
            default_price="65.00",
        )

        assert service.default_price == Decimal("65.00")

    @pytest.mark.asyncio
    async def test_update_invalid_price_raises(self):
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        with pytest.raises(ValueError, match="Invalid price format"):
            await update_service(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                service_id=service.id,
                default_price="bad",
            )

    @pytest.mark.asyncio
    async def test_update_invalid_category_raises(self):
        org_id = uuid.uuid4()
        service = _make_service(org_id=org_id)
        db = _mock_db_session()
        db.execute = AsyncMock(return_value=_mock_scalar_result(service))

        with pytest.raises(ValueError, match="Invalid category"):
            await update_service(
                db,
                org_id=org_id,
                user_id=uuid.uuid4(),
                service_id=service.id,
                category="invalid",
            )
